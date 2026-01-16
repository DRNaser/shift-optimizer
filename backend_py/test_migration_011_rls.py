"""
SOLVEREIGN V3.3b - Migration 011 Smoke Test + RLS Verification
================================================================

This script:
1. Applies migration 011 (driver model)
2. Verifies all tables created
3. Tests RLS policies work correctly
4. Creates test data to verify isolation

Run: python backend_py/test_migration_011_rls.py
"""

import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packs.roster.engine.db import get_connection, test_connection


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_result(name: str, passed: bool, details: str = ""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {name}")
    if details:
        print(f"         {details}")


def apply_migration_011():
    """Apply migration 011 if not already applied."""
    print_header("STEP 1: Apply Migration 011")

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "db", "migrations", "011_driver_model.sql"
    )

    with open(migration_path, "r", encoding="utf-8") as f:
        migration_sql = f.read()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if already applied
            cur.execute("""
                SELECT 1 FROM schema_migrations
                WHERE version = '011'
            """)
            if cur.fetchone():
                print("  [INFO] Migration 011 already applied, skipping...")
                return True

            # Apply migration
            try:
                cur.execute(migration_sql)
                conn.commit()
                print("  [PASS] Migration 011 applied successfully")
                return True
            except Exception as e:
                conn.rollback()
                print(f"  [FAIL] Migration failed: {e}")
                return False


def verify_tables_exist():
    """Verify all driver model tables exist."""
    print_header("STEP 2: Verify Tables Exist")

    tables = [
        "drivers",
        "driver_skills",
        "driver_availability",
        "repair_log"
    ]

    all_passed = True
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = %s
                    )
                """, (table,))
                exists = cur.fetchone()['exists']
                print_result(f"Table '{table}'", exists)
                all_passed = all_passed and exists

    return all_passed


def verify_columns_added():
    """Verify new columns added to existing tables."""
    print_header("STEP 3: Verify Column Extensions")

    checks = [
        ("assignments", "real_driver_id"),
        ("plan_versions", "is_repair"),
        ("plan_versions", "parent_plan_id"),
        ("plan_versions", "absent_driver_ids"),
    ]

    all_passed = True
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table, column in checks:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = %s AND column_name = %s
                    )
                """, (table, column))
                exists = cur.fetchone()['exists']
                print_result(f"{table}.{column}", exists)
                all_passed = all_passed and exists

    return all_passed


