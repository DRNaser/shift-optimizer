import requests
import json

# Get run status
try:
    resp = requests.get("http://localhost:8000/api/v1/runs/run_033ac8bb96da", timeout=5)
    if resp.status_code == 200:
        data = resp.json()
        print("Run Status:", data.get("status"))
        print("Phase:", data.get("phase"))
        print()
except Exception as e:
    print(f"Error getting status: {e}")

# Try to get recent logs from report
try:
    resp = requests.get("http://localhost:8000/api/v1/runs/run_033ac8bb96da/report", timeout=5)
    if resp.status_code == 200:
        data = resp.json()
        print("Report keys:", data.keys())
except Exception as e:
    print(f"Error getting report: {e}")
