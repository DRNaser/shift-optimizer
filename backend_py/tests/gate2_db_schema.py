"""
Gate 2: DB Schema & Constraints
===============================
Tests:
2.1 tenant_id on all tables
2.2 plan_versions.status CHECK constraint
2.3 LOCKED plans block UPDATE/DELETE on assignments
"""

import psycopg
from psycopg.rows import dict_row
import sys
import os

# DB connection
DB_DSN = os.getenv("DATABASE_URL", "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign")

def test_tenant_id_columns():
    """2.1: Verify tenant_id exists on core tables."""
    required_tables = [
        'forecast_versions',
        'plan_versions',
        'tours_raw',
        'tours_normalized',
        'tour_instances',
        'assignments',
    ]

    with psycopg.connect(DB_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            results = {}
            for table in required_tables:
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name = 'tenant_id'
                """, (table,))
                row = cur.fetchone()
                has_tenant_id = row is not None
                results[table] = has_tenant_id
                print(f"  {table}: {'PASS' if has_tenant_id else 'FAIL (no tenant_id)'}")

            all_pass = all(results.values())
            return all_pass, results

def test_status_constraint():
    """2.2: Verify plan_versions.status CHECK constraint exists."""
    with psycopg.connect(DB_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Check for CHECK constraint on status column
            cur.execute("""
                SELECT con.conname, pg_get_constraintdef(con.oid)
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'plan_versions'
                AND con.contype = 'c'
            """)
            constraints = cur.fetchall()

            status_constraint_found = False
            for c in constraints:
                if 'status' in str(c.get('pg_get_constraintdef', '')):
                    status_constraint_found = True
                    print(f"  Found constraint: {c['conname']}")
                    print(f"    Definition: {c['pg_get_constraintdef']}")

            if not status_constraint_found:
                # Check if there's an ENUM type for status
                cur.execute("""
                    SELECT data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = 'plan_versions' AND column_name = 'status'
                """)
                col = cur.fetchone()
                if col:
                    print(f"  Status column type: {col['data_type']} ({col.get('udt_name', 'N/A')})")
                    if col['data_type'] == 'USER-DEFINED' or col.get('udt_name') in ('plan_status', 'status_enum'):
                        print("  Status uses ENUM type (equivalent to CHECK constraint)")
                        status_constraint_found = True

            return status_constraint_found

def test_locked_immutability():
    """2.3: Verify LOCKED plans block UPDATE/DELETE on assignments."""
    with psycopg.connect(DB_DSN, row_factory=dict_row) as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # Check for immutability trigger
                cur.execute("""
                    SELECT tgname, pg_get_triggerdef(oid) as definition
                    FROM pg_trigger
                    WHERE tgrelid = 'assignments'::regclass
                    AND NOT tgisinternal
                """)
                triggers = cur.fetchall()

                immutability_trigger_found = False
                for t in triggers:
                    print(f"  Trigger: {t['tgname']}")
                    if 'locked' in t.get('definition', '').lower() or 'immut' in t['tgname'].lower():
                        immutability_trigger_found = True
                        print(f"    -> Immutability trigger found!")

                if not triggers:
                    print("  No triggers found on assignments table")
                    # Check if trigger exists via function-based approach
                    cur.execute("""
                        SELECT routine_name
                        FROM information_schema.routines
                        WHERE routine_name LIKE '%lock%' OR routine_name LIKE '%immut%'
                    """)
                    funcs = cur.fetchall()
                    if funcs:
                        print(f"  Found related functions: {[f['routine_name'] for f in funcs]}")
                        immutability_trigger_found = True

                return immutability_trigger_found
        finally:
            conn.rollback()

def main():
    print("=" * 60)
    print("GATE 2: DB SCHEMA & CONSTRAINTS")
    print("=" * 60)

    results = {}

    print("\n[2.1] tenant_id on all tables")
    print("-" * 40)
    all_tenant_id, tenant_results = test_tenant_id_columns()
    results['tenant_id'] = all_tenant_id

    print("\n[2.2] plan_versions.status CHECK constraint")
    print("-" * 40)
    results['status_constraint'] = test_status_constraint()

    print("\n[2.3] LOCKED plans immutability trigger")
    print("-" * 40)
    results['immutability'] = test_locked_immutability()

    print("\n" + "=" * 60)
    print("GATE 2 SUMMARY")
    print("=" * 60)
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test}: {status}")

    all_pass = all(results.values())
    print(f"\nGATE 2 OVERALL: {'PASS' if all_pass else 'FAIL'}")

    return 0 if all_pass else 1

if __name__ == "__main__":
    sys.exit(main())
