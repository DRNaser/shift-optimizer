import sys
import os
import csv
import logging
from datetime import datetime, time as datetime_time
from typing import List
from collections import defaultdict

# Setup Project Path
sys.path.append(os.getcwd())

from src.api.run_manager import run_manager
from src.domain.models import Tour, Driver, Weekday
from src.services.forecast_solver_v4 import ConfigV4

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QualityVerifier")

CSV_PATH = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv"

def parse_forecast_csv(filepath: str) -> List[Tour]:
    tours = []
    current_day = Weekday.MONDAY
    
    day_map = {
        "Montag": Weekday.MONDAY,
        "Dienstag": Weekday.TUESDAY,
        "Mittwoch": Weekday.WEDNESDAY,
        "Donnerstag": Weekday.THURSDAY,
        "Freitag": Weekday.FRIDAY,
        "Samstag": Weekday.SATURDAY,
        "Sonntag": Weekday.SUNDAY
    }
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row: continue
            
            # Check if header row (Day name)
            if row[0] in day_map:
                current_day = day_map[row[0]]
                continue
                
            # Parse Time Slot: HH:MM-HH:MM
            try:
                times, count_str = row[0], row[1]
                start_str, end_str = times.split('-')
                count = int(count_str)
                
                start_time = datetime.strptime(start_str, "%H:%M").time()
                end_time = datetime.strptime(end_str, "%H:%M").time()
                
                # Expand aggregate counts into individual tours
                for i in range(count):
                    t = Tour(
                        id=f"{current_day.value}_{start_str}_{end_str}_{i}",
                        day=current_day,
                        start_time=start_time,
                        end_time=end_time
                    )
                    tours.append(t)
            except ValueError:
                continue # Skip malformed lines
                
    return tours

def analyze_result(result):
    print("\n" + "="*50)
    print("QUALITY ANALYSIS RESULTS") 
    print("="*50)
    
    if not result or not result.solution:
        print("Run Failed or No Solution")
        return

    sol = result.solution
    assigns = sol.assignments
    total_drivers = len(assigns)
    
    counts = defaultdict(int)
    singleton_users = []
    
    # Detailed Pattern Analysis
    pattern_322_split = 0
    pattern_322_other = 0
    
    for a in assigns:
        # Check hydration
        days_worked = len(a.blocks) 
        
        if days_worked > 0:
             counts[min(days_worked, 6)] += 1
             if days_worked == 1:
                 singleton_users.append(a.driver_id)
        
        # Check for 3-2-2 Pattern (3 days, 1x Triple, 2x Double)
        if days_worked == 3:
            # Analyze duty lengths (tours per day)
            # a.blocks is list of "Block" or similar hydrated objects. 
            # We assume blocks have `tours` list or length.
            # In V2 Adapter, blocks are hydrated as {day, start, end, tours[]} dict-like or objects?
            # Let's try to inspect safe attributes
            
            tour_counts = []
            has_split = False
            
            for b in a.blocks:
                # V2 Adapter hydration produces "Shift" objects or dicts?
                # Using getattr to be safe
                ts = getattr(b, 'tours', [])
                if not ts and isinstance(b, dict): ts = b.get('tours', [])
                
                c = len(ts)
                tour_counts.append(c)
                
                # Check split (gap > 60m implies split in V2 logic usually, but here checking name/type might be hard)
                # Proxy: Split usually has duration > certain amount with 2 tours? 
                # Actually user defined split as "PauseZone".
                # For now just count tour structure: [3, 2, 2] in any order
                
            tour_counts.sort()
            if tour_counts == [2, 2, 3]:
                pattern_322_split += 1 # Calling it this for now
                
    print(f"Total Drivers: {total_drivers}")
    print("-" * 30)
    for k in sorted(counts.keys()):
        if counts[k] > 0:
            pct = (counts[k] / total_drivers * 100) if total_drivers else 0
            print(f"{k}-Day Rosters: {counts[k]} ({pct:.1f}%)")
    
    print("-" * 30)
    print(f"Pattern '3-2-2' Count: {pattern_322_split}")
    
    p_singleton = (counts[1] / total_drivers * 100) if total_drivers else 0
    print(f"Singleton Rate: {p_singleton:.1f}%")
    
    target = 5.7
    if p_singleton <= target + 2.0:
        print("[PASS] Singleton rate matches Golden Standard!")
    elif p_singleton <= 15.0:
        print("[WARN] Singleton rate acceptable but higher than reference.")
    else:
        print("[FAIL] Singleton rate too high (Poor connectivity).")

    # Print Culprit Report from Logs
    print("\n" + "="*50)
    print("SOLVER LOGS (CULPRIT REPORT)")
    print("="*50)
    
    if hasattr(result, 'logs') and result.logs:
        in_report = False
        for line in result.logs:
            if "CULPRIT REPORT" in line:
                in_report = True
            
            if in_report:
                print(line)
                # Stop after the report block (detected by separator)
                if "-----" in line and "CULPRIT REPORT" not in line:
                    in_report = False
    else:
        print("No logs found in result.")

    return

def main():
    print(f"Loading Forecast: {CSV_PATH}")
    tours = parse_forecast_csv(CSV_PATH)
    print(f"Loaded {len(tours)} individual tours.")
    
    # Create Dummy Drivers (infinite pool essentially)
    drivers = [Driver(id=f"D{i}", name=f"Driver {i}") for i in range(1000)]
    
    # Config - FORCE CORE V2
    config = ConfigV4(target_ftes=200, seed=42, use_core_v2=True)  # Force V2!
    
    print("Starting Optimization Run (CORE V2 - FORCED)...")
    run_id = run_manager.create_run(
        tours=tours,
        drivers=drivers,
        config=config,
        time_budget=300.0,  # Safe budget for Core V2
        week_start=datetime.now().date()
    )
    
    import time
    while True:
        ctx = run_manager.get_run(run_id)
        if ctx.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            break
        print(f"Status: {ctx.status}...", end='\r')
        time.sleep(1)
        
    print(f"\nFinal Status: {ctx.status}")
    if ctx.result:
        analyze_result(ctx.result)
    else:
        print("No result object returned.")

if __name__ == "__main__":
    main()
