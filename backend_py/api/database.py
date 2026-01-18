"""
SOLVEREIGN V3.3a API - Database Manager
=======================================

Async PostgreSQL connection management with psycopg3.
"""

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .logging_config import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """
    Async database connection pool manager.

    Features:
    - Connection pooling with psycopg_pool
    - Dict-row factory for easy access
    - Transaction context managers
    - Advisory lock support
    """

    def __init__(self):
        self._pool: Optional[AsyncConnectionPool] = None

    @property
    def pool(self) -> Optional[AsyncConnectionPool]:
        """Access to the underlying connection pool."""
        return self._pool

    async def initialize(self) -> None:
        """Initialize the connection pool."""
        self._pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=settings.database_pool_size,
            kwargs={"row_factory": dict_row},
        )
        await self._pool.wait()
        logger.info(
            "database_pool_created",
            extra={
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
            }
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("database_pool_closed")

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        """
        Get a connection from the pool.

        Usage:
            async with db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT ...")
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def tenant_connection(
        self, tenant_id: int
    ) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        """
        Get a connection with RLS tenant context already set.

        CRITICAL: Use this instead of connection() for all tenant-scoped operations.
        Sets app.current_tenant_id at connection acquire time, ensuring RLS
        is enforced for the entire connection lifetime.

        Usage:
            async with db.tenant_connection(tenant_id) as conn:
                async with conn.cursor() as cur:
                    # RLS already active - only sees tenant's data
                    await cur.execute("SELECT * FROM plans")
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.connection() as conn:
            # Set dual tenant context IMMEDIATELY on this connection
            # P0 FIX (migration 061): Uses auth.set_dual_tenant_context() which sets:
            #   - app.current_tenant_id_int (INTEGER)
            #   - app.current_tenant_id_uuid (UUID, auto-mapped if available)
            #   - app.current_tenant_id (legacy, for backward compat)
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT auth.set_dual_tenant_context(%s, %s, %s)",
                    (tenant_id, None, False)
                )
            logger.debug(
                "rls_context_set",
                extra={"tenant_id": tenant_id, "connection_id": id(conn)}
            )
            yield conn
            # Connection returns to pool - RLS setting is cleared on next use

    @asynccontextmanager
    async def core_tenant_transaction(
        self,
        tenant_id: str,
        site_id: Optional[str] = None,
        is_platform_admin: bool = False
    ) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        """
        Get a connection with transaction and core.tenants RLS context.

        Uses core.set_tenant_context() to set UUID-based tenant context
        for the new core schema tables.

        Usage:
            async with db.core_tenant_transaction(tenant_uuid, site_uuid) as conn:
                await conn.execute("SELECT * FROM core.sites")
                # Only sees current tenant's data
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.connection() as conn:
            async with conn.transaction():
                # Set core RLS context within transaction
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT core.set_tenant_context(%s, %s, %s)",
                        (tenant_id, site_id, is_platform_admin)
                    )
                logger.debug(
                    "core_rls_context_set",
                    extra={
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "is_platform_admin": is_platform_admin,
                        "connection_id": id(conn)
                    }
                )
                yield conn

    @asynccontextmanager
    async def tenant_transaction(
        self, tenant_id: int
    ) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        """
        Get a connection with transaction and RLS tenant context.

        Usage:
            async with db.tenant_transaction(tenant_id) as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
                # Commits on success, rolls back on exception
        """
        async with self.tenant_connection(tenant_id) as conn:
            async with conn.transaction():
                yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        """
        Get a connection with automatic transaction management.

        Usage:
            async with db.transaction() as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
                # Commits on success, rolls back on exception
        """
        async with self.connection() as conn:
            async with conn.transaction():
                yield conn


# =============================================================================
# TENANT OPERATIONS
# =============================================================================

async def get_tenant_by_api_key(db: DatabaseManager, api_key: str) -> Optional[dict]:
    """
    Look up tenant by API key hash.

    Uses SECURITY DEFINER function to bypass RLS (required for auth).
    The function is defined in migration 025 (025_tenants_rls_fix.sql).

    Args:
        db: Database manager
        api_key: Raw API key (will be hashed)

    Returns:
        Tenant dict or None if not found

    Security Note:
        This is called BEFORE tenant context is established.
        The get_tenant_by_api_key_hash() function uses SECURITY DEFINER
        to bypass RLS and allow authentication lookups.
    """
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Use SECURITY DEFINER function to bypass RLS for auth lookup
            # This function is defined in migration 025 and returns:
            # (id, name, is_active, metadata, created_at)
            await cur.execute(
                "SELECT * FROM get_tenant_by_api_key_hash(%s)",
                (api_key_hash,)
            )
            return await cur.fetchone()


async def get_tenant_by_id(db: DatabaseManager, tenant_id: int) -> Optional[dict]:
    """Get tenant by ID."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, is_active, metadata, created_at FROM tenants WHERE id = %s",
                (tenant_id,)
            )
            return await cur.fetchone()


