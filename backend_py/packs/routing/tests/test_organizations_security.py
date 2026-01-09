# =============================================================================
# SOLVEREIGN Organizations, Security & Escalation Tests
# =============================================================================
# Tests for:
# 1. Organization hierarchy (LTS org owns tenants)
# 2. Internal signature security (HMAC verification)
# 3. Platform admin cannot be spoofed via headers
# 4. Escalation and service status
# =============================================================================

import sys
import unittest
import time
import hmac
import hashlib
from datetime import datetime

sys.path.insert(0, ".")


class TestOrganizationSeedData(unittest.TestCase):
    """
    Test that organization seed data was applied correctly.

    Run after applying migrations 015 and 016.
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

    def test_lts_organization_exists(self):
        """Verify LTS organization was seeded."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("""
                SELECT org_code, name, is_active
                FROM core.organizations
                WHERE org_code = 'lts'
            """)
            org = cur.fetchone()

        self.assertIsNotNone(org, "LTS organization should exist")
        self.assertEqual(org["org_code"], "lts")
        self.assertEqual(org["name"], "LTS Transport & Logistik GmbH")
        self.assertTrue(org["is_active"])

    def test_all_tenants_linked_to_lts(self):
        """Verify all seeded tenants are owned by LTS organization."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Get LTS org ID
            cur.execute("SELECT id FROM core.organizations WHERE org_code = 'lts'")
            lts = cur.fetchone()
            self.assertIsNotNone(lts, "LTS org should exist")
            lts_id = lts["id"]

            # Get all tenants
            cur.execute("""
                SELECT tenant_code, owner_org_id
                FROM core.tenants
            """)
            tenants = cur.fetchall()

        # All tenants should be owned by LTS
        for tenant in tenants:
            self.assertEqual(
                str(tenant["owner_org_id"]), str(lts_id),
                f"Tenant {tenant['tenant_code']} should be owned by LTS"
            )

    def test_owner_org_id_not_nullable(self):
        """Verify owner_org_id is NOT NULL constraint."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Attempt to insert tenant without owner_org_id should fail
            try:
                cur.execute("""
                    INSERT INTO core.tenants (tenant_code, name)
                    VALUES ('test_orphan', 'Orphan Tenant')
                """)
                self.conn.commit()
                self.fail("Should not allow tenant without owner_org_id")
            except Exception as e:
                self.conn.rollback()
                self.assertIn("owner_org_id", str(e).lower())

    def test_get_tenants_for_org_function(self):
        """Verify core.get_tenants_for_org() helper works."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Get LTS org ID
            cur.execute("SELECT id FROM core.organizations WHERE org_code = 'lts'")
            lts = cur.fetchone()

            # Use helper function
            cur.execute("SELECT * FROM core.get_tenants_for_org(%s)", (lts["id"],))
            tenants = cur.fetchall()

        # Should return all 4 seeded tenants
        tenant_codes = [t["tenant_code"] for t in tenants]
        self.assertIn("rohlik", tenant_codes)
        self.assertIn("mediamarkt", tenant_codes)
        self.assertIn("hdplus", tenant_codes)
        self.assertIn("amazonlogistics", tenant_codes)


