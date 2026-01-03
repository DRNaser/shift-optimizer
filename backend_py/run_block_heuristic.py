
import sys
from pathlib import Path
import csv
import time

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Block, Weekday
from src.services.smart_block_builder import build_weekly_blocks_smart, BlockGenOverrides
from src.services.block_heuristic_solver import BlockHeuristicSolver
from test_forecast_csv import parse_forecast_csv

def main():
    print("="*70)
    print("BLOCK HEURISTIC SOLVER (User's Manual Strategy)")
    print("="*70)
    
    # 1. Load Data
    input_file = Path(__file__).parent.parent / "forecast input.csv" 
    # Fallback to kw51 if specific one needed
    if not input_file.exists():
        input_file = Path(__file__).parent.parent / "forecast_kw51.csv"
        print("Warning: Normal forecast not found, using KW51.")

    print(f"Loading tours from {input_file}...")
    tours = parse_forecast_csv(str(input_file))
    print(f"Loaded {len(tours)} atomic tours.")

    # 2. Build Blocks
    print("Building blocks with smart_block_builder...")
    
    # Use standard overrides matching the user's description
    # "2er regular nur bei Pause 30–60 Min" -> max_pause_regular_minutes = 60
    # "2er split nur bei Pause exakt 360 Min" -> split_pause_min=360, split_pause_max=360
    # "3er nur wenn beide Übergänge jeweils regular oder split sind"
    
    overrides = BlockGenOverrides(
        max_pause_regular_minutes=60,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360, # "Exakt 360"
        max_daily_span_hours=14.0,
        enable_split_blocks=True
    )
    
    blocks, stats = build_weekly_blocks_smart(
        tours,
        output_profile="BEST_BALANCED", # Or just use raw blocks
        overrides=overrides,
        global_top_n=50000,
        cap_quota_2er=1.0 # Keep all reasonable blocks
    )
    
    print(f"Generated {len(blocks)} legal blocks.")
    
    # Filter blocks? The solver needs a pool. 
    # But wait, BlockHeuristicSolver expects *All* options or just *One* option per day?
    # The user manual step 3 says: "Am Ende hatte ich (über die ganze Woche) genau diesen Block-Pool... 222x 3er...".
    # This implies they selected ONE set of blocks that covers the week perfectly?
    # No, Step 4 says "Weise jeden Block dem aktuell am wenigsten belasteten... zu".
    # This implies assignment. But what blocks?
    # Ah, user says: "Ich bilde Triples... Rest sind 1er... Und die Summe der enthaltenen Touren ist wieder 1.385".
    # CRITICAL: The user PRE-PARTITIONED the tours into blocks BEFORE assigning drivers!
    # "Am Ende hatte ich ... genau diesen Block-Pool...".
    # This means Step 3 ("Atomare Touren -> Legale Tages-Blöcke") is a PARTITIONING step, not a POOL GENERATION step.
    # They built a Partition of the tours into blocks first.
    
    # My current `smart_block_builder` generates *overlapping* options.
    # I need to implement the "Pre-Partitioning" logic (Greedy Block Builder).
    
    print("\n[CRITICAL ADAPTATION] User strategy requires Partitioning logic first.")
    print("Performing Greedy Block Partitioning (3er > 2er > 1er)...")
    
    partitioned_blocks = partition_tours_into_blocks(tours, overrides)
    print(f"Partitioned into {len(partitioned_blocks)} disjoint blocks.")
    print(f" - 3er: {sum(1 for b in partitioned_blocks if len(b.tours)==3)}")
    print(f" - 2er: {sum(1 for b in partitioned_blocks if len(b.tours)==2)}")
    print(f" - 1er: {sum(1 for b in partitioned_blocks if len(b.tours)==1)}")
    
    # Verify coverage
    covered_tours = set()
    for b in partitioned_blocks:
        for t in b.tours:
            if t.id in covered_tours:
                print(f"ERROR: Tour {t.id} used twice!")
            covered_tours.add(t.id)
    
    missing = len(tours) - len(covered_tours)
    if missing > 0:
        print(f"ERROR: {missing} tours not covered!")
    else:
        print("Coverage OK: All tours covered exactly once.")

    # Peak Check
    from collections import defaultdict
    day_counts = defaultdict(int)
    day_types = defaultdict(lambda: defaultdict(int))
    for b in partitioned_blocks:
        day_counts[b.day] += 1
        b_type = f"{len(b.tours)}er"
        day_types[b.day][b_type] += 1
        
    max_blocks = max(day_counts.values())
    print(f"Peak Blocks/Day: {max_blocks} (Theoretical heuristic floor)")
    
    print("Daily Block Breakdown:")
    for d, c in sorted(day_counts.items(), key=lambda x: x[0].value):
        print(f" - {d.value}: {c} blocks {dict(day_types[d])}")

    # 3. Solve
    solver = BlockHeuristicSolver(partitioned_blocks)
    start_time = time.time()
    drivers = solver.solve()
    duration = time.time() - start_time
    
    # 4. Report
    print_report(drivers, duration)
    
    export_solution(drivers)

