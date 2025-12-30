"""
Run Cap Proof for KW51 (Endgame 229)
"""
import sys
from pathlib import Path
import logging
sys.path.insert(0, str(Path(__file__).parent))

import argparse
from test_forecast_csv import parse_forecast_csv
from src.services.portfolio_controller import run_portfolio
from src.services.forecast_solver_v4 import ConfigV4
from fleet_counter import compute_fleet_peaks

def main():
    parser = argparse.ArgumentParser(description="Run KW51 Cap Proof")
    parser.add_argument("--cap", type=int, default=229, help="Hard Day Cap (Target Driver Count)")
    parser.add_argument("--time-budget", type=float, default=360, help="Solver time budget")
    args = parser.parse_args()

    # Data Loading
    csv_path = Path(__file__).parent.parent / "forecast_kw51_filtered.csv"
    tours = parse_forecast_csv(str(csv_path))
    print(f"Loaded {len(tours)} tours")

    # Config with HARD CAP
    config = ConfigV4(
        day_cap_hard=args.cap,
        time_limit_phase1=args.time_budget * 0.2, # 20% for Phase 1
        time_limit_phase2=args.time_budget * 0.7, # 70% for Phase 2
        seed=42,
        output_profile="MIN_HEADCOUNT_3ER", # Optimize for headcount primarily
        enable_diag_block_caps=True 
    )

    print("=" * 70)
    print(f"CAP PROOF RUN: Target <= {args.cap} Drivers")
    print(f"Time Budget: {args.time_budget}s")
    print("=" * 70)

    # Run Solver
    def log_tracker(msg):
        # Filter relevant logs
        if "drivers" in msg.lower() or "cap" in msg.lower() or "feasible" in msg.lower():
            print(f"[PROOF-LOG] {msg}")

    result = run_portfolio(tours, time_budget=args.time_budget, seed=42, config=config, log_fn=log_tracker)
    
    # Analysis
    solution = result.solution
    assignments = solution.assignments
    driver_count = len(assignments)
    
    print("\n" + "=" * 70)
    print("PROOF RESULT")
    print("=" * 70)
    print(f"Target Cap: {args.cap}")
    print(f"Actual Drivers: {driver_count}")
    print(f"Status: {solution.status}")
    
    if driver_count <= args.cap and solution.status in ["OK", "OPTIMAL", "FEASIBLE", "COMPLETED", "OK_ENDGAME"]:
        print(f"\n[SUCCESS] Cap Proof PASSED! Found {driver_count} drivers (<= {args.cap} target).")
        sys.exit(0)
    else:
        print(f"\n[FAIL] Could not achieve cap {args.cap}. Best found: {driver_count}")
        sys.exit(1)

if __name__ == "__main__":
    main()
