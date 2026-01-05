"""
SOLVEREIGN V3.3b - Security Audit Logging
==========================================

Tamper-evident security audit log with:
- Hash chain for integrity verification
- Immutable storage (append-only)
- Severity-based alerting
- Structured event format

Event Categories:
- AUTH: Login, logout, token refresh
- AUTHZ: Permission checks, denials
- DATA: PII access, exports
- SYSTEM: Configuration changes
"""

import time
import hashlib
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPES
# =============================================================================

class EventCategory(str, Enum):
    """Security event categories."""
    AUTH = "AUTH"           # Authentication events
    AUTHZ = "AUTHZ"         # Authorization events
    DATA = "DATA"           # Data access events
    SYSTEM = "SYSTEM"       # System events
    SECURITY = "SECURITY"   # Security-related events


class EventSeverity(str, Enum):
    """Event severity levels."""
    INFO = "INFO"           # Normal operations
    WARNING = "WARNING"     # Potential issues
    CRITICAL = "CRITICAL"   # Security incidents


# Common event types
class EventType(str, Enum):
    # AUTH
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    MFA_CHALLENGE = "MFA_CHALLENGE"
    MFA_SUCCESS = "MFA_SUCCESS"
    MFA_FAILED = "MFA_FAILED"

    # AUTHZ
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CROSS_TENANT_ATTEMPT = "CROSS_TENANT_ATTEMPT"
    PRIVILEGE_ESCALATION = "PRIVILEGE_ESCALATION"

    # DATA
    PII_ACCESS = "PII_ACCESS"
    BULK_EXPORT = "BULK_EXPORT"
    DATA_DELETE = "DATA_DELETE"
    GDPR_REQUEST = "GDPR_REQUEST"

    # SYSTEM
    CONFIG_CHANGE = "CONFIG_CHANGE"
    KEY_ROTATION = "KEY_ROTATION"
    USER_CREATED = "USER_CREATED"
    USER_DELETED = "USER_DELETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"

    # SECURITY
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    BRUTE_FORCE_DETECTED = "BRUTE_FORCE_DETECTED"
    INJECTION_ATTEMPT = "INJECTION_ATTEMPT"


# =============================================================================
# AUDIT EVENT
# =============================================================================

