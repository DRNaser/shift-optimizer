# =============================================================================
# SOLVEREIGN Core Tenants - RLS & Seed Validation Tests
# =============================================================================
# Tests for:
# 1. Seed data validation (all tenants, sites, entitlements exist)
# 2. RLS isolation (tenant A cannot see tenant B data)
# 3. Platform admin bypass (can see all tenants)
# 4. Transaction-scoped context (context clears after transaction)
# =============================================================================

import sys
import unittest
from datetime import datetime

sys.path.insert(0, ".")


class TestCoreTenantsSeedData(unittest.TestCase):
    """
    Test that seed data was applied correctly.

    Run after applying migrations 013 and 014.
    """

    def setUp(self):
        """Set up database connection."""
        try:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(
                "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
                row_factory=dict_row
            )
            self.skip_tests = False
        except Exception as e:
            print(f"Database connection failed: {e}")
            self.skip_tests = True

    def tearDown(self):
        """Close database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def test_tenants_exist(self):
        """Verify all 4 tenants were seeded."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Platform admin context to see all data
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("""
                SELECT tenant_code, name, is_active
                FROM core.tenants
                ORDER BY tenant_code
            """)
            tenants = cur.fetchall()

        tenant_codes = [t["tenant_code"] for t in tenants]
        self.assertEqual(len(tenants), 4, "Should have exactly 4 tenants")
        self.assertIn("amazonlogistics", tenant_codes)
        self.assertIn("hdplus", tenant_codes)
        self.assertIn("mediamarkt", tenant_codes)
        self.assertIn("rohlik", tenant_codes)

        # All should be active
        for t in tenants:
            self.assertTrue(t["is_active"], f"{t['tenant_code']} should be active")

    def test_rohlik_sites(self):
        """Verify Rohlik has 4 sites with correct timezones."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("""
                SELECT s.site_code, s.name, s.timezone
                FROM core.sites s
                JOIN core.tenants t ON s.tenant_id = t.id
                WHERE t.tenant_code = 'rohlik'
                ORDER BY s.site_code
            """)
            sites = cur.fetchall()

        self.assertEqual(len(sites), 4, "Rohlik should have 4 sites")

        site_map = {s["site_code"]: s for s in sites}
        self.assertEqual(site_map["wien"]["timezone"], "Europe/Vienna")
        self.assertEqual(site_map["prag"]["timezone"], "Europe/Prague")
        self.assertEqual(site_map["budapest"]["timezone"], "Europe/Budapest")
        self.assertEqual(site_map["muenchen"]["timezone"], "Europe/Berlin")

    def test_mediamarkt_sites(self):
        """Verify MediaMarkt has 7 sites."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("""
                SELECT COUNT(*) as site_count
                FROM core.sites s
                JOIN core.tenants t ON s.tenant_id = t.id
                WHERE t.tenant_code = 'mediamarkt'
            """)
            result = cur.fetchone()

        self.assertEqual(result["site_count"], 7, "MediaMarkt should have 7 sites")

    def test_entitlements_exist(self):
        """Verify entitlements were seeded correctly."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Check Rohlik has routing enabled
            cur.execute("""
                SELECT e.is_enabled, e.config
                FROM core.tenant_entitlements e
                JOIN core.tenants t ON e.tenant_id = t.id
                WHERE t.tenant_code = 'rohlik' AND e.pack_id = 'routing'
            """)
            rohlik_routing = cur.fetchone()
            self.assertIsNotNone(rohlik_routing)
            self.assertTrue(rohlik_routing["is_enabled"])
            self.assertEqual(rohlik_routing["config"]["pilot_site"], "wien")

            # Check Amazon has analytics enabled
            cur.execute("""
                SELECT e.is_enabled
                FROM core.tenant_entitlements e
                JOIN core.tenants t ON e.tenant_id = t.id
                WHERE t.tenant_code = 'amazonlogistics' AND e.pack_id = 'analytics'
            """)
            amazon_analytics = cur.fetchone()
            self.assertIsNotNone(amazon_analytics)
            self.assertTrue(amazon_analytics["is_enabled"])


