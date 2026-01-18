"""
SOLVEREIGN V4.1 - Portal Repository
=====================================

Database operations for portal tokens, read receipts, and acknowledgments.

Security:
    - All queries use parameterized statements (no SQL injection)
    - Tenant isolation via RLS and explicit tenant_id filtering
    - Audit trail for all state-changing operations
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from .models import (
    TokenScope,
    TokenStatus,
    AckStatus,
    AckReasonCode,
    AckSource,
    DeliveryChannel,
    PortalToken,
    ReadReceipt,
    DriverAck,
    DriverView,
    SnapshotSupersede,
    PortalStatus,
    RateLimitResult,
    PortalAction,
)
from .token_service import PortalTokenRepository

logger = logging.getLogger(__name__)


# =============================================================================
# POSTGRESQL REPOSITORY
# =============================================================================

class PostgresPortalRepository(PortalTokenRepository):
    """
    PostgreSQL implementation of portal repository.

    All operations respect RLS via app.current_tenant_id setting.
    """

    def __init__(self, pool):
        """
        Initialize repository.

        Args:
            pool: asyncpg connection pool
        """
        self.pool = pool

    async def _set_tenant_context(self, conn, tenant_id: int) -> None:
        """Set dual tenant context for RLS (P0 fix: migration 061)."""
        await conn.execute(
            "SELECT auth.set_dual_tenant_context($1, $2, $3)",
            tenant_id, None, False
        )

    # =========================================================================
    # TOKEN OPERATIONS
    # =========================================================================

    async def save_token(self, token: PortalToken) -> PortalToken:
        """
        Save a new token to database.

        Args:
            token: PortalToken to save (without id)

        Returns:
            PortalToken with id populated
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, token.tenant_id)

            row = await conn.fetchrow(
                """
                INSERT INTO portal.portal_tokens (
                    tenant_id, site_id, snapshot_id, driver_id,
                    scope, jti_hash, issued_at, expires_at,
                    delivery_channel, outbox_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                token.tenant_id,
                token.site_id,
                token.snapshot_id,
                token.driver_id,
                token.scope.value,
                token.jti_hash,
                token.issued_at,
                token.expires_at,
                token.delivery_channel.value if token.delivery_channel else None,
                token.outbox_id,
            )
            token.id = row["id"]

            # Record audit
            await self._record_audit(
                conn,
                token.tenant_id,
                token.site_id,
                token.snapshot_id,
                token.driver_id,
                PortalAction.TOKEN_ISSUED,
                token.jti_hash,
            )

            return token

    async def get_by_jti_hash(self, jti_hash: str) -> Optional[PortalToken]:
        """
        Get token by jti_hash.

        Note: Does not filter by tenant (jti_hash is globally unique).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, site_id, snapshot_id, driver_id,
                       scope, jti_hash, issued_at, expires_at,
                       revoked_at, last_seen_at, delivery_channel
                FROM portal.portal_tokens
                WHERE jti_hash = $1
                """,
                jti_hash,
            )

            if not row:
                return None

            return PortalToken(
                id=row["id"],
                tenant_id=row["tenant_id"],
                site_id=row["site_id"],
                snapshot_id=str(row["snapshot_id"]),
                driver_id=row["driver_id"],
                scope=TokenScope(row["scope"]),
                jti_hash=row["jti_hash"],
                issued_at=row["issued_at"],
                expires_at=row["expires_at"],
                revoked_at=row["revoked_at"],
                last_seen_at=row["last_seen_at"],
                delivery_channel=DeliveryChannel(row["delivery_channel"]) if row["delivery_channel"] else None,
            )

    async def revoke_token(self, jti_hash: str) -> bool:
        """Revoke a token by setting revoked_at."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE portal.portal_tokens
                SET revoked_at = NOW()
                WHERE jti_hash = $1 AND revoked_at IS NULL
                """,
                jti_hash,
            )

            success = result.split()[-1] != "0"

            if success:
                # Get token details for audit
                row = await conn.fetchrow(
                    "SELECT tenant_id, site_id, snapshot_id, driver_id FROM portal.portal_tokens WHERE jti_hash = $1",
                    jti_hash,
                )
                if row:
                    await self._record_audit(
                        conn,
                        row["tenant_id"],
                        row["site_id"],
                        str(row["snapshot_id"]),
                        row["driver_id"],
                        PortalAction.TOKEN_REVOKED,
                        jti_hash,
                    )

            return success

    async def update_last_seen(self, jti_hash: str) -> bool:
        """Update last_seen_at timestamp."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE portal.portal_tokens
                SET last_seen_at = NOW()
                WHERE jti_hash = $1
                """,
                jti_hash,
            )
            return result.split()[-1] != "0"

    async def get_tokens_for_snapshot(
        self,
        tenant_id: int,
        snapshot_id: str,
    ) -> List[PortalToken]:
        """Get all tokens issued for a snapshot."""
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            rows = await conn.fetch(
                """
                SELECT id, tenant_id, site_id, snapshot_id, driver_id,
                       scope, jti_hash, issued_at, expires_at,
                       revoked_at, last_seen_at, delivery_channel
                FROM portal.portal_tokens
                WHERE tenant_id = $1 AND snapshot_id = $2
                ORDER BY issued_at DESC
                """,
                tenant_id,
                snapshot_id,
            )

            return [
                PortalToken(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    site_id=row["site_id"],
                    snapshot_id=str(row["snapshot_id"]),
                    driver_id=row["driver_id"],
                    scope=TokenScope(row["scope"]),
                    jti_hash=row["jti_hash"],
                    issued_at=row["issued_at"],
                    expires_at=row["expires_at"],
                    revoked_at=row["revoked_at"],
                    last_seen_at=row["last_seen_at"],
                    delivery_channel=DeliveryChannel(row["delivery_channel"]) if row["delivery_channel"] else None,
                )
                for row in rows
            ]

    # =========================================================================
    # READ RECEIPT OPERATIONS
    # =========================================================================

    async def record_read(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> ReadReceipt:
        """
        Record a read receipt (idempotent).

        Uses PostgreSQL's ON CONFLICT for atomic upsert.
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                INSERT INTO portal.read_receipts (
                    tenant_id, site_id, snapshot_id, driver_id,
                    first_read_at, last_read_at, read_count
                ) VALUES ($1, $2, $3, $4, NOW(), NOW(), 1)
                ON CONFLICT (snapshot_id, driver_id) DO UPDATE SET
                    last_read_at = NOW(),
                    read_count = portal.read_receipts.read_count + 1
                RETURNING id, first_read_at, last_read_at, read_count
                """,
                tenant_id,
                site_id,
                snapshot_id,
                driver_id,
            )

            is_first = row["read_count"] == 1

            # Record audit only on first read
            if is_first:
                await self._record_audit(
                    conn,
                    tenant_id,
                    site_id,
                    snapshot_id,
                    driver_id,
                    PortalAction.PLAN_READ,
                )

            return ReadReceipt(
                id=row["id"],
                tenant_id=tenant_id,
                site_id=site_id,
                snapshot_id=snapshot_id,
                driver_id=driver_id,
                first_read_at=row["first_read_at"],
                last_read_at=row["last_read_at"],
                read_count=row["read_count"],
            )

    async def get_read_receipt(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> Optional[ReadReceipt]:
        """Get read receipt for a driver and snapshot."""
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, site_id, snapshot_id, driver_id,
                       first_read_at, last_read_at, read_count
                FROM portal.read_receipts
                WHERE tenant_id = $1 AND snapshot_id = $2 AND driver_id = $3
                """,
                tenant_id,
                snapshot_id,
                driver_id,
            )

            if not row:
                return None

            return ReadReceipt(
                id=row["id"],
                tenant_id=row["tenant_id"],
                site_id=row["site_id"],
                snapshot_id=str(row["snapshot_id"]),
                driver_id=row["driver_id"],
                first_read_at=row["first_read_at"],
                last_read_at=row["last_read_at"],
                read_count=row["read_count"],
            )

    # =========================================================================
    # ACKNOWLEDGMENT OPERATIONS
    # =========================================================================

    async def record_ack(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
        status: AckStatus,
        reason_code: Optional[AckReasonCode] = None,
        free_text: Optional[str] = None,
        source: AckSource = AckSource.PORTAL,
        override_by: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> DriverAck:
        """
        Record driver acknowledgment.

        Idempotent: returns existing ack if already exists.
        Immutable: cannot modify after creation (except DISPATCHER_OVERRIDE).
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Check for existing ack
            existing = await conn.fetchrow(
                """
                SELECT id, status, ack_at, reason_code, free_text, source,
                       override_by, override_reason
                FROM portal.driver_ack
                WHERE tenant_id = $1 AND snapshot_id = $2 AND driver_id = $3
                """,
                tenant_id,
                snapshot_id,
                driver_id,
            )

            if existing:
                # Return existing (immutable)
                return DriverAck(
                    id=existing["id"],
                    tenant_id=tenant_id,
                    site_id=site_id,
                    snapshot_id=snapshot_id,
                    driver_id=driver_id,
                    status=AckStatus(existing["status"]),
                    ack_at=existing["ack_at"],
                    reason_code=AckReasonCode(existing["reason_code"]) if existing["reason_code"] else None,
                    free_text=existing["free_text"],
                    source=AckSource(existing["source"]),
                    override_by=existing["override_by"],
                    override_reason=existing["override_reason"],
                )

            # Insert new ack
            row = await conn.fetchrow(
                """
                INSERT INTO portal.driver_ack (
                    tenant_id, site_id, snapshot_id, driver_id,
                    status, ack_at, reason_code, free_text,
                    source, override_by, override_reason
                ) VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8, $9, $10)
                RETURNING id, ack_at
                """,
                tenant_id,
                site_id,
                snapshot_id,
                driver_id,
                status.value,
                reason_code.value if reason_code else None,
                free_text,
                source.value,
                override_by,
                override_reason,
            )

            # Record audit
            action = PortalAction.PLAN_ACCEPTED if status == AckStatus.ACCEPTED else PortalAction.PLAN_DECLINED
            await self._record_audit(
                conn,
                tenant_id,
                site_id,
                snapshot_id,
                driver_id,
                action,
                details={
                    "reason_code": reason_code.value if reason_code else None,
                    "source": source.value,
                },
            )

            return DriverAck(
                id=row["id"],
                tenant_id=tenant_id,
                site_id=site_id,
                snapshot_id=snapshot_id,
                driver_id=driver_id,
                status=status,
                ack_at=row["ack_at"],
                reason_code=reason_code,
                free_text=free_text,
                source=source,
                override_by=override_by,
                override_reason=override_reason,
            )

    async def get_ack(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> Optional[DriverAck]:
        """Get acknowledgment for a driver and snapshot."""
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, site_id, snapshot_id, driver_id,
                       status, ack_at, reason_code, free_text,
                       source, override_by, override_reason
                FROM portal.driver_ack
                WHERE tenant_id = $1 AND snapshot_id = $2 AND driver_id = $3
                """,
                tenant_id,
                snapshot_id,
                driver_id,
            )

            if not row:
                return None

            return DriverAck(
                id=row["id"],
                tenant_id=row["tenant_id"],
                site_id=row["site_id"],
                snapshot_id=str(row["snapshot_id"]),
                driver_id=row["driver_id"],
                status=AckStatus(row["status"]),
                ack_at=row["ack_at"],
                reason_code=AckReasonCode(row["reason_code"]) if row["reason_code"] else None,
                free_text=row["free_text"],
                source=AckSource(row["source"]),
                override_by=row["override_by"],
                override_reason=row["override_reason"],
            )

    async def override_ack(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_id: str,
        new_status: AckStatus,
        override_by: str,
        override_reason: str,
    ) -> DriverAck:
        """
        Override an existing ack (dispatcher override).

        Only allowed for existing PORTAL acks.
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Update existing ack
            row = await conn.fetchrow(
                """
                UPDATE portal.driver_ack
                SET status = $4,
                    source = 'DISPATCHER_OVERRIDE',
                    override_by = $5,
                    override_reason = $6
                WHERE tenant_id = $1 AND snapshot_id = $2 AND driver_id = $3
                AND source = 'PORTAL'
                RETURNING id, site_id, ack_at
                """,
                tenant_id,
                snapshot_id,
                driver_id,
                new_status.value,
                override_by,
                override_reason,
            )

            if not row:
                raise ValueError("Ack not found or already overridden")

            # Record audit
            await self._record_audit(
                conn,
                tenant_id,
                row["site_id"],
                snapshot_id,
                driver_id,
                PortalAction.ACK_OVERRIDE,
                details={
                    "new_status": new_status.value,
                    "override_by": override_by,
                },
                performed_by=override_by,
            )

            return DriverAck(
                id=row["id"],
                tenant_id=tenant_id,
                site_id=row["site_id"],
                snapshot_id=snapshot_id,
                driver_id=driver_id,
                status=new_status,
                ack_at=row["ack_at"],
                source=AckSource.DISPATCHER_OVERRIDE,
                override_by=override_by,
                override_reason=override_reason,
            )

    # =========================================================================
    # PORTAL STATUS (AGGREGATES)
    # =========================================================================

    async def get_portal_status(
        self,
        tenant_id: int,
        snapshot_id: str,
    ) -> PortalStatus:
        """
        Get aggregated portal status for a snapshot.

        Used by dispatchers to monitor acknowledgment progress.
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Use the DB function
            row = await conn.fetchrow(
                "SELECT * FROM portal.get_portal_status($1, $2)",
                tenant_id,
                snapshot_id,
            )

            status = PortalStatus(
                snapshot_id=snapshot_id,
                total_drivers=row["total_drivers"],
                unread_count=row["unread_count"],
                read_count=row["read_count"],
                accepted_count=row["accepted_count"],
                declined_count=row["declined_count"],
                pending_count=row["pending_count"],
            )

            # Get driver lists
            status.unread_drivers = await self._get_unread_drivers(conn, tenant_id, snapshot_id)
            status.unacked_drivers = await self._get_unacked_drivers(conn, tenant_id, snapshot_id)
            status.declined_drivers = await self._get_declined_drivers(conn, tenant_id, snapshot_id)

            return status

    async def _get_unread_drivers(
        self,
        conn,
        tenant_id: int,
        snapshot_id: str,
    ) -> List[str]:
        """Get list of drivers who haven't read the plan."""
        rows = await conn.fetch(
            """
            SELECT DISTINCT t.driver_id
            FROM portal.portal_tokens t
            LEFT JOIN portal.read_receipts r
                ON t.snapshot_id = r.snapshot_id AND t.driver_id = r.driver_id
            WHERE t.tenant_id = $1 AND t.snapshot_id = $2 AND r.id IS NULL
            """,
            tenant_id,
            snapshot_id,
        )
        return [row["driver_id"] for row in rows]

    async def _get_unacked_drivers(
        self,
        conn,
        tenant_id: int,
        snapshot_id: str,
    ) -> List[str]:
        """Get list of drivers who have read but not acked."""
        rows = await conn.fetch(
            """
            SELECT r.driver_id
            FROM portal.read_receipts r
            LEFT JOIN portal.driver_ack a
                ON r.snapshot_id = a.snapshot_id AND r.driver_id = a.driver_id
            WHERE r.tenant_id = $1 AND r.snapshot_id = $2 AND a.id IS NULL
            """,
            tenant_id,
            snapshot_id,
        )
        return [row["driver_id"] for row in rows]

    async def _get_declined_drivers(
        self,
        conn,
        tenant_id: int,
        snapshot_id: str,
    ) -> List[str]:
        """Get list of drivers who declined."""
        rows = await conn.fetch(
            """
            SELECT driver_id
            FROM portal.driver_ack
            WHERE tenant_id = $1 AND snapshot_id = $2 AND status = 'DECLINED'
            """,
            tenant_id,
            snapshot_id,
        )
        return [row["driver_id"] for row in rows]

    # =========================================================================
    # SUPERSEDE MAPPING
    # =========================================================================

    async def mark_superseded(
        self,
        tenant_id: int,
        old_snapshot_id: str,
        new_snapshot_id: str,
        superseded_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> SnapshotSupersede:
        """
        Mark a snapshot as superseded by a new one.

        Used when repair creates a new snapshot.
        """
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                INSERT INTO portal.snapshot_supersedes (
                    tenant_id, old_snapshot_id, new_snapshot_id,
                    superseded_at, superseded_by, reason
                ) VALUES ($1, $2, $3, NOW(), $4, $5)
                ON CONFLICT (old_snapshot_id) DO UPDATE SET
                    new_snapshot_id = $3,
                    superseded_at = NOW(),
                    superseded_by = $4,
                    reason = $5
                RETURNING id, superseded_at
                """,
                tenant_id,
                old_snapshot_id,
                new_snapshot_id,
                superseded_by,
                reason,
            )

            return SnapshotSupersede(
                id=row["id"],
                tenant_id=tenant_id,
                old_snapshot_id=old_snapshot_id,
                new_snapshot_id=new_snapshot_id,
                superseded_at=row["superseded_at"],
                superseded_by=superseded_by,
                reason=reason,
            )

    async def get_supersede(
        self,
        tenant_id: int,
        old_snapshot_id: str,
    ) -> Optional[SnapshotSupersede]:
        """Check if a snapshot has been superseded."""
        async with self.pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, old_snapshot_id, new_snapshot_id,
                       superseded_at, superseded_by, reason
                FROM portal.snapshot_supersedes
                WHERE tenant_id = $1 AND old_snapshot_id = $2
                """,
                tenant_id,
                old_snapshot_id,
            )

            if not row:
                return None

            return SnapshotSupersede(
                id=row["id"],
                tenant_id=row["tenant_id"],
                old_snapshot_id=str(row["old_snapshot_id"]),
                new_snapshot_id=str(row["new_snapshot_id"]),
                superseded_at=row["superseded_at"],
                superseded_by=row["superseded_by"],
                reason=row["reason"],
            )

    # =========================================================================
    # RATE LIMITING
    # =========================================================================

    async def check_rate_limit(
        self,
        jti_hash: str,
        max_requests: int = 100,
        window_seconds: int = 3600,
    ) -> RateLimitResult:
        """Check and update rate limit."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM portal.check_rate_limit($1, $2, $3, $4)",
                jti_hash,
                "JTI",
                max_requests,
                window_seconds,
            )

            return RateLimitResult(
                is_allowed=row["is_allowed"],
                current_count=row["current_count"],
                max_requests=max_requests,
                window_resets_at=row["window_resets_at"],
            )

    # =========================================================================
    # AUDIT TRAIL
    # =========================================================================

    async def _record_audit(
        self,
        conn,
        tenant_id: int,
        site_id: int,
        snapshot_id: Optional[str],
        driver_id: Optional[str],
        action: PortalAction,
        jti_hash: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_hash: Optional[str] = None,
        performed_by: Optional[str] = None,
    ) -> None:
        """Record audit entry."""
        import json

        await conn.execute(
            """
            INSERT INTO portal.portal_audit (
                tenant_id, site_id, snapshot_id, driver_id,
                action, jti_hash, ip_hash, details, performed_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            tenant_id,
            site_id,
            snapshot_id,
            driver_id,
            action.value,
            jti_hash,
            ip_hash,
            json.dumps(details) if details else None,
            performed_by,
        )