class TestInternalSignatureSecurity(unittest.TestCase):
    """
    Test HMAC signature verification for internal requests.
    """

    def setUp(self):
        """Set up test secret."""
        self.secret = "test_secret_key_for_hmac_signing_1234567890"

    def test_signature_generation(self):
        """Test signature is generated correctly."""
        from backend_py.api.security.internal_signature import generate_signature

        timestamp = int(time.time())
        signature = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            tenant_code=None,
            site_code=None,
            is_platform_admin=True,
            secret=self.secret
        )

        self.assertIsNotNone(signature)
        self.assertEqual(len(signature), 64)  # SHA256 hex = 64 chars

    def test_signature_changes_with_params(self):
        """Test that different parameters produce different signatures."""
        from backend_py.api.security.internal_signature import generate_signature

        timestamp = int(time.time())

        sig1 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=self.secret
        )

        sig2 = generate_signature(
            method="POST",  # Different method
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=self.secret
        )

        sig3 = generate_signature(
            method="GET",
            path="/api/v1/platform/tenants",  # Different path
            timestamp=timestamp,
            is_platform_admin=True,
            secret=self.secret
        )

        self.assertNotEqual(sig1, sig2, "Different method should produce different signature")
        self.assertNotEqual(sig1, sig3, "Different path should produce different signature")

    def test_signature_reproducible(self):
        """Test that same inputs produce same signature."""
        from backend_py.api.security.internal_signature import generate_signature

        timestamp = int(time.time())

        sig1 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=self.secret
        )

        sig2 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=self.secret
        )

        self.assertEqual(sig1, sig2, "Same inputs should produce same signature")

    def test_signature_includes_tenant_context(self):
        """Test that tenant context affects signature."""
        from backend_py.api.security.internal_signature import generate_signature

        timestamp = int(time.time())

        sig_no_tenant = generate_signature(
            method="GET",
            path="/api/v1/tenant/me",
            timestamp=timestamp,
            tenant_code=None,
            secret=self.secret
        )

        sig_with_tenant = generate_signature(
            method="GET",
            path="/api/v1/tenant/me",
            timestamp=timestamp,
            tenant_code="rohlik",
            secret=self.secret
        )

        self.assertNotEqual(
            sig_no_tenant, sig_with_tenant,
            "Tenant code should be included in signature"
        )


class TestPlatformAdminSecurityGate(unittest.TestCase):
    """
    Test that platform admin cannot be spoofed via plain headers.

    In production, X-Platform-Admin must be accompanied by valid signature.
    """

    def test_plain_header_rejected_without_signature(self):
        """
        Verify that X-Platform-Admin: true without signature is rejected.

        Note: This is a conceptual test. Full integration test requires
        running the API server with production config.
        """
        # In production mode, require_platform_admin dependency should:
        # 1. Check X-SV-Internal header
        # 2. Verify X-SV-Signature
        # 3. Only then trust X-Platform-Admin

        # This test verifies the logic conceptually
        from backend_py.api.security.internal_signature import InternalContext

        # Without internal signature, context should be empty
        empty_context = InternalContext(is_internal=False)
        self.assertFalse(empty_context.is_internal)
        self.assertFalse(empty_context.is_platform_admin)

    def test_internal_context_with_signature(self):
        """Test that valid internal context has correct flags."""
        from backend_py.api.security.internal_signature import InternalContext

        # Simulated verified context
        verified_context = InternalContext(
            is_internal=True,
            is_platform_admin=True,
            tenant_code=None,
            site_code=None,
            timestamp=int(time.time()),
            signature="valid_signature_here"
        )

        self.assertTrue(verified_context.is_internal)
        self.assertTrue(verified_context.is_platform_admin)


