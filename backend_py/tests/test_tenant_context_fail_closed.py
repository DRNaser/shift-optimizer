"""
Test: Dual Tenant Context Fail-Closed Behavior (P0 Fix - Migration 061)

This test verifies that the dual tenant context system fails closed
when context is not properly set.

CRITICAL SECURITY TEST:
- RLS MUST deny access when tenant context is missing
- Should raise exception, NOT return empty results
"""

import os
import pytest
import psycopg
from psycopg import errors as pg_errors

# Get database URL from environment
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://solvereign:solvereign@localhost:5432/solvereign"
)


class TestDualTenantContextFailClosed:
    """Test suite for dual tenant context fail-closed behavior."""

    @pytest.fixture
    def db_connection(self):
        """Create a fresh database connection without tenant context."""
        conn = psycopg.connect(DATABASE_URL, autocommit=False)
        yield conn
        conn.rollback()
        conn.close()

    def test_current_tenant_id_int_fails_without_context(self, db_connection):
        """
        CRITICAL: auth.current_tenant_id_int() must RAISE when context not set.

        This is a P0 security requirement - silent failures would bypass RLS.
        """
        with db_connection.cursor() as cur:
            # Ensure context is NOT set
            cur.execute("SELECT set_config('app.current_tenant_id_int', '', true)")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true)")

            # Calling fail-closed function MUST raise exception
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute("SELECT auth.current_tenant_id_int()")

            # Verify error message indicates RLS violation
            error_msg = str(exc_info.value)
            assert "RLS VIOLATION" in error_msg or "insufficient_privilege" in error_msg, \
                f"Expected RLS violation error, got: {error_msg}"

    def test_current_tenant_id_uuid_fails_without_context(self, db_connection):
        """
        CRITICAL: auth.current_tenant_id_uuid() must RAISE when context not set.
        """
        with db_connection.cursor() as cur:
            # Ensure UUID context is NOT set
            cur.execute("SELECT set_config('app.current_tenant_id_uuid', '', true)")

            # Calling fail-closed function MUST raise exception
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute("SELECT auth.current_tenant_id_uuid()")

            # Verify error message indicates RLS violation
            error_msg = str(exc_info.value)
            assert "RLS VIOLATION" in error_msg or "insufficient_privilege" in error_msg, \
                f"Expected RLS violation error, got: {error_msg}"

    def test_permissive_variant_returns_null(self, db_connection):
        """
        Permissive variant should return NULL (not raise) when context not set.
        Used for platform admin scenarios.
        """
        with db_connection.cursor() as cur:
            # Clear all context
            cur.execute("SELECT set_config('app.current_tenant_id_int', '', true)")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true)")
            cur.execute("SELECT set_config('app.current_tenant_id_uuid', '', true)")

            # Permissive INT variant should return NULL
            cur.execute("SELECT auth.current_tenant_id_int_or_null()")
            result = cur.fetchone()[0]
            assert result is None, f"Expected NULL, got: {result}"

            # Permissive UUID variant should return NULL
            cur.execute("SELECT auth.current_tenant_id_uuid_or_null()")
            result = cur.fetchone()[0]
            assert result is None, f"Expected NULL, got: {result}"

    def test_dual_context_setter_sets_both(self, db_connection):
        """
        auth.set_dual_tenant_context() must set BOTH INT and legacy variables.
        """
        with db_connection.cursor() as cur:
            # Set context via dual setter
            cur.execute("SELECT auth.set_dual_tenant_context(42, NULL, FALSE)")

            # Verify INT context is set
            cur.execute("SELECT auth.current_tenant_id_int()")
            int_result = cur.fetchone()[0]
            assert int_result == 42, f"Expected INT 42, got: {int_result}"

            # Verify legacy variable is also set (for backward compat)
            cur.execute("SELECT current_setting('app.current_tenant_id', true)")
            legacy_result = cur.fetchone()[0]
            assert legacy_result == '42', f"Expected legacy '42', got: {legacy_result}"

    def test_dual_context_setter_handles_null(self, db_connection):
        """
        Platform admin scenario: NULL tenant should clear context.
        """
        with db_connection.cursor() as cur:
            # Set to a value first
            cur.execute("SELECT auth.set_dual_tenant_context(1, NULL, FALSE)")

            # Then set to NULL (platform admin)
            cur.execute("SELECT auth.set_dual_tenant_context(NULL, NULL, TRUE)")

            # INT context should now be empty
            cur.execute("SELECT current_setting('app.current_tenant_id_int', true)")
            int_val = cur.fetchone()[0]
            assert int_val == '', f"Expected empty string, got: {int_val}"

            # Platform admin flag should be set
            cur.execute("SELECT current_setting('app.is_platform_admin', true)")
            admin_flag = cur.fetchone()[0]
            assert admin_flag == 'true', f"Expected 'true', got: {admin_flag}"

    def test_invalid_int_raises_error(self, db_connection):
        """
        Setting non-integer value should cause fail-closed function to raise.
        """
        with db_connection.cursor() as cur:
            # Set invalid INT value
            cur.execute("SELECT set_config('app.current_tenant_id_int', 'not-an-int', true)")
            cur.execute("SELECT set_config('app.current_tenant_id', 'not-an-int', true)")

            # Fail-closed function should raise on invalid value
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute("SELECT auth.current_tenant_id_int()")

            error_msg = str(exc_info.value)
            assert "not a valid INTEGER" in error_msg or "data_exception" in error_msg, \
                f"Expected data exception error, got: {error_msg}"

    def test_invalid_uuid_raises_error(self, db_connection):
        """
        Setting non-UUID value should cause fail-closed function to raise.
        """
        with db_connection.cursor() as cur:
            # Set invalid UUID value
            cur.execute("SELECT set_config('app.current_tenant_id_uuid', 'not-a-uuid', true)")

            # Fail-closed function should raise on invalid value
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute("SELECT auth.current_tenant_id_uuid()")

            error_msg = str(exc_info.value)
            assert "not a valid UUID" in error_msg or "data_exception" in error_msg, \
                f"Expected data exception error, got: {error_msg}"


class TestVerifyTenantContextConsistency:
    """Test the verify gate function."""

    @pytest.fixture
    def db_connection(self):
        """Create database connection."""
        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        yield conn
        conn.close()

    def test_verify_gate_runs_without_error(self, db_connection):
        """
        auth.verify_tenant_context_consistency() should run without exceptions.
        """
        with db_connection.cursor() as cur:
            cur.execute("SELECT * FROM auth.verify_tenant_context_consistency()")
            results = cur.fetchall()

            # Should return multiple checks
            assert len(results) >= 4, f"Expected at least 4 checks, got: {len(results)}"

            # All checks should be PASS or WARN (not FAIL for properly configured DB)
            for check_name, status, details in results:
                assert status in ('PASS', 'WARN'), \
                    f"Check '{check_name}' has status '{status}': {details}"

    def test_verify_pass_gate_includes_new_gate(self, db_connection):
        """
        verify_pass_gate() should include the new tenant context gate.
        """
        with db_connection.cursor() as cur:
            cur.execute("SELECT gate_name FROM verify_pass_gate()")
            gate_names = [row[0] for row in cur.fetchall()]

            assert 'auth.verify_tenant_context_consistency' in gate_names, \
                f"New gate not found in verify_pass_gate. Gates: {gate_names}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
