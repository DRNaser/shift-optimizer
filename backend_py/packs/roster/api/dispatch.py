"""
SOLVEREIGN Gurkerl Dispatch Assist - API Router
================================================

REST API endpoints for dispatch assist operations.

ENDPOINTS:
    POST /api/v1/roster/dispatch/open-shifts    - Detect open shifts
    POST /api/v1/roster/dispatch/suggest        - Get candidate suggestions
    POST /api/v1/roster/dispatch/propose        - Generate and write proposals
    POST /api/v1/roster/dispatch/apply          - Apply proposal with optimistic concurrency
    GET  /api/v1/roster/dispatch/health         - Health check
"""

import logging
import os
from datetime import date, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dispatch", tags=["Dispatch Assist"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class DateRangeRequest(BaseModel):
    """Optional date range for queries."""
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")


class OpenShiftResponse(BaseModel):
    """Open shift information."""
    id: str
    shift_date: str
    shift_start: str
    shift_end: str
    route_id: Optional[str] = None
    zone: Optional[str] = None
    reason: str
    row_index: Optional[int] = None


class OpenShiftsResponse(BaseModel):
    """Response from open-shifts endpoint."""
    count: int
    open_shifts: List[OpenShiftResponse]


class CandidateResponse(BaseModel):
    """Candidate information."""
    driver_id: str
    driver_name: str
    rank: int
    score: float
    is_eligible: bool
    current_weekly_hours: float
    hours_after_assignment: float
    reasons: List[str]
    disqualifications: List[str] = []


class SuggestRequest(BaseModel):
    """Request for candidate suggestions."""
    shift_id: str = Field(..., description="Open shift ID")
    shift_date: str = Field(..., description="Shift date (YYYY-MM-DD)")
    shift_start: str = Field(..., description="Shift start time (HH:MM)")
    shift_end: str = Field(..., description="Shift end time (HH:MM)")
    route_id: Optional[str] = None
    zone: Optional[str] = None
    required_skills: List[str] = []
    top_n: int = Field(5, ge=1, le=20, description="Number of candidates to return")


class SuggestResponse(BaseModel):
    """Response from suggest endpoint."""
    shift_id: str
    total_drivers: int
    eligible_count: int
    candidates: List[CandidateResponse]


class ProposeRequest(BaseModel):
    """Request to generate proposals."""
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    write_to_sheet: bool = Field(False, description="Write proposals to Sheets")


class ProposalResponse(BaseModel):
    """Proposal information."""
    id: str
    shift_id: str
    shift_date: str
    top_candidate_id: Optional[str] = None
    top_candidate_name: Optional[str] = None
    candidate_count: int
    status: str


class ProposeResponse(BaseModel):
    """Response from propose endpoint."""
    open_shifts: int
    proposals: int
    proposals_with_candidates: int
    written_to_sheet: int
    proposals_list: List[ProposalResponse]


class SheetConfigRequest(BaseModel):
    """Sheet configuration for connecting to Google Sheets."""
    spreadsheet_id: str = Field(..., description="Google Sheets spreadsheet ID")
    roster_tab: str = Field("Dienstplan", description="Roster tab name")
    proposals_tab: str = Field("Proposals", description="Proposals tab name")
    drivers_tab: str = Field("Fahrer", description="Drivers tab name")
    absences_tab: str = Field("Abwesenheiten", description="Absences tab name")


# =============================================================================
# APPLY ENDPOINT SCHEMAS
# =============================================================================

class ApplyRequestSchema(BaseModel):
    """Request to apply a proposal."""
    proposal_id: str = Field(..., description="Proposal ID to apply")
    selected_driver_id: str = Field(..., description="Driver ID to assign")
    expected_plan_fingerprint: str = Field(..., description="Expected sheet fingerprint for optimistic concurrency")
    apply_request_id: Optional[str] = Field(None, description="Idempotency key (UUID)")
    force: bool = Field(False, description="Force apply even if fingerprint mismatch (requires Approver role)")
    force_reason: Optional[str] = Field(None, min_length=10, description="Required if force=true (min 10 chars)")


