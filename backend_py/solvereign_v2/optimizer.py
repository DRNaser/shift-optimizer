"""
Solvereign V2 - Optimizer Engine

Main orchestrator for the Column Generation pipeline.
Uses lazy duty generation to avoid duty explosion.

Migrated from:
- src/core_v2/optimizer_v2.py
- src/core_v2/seeder.py
- src/core_v2/contracts/result.py
"""

import time
import logging
import random
from dataclasses import dataclass, field
from typing import Optional, Any

from .types import TourV2, DutyV2, Weekday, WeekCategory
from .validator import ValidatorV2
from .config import BUSINESS_RULES, DEFAULT_SOLVER_CONFIG
from .duty_builder import DutyBuilderTopK, DutyBuilderCaps
from .roster_builder import (
    RosterBuilder, ColumnV2, Label,
    PROFILE_NORMAL, PROFILE_STALL, PROFILE_NUCLEAR
)
from .master_solver import MasterLP, MasterMIP, check_highs_available
from .fleet_counter import calculate_fleet_peak

# Guards from SINGLE SOURCE (src/core_v2/guards.py)
from src.core_v2.guards import (
    run_pre_mip_guards, 
    run_post_solve_guards, 
    run_post_seed_guards,
    AtomicCoverageGuard,
    RestTimeGuard,
    GapDayGuard,
)

logger = logging.getLogger("SolvereIgnOptimizer")


# =============================================================================
# RESULT CONTRACTS
# =============================================================================

@dataclass
class OptimizationProof:
    """Proof of correctness for optimization run."""
    coverage_pct: float = 0.0
    artificial_used_lp: int = 0
    artificial_used_final: int = 0
    mip_gap: float = 0.0
    total_tours: int = 0
    covered_tours: int = 0


@dataclass
class OptimizationResult:
    """Result contract for Solvereign V2 Optimizer."""
    status: str  # SUCCESS | FAIL | UNKNOWN
    run_id: str = ""
    error_code: str = ""
    error_message: str = ""
    
    week_type: str = ""
    active_days: int = 0
    
    selected_columns: list = field(default_factory=list)  # list[ColumnV2]
    kpis: dict = field(default_factory=dict)
    proof: OptimizationProof = field(default_factory=OptimizationProof)
    
    logs: list = field(default_factory=list)
    
    @property
    def num_drivers(self) -> int:
        return len(self.selected_columns)
    
    @property
    def is_valid(self) -> bool:
        return (
            self.status == "SUCCESS" and
            self.proof.coverage_pct == 100.0 and
            self.proof.artificial_used_final == 0
        )
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "week_type": self.week_type,
            "active_days": self.active_days,
            "num_drivers": self.num_drivers,
            "kpis": self.kpis,
            "proof": {
                "coverage_pct": self.proof.coverage_pct,
                "artificial_used_lp": self.proof.artificial_used_lp,
                "artificial_used_final": self.proof.artificial_used_final,
                "mip_gap": self.proof.mip_gap,
            },
            "is_valid": self.is_valid,
        }


# =============================================================================
# COLUMN POOL
# =============================================================================

class ColumnPool:
    """Simple column pool with deduplication."""
    
    def __init__(self):
        self.columns: list[ColumnV2] = []
        self._signatures: set[str] = set()
    
    @property
    def size(self) -> int:
        return len(self.columns)
    
    def add(self, col: ColumnV2) -> bool:
        """Add column if not duplicate. Returns True if added."""
        if col.signature not in self._signatures:
            self._signatures.add(col.signature)
            self.columns.append(col)
            return True
        return False
    
    def add_all(self, cols: list[ColumnV2]) -> int:
        """Add multiple columns. Returns count of actually added."""
        count = 0
        for c in cols:
            if self.add(c):
                count += 1
        return count


# =============================================================================
# GREEDY SEEDER
# =============================================================================

