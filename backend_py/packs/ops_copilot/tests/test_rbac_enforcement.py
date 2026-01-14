"""
RBAC Enforcement Tests

Tests:
- Viewer/ops_readonly cannot commit writes
- Dispatcher can commit tickets but not driver broadcasts
- Tenant admin can commit all actions
- Platform admin bypasses all checks
- Creator must match for draft confirmation
"""

import pytest
from unittest.mock import MagicMock

from ..security.rbac import (
    PERMISSION_TICKETS_WRITE,
    PERMISSION_AUDIT_WRITE,
    PERMISSION_BROADCAST_OPS,
    PERMISSION_BROADCAST_DRIVER,
    PERMISSION_PAIRING_MANAGE,
    has_permission,
    check_action_permission,
    can_commit_draft,
    ActionContext,
)


class TestHasPermission:
    """Tests for basic permission checking."""

    def test_platform_admin_bypass(self):
        """Platform admin should bypass all permission checks."""
        context = ActionContext(
            user_id="admin-id",
            role_name="platform_admin",
            permissions=[],  # No explicit permissions needed
            tenant_id=None,
        )

        # Should pass for any permission
        assert has_permission(context, PERMISSION_TICKETS_WRITE) is True
        assert has_permission(context, PERMISSION_BROADCAST_DRIVER) is True
        assert has_permission(context, "some.random.permission") is True

    def test_has_explicit_permission(self):
        """User with explicit permission should pass."""
        context = ActionContext(
            user_id="user-id",
            role_name="dispatcher",
            permissions=[PERMISSION_TICKETS_WRITE, PERMISSION_AUDIT_WRITE],
            tenant_id=1,
        )

        assert has_permission(context, PERMISSION_TICKETS_WRITE) is True
        assert has_permission(context, PERMISSION_AUDIT_WRITE) is True
        assert has_permission(context, PERMISSION_BROADCAST_DRIVER) is False

    def test_missing_permission(self):
        """User without permission should fail."""
        context = ActionContext(
            user_id="user-id",
            role_name="ops_readonly",
            permissions=["ops_copilot.tickets.read"],
            tenant_id=1,
        )

        assert has_permission(context, PERMISSION_TICKETS_WRITE) is False
        assert has_permission(context, PERMISSION_BROADCAST_OPS) is False


class TestCheckActionPermission:
    """Tests for action-specific permission checking."""

    def test_create_ticket_permission(self, test_users):
        """CREATE_TICKET requires ops_copilot.tickets.write."""
        dispatcher = test_users["dispatcher"]
        viewer = test_users["ops_readonly"]

        # Dispatcher has tickets.write
        dispatcher_result = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="CREATE_TICKET",
        )
        assert dispatcher_result[0] is True

        # Viewer does not
        viewer_result = check_action_permission(
            user_id=viewer["user_id"],
            user_permissions=viewer["permissions"],
            role_name=viewer["role_name"],
            action_type="CREATE_TICKET",
        )
        assert viewer_result[0] is False
        assert "permission" in viewer_result[1].lower()

    def test_audit_comment_permission(self, test_users):
        """AUDIT_COMMENT requires ops_copilot.audit.write."""
        dispatcher = test_users["dispatcher"]

        result = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="AUDIT_COMMENT",
        )
        assert result[0] is True

    def test_broadcast_ops_permission(self, test_users):
        """WHATSAPP_BROADCAST_OPS requires ops_copilot.broadcast.ops."""
        dispatcher = test_users["dispatcher"]
        viewer = test_users["ops_readonly"]

        # Dispatcher has broadcast.ops
        dispatcher_result = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="WHATSAPP_BROADCAST_OPS",
        )
        assert dispatcher_result[0] is True

        # Viewer does not
        viewer_result = check_action_permission(
            user_id=viewer["user_id"],
            user_permissions=viewer["permissions"],
            role_name=viewer["role_name"],
            action_type="WHATSAPP_BROADCAST_OPS",
        )
        assert viewer_result[0] is False

    def test_broadcast_driver_permission(self, test_users):
        """WHATSAPP_BROADCAST_DRIVER requires ops_copilot.broadcast.driver."""
        tenant_admin = test_users["tenant_admin"]
        dispatcher = test_users["dispatcher"]

        # Tenant admin has broadcast.driver
        admin_result = check_action_permission(
            user_id=tenant_admin["user_id"],
            user_permissions=tenant_admin["permissions"],
            role_name=tenant_admin["role_name"],
            action_type="WHATSAPP_BROADCAST_DRIVER",
        )
        assert admin_result[0] is True

        # Dispatcher does NOT have broadcast.driver
        dispatcher_result = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="WHATSAPP_BROADCAST_DRIVER",
        )
        assert dispatcher_result[0] is False

    def test_unknown_action_rejected(self, test_users):
        """Unknown action types should be rejected."""
        admin = test_users["tenant_admin"]

        result = check_action_permission(
            user_id=admin["user_id"],
            user_permissions=admin["permissions"],
            role_name=admin["role_name"],
            action_type="UNKNOWN_ACTION",
        )
        assert result[0] is False
        assert "unknown" in result[1].lower()


