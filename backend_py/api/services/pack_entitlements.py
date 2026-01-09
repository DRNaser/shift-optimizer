"""
SOLVEREIGN V3.7 - Pack Entitlements Service
============================================

Provides pack activation guards for multi-tenant SaaS:
- Check if tenant has pack enabled
- Log access attempts (audit trail)
- Block disabled pack access with 403

Usage:
    from backend_py.api.services.pack_entitlements import PackEntitlementService

    service = PackEntitlementService(db)
    if not await service.is_pack_enabled(tenant_id, "routing"):
        raise HTTPException(status_code=403, detail="Pack not enabled")
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional

from fastapi import HTTPException, status


class PackAccessResult(str, Enum):
    """Result of pack access check."""
    ALLOWED = "ALLOWED"
    DENIED_NOT_ENABLED = "DENIED_NOT_ENABLED"
    DENIED_SUSPENDED = "DENIED_SUSPENDED"
    DENIED_EXPIRED = "DENIED_EXPIRED"


@dataclass
class PackEntitlement:
    """Pack entitlement record."""
    pack_id: str
    is_enabled: bool
    config: Optional[Dict] = None
    expires_at: Optional[datetime] = None
    suspended: bool = False
    suspended_reason: Optional[str] = None


@dataclass
class PackAccessEvent:
    """Audit event for pack access."""
    tenant_id: str
    pack_id: str
    result: PackAccessResult
    endpoint: str
    timestamp: datetime
    details: Optional[Dict] = None


class PackEntitlementService:
    """
    Service for managing pack entitlements.

    Provides:
    - Entitlement checking with caching
    - Audit logging for access attempts
    - Configuration retrieval for enabled packs
    """

    # Known packs (for validation)
    KNOWN_PACKS = {
        "routing": "Routing optimization pack",
        "roster": "Roster/shift scheduling pack",
        "analytics": "Analytics and reporting pack",
        "premium": "Premium features pack"
    }

    def __init__(self, db_manager=None):
        self.db = db_manager
        self._cache: Dict[str, Dict[str, PackEntitlement]] = {}

    async def is_pack_enabled(
        self,
        tenant_id: str,
        pack_id: str,
        check_expiry: bool = True
    ) -> bool:
        """
        Check if pack is enabled for tenant.

        Args:
            tenant_id: Tenant UUID or code
            pack_id: Pack identifier (e.g., 'routing', 'roster')
            check_expiry: Also check if entitlement has expired

        Returns:
            True if pack is enabled and not expired/suspended
        """
        entitlement = await self.get_entitlement(tenant_id, pack_id)

        if not entitlement:
            return False

        if not entitlement.is_enabled:
            return False

        if entitlement.suspended:
            return False

        if check_expiry and entitlement.expires_at:
            if datetime.utcnow() > entitlement.expires_at:
                return False

        return True

    async def get_entitlement(
        self,
        tenant_id: str,
        pack_id: str
    ) -> Optional[PackEntitlement]:
        """
        Get pack entitlement for tenant.

        Args:
            tenant_id: Tenant UUID or code
            pack_id: Pack identifier

        Returns:
            PackEntitlement or None if not found
        """
        # Check cache first
        cache_key = f"{tenant_id}:{pack_id}"
        if tenant_id in self._cache and pack_id in self._cache.get(tenant_id, {}):
            return self._cache[tenant_id][pack_id]

        if not self.db:
            return None

        try:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT
                            pack_id,
                            is_enabled,
                            config,
                            expires_at,
                            suspended,
                            suspended_reason
                        FROM core.tenant_entitlements
                        WHERE tenant_id = %s AND pack_id = %s
                    """, (tenant_id, pack_id))

                    row = await cur.fetchone()

                    if not row:
                        return None

                    entitlement = PackEntitlement(
                        pack_id=row["pack_id"],
                        is_enabled=row["is_enabled"],
                        config=row.get("config"),
                        expires_at=row.get("expires_at"),
                        suspended=row.get("suspended", False),
                        suspended_reason=row.get("suspended_reason")
                    )

                    # Cache result
                    if tenant_id not in self._cache:
                        self._cache[tenant_id] = {}
                    self._cache[tenant_id][pack_id] = entitlement

                    return entitlement

        except Exception:
            # If DB query fails, return None (fail closed)
            return None

    async def get_all_entitlements(
        self,
        tenant_id: str
    ) -> Dict[str, PackEntitlement]:
        """
        Get all pack entitlements for tenant.

        Args:
            tenant_id: Tenant UUID or code

        Returns:
            Dict mapping pack_id to PackEntitlement
        """
        if not self.db:
            return {}

        try:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT
                            pack_id,
                            is_enabled,
                            config,
                            expires_at,
                            suspended,
                            suspended_reason
                        FROM core.tenant_entitlements
                        WHERE tenant_id = %s
                    """, (tenant_id,))

                    rows = await cur.fetchall()

                    entitlements = {}
                    for row in rows:
                        entitlements[row["pack_id"]] = PackEntitlement(
                            pack_id=row["pack_id"],
                            is_enabled=row["is_enabled"],
                            config=row.get("config"),
                            expires_at=row.get("expires_at"),
                            suspended=row.get("suspended", False),
                            suspended_reason=row.get("suspended_reason")
                        )

                    return entitlements

        except Exception:
            return {}

    async def check_access(
        self,
        tenant_id: str,
        pack_id: str,
        endpoint: str,
        log_event: bool = True
    ) -> PackAccessResult:
        """
        Check pack access and optionally log the attempt.

        Args:
            tenant_id: Tenant UUID or code
            pack_id: Pack identifier
            endpoint: API endpoint being accessed
            log_event: Whether to log the access attempt

        Returns:
            PackAccessResult indicating allow/deny reason
        """
        entitlement = await self.get_entitlement(tenant_id, pack_id)

        if not entitlement:
            result = PackAccessResult.DENIED_NOT_ENABLED
        elif not entitlement.is_enabled:
            result = PackAccessResult.DENIED_NOT_ENABLED
        elif entitlement.suspended:
            result = PackAccessResult.DENIED_SUSPENDED
        elif entitlement.expires_at and datetime.utcnow() > entitlement.expires_at:
            result = PackAccessResult.DENIED_EXPIRED
        else:
            result = PackAccessResult.ALLOWED

        if log_event:
            await self._log_access_event(
                tenant_id=tenant_id,
                pack_id=pack_id,
                result=result,
                endpoint=endpoint
            )

        return result

    async def _log_access_event(
        self,
        tenant_id: str,
        pack_id: str,
        result: PackAccessResult,
        endpoint: str
    ):
        """Log pack access attempt to audit table."""
        if not self.db:
            return

        try:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    # Only log denied attempts to reduce noise
                    if result != PackAccessResult.ALLOWED:
                        await cur.execute("""
                            INSERT INTO core.security_events
                            (event_type, severity, request_path, details)
                            VALUES (
                                'PACK_ACCESS_DENIED',
                                'S3',
                                %s,
                                %s
                            )
                        """, (
                            endpoint,
                            json.dumps({
                                "tenant_id": tenant_id,
                                "pack_id": pack_id,
                                "result": result.value
                            })
                        ))
                        await conn.commit()

        except Exception:
            # Don't fail on audit log errors
            pass

    def clear_cache(self, tenant_id: Optional[str] = None):
        """Clear entitlement cache."""
        if tenant_id:
            self._cache.pop(tenant_id, None)
        else:
            self._cache.clear()


def require_pack(pack_id: str, log_access: bool = True):
    """
    Dependency factory that enforces pack entitlement.

    Enhanced version with audit logging and detailed error messages.

    Usage:
        @router.post("/routing/solve")
        async def solve(
            request: Request,
            tenant: CoreTenantContext = Depends(get_core_tenant),
            _: None = Depends(require_pack("routing"))
        ):
            ...

    Args:
        pack_id: Pack identifier to check
        log_access: Whether to log access attempts

    Returns:
        Dependency function that raises 403 if pack not enabled
    """
    from fastapi import Request, Depends
    from ..dependencies import CoreTenantContext, get_core_tenant

    async def check_pack_entitlement(
        request: Request,
        tenant: CoreTenantContext = Depends(get_core_tenant),
    ):
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "unauthorized",
                    "message": "Tenant context required for pack access"
                }
            )

        # Get entitlements from context
        entitlements = tenant.entitlements or {}
        pack_entitlement = entitlements.get(pack_id, {})

        # Check if enabled
        if not pack_entitlement.get("is_enabled", False):
            # Log denied access
            if log_access and hasattr(request.app.state, "db"):
                service = PackEntitlementService(request.app.state.db)
                await service._log_access_event(
                    tenant_id=tenant.tenant_id,
                    pack_id=pack_id,
                    result=PackAccessResult.DENIED_NOT_ENABLED,
                    endpoint=str(request.url.path)
                )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "pack_not_enabled",
                    "message": f"Pack '{pack_id}' is not enabled for tenant '{tenant.tenant_code}'",
                    "pack_id": pack_id,
                    "tenant_code": tenant.tenant_code,
                    "action": "Contact your administrator to enable this pack"
                }
            )

        return True

    return check_pack_entitlement


def get_pack_config(pack_id: str):
    """
    Dependency factory to get pack configuration.

    Usage:
        @router.get("/routing/config")
        async def get_config(
            tenant: CoreTenantContext = Depends(get_core_tenant),
            config: dict = Depends(get_pack_config("routing"))
        ):
            return config
    """
    from fastapi import Depends
    from ..dependencies import CoreTenantContext, get_core_tenant

    async def get_config(
        tenant: CoreTenantContext = Depends(get_core_tenant),
    ) -> Dict[str, Any]:
        if not tenant:
            return {}

        entitlements = tenant.entitlements or {}
        pack_entitlement = entitlements.get(pack_id, {})

        if not pack_entitlement.get("is_enabled", False):
            return {}

        return pack_entitlement.get("config", {})

    return get_config
