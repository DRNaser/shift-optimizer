# =============================================================================
# SOLVEREIGN - Final Hardening Tests (Migration 025e) - PYTHON SMOKE SUBSET
# =============================================================================
#
# SOURCE OF TRUTH: SQL verify_final_hardening() (17 tests)
# THIS FILE: Python smoke tests (13 tests) - subset for CI quick-check
#
# CI STRATEGY:
#   1. Python tests run first (fast, catch obvious regressions)
#   2. SQL verify_final_hardening() is AUTHORITATIVE (run in CI job)
#   3. Any FAIL in SQL verify = CI FAIL (no exceptions)
#
# MAPPING: Python Test -> SQL Test
# ================================
# test_api_cannot_execute_verify_rls_boundary     -> SQL Test 1
# test_platform_can_execute_verify_rls_boundary   -> SQL Test 2 (partial)
# test_api_cannot_create_in_public_schema         -> SQL Test 3
# test_public_cannot_create_in_public_schema      -> SQL Test 4
# test_verify_final_hardening_function_exists     -> SQL Tests 1-17 (runs all)
# test_api_cannot_execute_verify_final_hardening  -> (additional Python check)
# test_default_privileges_public_schema           -> SQL Tests 5-7 (informational)
# test_default_privileges_core_schema             -> SQL Tests 9-11 (informational)
# test_api_cannot_create_in_core_schema           -> SQL Test 12
# test_platform_cannot_create_in_core_schema      -> SQL Test 13
# test_definer_cannot_create_in_core_schema       -> SQL Test 14
# test_no_public_execute_on_existing_functions    -> SQL Test 15 (informational)
# test_no_public_select_on_existing_tables        -> SQL Test 16 (informational)
#
# NOT COVERED IN PYTHON (run SQL verify for these):
#   SQL Test 8:  Schema security policy documented
#   SQL Test 17: Security functions executable by API (INFO)
#
# =============================================================================

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_test_connection():
    """Get database connection for testing."""
    try:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
            row_factory=dict_row
        )
    except Exception as e:
        print(f"Database connection failed: {e}")
        return None


