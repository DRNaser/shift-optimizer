"""
SOLVEREIGN Duplicate Instance Tie-Break Determinism Test (A3 Proof)
====================================================================

Tests that the solver produces STABLE, DETERMINISTIC output when given
duplicate tour instances (identical day/start/end/depot/skill).

This proves A3: Canonical tie-break handles duplicate tour instances
deterministically using instance_number (from count expansion) NOT database IDs.

Test Strategy:
    1. Create tour instances where some have IDENTICAL intrinsic properties
       (simulating count > 1 expansion)
    2. Each duplicate gets a unique instance_number (1, 2, 3...) from expansion
    3. Run solver with different database ID assignments but SAME instance_numbers
    4. Assert ALL runs produce IDENTICAL output (DB IDs don't affect ordering)
    5. Test with shuffled input order to prove sort stability

CRITICAL: This test REJECTS the use of database IDs for ordering.
          Only instance_number (intrinsic to the tour definition) is allowed.

Exit Codes:
    0 = PASS (deterministic across all runs, DB IDs don't influence output)
    1 = FAIL (non-deterministic output detected OR DB IDs influenced ordering)
"""

import sys
import os
import json
import hashlib
import random
from datetime import time
from pathlib import Path

# Add backend_py to path
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def create_duplicate_instances_with_instance_numbers(
    id_offset: int = 0,
    shuffle_ids: bool = False
) -> list[dict]:
    """
    Create tour instances with DUPLICATES and canonical instance_numbers.

    Args:
        id_offset: Offset to add to database IDs (simulates different insertion orders)
        shuffle_ids: If True, shuffle the ID assignment (simulates out-of-order insertion)

    Returns:
        List of instances with:
            - id: database ID (varies based on offset/shuffle)
            - instance_number: canonical position from count expansion (FIXED)

    This simulates what happens when a tours_normalized row has count > 1:
    Multiple tour_instances are created with the same (day, start, end, depot, skill)
    but each gets a unique instance_number (1, 2, 3...).
    """
    # Base data for instances - instance_number is the INTRINSIC tie-breaker
    base_instances = [
        # 3 IDENTICAL instances (simulating count=3 for 06:00-10:00)
        {"day": 1, "start_ts": "06:00", "end_ts": "10:00", "depot": "West", "skill": None, "instance_number": 1},
        {"day": 1, "start_ts": "06:00", "end_ts": "10:00", "depot": "West", "skill": None, "instance_number": 2},
        {"day": 1, "start_ts": "06:00", "end_ts": "10:00", "depot": "West", "skill": None, "instance_number": 3},
        # 2 IDENTICAL instances (simulating count=2 for 10:45-14:45)
        {"day": 1, "start_ts": "10:45", "end_ts": "14:45", "depot": "West", "skill": None, "instance_number": 1},
        {"day": 1, "start_ts": "10:45", "end_ts": "14:45", "depot": "West", "skill": None, "instance_number": 2},
        # Unique instances (Tue-Fri)
        {"day": 2, "start_ts": "08:00", "end_ts": "16:00", "depot": "Nord", "skill": None, "instance_number": 1},
        {"day": 3, "start_ts": "08:00", "end_ts": "16:00", "depot": "Nord", "skill": None, "instance_number": 1},
        {"day": 4, "start_ts": "08:00", "end_ts": "16:00", "depot": "Nord", "skill": None, "instance_number": 1},
        {"day": 5, "start_ts": "08:00", "end_ts": "16:00", "depot": "Nord", "skill": None, "instance_number": 1},
    ]

    # Assign database IDs
    ids = list(range(1 + id_offset, len(base_instances) + 1 + id_offset))
    if shuffle_ids:
        random.shuffle(ids)

    instances = []
    for idx, (base, db_id) in enumerate(zip(base_instances, ids)):
        instances.append({
            "id": db_id,  # Database ID (varies - should NOT affect ordering)
            "day": base["day"],
            "start_ts": base["start_ts"],
            "end_ts": base["end_ts"],
            "depot": base["depot"],
            "skill": base["skill"],
            "instance_number": base["instance_number"],  # INTRINSIC (canonical)
            "work_hours": 8.0 if "16:00" in base["end_ts"] else 4.0,
            "duration_min": 480 if "16:00" in base["end_ts"] else 240,
            "crosses_midnight": False
        })

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
            "instance_number": inst["instance_number"],  # CRITICAL: Pass through
            "work_hours": inst["work_hours"],
            "duration_min": inst["duration_min"],
            "crosses_midnight": inst["crosses_midnight"]
        })
    return converted


