"""
FORECAST WEEKLY SOLVER v2 - CANONICAL SOLVER
=============================================
This is the CANONICAL solver for forecast-based weekly planning.

Other solvers:
- forecast_solver_v4: Experimental use_block/set-partitioning model (Stage-A block selection)
- cpsat_solver: Legacy driver-assignment model (for future real driver/skills/availability)

KEY FEATURES:
- Range-feasibility guard (K_min <= K_max check)
- 4-phase lexicographic optimization:
  1. Minimize driver count
  2. Minimize hour violations (under/over)
  3. Minimize fairness gap
  4. Minimize 1er blocks
- Virtual PT/Reserve drivers as overflow valve (no hour limits)
- Clear status: HARD_OK vs SOFT_FALLBACK_HOURS

Constraints:
- 100% tour coverage (guaranteed by 1er fallback)
- 42-53h per FTE driver (hard when feasible, soft otherwise)
- PT drivers: unlimited hours (overflow valve)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import NamedTuple
from enum import Enum
import json
import math

from ortools.sat.python import cp_model

from src.domain.models import Block, Tour, Weekday, BlockType
from src.domain.virtual_driver import VirtualDriver, generate_virtual_drivers, compute_driver_bounds
from src.services.weekly_block_builder import (
    build_weekly_blocks,
    build_block_index,
    verify_coverage,
    get_block_pool_stats
)


# =============================================================================
# CONFIGURATION
# =============================================================================

class ForecastConfig(NamedTuple):
    """Configuration for forecast weekly solver."""
    min_hours_per_driver: float = 42.0
    max_hours_per_driver: float = 53.0
    time_limit_phase1: float = 30.0
    time_limit_phase2: float = 30.0
    time_limit_phase3: float = 30.0
    time_limit_phase4: float = 30.0
    seed: int = 42
    num_workers: int = 4
    pt_reserve_count: int = 3  # Number of PT/Reserve drivers (no hour limits)


# =============================================================================
# DRIVER TYPES
# =============================================================================

class DriverType(Enum):
    FTE = "FTE"       # Full-time: 42-53h strict
    PT = "PT"         # Part-time/Reserve: no hour limits (overflow valve)


@dataclass
class VirtualDriverV2:
    """Virtual driver with type."""
    id: str
    driver_type: DriverType
    min_weekly_hours: float = 0.0
    max_weekly_hours: float = 999.0
    
    def __hash__(self):
        return hash(self.id)


# =============================================================================
# SOLVE STATUS
# =============================================================================

class ForecastSolveStatus:
    """Status codes for forecast solver."""
    HARD_OK = "HARD_OK"
    SOFT_FALLBACK_HOURS = "SOFT_FALLBACK_HOURS"
    FAILED = "FAILED"


# =============================================================================
# OUTPUT MODELS
# =============================================================================

@dataclass
class DriverSchedule:
    """Schedule for a single virtual driver."""
    driver_id: str
    driver_type: str
    hours_week: float
    days_worked: int
    blocks_1er: int
    blocks_2er: int
    blocks_3er: int
    schedule: dict[str, list[dict]]
    
    def to_dict(self) -> dict:
        return {
            "id": self.driver_id,
            "type": self.driver_type,
            "hours_week": round(self.hours_week, 2),
            "days_worked": self.days_worked,
            "blocks_1er": self.blocks_1er,
            "blocks_2er": self.blocks_2er,
            "blocks_3er": self.blocks_3er,
            "schedule": self.schedule
        }


@dataclass
class WeeklyPlanResult:
    """Complete weekly plan result."""
    status: str
    drivers: list[DriverSchedule]
    kpi: dict
    block_pool_stats: dict
    feasibility: dict
    solve_times: dict[str, float] = field(default_factory=dict)
    
    def to_weekly_plan_json(self) -> dict:
        return {
            "status": self.status,
            "feasibility": self.feasibility,
            "drivers": [d.to_dict() for d in self.drivers]
        }
    
    def to_kpi_summary_json(self) -> dict:
        return self.kpi


# =============================================================================
# FEASIBILITY GUARD
# =============================================================================

def check_range_feasibility_hours_only(
    total_hours: float,
    min_per_driver: float = 42.0,
    max_per_driver: float = 53.0
) -> dict:
    """
    Check if the problem is range-feasible based on hours alone (mathematical).
    
    Does NOT consider hard constraints like overlaps, rest, max tours/day etc.
    This is a necessary but not sufficient condition for true feasibility.
    
    Returns:
        dict with feasibility info
    """
    if total_hours <= 0:
        return {
            "range_feasible_hours_only": True,
            "k_min": 0,
            "k_max": 0,
            "total_hours": 0,
            "explanation": "No hours to schedule"
        }
    
    k_min = math.ceil(total_hours / max_per_driver)
    k_max = math.floor(total_hours / min_per_driver)
    
    is_range_feasible = k_min <= k_max
    
    if is_range_feasible:
        explanation = f"Hours OK: can use {k_min}-{k_max} drivers at 42-53h each"
    else:
        explanation = f"Hours NOT feasible: need {k_min} drivers at 53h = {k_min * max_per_driver}h but only have {total_hours}h"
    
    return {
        "range_feasible_hours_only": is_range_feasible,
        "k_min": k_min,
        "k_max": k_max,
        "total_hours": total_hours,
        "min_per_driver": min_per_driver,
        "max_per_driver": max_per_driver,
        "explanation": explanation
    }


# =============================================================================
# DRIVER GENERATION
# =============================================================================

def generate_drivers_v2(
    k_fte: int,
    k_pt: int,
    min_hours: float = 42.0,
    max_hours: float = 53.0
) -> list[VirtualDriverV2]:
    """Generate FTE + PT drivers."""
    drivers = []
    
    # FTE drivers (strict hours)
    for i in range(1, k_fte + 1):
        drivers.append(VirtualDriverV2(
            id=f"FTE{i:03d}",
            driver_type=DriverType.FTE,
            min_weekly_hours=min_hours,
            max_weekly_hours=max_hours
        ))
    
    # PT/Reserve drivers (no limits - overflow valve)
    for i in range(1, k_pt + 1):
        drivers.append(VirtualDriverV2(
            id=f"PT{i:03d}",
            driver_type=DriverType.PT,
            min_weekly_hours=0.0,
            max_weekly_hours=999.0
        ))
    
    return drivers


# =============================================================================
# FORECAST WEEKLY SOLVER v2
# =============================================================================

class ForecastWeeklySolverV2:
    """
    4-phase CP-SAT solver for forecast-only weekly planning.
    
    Phase 1: Minimize FTE driver count
    Phase 2: Minimize hour violations (under/over for FTE)
    Phase 3: Minimize fairness gap
    Phase 4: Minimize 1er blocks
    
    Feasibility checks:
    - range_feasible_hours_only: Mathematical check (total_hours vs 42-53h bounds)
    - range_feasible_with_constraints: Actual FTE-only solve test
    """
    
    def __init__(self, tours: list[Tour], config: ForecastConfig = ForecastConfig()):
        self.tours = tours
        self.config = config
        
        # Calculate totals
        self.total_hours = sum(t.duration_hours for t in tours)
        
        # Check range feasibility (hours only - mathematical)
        hours_check = check_range_feasibility_hours_only(
            self.total_hours,
            config.min_hours_per_driver,
            config.max_hours_per_driver
        )
        
        self.k_min = hours_check['k_min']
        self.k_max = hours_check['k_max']
        self.range_feasible_hours_only = hours_check['range_feasible_hours_only']
        
        print(f"Total Hours: {self.total_hours:.1f}")
        print(f"Range Feasibility (hours): {self.range_feasible_hours_only}")
        print(f"  K_min={self.k_min}, K_max={self.k_max}")
        print(f"  {hours_check['explanation']}")
        
        # Generate drivers
        # FTE count: use k_max if hours-feasible, else use ceil(total/53) + buffer
        if self.range_feasible_hours_only:
            k_fte = max(self.k_max, self.k_min)  # Use enough FTE
        else:
            k_fte = self.k_min + 2  # Buffer for non-feasible cases
        
        self.drivers = generate_drivers_v2(
            k_fte=k_fte,
            k_pt=config.pt_reserve_count,
            min_hours=config.min_hours_per_driver,
            max_hours=config.max_hours_per_driver
        )
        
        self.fte_indices = [i for i, d in enumerate(self.drivers) if d.driver_type == DriverType.FTE]
        self.pt_indices = [i for i, d in enumerate(self.drivers) if d.driver_type == DriverType.PT]
        
        print(f"Drivers: {len(self.fte_indices)} FTE + {len(self.pt_indices)} PT")
        
        # Build block pool
        self.blocks = build_weekly_blocks(tours)
        self.block_index = build_block_index(self.blocks)
        self.block_pool_stats = get_block_pool_stats(self.blocks)
        
        # Verify coverage
        is_complete, missing = verify_coverage(tours, self.blocks)
        if not is_complete:
            raise ValueError(f"Block pool missing coverage for tours: {missing}")
        
        print(f"Blocks: {self.block_pool_stats['total_blocks']} (1er={self.block_pool_stats['blocks_1er']}, 2er={self.block_pool_stats['blocks_2er']}, 3er={self.block_pool_stats['blocks_3er']})")
        
        # Results
        self.best_driver_count: int | None = None
        self.best_violation_total: float = 0
        self.best_fairness_gap: float | None = None
        self.solution: dict[tuple[int, int], int] = {}
        self.status = ForecastSolveStatus.HARD_OK
        self.slack_under_total = 0.0
        self.slack_over_total = 0.0
        self.solve_times: dict[str, float] = {}
        
        # Will be set after FTE-only test
        self.range_feasible_with_constraints = False
        self.pt_hours_total = 0.0
        
        # Build feasibility dict for output
        self.feasibility = {
            "range_feasible_hours_only": self.range_feasible_hours_only,
            "range_feasible_with_constraints": False,  # Will update after test
            "k_min": self.k_min,
            "k_max": self.k_max,
            "total_hours": self.total_hours,
            "explanation": hours_check['explanation']
        }
    
    def _test_fte_only_feasibility(self) -> bool:
        """
        Test if FTE-only solution is possible (no PT needed, no slack).
        
        This tests range_feasible_with_constraints by actually trying to solve
        with PT hours forced to 0 and FTE slack forced to 0.
        
        Returns:
            True if FTE-only solution exists, False otherwise
        """
        if not self.range_feasible_hours_only:
            # If hours alone aren't feasible, constraints won't help
            return False
        
        print("\n" + "=" * 60)
        print("PRE-CHECK: Testing FTE-only feasibility")
        print("=" * 60)
        
        model = cp_model.CpModel()
        
        min_mins = int(self.config.min_hours_per_driver * 60)
        max_mins = int(self.config.max_hours_per_driver * 60)
        
        # Variables - FTE only (no PT in this test)
        x = {}
        use = {}
        hours = {}
        
        for k in self.fte_indices:
            use[k] = model.NewBoolVar(f"use_{k}")
            hours[k] = model.NewIntVar(0, max_mins, f"hours_{k}")
        
        for b in range(len(self.blocks)):
            for k in self.fte_indices:
                x[(b, k)] = model.NewBoolVar(f"x_{b}_{k}")
        
        # Coverage: each tour exactly once (FTE only)
        for tour in self.tours:
            blocks_with_tour = self.block_index.get(tour.id, [])
            block_indices = [self.blocks.index(blk) for blk in blocks_with_tour]
            tour_vars = [x[(b_idx, k)] for b_idx in block_indices for k in self.fte_indices]
            model.Add(sum(tour_vars) == 1)
        
        # Each block at most once
        for b in range(len(self.blocks)):
            model.Add(sum(x[(b, k)] for k in self.fte_indices) <= 1)
        
        # Driver activation
        for k in self.fte_indices:
            for b in range(len(self.blocks)):
                model.Add(x[(b, k)] <= use[k])
        
        # No overlaps
        blocks_by_day: dict[Weekday, list[int]] = defaultdict(list)
        for b, block in enumerate(self.blocks):
            blocks_by_day[block.day].append(b)
        
        for day, day_blocks in blocks_by_day.items():
            for k in self.fte_indices:
                for i, b1 in enumerate(day_blocks):
                    for b2 in day_blocks[i + 1:]:
                        if self._blocks_overlap(self.blocks[b1], self.blocks[b2]):
                            model.Add(x[(b1, k)] + x[(b2, k)] <= 1)
        
        # Hours calculation (strict 42-53h, no slack)
        for k in self.fte_indices:
            block_mins = [x[(b, k)] * int(self.blocks[b].total_work_minutes) for b in range(len(self.blocks))]
            model.Add(hours[k] == sum(block_mins))
            model.Add(hours[k] >= min_mins).OnlyEnforceIf(use[k])
            model.Add(hours[k] <= max_mins).OnlyEnforceIf(use[k])
            model.Add(hours[k] == 0).OnlyEnforceIf(use[k].Not())
        
        # Force enough FTE drivers (at least k_min)
        model.Add(sum(use[k] for k in self.fte_indices) >= self.k_min)
        
        # Just find any feasible solution
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0  # Quick test
        solver.parameters.num_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.seed
        
        status = solver.Solve(model)
        self.solve_times["fte_only_test"] = solver.WallTime()
        
        is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        
        if is_feasible:
            print(f"  Result: FTE-only FEASIBLE (can achieve HARD_OK)")
        else:
            print(f"  Result: FTE-only INFEASIBLE (PT will be needed)")
        print(f"  Time: {solver.WallTime():.2f}s")
        
        return is_feasible
    
    def solve(self) -> WeeklyPlanResult:
        """Run 4-phase optimization."""
        
        # Pre-check: Test if FTE-only is feasible
        self.range_feasible_with_constraints = self._test_fte_only_feasibility()
        self.feasibility["range_feasible_with_constraints"] = self.range_feasible_with_constraints
        
        # Phase 1: Minimize FTE drivers
        print("\n" + "=" * 60)
        print("PHASE 1: Minimize FTE Drivers")
        print("=" * 60)
        self._solve_phase1()
        
        if self.best_driver_count is None:
            return self._build_failed_result()
        
        print(f"  Result: {self.best_driver_count} FTE drivers")
        
        # Phase 2: Minimize hour violations
        print("\n" + "=" * 60)
        print("PHASE 2: Minimize Hour Violations")
        print("=" * 60)
        self._solve_phase2()
        
        print(f"  Result: Under={self.slack_under_total:.1f}h, Over={self.slack_over_total:.1f}h")
        
        # Phase 3: Minimize fairness gap
        print("\n" + "=" * 60)
        print("PHASE 3: Minimize Fairness Gap")
        print("=" * 60)
        self._solve_phase3()
        
        print(f"  Result: Gap={self.best_fairness_gap:.1f}h")
        
        # Phase 4: Minimize 1er blocks
        print("\n" + "=" * 60)
        print("PHASE 4: Optimize Block Quality")
        print("=" * 60)
        self._solve_phase4()
        
        return self._build_result()
    
    def _build_model_base(self, model: cp_model.CpModel) -> tuple[dict, dict, dict, dict, dict]:
        """Build base model with variables and core constraints."""
        min_mins = int(self.config.min_hours_per_driver * 60)
        max_mins = int(self.config.max_hours_per_driver * 60)
        
        # Variables
        x = {}      # x[b,k] = block b assigned to driver k
        use = {}    # use[k] = driver k is used
        hours = {}  # hours[k] = total minutes for driver k
        under = {}  # under[k] = slack below min (FTE only)
        over = {}   # over[k] = slack above max (FTE only)
        
        for k in range(len(self.drivers)):
            use[k] = model.NewBoolVar(f"use_{k}")
            hours[k] = model.NewIntVar(0, 999 * 60, f"hours_{k}")
            
            # Slack only for FTE drivers
            if k in self.fte_indices:
                under[k] = model.NewIntVar(0, min_mins, f"under_{k}")
                over[k] = model.NewIntVar(0, 600, f"over_{k}")  # Max 10h over
            else:
                # PT drivers: no slack needed (no hour limits)
                under[k] = model.NewIntVar(0, 0, f"under_{k}")
                over[k] = model.NewIntVar(0, 0, f"over_{k}")
        
        for b in range(len(self.blocks)):
            for k in range(len(self.drivers)):
                x[(b, k)] = model.NewBoolVar(f"x_{b}_{k}")
        
        # Constraint: Coverage (each tour exactly once)
        for tour in self.tours:
            blocks_with_tour = self.block_index.get(tour.id, [])
            block_indices = [self.blocks.index(blk) for blk in blocks_with_tour]
            tour_vars = [x[(b_idx, k)] for b_idx in block_indices for k in range(len(self.drivers))]
            model.Add(sum(tour_vars) == 1)
        
        # Constraint: Each block assigned to at most one driver
        for b in range(len(self.blocks)):
            model.Add(sum(x[(b, k)] for k in range(len(self.drivers))) <= 1)
        
        # Constraint: Driver activation
        for k in range(len(self.drivers)):
            for b in range(len(self.blocks)):
                model.Add(x[(b, k)] <= use[k])
        
        # Constraint: No overlaps per driver per day
        self._add_overlap_constraints(model, x)
        
        # Constraint: Hours calculation
        for k in range(len(self.drivers)):
            block_mins = [x[(b, k)] * int(self.blocks[b].total_work_minutes) for b in range(len(self.blocks))]
            model.Add(hours[k] == sum(block_mins))
        
        # Constraint: Hour bounds for FTE drivers (with slack)
        for k in self.fte_indices:
            model.Add(hours[k] >= min_mins - under[k]).OnlyEnforceIf(use[k])
            model.Add(hours[k] <= max_mins + over[k]).OnlyEnforceIf(use[k])
            model.Add(hours[k] == 0).OnlyEnforceIf(use[k].Not())
        
        # PT drivers: just need hours=0 when not used
        for k in self.pt_indices:
            model.Add(hours[k] == 0).OnlyEnforceIf(use[k].Not())
        
        # CRITICAL: If FTE-only was proven feasible, force PT to 0
        # This ensures we get HARD_OK when it's actually achievable
        if self.range_feasible_with_constraints:
            for k in self.pt_indices:
                model.Add(use[k] == 0)
                model.Add(hours[k] == 0)
        
        return x, use, hours, under, over
    
    def _solve_phase1(self) -> None:
        """
        Phase 1: Find optimal FTE count with minimal violations.
        
        Priority (from most to least important):
        1. Minimize hour violations (slack) - stay in 42-53h range
        2. Minimize PT usage (overflow valve only)
        3. Use enough FTE drivers to meet hours (not too few, not too many)
        """
        model = cp_model.CpModel()
        x, use, hours, under, over = self._build_model_base(model)
        
        min_mins = int(self.config.min_hours_per_driver * 60)
        max_mins = int(self.config.max_hours_per_driver * 60)
        
        fte_sum = sum(use[k] for k in self.fte_indices)
        pt_sum = sum(use[k] for k in self.pt_indices)
        slack_sum = sum(under[k] + over[k] for k in self.fte_indices)
        pt_hours = sum(hours[k] for k in self.pt_indices)
        
        # If range-feasible, we should be able to use exactly k_min to k_max FTE drivers
        # with zero slack. Penalize deviations heavily.
        if self.range_feasible_hours_only:
            # Force FTE count to be at least k_min
            model.Add(fte_sum >= self.k_min)
            
            # Objective: Minimize slack first (should be 0 if range-feasible)
            # Then minimize PT hours, then minimize excess FTE
            model.Minimize(
                slack_sum * 1000000 +      # #1 priority: no violations
                pt_hours * 10000 +          # #2 priority: no PT hours
                pt_sum * 1000 +             # #3 priority: no PT drivers
                fte_sum * 1                 # #4 priority: minimize FTE (but above k_min)
            )
        else:
            # Not range-feasible: use as few drivers as possible while
            # minimizing violations. PT is an acceptable overflow.
            model.Minimize(
                slack_sum * 10000 +         # #1 priority: minimize violations
                fte_sum * 1000 +            # #2 priority: minimize FTE
                pt_sum * 100 +              # #3 priority: minimize PT count
                pt_hours * 1                # #4 priority: minimize PT hours
            )
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_phase1
        solver.parameters.num_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.seed
        
        status = solver.Solve(model)
        self.solve_times["phase1"] = solver.WallTime()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self.best_driver_count = int(solver.Value(fte_sum))
            
            for (b, k), var in x.items():
                self.solution[(b, k)] = solver.Value(var)
            
            # Track slack
            total_under = sum(solver.Value(under[k]) for k in self.fte_indices)
            total_over = sum(solver.Value(over[k]) for k in self.fte_indices)
            self.slack_under_total = total_under / 60
            self.slack_over_total = total_over / 60
            
            pt_used = sum(solver.Value(use[k]) for k in self.pt_indices)
            
            if total_under > 0 or total_over > 0 or pt_used > 0:
                self.status = ForecastSolveStatus.SOFT_FALLBACK_HOURS
            
            print(f"  FTE: {self.best_driver_count}, PT: {pt_used}")
            print(f"  Slack: under={self.slack_under_total:.1f}h, over={self.slack_over_total:.1f}h")
            print(f"  Time: {solver.WallTime():.2f}s")
        else:
            print("  [FAILED] Phase 1 infeasible")
            self.status = ForecastSolveStatus.FAILED
    
    def _solve_phase2(self) -> None:
        """Phase 2: Minimize hour violations (fix driver count)."""
        if self.best_driver_count is None:
            return
        
        model = cp_model.CpModel()
        x, use, hours, under, over = self._build_model_base(model)
        
        # Fix FTE driver count
        fte_sum = sum(use[k] for k in self.fte_indices)
        model.Add(fte_sum == self.best_driver_count)
        
        # Objective: Minimize slack (violations)
        slack_sum = sum(under[k] + over[k] for k in self.fte_indices)
        pt_sum = sum(use[k] for k in self.pt_indices)
        
        model.Minimize(slack_sum * 100 + pt_sum * 10)
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_phase2
        solver.parameters.num_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.seed
        
        status = solver.Solve(model)
        self.solve_times["phase2"] = solver.WallTime()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for (b, k), var in x.items():
                self.solution[(b, k)] = solver.Value(var)
            
            total_under = sum(solver.Value(under[k]) for k in self.fte_indices)
            total_over = sum(solver.Value(over[k]) for k in self.fte_indices)
            self.slack_under_total = total_under / 60
            self.slack_over_total = total_over / 60
            self.best_violation_total = self.slack_under_total + self.slack_over_total
            
            if total_under > 0 or total_over > 0:
                self.status = ForecastSolveStatus.SOFT_FALLBACK_HOURS
            
            print(f"  Time: {solver.WallTime():.2f}s")
        else:
            print("  [WARNING] Phase 2 infeasible, keeping Phase 1 solution")
    
    def _solve_phase3(self) -> None:
        """Phase 3: Minimize fairness gap (fix violations)."""
        if self.best_driver_count is None:
            return
        
        model = cp_model.CpModel()
        x, use, hours, under, over = self._build_model_base(model)
        
        min_mins = int(self.config.min_hours_per_driver * 60)
        max_mins = int(self.config.max_hours_per_driver * 60)
        
        # Fix FTE driver count
        fte_sum = sum(use[k] for k in self.fte_indices)
        model.Add(fte_sum == self.best_driver_count)
        
        # Fix slack (approximately)
        slack_sum = sum(under[k] + over[k] for k in self.fte_indices)
        max_slack = int((self.best_violation_total + 1) * 60)  # +1h tolerance
        model.Add(slack_sum <= max_slack)
        
        # Fairness: minimize (max - min) hours for used FTE drivers
        max_hours_var = model.NewIntVar(0, max_mins + 600, "max_hours")
        min_hours_var = model.NewIntVar(0, max_mins + 600, "min_hours")
        
        for k in self.fte_indices:
            model.Add(max_hours_var >= hours[k]).OnlyEnforceIf(use[k])
            M = max_mins + 600
            model.Add(min_hours_var <= hours[k] + M * use[k].Not())
        
        fairness_gap = model.NewIntVar(0, max_mins, "fairness_gap")
        model.Add(fairness_gap >= max_hours_var - min_hours_var)
        
        model.Minimize(fairness_gap)
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_phase3
        solver.parameters.num_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.seed
        
        status = solver.Solve(model)
        self.solve_times["phase3"] = solver.WallTime()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self.best_fairness_gap = solver.Value(fairness_gap) / 60.0
            
            for (b, k), var in x.items():
                self.solution[(b, k)] = solver.Value(var)
            
            print(f"  Time: {solver.WallTime():.2f}s")
        else:
            print("  [WARNING] Phase 3 infeasible, keeping Phase 2 solution")
            self.best_fairness_gap = self.config.max_hours_per_driver - self.config.min_hours_per_driver
    
    def _solve_phase4(self) -> None:
        """Phase 4: Minimize 1er blocks (fix everything else)."""
        if self.best_driver_count is None:
            return
        
        model = cp_model.CpModel()
        x, use, hours, under, over = self._build_model_base(model)
        
        min_mins = int(self.config.min_hours_per_driver * 60)
        max_mins = int(self.config.max_hours_per_driver * 60)
        
        # Fix driver count
        fte_sum = sum(use[k] for k in self.fte_indices)
        model.Add(fte_sum == self.best_driver_count)
        
        # Fix slack
        slack_sum = sum(under[k] + over[k] for k in self.fte_indices)
        max_slack = int((self.best_violation_total + 1) * 60)
        model.Add(slack_sum <= max_slack)
        
        # Fix fairness gap (approximately)
        if self.best_fairness_gap is not None:
            max_hours_var = model.NewIntVar(0, max_mins + 600, "max_hours")
            min_hours_var = model.NewIntVar(0, max_mins + 600, "min_hours")
            
            for k in self.fte_indices:
                model.Add(max_hours_var >= hours[k]).OnlyEnforceIf(use[k])
                M = max_mins + 600
                model.Add(min_hours_var <= hours[k] + M * use[k].Not())
            
            max_gap = int((self.best_fairness_gap + 1) * 60)
            model.Add(max_hours_var - min_hours_var <= max_gap)
        
        # Objective: Minimize 1er, maximize 3er/2er
        block_quality = []
        for b, block in enumerate(self.blocks):
            n = len(block.tours)
            for k in range(len(self.drivers)):
                if n == 1:
                    block_quality.append(-x[(b, k)] * 100)
                elif n == 2:
                    block_quality.append(x[(b, k)] * 10)
                elif n == 3:
                    block_quality.append(x[(b, k)] * 50)
        
        model.Maximize(sum(block_quality))
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_phase4
        solver.parameters.num_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.seed
        
        status = solver.Solve(model)
        self.solve_times["phase4"] = solver.WallTime()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for (b, k), var in x.items():
                self.solution[(b, k)] = solver.Value(var)
            
            print(f"  Time: {solver.WallTime():.2f}s")
        else:
            print("  [WARNING] Phase 4 infeasible, keeping Phase 3 solution")
    
    def _add_overlap_constraints(self, model: cp_model.CpModel, x: dict) -> None:
        """Add constraints to prevent overlapping blocks for same driver."""
        blocks_by_day: dict[Weekday, list[int]] = defaultdict(list)
        for b, block in enumerate(self.blocks):
            blocks_by_day[block.day].append(b)
        
        for day, day_blocks in blocks_by_day.items():
            for k in range(len(self.drivers)):
                for i, b1 in enumerate(day_blocks):
                    for b2 in day_blocks[i + 1:]:
                        if self._blocks_overlap(self.blocks[b1], self.blocks[b2]):
                            model.Add(x[(b1, k)] + x[(b2, k)] <= 1)
    
    def _blocks_overlap(self, b1: Block, b2: Block) -> bool:
        """Check if two blocks overlap in time."""
        if b1.day != b2.day:
            return False
        
        b1_start = b1.first_start.hour * 60 + b1.first_start.minute
        b1_end = b1.last_end.hour * 60 + b1.last_end.minute
        b2_start = b2.first_start.hour * 60 + b2.first_start.minute
        b2_end = b2.last_end.hour * 60 + b2.last_end.minute
        
        return not (b1_end <= b2_start or b2_end <= b1_start)
    
    def _build_result(self) -> WeeklyPlanResult:
        """Build final result from solution."""
        driver_schedules: list[DriverSchedule] = []
        
        hours_per_driver: dict[int, float] = defaultdict(float)
        blocks_per_driver: dict[int, list[Block]] = defaultdict(list)
        
        for (b, k), val in self.solution.items():
            if val == 1:
                block = self.blocks[b]
                hours_per_driver[k] += block.total_work_hours
                blocks_per_driver[k].append(block)
        
        fte_hours = []
        pt_hours = []
        
        for k in range(len(self.drivers)):
            if hours_per_driver[k] > 0:
                driver = self.drivers[k]
                blocks = blocks_per_driver[k]
                
                schedule: dict[str, list[dict]] = {}
                days_worked = set()
                blocks_1er = blocks_2er = blocks_3er = 0
                
                for block in blocks:
                    day_name = block.day.value
                    days_worked.add(day_name)
                    
                    if day_name not in schedule:
                        schedule[day_name] = []
                    
                    n = len(block.tours)
                    if n == 1:
                        blocks_1er += 1
                    elif n == 2:
                        blocks_2er += 1
                    elif n == 3:
                        blocks_3er += 1
                    
                    schedule[day_name].append({
                        "block_id": block.id,
                        "tours": [t.id for t in block.tours],
                        "start": block.first_start.strftime("%H:%M"),
                        "end": block.last_end.strftime("%H:%M"),
                        "hours": round(block.total_work_hours, 2)
                    })
                
                driver_schedules.append(DriverSchedule(
                    driver_id=driver.id,
                    driver_type=driver.driver_type.value,
                    hours_week=hours_per_driver[k],
                    days_worked=len(days_worked),
                    blocks_1er=blocks_1er,
                    blocks_2er=blocks_2er,
                    blocks_3er=blocks_3er,
                    schedule=schedule
                ))
                
                if driver.driver_type == DriverType.FTE:
                    fte_hours.append(hours_per_driver[k])
                else:
                    pt_hours.append(hours_per_driver[k])
        
        # Calculate KPIs
        total_1er = sum(d.blocks_1er for d in driver_schedules)
        total_2er = sum(d.blocks_2er for d in driver_schedules)
        total_3er = sum(d.blocks_3er for d in driver_schedules)
        
        fte_count = len([d for d in driver_schedules if d.driver_type == "FTE"])
        pt_count = len([d for d in driver_schedules if d.driver_type == "PT"])
        
        # Calculate PT hours total
        pt_hours_total = sum(pt_hours) if pt_hours else 0.0
        self.pt_hours_total = pt_hours_total
        
        # STRICT STATUS DETERMINATION
        # HARD_OK only when:
        # 1. PT hours = 0 (no overflow to PT)
        # 2. All FTE in 42-53h range (slack = 0)
        has_pt_usage = pt_hours_total > 0
        has_slack = self.slack_under_total > 0 or self.slack_over_total > 0
        
        # Check if all FTE are in range
        fte_all_in_range = True
        min_hours = self.config.min_hours_per_driver
        max_hours = self.config.max_hours_per_driver
        for h in fte_hours:
            if h < min_hours or h > max_hours:
                fte_all_in_range = False
                break
        
        # HARD_OK = no PT usage AND all FTE strictly in range
        hard_ok_strict = not has_pt_usage and fte_all_in_range and not has_slack
        
        if hard_ok_strict:
            final_status = ForecastSolveStatus.HARD_OK
        else:
            final_status = ForecastSolveStatus.SOFT_FALLBACK_HOURS
        
        kpi = {
            "status": final_status,
            "hard_ok_strict": hard_ok_strict,
            "fallback_triggered": final_status == ForecastSolveStatus.SOFT_FALLBACK_HOURS,
            "range_feasible_hours_only": self.range_feasible_hours_only,
            "range_feasible_with_constraints": self.range_feasible_with_constraints,
            "k_min": self.k_min,
            "k_max": self.k_max,
            "slack_under_total": round(self.slack_under_total, 2),
            "slack_over_total": round(self.slack_over_total, 2),
            "drivers_fte": fte_count,
            "drivers_pt": pt_count,
            "drivers_total": fte_count + pt_count,
            "coverage_rate": 1.0,
            "total_hours": round(self.total_hours, 2),
            "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
            "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
            "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
            "fte_fairness_gap": round(max(fte_hours) - min(fte_hours), 2) if fte_hours else 0,
            "pt_hours_total": round(pt_hours_total, 2),
            "blocks_1er": total_1er,
            "blocks_2er": total_2er,
            "blocks_3er": total_3er,
            "solve_time_total": round(sum(self.solve_times.values()), 2),
            "solve_times": {k: round(v, 2) for k, v in self.solve_times.items()}
        }
        
        return WeeklyPlanResult(
            status=final_status,
            drivers=driver_schedules,
            kpi=kpi,
            block_pool_stats=self.block_pool_stats,
            feasibility=self.feasibility,
            solve_times=self.solve_times
        )
    
    def _build_failed_result(self) -> WeeklyPlanResult:
        """Build result for failed solve."""
        return WeeklyPlanResult(
            status=ForecastSolveStatus.FAILED,
            drivers=[],
            kpi={
                "status": ForecastSolveStatus.FAILED,
                "fallback_triggered": False,
                "drivers_total": 0,
                "coverage_rate": 0.0,
                "error": "Solver failed"
            },
            block_pool_stats=self.block_pool_stats,
            feasibility=self.feasibility,
            solve_times=self.solve_times
        )


# =============================================================================
# ENTRY POINT
# =============================================================================

def solve_forecast_weekly(
    tours: list[Tour],
    config: ForecastConfig = ForecastConfig()
) -> WeeklyPlanResult:
    """
    Solve forecast-only weekly planning problem.
    """
    solver = ForecastWeeklySolverV2(tours, config)
    return solver.solve()
