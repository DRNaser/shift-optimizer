"""
Core v2 - Optimizer Engine

The main orchestrator for the Column Generation pipeline.
Uses lazy duty generation to avoid duty explosion.
"""

import time
import logging
import os
import json
import subprocess
from typing import Optional

from .contracts.result import CoreV2Result, CoreV2Proof
from .pricing.spprc import SPPRCPricer
from .duty_factory import DutyFactoryTopK, DutyFactoryCaps
from .seeder import GreedyWeeklySeeder
from .adapter import Adapter
from .guards import (
    run_post_seed_guards,
    run_pre_mip_guards,
    run_post_solve_guards,
    OutputContractGuard,
)

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
        os.makedirs(ctx.artifact_dir, exist_ok=True)
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

        cg_telemetry = {
            "generated_cols_hist": [],
            "deduped_cols_hist": [],
            "kept_cols_hist": [],
            "unique_ratio_hist": [],
            "best_rc_hist": [],
            "lp_obj_hist": [],
            "duals_stale_hist": [],
            "lp_hit_time_limit_hist": [],
            "lp_time_limit_hist": [],
            "profile_hist": [],
            "lp_runtime_hist": [],
        }
        stop_reason = ""
        
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
            pool_size_after_seed = pool.size

            try:
                run_post_seed_guards(pool.columns, set([t.tour_id for t in tours]))
            except AssertionError as exc:
                log(f"GUARD FAILURE POST-SEED: {exc}", level=logging.ERROR)
                self._write_run_manifest(
                    ctx=ctx,
                    manifest_path=os.path.join(ctx.artifact_dir, "run_manifest.json"),
                    status="FAIL",
                    seed=config.get("seed"),
                    config_snapshot=config,
                    stop_reason="GUARD_FAIL_POST_SEED",
                    coverage_exact_once=False,
                    drivers_total=0,
                    avg_days_per_driver=0.0,
                    tours_per_driver=0.0,
                    fleet_peak=self._compute_fleet_peak(tours),
                    wall_time=0.0,
                    lp_times=cg_telemetry["lp_runtime_hist"],
                    mip_time=0.0,
                    cg_iters=0,
                    pool_size_after_seed=pool_size_after_seed,
                    pool_size_final=pool.size,
                    added_cols_hist=cg_telemetry["kept_cols_hist"],
                    profile_hist=cg_telemetry["profile_hist"],
                    best_rc_hist=cg_telemetry["best_rc_hist"],
                    duals_stale_hist=cg_telemetry["duals_stale_hist"],
                    dedupe_hist={
                        "generated_cols": cg_telemetry["generated_cols_hist"],
                        "deduped_cols": cg_telemetry["deduped_cols_hist"],
                        "kept_cols": cg_telemetry["kept_cols_hist"],
                        "unique_ratio": cg_telemetry["unique_ratio_hist"],
                    },
                    repairs_applied=[],
                )
                return self._fail_result(
                    ctx,
                    "GUARD_FAIL_POST_SEED",
                    str(exc),
                    logs,
                    proof,
                    telemetry,
                )
            
            # 4. Column Generation Loop
            all_tour_ids = sorted([t.tour_id for t in tours])
            
            pricer = SPPRCPricer(duty_factory, ctx.manifest.week_category, duty_caps)
            pricer.pricing_time_limit = config.get("pricing_time_limit_sec", 3.0)
            
            max_iter = config.get("max_cg_iterations", 30)
            lp_time_limit = config.get("lp_time_limit", 10.0)
            lp_time_limit_max = config.get("lp_time_limit_max", 90.0)
            lp_time_limit_stall_min = config.get("lp_time_limit_stall_min", 45.0)
            lp_time_limit_threshold = config.get("lp_time_limit_threshold", 20_000)
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
            stall_count = 0
            
            for iteration in range(1, max_iter + 1):
                iter_start = time.time()
                iter_log = {"iteration": iteration}
                
                # a. Solve Master LP
                master_lp = MasterLP(pool.columns, all_tour_ids)
                master_lp.build(ctx.manifest.week_category)
                if pool.size >= lp_time_limit_threshold and lp_time_limit < lp_time_limit_max:
                    lp_time_limit = min(lp_time_limit * 2, lp_time_limit_max)

                lp_res = master_lp.solve(time_limit=lp_time_limit)
                cg_telemetry["lp_time_limit_hist"].append(lp_time_limit)
                cg_telemetry["lp_runtime_hist"].append(lp_res.get("runtime", 0.0))
                cg_telemetry["lp_hit_time_limit_hist"].append(lp_res.get("hit_time_limit", False))

                if lp_res.get("duals_stale"):
                    if lp_time_limit < lp_time_limit_max:
                        lp_time_limit = min(lp_time_limit * 2, lp_time_limit_max)
                        lp_res = master_lp.solve(time_limit=lp_time_limit)
                        cg_telemetry["lp_time_limit_hist"].append(lp_time_limit)
                        cg_telemetry["lp_runtime_hist"].append(lp_res.get("runtime", 0.0))
                        cg_telemetry["lp_hit_time_limit_hist"].append(lp_res.get("hit_time_limit", False))
                
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
                unique_ratio = (added_count / len(new_cols)) if new_cols else 0.0
                deduped_count = max(0, len(new_cols) - added_count)

                cg_telemetry["generated_cols_hist"].append(len(new_cols))
                cg_telemetry["deduped_cols_hist"].append(deduped_count)
                cg_telemetry["kept_cols_hist"].append(added_count)
                cg_telemetry["unique_ratio_hist"].append(unique_ratio)
                cg_telemetry["best_rc_hist"].append(pricer.rc_telemetry.best_rc_total)
                cg_telemetry["duals_stale_hist"].append(lp_res.get("duals_stale", False))
                cg_telemetry["lp_obj_hist"].append(lp_obj)

                if unique_ratio < 0.6 and len(new_cols) > 0:
                    log(
                        f"Iter {iteration}: low unique_ratio={unique_ratio:.2f} "
                        f"(generated={len(new_cols)}, deduped={deduped_count})",
                        level=logging.WARNING,
                    )
                
                log(
                    f"Iter {iteration}: LP_Obj={lp_obj:.1f} ({lp_status}), "
                    f"Duals={duals_source} (NNZ={dual_stats['nnz']}), "
                    f"Cols={len(new_cols)} (Added={added_count}), "
                    f"Pool={pool_size}, "
                    f"Incumbent={incumbent_drivers if incumbent_drivers else 'N/A'}, "
                    f"Time={iter_time:.1f}s"
                )

                # --- f. Stall Detection (duals fresh only) ---
                best_rc = pricer.rc_telemetry.best_rc_total
                duals_stale = lp_res.get("duals_stale", False)
                is_stalled = ((added_count == 0) or (best_rc >= -1e-5)) and not duals_stale
                if is_stalled:
                    stall_count += 1
                else:
                    stall_count = 0

                profile = "STALL" if stall_count >= 2 else "NORMAL"
                cg_telemetry["profile_hist"].append(profile)
                if stall_count >= 2:
                    lp_time_limit = max(lp_time_limit, lp_time_limit_stall_min)
                
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
            if not stop_reason and iteration >= max_iter:
                stop_reason = "MAX_ITERS"
            ctx.add_timing("cg_loop", time.time() - cg_start)
            proof.artificial_used_lp = artificial_lp_max
            
            # 5. Final MIP
            t0 = time.time()
            log(f"Starting Final MIP Solve (pool size={pool.size})...")
            try:
                run_pre_mip_guards(pool.columns, set(all_tour_ids))
            except AssertionError as exc:
                log(f"GUARD FAILURE PRE-MIP: {exc}", level=logging.ERROR)
                self._write_run_manifest(
                    ctx=ctx,
                    manifest_path=os.path.join(ctx.artifact_dir, "run_manifest.json"),
                    status="FAIL",
                    seed=config.get("seed"),
                    config_snapshot=config,
                    stop_reason="GUARD_FAIL_PRE_MIP",
                    coverage_exact_once=False,
                    drivers_total=0,
                    avg_days_per_driver=0.0,
                    tours_per_driver=0.0,
                    fleet_peak=self._compute_fleet_peak(tours),
                    wall_time=time.time() - start_time,
                    lp_times=cg_telemetry["lp_runtime_hist"],
                    mip_time=0.0,
                    cg_iters=telemetry["cg_iterations"],
                    pool_size_after_seed=pool_size_after_seed,
                    pool_size_final=pool.size,
                    added_cols_hist=cg_telemetry["kept_cols_hist"],
                    profile_hist=cg_telemetry["profile_hist"],
                    best_rc_hist=cg_telemetry["best_rc_hist"],
                    duals_stale_hist=cg_telemetry["duals_stale_hist"],
                    dedupe_hist={
                        "generated_cols": cg_telemetry["generated_cols_hist"],
                        "deduped_cols": cg_telemetry["deduped_cols_hist"],
                        "kept_cols": cg_telemetry["kept_cols_hist"],
                        "unique_ratio": cg_telemetry["unique_ratio_hist"],
                    },
                    repairs_applied=[],
                )
                return self._fail_result(
                    ctx,
                    "GUARD_FAIL_PRE_MIP",
                    str(exc),
                    logs,
                    proof,
                    telemetry,
                )
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
                
                # Coverage check
                covered_tours = set()
                for col in selected_columns:
                    covered_tours.update(col.covered_tour_ids)
                
                proof.covered_tours = len(covered_tours)
                proof.coverage_pct = (len(covered_tours) / len(all_tour_ids)) * 100 if all_tour_ids else 100.0
                proof.mip_gap = mip_res.get("mip_gap", 0.0)

                try:
                    run_post_solve_guards(selected_columns)
                except AssertionError as exc:
                    log(f"GUARD FAILURE POST-SOLVE: {exc}", level=logging.ERROR)
                    self._write_run_manifest(
                        ctx=ctx,
                        manifest_path=os.path.join(ctx.artifact_dir, "run_manifest.json"),
                        status="FAIL",
                        seed=config.get("seed"),
                        config_snapshot=config,
                        stop_reason="GUARD_FAIL_POST_SOLVE",
                        coverage_exact_once=False,
                        drivers_total=0,
                        avg_days_per_driver=0.0,
                        tours_per_driver=0.0,
                        fleet_peak=self._compute_fleet_peak(tours),
                        wall_time=time.time() - start_time,
                        lp_times=cg_telemetry["lp_runtime_hist"],
                        mip_time=ctx.timings.get("final_mip", 0.0),
                        cg_iters=telemetry["cg_iterations"],
                        pool_size_after_seed=pool_size_after_seed,
                        pool_size_final=pool.size,
                        added_cols_hist=cg_telemetry["kept_cols_hist"],
                        profile_hist=cg_telemetry["profile_hist"],
                        best_rc_hist=cg_telemetry["best_rc_hist"],
                        duals_stale_hist=cg_telemetry["duals_stale_hist"],
                        dedupe_hist={
                            "generated_cols": cg_telemetry["generated_cols_hist"],
                            "deduped_cols": cg_telemetry["deduped_cols_hist"],
                            "kept_cols": cg_telemetry["kept_cols_hist"],
                            "unique_ratio": cg_telemetry["unique_ratio_hist"],
                        },
                        repairs_applied=[],
                    )
                    return self._fail_result(
                        ctx,
                        "GUARD_FAIL_POST_SOLVE",
                        str(exc),
                        logs,
                        proof,
                        telemetry,
                    )
                
                solution = self._columns_to_assignments(selected_columns)
                kpis = self._build_kpis(
                    solution,
                    selected_columns,
                    total_time,
                    mip_res["objective"],
                    telemetry,
                    converged,
                    pool,
                )

                coverage_exact_once = self._check_exact_once(selected_columns, all_tour_ids)
                selected_day_mix = self._day_mix(selected_columns)
                pool_day_mix = self._day_mix(pool.columns)
                avg_days_per_driver = (
                    sum(c.days_worked for c in selected_columns) / len(selected_columns)
                    if selected_columns
                    else 0.0
                )
                tours_per_driver = (
                    sum(len(c.covered_tour_ids) for c in selected_columns) / len(selected_columns)
                    if selected_columns
                    else 0.0
                )
                fleet_peak = self._compute_fleet_peak(tours)

                manifest_path = os.path.join(ctx.artifact_dir, "run_manifest.json")
                roster_path = os.path.join(ctx.artifact_dir, "roster.csv")
                self._export_roster_csv(selected_columns, roster_path)
                self._write_run_manifest(
                    ctx=ctx,
                    manifest_path=manifest_path,
                    status="SUCCESS",
                    seed=config.get("seed"),
                    config_snapshot=config,
                    stop_reason=stop_reason or "SUCCESS",
                    coverage_exact_once=coverage_exact_once,
                    drivers_total=len(selected_columns),
                    avg_days_per_driver=avg_days_per_driver,
                    tours_per_driver=tours_per_driver,
                    fleet_peak=fleet_peak,
                    wall_time=total_time,
                    lp_times=cg_telemetry["lp_runtime_hist"],
                    mip_time=ctx.timings.get("final_mip", 0.0),
                    cg_iters=telemetry["cg_iterations"],
                    pool_size_after_seed=pool_size_after_seed,
                    pool_size_final=pool.size,
                    added_cols_hist=cg_telemetry["kept_cols_hist"],
                    pool_day_mix=pool_day_mix,
                    selected_day_mix=selected_day_mix,
                    profile_hist=cg_telemetry["profile_hist"],
                    best_rc_hist=cg_telemetry["best_rc_hist"],
                    duals_stale_hist=cg_telemetry["duals_stale_hist"],
                    lp_hit_time_limit_hist=cg_telemetry["lp_hit_time_limit_hist"],
                    lp_obj_hist=cg_telemetry["lp_obj_hist"],
                    lp_time_limit_hist=cg_telemetry["lp_time_limit_hist"],
                    dedupe_hist={
                        "generated_cols": cg_telemetry["generated_cols_hist"],
                        "deduped_cols": cg_telemetry["deduped_cols_hist"],
                        "kept_cols": cg_telemetry["kept_cols_hist"],
                        "unique_ratio": cg_telemetry["unique_ratio_hist"],
                    },
                    repairs_applied=[],
                )

                OutputContractGuard.validate(
                    manifest_path,
                    roster_path,
                    expected_tour_ids=set(all_tour_ids),
                    strict=True,
                )
                
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
                self._write_run_manifest(
                    ctx=ctx,
                    manifest_path=os.path.join(ctx.artifact_dir, "run_manifest.json"),
                    status="FAIL",
                    seed=config.get("seed"),
                    config_snapshot=config,
                    stop_reason=mip_res["status"],
                    coverage_exact_once=False,
                    drivers_total=0,
                    avg_days_per_driver=0.0,
                    tours_per_driver=0.0,
                    fleet_peak=self._compute_fleet_peak(tours),
                    wall_time=total_time,
                    lp_times=cg_telemetry["lp_runtime_hist"],
                    mip_time=ctx.timings.get("final_mip", 0.0),
                    cg_iters=telemetry["cg_iterations"],
                    pool_size_after_seed=pool_size_after_seed,
                    pool_size_final=pool.size,
                    added_cols_hist=cg_telemetry["kept_cols_hist"],
                    pool_day_mix=self._day_mix(pool.columns),
                    selected_day_mix={},
                    profile_hist=cg_telemetry["profile_hist"],
                    best_rc_hist=cg_telemetry["best_rc_hist"],
                    duals_stale_hist=cg_telemetry["duals_stale_hist"],
                    lp_hit_time_limit_hist=cg_telemetry["lp_hit_time_limit_hist"],
                    lp_obj_hist=cg_telemetry["lp_obj_hist"],
                    lp_time_limit_hist=cg_telemetry["lp_time_limit_hist"],
                    dedupe_hist={
                        "generated_cols": cg_telemetry["generated_cols_hist"],
                        "deduped_cols": cg_telemetry["deduped_cols_hist"],
                        "kept_cols": cg_telemetry["kept_cols_hist"],
                        "unique_ratio": cg_telemetry["unique_ratio_hist"],
                    },
                    repairs_applied=[],
                )
                return self._fail_result(ctx, "MIP_FAILED", mip_res["status"], logs, proof, telemetry)
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log(f"EXCEPTION: {e}\n{tb}", level=logging.ERROR)
            self._write_run_manifest(
                ctx=ctx,
                manifest_path=os.path.join(ctx.artifact_dir, "run_manifest.json"),
                status="FAIL",
                seed=config.get("seed"),
                config_snapshot=config,
                stop_reason="EXCEPTION",
                coverage_exact_once=False,
                drivers_total=0,
                avg_days_per_driver=0.0,
                tours_per_driver=0.0,
                fleet_peak=self._compute_fleet_peak(tours),
                wall_time=0.0,
                lp_times=cg_telemetry["lp_runtime_hist"],
                mip_time=ctx.timings.get("final_mip", 0.0),
                cg_iters=telemetry.get("cg_iterations", 0),
                pool_size_after_seed=pool_size_after_seed if "pool_size_after_seed" in locals() else 0,
                pool_size_final=pool.size if "pool" in locals() else 0,
                added_cols_hist=cg_telemetry["kept_cols_hist"],
                pool_day_mix=self._day_mix(pool.columns) if "pool" in locals() else {},
                selected_day_mix={},
                profile_hist=cg_telemetry["profile_hist"],
                best_rc_hist=cg_telemetry["best_rc_hist"],
                duals_stale_hist=cg_telemetry["duals_stale_hist"],
                lp_hit_time_limit_hist=cg_telemetry["lp_hit_time_limit_hist"],
                lp_obj_hist=cg_telemetry["lp_obj_hist"],
                lp_time_limit_hist=cg_telemetry["lp_time_limit_hist"],
                dedupe_hist={
                    "generated_cols": cg_telemetry["generated_cols_hist"],
                    "deduped_cols": cg_telemetry["deduped_cols_hist"],
                    "kept_cols": cg_telemetry["kept_cols_hist"],
                    "unique_ratio": cg_telemetry["unique_ratio_hist"],
                },
                repairs_applied=[],
            )
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

    def _build_kpis(self, solution, selected_columns, total_time, mip_obj, telemetry, converged, pool):
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

        avg_days_per_driver = (
            sum(c.days_worked for c in selected_columns) / len(selected_columns)
            if selected_columns
            else 0.0
        )
        tours_per_driver = (
            sum(len(c.covered_tour_ids) for c in selected_columns) / len(selected_columns)
            if selected_columns
            else 0.0
        )
        
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
            "avg_days_per_driver": avg_days_per_driver,
            "tours_per_driver": tours_per_driver,
            "pool_final_size": pool.size,
            "selected_days_worked_hist": dict(sorted(selected_days_hist.items())),
            "pool_days_worked_hist": dict(sorted(pool_days_hist.items())),
            "cg_iterations": telemetry["cg_iterations"],
            "new_cols_added_total": telemetry["new_cols_added_total"],
            "converged": converged,
        }

    @staticmethod
    def _check_exact_once(columns: list, all_tour_ids: list[str]) -> bool:
        counts = {tid: 0 for tid in all_tour_ids}
        for col in columns:
            for tid in col.covered_tour_ids:
                if tid in counts:
                    counts[tid] += 1
        return all(count == 1 for count in counts.values())

    @staticmethod
    def _get_git_sha() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    @staticmethod
    def _export_roster_csv(columns: list, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write("driver_id,day,duty_start,duty_end,tour_ids,hours\n")
            for i, col in enumerate(columns):
                driver_type = "FTE" if col.hours >= 40.0 else "PT"
                driver_id = f"D_{driver_type}{i+1:03d}"
                for duty in col.duties:
                    handle.write(
                        f"{driver_id},{duty.day},{duty.start_min},{duty.end_min},"
                        f"{'|'.join(duty.tour_ids)},{col.hours:.1f}\n"
                    )

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        values_sorted = sorted(values)
        idx = int(round((len(values_sorted) - 1) * percentile))
        return values_sorted[min(max(idx, 0), len(values_sorted) - 1)]

    @staticmethod
    def _day_mix(columns: list) -> dict:
        mix = {}
        for col in columns:
            days = getattr(col, "days_worked", 1)
            mix[days] = mix.get(days, 0) + 1
        return dict(sorted(mix.items()))

    def _write_run_manifest(
        self,
        ctx: RunContext,
        manifest_path: str,
        status: str,
        seed: Optional[int],
        config_snapshot: dict,
        stop_reason: str,
        coverage_exact_once: bool,
        drivers_total: int,
        avg_days_per_driver: float,
        tours_per_driver: float,
        fleet_peak: int,
        wall_time: float,
        lp_times: list[float],
        mip_time: float,
        cg_iters: int,
        pool_size_after_seed: int,
        pool_size_final: int,
        added_cols_hist: list[int],
        pool_day_mix: dict,
        selected_day_mix: dict,
        profile_hist: list[str],
        best_rc_hist: list[float],
        duals_stale_hist: list[bool],
        lp_hit_time_limit_hist: list[bool],
        lp_obj_hist: list[float],
        lp_time_limit_hist: list[float],
        dedupe_hist: dict,
        repairs_applied: list,
    ) -> None:
        manifest = {
            "run_id": ctx.manifest.run_id,
            "git_sha": self._get_git_sha(),
            "seed": seed,
            "profile": "core_v2",
            "status": status,
            "stop_reason": stop_reason,
            "config_snapshot": config_snapshot,
            "kpis": {
                "coverage_exact_once": 1.0 if coverage_exact_once else 0.0,
                "drivers_total": drivers_total,
                "avg_days_per_driver": round(avg_days_per_driver, 3),
                "tours_per_driver": round(tours_per_driver, 3),
                "fleet_peak": fleet_peak,
            },
            "timing": {
                "wall_time_sec": round(wall_time, 3),
                "lp_time_sec_p50": round(self._percentile(lp_times, 0.5), 3),
                "lp_time_sec_p95": round(self._percentile(lp_times, 0.95), 3),
                "mip_time_sec": round(mip_time, 3),
                "lp_time_limit_sec": lp_time_limit_hist[-1] if lp_time_limit_hist else 0.0,
            },
            "cg": {
                "iters_done": cg_iters,
                "pool_size_after_seed": pool_size_after_seed,
                "pool_size_final": pool_size_final,
                "added_cols_hist": added_cols_hist,
                "pool_day_mix": pool_day_mix,
            },
            "pricing": {
                "profile_hist": profile_hist,
                "best_rc_hist": best_rc_hist,
                "duals_stale_hist": duals_stale_hist,
                "lp_hit_time_limit_hist": lp_hit_time_limit_hist,
                "lp_obj_hist": lp_obj_hist,
                "lp_time_limit_hist": lp_time_limit_hist,
            },
            "selection": {
                "selected_day_mix": selected_day_mix,
            },
            "telemetry": {
                "dedupe": dedupe_hist,
            },
            "repairs_applied": repairs_applied,
        }

        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, default=str)

    @staticmethod
    def _compute_fleet_peak(tours: list) -> int:
        try:
            from fleet_counter import compute_fleet_peaks
        except Exception:
            return 0

        try:
            summary = compute_fleet_peaks(tours, turnaround_minutes=5)
            return summary.global_peak_count
        except Exception:
            return 0
    
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
