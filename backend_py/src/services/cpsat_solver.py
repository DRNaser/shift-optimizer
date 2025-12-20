"""
SHIFT OPTIMIZER - CP-SAT Solver v3 (Production)
================================================
OR-Tools CP-SAT constraint programming solver with production-grade features.

KEY FEATURES:
1. Safety-Net Fallback: Hard coverage → auto-fallback to soft if infeasible
2. Two-Phase Optimization: Maximize coverage (soft) → fix → optimize quality
3. Extended Reason Codes: rest_violation, overlap, weekly_hours_exceeded, etc.
4. Hint Effectiveness Tracking: Log hints used vs hints in final solution
5. Determinism: Fixed seed + workers for reproducibility
6. Structured Output: JSON-serializable reports for debugging

The Validator remains the SINGLE SOURCE OF TRUTH.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import NamedTuple
import json
import uuid

from ortools.sat.python import cp_model

from src.domain.models import (
    Block,
    BlockType,
    Driver,
    DriverAssignment,
    ReasonCode,
    Tour,
    UnassignedTour,
    ValidationResult,
    Weekday,
    WeeklyPlan,
    WeeklyPlanStats,
)
from src.domain.constraints import HARD_CONSTRAINTS, SOFT_PENALTY_CONFIG
from src.domain.validator import Validator
from src.services.block_builder import build_blocks_greedy
from src.services.scheduler import BaselineScheduler


# =============================================================================
# CONFIGURATION
# =============================================================================

class CPSATConfig(NamedTuple):
    """Configuration for CP-SAT solver."""
    time_limit_seconds: float = 30.0
    num_workers: int = 1  # S0.1: Fixed for determinism (was 4)
    seed: int = 42  # Fixed seed for reproducibility (was None)
    optimize: bool = True
    prefer_larger_blocks: bool = True
    use_greedy_hints: bool = True
    fallback_to_soft: bool = True  # NEW: Auto-fallback if hard fails


# =============================================================================
# EXTENDED REASON CODES
# =============================================================================

class BlockingReason:
    """Extended blocking reason codes."""
    QUALIFICATION_MISSING = "qualification_missing"
    DRIVER_UNAVAILABLE = "driver_unavailable"
    SPAN_EXCEEDED = "span_exceeded"
    TOURS_PER_DAY_EXCEEDED = "tours_per_day_exceeded"
    REST_VIOLATION = "rest_violation"
    OVERLAP = "overlap"
    WEEKLY_HOURS_EXCEEDED = "weekly_hours_exceeded"
    NO_BLOCK_GENERATED = "no_block_generated"
    GLOBAL_INFEASIBLE = "global_infeasible"  # Passes pre-tour but fails globally


class SolveStatus:
    """Clear status semantics for solve results."""
    HARD_OK = "HARD_OK"              # Hard coverage succeeded, all coverable tours assigned
    SOFT_FALLBACK = "SOFT_FALLBACK"  # Fallback triggered OR not all covered
    FAILED = "FAILED"                # Solver failed completely
    INVALID = "INVALID"              # Plan produced but failed post-solve validation


# =============================================================================
# MACHINE-READABLE REPORTS
# =============================================================================

@dataclass
class TourReport:
    """Per-tour feasibility report."""
    tour_id: str
    day: str
    candidate_count: int
    is_feasible: bool
    is_forced: bool
    blocking_reasons: list[str] = field(default_factory=list)
    forced_block_id: str | None = None
    forced_driver_id: str | None = None


@dataclass
class PreSolveReport:
    """Pre-solve analysis report."""
    total_tours: int
    coverable_tours: int
    infeasible_tours: int
    forced_tours: int
    coverage_rate: float
    is_model_feasible: bool
    blocking_summary: dict[str, int] = field(default_factory=dict)
    tour_reports: dict[str, TourReport] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "total_tours": self.total_tours,
            "coverable_tours": self.coverable_tours,
            "infeasible_tours": self.infeasible_tours,
            "forced_tours": self.forced_tours,
            "coverage_rate": round(self.coverage_rate, 4),
            "is_model_feasible": self.is_model_feasible,
            "blocking_summary": self.blocking_summary,
            "infeasible_details": [
                {"tour_id": r.tour_id, "day": r.day, "reasons": r.blocking_reasons}
                for r in self.tour_reports.values() if not r.is_feasible
            ][:20]  # Limit to top 20
        }


@dataclass
class SolveReport:
    """Post-solve report with all diagnostics."""
    # Timing
    timestamp: str
    time_limit_seconds: float
    solve_time_seconds: float
    time_limit_hit: bool
    
    # Status
    solver_status: str
    objective_value: float
    
    # Coverage
    tours_expected: int
    tours_assigned: int
    tours_unassigned: int
    coverage_achieved: float
    
    # Hints
    hints_provided: int
    hints_used_in_solution: int
    hint_effectiveness: float
    
    # Quality
    blocks_triple: int
    blocks_double: int
    blocks_single: int
    drivers_used: int
    
    # Mode
    used_hard_coverage: bool
    fallback_triggered: bool
    
    # Top unassigned reasons
    unassigned_reasons: dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "timing": {
                "limit": self.time_limit_seconds,
                "actual": round(self.solve_time_seconds, 2),
                "hit_limit": self.time_limit_hit
            },
            "status": self.solver_status,
            "objective": self.objective_value,
            "coverage": {
                "expected": self.tours_expected,
                "assigned": self.tours_assigned,
                "unassigned": self.tours_unassigned,
                "rate": round(self.coverage_achieved, 4)
            },
            "hints": {
                "provided": self.hints_provided,
                "used": self.hints_used_in_solution,
                "effectiveness": round(self.hint_effectiveness, 2)
            },
            "quality": {
                "triple": self.blocks_triple,
                "double": self.blocks_double,
                "single": self.blocks_single,
                "drivers": self.drivers_used
            },
            "mode": {
                "hard_coverage": self.used_hard_coverage,
                "fallback_triggered": self.fallback_triggered
            },
            "unassigned_reasons_top10": dict(list(self.unassigned_reasons.items())[:10])
        }


# =============================================================================
# CP-SAT MODEL v3
# =============================================================================

class CPSATSchedulerModel:
    """
    Production CP-SAT model with safety-net fallback.
    
    Strategy:
    1. Try hard coverage for coverable tours
    2. If infeasible → fallback to soft coverage + maximize
    3. Fix best_coverage → optimize block quality + minimize drivers
    """
    
    def __init__(
        self,
        tours: list[Tour],
        drivers: list[Driver],
        config: CPSATConfig = CPSATConfig()
    ):
        self.tours = tours
        self.drivers = drivers
        self.config = config
        
        # Build blocks
        self.blocks = build_blocks_greedy(tours, prefer_larger=True)
        
        # Index
        self.tour_to_blocks: dict[str, list[Block]] = defaultdict(list)
        for block in self.blocks:
            for tour in block.tours:
                self.tour_to_blocks[tour.id].append(block)
        
        # Model & variables
        self.model = cp_model.CpModel()
        self.assignment: dict[tuple[int, int], cp_model.IntVar] = {}
        
        # Coverage tracking
        self.tour_to_vars: dict[str, list[tuple[int, int]]] = {t.id: [] for t in self.tours}
        self.coverable_tour_ids: set[str] = set()
        self.infeasible_tour_ids: set[str] = set()
        
        # Reports
        self.pre_solve_report: PreSolveReport | None = None
        self.solve_report: SolveReport | None = None
        
        # Hint tracking
        self.hints_added: set[tuple[int, int]] = set()
        
        # Mode tracking
        self.using_hard_coverage: bool = True
        self.fallback_triggered: bool = False
        
        # Build
        self._run_pre_solve()
        
        if self.pre_solve_report and self.pre_solve_report.is_model_feasible:
            self._create_variables()
            if self.config.use_greedy_hints:
                self._add_greedy_hints()
            self._add_constraints_hard()
            if self.config.optimize:
                self._add_objectives()
    
    # =========================================================================
    # PRE-SOLVE
    # =========================================================================
    
    def _run_pre_solve(self) -> None:
        """Analyze per-tour feasibility."""
        print("=" * 60)
        print("PRE-SOLVE ANALYSIS v3")
        print("=" * 60)
        
        tour_reports: dict[str, TourReport] = {}
        blocking: dict[str, int] = defaultdict(int)
        
        infeasible = forced = coverable = 0
        
        for tour in self.tours:
            options: list[tuple[Block, Driver]] = []
            blockers: dict[str, int] = defaultdict(int)
            
            # Check if block exists for tour
            blocks_for_tour = self.tour_to_blocks.get(tour.id, [])
            if not blocks_for_tour:
                blockers[BlockingReason.NO_BLOCK_GENERATED] = 1
                blocking[BlockingReason.NO_BLOCK_GENERATED] += 1
            
            for block in blocks_for_tour:
                for driver in self.drivers:
                    ok, reason = self._check_assignment(block, driver)
                    if ok:
                        options.append((block, driver))
                    elif reason:
                        blockers[reason] += 1
                        blocking[reason] += 1
            
            if len(options) == 0:
                infeasible += 1
                self.infeasible_tour_ids.add(tour.id)
                # S0.1: Stable tie-break for determinism
                top = sorted(blockers.keys(), key=lambda r: (-blockers[r], r))[:3]
                report = TourReport(tour.id, tour.day.value, 0, False, False, top)
                
            elif len(options) == 1:
                forced += 1
                coverable += 1
                self.coverable_tour_ids.add(tour.id)
                b, d = options[0]
                report = TourReport(tour.id, tour.day.value, 1, True, True, [], b.id, d.id)
                
            else:
                coverable += 1
                self.coverable_tour_ids.add(tour.id)
                report = TourReport(tour.id, tour.day.value, len(options), True, False)
            
            tour_reports[tour.id] = report
        
        self.pre_solve_report = PreSolveReport(
            total_tours=len(self.tours),
            coverable_tours=coverable,
            infeasible_tours=infeasible,
            forced_tours=forced,
            coverage_rate=coverable / len(self.tours) if self.tours else 0,
            is_model_feasible=coverable > 0,
            blocking_summary=dict(blocking),
            tour_reports=tour_reports
        )
        
        print(f"  Tours: {len(self.tours)} | Coverable: {coverable} | Infeasible: {infeasible} | Forced: {forced}")
        print(f"  Coverage Rate: {self.pre_solve_report.coverage_rate:.1%}")
        if blocking:
            # S0.1: Stable tie-break for determinism
            top5 = sorted(blocking.items(), key=lambda x: (-x[1], x[0]))[:5]
            print(f"  Top Blockers: {dict(top5)}")
        print("=" * 60)
    
    def _check_assignment(self, block: Block, driver: Driver) -> tuple[bool, str | None]:
        """Check assignment feasibility with extended reasons."""
        # Qualifications
        if block.required_qualifications - set(driver.qualifications):
            return False, BlockingReason.QUALIFICATION_MISSING
        
        # Availability
        if not driver.is_available_on(block.day):
            return False, BlockingReason.DRIVER_UNAVAILABLE
        
        # Span
        if block.span_hours > min(HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS, driver.max_daily_span_hours):
            return False, BlockingReason.SPAN_EXCEEDED
        
        # Tours per day
        if len(block.tours) > min(HARD_CONSTRAINTS.MAX_TOURS_PER_DAY, driver.max_tours_per_day):
            return False, BlockingReason.TOURS_PER_DAY_EXCEEDED
        
        return True, None
    
    # =========================================================================
    # VARIABLES
    # =========================================================================
    
    def _create_variables(self) -> None:
        for b_idx, block in enumerate(self.blocks):
            for d_idx, driver in enumerate(self.drivers):
                ok, _ = self._check_assignment(block, driver)
                if ok:
                    var = self.model.NewBoolVar(f"x_{b_idx}_{d_idx}")
                    self.assignment[(b_idx, d_idx)] = var
                    for tour in block.tours:
                        self.tour_to_vars[tour.id].append((b_idx, d_idx))
        
        print(f"Variables: {len(self.assignment)}")
    
    # =========================================================================
    # GREEDY HINTS
    # =========================================================================
    
    def _add_greedy_hints(self, week_start: 'date' = None) -> None:
        """Add hints from greedy solution."""
        try:
            greedy = BaselineScheduler(self.tours, self.drivers)
            # S0.1: Use deterministic date, not date.today() which breaks reproducibility
            from datetime import date
            hint_date = week_start if week_start else date(2025, 1, 6)  # Fixed deterministic date
            plan = greedy.schedule(hint_date)
            
            for a in plan.assignments:
                # Match block by tour set
                tour_ids = set(t.id for t in a.block.tours)
                b_idx = next((i for i, b in enumerate(self.blocks) 
                             if set(t.id for t in b.tours) == tour_ids), None)
                d_idx = next((i for i, d in enumerate(self.drivers) 
                             if d.id == a.driver_id), None)
                
                if b_idx is not None and d_idx is not None and (b_idx, d_idx) in self.assignment:
                    self.model.AddHint(self.assignment[(b_idx, d_idx)], 1)
                    self.hints_added.add((b_idx, d_idx))
            
            print(f"Hints: {len(self.hints_added)} added")
        except Exception as e:
            print(f"Hints: Failed - {e}")
    
    # =========================================================================
    # CONSTRAINTS (HARD COVERAGE)
    # =========================================================================
    
    def _add_constraints_hard(self) -> None:
        """Add constraints with hard coverage for coverable tours."""
        self.using_hard_coverage = True
        
        # Block: at most one driver
        for b_idx in range(len(self.blocks)):
            vars_b = [self.assignment[(b_idx, d)] for d in range(len(self.drivers)) 
                     if (b_idx, d) in self.assignment]
            if vars_b:
                self.model.Add(sum(vars_b) <= 1)
        
        # HARD coverage for coverable tours
        for tour_id in self.coverable_tour_ids:
            keys = self.tour_to_vars.get(tour_id, [])
            vars_t = [self.assignment[k] for k in keys if k in self.assignment]
            if vars_t:
                self.model.Add(sum(vars_t) == 1)
        
        # Driver constraints
        self._add_driver_constraints()
        
        print(f"Constraints: Hard coverage for {len(self.coverable_tour_ids)} tours")
    
    def _add_constraints_soft(self) -> None:
        """Rebuild model with soft coverage (fallback mode)."""
        self.model = cp_model.CpModel()
        self.assignment.clear()
        self.using_hard_coverage = False
        self.fallback_triggered = True
        
        # Recreate variables
        for b_idx, block in enumerate(self.blocks):
            for d_idx, driver in enumerate(self.drivers):
                ok, _ = self._check_assignment(block, driver)
                if ok:
                    var = self.model.NewBoolVar(f"x_{b_idx}_{d_idx}")
                    self.assignment[(b_idx, d_idx)] = var
        
        # Block: at most one driver
        for b_idx in range(len(self.blocks)):
            vars_b = [self.assignment[(b_idx, d)] for d in range(len(self.drivers)) 
                     if (b_idx, d) in self.assignment]
            if vars_b:
                self.model.Add(sum(vars_b) <= 1)
        
        # SOFT coverage: at most 1 (maximize in objective)
        for tour_id in self.coverable_tour_ids:
            keys = self.tour_to_vars.get(tour_id, [])
            vars_t = [self.assignment[k] for k in keys if k in self.assignment]
            if vars_t:
                self.model.Add(sum(vars_t) <= 1)
        
        # Driver constraints
        self._add_driver_constraints()
        
        # Re-add hints
        for key in self.hints_added:
            if key in self.assignment:
                self.model.AddHint(self.assignment[key], 1)
        
        print("Fallback: Switched to SOFT coverage mode")
    
    def _add_driver_constraints(self) -> None:
        """Add all driver-level constraints."""
        # Max blocks per day
        for d_idx in range(len(self.drivers)):
            for day in Weekday:
                vars_d = [self.assignment[(b, d_idx)] for b, blk in enumerate(self.blocks)
                         if blk.day == day and (b, d_idx) in self.assignment]
                if vars_d:
                    self.model.Add(sum(vars_d) <= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY)
        
        # Weekly hours
        for d_idx, driver in enumerate(self.drivers):
            limit = int(min(HARD_CONSTRAINTS.MAX_WEEKLY_HOURS, driver.max_weekly_hours) * 60)
            terms = [self.assignment[(b, d_idx)] * self.blocks[b].total_work_minutes
                    for b in range(len(self.blocks)) if (b, d_idx) in self.assignment]
            if terms:
                self.model.Add(sum(terms) <= limit)
        
        # Gap between blocks same day
        gap_mins = int(HARD_CONSTRAINTS.MIN_GAP_BETWEEN_BLOCKS_HOURS * 60)
        for d_idx in range(len(self.drivers)):
            for day in Weekday:
                day_blks = [(i, b) for i, b in enumerate(self.blocks) if b.day == day]
                for i, (b1, blk1) in enumerate(day_blks):
                    for b2, blk2 in day_blks[i+1:]:
                        if (b1, d_idx) not in self.assignment or (b2, d_idx) not in self.assignment:
                            continue
                        e1 = blk1.last_end.hour * 60 + blk1.last_end.minute
                        s2 = blk2.first_start.hour * 60 + blk2.first_start.minute
                        e2 = blk2.last_end.hour * 60 + blk2.last_end.minute
                        s1 = blk1.first_start.hour * 60 + blk1.first_start.minute
                        gap = s2 - e1 if e1 <= s2 else (s1 - e2 if e2 <= s1 else 0)
                        if gap < gap_mins:
                            self.model.Add(self.assignment[(b1, d_idx)] + self.assignment[(b2, d_idx)] <= 1)
        
        # Tours per day
        for d_idx, driver in enumerate(self.drivers):
            limit = min(HARD_CONSTRAINTS.MAX_TOURS_PER_DAY, driver.max_tours_per_day)
            for day in Weekday:
                terms = [(self.assignment[(b, d_idx)], len(self.blocks[b].tours))
                        for b in range(len(self.blocks)) 
                        if self.blocks[b].day == day and (b, d_idx) in self.assignment]
                if terms:
                    self.model.Add(sum(v * n for v, n in terms) <= limit)
        
        # Rest time
        days = list(Weekday)
        for d_idx, driver in enumerate(self.drivers):
            rest_mins = int(min(HARD_CONSTRAINTS.MIN_REST_HOURS, driver.min_rest_hours) * 60)
            for i in range(len(days) - 1):
                d1, d2 = days[i], days[i + 1]
                b1s = [(j, b) for j, b in enumerate(self.blocks) if b.day == d1 and (j, d_idx) in self.assignment]
                b2s = [(j, b) for j, b in enumerate(self.blocks) if b.day == d2 and (j, d_idx) in self.assignment]
                for j1, blk1 in b1s:
                    for j2, blk2 in b2s:
                        e1 = blk1.last_end.hour * 60 + blk1.last_end.minute
                        s2 = blk2.first_start.hour * 60 + blk2.first_start.minute
                        rest = (s2 + 24 * 60) - e1
                        if rest < rest_mins:
                            self.model.Add(self.assignment[(j1, d_idx)] + self.assignment[(j2, d_idx)] <= 1)
    
    # =========================================================================
    # OBJECTIVES
    # =========================================================================
    
    def _add_objectives(self) -> None:
        """Add optimization objectives."""
        terms = []
        
        # If soft coverage mode: add coverage maximization
        if not self.using_hard_coverage:
            for tour_id in self.coverable_tour_ids:
                keys = self.tour_to_vars.get(tour_id, [])
                vars_t = [self.assignment[k] for k in keys if k in self.assignment]
                if vars_t:
                    cov = self.model.NewBoolVar(f"cov_{tour_id}")
                    self.model.AddMaxEquality(cov, vars_t)
                    terms.append(cov * 10000)  # High weight for coverage
        
        # Block quality
        for b_idx, block in enumerate(self.blocks):
            n = len(block.tours)
            for d_idx in range(len(self.drivers)):
                if (b_idx, d_idx) in self.assignment:
                    if n == 3:
                        terms.append(self.assignment[(b_idx, d_idx)] * 300)
                    elif n == 2:
                        terms.append(self.assignment[(b_idx, d_idx)] * 100)
        
        # Driver minimization
        self.driver_used: dict[int, cp_model.IntVar] = {}
        for d_idx in range(len(self.drivers)):
            d_vars = [self.assignment[(b, d_idx)] for b in range(len(self.blocks)) 
                     if (b, d_idx) in self.assignment]
            if d_vars:
                used = self.model.NewBoolVar(f"driver_{d_idx}")
                self.model.AddMaxEquality(used, d_vars)
                self.driver_used[d_idx] = used
                terms.append(-used * 50)
        
        # =====================================================================
        # FATIGUE PREVENTION PENALTIES (Issue 2)
        # =====================================================================
        # Apply soft penalties for patterns that are legal but fatiguing
        
        for b_idx, block in enumerate(self.blocks):
            for d_idx in range(len(self.drivers)):
                if (b_idx, d_idx) not in self.assignment:
                    continue
                var = self.assignment[(b_idx, d_idx)]
                
                # Penalty for triple blocks (physically demanding)
                if len(block.tours) == 3:
                    terms.append(-var * SOFT_PENALTY_CONFIG.TRIPLE_BLOCK_PENALTY)
                
                # Penalty for early starts (before threshold, e.g., 06:00)
                if block.first_start.hour < SOFT_PENALTY_CONFIG.EARLY_THRESHOLD_HOUR:
                    terms.append(-var * SOFT_PENALTY_CONFIG.EARLY_START_PENALTY)
                
                # Penalty for late ends (at or after threshold, e.g., 21:00)
                if block.last_end.hour >= SOFT_PENALTY_CONFIG.LATE_THRESHOLD_HOUR:
                    terms.append(-var * SOFT_PENALTY_CONFIG.LATE_END_PENALTY)
        
        # Penalty for short (but legal) rest between consecutive days
        days = list(Weekday)
        comfort_mins = int(SOFT_PENALTY_CONFIG.COMFORT_REST_HOURS * 60)
        rest_mins = int(HARD_CONSTRAINTS.MIN_REST_HOURS * 60)
        
        for d_idx, driver in enumerate(self.drivers):
            for i in range(len(days) - 1):
                d1, d2 = days[i], days[i + 1]
                b1s = [(j, b) for j, b in enumerate(self.blocks) if b.day == d1 and (j, d_idx) in self.assignment]
                b2s = [(j, b) for j, b in enumerate(self.blocks) if b.day == d2 and (j, d_idx) in self.assignment]
                for j1, blk1 in b1s:
                    for j2, blk2 in b2s:
                        e1 = blk1.last_end.hour * 60 + blk1.last_end.minute
                        s2 = blk2.first_start.hour * 60 + blk2.first_start.minute
                        rest = (s2 + 24 * 60) - e1
                        # If rest is legal but below comfort threshold, add soft penalty
                        if rest_mins <= rest < comfort_mins:
                            # Create auxiliary variable for this pair
                            pair_var = self.model.NewBoolVar(f"short_rest_{d_idx}_{j1}_{j2}")
                            self.model.AddMinEquality(pair_var, [
                                self.assignment[(j1, d_idx)],
                                self.assignment[(j2, d_idx)]
                            ])
                            terms.append(-pair_var * SOFT_PENALTY_CONFIG.SHORT_REST_PENALTY)
        
        if terms:
            self.model.Maximize(sum(terms))
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    
    def solve(self) -> tuple[int, cp_model.CpSolver]:
        """Solve with automatic fallback."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_seconds
        solver.parameters.num_search_workers = 1  # S0.1: Determinism (always 1)
        solver.parameters.random_seed = self.config.seed
        
        print(f"\nSOLVING (seed={self.config.seed}, workers=1)...")
        status = solver.Solve(self.model)
        
        status_map = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE", 
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }
        
        print(f"  Status: {status_map.get(status, status)}")
        print(f"  Time: {solver.WallTime():.2f}s / {self.config.time_limit_seconds}s")
        
        # Fallback if infeasible and enabled
        if status == cp_model.INFEASIBLE and self.config.fallback_to_soft and self.using_hard_coverage:
            print("\n[WARNING] HARD COVERAGE INFEASIBLE - Triggering fallback to SOFT...")
            self._add_constraints_soft()
            self._add_objectives()
            
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = self.config.time_limit_seconds
            solver.parameters.num_search_workers = 1  # S0.1: Determinism (always 1)
            solver.parameters.random_seed = self.config.seed
            
            status = solver.Solve(self.model)
            print(f"  Fallback Status: {status_map.get(status, status)}")
            print(f"  Fallback Time: {solver.WallTime():.2f}s")
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"  Objective: {solver.ObjectiveValue():.0f}")
        
        return status, solver
    
    def extract_solution(self, solver: cp_model.CpSolver) -> tuple[list[DriverAssignment], set[str]]:
        """Extract solution and track hint effectiveness."""
        assignments: list[DriverAssignment] = []
        assigned_tour_ids: set[str] = set()
        hints_used = 0
        
        for (b_idx, d_idx), var in self.assignment.items():
            if solver.Value(var) == 1:
                block = self.blocks[b_idx]
                driver = self.drivers[d_idx]
                
                if (b_idx, d_idx) in self.hints_added:
                    hints_used += 1
                
                assignments.append(DriverAssignment(
                    driver_id=driver.id,
                    day=block.day,
                    block=Block(id=block.id, day=block.day, tours=block.tours, driver_id=driver.id)
                ))
                
                for tour in block.tours:
                    assigned_tour_ids.add(tour.id)
        
        # Log hint effectiveness
        if self.hints_added:
            eff = hints_used / len(self.hints_added) * 100
            print(f"  Hints: {hints_used}/{len(self.hints_added)} used ({eff:.0f}% effective)")
        
        return assignments, assigned_tour_ids


