"""
Core V2 Adapter for API
=======================
Bridges the 'routes_v2' API (which expects V4 structures) to the 'OptimizerCoreV2' engine.
This enables V2 to be the default solver transparently.
"""

import logging
import time
from typing import Callable, Optional

from src.core_v2.optimizer_v2 import OptimizerCoreV2, check_highspy_availability
from src.core_v2.adapter import Adapter
from src.services.forecast_solver_v4 import ConfigV4, SolveResultV4
from src.services.portfolio_controller import PortfolioResult, ParameterBundle, PathSelection
from src.services.instance_profiler import FeatureVector

# Dummy / Placeholder objects for fields V2 doesn't fully populate yet
from src.services.policy_engine import PathSelection

logger = logging.getLogger("AdapterV2")

class AdapterV2:
    """
    Static adapter to run OptimizerCoreV2 and return PortfolioResult.
    """
    
    @staticmethod
    def run_optimizer_v2_adapter(
        tours: list, # Domain Tour objects
        time_budget: float,
        seed: int,
        config: ConfigV4,
        log_fn: Callable[[str], None] = None,
        context: Optional[object] = None
    ) -> PortfolioResult:
        """
        Main entry point for API to call V2.
        Matches signature logic of portfolio_controller.run_portfolio (mostly).
        """
        start_time = time.perf_counter()
        
        def log(msg: str):
            logger.info(msg)
            if log_fn:
                log_fn(msg)

        # 1. Dependency Check
        try:
            check_highspy_availability()
        except ImportError as e:
            log(f"CRITICAL: HighsPy missing. {e}")
            raise e

        log("=" * 60)
        log("ADAPTER V2: Starting Core V2 Optimization")
        log(f"Tours: {len(tours)}, Budget: {time_budget}s, Seed: {seed}")
        log("=" * 60)

        # 2. Input Conversion (Domain Tour -> TourV2)
        # Using existing Adapter in core_v2
        tours_v2 = Adapter.to_v2_tours(tours)
        log(f"Converted {len(tours)} domain tours to V2 format.")

        # We need a run_id. If context has it, use it.
        run_id = "v2_adapter_run"
        if hasattr(context, "run_id"):
            run_id = context.run_id

        # 3. Config Mapping (ConfigV4 -> Dict)
        # Map relevant V4 fields to V2 config dict
        v2_config = {
            # Meta
            "artifacts_dir": f"artifacts/{run_id}", # Unique per run to avoid collision
            "week_category": "NORMAL", # Auto-detect in V2 handles this, but we can hint if needed
            
            # Constraints
            "hard_driver_limit": config.target_ftes if config.target_ftes > 0 else None,
            "target_fte_count": config.target_ftes,
            
            # Weights
            "pt_weight_base": 50.0,   # Standard
            "pt_weight_max": 200.0,   # Ramp up
            
            # Time Limits
            "lp_time_limit": 10.0,
            "pricing_time_limit_sec": 3.0,
            # "max_cg_iterations": 100,
            # "mip_time_limit": 300.0,
            
            # Misc
            "seed": seed,
            
            # Pass-through overrides if any
            # (In a real scenario, we'd map more fields from ConfigV4)
        }
        
        # 4. Run Optimizer
        optimizer = OptimizerCoreV2()
        
        try:
            # EXECUTE CORE V2
            v2_result = optimizer.solve(tours_v2, v2_config, run_id=run_id)
            
            total_runtime = time.perf_counter() - start_time
            
            # 5. Map Result (CoreV2Result -> PortfolioResult)

            # HYDRATION: Convert PseudoBlocks to Real Blocks (Domain)
            # This is critical because routes_v2 expects domain objects (Tour, Block)
            # but OptimizerCoreV2 returns lightweight structs with IDs.
            
            tour_map = {t.id: t for t in tours}
            
            hydrated_assignments = []
            from src.domain.models import Block, PauseZone
            from src.services.forecast_solver_v4 import DriverAssignment
            
            for i, raw_assign in enumerate(v2_result.solution):
                 # raw_assign is a dataclass from V4 (but with PseudoBlocks inside)
                 # Reconstruct it carefully
                 
                 real_blocks = []
                 for raw_block in raw_assign.blocks:
                     # raw_block is PseudoBlock(id, day, tours=[ids...], ...)
                     
                     # Resolve tours
                     block_tours = []
                     for tid in raw_block.tours:
                         if tid in tour_map:
                             block_tours.append(tour_map[tid])
                         else:
                             log(f"WARNING: Tour ID {tid} in solution not found in input map!")
                     
                     if not block_tours:
                         continue
                         
                     # Create Domain Block
                     real_block = Block(
                         id=raw_block.id,
                         day=raw_block.day,
                         tours=block_tours,
                         driver_id=raw_assign.driver_id,
                         is_split=False, # V2 doesn't do split yet
                         pause_zone=PauseZone.REGULAR
                     )
                     real_blocks.append(real_block)
                 
                 # Create proper DriverAssignment
                 assignment = DriverAssignment(
                     driver_id=raw_assign.driver_id,
                     driver_type=raw_assign.driver_type,
                     blocks=real_blocks,
                     total_hours=raw_assign.total_hours,
                     days_worked=raw_assign.days_worked,
                     analysis=getattr(raw_assign, "analysis", {})
                 )
                 hydrated_assignments.append(assignment)
                 
            # Use hydrated assignments
            solution_list = hydrated_assignments

            # Map KPIs
            # V2 returns a 'kpis' dict. We blend it with V4 expectations.
            final_kpis = v2_result.kpis.copy()
            # Ensure critical keys exist for API
            final_kpis.setdefault("status", v2_result.status)
            final_kpis.setdefault("drivers_total", v2_result.num_drivers)
            
            # Build SolveResultV4 (The wrapper expected by API)
            solve_result = SolveResultV4(
                status=v2_result.status,
                assignments=solution_list, # Hydrated list
                kpi=final_kpis,
                solve_times={
                    "total": total_runtime, 
                    "optimization": total_runtime # simplified
                },
                block_stats={},
                missing_tours=[] # V2 might populate this if infeasible
            )
            
            # Build PortfolioResult (The outer wrapper)
            # Create dummy features/params since V2 doesn't use the V4 profiler/policy engine
            dummy_features = FeatureVector(
                peakiness_index=0.0,
                pool_pressure=0.0,
                lower_bound_drivers=0,
                fleet_peak=0
            )
            
            dummy_params = ParameterBundle(
                path=PathSelection.C, # Pretend it's Path C
                lns_iterations=0,
                destroy_fraction=0.0
            )
            
            portfolio_res = PortfolioResult(
                solution=solve_result,
                features=dummy_features,
                initial_path=PathSelection.C,
                final_path=PathSelection.C,
                parameters_used=dummy_params,
                reason_codes=[],
                lower_bound=0,
                achieved_score=v2_result.num_drivers,
                total_runtime_s=total_runtime,
                fallback_used=False
            )
            
            log(f"ADAPTER V2: Success. Returned {v2_result.num_drivers} drivers.")
            return portfolio_res

        except Exception as e:
            log(f"ADAPTER V2 FAILED: {e}")
            import traceback
            log(traceback.format_exc())
            raise e