class ApplySuccessResponse(BaseModel):
    """Successful apply response."""
    success: bool = True
    proposal_id: str
    selected_driver_id: str
    selected_driver_name: str
    applied_at: str
    cells_written: List[str]


class ApplyConflictResponse(BaseModel):
    """Apply conflict response (HTTP 409)."""
    success: bool = False
    error_code: str = "PLAN_CHANGED"
    error_message: str
    proposal_id: str
    expected_fingerprint: str
    latest_fingerprint: str
    hint_diffs: Optional[Dict[str, Any]] = None


class ApplyEligibilityErrorResponse(BaseModel):
    """Apply eligibility error response (HTTP 422)."""
    success: bool = False
    error_code: str = "NOT_ELIGIBLE"
    error_message: str
    proposal_id: str
    driver_id: str
    disqualifications: List[Dict[str, Any]]


class ApplyErrorResponse(BaseModel):
    """Generic apply error response."""
    success: bool = False
    error_code: str
    error_message: str
    proposal_id: str


# =============================================================================
# HELPER: Get service instance
# =============================================================================

def _get_dispatch_service(config: Optional[SheetConfigRequest] = None):
    """
    Get dispatch service instance.

    Uses environment variables for configuration if not provided.
    """
    from ..dispatch.models import SheetConfig
    from ..dispatch.service import create_dispatch_service, DispatchConfig

    # Get spreadsheet ID from config or env
    spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    if config:
        spreadsheet_id = config.spreadsheet_id

    if not spreadsheet_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet ID required. Set SHEETS_SPREADSHEET_ID env var or provide in request.",
        )

    sheet_config = SheetConfig(
        spreadsheet_id=spreadsheet_id,
        roster_tab=config.roster_tab if config else os.environ.get("SHEETS_ROSTER_TAB", "Dienstplan"),
        proposals_tab=config.proposals_tab if config else os.environ.get("SHEETS_PROPOSALS_TAB", "Proposals"),
        drivers_tab=config.drivers_tab if config else os.environ.get("SHEETS_DRIVERS_TAB", "Fahrer"),
        absences_tab=config.absences_tab if config else os.environ.get("SHEETS_ABSENCES_TAB", "Abwesenheiten"),
    )

    dispatch_config = DispatchConfig(
        rest_hours=int(os.environ.get("DISPATCH_REST_HOURS", "11")),
        max_tours_per_day=int(os.environ.get("DISPATCH_MAX_TOURS_DAY", "2")),
        max_weekly_hours=float(os.environ.get("DISPATCH_MAX_WEEKLY_HOURS", "55")),
    )

    return create_dispatch_service(sheet_config, dispatch_config)


def _parse_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
):
    """Parse date range strings to tuple."""
    from datetime import datetime

    if not start_date and not end_date:
        # Default: this week
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        return (week_start, week_start + timedelta(days=6))

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today()
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else start + timedelta(days=7)
        return (start, end)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format. Use YYYY-MM-DD. Error: {e}",
        )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/open-shifts", response_model=OpenShiftsResponse)