# =============================================================================
# MOCK REPOSITORY (for testing)
# =============================================================================

class MockPortalRepository(PortalTokenRepository):
    """
    Mock repository for testing.

    Stores all data in memory.
    """

    def __init__(self):
        self._tokens: Dict[str, PortalToken] = {}
        self._read_receipts: Dict[str, ReadReceipt] = {}
        self._acks: Dict[str, DriverAck] = {}
        self._supersedes: Dict[str, SnapshotSupersede] = {}
        self._rate_counts: Dict[str, int] = {}
        self._audits: List[Dict] = []

    def _make_read_key(self, snapshot_id: str, driver_id: str) -> str:
        return f"{snapshot_id}:{driver_id}"

    async def save_token(self, token: PortalToken) -> PortalToken:
        token.id = len(self._tokens) + 1
        self._tokens[token.jti_hash] = token
        return token

    async def get_by_jti_hash(self, jti_hash: str) -> Optional[PortalToken]:
        return self._tokens.get(jti_hash)

    async def revoke_token(self, jti_hash: str) -> bool:
        if jti_hash in self._tokens:
            self._tokens[jti_hash].revoked_at = datetime.utcnow()
            return True
        return False

    async def update_last_seen(self, jti_hash: str) -> bool:
        if jti_hash in self._tokens:
            self._tokens[jti_hash].last_seen_at = datetime.utcnow()
            return True
        return False

    async def record_read(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> ReadReceipt:
        key = self._make_read_key(snapshot_id, driver_id)
        if key in self._read_receipts:
            receipt = self._read_receipts[key]
            receipt.last_read_at = datetime.utcnow()
            receipt.read_count += 1
        else:
            receipt = ReadReceipt(
                id=len(self._read_receipts) + 1,
                tenant_id=tenant_id,
                site_id=site_id,
                snapshot_id=snapshot_id,
                driver_id=driver_id,
            )
            self._read_receipts[key] = receipt
        return receipt

    async def get_read_receipt(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> Optional[ReadReceipt]:
        key = self._make_read_key(snapshot_id, driver_id)
        return self._read_receipts.get(key)

    async def record_ack(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
        status: AckStatus,
        reason_code: Optional[AckReasonCode] = None,
        free_text: Optional[str] = None,
        source: AckSource = AckSource.PORTAL,
        override_by: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> DriverAck:
        key = self._make_read_key(snapshot_id, driver_id)
        if key in self._acks:
            return self._acks[key]

        ack = DriverAck(
            id=len(self._acks) + 1,
            tenant_id=tenant_id,
            site_id=site_id,
            snapshot_id=snapshot_id,
            driver_id=driver_id,
            status=status,
            reason_code=reason_code,
            free_text=free_text,
            source=source,
            override_by=override_by,
            override_reason=override_reason,
        )
        self._acks[key] = ack
        return ack

    async def get_ack(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_id: str,
    ) -> Optional[DriverAck]:
        key = self._make_read_key(snapshot_id, driver_id)
        return self._acks.get(key)

    async def get_portal_status(
        self,
        tenant_id: int,
        snapshot_id: str,
    ) -> PortalStatus:
        # Count from in-memory storage
        total = sum(1 for t in self._tokens.values() if t.snapshot_id == snapshot_id)
        read = sum(1 for r in self._read_receipts.values() if r.snapshot_id == snapshot_id)
        accepted = sum(1 for a in self._acks.values()
                       if a.snapshot_id == snapshot_id and a.status == AckStatus.ACCEPTED)
        declined = sum(1 for a in self._acks.values()
                       if a.snapshot_id == snapshot_id and a.status == AckStatus.DECLINED)

        return PortalStatus(
            snapshot_id=snapshot_id,
            total_drivers=total,
            unread_count=total - read,
            read_count=read,
            accepted_count=accepted,
            declined_count=declined,
            pending_count=read - accepted - declined,
        )

    async def check_rate_limit(
        self,
        jti_hash: str,
        max_requests: int = 100,
        window_seconds: int = 3600,
    ) -> RateLimitResult:
        count = self._rate_counts.get(jti_hash, 0) + 1
        self._rate_counts[jti_hash] = count

        from datetime import timedelta
        return RateLimitResult(
            is_allowed=(count <= max_requests),
            current_count=count,
            max_requests=max_requests,
            window_resets_at=datetime.utcnow() + timedelta(seconds=window_seconds),
        )

    async def mark_superseded(
        self,
        tenant_id: int,
        old_snapshot_id: str,
        new_snapshot_id: str,
        superseded_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> SnapshotSupersede:
        supersede = SnapshotSupersede(
            id=len(self._supersedes) + 1,
            tenant_id=tenant_id,
            old_snapshot_id=old_snapshot_id,
            new_snapshot_id=new_snapshot_id,
            superseded_by=superseded_by,
            reason=reason,
        )
        self._supersedes[old_snapshot_id] = supersede
        return supersede

    async def get_supersede(
        self,
        tenant_id: int,
        old_snapshot_id: str,
    ) -> Optional[SnapshotSupersede]:
        return self._supersedes.get(old_snapshot_id)
