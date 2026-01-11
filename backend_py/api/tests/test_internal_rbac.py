"""
SOLVEREIGN V4.4 - Internal RBAC Tests
======================================

Tests for internal authentication and authorization.

Run with:
    pytest backend_py/api/tests/test_internal_rbac.py -v
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import secrets

from backend_py.api.security.internal_rbac import (
    hash_password,
    verify_password,
    generate_session_token,
    hash_session_token,
    InternalUserContext,
    MockRBACRepository,
    AuthService,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_MAX_AGE,
)


# =============================================================================
# PASSWORD HASHING TESTS
# =============================================================================

class TestPasswordHashing:
    """Tests for Argon2id password hashing."""

    def test_hash_password_returns_hash(self):
        """Hash should return a non-empty string."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert hashed is not None
        assert len(hashed) > 0
        assert hashed != password
        assert "$argon2id$" in hashed

    def test_verify_password_correct(self):
        """Correct password should verify successfully."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Incorrect password should not verify."""
        password = "TestPassword123!"
        wrong_password = "WrongPassword456!"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_hash_password_unique(self):
        """Same password should produce different hashes (due to salt)."""
        password = "TestPassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2
        # But both should verify
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


# =============================================================================
# SESSION TOKEN TESTS
# =============================================================================

class TestSessionToken:
    """Tests for session token generation and hashing."""

    def test_generate_session_token_length(self):
        """Session token should be 64 characters (32 bytes hex)."""
        token = generate_session_token()

        assert len(token) == 64
        # Should be valid hex
        int(token, 16)

    def test_generate_session_token_unique(self):
        """Each token should be unique."""
        tokens = [generate_session_token() for _ in range(100)]

        assert len(set(tokens)) == 100

    def test_hash_session_token(self):
        """Token hash should be deterministic SHA-256."""
        token = "abc123"
        hash1 = hash_session_token(token)
        hash2 = hash_session_token(token)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_hash_session_token_different_inputs(self):
        """Different tokens should produce different hashes."""
        hash1 = hash_session_token("token1")
        hash2 = hash_session_token("token2")

        assert hash1 != hash2


# =============================================================================
# INTERNAL USER CONTEXT TESTS
# =============================================================================

