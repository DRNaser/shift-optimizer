# =============================================================================
# SOLVEREIGN - RLS Boundary Fix Regression Tests (Migration 025c)
# =============================================================================
# Tests that verify the session variable bypass hole is closed.
#
# CRITICAL TESTS:
#   1. Setting app.is_super_admin='true' does NOT grant access to tenants
#   2. solvereign_api role has NO direct table privileges on tenants
#   3. Only solvereign_platform role can access tenants directly
#   4. Table privilege matrix is correct
#
# Prerequisites:
#   - Migration 025c must be applied
#   - Roles solvereign_api and solvereign_platform must exist
# =============================================================================

import sys
import os
import unittest
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_superuser_connection():
    """Get superuser connection for role switching."""
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


class TestSessionVariableBypassPrevention(unittest.TestCase):
    """
    CRITICAL: Test that session variable bypass is closed.

    Previously, any connection could run:
        SET app.is_super_admin = 'true';
        SELECT * FROM tenants;  -- Would return all rows!

    After migration 025c, this should return 0 rows because RLS
    now uses pg_has_role() checks that cannot be spoofed.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.conn = get_superuser_connection()
        if not cls.conn:
            return

        # Create test data as superuser (bypasses RLS)
        with cls.conn.cursor() as cur:
            # Ensure we're not in a transaction
            cls.conn.rollback()

            # Create test tenant
            cls.test_api_key = "test_key_bypass_test_025c"
            cls.test_hash = hashlib.sha256(cls.test_api_key.encode()).hexdigest()

            # Use superuser to insert (superuser bypasses RLS by default)
            cur.execute("""
                INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                VALUES ('_test_bypass_025c', %s, TRUE, '{"test": true}'::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    api_key_hash = EXCLUDED.api_key_hash,
                    is_active = EXCLUDED.is_active
                RETURNING id
            """, (cls.test_hash,))
            result = cur.fetchone()
            cls.test_tenant_id = result['id']
            cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if not cls.conn:
            return

        try:
            with cls.conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM tenants WHERE name LIKE '_test_bypass_025c%'
                """)
                cls.conn.commit()
        except Exception:
            pass
        finally:
            cls.conn.close()

    def setUp(self):
        """Check connection before each test."""
        if not self.conn:
            self.skipTest("Database not available")

    # =========================================================================
    # TEST 1: Session variable bypass MUST FAIL (API role)
    # =========================================================================

    def test_session_var_bypass_fails_api_role(self):
        """
        CRITICAL: Setting app.is_super_admin='true' as solvereign_api
        should NOT grant access to tenants table.

        This is the key security test. If this fails, the RLS boundary
        is still vulnerable to session variable attacks.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to API role
                cur.execute("SET LOCAL ROLE solvereign_api")

                # Attempt to bypass RLS with session variable
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                # Try to query tenants table
                cur.execute("SELECT COUNT(*) as cnt FROM tenants")
                result = cur.fetchone()

                # MUST return 0 rows - bypass should be blocked
                self.assertEqual(
                    result['cnt'], 0,
                    f"SECURITY VULNERABILITY: Session variable bypass succeeded! "
                    f"Got {result['cnt']} rows instead of 0. "
                    f"Migration 025c may not be applied correctly."
                )

                print("    [PASS] Session variable bypass BLOCKED - returned 0 rows")

            finally:
                cur.execute("ROLLBACK")

    def test_session_var_bypass_with_direct_select(self):
        """
        CRITICAL: Direct SELECT with spoofed session var should fail.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to API role
                cur.execute("SET LOCAL ROLE solvereign_api")

                # Set ALL possible session variables an attacker might try
                cur.execute("SET LOCAL app.is_super_admin = 'true'")
                cur.execute("SET LOCAL app.current_tenant_id = '1'")

                # Try to select specific tenant
                cur.execute("""
                    SELECT api_key_hash FROM tenants
                    WHERE name = '_test_bypass_025c'
                """)
                rows = cur.fetchall()

                # MUST return 0 rows
                self.assertEqual(
                    len(rows), 0,
                    f"SECURITY VULNERABILITY: Was able to read api_key_hash! "
                    f"Got {len(rows)} rows."
                )

                print("    [PASS] Cannot read api_key_hash with session var bypass")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST 2: Platform role SHOULD have access
    # =========================================================================

    def test_platform_role_can_access_tenants(self):
        """
        Platform role members should be able to access tenants table.
        This verifies the role-based policy works correctly.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to platform role
                cur.execute("SET LOCAL ROLE solvereign_platform")

                # Query tenants table - should work
                cur.execute("SELECT COUNT(*) as cnt FROM tenants")
                result = cur.fetchone()

                # Should see at least the test tenant
                self.assertGreaterEqual(
                    result['cnt'], 1,
                    f"Platform role should see tenants, got {result['cnt']} rows"
                )

                print(f"    [PASS] Platform role sees {result['cnt']} tenants")

            finally:
                cur.execute("ROLLBACK")

    def test_platform_role_can_call_list_all_tenants(self):
        """
        Platform role should be able to call list_all_tenants().
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to platform role
                cur.execute("SET LOCAL ROLE solvereign_platform")

                # Call list_all_tenants()
                cur.execute("SELECT * FROM list_all_tenants()")
                rows = cur.fetchall()

                # Should return tenants
                self.assertGreaterEqual(
                    len(rows), 1,
                    f"list_all_tenants() should return tenants for platform role"
                )

                # Verify api_key_hash is NOT in result
                if rows:
                    self.assertNotIn(
                        'api_key_hash', rows[0],
                        "api_key_hash should NOT be returned by list_all_tenants()"
                    )

                print(f"    [PASS] list_all_tenants() returned {len(rows)} tenants")

            finally:
                cur.execute("ROLLBACK")


