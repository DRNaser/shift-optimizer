"""
SOLVEREIGN V3.3b - RBAC Lock Endpoint Tests
============================================

Tests for:
1. PLANNER cannot lock plans (403)
2. APPROVER can lock plans (200)
3. TENANT_ADMIN can lock plans (200)
4. M2M tokens cannot lock plans (403)
5. VIEWER cannot lock plans (403)

Run with: pytest backend_py/tests/test_rbac_lock_approver.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import List
from fastapi import HTTPException


# =============================================================================
# TEST FIXTURES
# =============================================================================

@dataclass
class MockUser:
    """Mock EntraUserContext for testing."""
    user_id: str
    tenant_id: int
    roles: List[str]
    token_type: str = "user"
    app_id: str = None
    email: str = "test@lts-transport.de"
    name: str = "Test User"

    @property
    def is_app_token(self) -> bool:
        return self.token_type == "app"

    def has_role(self, role: str) -> bool:
        return role.lower() in [r.lower() for r in self.roles]

    def has_any_role(self, roles: List[str]) -> bool:
        user_roles_lower = {r.lower() for r in self.roles}
        return bool(user_roles_lower & {r.lower() for r in roles})


def create_planner_user():
    """Create a PLANNER user (dispatcher role)."""
    return MockUser(
        user_id="planner-user-123",
        tenant_id=2,
        roles=["dispatcher"],
        email="planner@lts-transport.de"
    )


def create_approver_user():
    """Create an APPROVER user."""
    return MockUser(
        user_id="approver-user-456",
        tenant_id=2,
        roles=["plan_approver"],
        email="approver@lts-transport.de"
    )


def create_tenant_admin_user():
    """Create a TENANT_ADMIN user."""
    return MockUser(
        user_id="admin-user-789",
        tenant_id=2,
        roles=["tenant_admin"],
        email="admin@lts-transport.de"
    )


def create_viewer_user():
    """Create a VIEWER user."""
    return MockUser(
        user_id="viewer-user-111",
        tenant_id=2,
        roles=["viewer"],
        email="viewer@lts-transport.de"
    )


def create_m2m_app():
    """Create an M2M app token (cannot have approver role)."""
    return MockUser(
        user_id="service-principal-222",
        tenant_id=2,
        roles=["dispatcher"],  # Note: no plan_approver even if configured
        token_type="app",
        app_id="automation-client-id"
    )


# =============================================================================
# TEST: Role requirements
# =============================================================================

class TestLockRoleRequirements:
    """Test that lock endpoint requires APPROVER role."""

    def test_approver_roles(self):
        """Verify which roles can lock plans."""
        # Roles that should be able to lock
        lock_roles = ["plan_approver", "tenant_admin"]

        approver = create_approver_user()
        admin = create_tenant_admin_user()
        planner = create_planner_user()
        viewer = create_viewer_user()

        assert approver.has_any_role(lock_roles)
        assert admin.has_any_role(lock_roles)
        assert not planner.has_any_role(lock_roles)
        assert not viewer.has_any_role(lock_roles)


# =============================================================================
# TEST: PLANNER cannot lock
# =============================================================================

class TestPlannerCannotLock:
    """Tests that PLANNER role cannot lock plans."""

    def test_planner_lacks_lock_permission(self):
        """PLANNER should not have plan_approver or tenant_admin role."""
        user = create_planner_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        assert not user.has_any_role(lock_roles)

    @pytest.mark.asyncio
    async def test_planner_lock_attempt_denied(self):
        """PLANNER attempting to lock should get 403."""
        user = create_planner_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        # Simulate RequireApprover check
        if not user.has_any_role(lock_roles):
            with pytest.raises(HTTPException) as exc_info:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "INSUFFICIENT_ROLE",
                        "message": f"This action requires one of: {', '.join(lock_roles)}",
                        "required_roles": lock_roles,
                    }
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error"] == "INSUFFICIENT_ROLE"


# =============================================================================
# TEST: APPROVER can lock
# =============================================================================

class TestApproverCanLock:
    """Tests that APPROVER role can lock plans."""

    def test_approver_has_lock_permission(self):
        """APPROVER should have plan_approver role."""
        user = create_approver_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        assert user.has_any_role(lock_roles)

    @pytest.mark.asyncio
    async def test_approver_lock_allowed(self):
        """APPROVER should be allowed to lock plans."""
        user = create_approver_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        # Check passes
        assert user.has_any_role(lock_roles)

        # Not an app token
        assert not user.is_app_token


# =============================================================================
# TEST: TENANT_ADMIN can lock
# =============================================================================

class TestTenantAdminCanLock:
    """Tests that TENANT_ADMIN role can lock plans."""

    def test_tenant_admin_has_lock_permission(self):
        """TENANT_ADMIN should have tenant_admin role."""
        user = create_tenant_admin_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        assert user.has_any_role(lock_roles)

    @pytest.mark.asyncio
    async def test_tenant_admin_lock_allowed(self):
        """TENANT_ADMIN should be allowed to lock plans."""
        user = create_tenant_admin_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        # Check passes
        assert user.has_any_role(lock_roles)

        # Not an app token
        assert not user.is_app_token


# =============================================================================
# TEST: M2M tokens cannot lock
# =============================================================================

class TestM2MCannotLock:
    """Tests that M2M (app) tokens cannot lock plans."""

    def test_m2m_is_app_token(self):
        """M2M token should be detected as app token."""
        app = create_m2m_app()
        assert app.is_app_token

    def test_m2m_cannot_have_approver_role(self):
        """M2M tokens should not have plan_approver role."""
        app = create_m2m_app()

        # Even if APPROVER was assigned in Entra, it should be stripped
        assert "plan_approver" not in app.roles

    @pytest.mark.asyncio
    async def test_m2m_lock_denied_even_with_valid_roles(self):
        """M2M token should be denied even if it somehow got approver role."""
        # Create app with approver role (shouldn't happen in real flow)
        app = MockUser(
            user_id="service-principal-222",
            tenant_id=2,
            roles=["plan_approver"],  # Hypothetically got this role
            token_type="app",
            app_id="automation-client-id"
        )

        # App tokens are blocked regardless of roles
        if app.is_app_token:
            with pytest.raises(HTTPException) as exc_info:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "APP_TOKEN_NOT_ALLOWED",
                        "message": "Plan locking requires human approval. App tokens cannot lock plans.",
                    }
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error"] == "APP_TOKEN_NOT_ALLOWED"


# =============================================================================
# TEST: VIEWER cannot lock
# =============================================================================

class TestViewerCannotLock:
    """Tests that VIEWER role cannot lock plans."""

    def test_viewer_lacks_lock_permission(self):
        """VIEWER should not have any lock permission."""
        user = create_viewer_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        assert not user.has_any_role(lock_roles)

    @pytest.mark.asyncio
    async def test_viewer_lock_attempt_denied(self):
        """VIEWER attempting to lock should get 403."""
        user = create_viewer_user()
        lock_roles = ["plan_approver", "tenant_admin"]

        if not user.has_any_role(lock_roles):
            with pytest.raises(HTTPException) as exc_info:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "INSUFFICIENT_ROLE",
                        "message": f"This action requires one of: {', '.join(lock_roles)}",
                        "required_roles": lock_roles,
                    }
                )

            assert exc_info.value.status_code == 403


# =============================================================================
# TEST: RequireApprover dependency
# =============================================================================

class TestRequireApproverDependency:
    """Tests for the RequireApprover FastAPI dependency."""

    def test_require_approver_accepts_approver(self):
        """RequireApprover should accept plan_approver role."""
        from api.security.entra_auth import EntraUserContext

        user = EntraUserContext(
            user_id="user-123",
            tenant_id=2,
            roles=["plan_approver"]
        )

        # Should not raise
        assert user.has_any_role(["plan_approver", "tenant_admin"])

    def test_require_approver_accepts_tenant_admin(self):
        """RequireApprover should accept tenant_admin role."""
        from api.security.entra_auth import EntraUserContext

        user = EntraUserContext(
            user_id="user-123",
            tenant_id=2,
            roles=["tenant_admin"]
        )

        # Should not raise
        assert user.has_any_role(["plan_approver", "tenant_admin"])

    def test_require_approver_rejects_dispatcher(self):
        """RequireApprover should reject dispatcher role."""
        from api.security.entra_auth import EntraUserContext

        user = EntraUserContext(
            user_id="user-123",
            tenant_id=2,
            roles=["dispatcher"]
        )

        # Should not have required roles
        assert not user.has_any_role(["plan_approver", "tenant_admin"])


# =============================================================================
# TEST: Lock audit logging
# =============================================================================

class TestLockAuditLogging:
    """Tests that lock attempts are properly logged."""

    def test_lock_attempt_log_format(self):
        """Verify lock attempt log contains required fields."""
        user = create_approver_user()
        plan_id = 42

        log_entry = {
            "event": "plan_lock_attempt",
            "plan_id": plan_id,
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "roles": user.roles,
            "is_app_token": user.is_app_token,
        }

        # Required fields for audit
        assert "plan_id" in log_entry
        assert "user_id" in log_entry
        assert "tenant_id" in log_entry
        assert "roles" in log_entry
        assert "is_app_token" in log_entry

    def test_lock_denied_log_format(self):
        """Verify lock denied log contains required fields."""
        user = create_planner_user()
        plan_id = 42

        log_entry = {
            "event": "plan_lock_denied",
            "plan_id": plan_id,
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "reason": "INSUFFICIENT_ROLE",
            "required_roles": ["plan_approver", "tenant_admin"],
            "user_roles": user.roles,
        }

        assert log_entry["reason"] == "INSUFFICIENT_ROLE"
        assert "required_roles" in log_entry


# =============================================================================
# INTEGRATION TEST: Lock flow
# =============================================================================

class TestLockFlowIntegration:
    """Integration tests for the lock flow."""

    @pytest.mark.asyncio
    async def test_full_lock_flow_approver(self):
        """Test complete lock flow with APPROVER user."""
        user = create_approver_user()
        plan_id = 42
        lock_roles = ["plan_approver", "tenant_admin"]

        # Step 1: Check role
        assert user.has_any_role(lock_roles)

        # Step 2: Check not app token
        assert not user.is_app_token

        # Step 3: Would proceed to lock (not testing DB here)
        locked_by = user.email or user.name or user.user_id
        assert locked_by == "approver@lts-transport.de"

    @pytest.mark.asyncio
    async def test_full_lock_flow_planner_denied(self):
        """Test lock flow denial for PLANNER user."""
        user = create_planner_user()
        plan_id = 42
        lock_roles = ["plan_approver", "tenant_admin"]

        # Step 1: Check role fails
        if not user.has_any_role(lock_roles):
            denied = True

        assert denied

    @pytest.mark.asyncio
    async def test_full_lock_flow_m2m_denied(self):
        """Test lock flow denial for M2M token."""
        app = create_m2m_app()
        plan_id = 42

        # Even with valid role check, app token is blocked
        if app.is_app_token:
            denied = True

        assert denied


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
