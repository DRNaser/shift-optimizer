"""
Direct Core V2 Verification Script

Tests the comprehensive seeder (patterns + bridges + early bird + split-chains)
using Core V2 engine directly (bypasses run_manager/V4 pipeline).
"""

import sys
import os
import csv
import logging
from datetime import datetime, time as datetime_time
from typing import List

# Setup Project Path
sys.path.append(os.getcwd())

from src.api.adapter_v2 import AdapterV2
from src.domain.models import Tour, Driver, Weekday

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CoreV2Verifier")

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
    }
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row:
                continue
            
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
            except:
                continue
    
    return tours


def main():
    print("="*60)
    print("CORE V2 VERIFICATION (Direct Adapter)")
    print("="*60)
    
    print(f"\nLoading Forecast: {CSV_PATH}")
    tours = parse_forecast_csv(CSV_PATH)
    print(f"Loaded {len(tours)} individual tours.\n")
    
    # Create dummy drivers (Core V2 doesn't use them)
    drivers = [Driver(id=f"D{i}", name=f"Driver {i}") for i in range(1000)]
    
    print("Starting Core V2 Optimization (Direct)...\n")
    
    # Call AdapterV2 directly
    adapter = AdapterV2()
    result = adapter.optimize(
        tours=tours,
        drivers=drivers,
        time_budget=300.0,  # 5 minutes
        seed=42
    )
    
    print("\n" + "="*60)
    print("CORE V2 RESULTS")
    print("="*60)
    
    if not result or not hasattr(result, 'driver_assignments'):
        print("\n[ERROR] No result returned from Core V2")
        return
    
    total_drivers = len(result.driver_assignments)
    
    # Analyze roster patterns
    roster_breakdown = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    
    for driver in result.driver_assignments:
        days_worked = len(driver.blocks)
        if days_worked in roster_breakdown:
            roster_breakdown[days_worked] += 1
    
    singleton_count = roster_breakdown[1]
    singleton_rate = (singleton_count / total_drivers * 100) if total_drivers > 0 else 0
    
    print(f"\nTotal Drivers: {total_drivers}")
    print("-" * 30)
    print(f"1-Day Rosters: {roster_breakdown[1]} ({roster_breakdown[1]/total_drivers*100:.1f}%)")
    print(f"2-Day Rosters: {roster_breakdown[2]} ({roster_breakdown[2]/total_drivers*100:.1f}%)")
    print(f"3-Day Rosters: {roster_breakdown[3]} ({roster_breakdown[3]/total_drivers*100:.1f}%)")
    print(f"4-Day Rosters: {roster_breakdown[4]} ({roster_breakdown[4]/total_drivers*100:.1f}%)")
    print(f"5-Day Rosters: {roster_breakdown[5]} ({roster_breakdown[5]/total_drivers*100:.1f}%)")
    print(f"6-Day Rosters: {roster_breakdown[6]} ({roster_breakdown[6]/total_drivers*100:.1f}%)")
    print("-" * 30)
    print(f"Singleton Rate: {singleton_rate:.1f}%")
    
    if singleton_rate <= 20.0:
        print("[PASS] Singleton rate excellent!")
    elif singleton_rate <= 50.0:
        print("[WARN] Singleton rate acceptable but could be better.")
    else:
        print("[FAIL] Singleton rate too high (poor connectivity).")
    
    print("\n" + "="*60)
    print(f"Core V2 with Comprehensive Seeder: {total_drivers} drivers, {singleton_rate:.1f}% singletons")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