# =============================================================================
# CORE TENANT OPERATIONS (UUID-based from core.tenants)
# =============================================================================

async def get_core_tenant_by_code(db: DatabaseManager, tenant_code: str) -> Optional[dict]:
    """
    Get tenant from core.tenants by code.

    Args:
        db: Database manager
        tenant_code: URL-safe tenant code (e.g., 'rohlik', 'mediamarkt')

    Returns:
        Tenant dict with UUID id, or None if not found
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, tenant_code, name, is_active, metadata, created_at, updated_at
                FROM core.tenants
                WHERE tenant_code = %s AND is_active = TRUE
                """,
                (tenant_code,)
            )
            return await cur.fetchone()


async def get_core_tenant_by_id(db: DatabaseManager, tenant_id: str) -> Optional[dict]:
    """Get tenant from core.tenants by UUID."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, tenant_code, name, is_active, metadata, created_at, updated_at
                FROM core.tenants
                WHERE id = %s AND is_active = TRUE
                """,
                (tenant_id,)
            )
            return await cur.fetchone()


async def get_core_sites_for_tenant(db: DatabaseManager, tenant_id: str) -> list[dict]:
    """Get all active sites for a tenant."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, site_code, name, timezone, is_active, metadata, created_at, updated_at
                FROM core.sites
                WHERE tenant_id = %s AND is_active = TRUE
                ORDER BY site_code
                """,
                (tenant_id,)
            )
            return await cur.fetchall()


async def get_core_site_by_code(
    db: DatabaseManager, tenant_id: str, site_code: str
) -> Optional[dict]:
    """Get a specific site by tenant and site code."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, site_code, name, timezone, is_active, metadata, created_at, updated_at
                FROM core.sites
                WHERE tenant_id = %s AND site_code = %s AND is_active = TRUE
                """,
                (tenant_id, site_code)
            )
            return await cur.fetchone()


async def get_core_entitlements_for_tenant(db: DatabaseManager, tenant_id: str) -> list[dict]:
    """Get all entitlements for a tenant."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, pack_id, is_enabled, config, valid_from, valid_until,
                       created_at, updated_at
                FROM core.tenant_entitlements
                WHERE tenant_id = %s
                ORDER BY pack_id
                """,
                (tenant_id,)
            )
            return await cur.fetchall()


async def check_core_entitlement(
    db: DatabaseManager, tenant_id: str, pack_id: str
) -> bool:
    """Check if tenant has active entitlement for a pack."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.has_entitlement(%s, %s)",
                (tenant_id, pack_id)
            )
            result = await cur.fetchone()
            return result["has_entitlement"] if result else False


async def set_core_tenant_context(
    conn: psycopg.AsyncConnection,
    tenant_id: str,
    site_id: Optional[str] = None,
    is_platform_admin: bool = False
) -> None:
    """
    Set transaction-local tenant context using core.set_tenant_context.

    CRITICAL: This uses SET LOCAL (transaction-scoped) for RLS security.
    Must be called at the start of each request within a transaction.

    Args:
        conn: Active connection (should be in a transaction)
        tenant_id: UUID of tenant (from core.tenants)
        site_id: Optional UUID of site (from core.sites)
        is_platform_admin: If True, bypasses tenant RLS policies
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT core.set_tenant_context(%s, %s, %s)",
            (tenant_id, site_id, is_platform_admin)
        )
    logger.debug(
        "core_rls_context_set",
        extra={
            "tenant_id": tenant_id,
            "site_id": site_id,
            "is_platform_admin": is_platform_admin,
            "connection_id": id(conn)
        }
    )