class GreedySeeder:
    """Generates initial seed columns without full duty enumeration."""
    
    def __init__(
        self, 
        tours_by_day: dict[int, list[TourV2]],
        target_seeds: int = 5000,
        validator=ValidatorV2
    ):
        self.tours_by_day = tours_by_day
        self.target_seeds = target_seeds
        self.validator = validator
        self.sorted_days = sorted(tours_by_day.keys())
        self._factory = DutyBuilderTopK(tours_by_day, validator)
    
    def generate_seeds(self) -> list[ColumnV2]:
        """Generate seed columns for CG initialization."""
        logger.info(f"Generating seeds (target={self.target_seeds})...")
        
        # 1. Singleton columns
        singleton_cols = self._generate_singletons()
        logger.info(f"  Singleton columns: {len(singleton_cols)}")
        
        # 2. Multi-day columns
        multi_cols = self._generate_multi_day()
        logger.info(f"  Multi-day columns: {len(multi_cols)}")
        
        # Combine and dedupe
        all_cols = singleton_cols + multi_cols
        seen = set()
        unique_cols = []
        for col in all_cols:
            if col.signature not in seen:
                seen.add(col.signature)
                unique_cols.append(col)
        
        logger.info(f"Total seed columns: {len(unique_cols)}")
        return unique_cols
    
    def _generate_singletons(self) -> list[ColumnV2]:
        """Generate one column per tour."""
        cols = []
        for day in self.sorted_days:
            for tour in self.tours_by_day[day]:
                duty = DutyV2.from_tours(duty_id=f"seed_s_{tour.tour_id}", tours=[tour])
                col = ColumnV2.from_duties(
                    col_id=f"seed_{duty.duty_id}",
                    duties=[duty],
                    origin="seed_singleton"
                )
                cols.append(col)
        return cols
    
    def _generate_multi_day(self) -> list[ColumnV2]:
        """Generate columns spanning multiple days."""
        uniform_duals = {}
        for day, tours in self.tours_by_day.items():
            for t in tours:
                uniform_duals[t.tour_id] = 1.0
        
        seed_caps = DutyBuilderCaps(
            max_multi_duties_per_day=5000,
            top_m_start_tours=500,
            max_succ_per_tour=15,
            max_triples_per_tour=5,
        )
        
        duties_by_day: dict[int, list[DutyV2]] = {}
        tour_to_duties: dict[str, list[DutyV2]] = {}
        
        for day in self.sorted_days:
            try:
                self._factory.reset_telemetry()
                duties = self._factory.get_day_duties(day, uniform_duals, seed_caps)
                duties_by_day[day] = duties
                for d in duties:
                    for tid in d.tour_ids:
                        tour_to_duties.setdefault(tid, []).append(d)
            except RuntimeError:
                duties_by_day[day] = []
        
        multi_cols = []
        seen_signatures = set()
        MIN_SEEDS_PER_TOUR = 5
        
        all_tours = []
        for day in self.sorted_days:
            all_tours.extend(self.tours_by_day.get(day, []))
        
        for tour in all_tours:
            candidate_duties = tour_to_duties.get(tour.tour_id, [])
            if not candidate_duties:
                continue
            
            random.shuffle(candidate_duties)
            seeds_found = 0
            
            for d1 in candidate_duties[:10]:
                if seeds_found >= MIN_SEEDS_PER_TOUR:
                    break
                
                current_chain = [d1]
                start_day_idx = self.sorted_days.index(d1.day)
                extended = False
                
                for next_day_idx in range(start_day_idx + 1, len(self.sorted_days)):
                    next_day = self.sorted_days[next_day_idx]
                    duties_next = duties_by_day.get(next_day, [])
                    
                    sample_next = list(duties_next)
                    if len(sample_next) > 50:
                        sample_next = random.sample(sample_next, 50)
                    
                    for d2 in sample_next:
                        if self.validator.can_chain_days(current_chain[-1], d2):
                            current_chain.append(d2)
                            extended = True
                            break
                
                if extended:
                    col = ColumnV2.from_duties(
                        col_id=f"seed_{len(multi_cols)}",
                        duties=current_chain,
                        origin=f"seed_tour_{tour.tour_id}"
                    )
                    if col.signature not in seen_signatures:
                        seen_signatures.add(col.signature)
                        multi_cols.append(col)
                        seeds_found += 1
        
        return multi_cols


# =============================================================================
# MAIN OPTIMIZER
# =============================================================================

