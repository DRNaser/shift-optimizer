"""
SOLVEREIGN Escalation Service
==============================

Central service for handling escalation events with severity-based responses.

Severity Model:
- S0: Security/Data Leak Risk → Hard Stop: block requests, emit alert
- S1: Integrity/Evidence Risk → Block lock/repair, require intervention
- S2: Operational Degraded → Allow read-only, fallback policy
- S3: UX/Non-critical → Log only, no operational block

Usage:
    from .services.escalation import EscalationService, Severity

    escalation = EscalationService(db)

    # Record and handle escalation
    await escalation.escalate(
        scope_type="tenant",
        scope_id=tenant_id,
        reason_code="OSRM_DOWN",
        details={"provider": "osrm", "error": "timeout"}
    )

    # Check before critical operation
    if await escalation.is_blocked("tenant", tenant_id):
        raise HTTPException(503, "Service temporarily unavailable")
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Awaitable, Any
import asyncio

from ..database import DatabaseManager
from ..logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# SEVERITY MODEL
# =============================================================================

class Severity(str, Enum):
    """
    Severity levels for escalation events.

    S0 = CRITICAL: Security/Data Leak Risk
         Action: Hard Stop - block requests, emit alert
         Examples: RLS violation, platform admin spoof, cross-tenant access

    S1 = HIGH: Integrity/Evidence Risk
         Action: Block lock/repair operations, require intervention
         Examples: Evidence hash mismatch, artifact write failure, freeze bypass

    S2 = MEDIUM: Operational Degraded
         Action: Allow read-only, apply fallback policy
         Examples: OSRM down, queue backlog, solver timeout

    S3 = LOW: UX/Non-critical
         Action: Log only, no operational block
         Examples: UI error, slow page load, minor validation warnings
    """
    S0 = "S0"  # Critical - Security
    S1 = "S1"  # High - Integrity
    S2 = "S2"  # Medium - Operational
    S3 = "S3"  # Low - UX


class ScopeType(str, Enum):
    """Scope types for escalation events."""
    PLATFORM = "platform"
    ORG = "org"
    TENANT = "tenant"
    SITE = "site"


class Status(str, Enum):
    """Service status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


# =============================================================================
# ESCALATION RESPONSE
# =============================================================================

@dataclass
class EscalationResponse:
    """Response from escalation action."""
    escalation_id: str
    severity: Severity
    status: Status
    reason_code: str
    fix_steps: list[str]
    runbook_link: Optional[str]
    blocked: bool
    degraded: bool


# =============================================================================
# ESCALATION SERVICE
# =============================================================================

