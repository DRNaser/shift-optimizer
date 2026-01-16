#!/usr/bin/env python3
"""
SOLVEREIGN V3.7 - Sick Call Drill (Gate H1)
============================================

Drill: 5 drivers marked unavailable, repair plan with 100% coverage.

Requirements (HARD):
- All 7 audits must PASS after repair
- Coverage must remain 100%
- Churn minimized (diff summary required)
- Evidence includes repair_reason="sick_call"

Usage:
    python scripts/run_sick_call_drill.py
    python scripts/run_sick_call_drill.py --plan-id 1 --absent-drivers 1,2,3,4,5
    python scripts/run_sick_call_drill.py --dry-run

Exit Codes:
    0 = PASS (all audits pass, 100% coverage)
    1 = WARN (audits pass but churn > 10%)
    2 = FAIL (audit failures or coverage < 100%)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_drill(
    tenant_id: str = "gurkerl",
    plan_version_id: int = None,
    absent_driver_ids: list = None,
    seed: int = 94,
    dry_run: bool = False,
    output_dir: str = None
) -> dict:
    """
    Execute sick-call drill.

    Args:
        tenant_id: Tenant UUID or code
        plan_version_id: Baseline plan (will create one if not provided)
        absent_driver_ids: Driver IDs to mark absent (default: first 5)
        seed: Random seed for determinism
        dry_run: If True, simulate without DB writes
        output_dir: Directory for evidence artifacts

    Returns:
        Drill result dict
    """
    print("=" * 70)
    print("SOLVEREIGN SICK-CALL DRILL (Gate H1)")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Tenant: {tenant_id}")
    print(f"Seed: {seed}")
    print(f"Dry Run: {dry_run}")
    print()

    start_time = time.perf_counter()

    # Setup output directory
    if output_dir is None:
        output_dir = PROJECT_ROOT / "artifacts" / "drills" / "sick_call"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "drill_type": "SICK_CALL",
        "timestamp": datetime.now().isoformat(),
        "tenant_id": tenant_id,
        "seed": seed,
        "status": "PENDING",
        "baseline_plan_id": plan_version_id,
        "absent_driver_ids": absent_driver_ids or [],
        "evidence": {},
        "audits": {},
        "churn_metrics": {},
        "verdict": "PENDING"
    }

    try:
        if dry_run:
            # Simulate drill without database
            result = _run_dry_run(result)
        else:
            # Run actual drill with database
            result = _run_with_database(
                result,
                tenant_id,
                plan_version_id,
                absent_driver_ids,
                seed
            )

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        result["verdict"] = "FAIL"
        print(f"\n[ERROR] {e}")

    # Calculate final verdict
    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
    result["execution_time_ms"] = execution_time_ms

    # Save evidence
    evidence_file = output_dir / f"sick_call_drill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(evidence_file, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[INFO] Evidence saved to: {evidence_file}")

    # Print summary
    _print_summary(result)

    return result


def _run_dry_run(result: dict) -> dict:
    """Simulate drill without database."""
    print("\n[1/5] SIMULATING baseline plan creation...")
    result["baseline_plan_id"] = 1
    result["baseline_drivers"] = 145
    result["baseline_coverage"] = 100.0
    print("       Created simulated baseline: 145 drivers, 100% coverage")

    print("\n[2/5] SIMULATING absent drivers (5)...")
    result["absent_driver_ids"] = [1, 2, 3, 4, 5]
    print(f"       Absent: {result['absent_driver_ids']}")

    print("\n[3/5] SIMULATING repair execution...")
    result["new_plan_id"] = 2
    result["repair_success"] = True
    print("       Repair simulated successfully")

    print("\n[4/5] SIMULATING churn metrics...")
    result["churn_metrics"] = {
        "changed_assignments": 15,
        "total_assignments": 1385,
        "churn_rate": 0.0108,
        "drivers_added": 0,
        "drivers_removed": 5,
        "tours_reassigned": 15,
        "unchanged_tours": 1370
    }
    print(f"       Churn rate: {result['churn_metrics']['churn_rate']:.2%}")
    print(f"       Tours reassigned: {result['churn_metrics']['tours_reassigned']}")

    print("\n[5/5] SIMULATING audits (7 checks)...")
    result["audits"] = {
        "all_passed": True,
        "checks_run": 7,
        "checks_passed": 7,
        "results": {
            "coverage": {"status": "PASS", "violations": 0},
            "overlap": {"status": "PASS", "violations": 0},
            "rest": {"status": "PASS", "violations": 0},
            "span_regular": {"status": "PASS", "violations": 0},
            "span_split": {"status": "PASS", "violations": 0},
            "fatigue": {"status": "PASS", "violations": 0},
            "55h_max": {"status": "PASS", "violations": 0}
        }
    }
    print("       7/7 audits PASS")

    # Set verdict
    result["status"] = "SUCCESS"
    result["new_coverage"] = 100.0
    result["new_drivers"] = 145

    if result["audits"]["all_passed"] and result["new_coverage"] == 100.0:
        if result["churn_metrics"]["churn_rate"] > 0.10:
            result["verdict"] = "WARN"
        else:
            result["verdict"] = "PASS"
    else:
        result["verdict"] = "FAIL"

    return result


def _run_with_database(
    result: dict,
    tenant_id: str,
    plan_version_id: int,
    absent_driver_ids: list,
    seed: int
) -> dict:
    """Run drill with actual database operations."""
    from packs.roster.engine.repair_service import RepairService, run_sick_call_drill

    print("\n[1/5] Loading baseline plan...")

    if plan_version_id is None:
        # Create baseline from golden run
        print("       Creating baseline from golden dataset...")
        from packs.roster.engine.solver_wrapper import solve_and_audit
        from packs.roster.engine.parser import parse_forecast_text

        # Use test data
        test_forecast = """
        Mo 08:00-16:00 5 Fahrer
        Di 06:00-14:00 5 Fahrer
        Mi 14:00-22:00 5 Fahrer
        Do 22:00-06:00 3 Fahrer
        Fr 06:00-10:00 + 15:00-19:00 2 Fahrer
        """

        parse_result = parse_forecast_text(test_forecast, source="drill", save_to_db=True)
        if parse_result["status"] == "FAIL":
            raise ValueError("Failed to parse test forecast")

        solve_result = solve_and_audit(parse_result["forecast_version_id"], seed=seed)
        plan_version_id = solve_result["plan_version_id"]

    result["baseline_plan_id"] = plan_version_id
    print(f"       Baseline plan ID: {plan_version_id}")

    print("\n[2/5] Selecting absent drivers...")
    if absent_driver_ids is None:
        # Get first 5 drivers from plan
        from packs.roster.engine import db
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT real_driver_id
                    FROM assignments
                    WHERE plan_version_id = %s AND real_driver_id IS NOT NULL
                    ORDER BY real_driver_id
                    LIMIT 5
                """, (plan_version_id,))
                absent_driver_ids = [row["real_driver_id"] for row in cur.fetchall()]

    result["absent_driver_ids"] = absent_driver_ids
    print(f"       Absent drivers: {absent_driver_ids}")

    print("\n[3/5] Executing repair...")
    evidence = run_sick_call_drill(
        tenant_id=tenant_id,
        plan_version_id=plan_version_id,
        absent_driver_ids=absent_driver_ids,
        seed=seed
    )

    result["repair_success"] = evidence.success
    result["new_plan_id"] = evidence.new_plan_id
    result["error"] = evidence.error_message

    if not evidence.success:
        result["status"] = "FAILED"
        result["verdict"] = "FAIL"
        return result

    print(f"       New plan ID: {evidence.new_plan_id}")

    print("\n[4/5] Computing churn metrics...")
    if evidence.churn_metrics:
        result["churn_metrics"] = evidence.churn_metrics.to_dict()
        print(f"       Churn rate: {result['churn_metrics']['churn_rate']:.2%}")
        print(f"       Tours reassigned: {result['churn_metrics']['tours_reassigned']}")
    else:
        result["churn_metrics"] = {}

    print("\n[5/5] Checking audit results...")
    result["audits"] = evidence.audit_results
    if evidence.audits_all_passed:
        print("       All audits PASS")
    else:
        print("       AUDIT FAILURES DETECTED")

    # Set final status
    result["status"] = "SUCCESS" if evidence.success else "FAILED"

    # Determine verdict
    if evidence.audits_all_passed:
        churn_rate = result["churn_metrics"].get("churn_rate", 0)
        if churn_rate > 0.10:
            result["verdict"] = "WARN"
            print("\n[WARN] Churn rate exceeds 10%")
        else:
            result["verdict"] = "PASS"
    else:
        result["verdict"] = "FAIL"

    return result


