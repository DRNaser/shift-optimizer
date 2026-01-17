#!/usr/bin/env python3
"""
SOLVEREIGN - Migration Idempotency Test
========================================

Tests that migrations can be applied twice without errors.
This proves all CREATE, ALTER, and INSERT statements are idempotent.

Usage:
    # With DATABASE_URL environment variable set
    python scripts/test_migration_idempotency.py

    # Or with explicit database URL
    python scripts/test_migration_idempotency.py --db-url postgresql://...

Exit codes:
    0 = PASS (all migrations idempotent)
    1 = FAIL (at least one migration failed on re-apply)
"""

import argparse
import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime


# Migrations to test (in order)
CRITICAL_MIGRATIONS = [
    "002_compose_scenarios.sql",
    "006_multi_tenant.sql",
    "025_tenants_rls_fix.sql",
    "025a_rls_hardening.sql",
    "025b_rls_role_lockdown.sql",
    "025c_rls_boundary_fix.sql",
    "025d_definer_owner_hardening.sql",
    "025e_final_hardening.sql",
    "025f_acl_fix.sql",
    "048_roster_pack_enhanced.sql",
    "048a_roster_pack_constraints.sql",
    "048b_roster_undo_columns.sql",
    "062_roster_rbac_permissions.sql",
    "063_activation_gate.sql",
    "064_slot_state_invariants.sql",
]


def get_db_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable not set")
    return url


def apply_migration(db_url: str, migration_path: Path, verbose: bool = False) -> tuple[bool, str]:
    """Apply a single migration file. Returns (success, error_message)."""
    try:
        result = subprocess.run(
            ["psql", db_url, "-f", str(migration_path), "-v", "ON_ERROR_STOP=1"],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            return False, result.stderr or result.stdout

        if verbose:
            print(f"  Output: {result.stdout[:200]}...")

        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Migration timed out after 60s"
    except Exception as e:
        return False, str(e)


def test_migration_idempotency(db_url: str, verbose: bool = False) -> dict:
    """
    Test that all migrations can be applied twice without errors.

    Returns:
        dict with:
            - passed: bool
            - results: list of {migration, pass1, pass2, error}
    """
    migrations_dir = Path(__file__).parent.parent / "backend_py" / "db" / "migrations"

    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")

    results = []
    all_passed = True

    print("=" * 70)
    print(" SOLVEREIGN Migration Idempotency Test")
    print("=" * 70)
    print()
    print(f" Testing {len(CRITICAL_MIGRATIONS)} critical migrations")
    print()

    for migration_name in CRITICAL_MIGRATIONS:
        migration_path = migrations_dir / migration_name

        if not migration_path.exists():
            print(f"[SKIP] {migration_name} - not found")
            results.append({
                "migration": migration_name,
                "pass1": "SKIP",
                "pass2": "SKIP",
                "error": "File not found"
            })
            continue

        print(f"[TEST] {migration_name}")

        # First pass
        if verbose:
            print(f"  Pass 1: Applying...")
        success1, error1 = apply_migration(db_url, migration_path, verbose)

        if not success1:
            print(f"  [FAIL] Pass 1 failed: {error1[:100]}")
            results.append({
                "migration": migration_name,
                "pass1": "FAIL",
                "pass2": "N/A",
                "error": error1
            })
            all_passed = False
            continue

        # Second pass (idempotency test)
        if verbose:
            print(f"  Pass 2: Re-applying...")
        success2, error2 = apply_migration(db_url, migration_path, verbose)

        if success2:
            print(f"  [PASS] Idempotent - both passes succeeded")
            results.append({
                "migration": migration_name,
                "pass1": "PASS",
                "pass2": "PASS",
                "error": None
            })
        else:
            print(f"  [FAIL] Pass 2 failed (NOT idempotent): {error2[:100]}")
            results.append({
                "migration": migration_name,
                "pass1": "PASS",
                "pass2": "FAIL",
                "error": error2
            })
            all_passed = False

    print()
    print("=" * 70)
    if all_passed:
        print(" [PASS] All migrations are IDEMPOTENT")
    else:
        failed_count = sum(1 for r in results if r["pass2"] == "FAIL")
        print(f" [FAIL] {failed_count} migration(s) NOT idempotent")
    print("=" * 70)

    return {
        "passed": all_passed,
        "results": results,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


def write_report(result: dict, output_path: str = "migration_idempotency_report.json"):
    """Write machine-readable report."""
    report = {
        "gate": "MIGRATION_IDEMPOTENCY",
        "status": "PASS" if result["passed"] else "FAIL",
        "timestamp": result["timestamp"],
        "migrations_tested": len(result["results"]),
        "migrations_passed": sum(1 for r in result["results"] if r["pass2"] == "PASS"),
        "migrations_failed": sum(1 for r in result["results"] if r["pass2"] == "FAIL"),
        "results": result["results"]
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[Report] Written to {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Migration Idempotency Test")
    parser.add_argument("--db-url", help="Database URL (or use DATABASE_URL env var)")
    parser.add_argument("--evidence", action="store_true", help="Write evidence report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Get database URL
    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Use --db-url or set DATABASE_URL env var")
        sys.exit(2)

    # Run test
    try:
        result = test_migration_idempotency(db_url, verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    # Write evidence
    if args.evidence:
        write_report(result)

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
