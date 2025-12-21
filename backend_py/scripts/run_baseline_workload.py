#!/usr/bin/env python3
"""
Stage 0 Baseline Workload Generator
====================================
Runs forecast tests in a loop to generate baseline data for Canary monitoring.

Usage:
    python run_baseline_workload.py --count 500 --delay 120

This will run 500 solver runs with ~2 minute delays between each.
Total time for 500 runs @ 120s delay: ~17 hours
"""

import os
import sys
import time
import argparse
import requests
import random
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000/api/v1"
INPUT_FILE = r"C:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt"

DAY_MAP = {
    "Montag": "Mon",
    "Dienstag": "Tue",
    "Mittwoch": "Wed",
    "Donnerstag": "Thu",
    "Freitag": "Fri",
    "Samstag": "Sat",
    "Sonntag": "Sun"
}


def parse_input(file_path):
    """Parse forecast input file."""
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


def generate_drivers(num_drivers=250):
    """Generate driver pool."""
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


def check_readyz():
    """Check /api/v1/readyz and return git_commit."""
    try:
        r = requests.get(f"{API_URL}/readyz", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("git_commit", "unknown")
    except Exception as e:
        return f"ERROR: {e}"
    return "unknown"


def get_run_count():
    """Get current solver_signature_runs_total from metrics."""
    try:
        r = requests.get(f"{API_URL}/metrics", timeout=5)
        for line in r.text.split('\n'):
            if line.startswith('solver_signature_runs_total '):
                return float(line.split()[1])
    except:
        pass
    return 0


def run_single_test(seed: int):
    """Run a single forecast test and return run_id or None."""
    tours = parse_input(INPUT_FILE)
    drivers = generate_drivers(300)
    
    payload = {
        "week_start": "2024-01-01",
        "tours": tours,
        "drivers": drivers,
        "run": {
            "time_budget_seconds": 60,
            "seed": seed,
            "config_overrides": {}  # Stage 0: no feature flags
        }
    }
    
    try:
        resp = requests.post(f"{API_URL}/runs", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("run_id")
    except Exception as e:
        return None


def main():
    parser = argparse.ArgumentParser(description="Stage 0 Baseline Workload Generator")
    parser.add_argument("--count", type=int, default=500, help="Number of runs to execute (default: 500)")
    parser.add_argument("--delay", type=int, default=120, help="Delay in seconds between runs (default: 120)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    args = parser.parse_args()
    
    print("=" * 60)
    print("STAGE 0 BASELINE WORKLOAD GENERATOR")
    print("=" * 60)
    
    # Check current state
    commit = check_readyz()
    runs_before = get_run_count()
    
    print(f"API: {API_URL}")
    print(f"git_commit: {commit}")
    print(f"Current runs: {runs_before}")
    print(f"Target runs: {args.count}")
    print(f"Delay between runs: {args.delay}s")
    
    estimated_hours = (args.count * (67 + args.delay)) / 3600  # ~67s per run + delay
    print(f"Estimated completion time: {estimated_hours:.1f} hours")
    print("=" * 60)
    
    if args.dry_run:
        print("DRY RUN - no runs will be executed")
        return
    
    # Verify locked commit
    if commit != "4e1abb5":
        print(f"WARNING: git_commit is {commit}, expected 4e1abb5")
        print("Proceeding anyway...")
    
    # Run loop
    successful = 0
    failed = 0
    
    for i in range(1, args.count + 1):
        seed = 42 + i  # Vary seed for each run
        
        print(f"\n[{i}/{args.count}] Starting run (seed={seed})...", end=" ", flush=True)
        run_id = run_single_test(seed)
        
        if run_id:
            print(f"✓ {run_id}")
            successful += 1
        else:
            print("✗ FAILED")
            failed += 1
        
        # Progress update every 10 runs
        if i % 10 == 0:
            current_runs = get_run_count()
            print(f"    Progress: {successful} successful, {failed} failed, total={current_runs}")
        
        # Delay before next run (skip on last)
        if i < args.count:
            time.sleep(args.delay)
    
    # Final summary
    print("\n" + "=" * 60)
    print("BASELINE COLLECTION COMPLETE")
    print("=" * 60)
    print(f"Successful runs: {successful}")
    print(f"Failed runs: {failed}")
    print(f"Final run count: {get_run_count()}")
    print(f"git_commit (still): {check_readyz()}")


if __name__ == "__main__":
    main()