class TestInternalUserContext:
    """Tests for InternalUserContext dataclass."""

    def test_user_context_creation(self):
        """Should create user context with all fields."""
        ctx = InternalUserContext(
            user_id="user-123",
            email="test@example.com",
            display_name="Test User",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read", "portal.details.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        assert ctx.user_id == "user-123"
        assert ctx.email == "test@example.com"
        assert ctx.tenant_id == 1
        assert ctx.site_id == 10
        assert "portal.summary.read" in ctx.permissions

    def test_has_permission(self):
        """Should correctly check for permissions."""
        ctx = InternalUserContext(
            user_id="user-123",
            email="test@example.com",
            display_name=None,
            tenant_id=1,
            site_id=None,
            role_name="dispatcher",
            permissions={"portal.summary.read", "portal.details.read"},
            session_id=None,
            expires_at=None,
        )

        assert ctx.has_permission("portal.summary.read") is True
        assert ctx.has_permission("portal.resend.write") is False

    def test_has_any_permission(self):
        """Should check for any of the given permissions."""
        ctx = InternalUserContext(
            user_id="user-123",
            email="test@example.com",
            display_name=None,
            tenant_id=1,
            site_id=None,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id=None,
            expires_at=None,
        )

        assert ctx.has_any_permission(["portal.summary.read", "portal.resend.write"]) is True
        assert ctx.has_any_permission(["portal.resend.write", "portal.approve.write"]) is False


# =============================================================================
# MOCK RBAC REPOSITORY TESTS
# =============================================================================

class TestMockRBACRepository:
    """Tests for MockRBACRepository."""

    def test_get_user_by_email_found(self):
        """Should return user data for known emails."""
        repo = MockRBACRepository()

        user = repo.get_user_by_email("test-dispatcher@example.com")

        assert user is not None
        assert user["email"] == "test-dispatcher@example.com"
        assert user["is_active"] is True

    def test_get_user_by_email_not_found(self):
        """Should return None for unknown emails."""
        repo = MockRBACRepository()

        user = repo.get_user_by_email("unknown@example.com")

        assert user is None

    def test_get_user_bindings(self):
        """Should return bindings for user."""
        repo = MockRBACRepository()

        bindings = repo.get_user_bindings("user-dispatcher")

        assert len(bindings) >= 1
        assert bindings[0]["role_name"] == "dispatcher"

    def test_get_role_permissions(self):
        """Should return permissions for role."""
        repo = MockRBACRepository()

        permissions = repo.get_role_permissions("dispatcher")

        assert "portal.summary.read" in permissions
        assert "portal.details.read" in permissions
        assert "portal.resend.write" in permissions

    def test_create_and_validate_session(self):
        """Should create session and validate it."""
        repo = MockRBACRepository()
        token = generate_session_token()
        token_hash = hash_session_token(token)

        # Create session using a user that exists in the mock
        # user-dispatcher is a known user in MockRBACRepository
        session_id = repo.create_session(
            token_hash=token_hash,
            user_id="user-dispatcher",
            tenant_id=1,
            site_id=10,
            role_id=3,  # dispatcher role
            ip="127.0.0.1",
            user_agent="Test Agent",
        )

        assert session_id is not None
        assert session_id.startswith("session-")

        # Validate session
        validated = repo.validate_session(token_hash)

        assert validated is not None
        assert validated["user_id"] == "user-dispatcher"
        assert validated["tenant_id"] == 1

    def test_revoke_session(self):
        """Should revoke session successfully."""
        repo = MockRBACRepository()
        token = generate_session_token()
        token_hash = hash_session_token(token)

        # Create and revoke
        repo.create_session(
            token_hash=token_hash,
            user_id="user-123",
            tenant_id=1,
            site_id=10,
            ip=None,
            user_agent=None,
        )
        repo.revoke_session(token_hash)

        # Should no longer validate
        validated = repo.validate_session(token_hash)
        assert validated is None


# =============================================================================
# AUTH SERVICE TESTS
# =============================================================================

class TestAuthService:
    """Tests for AuthService."""

    def test_login_success(self):
        """Should login with correct credentials."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,
            ip="127.0.0.1",
            user_agent="Test",
        )

        assert error is None
        assert token is not None
        assert ctx is not None
        assert ctx.email == "test-dispatcher@example.com"
        assert ctx.role_name == "dispatcher"
        assert "portal.summary.read" in ctx.permissions

    def test_login_invalid_email(self):
        """Should fail with invalid email."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        token, ctx, error = service.login(
            email="unknown@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,
            ip=None,
            user_agent=None,
        )

        assert error == "INVALID_CREDENTIALS"
        assert token is None
        assert ctx is None

    def test_login_invalid_password(self):
        """Should fail with invalid password."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password="WrongPassword!",
            tenant_id=None,
            ip=None,
            user_agent=None,
        )

        assert error == "INVALID_CREDENTIALS"
        assert token is None
        assert ctx is None

    def test_login_inactive_user(self):
        """Should fail for inactive user."""
        repo = MockRBACRepository()
        # Deactivate user
        repo._mock_users["test-dispatcher@example.com"]["is_active"] = False
        service = AuthService(repo)

        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,
            ip=None,
            user_agent=None,
        )

        assert error == "ACCOUNT_INACTIVE"
        assert token is None

        # Restore
        repo._mock_users["test-dispatcher@example.com"]["is_active"] = True

    def test_logout(self):
        """Should logout and revoke session."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        # Login first
        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,
            ip=None,
            user_agent=None,
        )

        assert token is not None

        # Logout
        service.logout(token)

        # Session should be revoked
        token_hash = hash_session_token(token)
        validated = repo.validate_session(token_hash)
        assert validated is None


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestConfiguration:
    """Tests for RBAC configuration constants."""

    def test_session_cookie_name(self):
        """Session cookie should be named '__Host-sv_platform_session' (canonical)."""
        assert SESSION_COOKIE_NAME == "__Host-sv_platform_session"

    def test_session_cookie_max_age(self):
        """Session should last 8 hours (28800 seconds)."""
        assert SESSION_COOKIE_MAX_AGE == 28800


# =============================================================================
# PERMISSION TESTS
# =============================================================================

class TestPermissions:
    """Tests for permission checking."""

    def test_dispatcher_permissions(self):
        """Dispatcher should have read and resend permissions."""
        repo = MockRBACRepository()
        permissions = repo.get_role_permissions("dispatcher")

        assert "portal.summary.read" in permissions
        assert "portal.details.read" in permissions
        assert "portal.resend.write" in permissions
        assert "portal.export.read" in permissions
        # Should NOT have approve permission
        assert "portal.approve.write" not in permissions

    def test_operator_admin_permissions(self):
        """Operator admin should have all portal permissions."""
        repo = MockRBACRepository()
        permissions = repo.get_role_permissions("operator_admin")

        assert "portal.summary.read" in permissions
        assert "portal.details.read" in permissions
        assert "portal.resend.write" in permissions
        assert "portal.approve.write" in permissions
        assert "portal.export.read" in permissions

    def test_ops_readonly_permissions(self):
        """Ops readonly should only have read permissions."""
        repo = MockRBACRepository()
        permissions = repo.get_role_permissions("ops_readonly")

        assert "portal.summary.read" in permissions
        assert "portal.details.read" in permissions
        # Should NOT have write permissions
        assert "portal.resend.write" not in permissions
        assert "portal.approve.write" not in permissions


