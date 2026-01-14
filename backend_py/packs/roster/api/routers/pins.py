"""
SOLVEREIGN V4.6 - Roster Pins API
==================================

Pin management endpoints for anti-churn stability.

Routes:
- GET    /api/v1/roster/plans/{plan_id}/pins      - List all pins
- POST   /api/v1/roster/plans/{plan_id}/pins      - Add a pin
- DELETE /api/v1/roster/plans/{plan_id}/pins/{id} - Remove a pin

PIN TYPES:
- MANUAL: Dispatcher/admin pinned
- FREEZE_WINDOW: Auto-pinned during freeze
- DRIVER_ACK: Pinned after driver acknowledgment
- SYSTEM: System-generated pin

SECURITY:
- Tenant isolation via user context
- RLS enforced on all queries
- Audit trail for all pin operations
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4
from enum import Enum

from fastapi import APIRouter, Request, HTTPException, status, Depends, Header, Query
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_csrf_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster", tags=["roster-pins"])


# =============================================================================
# SCHEMAS
# =============================================================================

class PinType(str, Enum):
    MANUAL = "MANUAL"
    FREEZE_WINDOW = "FREEZE_WINDOW"
    DRIVER_ACK = "DRIVER_ACK"
    SYSTEM = "SYSTEM"


class ReasonCode(str, Enum):
    DRIVER_REQUEST = "DRIVER_REQUEST"
    DISPATCHER_DECISION = "DISPATCHER_DECISION"
    CONTRACTUAL = "CONTRACTUAL"
    OPERATIONAL = "OPERATIONAL"
    FREEZE_WINDOW = "FREEZE_WINDOW"
    ACK_LOCKED = "ACK_LOCKED"
    OTHER = "OTHER"


class AddPinRequest(BaseModel):
    """Request to add a pin."""
    driver_id: str = Field(..., description="Driver ID to pin")
    tour_instance_id: int = Field(..., description="Tour instance ID")
    day: int = Field(..., ge=1, le=7, description="Day of week (1-7)")
    reason_code: ReasonCode = Field(..., description="Reason for pinning")
    note: Optional[str] = Field(None, min_length=5, description="Optional audit note")
    pin_type: PinType = Field(PinType.MANUAL, description="Pin type")


class PinResponse(BaseModel):
    """Single pin response."""
    id: int
    pin_id: str
    driver_id: str
    tour_instance_id: int
    day: int
    pin_type: str
    reason_code: str
    note: Optional[str]
    pinned_at: str
    pinned_by: str
    is_active: bool


class AddPinResponse(BaseModel):
    """Response from add pin."""
    success: bool = True
    pin: PinResponse
    message: str


class RemovePinRequest(BaseModel):
    """Request to remove a pin."""
    unpin_reason: str = Field(..., min_length=5, description="Required reason for unpinning")


class RemovePinResponse(BaseModel):
    """Response from remove pin."""
    success: bool = True
    pin_id: str
    message: str


class PinsListResponse(BaseModel):
    """Response from list pins."""
    success: bool = True
    plan_version_id: int
    pins: List[PinResponse]
    count: int


class BulkPinCheckRequest(BaseModel):
    """Request to check pins in bulk."""
    assignment_keys: List[str] = Field(..., description="List of keys: 'driver_id:tour_id:day'")


class BulkPinCheckResponse(BaseModel):
    """Response from bulk pin check."""
    success: bool = True
    plan_version_id: int
    pinned: List[str]
    not_pinned: List[str]


# =============================================================================
# IDEMPOTENCY
# =============================================================================

def require_pin_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
) -> str:
    """Require idempotency key on pin operations."""
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "x-idempotency-key header is required for pin operations",
            },
        )
    try:
        UUID(x_idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_IDEMPOTENCY_KEY",
                "message": "x-idempotency-key must be a valid UUID",
            },
        )
    return x_idempotency_key


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/plans/{plan_id}/pins", response_model=PinsListResponse)
async def list_pins(
    request: Request,
    plan_id: int,
    include_inactive: bool = Query(False, description="Include inactive pins"),
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    List all pins for a plan version.

    Returns active pins by default. Use include_inactive=true to see all.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify plan exists
        cur.execute(
            """
            SELECT id FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found or access denied",
            )

        # Load pins
        if include_inactive:
            cur.execute(
                """
                SELECT id, pin_id, driver_id, tour_instance_id, day,
                       pin_type, reason_code, note, pinned_at, pinned_by, is_active
                FROM roster.pins
                WHERE plan_version_id = %s AND tenant_id = %s
                ORDER BY pinned_at DESC
                """,
                (plan_id, ctx.tenant_id)
            )
        else:
            cur.execute(
                """
                SELECT id, pin_id, driver_id, tour_instance_id, day,
                       pin_type, reason_code, note, pinned_at, pinned_by, is_active
                FROM roster.pins
                WHERE plan_version_id = %s AND tenant_id = %s AND is_active = TRUE
                ORDER BY pinned_at DESC
                """,
                (plan_id, ctx.tenant_id)
            )

        pins_raw = cur.fetchall()

    pins = []
    for row in pins_raw:
        pins.append(PinResponse(
            id=row[0],
            pin_id=str(row[1]),
            driver_id=row[2],
            tour_instance_id=row[3],
            day=row[4],
            pin_type=row[5],
            reason_code=row[6],
            note=row[7],
            pinned_at=row[8].isoformat() if row[8] else None,
            pinned_by=row[9],
            is_active=row[10],
        ))

    logger.info(
        "pins_listed",
        extra={
            "plan_id": plan_id,
            "count": len(pins),
            "tenant_id": ctx.tenant_id,
        }
    )

    return PinsListResponse(
        success=True,
        plan_version_id=plan_id,
        pins=pins,
        count=len(pins),
    )