@dataclass
class AuditEvent:
    """
    Security audit event.

    Immutable record of a security-relevant action.
    """
    event_type: str
    tenant_id: Optional[str]
    user_id: Optional[str]
    severity: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None

    # Hash chain fields (populated by storage)
    id: Optional[int] = None
    previous_hash: Optional[str] = None
    current_hash: Optional[str] = None

    def compute_hash(self, previous: Optional[str] = None) -> str:
        """
        Compute hash for this event.

        Hash includes:
        - Previous hash (for chain)
        - Timestamp
        - Event type
        - Tenant/User
        - Details

        This creates a tamper-evident chain.
        """
        data = {
            "previous_hash": previous or "GENESIS",
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "severity": self.severity,
            "details": json.dumps(self.details, sort_keys=True),
        }

        # Canonical JSON for consistent hashing
        canonical = json.dumps(data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


# =============================================================================
# AUDIT STORAGE
# =============================================================================

class AuditStorage:
    """Abstract audit storage interface."""

    async def append(self, event: AuditEvent) -> AuditEvent:
        """Append event to audit log. Returns event with hash chain."""
        raise NotImplementedError

    async def get_last_hash(self) -> Optional[str]:
        """Get hash of last event for chain continuation."""
        raise NotImplementedError

    async def verify_chain(self, start_id: int = 0, limit: int = 1000) -> bool:
        """Verify hash chain integrity."""
        raise NotImplementedError

    async def query(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events."""
        raise NotImplementedError


class InMemoryAuditStorage(AuditStorage):
    """
    In-memory audit storage for development/testing.

    NOT suitable for production - data lost on restart.
    """

    def __init__(self):
        self._events: List[AuditEvent] = []
        self._id_counter = 0

    async def append(self, event: AuditEvent) -> AuditEvent:
        # Get previous hash
        previous_hash = await self.get_last_hash()

        # Compute hash
        event.previous_hash = previous_hash
        event.current_hash = event.compute_hash(previous_hash)

        # Assign ID
        self._id_counter += 1
        event.id = self._id_counter

        # Append
        self._events.append(event)

        return event

    async def get_last_hash(self) -> Optional[str]:
        if not self._events:
            return None
        return self._events[-1].current_hash

    async def verify_chain(self, start_id: int = 0, limit: int = 1000) -> bool:
        events = [e for e in self._events if e.id >= start_id][:limit]

        for i, event in enumerate(events):
            # Get expected previous hash
            if i == 0:
                if start_id == 0:
                    expected_prev = None
                else:
                    # Find previous event
                    prev_events = [e for e in self._events if e.id < start_id]
                    expected_prev = prev_events[-1].current_hash if prev_events else None
            else:
                expected_prev = events[i - 1].current_hash

            # Verify previous hash matches
            if event.previous_hash != expected_prev:
                logger.error(
                    "audit_chain_broken",
                    extra={
                        "event_id": event.id,
                        "expected_prev": expected_prev,
                        "actual_prev": event.previous_hash,
                    }
                )
                return False

            # Verify current hash is correct
            computed = event.compute_hash(event.previous_hash)
            if event.current_hash != computed:
                logger.error(
                    "audit_hash_mismatch",
                    extra={
                        "event_id": event.id,
                        "stored_hash": event.current_hash,
                        "computed_hash": computed,
                    }
                )
                return False

        return True

    async def query(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        results = []

        for event in reversed(self._events):
            if tenant_id and event.tenant_id != tenant_id:
                continue
            if event_type and event.event_type != event_type:
                continue
            if severity and event.severity != severity:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue

            results.append(event)

            if len(results) >= limit:
                break

        return results


class PostgresAuditStorage(AuditStorage):
    """
    PostgreSQL audit storage for production.

    Uses database triggers for hash chain computation.
    """

    def __init__(self, db_manager):
        self.db = db_manager

    async def append(self, event: AuditEvent) -> AuditEvent:
        """
        Append event to database.

        Hash chain is computed by database trigger.
        """
        async with self.db.connection() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO security_audit_log (
                    event_type, tenant_id, user_id, severity,
                    ip_address, user_agent, details_json, request_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, previous_hash, current_hash, timestamp
                """,
                event.event_type,
                event.tenant_id,
                event.user_id,
                event.severity,
                event.ip_address,
                event.user_agent,
                json.dumps(event.details),
                event.request_id,
            )

            event.id = result["id"]
            event.previous_hash = result["previous_hash"]
            event.current_hash = result["current_hash"]
            event.timestamp = result["timestamp"].isoformat()

        return event

    async def get_last_hash(self) -> Optional[str]:
        async with self.db.connection() as conn:
            result = await conn.fetchval(
                """
                SELECT current_hash
                FROM security_audit_log
                ORDER BY id DESC
                LIMIT 1
                """
            )
            return result

    async def verify_chain(self, start_id: int = 0, limit: int = 1000) -> bool:
        async with self.db.connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, previous_hash, current_hash, timestamp,
                       event_type, tenant_id, user_id, severity, details_json
                FROM security_audit_log
                WHERE id >= $1
                ORDER BY id ASC
                LIMIT $2
                """,
                start_id,
                limit,
            )

            for i, row in enumerate(rows):
                event = AuditEvent(
                    id=row["id"],
                    event_type=row["event_type"],
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    severity=row["severity"],
                    timestamp=row["timestamp"].isoformat(),
                    details=json.loads(row["details_json"]) if row["details_json"] else {},
                    previous_hash=row["previous_hash"],
                    current_hash=row["current_hash"],
                )

                # Verify hash
                computed = event.compute_hash(event.previous_hash)
                if event.current_hash != computed:
                    logger.error(
                        "audit_hash_mismatch",
                        extra={
                            "event_id": event.id,
                            "stored_hash": event.current_hash,
                            "computed_hash": computed,
                        }
                    )
                    return False

        return True

    async def query(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        conditions = []
        params = []
        param_idx = 1

        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1

        if event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1

        if severity:
            conditions.append(f"severity = ${param_idx}")
            params.append(severity)
            param_idx += 1

        if start_time:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_time)
            param_idx += 1

        if end_time:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        async with self.db.connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, event_type, tenant_id, user_id, severity,
                       timestamp, ip_address, user_agent, details_json,
                       request_id, previous_hash, current_hash
                FROM security_audit_log
                WHERE {where_clause}
                ORDER BY id DESC
                LIMIT ${param_idx}
                """,
                *params,
                limit,
            )

            return [
                AuditEvent(
                    id=row["id"],
                    event_type=row["event_type"],
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    severity=row["severity"],
                    timestamp=row["timestamp"].isoformat(),
                    ip_address=row["ip_address"],
                    user_agent=row["user_agent"],
                    details=json.loads(row["details_json"]) if row["details_json"] else {},
                    request_id=row["request_id"],
                    previous_hash=row["previous_hash"],
                    current_hash=row["current_hash"],
                )
                for row in rows
            ]


# =============================================================================
# SECURITY AUDIT LOGGER (SINGLETON)
# =============================================================================

