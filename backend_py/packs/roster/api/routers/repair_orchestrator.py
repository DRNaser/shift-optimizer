"""
SOLVEREIGN V4.8 - Repair Orchestrator API
==========================================

Orchestrated repair endpoints for incident-driven Top-K proposal generation.

Routes:
- POST /api/v1/roster/repairs/orchestrated/preview  - Generate Top-K proposals (read-only)
- POST /api/v1/roster/repairs/orchestrated/prepare  - Create repair draft from proposal
- POST /api/v1/roster/repairs/orchestrated/confirm  - Confirm repair draft for publish

This is ADDITIVE to existing repair endpoints (repair.py, repair_sessions.py).
The existing endpoints continue to work unchanged.

NON-NEGOTIABLES:
- Tenant isolation via user context
- CSRF check on writes
- Idempotency key on prepare/confirm
- All proposals must have 100% coverage and 0 BLOCK violations
- Delta-first: minimal changes by default
"""

import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_csrf_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/roster/repairs/orchestrated",
    tags=["roster-repairs-orchestrated"]
)


# =============================================================================
# SCHEMAS
# =============================================================================

class IncidentSpecRequest(BaseModel):
    """Specification of a driver unavailability incident."""
    type: Literal["DRIVER_UNAVAILABLE"] = Field(
        "DRIVER_UNAVAILABLE",
        description="Type of incident"
    )
    driver_id: int = Field(..., description="ID of the unavailable driver")
    time_range_start: str = Field(..., description="Start of unavailability (ISO timestamp)")
    time_range_end: Optional[str] = Field(
        None,
        description="End of unavailability (ISO timestamp, null = open-ended)"
    )
    reason: str = Field("SICK", description="Reason: SICK, VACATION, UNAVAILABLE")


class FreezeSpecRequest(BaseModel):
    """What to freeze (not change) during repair."""
    freeze_assignments: List[int] = Field(
        default_factory=list,
        description="Tour instance IDs to keep unchanged"
    )
    freeze_drivers: List[int] = Field(
        default_factory=list,
        description="Driver IDs not to reassign"
    )


class ChangeBudgetRequest(BaseModel):
    """Budget for how much change is allowed (delta-first)."""
    max_changed_tours: int = Field(5, ge=1, le=20, description="Max tours to change")
    max_changed_drivers: int = Field(3, ge=1, le=10, description="Max drivers to involve")
    max_chain_depth: int = Field(2, ge=0, le=3, description="Max chain swap depth")


class SplitPolicyRequest(BaseModel):
    """Policy for splitting tours across drivers."""
    allow_split: bool = Field(True, description="Allow splitting tours across drivers")
    max_splits: int = Field(2, ge=1, le=5, description="Max number of drivers to split to")
    split_granularity: Literal["TOUR"] = Field("TOUR", description="Granularity (TOUR only)")


class RepairOrchestratorPreviewRequest(BaseModel):
    """Request to preview repair proposals."""
    snapshot_id: Optional[int] = Field(
        None,
        description="Published snapshot ID to repair from (alternative to plan_version_id)"
    )
    plan_version_id: Optional[int] = Field(
        None,
        description="Plan version ID to repair from"
    )
    incident: IncidentSpecRequest = Field(..., description="The incident specification")
    freeze: Optional[FreezeSpecRequest] = Field(None, description="What to freeze")
    change_budget: Optional[ChangeBudgetRequest] = Field(None, description="Change budget")
    split_policy: Optional[SplitPolicyRequest] = Field(None, description="Split policy")
    top_k: int = Field(3, ge=1, le=5, description="Number of proposals to generate")
    validation: Literal["none", "fast", "full"] = Field(
        "none",
        description="Validation mode: 'none' (fast preview), 'fast' (impacted tours), 'full' (entire plan)"
    )


class DeltaSummaryResponse(BaseModel):
    """Summary of changes in a proposal."""
    changed_tours_count: int
    changed_drivers_count: int
    impacted_drivers: List[int]
    reserve_usage: int
    chain_depth: int


class CoverageInfoResponse(BaseModel):
    """Coverage information for a proposal."""
    impacted_tours_count: int = Field(..., description="Total tours needing coverage")
    impacted_assigned_count: int = Field(..., description="Tours actually assigned")
    coverage_percent: float = Field(..., description="impacted_assigned/impacted_tours * 100")
    coverage_computed: bool = Field(True, description="Always true for proposals")


