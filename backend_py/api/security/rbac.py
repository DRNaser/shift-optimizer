"""
SOLVEREIGN V3.3b - Role-Based Access Control (RBAC)
====================================================

Hierarchical RBAC with:
- 5 role levels (VIEWER → SUPER_ADMIN)
- Fine-grained permissions
- Cross-tenant prevention
- Audit logging on denial

Role Hierarchy:
    SUPER_ADMIN (Solvereign Ops)
        └── TENANT_ADMIN (Customer IT)
            ├── PLAN_APPROVER (Betriebsleiter)
            │   └── DISPATCHER (Schichtplaner)
            │       └── VIEWER (Read-only)
            └── DRIVER (Mobile app - future)
"""

import logging
from enum import Enum
from typing import List, Set, Optional, Callable
from dataclasses import dataclass, field
from functools import wraps

from fastapi import Request, HTTPException, status, Depends

from .jwt import JWTClaims, require_jwt

logger = logging.getLogger(__name__)


# =============================================================================
# PERMISSIONS
# =============================================================================

class Permission(str, Enum):
    """
    Fine-grained permissions.

    Naming convention: {resource}:{action}
    """
    # Forecast
    FORECAST_READ = "forecast:read"
    FORECAST_WRITE = "forecast:write"
    FORECAST_DELETE = "forecast:delete"

    # Plan
    PLAN_READ = "plan:read"
    PLAN_SOLVE = "plan:solve"
    PLAN_APPROVE = "plan:approve"
    PLAN_LOCK = "plan:lock"
    PLAN_UNLOCK = "plan:unlock"
    PLAN_DELETE = "plan:delete"

    # Driver
    DRIVER_READ = "driver:read"
    DRIVER_WRITE = "driver:write"
    DRIVER_DELETE = "driver:delete"
    DRIVER_PII_READ = "driver:pii:read"    # Sensitive: access to PII

    # Simulation
    SIMULATION_READ = "simulation:read"
    SIMULATION_RUN = "simulation:run"

    # Export
    EXPORT_READ = "export:read"
    EXPORT_BULK = "export:bulk"            # Sensitive: bulk data export

    # User Management
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"

    # Tenant Configuration
    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"
    TENANT_DELETE = "tenant:delete"

    # System (Super Admin only)
    SYSTEM_ADMIN = "system:admin"
    SYSTEM_METRICS = "system:metrics"
    SYSTEM_AUDIT = "system:audit"


# =============================================================================
# ROLES
# =============================================================================

class Role(str, Enum):
    """
    Role definitions with implicit permissions.
    """
    VIEWER = "viewer"
    DISPATCHER = "dispatcher"
    PLAN_APPROVER = "plan_approver"
    TENANT_ADMIN = "tenant_admin"
    SUPER_ADMIN = "super_admin"
    DRIVER = "driver"  # Future: mobile app