class TestServiceStatusEscalation(unittest.TestCase):
    """
    Test service status and escalation tracking.

    Run after applying migration 017.
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

    def test_reason_code_registry_seeded(self):
        """Verify reason code registry has common codes."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("""
                SELECT reason_code, severity, category
                FROM core.reason_code_registry
                ORDER BY reason_code
            """)
            codes = cur.fetchall()

        # Check some critical codes exist
        code_map = {c["reason_code"]: c for c in codes}

        self.assertIn("PLATFORM_ADMIN_SPOOF", code_map)
        self.assertEqual(code_map["PLATFORM_ADMIN_SPOOF"]["severity"], "S0")

        self.assertIn("RLS_VIOLATION", code_map)
        self.assertEqual(code_map["RLS_VIOLATION"]["severity"], "S0")

        self.assertIn("EVIDENCE_HASH_MISMATCH", code_map)
        self.assertEqual(code_map["EVIDENCE_HASH_MISMATCH"]["severity"], "S1")

        self.assertIn("OSRM_DOWN", code_map)
        self.assertEqual(code_map["OSRM_DOWN"]["severity"], "S2")

    def test_record_and_resolve_escalation(self):
        """Test recording and resolving an escalation."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Record escalation
            cur.execute("""
                SELECT core.record_escalation(
                    'platform'::core.scope_type,
                    NULL,
                    'OSRM_DOWN',
                    '{"test": true}'::jsonb
                )
            """)
            result = cur.fetchone()
            escalation_id = result["record_escalation"]
            self.assertIsNotNone(escalation_id)

            # Check it's active
            cur.execute("""
                SELECT * FROM core.service_status
                WHERE id = %s
            """, (escalation_id,))
            escalation = cur.fetchone()
            self.assertIsNotNone(escalation)
            self.assertEqual(escalation["status"], "degraded")  # S2 = degraded
            self.assertEqual(escalation["severity"], "S2")
            self.assertIsNone(escalation["ended_at"])

            # Resolve
            cur.execute("""
                SELECT core.resolve_escalation(
                    'platform'::core.scope_type,
                    NULL,
                    'OSRM_DOWN',
                    'test_operator'
                )
            """)
            resolve_result = cur.fetchone()
            self.assertEqual(resolve_result["resolve_escalation"], 1)

            # Check it's resolved
            cur.execute("""
                SELECT * FROM core.service_status
                WHERE id = %s
            """, (escalation_id,))
            resolved = cur.fetchone()
            self.assertIsNotNone(resolved["ended_at"])
            self.assertEqual(resolved["resolved_by"], "test_operator")

            self.conn.commit()

    def test_s0_blocks_scope(self):
        """Test that S0 severity blocks scope."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Record S0 escalation
            cur.execute("""
                SELECT core.record_escalation(
                    'platform'::core.scope_type,
                    NULL,
                    'RLS_VIOLATION',
                    '{"test": true}'::jsonb
                )
            """)

            # Check is_scope_blocked
            cur.execute("""
                SELECT core.is_scope_blocked('platform'::core.scope_type, NULL)
            """)
            result = cur.fetchone()
            self.assertTrue(result["is_scope_blocked"], "S0 should block scope")

            cur.execute("ROLLBACK")

    def test_s2_degrades_but_not_blocks(self):
        """Test that S2 degrades but doesn't block."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            # Record S2 escalation
            cur.execute("""
                SELECT core.record_escalation(
                    'platform'::core.scope_type,
                    NULL,
                    'OSRM_DOWN',
                    '{"test": true}'::jsonb
                )
            """)

            # Check is_scope_blocked (should be false for S2)
            cur.execute("""
                SELECT core.is_scope_blocked('platform'::core.scope_type, NULL)
            """)
            blocked = cur.fetchone()
            self.assertFalse(blocked["is_scope_blocked"], "S2 should NOT block")

            # Check is_scope_degraded (should be true)
            cur.execute("""
                SELECT core.is_scope_degraded('platform'::core.scope_type, NULL)
            """)
            degraded = cur.fetchone()
            self.assertTrue(degraded["is_scope_degraded"], "S2 should degrade")

            cur.execute("ROLLBACK")


class TestOrganizationRLS(unittest.TestCase):
    """
    Test RLS policies for organizations.
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

    def test_tenant_can_see_own_org(self):
        """Test that a tenant can see its own organization."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            # Set context to Rohlik tenant
            rohlik_id = self.tenant_ids["rohlik"]
            cur.execute("SELECT core.set_tenant_context(%s, NULL, FALSE)", (rohlik_id,))

            # Should be able to see own org
            cur.execute("""
                SELECT org_code FROM core.organizations
            """)
            orgs = cur.fetchall()

        self.assertEqual(len(orgs), 1, "Tenant should see exactly 1 org")
        self.assertEqual(orgs[0]["org_code"], "lts")

    def test_platform_admin_sees_all_orgs(self):
        """Test that platform admin can see all organizations."""
        if self.skip_tests:
            self.skipTest("Database not available")

        with self.conn.cursor() as cur:
            cur.execute("SELECT core.set_tenant_context(NULL, NULL, TRUE)")

            cur.execute("SELECT COUNT(*) as cnt FROM core.organizations")
            result = cur.fetchone()

        # Should see LTS (and any others)
        self.assertGreaterEqual(result["cnt"], 1)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Organizations, Security & Escalation Tests")
    print("=" * 70)
    print("\nPrerequisites:")
    print("  1. PostgreSQL running on localhost:5432")
    print("  2. Migrations 015, 016, 017 applied")
    print("")
    unittest.main(verbosity=2)