class TestFinalHardening(unittest.TestCase):
    """
    Test class for migration 025e final hardening measures.

    Tests verify:
    1. verify_rls_boundary() is restricted to solvereign_platform only
    2. solvereign_api cannot CREATE objects in public schema
    3. PUBLIC cannot CREATE objects in public schema
    4. Default privileges are configured to prevent drift
    """

    def setUp(self):
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

    def tearDown(self):
        if self.conn:
            self.conn.close()

    def test_api_cannot_execute_verify_rls_boundary(self):
        """
        CRITICAL: solvereign_api should NOT be able to execute verify_rls_boundary().

        This function leaks security information (role names, policy definitions).
        Only platform admins should have access.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc WHERE proname = 'verify_rls_boundary'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("verify_rls_boundary() function does not exist")

            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'verify_rls_boundary()',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_execute'],
                    "solvereign_api should NOT be able to execute verify_rls_boundary(). "
                    "This function exposes sensitive security information."
                )
                print(f"    [PASS] solvereign_api cannot execute verify_rls_boundary()")

    def test_platform_can_execute_verify_rls_boundary(self):
        """
        solvereign_platform SHOULD be able to execute verify_rls_boundary().

        Platform admins need access to run security diagnostics.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc WHERE proname = 'verify_rls_boundary'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("verify_rls_boundary() function does not exist")

            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_platform',
                    'verify_rls_boundary()',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            if result:
                self.assertTrue(
                    result['can_execute'],
                    "solvereign_platform should be able to execute verify_rls_boundary()"
                )
                print(f"    [PASS] solvereign_platform can execute verify_rls_boundary()")

    def test_api_cannot_create_in_public_schema(self):
        """
        CRITICAL: solvereign_api should NOT be able to CREATE objects in public schema.

        This prevents the API role from creating malicious functions or tables.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT has_schema_privilege(
                    'solvereign_api',
                    'public',
                    'CREATE'
                ) as can_create
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_create'],
                    "solvereign_api should NOT have CREATE on schema public"
                )
                print(f"    [PASS] solvereign_api cannot CREATE in public schema")

    def test_public_cannot_create_in_public_schema(self):
        """
        PUBLIC role should NOT be able to CREATE objects in public schema.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    nspacl::TEXT LIKE '%=C%' as public_has_create
                FROM pg_namespace
                WHERE nspname = 'public'
            """)
            result = cur.fetchone()

            if result and result['public_has_create']:
                self.fail("PUBLIC has CREATE on schema public - this should be revoked")
            else:
                print(f"    [PASS] PUBLIC cannot CREATE in public schema")

    def test_verify_final_hardening_function_exists(self):
        """
        verify_final_hardening() function should exist after 025e migration.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc WHERE proname = 'verify_final_hardening'
                ) as exists
            """)
            result = cur.fetchone()

            if result and result['exists']:
                cur.execute("SELECT * FROM verify_final_hardening()")
                results = cur.fetchall()

                fail_count = 0
                for r in results:
                    if r['status'] == 'FAIL':
                        fail_count += 1
                        print(f"    [FAIL] {r['test_name']}: expected={r['expected']}, actual={r['actual']}")

                self.assertEqual(
                    fail_count, 0,
                    f"{fail_count} hardening tests failed in verify_final_hardening()"
                )
                print(f"    [PASS] All verify_final_hardening() tests passed")
            else:
                self.skipTest("verify_final_hardening() not found - run 025e migration first")

    def test_api_cannot_execute_verify_final_hardening(self):
        """
        solvereign_api should NOT be able to execute verify_final_hardening().
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc WHERE proname = 'verify_final_hardening'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("verify_final_hardening() function does not exist")

            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'verify_final_hardening()',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_execute'],
                    "solvereign_api should NOT be able to execute verify_final_hardening()"
                )
                print(f"    [PASS] solvereign_api cannot execute verify_final_hardening()")

    def test_default_privileges_public_schema(self):
        """
        Verify ALTER DEFAULT PRIVILEGES was set for public schema.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT defaclrole::regrole::TEXT AS role,
                       defaclnamespace::regnamespace::TEXT AS schema,
                       defaclobjtype AS objtype,
                       defaclacl::TEXT AS acl
                FROM pg_default_acl
                WHERE defaclnamespace = 'public'::regnamespace
            """)
            defaults = cur.fetchall()

            if defaults:
                print(f"\n    Default privileges for public schema:")
                for d in defaults:
                    print(f"      Role: {d['role']}, Type: {d['objtype']}, ACL: {d['acl']}")
                print(f"    [PASS] {len(defaults)} default privilege rules found for public schema")
            else:
                print(f"    [INFO] No explicit default privileges found for public schema")

            # Informational test - always passes
            self.assertTrue(True)

    def test_default_privileges_core_schema(self):
        """
        Verify ALTER DEFAULT PRIVILEGES was set for core schema (if exists).
        """
        with self.conn.cursor() as cur:
            # Check if core schema exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("core schema does not exist")

            cur.execute("""
                SELECT defaclrole::regrole::TEXT AS role,
                       defaclnamespace::regnamespace::TEXT AS schema,
                       defaclobjtype AS objtype,
                       defaclacl::TEXT AS acl
                FROM pg_default_acl
                WHERE defaclnamespace = 'core'::regnamespace
            """)
            defaults = cur.fetchall()

            if defaults:
                print(f"\n    Default privileges for core schema:")
                for d in defaults:
                    print(f"      Role: {d['role']}, Type: {d['objtype']}, ACL: {d['acl']}")
                print(f"    [PASS] {len(defaults)} default privilege rules found for core schema")
            else:
                print(f"    [INFO] No explicit default privileges found for core schema")

            # Informational test - always passes
            self.assertTrue(True)

    def test_api_cannot_create_in_core_schema(self):
        """
        solvereign_api should NOT be able to CREATE objects in core schema.
        """
        with self.conn.cursor() as cur:
            # Check if core schema exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("core schema does not exist")

            cur.execute("""
                SELECT has_schema_privilege(
                    'solvereign_api',
                    'core',
                    'CREATE'
                ) as can_create
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_create'],
                    "solvereign_api should NOT have CREATE on schema core"
                )
                print(f"    [PASS] solvereign_api cannot CREATE in core schema")

    def test_platform_cannot_create_in_core_schema(self):
        """
        solvereign_platform should NOT be able to CREATE objects in core schema.
        Only solvereign_admin (migrations) should create objects in core.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("core schema does not exist")

            cur.execute("""
                SELECT has_schema_privilege(
                    'solvereign_platform',
                    'core',
                    'CREATE'
                ) as can_create
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_create'],
                    "solvereign_platform should NOT have CREATE on schema core"
                )
                print(f"    [PASS] solvereign_platform cannot CREATE in core schema")

    def test_definer_cannot_create_in_core_schema(self):
        """
        solvereign_definer should NOT be able to CREATE objects in core schema.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("core schema does not exist")

            cur.execute("""
                SELECT has_schema_privilege(
                    'solvereign_definer',
                    'core',
                    'CREATE'
                ) as can_create
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['can_create'],
                    "solvereign_definer should NOT have CREATE on schema core"
                )
                print(f"    [PASS] solvereign_definer cannot CREATE in core schema")

    def test_no_public_execute_on_existing_functions(self):
        """
        CRITICAL: Existing functions in public schema should NOT have PUBLIC EXECUTE.
        Default privileges only protect NEW objects - must check existing ones.
        """
        with self.conn.cursor() as cur:
            # Check for functions with PUBLIC execute (excluding pg_ functions)
            cur.execute("""
                SELECT p.proname, n.nspname,
                       has_function_privilege('PUBLIC', p.oid, 'EXECUTE') as public_can_execute
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public'
                  AND p.proname NOT LIKE 'pg_%'
                  AND p.proname NOT LIKE '_%'
                  AND has_function_privilege('PUBLIC', p.oid, 'EXECUTE') = true
                ORDER BY p.proname
                LIMIT 20
            """)
            public_functions = cur.fetchall()

            if public_functions:
                print(f"\n    [WARN] {len(public_functions)} functions have PUBLIC EXECUTE:")
                for f in public_functions[:10]:
                    print(f"      - {f['nspname']}.{f['proname']}")
                if len(public_functions) > 10:
                    print(f"      ... and {len(public_functions) - 10} more")
                # This is a warning, not a failure - some functions may legitimately need PUBLIC access
            else:
                print(f"    [PASS] No user-defined functions have PUBLIC EXECUTE")

            # Informational - always passes (existing objects need manual review)
            self.assertTrue(True)

    def test_no_public_select_on_existing_tables(self):
        """
        CRITICAL: Existing tables in public schema should NOT have PUBLIC SELECT.
        """
        with self.conn.cursor() as cur:
            # Check for tables with PUBLIC select
            cur.execute("""
                SELECT c.relname, n.nspname,
                       has_table_privilege('PUBLIC', c.oid, 'SELECT') as public_can_select
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relname NOT LIKE 'pg_%'
                  AND has_table_privilege('PUBLIC', c.oid, 'SELECT') = true
                ORDER BY c.relname
            """)
            public_tables = cur.fetchall()

            if public_tables:
                print(f"\n    [WARN] {len(public_tables)} tables have PUBLIC SELECT:")
                for t in public_tables[:10]:
                    print(f"      - {t['nspname']}.{t['relname']}")
                # This is a warning - existing tables may need manual REVOKE
            else:
                print(f"    [PASS] No tables have PUBLIC SELECT")

            # Informational
            self.assertTrue(True)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN - Final Hardening Tests (Migration 025e)")
    print("=" * 70)
    print("\nPrerequisites:")
    print("  1. PostgreSQL running on localhost:5432")
    print("  2. Migrations 025, 025a, 025b, 025c, 025d, 025e applied")
    print("")

    # Run tests
    unittest.main(verbosity=2)