class TestTablePrivilegeMatrix(unittest.TestCase):
    """
    Test that table privileges are correctly configured.

    Expected privilege matrix:
    +---------------------+----------+--------+--------+--------+
    | Table               | Role     | SELECT | INSERT | UPDATE | DELETE |
    +---------------------+----------+--------+--------+--------+--------+
    | tenants             | api      | NO     | NO     | NO     | NO     |
    | tenants             | platform | YES    | YES    | YES    | YES    |
    | idempotency_keys    | api      | YES*   | YES*   | YES*   | YES*   |
    | idempotency_keys    | platform | YES    | YES    | YES    | YES    |
    +---------------------+----------+--------+--------+--------+--------+
    * With RLS filtering by tenant_id
    """

    @classmethod
    def setUpClass(cls):
        """Set up test connection."""
        cls.conn = get_superuser_connection()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if cls.conn:
            cls.conn.close()

    def setUp(self):
        """Check connection before each test."""
        if not self.conn:
            self.skipTest("Database not available")

    def test_api_role_no_tenants_privileges(self):
        """
        solvereign_api should have NO privileges on tenants table.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    has_table_privilege('solvereign_api', 'tenants', 'SELECT') as can_select,
                    has_table_privilege('solvereign_api', 'tenants', 'INSERT') as can_insert,
                    has_table_privilege('solvereign_api', 'tenants', 'UPDATE') as can_update,
                    has_table_privilege('solvereign_api', 'tenants', 'DELETE') as can_delete
            """)
            result = cur.fetchone()

            self.assertFalse(
                result['can_select'],
                "solvereign_api should NOT have SELECT on tenants"
            )
            self.assertFalse(
                result['can_insert'],
                "solvereign_api should NOT have INSERT on tenants"
            )
            self.assertFalse(
                result['can_update'],
                "solvereign_api should NOT have UPDATE on tenants"
            )
            self.assertFalse(
                result['can_delete'],
                "solvereign_api should NOT have DELETE on tenants"
            )

            print("    [PASS] solvereign_api has NO privileges on tenants")

    def test_platform_role_has_tenants_privileges(self):
        """
        solvereign_platform should have full privileges on tenants table.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    has_table_privilege('solvereign_platform', 'tenants', 'SELECT') as can_select,
                    has_table_privilege('solvereign_platform', 'tenants', 'INSERT') as can_insert,
                    has_table_privilege('solvereign_platform', 'tenants', 'UPDATE') as can_update,
                    has_table_privilege('solvereign_platform', 'tenants', 'DELETE') as can_delete
            """)
            result = cur.fetchone()

            self.assertTrue(
                result['can_select'],
                "solvereign_platform should have SELECT on tenants"
            )
            self.assertTrue(
                result['can_insert'],
                "solvereign_platform should have INSERT on tenants"
            )
            self.assertTrue(
                result['can_update'],
                "solvereign_platform should have UPDATE on tenants"
            )
            self.assertTrue(
                result['can_delete'],
                "solvereign_platform should have DELETE on tenants"
            )

            print("    [PASS] solvereign_platform has full privileges on tenants")

    def test_function_privileges(self):
        """
        Verify function execution privileges are correct.
        """
        with self.conn.cursor() as cur:
            # API role functions
            cur.execute("""
                SELECT
                    has_function_privilege('solvereign_api',
                        'get_tenant_by_api_key_hash(VARCHAR)', 'EXECUTE') as can_auth,
                    has_function_privilege('solvereign_api',
                        'set_tenant_context(INTEGER)', 'EXECUTE') as can_set_tenant,
                    has_function_privilege('solvereign_api',
                        'list_all_tenants()', 'EXECUTE') as can_list
            """)
            api_result = cur.fetchone()

            self.assertTrue(
                api_result['can_auth'],
                "solvereign_api should have EXECUTE on get_tenant_by_api_key_hash()"
            )
            self.assertTrue(
                api_result['can_set_tenant'],
                "solvereign_api should have EXECUTE on set_tenant_context()"
            )
            self.assertFalse(
                api_result['can_list'],
                "solvereign_api should NOT have EXECUTE on list_all_tenants()"
            )

            # Platform role functions
            cur.execute("""
                SELECT
                    has_function_privilege('solvereign_platform',
                        'list_all_tenants()', 'EXECUTE') as can_list
            """)
            platform_result = cur.fetchone()

            self.assertTrue(
                platform_result['can_list'],
                "solvereign_platform should have EXECUTE on list_all_tenants()"
            )

            print("    [PASS] Function privileges are correctly configured")


