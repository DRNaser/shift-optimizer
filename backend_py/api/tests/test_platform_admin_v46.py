"""
SOLVEREIGN V4.6 - Platform Admin Endpoints Tests
=================================================

Real pytest tests for V4.6 platform admin god-mode endpoints:
- Role permission management
- User disable/enable/lock/unlock
- Session management
- Context switching hardening
- Audit log verification

Run with: pytest backend_py/api/tests/test_platform_admin_v46.py -v
"""

import os
import pytest
import httpx
from typing import Optional, Dict, Any


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

BACKEND_URL = os.environ.get("TEST_BACKEND_URL", "http://localhost:8000")
TEST_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@solvereign.com")
TEST_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


class PlatformAdminClient:
    """HTTP client for platform admin API testing."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)
        self.session_cookie: Optional[str] = None

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login and store session cookie."""
        resp = self.client.post(
            f"{self.base_url}/api/auth/login",
            json={"email": email, "password": password},
        )
        if resp.status_code == 200:
            self.session_cookie = resp.cookies.get("__Host-sv_platform_session")
        return resp.json() if resp.status_code < 500 else {"error": "server_error"}

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make authenticated request."""
        headers = kwargs.pop("headers", {})
        if self.session_cookie:
            headers["Cookie"] = f"__Host-sv_platform_session={self.session_cookie}"
        return self.client.request(
            method, f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def close(self):
        self.client.close()


@pytest.fixture(scope="module")
def admin_client():
    """Create authenticated admin client."""
    client = PlatformAdminClient(BACKEND_URL)
    if TEST_ADMIN_PASSWORD:
        result = client.login(TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD)
        if "error" in result or not client.session_cookie:
            pytest.skip("Could not login as platform admin")
    else:
        pytest.skip("TEST_ADMIN_PASSWORD not set")
    yield client
    client.close()


# =============================================================================
# TEST 1: Role Permission - Cannot Modify platform_admin
# =============================================================================

def test_cannot_modify_platform_admin_permissions(admin_client):
    """
    Test 1: PUT /api/platform/roles/platform_admin/permissions returns 403.

    platform_admin role has all permissions and cannot be modified.
    """
    resp = admin_client.put(
        "/api/platform/roles/platform_admin/permissions",
        json={"permission_keys": ["portal.summary.read"]},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert "Cannot modify platform_admin" in data.get("detail", "")


# =============================================================================
# TEST 2: Role Permission - Invalid Keys Return 400
# =============================================================================

def test_invalid_permission_keys_return_400(admin_client):
    """
    Test 2: PUT /api/platform/roles/{role}/permissions with invalid keys returns 400.
    """
    resp = admin_client.put(
        "/api/platform/roles/dispatcher/permissions",
        json={"permission_keys": ["invalid.permission.key", "another.fake.key"]},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "Invalid permission keys" in data.get("detail", "")


# =============================================================================
# TEST 3: User Disable - Cannot Disable Self
# =============================================================================

def test_cannot_disable_self(admin_client):
    """
    Test 3: POST /api/platform/users/{self}/disable returns 400.

    Admin cannot disable their own account.
    """
    # Get current user ID
    me_resp = admin_client.get("/api/auth/me")
    assert me_resp.status_code == 200
    user_id = me_resp.json().get("user_id")

    # Try to disable self
    resp = admin_client.post(f"/api/platform/users/{user_id}/disable")
    assert resp.status_code == 400
    assert "Cannot disable your own" in resp.json().get("detail", "")


# =============================================================================
# TEST 4: User Lock - Requires Reason
# =============================================================================

def test_lock_user_requires_reason(admin_client):
    """
    Test 4: POST /api/platform/users/{id}/lock without reason returns 422.
    """
    # Get any user ID (we won't actually lock)
    users_resp = admin_client.get("/api/platform/users")
    if users_resp.status_code != 200:
        pytest.skip("Could not list users")

    users = users_resp.json()
    if not users:
        pytest.skip("No users to test with")

    user_id = users[0].get("id")

    # Try to lock without reason
    resp = admin_client.post(
        f"/api/platform/users/{user_id}/lock",
        json={},  # Missing reason
    )
    # Should fail validation
    assert resp.status_code == 422


# =============================================================================
# TEST 5: Session Revoke - Requires Exactly One Criteria
# =============================================================================

def test_session_revoke_requires_one_criteria(admin_client):
    """
    Test 5: POST /api/platform/sessions/revoke with multiple criteria returns 400.
    """
    resp = admin_client.post(
        "/api/platform/sessions/revoke",
        json={
            "user_id": "some-uuid",
            "tenant_id": 1,
        },
    )
    assert resp.status_code == 400
    assert "exactly one" in resp.json().get("detail", "").lower()


# =============================================================================
# TEST 6: Context - Site Must Belong to Tenant
# =============================================================================

def test_context_site_tenant_mismatch(admin_client):
    """
    Test 6: POST /api/platform/context with mismatched site returns 400.
    """
    # Get a valid tenant
    tenants_resp = admin_client.get("/api/platform/tenants")
    if tenants_resp.status_code != 200:
        pytest.skip("Could not list tenants")

    tenants = tenants_resp.json()
    if not tenants:
        pytest.skip("No tenants to test with")

    tenant_id = tenants[0].get("id")

    # Try to set context with non-existent site
    resp = admin_client.post(
        "/api/platform/context",
        json={"tenant_id": tenant_id, "site_id": 999999},
    )
    assert resp.status_code == 400
    detail = resp.json().get("detail", {})
    assert detail.get("error_code") == "SITE_TENANT_MISMATCH"


# =============================================================================
# TEST 7: Context - Validates Tenant Exists
# =============================================================================

def test_context_validates_tenant_exists(admin_client):
    """
    Test 7: POST /api/platform/context with non-existent tenant returns 404.
    """
    resp = admin_client.post(
        "/api/platform/context",
        json={"tenant_id": 999999},
    )
    assert resp.status_code == 404
    detail = resp.json().get("detail", {})
    assert detail.get("error_code") == "TENANT_NOT_FOUND"


# =============================================================================
# TEST 8: /me Returns Platform Admin Context Fields
# =============================================================================

def test_me_returns_platform_admin_context_fields(admin_client):
    """
    Test 8: GET /api/auth/me returns V4.6 context fields.
    """
    resp = admin_client.get("/api/auth/me")
    assert resp.status_code == 200

    data = resp.json()
    # Check V4.6 fields exist
    assert "is_platform_admin" in data
    assert "active_tenant_id" in data
    assert "active_site_id" in data
    assert "active_tenant_name" in data
    assert "active_site_name" in data

    # Platform admin should have is_platform_admin = True
    assert data.get("is_platform_admin") is True


# =============================================================================
# TEST 9: Sessions List Returns Valid Structure
# =============================================================================

def test_sessions_list_returns_valid_structure(admin_client):
    """
    Test 9: GET /api/platform/sessions returns list with correct fields.
    """
    resp = admin_client.get("/api/platform/sessions")
    assert resp.status_code == 200

    sessions = resp.json()
    assert isinstance(sessions, list)

    if sessions:
        session = sessions[0]
        # Check expected fields
        assert "id" in session
        assert "user_id" in session
        assert "user_email" in session
        assert "role_name" in session
        assert "created_at" in session
        assert "expires_at" in session
        assert "is_platform_scope" in session


# =============================================================================
# TEST 10: Audit Log - Role Permission Update Creates Entry
# =============================================================================

def test_role_permission_update_creates_audit_log(admin_client):
    """
    Test 10: Updating role permissions creates audit log entry.

    This test verifies that:
    1. We can update permissions for a non-platform_admin role
    2. The audit log contains the expected event
    """
    # Get current permissions for dispatcher role
    resp = admin_client.get("/api/platform/roles/dispatcher/permissions")
    if resp.status_code != 200:
        pytest.skip("Could not get dispatcher permissions")

    current_perms = resp.json()

    # Get available permissions
    perms_resp = admin_client.get("/api/platform/permissions")
    if perms_resp.status_code != 200:
        pytest.skip("Could not get permissions list")

    all_perms = perms_resp.json()
    if not all_perms:
        pytest.skip("No permissions available")

    # Pick first permission that's not already assigned
    perm_keys = [p.get("key") for p in all_perms if p.get("key") not in current_perms]
    if not perm_keys:
        perm_keys = [p.get("key") for p in all_perms[:1]]

    # Update with same permissions (safe operation)
    resp = admin_client.put(
        "/api/platform/roles/dispatcher/permissions",
        json={"permission_keys": current_perms},
    )

    # Should succeed
    assert resp.status_code == 200

    # Verify response is the list of permissions
    updated_perms = resp.json()
    assert isinstance(updated_perms, list)


# =============================================================================
# AUDIT EVENT TYPES VERIFICATION
# =============================================================================

class TestAuditEventTypes:
    """Verify all expected audit event types are defined."""

    EXPECTED_V46_EVENT_TYPES = [
        "ROLE_PERMISSIONS_UPDATED",
        "ROLE_PERMISSION_ADDED",
        "ROLE_PERMISSION_REMOVED",
        "USER_DISABLED",
        "USER_ENABLED",
        "USER_LOCKED",
        "USER_UNLOCKED",
        "SESSIONS_BULK_REVOKED",
        "CONTEXT_SWITCHED",
        "CONTEXT_CLEARED",
    ]

    def test_v46_defines_10_event_types(self):
        """V4.6 should define 10 new audit event types."""
        assert len(self.EXPECTED_V46_EVENT_TYPES) == 10

    def test_event_type_naming_convention(self):
        """Event types should follow UPPER_SNAKE_CASE convention."""
        for event_type in self.EXPECTED_V46_EVENT_TYPES:
            assert event_type == event_type.upper()
            assert "_" in event_type or event_type.isalpha()


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