# Role → Permissions mapping
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.FORECAST_READ,
        Permission.PLAN_READ,
        Permission.DRIVER_READ,
        Permission.SIMULATION_READ,
    },

    Role.DISPATCHER: {
        # All VIEWER permissions
        Permission.FORECAST_READ,
        Permission.PLAN_READ,
        Permission.DRIVER_READ,
        Permission.SIMULATION_READ,
        # Plus write permissions
        Permission.FORECAST_WRITE,
        Permission.PLAN_SOLVE,
        Permission.SIMULATION_RUN,
        Permission.EXPORT_READ,
    },

    Role.PLAN_APPROVER: {
        # All DISPATCHER permissions
        Permission.FORECAST_READ,
        Permission.FORECAST_WRITE,
        Permission.PLAN_READ,
        Permission.PLAN_SOLVE,
        Permission.DRIVER_READ,
        Permission.SIMULATION_READ,
        Permission.SIMULATION_RUN,
        Permission.EXPORT_READ,
        # Plus approval permissions
        Permission.PLAN_APPROVE,
        Permission.PLAN_LOCK,
        Permission.EXPORT_BULK,
    },

    Role.TENANT_ADMIN: {
        # All PLAN_APPROVER permissions
        Permission.FORECAST_READ,
        Permission.FORECAST_WRITE,
        Permission.FORECAST_DELETE,
        Permission.PLAN_READ,
        Permission.PLAN_SOLVE,
        Permission.PLAN_APPROVE,
        Permission.PLAN_LOCK,
        Permission.PLAN_UNLOCK,
        Permission.PLAN_DELETE,
        Permission.DRIVER_READ,
        Permission.DRIVER_WRITE,
        Permission.DRIVER_DELETE,
        Permission.DRIVER_PII_READ,
        Permission.SIMULATION_READ,
        Permission.SIMULATION_RUN,
        Permission.EXPORT_READ,
        Permission.EXPORT_BULK,
        # Plus admin permissions
        Permission.USER_READ,
        Permission.USER_WRITE,
        Permission.USER_DELETE,
        Permission.TENANT_READ,
        Permission.TENANT_WRITE,
    },

    Role.SUPER_ADMIN: {
        # All permissions
        *Permission,
    },

    Role.DRIVER: {
        # Limited mobile app permissions
        Permission.PLAN_READ,
    },
}


def get_permissions_for_roles(roles: List[str]) -> Set[str]:
    """
    Get all permissions for a list of roles.

    Combines permissions from all roles (union).
    """
    permissions: Set[str] = set()

    for role_name in roles:
        try:
            role = Role(role_name.lower())
            role_perms = ROLE_PERMISSIONS.get(role, set())
            permissions.update(p.value for p in role_perms)
        except ValueError:
            # Unknown role, skip
            logger.warning("unknown_role", extra={"role": role_name})
            continue

    return permissions


# =============================================================================
# PERMISSION CHECKER
# =============================================================================

@dataclass
class PermissionContext:
    """
    Permission check result with context.
    """
    claims: JWTClaims
    required: Set[str]
    granted: Set[str]
    missing: Set[str]
    passed: bool
    target_tenant_id: Optional[str] = None