class Optimizer:
    """
    Column Generation Optimizer.
    Main entry point for Solvereign V2.
    """
    
    def solve(
        self, 
        tours: list[TourV2], 
        config: dict = None,
        run_id: str = "sv2_run"
    ) -> OptimizationResult:
        """
        Main entry point.
        
        Args:
            tours: List of TourV2 objects
            config: Configuration dict
            run_id: Unique run identifier
        """
        check_highs_available()
        
        config = config or {}
        logs = []
        
        def log(msg: str, level: int = logging.INFO):
            logger.log(level, msg)
            logs.append(msg)
        
        start_time = time.time()
        proof = OptimizationProof(total_tours=len(tours))
        
        # Extract config
        duty_caps = DutyBuilderCaps(
            max_multi_duties_per_day=config.get("max_multi_duties_per_day", 50_000),
            top_m_start_tours=config.get("top_m_start_tours", 200),
            max_succ_per_tour=config.get("max_succ_per_tour", 20),
            max_triples_per_tour=config.get("max_triples_per_tour", 5),
        )
        
        telemetry = {
            "cg_iterations": 0,
            "new_cols_added_total": 0,
        }
        
        try:
            # 1. Group tours by day
            tours_by_day: dict[int, list[TourV2]] = {}
            for t in tours:
                tours_by_day.setdefault(t.day, []).append(t)
            
            active_days = len(tours_by_day)
            week_category = self._classify_week(active_days)
            
            log(f"Starting optimization: {len(tours)} tours, {active_days} days, {week_category.value}")
            
            # 2. Create duty builder
            duty_builder = DutyBuilderTopK(tours_by_day, ValidatorV2)
            
            # 3. Generate seed columns
            target_seeds = config.get("target_seed_columns", 5000)
            seeder = GreedySeeder(tours_by_day, target_seeds, ValidatorV2)
            
            pool = ColumnPool()
            seed_cols = seeder.generate_seeds()
            pool.add_all(seed_cols)
            
            log(f"Seeded pool with {pool.size} columns")
            
            # 4. Column Generation Loop
            all_tour_ids = sorted([t.tour_id for t in tours])
            
            # GUARD: Validate atomics exist for ALL tours (CODE INVARIANT)
            try:
                run_post_seed_guards(pool.columns, set(all_tour_ids))
            except AssertionError as e:
                log(f"GUARD FAILURE POST-SEED: {e}", logging.ERROR)
                return self._fail_result(run_id, "GUARD_FAIL_POST_SEED", str(e), logs, proof)
            
            pricer = RosterBuilder(duty_builder, week_category, duty_caps)
            pricer.pricing_time_limit = config.get("pricing_time_limit_sec", 6.0)
            
            max_iter = config.get("max_cg_iterations", 30)
            lp_time_limit = config.get("lp_time_limit", 10.0)
            max_new_cols = config.get("max_new_cols_per_iter", 1500)
            
            log(f"Starting CG loop (max {max_iter} iters, LP limit {lp_time_limit}s)")
            
            converged = False
            current_duals = {}
            last_optimal_duals = {}
            no_new_cols_iters = 0
            
            # Stall Detection state
            stall_count = 0
            
            for iteration in range(1, max_iter + 1):
                iter_start = time.time()
                
                # a. Solve Master LP
                master_lp = MasterLP(pool.columns, all_tour_ids)
                master_lp.build(week_category)
                lp_res = master_lp.solve(time_limit=lp_time_limit)
                
                lp_status = lp_res["status"]
                lp_obj = lp_res.get("objective", 0.0)
                artificial_lp = lp_res.get("artificial_used", 0)
                
                if lp_status == "Optimal":
                    current_duals = lp_res["duals"]
                    last_optimal_duals = current_duals.copy()
                elif lp_status == "Time limit reached" and lp_res.get("objective"):
                    if last_optimal_duals:
                        current_duals = last_optimal_duals
                        log(f"Iter {iteration}: LP timeout, using stale duals", logging.WARNING)
                    else:
                        return self._fail_result(run_id, "LP_NEVER_OPTIMAL", "No duals", logs, proof)
                else:
                    return self._fail_result(run_id, "LP_FAIL", lp_status, logs, proof)
                
                # b. Pricing
                try:
                    new_cols = pricer.price(current_duals, max_new_cols=max_new_cols)
                    added_count = pool.add_all(new_cols)
                    telemetry["new_cols_added_total"] += added_count
                except RuntimeError as e:
                    return self._fail_result(run_id, "PRICING_FAIL", str(e), logs, proof)
                
                # c. Stall Detection & Profile Switching
                best_rc = pricer.rc_telemetry.best_rc_total
                
                # Stall definition: added=0 or no negative RC found
                is_stalled = (added_count == 0) or (best_rc >= -1e-5)
                
                if is_stalled:
                    stall_count += 1
                else:
                    # Reset stall count on progress
                    stall_count = 0
                
                # State Machine for Profile
                target_profile = PROFILE_NORMAL
                
                if stall_count >= 5:
                    target_profile = PROFILE_NUCLEAR
                elif stall_count >= 2:
                    target_profile = PROFILE_STALL
                
                # Apply profile
                if pricer.profile.name != target_profile.name:
                    pricer.set_profile(target_profile)
                    
                
                iter_time = time.time() - iter_start
                log(
                    f"Iter {iteration}: LP={lp_obj:.1f}, "
                    f"Cols={len(new_cols)} (Added={added_count}), "
                    f"BestRC={best_rc:.4f}, "
                    f"Profile={pricer.profile.name}, "
                    f"Pool={pool.size}, "
                    f"Time={iter_time:.1f}s"
                )
                
                # d. Stop conditions (using stall_count logic for consistency)
                # If stalled in NUCLEAR mode for 2 iters -> STOP
                if pricer.profile.name == "NUCLEAR" and stall_count >= 7:
                    log("STOPPING: CG converged (stalled in NUCLEAR mode)")
                    converged = True
                    break
                
                # Legacy stop condition (fallback)
                if len(new_cols) == 0:
                    no_new_cols_iters += 1
                else:
                    no_new_cols_iters = 0
                
                if no_new_cols_iters >= 10: # Increased from 3 to allow profiles to work
                    log("STOPPING: CG converged (no new columns for 10 iters)")
                    converged = True
                    break
            
            telemetry["cg_iterations"] = iteration
            
            # 5. Final MIP
            log(f"Starting Final MIP (pool={pool.size})...")
            
            # GUARD: Validate atomic coverage BEFORE MIP (HARD FAILURE)
            try:
                run_pre_mip_guards(pool.columns, set(all_tour_ids))
            except AssertionError as e:
                log(f"GUARD FAILURE: {e}", logging.ERROR)
                return self._fail_result(run_id, "GUARD_FAIL_PRE_MIP", str(e), logs, proof)
            
            master_mip = MasterMIP(pool.columns, all_tour_ids)
            mip_res = master_mip.solve_lexico(
                week_category,
                time_limit=config.get("mip_time_limit", 300.0)
            )
            
            total_time = time.time() - start_time
            
            if mip_res["status"] == "OPTIMAL":
                selected_columns: list[ColumnV2] = mip_res["selected_columns"]
                log(f"MIP Optimal! {len(selected_columns)} drivers. Obj={mip_res['objective']}")
                
                # GUARD: Validate solution constraints (HARD FAILURE)
                try:
                    run_post_solve_guards(selected_columns)
                except AssertionError as e:
                    log(f"GUARD FAILURE POST-SOLVE: {e}", logging.ERROR)
                    return self._fail_result(run_id, "GUARD_FAIL_POST_SOLVE", str(e), logs, proof)
                
                # Coverage check
                covered_tours = set()
                for col in selected_columns:
                    covered_tours.update(col.covered_tour_ids)
                
                proof.covered_tours = len(covered_tours)
                proof.coverage_pct = (len(covered_tours) / len(all_tour_ids)) * 100 if all_tour_ids else 100.0
                
                # Build KPIs
                kpis = self._build_kpis(selected_columns, total_time, telemetry, pool)
                
                return OptimizationResult(
                    status="SUCCESS",
                    run_id=run_id,
                    week_type=week_category.value,
                    active_days=active_days,
                    selected_columns=selected_columns,
                    kpis=kpis,
                    proof=proof,
                    logs=logs,
                )
            else:
                return self._fail_result(run_id, "MIP_FAILED", mip_res["status"], logs, proof)
                
        except Exception as e:
            import traceback
            log(f"EXCEPTION: {e}\n{traceback.format_exc()}", logging.ERROR)
            return self._fail_result(run_id, "EXCEPTION", str(e), logs, proof)
    
    def _classify_week(self, active_days: int) -> WeekCategory:
        """Classify week by active days."""
        if active_days <= 2:
            return WeekCategory.SHORT
        elif active_days <= 4:
            return WeekCategory.COMPRESSED
        else:
            return WeekCategory.NORMAL
    
    def _fail_result(self, run_id, code, msg, logs, proof) -> OptimizationResult:
        return OptimizationResult(
            status="FAIL",
            run_id=run_id,
            error_code=code,
            error_message=msg,
            week_type="UNKNOWN",
            active_days=0,
            selected_columns=[],
            kpis={"error": msg},
            proof=proof,
            logs=logs,
        )
    
    def _build_kpis(self, selected_columns, total_time, telemetry, pool) -> dict:
        """Build KPI dictionary."""
        hours = [c.hours for c in selected_columns]
        days = [c.days_worked for c in selected_columns]
        
        # Days histogram
        days_hist = {}
        for d in days:
            days_hist[d] = days_hist.get(d, 0) + 1
        
        # FTE/PT split
        fte_count = sum(1 for h in hours if h >= 40.0)
        pt_count = len(hours) - fte_count
        
        return {
            "total_time": total_time,
            "drivers_total": len(selected_columns),
            "drivers_fte": fte_count,
            "drivers_pt": pt_count,
            "pt_share_pct": (pt_count / max(1, len(selected_columns))) * 100,
            "avg_hours": sum(hours) / len(hours) if hours else 0,
            "pct_under_30": (sum(1 for h in hours if h < 30) / len(hours) * 100) if hours else 0,
            "pct_under_20": (sum(1 for h in hours if h < 20) / len(hours) * 100) if hours else 0,
            "selected_days_worked_hist": dict(sorted(days_hist.items())),
            "pool_final_size": pool.size,
            "cg_iterations": telemetry["cg_iterations"],
            "new_cols_added_total": telemetry["new_cols_added_total"],
        }