class TestCoreTenantRLS(unittest.TestCase):
    """
    Test RLS policies work correctly.
    """

    def setUp(self):
        """Set up database connection."""
        try:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(
                "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
                row_factory=dict_row
            )
            self.skip_tests = False

            # Get tenant IDs
            with self.conn.cursor() as cur:
                cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")
                cur.execute("SELECT id, tenant_code FROM core.tenants")
                tenants = cur.fetchall()
                self.tenant_ids = {t["tenant_code"]: str(t["id"]) for t in tenants}

        except Exception as e:
            print(f"Database connection failed: {e}")
            self.skip_tests = True

    def tearDown(self):
        """Close database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def test_tenant_isolation_tenants_table(self):
        """Test that tenant A cannot see tenant B in core.tenants."""
        if self.skip_tests:
            self.skipTest("Database not available")

        # Set context to Rohlik
        with self.conn.cursor() as cur:
            rohlik_id = self.tenant_ids["rohlik"]
            cur.execute("SELECT core.set_tenant_context(%s, NULL, FALSE)", (rohlik_id,))

            # Should only see own tenant
            cur.execute("SELECT tenant_code FROM core.tenants")
            tenants = cur.fetchall()

        self.assertEqual(len(tenants), 1, "Should only see own tenant")
        self.assertEqual(tenants[0]["tenant_code"], "rohlik")

    def test_tenant_isolation_sites_table(self):
        """Test that tenant A cannot see tenant B sites."""
        if self.skip_tests:
            self.skipTest("Database not available")

        # Set context to Rohlik
        with self.conn.cursor() as cur:
            rohlik_id = self.tenant_ids["rohlik"]
            cur.execute("SELECT core.set_tenant_context(%s, NULL, FALSE)", (rohlik_id,))

            # Should only see Rohlik sites
            cur.execute("SELECT site_code FROM core.sites ORDER BY site_code")
            sites = cur.fetchall()

        site_codes = [s["site_code"] for s in sites]
        self.assertEqual(len(sites), 4, "Should see exactly 4 Rohlik sites")
        self.assertIn("wien", site_codes)
        self.assertNotIn("berlin", site_codes)  # MediaMarkt site

    def test_platform_admin_sees_all(self):
        """Test that platform admin can see all tenants."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Set platform admin context
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("SELECT COUNT(*) as cnt FROM core.tenants")
            result = cur.fetchone()

        self.assertEqual(result["cnt"], 4, "Platform admin should see all 4 tenants")

    def test_platform_admin_can_modify(self):
        """Test that platform admin can insert into tenants."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Start transaction
            cur.execute("BEGIN")
            try:
                cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

                # Try to insert a test tenant
                cur.execute("""
                    INSERT INTO core.tenants (tenant_code, name)
                    VALUES ('test_tenant_rls', 'Test Tenant for RLS')
                    RETURNING id
                """)
                result = cur.fetchone()
                self.assertIsNotNone(result["id"])

            finally:
                # Rollback to not persist test data
                cur.execute("ROLLBACK")

    def test_regular_tenant_cannot_modify_others(self):
        """Test that regular tenant cannot modify other tenants."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Set context to Rohlik (not admin)
            rohlik_id = self.tenant_ids["rohlik"]
            cur.execute("SELECT core.set_tenant_context(%s, NULL, FALSE)", (rohlik_id,))

            # Try to insert - should fail due to RLS
            # (INSERT requires WITH CHECK policy to pass)
            try:
                cur.execute("BEGIN")
                cur.execute("""
                    INSERT INTO core.tenants (tenant_code, name)
                    VALUES ('hacker_tenant', 'Evil Tenant')
                """)
                # If we get here, RLS didn't block - that's a failure
                cur.execute("ROLLBACK")
                self.fail("Regular tenant should not be able to insert into tenants")
            except Exception as e:
                cur.execute("ROLLBACK")
                # Expected: RLS policy violation
                self.assertIn("row-level", str(e).lower())


