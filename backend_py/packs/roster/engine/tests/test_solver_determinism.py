"""
SOLVEREIGN Solver Determinism Proof Test (PR-4)
================================================

This test verifies that the solver produces IDENTICAL output when run
multiple times with the same input. This is a critical property for:
- Audit reproducibility
- Debug reproducibility
- Production stability

Test Strategy:
    1. Create realistic tour_instances dataset
    2. Run solve_with_v2_solver N times (default: 3)
    3. Hash each result (assignments JSON)
    4. Assert all hashes are identical

Exit Codes:
    0 = PASS (all runs produce identical output)
    1 = FAIL (at least one run differs)
"""

import sys
import json
import hashlib
from datetime import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packs.roster.engine.solver_v2_integration import solve_with_v2_solver


def create_test_instances() -> list[dict]:
    """
    Create realistic tour_instances dataset for determinism testing.

    This mimics the Wien pilot data structure with various tour types:
    - Morning tours (06:00-10:00)
    - Midday tours (10:30-14:30)
    - Afternoon tours (14:00-18:00)
    - Evening tours (18:30-22:30)

    Returns ~50 tour instances across 7 days.
    """
    instances = []
    instance_id = 1

    # Tour templates (start, end, crosses_midnight)
    tour_templates = [
        (time(6, 0), time(10, 0), False),    # Morning
        (time(10, 45), time(14, 45), False), # Mid-morning (45min gap)
        (time(15, 30), time(19, 30), False), # Afternoon (45min gap)
        (time(8, 0), time(12, 0), False),    # Alt morning
        (time(12, 45), time(16, 45), False), # Alt midday (45min gap)
        (time(17, 30), time(21, 30), False), # Alt evening (45min gap)
        (time(5, 0), time(9, 0), False),     # Early
        (time(9, 45), time(13, 45), False),  # Late morning (45min gap)
    ]

    depots = ["West", "Nord", "Ost"]

    for day in range(1, 8):  # Monday to Sunday
        # Vary number of tours per day
        num_tours = 6 if day <= 5 else 4  # Fewer on weekends

        for i in range(num_tours):
            template_idx = (day + i) % len(tour_templates)
            start_ts, end_ts, crosses = tour_templates[template_idx]
            depot = depots[(day + i) % len(depots)]

            # Calculate work hours
            start_min = start_ts.hour * 60 + start_ts.minute
            end_min = end_ts.hour * 60 + end_ts.minute
            duration_min = end_min - start_min
            if duration_min < 0:
                duration_min += 24 * 60  # Handle midnight crossing

            instances.append({
                "id": instance_id,
                "day": day,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "depot": depot,
                "skill": None,
                "work_hours": duration_min / 60,
                "duration_min": duration_min,
                "crosses_midnight": crosses
            })
            instance_id += 1

    return instances


def hash_assignments(assignments: list[dict]) -> str:
    """
    Create deterministic hash of assignments for comparison.

    Sorts assignments by (driver_id, tour_instance_id) before hashing
    to ensure stable ordering.
    """
    # Sort by stable keys
    sorted_assignments = sorted(
        assignments,
        key=lambda a: (a["driver_id"], a["tour_instance_id"])
    )

    # Convert to JSON string with sorted keys
    json_str = json.dumps(sorted_assignments, sort_keys=True, default=str)

    # SHA256 hash
    return hashlib.sha256(json_str.encode()).hexdigest()


def run_determinism_test(num_runs: int = 3, verbose: bool = True) -> dict:
    """
    Run determinism proof test.

    Args:
        num_runs: Number of times to run solver (default: 3)
        verbose: Print progress messages

    Returns:
        dict with:
            - passed: bool
            - hashes: list of output hashes
            - num_assignments: number of assignments per run
            - num_drivers: number of unique drivers per run
    """
    if verbose:
        print("=" * 70)
        print(" SOLVEREIGN Solver Determinism Proof Test")
        print("=" * 70)
        print()

    # Create test data
    instances = create_test_instances()
    if verbose:
        print(f"[Setup] Created {len(instances)} tour instances across 7 days")
        print()

    hashes = []
    stats = []

    for run_num in range(1, num_runs + 1):
        if verbose:
            print(f"[Run {run_num}/{num_runs}] Running solver...")

        assignments = solve_with_v2_solver(instances)
        run_hash = hash_assignments(assignments)
        unique_drivers = len(set(a["driver_id"] for a in assignments))

        hashes.append(run_hash)
        stats.append({
            "num_assignments": len(assignments),
            "num_drivers": unique_drivers
        })

        if verbose:
            print(f"[Run {run_num}/{num_runs}] Hash: {run_hash[:16]}... | "
                  f"Assignments: {len(assignments)} | Drivers: {unique_drivers}")
            print()

    # Check all hashes match
    passed = len(set(hashes)) == 1

    if verbose:
        print("=" * 70)
        if passed:
            print(" [PASS] DETERMINISM PROOF: All runs produced identical output")
        else:
            print(" [FAIL] DETERMINISM PROOF: Runs produced different output!")
            print(f"        Unique hashes: {len(set(hashes))}")
            for i, h in enumerate(hashes, 1):
                print(f"        Run {i}: {h}")
        print("=" * 70)

    return {
        "passed": passed,
        "hashes": hashes,
        "stats": stats
    }


def write_gate_report(result: dict, output_path: str = "gate_report_determinism.json"):
    """Write machine-readable gate report."""
    report = {
        "gate": "DETERMINISM_PROOF",
        "status": "PASS" if result["passed"] else "FAIL",
        "runs": len(result["hashes"]),
        "unique_hashes": len(set(result["hashes"])),
        "output_hash": result["hashes"][0] if result["passed"] else None,
        "stats": result["stats"]
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[Gate Report] Written to {output_path}")
    return report


# Entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Solver Determinism Proof Test")
    parser.add_argument("--runs", type=int, default=3, help="Number of test runs (default: 3)")
    parser.add_argument("--evidence", action="store_true", help="Write gate_report.json")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")

    args = parser.parse_args()

    result = run_determinism_test(num_runs=args.runs, verbose=not args.quiet)

    if args.evidence:
        write_gate_report(result)

    sys.exit(0 if result["passed"] else 1)
