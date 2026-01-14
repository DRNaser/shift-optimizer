#!/usr/bin/env python3
"""
RLS Leak Harness CLI (Skill 101)
================================

Validates Row-Level Security isolation under parallel load.

Usage:
    # Quick test (2 tenants, 100 operations)
    python -m backend_py.skills.rls_leak_harness

    # Full test (10 tenants, 1000 operations)
    python -m backend_py.skills.rls_leak_harness --tenants 10 --operations 1000 --workers 50

Exit codes:
    0: PASS - No cross-tenant leaks detected
    1: FAIL - RLS leak detected
    2: ERROR - Infrastructure error
"""

import argparse
import asyncio
import json
import os
import sys

from .harness import RLSLeakHarness


async def run_harness(args) -> int:
    """Run the RLS leak harness."""
    print("=" * 60)
    print("RLS LEAK HARNESS (Skill 101)")
    print("=" * 60)
    print(f"\nTenants: {args.tenants}")
    print(f"Operations: {args.operations}")
    print(f"Workers: {args.workers}")
    print(f"Database: {args.db_url[:30]}...")
    print("=" * 60)

    # Run harness
    harness = RLSLeakHarness(args.db_url, verbose=args.verbose)
    result = await harness.run(
        tenants=args.tenants,
        operations=args.operations,
        workers=args.workers,
        cleanup=not args.no_cleanup,
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
        print(f"\nResult saved to: {args.output}")
        return 2

    if result.passed:
        print(f"[PASS] No RLS leaks detected")
        print(f"  Tenants: {result.tenants_tested}")
        print(f"  Operations: {result.total_operations}")
        print(f"  Leaks: {result.leaks_detected}")
    else:
        print(f"[FAIL] RLS LEAK DETECTED!")
        print(f"  Tenants: {result.tenants_tested}")
        print(f"  Operations: {result.total_operations}")
        print(f"  Leaks: {result.leaks_detected}")
        print("\n  Leak details:")
        for detail in result.leak_details[:10]:  # Show first 10
            print(f"    - Tenant {detail['tenant_id']} saw data from {detail['leaked_from']}")

    print(f"\nResult saved to: {args.output}")
    return 0 if result.passed else 1


def main():
    parser = argparse.ArgumentParser(
        description="RLS Leak Harness - Validate multi-tenant isolation"
    )
    parser.add_argument(
        "--tenants",
        type=int,
        default=2,
        help="Number of test tenants to create (default: 2)"
    )
    parser.add_argument(
        "--operations",
        type=int,
        default=100,
        help="Total number of operations to run (default: 100)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of parallel workers (default: 10)"
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", "postgresql://test:test@localhost:5432/solvereign_test"),
        help="PostgreSQL connection URL"
    )
    parser.add_argument(
        "--output",
        default="rls_harness.json",
        help="Output file for results"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't clean up test data after run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()
    exit_code = asyncio.run(run_harness(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
