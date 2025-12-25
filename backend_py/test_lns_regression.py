"""
Test LNS with activation costs - Regression Test
=================================================
Demonstrates the effect of LNS with consolidation on PT fragmentation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import solve_forecast_v4, ConfigV4
from src.services.lns_refiner_v4 import refine_assignments_v4, LNSConfigV4
from datetime import time as dt_time

# German day names
DAY_MAP = {
    "Montag": Weekday.MONDAY,
    "Dienstag": Weekday.TUESDAY,
    "Mittwoch": Weekday.WEDNESDAY,
    "Donnerstag": Weekday.THURSDAY,
    "Freitag": Weekday.FRIDAY,
    "Freitag ": Weekday.FRIDAY,
    "Samstag": Weekday.SATURDAY,
"Sonntag": Weekday.SUNDAY,
}


def parse_forecast_csv(csv_path: str) -> list[Tour]:
    """Parse the German-formatted forecast CSV."""
    tours = []
    tour_counter = 0
    current_day = None
    
    with open(csv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line == ";":
                continue
            
            parts = line.split(";")
            if len(parts) < 2:
                continue
            
            col1 = parts[0].strip()
            col2 = parts[1].strip()
            
            day_match = None
            for day_name, weekday in DAY_MAP.items():
                if col1.startswith(day_name):
                    day_match = weekday
                    break
            
            if day_match:
                current_day = day_match
                continue
            
            if current_day and "-" in col1 and col2.isdigit():
                try:
                    time_range = col1
                    count = int(col2)
                    
                    start_str, end_str = time_range.split("-")
                    start_h, start_m = map(int, start_str.split(":"))
                    end_h, end_m = map(int, end_str.split(":"))
                    
                    for i in range(count):
                        tour_counter += 1
                        tour = Tour(
                            id=f"T{tour_counter:04d}",
                            day=current_day,
                            start_time=dt_time(start_h, start_m),
                            end_time=dt_time(end_h, end_m),
                        )
                        tours.append(tour)
                except Exception:
                    continue
    
    return tours


def main():
    csv_path = Path(__file__).parent.parent / "forecast input.csv"
    
    print("=" * 70)
    print("LNS REGRESSION TEST - PT Fragmentation Reduction")
    print("=" * 70)
    print(f"Input: {csv_path}")
    print()
    
    # Parse CSV
    tours = parse_forecast_csv(str(csv_path))
    print(f"Loaded {len(tours)} tours")
    
    total_hours = sum(t.duration_hours for t in tours)
    print(f"Total hours: {total_hours:.1f}h")
    print()
    
    # Run solver with activation costs
    print("PHASE 1: Running initial solver with activation costs...")
    print("=" * 70)
    
    config = ConfigV4(
        time_limit_phase1=60.0,
        seed=42,
        w_new_driver=1000.0,  # Activation penalty
        w_pt_new=500.0,       # PT activation penalty
    )
    
    result = solve_forecast_v4(tours, config)
    
    print(f"\nInitial Result:")
    print(f"  Status: {result.status}")
    print(f"  Drivers: {result.kpi['drivers_fte']} FTE + {result.kpi['drivers_pt']} PT")
    print(f"  PT single segment: {result.kpi.get('pt_single_segment_count', 'N/A')}")
    print(f"  PT with <=4.5h: {result.kpi.get('pt_low_utilization_count', 'N/A')}")
    
    # Run LNS with consolidation
    print("\n" + "=" * 70)
    print("PHASE 2: Running LNS with consolidation...")
    print("=" * 70)
    
    lns_config = LNSConfigV4(
        max_iterations=10,
        destroy_fraction=0.30,
        seed=42,
        w_new_driver=1000.0,
        w_pt_new=500.0,
        enable_consolidation=True,
        max_consolidation_iterations=5,
    )
    
    refined_assignments = refine_assignments_v4(result.assignments, lns_config)
    
    # Analyze final result
    print("\n" + "=" * 70)
    print("FINAL COMPARISON")
    print("=" * 70)
    
    fte_count = len([a for a in refined_assignments if a.driver_type == "FTE" and a.blocks])
    pt_count = len([a for a in refined_assignments if a.driver_type == "PT" and a.blocks])
    pt_single = len([a for a in refined_assignments if a.driver_type == "PT" and len(a.blocks) == 1 and a.blocks])
    pt_low_util = len([a for a in refined_assignments if a.driver_type == "PT" and a.total_hours <= 4.5 and a.blocks])
    
    print(f"\nBefore LNS:")
    print(f"  Drivers: {result.kpi['drivers_fte']} FTE + {result.kpi['drivers_pt']} PT = {result.kpi['drivers_fte'] + result.kpi['drivers_pt']}")
    print(f"  PT single segment: {result.kpi.get('pt_single_segment_count', 'N/A')}")
    print(f"  PT with <=4.5h: {result.kpi.get('pt_low_utilization_count', 'N/A')}")
    
    print(f"\nAfter LNS:")
    print(f"  Drivers: {fte_count} FTE + {pt_count} PT = {fte_count + pt_count}")
    print(f"  PT single segment: {pt_single}")
    print(f"  PT with <=4.5h: {pt_low_util}")
    
    print(f"\nImprovement:")
    print(f"  Total drivers: {result.kpi['drivers_fte'] + result.kpi['drivers_pt']} -> {fte_count + pt_count} (Delta {(fte_count + pt_count) - (result.kpi['drivers_fte'] + result.kpi['drivers_pt'])})")
    print(f"  PT drivers: {result.kpi['drivers_pt']} -> {pt_count} (Delta {pt_count - result.kpi['drivers_pt']})")
    print(f"  PT with <=4.5h: {result.kpi.get('pt_low_utilization_count', 0)} -> {pt_low_util} (Delta {pt_low_util - result.kpi.get('pt_low_utilization_count', 0)})")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
