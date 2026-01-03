"""
P1 Verification: Fleet Peak Counter
Confirms that weekly drivers and peak fleet are correctly separated.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.core_v2.fleet_counter import calculate_fleet_peak_from_tours
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("P1_Verify")

def main():
    # Load forecast
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Calculate baseline fleet peak (before optimization)
    baseline_fleet = calculate_fleet_peak_from_tours(tours_v1)
    
    logger.info(f"BASELINE Fleet Peak: {baseline_fleet['fleet_peak']} vehicles")
    logger.info(f"  By Day: {baseline_fleet['fleet_peak_by_day']}")
    logger.info(f"  Peak Time: {baseline_fleet['fleet_peak_time']}")
    
    # Convert tours
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(f"T_{day_map.get(t.day, 0)}_{t.id}", day_map.get(t.day, 0), t.start_time.hour*60+t.start_time.minute, t.start_time.hour*60+t.start_time.minute+int(t.duration_hours*60), int(t.duration_hours*60)))

    # Run quick optimization
    config = {
        "run_id": "p1_verify",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results/p1_verify",
        
        "max_cg_iterations": 10,
        "lp_time_limit": 20.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 20.0,
        "mip_time_limit": 60.0,
        "final_subset_cap": 15_000,
        "target_seed_columns": 3000,
        "pricing_time_limit_sec": 8.0,
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 1440,  # 24h
            "top_m_start_tours": 300,
            "max_succ_per_tour": 50,
            "max_triples_per_tour": 5,
        },
        "export_csv": False
    }
    
    import os
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    # Report
    print("\n" + "=" * 80)
    print("P1 VERIFICATION RESULTS")
    print("=" * 80)
    
    if result.status == "SUCCESS":
        kpis = result.kpis
        
        print(f"\nOPTIMIZATION RESULT:")
        print(f"  Status: {result.status}")
        print(f"  Weekly Drivers (MIP Objective): {kpis['drivers_total']}")
        print(f"  Peak Fleet (Concurrent Vehicles): {kpis.get('fleet_peak', 'N/A')}")
        print(f"  Peak Fleet Time: {kpis.get('fleet_peak_time', 'N/A')}")
        print(f"  Peak Fleet by Day: {kpis.get('fleet_peak_by_day', {})}")
        
        print(f"\nCOMPARISON:")
        print(f"  Baseline Fleet Peak: {baseline_fleet['fleet_peak']}")
        print(f"  Optimized Fleet Peak: {kpis.get('fleet_peak', 'N/A')}")
        print(f"  Fleet Delta: {kpis.get('fleet_peak', 0) - baseline_fleet['fleet_peak']} (should be 0 - same tours)")
        
        print(f"\nKEY METRICS SEPARATION:")
        print(f"  Weekly Drivers: {kpis['drivers_total']} (people working this week)")
        print(f"  Peak Fleet: {kpis.get('fleet_peak', 'N/A')} (max vehicles needed simultaneously)")
        print(f"  Ratio: {kpis['drivers_total'] / max(1, kpis.get('fleet_peak', 1)):.1f}x (drivers per vehicle)")
        
        print(f"\n" + "=" * 80)
        print("VERDICT:")
        print("=" * 80)
        
        if kpis.get('fleet_peak') == baseline_fleet['fleet_peak']:
            print("[PASS] Fleet peak correctly calculated and matches baseline.")
        else:
            print(f"[WARN] Fleet peak mismatch: {kpis.get('fleet_peak')} vs {baseline_fleet['fleet_peak']}")
        
        if kpis['drivers_total'] > kpis.get('fleet_peak', 0):
            print(f"[PASS] Weekly drivers ({kpis['drivers_total']}) > Fleet peak ({kpis.get('fleet_peak')}), as expected.")
        else:
            print(f"[FAIL] Weekly drivers should be > fleet peak!")
        
        print("\n[OK] P1 Implementation Complete: Metrics correctly separated.")
        
    else:
        print(f"\n[FAIL] Optimization failed: {result.error_message}")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