async def detect_open_shifts(
    request: DateRangeRequest = None,
    config: Optional[SheetConfigRequest] = None,
):
    """
    Detect open shifts from Google Sheets roster.

    Returns all shifts that need to be filled:
    - No driver assigned
    - Status = OPEN
    - Empty driver cell

    **Google Sheets Required:**
    Set SHEETS_SPREADSHEET_ID and SHEETS_SERVICE_ACCOUNT_JSON env vars,
    or provide spreadsheet_id in request.
    """
    service = _get_dispatch_service(config)
    date_range = _parse_date_range(
        request.start_date if request else None,
        request.end_date if request else None,
    )

    try:
        open_shifts = await service.detect_open_shifts(date_range)

        return OpenShiftsResponse(
            count=len(open_shifts),
            open_shifts=[
                OpenShiftResponse(
                    id=s.id,
                    shift_date=s.shift_date.isoformat(),
                    shift_start=s.shift_start.strftime("%H:%M"),
                    shift_end=s.shift_end.strftime("%H:%M"),
                    route_id=s.route_id,
                    zone=s.zone,
                    reason=s.reason,
                    row_index=s.row_index,
                )
                for s in open_shifts
            ],
        )

    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Google Sheets integration not available: {e}",
        )
    except Exception as e:
        logger.error(f"Error detecting open shifts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error detecting open shifts: {e}",
        )


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_candidates(
    request: SuggestRequest,
    config: Optional[SheetConfigRequest] = None,
):
    """
    Get ranked candidate suggestions for an open shift.

    **Eligibility Checks (Hard Constraints):**
    - Not absent (sick/vacation)
    - 11-hour rest between shifts
    - Max 2 tours per day
    - Max 55 hours per week
    - Required skills match
    - Zone match

    **Ranking Criteria (Soft):**
    - Fairness (under-target drivers preferred)
    - Minimal churn (already-working drivers preferred)
    - Zone affinity
    - Part-time balance
    """
    from datetime import datetime
    from ..dispatch.models import OpenShift

    service = _get_dispatch_service(config)

    # Parse shift times
    try:
        shift_date = datetime.strptime(request.shift_date, "%Y-%m-%d").date()
        shift_start = datetime.strptime(request.shift_start, "%H:%M").time()
        shift_end = datetime.strptime(request.shift_end, "%H:%M").time()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date/time format: {e}",
        )

    # Build OpenShift object
    open_shift = OpenShift(
        id=request.shift_id,
        shift_date=shift_date,
        shift_start=shift_start,
        shift_end=shift_end,
        route_id=request.route_id,
        zone=request.zone,
        required_skills=request.required_skills,
    )

    try:
        candidates = await service.suggest_candidates(open_shift)

        # Get top N
        top_candidates = candidates[:request.top_n]

        eligible_count = sum(1 for c in candidates if c.is_eligible)

        return SuggestResponse(
            shift_id=request.shift_id,
            total_drivers=len(candidates),
            eligible_count=eligible_count,
            candidates=[
                CandidateResponse(
                    driver_id=c.driver_id,
                    driver_name=c.driver_name,
                    rank=c.rank,
                    score=round(c.score, 2),
                    is_eligible=c.is_eligible,
                    current_weekly_hours=round(c.current_weekly_hours, 1),
                    hours_after_assignment=round(c.hours_after_assignment, 1),
                    reasons=c.reasons,
                    disqualifications=[d.details for d in c.disqualifications],
                )
                for c in top_candidates
            ],
        )

    except Exception as e:
        logger.error(f"Error suggesting candidates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error suggesting candidates: {e}",
        )


@router.post("/propose", response_model=ProposeResponse)
async def generate_proposals(
    request: ProposeRequest,
    config: Optional[SheetConfigRequest] = None,
):
    """
    Generate proposals for all open shifts.

    Optionally writes proposals to the Proposals tab in Google Sheets.

    **Workflow:**
    1. Detect all open shifts in date range
    2. For each open shift, find and rank candidates
    3. Create proposal with top 3 candidates
    4. (Optional) Write proposals to Sheets

    **Note:** This does NOT modify the roster directly.
    Proposals are suggestions for dispatcher review.
    """
    service = _get_dispatch_service(config)
    date_range = _parse_date_range(request.start_date, request.end_date)

    try:
        result = await service.run_full_workflow(
            date_range=date_range,
            write_to_sheet=request.write_to_sheet,
        )

        # Get proposals from result
        proposals = result.get("proposal_details", [])

        return ProposeResponse(
            open_shifts=result.get("open_shifts", 0),
            proposals=result.get("proposals", 0),
            proposals_with_candidates=result.get("proposals_with_candidates", 0),
            written_to_sheet=result.get("written", 0),
            proposals_list=[
                ProposalResponse(
                    id=p.get("id", ""),
                    shift_id=p.get("shift_id", ""),
                    shift_date=p.get("date", ""),
                    top_candidate_id=None,  # Not in summary
                    top_candidate_name=p.get("top_candidate"),
                    candidate_count=p.get("candidate_count", 0),
                    status="pending",
                )
                for p in proposals
            ],
        )

    except Exception as e:
        logger.error(f"Error generating proposals: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating proposals: {e}",
        )


