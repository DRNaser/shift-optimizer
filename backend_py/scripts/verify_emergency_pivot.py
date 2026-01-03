"""
Verification Script for Emergency Pivot (Soft Constraints & Early Stopping)
"""
import sys
import os
import logging
import time
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VerifyPivot")

# Imports
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_file

def main():
    # CSV Path (parent dir of backend_py)
    # run_kw51_v2.py says: Path(__file__).parent.parent / "forecast_kw51_filtered.csv"
    # This script is in scripts/, so parent.parent is backend_py.
    # The csv seems to be in the folder ABOVE backend_py?
    # run_kw51_v2.py is in backend_py. csv is in backend_py/../forecast... = Desktop/shift-optimizer/forecast...
    
    csv_file = Path(__file__).parent.parent.parent / "forecast_kw51_filtered.csv"
    if not csv_file.exists():
        # Fallback to backend_py root if user moved it
        csv_file = Path(__file__).parent.parent / "forecast_kw51_filtered.csv"
        
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return

    logger.info(f"Loading tours from: {csv_file}")
    
    try:
        tours_v1 = parse_forecast_file(str(csv_file))
        logger.info(f"Loaded {len(tours_v1)} V1 tours")
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        return
    
    # Tours are already TourV2 from the parser
    tours_v2 = tours_v1
    logger.info(f"Using {len(tours_v2)} tours directly.")

    # EMERGENCY CONFIG
    config = {
        "run_id": "verify_pivot",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results_verify",
        
        "max_cg_iterations": 20,       # Targeted short run
        "hard_driver_limit": 145,      # Trigger limit
        "hard_constraint_mode": "A",
        
        # PIVOT PARAMS
        "pt_weight_base": 50.0,
        "pt_weight_max": 200.0,
        "driver_overage_penalty": 500.0,
        
        # Performance
        "lp_time_limit": 30.0,
        "pricing_time_limit_sec": 5.0, # Fast pricing
        "mip_time_limit": 60.0,
        
        "duty_caps": {
            "max_gap_minutes": 420,
            "top_m_start_tours": 100,  # Reduced for speed
            "max_succ_per_tour": 20,
        }
    }
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    if result.status == "SUCCESS":
        logger.info("SUCCESS! Pivot Verified.")
        kpis = result.kpis
        logger.info(f"Drivers: {kpis.get('drivers_total')} (Overage Penalty applied?)")
        logger.info(f"PT Share: {kpis.get('pt_share_pct', 0):.1f}%")
        logger.info(f"Converged: {kpis.get('converged')}")
    else:
        logger.error(f"FAILED: {result.error_message}")

if __name__ == "__main__":
    main()
