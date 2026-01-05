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
            # Set RLS context IMMEDIATELY on this connection
            # Uses SET LOCAL so it's transaction-scoped and cleared on commit/rollback
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT set_config('app.current_tenant_id', %s, false)",
                    (str(tenant_id),)
                )
            logger.debug(
                "rls_context_set",
                extra={"tenant_id": tenant_id, "connection_id": id(conn)}
            )
            yield conn
            # Connection returns to pool - RLS setting is cleared on next use

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

    Args:
        db: Database manager
        api_key: Raw API key (will be hashed)

    Returns:
        Tenant dict or None if not found
    """
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, name, is_active, metadata, created_at
                FROM tenants
                WHERE api_key_hash = %s
                """,
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
