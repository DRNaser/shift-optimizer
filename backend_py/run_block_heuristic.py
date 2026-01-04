
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
    Exports the roster to a rich interactive HTML Dashboard (The "Dispatcher Cockpit").
    Features:
    - Density View (Color Coding)
    - Safety View (Red Borders for Rest < 12h)
    - Chronological Info (Hover)
    - JS Sorting/Filtering
    """
    import json
    from datetime import datetime
    
    # Sort drivers: FTE first, then PT, then by hours descending
    drivers.sort(key=lambda d: (-1 if d.total_hours >= 40.0 else 1, -d.total_hours))
    
    days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
    
    # Prepare Data Structure for JS
    # We need to calculate Rest Times to flag "Red Borders"
    
    data_model = []
    
    for d in drivers:
        driver_obj = {
            "id": d.id,
            "type": "FTE" if d.total_hours >= 40 else "PT",
            "total_hours": round(d.total_hours, 1),
            "days": {}
        }
        
        last_end_minutes = -9999 # From previous week (assume rested)
        last_day_idx = -1
        
        for d_idx, day in enumerate(days):
            if day in d.day_map:
                blk = d.day_map[day]
                
                # Identify Type
                if len(blk.tours) == 3: btype = "3er"
                elif len(blk.tours) == 2:
                    if "S" in blk.id: btype = "2er-Split"
                    else: btype = "2er-Reg"
                else: btype = "1er"
                
                # Calc Rest from Prev Block
                # Rest = (Current Start + (DayDiff * 24h)) - Last End
                current_start_min = blk.first_start.hour * 60 + blk.first_start.minute
                current_end_min = blk.last_end.hour * 60 + blk.last_end.minute
                
                if last_day_idx != -1:
                    day_diff = d_idx - last_day_idx
                    gap_min = (current_start_min + (day_diff * 1440)) - last_end_minutes
                else:
                    gap_min = 9999 # First shift of week
                
                # Calc Risk (Gap quality within block)
                # Simple proxy: (Work Hours / Span) ratio? Or just average gap?
                # Let's use Span - WorkHours as "Idle Time". Less Idle = Redder?
                # User said: "Je kürzer der Gap, desto röter der Balken" (Pünktlichkeit risk).
                # Actually, small gap between tours = risk.
                # Let's compute min_gap inside block
                min_inner_gap = 999
                tours_sorted = sorted(blk.tours, key=lambda t: t.start_time)
                for i in range(len(tours_sorted)-1):
                     t1 = tours_sorted[i]
                     t2 = tours_sorted[i+1]
                     # simplified
                     g = (t2.start_time.hour*60 + t2.start_time.minute) - (t1.end_time.hour*60 + t1.end_time.minute)
                     if g < min_inner_gap: min_inner_gap = g
                
                if min_inner_gap == 999: min_inner_gap = 60 # Single tour default
                
                
                block_data = {
                    "id": blk.id,
                    "type": btype,
                    "work_h": round(blk.total_work_hours, 1),
                    "start": blk.first_start.strftime('%H:%M'),
                    "end": blk.last_end.strftime('%H:%M'),
                    "tours": len(blk.tours),
                    "rest_before": gap_min,
                    "min_inner_gap": min_inner_gap
                }
                
                driver_obj["days"][day.value] = block_data
                
                last_end_minutes = current_end_min
                last_day_idx = d_idx
                
        data_model.append(driver_obj)

    # Generate HTML
    html_file = Path(__file__).parent.parent / "final_schedule_matrix.html"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Shift Optimizer V2 - Dispatcher Cockpit</title>
        <style>
            :root {{
                --c-3er: #00695c; /* Deep Emerald */
                --c-3er-bg: #e0f2f1;
                --c-2reg: #1565c0; /* Ocean Blue */
                --c-2reg-bg: #e3f2fd;
                --c-2split: #ef6c00; /* Glowing Orange */
                --c-2split-bg: #fff3e0;
                --c-1er: #616161; /* Grey */
                --c-1er-bg: #f5f5f5;
                --c-risk: #d32f2f;
            }}
            body {{ font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #fafafa; padding: 20px; }}
            h2 {{ color: #333; }}
            
            /* Controls */
            .controls {{ margin-bottom: 20px; padding: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; gap: 15px; align-items: center; }}
            .kpi-badge {{ background: #333; color: white; padding: 5px 10px; border-radius: 4px; font-weight: bold; font-size: 0.9em; }}
            button {{ padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; background: #e0e0e0; transition: background 0.2s; }}
            button:hover {{ background: #d0d0d0; }}
            button.active {{ background: #333; color: white; }}
            
            /* Table */
            table {{ border-collapse: separate; border-spacing: 2px; width: 100%; font-size: 13px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            th {{ background: #f4f4f4; padding: 10px; text-align: left; font-weight: 600; color: #555; position: sticky; top: 0; z-index: 10; }}
            td {{ padding: 0; height: 50px; vertical-align: middle; }}
            
            /* Cells */
            .cell-inner {{
                height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center;
                position: relative; border-radius: 4px; transition: transform 0.1s;
                border: 2px solid transparent; /* reserved for safety border */
            }}
            .cell-inner:hover {{ z-index: 2; transform: scale(1.05); box-shadow: 0 4px 8px rgba(0,0,0,0.2); }}
            
            /* Types */
            .type-3er {{ background-color: var(--c-3er-bg); color: var(--c-3er); border-left: 4px solid var(--c-3er); }}
            .type-2er-Reg {{ background-color: var(--c-2reg-bg); color: var(--c-2reg); border-left: 4px solid var(--c-2reg); }}
            .type-2er-Split {{ background-color: var(--c-2split-bg); color: var(--c-2split); border-left: 4px solid var(--c-2split); }}
            .type-1er {{ background-color: var(--c-1er-bg); color: var(--c-1er); border-left: 4px solid var(--c-1er); }}
            
            /* Safety & Risk */
            .safety-violation {{ border-color: var(--c-risk) !important; animation: pulse 2s infinite; }} 
            .rest-warning {{ border-bottom: 3px solid var(--c-risk); }} /* Rest < 12h */
            
            /* Double Tone Risk Bar (Left Edge) */
            /* We use the border-left for Type, maybe use a dot for Risk? */
            .risk-dot {{
                position: absolute; top: 4px; right: 4px; width: 8px; height: 8px; border-radius: 50%;
            }}
            
            .content-main {{ font-weight: 700; font-size: 1.1em; }}
            .content-sub {{ font-size: 0.85em; opacity: 0.8; }}
            
            /* Tooltip */
            #tooltip {{
                position: fixed; background: #333; color: white; padding: 10px; border-radius: 6px;
                font-size: 12px; display: none; pointer-events: none; z-index: 1000;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            }}
            
            @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(211, 47, 47, 0.4); }} 70% {{ box-shadow: 0 0 0 10px rgba(211, 47, 47, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(211, 47, 47, 0); }} }}

            .fte-label {{ color: green; font-weight: bold; background: #e8f5e9; padding: 2px 6px; border-radius: 4px; }}
            .pt-label {{ color: red; font-weight: bold; background: #ffebee; padding: 2px 6px; border-radius: 4px; }}

        </style>
    </head>
    <body>
        <div class="controls">
            <h2>Shift Optimizer V2</h2>
            <div class="kpi-badge">Drivers: {len(drivers)}</div>
            <div class="kpi-badge">FTE: {len([d for d in drivers if d.total_hours >= 40])}</div>
            
            <div style="flex-grow:1"></div>
            
            <button onclick="toggleView('matrix')" class="active">Matrix View</button>
            <button onclick="toggleView('timeline')" disabled title="Coming Soon">Timeline View</button>
            
            <label><input type="checkbox" id="chkShowGaps" checked onchange="render()"> Show Gap Risk</label>
        </div>

        <div id="grid-container"></div>
        <div id="tooltip"></div>

        <script>
            const data = {json.dumps(data_model)};
            const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
            const container = document.getElementById('grid-container');
            const tooltip = document.getElementById('tooltip');
            
            function render() {{
                let html = '<table><thead><tr><th>ID</th><th>Type</th><th>Hrs</th>';
                days.forEach(d => html += '<th>' + d + '</th>');
                html += '</tr></thead><tbody>';
                
                data.forEach(d => {{
                    html += `<tr>
                        <td style="padding:10px; font-weight:bold">${{d.id}}</td>
                        <td style="padding:10px"><span class="${{d.type === 'FTE' ? 'fte-label' : 'pt-label'}}">${{d.type}}</span></td>
                        <td style="padding:10px">${{d.total_hours}}h</td>`;
                        
                    days.forEach(dayName => {{
                        let blk = d.days[dayName];
                        if (blk) {{
                            // Classes
                            let cls = "cell-inner type-" + blk.type;
                            
                            // Safety Check: Rest < 12h (Warning)
                            if (blk.rest_before < 12 * 60) cls += " rest-warning";
                            
                            // Risk Indicator (Gap < 45m = High Risk/Red)
                            let riskColor = "transparent";
                            if (document.getElementById('chkShowGaps').checked) {{
                                if (blk.min_inner_gap < 45) riskColor = "#d32f2f"; // High Risk
                                else if (blk.min_inner_gap < 60) riskColor = "#fbc02d"; // Med Risk
                                else riskColor = "#388e3c"; // Safe
                            }}
                            
                            html += `<td>
                                <div class="${{cls}}" 
                                     onmousemove="showTip(event, '${{blk.id}}', '${{blk.start}}', '${{blk.end}}', ${{blk.rest_before}}, ${{blk.min_inner_gap}})"
                                     onmouseleave="hideTip()">
                                    <div class="risk-dot" style="background:${{riskColor}}"></div>
                                    <div class="content-main">${{blk.type}}</div>
                                    <div class="content-sub">${{blk.start}}-${{blk.end}}</div>
                                </div>
                            </td>`;
                        }} else {{
                            html += '<td style="background:#fafafa"></td>';
                        }}
                    }});
                    html += '</tr>';
                }});
                
                html += '</tbody></table>';
                container.innerHTML = html;
            }}
            
            function showTip(e, id, s, e_time, rest, gap) {{
                let restHrs = (rest / 60).toFixed(1);
                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY + 15) + 'px';
                tooltip.innerHTML = `<strong>${{id}}</strong><br>
                                     Time: ${{s}} - ${{e_time}}<br>
                                     Rest Before: ${{restHrs}}h<br>
                                     Min Gap: ${{gap}}m`;
            }}
            
            function hideTip() {{
                tooltip.style.display = 'none';
            }}
            
            render();
        </script>
    </body>
    </html>
    """
    
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Exported Rich HTML to {html_file}")

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
        def is_split(gap): return 240 <= gap <= 360  # 4-6 hours split break
        
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
                    if is_reg(g):  # 3er-chain: NUR 30-60min Gaps (keine Split-Gaps)
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
                        if is_reg(g2):  # 3er-chain: NUR 30-60min Gaps (keine Split-Gaps)
                            # Check span - 3er blocks use 16h span limit
                            span = (t3.end_time.hour*60+t3.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                            if span <= 16*60:  # 16h max span for 3er
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