@router.get("/health")
async def dispatch_health():
    """
    Health check for dispatch assist module.

    Checks:
    - Module loaded
    - Environment variables configured
    """
    has_spreadsheet_id = bool(os.environ.get("SHEETS_SPREADSHEET_ID"))
    has_credentials = bool(os.environ.get("SHEETS_SERVICE_ACCOUNT_JSON"))

    status_ok = has_spreadsheet_id and has_credentials

    return {
        "status": "ok" if status_ok else "degraded",
        "module": "dispatch_assist",
        "version": "v1.0.0",
        "checks": {
            "spreadsheet_id_configured": has_spreadsheet_id,
            "credentials_configured": has_credentials,
        },
        "message": "Ready" if status_ok else "Missing SHEETS_* environment variables",
    }


# =============================================================================
# APPLY ENDPOINT
# =============================================================================

def _get_apply_service(config: Optional[SheetConfigRequest] = None, db_pool=None):
    """
    Get apply service instance with repository.

    Args:
        config: Optional sheet configuration
        db_pool: Database connection pool

    Returns:
        Configured DispatchApplyService
    """
    from ..dispatch.models import SheetConfig
    from ..dispatch.service import create_apply_service, DispatchConfig
    from ..dispatch.repository import DispatchRepository

    # Get spreadsheet ID from config or env
    spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    if config:
        spreadsheet_id = config.spreadsheet_id

    if not spreadsheet_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet ID required. Set SHEETS_SPREADSHEET_ID env var or provide in request.",
        )

    sheet_config = SheetConfig(
        spreadsheet_id=spreadsheet_id,
        roster_tab=config.roster_tab if config else os.environ.get("SHEETS_ROSTER_TAB", "Dienstplan"),
        proposals_tab=config.proposals_tab if config else os.environ.get("SHEETS_PROPOSALS_TAB", "Proposals"),
        drivers_tab=config.drivers_tab if config else os.environ.get("SHEETS_DRIVERS_TAB", "Fahrer"),
        absences_tab=config.absences_tab if config else os.environ.get("SHEETS_ABSENCES_TAB", "Abwesenheiten"),
    )

    dispatch_config = DispatchConfig(
        rest_hours=int(os.environ.get("DISPATCH_REST_HOURS", "11")),
        max_tours_per_day=int(os.environ.get("DISPATCH_MAX_TOURS_DAY", "2")),
        max_weekly_hours=float(os.environ.get("DISPATCH_MAX_WEEKLY_HOURS", "55")),
    )

    repository = DispatchRepository(db_pool)
    return create_apply_service(sheet_config, repository, dispatch_config)


def _check_approver_role(user_roles: List[str], is_app_token: bool) -> bool:
    """
    Check if user has Approver role for force operations.

    Args:
        user_roles: List of user's Entra ID app roles
        is_app_token: Whether this is an app token (service principal)

    Returns:
        True if user can force, False otherwise
    """
    # App tokens cannot use force
    if is_app_token:
        return False

    # Check for Approver or Admin role
    approver_roles = {"Approver", "Admin", "SuperAdmin", "solvereign_platform"}
    return bool(set(user_roles) & approver_roles)


