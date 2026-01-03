"""
Parameter Sweep: Connector Window
Tests impact of connector_window on LP Objective and Driver Count.
Target: Find window size that allows LP Obj < 220.

Configs to test:
- 12h (Baseline)
- 16h
- 24h
"""
import sys
import os
import time
import logging
from pathlib import Path
import pandas as pd

# Setup Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Sweep")

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv

def run_config(tours, window_hours, run_id):
    logger.info(f"--- STARTING RUN: {run_id} (Window={window_hours}h) ---")
    
    config = {
        "run_id": run_id,
        "week_category": "COMPRESSED", # Force compressed logic for stress test
        "artifacts_dir": f"results/sweep_{run_id}",
        
        "max_cg_iterations": 30,          # Short run to see LP Trend
        "lp_time_limit": 20.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 20.0,
        "mip_time_limit": 60.0,
        "final_subset_cap": 10_000,
        "target_seed_columns": 3000,
        "pricing_time_limit_sec": 8.0,
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": window_hours * 60,
            "top_m_start_tours": 300,
            "max_succ_per_tour": 50,
            "max_triples_per_tour": 5,
        },
        "export_csv": False
    }
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours, config, run_id=run_id)
    
    # Extract Metrics
    lp_obj = result.kpis.get("lp_obj", -1)
    mip_obj = result.kpis.get("mip_obj", -1)
    drivers = result.kpis.get("drivers_total", -1)
    pt_share = result.kpis.get("pt_share_pct", -1)
    
    return {
        "run_id": run_id,
        "window_h": window_hours,
        "status": result.status,
        "drivers": drivers,
        "lp_obj": lp_obj,
        "mip_obj": mip_obj,
        "pt_share": pt_share,
        "runtime": result.kpis.get("total_time", 0)
    }

def main():
    # Load Data
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Convert
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(f"T_{day_map.get(t.day, 0)}_{t.id}", day_map.get(t.day, 0), t.start_time.hour*60+t.start_time.minute, t.start_time.hour*60+t.start_time.minute+int(t.duration_hours*60), int(t.duration_hours*60)))

    results = []
    
    # SWEEP EXECUTION
    windows = [12, 16, 24]
    
    for w in windows:
        res = run_config(tours_v2, w, f"sweep_win_{w}h")
        results.append(res)
        
        # Log immediate result
        print(f"\n>>> RESULT {w}h: {res['status']} | Drivers={res['drivers']} | LP={res['lp_obj']:.1f}\n")

    # Save Results
    df = pd.DataFrame(results)
    df.to_csv("results/sweep_results_window.csv", index=False)
    print("\n--- SWEEP COMPLETE ---")
    print(df.to_string())

if __name__ == "__main__":
    main()