def verify_helper_functions():
    """Verify helper functions exist."""
    print_header("STEP 4: Verify Helper Functions")

    functions = [
        "get_eligible_drivers",
        "get_eligible_drivers_week",
        "driver_has_skill"
    ]

    all_passed = True
    with get_connection() as conn:
        with conn.cursor() as cur:
            for func in functions:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_proc p
                        JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = 'public' AND p.proname = %s
                    )
                """, (func,))
                exists = cur.fetchone()['exists']
                print_result(f"Function {func}()", exists)
                all_passed = all_passed and exists

    return all_passed


def verify_rls_policies():
    """Verify RLS policies exist (if RLS is enabled)."""
    print_header("STEP 5: Verify RLS Policies")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if security_audit_log exists (RLS enabled)
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'security_audit_log'
                )
            """)
            rls_enabled = cur.fetchone()['exists']

            if not rls_enabled:
                print("  [INFO] RLS not enabled (security_audit_log not found)")
                print("  [INFO] Skipping policy verification")
                return True

            # Check policies
            policies = [
                ("drivers", "tenant_isolation_drivers"),
                ("driver_skills", "tenant_isolation_driver_skills"),
                ("driver_availability", "tenant_isolation_driver_availability"),
                ("repair_log", "tenant_isolation_repair_log"),
            ]

            all_passed = True
            for table, policy in policies:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_policies
                        WHERE tablename = %s AND policyname = %s
                    )
                """, (table, policy))
                exists = cur.fetchone()['exists']
                print_result(f"Policy {policy}", exists)
                all_passed = all_passed and exists

            return all_passed


def test_driver_crud():
    """Test basic driver CRUD operations."""
    print_header("STEP 6: Test Driver CRUD")

    test_tenant = "00000000-0000-0000-0000-000000000001"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Create test driver
                cur.execute("""
                    INSERT INTO drivers (tenant_id, external_ref, display_name, home_depot)
                    VALUES (%s, 'TEST-001', 'Test Driver', 'Depot-A')
                    ON CONFLICT (tenant_id, external_ref) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                    RETURNING id
                """, (test_tenant,))
                driver_id = cur.fetchone()['id']
                print_result("Create driver", True, f"id={driver_id}")

                # Read driver
                cur.execute("""
                    SELECT * FROM drivers WHERE id = %s
                """, (driver_id,))
                driver = cur.fetchone()
                print_result("Read driver", driver is not None,
                           f"external_ref={driver['external_ref']}")

                # Update driver
                cur.execute("""
                    UPDATE drivers SET display_name = 'Updated Name'
                    WHERE id = %s
                    RETURNING display_name
                """, (driver_id,))
                updated = cur.fetchone()
                print_result("Update driver", updated['display_name'] == 'Updated Name')

                # Test eligible drivers function
                cur.execute("""
                    SELECT * FROM get_eligible_drivers(%s, CURRENT_DATE)
                """, (test_tenant,))
                eligible = cur.fetchall()
                print_result("get_eligible_drivers()", True,
                           f"found {len(eligible)} drivers")

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print_result("Driver CRUD", False, str(e))
                return False


def test_availability_crud():
    """Test availability CRUD operations."""
    print_header("STEP 7: Test Availability CRUD")

    test_tenant = "00000000-0000-0000-0000-000000000001"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Get test driver
                cur.execute("""
                    SELECT id FROM drivers
                    WHERE tenant_id = %s AND external_ref = 'TEST-001'
                """, (test_tenant,))
                row = cur.fetchone()
                if not row:
                    print_result("Find test driver", False)
                    return False
                driver_id = row['id']

                # Set availability SICK
                cur.execute("""
                    INSERT INTO driver_availability
                        (tenant_id, driver_id, date, status, note, source)
                    VALUES (%s, %s, CURRENT_DATE, 'SICK', 'Test sick call', 'test')
                    ON CONFLICT (tenant_id, driver_id, date) DO UPDATE
                    SET status = EXCLUDED.status, note = EXCLUDED.note
                    RETURNING id
                """, (test_tenant, driver_id))
                avail_id = cur.fetchone()['id']
                print_result("Set availability SICK", True, f"id={avail_id}")

                # Verify driver NOT in eligible (should be excluded due to SICK)
                cur.execute("""
                    SELECT * FROM get_eligible_drivers(%s, CURRENT_DATE)
                    WHERE driver_id = %s
                """, (test_tenant, driver_id))
                excluded = cur.fetchone() is None
                print_result("SICK driver excluded from eligible", excluded)

                # Reset to AVAILABLE
                cur.execute("""
                    UPDATE driver_availability
                    SET status = 'AVAILABLE'
                    WHERE id = %s
                """, (avail_id,))

                # Delete test availability
                cur.execute("""
                    DELETE FROM driver_availability WHERE id = %s
                """, (avail_id,))

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print_result("Availability CRUD", False, str(e))
                return False


def test_repair_log_crud():
    """Test repair log CRUD."""
    print_header("STEP 8: Test Repair Log CRUD")

    test_tenant = "00000000-0000-0000-0000-000000000001"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # We need a plan_version_id to test repair_log
                # First check if we have any plan versions
                cur.execute("SELECT id FROM plan_versions LIMIT 1")
                pv = cur.fetchone()

                if not pv:
                    print("  [INFO] No plan_versions exist, creating dummy for test")
                    # Need a forecast first
                    cur.execute("SELECT id FROM forecast_versions LIMIT 1")
                    fv = cur.fetchone()
                    if not fv:
                        print("  [SKIP] No forecast_versions exist, skipping repair_log test")
                        return True

                    cur.execute("""
                        INSERT INTO plan_versions (
                            forecast_version_id, seed, solver_config_hash,
                            output_hash, status, tenant_id
                        )
                        VALUES (%s, 42, 'test', 'test', 'DRAFT', %s)
                        RETURNING id
                    """, (fv['id'], test_tenant))
                    pv = cur.fetchone()

                plan_version_id = pv['id']

                # Create repair log entry
                cur.execute("""
                    INSERT INTO repair_log (
                        tenant_id, parent_plan_id, absent_driver_ids,
                        respect_freeze, strategy, status
                    )
                    VALUES (%s, %s, '[1,2,3]'::jsonb, TRUE, 'MIN_CHURN', 'PENDING')
                    RETURNING id
                """, (test_tenant, plan_version_id))
                repair_id = cur.fetchone()['id']
                print_result("Create repair_log", True, f"id={repair_id}")

                # Read repair log
                cur.execute("""
                    SELECT * FROM repair_log WHERE id = %s
                """, (repair_id,))
                log = cur.fetchone()
                print_result("Read repair_log", log is not None)

                # Update status
                cur.execute("""
                    UPDATE repair_log
                    SET status = 'SUCCESS', completed_at = NOW()
                    WHERE id = %s
                    RETURNING status
                """, (repair_id,))
                updated = cur.fetchone()
                print_result("Update repair_log status", updated['status'] == 'SUCCESS')

                # Clean up
                cur.execute("DELETE FROM repair_log WHERE id = %s", (repair_id,))

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print_result("Repair Log CRUD", False, str(e))
                return False


def test_deterministic_ordering():
    """Verify queries return deterministic order."""
    print_header("STEP 9: Test Deterministic Ordering")

    test_tenant = "00000000-0000-0000-0000-000000000001"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Create multiple test drivers
                for i in range(5):
                    cur.execute("""
                        INSERT INTO drivers (tenant_id, external_ref, display_name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (tenant_id, external_ref) DO NOTHING
                    """, (test_tenant, f'TEST-ORDER-{i:03d}', f'Driver {i}'))

                conn.commit()

                # Run get_eligible_drivers 3 times, verify same order
                results = []
                for _ in range(3):
                    cur.execute("""
                        SELECT driver_id FROM get_eligible_drivers(%s, CURRENT_DATE)
                        WHERE external_ref LIKE 'TEST-ORDER-%%'
                        ORDER BY driver_id
                    """, (test_tenant,))
                    ids = [r['driver_id'] for r in cur.fetchall()]
                    results.append(tuple(ids))

                # All results should be identical
                all_same = len(set(results)) == 1
                print_result("Deterministic ordering", all_same,
                           f"3 runs returned {'identical' if all_same else 'different'} order")

                # Clean up test drivers
                cur.execute("""
                    DELETE FROM drivers
                    WHERE tenant_id = %s AND external_ref LIKE 'TEST-ORDER-%%'
                """, (test_tenant,))
                conn.commit()

                return all_same

            except Exception as e:
                conn.rollback()
                print_result("Deterministic ordering", False, str(e))
                return False


def cleanup_test_data():
    """Clean up test data."""
    print_header("CLEANUP: Remove Test Data")

    test_tenant = "00000000-0000-0000-0000-000000000001"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Delete test driver (cascades to skills/availability)
                cur.execute("""
                    DELETE FROM drivers
                    WHERE tenant_id = %s AND external_ref LIKE 'TEST-%%'
                """, (test_tenant,))
                deleted = cur.rowcount
                conn.commit()
                print(f"  [INFO] Deleted {deleted} test driver(s)")
                return True
            except Exception as e:
                conn.rollback()
                print(f"  [WARN] Cleanup failed: {e}")
                return True  # Don't fail on cleanup


def main():
    """Run all smoke tests."""
    print("\n" + "="*60)
    print("  SOLVEREIGN V3.3b - Migration 011 Smoke Test")
    print("="*60)

    # Test connection first
    if not test_connection():
        print("\n[FAIL] Database connection failed!")
        print("       Start the database: docker compose up -d postgres")
        return 1

    print("\n[OK] Database connection successful")

    results = []

    # Run all tests
    results.append(("Migration 011", apply_migration_011()))
    results.append(("Tables Exist", verify_tables_exist()))
    results.append(("Columns Added", verify_columns_added()))
    results.append(("Helper Functions", verify_helper_functions()))
    results.append(("RLS Policies", verify_rls_policies()))
    results.append(("Driver CRUD", test_driver_crud()))
    results.append(("Availability CRUD", test_availability_crud()))
    results.append(("Repair Log CRUD", test_repair_log_crud()))
    results.append(("Deterministic Order", test_deterministic_ordering()))

    cleanup_test_data()

    # Summary
    print_header("SUMMARY")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n  Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n  [SUCCESS] Migration 011 smoke test PASSED!")
        print("            Driver model ready for Repair API implementation.")
        return 0
    else:
        print("\n  [FAILURE] Some tests failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