class TestCanCommitDraft:
    """Tests for draft confirmation authorization."""

    def test_owner_can_commit_own_draft(self, test_users):
        """Draft creator can confirm their own draft."""
        dispatcher = test_users["dispatcher"]

        allowed, reason = can_commit_draft(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            draft_created_by=dispatcher["user_id"],  # Same user
            action_type="CREATE_TICKET",
        )
        assert allowed is True

    def test_viewer_cannot_commit(self, test_users):
        """Viewer cannot commit any draft."""
        viewer = test_users["ops_readonly"]
        dispatcher = test_users["dispatcher"]

        allowed, reason = can_commit_draft(
            user_id=viewer["user_id"],
            user_permissions=viewer["permissions"],
            role_name=viewer["role_name"],
            draft_created_by=dispatcher["user_id"],
            action_type="CREATE_TICKET",
        )
        assert allowed is False
        assert "permission" in reason.lower()

    def test_different_user_cannot_commit_others_draft(self, test_users):
        """User cannot confirm another user's draft (even with permission)."""
        dispatcher = test_users["dispatcher"]
        tenant_admin = test_users["tenant_admin"]

        # Dispatcher tries to confirm tenant_admin's draft
        allowed, reason = can_commit_draft(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            draft_created_by=tenant_admin["user_id"],  # Different user
            action_type="CREATE_TICKET",
        )
        assert allowed is False
        assert "creator" in reason.lower() or "owner" in reason.lower()

    def test_platform_admin_can_commit_any_draft(self, test_users):
        """Platform admin can confirm any draft."""
        platform_admin = test_users["platform_admin"]
        dispatcher = test_users["dispatcher"]

        allowed, reason = can_commit_draft(
            user_id=platform_admin["user_id"],
            user_permissions=platform_admin["permissions"],
            role_name=platform_admin["role_name"],
            draft_created_by=dispatcher["user_id"],  # Different user
            action_type="CREATE_TICKET",
        )
        assert allowed is True

    def test_tenant_admin_can_commit_tenant_drafts(self, test_users):
        """Tenant admin can confirm drafts within their tenant."""
        tenant_admin = test_users["tenant_admin"]
        dispatcher = test_users["dispatcher"]

        allowed, reason = can_commit_draft(
            user_id=tenant_admin["user_id"],
            user_permissions=tenant_admin["permissions"],
            role_name=tenant_admin["role_name"],
            draft_created_by=dispatcher["user_id"],
            action_type="CREATE_TICKET",
        )
        assert allowed is True


class TestRBACIntegration:
    """Integration tests for RBAC enforcement scenarios."""

    def test_dispatcher_ticket_workflow(self, test_users):
        """Dispatcher can create and confirm their own ticket."""
        dispatcher = test_users["dispatcher"]

        # Can create ticket
        create_allowed, _ = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="CREATE_TICKET",
        )
        assert create_allowed is True

        # Can confirm their own draft
        confirm_allowed, _ = can_commit_draft(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            draft_created_by=dispatcher["user_id"],
            action_type="CREATE_TICKET",
        )
        assert confirm_allowed is True

    def test_viewer_blocked_from_writes(self, test_users):
        """Viewer cannot perform any write action."""
        viewer = test_users["ops_readonly"]

        write_actions = [
            "CREATE_TICKET",
            "AUDIT_COMMENT",
            "WHATSAPP_BROADCAST_OPS",
            "WHATSAPP_BROADCAST_DRIVER",
        ]

        for action in write_actions:
            allowed, reason = check_action_permission(
                user_id=viewer["user_id"],
                user_permissions=viewer["permissions"],
                role_name=viewer["role_name"],
                action_type=action,
            )
            assert allowed is False, f"Viewer should not be allowed to {action}"

    def test_permission_escalation_blocked(self, test_users):
        """User cannot escalate beyond their permissions."""
        dispatcher = test_users["dispatcher"]

        # Dispatcher cannot send driver broadcasts (requires broadcast.driver)
        allowed, reason = check_action_permission(
            user_id=dispatcher["user_id"],
            user_permissions=dispatcher["permissions"],
            role_name=dispatcher["role_name"],
            action_type="WHATSAPP_BROADCAST_DRIVER",
        )
        assert allowed is False
