"""
SOLVEREIGN Solver Determinism Cross-Process Proof (PR-4 Addendum)
==================================================================

This test PROVES determinism holds ACROSS PROCESSES with varying
PYTHONHASHSEED values. This is critical because:

1. Python's hash() is randomized by default (PYTHONHASHSEED)
2. dict/set iteration order depends on hash values
3. If our solver used dict/set ordering, different processes would
   produce different results

Test Strategy:
    1. Spawn N subprocesses with DIFFERENT PYTHONHASHSEED values
    2. Each subprocess runs the solver and returns output hash
    3. Assert ALL hashes are identical

This proves the solver does NOT depend on Python's internal hash state.

Exit Codes:
    0 = PASS (all processes produce identical output)
    1 = FAIL (at least one process differs)
"""

import sys
import os
import json
import subprocess
import hashlib
from pathlib import Path
from datetime import time

# Test configuration
HASHSEED_VALUES = [0, 42, 12345, 999999, "random"]
NUM_RUNS_PER_SEED = 1


def create_test_instances_json() -> str:
    """Create test instances as JSON string for subprocess."""
    instances = []
    instance_id = 1

    tour_templates = [
        ("06:00", "10:00"),
        ("10:45", "14:45"),
        ("15:30", "19:30"),
        ("08:00", "12:00"),
        ("12:45", "16:45"),
        ("17:30", "21:30"),
    ]

    depots = ["West", "Nord", "Ost"]

    for day in range(1, 8):
        num_tours = 6 if day <= 5 else 4
        for i in range(num_tours):
            template_idx = (day + i) % len(tour_templates)
            start_str, end_str = tour_templates[template_idx]
            depot = depots[(day + i) % len(depots)]

            instances.append({
                "id": instance_id,
                "day": day,
                "start_ts": start_str,
                "end_ts": end_str,
                "depot": depot,
                "skill": None,
                "work_hours": 4.0,
                "duration_min": 240,
                "crosses_midnight": False
            })
            instance_id += 1

    return json.dumps(instances)


SUBPROCESS_SCRIPT = '''
import sys
import os
import json
import hashlib
from datetime import time

# cwd is set to backend_py, so we can import directly
from packs.roster.engine.solver_v2_integration import solve_with_v2_solver

def main():
    # Read instances from stdin
    instances_json = sys.stdin.read()
    instances_raw = json.loads(instances_json)

    # Convert time strings back to time objects
    instances = []
    for inst in instances_raw:
        start_parts = inst["start_ts"].split(":")
        end_parts = inst["end_ts"].split(":")
        instances.append({
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

    # Run solver (suppress output)
    import io
    from contextlib import redirect_stdout
    with redirect_stdout(io.StringIO()):
        assignments = solve_with_v2_solver(instances)

    # Hash the result
    sorted_assignments = sorted(
        assignments,
        key=lambda a: (a["driver_id"], a["tour_instance_id"])
    )
    json_str = json.dumps(sorted_assignments, sort_keys=True, default=str)
    result_hash = hashlib.sha256(json_str.encode()).hexdigest()

    # Output hash and stats
    print(json.dumps({
        "hash": result_hash,
        "num_assignments": len(assignments),
        "num_drivers": len(set(a["driver_id"] for a in assignments)),
        "pythonhashseed": str(os.environ.get("PYTHONHASHSEED", "not_set"))
    }))

if __name__ == "__main__":
    main()
'''


def run_subprocess_with_hashseed(hashseed: str, instances_json: str, backend_dir: Path) -> dict:
    """Run solver in subprocess with specific PYTHONHASHSEED."""
    env = os.environ.copy()
    if hashseed != "random":
        env["PYTHONHASHSEED"] = str(hashseed)
    else:
        # Remove PYTHONHASHSEED to use random (default)
        env.pop("PYTHONHASHSEED", None)

    result = subprocess.run(
        [sys.executable, "-c", SUBPROCESS_SCRIPT],
        input=instances_json,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(backend_dir)
    )

    if result.returncode != 0:
        raise RuntimeError(f"Subprocess failed: {result.stderr}")

    # Parse output (last line is JSON)
    output_lines = result.stdout.strip().split("\n")
    return json.loads(output_lines[-1])


