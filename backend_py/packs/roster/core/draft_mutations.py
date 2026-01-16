"""
SOLVEREIGN V4.9 - Draft Mutations Engine
=========================================

Handles idempotent draft mutations within repair sessions for the Daily Tab workbench.

Operations:
- ASSIGN: Assign a driver to an unassigned tour instance
- UNASSIGN: Remove a driver from an assigned tour instance
- MOVE: Move an assignment from one driver to another

Validation Status:
- PENDING: Not yet validated
- VALID: Validated with no violations
- HARD_BLOCK: Rejected immediately (overlap/rest/pin conflict)
- SOFT_BLOCK: Allowed but requires acknowledgment (compatibility unknown)
- UNKNOWN: Validation mode = none (not checked)

NON-NEGOTIABLES:
- Draft-first: mutations only affect draft state, confirm commits atomically
- Idempotency: same operation with same hash returns same result
- No fake-green: never return VALID unless actually validated
- Hard blocks are rejected immediately, not stored
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & TYPES
# =============================================================================

class OpType(str, Enum):
    """Draft mutation operation types."""
    ASSIGN = "ASSIGN"           # Assign driver to empty slot
    UNASSIGN = "UNASSIGN"       # Remove driver from slot
    MOVE = "MOVE"               # Move assignment to different driver
    SET_SLOT_STATUS = "SET_SLOT_STATUS"  # Change slot status (e.g., ABORTED)


class SlotStatus(str, Enum):
    """Slot status values for dispatch workbench."""
    PLANNED = "PLANNED"       # Forecasted, not yet assigned
    HOLD = "HOLD"             # Temporarily deactivated (surplus capacity)
    RELEASED = "RELEASED"     # Reactivated, awaiting assignment
    ASSIGNED = "ASSIGNED"     # Driver assigned
    EXECUTED = "EXECUTED"     # Tour completed
    ABORTED = "ABORTED"       # Tour cancelled (first-class status)


class AbortReason(str, Enum):
    """Reasons for aborting a slot."""
    LOW_DEMAND = "LOW_DEMAND"       # Low demand / overcapacity
    WEATHER = "WEATHER"             # Weather conditions
    VEHICLE = "VEHICLE"             # Vehicle unavailable
    OPS_DECISION = "OPS_DECISION"   # Operational decision
    OTHER = "OTHER"                 # Other reason


class ValidationStatus(str, Enum):
    """Validation status for a mutation."""
    PENDING = "PENDING"         # Not yet validated
    VALID = "VALID"             # Validated, no violations
    HARD_BLOCK = "HARD_BLOCK"   # Rejected: overlap/rest/pin
    SOFT_BLOCK = "SOFT_BLOCK"   # Allowed: compatibility unknown
    UNKNOWN = "UNKNOWN"         # Validation mode = none


class HardBlockReason(str, Enum):
    """Reasons for hard blocking an operation."""
    OVERLAP = "OVERLAP"                     # Driver already assigned at same time
    REST_VIOLATION = "REST_VIOLATION"       # Less than 11h rest
    PIN_CONFLICT = "PIN_CONFLICT"           # Tour or driver is pinned
    ALREADY_ASSIGNED = "ALREADY_ASSIGNED"   # Slot already has a driver
    NOT_ASSIGNED = "NOT_ASSIGNED"           # Trying to unassign/move empty slot
    DRIVER_NOT_FOUND = "DRIVER_NOT_FOUND"   # Driver doesn't exist
    TOUR_NOT_FOUND = "TOUR_NOT_FOUND"       # Tour instance doesn't exist
    SLOT_NOT_FOUND = "SLOT_NOT_FOUND"       # Slot doesn't exist
    DAY_FROZEN = "DAY_FROZEN"               # Day is frozen, no mutations allowed
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"  # Invalid status change
    ALREADY_ABORTED = "ALREADY_ABORTED"     # Slot already aborted
    SLOT_ON_HOLD = "SLOT_ON_HOLD"           # Cannot assign to slot on HOLD (INV-1)
    GHOST_STATE_PREVENTED = "GHOST_STATE_PREVENTED"  # Operation would create invalid state


class SoftBlockReason(str, Enum):
    """Reasons for soft blocking an operation."""
    COMPATIBILITY_UNKNOWN = "COMPATIBILITY_UNKNOWN"  # Missing skill/vehicle data
    HOURS_EXCEEDED = "HOURS_EXCEEDED"               # Would exceed weekly hours
    PREFERENCE_MISMATCH = "PREFERENCE_MISMATCH"     # Driver preference not met


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MutationOp:
    """A single mutation operation from the client."""
    op: OpType
    tour_instance_id: int
    day: int
    driver_id: Optional[str] = None          # For ASSIGN/MOVE: new driver
    from_driver_id: Optional[str] = None     # For MOVE: previous driver
    block_id: Optional[str] = None           # Block identifier
    slot_index: Optional[int] = None         # Slot within block
    # For SET_SLOT_STATUS
    slot_id: Optional[UUID] = None           # Slot UUID for status change
    new_status: Optional[SlotStatus] = None  # New status value
    abort_reason: Optional[AbortReason] = None  # Reason for abort
    abort_note: Optional[str] = None         # Optional note for abort


@dataclass
class MutationResult:
    """Result of applying a single mutation."""
    op: OpType
    tour_instance_id: int
    status: ValidationStatus
    validation_mode: str
    violations: List[Dict[str, Any]] = field(default_factory=list)
    hard_block_reason: Optional[HardBlockReason] = None
    soft_block_reasons: List[SoftBlockReason] = field(default_factory=list)
    mutation_id: Optional[UUID] = None
    sequence_no: Optional[int] = None


@dataclass
class DraftSummary:
    """Summary of current draft state."""
    pending_changes: int
    hard_blocks: int
    soft_blocks: int
    unknown: int
    valid: int


@dataclass
class ApplyResult:
    """Result of applying a batch of mutations."""
    success: bool
    session_id: UUID
    operations_applied: int
    operations_rejected: int
    results: List[MutationResult]
    draft_summary: DraftSummary


# =============================================================================
# IDEMPOTENCY
# =============================================================================

def compute_mutation_hash(
    tenant_id: int,
    repair_id: UUID,
    op_type: OpType,
    tour_instance_id: int,
    driver_id: Optional[str],
    day: int,
) -> str:
    """
    Compute SHA-256 hash for idempotency.

    Same inputs always produce same hash.
    """
    content = (
        f"{tenant_id}:{repair_id}:{op_type.value}:"
        f"{tour_instance_id}:{driver_id or 'NULL'}:{day}"
    )
    return hashlib.sha256(content.encode()).hexdigest()


# =============================================================================
# HARD BLOCK CHECKS
# =============================================================================

async def check_hard_blocks(
    conn,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    repair_id: UUID,
    op: MutationOp,
) -> Optional[HardBlockReason]:
    """
    Check for hard blocks that prevent the operation.

    Hard blocks are checked BEFORE storing the mutation.
    If a hard block is found, the operation is rejected immediately.

    Returns:
        HardBlockReason if blocked, None if allowed
    """
    # 1. Check tour instance exists
    tour_row = await conn.fetchrow(
        """
        SELECT ti.id, ti.start_ts, ti.end_ts, ti.day
        FROM tour_instances ti
        JOIN forecast_versions fv ON ti.forecast_version_id = fv.id
        JOIN plan_versions pv ON pv.forecast_version_id = fv.id
        WHERE ti.id = $1 AND pv.id = $2 AND pv.tenant_id = $3
        """,
        op.tour_instance_id, plan_version_id, tenant_id
    )
    if not tour_row:
        logger.warning(f"Tour instance {op.tour_instance_id} not found for plan {plan_version_id}")
        return HardBlockReason.TOUR_NOT_FOUND

    # 2. Check driver exists (for ASSIGN/MOVE)
    if op.op in (OpType.ASSIGN, OpType.MOVE) and op.driver_id:
        driver_row = await conn.fetchrow(
            """
            SELECT id FROM drivers
            WHERE id = $1 AND tenant_id = $2
            """,
            int(op.driver_id), tenant_id
        )
        if not driver_row:
            logger.warning(f"Driver {op.driver_id} not found for tenant {tenant_id}")
            return HardBlockReason.DRIVER_NOT_FOUND

    # 3. Check current assignment state
    current_assignment = await conn.fetchrow(
        """
        SELECT a.id, a.driver_id
        FROM assignments a
        WHERE a.plan_version_id = $1
          AND a.tour_instance_id = $2
        """,
        plan_version_id, op.tour_instance_id
    )

    # Check UNASSIGN/MOVE requires existing assignment
    if op.op in (OpType.UNASSIGN, OpType.MOVE):
        if not current_assignment:
            return HardBlockReason.NOT_ASSIGNED
        if op.op == OpType.MOVE and op.from_driver_id:
            if str(current_assignment["driver_id"]) != str(op.from_driver_id):
                logger.warning(f"Move from_driver_id mismatch: expected {current_assignment['driver_id']}, got {op.from_driver_id}")
                return HardBlockReason.NOT_ASSIGNED

    # Check ASSIGN requires no existing assignment
    if op.op == OpType.ASSIGN and current_assignment:
        return HardBlockReason.ALREADY_ASSIGNED

    # 4. Check pin conflicts
    if op.op in (OpType.UNASSIGN, OpType.MOVE):
        pin_row = await conn.fetchrow(
            """
            SELECT p.id, p.reason_code
            FROM roster.pins p
            WHERE p.tenant_id = $1
              AND p.plan_version_id = $2
              AND p.tour_instance_id = $3
              AND p.is_active = TRUE
            """,
            tenant_id, plan_version_id, op.tour_instance_id
        )
        if pin_row:
            logger.info(f"Pin conflict on tour {op.tour_instance_id}: {pin_row['reason_code']}")
            return HardBlockReason.PIN_CONFLICT

    # 5. Check overlap for ASSIGN/MOVE
    if op.op in (OpType.ASSIGN, OpType.MOVE) and op.driver_id:
        # Get the tour's time window
        tour_start = tour_row["start_ts"]
        tour_end = tour_row["end_ts"]
        tour_day = tour_row["day"]

        # Check for overlapping assignments for the driver
        overlap_row = await conn.fetchrow(
            """
            SELECT a.id, ti.start_ts, ti.end_ts
            FROM assignments a
            JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = $1
              AND a.driver_id = $2
              AND ti.day = $3
              AND a.tour_instance_id != $4
              AND (
                  (ti.start_ts < $6 AND ti.end_ts > $5) OR
                  (ti.start_ts >= $5 AND ti.start_ts < $6)
              )
            """,
            plan_version_id, op.driver_id, tour_day, op.tour_instance_id,
            tour_start, tour_end
        )
        if overlap_row:
            logger.info(f"Overlap detected for driver {op.driver_id} on day {tour_day}")
            return HardBlockReason.OVERLAP

    # 6. Check rest time violation (11h minimum)
    # This would check previous/next day assignments
    # For MVP, we skip this and let full validation catch it
    # TODO: Implement rest time check for instant feedback

    return None  # No hard blocks


# =============================================================================
# SOFT BLOCK CHECKS
# =============================================================================

async def check_soft_blocks(
    conn,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    op: MutationOp,
) -> List[SoftBlockReason]:
    """
    Check for soft blocks that allow the operation but require acknowledgment.

    Returns:
        List of SoftBlockReason (empty if none)
    """
    reasons = []

    if op.op in (OpType.ASSIGN, OpType.MOVE) and op.driver_id:
        # 1. Check skill/vehicle compatibility
        # For now, always flag as unknown if tour has skill requirement
        tour_skill = await conn.fetchrow(
            """
            SELECT ti.skill, tn.skill as template_skill
            FROM tour_instances ti
            JOIN tours_normalized tn ON ti.tour_template_id = tn.id
            WHERE ti.id = $1
            """,
            op.tour_instance_id
        )
        if tour_skill and (tour_skill["skill"] or tour_skill["template_skill"]):
            # Check if driver has the skill
            # For MVP, flag as unknown (data quality issue)
            reasons.append(SoftBlockReason.COMPATIBILITY_UNKNOWN)

        # 2. Check weekly hours
        # TODO: Implement hours calculation
        # For MVP, skip this check

    return reasons


# =============================================================================
# MAIN MUTATION ENGINE
# =============================================================================

async def apply_mutations(
    conn,
    tenant_id: int,
    site_id: int,
    repair_id: UUID,
    plan_version_id: int,
    operations: List[MutationOp],
    validation_mode: str,
    performed_by: str,
    idempotency_key: Optional[str] = None,
) -> ApplyResult:
    """
    Apply a batch of draft mutations to a repair session.

    Args:
        conn: Async database connection
        tenant_id: Tenant ID
        site_id: Site ID
        repair_id: Repair session UUID
        plan_version_id: Plan version being repaired
        operations: List of mutation operations
        validation_mode: "none" | "fast" | "full"
        performed_by: User performing the action
        idempotency_key: Optional batch idempotency key

    Returns:
        ApplyResult with all mutation results
    """
    results: List[MutationResult] = []
    applied_count = 0
    rejected_count = 0

    # Validate session is OPEN
    session = await conn.fetchrow(
        """
        SELECT r.repair_id, r.status, r.expires_at, r.plan_version_id
        FROM roster.repairs r
        WHERE r.repair_id = $1 AND r.tenant_id = $2
        """,
        repair_id, tenant_id
    )
    if not session:
        raise ValueError(f"Repair session {repair_id} not found")
    if session["status"] != "OPEN":
        raise ValueError(f"Repair session is {session['status']}, expected OPEN")
    if session["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("Repair session has expired")

    for op in operations:
        # Compute idempotency hash
        op_hash = compute_mutation_hash(
            tenant_id, repair_id, op.op, op.tour_instance_id, op.driver_id, op.day
        )

        # Check for existing mutation with same hash (idempotent return)
        existing = await conn.fetchrow(
            """
            SELECT mutation_id, sequence_no, validation_status, violations_json
            FROM roster.draft_mutations
            WHERE repair_id = $1 AND idempotency_hash = $2
            """,
            repair_id, op_hash
        )
        if existing:
            # Idempotent return
            results.append(MutationResult(
                op=op.op,
                tour_instance_id=op.tour_instance_id,
                status=ValidationStatus(existing["validation_status"]),
                validation_mode=validation_mode,
                violations=existing["violations_json"] or [],
                mutation_id=existing["mutation_id"],
                sequence_no=existing["sequence_no"],
            ))
            applied_count += 1
            continue

        # Check hard blocks
        hard_block = await check_hard_blocks(
            conn, tenant_id, site_id, plan_version_id, repair_id, op
        )
        if hard_block:
            # Hard block - reject immediately, don't store
            results.append(MutationResult(
                op=op.op,
                tour_instance_id=op.tour_instance_id,
                status=ValidationStatus.HARD_BLOCK,
                validation_mode=validation_mode,
                hard_block_reason=hard_block,
                violations=[{
                    "type": hard_block.value,
                    "severity": "BLOCK",
                    "message": f"Operation blocked: {hard_block.value}",
                }],
            ))
            rejected_count += 1
            continue

        # Check soft blocks
        soft_blocks = await check_soft_blocks(
            conn, tenant_id, site_id, plan_version_id, op
        )

        # Determine validation status
        if validation_mode == "none":
            status = ValidationStatus.UNKNOWN
        elif soft_blocks:
            status = ValidationStatus.SOFT_BLOCK
        else:
            status = ValidationStatus.VALID

        # Get next sequence number
        seq_row = await conn.fetchrow(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 as next_seq
            FROM roster.draft_mutations
            WHERE repair_id = $1 AND undone_at IS NULL
            """,
            repair_id
        )
        next_seq = seq_row["next_seq"]

        # Build violations list
        violations = [
            {
                "type": reason.value,
                "severity": "WARN",
                "message": f"Soft block: {reason.value}",
            }
            for reason in soft_blocks
        ]

        # Insert mutation
        mutation_id = uuid4()
        await conn.execute(
            """
            INSERT INTO roster.draft_mutations (
                mutation_id, repair_id, tenant_id,
                op_type, sequence_no,
                tour_instance_id, day, driver_id, from_driver_id,
                block_id, slot_index,
                validation_status, validation_mode, violations_json,
                idempotency_hash, created_by
            ) VALUES (
                $1, $2, $3,
                $4, $5,
                $6, $7, $8, $9,
                $10, $11,
                $12, $13, $14,
                $15, $16
            )
            """,
            mutation_id, repair_id, tenant_id,
            op.op.value, next_seq,
            op.tour_instance_id, op.day, op.driver_id, op.from_driver_id,
            op.block_id, op.slot_index,
            status.value, validation_mode, violations,
            op_hash, performed_by
        )

        results.append(MutationResult(
            op=op.op,
            tour_instance_id=op.tour_instance_id,
            status=status,
            validation_mode=validation_mode,
            violations=violations,
            soft_block_reasons=soft_blocks,
            mutation_id=mutation_id,
            sequence_no=next_seq,
        ))
        applied_count += 1

    # Compute draft summary
    summary_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE undone_at IS NULL) as pending,
            COUNT(*) FILTER (WHERE validation_status = 'HARD_BLOCK' AND undone_at IS NULL) as hard,
            COUNT(*) FILTER (WHERE validation_status = 'SOFT_BLOCK' AND undone_at IS NULL) as soft,
            COUNT(*) FILTER (WHERE validation_status = 'UNKNOWN' AND undone_at IS NULL) as unknown,
            COUNT(*) FILTER (WHERE validation_status = 'VALID' AND undone_at IS NULL) as valid
        FROM roster.draft_mutations
        WHERE repair_id = $1
        """,
        repair_id
    )

    draft_summary = DraftSummary(
        pending_changes=summary_row["pending"],
        hard_blocks=summary_row["hard"],
        soft_blocks=summary_row["soft"],
        unknown=summary_row["unknown"],
        valid=summary_row["valid"],
    )

    logger.info(
        "draft_mutations_applied",
        extra={
            "repair_id": str(repair_id),
            "applied": applied_count,
            "rejected": rejected_count,
            "tenant_id": tenant_id,
        }
    )

    return ApplyResult(
        success=True,
        session_id=repair_id,
        operations_applied=applied_count,
        operations_rejected=rejected_count,
        results=results,
        draft_summary=draft_summary,
    )


# =============================================================================
# DRAFT STATE QUERIES
# =============================================================================

async def get_draft_state(
    conn,
    tenant_id: int,
    repair_id: UUID,
) -> Dict[str, Any]:
    """
    Get the current draft state for a repair session.

    Returns all active (non-undone) mutations.
    """
    rows = await conn.fetch(
        """
        SELECT
            mutation_id, op_type, sequence_no,
            tour_instance_id, day, driver_id, from_driver_id,
            block_id, slot_index,
            validation_status, validation_mode, violations_json,
            created_by, created_at
        FROM roster.draft_mutations
        WHERE repair_id = $1 AND tenant_id = $2 AND undone_at IS NULL
        ORDER BY sequence_no ASC
        """,
        repair_id, tenant_id
    )

    return {
        "mutations": [
            {
                "mutation_id": str(row["mutation_id"]),
                "op_type": row["op_type"],
                "sequence_no": row["sequence_no"],
                "tour_instance_id": row["tour_instance_id"],
                "day": row["day"],
                "driver_id": row["driver_id"],
                "from_driver_id": row["from_driver_id"],
                "block_id": row["block_id"],
                "slot_index": row["slot_index"],
                "validation_status": row["validation_status"],
                "validation_mode": row["validation_mode"],
                "violations": row["violations_json"] or [],
                "created_by": row["created_by"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
    }


async def undo_last_mutation(
    conn,
    tenant_id: int,
    repair_id: UUID,
    performed_by: str,
) -> Optional[Dict[str, Any]]:
    """
    Undo the most recent active mutation.

    Returns the undone mutation, or None if no mutations to undo.
    """
    # Find most recent active mutation
    last = await conn.fetchrow(
        """
        SELECT mutation_id, op_type, sequence_no, tour_instance_id
        FROM roster.draft_mutations
        WHERE repair_id = $1 AND tenant_id = $2 AND undone_at IS NULL
        ORDER BY sequence_no DESC
        LIMIT 1
        """,
        repair_id, tenant_id
    )
    if not last:
        return None

    # Mark as undone
    await conn.execute(
        """
        UPDATE roster.draft_mutations
        SET undone_at = NOW(), undone_by = $3
        WHERE mutation_id = $1 AND tenant_id = $2
        """,
        last["mutation_id"], tenant_id, performed_by
    )

    logger.info(
        "draft_mutation_undone",
        extra={
            "mutation_id": str(last["mutation_id"]),
            "repair_id": str(repair_id),
            "tenant_id": tenant_id,
        }
    )

    return {
        "mutation_id": str(last["mutation_id"]),
        "op_type": last["op_type"],
        "sequence_no": last["sequence_no"],
        "tour_instance_id": last["tour_instance_id"],
    }


# =============================================================================
# DAY FREEZE GUARD
# =============================================================================

async def check_day_frozen(
    conn,
    tenant_id: int,
    site_id: int,
    day_date,
) -> bool:
    """
    Check if a day is frozen (immutable).

    Returns True if frozen, False if open or no record exists.
    """
    row = await conn.fetchrow(
        """
        SELECT status FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
        """,
        tenant_id, site_id, day_date
    )
    return row is not None and row["status"] == "FROZEN"


async def get_day_status(
    conn,
    tenant_id: int,
    site_id: int,
    day_date,
) -> Dict[str, Any]:
    """
    Get the status of a workbench day.

    Returns day info including frozen status, stats, and evidence.
    """
    row = await conn.fetchrow(
        """
        SELECT day_id, status, frozen_at, frozen_by_user_id,
               final_stats, evidence_id, created_at, updated_at
        FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
        """,
        tenant_id, site_id, day_date
    )

    if not row:
        return {
            "exists": False,
            "status": "OPEN",
            "is_frozen": False,
            "day_date": str(day_date),
        }

    return {
        "exists": True,
        "day_id": str(row["day_id"]),
        "status": row["status"],
        "is_frozen": row["status"] == "FROZEN",
        "frozen_at": row["frozen_at"].isoformat() if row["frozen_at"] else None,
        "frozen_by_user_id": row["frozen_by_user_id"],
        "final_stats": row["final_stats"],
        "evidence_id": str(row["evidence_id"]) if row["evidence_id"] else None,
        "day_date": str(day_date),
    }


# =============================================================================
# SLOT STATUS MUTATIONS (ABORT)
# =============================================================================

def compute_slot_status_hash(
    tenant_id: int,
    site_id: int,
    slot_id: UUID,
    new_status: SlotStatus,
    abort_reason: Optional[AbortReason],
    abort_note: Optional[str],
    performed_by: str,
    day_date,
) -> str:
    """
    Compute SHA-256 hash for slot status change idempotency.
    """
    content = (
        f"{tenant_id}:{site_id}:{slot_id}:{new_status.value}:"
        f"{abort_reason.value if abort_reason else 'NULL'}:"
        f"{abort_note or 'NULL'}:{performed_by}:{day_date}"
    )
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class SlotStatusResult:
    """Result of a slot status change operation."""
    success: bool
    slot_id: UUID
    previous_status: Optional[SlotStatus]
    new_status: SlotStatus
    hard_block_reason: Optional[HardBlockReason] = None
    idempotent_return: bool = False
    error_message: Optional[str] = None


async def set_slot_status(
    conn,
    tenant_id: int,
    site_id: int,
    slot_id: UUID,
    new_status: SlotStatus,
    abort_reason: Optional[AbortReason],
    abort_note: Optional[str],
    performed_by: str,
) -> SlotStatusResult:
    """
    Set the status of a dispatch slot.

    For ABORTED status, requires abort_reason.
    Checks freeze guard before mutation.

    Returns:
        SlotStatusResult with success/failure details
    """
    # 1. Get slot info
    slot = await conn.fetchrow(
        """
        SELECT slot_id, tenant_id, site_id, day_date, status,
               abort_reason, abort_note
        FROM dispatch.daily_slots
        WHERE slot_id = $1 AND tenant_id = $2
        """,
        slot_id, tenant_id
    )

    if not slot:
        return SlotStatusResult(
            success=False,
            slot_id=slot_id,
            previous_status=None,
            new_status=new_status,
            hard_block_reason=HardBlockReason.SLOT_NOT_FOUND,
            error_message=f"Slot {slot_id} not found",
        )

    # 2. Check if day is frozen
    is_frozen = await check_day_frozen(conn, tenant_id, site_id, slot["day_date"])
    if is_frozen:
        return SlotStatusResult(
            success=False,
            slot_id=slot_id,
            previous_status=SlotStatus(slot["status"]),
            new_status=new_status,
            hard_block_reason=HardBlockReason.DAY_FROZEN,
            error_message=f"Day {slot['day_date']} is frozen, no mutations allowed",
        )

    previous_status = SlotStatus(slot["status"])

    # 3. Validate status transition
    if new_status == SlotStatus.ABORTED:
        if previous_status == SlotStatus.ABORTED:
            # Already aborted - check if same reason (idempotent)
            if (slot["abort_reason"] == abort_reason.value if abort_reason else None):
                return SlotStatusResult(
                    success=True,
                    slot_id=slot_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    idempotent_return=True,
                )
            return SlotStatusResult(
                success=False,
                slot_id=slot_id,
                previous_status=previous_status,
                new_status=new_status,
                hard_block_reason=HardBlockReason.ALREADY_ABORTED,
                error_message="Slot already aborted",
            )

        if not abort_reason:
            return SlotStatusResult(
                success=False,
                slot_id=slot_id,
                previous_status=previous_status,
                new_status=new_status,
                hard_block_reason=HardBlockReason.INVALID_STATUS_TRANSITION,
                error_message="abort_reason required for ABORTED status",
            )

    # 4. Apply the status change
    if new_status == SlotStatus.ABORTED:
        await conn.execute(
            """
            UPDATE dispatch.daily_slots
            SET status = $3,
                abort_reason = $4,
                abort_note = $5,
                abort_set_at = NOW(),
                abort_set_by_user_id = $6,
                updated_at = NOW()
            WHERE slot_id = $1 AND tenant_id = $2
            """,
            slot_id, tenant_id, new_status.value,
            abort_reason.value if abort_reason else None,
            abort_note, performed_by
        )
    else:
        await conn.execute(
            """
            UPDATE dispatch.daily_slots
            SET status = $3,
                abort_reason = NULL,
                abort_note = NULL,
                abort_set_at = NULL,
                abort_set_by_user_id = NULL,
                updated_at = NOW()
            WHERE slot_id = $1 AND tenant_id = $2
            """,
            slot_id, tenant_id, new_status.value
        )

    logger.info(
        "slot_status_changed",
        extra={
            "slot_id": str(slot_id),
            "tenant_id": tenant_id,
            "previous_status": previous_status.value,
            "new_status": new_status.value,
            "abort_reason": abort_reason.value if abort_reason else None,
            "performed_by": performed_by,
        }
    )

    return SlotStatusResult(
        success=True,
        slot_id=slot_id,
        previous_status=previous_status,
        new_status=new_status,
    )


# =============================================================================
# BATCH SLOT STATUS (for bulk abort)
# =============================================================================

@dataclass
class BatchSlotStatusResult:
    """Result of batch slot status operations."""
    success: bool
    total: int
    applied: int
    rejected: int
    results: List[SlotStatusResult]


async def batch_set_slot_status(
    conn,
    tenant_id: int,
    site_id: int,
    operations: List[Dict[str, Any]],
    performed_by: str,
) -> BatchSlotStatusResult:
    """
    Apply multiple slot status changes in batch.

    Each operation should have:
    - slot_id: UUID
    - new_status: SlotStatus
    - abort_reason: Optional[AbortReason]
    - abort_note: Optional[str]

    IDEMPOTENCY: Operations are sorted by slot_id before processing.
    This ensures the same batch with different ordering produces consistent results.

    Returns:
        BatchSlotStatusResult with individual results
    """
    results: List[SlotStatusResult] = []
    applied = 0
    rejected = 0

    # CRITICAL: Sort operations by slot_id for idempotency
    # Same batch in different order -> same hash -> same result
    sorted_operations = sorted(operations, key=lambda x: str(x.get("slot_id", "")))

    for op in sorted_operations:
        result = await set_slot_status(
            conn=conn,
            tenant_id=tenant_id,
            site_id=site_id,
            slot_id=UUID(op["slot_id"]) if isinstance(op["slot_id"], str) else op["slot_id"],
            new_status=SlotStatus(op["new_status"]) if isinstance(op["new_status"], str) else op["new_status"],
            abort_reason=AbortReason(op["abort_reason"]) if op.get("abort_reason") else None,
            abort_note=op.get("abort_note"),
            performed_by=performed_by,
        )

        results.append(result)
        if result.success:
            applied += 1
        else:
            rejected += 1

    return BatchSlotStatusResult(
        success=rejected == 0,
        total=len(operations),
        applied=applied,
        rejected=rejected,
        results=results,
    )


# =============================================================================
# REPAIR SESSION HELPERS (for integration with orchestrator)
# =============================================================================

async def get_or_create_repair_session(
    conn,
    tenant_id: int,
    plan_version_id: int,
    trigger_type: str,
    description: str,
) -> UUID:
    """
    Get or create a repair session for the given plan version.

    Idempotent: returns existing open session if one exists.
    """
    # Check for existing open session
    existing = await conn.fetchrow(
        """
        SELECT repair_id FROM roster.repairs
        WHERE tenant_id = $1 AND plan_version_id = $2 AND status = 'OPEN'
        ORDER BY created_at DESC LIMIT 1
        """,
        tenant_id, plan_version_id
    )
    if existing:
        return existing["repair_id"]

    # Create new session
    repair_id = uuid4()
    await conn.execute(
        """
        INSERT INTO roster.repairs (
            repair_id, tenant_id, plan_version_id,
            trigger_type, description, status, expires_at
        ) VALUES ($1, $2, $3, $4, $5, 'OPEN', NOW() + INTERVAL '4 hours')
        """,
        repair_id, tenant_id, plan_version_id, trigger_type, description
    )

    logger.info(
        "repair_session_created",
        extra={
            "repair_id": str(repair_id),
            "tenant_id": tenant_id,
            "plan_version_id": plan_version_id,
            "trigger_type": trigger_type,
        }
    )

    return repair_id