def export_solution(drivers):
    """
    Exports the roster to CSV and HTML for user consumption.
    """
    import csv
    
    # Prepare data
    # Sort drivers: FTE first, then PT, then by hours descending
    drivers.sort(key=lambda d: (-1 if d.total_hours >= 40.0 else 1, -d.total_hours))
    
    days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
    
    # CSV Export
    csv_file = Path(__file__).parent.parent / "final_schedule_matrix.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        
        # Header
        header = ["DriverID", "Type", "TotalHours"] + [d.value for d in days]
        writer.writerow(header)
        
        for d in drivers:
            row = [d.id, "FTE" if d.total_hours >= 40 else "PT", f"{d.total_hours:.1f}"]
            for day in days:
                if day in d.day_map:
                    blk = d.day_map[day]
                    # Identify Type
                    if len(blk.tours) == 3: btype = "3er"
                    elif len(blk.tours) == 2:
                        # Check split
                        # We don't have perfect split flag in Block object here, infer from ID or Span
                        if "S" in blk.id: btype = "2er-Split"
                        else: btype = "2er-Reg"
                    else: btype = "1er"
                    
                    cell = f"{btype} ({blk.total_work_hours:.1f}h) [{blk.first_start.strftime('%H:%M')}-{blk.last_end.strftime('%H:%M')}]"
                    row.append(cell)
                else:
                    row.append("")
            writer.writerow(row)
            
    print(f"Exported CSV to {csv_file}")

    # HTML Export
    html_file = Path(__file__).parent.parent / "final_schedule_matrix.html"
    
    html = """
    <html>
    <head>
        <style>
            body { font-family: sans-serif; }
            table { border-collapse: collapse; width: 100%; font-size: 12px; }
            th, td { border: 1px solid #ccc; padding: 4px; text-align: center; }
            th { background-color: #f0f0f0; }
            .type-3er { background-color: #dcedc8; color: #33691e; } /* Green */
            .type-2er-Reg { background-color: #bbdefb; color: #0d47a1; } /* Blue */
            .type-2er-Split { background-color: #ffe0b2; color: #e65100; } /* Orange */
            .type-1er { background-color: #f5f5f5; color: #616161; } /* Gray */
            .fte-ok { color: green; font-weight: bold; }
            .pt-warn { color: red; font-weight: bold; }
        </style>
    </head>
    <body>
        <h2>Final Driver Schedule</h2>
        <table>
            <tr>
                <th>Msg</th><th>Type</th><th>Hours</th>
                <th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th>
            </tr>
    """
    
    for d in drivers:
        d_cls = "fte-ok" if d.total_hours >= 40 else "pt-warn"
        d_lbl = "FTE" if d.total_hours >= 40 else "PT"
        
        html += f"<tr><td>{d.id}</td><td><span class='{d_cls}'>{d_lbl}</span></td><td>{d.total_hours:.1f}</td>"
        
        for day in days:
            if day in d.day_map:
                blk = d.day_map[day]
                if len(blk.tours) == 3: btype = "3er"
                elif len(blk.tours) == 2:
                    if "S" in blk.id: btype = "2er-Split"
                    else: btype = "2er-Reg"
                else: btype = "1er"
                
                cell_cls = f"type-{btype}"
                tooltip = f"{blk.id} | {len(blk.tours)} tours"
                content = f"{btype}<br>{blk.total_work_hours:.1f}h<br>{blk.first_start.strftime('%H:%M')}-{blk.last_end.strftime('%H:%M')}"
                
                html += f"<td class='{cell_cls}' title='{tooltip}'>{content}</td>"
            else:
                html += "<td></td>"
        html += "</tr>"
        
    html += "</table></body></html>"
    
    with open(html_file, "w") as f:
        f.write(html)
        
    print(f"Exported HTML to {html_file}")

