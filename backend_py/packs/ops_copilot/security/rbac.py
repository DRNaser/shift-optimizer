"""
Ops-Copilot RBAC (Role-Based Access Control)

Permission checks for write actions and resource access.
"""

import logging
from typing import Set, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# Permission Constants
# =============================================================================

# Permission strings for Ops-Copilot actions
PERMISSION_PAIRING_WRITE = "ops_copilot.pairing.write"
PERMISSION_PAIRING_READ = "ops_copilot.pairing.read"
PERMISSION_PAIRING_MANAGE = "ops_copilot.pairing.manage"  # Alias for backward compat
PERMISSION_IDENTITY_REVOKE = "ops_copilot.identity.revoke"
PERMISSION_TICKETS_WRITE = "ops_copilot.tickets.write"
PERMISSION_TICKETS_READ = "ops_copilot.tickets.read"
PERMISSION_AUDIT_WRITE = "ops_copilot.audit.write"
PERMISSION_BROADCAST_OPS = "ops_copilot.broadcast.ops"
PERMISSION_BROADCAST_DRIVER = "ops_copilot.broadcast.driver"
PERMISSION_PLAYBOOKS_WRITE = "ops_copilot.playbooks.write"
PERMISSION_PLAYBOOKS_READ = "ops_copilot.playbooks.read"

# Map action types to required permissions
WRITE_ACTION_PERMISSIONS = {
    "CREATE_TICKET": [PERMISSION_TICKETS_WRITE],
    "AUDIT_COMMENT": [PERMISSION_AUDIT_WRITE],
    "WHATSAPP_BROADCAST_OPS": [PERMISSION_BROADCAST_OPS],
    "WHATSAPP_BROADCAST_DRIVER": [PERMISSION_BROADCAST_DRIVER],
}

# Roles that can approve/commit write actions (for 2-phase commit)
APPROVER_ROLES = {
    "platform_admin",
    "tenant_admin",
    "operator_admin",
}

# Roles with full bypass (superuser)
BYPASS_ROLES = {"platform_admin"}


# =============================================================================
# RBAC Helpers
# =============================================================================


def has_permission(
    context_or_permissions,
    required_permission: str,
    role_name: Optional[str] = None,
) -> bool:
    """
    Check if user has a specific permission.

    Platform admins bypass all permission checks.

    Accepts either:
    - ActionContext as first argument (new API)
    - Set[str] of permissions as first argument (legacy API)

    Args:
        context_or_permissions: ActionContext or Set of permission strings
        required_permission: Permission to check
        role_name: User's role name (for bypass check, ignored if ActionContext)

    Returns:
        True if user has permission
    """
    # Handle ActionContext (new API)
    if hasattr(context_or_permissions, 'role_name') and hasattr(context_or_permissions, 'permissions'):
        ctx = context_or_permissions
        if ctx.role_name in BYPASS_ROLES:
            return True
        perms = ctx.permissions if isinstance(ctx.permissions, set) else set(ctx.permissions)
        return required_permission in perms

    # Legacy API: Set[str] of permissions
    user_permissions = context_or_permissions
    if role_name in BYPASS_ROLES:
        return True

    return required_permission in user_permissions


def has_any_permission(
    user_permissions: Set[str],
    required_permissions: List[str],
    role_name: Optional[str] = None,
) -> bool:
    """
    Check if user has any of the required permissions.

    Args:
        user_permissions: Set of permission strings
        required_permissions: List of permissions (any match succeeds)
        role_name: User's role name

    Returns:
        True if user has at least one permission
    """
    if role_name in BYPASS_ROLES:
        return True

    return any(p in user_permissions for p in required_permissions)


def has_all_permissions(
    user_permissions: Set[str],
    required_permissions: List[str],
    role_name: Optional[str] = None,
) -> bool:
    """
    Check if user has all required permissions.

    Args:
        user_permissions: Set of permission strings
        required_permissions: List of permissions (all must match)
        role_name: User's role name

    Returns:
        True if user has all permissions
    """
    if role_name in BYPASS_ROLES:
        return True

    return all(p in user_permissions for p in required_permissions)