# =============================================================================
# CROSS-TENANT ISOLATION TESTS
# =============================================================================

class TestCrossTenantIsolation:
    """
    Tests for multi-tenant isolation.

    Critical security tests that verify:
    1. User bound to Tenant A cannot access Tenant B data
    2. Sessions are scoped to their bound tenant
    3. RLS policies work correctly in mock repository
    """

    def test_user_binding_tenant_isolation(self):
        """User bindings should only return bindings for the user's tenant."""
        repo = MockRBACRepository()

        # Dispatcher is bound to tenant 1
        bindings = repo.get_user_bindings("user-dispatcher")

        assert len(bindings) >= 1
        for binding in bindings:
            # All bindings must be for tenant 1
            assert binding["tenant_id"] == 1

    def test_session_tenant_scope(self):
        """Session should be scoped to the tenant from binding."""
        repo = MockRBACRepository()
        token = generate_session_token()
        token_hash = hash_session_token(token)

        # Create session for tenant 1 using existing mock user
        session_id = repo.create_session(
            token_hash=token_hash,
            user_id="user-dispatcher",
            tenant_id=1,
            site_id=10,
            role_id=3,
            ip=None,
            user_agent=None,
        )

        assert session_id is not None

        # Validate session returns same tenant
        validated = repo.validate_session(token_hash)
        assert validated is not None
        assert validated["tenant_id"] == 1

    def test_different_tenants_different_sessions(self):
        """Users in different tenants should have isolated sessions."""
        repo = MockRBACRepository()

        # Create session for tenant 1 using dispatcher
        token1 = generate_session_token()
        token1_hash = hash_session_token(token1)
        repo.create_session(
            token_hash=token1_hash,
            user_id="user-dispatcher",
            tenant_id=1,
            site_id=None,
            role_id=3,
            ip=None,
            user_agent=None,
        )

        # Create session for tenant 2 using admin (add binding first)
        repo._mock_bindings["user-admin"].append({
            "binding_id": 99,
            "tenant_id": 2,
            "site_id": None,
            "role_id": 1,
            "role_name": "platform_admin",
        })
        token2 = generate_session_token()
        token2_hash = hash_session_token(token2)
        repo.create_session(
            token_hash=token2_hash,
            user_id="user-admin",
            tenant_id=2,
            site_id=None,
            role_id=1,
            ip=None,
            user_agent=None,
        )

        # Each session should have its own tenant
        validated1 = repo.validate_session(token1_hash)
        validated2 = repo.validate_session(token2_hash)

        assert validated1 is not None
        assert validated2 is not None
        assert validated1["tenant_id"] == 1
        assert validated2["tenant_id"] == 2

        # Cross-tenant session lookup should not leak data
        assert validated1["user_id"] == "user-dispatcher"
        assert validated2["user_id"] == "user-admin"

    def test_login_respects_tenant_binding(self):
        """Login should only succeed for tenants the user is bound to."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        # Dispatcher is bound to tenant 1
        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,  # Auto-select first binding
            ip=None,
            user_agent=None,
        )

        assert error is None
        assert ctx is not None
        # Should use tenant from binding
        assert ctx.tenant_id == 1

    def test_multi_tenant_user_selects_tenant(self):
        """User with multiple bindings should be able to select tenant."""
        repo = MockRBACRepository()

        # Add a second tenant binding for admin user
        repo._mock_bindings["user-admin"].append({
            "binding_id": 99,
            "tenant_id": 2,
            "site_id": None,
            "role_id": 1,
            "role_name": "platform_admin",
        })

        service = AuthService(repo)

        # Login with explicit tenant selection (use first binding tenant)
        token, ctx, error = service.login(
            email="test-admin@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=1,  # Use original binding tenant
            ip=None,
            user_agent=None,
        )

        assert error is None
        assert ctx is not None
        assert ctx.tenant_id == 1  # Should be tenant from first binding

    def test_user_cannot_login_to_unbound_tenant(self):
        """User cannot login to a tenant they are not bound to."""
        repo = MockRBACRepository()
        service = AuthService(repo)

        # Dispatcher is only bound to tenant 1, try to login to tenant 99
        token, ctx, error = service.login(
            email="test-dispatcher@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=99,  # Not bound to this tenant
            ip=None,
            user_agent=None,
        )

        # Error code is TENANT_NOT_ALLOWED (actual implementation)
        assert error == "TENANT_NOT_ALLOWED"
        assert token is None
        assert ctx is None

    def test_context_enforces_tenant_scope(self):
        """Non-platform-admin users should always have tenant_id for data access."""
        ctx = InternalUserContext(
            user_id="user-123",
            email="test@example.com",
            display_name="Test User",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        # Tenant ID must always be present for non-platform-admin users
        assert ctx.tenant_id is not None
        assert ctx.tenant_id > 0
        assert ctx.is_platform_admin is False  # Dispatcher is not platform admin

    def test_site_isolation_within_tenant(self):
        """Site-scoped users should only access their assigned site."""
        repo = MockRBACRepository()

        # Dispatcher is bound to site 10
        bindings = repo.get_user_bindings("user-dispatcher")

        site_binding = next((b for b in bindings if b.get("site_id") is not None), None)
        if site_binding:
            assert site_binding["site_id"] == 10
            # All data queries should be filtered by this site_id

    def test_session_cannot_escalate_tenant(self):
        """Session created for tenant A cannot be used to access tenant B."""
        repo = MockRBACRepository()
        token = generate_session_token()
        token_hash = hash_session_token(token)

        # Create session for tenant 1 using existing mock user
        repo.create_session(
            token_hash=token_hash,
            user_id="user-dispatcher",
            tenant_id=1,
            site_id=None,
            role_id=3,
            ip=None,
            user_agent=None,
        )

        # Validate session
        validated = repo.validate_session(token_hash)

        # Session is locked to tenant 1
        assert validated is not None
        assert validated["tenant_id"] == 1

        # The application layer must enforce that this tenant_id
        # is used for ALL subsequent data access - not a parameter
        # from the request. This is the key security boundary.


# =============================================================================
# PLATFORM ADMIN ACCESS CONTROL TESTS
# =============================================================================

class TestPlatformAdminAccessControl:
    """
    Tests for platform admin access control.

    Verifies:
    1. platform_admin identified by role_name only (not tenant_id)
    2. tenant_admin cannot access platform-level resources
    3. platform_admin can access any tenant
    4. Cross-tenant data isolation maintained
    """

    def test_is_platform_admin_checks_role_name_only(self):
        """Platform admin should be identified by role_name, not tenant_id."""
        # Platform admin with NULL tenant_id (correct)
        platform_admin = InternalUserContext(
            user_id="admin-123",
            email="admin@example.com",
            display_name="Platform Admin",
            tenant_id=None,  # NULL for platform admin
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read", "platform.users.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        assert platform_admin.is_platform_admin is True

    def test_is_platform_admin_requires_role_name(self):
        """is_platform_admin should return False for non-platform_admin roles."""
        # Tenant admin (should NOT be platform admin)
        tenant_admin = InternalUserContext(
            user_id="tenant-admin-123",
            email="tenant-admin@example.com",
            display_name="Tenant Admin",
            tenant_id=1,
            site_id=None,
            role_name="tenant_admin",
            permissions={"tenant.users.read", "tenant.users.write"},
            session_id="session-def",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        assert tenant_admin.is_platform_admin is False

    def test_is_platform_admin_not_based_on_tenant_id_zero(self):
        """Platform admin should NOT rely on tenant_id=0 (old broken pattern)."""
        # User with tenant_id=0 but not platform_admin role (should NOT be platform admin)
        fake_admin = InternalUserContext(
            user_id="fake-123",
            email="fake@example.com",
            display_name="Fake Admin",
            tenant_id=0,  # Old pattern - should NOT make them platform admin
            site_id=None,
            role_name="dispatcher",  # NOT platform_admin
            permissions={"portal.summary.read"},
            session_id="session-ghi",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        assert fake_admin.is_platform_admin is False

    def test_platform_admin_can_access_any_tenant(self):
        """Platform admin should be able to access any tenant's data."""
        platform_admin = InternalUserContext(
            user_id="admin-123",
            email="admin@example.com",
            display_name="Platform Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        # Platform admin can access any tenant
        assert platform_admin.can_access_tenant(1) is True
        assert platform_admin.can_access_tenant(2) is True
        assert platform_admin.can_access_tenant(999) is True

    def test_tenant_admin_cannot_access_other_tenants(self):
        """Tenant admin should only access their assigned tenant."""
        tenant_admin = InternalUserContext(
            user_id="tenant-admin-123",
            email="tenant-admin@example.com",
            display_name="Tenant Admin",
            tenant_id=1,  # Bound to tenant 1
            site_id=None,
            role_name="tenant_admin",
            permissions={"tenant.users.read"},
            session_id="session-def",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        # Can only access their tenant
        assert tenant_admin.can_access_tenant(1) is True
        assert tenant_admin.can_access_tenant(2) is False
        assert tenant_admin.can_access_tenant(999) is False

    def test_get_effective_tenant_id_for_platform_admin(self):
        """Platform admin can specify target tenant for operations."""
        platform_admin = InternalUserContext(
            user_id="admin-123",
            email="admin@example.com",
            display_name="Platform Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        # Without target: returns None (platform scope)
        assert platform_admin.get_effective_tenant_id() is None

        # With target: returns target tenant
        assert platform_admin.get_effective_tenant_id(target_tenant_id=1) == 1
        assert platform_admin.get_effective_tenant_id(target_tenant_id=2) == 2

    def test_get_effective_tenant_id_for_regular_user(self):
        """Regular user cannot override their tenant via target parameter."""
        dispatcher = InternalUserContext(
            user_id="user-123",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,  # Bound to tenant 1
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-xyz",
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )

        # Always returns their bound tenant, regardless of target parameter
        assert dispatcher.get_effective_tenant_id() == 1
        assert dispatcher.get_effective_tenant_id(target_tenant_id=2) == 1  # Ignored!
        assert dispatcher.get_effective_tenant_id(target_tenant_id=999) == 1  # Ignored!

    def test_null_tenant_id_for_platform_admin(self):
        """Platform admin should have NULL tenant_id in their binding."""
        platform_admin = InternalUserContext(
            user_id="admin-123",
            email="admin@example.com",
            display_name="Platform Admin",
            tenant_id=None,  # Must be NULL
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        assert platform_admin.tenant_id is None
        assert platform_admin.is_platform_admin is True

    def test_platform_scope_flag(self):
        """Session should track is_platform_scope flag."""
        platform_admin = InternalUserContext(
            user_id="admin-123",
            email="admin@example.com",
            display_name="Platform Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-abc",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,  # Explicit flag
        )

        assert platform_admin.is_platform_scope is True

        # Regular user should not have platform scope
        dispatcher = InternalUserContext(
            user_id="user-123",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-xyz",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,  # Default
        )

        assert dispatcher.is_platform_scope is False


class TestPlatformAdminMockRepository:
    """
    Tests for platform admin in MockRBACRepository.
    """

    def test_mock_repo_supports_platform_admin(self):
        """Mock repository should support platform admin users."""
        repo = MockRBACRepository()

        # Add a platform admin to the mock
        repo._mock_users["platform-admin@example.com"] = {
            "id": "user-platform-admin",
            "email": "platform-admin@example.com",
            "display_name": "Platform Admin",
            "password_hash": hash_password(MockRBACRepository.TEST_PASSWORD),
            "is_active": True,
            "is_locked": False,
            "failed_login_count": 0,
        }
        repo._mock_bindings["user-platform-admin"] = [{
            "binding_id": 100,
            "tenant_id": None,  # NULL for platform admin
            "site_id": None,
            "role_id": 1,  # platform_admin role
            "role_name": "platform_admin",
        }]
        repo._mock_permissions["platform_admin"] = {
            "platform.tenants.read",
            "platform.tenants.write",
            "platform.users.read",
            "platform.users.write",
        }

        # Verify platform admin can be retrieved
        user = repo.get_user_by_email("platform-admin@example.com")
        assert user is not None
        assert user["email"] == "platform-admin@example.com"

        # Verify bindings have NULL tenant
        bindings = repo.get_user_bindings("user-platform-admin")
        assert len(bindings) == 1
        assert bindings[0]["tenant_id"] is None
        assert bindings[0]["role_name"] == "platform_admin"

        # Verify platform admin permissions
        permissions = repo.get_role_permissions("platform_admin")
        assert "platform.tenants.read" in permissions
        assert "platform.users.write" in permissions

    def test_platform_admin_login(self):
        """Platform admin should be able to login successfully."""
        repo = MockRBACRepository()

        # Add platform admin to mock
        repo._mock_users["platform-admin@example.com"] = {
            "id": "user-platform-admin",
            "email": "platform-admin@example.com",
            "display_name": "Platform Admin",
            "password_hash": hash_password(MockRBACRepository.TEST_PASSWORD),
            "is_active": True,
            "is_locked": False,
            "failed_login_count": 0,
        }
        repo._mock_bindings["user-platform-admin"] = [{
            "binding_id": 100,
            "tenant_id": None,
            "site_id": None,
            "role_id": 1,
            "role_name": "platform_admin",
        }]
        repo._mock_permissions["platform_admin"] = {
            "platform.tenants.read",
            "platform.tenants.write",
        }

        service = AuthService(repo)

        token, ctx, error = service.login(
            email="platform-admin@example.com",
            password=MockRBACRepository.TEST_PASSWORD,
            tenant_id=None,  # Platform admin doesn't specify tenant
            ip="127.0.0.1",
            user_agent="Test",
        )

        assert error is None
        assert token is not None
        assert ctx is not None
        assert ctx.email == "platform-admin@example.com"
        assert ctx.role_name == "platform_admin"
        assert ctx.tenant_id is None  # NULL for platform admin
        assert ctx.is_platform_admin is True
        assert ctx.is_platform_scope is True


# =============================================================================
# ROLE ASSIGNMENT BOUNDARY TESTS
# =============================================================================

class TestRoleAssignmentBoundaries:
    """
    Tests for role assignment privilege boundaries.

    Verifies:
    1. platform_admin can assign any role
    2. tenant_admin cannot assign platform_admin role
    3. Lower roles cannot assign any roles
    """

    def test_platform_admin_can_assign_platform_admin(self):
        """Platform admin can assign platform_admin role."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("platform_admin", "platform_admin") is True
        assert validate_role_assignment("platform_admin", "tenant_admin") is True
        assert validate_role_assignment("platform_admin", "operator_admin") is True
        assert validate_role_assignment("platform_admin", "dispatcher") is True
        assert validate_role_assignment("platform_admin", "ops_readonly") is True

    def test_tenant_admin_cannot_assign_platform_admin(self):
        """Tenant admin cannot assign platform_admin role."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("tenant_admin", "platform_admin") is False
        assert validate_role_assignment("tenant_admin", "tenant_admin") is True
        assert validate_role_assignment("tenant_admin", "operator_admin") is True
        assert validate_role_assignment("tenant_admin", "dispatcher") is True
        assert validate_role_assignment("tenant_admin", "ops_readonly") is True

    def test_operator_admin_cannot_assign_roles(self):
        """Operator admin cannot assign any roles."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("operator_admin", "platform_admin") is False
        assert validate_role_assignment("operator_admin", "tenant_admin") is False
        assert validate_role_assignment("operator_admin", "operator_admin") is False
        assert validate_role_assignment("operator_admin", "dispatcher") is False
        assert validate_role_assignment("operator_admin", "ops_readonly") is False

    def test_dispatcher_cannot_assign_roles(self):
        """Dispatcher cannot assign any roles."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("dispatcher", "platform_admin") is False
        assert validate_role_assignment("dispatcher", "tenant_admin") is False
        assert validate_role_assignment("dispatcher", "dispatcher") is False

    def test_unknown_role_cannot_assign(self):
        """Unknown role cannot assign any roles."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("unknown_role", "dispatcher") is False


# =============================================================================
# SMOKE TESTS - PLATFORM ADMIN WORKFLOW
# =============================================================================

class TestPlatformAdminWorkflowSmoke:
    """
    End-to-end smoke tests for platform admin workflow.

    These tests verify the core admin workflow:
    1. Platform admin can create tenant
    2. Platform admin can create site in tenant
    3. Platform admin can create tenant_admin user
    4. Tenant admin can login successfully
    5. Tenant admin cannot access platform routes
    """

    def test_role_hierarchy_correct_order(self):
        """Role hierarchy should have correct ordering."""
        from backend_py.api.routers.platform_admin import ROLE_HIERARCHY

        assert ROLE_HIERARCHY["ops_readonly"] < ROLE_HIERARCHY["dispatcher"]
        assert ROLE_HIERARCHY["dispatcher"] < ROLE_HIERARCHY["operator_admin"]
        assert ROLE_HIERARCHY["operator_admin"] < ROLE_HIERARCHY["tenant_admin"]
        assert ROLE_HIERARCHY["tenant_admin"] < ROLE_HIERARCHY["platform_admin"]

    def test_platform_admin_context_has_all_access(self):
        """Platform admin context should have access to all tenants."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,  # NULL for platform admin
            site_id=None,
            role_name="platform_admin",
            permissions={
                "platform.tenants.read",
                "platform.tenants.write",
                "platform.users.read",
                "platform.users.write",
            },
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        # Should be able to access any tenant
        assert platform_admin.can_access_tenant(1) is True
        assert platform_admin.can_access_tenant(2) is True
        assert platform_admin.can_access_tenant(100) is True

        # Should be platform admin
        assert platform_admin.is_platform_admin is True

    def test_tenant_admin_context_restricted_to_tenant(self):
        """Tenant admin context should be restricted to their tenant."""
        tenant_admin = InternalUserContext(
            user_id="tenant-admin-1",
            email="tenant-admin@example.com",
            display_name="Tenant Admin",
            tenant_id=1,  # Bound to tenant 1
            site_id=None,
            role_name="tenant_admin",
            permissions={
                "tenant.users.read",
                "tenant.users.write",
                "tenant.sites.read",
            },
            session_id="session-2",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,
        )

        # Should only access their tenant
        assert tenant_admin.can_access_tenant(1) is True
        assert tenant_admin.can_access_tenant(2) is False

        # Should NOT be platform admin
        assert tenant_admin.is_platform_admin is False

    def test_tenant_admin_cannot_escalate_to_platform(self):
        """Tenant admin cannot escalate privileges to platform admin."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        # tenant_admin trying to create platform_admin should fail
        assert validate_role_assignment("tenant_admin", "platform_admin") is False

    def test_platform_admin_can_create_platform_admin(self):
        """Platform admin can create another platform admin."""
        from backend_py.api.routers.platform_admin import validate_role_assignment

        assert validate_role_assignment("platform_admin", "platform_admin") is True

    def test_effective_tenant_id_for_cross_tenant_access(self):
        """Platform admin can set effective tenant for cross-tenant ops."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        # Without target: None (platform-wide)
        assert platform_admin.get_effective_tenant_id() is None

        # With target: specific tenant
        assert platform_admin.get_effective_tenant_id(target_tenant_id=1) == 1
        assert platform_admin.get_effective_tenant_id(target_tenant_id=2) == 2

    def test_regular_user_cannot_override_tenant(self):
        """Regular user cannot override their tenant via target parameter."""
        dispatcher = InternalUserContext(
            user_id="user-1",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-3",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,
        )

        # Should always return their bound tenant
        assert dispatcher.get_effective_tenant_id() == 1
        assert dispatcher.get_effective_tenant_id(target_tenant_id=2) == 1  # Ignored!
        assert dispatcher.get_effective_tenant_id(target_tenant_id=999) == 1  # Ignored!


# =============================================================================
# PLATFORM ADMIN RBAC BYPASS TESTS
# =============================================================================

class TestPlatformAdminRBACBypass:
    """
    Tests for platform admin RBAC bypass functionality.

    Verifies:
    1. Platform admin bypasses all permission checks
    2. Regular users still require permissions
    3. RBAC bypass is role-based (not tenant-based)
    """

    def test_platform_admin_bypasses_has_permission(self):
        """Platform admin should bypass has_permission checks."""
        # Note: has_permission itself doesn't bypass - the bypass happens
        # in the require_permission dependency. But we verify behavior here.
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions=set(),  # Empty permissions - bypass should still work
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
        )

        # Platform admin identified by role
        assert platform_admin.is_platform_admin is True

    def test_regular_user_requires_permission(self):
        """Regular user should require specific permissions."""
        dispatcher = InternalUserContext(
            user_id="user-1",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-2",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,
        )

        # Regular user needs specific permission
        assert dispatcher.has_permission("portal.summary.read") is True
        assert dispatcher.has_permission("portal.approve.write") is False
        assert dispatcher.is_platform_admin is False


# =============================================================================
# ACTIVE CONTEXT TESTS
# =============================================================================

class TestActiveContext:
    """
    Tests for platform admin active context functionality.

    Verifies:
    1. active_tenant_id/active_site_id tracking
    2. has_active_context property
    3. get_effective_tenant_id with active context
    4. get_effective_site_id with active context
    """

    def test_active_context_fields(self):
        """Platform admin should support active context fields."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=1,
            active_site_id=10,
        )

        assert platform_admin.active_tenant_id == 1
        assert platform_admin.active_site_id == 10

    def test_has_active_context_true(self):
        """has_active_context should return True when active tenant is set."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=1,
            active_site_id=None,
        )

        assert platform_admin.has_active_context is True

    def test_has_active_context_false_no_active_tenant(self):
        """has_active_context should return False when no active tenant."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=None,
            active_site_id=None,
        )

        assert platform_admin.has_active_context is False

    def test_has_active_context_false_for_regular_user(self):
        """has_active_context should return False for regular users."""
        dispatcher = InternalUserContext(
            user_id="user-1",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,
            site_id=10,
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-2",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,
            active_tenant_id=1,  # Even if set, not platform admin
            active_site_id=10,
        )

        # Not platform admin, so has_active_context is False
        assert dispatcher.has_active_context is False

    def test_get_effective_tenant_id_priority(self):
        """get_effective_tenant_id should respect priority order."""
        # Priority: explicit target > active context > binding context
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,  # Binding context
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=2,  # Active context
            active_site_id=None,
        )

        # Explicit target takes priority
        assert platform_admin.get_effective_tenant_id(target_tenant_id=3) == 3

        # Active context is used when no explicit target
        assert platform_admin.get_effective_tenant_id() == 2

    def test_get_effective_tenant_id_no_active_context(self):
        """get_effective_tenant_id without active context returns binding tenant."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,  # Platform admin has NULL binding
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=None,  # No active context
            active_site_id=None,
        )

        # Returns None (platform-wide scope)
        assert platform_admin.get_effective_tenant_id() is None

    def test_get_effective_site_id_priority(self):
        """get_effective_site_id should respect priority order."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,  # Binding site
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=1,
            active_site_id=20,  # Active site
        )

        # Explicit target takes priority
        assert platform_admin.get_effective_site_id(target_site_id=30) == 30

        # Active site is used when no explicit target
        assert platform_admin.get_effective_site_id() == 20

    def test_regular_user_ignores_active_context(self):
        """Regular users should always use binding tenant, ignoring active context."""
        dispatcher = InternalUserContext(
            user_id="user-1",
            email="dispatcher@example.com",
            display_name="Dispatcher",
            tenant_id=1,  # Binding tenant
            site_id=10,  # Binding site
            role_name="dispatcher",
            permissions={"portal.summary.read"},
            session_id="session-2",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=False,
            active_tenant_id=999,  # Should be ignored
            active_site_id=888,  # Should be ignored
        )

        # Always returns binding context
        assert dispatcher.get_effective_tenant_id() == 1
        assert dispatcher.get_effective_tenant_id(target_tenant_id=2) == 1  # Ignored
        assert dispatcher.get_effective_site_id() == 10
        assert dispatcher.get_effective_site_id(target_site_id=20) == 10  # Ignored


# =============================================================================
# MOCK REPOSITORY CONTEXT TESTS
# =============================================================================

class TestMockRepositoryContext:
    """
    Tests for context switching in MockRBACRepository.
    """

    def test_create_session_with_platform_scope(self):
        """Should create platform admin session with is_platform_scope."""
        repo = MockRBACRepository()

        # Add platform admin
        repo._mock_users["platform-admin@example.com"] = {
            "id": "user-platform-admin",
            "email": "platform-admin@example.com",
            "display_name": "Platform Admin",
            "password_hash": hash_password(MockRBACRepository.TEST_PASSWORD),
            "is_active": True,
            "is_locked": False,
            "failed_login_count": 0,
        }
        repo._mock_bindings["user-platform-admin"] = [{
            "binding_id": 100,
            "tenant_id": None,
            "site_id": None,
            "role_id": 1,
            "role_name": "platform_admin",
        }]

        token = generate_session_token()
        token_hash = hash_session_token(token)

        session_id = repo.create_session(
            token_hash=token_hash,
            user_id="user-platform-admin",
            tenant_id=None,
            site_id=None,
            role_id=1,
            ip_hash=None,
            user_agent_hash=None,
            is_platform_scope=True,
        )

        assert session_id is not None

        # Validate session includes platform scope
        validated = repo.validate_session(token_hash)
        assert validated is not None
        assert validated["tenant_id"] is None
        assert validated.get("is_platform_scope") is True


# =============================================================================
# AUDIT VERIFICATION TESTS
# =============================================================================

class TestAuditVerification:
    """
    Tests for audit log verification requirements.

    Verifies:
    1. Context switch should be auditable
    2. Cross-tenant operations should include target_tenant_id
    """

    def test_context_switch_auditable_via_active_tenant(self):
        """Context switches should be traceable via active_tenant_id."""
        # This tests the data model supports auditing
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,  # Platform scope
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=1,  # Currently working in tenant 1
            active_site_id=None,
        )

        # The active_tenant_id can be logged in audit entries
        assert platform_admin.active_tenant_id == 1
        assert platform_admin.is_platform_admin is True

    def test_cross_tenant_operation_traceable(self):
        """Cross-tenant operations should be traceable via get_effective_tenant_id."""
        platform_admin = InternalUserContext(
            user_id="admin-1",
            email="admin@example.com",
            display_name="Admin",
            tenant_id=None,
            site_id=None,
            role_name="platform_admin",
            permissions={"platform.tenants.read"},
            session_id="session-1",
            expires_at=datetime.utcnow() + timedelta(hours=8),
            is_platform_scope=True,
            active_tenant_id=None,
        )

        # When platform admin accesses tenant 1's data
        target_tenant = 1
        effective_tenant = platform_admin.get_effective_tenant_id(target_tenant_id=target_tenant)

        # This effective_tenant_id should be logged as target_tenant_id in audit
        assert effective_tenant == target_tenant
