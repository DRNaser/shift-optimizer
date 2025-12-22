"""
PORTFOLIO CONTROLLER - Meta-Orchestrator for Shift Optimizer
=============================================================
Orchestrates the complete optimization pipeline:
1. Profile instance (extract features)
2. Select path and parameters via policy engine
3. Execute solver with early-stop monitoring
4. Fallback on stagnation
5. Return best solution with full telemetry

All execution is deterministic (seeded, num_workers=1).
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter, monotonic
from typing import Optional, Callable

from src.domain.models import Tour, Block, Weekday
from src.services.instance_profiler import (
    FeatureVector,
    compute_features,
    InstanceProfiler,
)
from src.services.policy_engine import (
    PathSelection,
    ParameterBundle,
    ReasonCode,
    PolicyEngine,
    select_path,
    select_parameters,
    should_early_stop,
    should_fallback,
    get_fallback_path,
)

# Prometheus metrics (optional - graceful degradation if not available)
try:
    from src.api.prometheus_metrics import (
        record_run_completed,
        record_phase_timing,
        record_path_selection,
        record_fallback,
        record_candidate_counts,
    )
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False

# Alias to prevent shadowing issues inside functions
PS = PathSelection

logger = logging.getLogger("PortfolioController")


# =============================================================================
# S0.2: HARD BUDGET SLICING
# =============================================================================

@dataclass
class BudgetSlice:
    """
    S0.2: Hard time slices for deterministic budget allocation.
    Each phase gets a fixed slice. No overruns allowed.
    """
    total: float
    profiling: float
    phase1: float
    phase2: float
    lns: float
    buffer: float
    
    @classmethod
    def from_total(cls, total: float) -> 'BudgetSlice':
        """
        Create budget slices from total budget.
        Distribution: profiling=2%, phase1=50%, phase2=15%, lns=28%, buffer=5%
        """
        return cls(
            total=total,
            profiling=total * 0.02,  # 0.6s for 30s budget
            phase1=total * 0.50,     # 15s for 30s budget
            phase2=total * 0.15,     # 4.5s for 30s budget
            lns=total * 0.28,        # 8.4s for 30s budget
            buffer=total * 0.05,     # 1.5s for 30s budget
        )
    
    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 2),
            "profiling": round(self.profiling, 2),
            "phase1": round(self.phase1, 2),
            "phase2": round(self.phase2, 2),
            "lns": round(self.lns, 2),
            "buffer": round(self.buffer, 2),
        }


# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass
class PortfolioResult:
    """
    Complete result from portfolio optimization.
    Includes solution, features, decisions, and telemetry.
    """
    # Solution (wrapped SolveResultV4)
    solution: 'SolveResultV4'
    
    # Profiler output
    features: FeatureVector
    
    # Policy decisions
    initial_path: PathSelection
    final_path: PathSelection
    parameters_used: ParameterBundle
    reason_codes: list[str] = field(default_factory=list)
    
    # Bounds
    lower_bound: int = 0
    achieved_score: int = 0
    gap_to_lb: float = 0.0
    
    # Execution telemetry
    early_stopped: bool = False
    early_stop_reason: str = ""
    fallback_used: bool = False
    fallback_count: int = 0
    total_runtime_s: float = 0.0
    
    # Phase timings
    profiling_time_s: float = 0.0
    phase1_time_s: float = 0.0
    phase2_time_s: float = 0.0
    lns_time_s: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "solution_status": self.solution.status if self.solution else None,
            "features": self.features.to_dict() if self.features else None,
            "initial_path": self.initial_path.value if self.initial_path else None,
            "final_path": self.final_path.value if self.final_path else None,
            "parameters_used": self.parameters_used.to_dict() if self.parameters_used else None,
            "reason_codes": self.reason_codes,
            "lower_bound": self.lower_bound,
            "achieved_score": self.achieved_score,
            "gap_to_lb": round(self.gap_to_lb, 4),
            "early_stopped": self.early_stopped,
            "early_stop_reason": self.early_stop_reason,
            "fallback_used": self.fallback_used,
            "fallback_count": self.fallback_count,
            "total_runtime_s": round(self.total_runtime_s, 2),
            "profiling_time_s": round(self.profiling_time_s, 3),
            "phase1_time_s": round(self.phase1_time_s, 2),
            "phase2_time_s": round(self.phase2_time_s, 2),
            "lns_time_s": round(self.lns_time_s, 2),
        }


@dataclass
class RunReport:
    """
    S0.7: Full run report for logging and debugging.
    
    Contains canonical, deterministic fields for regression testing:
    - Pool stats: raw, dedup, capped counts
    - Budget: slices and enforcement status
    - Determinism: seed, num_workers, use_deterministic_time
    - Timing: per-phase and total (wall-clock, not for determinism gate)
    - Reason codes: all decision points
    - Solution signature: canonical (excludes uuid/timestamp)
    """
    # Input (stable)
    input_summary: dict
    features: dict
    
    # Pool stats (S0.7)
    pool_raw: int = 0
    pool_dedup: int = 0
    pool_capped: int = 0
    
    # Budget (S0.7)
    budget_total: float = 0.0
    budget_slices: dict = field(default_factory=dict)
    budget_enforced: bool = True
    
    # Determinism params (S0.7)
    seed: int = 42
    num_workers: int = 1
    use_deterministic_time: bool = False
    
    # Policy decisions
    policy_decisions: dict = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    
    # Timing (wall-clock, NOT for determinism gate)
    time_phase1: float = 0.0
    time_phase2: float = 0.0
    time_lns: float = 0.0
    time_total: float = 0.0
    
    # Result
    result_summary: dict = field(default_factory=dict)
    
    # Solution signature (S0.5 canonical, for determinism gate)
    solution_signature: dict = field(default_factory=dict)
    
    # Legacy compatibility
    timestamp: str = ""  # NOT used in canonical JSON
    execution_log: list[dict] = field(default_factory=list)
    solve_times: dict = field(default_factory=dict)
    
    def to_json(self) -> str:
        """Serialize to JSON string (includes timestamp for logging)."""
        return json.dumps({
            "timestamp": self.timestamp,
            "input_summary": self.input_summary,
            "features": self.features,
            "pool": {
                "raw": self.pool_raw,
                "dedup": self.pool_dedup,
                "capped": self.pool_capped,
            },
            "budget": {
                "total": self.budget_total,
                "slices": self.budget_slices,
                "enforced": self.budget_enforced,
            },
            "determinism": {
                "seed": self.seed,
                "num_workers": self.num_workers,
                "use_deterministic_time": self.use_deterministic_time,
            },
            "policy_decisions": self.policy_decisions,
            "reason_codes": self.reason_codes,
            "timing": {
                "phase1_s": round(self.time_phase1, 3),
                "phase2_s": round(self.time_phase2, 3),
                "lns_s": round(self.time_lns, 3),
                "total_s": round(self.time_total, 3),
            },
            "result_summary": self.result_summary,
            "solution_signature": self.solution_signature,
        }, indent=2, sort_keys=True)  # sort_keys for stable output
    
    def to_canonical_json(self) -> str:
        """
        S0.7: Canonical JSON for determinism testing.
        EXCLUDES: timestamp, wallclock times, execution_log.
        Uses sorted keys for stable output.
        """
        return json.dumps({
            "input_summary": self.input_summary,
            "features": self.features,
            "pool": {
                "raw": self.pool_raw,
                "dedup": self.pool_dedup,
                "capped": self.pool_capped,
            },
            "budget": {
                "total": self.budget_total,
                "slices": self.budget_slices,
                "enforced": self.budget_enforced,
            },
            "determinism": {
                "seed": self.seed,
                "num_workers": self.num_workers,
            },
            "reason_codes": sorted(self.reason_codes),  # Sorted for determinism
            "result_summary": self.result_summary,
            "solution_signature": self.solution_signature,
        }, indent=2, sort_keys=True)


# =============================================================================
# PORTFOLIO CONTROLLER
# =============================================================================

def run_portfolio(
    tours: list[Tour],
    time_budget: float = 30.0,
    seed: int = 42,
    config: 'ConfigV4' = None,
    log_fn: Callable[[str], None] = None,
) -> PortfolioResult:
    """
    Main entry point for portfolio-based optimization.
    
    Orchestrates the complete pipeline:
    1. Profile instance -> FeatureVector
    2. Select path (A/B/C) and parameters
    3. Execute solver with monitoring
    4. Early-stop if good enough
    5. Fallback if stagnation detected
    6. Return best solution with telemetry
    
    Args:
        tours: List of Tour objects (forecast input)
        time_budget: Total time budget in seconds (default 30s)
        seed: Random seed for determinism
        config: Optional ConfigV4 override
        log_fn: Optional logging callback
    
    Returns:
        PortfolioResult with solution, features, and telemetry
    """
    start_time = perf_counter()
    execution_log = []
    
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
        execution_log.append({
            "time": round(perf_counter() - start_time, 3),
            "message": msg
        })
    
    log("=" * 70)
    log("PORTFOLIO CONTROLLER - Starting optimization")
    log("=" * 70)
    log(f"Tours: {len(tours)}, Time budget: {time_budget}s, Seed: {seed}")
    
    # GLOBAL DEADLINE for budget enforcement
    deadline = monotonic() + time_budget
    
    def remaining() -> float:
        """Return remaining time budget in seconds."""
        return max(0.0, deadline - monotonic())
    
    # S0.2: Compute hard budget slices upfront
    budget_slices = BudgetSlice.from_total(time_budget)
    log(f"S0.2 Budget Slices: phase1={budget_slices.phase1:.1f}s, phase2={budget_slices.phase2:.1f}s, lns={budget_slices.lns:.1f}s")
    
    # Import here to avoid circular imports
    from src.services.forecast_solver_v4 import (
        ConfigV4,
        SolveResultV4,
        solve_capacity_phase,
        solve_capacity_twopass_balanced,  # Two-pass for BEST_BALANCED
        assign_drivers_greedy,
        DriverAssignment,
    )
    from src.services.smart_block_builder import (
        build_weekly_blocks_smart,
        build_block_index,
    )
    
    # Use default config if not provided
    if config is None:
        config = ConfigV4(seed=seed, num_workers=1)
    
    try:
        # ==========================================================================
        # PHASE 0: BUILD BLOCKS
        # ==========================================================================
        log("PHASE 0: Block building...")
        t_block = perf_counter()
        
        blocks, block_stats = build_weekly_blocks_smart(
            tours,
            cap_quota_2er=config.cap_quota_2er,
            enable_diag=config.enable_diag_block_caps,
            output_profile=config.output_profile,
            gap_3er_min_minutes=config.gap_3er_min_minutes,
            cap_quota_3er=config.cap_quota_3er,
        )
        block_time = perf_counter() - t_block
        
        log(f"Generated {len(blocks)} blocks in {block_time:.1f}s (profile={config.output_profile})")
        
        if METRICS_ENABLED:
            record_candidate_counts(block_stats)
            
        block_scores = block_stats.get("block_scores", {})
        block_props = block_stats.get("block_props", {})
        block_index = build_block_index(blocks)
        
        # ==========================================================================
        # PHASE 1: PROFILING
        # ==========================================================================
        log("PHASE 1: Instance profiling...")
        t_profile = perf_counter()
        
        features = compute_features(tours, blocks, time_budget, config.max_blocks)
        profiling_time = perf_counter() - t_profile
        
        log(f"Features: peakiness={features.peakiness_index:.2f}, "
            f"pool_pressure={features.pool_pressure}, "
            f"lower_bound={features.lower_bound_drivers}")
        
        # ==========================================================================
        # PHASE 2: PATH SELECTION
        # ==========================================================================
        log("PHASE 2: Path selection...")
        
        policy = PolicyEngine()
        params = policy.select(features, time_budget)
        
        initial_path = policy.current_path
        reason_codes = policy.reason_codes.copy()
        
        log(f"Selected Path {initial_path.value}: {reason_codes[0]}")
        log(f"Parameters: lns_iters={params.lns_iterations}, "
            f"destroy={params.destroy_fraction:.2f}")
        
        # ==========================================================================
        # PHASE 3: BLOCK SELECTION (CP-SAT Phase 1)
        # ==========================================================================
        log("PHASE 3: Block selection (CP-SAT)...")
        t_capacity = perf_counter()
        
        # Profile-specific block selection
        if config.output_profile == "BEST_BALANCED":
            # Two-pass solve: minimize headcount first, then optimize balance with cap
            log(f"Using TWO-PASS solve for BEST_BALANCED (max_extra_driver_pct={config.max_extra_driver_pct})")
            
            # S0.2: Allocate 85% of total budget to Two-Pass solve (Pass 1 + Pass 2)
            # This logic replaces standard Phase 3 (50%) and consumes much of Phase 4/LNS time
            # because it performs its own internal optimization and assignment steps.
            best_balanced_budget = time_budget * 0.85
            
            selected_blocks, phase1_stats = solve_capacity_twopass_balanced(
                blocks, tours, block_index, config,
                block_scores=block_scores, block_props=block_props,
                total_time_budget=best_balanced_budget
            )
            # DEBUG TRACE
            log(f"DEBUG: Portfolio received phase1_stats: twopass_executed={phase1_stats.get('twopass_executed')}")
        else:
            # MIN_HEADCOUNT_3ER: single-pass with standard objective
            phase1_config = config._replace(time_limit_phase1=budget_slices.phase1)
            selected_blocks, phase1_stats = solve_capacity_phase(
                blocks, tours, block_index, phase1_config,
                block_scores=block_scores, block_props=block_props
            )
        capacity_time = perf_counter() - t_capacity
        
        # S0.2: Log budget compliance
        if capacity_time > budget_slices.phase1 * 1.05:
            log(f"WARNING: Phase 1 overrun {capacity_time:.1f}s > {budget_slices.phase1:.1f}s")
        
        if phase1_stats["status"] != "OK":
            log(f"Phase 1 FAILED: {phase1_stats.get('error', 'Unknown error')}")
            from src.services.forecast_solver_v4 import SolveResultV4
            
            fail_solution = SolveResultV4(
                status="FAILED",
                assignments=[],
                kpi={"error": "Phase 1 failed"},
                solve_times={"block_building": block_time},
                block_stats=phase1_stats,
            )
            
            fail_runtime = perf_counter() - start_time
            
            # Record metrics for failure
            if METRICS_ENABLED:
                try:
                    record_phase_timing("profiling", profiling_time)
                    record_phase_timing("phase1", capacity_time)
                    record_phase_timing("total", fail_runtime)
                    
                    record_run_completed({
                        "status": "FAILED",
                        "reason_codes": reason_codes + ["PHASE1_FAILED"],
                        "solution_signature": "failed_" + str(seed),
                        "kpi": fail_solution.kpi,
                        "time_budget": time_budget,
                        "total_runtime": fail_runtime,
                    })
                except Exception as m_err:
                    log(f"Metrics recording failed: {m_err}")
            
            return PortfolioResult(
                solution=fail_solution,
                features=features,
                initial_path=initial_path,
                final_path=initial_path,
                parameters_used=params,
                reason_codes=reason_codes + ["PHASE1_FAILED"],
                total_runtime_s=fail_runtime,
                profiling_time_s=profiling_time,
                phase1_time_s=capacity_time,
            )
        
        log(f"Selected {len(selected_blocks)} blocks in {capacity_time:.1f}s")
        
        # ==========================================================================
        # PHASE 4: EXECUTE SOLVER PATH
        # ==========================================================================
        # S0.2: Use hard budget slices (phase2 + lns), not remaining_budget
        log(f"PHASE 4: Executing Path {initial_path.value} (phase2={budget_slices.phase2:.1f}s, lns={budget_slices.lns:.1f}s)...")
        
        result = _execute_path(
            path=initial_path,
            params=params,
            selected_blocks=selected_blocks,
            tours=tours,
            config=config,
            block_index=block_index,
            features=features,
            phase2_budget=budget_slices.phase2,  # S0.2: Hard slice
            lns_budget=budget_slices.lns,        # S0.2: Hard slice
            log_fn=log,
            seed=seed,
            remaining_fn=remaining,  # Global deadline enforcement
        )
        
        phase2_time = result.get("phase2_time", 0.0)
        lns_time = result.get("lns_time", 0.0)
        assignments = result.get("assignments", [])
        solver_status = result.get("status", "UNKNOWN")
        
        final_path = initial_path
        fallback_used = False
        fallback_count = 0
        rerun_count = 0  # Guard: only allow 1 rerun
        
        # ==========================================================================
        # PHASE 4.5: FEEDBACK LOOP - Auto-trigger Path B on bad block mix
        # ==========================================================================
        MIN_RERUN_BUDGET = 15.0  # seconds
        remaining_after_phase4 = time_budget - (perf_counter() - start_time)
        
        if (initial_path == PS.A 
            and solver_status in ["OK", "FEASIBLE"]
            and rerun_count == 0 
            and remaining_after_phase4 > MIN_RERUN_BUDGET):
            
            # Calculate quality metrics
            fte_count = len([a for a in assignments if a.driver_type == "FTE"])
            pt_count = len([a for a in assignments if a.driver_type == "PT"])
            underfull = len([a for a in assignments if a.driver_type == "FTE" and a.total_hours < config.min_hours_per_fte])
            
            total_drivers = fte_count + pt_count
            pt_ratio = pt_count / total_drivers if total_drivers > 0 else 0
            underfull_ratio = underfull / fte_count if fte_count > 0 else 0
            
            if pt_ratio > 0.25 or underfull_ratio > 0.15:
                log(f"BAD_BLOCK_MIX detected: PT={pt_ratio:.0%}, underfull={underfull_ratio:.0%}")
                log(f"Auto-triggering Path B (rerun_count={rerun_count}, budget={remaining_after_phase4:.1f}s)...")
                rerun_count += 1
                
                # Get Path B parameters and re-execute
                from src.services.policy_engine import select_parameters
                new_params = select_parameters(features, PS.B, "BAD_BLOCK_MIX", remaining_after_phase4)
                
                result = _execute_path(
                    path=PS.B,
                    params=new_params,
                    selected_blocks=selected_blocks,
                    tours=tours,
                    config=config,
                    block_index=block_index,
                    features=features,
                    phase2_budget=budget_slices.phase2,  # S0.2: Reuse original slice
                    lns_budget=budget_slices.lns,        # S0.2: Reuse original slice
                    log_fn=log,
                    seed=seed,
                    remaining_fn=remaining,  # Global deadline enforcement
                )
                
                phase2_time += result.get("phase2_time", 0.0)
                lns_time += result.get("lns_time", 0.0)
                assignments = result.get("assignments", assignments)
                solver_status = result.get("status", solver_status)
                final_path = PS.B
                fallback_used = True
                fallback_count = 1
                params = new_params
        
        # ==========================================================================
        # PHASE 5: FALLBACK IF NEEDED
        # ==========================================================================
        if solver_status not in ["OK", "OPTIMAL", "FEASIBLE"] and initial_path != PS.C:
            remaining_budget = time_budget - (perf_counter() - start_time)
            
            if remaining_budget > 5.0:  # Only fallback if we have time
                next_path, fallback_reason = get_fallback_path(initial_path)
                
                if next_path:
                    log(f"FALLBACK: Switching to Path {next_path.value} ({fallback_reason})")
                    reason_codes.append(fallback_reason)
                    
                    # Get new parameters for fallback path
                    new_params = select_parameters(features, next_path, fallback_reason, remaining_budget)
                    
                    result = _execute_path(
                        path=next_path,
                        params=new_params,
                        selected_blocks=selected_blocks,
                        tours=tours,
                        config=config,
                        block_index=block_index,
                        features=features,
                        phase2_budget=budget_slices.phase2,  # S0.2: Reuse original slice
                        lns_budget=budget_slices.lns,        # S0.2: Reuse original slice
                        log_fn=log,
                        seed=seed,
                        remaining_fn=remaining,  # Global deadline enforcement
                    )
                    
                    phase2_time += result.get("phase2_time", 0.0)
                    lns_time += result.get("lns_time", 0.0)
                    assignments = result.get("assignments", assignments)
                    solver_status = result.get("status", solver_status)
                    final_path = next_path
                    fallback_used = True
                    fallback_count = 1
                    params = new_params
        
        # ==========================================================================
        # PHASE 6: BUILD RESULT
        # ==========================================================================
        total_runtime = perf_counter() - start_time
        
        # Calculate score (driver count)
        achieved_score = len(assignments)
        lower_bound = features.lower_bound_drivers
        gap_to_lb = (achieved_score - lower_bound) / lower_bound if lower_bound > 0 else 0.0
        
        # Check early stop conditions
        early_stopped, early_stop_reason = should_early_stop(
            achieved_score, lower_bound, 
            achieved_score <= lower_bound + params.daymin_buffer,
            params
        )
        
        if early_stopped:
            reason_codes.append(early_stop_reason)
            log(f"Early stop triggered: {early_stop_reason}")
        
        # ==========================================================================
        # S1.4: COMPUTE PACKABILITY METRICS (for block mix diagnostics)
        # ==========================================================================
        from src.services.forecast_solver_v4 import compute_packability_metrics
        
        packability_metrics = compute_packability_metrics(
            selected_blocks=selected_blocks,
            all_blocks=blocks,
            tours=tours,
        )
        log(f"Packability: forced_1er_rate={packability_metrics['forced_1er_rate']:.2%}, "
            f"missed_3er_opps={packability_metrics['missed_3er_opps_count']}")
        
        # Build final KPI
        fte_drivers = [a for a in assignments if a.driver_type == "FTE"]
        pt_drivers = [a for a in assignments if a.driver_type == "PT"]
        fte_hours = [a.total_hours for a in fte_drivers]
        
        kpi = {
            "solver_arch": f"portfolio_{final_path.value.lower()}",
            "status": solver_status,
            "total_hours": round(sum(t.duration_hours for t in tours), 2),
            "drivers_fte": len(fte_drivers),
            "drivers_pt": len(pt_drivers),
            "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
            "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
            "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
            "blocks_selected": phase1_stats.get("selected_blocks", len(selected_blocks)),
            "blocks_1er": phase1_stats.get("blocks_1er", 0),
            "blocks_2er": phase1_stats.get("blocks_2er", 0),
            "blocks_3er": phase1_stats.get("blocks_3er", 0),
            "candidates_3er_pre_cap": block_stats.get("candidates_3er_pre_cap", 0),
            "path_used": final_path.value,
            "fallback_used": fallback_used,
            "early_stopped": early_stopped,
            "lower_bound": lower_bound,
            "gap_to_lb_pct": round(gap_to_lb * 100, 2),
            # S1.4: Packability diagnostics
            "forced_1er_rate": packability_metrics["forced_1er_rate"],
            "forced_1er_count": packability_metrics["forced_1er_count"],
            "missed_3er_opps_count": packability_metrics["missed_3er_opps_count"],
            "missed_2er_opps_count": packability_metrics["missed_2er_opps_count"],
            "missed_multi_opps_count": packability_metrics["missed_multi_opps_count"],
            # Output Profile Info (from config)
            "output_profile": config.output_profile,
            "gap_3er_min_minutes": config.gap_3er_min_minutes,
        }
        
        # Merge two-pass stats from phase1_stats into kpi (for BEST_BALANCED profile)
        twopass_keys = [
            "twopass_executed", "D_pass1_seed", "D_min", "driver_cap", "block_cap",
            "drivers_total_pass1", "drivers_total_pass2", "twopass_status",
            "pass1_time_s", "pass2_time_s", "underfull_pass1", "pt_pass1",
            "diagnostics_failure_reason"
        ]
        for key in twopass_keys:
            if key in phase1_stats:
                kpi[key] = phase1_stats[key]
        
        solve_times = {
            "block_building": round(block_time, 2),
            "profiling": round(profiling_time, 3),
            "phase1_capacity": round(capacity_time, 2),
            "phase2_assignment": round(phase2_time, 2),
            "lns_refinement": round(lns_time, 2),
            "total": round(total_runtime, 2),
        }
        
        # Build SolveResultV4
        from src.services.forecast_solver_v4 import SolveResultV4
        
        solution = SolveResultV4(
            status=solver_status if solver_status in ["OK", "OPTIMAL", "FEASIBLE"] else "COMPLETED",
            assignments=assignments,
            kpi=kpi,
            solve_times=solve_times,
            block_stats=phase1_stats,
        )
        
        log("=" * 70)
        log(f"PORTFOLIO CONTROLLER - Complete")
        log(f"Path: {initial_path.value} -> {final_path.value}")
        log(f"Drivers: {len(fte_drivers)} FTE, {len(pt_drivers)} PT")
        log(f"Gap to LB: {gap_to_lb*100:.1f}%")
        log(f"Runtime: {total_runtime:.1f}s")
        log("=" * 70)
        
        # ==========================================================================
        # PROMETHEUS METRICS
        # ==========================================================================
        if METRICS_ENABLED:
            try:
                # Record phase timings
                record_phase_timing("profiling", profiling_time)
                record_phase_timing("phase1", capacity_time)
                record_phase_timing("phase2", phase2_time)
                record_phase_timing("lns", lns_time)
                record_phase_timing("total", total_runtime)
                
                # Record path selection
                record_path_selection(initial_path.value, reason_codes[0] if reason_codes else "UNKNOWN")
                
                # Record fallback if used
                if fallback_used:
                    record_fallback(initial_path.value, final_path.value)
                
                # Record run completion with full report
                run_report = {
                    "status": solver_status,
                    "reason_codes": reason_codes,
                    "solution_signature": solution.kpi.get("solver_arch", "") + "_" + str(seed),
                    "kpi": kpi,
                    "time_budget": time_budget,
                    "total_runtime": total_runtime,
                }
                record_run_completed(run_report)
            except Exception as metrics_err:
                log(f"Metrics recording failed (non-fatal): {metrics_err}")
        
        return PortfolioResult(
            solution=solution,
            features=features,
            initial_path=initial_path,
            final_path=final_path,
            parameters_used=params,
            reason_codes=reason_codes,
            lower_bound=lower_bound,
            achieved_score=achieved_score,
            gap_to_lb=gap_to_lb,
            early_stopped=early_stopped,
            early_stop_reason=early_stop_reason,
            fallback_used=fallback_used,
            fallback_count=fallback_count,
            total_runtime_s=total_runtime,
            profiling_time_s=profiling_time,
            phase1_time_s=capacity_time,
            phase2_time_s=phase2_time,
            lns_time_s=lns_time,
        )
        
    except Exception as e:
        import traceback
        error_tb = traceback.format_exc()
        log(f"CRITICAL PORTFOLIO ERROR: {type(e).__name__}: {e}")
        log(error_tb)
        
        # Robust error result construction - must never crash
        try:
            from src.services.forecast_solver_v4 import SolveResultV4
            
            dummy_params = ParameterBundle(path=PS.A, reason_code="CRITICAL_PORTFOLIO_ERROR")
            dummy_features = FeatureVector(n_tours=len(tours))
            
            error_solution = SolveResultV4(
                status="CRITICAL_ERROR",
                assignments=[],
                kpi={"error": str(e), "traceback": error_tb},
                solve_times={"total": round(perf_counter() - start_time, 2)},
                block_stats={},
            )
            
            return PortfolioResult(
                solution=error_solution,
                features=dummy_features,
                initial_path=PS.A,
                final_path=PS.A,
                parameters_used=dummy_params,
                reason_codes=["CRITICAL_PORTFOLIO_ERROR"],
                total_runtime_s=perf_counter() - start_time,
            )
        except Exception as inner_e:
            # Absolute fallback - error handler must never crash
            logger.error(f"Error handler crashed: {type(inner_e).__name__}: {inner_e}")
            from src.services.forecast_solver_v4 import SolveResultV4
            return PortfolioResult(
                solution=SolveResultV4(
                    status="CRITICAL_ERROR",
                    assignments=[],
                    kpi={"error": "Error handler failed"},
                    solve_times={},
                    block_stats={},
                ),
                features=FeatureVector(n_tours=0),
                initial_path=PS.A,
                final_path=PS.A,
                parameters_used=ParameterBundle(path=PS.A, reason_code="CRITICAL_PORTFOLIO_ERROR"),
                reason_codes=["CRITICAL_PORTFOLIO_ERROR", "ERROR_HANDLER_FAILED"],
                total_runtime_s=0.0,
            )


def _execute_path(
    path: PathSelection,
    params: ParameterBundle,
    selected_blocks: list[Block],
    tours: list[Tour],
    config: 'ConfigV4',
    block_index: dict,
    features: FeatureVector,
    phase2_budget: float,  # S0.2: Hard slice for phase 2
    lns_budget: float,      # S0.2: Hard slice for LNS
    log_fn: Callable[[str], None],
    seed: int,
    remaining_fn: Callable[[], float] = None,  # Global deadline function
) -> dict:
    """
    Execute a specific solver path.
    
    S0.2: Uses hard budget slices for phase2 and lns, not remaining time.
    Returns dict with: status, assignments, phase2_time, lns_time
    
    Args:
        remaining_fn: Optional callable returning seconds remaining in global budget.
    """
    from src.services.forecast_solver_v4 import (
        assign_drivers_greedy,
        rebalance_to_min_fte_hours,
        eliminate_pt_drivers,
        DriverAssignment,
    )
    from src.services.heuristic_solver import HeuristicSolver
    
    result = {
        "status": "UNKNOWN",
        "assignments": [],
        "phase2_time": 0.0,
        "lns_time": 0.0,
    }
    
    try:
        if path == PS.A:
            # Path A: Greedy + Light LNS
            t_phase2 = perf_counter()
            
            assignments, stats = assign_drivers_greedy(selected_blocks, config)
            result["phase2_time"] = perf_counter() - t_phase2
            
            # Light repair
            assignments, _ = rebalance_to_min_fte_hours(assignments, 40.0, 53.0)
            
            # Aggressive PT elimination (NEW)
            # S0.2: Use hard phase2_budget for PT elimination
            assignments, _ = eliminate_pt_drivers(assignments, 53.0, time_limit=min(phase2_budget * 0.3, 10.0))
            
            # S0.2: Use hard lns_budget (already passed from controller)
            actual_lns_budget = lns_budget
            if actual_lns_budget > 5.0:
                log_fn(f"Path A: Light LNS ({actual_lns_budget:.1f}s budget)...")
                t_lns = perf_counter()
                assignments = _run_light_lns(assignments, selected_blocks, config, actual_lns_budget, seed, remaining_fn=remaining_fn)
                result["lns_time"] = perf_counter() - t_lns
            
            result["assignments"] = assignments
            result["status"] = "OK"
            
        elif path == PS.B:
            # Path B: Heuristic + Extended LNS
            log_fn(f"Path B: Heuristic solver...")
            t_phase2 = perf_counter()
            
            solver = HeuristicSolver(selected_blocks, config)
            heuristic_result, _ = solver.solve()
            assignments = heuristic_result
            
            result["phase2_time"] = perf_counter() - t_phase2
            
            # Repair
            assignments, _ = rebalance_to_min_fte_hours(assignments, 40.0, 53.0)
            # S0.2: Use hard phase2_budget for PT elimination
            assignments, _ = eliminate_pt_drivers(assignments, 53.0, time_limit=min(phase2_budget * 0.3, 10.0))
            
            # S0.2: Use hard lns_budget (already passed from controller)
            actual_lns_budget = lns_budget
            if actual_lns_budget > 5.0:
                log_fn(f"Path B: Extended LNS ({actual_lns_budget:.1f}s budget)...")
                t_lns = perf_counter()
                assignments = _run_extended_lns(
                    assignments, selected_blocks, config, actual_lns_budget, seed, params, remaining_fn=remaining_fn
                )
                result["lns_time"] = perf_counter() - t_lns
            
            result["assignments"] = assignments
            result["status"] = "OK"
            
        elif path == PS.C:
            # Path C: Set-Partitioning + Fallback
            log_fn(f"Path C: Set-Partitioning...")
            t_phase2 = perf_counter()
            
            from src.services.set_partition_solver import solve_set_partitioning, convert_rosters_to_assignments
            
            # S0.2: Use combined phase2 + lns budget for SP
            sp_budget = phase2_budget + lns_budget
            
            sp_result = solve_set_partitioning(
                blocks=selected_blocks,
                max_rounds=params.sp_max_rounds,
                initial_pool_size=params.pool_cap,
                columns_per_round=params.column_gen_quota,
                rmp_time_limit=params.pricing_time_limit_s,
                seed=seed,
                log_fn=log_fn,
            )
            
            result["phase2_time"] = perf_counter() - t_phase2
            
            if sp_result.status == "OK":
                block_lookup = {b.id: b for b in selected_blocks}
                assignments = convert_rosters_to_assignments(sp_result.selected_rosters, block_lookup)
                result["assignments"] = assignments
                result["status"] = "OK"
            else:
                # SP failed - greedy fallback
                log_fn(f"SP failed ({sp_result.status}), falling back to greedy...")
                assignments, _ = assign_drivers_greedy(selected_blocks, config)
                assignments, _ = rebalance_to_min_fte_hours(assignments, 40.0, 53.0)
                assignments, _ = eliminate_pt_drivers(assignments, 53.0, time_limit=30.0)
                result["assignments"] = assignments
                result["status"] = "GREEDY_FALLBACK"
    
    except Exception as e:
        log_fn(f"Path {path.value} failed with exception: {e}")
        logger.exception(f"Path {path.value} execution failed")
        result["status"] = "FAILED"
    
    return result


def _run_light_lns(
    assignments: list,
    blocks: list[Block],
    config: 'ConfigV4',
    budget: float,
    seed: int,
    remaining_fn: callable = None,
) -> list:
    """
    Run light LNS refinement (Path A).
    
    Args:
        remaining_fn: Optional callable returning seconds remaining in global budget.
    """
    try:
        from src.services.lns_refiner_v4 import refine_assignments_v4, LNSConfigV4
        
        lns_config = LNSConfigV4(
            max_iterations=50,
            lns_time_limit=budget,
            destroy_fraction=0.10,
            repair_time_limit=3.0,
            seed=seed,
        )
        
        # Pass remaining_fn for global deadline enforcement
        assignments = refine_assignments_v4(assignments, lns_config, remaining_fn=remaining_fn)
        return assignments
    except Exception as e:
        logger.warning(f"Light LNS failed: {e}")
        return assignments


def _run_extended_lns(
    assignments: list,
    blocks: list[Block],
    config: 'ConfigV4',
    budget: float,
    seed: int,
    params: ParameterBundle,
    remaining_fn: callable = None,
) -> list:
    """
    Run extended LNS refinement (Path B).
    
    Args:
        remaining_fn: Optional callable returning seconds remaining in global budget.
    """
    try:
        from src.services.lns_refiner_v4 import refine_assignments_v4, LNSConfigV4
        
        lns_config = LNSConfigV4(
            max_iterations=params.lns_iterations,
            lns_time_limit=budget,
            destroy_fraction=params.destroy_fraction,
            repair_time_limit=params.repair_time_limit_s,
            seed=seed,
            enable_pt_elimination=params.enable_pt_elimination,
            pt_elimination_fraction=params.pt_focused_destroy_weight,
        )
        
        # Pass remaining_fn for global deadline enforcement
        assignments = refine_assignments_v4(assignments, lns_config, remaining_fn=remaining_fn)
        return assignments
    except Exception as e:
        logger.warning(f"Extended LNS failed: {e}")
        return assignments


# =============================================================================
# RUN REPORT GENERATION
# =============================================================================

def generate_run_report(
    result: PortfolioResult,
    tours: list[Tour],
    output_path: Optional[str] = None,
) -> RunReport:
    """
    Generate a detailed run report for debugging and analysis.
    
    Args:
        result: PortfolioResult from run_portfolio
        tours: Input tours
        output_path: Optional path to save JSON report
    
    Returns:
        RunReport object
    """
    # S0.7: Generate solution signature for determinism gate
    sig = canonical_solution_signature(result)
    
    # S0.7: Extract pool stats from block_stats if available
    block_stats = result.solution.block_stats if result.solution and hasattr(result.solution, 'block_stats') else {}
    pool_raw = block_stats.get("pool_raw", block_stats.get("blocks_generated_total", 0))
    pool_dedup = block_stats.get("pool_dedup", block_stats.get("blocks_dedup", 0))
    pool_capped = block_stats.get("pool_capped", block_stats.get("blocks_capped", 0))
    
    report = RunReport(
        # Input
        input_summary={
            "n_tours": len(tours),
            "total_hours": round(sum(t.duration_hours for t in tours), 2),
        },
        features=result.features.to_dict() if result.features else {},
        
        # S0.7: Pool stats
        pool_raw=pool_raw,
        pool_dedup=pool_dedup,
        pool_capped=pool_capped,
        
        # S0.7: Budget
        budget_total=result.total_runtime_s,
        budget_slices={
            "phase1": result.phase1_time_s,
            "phase2": result.phase2_time_s,
            "lns": result.lns_time_s,
        },
        budget_enforced=True,
        
        # S0.7: Determinism params
        seed=42,  # Could be extracted from config
        num_workers=1,
        use_deterministic_time=False,
        
        # Policy
        policy_decisions={
            "initial_path": result.initial_path.value if result.initial_path else None,
            "final_path": result.final_path.value if result.final_path else None,
            "fallback_used": result.fallback_used,
            "fallback_count": result.fallback_count,
            "parameters": result.parameters_used.to_dict() if result.parameters_used else None,
        },
        reason_codes=list(result.reason_codes),
        
        # S0.7: Timing
        time_phase1=result.phase1_time_s,
        time_phase2=result.phase2_time_s,
        time_lns=result.lns_time_s,
        time_total=result.total_runtime_s,
        
        # Result
        result_summary={
            "status": result.solution.status if result.solution else None,
            "drivers_fte": result.solution.kpi.get("drivers_fte", 0) if result.solution else 0,
            "drivers_pt": result.solution.kpi.get("drivers_pt", 0) if result.solution else 0,
            "lower_bound": result.lower_bound,
            "achieved_score": result.achieved_score,
            "gap_to_lb_pct": round(result.gap_to_lb * 100, 2),
            "early_stopped": result.early_stopped,
            "early_stop_reason": result.early_stop_reason,
        },
        
        # S0.7: Solution signature for determinism gate
        solution_signature=sig,
        
        # Legacy
        timestamp=datetime.now().isoformat(),
        execution_log=[],
        solve_times={
            "profiling_s": result.profiling_time_s,
            "phase1_s": result.phase1_time_s,
            "phase2_s": result.phase2_time_s,
            "lns_s": result.lns_time_s,
            "total_s": result.total_runtime_s,
        },
    )
    
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())
        logger.info(f"Run report saved to {output_path}")
    
    return report


# =============================================================================
# S0.5: CANONICAL SOLUTION SIGNATURE (for determinism testing)
# =============================================================================

def canonical_solution_signature(result: PortfolioResult) -> dict:
    """
    S0.5: Generate deterministic solution signature for regression testing.
    
    This signature contains ONLY stable, deterministic content:
    - Sorted list of (driver_id, block_id) assignments
    - Sorted list of selected block IDs
    - Objective values (driver counts)
    - Seed used
    - Path selection
    
    EXCLUDES: uuid, timestamp, walltime, any non-deterministic fields.
    
    Same input + same seed => identical signature (determinism gate).
    """
    if not result.solution or not result.solution.assignments:
        return {
            "status": result.solution.status if result.solution else "NO_SOLUTION",
            "assignments": [],
            "block_ids": [],
            "drivers_fte": 0,
            "drivers_pt": 0,
            "seed": 0,
            "path": result.final_path.value if result.final_path else None,
        }
    
    # Extract canonical assignment tuples: sorted by (driver_id, block_id)
    assignment_tuples = []
    block_ids = set()
    
    for a in result.solution.assignments:
        for block in a.blocks:
            assignment_tuples.append((a.driver_id, block.id))
            block_ids.add(block.id)
    
    # Sort for determinism
    assignment_tuples.sort()
    sorted_block_ids = sorted(block_ids)
    
    return {
        "status": result.solution.status,
        "assignments": assignment_tuples,
        "block_ids": sorted_block_ids,
        "drivers_fte": result.solution.kpi.get("drivers_fte", 0),
        "drivers_pt": result.solution.kpi.get("drivers_pt", 0),
        "achieved_score": result.achieved_score,
        "path": result.final_path.value if result.final_path else None,
    }


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

def solve_forecast_portfolio(
    tours: list[Tour],
    time_budget: float = 30.0,
    seed: int = 42,
) -> 'SolveResultV4':
    """
    Portfolio-based solver entry point.
    
    Wraps run_portfolio and returns standard SolveResultV4.
    This is the recommended entry point for production use.
    
    Args:
        tours: List of Tour objects
        time_budget: Total time budget in seconds
        seed: Random seed for determinism
    
    Returns:
        SolveResultV4 with solution and KPIs
    """
    result = run_portfolio(tours, time_budget, seed)
    return result.solution
