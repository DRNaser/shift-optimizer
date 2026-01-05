"""
SOLVEREIGN V3.3a - Crash Recovery
=================================

Handles stuck plans after solver crashes:
- Detects plans stuck in SOLVING status
- Marks them as FAILED after timeout
- Logs recovery actions to audit_log

Usage:
    # CLI
    python -m v3.crash_recovery --max-age-minutes 30

    # Programmatic
    from v3.crash_recovery import run_crash_recovery
    recovered = run_crash_recovery(max_age_minutes=30)

Per senior dev requirements:
- SOLVING older than threshold → FAILED
- error_message recorded
- audit_log entry created
"""

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from .db import get_connection

logger = logging.getLogger(__name__)


def find_stuck_plans(max_age_minutes: int = 30) -> List[Dict]:
    """
    Find plans stuck in SOLVING status.

    Args:
        max_age_minutes: Plans SOLVING longer than this are considered stuck

    Returns:
        List of stuck plan records
    """
    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pv.id,
                    pv.forecast_version_id,
                    pv.seed,
                    pv.status,
                    pv.created_at,
                    pv.tenant_id,
                    EXTRACT(EPOCH FROM (NOW() - pv.created_at)) / 60 as age_minutes
                FROM plan_versions pv
                WHERE pv.status = 'SOLVING'
                  AND pv.created_at < %s
                ORDER BY pv.created_at ASC
            """, (cutoff,))

            rows = cur.fetchall()
            return [dict(row) for row in rows]


def recover_stuck_plan(plan_version_id: int, reason: str = "Crash recovery timeout") -> Dict:
    """
    Recover a single stuck plan by marking it as FAILED.

    Args:
        plan_version_id: Plan to recover
        reason: Reason for failure

    Returns:
        Recovery result dict
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get current plan state
            cur.execute("""
                SELECT id, status, created_at, tenant_id
                FROM plan_versions
                WHERE id = %s
            """, (plan_version_id,))

            plan = cur.fetchone()
            if not plan:
                return {
                    "plan_version_id": plan_version_id,
                    "status": "error",
                    "message": "Plan not found"
                }

            if plan["status"] != "SOLVING":
                return {
                    "plan_version_id": plan_version_id,
                    "status": "skipped",
                    "message": f"Plan status is {plan['status']}, not SOLVING"
                }

            # Update plan to FAILED
            cur.execute("""
                UPDATE plan_versions
                SET status = 'FAILED',
                    notes = COALESCE(notes, '') || %s
                WHERE id = %s
            """, (f"\n[CRASH_RECOVERY] {reason} at {datetime.now().isoformat()}", plan_version_id))

            # Create audit log entry
            cur.execute("""
                INSERT INTO audit_log (
                    plan_version_id,
                    check_name,
                    status,
                    count,
                    details_json,
                    tenant_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                plan_version_id,
                "CRASH_RECOVERY",
                "RECOVERED",
                1,
                json.dumps({
                    "reason": reason,
                    "original_status": "SOLVING",
                    "new_status": "FAILED",
                    "stuck_since": plan["created_at"].isoformat() if plan["created_at"] else None,
                    "recovered_at": datetime.now().isoformat(),
                }),
                plan["tenant_id"]
            ))
            audit_id = cur.fetchone()["id"]

            conn.commit()

            return {
                "plan_version_id": plan_version_id,
                "status": "recovered",
                "audit_log_id": audit_id,
                "message": f"Plan marked as FAILED: {reason}"
            }


def run_crash_recovery(
    max_age_minutes: int = 30,
    dry_run: bool = False
) -> Dict:
    """
    Run crash recovery for all stuck plans.

    Args:
        max_age_minutes: Plans SOLVING longer than this are considered stuck
        dry_run: If True, don't actually update plans

    Returns:
        Recovery summary dict
    """
    logger.info(f"Starting crash recovery (max_age={max_age_minutes}min, dry_run={dry_run})")

    # Find stuck plans
    stuck_plans = find_stuck_plans(max_age_minutes)

    if not stuck_plans:
        logger.info("No stuck plans found")
        return {
            "status": "ok",
            "stuck_count": 0,
            "recovered_count": 0,
            "plans": []
        }

    logger.warning(f"Found {len(stuck_plans)} stuck plans")

    # Recover each plan
    results = []
    for plan in stuck_plans:
        if dry_run:
            result = {
                "plan_version_id": plan["id"],
                "status": "dry_run",
                "message": f"Would recover plan (age: {plan['age_minutes']:.1f}min)",
                "age_minutes": plan["age_minutes"]
            }
        else:
            result = recover_stuck_plan(
                plan["id"],
                reason=f"Stuck in SOLVING for {plan['age_minutes']:.1f} minutes"
            )
            result["age_minutes"] = plan["age_minutes"]

        results.append(result)

        logger.info(
            f"Plan {plan['id']}: {result['status']} "
            f"(age={plan['age_minutes']:.1f}min)"
        )

    recovered_count = sum(1 for r in results if r["status"] == "recovered")

    summary = {
        "status": "ok",
        "stuck_count": len(stuck_plans),
        "recovered_count": recovered_count,
        "dry_run": dry_run,
        "max_age_minutes": max_age_minutes,
        "plans": results
    }

    logger.info(
        f"Crash recovery complete: "
        f"{recovered_count}/{len(stuck_plans)} plans recovered"
    )

    return summary


def check_for_stuck_plans(max_age_minutes: int = 5) -> Optional[Dict]:
    """
    Quick check for stuck plans (for health checks).

    Returns:
        None if no stuck plans, otherwise dict with stuck plan info
    """
    stuck_plans = find_stuck_plans(max_age_minutes)

    if not stuck_plans:
        return None

    return {
        "warning": "stuck_plans_detected",
        "count": len(stuck_plans),
        "oldest_age_minutes": max(p["age_minutes"] for p in stuck_plans),
        "plan_ids": [p["id"] for p in stuck_plans]
    }


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Crash Recovery - Recover stuck plans"
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=30,
        help="Plans SOLVING longer than this are considered stuck (default: 30)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be recovered without making changes"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check for stuck plans, don't recover"
    )

    args = parser.parse_args()

    if args.check_only:
        stuck = check_for_stuck_plans(args.max_age_minutes)
        if stuck:
            print(f"WARNING: {stuck['count']} stuck plans detected!")
            print(f"  Oldest: {stuck['oldest_age_minutes']:.1f} minutes")
            print(f"  Plan IDs: {stuck['plan_ids']}")
            return 1
        else:
            print("OK: No stuck plans")
            return 0

    result = run_crash_recovery(
        max_age_minutes=args.max_age_minutes,
        dry_run=args.dry_run
    )

    print(f"\nCrash Recovery Summary:")
    print(f"  Stuck plans found: {result['stuck_count']}")
    print(f"  Plans recovered: {result['recovered_count']}")
    if result.get('dry_run'):
        print(f"  (DRY RUN - no changes made)")

    for plan in result['plans']:
        print(f"\n  Plan {plan['plan_version_id']}:")
        print(f"    Status: {plan['status']}")
        print(f"    Age: {plan.get('age_minutes', 'N/A'):.1f}min")
        print(f"    Message: {plan['message']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