def _print_summary(result: dict) -> None:
    """Print drill summary."""
    print("\n" + "=" * 70)
    print("SICK-CALL DRILL SUMMARY")
    print("=" * 70)

    print(f"\nBaseline Plan ID: {result.get('baseline_plan_id')}")
    print(f"Absent Drivers:   {result.get('absent_driver_ids')}")
    print(f"New Plan ID:      {result.get('new_plan_id')}")

    if result.get("churn_metrics"):
        cm = result["churn_metrics"]
        print(f"\nChurn Metrics:")
        print(f"  - Tours Reassigned: {cm.get('tours_reassigned', 0)}")
        print(f"  - Churn Rate:       {cm.get('churn_rate', 0):.2%}")
        print(f"  - Unchanged Tours:  {cm.get('unchanged_tours', 0)}")

    if result.get("audits"):
        audits = result["audits"]
        passed = audits.get("checks_passed", 0)
        total = audits.get("checks_run", 0)
        print(f"\nAudits: {passed}/{total} PASS")

    print(f"\nExecution Time: {result.get('execution_time_ms', 0)}ms")

    verdict = result.get("verdict", "UNKNOWN")
    if verdict == "PASS":
        print(f"\n{'=' * 70}")
        print(f"VERDICT: PASS")
        print(f"{'=' * 70}")
    elif verdict == "WARN":
        print(f"\n{'=' * 70}")
        print(f"VERDICT: WARN (churn > 10%)")
        print(f"{'=' * 70}")
    else:
        print(f"\n{'=' * 70}")
        print(f"VERDICT: FAIL")
        if result.get("error"):
            print(f"Error: {result['error']}")
        print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Sick-Call Drill (Gate H1)"
    )
    parser.add_argument(
        "--tenant-id", "--tenant",
        dest="tenant_id",
        default="gurkerl",
        help="Tenant ID or code"
    )
    parser.add_argument(
        "--plan-id",
        type=int,
        default=None,
        help="Baseline plan version ID (creates one if not provided)"
    )
    parser.add_argument(
        "--absent-drivers",
        type=str,
        default=None,
        help="Comma-separated driver IDs (e.g., 1,2,3,4,5)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=94,
        help="Random seed for determinism"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without database"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for evidence artifacts"
    )

    args = parser.parse_args()

    # Parse absent drivers (supports both integer IDs and string codes like DRV001)
    absent_drivers = None
    if args.absent_drivers:
        raw_ids = [x.strip() for x in args.absent_drivers.split(",")]
        # Try to parse as integers, but keep as strings if not numeric (for dry-run mode)
        absent_drivers = []
        for x in raw_ids:
            try:
                absent_drivers.append(int(x))
            except ValueError:
                # String driver ID (e.g., "DRV001") - use as-is for dry-run
                absent_drivers.append(x)

    result = run_drill(
        tenant_id=args.tenant_id,
        plan_version_id=args.plan_id,
        absent_driver_ids=absent_drivers,
        seed=args.seed,
        dry_run=args.dry_run,
        output_dir=args.output_dir
    )

    # Exit with appropriate code
    verdict = result.get("verdict", "FAIL")
    if verdict == "PASS":
        sys.exit(0)
    elif verdict == "WARN":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
