#!/usr/bin/env python3
"""
Diagnostic Run - Capture full KPIs for analysis
"""
import os
import sys
import json
import requests

API_URL = "http://localhost:8000/api/v1"
INPUT_FILE = r"C:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt"

DAY_MAP = {
    "Montag": "Mon", "Dienstag": "Tue", "Mittwoch": "Wed",
    "Donnerstag": "Thu", "Freitag": "Fri", "Samstag": "Sat", "Sonntag": "Sun"
}

def parse_input(file_path):
    tours = []
    current_day = None
    tour_id_counter = 1
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 1 and parts[0] in DAY_MAP:
                current_day = DAY_MAP[parts[0]]
                continue
            if '\t' in line:
                tokens = line.split('\t')
            else:
                tokens = line.split()
            if len(tokens) < 2:
                continue
            time_range = tokens[0]
            try:
                count = int(tokens[1])
            except ValueError:
                continue
            if '-' not in time_range:
                continue
            start_str, end_str = time_range.split('-')
            for _ in range(count):
                tours.append({
                    "id": f"T{tour_id_counter}",
                    "day": current_day,
                    "start_time": start_str.strip(),
                    "end_time": end_str.strip(),
                    "location": "HUB_A",
                    "required_qualifications": []
                })
                tour_id_counter += 1
    return tours

def generate_drivers(num_drivers=300):
    drivers = []
    for i in range(1, num_drivers + 1):
        drivers.append({
            "id": f"D{i}",
            "name": f"Driver {i}",
            "qualifications": [],
            "max_weekly_hours": 55.0,
            "max_daily_span_hours": 14.0,
            "max_tours_per_day": 3,
            "min_rest_hours": 11.0,
            "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        })
    return drivers

def main():
    print("=" * 60)
    print("DIAGNOSTIC RUN - Full KPI Analysis")
    print("=" * 60)
    
    tours = parse_input(INPUT_FILE)
    drivers = generate_drivers(300)
    
    print(f"Tours: {len(tours)}")
    print(f"Drivers pool: {len(drivers)}")
    
    # Run with all feature flags ON and 180s budget
    payload = {
        "week_start": "2024-01-01",
        "tours": tours,
        "drivers": drivers,
        "run": {
            "time_budget_seconds": 180,  # QUALITY tier
            "seed": 42,
            "config_overrides": {
                "cap_quota_2er": 0.30,
                "enable_fill_to_target_greedy": True,   # Feature flag ON
                "enable_bad_block_mix_rerun": True,     # Feature flag ON
                "enable_diag_block_caps": False
            }
        }
    }
    
    print("\nFeature Flags:")
    for k, v in payload["run"]["config_overrides"].items():
        print(f"  {k}: {v}")
    print(f"\nTime Budget: {payload['run']['time_budget_seconds']}s")
    print("\nStarting solver...")
    
    try:
        resp = requests.post(f"{API_URL}/runs", json=payload, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        run_id = result.get("run_id", "unknown")
        print(f"\nRun ID: {run_id}")
        
        # Fetch the plan
        plan_resp = requests.get(f"{API_URL}/runs/{run_id}/plan", timeout=10)
        if plan_resp.status_code == 200:
            plan = plan_resp.json()
            
            print("\n" + "=" * 60)
            print("RUN RESULT")
            print("=" * 60)
            
            # Extract KPIs
            stats = plan.get("stats", {})
            validation = plan.get("validation", {})
            
            print(f"\nStatus: {validation.get('is_valid', 'unknown')}")
            print(f"\nKPIs:")
            print(f"  drivers_total:    {stats.get('total_drivers', 'N/A')}")
            print(f"  tours_input:      {stats.get('total_tours_input', 'N/A')}")
            print(f"  tours_assigned:   {stats.get('total_tours_assigned', 'N/A')}")
            print(f"  coverage_rate:    {stats.get('assignment_rate', 'N/A')}")
            print(f"  avg_work_hours:   {stats.get('average_work_hours', 'N/A'):.1f}h")
            print(f"  utilization:      {stats.get('average_driver_utilization', 0) * 100:.1f}%")
            
            block_counts = stats.get("block_counts", {})
            print(f"\nBlock Mix (final solution):")
            print(f"  blocks_1er: {block_counts.get('single', 0)}")
            print(f"  blocks_2er: {block_counts.get('double', 0)}")
            print(f"  blocks_3er: {block_counts.get('triple', 0)}")
            
            # Save full result for analysis
            with open("diag_run_result.json", "w") as f:
                json.dump(plan, f, indent=2)
            print("\nFull result saved to: diag_run_result.json")
            
        else:
            print(f"Failed to fetch plan: {plan_resp.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
