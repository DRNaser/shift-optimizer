
import os
import requests
import json
import datetime
from pathlib import Path

# Configuration
API_URL = "http://localhost:8000/api/v1"
INPUT_FILE = str(Path(__file__).parent.parent / "forecast-test.txt")

# Mappings
DAY_MAP = {
    "Montag": "Mon",
    "Dienstag": "Tue",
    "Mittwoch": "Wed",
    "Donnerstag": "Thu",
    "Freitag": "Fri",
    "Samstag": "Sat",
    "Sonntag": "Sun"
}

def parse_time(t_str):
    # Format HH:MM
    return t_str.strip()

def parse_input(file_path):
    tours = []
    current_day = None
    tour_id_counter = 1
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Check for header/day
            parts = line.split()
            if len(parts) >= 1 and parts[0] in DAY_MAP:
                current_day = DAY_MAP[parts[0]]
                continue
            
            # Check for time range line: "HH:MM-HH:MM Count"
            # Tab separated or space separated? File looks tab or mixed.
            # Example: "04:45-09:15 15"
            
            # Try splitting by tab first
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
                    "start_time": parse_time(start_str),
                    "end_time": parse_time(end_str),
                    "location": "HUB_A",
                    "required_qualifications": []
                })
                tour_id_counter += 1
                
    return tours

def generate_drivers(num_drivers=250):
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
    print(f"Reading input from {INPUT_FILE}...")
    tours = parse_input(INPUT_FILE)
    print(f"Parsed {len(tours)} tours.")
    
    drivers = generate_drivers(300) # Generous pool
    print(f"Generated {len(drivers)} drivers.")
    
    payload = {
        "week_start": "2024-01-01",
        "tours": tours,
        "drivers": drivers,
        "run": {
            "time_budget_seconds": 60,
            "seed": 42,
            "config_overrides": {
                "cap_quota_2er": 0.30,
                "enable_diag_block_caps": False
            }
        }
    }
    
    print("Sending request to API...")
    try:
        resp = requests.post(f"{API_URL}/runs", json=payload)
        resp.raise_for_status()
        data = resp.json()
        run_id = data['run_id']
        print(f"Run started! ID: {run_id}")
        print(f"Monitor at: {API_URL}/runs/{run_id}")
        print(f"Check Dashboard: http://localhost:3000/d/shift-opt-safety")
        
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to API. Is the backend running?")
        print("Run: uvicorn src.main:app --reload --port 8000")
    except Exception as e:
        print(f"Error: {e}")
        if 'resp' in locals():
            print(resp.text)

if __name__ == "__main__":
    main()
