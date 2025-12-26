#!/usr/bin/env python
"""Quick test script to check API response fields.

This is NOT a pytest test - it's a manual script that requires the API server.
Guarded to prevent pytest collection errors.
"""
import sys

# Skip at module level for pytest collection
if "pytest" in sys.modules:
    import pytest
    pytest.skip("Requires running API server", allow_module_level=True)

import requests
import time
import json

API_URL = "http://localhost:8010/api/v1"

def main():
    # Create a simple run
    payload = {
        "week_start": "2024-01-01",
        "tours": [{"id": "T1", "day": "Mon", "start_time": "08:00", "end_time": "12:00"}],
        "run": {"time_budget_seconds": 10, "seed": 42}
    }

    print("Creating run...")
    r = requests.post(f"{API_URL}/runs", json=payload)
    run_id = r.json()["run_id"]
    print(f"run_id: {run_id}")

    print("Waiting for completion...")
    time.sleep(8)

    print("Fetching plan...")
    plan = requests.get(f"{API_URL}/runs/{run_id}/plan").json()

    print("\n=== KEY CHECK ===")
    print(f"schema_version: {plan.get('schema_version', 'MISSING')!r}")
    print(f"version: {plan.get('version')!r}")
    print(f"top-level keys: {sorted(plan.keys())}")

    if plan.get("assignments"):
        block = plan["assignments"][0]["block"]
        print(f"pause_zone: {block.get('pause_zone', 'MISSING')!r}")
        print(f"block keys: {sorted(block.keys())}")
    else:
        print("No assignments in response")


if __name__ == "__main__":
    main()
