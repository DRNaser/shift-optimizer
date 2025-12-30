"""
Core v2 - Optimizer Engine

The main orchestrator for the Column Generation pipeline.
"""

import time
import logging
from typing import Optional

from .pricing.spprc import SPPRCPricer

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

from dataclasses import dataclass, field

@dataclass
class CoreV2Result:
    status: str
    run_id: str
    best_columns: list[ColumnV2] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    
    @property
    def num_drivers(self) -> int:
        return len(self.best_columns)

class OptimizerCoreV2:
    """
    Column Generation Optimizer.
    """
    
    def solve(self, 
             tours: list[TourV2], 
             config: dict, 
             run_id: str = "v2_run") -> CoreV2Result:
        """
        Main entry point.
        """
        # Strict Dependency Check FIRST (Phase 7 Requirement)
        check_highspy_availability()
        
        # 0. Initialize Context
        ctx = RunContext.create(run_id, tours, config)
        ctx.log(f"Starting Core v2 Optimization for {len(tours)} tours. Category: {ctx.manifest.week_category.name}")
        
        start_time = time.time()
        
        # 1. Build Duties
        t0 = time.time()
        duties_by_day = self._build_duties(tours)
        ctx.add_timing("duty_building", time.time() - t0)
        
        total_duties = sum(len(d) for d in duties_by_day.values())
        ctx.log(f"Built {total_duties} duties across {ctx.manifest.active_days_count} active days")
        
        # 2. Initialize Pool
        t0 = time.time()
        pool = ColumnPoolStore()
        # Seed with 1-duty columns (guarantees feasibility coverage)
        seed_cols = self._generate_seed_columns(duties_by_day)
        pool.add_all(seed_cols)
        ctx.add_timing("pooling_seed", time.time() - t0)
        ctx.log(f"Initialized pool with {pool.size} seed columns")
        
        # 3. Column Generation Loop
        pricer = SPPRCPricer(duties_by_day, ctx.manifest.week_category)
        
        # Re-list all unique tour IDs for coverage constraint
        # (Could strictly use ctx.manifest logic, but safe to derive from input)
        # Note: manifest uses hash, so we need the list.
        all_tour_ids = sorted([t.tour_id for t in tours])
        
        max_iter = config.get("max_cg_iterations", 50)
        ctx.log(f"Starting generic CG loop (max {max_iter} iterations)")
        
        cg_start = time.time()
        converged = False
        
        for iteration in range(1, max_iter + 1):
            iter_start = time.time()
            
            # a. Solve Master LP
            # Re-instantiate MasterLP each time? Or update?
            # MasterLP implementation currently rebuilds. That's fine.
            master_lp = MasterLP(pool.columns, all_tour_ids)
            master_lp.build(ctx.manifest.week_category)
            lp_res = master_lp.solve(time_limit=30.0)
            
            if lp_res["status"] != "OPTIMAL":
                ctx.log(f"Iter {iteration}: Master LP Infeasible/Error: {lp_res['status']}", level=logging.ERROR)
                break
                
            duals = lp_res["duals"]
            obj_val = lp_res["objective"]
            
            # Snapshot
            ctx.save_snapshot(f"iter_{iteration}_lp", {
                "objective": obj_val,
                "pool_size": pool.size,
                "duals_count": len(duals)
            })
            
            # b. Solve Pricing
            new_cols = pricer.price(duals, max_new_cols=200) # Tunable batch size
            
            # c. Update Pool
            added_count = pool.add_all(new_cols)
            
            iter_time = time.time() - iter_start
            ctx.log(
                f"Iter {iteration}: LP_Obj={obj_val:.2f}, "
                f"NewCols={len(new_cols)} (Added={added_count}), "
                f"Pool={pool.size}, Time={iter_time:.2f}s"
            )
            
            if added_count == 0:
                ctx.log("Convergence reached (no new negative-RC columns).")
                converged = True
                break
                
        ctx.add_timing("cg_loop", time.time() - cg_start)
        
        # 4. Final MIP
        t0 = time.time()
        ctx.log("Starting Final MIP Solve...")
        master_mip = MasterMIP(pool.columns, all_tour_ids)
        mip_res = master_mip.solve_lexico(
            ctx.manifest.week_category,
            time_limit=config.get("mip_time_limit", 300.0)
        )
        ctx.add_timing("final_mip", time.time() - t0)
        
        total_time = time.time() - start_time
        
        if mip_res["status"] == "OPTIMAL":
            selected = mip_res["selected_columns"]
            ctx.log(f"MIP Optimal! Selected {len(selected)} rosters. Obj={mip_res['objective']:.2f}")
            
            return CoreV2Result(
                status="SUCCESS",
                run_id=ctx.manifest.run_id,
                best_columns=selected,
                stats={
                    "total_time": total_time,
                    "mip_obj": mip_res["objective"]
                }
            )
        else:
            ctx.log(f"MIP Failed: {mip_res['status']}", level=logging.ERROR)
            return CoreV2Result(
                status="FAIL",
                run_id=ctx.manifest.run_id,
                stats={"error": mip_res["status"]}
            )

    def _build_duties(self, tours: list[TourV2]) -> dict[int, list]:
        """Group tours by day and run DutyBuilder."""
        by_day = {}
        for t in tours:
            by_day.setdefault(t.day, []).append(t)
            
        builder = DutyBuilder() # Uses default ValidatorV2
        duties_map = {}
        for day, day_tours in by_day.items():
            duties = builder.build_duties_for_day(day, day_tours)
            duties_map[day] = duties
        return duties_map

    def _generate_seed_columns(self, duties_by_day: dict) -> list[ColumnV2]:
        """Generate initial pool (simple 1-duty columns)."""
        seeds = []
        for day, duties in duties_by_day.items():
            for d in duties:
                # Filter for 1-tour duties only?
                # Blueprint says: "start with one block" or "singleton fallback".
                # To keep seed small, start with Singletons (1-duty).
                # But should we include 2er/3er duties as singletons?
                # Yes, any valid duty can be a singleton column.
                # Actually, purely 1-tour duties guarantee coverage. 2/3-tour duties are optimizations.
                # Let's seed with ALL generated duties as singleton columns. 
                # Why? To give the LP maximum freedom initially.
                # It's safer.
                
                col = ColumnV2.from_duties(
                    col_id=f"seed_{d.duty_id}",
                    duties=[d],
                    origin="seed_singleton"
                )
                seeds.append(col)
        return seeds
