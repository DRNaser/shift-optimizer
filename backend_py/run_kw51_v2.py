"""
Production Run Script for KW51 Core V2 (Aggressive Split-Shift Profile)
"""
import sys
import os
import logging
import time
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path(__file__).parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RunKW51_V2")

# Imports
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_file

def main():
    # CSV Path (parent dir)
    csv_file = Path(__file__).parent.parent / "forecast_kw51_filtered.csv"
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return

    logger.info(f"Loading tours from: {csv_file}")
    
    # 1. Parse CSV (Aggregated -> V1 Tours)
    try:
        tours_v1 = parse_forecast_file(str(csv_file))
        logger.info(f"Loaded {len(tours_v1)} V1 tours (expanded from aggregate)")
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        return
    
    # 2. Convert to V2 Tours (Already V2 from parser)
    tours_v2 = tours_v1
    logger.info(f"Using {len(tours_v2)} V2 tours")

    # 3. Configure & Run (Moderate Profile - Production Ready)
    config = {
        "run_id": "kw51_moderate_split",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results",
        
        "max_cg_iterations": 10,  # Diagnostic Run (Pruning Fix)
        "lp_time_limit": 60.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 45.0,  # Optimized for stability
        "mip_time_limit": 300.0,  # 5min budget
        "final_subset_cap": 12_000,  # MIP-friendly subset
        "target_seed_columns": 5000,
        "pricing_time_limit_sec": 12.0,
        
        # MODERATE PROFILE (Task 3)
        "duty_caps": {
            "max_gap_minutes": 420,        # 7h (was 10h in Aggressive)
            "top_m_start_tours": 300,      # (was 500)
            "max_succ_per_tour": 30,       # (was 50)
            "max_triples_per_tour": 5,
        },
        
        "export_csv": True
    }
    
    os.makedirs("results", exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    if result.status == "SUCCESS":
        logger.info("SUCCESS!")
        kpis = result.kpis
        logger.info(f"Drivers: {kpis['drivers_total']}")
        logger.info(f"PT Share: {kpis['pt_share_pct']:.1f}%")
        logger.info(f"Obj: {kpis['mip_obj']:.2f}")
        
        logger.info(f"Spread p95: {kpis.get('spread_p95', 'N/A')}h")
        logger.info(f"Max Gap p95: {kpis.get('max_gap_p95', 'N/A')}h")
        logger.info(f"Violations > 16.5h: {kpis.get('count_spread_gt_16_5h', 'N/A')}")
        
        logger.info(f"Result artifacts in: {result.artifacts_dir}")
    else:
        logger.error(f"FAILED: {result.error_message}")

if __name__ == "__main__":
    main()
