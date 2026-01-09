#!/usr/bin/env python3
"""
SOLVEREIGN V4.3 - Production Migration Safety Gate
===================================================

Pre/Post check script for production migrations.
Run BEFORE and AFTER applying migrations 037/037a.

Usage:
    # Pre-migration check
    python scripts/prod_migration_gate.py --env prod --phase pre

    # Apply migrations (manual step)
    psql $DATABASE_URL < backend_py/db/migrations/037_portal_notify_integration.sql
    psql $DATABASE_URL < backend_py/db/migrations/037a_portal_notify_hardening.sql

    # Post-migration check
    python scripts/prod_migration_gate.py --env prod --phase post

Exit codes:
    0 = All checks PASS
    1 = One or more checks FAIL
    2 = Script error
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any  # noqa: F401 - used in type hints

# Try to import asyncpg, fall back to psycopg2
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def get_db_url(env: str) -> str:
    """Get database URL for environment."""
    env_var = f"DATABASE_URL_{env.upper()}" if env != "local" else "DATABASE_URL"
    url = os.environ.get(env_var)
    if not url:
        raise ValueError(f"Environment variable {env_var} not set")
    return url


def run_checks_sync(db_url: str, phase: str) -> dict:
    """Run checks using psycopg2 (sync)."""
    if not HAS_PSYCOPG2:
        raise ImportError("psycopg2 not installed")

    results = {
        "phase": phase,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": [],
        "all_pass": True,
    }

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        if phase == "pre":
            # Pre-migration checks
            checks = [
                ("migration_036_applied", """
                    SELECT COUNT(*) > 0 FROM pg_proc
                    WHERE proname = 'cleanup_old_notifications'
                """),
                ("notify_schema_exists", """
                    SELECT COUNT(*) > 0 FROM information_schema.schemata
                    WHERE schema_name = 'notify'
                """),
                ("portal_schema_exists", """
                    SELECT COUNT(*) > 0 FROM information_schema.schemata
                    WHERE schema_name = 'portal'
                """),
                ("portal_tokens_table_exists", """
                    SELECT COUNT(*) > 0 FROM information_schema.tables
                    WHERE table_schema = 'portal' AND table_name = 'portal_tokens'
                """),
                ("notification_templates_table_exists", """
                    SELECT COUNT(*) > 0 FROM information_schema.tables
                    WHERE table_schema = 'notify' AND table_name = 'notification_templates'
                """),
                ("no_active_connections_blocking", """
                    SELECT COUNT(*) = 0 FROM pg_stat_activity
                    WHERE state = 'active'
                    AND query LIKE '%ALTER TABLE%portal%'
                    AND pid != pg_backend_pid()
                """),
            ]

        elif phase == "post":
            # Post-migration checks
            checks = [
                ("verify_notify_integration", """
                    SELECT COUNT(*) = (
                        SELECT COUNT(*) FROM portal.verify_notify_integration()
                        WHERE status = 'PASS'
                    )
                    FROM portal.verify_notify_integration()
                """),
                ("templates_use_plan_link", """
                    SELECT COUNT(*) = 0 FROM notify.notification_templates
                    WHERE body_template LIKE '%{{portal_url}}%'
                """),
                ("outbox_id_index_exists", """
                    SELECT COUNT(*) > 0 FROM pg_indexes
                    WHERE indexname = 'idx_portal_tokens_outbox'
                """),
                ("dedup_key_column_exists", """
                    SELECT COUNT(*) > 0 FROM information_schema.columns
                    WHERE table_schema = 'portal'
                    AND table_name = 'portal_tokens'
                    AND column_name = 'dedup_key'
                """),
                ("dedup_key_index_exists", """
                    SELECT COUNT(*) > 0 FROM pg_indexes
                    WHERE indexname = 'idx_portal_tokens_dedup'
                """),
                ("integration_view_exists", """
                    SELECT COUNT(*) > 0 FROM pg_views
                    WHERE schemaname = 'portal' AND viewname = 'notify_integration_status'
                """),
                ("summary_view_exists", """
                    SELECT COUNT(*) > 0 FROM pg_views
                    WHERE schemaname = 'portal' AND viewname = 'snapshot_notify_summary'
                """),
                ("atomic_function_exists", """
                    SELECT COUNT(*) > 0 FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'portal' AND p.proname = 'issue_token_atomic'
                """),
                ("retention_function_exists", """
                    SELECT COUNT(*) > 0 FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'portal' AND p.proname = 'cleanup_portal_data'
                """),
            ]

        else:
            raise ValueError(f"Unknown phase: {phase}")

        for check_name, query in checks:
            try:
                cur.execute(query)
                row = cur.fetchone()
                passed = row[0] if row else False

                results["checks"].append({
                    "name": check_name,
                    "status": "PASS" if passed else "FAIL",
                })

                if not passed:
                    results["all_pass"] = False

            except Exception as e:
                results["checks"].append({
                    "name": check_name,
                    "status": "ERROR",
                    "error": str(e),
                })
                results["all_pass"] = False

    finally:
        cur.close()
        conn.close()

    return results


async def run_checks_async(db_url: str, phase: str) -> dict:
    """Run checks using asyncpg (async)."""
    if not HAS_ASYNCPG:
        raise ImportError("asyncpg not installed")

    # Convert psycopg2-style URL to asyncpg format if needed
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)

    results = {
        "phase": phase,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": [],
        "all_pass": True,
    }

    conn = await asyncpg.connect(db_url)

    try:
        # Same checks as sync version
        if phase == "post":
            # Run the verify function and get detailed results
            rows = await conn.fetch("SELECT * FROM portal.verify_notify_integration()")
            for row in rows:
                results["checks"].append({
                    "name": row["check_name"],
                    "status": row["status"],
                    "details": row["details"],
                })
                if row["status"] != "PASS":
                    results["all_pass"] = False

    finally:
        await conn.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Production Migration Safety Gate")
    parser.add_argument("--env", required=True, choices=["local", "staging", "prod"])
    parser.add_argument("--phase", required=True, choices=["pre", "post"])
    parser.add_argument("--output", help="Output file for JSON results")
    args = parser.parse_args()

    try:
        db_url = get_db_url(args.env)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    print(f"Running {args.phase}-migration checks for {args.env}...")
    print()

    try:
        # Prefer sync for simplicity
        results = run_checks_sync(db_url, args.phase)
    except ImportError:
        print("ERROR: psycopg2 not installed", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    # Print results
    print(f"Phase: {results['phase']}")
    print(f"Timestamp: {results['timestamp']}")
    print()
    print("Checks:")
    for check in results["checks"]:
        status_icon = "✓" if check["status"] == "PASS" else "✗"
        print(f"  {status_icon} {check['name']}: {check['status']}")
        if check.get("error"):
            print(f"      Error: {check['error']}")
        if check.get("details"):
            print(f"      Details: {check['details']}")

    print()
    if results["all_pass"]:
        print("RESULT: ALL CHECKS PASS")
    else:
        print("RESULT: SOME CHECKS FAILED")

    # Save to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")

    # Auto-save to evidence store
    try:
        from evidence_store import EvidenceStore
        store = EvidenceStore()
        evidence_path = store.save(
            category=f"migration_gate_{args.phase}",
            data=results,
            env=args.env,
        )
        print(f"Evidence stored: {evidence_path}")
    except ImportError:
        pass  # evidence_store not available, skip

    sys.exit(0 if results["all_pass"] else 1)


if __name__ == "__main__":
    main()