class SecurityAuditLogger:
    """
    Security audit logger singleton.

    Provides static methods for easy logging from anywhere.
    """

    _storage: Optional[AuditStorage] = None
    _alert_callbacks: List[callable] = []

    @classmethod
    def configure(cls, storage: AuditStorage):
        """Configure audit storage backend."""
        cls._storage = storage

    @classmethod
    def add_alert_callback(cls, callback: callable):
        """Add callback for CRITICAL events."""
        cls._alert_callbacks.append(callback)

    @classmethod
    async def log(
        cls,
        event_type: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        severity: str = "INFO",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> AuditEvent:
        """
        Log a security event.

        Automatically handles:
        - Hash chain computation
        - CRITICAL event alerting
        - Structured logging
        """
        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            severity=severity,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
            request_id=request_id,
        )

        # Use in-memory if not configured
        if cls._storage is None:
            cls._storage = InMemoryAuditStorage()

        # Append to storage
        event = await cls._storage.append(event)

        # Log to standard logger
        log_level = {
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "CRITICAL": logging.CRITICAL,
        }.get(severity, logging.INFO)

        logger.log(
            log_level,
            f"security_audit_{event_type.lower()}",
            extra={
                "audit_event_id": event.id,
                "event_type": event_type,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "severity": severity,
                "ip_address": ip_address,
                "details": details,
            }
        )

        # Alert on CRITICAL
        if severity == "CRITICAL":
            await cls._send_alerts(event)

        return event

    @classmethod
    async def _send_alerts(cls, event: AuditEvent):
        """Send alerts for CRITICAL events."""
        for callback in cls._alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(
                    "alert_callback_failed",
                    extra={"error": str(e), "event_id": event.id}
                )

    @classmethod
    async def verify_integrity(cls, start_id: int = 0, limit: int = 1000) -> bool:
        """Verify audit log integrity."""
        if cls._storage is None:
            return True
        return await cls._storage.verify_chain(start_id, limit)


# Import asyncio for alert callbacks
import asyncio


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def log_login_success(
    tenant_id: str,
    user_id: str,
    ip_address: str,
    user_agent: Optional[str] = None,
    mfa_used: bool = False,
):
    """Log successful login."""
    return await SecurityAuditLogger.log(
        event_type=EventType.LOGIN_SUCCESS,
        tenant_id=tenant_id,
        user_id=user_id,
        severity="INFO",
        ip_address=ip_address,
        user_agent=user_agent,
        details={"mfa_used": mfa_used},
    )


async def log_login_failed(
    ip_address: str,
    user_agent: Optional[str] = None,
    reason: str = "invalid_credentials",
    username: Optional[str] = None,
):
    """Log failed login attempt."""
    return await SecurityAuditLogger.log(
        event_type=EventType.LOGIN_FAILED,
        severity="WARNING",
        ip_address=ip_address,
        user_agent=user_agent,
        details={"reason": reason, "username": username},
    )


async def log_permission_denied(
    tenant_id: str,
    user_id: str,
    ip_address: str,
    required_permissions: List[str],
    path: str,
):
    """Log permission denial."""
    return await SecurityAuditLogger.log(
        event_type=EventType.PERMISSION_DENIED,
        tenant_id=tenant_id,
        user_id=user_id,
        severity="WARNING",
        ip_address=ip_address,
        details={
            "required_permissions": required_permissions,
            "path": path,
        },
    )


async def log_cross_tenant_attempt(
    source_tenant: str,
    target_tenant: str,
    user_id: str,
    ip_address: str,
    path: str,
):
    """Log cross-tenant access attempt (CRITICAL)."""
    return await SecurityAuditLogger.log(
        event_type=EventType.CROSS_TENANT_ATTEMPT,
        tenant_id=source_tenant,
        user_id=user_id,
        severity="CRITICAL",
        ip_address=ip_address,
        details={
            "source_tenant": source_tenant,
            "target_tenant": target_tenant,
            "path": path,
        },
    )


async def log_pii_access(
    tenant_id: str,
    user_id: str,
    ip_address: str,
    driver_ids: List[str],
    fields_accessed: List[str],
):
    """Log PII data access."""
    return await SecurityAuditLogger.log(
        event_type=EventType.PII_ACCESS,
        tenant_id=tenant_id,
        user_id=user_id,
        severity="INFO",
        ip_address=ip_address,
        details={
            "driver_ids": driver_ids,
            "fields_accessed": fields_accessed,
        },
    )


async def log_bulk_export(
    tenant_id: str,
    user_id: str,
    ip_address: str,
    export_type: str,
    record_count: int,
):
    """Log bulk data export (sensitive)."""
    return await SecurityAuditLogger.log(
        event_type=EventType.BULK_EXPORT,
        tenant_id=tenant_id,
        user_id=user_id,
        severity="WARNING",
        ip_address=ip_address,
        details={
            "export_type": export_type,
            "record_count": record_count,
        },
    )
