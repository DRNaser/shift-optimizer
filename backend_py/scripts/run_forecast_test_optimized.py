"""
Phase 4 Optimized Run: Forecast-Test (6 Days)
Configuration based on diagnosis:
- Reduced Graph Size (Duty Caps 50/30) prevents SPPRC timeouts.
- Increased Pricing Time (60s) allows full label propagation (Day 1->6).
- 24h Window allows bridging gap days properly.
"""
import sys
import os
import logging
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Phase4_Run")

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv

def main():
    # Load Forecast
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv")
    if not csv_file.exists():
        logger.error("forecast_test.csv not found!")
        return
        
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Convert to V2
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(f"T_{day_map.get(t.day, 0)}_{t.id}", day_map.get(t.day, 0), t.start_time.hour*60+t.start_time.minute, t.start_time.hour*60+t.start_time.minute+int(t.duration_hours*60), int(t.duration_hours*60)))

    # Phase 4 Optimization Config
    config = {
        "run_id": "phase4_opt",
        "week_category": "NORMAL",
        "artifacts_dir": "results/phase4_opt",
        
        "max_cg_iterations": 30,  # 30 Iterations as requested
        "lp_time_limit": 60.0,
        "restricted_mip_var_cap": 25_000,
        "restricted_mip_time_limit": 60.0,
        "mip_time_limit": 300.0,
        "final_subset_cap": 25_000,
        "target_seed_columns": 3000,
        
        # CRITICAL FIXES FROM DIAGNOSIS
        "pricing_time_limit_sec": 60.0,  # Ensure full propagation
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 1440, # 24h window
            
            # Graph Size Control (Prevents Explosion)
            "top_m_start_tours": 50, # Was 300 -> Explosion
            "max_succ_per_tour": 30, # Was 100 -> Explosion
            "max_triples_per_tour": 5,
        },
        "export_csv": True
    }
    
    # Phase 4 Adaptive Config
    # Logic is now internal to OptimizerCoreV2
    
    # Ensure base config is set for "Cruise Mode"
    config["pricing_time_limit_sec"] = 60.0
    config["duty_caps"]["top_m_start_tours"] = 50
    config["duty_caps"]["max_succ_per_tour"] = 30
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])

    # Report Final Metrics
    kpis = result.kpis
    print("\n" + "=" * 80)
    print("PHASE 4 OPTIMIZED RESULT")
    print("=" * 80)
    print(f"Total Tours: {len(tours_v2)}")
    print(f"Drivers (Weekly Rosters): {kpis.get('drivers_total', 0)}")
    print(f"Driver Days: {sum(k * v for k, v in kpis.get('selected_days_worked_hist', {}).items())}")
    print(f"Avg Days/Driver: {sum(k * v for k, v in kpis.get('selected_days_worked_hist', {}).items()) / max(1, kpis.get('drivers_total', 1)):.2f}")
    print(f"Days Hist (Selected): {kpis.get('selected_days_worked_hist', {})}")
    print(f"Pool Days>=4: {kpis.get('pct_pool_days_ge_4', 0):.1f}%")
    print(f"Fleet Peak: {kpis.get('fleet_peak', 0)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
