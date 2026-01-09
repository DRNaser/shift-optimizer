# =============================================================================
# SOLVEREIGN Routing Pack - Database Connection
# =============================================================================
# Synchronous PostgreSQL connection management for Celery workers.
#
# P0-2: Worker RLS/Tenant Isolation
# - Every operation uses tenant_transaction() for RLS enforcement
# - Advisory locks prevent concurrent solves on same scenario
# =============================================================================

from __future__ import annotations

import os
import hashlib
import logging
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.getenv(
    "SOLVEREIGN_DATABASE_URL",
    "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign"
)


# =============================================================================
# CONNECTION MANAGEMENT
# =============================================================================

@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """
    Get a raw database connection.

    WARNING: This does NOT set RLS context. Use tenant_connection() or
    tenant_transaction() for tenant-scoped operations.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
    """
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tenant_connection(tenant_id: int) -> Generator[psycopg.Connection, None, None]:
    """
    Get a connection with RLS tenant context set.

    CRITICAL: Use this for all tenant-scoped operations.
    Sets app.current_tenant_id which enables Row-Level Security.

    P0-2 FIX: Uses set_config(..., true) which is transaction-scoped (like SET LOCAL).
    This prevents tenant context leaking if connection pooling is added later.

    Usage:
        with tenant_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                # RLS is active - only sees this tenant's data
                cur.execute("SELECT * FROM routing_stops")
    """
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        # Set RLS context - transaction-scoped (P0-2: is_local=true)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true)",
                (str(tenant_id),)
            )
        logger.debug(
            f"RLS context set (transaction-scoped) for tenant_id={tenant_id}",
            extra={"tenant_id": tenant_id}
        )
        yield conn
    finally:
        conn.close()


@contextmanager
def tenant_transaction(tenant_id: int) -> Generator[psycopg.Connection, None, None]:
    """
    Get a connection with RLS context AND automatic transaction management.

    This is the PRIMARY entry point for Celery tasks.

    Features:
    - Sets RLS tenant context
    - Auto-commits on success
    - Auto-rollbacks on exception

    Usage:
        with tenant_transaction(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO routing_plans ...")
                cur.execute("INSERT INTO routing_assignments ...")
            # Commits on context exit

    Args:
        tenant_id: The tenant ID for RLS context

    Yields:
        psycopg.Connection with RLS context set
    """
    with tenant_connection(tenant_id) as conn:
        try:
            # Start transaction
            conn.execute("BEGIN")
            logger.debug(f"Transaction started for tenant_id={tenant_id}")

            yield conn

            # Commit on success
            conn.execute("COMMIT")
            logger.debug(f"Transaction committed for tenant_id={tenant_id}")

        except Exception as e:
            # Rollback on failure
            conn.execute("ROLLBACK")
            logger.error(
                f"Transaction rolled back for tenant_id={tenant_id}: {e}",
                extra={"tenant_id": tenant_id, "error": str(e)}
            )
            raise


# =============================================================================
# ADVISORY LOCKS
# =============================================================================

def compute_scenario_lock_key(tenant_id: int, scenario_id: str) -> int:
    """
    Compute advisory lock key for a scenario.

    Creates a unique 64-bit key from tenant_id + scenario_id hash.
    This prevents concurrent solves on the same scenario.

    Args:
        tenant_id: The tenant ID
        scenario_id: The scenario UUID (string)

    Returns:
        64-bit integer lock key
    """
    # Hash the scenario_id to get a 32-bit integer
    scenario_hash = int(hashlib.md5(scenario_id.encode()).hexdigest()[:8], 16)

    # Combine: upper 32 bits = tenant_id, lower 32 bits = scenario hash
    return (tenant_id << 32) | scenario_hash


def try_acquire_scenario_lock(
    conn: psycopg.Connection,
    tenant_id: int,
    scenario_id: str
) -> bool:
    """
    Try to acquire advisory lock for solving (non-blocking).

    Use this at the start of solve_routing_scenario to prevent double-solve.

    Args:
        conn: Database connection
        tenant_id: The tenant ID
        scenario_id: The scenario UUID

    Returns:
        True if lock acquired, False if already held by another worker
    """
    lock_key = compute_scenario_lock_key(tenant_id, scenario_id)

    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
        result = cur.fetchone()

        if result and result["pg_try_advisory_lock"]:
            logger.info(
                f"Acquired solve lock for scenario {scenario_id}",
                extra={"tenant_id": tenant_id, "scenario_id": scenario_id, "lock_key": lock_key}
            )
            return True
        else:
            logger.warning(
                f"Failed to acquire lock - scenario {scenario_id} already being solved",
                extra={"tenant_id": tenant_id, "scenario_id": scenario_id, "lock_key": lock_key}
            )
            return False


def release_scenario_lock(
    conn: psycopg.Connection,
    tenant_id: int,
    scenario_id: str
) -> bool:
    """
    Release advisory lock after solving.

    Args:
        conn: Database connection
        tenant_id: The tenant ID
        scenario_id: The scenario UUID

    Returns:
        True if lock was released, False otherwise
    """
    lock_key = compute_scenario_lock_key(tenant_id, scenario_id)

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        result = cur.fetchone()

        if result and result["pg_advisory_unlock"]:
            logger.info(
                f"Released solve lock for scenario {scenario_id}",
                extra={"tenant_id": tenant_id, "scenario_id": scenario_id}
            )
            return True
        else:
            logger.warning(
                f"Failed to release lock for scenario {scenario_id}",
                extra={"tenant_id": tenant_id, "scenario_id": scenario_id}
            )
            return False


def is_scenario_locked(
    conn: psycopg.Connection,
    tenant_id: int,
    scenario_id: str
) -> bool:
    """
    Check if a scenario is currently being solved.

    Args:
        conn: Database connection
        tenant_id: The tenant ID
        scenario_id: The scenario UUID

    Returns:
        True if locked, False if available
    """
    lock_key = compute_scenario_lock_key(tenant_id, scenario_id)
    objid = lock_key & 0xFFFFFFFF
    classid = lock_key >> 32

    with conn.cursor() as cur:
        cur.execute(
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
        result = cur.fetchone()
        return result["exists"] if result else False


# =============================================================================
# TENANT LOOKUP
# =============================================================================

def get_scenario_tenant_id(conn: psycopg.Connection, scenario_id: str) -> Optional[int]:
    """
    Get tenant_id for a scenario.

    This is called FIRST before setting RLS context, so uses raw connection.

    Args:
        conn: Database connection (no RLS needed)
        scenario_id: The scenario UUID

    Returns:
        tenant_id or None if not found
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tenant_id FROM routing_scenarios WHERE id = %s",
            (scenario_id,)
        )
        result = cur.fetchone()
        return result["tenant_id"] if result else None


def get_plan_tenant_id(conn: psycopg.Connection, plan_id: str) -> Optional[int]:
    """
    Get tenant_id for a plan.

    Args:
        conn: Database connection (no RLS needed)
        plan_id: The plan UUID

    Returns:
        tenant_id or None if not found
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tenant_id FROM routing_plans WHERE id = %s",
            (plan_id,)
        )
        result = cur.fetchone()
        return result["tenant_id"] if result else None
