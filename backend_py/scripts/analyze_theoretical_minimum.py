"""
Calculate theoretical minimum FTE from forecast data.
"""
import csv
from datetime import datetime

# Parse CSV
total_hours = 0
total_tours = 0

with open('forecast_test.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f, delimiter=';')
    
    current_day = None
    for row in reader:
        if len(row) >= 2:
            if row[1] == 'Anzahl':  # Header for new day
                current_day = row[0]
                print(f"\n{current_day}:")
                continue
            
            # Parse time range and count
            time_range = row[0]
            count = int(row[1])
            
            # Parse duration (e.g., "04:45-09:15")
            if '-' in time_range:
                start, end = time_range.split('-')
                start_h, start_m = map(int, start.split(':'))
                end_h, end_m = map(int, end.split(':'))
                
                # Calculate duration
                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m
                duration_min = end_min - start_min
                duration_h = duration_min / 60
                
                tour_hours = duration_h * count
                total_hours += tour_hours
                total_tours += count
                
                print(f"  {time_range}: {count} tours × {duration_h:.2f}h = {tour_hours:.1f}h")

print(f"\n{'='*60}")
print(f"TOTAL STATISTICS")
print(f"{'='*60}")
print(f"Total Tours: {total_tours}")
print(f"Total Hours: {total_hours:.1f}h")
print(f"Avg Duration per Tour: {total_hours/total_tours:.2f}h")
print(f"\n{'='*60}")
print(f"THEORETICAL MINIMUM (6-Day Week)")
print(f"{'='*60}")

# Theoretical minimum calculations
print(f"\nTarget: 40h/week FTE")
print(f"  → Minimum FTE: {total_hours / 40:.1f} drivers")
print(f"  → With 10% buffer: {(total_hours / 40) * 1.1:.1f} drivers")

print(f"\nTarget: 45h/week FTE (high utilization)")
print(f"  → Minimum FTE: {total_hours / 45:.1f} drivers")
print(f"  → With 10% buffer: {(total_hours / 45) * 1.1:.1f} drivers")

print(f"\nTarget: 38h/week FTE (union standard)")
print(f"  → Minimum FTE: {total_hours / 38:.1f} drivers")
print(f"  → With 10% buffer: {(total_hours / 38) * 1.1:.1f} drivers")

print(f"\n{'='*60}")
print(f"ACTUAL RESULTS COMPARISON")
print(f"{'='*60}")

actual_results = [
    ("V2 Current", 659, total_hours / 659),
    ("V2 Phase 1", 734, total_hours / 734),
    ("V4 Baseline", 381, total_hours / 381),
]

for name, drivers, avg_h in actual_results:
    util_pct = (avg_h / 40) * 100
    efficiency = (total_hours / 40) / drivers * 100
    print(f"\n{name}:")
    print(f"  Drivers: {drivers}")
    print(f"  Avg Hours/Driver: {avg_h:.1f}h")
    print(f"  Utilization: {util_pct:.1f}%")
    print(f"  Efficiency vs Theoretical: {efficiency:.1f}%")

print(f"\n{'='*60}")
print(f"GAP TO THEORETICAL OPTIMUM")
print(f"{'='*60}")

theoretical_40h = total_hours / 40
for name, drivers, _ in actual_results:
    gap = drivers - theoretical_40h
    gap_pct = (gap / theoretical_40h) * 100
    print(f"{name}: +{gap:.0f} drivers (+{gap_pct:.0f}% over theoretical)")
