"""Test singleton columns with forecast-test.txt data"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from datetime import time
from src.services.portfolio_controller import run_portfolio
from src.services.forecast_solver_v4 import ConfigV4

# Parse forecast-test.txt
day_map = {
    "Montag": Weekday.MONDAY,
    "Dienstag": Weekday.TUESDAY,
    "Mittwoch": Weekday.WEDNESDAY,
    "Donnerstag": Weekday.THURSDAY,
    "Freitag": Weekday.FRIDAY,
    "Samstag": Weekday.SATURDAY,
}

tours = []
current_day = None
tour_id_counter = 0

with open(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        
        # Check if this is a day header
        day_detected = False
        for day_name, day_enum in day_map.items():
            if day_name in line:
                current_day = day_enum
                day_detected = True
                break
        
        if day_detected or "Anzahl" in line:
            continue
        
        # Parse time slot and count
        parts = line.split("\t")
        if len(parts) >= 2 and current_day is not None:
            time_slot = parts[0].strip()
            try:
                count = int(parts[1].strip())
            except (ValueError, IndexError):
                continue
            
            if "-" in time_slot:
                start_str, end_str = time_slot.split("-")
                try:
                    start_h, start_m = map(int, start_str.split(":"))
                    end_h, end_m = map(int, end_str.split(":"))
                    
                    # Create 'count' tours for this time slot
                    for i in range(count):
                        tour_id_counter += 1
                        tours.append(Tour(
                            id=f"T{tour_id_counter:04d}",
                            day=current_day,
                            start_time=time(start_h, start_m),
                            end_time=time(end_h, end_m)
                        ))
                except ValueError:
                    continue

print(f"\n{'='*70}")
print(f"FORECAST-TEST.TXT DATA LOADED")
print(f"{'='*70}")
print(f"Total tours: {len(tours)}")

# Count by day
from collections import Counter
day_counts = Counter(t.day for t in tours)
for day in sorted(day_counts.keys(), key=lambda d: list(Weekday).index(d)):
    print(f"  {day.value}: {day_counts[day]} tours")

total_hours = sum(t.duration_hours for t in tours)
print(f"Total hours: {total_hours:.1f}h")
print(f"Expected FTE (42-53h): {int(total_hours/53)} - {int(total_hours/42)}")
print(f"{'='*70}\n")

# Run solver with singleton columns
config = ConfigV4(seed=42)

# Custom log function to capture singleton messages
singleton_logs = []
def log_fn(msg):
    if "singleton" in msg.lower() or "pool after" in msg.lower():
        print(msg)
        singleton_logs.append(msg)

print("Running solver with time_budget=600s...")
result = run_portfolio(tours, time_budget=600, seed=42, config=config, log_fn=log_fn)

print(f"\n{'='*70}")
print(f"RESULT")
print(f"{'='*70}")

if result.solution:
    kpi = result.solution.kpi
    print(f"Status: {kpi.get('status')}")
    print(f"Drivers: {kpi.get('drivers_fte', 0)} FTE + {kpi.get('drivers_pt', 0)} PT")
    print(f"Total: {kpi.get('drivers_fte', 0) + kpi.get('drivers_pt', 0)} drivers")
    print(f"Blocks: {kpi.get('blocks_3er', 0)}x3er + {kpi.get('blocks_2er', 0)}x2er + {kpi.get('blocks_1er', 0)}x1er")
    print(f"Runtime: {kpi.get('solve_time_total', 0):.1f}s")
else:
    print("FAILED - No solution")

print(f"\n{'='*70}")
print(f"SINGLETON COLUMNS TEST")
print(f"{'='*70}")
if singleton_logs:
    print(f"[OK] Singleton columns detected in logs:")
    for log in singleton_logs[:5]:  # Show first 5
        print(f"  {log}")
    if len(singleton_logs) > 5:
        print(f"  ... ({len(singleton_logs)} total singleton-related logs)")
else:
    print("[WARN] No singleton logs found (may indicate path didn't reach SP or logs filtered)")

print(f"{'='*70}")
