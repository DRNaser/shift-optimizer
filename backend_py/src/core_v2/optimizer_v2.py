"""
Core v2 - Optimizer Engine

The main orchestrator for the Column Generation pipeline.
Uses lazy duty generation to avoid duty explosion.
"""

import time
import logging
import os
from typing import Optional

from .contracts.result import CoreV2Result, CoreV2Proof
from .pricing.spprc import SPPRCPricer
from .duty_factory import DutyFactoryTopK, DutyFactoryCaps
from .seeder import GreedyWeeklySeeder
from .adapter import Adapter

logger = logging.getLogger("OptimizerCoreV2")


def check_highspy_availability():
    """Fail hard if highspy is missing."""
    import importlib.util
    if importlib.util.find_spec("highspy") is None:
        raise ImportError(
            "CRITICAL: 'highspy' not installed. "
            "Optimizer Mode v2 (or Shadow Mode) requires the HiGHS solver. "
            "Please run: pip install highspy"
        )


class OptimizerCoreV2:
    """
    Column Generation Optimizer.
    
    Returns strictly typed CoreV2Result (never dict).
    Uses lazy duty generation to handle large instances.
    """
    
    def solve(self, 
             tours: list, 
             config: dict, 
             run_id: str = "v2_run") -> CoreV2Result:
        """
        Main entry point.
        
        Args:
            tours: List of TourV2 objects
            config: Configuration dict
            run_id: Unique run identifier
            
        Returns:
            CoreV2Result (never dict, strictly typed)
        """
        # Strict Dependency Check FIRST
        check_highspy_availability()
        
        # Lazy imports to avoid top-level highspy dependency
        from .run.manifest import RunContext
        from .pool.store import ColumnPoolStore
        from .master.master_lp import MasterLP
        from .master.master_mip import MasterMIP
        from .model.column import ColumnV2
        from .validator.rules import ValidatorV2
        
        logs = []
        
        def log(msg: str, level: int = logging.INFO):
            logger.log(level, msg)
            logs.append(msg)
        
        # 0. Initialize Context
        artifacts_dir = config.get("artifacts_dir", ".")
        ctx = RunContext.create(run_id, tours, config, artifacts_dir)
        log(f"Starting Core v2 Optimization for {len(tours)} tours. Category: {ctx.manifest.week_category.name}")
        
        start_time = time.time()
        
        # Initialize proof tracking
        proof = CoreV2Proof(total_tours=len(tours))
        
        # Extract duty caps from config
        duty_caps_config = config.get("duty_caps", {})
        duty_caps = DutyFactoryCaps(
            max_multi_duties_per_day=duty_caps_config.get("max_multi_duties_per_day", 50_000),
            top_m_start_tours=duty_caps_config.get("top_m_start_tours", 200),
            max_succ_per_tour=duty_caps_config.get("max_succ_per_tour", 20),
            max_triples_per_tour=duty_caps_config.get("max_triples_per_tour", 5),
        )
        
        # Telemetry accumulator
        telemetry = {
            "duty_counts_by_day": {},
            "cg_iterations": 0,
            "new_cols_added_total": 0,
        }
        
        try:
            # 1. Group tours by day (NO duty enumeration yet!)
            t0 = time.time()
            tours_by_day: dict[int, list] = {}
            for t in tours:
                tours_by_day.setdefault(t.day, []).append(t)
            
            log(f"Grouped {len(tours)} tours across {len(tours_by_day)} days")
            
            ctx.add_timing("tour_grouping", time.time() - t0)
            
            # 2. Create lazy duty factory (no enumeration yet)
            duty_factory = DutyFactoryTopK(tours_by_day, ValidatorV2)
            log("Duty factory initialized (lazy - no enumeration yet)")
            
            # 3. Generate seed columns via greedy seeder
            t0 = time.time()
            target_seeds = config.get("target_seed_columns", 5000)
            seeder = GreedyWeeklySeeder(tours_by_day, target_seeds, ValidatorV2)
            
            pool = ColumnPoolStore()
            seed_cols = seeder.generate_seeds()
            pool.add_all(seed_cols)
            
            ctx.add_timing("seeding", time.time() - t0)
            log(f"Seeded pool with {pool.size} columns (target={target_seeds})")
            
            # 4. Column Generation Loop
            all_tour_ids = sorted([t.tour_id for t in tours])
            
            pricer = SPPRCPricer(duty_factory, ctx.manifest.week_category, duty_caps)
            pricer.pricing_time_limit = config.get("pricing_time_limit_sec", 3.0)
            
            max_iter = config.get("max_cg_iterations", 30)
            lp_time_limit = config.get("lp_time_limit", 10.0)
            max_new_cols = config.get("max_new_cols_per_iter", 1500)
            
            log(f"Starting CG loop (max {max_iter} iterations, LP limit {lp_time_limit}s)")
            
            cg_start = time.time()
            converged = False
            artificial_lp_max = 0
            
            # STATE: Dual Governor
            current_duals = {}
            last_optimal_duals = {}
            stale_duals_age = 0  # Number of iters using stale duals
            
            # STATE: Stop Conditions
            no_new_cols_iters = 0
            pool_stagnation_iters = 0 # dedupe high + low added
            incumbent_stagnation_iters = 0
            
            # STATE: Incumbent
            best_incumbent_drivers = 9999
            
            for iteration in range(1, max_iter + 1):
                iter_start = time.time()
                iter_log = {"iteration": iteration}
                
                # a. Solve Master LP
                master_lp = MasterLP(pool.columns, all_tour_ids)
                master_lp.build(ctx.manifest.week_category)
                lp_res = master_lp.solve(time_limit=lp_time_limit)
                
                lp_status = lp_res["status"]
                lp_obj = lp_res.get("objective", 0.0)
                artificial_lp = lp_res.get("artificial_used", 0)
                artificial_lp_max = max(artificial_lp_max, artificial_lp)
                
                # --- Dual Governor ---
                duals_source = "none"
                skip_pricing = False
                
                # Dual Health Stats
                dual_stats = {"count": 0, "nnz": 0, "min": 0.0, "max": 0.0, "mean": 0.0}
                
                if lp_status == "Optimal":
                    current_duals = lp_res["duals"]
                    last_optimal_duals = current_duals.copy()
                    duals_source = "fresh"
                    stale_duals_age = 0
                    
                    # Compute Dual Health
                    d_values = list(current_duals.values())
                    dual_stats["count"] = len(d_values)
                    dual_stats["nnz"] = sum(1 for d in d_values if abs(d) > 1e-6)
                    dual_stats["min"] = min(d_values) if d_values else 0.0
                    dual_stats["max"] = max(d_values) if d_values else 0.0
                    dual_stats["mean"] = sum(d_values) / len(d_values) if d_values else 0.0
                    
                elif lp_status == "Time limit reached" and lp_res.get("objective") is not None:
                    # Feasible but timeout - Reuse stale if available
                    if last_optimal_duals:
                        current_duals = last_optimal_duals
                        duals_source = "stale"
                        stale_duals_age += 1
                        log(f"Iter {iteration}: LP Timeout (Feasible). Using STALE duals (age={stale_duals_age}).", level=logging.WARNING)
                    else:
                        # No duals to proceed
                        log(f"FAIL: LP Timeout on Iter {iteration} and NO previous optimal duals.", level=logging.ERROR)
                        return self._fail_result(ctx, "LP_NEVER_OPTIMAL", "LP Timeout and no duals", logs, proof, telemetry)
                else:
                    # Infeasible or Error
                    log(f"FAIL: LP Status {lp_status} at Iter {iteration}.", level=logging.ERROR)
                    return self._fail_result(ctx, "LP_FAIL", f"LP Status: {lp_status}", logs, proof, telemetry)
                
                # Check Stale Limit
                if stale_duals_age > 3:
                    log(f"Iter {iteration}: Stale duals limit exceeded (age={stale_duals_age}). Skipping Pricing.", level=logging.WARNING)
                    skip_pricing = True
                
                # --- b. Restricted MIP (Incumbent Check) ---
                # Every 5 iterations (or first/last), run a quick MIP
                incumbent_drivers = None
                mip_start = time.time()
                
                if iteration % 5 == 0 or iteration == 1:
                    # Subset Selection: Elite (Best Cost) + Newest
                    mip_subset_cap = config.get("restricted_mip_var_cap", 20_000)
                    
                    # Sort by cost (Elite)
                    sorted_by_cost = sorted(pool.columns, key=lambda c: c.cost_utilization(ctx.manifest.week_category))
                    
                    # Take top 80% capacity as Elite, 20% as Newest (from back of pool)
                    elite_count = int(mip_subset_cap * 0.8)
                    newest_count = mip_subset_cap - elite_count
                    
                    subset_cols = sorted_by_cost[:elite_count]
                    
                    # Add newest (that are not already in elite)
                    # Note: pool.columns is insertion ordered (newest at end)
                    all_cols_list = pool.columns
                    limit_idx = len(all_cols_list)
                    added_new = 0
                    for i in range(limit_idx - 1, -1, -1):
                        if added_new >= newest_count: break
                        col = all_cols_list[i]
                        if col not in subset_cols:
                            subset_cols.append(col)
                            added_new += 1
                            
                    sub_mip = MasterMIP(subset_cols, all_tour_ids)
                    mip_tl = config.get("restricted_mip_time_limit", 15.0)
                    sub_res = sub_mip.solve_lexico(ctx.manifest.week_category, time_limit=mip_tl)
                    
                    iter_log["mip_status"] = sub_res["status"]
                    iter_log["mip_time"] = time.time() - mip_start
                    
                    if sub_res["status"] == "OPTIMAL":
                        sel_cols = sub_res["selected_columns"]
                        incumbent_drivers = len(sel_cols)
                        iter_log["incumbent_drivers"] = incumbent_drivers
                        
                        # Incumbent KPIs
                        hours = [c.hours for c in sel_cols]
                        days = [c.days_worked for c in sel_cols]
                        
                        iter_log["avg_hours"] = sum(hours) / len(hours) if hours else 0
                        iter_log["pct_under_30"] = (sum(1 for h in hours if h < 30) / len(hours) * 100) if hours else 0
                        iter_log["pct_under_20"] = (sum(1 for h in hours if h < 20) / len(hours) * 100) if hours else 0
                        
                        # Histogram: Days Worked
                        hist_days = {}
                        for d in days:
                            hist_days[d] = hist_days.get(d, 0) + 1
                        iter_log["selected_days_worked_hist"] = dict(sorted(hist_days.items()))
                        
                        # Incumbent Stagnation Check
                        if incumbent_drivers < best_incumbent_drivers:
                            best_incumbent_drivers = incumbent_drivers
                            incumbent_stagnation_iters = 0
                        else:
                            incumbent_stagnation_iters += 1
                        
                        log(f"  [MIP] Incumbent: {incumbent_drivers} drivers, Avg={iter_log['avg_hours']:.1f}h, Hist={iter_log['selected_days_worked_hist']}")

                # --- c. Pricing ---
                new_cols = []
                added_count = 0
                if not skip_pricing:
                    try:
                        new_cols = pricer.price(current_duals, max_new_cols=max_new_cols)
                        added_count = pool.add_all(new_cols)
                        telemetry["new_cols_added_total"] += added_count
                    except RuntimeError as e:
                        return self._fail_result(ctx, "FAIL_FAST_DUTY_CAP", str(e), logs, proof, telemetry)
                
                # --- d. Telemetry & Checkpointing ---
                iter_time = time.time() - iter_start
                pool_size = pool.size
                dedupe_rate = 1.0 - (added_count / len(new_cols)) if new_cols else 0.0
                
                log(
                    f"Iter {iteration}: LP_Obj={lp_obj:.1f} ({lp_status}), "
                    f"Duals={duals_source} (NNZ={dual_stats['nnz']}), "
                    f"Cols={len(new_cols)} (Added={added_count}), "
                    f"Pool={pool_size}, "
                    f"Incumbent={incumbent_drivers if incumbent_drivers else 'N/A'}, "
                    f"Time={iter_time:.1f}s"
                )
                
                # Checkpoint Manifest
                iter_log.update({
                    "lp_obj": lp_obj,
                    "lp_status": lp_status,
                    "duals_source": duals_source,
                    "dual_stats": dual_stats,
                    "new_cols": len(new_cols),
                    "added_count": added_count,
                    "pool_size": pool_size,
                    "stale_age": stale_duals_age,
                    "stop_counters": {
                        "no_new_cols": no_new_cols_iters,
                        "pool_stagnation": pool_stagnation_iters,
                        "incumbent_stagnation": incumbent_stagnation_iters
                    }
                })
                ctx.save_snapshot(f"cg_iter_{iteration}", iter_log)

                # --- e. Stop Rules ---
                stop_reason = ""
                
                # 1. No New Columns (Converged)
                if len(new_cols) == 0 and not skip_pricing:
                    no_new_cols_iters += 1
                else:
                    no_new_cols_iters = 0
                    
                if no_new_cols_iters >= 3:
                     stop_reason = "CG_CONVERGED_NO_NEW_COLS"
                
                # 2. Pool Stagnation (High Dedupe, Low Added)
                if dedupe_rate > 0.95 and added_count < 50:
                    pool_stagnation_iters += 1
                else:
                    pool_stagnation_iters = 0
                
                if pool_stagnation_iters >= 3:
                    stop_reason = "POOL_STAGNATION"
                    
                # 3. Incumbent Stagnation
                if incumbent_stagnation_iters >= 5:
                    # Only stop if we are deeper in loops, not at start
                    if iteration > 10: 
                        stop_reason = "INCUMBENT_STAGNATION"
                
                if stop_reason:
                    log(f"STOPPING: {stop_reason}")
                    converged = True
                    break
            
            telemetry["cg_iterations"] = iteration
            ctx.add_timing("cg_loop", time.time() - cg_start)
            proof.artificial_used_lp = artificial_lp_max
            
            # 5. Final MIP
            t0 = time.time()
            log(f"Starting Final MIP Solve (pool size={pool.size})...")
            master_mip = MasterMIP(pool.columns, all_tour_ids)
            mip_res = master_mip.solve_lexico(
                ctx.manifest.week_category,
                time_limit=config.get("mip_time_limit", 300.0)
            )
            ctx.add_timing("final_mip", time.time() - t0)
            
            total_time = time.time() - start_time
            
            if mip_res["status"] == "OPTIMAL":
                selected_columns: list[ColumnV2] = mip_res["selected_columns"]
                log(f"MIP Optimal! Selected {len(selected_columns)} rosters. Obj={mip_res['objective']:.2f}")
                
                # Check for artificial columns in final solution
                artificial_final = sum(1 for c in selected_columns if c.origin.startswith("artificial"))
                proof.artificial_used_final = artificial_final
                
                if artificial_final > 0:
                    return self._fail_result(ctx, "ARTIFICIAL_USED", f"{artificial_final} artificials in final", logs, proof, telemetry)
                
                # Duplicate tour coverage guard (should be impossible under exact cover)
                tour_counts: dict[str, int] = {}
                for col in selected_columns:
                    for tour_id in col.covered_tour_ids:
                        tour_counts[tour_id] = tour_counts.get(tour_id, 0) + 1
                duplicate_tours = [t for t, count in tour_counts.items() if count > 1]
                if duplicate_tours:
                    sample = ", ".join(sorted(duplicate_tours)[:5])
                    return self._fail_result(
                        ctx,
                        "DUPLICATE_TOUR_COVERAGE",
                        f"{len(duplicate_tours)} tours duplicated in final solution (sample: {sample})",
                        logs,
                        proof,
                        telemetry,
                    )

                # Coverage check
                covered_tours = set()
                for col in selected_columns:
                    covered_tours.update(col.covered_tour_ids)
                
                proof.covered_tours = len(covered_tours)
                proof.coverage_pct = (len(covered_tours) / len(all_tour_ids)) * 100 if all_tour_ids else 100.0
                proof.mip_gap = mip_res.get("mip_gap", 0.0)
                
                solution = self._columns_to_assignments(selected_columns)
                kpis = self._build_kpis(solution, total_time, mip_res["objective"], telemetry, converged, pool)
                
                return CoreV2Result(
                    status="SUCCESS",
                    run_id=ctx.manifest.run_id,
                    error_code="",
                    error_message="",
                    week_type=ctx.manifest.week_category.name,
                    active_days=ctx.manifest.active_days_count,
                    solution=solution,
                    kpis=kpis,
                    proof=proof,
                    artifacts_dir=ctx.artifact_dir,
                    logs=logs,
                    _debug_columns=selected_columns,
                )
            else:
                return self._fail_result(ctx, "MIP_FAILED", mip_res["status"], logs, proof, telemetry)
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log(f"EXCEPTION: {e}\n{tb}", level=logging.ERROR)
            return self._fail_result(ctx, "EXCEPTION", str(e), logs, proof, telemetry)

    def _fail_result(self, ctx, code, msg, logs, proof, telemetry):
        """Helper to return failure result."""
        return CoreV2Result(
            status="FAIL",
            run_id=ctx.manifest.run_id,
            error_code=code,
            error_message=msg,
            week_type="UNKNOWN",
            active_days=0,
            solution=[],
            kpis={"error": msg, "duty_counts": telemetry.get("duty_counts_by_day")},
            proof=proof,
            artifacts_dir=ctx.artifact_dir,
            logs=logs,
        )

    def _build_kpis(self, solution, total_time, mip_obj, telemetry, converged, pool):
        """Helper to build KPI dict."""
        fte_drivers = [a for a in solution if a.driver_type == "FTE"]
        pt_drivers = [a for a in solution if a.driver_type == "PT"]
        fte_hours = [a.total_hours for a in fte_drivers]
        all_hours = [a.total_hours for a in solution]
        
        # Selected Days Hist
        selected_days_hist = {}
        for a in solution:
            d = a.days_worked
            selected_days_hist[d] = selected_days_hist.get(d, 0) + 1
            
        # Pool Days Hist
        pool_days_hist = {}
        for c in pool.columns:
            d = c.days_worked
            pool_days_hist[d] = pool_days_hist.get(d, 0) + 1
        
        return {
            "total_time": total_time,
            "mip_obj": mip_obj,
            "drivers_total": len(solution),
            "drivers_fte": len(fte_drivers),
            "drivers_pt": len(pt_drivers),
            "pt_share_pct": (len(pt_drivers) / max(1, len(solution))) * 100,
            "fte_hours_min": min(fte_hours) if fte_hours else 0,
            "fte_hours_max": max(fte_hours) if fte_hours else 0,
            "fte_hours_avg": sum(fte_hours) / max(1, len(fte_hours)) if fte_hours else 0,
            "pct_under_30": (sum(1 for h in all_hours if h < 30) / len(all_hours) * 100) if all_hours else 0,
            "pct_under_20": (sum(1 for h in all_hours if h < 20) / len(all_hours) * 100) if all_hours else 0,
            "avg_hours": sum(all_hours) / len(all_hours) if all_hours else 0,
            "pool_final_size": pool.size,
            "selected_days_worked_hist": dict(sorted(selected_days_hist.items())),
            "pool_days_worked_hist": dict(sorted(pool_days_hist.items())),
            "cg_iterations": telemetry["cg_iterations"],
            "new_cols_added_total": telemetry["new_cols_added_total"],
            "converged": converged,
        }
    
    def _columns_to_assignments(self, columns: list) -> list:
        """Convert ColumnV2 list to DriverAssignment list (v1-compatible)."""
        from src.services.forecast_solver_v4 import DriverAssignment
        from src.domain.models import Weekday
        from datetime import time
        from dataclasses import dataclass
        
        DAY_MAP = {
            0: Weekday.MONDAY,
            1: Weekday.TUESDAY,
            2: Weekday.WEDNESDAY,
            3: Weekday.THURSDAY,
            4: Weekday.FRIDAY,
            5: Weekday.SATURDAY,
            6: Weekday.SUNDAY,
        }
        
        @dataclass
        class PseudoBlock:
            """Lightweight block for v2→v1 conversion."""
            id: str
            day: Weekday
            tours: list
            total_work_hours: float
            first_start: time
            last_end: time
            
            @property
            def total_work_minutes(self) -> int:
                return int(self.total_work_hours * 60)
        
        assignments = []
        for i, col in enumerate(columns):
            blocks = []
            for duty in col.duties:
                weekday = DAY_MAP.get(duty.day, Weekday.MONDAY)
                start_h, start_m = divmod(duty.start_min, 60)
                end_h, end_m = divmod(duty.end_min % 1440, 60)
                
                block = PseudoBlock(
                    id=duty.duty_id,
                    day=weekday,
                    tours=list(duty.tour_ids),
                    total_work_hours=duty.work_min / 60.0,
                    first_start=time(min(start_h, 23), start_m),
                    last_end=time(min(end_h, 23), end_m),
                )
                blocks.append(block)
            
            hours = col.hours
            driver_type = "FTE" if hours >= 40.0 else "PT"
            driver_id = f"V2_{driver_type}{i+1:03d}"
            
            assignment = DriverAssignment(
                driver_id=driver_id,
                driver_type=driver_type,
                blocks=blocks,
                total_hours=hours,
                days_worked=col.days_worked,
            )
            assignments.append(assignment)
        
        return assignments
