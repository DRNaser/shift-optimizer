"""
Baseline Run Script for KW51 Core V2
Strictly enforces 'Locked Config' for Phase 0 measurement.
"""
import sys
import os
import logging
import time
import csv
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RunBaseline")

# Imports
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv

def main():
    # CSV Path
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return

    logger.info(f"Loading tours from: {csv_file}")
    
    # 1. Parse CSV
    try:
        tours_v1 = parse_forecast_csv(str(csv_file))
        logger.info(f"Loaded {len(tours_v1)} V1 tours")
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        return
    
    # 2. Convert to V2
    day_map = {
        Weekday.MONDAY: 0, Weekday.TUESDAY: 1, Weekday.WEDNESDAY: 2,
        Weekday.THURSDAY: 3, Weekday.FRIDAY: 4, Weekday.SATURDAY: 5, Weekday.SUNDAY: 6,
    }
    
    tours_v2 = []
    for t in tours_v1:
        day = day_map.get(t.day, 0)
        start_min = t.start_time.hour * 60 + t.start_time.minute
        duration_min = int(t.duration_hours * 60)
        end_min = start_min + duration_min
        
        tv2 = TourV2(
            tour_id=f"T_{day}_{t.id}",
            day=day,
            start_min=start_min,
            end_min=end_min,
            duration_min=duration_min
        )
        tours_v2.append(tv2)

    # 3. LOCKED CONFIGURATION (Do Not Change in Phase 0)
    config = {
        "run_id": "baseline_locked_v1",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results/baseline",
        
        # Stability & Performance Limits
        "max_cg_iterations": 20,         # Sufficient for convergence
        "lp_time_limit": 60.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 45.0, # LOCKED
        "mip_time_limit": 300.0,           # LOCKED
        "final_subset_cap": 12_000,        # LOCKED
        "target_seed_columns": 5000,
        "pricing_time_limit_sec": 12.0,
        
        # Duty Generation (Locked Baseline)
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 720,        # LOCKED: 12h relative (search window)
            "top_m_start_tours": 500,      # High capacity for initial exploration
            "max_succ_per_tour": 50,       # LOCKED: 50 candidates
            "max_triples_per_tour": 5,
        },
        
        "export_csv": True
    }
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    logger.info("Starting BASELINE optimization run...")
    logger.info(f"Config: {config}")
    
    start_time = time.time()
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    end_time = time.time()
    
    # Report & CSV Log
    kpis = result.kpis
    status = result.status
    
    print("\n" + "="*40)
    print(f"BASELINE RESULT: {status}")
    print(f"Total Runtime: {end_time - start_time:.1f}s")
    if status == "SUCCESS":
        print(f"Headcount: {kpis['drivers_total']}")
        print(f"PT Share: {kpis['pt_share_pct']:.1f}%")
        print(f"MIP Obj: {kpis.get('mip_obj', -1):.2f}")
        print(f"LP Lower Bound: {kpis.get('lp_lower_bound', 'N/A')}")
        
        # Append to results.csv
        results_file = Path("results/baseline_results.csv")
        file_exists = results_file.exists()
        
        with open(results_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "timestamp", "config_id", "status", "headcount", "pt_share", 
                    "mip_obj", "lp_lb", "linker_time", "restricted_time", "final_time"
                ])
            
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                config["run_id"],
                status,
                kpis.get('drivers_total'),
                kpis.get('pt_share_pct'),
                kpis.get('mip_obj'),
                kpis.get('lp_lower_bound'),
                kpis.get('time_linker'),
                kpis.get('time_restricted_mip'),
                kpis.get('time_final_mip')
            ])
            logger.info(f"Results appended to {results_file}")
    else:
        logger.error(f"Run Failed: {result.error_message}")

if __name__ == "__main__":
    main()