class TestAPIRoleCannotEscalate(unittest.TestCase):
    """
    Test that solvereign_api role cannot escalate privileges.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test connection."""
        cls.conn = get_superuser_connection()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if cls.conn:
            cls.conn.close()

    def setUp(self):
        """Check connection before each test."""
        if not self.conn:
            self.skipTest("Database not available")

    def test_api_role_cannot_call_list_all_tenants(self):
        """
        solvereign_api should NOT be able to call list_all_tenants().
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to API role
                cur.execute("SET LOCAL ROLE solvereign_api")

                # Try to call list_all_tenants() - should fail
                with self.assertRaises(Exception) as ctx:
                    cur.execute("SELECT * FROM list_all_tenants()")

                # Should get permission denied error
                error_msg = str(ctx.exception).lower()
                self.assertTrue(
                    'permission' in error_msg or 'denied' in error_msg or 'privilege' in error_msg,
                    f"Expected permission denied error, got: {ctx.exception}"
                )

                print("    [PASS] solvereign_api cannot call list_all_tenants()")

            except AssertionError:
                raise
            except Exception as e:
                # If we got here from the execute, that's also acceptable
                if 'permission' in str(e).lower() or 'denied' in str(e).lower():
                    print("    [PASS] solvereign_api cannot call list_all_tenants()")
                else:
                    raise
            finally:
                cur.execute("ROLLBACK")

    def test_api_role_cannot_set_role_to_platform(self):
        """
        solvereign_api should NOT be able to SET ROLE to solvereign_platform.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Switch to API role
                cur.execute("SET LOCAL ROLE solvereign_api")

                # Try to escalate to platform role
                try:
                    cur.execute("SET LOCAL ROLE solvereign_platform")
                    # If we get here, check we didn't actually switch
                    cur.execute("SELECT current_user")
                    result = cur.fetchone()
                    self.assertNotEqual(
                        result['current_user'], 'solvereign_platform',
                        "API role should NOT be able to SET ROLE to platform!"
                    )
                except Exception as e:
                    # Expected: permission denied
                    error_msg = str(e).lower()
                    self.assertTrue(
                        'permission' in error_msg or 'denied' in error_msg or 'member' in error_msg,
                        f"Expected permission denied, got: {e}"
                    )
                    print("    [PASS] solvereign_api cannot escalate to solvereign_platform")

            finally:
                cur.execute("ROLLBACK")


