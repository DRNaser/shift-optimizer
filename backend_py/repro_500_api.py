
import requests
import json
from datetime import datetime, timedelta

# Minimal tour data (same as test_portfolio.py)
tours = []
base_date = "2023-11-20" # Monday

def add_tour(day_offset, start, end, count):
    day_map = {0: "MONDAY", 1: "TUESDAY", 2: "WEDNESDAY", 3: "THURSDAY", 4: "FRIDAY", 5: "SATURDAY", 6: "SUNDAY"}
    day_str = day_map[day_offset]
    for _ in range(count):
        tours.append({
            "id": f"T{len(tours)+1}",
            "day": day_str,
            "start_time": start,
            "end_time": end,
            "qualification": "Driver"
        })

# Create a mix of tours
add_tour(0, "06:00", "14:00", 80) # Mon
add_tour(0, "14:00", "22:00", 80)
add_tour(4, "06:00", "14:00", 120) # Fri peak
add_tour(4, "14:00", "22:00", 120)

payload = {
    "week_start": base_date,
    "tours": tours,
    "solver_type": "portfolio",
    "time_limit_seconds": 30,
    "seed": 42,
    "extended_hours": False
}

print(f"Sending request with {len(tours)} tours...")
try:
    response = requests.post("http://127.0.0.1:8000/api/v1/schedule", json=payload)
    print(f"Status: {response.status_code}")
    print("Response Text:")
    print(response.text)
except Exception as e:
    print(f"Request failed: {e}")
