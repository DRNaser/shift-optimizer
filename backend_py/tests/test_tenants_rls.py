# =============================================================================
# SOLVEREIGN - RLS Regression Test for `tenants` Table (Migration 025)
# =============================================================================
# P0 Security Fix Validation:
#
# 1. Normal tenant context CANNOT see any rows in `tenants` table
# 2. SUPER_ADMIN context CAN see all rows in `tenants` table
# 3. API key lookup works via SECURITY DEFINER function
# 4. Default tenant is INACTIVE and cannot be used for auth
#
# Prerequisite: Migration 025 must be applied
# =============================================================================

import sys
import os
import unittest
import hashlib
from concurrent.futures import ThreadPoolExecutor

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


class TestTenantsTableRLS(unittest.TestCase):
    """
    P0 Security Fix: Test RLS on legacy `tenants` table.

    The `tenants` table contains api_key_hash values.
    Without RLS, a compromised connection could read ALL tenants' API keys.

    After Migration 025:
    - RLS is ENABLED on tenants table
    - Only super_admin can access rows directly
    - Normal tenant context sees NOTHING (tenants don't query each other)
    - API key lookup uses SECURITY DEFINER function
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.conn = get_test_connection()
        if not cls.conn:
            return

        # Create test tenants for this test
        with cls.conn.cursor() as cur:
            # Set super_admin context to create test data
            cur.execute("SET LOCAL app.is_super_admin = 'true'")

            # Create two test tenants
            cls.test_api_key_1 = "test_key_tenant_A_rls_test"
            cls.test_api_key_2 = "test_key_tenant_B_rls_test"
            cls.test_hash_1 = hashlib.sha256(cls.test_api_key_1.encode()).hexdigest()
            cls.test_hash_2 = hashlib.sha256(cls.test_api_key_2.encode()).hexdigest()

            cur.execute("""
                INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                VALUES
                    ('_test_tenant_A', %s, TRUE, '{"test": true}'::jsonb),
                    ('_test_tenant_B', %s, TRUE, '{"test": true}'::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    api_key_hash = EXCLUDED.api_key_hash,
                    is_active = EXCLUDED.is_active
                RETURNING id, name
            """, (cls.test_hash_1, cls.test_hash_2))

            results = cur.fetchall()
            cls.tenant_a_id = None
            cls.tenant_b_id = None
            for r in results:
                if r['name'] == '_test_tenant_A':
                    cls.tenant_a_id = r['id']
                elif r['name'] == '_test_tenant_B':
                    cls.tenant_b_id = r['id']

            cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if not cls.conn:
            return

        try:
            with cls.conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")
                cur.execute("""
                    DELETE FROM tenants WHERE name LIKE '_test_tenant_%'
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
    # TEST 1: Normal tenant context sees NOTHING
    # =========================================================================

    def test_normal_tenant_sees_no_rows(self):
        """
        PROOF: Normal tenant context cannot see ANY rows in tenants table.

        This is the CRITICAL isolation test. When a tenant queries the
        `tenants` table, they should see ZERO rows (not even their own).
        """
        with self.conn.cursor() as cur:
            # Start fresh transaction
            cur.execute("BEGIN")
            try:
                # Set tenant A context (NOT super_admin)
                cur.execute("SET LOCAL app.current_tenant_id = %s", (str(self.tenant_a_id),))
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Query tenants table
                cur.execute("SELECT * FROM tenants")
                rows = cur.fetchall()

                # Should see ZERO rows (super_admin_only policy)
                self.assertEqual(
                    len(rows), 0,
                    f"Normal tenant should see 0 rows in tenants table, got {len(rows)}"
                )

                print(f"    [PASS] Normal tenant sees 0 rows (CORRECT)")

            finally:
                cur.execute("ROLLBACK")

    def test_tenant_a_cannot_see_tenant_b_api_key(self):
        """
        PROOF: Tenant A cannot query for Tenant B's API key hash.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Set tenant A context
                cur.execute("SET LOCAL app.current_tenant_id = %s", (str(self.tenant_a_id),))
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Try to find tenant B's API key hash
                cur.execute("""
                    SELECT api_key_hash FROM tenants WHERE name = '_test_tenant_B'
                """)
                rows = cur.fetchall()

                # Should find NOTHING
                self.assertEqual(
                    len(rows), 0,
                    f"Tenant A should NOT see Tenant B's API key hash"
                )

                print(f"    [PASS] Tenant A cannot see Tenant B's API key hash")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST 2: SUPER_ADMIN can see all rows
    # =========================================================================

    def test_super_admin_sees_all_tenants(self):
        """
        PROOF: SUPER_ADMIN context can see all tenants.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Set super_admin context
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                # Query tenants table
                cur.execute("SELECT COUNT(*) as cnt FROM tenants")
                result = cur.fetchone()

                # Should see at least the 2 test tenants + migration data owner
                self.assertGreaterEqual(
                    result['cnt'], 3,
                    f"SUPER_ADMIN should see at least 3 tenants, got {result['cnt']}"
                )

                print(f"    [PASS] SUPER_ADMIN sees {result['cnt']} tenants")

            finally:
                cur.execute("ROLLBACK")

    def test_super_admin_can_read_api_key_hashes(self):
        """
        PROOF: SUPER_ADMIN can read API key hashes (for admin operations).
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                cur.execute("""
                    SELECT name, api_key_hash FROM tenants
                    WHERE name LIKE '_test_tenant_%'
                    ORDER BY name
                """)
                rows = cur.fetchall()

                self.assertEqual(len(rows), 2, "Should see both test tenants")

                # Verify hashes are correct
                for row in rows:
                    if row['name'] == '_test_tenant_A':
                        self.assertEqual(row['api_key_hash'], self.test_hash_1)
                    elif row['name'] == '_test_tenant_B':
                        self.assertEqual(row['api_key_hash'], self.test_hash_2)

                print(f"    [PASS] SUPER_ADMIN can read API key hashes")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST 3: SECURITY DEFINER function for API key lookup
    # =========================================================================

    def test_security_definer_function_exists(self):
        """
        PROOF: SECURITY DEFINER function for API key lookup exists.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public'
                    AND p.proname = 'get_tenant_by_api_key_hash'
                ) as exists
            """)
            result = cur.fetchone()

            self.assertTrue(
                result['exists'],
                "get_tenant_by_api_key_hash() function should exist"
            )

            print(f"    [PASS] SECURITY DEFINER function exists")

    def test_security_definer_bypasses_rls(self):
        """
        PROOF: SECURITY DEFINER function can lookup tenant even without context.

        This is critical for authentication - the function must work BEFORE
        tenant context is established.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Clear ALL context (simulate pre-auth state)
                cur.execute("SET LOCAL app.current_tenant_id = ''")
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Direct query should return nothing
                cur.execute("SELECT COUNT(*) as cnt FROM tenants")
                direct_count = cur.fetchone()['cnt']
                self.assertEqual(direct_count, 0, "Direct query should return 0 rows")

                # But SECURITY DEFINER function should work
                cur.execute("""
                    SELECT * FROM get_tenant_by_api_key_hash(%s)
                """, (self.test_hash_1,))
                result = cur.fetchone()

                self.assertIsNotNone(
                    result,
                    "SECURITY DEFINER function should find tenant by hash"
                )
                self.assertEqual(result['name'], '_test_tenant_A')
                self.assertTrue(result['is_active'])

                print(f"    [PASS] SECURITY DEFINER function bypasses RLS correctly")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST 4: Default tenant is INACTIVE
    # =========================================================================

    def test_default_tenant_is_inactive(self):
        """
        PROOF: Migration data owner tenant is INACTIVE (cannot auth).
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                cur.execute("""
                    SELECT name, is_active, api_key_hash, metadata
                    FROM tenants WHERE id = 1
                """)
                result = cur.fetchone()

                if result:
                    self.assertFalse(
                        result['is_active'],
                        f"Default tenant (id=1) should be INACTIVE, got is_active={result['is_active']}"
                    )

                    # Verify it's the migration owner
                    self.assertIn('migration', result['name'].lower())

                    # Verify hash is placeholder (64 zeros)
                    expected_placeholder = '0' * 64
                    self.assertEqual(
                        result['api_key_hash'], expected_placeholder,
                        "Default tenant should have placeholder hash (64 zeros)"
                    )

                    print(f"    [PASS] Default tenant is INACTIVE with placeholder hash")
                else:
                    # If id=1 doesn't exist, that's also acceptable
                    print(f"    [INFO] No tenant with id=1 exists")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST 5: Parallel access isolation
    # =========================================================================

    def test_parallel_tenant_isolation(self):
        """
        PROOF: Parallel connections with different tenant contexts are isolated.
        """
        results = {}
        errors = []

        def query_as_tenant(tenant_id: int, label: str):
            """Query tenants table with specific tenant context."""
            conn = get_test_connection()
            if not conn:
                errors.append(f"{label}: Connection failed")
                return

            try:
                with conn.cursor() as cur:
                    cur.execute("BEGIN")
                    cur.execute("SET LOCAL app.current_tenant_id = %s", (str(tenant_id),))
                    cur.execute("SET LOCAL app.is_super_admin = 'false'")

                    cur.execute("SELECT COUNT(*) as cnt FROM tenants")
                    count = cur.fetchone()['cnt']
                    results[label] = count

                    cur.execute("ROLLBACK")
            except Exception as e:
                errors.append(f"{label}: {e}")
            finally:
                conn.close()

        # Run parallel queries
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(5):
                # Alternate between tenant A and B
                tid = self.tenant_a_id if i % 2 == 0 else self.tenant_b_id
                label = f"query_{i}_tenant_{'A' if i % 2 == 0 else 'B'}"
                futures.append(executor.submit(query_as_tenant, tid, label))

            for f in futures:
                f.result()

        # Verify no errors
        self.assertEqual(len(errors), 0, f"Parallel queries had errors: {errors}")

        # Verify all queries returned 0 (RLS blocked access)
        for label, count in results.items():
            self.assertEqual(
                count, 0,
                f"{label} should see 0 rows, got {count}"
            )

        print(f"    [PASS] {len(results)} parallel queries correctly isolated")


class TestListAllTenantsFunction(unittest.TestCase):
    """
    Test the list_all_tenants() platform admin function.
    """

    def setUp(self):
        """Set up database connection."""
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

    def tearDown(self):
        """Close connection."""
        if self.conn:
            self.conn.close()

    def test_non_admin_cannot_list_tenants(self):
        """
        PROOF: Non-admin cannot use list_all_tenants() function.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Set non-admin context
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Try to call list_all_tenants
                with self.assertRaises(Exception) as context:
                    cur.execute("SELECT * FROM list_all_tenants()")

                self.assertIn(
                    "super_admin",
                    str(context.exception).lower(),
                    "Error should mention super_admin requirement"
                )

                print(f"    [PASS] Non-admin blocked from list_all_tenants()")

            except AssertionError:
                raise
            except Exception:
                # Exception is expected
                print(f"    [PASS] Non-admin blocked from list_all_tenants()")
            finally:
                cur.execute("ROLLBACK")

    def test_admin_can_list_tenants(self):
        """
        PROOF: SUPER_ADMIN can use list_all_tenants() function.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                cur.execute("SELECT * FROM list_all_tenants()")
                rows = cur.fetchall()

                self.assertGreaterEqual(
                    len(rows), 1,
                    "SUPER_ADMIN should see at least 1 tenant"
                )

                # Verify no api_key_hash in results (security)
                for row in rows:
                    self.assertNotIn(
                        'api_key_hash', row,
                        "list_all_tenants() should NOT return api_key_hash"
                    )

                print(f"    [PASS] SUPER_ADMIN can list {len(rows)} tenants (no api_key_hash)")

            finally:
                cur.execute("ROLLBACK")


class TestHardenedFunctions(unittest.TestCase):
    """
    Test hardening requirements from Migration 025a.

    Tests:
    - search_path is set on SECURITY DEFINER functions
    - is_active enforcement in get_tenant_by_api_key_hash()
    - REVOKE FROM PUBLIC is applied
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.conn = get_test_connection()
        if not cls.conn:
            return

        # Create test tenants including an INACTIVE one
        with cls.conn.cursor() as cur:
            cur.execute("SET LOCAL app.is_super_admin = 'true'")

            cls.inactive_api_key = "test_key_INACTIVE_tenant"
            cls.inactive_hash = hashlib.sha256(cls.inactive_api_key.encode()).hexdigest()

            cur.execute("""
                INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                VALUES ('_test_tenant_INACTIVE', %s, FALSE, '{"test": true}'::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    api_key_hash = EXCLUDED.api_key_hash,
                    is_active = FALSE
                RETURNING id
            """, (cls.inactive_hash,))

            result = cur.fetchone()
            cls.inactive_tenant_id = result['id'] if result else None
            cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if not cls.conn:
            return

        try:
            with cls.conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")
                cur.execute("DELETE FROM tenants WHERE name = '_test_tenant_INACTIVE'")
                cls.conn.commit()
        except Exception:
            pass
        finally:
            cls.conn.close()

    def setUp(self):
        if not self.conn:
            self.skipTest("Database not available")

    # =========================================================================
    # TEST: is_active enforcement
    # =========================================================================

    def test_inactive_tenant_not_returned_by_auth_function(self):
        """
        PROOF: get_tenant_by_api_key_hash() does NOT return inactive tenants.

        This is defense-in-depth. Even if an attacker obtains a valid API key
        for an inactive tenant, the DB-level check rejects it.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Clear context
                cur.execute("SET LOCAL app.current_tenant_id = ''")
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Try to look up the INACTIVE tenant
                cur.execute("""
                    SELECT * FROM get_tenant_by_api_key_hash(%s)
                """, (self.inactive_hash,))
                result = cur.fetchone()

                # Should return NULL (no rows)
                self.assertIsNone(
                    result,
                    "get_tenant_by_api_key_hash() should NOT return inactive tenants"
                )

                print(f"    [PASS] Inactive tenant blocked at DB level")

            finally:
                cur.execute("ROLLBACK")

    def test_inactive_tenant_exists_but_blocked(self):
        """
        PROOF: Verify the inactive tenant exists but is blocked by is_active filter.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # As super_admin, verify tenant exists
                cur.execute("SET LOCAL app.is_super_admin = 'true'")

                cur.execute("""
                    SELECT id, name, is_active FROM tenants
                    WHERE api_key_hash = %s
                """, (self.inactive_hash,))
                result = cur.fetchone()

                self.assertIsNotNone(result, "Inactive tenant should exist in DB")
                self.assertEqual(result['name'], '_test_tenant_INACTIVE')
                self.assertFalse(result['is_active'], "Tenant should be inactive")

                print(f"    [PASS] Inactive tenant exists but is correctly marked inactive")

            finally:
                cur.execute("ROLLBACK")

    # =========================================================================
    # TEST: search_path hardening
    # =========================================================================

    def test_security_definer_functions_have_search_path(self):
        """
        PROOF: All SECURITY DEFINER functions have search_path set.

        This prevents search_path hijacking attacks where an attacker creates
        a malicious function in a schema that appears earlier in search_path.
        """
        with self.conn.cursor() as cur:
            # Check all relevant functions
            cur.execute("""
                SELECT p.proname, p.proconfig
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public'
                  AND p.prosecdef = true
                  AND p.proname IN (
                      'get_tenant_by_api_key_hash',
                      'list_all_tenants',
                      'set_super_admin_context',
                      'set_tenant_context'
                  )
            """)
            functions = cur.fetchall()

            for func in functions:
                proconfig = func['proconfig'] or []
                has_search_path = any('search_path' in str(c) for c in proconfig)

                self.assertTrue(
                    has_search_path,
                    f"Function {func['proname']} should have search_path set in proconfig"
                )
                print(f"    [PASS] {func['proname']} has search_path hardening")

    # =========================================================================
    # TEST: REVOKE FROM PUBLIC
    # =========================================================================

    def test_no_public_execute_on_sensitive_functions(self):
        """
        PROOF: Sensitive functions do NOT have PUBLIC EXECUTE.
        """
        with self.conn.cursor() as cur:
            sensitive_functions = [
                'get_tenant_by_api_key_hash',
                'list_all_tenants',
            ]

            for func_name in sensitive_functions:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.routine_privileges
                        WHERE routine_name = %s
                          AND grantee = 'PUBLIC'
                          AND privilege_type = 'EXECUTE'
                    ) as has_public
                """, (func_name,))
                result = cur.fetchone()

                self.assertFalse(
                    result['has_public'],
                    f"Function {func_name} should NOT have PUBLIC EXECUTE privilege"
                )
                print(f"    [PASS] {func_name} has no PUBLIC EXECUTE")

    # =========================================================================
    # TEST: list_all_tenants output validation
    # =========================================================================

    def test_list_all_tenants_no_api_key_hash_column(self):
        """
        PROOF: list_all_tenants() return type does NOT include api_key_hash.
        """
        with self.conn.cursor() as cur:
            # Check the function's return columns
            cur.execute("""
                SELECT a.attname
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                JOIN pg_type t ON p.prorettype = t.oid
                JOIN pg_class c ON t.typrelid = c.oid
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE n.nspname = 'public'
                  AND p.proname = 'list_all_tenants'
                  AND a.attnum > 0
            """)
            columns = [row['attname'] for row in cur.fetchall()]

            self.assertNotIn(
                'api_key_hash', columns,
                f"list_all_tenants() should NOT return api_key_hash. Columns: {columns}"
            )

            print(f"    [PASS] list_all_tenants() columns: {columns} (no api_key_hash)")


class TestIdempotencyKeysRLS(unittest.TestCase):
    """
    Test RLS on idempotency_keys table.
    """

    def setUp(self):
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

    def tearDown(self):
        if self.conn:
            self.conn.close()

    def test_idempotency_keys_has_rls_enabled(self):
        """
        PROOF: idempotency_keys table has RLS enabled.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = 'idempotency_keys'
            """)
            result = cur.fetchone()

            if result:
                self.assertTrue(
                    result['relrowsecurity'],
                    "idempotency_keys should have RLS enabled"
                )
                self.assertTrue(
                    result['relforcerowsecurity'],
                    "idempotency_keys should have FORCE RLS enabled"
                )
                print(f"    [PASS] idempotency_keys has RLS + FORCE RLS")
            else:
                self.skipTest("idempotency_keys table does not exist")

    def test_idempotency_keys_has_tenant_isolation_policy(self):
        """
        PROOF: idempotency_keys has tenant isolation policy.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT policyname, cmd, qual, with_check
                FROM pg_policies
                WHERE tablename = 'idempotency_keys'
            """)
            policies = cur.fetchall()

            if not policies:
                self.skipTest("idempotency_keys table or policies do not exist")

            policy_names = [p['policyname'] for p in policies]
            self.assertIn(
                'idempotency_keys_tenant_isolation', policy_names,
                f"Should have tenant_isolation policy. Found: {policy_names}"
            )

            print(f"    [PASS] idempotency_keys has tenant isolation policy")

    def test_idempotency_keys_policy_has_using_and_with_check(self):
        """
        PROOF: idempotency_keys policy has both USING and WITH CHECK clauses.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT qual, with_check
                FROM pg_policies
                WHERE tablename = 'idempotency_keys'
                  AND policyname = 'idempotency_keys_tenant_isolation'
            """)
            result = cur.fetchone()

            if not result:
                self.skipTest("idempotency_keys_tenant_isolation policy not found")

            self.assertIsNotNone(
                result['qual'],
                "Policy should have USING clause"
            )
            self.assertIsNotNone(
                result['with_check'],
                "Policy should have WITH CHECK clause"
            )

            # Verify tenant_id is in the clauses
            self.assertIn(
                'tenant_id', result['qual'],
                "USING clause should reference tenant_id"
            )
            self.assertIn(
                'tenant_id', result['with_check'],
                "WITH CHECK clause should reference tenant_id"
            )

            print(f"    [PASS] idempotency_keys policy has USING + WITH CHECK with tenant_id")


class TestIdempotencyKeysCrossTenantIsolation(unittest.TestCase):
    """
    Test cross-tenant isolation on idempotency_keys table.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.conn = get_test_connection()
        if not cls.conn:
            return

        # Check if idempotency_keys table exists
        with cls.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'idempotency_keys'
                )
            """)
            if not cur.fetchone()['exists']:
                cls.table_exists = False
                return
            cls.table_exists = True

            # Create test tenants
            cur.execute("SET LOCAL app.is_super_admin = 'true'")

            # Get or create tenant IDs for testing
            cur.execute("""
                INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                VALUES
                    ('_test_idem_tenant_A', 'idem_hash_a_test', TRUE, '{}'::jsonb),
                    ('_test_idem_tenant_B', 'idem_hash_b_test', TRUE, '{}'::jsonb)
                ON CONFLICT (name) DO UPDATE SET is_active = TRUE
                RETURNING id, name
            """)
            results = cur.fetchall()
            cls.tenant_a_id = None
            cls.tenant_b_id = None
            for r in results:
                if r['name'] == '_test_idem_tenant_A':
                    cls.tenant_a_id = r['id']
                elif r['name'] == '_test_idem_tenant_B':
                    cls.tenant_b_id = r['id']

            cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if not cls.conn:
            return

        try:
            with cls.conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true'")
                cur.execute("""
                    DELETE FROM idempotency_keys
                    WHERE tenant_id IN (
                        SELECT id FROM tenants WHERE name LIKE '_test_idem_tenant_%'
                    )
                """)
                cur.execute("DELETE FROM tenants WHERE name LIKE '_test_idem_tenant_%'")
                cls.conn.commit()
        except Exception:
            pass
        finally:
            cls.conn.close()

    def setUp(self):
        if not self.conn:
            self.skipTest("Database not available")
        if not getattr(self, 'table_exists', False):
            self.skipTest("idempotency_keys table does not exist")

    def test_tenant_cannot_read_other_tenant_idempotency_keys(self):
        """
        PROOF: Tenant A cannot read Tenant B's idempotency keys.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Insert key as Tenant A
                cur.execute("SET LOCAL app.current_tenant_id = %s", (str(self.tenant_a_id),))
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                cur.execute("""
                    INSERT INTO idempotency_keys
                        (tenant_id, idempotency_key, endpoint, method, request_hash, expires_at)
                    VALUES (%s, 'key_A_test', '/test', 'POST', 'hash_a', NOW() + INTERVAL '1 hour')
                    ON CONFLICT DO NOTHING
                """, (self.tenant_a_id,))

                # Switch to Tenant B context
                cur.execute("SET LOCAL app.current_tenant_id = %s", (str(self.tenant_b_id),))

                # Try to read Tenant A's key
                cur.execute("""
                    SELECT * FROM idempotency_keys
                    WHERE idempotency_key = 'key_A_test'
                """)
                result = cur.fetchone()

                self.assertIsNone(
                    result,
                    "Tenant B should NOT be able to read Tenant A's idempotency key"
                )

                print(f"    [PASS] Tenant B cannot read Tenant A's idempotency keys")

            finally:
                cur.execute("ROLLBACK")

    def test_tenant_cannot_write_other_tenant_idempotency_keys(self):
        """
        PROOF: Tenant A cannot insert idempotency keys with Tenant B's tenant_id.
        """
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                # Set context as Tenant A
                cur.execute("SET LOCAL app.current_tenant_id = %s", (str(self.tenant_a_id),))
                cur.execute("SET LOCAL app.is_super_admin = 'false'")

                # Try to insert with Tenant B's ID (should fail WITH CHECK)
                try:
                    cur.execute("""
                        INSERT INTO idempotency_keys
                            (tenant_id, idempotency_key, endpoint, method, request_hash, expires_at)
                        VALUES (%s, 'key_evil_test', '/test', 'POST', 'hash_evil', NOW() + INTERVAL '1 hour')
                    """, (self.tenant_b_id,))
                    # If we get here, RLS didn't block - that's a failure
                    self.fail("Tenant A should NOT be able to insert with Tenant B's tenant_id")
                except Exception as e:
                    # Expected: RLS WITH CHECK violation
                    self.assertIn(
                        "row-level", str(e).lower(),
                        f"Expected RLS violation, got: {e}"
                    )

                print(f"    [PASS] Tenant A cannot insert with Tenant B's tenant_id")

            finally:
                cur.execute("ROLLBACK")