def compute_output_hash(assignments: list[dict], instances: list[dict]) -> str:
    """
    Compute deterministic hash of solver output using CANONICAL fields only.

    IMPORTANT: Uses instance_number (canonical) NOT tour_instance_id (database ID).
    This verifies that the solver assigns tours to drivers based on intrinsic
    properties, not database IDs.

    Args:
        assignments: Solver output with tour_instance_id (database ID)
        instances: Original instances with instance_number mapping

    Returns:
        SHA256 hash based on (instance_number, driver_id) pairs
    """
    # Build lookup: database_id -> instance_number
    id_to_instance_number = {inst["id"]: inst["instance_number"] for inst in instances}

    # Normalize assignments using instance_number (canonical)
    normalized = []
    for a in assignments:
        db_id = a["tour_instance_id"]
        instance_number = id_to_instance_number.get(db_id, 0)
        normalized.append({
            "instance_number": instance_number,  # CANONICAL (not DB ID)
            "driver_id": a["driver_id"],
            "day": a["day"]
        })

    sorted_assignments = sorted(
        normalized,
        key=lambda a: (a["day"], a["instance_number"], a["driver_id"])
    )
    json_str = json.dumps(sorted_assignments, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()


def run_duplicate_instance_test(verbose: bool = True) -> dict:
    """
    Run duplicate instance tie-break test.

    This test PROVES that:
    1. Database IDs do NOT influence solver ordering
    2. Only instance_number (intrinsic) is used for tie-breaking
    3. Output is IDENTICAL regardless of ID assignment or input order

    Returns:
        dict with:
            - passed: bool
            - num_runs: int
            - hashes: list of output hashes
            - unique_hashes: int
            - id_independent: bool (True if IDs didn't affect output)
    """
    import io
    from contextlib import redirect_stdout
    from packs.roster.engine.solver_v2_integration import solve_with_v2_solver

    if verbose:
        print("=" * 70)
        print(" SOLVEREIGN Duplicate Instance Tie-Break Test (A3)")
        print("=" * 70)
        print()
        print(" This test REJECTS database ID influence on ordering.")
        print(" Only instance_number (from count expansion) is allowed.")
        print()

    hashes = []
    id_configs = []

    # Test 1: Normal ID assignment (1, 2, 3, ...)
    if verbose:
        print("[Test 1] Normal ID assignment (id=1,2,3,...)")
    raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=0, shuffle_ids=False)
    instances = convert_to_tour_objects(raw_instances)

    with redirect_stdout(io.StringIO()):
        assignments = solve_with_v2_solver(instances)
    output_hash = compute_output_hash(assignments, raw_instances)
    hashes.append(output_hash)
    id_configs.append("normal_ids")
    if verbose:
        print(f"         Hash: {output_hash[:16]}... | Assignments: {len(assignments)}")

    # Test 2: Offset ID assignment (id=100,101,102,...)
    if verbose:
        print("\n[Test 2] Offset ID assignment (id=100,101,102,...)")
    raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=99, shuffle_ids=False)
    instances = convert_to_tour_objects(raw_instances)

    with redirect_stdout(io.StringIO()):
        assignments = solve_with_v2_solver(instances)
    output_hash = compute_output_hash(assignments, raw_instances)
    hashes.append(output_hash)
    id_configs.append("offset_ids")
    if verbose:
        print(f"         Hash: {output_hash[:16]}... | Assignments: {len(assignments)}")

    # Test 3: Shuffled ID assignment (random IDs, but same instance_numbers)
    if verbose:
        print("\n[Test 3] Shuffled ID assignment (random IDs)")
    random.seed(12345)
    raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=0, shuffle_ids=True)
    instances = convert_to_tour_objects(raw_instances)

    with redirect_stdout(io.StringIO()):
        assignments = solve_with_v2_solver(instances)
    output_hash = compute_output_hash(assignments, raw_instances)
    hashes.append(output_hash)
    id_configs.append("shuffled_ids")
    if verbose:
        print(f"         Hash: {output_hash[:16]}... | Assignments: {len(assignments)}")

    # Test 4: Reversed ID assignment (highest to lowest)
    if verbose:
        print("\n[Test 4] Reversed ID assignment (id=9,8,7,...)")
    raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=0, shuffle_ids=False)
    # Reverse the IDs
    for i, inst in enumerate(raw_instances):
        inst["id"] = len(raw_instances) - i
    instances = convert_to_tour_objects(raw_instances)

    with redirect_stdout(io.StringIO()):
        assignments = solve_with_v2_solver(instances)
    output_hash = compute_output_hash(assignments, raw_instances)
    hashes.append(output_hash)
    id_configs.append("reversed_ids")
    if verbose:
        print(f"         Hash: {output_hash[:16]}... | Assignments: {len(assignments)}")

    # Test 5-7: Shuffled input order (same IDs/instance_numbers, different order)
    if verbose:
        print("\n[Test 5-7] Shuffled INPUT ORDER (same data, different order)")

    for shuffle_run in range(3):
        raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=0, shuffle_ids=False)
        random.seed(shuffle_run * 7777)
        random.shuffle(raw_instances)
        instances = convert_to_tour_objects(raw_instances)

        with redirect_stdout(io.StringIO()):
            assignments = solve_with_v2_solver(instances)
        output_hash = compute_output_hash(assignments, raw_instances)
        hashes.append(output_hash)
        id_configs.append(f"shuffled_order_{shuffle_run}")
        if verbose:
            print(f"         Shuffle {shuffle_run + 1}: Hash: {output_hash[:16]}...")

    # Test 8: Repeated runs with identical input
    if verbose:
        print("\n[Test 8] 3 identical runs (stability check)")
    raw_instances = create_duplicate_instances_with_instance_numbers(id_offset=0, shuffle_ids=False)
    instances = convert_to_tour_objects(raw_instances)

    for run in range(3):
        with redirect_stdout(io.StringIO()):
            assignments = solve_with_v2_solver(instances)
        output_hash = compute_output_hash(assignments, raw_instances)
        hashes.append(output_hash)
        id_configs.append(f"repeat_run_{run}")
        if verbose:
            print(f"         Run {run + 1}: Hash: {output_hash[:16]}...")

    # Verify all hashes match
    unique_hashes = len(set(hashes))
    passed = unique_hashes == 1

    # Check ID independence specifically
    id_test_hashes = hashes[:4]  # Tests 1-4 (different ID schemes)
    id_independent = len(set(id_test_hashes)) == 1

    if verbose:
        print()
        print("=" * 70)
        if passed:
            print(" [PASS] DUPLICATE INSTANCE TIE-BREAK: All runs produced IDENTICAL output")
            print()
            print(" Verification:")
            print(f"   - Total runs: {len(hashes)}")
            print(f"   - Unique hashes: {unique_hashes}")
            print(f"   - ID-independent: {id_independent}")
            print(f"   - Canonical hash: {hashes[0][:32]}...")
            print()
            print(" Conclusion:")
            print("   Database IDs do NOT influence ordering.")
            print("   Only instance_number (intrinsic) is used for tie-breaking.")
        else:
            print(f" [FAIL] DUPLICATE INSTANCE TIE-BREAK: {unique_hashes} different hashes!")
            print()
            print(" Failure analysis:")
            for i, (cfg, h) in enumerate(zip(id_configs, hashes)):
                print(f"   {cfg:20s}: {h[:32]}...")
            print()
            if not id_independent:
                print(" CRITICAL: Database IDs influenced ordering! This violates A3.")
                print("           The solver must use instance_number, NOT tour.id.")
        print("=" * 70)

    return {
        "passed": passed,
        "num_runs": len(hashes),
        "hashes": hashes,
        "unique_hashes": unique_hashes,
        "id_independent": id_independent,
        "id_configs": id_configs
    }


def write_report(result: dict, output_path: str = "gate_report_duplicate_tiebreak.json"):
    """Write machine-readable report."""
    report = {
        "gate": "DUPLICATE_INSTANCE_TIEBREAK",
        "status": "PASS" if result["passed"] else "FAIL",
        "num_runs": result["num_runs"],
        "unique_hashes": result["unique_hashes"],
        "id_independent": result["id_independent"],
        "canonical_hash": result["hashes"][0] if result["passed"] else None,
        "hashes": result["hashes"],
        "id_configs": result["id_configs"]
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
