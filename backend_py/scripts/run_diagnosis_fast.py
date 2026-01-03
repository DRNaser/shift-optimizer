"""
Diagnosis Run Script (Fast)
Verifies impact of Linker Fix (Gap Day Window + Dual Ranking).
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
logger = logging.getLogger("RunDiag")

# Imports
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv

def main():
    # CSV Path
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    
    logger.info(f"Loading tours from: {csv_file}")
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Convert to V2
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(f"T_{day_map.get(t.day, 0)}_{t.id}", day_map.get(t.day, 0), t.start_time.hour*60+t.start_time.minute, t.start_time.hour*60+t.start_time.minute+int(t.duration_hours*60), int(t.duration_hours*60)))

    # DIAGNOSIS CONFIG (Fast)
    config = {
        "run_id": "diag_linker_fix_v1",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results/diag_linker",
        
        "max_cg_iterations": 5,          # Short run
        "lp_time_limit": 30.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 30.0,
        "mip_time_limit": 60.0,
        "final_subset_cap": 12_000,
        "target_seed_columns": 5000,
        "pricing_time_limit_sec": 10.0,
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 720,        # 12h (This is the config, but code now overrides for Gap Days)
            "top_m_start_tours": 300,
            "max_succ_per_tour": 50,
            "max_triples_per_tour": 5,
        },
        "export_csv": False
    }
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    # Report
    kpis = result.kpis
    print(f"\nDIAGNOSIS RESULT: {result.status}")
    if result.status == "SUCCESS":
        print(f"Headcount: {kpis['drivers_total']}")
        print(f"PT Share: {kpis['pt_share_pct']:.1f}%")
        print(f"MIP Obj: {kpis.get('mip_obj', -1):.2f}")
    else:
        print(f"FAILED: {result.error_message}")
        print(f"Last LP Obj: {kpis.get('lp_obj', 'N/A')}") # Custom access if available? No, kpis only populated on success?
        # Check logs for LP Obj

if __name__ == "__main__":
    main()