# =============================================================================
# SCHEDULER
# =============================================================================

def generate_plan_id() -> str:
    return f"P-{uuid.uuid4().hex[:8]}"


class CPSATScheduler:
    """Production scheduler with full diagnostics."""
    
    def __init__(self, tours: list[Tour], drivers: list[Driver], config: CPSATConfig = CPSATConfig()):
        self.tours = tours
        self.drivers = drivers
        self.config = config
        self.validator = Validator(drivers)
    
    def schedule(self, week_start: date) -> WeeklyPlan:
        """Create optimized schedule with full reporting."""
        
        model = CPSATSchedulerModel(self.tours, self.drivers, self.config)
        
        if not model.pre_solve_report or not model.pre_solve_report.is_model_feasible:
            return self._empty_plan(week_start, model)
        
        status, solver = model.solve()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            assignments, assigned_ids = model.extract_solution(solver)
            
            # Validate
            self.validator.reset()
            validated = []
            for a in assignments:
                r = self.validator.validate_and_commit(a.driver_id, a.block)
                if r.is_valid:
                    validated.append(a)
                else:
                    for t in a.block.tours:
                        assigned_ids.discard(t.id)
            assignments = validated
            
            # Report
            model.solve_report = SolveReport(
                timestamp=datetime.now().isoformat(),
                time_limit_seconds=self.config.time_limit_seconds,
                solve_time_seconds=solver.WallTime(),
                time_limit_hit=solver.WallTime() >= self.config.time_limit_seconds * 0.95,
                solver_status="OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
                objective_value=solver.ObjectiveValue(),
                tours_expected=len(model.coverable_tour_ids),
                tours_assigned=len(assigned_ids),
                tours_unassigned=len(self.tours) - len(assigned_ids),
                coverage_achieved=len(assigned_ids) / len(self.tours) if self.tours else 0,
                hints_provided=len(model.hints_added),
                hints_used_in_solution=sum(1 for k in model.hints_added if k in model.assignment and solver.Value(model.assignment[k]) == 1),
                hint_effectiveness=0,
                blocks_triple=sum(1 for a in assignments if len(a.block.tours) == 3),
                blocks_double=sum(1 for a in assignments if len(a.block.tours) == 2),
                blocks_single=sum(1 for a in assignments if len(a.block.tours) == 1),
                drivers_used=len(set(a.driver_id for a in assignments)),
                used_hard_coverage=model.using_hard_coverage,
                fallback_triggered=model.fallback_triggered
            )
            if model.solve_report.hints_provided:
                model.solve_report.hint_effectiveness = model.solve_report.hints_used_in_solution / model.solve_report.hints_provided
            
            print(f"\n[SOLVE REPORT]:")
            print(json.dumps(model.solve_report.to_dict(), indent=2))
        else:
            assignments = []
            assigned_ids = set()
        
        unassigned = self._build_unassigned(assigned_ids, model)
        stats = self._calc_stats(assignments)
        
        plan = WeeklyPlan(
            id=generate_plan_id(),
            week_start=week_start,
            assignments=assignments,
            unassigned_tours=unassigned,
            validation=self.validator.validate_plan(WeeklyPlan(
                id="tmp", week_start=week_start, assignments=assignments,
                unassigned_tours=unassigned, validation=ValidationResult(is_valid=True),
                stats=stats, version="3.0.0"
            )),
            stats=stats,
            version="3.0.0",
            solver_seed=self.config.seed
        )
        
        # =====================================================================
        # POST-SOLVE VALIDATION GATE (Issue 3)
        # =====================================================================
        # Final safety check - if validation found rest violations, mark plan INVALID
        if not plan.validation.is_valid:
            rest_violations = [v for v in plan.validation.hard_violations 
                              if "rest" in v.lower()]
            if rest_violations:
                print(f"[VALIDATION GATE] INVALID PLAN: {len(rest_violations)} rest violations detected")
                for rv in rest_violations[:5]:  # Show first 5
                    print(f"  - {rv}")
                plan.validation = ValidationResult(
                    is_valid=False,
                    hard_violations=[f"INVALID_PLAN: {len(rest_violations)} rest rule violations detected"],
                    warnings=rest_violations[:10]  # Include first 10 as warnings for details
                )
        
        return plan
    
    def _empty_plan(self, week_start: date, model: CPSATSchedulerModel) -> WeeklyPlan:
        unassigned = [
            UnassignedTour(tour=t, reason_codes=[ReasonCode.INFEASIBLE], 
                          details=", ".join(model.pre_solve_report.tour_reports.get(t.id, TourReport(t.id, "", 0, False, False)).blocking_reasons) or "No options")
            for t in self.tours
        ]
        return WeeklyPlan(
            id=generate_plan_id(), week_start=week_start, assignments=[], unassigned_tours=unassigned,
            validation=ValidationResult(is_valid=False, hard_violations=["Pre-solve failed"]),
            stats=WeeklyPlanStats(
                total_drivers=0,
                total_tours_input=len(self.tours),
                total_tours_assigned=0,
                total_tours_unassigned=len(self.tours),
                block_counts={BlockType.SINGLE: 0, BlockType.DOUBLE: 0, BlockType.TRIPLE: 0},
                average_driver_utilization=0.0
            ),
            version="3.0.0", solver_seed=self.config.seed
        )
    
    def _build_unassigned(self, assigned: set[str], model: CPSATSchedulerModel) -> list[UnassignedTour]:
        result = []
        for t in self.tours:
            if t.id in assigned:
                continue
            report = model.pre_solve_report.tour_reports.get(t.id) if model.pre_solve_report else None
            if report and not report.is_feasible:
                result.append(UnassignedTour(
                    tour=t, 
                    reason_codes=[ReasonCode.INFEASIBLE], 
                    details=", ".join(report.blocking_reasons) or "No options"
                ))
            else:
                result.append(UnassignedTour(
                    tour=t, 
                    reason_codes=[ReasonCode.DRIVER_WEEKLY_LIMIT], 
                    details=BlockingReason.GLOBAL_INFEASIBLE
                ))
        return result
    
    def _calc_stats(self, assignments: list[DriverAssignment]) -> WeeklyPlanStats:
        ids = set(t.id for a in assignments for t in a.block.tours)
        bc = {
            BlockType.SINGLE: sum(1 for a in assignments if len(a.block.tours) == 1),
            BlockType.DOUBLE: sum(1 for a in assignments if len(a.block.tours) == 2),
            BlockType.TRIPLE: sum(1 for a in assignments if len(a.block.tours) == 3),
        }
        drivers = set(a.driver_id for a in assignments)
        hours = sum(a.block.total_work_hours for a in assignments)
        util = hours / (len(drivers) * HARD_CONSTRAINTS.MAX_WEEKLY_HOURS) if drivers else 0
        return WeeklyPlanStats(
            total_drivers=len(drivers),
            total_tours_input=len(self.tours),
            total_tours_assigned=len(ids),
            total_tours_unassigned=len(self.tours) - len(ids),
            block_counts=bc,
            average_driver_utilization=util
        )


def create_cpsat_schedule(tours: list[Tour], drivers: list[Driver], week_start: date, 
                         config: CPSATConfig = CPSATConfig()) -> WeeklyPlan:
    return CPSATScheduler(tours, drivers, config).schedule(week_start)