def can_perform_action(
    user_permissions: Set[str],
    action_type: str,
    role_name: Optional[str] = None,
) -> bool:
    """
    Check if user can perform a specific write action.

    Args:
        user_permissions: Set of permission strings
        action_type: Action type (CREATE_TICKET, AUDIT_COMMENT, etc.)
        role_name: User's role name

    Returns:
        True if user can perform the action
    """
    if role_name in BYPASS_ROLES:
        return True

    required = WRITE_ACTION_PERMISSIONS.get(action_type, [])
    if not required:
        logger.warning(
            "unknown_action_type",
            extra={"action_type": action_type},
        )
        return False

    return has_any_permission(user_permissions, required, role_name)


def can_approve_action(role_name: str) -> bool:
    """
    Check if user's role can approve/commit write actions.

    Args:
        role_name: User's role name

    Returns:
        True if user can approve actions
    """
    return role_name in APPROVER_ROLES


def check_action_permission(
    user_id: str,
    user_permissions,
    role_name: str,
    action_type: str,
) -> tuple[bool, str]:
    """
    Check if user can perform a specific action (test-compatible API).

    Args:
        user_id: User's UUID (unused but kept for API compat)
        user_permissions: Set or list of permission strings
        role_name: User's role name
        action_type: Action type to check

    Returns:
        Tuple of (allowed, reason_message)
    """
    perms = set(user_permissions) if not isinstance(user_permissions, set) else user_permissions

    if role_name in BYPASS_ROLES:
        return True, "platform_admin_bypass"

    if can_perform_action(perms, action_type, role_name):
        return True, "permission_granted"

    return False, "Insufficient permission for action"


def is_owner_of_draft(
    user_id: str,
    draft_created_by: str,
) -> bool:
    """
    Check if user owns a draft (created it).

    Args:
        user_id: Current user's UUID
        draft_created_by: UUID of draft creator

    Returns:
        True if user owns the draft
    """
    return user_id == draft_created_by


def can_commit_draft(
    user_id: str,
    user_permissions: Set[str],
    role_name: str,
    draft_created_by: str,
    action_type: str,
) -> tuple[bool, str]:
    """
    Check if user can commit a specific draft.

    Rules:
    1. Platform admin can commit any draft
    2. Approver roles can commit any draft they have permission for
    3. Owner can commit their own draft if they have permission

    Args:
        user_id: Current user's UUID
        user_permissions: Set of permission strings
        role_name: User's role name
        draft_created_by: UUID of draft creator
        action_type: Draft action type

    Returns:
        Tuple of (can_commit, reason)
    """
    # Check action permission first
    if not can_perform_action(user_permissions, action_type, role_name):
        return False, "insufficient_permission"

    # Platform admin bypass
    if role_name in BYPASS_ROLES:
        return True, "platform_admin_bypass"

    # Check if approver
    if can_approve_action(role_name):
        return True, "approver_role"

    # Check if owner
    if is_owner_of_draft(user_id, draft_created_by):
        return True, "owner"

    return False, "not_authorized"


# =============================================================================
# Context Helpers
# =============================================================================


@dataclass
class ActionContext:
    """Context for evaluating action permissions."""

    user_id: str
    role_name: str
    permissions: Set[str]
    tenant_id: Optional[int] = None
    site_id: Optional[int] = None
    is_platform_admin: bool = False

    @classmethod
    def from_user_context(cls, user_context) -> "ActionContext":
        """
        Create ActionContext from InternalUserContext.

        Args:
            user_context: InternalUserContext instance

        Returns:
            ActionContext instance
        """
        return cls(
            user_id=str(user_context.user_id),
            tenant_id=user_context.tenant_id or user_context.active_tenant_id,
            site_id=user_context.site_id or user_context.active_site_id,
            role_name=user_context.role_name,
            permissions=set(user_context.permissions),
            is_platform_admin=user_context.is_platform_admin,
        )

    def can_perform(self, action_type: str) -> bool:
        """Check if this context can perform an action."""
        return can_perform_action(self.permissions, action_type, self.role_name)

    def can_commit(self, draft_created_by: str, action_type: str) -> tuple[bool, str]:
        """Check if this context can commit a draft."""
        return can_commit_draft(
            self.user_id,
            self.permissions,
            self.role_name,
            draft_created_by,
            action_type,
        )