class EscalationService:
    """
    Central escalation handling service.

    Provides:
    - Severity-based escalation recording
    - Automatic status determination
    - Rate limiting for repeated events
    - Alert dispatch (extensible)
    - Operation gating based on status
    """

    # Counter thresholds for automatic escalation
    RATE_LIMIT_THRESHOLDS = {
        "SIGNATURE_INVALID": 5,      # 5 failures in window → escalate
        "RLS_VIOLATION": 3,          # 3 violations → escalate
        "SOLVER_TIMEOUT": 10,        # 10 timeouts → escalate to S2
        "IMPORT_VALIDATION": 100,    # 100 warnings → escalate
    }

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._alert_handlers: list[Callable[[EscalationResponse], Awaitable[None]]] = []

    def register_alert_handler(
        self,
        handler: Callable[[EscalationResponse], Awaitable[None]]
    ) -> None:
        """
        Register an alert handler for escalation events.

        Handler is called asynchronously when S0/S1 events occur.
        """
        self._alert_handlers.append(handler)

    async def escalate(
        self,
        scope_type: str,
        scope_id: Optional[str],
        reason_code: str,
        details: Optional[dict] = None,
        force_severity: Optional[Severity] = None
    ) -> EscalationResponse:
        """
        Record an escalation event and trigger appropriate response.

        Args:
            scope_type: platform|org|tenant|site
            scope_id: UUID of scope (None for platform)
            reason_code: Reason code from registry
            details: Additional context
            force_severity: Override severity from registry

        Returns:
            EscalationResponse with status and guidance
        """
        # Record to database
        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
                )

                # Get reason code details from registry
                await cur.execute("""
                    SELECT severity, default_fix_steps, runbook_section
                    FROM core.reason_code_registry
                    WHERE reason_code = %s
                """, (reason_code,))
                registry = await cur.fetchone()

                if registry:
                    severity = Severity(force_severity or registry["severity"])
                    fix_steps = registry["default_fix_steps"] or []
                    runbook_section = registry["runbook_section"]
                else:
                    # Unknown reason - default to S2
                    severity = force_severity or Severity.S2
                    fix_steps = ["Check logs", "Contact support"]
                    runbook_section = "unknown"

                # Determine status based on severity
                if severity in (Severity.S0, Severity.S1):
                    status = Status.BLOCKED
                elif severity == Severity.S2:
                    status = Status.DEGRADED
                else:
                    status = Status.HEALTHY

                # Record escalation
                await cur.execute("""
                    SELECT core.record_escalation(%s::core.scope_type, %s, %s, %s)
                """, (scope_type, scope_id, reason_code, details or {}))
                result = await cur.fetchone()
                escalation_id = str(result["record_escalation"])

        response = EscalationResponse(
            escalation_id=escalation_id,
            severity=severity,
            status=status,
            reason_code=reason_code,
            fix_steps=fix_steps,
            runbook_link=f"/runbook/{runbook_section}" if runbook_section else None,
            blocked=status == Status.BLOCKED,
            degraded=status in (Status.BLOCKED, Status.DEGRADED)
        )

        # Log
        logger.warning(
            "escalation_recorded",
            extra={
                "escalation_id": escalation_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "reason_code": reason_code,
                "severity": severity.value,
                "status": status.value
            }
        )

        # Dispatch alerts for S0/S1
        if severity in (Severity.S0, Severity.S1):
            await self._dispatch_alerts(response)

        return response

    async def resolve(
        self,
        scope_type: str,
        scope_id: Optional[str],
        reason_code: str,
        resolved_by: str = "system"
    ) -> int:
        """
        Resolve an active escalation.

        Returns:
            Number of resolved escalations
        """
        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
                )
                await cur.execute("""
                    SELECT core.resolve_escalation(%s::core.scope_type, %s, %s, %s)
                """, (scope_type, scope_id, reason_code, resolved_by))
                result = await cur.fetchone()
                count = result["resolve_escalation"]

        if count > 0:
            logger.info(
                "escalation_resolved",
                extra={
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "reason_code": reason_code,
                    "resolved_by": resolved_by,
                    "count": count
                }
            )

        return count

    async def is_blocked(
        self,
        scope_type: str,
        scope_id: Optional[str] = None
    ) -> bool:
        """
        Check if scope has active S0/S1 blocks.

        Use before critical operations like lock/repair.
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT core.is_scope_blocked(%s::core.scope_type, %s)
                """, (scope_type, scope_id))
                result = await cur.fetchone()
                return result["is_scope_blocked"] if result else False

    async def is_degraded(
        self,
        scope_type: str,
        scope_id: Optional[str] = None
    ) -> bool:
        """
        Check if scope has any degradation (S0-S2).

        Use for UI banners and fallback policy selection.
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT core.is_scope_degraded(%s::core.scope_type, %s)
                """, (scope_type, scope_id))
                result = await cur.fetchone()
                return result["is_scope_degraded"] if result else False

    async def check_rate_limit(
        self,
        counter_key: str,
        window_minutes: int = 60
    ) -> tuple[int, bool]:
        """
        Increment rate limit counter and check if threshold exceeded.

        Returns:
            (count, exceeded) - current count and whether threshold exceeded
        """
        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT core.increment_escalation_counter(%s, %s)
                """, (counter_key, window_minutes))
                result = await cur.fetchone()
                count = result["increment_escalation_counter"]

        # Check threshold
        threshold = self.RATE_LIMIT_THRESHOLDS.get(counter_key.split(":")[0], 100)
        exceeded = count >= threshold

        if exceeded:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "counter_key": counter_key,
                    "count": count,
                    "threshold": threshold
                }
            )

        return count, exceeded

    async def _dispatch_alerts(self, response: EscalationResponse) -> None:
        """Dispatch alerts to registered handlers."""
        if not self._alert_handlers:
            return

        # Run handlers concurrently
        tasks = [handler(response) for handler in self._alert_handlers]
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(
                "alert_dispatch_failed",
                extra={"error": str(e), "escalation_id": response.escalation_id}
            )


# =============================================================================
# GATE DECORATORS
# =============================================================================

def require_not_blocked(scope_type: str, scope_id_param: str = "tenant_id"):
    """
    Decorator that blocks operation if scope is blocked (S0/S1).

    Usage:
        @require_not_blocked("tenant", "tenant_id")
        async def lock_plan(tenant_id: str, plan_id: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            # Get scope_id from kwargs
            scope_id = kwargs.get(scope_id_param)

            # Get db from kwargs (must be passed)
            db = kwargs.get("db")
            if not db:
                raise ValueError("db must be provided in kwargs")

            # Check if blocked
            is_blocked = await is_scope_blocked_check(db, scope_type, scope_id)
            if is_blocked:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "service_blocked",
                        "message": "Operation blocked due to active escalation",
                        "scope_type": scope_type,
                        "scope_id": scope_id
                    }
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


async def is_scope_blocked_check(
    db: DatabaseManager,
    scope_type: str,
    scope_id: Optional[str]
) -> bool:
    """Helper function to check if scope is blocked."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT core.is_scope_blocked(%s::core.scope_type, %s)
            """, (scope_type, scope_id))
            result = await cur.fetchone()
            return result["is_scope_blocked"] if result else False


# =============================================================================
# FACTORY
# =============================================================================

def get_escalation_service(db: DatabaseManager) -> EscalationService:
    """Factory function for EscalationService."""
    return EscalationService(db)