class TestCoreTenantContextScoping(unittest.TestCase):
    """
    Test that tenant context is transaction-scoped.
    """

    def setUp(self):
        """Set up database connection."""
        try:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(
                "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
                row_factory=dict_row
            )
            self.skip_tests = False
        except Exception as e:
            print(f"Database connection failed: {e}")
            self.skip_tests = True

    def tearDown(self):
        """Close database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def test_context_clears_after_transaction(self):
        """Test that context is cleared after transaction ends."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Start transaction and set context
            cur.execute("BEGIN")
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Verify context is set
            cur.execute("SELECT core.app_is_platform_admin() as is_admin")
            result = cur.fetchone()
            self.assertTrue(result["is_admin"])

            # Commit transaction
            cur.execute("COMMIT")

            # Context should be cleared (will be empty string or null)
            cur.execute("SELECT core.app_is_platform_admin() as is_admin")
            result = cur.fetchone()
            # After commit, the SET LOCAL should be gone
            # Default is FALSE
            self.assertFalse(result["is_admin"])

    def test_helper_functions(self):
        """Test helper functions return correct values."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Get a tenant ID
            cur.execute("SELECT id FROM core.tenants WHERE tenant_code = 'rohlik'")
            rohlik = cur.fetchone()
            rohlik_id = str(rohlik["id"])

            # Get a site ID
            cur.execute("""
                SELECT id FROM core.sites
                WHERE tenant_id = %s AND site_code = 'wien'
            """, (rohlik_id,))
            wien = cur.fetchone()
            wien_id = str(wien["id"])

            # Now set context with tenant and site
            cur.execute("BEGIN")
            cur.execute(
                "SELECT core.set_tenant_context(%s, %s, FALSE)",
                (rohlik_id, wien_id)
            )

            # Verify helper functions
            cur.execute("SELECT core.app_current_tenant_id() as tid")
            result = cur.fetchone()
            self.assertEqual(str(result["tid"]), rohlik_id)

            cur.execute("SELECT core.app_current_site_id() as sid")
            result = cur.fetchone()
            self.assertEqual(str(result["sid"]), wien_id)

            cur.execute("SELECT core.app_is_platform_admin() as admin")
            result = cur.fetchone()
            self.assertFalse(result["admin"])

            cur.execute("ROLLBACK")


class TestHasEntitlementFunction(unittest.TestCase):
    """Test the core.has_entitlement() function."""

    def setUp(self):
        """Set up database connection."""
        try:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(
                "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
                row_factory=dict_row
            )
            self.skip_tests = False
        except Exception as e:
            print(f"Database connection failed: {e}")
            self.skip_tests = True

    def tearDown(self):
        """Close database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def test_rohlik_has_routing(self):
        """Test Rohlik has routing entitlement."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("SELECT id FROM core.tenants WHERE tenant_code = 'rohlik'")
            rohlik = cur.fetchone()

            cur.execute("SELECT core.has_entitlement(%s, 'routing')", (rohlik["id"],))
            result = cur.fetchone()
            self.assertTrue(result["has_entitlement"])

    def test_rohlik_no_analytics(self):
        """Test Rohlik does NOT have analytics entitlement."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("SELECT id FROM core.tenants WHERE tenant_code = 'rohlik'")
            rohlik = cur.fetchone()

            cur.execute("SELECT core.has_entitlement(%s, 'analytics')", (rohlik["id"],))
            result = cur.fetchone()
            self.assertFalse(result["has_entitlement"])

    def test_amazon_has_analytics(self):
        """Test Amazon has analytics entitlement."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("SELECT id FROM core.tenants WHERE tenant_code = 'amazonlogistics'")
            amazon = cur.fetchone()

            cur.execute("SELECT core.has_entitlement(%s, 'analytics')", (amazon["id"],))
            result = cur.fetchone()
            self.assertTrue(result["has_entitlement"])


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Core Tenants - RLS & Seed Validation Tests")
    print("=" * 70)
    print("\nPrerequisites:")
    print("  1. PostgreSQL running on localhost:5432")
    print("  2. Migrations 013 and 014 applied")
    print("")
    unittest.main(verbosity=2)