def run_crossprocess_determinism_test(verbose: bool = True) -> dict:
    """
    Run cross-process determinism proof test.

    Returns:
        dict with:
            - passed: bool
            - results: list of (hashseed, hash) tuples
            - unique_hashes: count of unique hashes
    """
    if verbose:
        print("=" * 70)
        print(" SOLVEREIGN Solver Cross-Process Determinism Proof")
        print("=" * 70)
        print()
        print(" This test proves determinism holds across processes with")
        print(" DIFFERENT PYTHONHASHSEED values. If our solver depended on")
        print(" dict/set iteration order, results would vary.")
        print()

    # Get backend directory
    backend_dir = Path(__file__).parent.parent.parent.parent.parent

    # Create test data
    instances_json = create_test_instances_json()
    if verbose:
        instances = json.loads(instances_json)
        print(f"[Setup] Created {len(instances)} tour instances")
        print(f"[Setup] Testing with PYTHONHASHSEED values: {HASHSEED_VALUES}")
        print()

    results = []

    for hashseed in HASHSEED_VALUES:
        if verbose:
            print(f"[PYTHONHASHSEED={hashseed}] Running solver in subprocess...")

        try:
            result = run_subprocess_with_hashseed(str(hashseed), instances_json, backend_dir)
            results.append({
                "hashseed": hashseed,
                "hash": result["hash"],
                "num_assignments": result["num_assignments"],
                "num_drivers": result["num_drivers"]
            })

            if verbose:
                print(f"[PYTHONHASHSEED={hashseed}] Hash: {result['hash'][:16]}... | "
                      f"Assignments: {result['num_assignments']} | Drivers: {result['num_drivers']}")
        except Exception as e:
            if verbose:
                print(f"[PYTHONHASHSEED={hashseed}] ERROR: {e}")
            results.append({
                "hashseed": hashseed,
                "hash": f"ERROR: {e}",
                "num_assignments": 0,
                "num_drivers": 0
            })

    # Check all hashes match
    hashes = [r["hash"] for r in results if not r["hash"].startswith("ERROR")]
    passed = len(set(hashes)) == 1 and len(hashes) == len(HASHSEED_VALUES)

    if verbose:
        print()
        print("=" * 70)
        if passed:
            print(" [PASS] CROSS-PROCESS DETERMINISM: All PYTHONHASHSEED values")
            print("        produced IDENTICAL output")
        else:
            print(" [FAIL] CROSS-PROCESS DETERMINISM: Results differ!")
            print(f"        Unique hashes: {len(set(hashes))}")
            for r in results:
                print(f"        PYTHONHASHSEED={r['hashseed']}: {r['hash'][:32]}...")
        print("=" * 70)

    return {
        "passed": passed,
        "results": results,
        "unique_hashes": len(set(hashes))
    }


def write_gate_report(result: dict, output_path: str = "gate_report_crossprocess.json"):
    """Write machine-readable gate report."""
    report = {
        "gate": "CROSSPROCESS_DETERMINISM",
        "status": "PASS" if result["passed"] else "FAIL",
        "hashseed_values_tested": HASHSEED_VALUES,
        "unique_hashes": result["unique_hashes"],
        "output_hash": result["results"][0]["hash"] if result["passed"] else None,
        "results": result["results"]
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[Gate Report] Written to {output_path}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cross-Process Determinism Proof")
    parser.add_argument("--evidence", action="store_true", help="Write gate_report.json")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")

    args = parser.parse_args()

    result = run_crossprocess_determinism_test(verbose=not args.quiet)

    if args.evidence:
        write_gate_report(result)

    sys.exit(0 if result["passed"] else 1)