# =============================================================================
# ORGANIZATION OPERATIONS (from core.organizations)
# =============================================================================

async def get_organization_by_code(db: DatabaseManager, org_code: str) -> Optional[dict]:
    """
    Get organization from core.organizations by code.

    Args:
        db: Database manager
        org_code: URL-safe org code (e.g., 'lts')

    Returns:
        Organization dict with UUID id, or None if not found
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, org_code, name, is_active, metadata, created_at, updated_at
                FROM core.organizations
                WHERE org_code = %s AND is_active = TRUE
                """,
                (org_code,)
            )
            return await cur.fetchone()


async def get_organization_by_id(db: DatabaseManager, org_id: str) -> Optional[dict]:
    """Get organization from core.organizations by UUID."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, org_code, name, is_active, metadata, created_at, updated_at
                FROM core.organizations
                WHERE id = %s AND is_active = TRUE
                """,
                (org_id,)
            )
            return await cur.fetchone()


async def get_tenants_for_organization(db: DatabaseManager, org_id: str) -> list[dict]:
    """Get all tenants belonging to an organization."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, tenant_code, name, is_active, metadata, created_at, updated_at
                FROM core.tenants
                WHERE owner_org_id = %s
                ORDER BY tenant_code
                """,
                (org_id,)
            )
            return await cur.fetchall()


async def get_organization_for_tenant(db: DatabaseManager, tenant_id: str) -> Optional[dict]:
    """Get the organization that owns a tenant."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT o.id, o.org_code, o.name, o.is_active, o.metadata, o.created_at, o.updated_at
                FROM core.organizations o
                JOIN core.tenants t ON t.owner_org_id = o.id
                WHERE t.id = %s
                """,
                (tenant_id,)
            )
            return await cur.fetchone()


# =============================================================================
# ESCALATION OPERATIONS (from core.service_status)
# =============================================================================

async def record_escalation(
    db: DatabaseManager,
    scope_type: str,
    scope_id: Optional[str],
    reason_code: str,
    details: Optional[dict] = None
) -> str:
    """
    Record a new escalation event.

    Args:
        db: Database manager
        scope_type: platform|org|tenant|site
        scope_id: UUID of scope (None for platform)
        reason_code: Reason code from registry
        details: Additional context

    Returns:
        UUID of created escalation
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )
            await cur.execute(
                """
                SELECT core.record_escalation(%s::core.scope_type, %s, %s, %s)
                """,
                (scope_type, scope_id, reason_code, details or {})
            )
            result = await cur.fetchone()
            return str(result["record_escalation"])


async def resolve_escalation(
    db: DatabaseManager,
    scope_type: str,
    scope_id: Optional[str],
    reason_code: str,
    resolved_by: str = "system"
) -> int:
    """
    Resolve an escalation event.

    Returns:
        Number of resolved escalations
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )
            await cur.execute(
                """
                SELECT core.resolve_escalation(%s::core.scope_type, %s, %s, %s)
                """,
                (scope_type, scope_id, reason_code, resolved_by)
            )
            result = await cur.fetchone()
            return result["resolve_escalation"]


async def is_scope_blocked(
    db: DatabaseManager,
    scope_type: str,
    scope_id: Optional[str] = None
) -> bool:
    """Check if a scope has active S0/S1 blocks."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT core.is_scope_blocked(%s::core.scope_type, %s)
                """,
                (scope_type, scope_id)
            )
            result = await cur.fetchone()
            return result["is_scope_blocked"] if result else False


async def is_scope_degraded(
    db: DatabaseManager,
    scope_type: str,
    scope_id: Optional[str] = None
) -> bool:
    """Check if a scope has any degradation (S0-S2)."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT core.is_scope_degraded(%s::core.scope_type, %s)
                """,
                (scope_type, scope_id)
            )
            result = await cur.fetchone()
            return result["is_scope_degraded"] if result else False


