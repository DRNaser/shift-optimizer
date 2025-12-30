"""
run_regression_suite.py
Runs the regression suite for Step 10 validation.
Scenarios:
1. Normal Week (forecast input neu.csv) -> Baseline check
2. Compressed Week (KW51) -> Hard Target check

Generates artifacts/regression_report.json
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, Any

# Ensure we can import src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.portfolio_controller import run_portfolio
from test_forecast_csv import parse_forecast_csv

# --- BASLINES (Hardcoded for now as user requested snapshots later) ---
# Normal week baseline (drivers_total)
BASELINE_NORMAL_DRIVERS = 113
BASELINE_NORMAL_RUNTIME = 45.0
BASELINE_NORMAL_PT_SHARE = 0.40 # Current high share, user wants maintain or improve.

def run_scenario(name: str, csv_filename: str, time_budget: float, pool_size: int = 176) -> Dict[str, Any]:
    print(f"\n[SCENARIO] {name} (Budget: {time_budget}s)...")
    
    root_dir = Path(__file__).parent.parent
    repo_root = root_dir.parent
    
    possible_paths = [
        root_dir / csv_filename,
        repo_root / csv_filename
    ]
    file_path = next((p for p in possible_paths if p.exists()), None)
    
    if not file_path:
        print(f"  [MISSING] File missing: {csv_filename}")
        return None
        
    tours = parse_forecast_csv(str(file_path))
    print(f"  Loaded {len(tours)} tours")
    
    # Detect active days
    unique_days = set(t.day for t in tours)
    active_days_count = len(unique_days)
    
    classification = "UNKNOWN"
    if active_days_count >= 5:
        classification = "NORMAL"
    elif 3 <= active_days_count <= 4:
        classification = "COMPRESSED"
    else:
        classification = "SHORT_WEEK"
        
    print(f"  Analyzing {len(tours)} tours over {active_days_count} days ({classification})")

    from src.services.portfolio_controller import run_portfolio
    result = run_portfolio(
        tours, 
        time_budget=time_budget, 
        seed=42,
        log_fn=lambda x: None
    )
    
    sol = result.solution
    kpi = sol.kpi
    
    # Enrich result
    kpi["classification"] = classification
    kpi["active_days_count"] = active_days_count
    kpi["tours_total"] = len(tours)
    kpi["filename"] = csv_filename
    
    # Calculate Singleton Share (Roster-based)
    num_drivers = len(sol.assignments)
    if num_drivers > 0:
        singleton_count = 0
        for d in sol.assignments:
            covered = set()
            for b in d.blocks:
                if hasattr(b, "tour_ids"):
                    covered.update(b.tour_ids)
                else:
                    covered.add(b.id)
            if len(covered) == 1:
                singleton_count += 1
        kpi["singleton_share"] = singleton_count / num_drivers
    else:
        kpi["singleton_share"] = 0.0
    
    # Add baseline values for regression
    baseline = {}
    if classification == "NORMAL":
        baseline["drivers_total"] = BASELINE_NORMAL_DRIVERS
        baseline["runtime_s"] = BASELINE_NORMAL_RUNTIME
        baseline["core_pt_share_hours"] = BASELINE_NORMAL_PT_SHARE
        
    return {
        "name": name,
        "seed": 42,
        "candidate": kpi,
        "baseline": baseline
    }

def main():
    print("="*70)
    print("RUNNING REGRESSION SUITE (Step 11)")
    print("="*70)
    
    runs = []
    
    # 1. Normal Week (forecast input neu.csv)
    # Note: If this file is Mon-only, it will be classified as SHORT_WEEK
    res_normal = run_scenario("Normal Week (Baseline)", "forecast input neu.csv", 60.0)
    if res_normal:
        runs.append(res_normal)
        
    # 2. Compressed Week (KW51)
    # We construct the input for KW51 (filtered)
    # run_scenario handles path check.
    res_kw51 = run_scenario("Compressed Week (KW51)", "forecast_kw51_filtered.csv", 120.0, pool_size=176)
    if res_kw51:
        runs.append(res_kw51)
    
    # Report
    report = {
        "generated_at": time.ctime(),
        "baseline_ref": "v7.0.0-freeze",
        "candidate_ref": "v7.1.0-step11",
        "seeds": [42],
        "runs": runs
    }
    
    out_path = Path("artifacts/regression_report.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {out_path}")

if __name__ == "__main__":
    main()
