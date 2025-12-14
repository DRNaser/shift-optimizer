"""
FORECAST SOLVER INVARIANT AUDIT
===============================
Audits v2 solver for correctness of:
1. Hour accounting (sum must match)
2. HARD_OK never coexists with PT usage
3. Range feasibility consistency

Run from backend_py directory:
    python -m audit_invariants
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import time
from src.domain.models import Tour, Weekday
from src.services.forecast_weekly_solver import (
    ForecastWeeklySolverV2,
    ForecastConfig,
    ForecastSolveStatus
)

# Weekday mapping
DAY_MAP = {
    "Mon": Weekday.MONDAY,
    "Tue": Weekday.TUESDAY,
    "Wed": Weekday.WEDNESDAY,
    "Thu": Weekday.THURSDAY,
    "Fri": Weekday.FRIDAY,
    "Sat": Weekday.SATURDAY,
    "Sun": Weekday.SUNDAY,
}

def parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))

def load_fixture(path: Path) -> tuple[list[Tour], str]:
    """Load fixture and convert to Tour objects."""
    with open(path) as f:
        data = json.load(f)
    
    tours = []
    for t in data["tours"]:
        tours.append(Tour(
            id=t["id"],
            day=DAY_MAP[t["day"]],
            start_time=parse_time(t["start"]),
            end_time=parse_time(t["end"]),
            location="DEFAULT",
            required_qualifications=[]
        ))
    
    return tours, data.get("description", path.name)

def audit_fixture(name: str, tours: list[Tour], description: str) -> dict:
    """Run solver and check invariants."""
    print(f"\n{'='*70}")
    print(f"AUDITING: {name}")
    print(f"  {description}")
    print(f"{'='*70}")
    
    # Calculate expected total
    total_hours = sum(t.duration_hours for t in tours)
    print(f"\nInput: {len(tours)} tours, {total_hours:.1f} total hours")
    
    # Run solver
    config = ForecastConfig(
        time_limit_phase1=30.0,
        time_limit_phase2=30.0,
        time_limit_phase3=30.0,
        time_limit_phase4=30.0,
    )
    solver = ForecastWeeklySolverV2(tours, config)
    result = solver.solve()
    
    kpi = result.kpi
    
    # Calculate actual totals from driver schedules
    fte_hours_sum = 0.0
    pt_hours_sum = 0.0
    fte_hours_list = []
    
    for d in result.drivers:
        if d.driver_type == "FTE":
            fte_hours_sum += d.hours_week
            fte_hours_list.append(d.hours_week)
        else:
            pt_hours_sum += d.hours_week
    
    actual_total = fte_hours_sum + pt_hours_sum
    
    print(f"\n--- RESULTS ---")
    print(f"Status: {kpi['status']}")
    print(f"FTE count: {kpi['drivers_fte']}, PT count: {kpi['drivers_pt']}")
    print(f"FTE hours sum: {fte_hours_sum:.2f}h")
    print(f"PT hours sum: {pt_hours_sum:.2f}h")
    print(f"Actual total: {actual_total:.2f}h")
    print(f"Expected total: {total_hours:.2f}h")
    print(f"FTE hours per driver: {fte_hours_list}")
    print(f"range_feasible_hours_only: {kpi['range_feasible_hours_only']}")
    print(f"range_feasible_with_constraints: {kpi['range_feasible_with_constraints']}")
    print(f"k_min: {kpi['k_min']}, k_max: {kpi['k_max']}")
    print(f"slack_under: {kpi['slack_under_total']:.2f}h, slack_over: {kpi['slack_over_total']:.2f}h")
    
    # Check invariants
    issues = []
    
    # INVARIANT 1: Hour accounting
    tolerance = 0.01  # 0.01h = ~36 seconds
    hour_diff = abs(actual_total - total_hours)
    if hour_diff > tolerance:
        issues.append(f"INVARIANT 1 FAIL: Hour mismatch! actual={actual_total:.2f} vs expected={total_hours:.2f} (diff={hour_diff:.2f}h)")
    else:
        print(f"\n[OK] INVARIANT 1 PASS: Hours match (diff={hour_diff:.4f}h)")
    
    # INVARIANT 2: HARD_OK never coexists with PT usage
    pt_hours_total = kpi['pt_hours_total']
    status = kpi['status']
    
    if status == ForecastSolveStatus.HARD_OK:
        if pt_hours_total > 0:
            issues.append(f"INVARIANT 2 FAIL: HARD_OK but pt_hours_total={pt_hours_total:.2f}h > 0!")
        else:
            print(f"[OK] INVARIANT 2 PASS: HARD_OK with pt_hours_total=0")
        
        # Also check FTE all in range
        min_h, max_h = 42.0, 53.0
        for h in fte_hours_list:
            if h < min_h - 0.01 or h > max_h + 0.01:
                issues.append(f"INVARIANT 2 FAIL: HARD_OK but FTE hour {h:.2f} out of 42-53h range!")
        if not any("INVARIANT 2 FAIL" in i for i in issues):
            print(f"[OK] INVARIANT 2 PASS: All FTE in 42-53h range")
    else:
        # Should be SOFT_FALLBACK_HOURS
        if pt_hours_total > 0 or kpi['slack_under_total'] > 0 or kpi['slack_over_total'] > 0:
            print(f"[OK] INVARIANT 2 PASS: SOFT_FALLBACK_HOURS with pt/slack usage (expected)")
        else:
            # This is suspicious - why fallback if no PT and no slack?
            print(f"[WARN] INVARIANT 2 CHECK: SOFT_FALLBACK_HOURS but no PT and no slack - check FTE range")
            for h in fte_hours_list:
                if h < 42.0 or h > 53.0:
                    print(f"   Found FTE hour {h:.2f} out of range - fallback justified")
    
    # INVARIANT 3: Range feasibility consistency
    range_hours = kpi['range_feasible_hours_only']
    range_constraints = kpi['range_feasible_with_constraints']
    
    if not range_hours and range_constraints:
        issues.append(f"INVARIANT 3 FAIL: hours_only=False but with_constraints=True (impossible!)")
    else:
        print(f"[OK] INVARIANT 3 PASS: Feasibility consistency OK")
    
    # Additional check: if range_feasible_hours_only but PT used, then range_feasible_with_constraints should be False
    if range_hours and pt_hours_total > 0:
        if range_constraints:
            issues.append(f"INVARIANT 3 FAIL: hours_feasible=True, PT used ({pt_hours_total:.1f}h), but with_constraints=True!")
        else:
            print(f"[OK] INVARIANT 3 PASS: Hours feasible but PT needed -> with_constraints=False (correct)")
    
    # Determine case
    print(f"\n--- CASE DETERMINATION ---")
    if status == ForecastSolveStatus.HARD_OK and pt_hours_total == 0:
        all_in_range = all(42.0 <= h <= 53.0 for h in fte_hours_list)
        if all_in_range:
            print("CASE 1: [OK] FTE-only solution exists, HARD_OK correct")
        else:
            print("CASE 3: [FAIL] BUG - HARD_OK but FTE hours out of range!")
            issues.append("CASE 3 BUG: HARD_OK with FTE hours out of range")
    elif status == ForecastSolveStatus.SOFT_FALLBACK_HOURS:
        if pt_hours_total > 0 or kpi['slack_under_total'] > 0 or kpi['slack_over_total'] > 0:
            if not range_constraints:
                print("CASE 2: [OK] FTE-only infeasible due to constraints, SOFT_FALLBACK_HOURS correct")
            else:
                print("CASE 3: [FAIL] BUG - SOFT_FALLBACK but range_feasible_with_constraints=True!")
                issues.append("CASE 3 BUG: SOFT_FALLBACK but range_feasible_with_constraints=True")
        else:
            print("CASE ?: [WARN] SOFT_FALLBACK but no PT/slack - investigating FTE hours")
    else:
        print(f"CASE: Status is {status}")
    
    # Summary
    print(f"\n--- AUDIT SUMMARY ---")
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        return {"pass": False, "issues": issues}
    else:
        print("[OK] ALL INVARIANTS PASS")
        return {"pass": True, "issues": []}


def main():
    # Find fixture files
    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        data_dir = Path(__file__).parent.parent / "data"
    
    fixtures = [
        ("small", data_dir / "forecast_small.json"),
        ("medium", data_dir / "forecast_medium.json"),
        ("large", data_dir / "forecast_large.json"),
    ]
    
    results = {}
    
    for name, path in fixtures:
        if not path.exists():
            print(f"\n⚠️ Fixture not found: {path}")
            continue
        
        tours, desc = load_fixture(path)
        result = audit_fixture(name, tours, desc)
        results[name] = result
    
    # Final summary
    print(f"\n{'='*70}")
    print("FINAL AUDIT SUMMARY")
    print(f"{'='*70}")
    
    all_pass = True
    for name, result in results.items():
        status = "✅ PASS" if result["pass"] else "❌ FAIL"
        print(f"  {name}: {status}")
        if not result["pass"]:
            all_pass = False
            for issue in result["issues"]:
                print(f"    - {issue}")
    
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
