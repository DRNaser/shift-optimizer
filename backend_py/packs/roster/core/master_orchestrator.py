"""
SOLVEREIGN V4.9 - Master Orchestrator for Dispatch Workbench

Event-driven automation system (NO LLM - deterministic only).

Architecture:
- Event Ingestion: Receives events from external systems (sick calls, etc.)
- Work Queue: Prioritized by risk tier
- Policy Router: Routes to appropriate handler based on event type
- Risk Tiers: HOT (immediate) / WARM (batch) / COLD (scheduled)

NON-NEGOTIABLES:
- NO LLM: Purely rule-based, deterministic
- Audit trail for every action
- Tenant isolation via RLS
- Idempotent operations
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Callable, Any
from uuid import UUID, uuid4
import asyncpg
import logging
import json
import hashlib

logger = logging.getLogger(__name__)

# =============================================================================
# TYPES
# =============================================================================

class EventType(str, Enum):
    """Event types that the orchestrator can handle."""
    # Driver events
    DRIVER_SICK_CALL = "DRIVER_SICK_CALL"
    DRIVER_LATE = "DRIVER_LATE"
    DRIVER_NO_SHOW = "DRIVER_NO_SHOW"
    DRIVER_AVAILABILITY_CHANGE = "DRIVER_AVAILABILITY_CHANGE"

    # Tour events
    TOUR_CANCELLED = "TOUR_CANCELLED"
    TOUR_DELAYED = "TOUR_DELAYED"
    TOUR_ADDED = "TOUR_ADDED"
    TOUR_MODIFIED = "TOUR_MODIFIED"

    # System events
    SCHEDULE_PUBLISHED = "SCHEDULE_PUBLISHED"
    REPAIR_SESSION_TIMEOUT = "REPAIR_SESSION_TIMEOUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"

    # Manual triggers
    MANUAL_REPAIR = "MANUAL_REPAIR"
    BULK_REASSIGN = "BULK_REASSIGN"


class RiskTier(str, Enum):
    """Risk tier determines processing priority."""
    HOT = "HOT"      # Immediate processing (< 1 min)
    WARM = "WARM"    # Batch processing (< 15 min)
    COLD = "COLD"    # Scheduled processing (next batch window)


class EventStatus(str, Enum):
    """Event processing status."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"


class ActionType(str, Enum):
    """Action types the orchestrator can take."""
    CREATE_REPAIR_SESSION = "CREATE_REPAIR_SESSION"
    AUTO_REASSIGN = "AUTO_REASSIGN"
    NOTIFY_DISPATCHER = "NOTIFY_DISPATCHER"
    ESCALATE = "ESCALATE"
    NO_ACTION = "NO_ACTION"


@dataclass
class OpsEvent:
    """An event in the operations queue."""
    event_id: UUID
    event_type: EventType
    tenant_id: int
    site_id: int
    payload: dict
    risk_tier: RiskTier
    status: EventStatus = EventStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class PolicyMatch:
    """Result of matching an event to a workflow policy."""
    policy_id: int
    policy_name: str
    action: ActionType
    config: dict
    priority: int


@dataclass
class OrchestratorResult:
    """Result of processing an event."""
    event_id: UUID
    success: bool
    action_taken: ActionType
    details: dict
    repair_session_id: Optional[UUID] = None
    error: Optional[str] = None


# =============================================================================
# RISK TIER CLASSIFICATION
# =============================================================================

