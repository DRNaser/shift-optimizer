"""
Quick Test: forecast-test.txt (New Dataset)
Runs P0.1 verification with physical bounds and quick optimization.
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

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("ForecastTest")
logger.setLevel(logging.INFO)

def main():
    # Load forecast-test.csv
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv")
    
    if not csv_file.exists():
        print(f"ERROR: {csv_file} not found. Run convert_forecast_test.py first!")
        return
    
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Calculate physical bounds
    total_tours = len(tours_v1)
    total_minutes = sum(int(t.duration_hours * 60) for t in tours_v1)
    hours_total = total_minutes / 60.0
    physical_lb = hours_total / 55.0
    
    # Fleet peak
    fleet_stats = calculate_fleet_peak_from_tours(tours_v1)
    
    print("=" * 80)
    print("FORECAST-TEST.TXT - Quick Analysis")
    print("=" * 80)
    print(f"\nPhysical Metrics:")
    print(f"  Total Tours: {total_tours}")
    print(f"  Total Hours: {hours_total:.1f}h")
    print(f"  Physical LB (55h/week): {physical_lb:.1f} drivers")
    print(f"  Fleet Peak: {fleet_stats['fleet_peak']} vehicles")
    print(f"  Peak Time: {fleet_stats['fleet_peak_time']}")
    print(f"  By Day: {fleet_stats['fleet_peak_by_day']}")
    
    # Convert to V2
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(
            f"T_{day_map.get(t.day, 0)}_{t.id}", 
            day_map.get(t.day, 0), 
            t.start_time.hour*60 + t.start_time.minute, 
            t.start_time.hour*60 + t.start_time.minute + int(t.duration_hours*60), 
            int(t.duration_hours*60)
        ))
    
    # Quick optimization run (5 iterations)
    print("\n" + "=" * 80)
    print("Running Quick Optimization (5 iterations)...")
    print("=" * 80)
    
    config = {
        "run_id": "forecast_test",
        "week_category": "NORMAL",  # 6 days
        "artifacts_dir": "results/forecast_test",
        
        "max_cg_iterations": 5,
        "lp_time_limit": 20.0,
        "restricted_mip_var_cap": 15_000,
        "restricted_mip_time_limit": 20.0,
        "mip_time_limit": 60.0,
        "final_subset_cap": 10_000,
        "target_seed_columns": 2000,
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
    
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    if result.status == "SUCCESS":
        kpis = result.kpis
        selected_cols = result._debug_columns
        
        driver_days_total = sum(c.days_worked for c in selected_cols)
        
        print(f"\nOptimization Status: {result.status}")
        print(f"\n--- USER-REQUESTED VALUES ---")
        print(f"total_tours: {total_tours}")
        print(f"hours_total: {hours_total:.1f}h")
        print(f"drivers_total (selected columns): {kpis['drivers_total']}")
        print(f"driver_days_total: {driver_days_total}")
        print(f"LP_objective: {kpis.get('mip_obj', 0):.2f}")
        print(f"fleet_peak: {kpis.get('fleet_peak', 0)}")
        
        print(f"\n--- COMPARISON ---")
        print(f"Physical LB: {physical_lb:.0f} drivers")
        print(f"Observed: {kpis['drivers_total']} drivers")
        print(f"Gap: {kpis['drivers_total'] - physical_lb:.0f} ({((kpis['drivers_total']/physical_lb - 1)*100):.0f}% fragmentation)")
        print(f"Fleet Peak: {fleet_stats['fleet_peak']} vehicles")
        print(f"Drivers/Vehicle Ratio: {kpis['drivers_total'] / max(1, fleet_stats['fleet_peak']):.1f}x")
        
        print("\n" + "=" * 80)
    else:
        print(f"\nOptimization FAILED: {result.error_message}")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
