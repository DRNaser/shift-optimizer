"""
Run Emergency Pivot (Sniper Mode) on a specific CSV file.
Usage: python scripts/run_pivot_test.py <path_to_csv>
"""
import sys
import os
import logging
import time
from pathlib import Path

# Setup Path to access backend_py modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Imports
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
# Import the parser we verified earlier
from test_forecast_csv import parse_forecast_file

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PivotRun")

def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python scripts/run_pivot_test.py <path_to_csv>")
        return

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        logger.error(f"File not found: {csv_path}")
        return

    logger.info(f"Loading tours from: {csv_path}")
    
    try:
        # Check file extension / content type roughly?
        # parse_forecast_file handles csv/txt inference
        tours = parse_forecast_file(str(csv_path))
        logger.info(f"Loaded {len(tours)} tours")
    except Exception as e:
        logger.error(f"Failed to parse file: {e}")
        return

    # CONFIGURATION (The "Emergency Pivot" Settings)
    timestamp = int(time.time())
    run_id = f"pivot_{csv_path.stem}_{timestamp}"
    config = {
        "run_id": run_id,
        "week_category": "COMPRESSED",
        "artifacts_dir": f"results_pivot/{run_id}",
        
        # --- Core Pivot Params ---
        "hard_driver_limit": 145,      # The target
        "hard_constraint_mode": "A",   # Mode A (Total <= Limit)
        
        "pt_weight_base": 500.0,       # NUCLEAR OPTION (Was 50.0)
        "pt_weight_max": 2000.0,       # Extreme ramp
        "driver_overage_penalty": 5000.0, # Make overage PAINFUL to encourage efficiency
        
        # --- Performance Params ---
        "max_cg_iterations": 30,       # Cap at 30 as requested
        "max_new_cols_per_iter": 1000, # Sniper limit
        "lp_time_limit": 60.0,
        "pricing_time_limit_sec": 10.0,
        "mip_time_limit": 180.0,       # 3 min final MIP
        
        "restricted_mip_time_limit": 5.0, # Fast intermediate checks
        
        "duty_caps": {
            "max_gap_minutes": 420,
            "top_m_start_tours": 150, # Narrow search for speed
            "max_succ_per_tour": 25,
        }
    }
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    logger.info("Starting Optimizer with Emergency Pivot Config...")
    opt = OptimizerCoreV2()
    result = opt.solve(tours, config, run_id=config["run_id"])
    
    if result.status == "SUCCESS":
        logger.info("SUCCESS!")
        kpis = result.kpis
        logger.info(f"Drivers Total: {kpis.get('drivers_total')}")
        logger.info(f"FTE: {kpis.get('drivers_fte')}")
        logger.info(f"PT:  {kpis.get('drivers_pt')}")
        logger.info(f"PT Share: {kpis.get('pt_share_pct', 0):.1f}%")
        logger.info(f"Obj: {kpis.get('mip_obj'):.2f}")
    else:
        logger.error(f"FAILED: {result.error_message}")

if __name__ == "__main__":
    main()