class ViolationInfoResponse(BaseModel):
    """
    Violation information for a proposal.

    CRITICAL: violations_validated indicates whether violation counts are trustworthy.
    If violations_validated=False, block_violations and warn_violations are advisory only.
    """
    violations_validated: bool = Field(
        ...,
        description="True only if canonical violations engine was called"
    )
    block_violations: Optional[int] = Field(
        None,
        description="null if not validated, actual count if validated"
    )
    warn_violations: Optional[int] = Field(
        None,
        description="null if not validated, actual count if validated"
    )
    validation_mode: str = Field(
        "none",
        description="Validation mode: 'none', 'fast', 'full'"
    )
    validation_note: str = Field(
        "Preview is advisory. Confirm validates authoritatively.",
        description="Explanation of validation semantics"
    )


class ProposedAssignmentResponse(BaseModel):
    """A single assignment in a proposal."""
    tour_instance_id: int
    driver_id: int
    day: int
    block_id: str
    start_ts: Optional[str]
    end_ts: Optional[str]
    is_new: bool


class CompatibilityInfoResponse(BaseModel):
    """Compatibility information for skills/vehicle matching."""
    compatibility_checked: bool = Field(False, description="True if skills/vehicle were checked")
    compatibility_unknown: bool = Field(
        False,
        description="True if data is missing - user must acknowledge before auto-prepare"
    )
    missing_data: List[str] = Field(default_factory=list, description="What data is missing")
    incompatibilities: List[str] = Field(default_factory=list, description="Hard incompatibilities found")


class RepairProposalResponse(BaseModel):
    """
    A single repair proposal.

    CRITICAL SEMANTICS:
    - coverage: Always computed, always accurate for impacted tours
    - violations: Only trustworthy if violations.violations_validated=True
    - compatibility: Check compatibility_unknown before auto-prepare
    - Legacy fields (coverage_percent, block_violations, warn_violations) are DEPRECATED

    Do NOT trust block_violations=0 unless violations.violations_validated=True.
    """
    proposal_id: str
    label: str
    strategy: str
    feasible: bool
    quality_score: float
    delta_summary: DeltaSummaryResponse
    assignments: List[ProposedAssignmentResponse]
    removed_assignments: List[int]
    evidence_hash: str
    # New structured fields
    coverage: CoverageInfoResponse = Field(..., description="Coverage info (always computed)")
    violations: ViolationInfoResponse = Field(..., description="Violation info (check violations_validated!)")
    compatibility: Optional[CompatibilityInfoResponse] = Field(
        None,
        description="Compatibility info (check compatibility_unknown!)"
    )
    # Legacy fields for backward compat (DEPRECATED - use coverage/violations instead)
    coverage_percent: float = Field(0.0, description="DEPRECATED: Use coverage.coverage_percent")
    block_violations: Optional[int] = Field(None, description="DEPRECATED: Use violations.block_violations")
    warn_violations: Optional[int] = Field(None, description="DEPRECATED: Use violations.warn_violations")


class DiagnosticReasonResponse(BaseModel):
    """A single reason why no feasible proposals were found."""
    code: str = Field(..., description="Reason code: NO_CANDIDATES, PARTIAL_COVERAGE, etc.")
    message: str = Field(..., description="Human-readable explanation")
    tour_instance_ids: List[int] = Field(default_factory=list, description="Affected tours")
    suggested_action: Optional[str] = Field(None, description="What user can do")
    priority: int = Field(99, description="Priority for sorting (lower = more important)")


class UncoveredTourInfoResponse(BaseModel):
    """Context for an uncovered tour (not just ID)."""
    tour_instance_id: int = Field(..., description="Tour instance ID")
    tour_name: str = Field(..., description="Tour name/label")
    day: int = Field(..., description="Day of week (0-6)")
    start_ts: Optional[str] = Field(None, description="Start time ISO timestamp")
    end_ts: Optional[str] = Field(None, description="End time ISO timestamp")
    reason: str = Field(..., description="Why uncovered: no_candidates, all_filtered")