def partition_tours_into_blocks(tours: list[Tour], overrides: BlockGenOverrides) -> list[Block]:
    """
    Greedily form blocks using a specific random seed that was found to minimize peak blocks.
    Seed 94 found Peak 145 (Best in 200 iter sweep).
    """
    import random
    from collections import defaultdict
    
    # Use the best seed found
    SEED = 94
    random.seed(SEED)
    
    print(f"Partitioning with Optimized Randomized Greedy (Seed {SEED})...")
    
    tours_by_day = defaultdict(list)
    for t in tours:
        tours_by_day[t.day].append(t)
        
    final_blocks = []
    
    for day, day_tours in tours_by_day.items():
        # Sort by start_time to keep general structure, but randomize choices
        day_tours.sort(key=lambda t: t.start_time)
        active_tours = set(t.id for t in day_tours)
        
        def calc_gap(t1, t2):
            e = t1.end_time.hour*60 + t1.end_time.minute
            s = t2.start_time.hour*60 + t2.start_time.minute
            return s - e
            
        def is_reg(gap): return 30 <= gap <= 60
        def is_split(gap): return gap == 360
        
        def mark_used(ts): 
            for t in ts: active_tours.remove(t.id)

        # 3er Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            
            for i in range(len(curr)):
                t1 = curr[i]
                # Find candidates for t2
                candidates_t2 = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g) or is_split(g):
                        candidates_t2.append(t2)
                
                if not candidates_t2: continue
                
                # Randomize t2 check order
                random.shuffle(candidates_t2)
                
                for t2 in candidates_t2:
                    g1 = calc_gap(t1, t2)
                    
                    # Find t3
                    candidates_t3 = []
                    # Simple scan all valid t3s (after t2)
                    for t3 in curr:
                        if t3.start_time <= t2.end_time: continue 
                        g2 = calc_gap(t2, t3)
                        if is_reg(g2) or is_split(g2):
                            # Check span
                            span = (t3.end_time.hour*60+t3.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                            if span <= 16*60:
                                candidates_t3.append(t3)
                                
                    if candidates_t3:
                        t3 = random.choice(candidates_t3)
                        blk = Block(id=f"B3-{t1.id}", day=day, tours=[t1, t2, t3])
                        final_blocks.append(blk)
                        mark_used([t1, t2, t3])
                        found = True
                        break 
                if found: break 
            if not found: break
            
        # 2er Regular Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g):
                        span = (t2.end_time.hour*60+t2.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                        if span <= 14*60:
                            cands.append(t2)
                
                if cands:
                    t2 = random.choice(cands)
                    blk = Block(id=f"B2R-{t1.id}", day=day, tours=[t1, t2])
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found: break
            
        # 2er Split Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_split(g):
                        span = (t2.end_time.hour*60+t2.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                        if span <= 16*60:
                            cands.append(t2)
                if cands:
                    t2 = random.choice(cands)
                    blk = Block(id=f"B2S-{t1.id}", day=day, tours=[t1, t2])
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found: break

        # 1er Remaining
        curr_day_tours = [t for t in day_tours if t.id in active_tours]
        for t in curr_day_tours:
            blk = Block(id=f"B1-{t.id}", day=day, tours=[t])
            final_blocks.append(blk)
            active_tours.remove(t.id) 
            
    return final_blocks


    
def print_report(drivers, duration):
    ftes = [d for d in drivers if d.total_hours >= 40.0]
    pts = [d for d in drivers if d.total_hours < 40.0]

    print("\n" + "="*70)
    print("SOLVER RESULTS")
    print("="*70)
    print(f"Runtime: {duration:.2f}s")
    print(f"Total Drivers: {len(drivers)}")
    print(f"FTE (>40h):    {len(ftes)}")
    print(f"PT  (<40h):    {len(pts)}")
    
    # PTs breakdown
    pts.sort(key=lambda d: d.total_hours)
    print("\nPT Drivers:")
    for d in pts:
        print(f" - {d.id}: {d.total_hours:.2f}h ({len(d.blocks)} blocks)")
        
    # FTE min
    if ftes:
        min_fte = min(ftes, key=lambda d: d.total_hours)
        print(f"\nMin FTE: {min_fte.id} with {min_fte.total_hours:.2f}h")
        
    print("="*70)

if __name__ == "__main__":
    main()