class PermissionChecker:
    """
    Dependency for checking permissions.

    Features:
    - Role-based permission expansion
    - Fine-grained permission check
    - Cross-tenant prevention
    - Audit logging on denial

    Usage:
        @router.post("/plans/{plan_id}/lock")
        async def lock_plan(
            plan_id: int,
            auth: PermissionContext = Depends(
                PermissionChecker([Permission.PLAN_LOCK])
            )
        ):
            ...
    """

    def __init__(
        self,
        required_permissions: List[Permission],
        require_all: bool = True,
        require_mfa: bool = False,
    ):
        """
        Initialize permission checker.

        Args:
            required_permissions: List of required permissions
            require_all: If True, all permissions required. If False, any one.
            require_mfa: If True, MFA must be verified
        """
        self.required = {p.value for p in required_permissions}
        self.require_all = require_all
        self.require_mfa = require_mfa

    async def __call__(
        self,
        request: Request,
        claims: JWTClaims = Depends(require_jwt),
    ) -> PermissionContext:
        """
        Check permissions and return context.

        Raises 403 if permissions not granted.
        """
        # Check MFA if required
        if self.require_mfa and not claims.mfa_verified:
            await self._log_denial(
                request, claims, "MFA_REQUIRED",
                {"required": list(self.required)}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "MFA_REQUIRED",
                    "message": "This action requires MFA verification",
                }
            )

        # Get user's permissions (from JWT claims + role expansion)
        user_permissions = set(claims.permissions)

        # Expand roles to permissions
        role_permissions = get_permissions_for_roles(claims.roles)
        user_permissions.update(role_permissions)

        # Check permissions
        if self.require_all:
            missing = self.required - user_permissions
            passed = len(missing) == 0
        else:
            granted = self.required & user_permissions
            missing = self.required - granted if not granted else set()
            passed = len(granted) > 0

        # Create context
        context = PermissionContext(
            claims=claims,
            required=self.required,
            granted=user_permissions & self.required,
            missing=missing,
            passed=passed,
        )

        # Check cross-tenant access
        target_tenant = self._extract_target_tenant(request)
        if target_tenant and target_tenant != claims.tenant_id:
            # CRITICAL: Cross-tenant access attempt
            await self._log_denial(
                request, claims, "CROSS_TENANT_ACCESS",
                {
                    "source_tenant": claims.tenant_id,
                    "target_tenant": target_tenant,
                },
                severity="CRITICAL"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "CROSS_TENANT_ACCESS",
                    "message": "Access to other tenant's resources denied",
                }
            )

        context.target_tenant_id = target_tenant or claims.tenant_id

        # Handle permission denial
        if not passed:
            await self._log_denial(
                request, claims, "PERMISSION_DENIED",
                {
                    "required": list(self.required),
                    "missing": list(missing),
                    "roles": claims.roles,
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PERMISSION_DENIED",
                    "message": "Insufficient permissions",
                    "missing_permissions": list(missing),
                }
            )

        return context

    def _extract_target_tenant(self, request: Request) -> Optional[str]:
        """
        Extract target tenant from request.

        Checks:
        1. Path parameter (tenant_id)
        2. Query parameter (tenant_id)
        3. Request body (if JSON)
        """
        # Check path parameters
        if "tenant_id" in request.path_params:
            return str(request.path_params["tenant_id"])

        # Check query parameters
        if "tenant_id" in request.query_params:
            return request.query_params["tenant_id"]

        return None

    async def _log_denial(
        self,
        request: Request,
        claims: JWTClaims,
        event_type: str,
        details: dict,
        severity: str = "WARNING",
    ):
        """Log permission denial to security audit log."""
        from .audit import SecurityAuditLogger

        await SecurityAuditLogger.log(
            event_type=event_type,
            tenant_id=claims.tenant_id,
            user_id=claims.sub,
            severity=severity,
            ip_address=self._get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            details={
                **details,
                "path": request.url.path,
                "method": request.method,
            },
        )

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, respecting X-Forwarded-For."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"


# =============================================================================
# DECORATOR STYLE
# =============================================================================

def require_permissions(
    *permissions: Permission,
    require_all: bool = True,
    require_mfa: bool = False,
):
    """
    Decorator for permission-protected endpoints.

    Usage:
        @router.post("/plans/{plan_id}/lock")
        @require_permissions(Permission.PLAN_LOCK, Permission.PLAN_APPROVE)
        async def lock_plan(plan_id: int, request: Request):
            ...

    Note: Use Depends(PermissionChecker(...)) for access to PermissionContext.
    """
    checker = PermissionChecker(
        list(permissions),
        require_all=require_all,
        require_mfa=require_mfa,
    )

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from kwargs
            request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                raise RuntimeError("@require_permissions requires Request parameter")

            # Get claims from request state (set by auth middleware)
            claims = getattr(request.state, "jwt_claims", None)
            if not claims:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )

            # Check permissions
            await checker(request, claims)

            return await func(*args, **kwargs)

        return wrapper
    return decorator


# =============================================================================
# CONVENIENCE DEPENDENCIES
# =============================================================================

# Pre-configured permission checkers for common use cases
require_viewer = PermissionChecker([Permission.FORECAST_READ, Permission.PLAN_READ])
require_dispatcher = PermissionChecker([Permission.FORECAST_WRITE, Permission.PLAN_SOLVE])
require_approver = PermissionChecker([Permission.PLAN_APPROVE, Permission.PLAN_LOCK])
require_tenant_admin = PermissionChecker([Permission.USER_WRITE, Permission.TENANT_WRITE])
require_super_admin = PermissionChecker([Permission.SYSTEM_ADMIN])

# MFA-protected actions
require_plan_lock_mfa = PermissionChecker(
    [Permission.PLAN_LOCK],
    require_mfa=True
)
require_bulk_export_mfa = PermissionChecker(
    [Permission.EXPORT_BULK],
    require_mfa=True
)
