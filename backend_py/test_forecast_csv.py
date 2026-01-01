"""
Test script: Run forecast solver with the forecast input.csv
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
from datetime import time as dt_time

# German day names to Weekday mapping
DAY_MAP = {
    "Montag": Weekday.MONDAY,
    "Dienstag": Weekday.TUESDAY,
    "Mittwoch": Weekday.WEDNESDAY,
    "Donnerstag": Weekday.THURSDAY,
    "Freitag": Weekday.FRIDAY,
    "Freitag ": Weekday.FRIDAY,  # Handle trailing space
    "Samstag": Weekday.SATURDAY,
    "Sonntag": Weekday.SUNDAY,
}


def parse_forecast_csv(csv_path: str) -> list[Tour]:
    """Parse the German-formatted forecast CSV into Tour objects."""
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
            
            # Check if this is a day header
            day_match = None
            for day_name, weekday in DAY_MAP.items():
                if col1.startswith(day_name):
                    day_match = weekday
                    break
            
            if day_match:
                current_day = day_match
                print(f"Parsing day: {current_day.value}", flush=True)
                continue
            
            # Parse time range and count
            if current_day and "-" in col1 and col2.isdigit():
                try:
                    time_range = col1
                    count = int(col2)
                    
                    start_str, end_str = time_range.split("-")
                    start_h, start_m = map(int, start_str.split(":"))
                    end_h, end_m = map(int, end_str.split(":"))
                    
                    # Create 'count' tours for this time slot
                    for i in range(count):
                        tour_counter += 1
                        tour = Tour(
                            id=f"T{tour_counter:04d}",
                            day=current_day,
                            start_time=dt_time(start_h, start_m),
                            end_time=dt_time(end_h, end_m),
                        )
                        tours.append(tour)
                except Exception as e:
                    print(f"Error parsing line '{line}': {e}", flush=True)
                    continue
    
    return tours


def main():
    # Path to CSV
    csv_path = Path(__file__).parent.parent / "forecast input.csv"
    
    print("=" * 70, flush=True)
    print("FORECAST SOLVER TEST", flush=True)
    print("=" * 70, flush=True)
    print(f"Input: {csv_path}", flush=True)
    print(flush=True)
    
    # Parse CSV
    print("Parsing CSV...", flush=True)
    tours = parse_forecast_csv(str(csv_path))
    
    print(f"\nLoaded {len(tours)} tours", flush=True)
    
    # Count by day
    by_day = {}
    for t in tours:
        by_day[t.day.value] = by_day.get(t.day.value, 0) + 1
    
    print("\nTours by day:", flush=True)
    for day, count in sorted(by_day.items()):
        print(f"  {day}: {count}", flush=True)
    
    # Total hours
    total_hours = sum(t.duration_hours for t in tours)
    print(f"\nTotal hours: {total_hours:.1f}h", flush=True)
    
    # Run solver
    print("\n" + "=" * 70, flush=True)
    print("RUNNING SOLVER...", flush=True)
    print("=" * 70, flush=True)
    
    # Run Set-Partitioning Solver (avoids greedy assignment fallback)
    result = solve_forecast_set_partitioning(tours, time_limit=120.0, seed=42)
    
    # Print results
    print("\n" + "=" * 70, flush=True)
    print("RESULTS", flush=True)
    print("=" * 70, flush=True)
    print(f"Status: {result.status}", flush=True)
    print(f"\nKPIs:", flush=True)
    for key, value in result.kpi.items():
        print(f"  {key}: {value}", flush=True)
    
    print(f"\nSolve Times:", flush=True)
    for phase, time in result.solve_times.items():
        print(f"  {phase}: {time}s", flush=True)
    
    print(f"\nDriver Summary:", flush=True)
    print(f"  FTE drivers: {result.kpi.get('drivers_fte', 0)}", flush=True)
    print(f"  PT drivers: {result.kpi.get('drivers_pt', 0)}", flush=True)
    
    # Print driver details
    print(f"\nDriver Details:", flush=True)
    for a in result.assignments[:10]:  # First 10
        print(f"  {a.driver_id}: {a.total_hours:.1f}h, {a.days_worked} days, {len(a.blocks)} blocks", flush=True)
    
    if len(result.assignments) > 10:
        print(f"  ... and {len(result.assignments) - 10} more drivers", flush=True)
    
    print("\n" + "=" * 70, flush=True)
    print("TEST COMPLETE", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