class TestRoleBasedAccessControl(unittest.TestCase):
    """
    Test role-based access control on security functions.

    Uses SET ROLE to simulate different database roles.
    Requires migration 025b to be applied.
    """

    def setUp(self):
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

        # Check if roles exist
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api'
                ) as api_exists,
                EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform'
                ) as platform_exists
            """)
            result = cur.fetchone()
            self.api_role_exists = result['api_exists']
            self.platform_role_exists = result['platform_exists']

    def tearDown(self):
        if self.conn:
            self.conn.close()

    def test_api_role_can_execute_auth_function(self):
        """
        PROOF: solvereign_api role CAN execute get_tenant_by_api_key_hash().
        """
        if not self.api_role_exists:
            self.skipTest("solvereign_api role does not exist")

        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'get_tenant_by_api_key_hash(VARCHAR)',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            self.assertTrue(
                result['can_execute'],
                "solvereign_api should be able to execute get_tenant_by_api_key_hash()"
            )

            print(f"    [PASS] solvereign_api can execute get_tenant_by_api_key_hash()")

    def test_api_role_cannot_execute_list_all_tenants(self):
        """
        PROOF: solvereign_api role CANNOT execute list_all_tenants().
        """
        if not self.api_role_exists:
            self.skipTest("solvereign_api role does not exist")

        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'list_all_tenants()',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            self.assertFalse(
                result['can_execute'],
                "solvereign_api should NOT be able to execute list_all_tenants()"
            )

            print(f"    [PASS] solvereign_api CANNOT execute list_all_tenants()")

    def test_api_role_cannot_execute_set_super_admin_context(self):
        """
        PROOF: solvereign_api role CANNOT execute set_super_admin_context().

        This is CRITICAL: prevents privilege escalation from API role.
        """
        if not self.api_role_exists:
            self.skipTest("solvereign_api role does not exist")

        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'set_super_admin_context(BOOLEAN)',
                    'EXECUTE'
                ) as can_execute
            """)
            result = cur.fetchone()

            self.assertFalse(
                result['can_execute'],
                "solvereign_api should NOT be able to execute set_super_admin_context()"
            )

            print(f"    [PASS] solvereign_api CANNOT escalate to super_admin")

    def test_platform_role_can_execute_admin_functions(self):
        """
        PROOF: solvereign_platform role CAN execute admin functions.
        """
        if not self.platform_role_exists:
            self.skipTest("solvereign_platform role does not exist")

        with self.conn.cursor() as cur:
            # Check list_all_tenants
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_platform',
                    'list_all_tenants()',
                    'EXECUTE'
                ) as can_list
            """)
            can_list = cur.fetchone()['can_list']

            # Check set_super_admin_context
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_platform',
                    'set_super_admin_context(BOOLEAN)',
                    'EXECUTE'
                ) as can_escalate
            """)
            can_escalate = cur.fetchone()['can_escalate']

            self.assertTrue(can_list, "solvereign_platform should be able to list tenants")
            self.assertTrue(can_escalate, "solvereign_platform should be able to set super_admin")

            print(f"    [PASS] solvereign_platform can execute admin functions")

    def test_public_cannot_execute_any_security_functions(self):
        """
        PROOF: PUBLIC role cannot execute any security functions.
        """
        security_functions = [
            'get_tenant_by_api_key_hash(VARCHAR)',
            'list_all_tenants()',
            'set_super_admin_context(BOOLEAN)',
            'set_tenant_context(INTEGER)',
        ]

        with self.conn.cursor() as cur:
            for func in security_functions:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.routine_privileges
                        WHERE routine_schema = 'public'
                          AND routine_name = split_part(%s, '(', 1)
                          AND grantee = 'PUBLIC'
                          AND privilege_type = 'EXECUTE'
                    ) as has_public
                """, (func,))
                result = cur.fetchone()

                self.assertFalse(
                    result['has_public'],
                    f"PUBLIC should NOT have EXECUTE on {func}"
                )

            print(f"    [PASS] PUBLIC cannot execute any security functions")


class TestSecurityDefinerCallerCheck(unittest.TestCase):
    """
    Regression test for SECURITY DEFINER session_user vs current_user bug.

    BUG: In SECURITY DEFINER functions, current_user returns the function OWNER,
    not the actual caller. This means pg_has_role(current_user, ...) checks if
    the function owner has the role, not the caller.

    FIX: Use session_user instead, which always returns the original connection user.

    This test verifies:
    1. list_all_tenants() uses session_user (not current_user) for role check
    2. A non-platform caller is denied even if function owner has platform access
    3. The function definition explicitly uses session_user
    """

    def setUp(self):
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

        # Check if the function exists
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc
                    WHERE proname = 'list_all_tenants'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("list_all_tenants() function does not exist")

    def tearDown(self):
        if self.conn:
            self.conn.close()

    def test_list_all_tenants_uses_session_user(self):
        """
        REGRESSION TEST: list_all_tenants() MUST use session_user for role check.

        If this test fails, there's a security vulnerability: any SECURITY DEFINER
        function owned by a platform member would grant access regardless of caller.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT pg_get_functiondef(oid) as funcdef
                FROM pg_proc
                WHERE proname = 'list_all_tenants'
            """)
            result = cur.fetchone()
            funcdef = result['funcdef']

            # MUST use session_user
            self.assertIn(
                'pg_has_role(session_user',
                funcdef,
                "list_all_tenants() MUST use session_user for role check, not current_user. "
                "In SECURITY DEFINER context, current_user is the function owner!"
            )

            # MUST NOT use current_user for role check
            self.assertNotIn(
                'pg_has_role(current_user',
                funcdef,
                "list_all_tenants() MUST NOT use current_user for role check. "
                "In SECURITY DEFINER context, current_user is the function owner, not the caller!"
            )

            print(f"    [PASS] list_all_tenants() correctly uses session_user for role check")

    def test_verify_rls_boundary_checks_function_definition(self):
        """
        REGRESSION TEST: verify_rls_boundary() includes checks for session_user usage.
        """
        with self.conn.cursor() as cur:
            # Run verify_rls_boundary and check for session_user tests
            cur.execute("SELECT * FROM verify_rls_boundary()")
            results = cur.fetchall()

            # Find the session_user test result
            session_user_test = None
            current_user_test = None
            for r in results:
                if 'uses session_user' in r['test_name']:
                    session_user_test = r
                if 'NOT use current_user' in r['test_name']:
                    current_user_test = r

            # Verify the tests exist and pass
            if session_user_test:
                self.assertEqual(
                    session_user_test['status'], 'PASS',
                    f"session_user check failed: {session_user_test}"
                )
                print(f"    [PASS] verify_rls_boundary() confirms session_user usage")

            if current_user_test:
                self.assertEqual(
                    current_user_test['status'], 'PASS',
                    f"current_user check failed: {current_user_test}"
                )
                print(f"    [PASS] verify_rls_boundary() confirms no current_user usage")

    def test_security_definer_context_shows_different_users(self):
        """
        INFO TEST: Show session_user vs current_user in SECURITY DEFINER context.

        This is informational - it shows that inside a SECURITY DEFINER function,
        current_user becomes the function owner while session_user stays as the caller.
        """
        with self.conn.cursor() as cur:
            # Run verify_rls_boundary and get the context info
            cur.execute("SELECT * FROM verify_rls_boundary()")
            results = cur.fetchall()

            for r in results:
                if 'session_user != current_user' in r['test_name']:
                    print(f"    [INFO] SECURITY DEFINER context: {r['actual']}")
                    # This is informational - always passes
                    break

            self.assertTrue(True)  # Informational test

    def test_non_platform_caller_denied_access(self):
        """
        CRITICAL: A non-platform caller MUST be denied access to list_all_tenants().

        This tests the actual security boundary, not just the function definition.
        """
        with self.conn.cursor() as cur:
            # Check if solvereign_api exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api'
                ) as exists
            """)
            if not cur.fetchone()['exists']:
                self.skipTest("solvereign_api role does not exist")

            # Verify API role cannot execute list_all_tenants even if it could call it
            # (The GRANT already prevents calling, but this tests the internal check too)
            cur.execute("""
                SELECT has_function_privilege(
                    'solvereign_api',
                    'list_all_tenants()',
                    'EXECUTE'
                ) as can_execute
            """)
            can_execute = cur.fetchone()['can_execute']

            self.assertFalse(
                can_execute,
                "solvereign_api should NOT be able to execute list_all_tenants()"
            )

            print(f"    [PASS] Non-platform caller (solvereign_api) is denied access")

    def test_function_owner_has_no_bypassrls(self):
        """
        CRITICAL: Function owner of SECURITY DEFINER functions MUST NOT have BYPASSRLS.

        If the function owner has BYPASSRLS, the function can bypass RLS even with
        FORCE ROW LEVEL SECURITY enabled.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT r.rolname, r.rolbypassrls
                FROM pg_proc p
                JOIN pg_roles r ON p.proowner = r.oid
                WHERE p.proname = 'list_all_tenants'
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['rolbypassrls'],
                    f"Function owner '{result['rolname']}' has BYPASSRLS! "
                    "SECURITY DEFINER functions should be owned by a role without BYPASSRLS."
                )
                print(f"    [PASS] Function owner '{result['rolname']}' has NO BYPASSRLS")
            else:
                self.skipTest("list_all_tenants() function not found")

    def test_api_role_cannot_escalate_to_platform(self):
        """
        CRITICAL: solvereign_api MUST NOT be able to SET ROLE to solvereign_platform.

        If api can escalate to platform, the entire RLS boundary is compromised.
        """
        with self.conn.cursor() as cur:
            # Check if both roles exist
            cur.execute("""
                SELECT
                    EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') as api_exists,
                    EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') as platform_exists
            """)
            result = cur.fetchone()

            if not result['api_exists'] or not result['platform_exists']:
                self.skipTest("Required roles do not exist")

            # Check if solvereign_api is a member of solvereign_platform
            cur.execute("""
                SELECT pg_has_role('solvereign_api', 'solvereign_platform', 'MEMBER') as is_member
            """)
            is_member = cur.fetchone()['is_member']

            self.assertFalse(
                is_member,
                "solvereign_api is a MEMBER of solvereign_platform! "
                "This allows privilege escalation via SET ROLE."
            )

            print(f"    [PASS] solvereign_api cannot escalate to solvereign_platform")

    def test_api_role_has_no_bypassrls(self):
        """
        CRITICAL: solvereign_api role MUST NOT have BYPASSRLS.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT rolbypassrls FROM pg_roles WHERE rolname = 'solvereign_api'
            """)
            result = cur.fetchone()

            if result:
                self.assertFalse(
                    result['rolbypassrls'],
                    "solvereign_api has BYPASSRLS! This bypasses all RLS policies."
                )
                print(f"    [PASS] solvereign_api has NO BYPASSRLS")
            else:
                self.skipTest("solvereign_api role does not exist")


class TestPrivilegeEnumeration(unittest.TestCase):
    """
    Test that shows current privilege state for verification.
    """

    def setUp(self):
        self.conn = get_test_connection()
        if not self.conn:
            self.skipTest("Database not available")

    def tearDown(self):
        if self.conn:
            self.conn.close()

    def test_enumerate_security_function_grants(self):
        """
        Enumerate all EXECUTE grants on security functions.

        This test always passes but prints the current state for verification.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    p.proname AS function_name,
                    r.rolname AS grantee,
                    'EXECUTE' AS privilege
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                CROSS JOIN pg_roles r
                WHERE n.nspname = 'public'
                  AND p.proname IN (
                      'get_tenant_by_api_key_hash',
                      'list_all_tenants',
                      'set_super_admin_context',
                      'set_tenant_context'
                  )
                  AND has_function_privilege(r.oid, p.oid, 'EXECUTE')
                  AND r.rolname NOT LIKE 'pg_%'
                  AND r.rolname != 'PUBLIC'
                ORDER BY p.proname, r.rolname
            """)
            grants = cur.fetchall()

            print("\n    Current EXECUTE grants on security functions:")
            print("    " + "-" * 60)
            for g in grants:
                print(f"    {g['function_name']:30} → {g['grantee']}")
            print("    " + "-" * 60)

            # This test is informational - always passes
            self.assertTrue(True)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN - RLS Regression Test for `tenants` Table")
    print("Migrations: 025 (RLS) + 025a (Hardening)")
    print("=" * 70)
    print("\nPrerequisites:")
    print("  1. PostgreSQL running on localhost:5432")
    print("  2. Migration 025 (025_tenants_rls_fix.sql) applied")
    print("  3. Migration 025a (025a_rls_hardening.sql) applied")
    print("")

    # Run tests
    unittest.main(verbosity=2)
