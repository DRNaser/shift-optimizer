"""
O0: Culprit Coverage Snapshot

Analyzes singleton usage patterns for culprit time windows.
Must be run BEFORE any new seeding/generation to confirm gaps exist.
"""

import sys
import os
import csv
import logging
from collections import defaultdict
from datetime import datetime, time as datetime_time

# Setup Project Path
sys.path.append(os.getcwd())

from src.api.run_manager import run_manager
from src.domain.models import Tour, Driver, Weekday
from src.services.forecast_solver_v4 import ConfigV4

CSV_PATH = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv"

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CulpritAnalyzer")


def parse_forecast_csv(filepath: str):
    """Parse forecast CSV."""
    tours = []
    current_day = Weekday.MONDAY
    
    day_map = {
        "Montag": Weekday.MONDAY,
        "Dienstag": Weekday.TUESDAY,
        "Mittwoch": Weekday.WEDNESDAY,
        "Donnerstag": Weekday.THURSDAY,
        "Freitag": Weekday.FRIDAY,
        "Samstag": Weekday.SATURDAY,
    }
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row: continue
            
            if row[0] in day_map:
                current_day = day_map[row[0]]
                continue
                
            try:
                times, count_str = row[0], row[1]
                start_str, end_str = times.split('-')
                count = int(count_str)
                
                start_hour, start_min = map(int, start_str.split(':'))
                end_hour, end_min = map(int, end_str.split(':'))
                
                start_time = datetime_time(start_hour, start_min)
                end_time = datetime_time(end_hour, end_min)
                
                for i in range(count):
                    tour = Tour(
                        day=current_day,
                        start_time=start_time,
                        end_time=end_time,
                        tour_id=f"{current_day.name[:3]}_{start_str.replace(':', '')}_{end_str.replace(':', '')}_{i}"
                    )
                    tours.append(tour)
            except Exception as e:
                continue
    
    return tours


def run_snapshot():
    """Run quick optimization and analyze culprit coverage."""
    print("=" * 60)
    print("O0: CULPRIT COVERAGE SNAPSHOT")
    print("=" * 60)
    
    # Known culprit time windows (from Culprit Report)
    CULPRIT_PATTERNS = [
        "Mon_0530_1000",  # Early morning shifts
        "Mon_0545_1015",
        "Mon_0600_1030",
    ]
    
    print(f"\n[STEP 1] Loading forecast from {CSV_PATH}...")
    tours = parse_forecast_csv(CSV_PATH)
    print(f"Loaded {len(tours)} tours\n")
    
    print(f"[STEP 2] Running quick optimization (60s budget)...")
    print("  Purpose: Generate column pool for analysis\n")
    
    # Create dummy drivers
    drivers = [Driver(id=f"D{i}", name=f"Driver {i}") for i in range(1000)]
    config = ConfigV4(target_ftes=200, seed=42)
    
    # Run via manager - correct API
    run_id = run_manager.create_run(
        tours=tours,
        drivers=drivers,
        config=config,
        time_budget=60.0  # Quick run
    )
    
    # Wait for completion
    import time
    while run_manager.get_run_status(run_id).value == "RUNNING":
        time.sleep(1)
        print(".", end="", flush=True)
    
    result = run_manager.get_result(run_id)
    
    print(f"\n[STEP 3] Analyzing result...")
    
    if not result or not result.driver_assignments:
        print("\n[WARNING] No result returned. Cannot analyze.")
        return
    
    total_drivers = len(result.driver_assignments)
    
    # Analyze singleton coverage by time window
    culprit_coverage = defaultdict(lambda: {"total": 0, "singleton": 0})
    
    for driver in result.driver_assignments:
        roster_days = len(driver.blocks)
        
        for block in driver.blocks:
            if not block.tours:
                continue
                
            tour = block.tours[0]
            time_key = f"{tour.day.name[:3]}_{tour.start_time.strftime('%H%M')}_{tour.end_time.strftime('%H%M')}"
            
            # Check if this matches a culprit pattern
            for pattern in CULPRIT_PATTERNS:
                if pattern in time_key:
                    culprit_coverage[pattern]["total"] += 1
                    if roster_days == 1:
                        culprit_coverage[pattern]["singleton"] += 1
                    break
    
    # Report
    print("\n" + "=" * 60)
    print("CULPRIT COVERAGE ANALYSIS")
    print("=" * 60)
    print(f"Total Drivers: {total_drivers}")
    print()
    
    for pattern in CULPRIT_PATTERNS:
        stats = culprit_coverage[pattern]
        total = stats["total"]
        singleton = stats["singleton"]
        
        if total == 0:
            print(f"{pattern:25s} | NOT FOUND in solution")
        else:
            pct = (singleton / total * 100) if total > 0 else 0
            status = "[FAIL] HIGH SINGLETON" if pct > 80 else "[PASS] GOOD"
            print(f"{pattern:25s} | Total: {total:3d} | Singleton: {singleton:3d} ({pct:5.1f}%) | {status}")
    
    # Decision
    print("\n" + "=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)
    
    high_singleton_patterns = [
        p for p in CULPRIT_PATTERNS 
        if culprit_coverage[p]["total"] > 0 and 
           (culprit_coverage[p]["singleton"] / culprit_coverage[p]["total"]) > 0.8
    ]
    
    if high_singleton_patterns:
        print(f"\n[ACTION REQUIRED] {len(high_singleton_patterns)} time windows have >80% singleton usage.")
        print("   -> Proceed with O3 (Targeted Seeding) for these specific windows.")
        print("\nAffected patterns:")
        for p in high_singleton_patterns:
            print(f"  - {p}")
    else:
        print("\n[SKIP SEEDING] No critical singleton patterns detected.")
        print("   -> Problem is likely MIP selection, not pool sparsity.")
        print("   -> Consider O5 (Repair-Column Loop) instead of more seeding.")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    run_snapshot()
