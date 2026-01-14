#!/usr/bin/env python3
"""
Escalation Drill CLI (Skill 105)
================================

Tests the escalation lifecycle (create -> block -> resolve -> unblock).

This is a DRILL (template validation), NOT live incident response.

Usage:
    python -m backend_py.skills.escalation_drill --tenant test_tenant
    python -m backend_py.skills.escalation_drill --tenant test --severity S1

Exit codes:
    0: PASS - Escalation lifecycle works correctly
    1: FAIL - Lifecycle validation failed
    2: ERROR - Infrastructure error
"""

import argparse
import asyncio
import json
import os
import sys

from .drill import EscalationDrill


async def run_drill(args) -> int:
    """Run the escalation drill."""
    print("=" * 60)
    print("ESCALATION DRILL (Skill 105)")
    print("=" * 60)
    print("\nNOTE: This is a DRILL - template validation only.")
    print("      NOT live incident response.")
    print(f"\nTenant: {args.tenant}")
    print(f"Severity: {args.severity}")
    print("=" * 60)

    # Run drill
    drill = EscalationDrill(args.db_url, verbose=args.verbose)
    result = await drill.run(
        tenant_code=args.tenant,
        severity=args.severity,
    )

    # Save result
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    # Print result
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)

    if result.error:
        print(f"[ERROR] {result.error}")
        print(f"\nSteps completed: {result.steps_completed}/{result.total_steps}")
        print(f"\nResult saved to: {args.output}")
        return 2 if result.steps_completed == 0 else 1

    if result.passed:
        print(f"[PASS] Escalation lifecycle validated")
        print(f"\n  Steps completed: {result.steps_completed}/{result.total_steps}")
        print(f"  1. Create escalation: {'OK' if result.create_ok else 'FAIL'}")
        print(f"  2. Block check:       {'OK' if result.block_check_ok else 'FAIL'}")
        print(f"  3. Resolve:           {'OK' if result.resolve_ok else 'FAIL'}")
        print(f"  4. Unblock check:     {'OK' if result.unblock_check_ok else 'FAIL'}")
    else:
        print(f"[FAIL] Escalation lifecycle validation failed")
        print(f"\n  Steps completed: {result.steps_completed}/{result.total_steps}")
        if result.error:
            print(f"\n  Error: {result.error}")

    print(f"\nResult saved to: {args.output}")
    return 0 if result.passed else 1


def main():
    parser = argparse.ArgumentParser(
        description="Escalation Drill - Validate escalation lifecycle"
    )
    parser.add_argument(
        "--tenant",
        default="test_tenant",
        help="Test tenant identifier (default: test_tenant)"
    )
    parser.add_argument(
        "--severity",
        choices=["S0", "S1", "S2", "S3"],
        default="S1",
        help="Escalation severity (default: S1)"
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", "postgresql://test:test@localhost:5432/solvereign_test"),
        help="PostgreSQL connection URL"
    )
    parser.add_argument(
        "--output",
        default="escalation_drill.json",
        help="Output file for results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()
    exit_code = asyncio.run(run_drill(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