class TestRLSPolicyDefinitions(unittest.TestCase):
    """
    Test that RLS policies are correctly defined.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test connection."""
        cls.conn = get_superuser_connection()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if cls.conn:
            cls.conn.close()

    def setUp(self):
        """Check connection before each test."""
        if not self.conn:
            self.skipTest("Database not available")

    def test_tenants_policy_uses_pg_has_role(self):
        """
        Verify tenants RLS policy uses pg_has_role(), not session variables.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT pg_get_expr(polqual, polrelid) as using_clause
                FROM pg_policy
                WHERE polrelid = 'tenants'::regclass
                  AND polname = 'tenants_platform_role_only'
            """)
            result = cur.fetchone()

            self.assertIsNotNone(
                result,
                "tenants_platform_role_only policy should exist"
            )

            using_clause = result['using_clause']

            # Should contain pg_has_role check
            self.assertIn(
                'pg_has_role',
                using_clause,
                f"Policy should use pg_has_role(), got: {using_clause}"
            )

            # Should NOT contain app.is_super_admin
            self.assertNotIn(
                'is_super_admin',
                using_clause,
                f"Policy should NOT use is_super_admin session var, got: {using_clause}"
            )

            print(f"    [PASS] tenants policy uses pg_has_role()")
            print(f"           Policy USING: {using_clause[:80]}...")

    def test_old_session_var_policy_removed(self):
        """
        Verify the old tenants_super_admin_only policy is removed.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pg_policies
                WHERE tablename = 'tenants'
                  AND policyname = 'tenants_super_admin_only'
            """)
            result = cur.fetchone()

            self.assertEqual(
                result['cnt'], 0,
                "Old tenants_super_admin_only policy should be removed"
            )

            print("    [PASS] Old session-var policy removed")


class TestVerificationFunction(unittest.TestCase):
    """
    Test the verify_rls_boundary() function.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test connection."""
        cls.conn = get_superuser_connection()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if cls.conn:
            cls.conn.close()

    def setUp(self):
        """Check connection before each test."""
        if not self.conn:
            self.skipTest("Database not available")

    def test_verify_function_all_pass(self):
        """
        Run verify_rls_boundary() and ensure all tests pass.
        """
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM verify_rls_boundary()")
            results = cur.fetchall()

            all_pass = True
            for r in results:
                if r['status'] != 'PASS':
                    print(f"    [FAIL] {r['test_name']}: expected={r['expected']}, actual={r['actual']}")
                    all_pass = False
                else:
                    print(f"    [PASS] {r['test_name']}")

            self.assertTrue(
                all_pass,
                "All verify_rls_boundary() tests should pass"
            )


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("RLS Boundary Fix Regression Tests (Migration 025c)")
    print("=" * 70)
    print()
    print("CRITICAL: These tests verify that the session variable bypass hole")
    print("          is closed. Failure indicates a security vulnerability.")
    print()
    print("-" * 70)

    # Run with verbosity
    unittest.main(verbosity=2)