@router.post(
    "/plans/{plan_id}/pins",
    response_model=AddPinResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def add_pin(
    request: Request,
    plan_id: int,
    body: AddPinRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_pin_idempotency_key),
):
    """
    Add a pin to an assignment.

    Pins prevent the solver/repair from modifying specific assignments.
    Requires reason_code for audit trail.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Verify plan exists
        cur.execute(
            """
            SELECT id, site_id FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found or access denied",
            )

        site_id = ctx.site_id or plan[1]

        # Check if already pinned
        cur.execute(
            """
            SELECT id, pin_id, is_active FROM roster.pins
            WHERE plan_version_id = %s AND tenant_id = %s
              AND driver_id = %s AND tour_instance_id = %s AND day = %s
            """,
            (plan_id, ctx.tenant_id, body.driver_id, body.tour_instance_id, body.day)
        )
        existing = cur.fetchone()

        if existing:
            if existing[2]:  # is_active
                # Already pinned and active - idempotent return
                cur.execute(
                    """
                    SELECT id, pin_id, driver_id, tour_instance_id, day,
                           pin_type, reason_code, note, pinned_at, pinned_by, is_active
                    FROM roster.pins WHERE id = %s
                    """,
                    (existing[0],)
                )
                row = cur.fetchone()
                return AddPinResponse(
                    success=True,
                    pin=PinResponse(
                        id=row[0],
                        pin_id=str(row[1]),
                        driver_id=row[2],
                        tour_instance_id=row[3],
                        day=row[4],
                        pin_type=row[5],
                        reason_code=row[6],
                        note=row[7],
                        pinned_at=row[8].isoformat() if row[8] else None,
                        pinned_by=row[9],
                        is_active=row[10],
                    ),
                    message="Pin already exists (idempotent return)",
                )
            else:
                # Was unpinned - reactivate
                cur.execute(
                    """
                    UPDATE roster.pins
                    SET is_active = TRUE, unpinned_at = NULL, unpinned_by = NULL, unpin_reason = NULL,
                        pinned_at = %s, pinned_by = %s, pin_type = %s, reason_code = %s, note = %s
                    WHERE id = %s
                    RETURNING id, pin_id
                    """,
                    (now, performed_by, body.pin_type.value, body.reason_code.value, body.note, existing[0])
                )
                updated = cur.fetchone()
                pin_id_str = str(updated[1])
        else:
            # Create new pin
            cur.execute(
                """
                INSERT INTO roster.pins (
                    tenant_id, site_id, plan_version_id,
                    driver_id, tour_instance_id, day,
                    pin_type, reason_code, note,
                    pinned_at, pinned_by, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                RETURNING id, pin_id
                """,
                (
                    ctx.tenant_id, site_id, plan_id,
                    body.driver_id, body.tour_instance_id, body.day,
                    body.pin_type.value, body.reason_code.value, body.note,
                    now, performed_by,
                )
            )
            new_pin = cur.fetchone()
            pin_id_str = str(new_pin[1])

        # Record audit note
        cur.execute(
            """
            SELECT roster.record_audit_note(%s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                ctx.tenant_id, site_id, plan_id,
                'PIN', pin_id_str, performed_by,
                body.reason_code.value,
                body.note or f"Pin added: {body.driver_id}:{body.tour_instance_id}:{body.day}",
            )
        )

        conn.commit()

        # Fetch the pin for response
        cur.execute(
            """
            SELECT id, pin_id, driver_id, tour_instance_id, day,
                   pin_type, reason_code, note, pinned_at, pinned_by, is_active
            FROM roster.pins WHERE pin_id = %s
            """,
            (pin_id_str,)
        )
        row = cur.fetchone()

    logger.info(
        "pin_added",
        extra={
            "plan_id": plan_id,
            "pin_id": pin_id_str,
            "driver_id": body.driver_id,
            "tenant_id": ctx.tenant_id,
        }
    )

    return AddPinResponse(
        success=True,
        pin=PinResponse(
            id=row[0],
            pin_id=str(row[1]),
            driver_id=row[2],
            tour_instance_id=row[3],
            day=row[4],
            pin_type=row[5],
            reason_code=row[6],
            note=row[7],
            pinned_at=row[8].isoformat() if row[8] else None,
            pinned_by=row[9],
            is_active=row[10],
        ),
        message="Pin added successfully",
    )


@router.delete(
    "/plans/{plan_id}/pins/{pin_id}",
    response_model=RemovePinResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def remove_pin(
    request: Request,
    plan_id: int,
    pin_id: str,
    body: RemovePinRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
):
    """
    Remove (soft-delete) a pin.

    Requires unpin_reason for audit trail.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Verify pin exists and is active
        cur.execute(
            """
            SELECT id, site_id, is_active FROM roster.pins
            WHERE pin_id = %s AND plan_version_id = %s AND tenant_id = %s
            """,
            (pin_id, plan_id, ctx.tenant_id)
        )
        existing = cur.fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pin {pin_id} not found",
            )

        if not existing[2]:  # not is_active
            return RemovePinResponse(
                success=True,
                pin_id=pin_id,
                message="Pin already inactive (idempotent return)",
            )

        site_id = ctx.site_id or existing[1]

        # Soft delete
        cur.execute(
            """
            UPDATE roster.pins
            SET is_active = FALSE, unpinned_at = %s, unpinned_by = %s, unpin_reason = %s
            WHERE pin_id = %s
            """,
            (now, performed_by, body.unpin_reason, pin_id)
        )

        # Record audit note
        cur.execute(
            """
            SELECT roster.record_audit_note(%s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                ctx.tenant_id, site_id, plan_id,
                'PIN', pin_id, performed_by,
                'OTHER',
                body.unpin_reason,
            )
        )

        conn.commit()

    logger.info(
        "pin_removed",
        extra={
            "plan_id": plan_id,
            "pin_id": pin_id,
            "tenant_id": ctx.tenant_id,
        }
    )

    return RemovePinResponse(
        success=True,
        pin_id=pin_id,
        message="Pin removed successfully",
    )


@router.post("/plans/{plan_id}/pins/bulk-check", response_model=BulkPinCheckResponse)
async def bulk_check_pins(
    request: Request,
    plan_id: int,
    body: BulkPinCheckRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Check pin status for multiple assignments.

    Assignment keys are in format: 'driver_id:tour_instance_id:day'
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Load all active pins for this plan
        cur.execute(
            """
            SELECT driver_id, tour_instance_id, day
            FROM roster.pins
            WHERE plan_version_id = %s AND tenant_id = %s AND is_active = TRUE
            """,
            (plan_id, ctx.tenant_id)
        )
        pins_raw = cur.fetchall()

    # Build set of pinned keys
    pinned_keys = {f"{row[0]}:{row[1]}:{row[2]}" for row in pins_raw}

    # Check each requested key
    pinned = []
    not_pinned = []
    for key in body.assignment_keys:
        if key in pinned_keys:
            pinned.append(key)
        else:
            not_pinned.append(key)

    return BulkPinCheckResponse(
        success=True,
        plan_version_id=plan_id,
        pinned=pinned,
        not_pinned=not_pinned,
    )