async def record_security_event(
    db: DatabaseManager,
    event_type: str,
    severity: str,
    source_ip: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    details: Optional[dict] = None
) -> str:
    """
    Record a security event to the audit log.

    Args:
        db: Database manager
        event_type: Type of event (PLATFORM_ADMIN_SPOOF, RLS_VIOLATION, etc.)
        severity: S0|S1|S2|S3
        source_ip: Client IP address
        tenant_id: Affected tenant UUID (optional)
        user_id: User identifier (optional)
        request_path: Request path
        request_method: HTTP method
        details: Additional context

    Returns:
        UUID of created event
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO core.security_events (
                    event_type, severity, source_ip, tenant_id, user_id,
                    request_path, request_method, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    event_type, severity, source_ip, tenant_id, user_id,
                    request_path, request_method, details or {}
                )
            )
            result = await cur.fetchone()
            return str(result["id"])


# =============================================================================
# ADVISORY LOCK OPERATIONS
# =============================================================================

def compute_lock_key(tenant_id: int, forecast_id: int) -> int:
    """
    Compute advisory lock key from tenant + forecast.

    Uses bit shifting to create unique key:
    - Upper 32 bits: tenant_id
    - Lower 32 bits: forecast_id
    """
    return (tenant_id << 32) | forecast_id


async def try_acquire_solve_lock(
    conn: psycopg.AsyncConnection,
    tenant_id: int,
    forecast_id: int
) -> bool:
    """
    Try to acquire advisory lock for solving (non-blocking).

    Returns:
        True if lock acquired, False if already held
    """
    lock_key = compute_lock_key(tenant_id, forecast_id)

    async with conn.cursor() as cur:
        await cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
        result = await cur.fetchone()
        return result["pg_try_advisory_lock"] if result else False


async def release_solve_lock(
    conn: psycopg.AsyncConnection,
    tenant_id: int,
    forecast_id: int
) -> bool:
    """Release advisory lock after solving."""
    lock_key = compute_lock_key(tenant_id, forecast_id)

    async with conn.cursor() as cur:
        await cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        result = await cur.fetchone()
        return result["pg_advisory_unlock"] if result else False


async def is_solve_locked(
    conn: psycopg.AsyncConnection,
    tenant_id: int,
    forecast_id: int
) -> bool:
    """Check if forecast is currently being solved."""
    lock_key = compute_lock_key(tenant_id, forecast_id)
    objid = lock_key & 0xFFFFFFFF
    classid = lock_key >> 32

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_locks
                WHERE locktype = 'advisory'
                  AND objid = %s
                  AND classid = %s
            )
            """,
            (objid, classid)
        )
        result = await cur.fetchone()
        return result["exists"] if result else False


# =============================================================================
# IDEMPOTENCY OPERATIONS
# =============================================================================

async def check_idempotency(
    conn: psycopg.AsyncConnection,
    tenant_id: int,
    idempotency_key: str,
    endpoint: str,
    request_hash: str
) -> dict:
    """
    Check idempotency key status.

    Returns:
        {
            "status": "NEW" | "HIT" | "MISMATCH",
            "cached_response": {...} | None,
            "cached_status": int | None
        }
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT request_hash, response_status, response_body
            FROM idempotency_keys
            WHERE tenant_id = %s
              AND idempotency_key = %s
              AND endpoint = %s
              AND expires_at > NOW()
            """,
            (tenant_id, idempotency_key, endpoint)
        )
        row = await cur.fetchone()

        if not row:
            return {"status": "NEW", "cached_response": None, "cached_status": None}

        if row["request_hash"] != request_hash:
            return {"status": "MISMATCH", "cached_response": None, "cached_status": None}

        return {
            "status": "HIT",
            "cached_response": row["response_body"],
            "cached_status": row["response_status"]
        }


async def record_idempotency(
    conn: psycopg.AsyncConnection,
    tenant_id: int,
    idempotency_key: str,
    endpoint: str,
    method: str,
    request_hash: str,
    response_status: int,
    response_body: dict,
    ttl_hours: int = 24
) -> int:
    """Record successful response for idempotency replay."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO idempotency_keys (
                tenant_id, idempotency_key, endpoint, method,
                request_hash, response_status, response_body, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW() + INTERVAL '%s hours')
            ON CONFLICT (tenant_id, idempotency_key, endpoint)
            DO UPDATE SET
                response_status = EXCLUDED.response_status,
                response_body = EXCLUDED.response_body
            RETURNING id
            """,
            (
                tenant_id, idempotency_key, endpoint, method,
                request_hash, response_status, response_body, ttl_hours
            )
        )
        result = await cur.fetchone()
        return result["id"] if result else 0