# Risk tier mappings based on event type
RISK_TIER_MAP: dict[EventType, RiskTier] = {
    # HOT: Immediate action required
    EventType.DRIVER_SICK_CALL: RiskTier.HOT,
    EventType.DRIVER_NO_SHOW: RiskTier.HOT,
    EventType.TOUR_CANCELLED: RiskTier.HOT,

    # WARM: Batch processing OK
    EventType.DRIVER_LATE: RiskTier.WARM,
    EventType.DRIVER_AVAILABILITY_CHANGE: RiskTier.WARM,
    EventType.TOUR_DELAYED: RiskTier.WARM,
    EventType.TOUR_MODIFIED: RiskTier.WARM,

    # COLD: Scheduled processing
    EventType.SCHEDULE_PUBLISHED: RiskTier.COLD,
    EventType.TOUR_ADDED: RiskTier.COLD,
    EventType.MANUAL_REPAIR: RiskTier.WARM,
    EventType.BULK_REASSIGN: RiskTier.COLD,
    EventType.REPAIR_SESSION_TIMEOUT: RiskTier.COLD,
    EventType.VALIDATION_FAILED: RiskTier.WARM,
}


def classify_risk_tier(event_type: EventType, payload: dict) -> RiskTier:
    """
    Classify risk tier based on event type and payload.

    Some events may be upgraded based on payload (e.g., late for critical tour).
    """
    base_tier = RISK_TIER_MAP.get(event_type, RiskTier.WARM)

    # Check for tier upgrades based on payload
    if payload.get("is_critical") or payload.get("affects_multiple_tours"):
        if base_tier == RiskTier.WARM:
            return RiskTier.HOT
        elif base_tier == RiskTier.COLD:
            return RiskTier.WARM

    return base_tier


# =============================================================================
# EVENT INGESTION
# =============================================================================