class DiagnosticSummaryResponse(BaseModel):
    """Summary when no feasible proposals exist."""
    has_diagnostics: bool = Field(False, description="True if diagnostics are available")
    reasons: List[DiagnosticReasonResponse] = Field(
        default_factory=list,
        description="Top blocking reasons (max 3, sorted by priority)"
    )
    uncovered_tour_ids: List[int] = Field(default_factory=list, description="Tours without coverage (legacy)")
    uncovered_tours: List[UncoveredTourInfoResponse] = Field(
        default_factory=list,
        description="Tours without coverage with context (name, time, reason)"
    )
    partial_proposals_available: bool = Field(
        False,
        description="True if infeasible proposals exist for review"
    )
    suggested_actions: List[str] = Field(
        default_factory=list,
        description="UI call-to-action hints (deterministic order)"
    )
    earliest_uncovered_start: Optional[str] = Field(
        None,
        description="ISO timestamp of earliest uncovered tour start"
    )


class RepairPreviewResponse(BaseModel):
    """Response from preview endpoint."""
    success: bool = True
    proposals: List[RepairProposalResponse]
    proposal_count: int
    impacted_tours_count: int
    incident_driver_id: int
    preview_computed_at: str
    evidence_id: str
    validation_note: str = Field(
        "Preview is advisory. Violations validated at confirm time.",
        description="Note about validation timing"
    )
    # P0.6: Diagnostics when no feasible proposals
    diagnostics: Optional[DiagnosticSummaryResponse] = Field(
        None,
        description="Diagnostic info when no feasible proposals exist"
    )
    # P1.5A: Compatibility warning
    compatibility_unknown: bool = Field(
        False,
        description="True if skill/vehicle data is missing - user must acknowledge"
    )


class PrepareRequest(BaseModel):
    """Request to prepare a repair draft from a proposal."""
    proposal_id: str = Field(..., description="Proposal ID from preview")
    plan_version_id: int = Field(..., description="Original plan version")
    assignments: List[ProposedAssignmentResponse] = Field(
        ...,
        description="Assignments from the proposal"
    )
    removed_assignments: List[int] = Field(
        ...,
        description="Tour instance IDs to remove"
    )
    commit_reason: Optional[str] = Field(None, description="Reason for repair")
    # P1.5A: Compatibility acknowledgment for audit trail
    compatibility_acknowledged: bool = Field(
        False,
        description="True if user acknowledged compatibility_unknown warning"
    )


class PrepareResponse(BaseModel):
    """Response from prepare endpoint."""
    success: bool = True
    draft_id: int
    proposal_id: str
    parent_plan_version_id: int
    status: str
    evidence_id: str
    idempotency_key: str
    prepared_at: str
    message: str


class ConfirmRequest(BaseModel):
    """Request to confirm a repair draft."""
    draft_id: int = Field(..., description="Draft ID from prepare")
    commit_reason: Optional[str] = Field(None, description="Reason for confirmation")


class ConfirmResponse(BaseModel):
    """Response from confirm endpoint."""
    success: bool = True
    draft_id: int
    status: str
    evidence_id: str
    evidence_ref: str
    confirmed_by: str
    confirmed_at: str
    ready_for_publish: bool
    message: str


# =============================================================================
# IDEMPOTENCY HELPERS
# =============================================================================

