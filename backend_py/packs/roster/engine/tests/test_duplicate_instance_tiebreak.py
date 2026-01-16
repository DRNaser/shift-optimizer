"""
SOLVEREIGN Duplicate Instance Tie-Break Determinism Test (A3 Proof)
====================================================================

Tests that the solver produces STABLE, DETERMINISTIC output when given
duplicate tour instances (identical day/start/end/depot/skill).

This proves A3: Canonical tie-break handles duplicate tour instances
deterministically.

Test Strategy:
    1. Create tour instances where some have IDENTICAL intrinsic properties
       (simulating count > 1 expansion)
    2. Run the solver multiple times
    3. Assert ALL runs produce IDENTICAL assignments
    4. Also test with shuffled input order to prove sort stability

Exit Codes:
    0 = PASS (deterministic across all runs)
    1 = FAIL (non-deterministic output detected)
"""

import sys
import os
import json
import hashlib
from datetime import time
from pathlib import Path

# Add backend_py to path
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def create_duplicate_instances() -> list[dict]:
    """
    Create tour instances with DUPLICATES (identical intrinsic properties).

    This simulates what happens when a tours_normalized row has count > 1:
    Multiple tour_instances are created with the same (day, start, end, depot, skill).
    """
    instances = []
    instance_id = 1

    # Create 3 IDENTICAL instances (simulating count=3)
    for _ in range(3):
        instances.append({
            "id": instance_id,
            "day": 1,  # Monday
            "start_ts": "06:00",
            "end_ts": "10:00",
            "depot": "West",
            "skill": None,
            "work_hours": 4.0,
            "duration_min": 240,
            "crosses_midnight": False
        })
        instance_id += 1

    # Create 2 more IDENTICAL instances at a different time
    for _ in range(2):
        instances.append({
            "id": instance_id,
            "day": 1,
            "start_ts": "10:45",
            "end_ts": "14:45",
            "depot": "West",
            "skill": None,
            "work_hours": 4.0,
            "duration_min": 240,
            "crosses_midnight": False
        })
        instance_id += 1

    # Add some unique instances for a more realistic test
    for day in range(2, 6):  # Tue-Fri
        instances.append({
            "id": instance_id,
            "day": day,
            "start_ts": "08:00",
            "end_ts": "16:00",
            "depot": "Nord",
            "skill": None,
            "work_hours": 8.0,
            "duration_min": 480,
            "crosses_midnight": False
        })
        instance_id += 1

    return instances


def convert_to_tour_objects(instances: list[dict]) -> list:
    """Convert instances to time objects for solver input."""
    converted = []
    for inst in instances:
        start_parts = inst["start_ts"].split(":")
        end_parts = inst["end_ts"].split(":")
        converted.append({
            "id": inst["id"],
            "day": inst["day"],
            "start_ts": time(int(start_parts[0]), int(start_parts[1])),
            "end_ts": time(int(end_parts[0]), int(end_parts[1])),
            "depot": inst["depot"],
            "skill": inst["skill"],
            "work_hours": inst["work_hours"],
            "duration_min": inst["duration_min"],
            "crosses_midnight": inst["crosses_midnight"]
        })
    return converted


def compute_output_hash(assignments: list[dict]) -> str:
    """Compute deterministic hash of solver output."""
    sorted_assignments = sorted(
        assignments,
        key=lambda a: (a["driver_id"], a["tour_instance_id"])
    )
    json_str = json.dumps(sorted_assignments, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()


def run_duplicate_instance_test(verbose: bool = True) -> dict:
    """
    Run duplicate instance tie-break test.

    Returns:
        dict with:
            - passed: bool
            - num_runs: int
            - hashes: list of output hashes
            - unique_hashes: int
    """
    import io
    from contextlib import redirect_stdout
    from packs.roster.engine.solver_v2_integration import solve_with_v2_solver

    if verbose:
        print("=" * 70)
        print(" SOLVEREIGN Duplicate Instance Tie-Break Test (A3)")
        print("=" * 70)
        print()

    # Create instances with duplicates
    raw_instances = create_duplicate_instances()
    if verbose:
        print(f"[Setup] Created {len(raw_instances)} tour instances")
        dup_count = sum(1 for i in raw_instances if i["day"] == 1 and i["start_ts"] == "06:00")
        print(f"[Setup] Including {dup_count} IDENTICAL instances (day=1, 06:00-10:00, West)")

    instances = convert_to_tour_objects(raw_instances)

    # Run solver multiple times with IDENTICAL input
    NUM_RUNS = 5
    hashes = []

    for run in range(1, NUM_RUNS + 1):
        if verbose:
            print(f"\n[Run {run}/{NUM_RUNS}] Solving with identical input...")

        # Suppress solver output
        with redirect_stdout(io.StringIO()):
            assignments = solve_with_v2_solver(instances)

        output_hash = compute_output_hash(assignments)
        hashes.append(output_hash)

        if verbose:
            print(f"[Run {run}/{NUM_RUNS}] Hash: {output_hash[:16]}... | Assignments: {len(assignments)}")

    # Test with SHUFFLED input order to prove sort stability
    if verbose:
        print("\n[Shuffle Test] Testing with different input orders...")

    import random
    for shuffle_run in range(3):
        shuffled = list(raw_instances)
        random.seed(shuffle_run * 1000)  # Different shuffle each time
        random.shuffle(shuffled)
        shuffled_instances = convert_to_tour_objects(shuffled)

        with redirect_stdout(io.StringIO()):
            assignments = solve_with_v2_solver(shuffled_instances)

        output_hash = compute_output_hash(assignments)
        hashes.append(output_hash)

        if verbose:
            print(f"[Shuffle {shuffle_run + 1}/3] Hash: {output_hash[:16]}... (shuffled input)")

    # Verify all hashes match
    unique_hashes = len(set(hashes))
    passed = unique_hashes == 1

    if verbose:
        print()
        print("=" * 70)
        if passed:
            print(" [PASS] DUPLICATE INSTANCE TIE-BREAK: All runs produced IDENTICAL output")
            print("        regardless of input order or run count")
        else:
            print(f" [FAIL] DUPLICATE INSTANCE TIE-BREAK: {unique_hashes} different hashes!")
            for i, h in enumerate(hashes):
                print(f"        Run {i + 1}: {h[:32]}...")
        print("=" * 70)

    return {
        "passed": passed,
        "num_runs": len(hashes),
        "hashes": hashes,
        "unique_hashes": unique_hashes
    }


def write_report(result: dict, output_path: str = "gate_report_duplicate_tiebreak.json"):
    """Write machine-readable report."""
    report = {
        "gate": "DUPLICATE_INSTANCE_TIEBREAK",
        "status": "PASS" if result["passed"] else "FAIL",
        "num_runs": result["num_runs"],
        "unique_hashes": result["unique_hashes"],
        "canonical_hash": result["hashes"][0] if result["passed"] else None,
        "hashes": result["hashes"]
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[Report] Written to {output_path}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Duplicate Instance Tie-Break Test (A3)")
    parser.add_argument("--evidence", action="store_true", help="Write evidence report")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")

    args = parser.parse_args()

    result = run_duplicate_instance_test(verbose=not args.quiet)

    if args.evidence:
        write_report(result)

    sys.exit(0 if result["passed"] else 1)
