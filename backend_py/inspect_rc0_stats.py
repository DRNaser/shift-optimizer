import json
from pathlib import Path

def analyze_plan():
    path = Path("artifacts/rc0/weekly_plan.json")
    if not path.exists():
        print(f"Error: {path} not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    stats = data.get("stats", {})
    
    print("=== RC0 Solver Telemetry ===")
    print(f"Total Drivers: {stats.get('total_drivers')}")
    print(f"Total Tours: {stats.get('total_tours_input')}")
    print(f"Assignments: {stats.get('total_tours_assigned')}")
    
    print("\n--- Block Mix ---")
    counts = stats.get("block_counts", {})
    total_blocks = sum(counts.values())
    for k, v in counts.items():
        print(f"  {k}: {v} ({v/total_blocks*100:.1f}%)")
        
    print("\n--- Efficiency Leakage ---")
    print(f"Forced 1er (Constraint): {stats.get('forced_1er_count', 'N/A')}")
    print(f"Missed 3er Opps: {stats.get('missed_3er_opps_count', 'N/A')}")
    print(f"Missed Multi Opps: {stats.get('missed_multi_opps_count', 'N/A')}")
    
    print("\n--- Utilization ---")
    print(f"Avg Driver Util: {stats.get('average_driver_utilization', 0)*100:.1f}%")
    print(f"Avg Work Hours: {stats.get('average_work_hours', 'N/A')}")
    
    # Calculate simple theoretical lower bound
    # 545 tours / 3 tours/day / 5 days = ~36 drivers? No that's not right.
    # Total hours / Max hours?
    # We will just report the raw stats for the user to interpret based on their "usual suspects"
    
if __name__ == "__main__":
    analyze_plan()