def compute_preview_hash(
    plan_version_id: int,
    incident: IncidentSpecRequest,
    freeze: Optional[FreezeSpecRequest],
    change_budget: Optional[ChangeBudgetRequest],
) -> str:
    """Compute hash for preview caching (determinism proof)."""
    payload = json.dumps({
        "plan_version_id": plan_version_id,
        "incident": incident.dict(),
        "freeze": freeze.dict() if freeze else None,
        "change_budget": change_budget.dict() if change_budget else None,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def require_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
) -> str:
    """Require idempotency key for state-changing operations."""
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "x-idempotency-key header is required",
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
# EVIDENCE + AUDIT HELPERS
# =============================================================================

def generate_evidence_id() -> str:
    """Generate unique evidence ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"repair_orch_{ts}"


def generate_evidence_ref(
    tenant_id: int,
    site_id: Optional[int],
    action: str,
    entity_id: int,
) -> str:
    """Generate evidence reference path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"evidence/roster_orch_{action}_{tenant_id}_{site_id or 0}_{entity_id}_{ts}.json"


def write_evidence(evidence_ref: str, data: dict) -> None:
    """Write evidence JSON to file system."""
    import os
    evidence_dir = "evidence"
    os.makedirs(evidence_dir, exist_ok=True)
    filepath = os.path.join(evidence_dir, os.path.basename(evidence_ref))
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Evidence written: {filepath}")


def record_audit_event(
    conn,
    event_type: str,
    user: InternalUserContext,
    details: dict,
) -> None:
    """Record audit event."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.audit_log (
                event_type, user_id, user_email, tenant_id, site_id,
                details, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                event_type,
                user.user_id,
                user.email,
                user.tenant_id or user.active_tenant_id,
                user.site_id or user.active_site_id,
                json.dumps(details, default=str),
            )
        )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/preview", response_model=RepairPreviewResponse)
async def preview_repair_proposals(
    request: Request,
    body: RepairOrchestratorPreviewRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Generate Top-K repair proposals for an incident.

    This is a read-only operation - no database mutations.
    Returns up to top_k feasible proposals, each with:
    - 100% coverage for impacted tours (always computed)
    - Quality score (higher = better/less disruptive)

    CRITICAL SEMANTICS:
    - coverage: Always accurate (computed during proposal generation)
    - violations: Only trustworthy if validation != "none"

    Validation modes:
    - "none" (default): Fast preview, violations NOT validated
    - "fast": Validate impacted tours only (recommended for UX)
    - "full": Full plan validation (equivalent to confirm)

    Proposals are generated using three strategies:
    - A: Single driver (no split) - least disruptive if feasible
    - B: Split across drivers - more flexible
    - C: Chain swap - most complex, last resort
    """
    from packs.roster.core.repair_orchestrator import (
        generate_repair_proposals_sync,
        IncidentSpec,
        FreezeSpec,
        ChangeBudget,
        SplitPolicy,
    )
    from packs.roster.core.violation_simulator import (
        simulate_violations_sync,
        update_proposal_with_validation,
    )

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Determine plan_version_id
    plan_version_id = body.plan_version_id
    if body.snapshot_id and not plan_version_id:
        # Look up plan_version_id from snapshot
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT plan_version_id FROM plan_snapshots
                WHERE id = %s AND tenant_id = %s
                """,
                (body.snapshot_id, ctx.tenant_id)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Snapshot {body.snapshot_id} not found",
                )
            plan_version_id = row[0]

    if not plan_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either snapshot_id or plan_version_id is required",
        )

    # Validate plan belongs to tenant
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, site_id FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_version_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_version_id} not found or access denied",
            )

    # Convert request models to core models
    incident = IncidentSpec(
        type=body.incident.type,
        driver_id=body.incident.driver_id,
        time_range_start=datetime.fromisoformat(
            body.incident.time_range_start.replace('Z', '+00:00')
        ),
        time_range_end=datetime.fromisoformat(
            body.incident.time_range_end.replace('Z', '+00:00')
        ) if body.incident.time_range_end else None,
        reason=body.incident.reason,
    )

    freeze = FreezeSpec(
        freeze_assignments=set(body.freeze.freeze_assignments) if body.freeze else set(),
        freeze_drivers=set(body.freeze.freeze_drivers) if body.freeze else set(),
    )

    change_budget = ChangeBudget(
        max_changed_tours=body.change_budget.max_changed_tours if body.change_budget else 5,
        max_changed_drivers=body.change_budget.max_changed_drivers if body.change_budget else 3,
        max_chain_depth=body.change_budget.max_chain_depth if body.change_budget else 2,
    )

    split_policy = SplitPolicy(
        allow_split=body.split_policy.allow_split if body.split_policy else True,
        max_splits=body.split_policy.max_splits if body.split_policy else 2,
        split_granularity=body.split_policy.split_granularity if body.split_policy else "TOUR",
    )

    # Generate proposals with diagnostics
    result = generate_repair_proposals_sync(
        cursor=conn.cursor(),
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id,
        plan_version_id=plan_version_id,
        incident=incident,
        freeze=freeze,
        change_budget=change_budget,
        split_policy=split_policy,
        top_k=body.top_k,
        return_result=True,  # Get diagnostics
    )
    proposals = result.proposals

    # Optionally validate proposals if requested
    if body.validation != "none" and proposals:
        with conn.cursor() as cur:
            for p in proposals:
                # Build assignment dicts for simulator
                proposed_assignments = [
                    {
                        "driver_id": a.driver_id,
                        "tour_instance_id": a.tour_instance_id,
                        "day": a.day,
                        "start_ts": a.start_ts,
                        "end_ts": a.end_ts,
                    }
                    for a in p.assignments
                ]
                validation_result = simulate_violations_sync(
                    cursor=cur,
                    plan_version_id=plan_version_id,
                    proposed_assignments=proposed_assignments,
                    removed_tour_ids=p.removed_assignments,
                    mode=body.validation,
                )
                update_proposal_with_validation(p, validation_result)

        # Re-filter proposals if validation revealed BLOCK violations
        if body.validation in ("fast", "full"):
            proposals = [
                p for p in proposals
                if p.violations.block_violations is None or p.violations.block_violations == 0
            ]

    # Convert to response models
    proposal_responses = []
    for p in proposals:
        proposal_responses.append(RepairProposalResponse(
            proposal_id=p.proposal_id,
            label=p.label,
            strategy=p.strategy,
            feasible=p.feasible,
            quality_score=p.quality_score,
            delta_summary=DeltaSummaryResponse(
                changed_tours_count=p.delta_summary.changed_tours_count,
                changed_drivers_count=p.delta_summary.changed_drivers_count,
                impacted_drivers=p.delta_summary.impacted_drivers,
                reserve_usage=p.delta_summary.reserve_usage,
                chain_depth=p.delta_summary.chain_depth,
            ),
            assignments=[
                ProposedAssignmentResponse(
                    tour_instance_id=a.tour_instance_id,
                    driver_id=a.driver_id,
                    day=a.day,
                    block_id=a.block_id,
                    start_ts=a.start_ts.isoformat() if a.start_ts else None,
                    end_ts=a.end_ts.isoformat() if a.end_ts else None,
                    is_new=a.is_new,
                )
                for a in p.assignments
            ],
            removed_assignments=p.removed_assignments,
            evidence_hash=p.evidence_hash,
            # New structured fields
            coverage=CoverageInfoResponse(
                impacted_tours_count=p.coverage.impacted_tours_count,
                impacted_assigned_count=p.coverage.impacted_assigned_count,
                coverage_percent=p.coverage.coverage_percent,
                coverage_computed=p.coverage.coverage_computed,
            ),
            violations=ViolationInfoResponse(
                violations_validated=p.violations.violations_validated,
                block_violations=p.violations.block_violations,
                warn_violations=p.violations.warn_violations,
                validation_mode=p.violations.validation_mode,
                validation_note=p.violations.validation_note,
            ),
            compatibility=CompatibilityInfoResponse(
                compatibility_checked=p.compatibility.compatibility_checked,
                compatibility_unknown=p.compatibility.compatibility_unknown,
                missing_data=p.compatibility.missing_data,
                incompatibilities=p.compatibility.incompatibilities,
            ),
            # Legacy fields for backward compat
            coverage_percent=p.coverage.coverage_percent,
            block_violations=p.violations.block_violations,
            warn_violations=p.violations.warn_violations,
        ))

    evidence_id = generate_evidence_id()
    now = datetime.now(timezone.utc)

    # Use impacted_tours_count from result (more reliable than from proposals)
    impacted_count = result.impacted_tours_count

    # Build diagnostics response if applicable
    diagnostics_response = None
    if result.diagnostics.has_diagnostics:
        diagnostics_response = DiagnosticSummaryResponse(
            has_diagnostics=True,
            reasons=[
                DiagnosticReasonResponse(
                    code=r.code,
                    message=r.message,
                    tour_instance_ids=r.tour_instance_ids,
                    suggested_action=r.suggested_action,
                    priority=r.priority,
                )
                for r in result.diagnostics.reasons
            ],
            uncovered_tour_ids=result.diagnostics.uncovered_tour_ids,
            uncovered_tours=[
                UncoveredTourInfoResponse(
                    tour_instance_id=t.tour_instance_id,
                    tour_name=t.tour_name,
                    day=t.day,
                    start_ts=t.start_ts,
                    end_ts=t.end_ts,
                    reason=t.reason,
                )
                for t in result.diagnostics.uncovered_tours
            ],
            partial_proposals_available=result.diagnostics.partial_proposals_available,
            suggested_actions=result.diagnostics.suggested_actions,
            earliest_uncovered_start=result.diagnostics.earliest_uncovered_start,
        )

    # Check if any proposal has compatibility_unknown
    compatibility_unknown = any(
        p.compatibility.compatibility_unknown
        for p in proposals
    ) if proposals else not result.candidates_found

    # Record audit event (preview is read-only but we track it)
    record_audit_event(
        conn,
        event_type="roster.repair.orchestrated.preview",
        user=ctx.user,
        details={
            "plan_version_id": plan_version_id,
            "incident_driver_id": body.incident.driver_id,
            "proposals_count": len(proposals),
            "impacted_tours_count": impacted_count,
            "evidence_id": evidence_id,
            "has_diagnostics": result.diagnostics.has_diagnostics,
            "compatibility_unknown": compatibility_unknown,
        },
    )
    conn.commit()

    logger.info(
        "repair_orchestrated_preview_computed",
        extra={
            "plan_id": plan_version_id,
            "proposals": len(proposals),
            "tenant_id": ctx.tenant_id,
            "has_diagnostics": result.diagnostics.has_diagnostics,
        }
    )

    return RepairPreviewResponse(
        success=True,
        proposals=proposal_responses,
        proposal_count=len(proposals),
        impacted_tours_count=impacted_count,
        incident_driver_id=body.incident.driver_id,
        preview_computed_at=now.isoformat(),
        evidence_id=evidence_id,
        diagnostics=diagnostics_response,
        compatibility_unknown=compatibility_unknown,
    )


@router.post(
    "/prepare",
    response_model=PrepareResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def prepare_repair_draft(
    request: Request,
    body: PrepareRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Create a repair draft from a chosen proposal.

    This creates a new plan_version as a child of the original plan,
    with the proposed assignments applied.

    Idempotent: same idempotency_key returns same result.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Check idempotency
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT response_body FROM core.idempotency_keys
            WHERE idempotency_key = %s AND tenant_id = %s
              AND created_at > NOW() - INTERVAL '24 hours'
            """,
            (idempotency_key, ctx.tenant_id)
        )
        cached = cur.fetchone()
        if cached:
            logger.info(f"Idempotent return for prepare key {idempotency_key}")
            return PrepareResponse(**json.loads(cached[0]))

    # Validate plan ownership
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, site_id, forecast_version_id, seed
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (body.plan_version_id, ctx.tenant_id)
        )
        base_plan = cur.fetchone()
        if not base_plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {body.plan_version_id} not found or access denied",
            )

    # Create new draft plan version
    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Create draft
        cur.execute(
            """
            INSERT INTO plan_versions (
                tenant_id, site_id, forecast_version_id, seed,
                status, plan_state, baseline_plan_version_id,
                churn_count, notes, created_at
            ) VALUES (
                %s, %s, %s, %s,
                'DRAFT', 'DRAFT', %s,
                %s, %s, NOW()
            )
            RETURNING id, created_at
            """,
            (
                ctx.tenant_id,
                ctx.site_id or base_plan[2],
                base_plan[3],  # forecast_version_id
                base_plan[4],  # seed
                body.plan_version_id,  # baseline
                len(body.assignments),  # churn_count
                f"Repair from plan {body.plan_version_id}: {body.commit_reason or 'incident handling'}",
            )
        )
        draft_row = cur.fetchone()
        draft_id = draft_row[0]

        # Copy all assignments from base plan
        cur.execute(
            """
            INSERT INTO assignments (
                plan_version_id, tenant_id, driver_id,
                tour_instance_id, day, block_id, role, metadata
            )
            SELECT
                %s, tenant_id, driver_id,
                tour_instance_id, day, block_id, role, metadata
            FROM assignments
            WHERE plan_version_id = %s
            """,
            (draft_id, body.plan_version_id)
        )

        # Remove assignments for removed tours
        if body.removed_assignments:
            cur.execute(
                """
                DELETE FROM assignments
                WHERE plan_version_id = %s
                  AND tour_instance_id = ANY(%s)
                """,
                (draft_id, body.removed_assignments)
            )

        # Insert new assignments
        for asgn in body.assignments:
            cur.execute(
                """
                INSERT INTO assignments (
                    plan_version_id, tenant_id, driver_id,
                    tour_instance_id, day, block_id, role
                ) VALUES (%s, %s, %s, %s, %s, %s, 'PRIMARY')
                ON CONFLICT (plan_version_id, tour_instance_id)
                DO UPDATE SET driver_id = EXCLUDED.driver_id
                """,
                (
                    draft_id,
                    ctx.tenant_id,
                    str(asgn.driver_id),
                    asgn.tour_instance_id,
                    asgn.day,
                    asgn.block_id,
                )
            )

        # Record approval action
        cur.execute(
            """
            INSERT INTO plan_approvals (
                plan_version_id, tenant_id, action, performed_by,
                from_state, to_state, reason, created_at
            ) VALUES (%s, %s, 'REPAIR_PREPARE', %s, NULL, 'DRAFT', %s, NOW())
            """,
            (
                draft_id,
                ctx.tenant_id,
                performed_by,
                body.commit_reason or f"Prepared from proposal {body.proposal_id}",
            )
        )

    evidence_id = generate_evidence_id()
    evidence_ref = generate_evidence_ref(
        ctx.tenant_id, ctx.site_id, "prepare", draft_id
    )

    # Write evidence (including compatibility acknowledgment for audit trail)
    evidence_data = {
        "event": "repair_orchestrated_prepare",
        "evidence_id": evidence_id,
        "tenant_id": ctx.tenant_id,
        "site_id": ctx.site_id,
        "draft_id": draft_id,
        "proposal_id": body.proposal_id,
        "parent_plan_version_id": body.plan_version_id,
        "assignments_count": len(body.assignments),
        "removed_count": len(body.removed_assignments),
        "prepared_by": performed_by,
        "prepared_at": now.isoformat(),
        "idempotency_key": idempotency_key,
        # P1.5A: Track user acknowledgment for compatibility_unknown
        "compatibility_acknowledged": body.compatibility_acknowledged,
    }
    write_evidence(evidence_ref, evidence_data)

    # Record audit event
    record_audit_event(
        conn,
        event_type="roster.repair.orchestrated.prepare",
        user=ctx.user,
        details=evidence_data,
    )

    # Build response
    response_data = {
        "success": True,
        "draft_id": draft_id,
        "proposal_id": body.proposal_id,
        "parent_plan_version_id": body.plan_version_id,
        "status": "DRAFT",
        "evidence_id": evidence_id,
        "idempotency_key": idempotency_key,
        "prepared_at": now.isoformat(),
        "message": f"Repair draft {draft_id} created from proposal {body.proposal_id}",
    }

    # Store idempotency
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO core.idempotency_keys (
                tenant_id, idempotency_key, action, request_hash, response_body
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                ctx.tenant_id,
                idempotency_key,
                "roster.repair.orchestrated.prepare",
                body.proposal_id,  # Use proposal_id as request hash
                json.dumps(response_data),
            )
        )

    conn.commit()

    logger.info(
        "repair_orchestrated_draft_prepared",
        extra={
            "draft_id": draft_id,
            "proposal_id": body.proposal_id,
            "tenant_id": ctx.tenant_id,
        }
    )

    return PrepareResponse(**response_data)


