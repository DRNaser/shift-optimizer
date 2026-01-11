"""
V3 Solver Regression Proof Test
================================

ADR-003: This test validates the V3 solver canonical output.

GOLDEN DATASET: Wien pilot forecast (1385 tours, 6 days)
EXPECTED RESULT: 145 FTE, 0 PT, 100% coverage

This test MUST pass before any release or pilot deployment.

Test Criteria:
1. Coverage == 100% (1385 tours assigned)
2. PT drivers == 0
3. FTE count == 145 (strict)
4. Hours range: 40.0h - 55.0h (within constraints)
5. Determinism: Same result across 2 runs with same seed

Evidence Output:
- evidence/v3_regression_proof_<timestamp>.json
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "v3"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.models import Tour, Weekday
from v3.solver_v2_integration import partition_tours_into_blocks
from src.services.block_heuristic_solver import BlockHeuristicSolver
from datetime import time as dt_time


# =============================================================================
# GOLDEN DATASET EXPECTATIONS
# =============================================================================

GOLDEN_SEED = 94  # Production seed
GOLDEN_FTE_COUNT = 145
GOLDEN_PT_COUNT = 0
GOLDEN_TOUR_COUNT = 1385
GOLDEN_COVERAGE_PERCENT = 100.0
GOLDEN_HOURS_MIN = 40.0
GOLDEN_HOURS_MAX = 55.0  # Hard constraint


def parse_forecast_csv_multicolumn(csv_path: str) -> list[Tour]:
    """
    Parse the multi-column German-formatted forecast CSV into Tour objects.
    """
    tours = []
    tour_counter = 0

    column_days = [
        (0, 1, Weekday.MONDAY),
        (2, 3, Weekday.TUESDAY),
        (4, 5, Weekday.WEDNESDAY),
        (6, 7, Weekday.THURSDAY),
        (8, 9, Weekday.FRIDAY),
        (10, 11, Weekday.SATURDAY),
    ]

    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(";")

        for time_col, count_col, weekday in column_days:
            if time_col >= len(parts) or count_col >= len(parts):
                continue

            time_range = parts[time_col].strip()
            count_str = parts[count_col].strip()

            if not time_range or not count_str or "-" not in time_range:
                continue

            try:
                count = int(count_str)
                if count <= 0:
                    continue

                start_str, end_str = time_range.split("-")
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))

                for i in range(count):
                    tour_counter += 1
                    tour = Tour(
                        id=f"T{tour_counter:04d}",
                        day=weekday,
                        start_time=dt_time(start_h, start_m),
                        end_time=dt_time(end_h, end_m),
                    )
                    tours.append(tour)
            except Exception:
                continue

    return tours


def run_v3_solver(tours: list[Tour], seed: int) -> dict:
    """
    Run V3 original solver pipeline.

    Returns:
        dict with solver results and metrics
    """
    # Step 1: Greedy block partitioning
    blocks = partition_tours_into_blocks(tours, seed=seed)

    # Step 2: BlockHeuristicSolver (Min-Cost Max-Flow + Consolidation + PT Elimination)
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve()

    # Compute metrics
    fte_drivers = [d for d in drivers if d.total_hours >= 40.0]
    pt_drivers = [d for d in drivers if d.total_hours < 40.0]

    total_tours_assigned = sum(len(b.tours) for d in drivers for b in d.blocks)

    hours_list = [d.total_hours for d in drivers]

    # Build determinism hash
    driver_data = sorted([
        (d.id, round(d.total_hours, 2), len(d.blocks))
        for d in drivers
    ])
    determinism_hash = hashlib.sha256(
        json.dumps(driver_data, sort_keys=True).encode()
    ).hexdigest()

    return {
        "total_drivers": len(drivers),
        "fte_count": len(fte_drivers),
        "pt_count": len(pt_drivers),
        "tours_assigned": total_tours_assigned,
        "coverage_percent": round(100 * total_tours_assigned / len(tours), 2) if tours else 0,
        "hours_min": round(min(hours_list), 2) if hours_list else 0,
        "hours_max": round(max(hours_list), 2) if hours_list else 0,
        "hours_avg": round(sum(hours_list) / len(hours_list), 2) if hours_list else 0,
        "blocks_total": len(blocks),
        "blocks_3er": sum(1 for b in blocks if len(b.tours) == 3),
        "blocks_2er": sum(1 for b in blocks if len(b.tours) == 2),
        "blocks_1er": sum(1 for b in blocks if len(b.tours) == 1),
        "determinism_hash": determinism_hash,
        "seed": seed,
        "solver_engine": "v3",
    }


def test_v3_regression_golden_dataset():
    """
    GOLDEN DATASET REGRESSION TEST

    This test validates the V3 solver produces the expected result:
    - 145 FTE drivers
    - 0 PT drivers
    - 100% coverage
    - Hours within 40-55h range
    """
    # Locate forecast CSV
    csv_path = Path(__file__).parent.parent.parent / "forecast input.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {csv_path}")

    # Parse tours
    tours = parse_forecast_csv_multicolumn(str(csv_path))
    assert len(tours) == GOLDEN_TOUR_COUNT, f"Expected {GOLDEN_TOUR_COUNT} tours, got {len(tours)}"

    # Run solver
    result = run_v3_solver(tours, seed=GOLDEN_SEED)

    # =================================================================
    # REGRESSION ASSERTIONS
    # =================================================================

    # 1. Coverage must be 100%
    assert result["tours_assigned"] == GOLDEN_TOUR_COUNT, \
        f"Coverage FAIL: {result['tours_assigned']}/{GOLDEN_TOUR_COUNT} tours assigned"
    assert result["coverage_percent"] == GOLDEN_COVERAGE_PERCENT, \
        f"Coverage percent FAIL: {result['coverage_percent']}% (expected {GOLDEN_COVERAGE_PERCENT}%)"

    # 2. PT drivers must be 0
    assert result["pt_count"] == GOLDEN_PT_COUNT, \
        f"PT count FAIL: {result['pt_count']} PT drivers (expected {GOLDEN_PT_COUNT})"

    # 3. FTE count must be exactly 145
    assert result["fte_count"] == GOLDEN_FTE_COUNT, \
        f"FTE count FAIL: {result['fte_count']} FTE drivers (expected {GOLDEN_FTE_COUNT})"

    # 4. Hours must be within constraints
    assert result["hours_min"] >= GOLDEN_HOURS_MIN, \
        f"Hours min FAIL: {result['hours_min']}h < {GOLDEN_HOURS_MIN}h"
    assert result["hours_max"] <= GOLDEN_HOURS_MAX, \
        f"Hours max FAIL: {result['hours_max']}h > {GOLDEN_HOURS_MAX}h"

    print(f"V3 Regression Test PASSED:")
    print(f"  FTE: {result['fte_count']} (expected {GOLDEN_FTE_COUNT})")
    print(f"  PT: {result['pt_count']} (expected {GOLDEN_PT_COUNT})")
    print(f"  Coverage: {result['coverage_percent']}%")
    print(f"  Hours: {result['hours_min']}h - {result['hours_max']}h")


def test_v3_determinism():
    """
    DETERMINISM TEST

    Verifies that V3 solver produces identical results across 2 runs.
    """
    csv_path = Path(__file__).parent.parent.parent / "forecast input.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {csv_path}")

    tours = parse_forecast_csv_multicolumn(str(csv_path))

    # Run 1
    result1 = run_v3_solver(tours, seed=GOLDEN_SEED)

    # Run 2 (same seed)
    result2 = run_v3_solver(tours, seed=GOLDEN_SEED)

    # Verify identical results
    assert result1["determinism_hash"] == result2["determinism_hash"], \
        f"Determinism FAIL: hash1={result1['determinism_hash'][:16]}... != hash2={result2['determinism_hash'][:16]}..."

    assert result1["fte_count"] == result2["fte_count"], \
        f"FTE count mismatch: {result1['fte_count']} vs {result2['fte_count']}"

    assert result1["pt_count"] == result2["pt_count"], \
        f"PT count mismatch: {result1['pt_count']} vs {result2['pt_count']}"

    print(f"V3 Determinism Test PASSED:")
    print(f"  Hash: {result1['determinism_hash'][:32]}...")
    print(f"  Identical results across 2 runs")


def generate_regression_evidence():
    """
    Generate evidence file for V3 regression proof.

    Output: evidence/v3_regression_proof_<timestamp>.json
    """
    csv_path = Path(__file__).parent.parent.parent / "forecast input.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {csv_path}")

    tours = parse_forecast_csv_multicolumn(str(csv_path))
    result = run_v3_solver(tours, seed=GOLDEN_SEED)

    # Build evidence
    evidence = {
        "test_type": "v3_solver_regression_proof",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "solver_engine": "v3",
        "seed": GOLDEN_SEED,
        "input": {
            "dataset": "wien_pilot_forecast",
            "tour_count": len(tours),
            "days": 6,
        },
        "result": result,
        "assertions": {
            "coverage_100_percent": result["coverage_percent"] == 100.0,
            "pt_count_zero": result["pt_count"] == 0,
            "fte_count_145": result["fte_count"] == 145,
            "hours_in_range": result["hours_min"] >= 40.0 and result["hours_max"] <= 55.0,
        },
        "verdict": "PASS" if all([
            result["coverage_percent"] == 100.0,
            result["pt_count"] == 0,
            result["fte_count"] == 145,
            result["hours_min"] >= 40.0,
            result["hours_max"] <= 55.0,
        ]) else "FAIL",
    }

    # Write evidence file
    evidence_dir = Path(__file__).parent.parent.parent / "evidence"
    evidence_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_file = evidence_dir / f"v3_regression_proof_{timestamp}.json"

    with open(evidence_file, "w") as f:
        json.dump(evidence, f, indent=2)

    print(f"Evidence written to: {evidence_file}")
    return evidence_file, evidence


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="V3 Solver Regression Tests")
    parser.add_argument("--evidence", action="store_true", help="Generate evidence file")
    args = parser.parse_args()

    print("=" * 70)
    print("V3 SOLVER REGRESSION PROOF TEST")
    print("=" * 70)
    print()

    try:
        # Run regression test
        test_v3_regression_golden_dataset()
        print()

        # Run determinism test
        test_v3_determinism()
        print()

        # Generate evidence if requested
        if args.evidence:
            print("-" * 70)
            evidence_file, evidence = generate_regression_evidence()
            print(f"Verdict: {evidence['verdict']}")

        print()
        print("=" * 70)
        print("ALL TESTS PASSED")
        print("=" * 70)

    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"TEST FAILED: {e}")
        print("=" * 70)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 70)
        print(f"ERROR: {e}")
        print("=" * 70)
        sys.exit(1)
