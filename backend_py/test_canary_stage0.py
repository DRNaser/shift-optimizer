"""
Test script for Canary Stage 0 with real forecast data.
Parses forecast-test.txt and sends to solver API.
"""

import json
import requests
from datetime import datetime

# Parse forecast-test.txt
def parse_forecast_file(filepath: str) -> list[dict]:
    """Parse the forecast file into tour list."""
    tours = []
    current_day = None
    tour_id = 1
    
    # German day name mapping (schema expects 'Mon', 'Tue', etc.)
    day_map = {
        "Montag": "Mon",
        "Dienstag": "Tue", 
        "Mittwoch": "Wed",
        "Donnerstag": "Thu",
        "Freitag": "Fri",
        "Samstag": "Sat",
        "Sonntag": "Sun",
    }
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Check if this is a day header
            for german_day, english_day in day_map.items():
                if line.startswith(german_day):
                    current_day = english_day
                    break
            else:
                # Parse time slot  
                if current_day and '\t' in line:
                    parts = line.split('\t')
                    if len(parts) >= 2 and '-' in parts[0]:
                        time_range = parts[0].strip()
                        try:
                            count = int(parts[1].strip())
                        except ValueError:
                            continue
                        
                        # Parse time range
                        start_time, end_time = time_range.split('-')
                        
                        # Create tours for this slot
                        for i in range(count):
                            tours.append({
                                "id": f"T{tour_id:04d}",
                                "day": current_day,
                                "start_time": start_time.strip(),
                                "end_time": end_time.strip(),
                            })
                            tour_id += 1
    
    return tours


def main():
    # Parse forecast file
    filepath = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt"
    tours = parse_forecast_file(filepath)
    
    print(f"Parsed {len(tours)} tours from forecast file")
    
    # Count per day
    per_day = {}
    for t in tours:
        per_day[t['day']] = per_day.get(t['day'], 0) + 1
    
    print("\nTours per day:")
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
        print(f"  {day}: {per_day.get(day, 0)}")
    
    # Build request using /runs endpoint format (v2 format with RunCreateRequest)
    request_body = {
        "week_start": "2024-01-01",
        "tours": tours,
        "drivers": [],  # Auto-create virtual drivers
        "run": {
            "seed": 42,
            "time_budget_seconds": 120,
            "config_overrides": {}
        }
    }
    
    # Send to API
    print("\n" + "=" * 60)
    print("SENDING TO API (/api/v1/runs)...")
    print(f"Tours: {len(tours)}, Time budget: 120s, Seed: 42")
    print("=" * 60)
    
    try:
        response = requests.post(
            "http://127.0.0.1:8005/api/v1/runs",
            json=request_body,
            timeout=180
        )
        
        print(f"\nStatus Code: {response.status_code}")
        
        if response.status_code in [200, 201]:
            result = response.json()
            run_id = result.get('run_id')
            print(f"Run ID: {run_id}")
            print(f"Status: {result.get('status')}")
            
            # Wait a bit if queued
            status = result.get('status')
            if status == 'QUEUED':
                print("Run is queued, waiting for completion...")
                import time
                for _ in range(60):  # Wait up to 60 seconds
                    time.sleep(2)
                    status_resp = requests.get(
                        f"http://127.0.0.1:8005/api/v1/runs/{run_id}",
                        timeout=10
                    )
                    if status_resp.status_code == 200:
                        status_data = status_resp.json()
                        status = status_data.get('status')
                        print(f"  Status: {status}")
                        if status in ['COMPLETED', 'FAILED']:
                            break
            
            # Get detailed result via /runs/{id}/plan
            if run_id:
                print("\nFetching plan...")
                plan_response = requests.get(
                    f"http://127.0.0.1:8005/api/v1/runs/{run_id}/plan",
                    timeout=30
                )
                if plan_response.status_code == 200:
                    plan = plan_response.json()
                    print("\n" + "=" * 60)
                    print("RESULTS")
                    print("=" * 60)
                    
                    stats = plan.get('stats', {})
                    print(f"Total Drivers: {stats.get('total_drivers', 'N/A')}")
                    print(f"Block Counts: {stats.get('block_counts', {})}")
                    
                    ar = stats.get('assignment_rate')
                    print(f"Assignment Rate: {ar:.1%}" if ar else "Assignment Rate: N/A")
                    print(f"Tours Assigned: {stats.get('total_tours_assigned', 'N/A')} / {stats.get('total_tours_input', 'N/A')}")
                    
                    validation = plan.get('validation', {})
                    print(f"Valid: {validation.get('is_valid', 'N/A')}")
                    if validation.get('warnings'):
                        print(f"Warnings: {validation.get('warnings')[:3]}")  # First 3
                else:
                    print(f"Plan fetch failed: {plan_response.status_code} - {plan_response.text[:200]}")
        else:
            print(f"Error: {response.text[:800]}")
            
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to API. Start server first:")
        print("  cd backend_py")
        print("  uvicorn src.main:app --host 127.0.0.1 --port 8004 --workers 1")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Check metrics
    print("\n" + "=" * 60)
    print("CHECKING METRICS...")
    print("=" * 60)
    
    try:
        metrics_response = requests.get(
            "http://127.0.0.1:8005/api/v1/metrics",
            timeout=10
        )
        if metrics_response.status_code == 200:
            metrics_text = metrics_response.text
            
            # Extract key metrics
            printed = False
            for line in metrics_text.split('\n'):
                if any(m in line for m in [
                    'solver_signature_runs_total ',
                    'solver_signature_unique_total ',
                    'solver_budget_overrun_total{',
                    'solver_infeasible_total ',
                    'solver_path_selection_total{',
                    'solver_phase_duration_seconds_count{',
                    'solver_driver_count_count{',
                ]):
                    if not line.startswith('#'):
                        print(line)
                        printed = True
            
            if not printed:
                print("No solver metrics recorded yet (counters at 0)")
    except Exception as e:
        print(f"Could not fetch metrics: {e}")


if __name__ == "__main__":
    main()
