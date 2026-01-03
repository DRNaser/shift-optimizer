import sys
from pathlib import Path
import hashlib
import time

# Add backend path
sys.path.insert(0, str(Path(__file__).parent / "backend_py"))

from test_forecast_csv import parse_forecast_csv
from run_block_heuristic import partition_tours_into_blocks
from src.services.smart_block_builder import BlockGenOverrides
from src.services.block_heuristic_solver import BlockHeuristicSolver

def calculate_hash(obj_str):
    return hashlib.md5(obj_str.encode()).hexdigest()[:8]

def perform_golden_run():
    print("=== GOLDEN RUN: BLOCK HEURISTIC SOLVER v1 (SEED 94) ===")
    
    # 1. Input Loading
    input_file = Path(__file__).parent / "forecast input.csv"
    if not input_file.exists():
        input_file = Path(__file__).parent / "forecast_kw51.csv"
        
    tours = parse_forecast_csv(str(input_file))
    input_hash = calculate_hash(str(sorted([t.id for t in tours])))
    print(f"[Audit] Input: {len(tours)} tours loaded. Hash: {input_hash}")
    
    # 2. Partitioning (Restoring Determinism via Seed 24)
    # The partition function in run_block_heuristic now defaults to Seed 24.
    overrides = BlockGenOverrides(
        max_pause_regular_minutes=60,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
        max_daily_span_hours=16.0,
        enable_split_blocks=True
    )
    
    start_time = time.time()
    blocks = partition_tours_into_blocks(tours, overrides)
    
    # Audit Partition
    tours_in_blocks = set()
    for b in blocks:
        for t in b.tours:
            if t.id in tours_in_blocks:
                print(f"[FAIL] Tour {t.id} duplicated in partition!")
                sys.exit(1)
            tours_in_blocks.add(t.id)
            
    missing = set(t.id for t in tours) - tours_in_blocks
    if missing:
        print(f"[FAIL] {len(missing)} tours missing from partition!")
        sys.exit(1)
        
    print(f"[Audit] Partition Valid. {len(blocks)} blocks. All tours unique & covered.")
    
    # 3. Solve (Flow)
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve(target_fte_count=145)
    solve_time = time.time() - start_time
    
    print(f"\n=== SOLVER AUDIT ===")
    print(f"Runtime: {solve_time:.4f}s")
    print(f"Total Drivers: {len(drivers)}")
    
    # 4. Detailed Audits
    
    # A. Coverage Audit (Blocks -> Drivers)
    blocks_in_drivers = set()
    for d in drivers:
        for b in d.blocks:
            if b.id in blocks_in_drivers:
                print(f"[FAIL] Block {b.id} assigned to multiple drivers!")
                sys.exit(1)
            blocks_in_drivers.add(b.id)
            
    all_block_ids = set(b.id for b in blocks)
    missing_blocks = all_block_ids - blocks_in_drivers
    if missing_blocks:
        print(f"[FAIL] {len(missing_blocks)} blocks not assigned to any driver!")
        sys.exit(1)
    print(f"[PASS] Coverage Audit: 100% Blocks assigned exactly once.")
    
    # B. Rest Audit (11h)
    rest_violations = 0
    day_map = {'Mon':0, 'Tue':1, 'Wed':2, 'Thu':3, 'Fri':4, 'Sat':5}
    
    for d in drivers:
        # Sort by Day Index THEN Time
        sorted_blocks = sorted(d.blocks, key=lambda b: (day_map[b.day.value], b.first_start))
        
        for i in range(len(sorted_blocks) - 1):
            b1 = sorted_blocks[i]
            b2 = sorted_blocks[i+1]
            
            end_min = b1.last_end.hour * 60 + b1.last_end.minute
            start_min = b2.first_start.hour * 60 + b2.first_start.minute
            
            diff = day_map[b2.day.value] - day_map[b1.day.value]
            
            gap = (start_min + diff * 1440) - end_min
            if gap < 11 * 60:
                print(f"[FAIL] Rest Violation Driver {d.id}: {b1.day} End {b1.last_end} -> {b2.day} Start {b2.first_start} (Gap {gap/60:.2f}h)")
                rest_violations += 1
                
    if rest_violations == 0:
        print(f"[PASS] Rest Audit: 0 Violations (11h rule).")
    else:
        print(f"[FAIL] Rest Audit: {rest_violations} Violations found!")
        sys.exit(1)
        
    # C. Overlap Audit
    # Ensure no blocks overlap in time for same driver
    overlap_violations = 0
    for d in drivers:
        sorted_blks = sorted(d.blocks, key=lambda b: (day_map[b.day.value], b.first_start))
        for i in range(len(sorted_blks) - 1):
            b1 = sorted_blks[i]
            b2 = sorted_blks[i+1]
            if b1.day != b2.day: continue
            
            if b1.last_end > b2.first_start: # Simple datetime comparison if same day
                 # Actually strictly > 
                 # If end == start, it's 0 gap, physically impossible without teleport?
                 # But logically distinct.
                 # Let's check mins
                 e = b1.last_end.hour*60 + b1.last_end.minute
                 s = b2.first_start.hour*60 + b2.first_start.minute
                 if e > s:
                     print(f"[FAIL] Overlap Driver {d.id}: {b1.id} ends {e} > {b2.id} starts {s}")
                     overlap_violations += 1
                     
    if overlap_violations == 0:
        print(f"[PASS] Overlap Audit: 0 Violations.")
    else:
        print(f"[FAIL] Overlap Audit: {overlap_violations} Violations!")
        sys.exit(1)

    # 5. KPI Verification
    pt_drivers = [d for d in drivers if d.total_hours < 40.0]
    fte_drivers = [d for d in drivers if d.total_hours >= 40.0]
    
    print(f"\n=== KPI CHECK ===")
    print(f"Drivers: {len(drivers)} (Target <= 150)")
    print(f"PT Count: {len(pt_drivers)} (Target 0-10)")
    
    if len(drivers) > 150:
        print(f"[FAIL] Driver count {len(drivers)} exceeds target 150!")
        sys.exit(1)
        
    if len(pt_drivers) > 0:
        print(f"[WARN] PT Count {len(pt_drivers)} > 0. (Ideal is 0)")
        # Strict "Golden" might allow 0-5?
        # Current result is 0. So fail if > 0 checking regression.
        if len(pt_drivers) > 0:
            print("[FAIL] Regression: Previous run had 0 PTs.")
            sys.exit(1)
            
    print("[PASS] All KPIs Met.")
    print("=== GOLDEN RUN SUCCESSFUL ===")

if __name__ == "__main__":
    perform_golden_run()
