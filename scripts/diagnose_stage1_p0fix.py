"""
Diagnostic: Simulate Stage 1 Subset Selection WITH P0 FIX to verify coverage preservation.
"""

import sys
sys.path.insert(0, 'backend_py/src')

from core_v2.model.tour import TourV2
from core_v2.model.column import ColumnV2
from core_v2.model.weektype import WeekCategory
from core_v2.seeder import GreedyWeeklySeeder
from core_v2.validator.rules import ValidatorV2

import csv
from pathlib import Path
from dataclasses import replace

# --- LOAD TOURS ---
def load_kw51_tours():
    forecast_path = Path("forecast_kw51.csv")
    tours = []
    day_map = {'Montag': 0, 'Dienstag': 1, 'Mittwoch': 2, 'Donnerstag': 3, 'Freitag': 4}
    current_day = -1
    
    with open(forecast_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row or len(row) < 2: continue
            first_col = row[0].strip()
            if first_col in day_map:
                current_day = day_map[first_col]
                continue
            if current_day == -1 or current_day == 3: continue
            if '-' in first_col:
                parts = first_col.split('-')
                if len(parts) != 2: continue
                try:
                    count = int(row[1])
                    start_min = int(parts[0].split(':')[0])*60 + int(parts[0].split(':')[1])
                    end_min = int(parts[1].split(':')[0])*60 + int(parts[1].split(':')[1])
                    if end_min < start_min: end_min += 1440
                    for _ in range(count):
                        tour_id = f"T_{current_day}_{start_min:04d}_{end_min:04d}_{len(tours)}"
                        tours.append(TourV2(tour_id, current_day, start_min, end_min, end_min-start_min))
                except ValueError: continue
    return tours

def main():
    print("=" * 70)
    print("STAGE 1 DIAGNOSTIC (WITH P0 FIX): Subset Selection Coverage Check")
    print("=" * 70)
    
    tours = load_kw51_tours()
    all_tour_ids = set(t.tour_id for t in tours)
    print(f"Loaded {len(tours)} tours")
    
    # 1. Generate Pool (Seeds)
    tours_by_day = {}
    for t in tours: tours_by_day.setdefault(t.day, []).append(t)
    seeder = GreedyWeeklySeeder(tours_by_day, target_seeds=5000, validator=ValidatorV2)
    columns = seeder.generate_seeds()
    print(f"Pool Generated: {len(columns)} columns")
    
    singletons = [c for c in columns if c.is_singleton]
    multidays = [c for c in columns if not c.is_singleton]
    
    print(f"  Singletons: {len(singletons)} (Oldest)")
    print(f"  Multi-day:  {len(multidays)}")
    
    # 2. Inflate pool to 45,000 with distinct objects
    inflated_pool = list(singletons)
    count_needed = 45000 - len(inflated_pool)
    print(f"  generating {count_needed} distinct multi-day clones...")
    
    clones = []
    base_idx = 0
    while len(clones) < count_needed:
        base_col = multidays[base_idx % len(multidays)]
        new_col = replace(base_col, col_id=f"sim_{len(clones)}")
        clones.append(new_col)
        base_idx += 1
        
    inflated_pool.extend(clones)
    print(f"Simulated Runtime Pool: {len(inflated_pool)} columns")
    
    # 3. Apply P0 FIX LOGIC
    MIP_SUBSET_CAP = 20_000
    ELITE_RATIO = 0.8
    WEEK_CAT = WeekCategory.COMPRESSED
    
    print("\n--- Applying P0 FIX Selection Logic ---")
    print(f"  Cap: {MIP_SUBSET_CAP}")
    
    # P0 FIX: Prioritize singletons in sort
    sorted_by_cost = sorted(
        inflated_pool,
        key=lambda c: (0 if c.is_singleton else 1, c.cost_utilization(WEEK_CAT))
    )
    
    # Count singletons
    singleton_count = sum(1 for c in inflated_pool if c.is_singleton)
    print(f"  Singleton Count: {singleton_count}")
    
    # Adjust elite_count to guarantee all singletons
    elite_count = min(MIP_SUBSET_CAP, max(int(MIP_SUBSET_CAP * ELITE_RATIO), singleton_count))
    newest_count = MIP_SUBSET_CAP - elite_count
    
    print(f"  Elite (adjusted): {elite_count}")
    print(f"  Newest: {newest_count}")
    
    subset_cols = list(sorted_by_cost[:elite_count])
    
    # Check if singletons are in Elite
    sing_in_elite = sum(1 for c in subset_cols if c.is_singleton)
    print(f"  Singletons in Elite: {sing_in_elite}")
    
    # Add newest
    subset_set = set(subset_cols)
    limit_idx = len(inflated_pool)
    added_new = 0
    
    for i in range(limit_idx - 1, -1, -1):
        if added_new >= newest_count: break
        col = inflated_pool[i]
        if col not in subset_set:
            subset_cols.append(col)
            subset_set.add(col)
            added_new += 1
            
    print(f"  Selected {added_new} Newest columns")
    print(f"  Total Subset: {len(subset_cols)}")
    
    sing_total = sum(1 for c in subset_cols if c.is_singleton)
    print(f"  Total Singletons in Subset: {sing_total}")
    
    # 4. Verification Check
    print("\n" + "=" * 70)
    print("VERIFICATION: Subset Coverage")
    print("=" * 70)
    
    covered_tours = set()
    for col in subset_cols:
        covered_tours.update(col.covered_tour_ids)
        
    missing_tours = all_tour_ids - covered_tours
    zero_coverage_rows_in_stage1_subset = len(missing_tours)
    
    print(f"zero_coverage_rows_in_stage1_subset = {zero_coverage_rows_in_stage1_subset}")
    
    if zero_coverage_rows_in_stage1_subset > 0:
        print("\n[FAIL] Coverage loss detected!")
        print(f"Example {min(20, len(missing_tours))} Missing Tour IDs:")
        for tid in sorted(missing_tours)[:20]:
            print(f"  {tid}")
    else:
        print("\n[PASS] P0 FIX SUCCESS! Subset covers all tours.")
        print(f"  ✓ All {singleton_count} singletons included in subset")
        print(f"  ✓ Coverage preserved (100%)")

if __name__ == "__main__":
    main()
