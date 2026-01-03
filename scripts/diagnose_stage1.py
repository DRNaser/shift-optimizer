"""
Diagnostic: Simulate Stage 1 Subset Selection to check for Coverage Loss.
"""

import sys
sys.path.insert(0, 'backend_py/src')

from core_v2.model.tour import TourV2
from core_v2.model.duty import DutyV2
from core_v2.model.column import ColumnV2
from core_v2.model.weektype import WeekCategory
from core_v2.seeder import GreedyWeeklySeeder
from core_v2.validator.rules import ValidatorV2
from core_v2.duty_factory import DutyFactoryTopK

import csv
from pathlib import Path
from collections import Counter

# --- LOAD TOURS (Reuse from diagnose_pool.py) ---
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
    print("=" * 60)
    print("STAGE 1 DIAGNOSTIC: Subset Selection Coverage Check")
    print("=" * 60)
    
    tours = load_kw51_tours()
    all_tour_ids = set(t.tour_id for t in tours)
    print(f"Loaded {len(tours)} tours")
    
    # 1. Generate Pool (Seeds)
    tours_by_day = {}
    for t in tours: tours_by_day.setdefault(t.day, []).append(t)
    seeder = GreedyWeeklySeeder(tours_by_day, target_seeds=5000, validator=ValidatorV2)
    columns = seeder.generate_seeds()
    print(f"Pool Generated: {len(columns)} columns")
    
    # 2. Simulate Optimization Run State
    # In a real run, we have ~45k columns.
    # Singletons are generated FIRST (Seed), so they are at index 0..N.
    # Good columns are generated LATER (CG), so they are at index N..M.
    # To simulate this, we will duplicate the 'good' columns to inflate the pool size,
    # keeping singletons at the start (OLD).
    
    singletons = [c for c in columns if c.is_singleton]
    multidays = [c for c in columns if not c.is_singleton]
    
    print(f"  Singletons: {len(singletons)} (Oldest)")
    print(f"  Multi-day:  {len(multidays)}")
    
    # Inflate pool to 45,000 to match production crash
    # Order: Singletons, then copies of Multi-day (simulating CG finding better cols)
    # CRITICAL: In real CG, these are DISTINCT objects.
    from dataclasses import replace
    
    inflated_pool = list(singletons) # Keep singletons (Oldest)
    
    # Create distinct copies of multi-days to simulate new columns
    # We loop through multidays repeatedly, but create new objects
    count_needed = 45000 - len(inflated_pool)
    print(f"  generating {count_needed} distinct multi-day clones...")
    
    clones = []
    base_idx = 0
    while len(clones) < count_needed:
        base_col = multidays[base_idx % len(multidays)]
        # Create a distinct clone (different object, same content)
        # We assume distinctness in Python's 'is' check, which 'set' uses if not hashing by content?
        # ColumnV2 is frozen and hashable... set uses hash + eq.
        # If hash is same, set treats them as same.
        # In real run, CG columns have different IDs. 
        # So we MUST change ID or Signature.
        new_col = replace(base_col, col_id=f"sim_{len(clones)}") 
        clones.append(new_col)
        base_idx += 1
        
    inflated_pool.extend(clones)
    inflated_pool = inflated_pool[:45000] # Cap exact
    
    print(f"Simulated Runtime Pool: {len(inflated_pool)} columns")
    print("  (Singletons are at indices 0-1200, protecting them from 'Newest' strategy)")
    
    # 3. Apply Subset Selection Logic (from optimizer_v2.py)
    # CONFIG
    MIP_SUBSET_CAP = 20_000
    ELITE_RATIO = 0.8
    WEEK_CAT = WeekCategory.COMPRESSED # KW51 is likely compressed
    
    print("\n--- Applying Selection Logic ---")
    print(f"  Cap: {MIP_SUBSET_CAP}")
    print(f"  Elite: {int(MIP_SUBSET_CAP * ELITE_RATIO)}")
    print(f"  Newest: {MIP_SUBSET_CAP - int(MIP_SUBSET_CAP * ELITE_RATIO)}")
    
    # LOGIC START
    # Sort by cost (Elite)
    # Note: cost_utilization punishes singletons (+0.2) + low hours
    sorted_by_cost = sorted(inflated_pool, key=lambda c: c.cost_utilization(WEEK_CAT))
    
    # DEBUG: Print cost examples
    print("\nDEBUG COSTS:")
    print(f"  First (Best): {sorted_by_cost[0].cost_utilization(WEEK_CAT):.2f} (Singleton? {sorted_by_cost[0].is_singleton})")
    print(f"  Last (Worst): {sorted_by_cost[-1].cost_utilization(WEEK_CAT):.2f} (Singleton? {sorted_by_cost[-1].is_singleton})")
    
    # Check singleton costs
    singleton_costs = [c.cost_utilization(WEEK_CAT) for c in singletons]
    print(f"  Singleton Cost Range: {min(singleton_costs):.2f} - {max(singleton_costs):.2f}")
    
    elite_count = int(MIP_SUBSET_CAP * ELITE_RATIO)
    newest_count = MIP_SUBSET_CAP - elite_count
    
    subset_cols = list(sorted_by_cost[:elite_count])
    print(f"  Selected {len(subset_cols)} Elite columns")
    
    # Check if singletons are in Elite
    sing_in_elite = sum(1 for c in subset_cols if c.is_singleton)
    print(f"  Singletons in Elite: {sing_in_elite}")
    
    # Add newest (from back of the original list)
    limit_idx = len(inflated_pool)
    added_new = 0
    # Use set for fast lookup
    subset_set = set(subset_cols) # Object identity
    
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
    # LOGIC END
    
    # 4. Verification Check
    print("\n" + "=" * 60)
    print("VERIFICATION: Subset Coverage")
    print("=" * 60)
    
    covered_tours = set()
    for col in subset_cols:
        covered_tours.update(col.covered_tour_ids)
        
    missing_tours = all_tour_ids - covered_tours
    zero_coverage_rows_in_stage1_subset = len(missing_tours)
    
    print(f"zero_coverage_rows_in_stage1_subset = {zero_coverage_rows_in_stage1_subset}")
    
    if zero_coverage_rows_in_stage1_subset > 0:
        print("\n[FAIL] CRITICAL COVERAGE LOSS detected!")
        print("Example 20 Missing Tour IDs:")
        for tid in sorted(missing_tours)[:20]:
            print(f"  {tid}")
            
        print("\nAnalysis:")
        # Check rank of singletons in sorted list
        print("Why were singletons dropped?")
        singleton_ranks = []
        for i, col in enumerate(sorted_by_cost):
            if col.is_singleton:
                singleton_ranks.append(i)
        
        if singleton_ranks:
            print(f"  Best Singleton Rank: {min(singleton_ranks)}")
            print(f"  Avg Singleton Rank: {sum(singleton_ranks)/len(singleton_ranks):.1f}")
            print(f"  Elite Cutoff Index: {elite_count}")
            print("  -> Singletons are too expensive for Elite set.")
            print("  -> Singletons are too old (index 0) for Newest set.")
    else:
        print("\n[PASS] Subset covers all tours.")

if __name__ == "__main__":
    main()
