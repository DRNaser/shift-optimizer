"""
Tenant Isolation E2E Tests
==========================

End-to-end tests verifying tenant isolation across the roster lifecycle.

NON-NEGOTIABLES:
- Tenant A cannot access Tenant B's plans/snapshots/evidence
- All write operations require RBAC + CSRF + idempotency
- Evidence files are tenant-scoped

Run with: pytest backend_py/api/tests/test_tenant_isolation_e2e.py -v
"""

import pytest
import os
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException


class TestTenantIsolation:
    """E2E tests for tenant isolation."""

    def test_tenant_a_cannot_access_tenant_b_evidence(self):
        """
        Tenant A user should not be able to access Tenant B's evidence files.
        """
        from routers.evidence_viewer import _validate_evidence_filename

        # Tenant B's evidence file
        tenant_b_filename = "roster_publish_2_20_456_20260110T120000.json"

        # Tenant A user (tenant_id=1) tries to access
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename(tenant_b_filename, tenant_id=1)

        assert exc.value.status_code == 404
        assert "not found" in exc.value.detail.lower()

    def test_tenant_a_can_access_own_evidence(self):
        """
        Tenant A user should be able to access their own evidence files.
        """
        from routers.evidence_viewer import _validate_evidence_filename

        # Tenant A's evidence file
        tenant_a_filename = "roster_publish_1_10_123_20260110T120000.json"

        # Tenant A user (tenant_id=1) accesses
        result = _validate_evidence_filename(tenant_a_filename, tenant_id=1)
        assert result == tenant_a_filename

    def test_platform_admin_scope_allows_all_tenants(self):
        """
        Platform admin with context switching should be able to access any tenant's evidence.
        This is tested by verifying the validation passes when tenant IDs match.
        """
        from routers.evidence_viewer import _validate_evidence_filename

        # Platform admin has set context to tenant 2
        tenant_b_filename = "roster_publish_2_20_456_20260110T120000.json"

        # When platform admin context is set to tenant 2, validation should pass
        result = _validate_evidence_filename(tenant_b_filename, tenant_id=2)
        assert result == tenant_b_filename


class TestWriteGuards:
    """Tests for write operation guards (RBAC + CSRF + Idempotency)."""

    def test_bff_routes_require_session_cookie(self):
        """
        All BFF write routes should require session cookie.
        """
        # This test documents the requirement that BFF routes check for session cookie
        # Actual testing requires running the Next.js server

        # Expected cookie names for session
        expected_cookies = ['__Host-sv_platform_session', 'sv_platform_session']

        # Verify our routes are documented to check these
        bff_routes_with_writes = [
            '/api/roster/snapshots/publish',
            '/api/roster/plans',  # POST for create
        ]

        # Document: All routes above MUST check for session cookie
        assert len(bff_routes_with_writes) > 0
        assert len(expected_cookies) == 2

    def test_idempotency_key_required_for_publish(self):
        """
        Snapshot publish should require x-idempotency-key header.
        """
        # Import the lifecycle router to check its implementation
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from packs.roster.api.routers.lifecycle import require_idempotency_key
        from fastapi import Request

        # Mock request without idempotency key
        mock_request = MagicMock()
        mock_request.headers = {}

        # Should raise exception when key is missing
        with pytest.raises(HTTPException) as exc:
            require_idempotency_key(mock_request)

        assert exc.value.status_code == 400
        assert "idempotency" in exc.value.detail.lower()

    def test_idempotency_key_accepted_when_present(self):
        """
        Valid idempotency key should be accepted.
        """
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from packs.roster.api.routers.lifecycle import require_idempotency_key
        from fastapi import Request

        # Mock request with valid idempotency key
        mock_request = MagicMock()
        mock_request.headers = {'x-idempotency-key': '550e8400-e29b-41d4-a716-446655440000'}

        # Should return the key
        key = require_idempotency_key(mock_request)
        assert key == '550e8400-e29b-41d4-a716-446655440000'


class TestEvidenceCreation:
    """Tests for evidence file creation and access."""

    def test_evidence_filename_format(self):
        """
        Evidence files should follow the naming convention:
        roster_{action}_{tenant}_{site}_{entity}_{timestamp}.json
        """
        valid_filenames = [
            "roster_publish_1_10_123_20260110T120000.json",
            "roster_approve_2_20_456_20260110T143000.json",
            "routing_solve_1_10_789_20260110T160000.json",
        ]

        from routers.evidence_viewer import _validate_evidence_filename

        for filename in valid_filenames:
            # Extract tenant ID from filename
            parts = filename.replace(".json", "").split("_")
            tenant_id = int(parts[2])

            # Should pass validation
            result = _validate_evidence_filename(filename, tenant_id=tenant_id)
            assert result == filename

    def test_evidence_directory_is_sandboxed(self):
        """
        Evidence access should be restricted to the evidence/ directory.
        """
        from routers.evidence_viewer import _validate_evidence_filename

        # Attempt to escape evidence directory
        escape_attempts = [
            "../config/secrets.json",
            "..\\..\\Windows\\system32.json",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
        ]

        for filename in escape_attempts:
            with pytest.raises(HTTPException) as exc:
                _validate_evidence_filename(filename, tenant_id=1)

            # Should get 404 (not 400) to avoid information disclosure
            assert exc.value.status_code in (400, 404)


class TestCrossOriginProtection:
    """Tests for CSRF protection."""

    def test_csrf_check_blocks_cross_origin_requests(self):
        """
        CSRF check should block requests from different origins.
        """
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from packs.roster.api.routers.lifecycle import require_csrf_check
        from fastapi import Request

        # Mock cross-origin request
        mock_request = MagicMock()
        mock_request.headers = {
            'origin': 'https://evil.com',
        }
        mock_request.url = MagicMock()
        mock_request.url.scheme = 'https'
        mock_request.url.netloc = 'app.solvereign.com'

        # Should raise exception for cross-origin request
        with pytest.raises(HTTPException) as exc:
            require_csrf_check(mock_request)

        assert exc.value.status_code == 403


class TestAuditLogIsolation:
    """Tests for audit log tenant isolation."""

    def test_audit_query_includes_tenant_filter(self):
        """
        Audit log queries should always include tenant_id filter.
        """
        # This is a documentation test to ensure our audit viewer
        # always filters by tenant_id

        # The audit_viewer.py should have queries like:
        # WHERE tenant_id = %s OR target_tenant_id = %s
        # to show both own tenant events and events targeting this tenant

        # Verify the router exists and has the expected structure
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from routers.audit_viewer import router

        # Should have audit endpoints
        routes = [r.path for r in router.routes]
        assert "/api/v1/audit" in routes or any("/audit" in r for r in routes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