@router.post(
    "/apply",
    response_model=ApplySuccessResponse,
    responses={
        409: {"model": ApplyConflictResponse, "description": "Sheet data changed"},
        422: {"model": ApplyEligibilityErrorResponse, "description": "Driver not eligible"},
        400: {"model": ApplyErrorResponse, "description": "Invalid request"},
        403: {"model": ApplyErrorResponse, "description": "Force not allowed"},
    },
)
async def apply_proposal(
    request: ApplyRequestSchema,
    config: Optional[SheetConfigRequest] = None,
    # TODO: Add Depends for auth and DB pool when integrated
    # current_user: UserInfo = Depends(get_current_user),
    # db_pool = Depends(get_db_pool),
):
    """
    Apply a proposal to assign a driver to an open shift.

    **Workflow:**
    1. Verify proposal exists and status is PROPOSED
    2. Check idempotency (apply_request_id) - returns cached result if duplicate
    3. Compare sheet fingerprint for optimistic concurrency
    4. Revalidate driver eligibility (server-side check)
    5. Write assignment to Google Sheets
    6. Update proposal status to APPLIED
    7. Record audit entry

    **Error Codes:**
    - `PLAN_CHANGED` (409): Sheet data changed since proposal generation
    - `NOT_ELIGIBLE` (422): Driver failed eligibility revalidation
    - `PROPOSAL_NOT_FOUND` (400): Proposal doesn't exist
    - `INVALID_STATUS` (400): Proposal already applied or invalidated
    - `FORCE_NOT_ALLOWED` (403): App tokens cannot use force

    **Force Mode:**
    - Requires `Approver` or `Admin` role
    - Requires `force_reason` (min 10 chars)
    - Bypasses fingerprint check but still validates eligibility
    - App tokens (service principals) cannot use force
    """
    from ..dispatch.models import ApplyRequest

    # TODO: Get tenant_id and user info from auth context
    # For now, use defaults for development
    tenant_id = int(os.environ.get("DEFAULT_TENANT_ID", "1"))
    performed_by = os.environ.get("DEFAULT_USER", "api@solvereign.dev")
    user_roles: List[str] = []
    is_app_token = False

    # Validate force request
    if request.force:
        if not request.force_reason or len(request.force_reason.strip()) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="force_reason required (min 10 chars) when force=true",
            )

        # Check approver role
        if not _check_approver_role(user_roles, is_app_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "error_code": "FORCE_NOT_ALLOWED",
                    "error_message": "Force requires Approver or Admin role. App tokens cannot use force.",
                    "proposal_id": request.proposal_id,
                },
            )

    try:
        # Get service (TODO: pass db_pool when integrated)
        service = _get_apply_service(config, db_pool=None)

        # Build internal request model
        apply_request = ApplyRequest(
            proposal_id=request.proposal_id,
            selected_driver_id=request.selected_driver_id,
            expected_plan_fingerprint=request.expected_plan_fingerprint,
            apply_request_id=request.apply_request_id,
            force=request.force,
            force_reason=request.force_reason,
        )

        # Execute apply workflow
        result = await service.apply_proposal(
            tenant_id=tenant_id,
            request=apply_request,
            performed_by=performed_by,
        )

        # Handle different result types
        if result.success:
            return ApplySuccessResponse(
                success=True,
                proposal_id=result.proposal_id,
                selected_driver_id=result.selected_driver_id or "",
                selected_driver_name=result.selected_driver_name or "",
                applied_at=result.applied_at.isoformat() if result.applied_at else "",
                cells_written=result.cells_written or [],
            )

        # Handle error cases
        if result.error_code == "PLAN_CHANGED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "success": False,
                    "error_code": "PLAN_CHANGED",
                    "error_message": result.error_message or "Sheet data has changed",
                    "proposal_id": result.proposal_id,
                    "expected_fingerprint": result.expected_fingerprint or "",
                    "latest_fingerprint": result.latest_fingerprint or "",
                    "hint_diffs": result.hint_diffs.to_dict() if result.hint_diffs else None,
                },
            )

        if result.error_code == "NOT_ELIGIBLE":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "success": False,
                    "error_code": "NOT_ELIGIBLE",
                    "error_message": result.error_message or "Driver not eligible",
                    "proposal_id": result.proposal_id,
                    "driver_id": request.selected_driver_id,
                    "disqualifications": [d.to_dict() for d in (result.disqualifications or [])],
                },
            )

        # Generic error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": result.error_code or "UNKNOWN_ERROR",
                "error_message": result.error_message or "Apply failed",
                "proposal_id": result.proposal_id,
            },
        )

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Google Sheets integration not available: {e}",
        )
    except Exception as e:
        logger.error(f"Error applying proposal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error applying proposal: {e}",
        )
