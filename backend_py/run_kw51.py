"""
Run KW51 Forecast (Mon, Tue, Wed, Fri only - Thu is Feiertag, Sat no data)
With Contract-Based FTE/PT Classification (v7.3.0)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from test_forecast_csv import parse_forecast_csv
from src.services.portfolio_controller import run_portfolio
from src.services.kpi_recompute import recompute_kpis_from_roster
from fleet_counter import compute_fleet_peaks

import argparse
parser = argparse.ArgumentParser(description="Run KW51 Forecast")
parser.add_argument("--time-budget", type=float, default=120, help="Solver time budget")
parser.add_argument("--fte-pool-size", type=int, default=176, help="Contract FTE pool size")
args = parser.parse_args()

# Use the filtered forecast
csv_path = Path(__file__).parent.parent / "forecast_kw51_filtered.csv"

print("=" * 70)
print("KW51 FORECAST (Mon, Tue, Wed, Fri only)")
print(f"  Contract FTE Pool: {args.fte_pool_size}")
print("=" * 70)

# Parse tours
tours = parse_forecast_csv(str(csv_path))
print(f"\nLoaded {len(tours)} tours")

# Count by day
by_day = {}
for t in tours:
    by_day[t.day.value] = by_day.get(t.day.value, 0) + 1

print("\nTours by day:")
for day, count in sorted(by_day.items()):
    print(f"  {day}: {count}")

total_hours = sum(t.duration_hours for t in tours)
print(f"\nTotal hours: {total_hours:.1f}h")

# Fleet Counter
print("\n" + "=" * 70)
print("FLEET COUNTER")
print("=" * 70)
fleet = compute_fleet_peaks(tours, turnaround_minutes=5)
print(f"Global Peak: {fleet.global_peak_count} vehicles @ {fleet.global_peak_day.value} {fleet.global_peak_time.strftime('%H:%M')}")
for day, peak in fleet.day_peaks.items():
    marker = " <- PEAK" if day == fleet.global_peak_day else ""
    print(f"  {day.value}: {peak.peak_count} vehicles @ {peak.peak_time.strftime('%H:%M')}{marker}")

# Run solver
print("\n" + "=" * 70)
print(f"Running solver (budget={args.time_budget}s)...")
print("=" * 70)

result = run_portfolio(tours, time_budget=args.time_budget, seed=42)

# Results
solution = result.solution
kpi = solution.kpi
assignments = solution.assignments

# ==========================================================================
# CONTRACT-BASED FTE/PT CLASSIFICATION (v7.3.0)
# ==========================================================================
fte_pool_size = args.fte_pool_size
drivers_total = len(assignments)
fte_used = min(drivers_total, fte_pool_size)
pt_used = max(0, drivers_total - fte_pool_size)

# Sort by hours (descending) for deterministic labeling
assignments.sort(key=lambda a: (-a.total_hours, getattr(a, 'driver_id', '')))

for idx, a in enumerate(assignments):
    if idx < fte_used:
        a.driver_type = "FTE"
        a.driver_id = f"FTE{idx + 1:03d}"
    else:
        a.driver_type = "PT"
        a.driver_id = f"PT{idx - fte_used + 1:03d}"

# Export
import csv
from src.domain.models import Weekday

output_dir = Path(__file__).parent
roster_file = output_dir / "roster_kw51.csv"

def format_time(t):
    return f"{t.hour:02d}:{t.minute:02d}"

day_map = {
    Weekday.MONDAY: "Mon",
    Weekday.TUESDAY: "Tue", 
    Weekday.WEDNESDAY: "Wed",
    Weekday.THURSDAY: "Thu",
    Weekday.FRIDAY: "Fri",
    Weekday.SATURDAY: "Sat"
}

rows = []
headers = ["Driver ID", "Type", "Weekly Hours", "Mon", "Tue", "Wed", "Fri"]

for assignment in assignments:
    if assignment.total_hours <= 0.01:
        continue
    row = {
        "Driver ID": assignment.driver_id,
        "Type": assignment.driver_type,
        "Weekly Hours": f"{assignment.total_hours:.2f}".replace('.', ','),
        "Mon": "", "Tue": "", "Wed": "", "Fri": ""
    }
    for block in assignment.blocks:
        day_str = day_map.get(block.day)
        if day_str and day_str in headers:
            start = format_time(block.first_start)
            end = format_time(block.last_end)
            try:
                b_type = block.block_type.value
            except:
                b_type = "Block"
            row[day_str] = f"{start}-{end} ({b_type})"
    rows.append(row)

with open(roster_file, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=headers, delimiter=";", extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)

print(f"\n[SUCCESS] Roster exported to: {roster_file}")
print(f"Total Drivers: {len(rows)}")

recomputed_kpis = recompute_kpis_from_roster(roster_file, active_days=kpi.get("active_days", []))
kpi.update(recomputed_kpis)

print(f"\n" + "=" * 70)
print("RESULT (Contract-Based Classification)")
print("=" * 70)
print(f"Status: {solution.status}")
print(f"Drivers: {kpi.get('drivers_fte', 0)} FTE + {kpi.get('drivers_pt', 0)} PT = {kpi.get('drivers_total', drivers_total)} Total")
print(f"  (FTE Pool: {fte_pool_size}, PT if drivers > pool)")
print(f"Active Days: {kpi.get('active_days', [])} (k={kpi.get('active_days_count', 0)})")
print(f"Fleet Peak: {kpi.get('fleet_peak_count', 0)} vehicles")
print(f"Drivers vs Peak: {kpi.get('drivers_vs_peak', 0)}")
print(f"Tours per Driver: {kpi.get('tours_per_driver', 0)}")

# FTE Hours Stats
if kpi.get("drivers_fte", 0) > 0:
    print(f"\nFTE Hours:")
    print(f"  Min: {kpi.get('fte_hours_min', 0):.1f}h, Max: {kpi.get('fte_hours_max', 0):.1f}h, Avg: {kpi.get('fte_hours_avg', 0):.1f}h")