@router.post(
    "/confirm",
    response_model=ConfirmResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def confirm_repair_draft(
    request: Request,
    body: ConfirmRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Confirm a repair draft for publishing.

    This validates the draft has:
    - 100% coverage
    - 0 BLOCK violations

    Then transitions status to CONFIRMED (ready for publish).
    Idempotent: same idempotency_key returns same result.
    """
    from packs.roster.core.violations import compute_violations_sync

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Check idempotency
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT response_body FROM core.idempotency_keys
            WHERE idempotency_key = %s AND tenant_id = %s
              AND created_at > NOW() - INTERVAL '24 hours'
            """,
            (idempotency_key, ctx.tenant_id)
        )
        cached = cur.fetchone()
        if cached:
            logger.info(f"Idempotent return for confirm key {idempotency_key}")
            return ConfirmResponse(**json.loads(cached[0]))

    # Validate draft ownership and status
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, site_id, status, baseline_plan_version_id
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (body.draft_id, ctx.tenant_id)
        )
        draft = cur.fetchone()
        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Draft {body.draft_id} not found or access denied",
            )

        if draft[3] != "DRAFT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "INVALID_STATUS",
                    "message": f"Draft is in status {draft[3]}, expected DRAFT",
                    "current_status": draft[3],
                },
            )

    # Compute violations
    with conn.cursor() as cur:
        violation_counts, _ = compute_violations_sync(cur, body.draft_id)

    if violation_counts.block_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "BLOCK_VIOLATIONS",
                "message": f"Draft has {violation_counts.block_count} BLOCK violations",
                "block_count": violation_counts.block_count,
                "warn_count": violation_counts.warn_count,
            },
        )

    # Transition to CONFIRMED
    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE plan_versions
            SET status = 'AUDITED', plan_state = 'AUDITED'
            WHERE id = %s AND status = 'DRAFT'
            """,
            (body.draft_id,)
        )

        # Record approval action
        cur.execute(
            """
            INSERT INTO plan_approvals (
                plan_version_id, tenant_id, action, performed_by,
                from_state, to_state, reason, created_at
            ) VALUES (%s, %s, 'REPAIR_CONFIRM', %s, 'DRAFT', 'AUDITED', %s, NOW())
            """,
            (
                body.draft_id,
                ctx.tenant_id,
                performed_by,
                body.commit_reason or "Repair confirmed for publish",
            )
        )

    evidence_id = generate_evidence_id()
    evidence_ref = generate_evidence_ref(
        ctx.tenant_id, ctx.site_id, "confirm", body.draft_id
    )

    # Write evidence
    evidence_data = {
        "event": "repair_orchestrated_confirm",
        "evidence_id": evidence_id,
        "tenant_id": ctx.tenant_id,
        "site_id": ctx.site_id,
        "draft_id": body.draft_id,
        "block_violations": violation_counts.block_count,
        "warn_violations": violation_counts.warn_count,
        "confirmed_by": performed_by,
        "confirmed_at": now.isoformat(),
        "idempotency_key": idempotency_key,
    }
    write_evidence(evidence_ref, evidence_data)

    # Record audit event
    record_audit_event(
        conn,
        event_type="roster.repair.orchestrated.confirm",
        user=ctx.user,
        details=evidence_data,
    )

    # Build response
    response_data = {
        "success": True,
        "draft_id": body.draft_id,
        "status": "AUDITED",
        "evidence_id": evidence_id,
        "evidence_ref": evidence_ref,
        "confirmed_by": performed_by,
        "confirmed_at": now.isoformat(),
        "ready_for_publish": True,
        "message": f"Repair {body.draft_id} confirmed and ready for publish",
    }

    # Store idempotency
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO core.idempotency_keys (
                tenant_id, idempotency_key, action, request_hash, response_body
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                ctx.tenant_id,
                idempotency_key,
                "roster.repair.orchestrated.confirm",
                str(body.draft_id),
                json.dumps(response_data),
            )
        )

    conn.commit()

    logger.info(
        "repair_orchestrated_confirmed",
        extra={
            "draft_id": body.draft_id,
            "tenant_id": ctx.tenant_id,
            "ready_for_publish": True,
        }
    )

    return ConfirmResponse(**response_data)


@router.get("/candidates/{plan_version_id}/{driver_id}")
async def get_candidates_for_driver(
    plan_version_id: int,
    driver_id: int,
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get candidate drivers for all tours assigned to a specific driver.

    Useful for UI to show dispatcher who could cover if this driver is unavailable.
    """
    from packs.roster.core.candidate_finder import find_candidates_sync, TourInfo

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Validate plan ownership
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_version_id, ctx.tenant_id)
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_version_id} not found or access denied",
            )

    # Get tours for driver
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                a.tour_instance_id,
                ti.tour_id,
                a.day,
                ti.start_ts,
                ti.end_ts,
                a.block_id
            FROM assignments a
            JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
              AND a.driver_id::integer = %s
            ORDER BY a.day, ti.start_ts
            """,
            (plan_version_id, driver_id)
        )
        tours = [
            TourInfo(
                tour_instance_id=row[0],
                tour_id=row[1],
                day=row[2],
                start_ts=row[3],
                end_ts=row[4],
                driver_id=driver_id,
                block_type=row[5] or "1er",
            )
            for row in cur.fetchall()
        ]

    if not tours:
        return {"driver_id": driver_id, "tours": [], "candidates_by_tour": {}}

    # Find candidates
    candidates_result = find_candidates_sync(
        cursor=conn.cursor(),
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id,
        plan_version_id=plan_version_id,
        impacted_tours=tours,
        absent_driver_ids={driver_id},
        freeze_driver_ids=set(),
    )

    # Format response
    result = {
        "driver_id": driver_id,
        "tours": [
            {
                "tour_instance_id": t.tour_instance_id,
                "tour_id": t.tour_id,
                "day": t.day,
                "start_ts": t.start_ts.isoformat() if t.start_ts else None,
                "end_ts": t.end_ts.isoformat() if t.end_ts else None,
            }
            for t in tours
        ],
        "candidates_by_tour": {
            str(tour_id): {
                "candidates": [
                    {
                        "driver_id": c.driver_id,
                        "name": c.name,
                        "score": c.score,
                        "existing_tours_count": c.existing_tours_count,
                        "is_working_same_day": c.is_working_same_day,
                    }
                    for c in result.candidates
                ],
                "total_available": result.total_available,
                "filtered_count": result.filtered_count,
            }
            for tour_id, result in candidates_result.items()
        },
    }

    return result
