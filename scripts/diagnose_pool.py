"""
Diagnostic: Analyze pool column structure to find why only singletons are selected.
"""

import sys
sys.path.insert(0, 'backend_py/src')

from core_v2.model.tour import TourV2
from core_v2.model.duty import DutyV2
from core_v2.model.column import ColumnV2
from core_v2.seeder import GreedyWeeklySeeder
from core_v2.validator.rules import ValidatorV2
from core_v2.duty_factory import DutyFactoryTopK

import csv
from pathlib import Path
from collections import Counter

# Load KW51 tours
def load_kw51_tours():
    forecast_path = Path("forecast_kw51.csv")
    tours = []
    
    day_map = {'Montag': 0, 'Dienstag': 1, 'Mittwoch': 2, 'Donnerstag': 3, 'Freitag': 4}
    current_day = -1
    
    with open(forecast_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row or len(row) < 2:
                continue
                
            first_col = row[0].strip()
            
            # Check if this is a header row for a day
            if first_col in day_map:
                current_day = day_map[first_col]
                continue
            
            # Skip if we haven't found a day yet or it's Thursday (Holiday)
            if current_day == -1 or current_day == 3:
                continue
                
            # Parse time range: "03:30-08:00"
            if '-' in first_col:
                parts = first_col.split('-')
                if len(parts) != 2:
                    continue
                    
                start_str, end_str = parts
                count_str = row[1]
                
                try:
                    count = int(count_str)
                except ValueError:
                    continue
                
                def parse_time(t):
                    h, m = map(int, t.split(':'))
                    return h * 60 + m
                
                try:
                    start_min = parse_time(start_str)
                    end_min = parse_time(end_str)
                except ValueError:
                    continue
                
                # Handle cross-midnight
                if end_min < start_min:
                    end_min += 1440
                
                duration = end_min - start_min
                
                # Create 'count' copies of this tour
                for _ in range(count):
                    tour_id = f"T_{current_day}_{start_min:04d}_{end_min:04d}_{len(tours)}"
                    
                    tour = TourV2(
                        tour_id=tour_id,
                        day=current_day,
                        start_min=start_min,
                        end_min=end_min,
                        duration_min=duration
                    )
                    tours.append(tour)
    
    return tours

def main():
    print("=" * 60)
    print("POOL DIAGNOSTIC: Multi-Day Column Analysis")
    print("=" * 60)
    
    tours = load_kw51_tours()
    print(f"Loaded {len(tours)} tours")
    
    # Group by day
    tours_by_day = {}
    for t in tours:
        tours_by_day.setdefault(t.day, []).append(t)
    
    for d, tlist in sorted(tours_by_day.items()):
        print(f"  Day {d}: {len(tlist)} tours")
    
    # Generate seed pool
    seeder = GreedyWeeklySeeder(tours_by_day, target_seeds=5000, validator=ValidatorV2)
    columns = seeder.generate_seeds()
    
    print(f"\nPool Size: {len(columns)}")
    
    # Analyze days_worked distribution
    days_dist = Counter(col.days_worked for col in columns)
    print("\nDays Worked Distribution:")
    for days, count in sorted(days_dist.items()):
        pct = 100.0 * count / len(columns)
        print(f"  {days}-day columns: {count} ({pct:.1f}%)")
    
    # Analyze hours distribution for multi-day columns
    multi_day_cols = [c for c in columns if c.days_worked >= 2]
    if multi_day_cols:
        hours = [c.hours for c in multi_day_cols]
        print(f"\nMulti-Day Column Hours (n={len(multi_day_cols)}):")
        print(f"  Min: {min(hours):.1f}h, Max: {max(hours):.1f}h, Avg: {sum(hours)/len(hours):.1f}h")
        
        # Check which days are combined
        day_combos = Counter()
        for c in multi_day_cols:
            days = tuple(sorted(d.day for d in c.duties))
            day_combos[days] += 1
        
        print(f"\nDay Combination Patterns:")
        for combo, count in day_combos.most_common(10):
            print(f"  Days {combo}: {count} columns")
    else:
        print("\n[ERROR] NO multi-day columns in pool!")
    
    # Check for tiling issue: coverage overlap
    print("\n" + "=" * 60)
    print("TILING ANALYSIS: Tour Coverage Overlap")
    print("=" * 60)
    
    # Build tour -> columns mapping
    tour_to_cols = {}
    for i, col in enumerate(columns):
        for tid in col.covered_tour_ids:
            tour_to_cols.setdefault(tid, []).append(i)
    
    # Count tours with low coverage (fewer column options)
    coverage_counts = Counter(len(cols) for cols in tour_to_cols.values())
    print("\nTours by Number of Covering Columns:")
    for count, num_tours in sorted(coverage_counts.items())[:10]:
        print(f"  {count} columns: {num_tours} tours")
    
    # Find tours with NO multi-day coverage
    multi_day_coverage = set()
    for col in multi_day_cols:
        multi_day_coverage.update(col.covered_tour_ids)
    
    all_tour_ids = set(t.tour_id for t in tours)
    tours_no_multiday = all_tour_ids - multi_day_coverage
    
    print(f"\nTours with NO multi-day column coverage: {len(tours_no_multiday)}/{len(all_tour_ids)}")
    if len(tours_no_multiday) > 0 and len(tours_no_multiday) < 20:
        for tid in sorted(tours_no_multiday):
            print(f"  {tid}")
    
    # Check if multi-day columns can tile (non-overlapping)
    print("\n" + "=" * 60)
    print("TILING TEST: Can multi-day columns cover without overlap?")
    print("=" * 60)
    
    # Simple greedy: try to select non-overlapping multi-day columns
    selected = []
    covered = set()
    
    # Sort by hours descending (prefer fuller rosters)
    sorted_multi = sorted(multi_day_cols, key=lambda c: -c.hours)
    
    for col in sorted_multi:
        # Check if this column overlaps with already covered tours
        if col.covered_tour_ids & covered:
            continue  # Skip - overlaps
        
        # Select this column
        selected.append(col)
        covered.update(col.covered_tour_ids)
    
    print(f"Greedy non-overlapping multi-day selection:")
    print(f"  Selected: {len(selected)} columns")
    print(f"  Covered: {len(covered)}/{len(all_tour_ids)} tours ({100.0*len(covered)/len(all_tour_ids):.1f}%)")
    
    remaining = all_tour_ids - covered
    print(f"  Remaining: {len(remaining)} tours need singleton coverage")
    
    if selected:
        hours = [c.hours for c in selected]
        print(f"  Hours: min={min(hours):.1f}h, max={max(hours):.1f}h, avg={sum(hours)/len(hours):.1f}h")
        
        days_counts = Counter(c.days_worked for c in selected)
        print(f"  Days breakdown: {dict(days_counts)}")

if __name__ == "__main__":
    main()