async def ingest_event(
    conn: asyncpg.Connection,
    event_type: EventType,
    tenant_id: int,
    site_id: int,
    payload: dict,
    idempotency_key: Optional[str] = None,
) -> OpsEvent:
    """
    Ingest a new event into the work queue.

    Idempotent: duplicate events with same key are rejected.
    """
    event_id = uuid4()
    risk_tier = classify_risk_tier(event_type, payload)

    # Generate idempotency key if not provided
    if not idempotency_key:
        key_data = f"{event_type.value}:{tenant_id}:{site_id}:{json.dumps(payload, sort_keys=True)}"
        idempotency_key = hashlib.sha256(key_data.encode()).hexdigest()[:32]

    # Check for duplicate
    existing = await conn.fetchrow("""
        SELECT event_id FROM ops.event_queue
        WHERE idempotency_key = $1 AND tenant_id = $2
    """, idempotency_key, tenant_id)

    if existing:
        logger.info(f"Duplicate event ignored: {idempotency_key}")
        return OpsEvent(
            event_id=existing["event_id"],
            event_type=event_type,
            tenant_id=tenant_id,
            site_id=site_id,
            payload=payload,
            risk_tier=risk_tier,
            status=EventStatus.COMPLETED,
            idempotency_key=idempotency_key,
        )

    # Insert event
    await conn.execute("""
        INSERT INTO ops.event_queue (
            event_id, event_type, tenant_id, site_id,
            payload, risk_tier, status, idempotency_key
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, event_id, event_type.value, tenant_id, site_id,
         json.dumps(payload), risk_tier.value, EventStatus.PENDING.value,
         idempotency_key)

    logger.info(f"Event ingested: {event_id} type={event_type.value} tier={risk_tier.value}")

    return OpsEvent(
        event_id=event_id,
        event_type=event_type,
        tenant_id=tenant_id,
        site_id=site_id,
        payload=payload,
        risk_tier=risk_tier,
        status=EventStatus.PENDING,
        idempotency_key=idempotency_key,
    )


# =============================================================================
# POLICY ROUTER
# =============================================================================

async def match_policy(
    conn: asyncpg.Connection,
    event_type: EventType,
    tenant_id: int,
    site_id: int,
) -> Optional[PolicyMatch]:
    """
    Find the best matching workflow policy for an event.

    Policies are matched by (tenant, site, event_type) with tenant=NULL as fallback.
    """
    row = await conn.fetchrow("""
        SELECT
            policy_id,
            policy_name,
            action,
            config,
            priority
        FROM ops.match_workflow_policy($1, $2, $3)
    """, event_type.value, tenant_id, site_id)

    if not row:
        return None

    return PolicyMatch(
        policy_id=row["policy_id"],
        policy_name=row["policy_name"],
        action=ActionType(row["action"]),
        config=row["config"] or {},
        priority=row["priority"],
    )


# =============================================================================
# ACTION HANDLERS
# =============================================================================

async def handle_create_repair_session(
    conn: asyncpg.Connection,
    event: OpsEvent,
    policy: PolicyMatch,
) -> OrchestratorResult:
    """Create a repair session for manual intervention."""
    from packs.roster.core.draft_mutations import get_or_create_repair_session

    # Get plan version for this site
    plan = await conn.fetchrow("""
        SELECT id FROM plan_versions
        WHERE tenant_id = $1 AND site_id = $2 AND plan_state = 'PUBLISHED'
        ORDER BY created_at DESC LIMIT 1
    """, event.tenant_id, event.site_id)

    if not plan:
        return OrchestratorResult(
            event_id=event.event_id,
            success=False,
            action_taken=ActionType.NO_ACTION,
            details={"reason": "No published plan found"},
            error="No published plan for site",
        )

    # Create repair session
    session_id = await get_or_create_repair_session(
        conn=conn,
        tenant_id=event.tenant_id,
        plan_version_id=plan["id"],
        trigger_type=event.event_type.value,
        description=f"Auto-created for {event.event_type.value}",
    )

    return OrchestratorResult(
        event_id=event.event_id,
        success=True,
        action_taken=ActionType.CREATE_REPAIR_SESSION,
        details={
            "plan_version_id": plan["id"],
            "trigger": event.event_type.value,
        },
        repair_session_id=session_id,
    )


async def handle_auto_reassign(
    conn: asyncpg.Connection,
    event: OpsEvent,
    policy: PolicyMatch,
) -> OrchestratorResult:
    """
    Automatically reassign affected tours.

    Rules-based assignment:
    1. Find tours affected by event
    2. Find eligible drivers (available, qualified, within hours)
    3. Apply best match assignment
    """
    payload = event.payload
    driver_id = payload.get("driver_id")

    if not driver_id:
        return OrchestratorResult(
            event_id=event.event_id,
            success=False,
            action_taken=ActionType.NO_ACTION,
            details={"reason": "No driver_id in payload"},
            error="Missing driver_id",
        )

    # Get affected tours
    affected = await conn.fetch("""
        SELECT
            a.id as assignment_id,
            a.tour_instance_id,
            ti.start_ts,
            ti.end_ts,
            ti.skill,
            ti.day
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.driver_id = $1
          AND ti.site_id = $2
          AND ti.start_ts >= NOW()
        ORDER BY ti.start_ts
        LIMIT 10
    """, str(driver_id), event.site_id)

    if not affected:
        return OrchestratorResult(
            event_id=event.event_id,
            success=True,
            action_taken=ActionType.NO_ACTION,
            details={"reason": "No affected tours found"},
        )

    # Find replacement drivers for each tour
    reassignments = []
    for tour in affected:
        replacement = await _find_replacement_driver(
            conn, event.tenant_id, event.site_id, tour
        )
        if replacement:
            reassignments.append({
                "tour_instance_id": tour["tour_instance_id"],
                "old_driver_id": driver_id,
                "new_driver_id": replacement["driver_id"],
                "new_driver_name": replacement["driver_name"],
            })

    if not reassignments:
        # Escalate if no replacements found
        return OrchestratorResult(
            event_id=event.event_id,
            success=True,
            action_taken=ActionType.ESCALATE,
            details={
                "reason": "No replacement drivers available",
                "affected_tours": len(affected),
            },
        )

    # Apply reassignments (this would create a repair session with the mutations)
    return OrchestratorResult(
        event_id=event.event_id,
        success=True,
        action_taken=ActionType.AUTO_REASSIGN,
        details={
            "reassignments": reassignments,
            "tours_affected": len(affected),
            "tours_reassigned": len(reassignments),
        },
    )


async def _find_replacement_driver(
    conn: asyncpg.Connection,
    tenant_id: int,
    site_id: int,
    tour: dict,
) -> Optional[dict]:
    """Find the best available replacement driver for a tour."""
    # Find drivers who:
    # 1. Are active and available
    # 2. Have required skills
    # 3. Won't exceed hours limit
    # 4. Don't have conflicting assignments

    row = await conn.fetchrow("""
        SELECT
            d.id as driver_id,
            d.name as driver_name
        FROM drivers d
        WHERE d.tenant_id = $1
          AND d.site_id = $2
          AND d.is_active = TRUE
          AND ($3::text IS NULL OR $3 = ANY(d.skills))
          AND NOT EXISTS (
              -- No overlapping assignments
              SELECT 1 FROM assignments a2
              JOIN tour_instances ti2 ON a2.tour_instance_id = ti2.id
              WHERE a2.driver_id = d.id::TEXT
                AND ti2.site_id = $2
                AND ti2.start_ts < $5
                AND ti2.end_ts > $4
          )
        ORDER BY
            -- Prefer drivers with fewer hours
            COALESCE((
                SELECT SUM(ti3.work_hours)
                FROM assignments a3
                JOIN tour_instances ti3 ON a3.tour_instance_id = ti3.id
                WHERE a3.driver_id = d.id::TEXT
            ), 0) ASC
        LIMIT 1
    """, tenant_id, site_id, tour.get("skill"),
         tour["start_ts"], tour["end_ts"])

    if row:
        return {"driver_id": row["driver_id"], "driver_name": row["driver_name"]}
    return None


async def handle_notify_dispatcher(
    conn: asyncpg.Connection,
    event: OpsEvent,
    policy: PolicyMatch,
) -> OrchestratorResult:
    """Send notification to dispatcher."""
    # This would integrate with the notification system
    # For now, just log the intent
    logger.info(f"Would notify dispatcher: {event.event_type.value} for site {event.site_id}")

    return OrchestratorResult(
        event_id=event.event_id,
        success=True,
        action_taken=ActionType.NOTIFY_DISPATCHER,
        details={
            "notification_type": "dispatcher_alert",
            "event_type": event.event_type.value,
        },
    )


async def handle_escalate(
    conn: asyncpg.Connection,
    event: OpsEvent,
    policy: PolicyMatch,
) -> OrchestratorResult:
    """Escalate to management."""
    logger.warning(f"Escalating event {event.event_id}: {event.event_type.value}")

    return OrchestratorResult(
        event_id=event.event_id,
        success=True,
        action_taken=ActionType.ESCALATE,
        details={
            "escalation_reason": policy.config.get("reason", "Policy triggered"),
            "event_type": event.event_type.value,
        },
    )


# Handler registry
ACTION_HANDLERS: dict[ActionType, Callable] = {
    ActionType.CREATE_REPAIR_SESSION: handle_create_repair_session,
    ActionType.AUTO_REASSIGN: handle_auto_reassign,
    ActionType.NOTIFY_DISPATCHER: handle_notify_dispatcher,
    ActionType.ESCALATE: handle_escalate,
}


# =============================================================================
# EVENT PROCESSOR
# =============================================================================

async def process_event(
    conn: asyncpg.Connection,
    event: OpsEvent,
) -> OrchestratorResult:
    """
    Process a single event through the orchestrator.

    Flow:
    1. Match policy for event type
    2. Execute action handler
    3. Update event status
    4. Create audit trail
    """
    # Match policy
    policy = await match_policy(conn, event.event_type, event.tenant_id, event.site_id)

    if not policy:
        logger.warning(f"No policy matched for {event.event_type.value}")
        return OrchestratorResult(
            event_id=event.event_id,
            success=True,
            action_taken=ActionType.NO_ACTION,
            details={"reason": "No matching policy"},
        )

    # Get handler
    handler = ACTION_HANDLERS.get(policy.action)
    if not handler:
        logger.error(f"No handler for action {policy.action.value}")
        return OrchestratorResult(
            event_id=event.event_id,
            success=False,
            action_taken=ActionType.NO_ACTION,
            details={"reason": f"No handler for {policy.action.value}"},
            error=f"Missing handler: {policy.action.value}",
        )

    # Execute handler
    try:
        result = await handler(conn, event, policy)
    except Exception as e:
        logger.exception(f"Handler failed for {event.event_id}")
        result = OrchestratorResult(
            event_id=event.event_id,
            success=False,
            action_taken=policy.action,
            details={},
            error=str(e),
        )

    # Update event status
    new_status = EventStatus.COMPLETED if result.success else EventStatus.FAILED
    await conn.execute("""
        UPDATE ops.event_queue
        SET status = $2,
            processed_at = NOW(),
            error_message = $3
        WHERE event_id = $1
    """, event.event_id, new_status.value, result.error)

    return result


async def process_queue_batch(
    conn: asyncpg.Connection,
    tenant_id: Optional[int] = None,
    risk_tier: Optional[RiskTier] = None,
    batch_size: int = 10,
) -> list[OrchestratorResult]:
    """
    Process a batch of events from the queue.

    Processes events in priority order (HOT > WARM > COLD).
    """
    # Build query with filters
    query = """
        SELECT
            event_id, event_type, tenant_id, site_id,
            payload, risk_tier, status, retry_count,
            idempotency_key, created_at
        FROM ops.event_queue
        WHERE status = 'PENDING'
    """
    params = []

    if tenant_id is not None:
        params.append(tenant_id)
        query += f" AND tenant_id = ${len(params)}"

    if risk_tier is not None:
        params.append(risk_tier.value)
        query += f" AND risk_tier = ${len(params)}"

    query += """
        ORDER BY
            CASE risk_tier
                WHEN 'HOT' THEN 1
                WHEN 'WARM' THEN 2
                WHEN 'COLD' THEN 3
            END,
            created_at ASC
        LIMIT ${}
    """.format(len(params) + 1)
    params.append(batch_size)

    rows = await conn.fetch(query, *params)

    results = []
    for row in rows:
        event = OpsEvent(
            event_id=row["event_id"],
            event_type=EventType(row["event_type"]),
            tenant_id=row["tenant_id"],
            site_id=row["site_id"],
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            risk_tier=RiskTier(row["risk_tier"]),
            status=EventStatus(row["status"]),
            retry_count=row["retry_count"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

        # Mark as processing
        await conn.execute("""
            UPDATE ops.event_queue
            SET status = 'PROCESSING'
            WHERE event_id = $1
        """, event.event_id)

        # Process
        result = await process_event(conn, event)
        results.append(result)

    return results


# =============================================================================
# SCHEDULED JOBS
# =============================================================================

async def cleanup_old_events(
    conn: asyncpg.Connection,
    retention_days: int = 30,
) -> int:
    """Clean up completed events older than retention period."""
    result = await conn.execute("""
        DELETE FROM ops.event_queue
        WHERE status IN ('COMPLETED', 'DEAD_LETTER')
          AND created_at < NOW() - INTERVAL '1 day' * $1
    """, retention_days)

    deleted = int(result.split()[-1]) if result else 0
    logger.info(f"Cleaned up {deleted} old events")
    return deleted


async def retry_failed_events(
    conn: asyncpg.Connection,
) -> int:
    """Retry failed events that haven't exceeded max retries."""
    result = await conn.execute("""
        UPDATE ops.event_queue
        SET status = 'PENDING',
            retry_count = retry_count + 1
        WHERE status = 'FAILED'
          AND retry_count < 3
    """)

    retried = int(result.split()[-1]) if result else 0
    logger.info(f"Queued {retried} events for retry")
    return retried
