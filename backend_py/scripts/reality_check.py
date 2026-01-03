"""
Reality Check: Physical Lower Bound Calculation
Goal: Determine if "214 drivers" is realistic given the workload.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_forecast_csv import parse_forecast_csv
from src.domain.models import Weekday

def main():
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Calculate total workload
    total_tours = len(tours_v1)
    total_hours = sum(t.duration_hours for t in tours_v1)
    
    # Tours by day
    tours_by_day = {}
    for t in tours_v1:
        tours_by_day.setdefault(t.day, []).append(t)
    
    # Calculate peak concurrency per day (max simultaneous tours)
    peak_fleet_by_day = {}
    for day, day_tours in tours_by_day.items():
        # Create events
        events = []
        for t in day_tours:
            start_min = t.start_time.hour * 60 + t.start_time.minute
            end_min = start_min + int(t.duration_hours * 60)
            events.append((start_min, +1))  # Start
            events.append((end_min, -1))    # End
        
        events.sort()
        concurrent = 0
        max_concurrent = 0
        for time, delta in events:
            concurrent += delta
            max_concurrent = max(max_concurrent, concurrent)
        
        peak_fleet_by_day[day] = max_concurrent
    
    peak_fleet_weekly = max(peak_fleet_by_day.values())
    
    # Calculate lower bounds for weekly drivers
    # Assumption: Each driver can work max 55 hours/week (generous upper bound)
    # Or max 5 days/week with 5 tours/day = 25 tours/week
    
    max_hours_per_driver_week = 55.0
    max_tours_per_driver_week = 25  # Very optimistic (5 days * 5 tours)
    
    lb_by_hours = total_hours / max_hours_per_driver_week
    lb_by_tours = total_tours / max_tours_per_driver_week
    
    # Report
    print("=" * 80)
    print("REALITY CHECK: Physical Lower Bounds")
    print("=" * 80)
    print(f"\nForecast Summary:")
    print(f"  Total Tours: {total_tours}")
    print(f"  Total Hours: {total_hours:.1f}h")
    print(f"  Active Days: {len(tours_by_day)}")
    print(f"  Avg Tours/Day: {total_tours / len(tours_by_day):.1f}")
    
    print(f"\nPeak Fleet (Max Concurrent):")
    for day, peak in sorted(peak_fleet_by_day.items()):
        day_name = day.name if hasattr(day, 'name') else str(day)
        print(f"  {day_name}: {peak} vehicles")
    print(f"  Weekly Peak: {peak_fleet_weekly} vehicles")
    
    print(f"\nPhysical Lower Bounds for Weekly Drivers:")
    print(f"  By Hours ({max_hours_per_driver_week}h/week max): {lb_by_hours:.1f} drivers")
    print(f"  By Tours ({max_tours_per_driver_week} tours/week max): {lb_by_tours:.1f} drivers")
    
    print(f"\n" + "=" * 80)
    print("COMPARISON WITH TARGETS:")
    print("=" * 80)
    print(f"  Target Claim: 214 drivers")
    print(f"  LP Lower Bound (Observed): ~460-600 drivers")
    print(f"  Physical Lower Bound: ~{max(lb_by_hours, lb_by_tours):.0f} drivers")
    print(f"  Peak Fleet: {peak_fleet_weekly} vehicles")
    
    print(f"\n" + "=" * 80)
    print("VERDICT:")
    print("=" * 80)
    
    if peak_fleet_weekly <= 220:
        print(f"[OK] Target '214' MATCHES Peak Fleet ({peak_fleet_weekly})")
        print(f"  -> '214' likely refers to VEHICLES/FLEET, not weekly drivers.")
        print(f"  -> Weekly drivers will be ~{max(lb_by_hours, lb_by_tours):.0f}-600 (different metric).")
    else:
        print(f"[FAIL] Target '214' does NOT match Peak Fleet ({peak_fleet_weekly})")
        print(f"[FAIL] Target '214' is IMPOSSIBLE for weekly drivers")
        print(f"  -> Physical bound is ~{max(lb_by_hours, lb_by_tours):.0f} drivers minimum")
        print(f"  -> LP bound of 460-600 is CORRECT order of magnitude")
        print(f"  -> Either target is WRONG or refers to different KPI")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
