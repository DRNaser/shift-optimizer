"""
SOLVEREIGN Gurkerl Dispatch Assist - Service Layer
===================================================

Orchestrates the dispatch assist workflow:
1. Read roster from Google Sheets
2. Detect open shifts
3. Compute driver states (hours, shifts)
4. Find eligible candidates
5. Score and rank candidates
6. Generate proposals
7. (Optional) Write proposals back to Sheets

This is the main entry point for dispatch assist operations.
"""

import logging
import uuid
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple

from .models import (
    OpenShift,
    Candidate,
    Proposal,
    ShiftAssignment,
    DriverState,
    SheetConfig,
    ProposalStatus,
    FingerprintScope,
    FingerprintScopeType,
    ApplyRequest,
    ApplyResult,
    PersistedProposal,
    OpenShiftStatus,
)
from .eligibility import EligibilityChecker
from .scoring import CandidateScorer, ScoringWeights
from .sheet_adapter import SheetAdapterBase, GoogleSheetsAdapter, MockSheetAdapter
from .repository import DispatchRepository, MockDispatchRepository

logger = logging.getLogger(__name__)


# =============================================================================
# SERVICE CONFIGURATION
# =============================================================================

class DispatchConfig:
    """Configuration for dispatch assist service."""

    def __init__(
        self,
        rest_hours: int = 11,
        max_tours_per_day: int = 2,
        max_weekly_hours: float = 55.0,
        top_candidates: int = 3,
        scoring_weights: Optional[ScoringWeights] = None,
    ):
        self.rest_hours = rest_hours
        self.max_tours_per_day = max_tours_per_day
        self.max_weekly_hours = max_weekly_hours
        self.top_candidates = top_candidates
        self.scoring_weights = scoring_weights or ScoringWeights()


# =============================================================================
# DISPATCH ASSIST SERVICE
# =============================================================================

class DispatchAssistService:
    """
    Main service for dispatch assist operations.

    Coordinates reading from Sheets, eligibility checking,
    scoring, and proposal generation.
    """

    def __init__(
        self,
        adapter: SheetAdapterBase,
        config: Optional[DispatchConfig] = None,
    ):
        """
        Initialize service.

        Args:
            adapter: Sheet adapter (GoogleSheetsAdapter or MockSheetAdapter)
            config: Optional dispatch configuration
        """
        self.adapter = adapter
        self.config = config or DispatchConfig()
        self.eligibility_checker = EligibilityChecker(
            rest_hours=self.config.rest_hours,
            max_tours_per_day=self.config.max_tours_per_day,
            max_weekly_hours=self.config.max_weekly_hours,
        )
        self.scorer = CandidateScorer(self.config.scoring_weights)

    async def detect_open_shifts(
        self,
        date_range: Optional[Tuple[date, date]] = None,
    ) -> List[OpenShift]:
        """
        Detect open shifts from the roster.

        Args:
            date_range: Optional (start, end) date filter

        Returns:
            List of OpenShift objects
        """
        # Read roster
        roster = await self.adapter.read_roster(date_range)

        # Detect open shifts
        open_shifts = await self.adapter.detect_open_shifts(roster)

        logger.info(f"Detected {len(open_shifts)} open shifts")
        return open_shifts

    async def suggest_candidates(
        self,
        open_shift: OpenShift,
        date_range: Optional[Tuple[date, date]] = None,
    ) -> List[Candidate]:
        """
        Generate ranked candidate suggestions for an open shift.

        Args:
            open_shift: The open shift to fill
            date_range: Optional date range for computing driver states

        Returns:
            Sorted list of candidates (best first)
        """
        # Determine date range for context
        if not date_range:
            # Default: current week (Mon-Sun)
            today = open_shift.shift_date
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            date_range = (week_start, week_end)

        # Read roster for the date range
        roster = await self.adapter.read_roster(date_range)

        # Read drivers
        drivers = await self.adapter.read_drivers()

        # Compute driver states (hours worked, shifts today, etc.)
        driver_states = self._compute_driver_states(drivers, roster, open_shift.shift_date)

        # Check eligibility
        candidates = self.eligibility_checker.filter_eligible_drivers(
            list(driver_states.values()),
            open_shift,
        )

        # Score and rank
        ranked_candidates = self.scorer.score_candidates(
            candidates,
            open_shift,
            driver_states,
        )

        return ranked_candidates

    async def generate_proposals(
        self,
        open_shifts: Optional[List[OpenShift]] = None,
        date_range: Optional[Tuple[date, date]] = None,
    ) -> List[Proposal]:
        """
        Generate proposals for all open shifts.

        Args:
            open_shifts: Optional list of open shifts (will detect if None)
            date_range: Optional date range

        Returns:
            List of Proposal objects
        """
        # Detect open shifts if not provided
        if open_shifts is None:
            open_shifts = await self.detect_open_shifts(date_range)

        if not open_shifts:
            logger.info("No open shifts found")
            return []

        proposals = []
        for shift in open_shifts:
            try:
                candidates = await self.suggest_candidates(shift, date_range)

                # Get top N eligible candidates
                eligible = [c for c in candidates if c.is_eligible]
                top_candidates = eligible[:self.config.top_candidates]

                proposal = Proposal(
                    id=f"prop_{uuid.uuid4().hex[:8]}",
                    open_shift_id=shift.id,
                    shift_date=shift.shift_date,
                    candidates=top_candidates,
                    top_candidate_id=top_candidates[0].driver_id if top_candidates else None,
                    top_candidate_name=top_candidates[0].driver_name if top_candidates else None,
                    status=ProposalStatus.PENDING,
                )
                proposals.append(proposal)

                logger.info(
                    f"Generated proposal for shift {shift.id}: "
                    f"{len(top_candidates)} candidates, "
                    f"top={proposal.top_candidate_name}"
                )

            except Exception as e:
                logger.error(f"Error generating proposal for shift {shift.id}: {e}")

        return proposals

    async def write_proposals(self, proposals: List[Proposal]) -> int:
        """
        Write proposals to Google Sheets.

        Args:
            proposals: List of proposals to write

        Returns:
            Number of proposals written
        """
        return await self.adapter.write_proposals(proposals)

    async def run_full_workflow(
        self,
        date_range: Optional[Tuple[date, date]] = None,
        write_to_sheet: bool = False,
    ) -> Dict:
        """
        Run the full dispatch assist workflow.

        Args:
            date_range: Optional date range to process
            write_to_sheet: Whether to write proposals to Sheets

        Returns:
            Summary dict with open_shifts, proposals, and stats
        """
        logger.info(f"Starting dispatch assist workflow (date_range={date_range})")

        # Step 1: Detect open shifts
        open_shifts = await self.detect_open_shifts(date_range)

        if not open_shifts:
            return {
                "open_shifts": 0,
                "proposals": 0,
                "written": 0,
                "message": "No open shifts found",
            }

        # Step 2: Generate proposals
        proposals = await self.generate_proposals(open_shifts, date_range)

        # Step 3: Write to sheet (optional)
        written = 0
        if write_to_sheet and proposals:
            written = await self.write_proposals(proposals)

        # Build summary
        proposals_with_candidates = sum(1 for p in proposals if p.has_candidates)

        summary = {
            "open_shifts": len(open_shifts),
            "proposals": len(proposals),
            "proposals_with_candidates": proposals_with_candidates,
            "proposals_without_candidates": len(proposals) - proposals_with_candidates,
            "written": written,
            "open_shift_details": [
                {
                    "id": s.id,
                    "date": s.shift_date.isoformat(),
                    "time": f"{s.shift_start}-{s.shift_end}",
                    "zone": s.zone,
                }
                for s in open_shifts
            ],
            "proposal_details": [
                {
                    "id": p.id,
                    "shift_id": p.open_shift_id,
                    "date": p.shift_date.isoformat(),
                    "top_candidate": p.top_candidate_name,
                    "candidate_count": len([c for c in p.candidates if c.is_eligible]),
                }
                for p in proposals
            ],
        }

        logger.info(
            f"Dispatch assist complete: {summary['open_shifts']} open shifts, "
            f"{summary['proposals']} proposals generated, {written} written to sheet"
        )

        return summary

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _compute_driver_states(
        self,
        drivers: List[DriverState],
        roster: List[ShiftAssignment],
        target_date: date,
    ) -> Dict[str, DriverState]:
        """
        Compute current state for each driver based on roster.

        Updates each driver with:
        - hours_worked_this_week
        - tours_this_week
        - shifts_today
        - last_shift_end

        Args:
            drivers: Base driver data
            roster: All roster assignments
            target_date: The date we're evaluating for

        Returns:
            Dict of driver_id -> DriverState with computed values
        """
        # Build roster by driver
        assignments_by_driver: Dict[str, List[ShiftAssignment]] = {}
        for assignment in roster:
            if not assignment.driver_id:
                continue
            if assignment.driver_id not in assignments_by_driver:
                assignments_by_driver[assignment.driver_id] = []
            assignments_by_driver[assignment.driver_id].append(assignment)

        # Determine week boundaries
        week_start = target_date - timedelta(days=target_date.weekday())
        week_end = week_start + timedelta(days=6)

        # Update each driver
        driver_states = {}
        for driver in drivers:
            driver.week_start = week_start

            assignments = assignments_by_driver.get(driver.driver_id, [])

            # Calculate weekly hours
            weekly_hours = 0.0
            weekly_tours = 0
            for a in assignments:
                if week_start <= a.shift_date <= week_end:
                    weekly_hours += a.duration_hours
                    weekly_tours += 1

            driver.hours_worked_this_week = weekly_hours
            driver.tours_this_week = weekly_tours

            # Get today's shifts
            driver.shifts_today = [a for a in assignments if a.shift_date == target_date]

            # Find last shift end (for rest calculation)
            past_shifts = [a for a in assignments if a.shift_date < target_date]
            if past_shifts:
                # Sort by date/time descending
                past_shifts.sort(
                    key=lambda a: (a.shift_date, a.shift_end),
                    reverse=True,
                )
                last = past_shifts[0]
                driver.last_shift_end = datetime.combine(last.shift_date, last.shift_end)
            else:
                driver.last_shift_end = None

            driver_states[driver.driver_id] = driver

        return driver_states


# =============================================================================
# DISPATCH APPLY SERVICE
# =============================================================================

class DispatchApplyService:
    """
    Service for applying dispatch proposals with optimistic concurrency control.

    Implements the apply workflow:
    1. Load proposal and verify status = PROPOSED
    2. Check idempotency (apply_request_id) - return cached if exists
    3. Get latest sheet fingerprint
    4. Compare fingerprints - PLAN_CHANGED if mismatch (unless force=true)
    5. Revalidate selected driver eligibility
    6. If ineligible - NOT_ELIGIBLE with reason codes
    7. Write to sheet (driver_id, driver_name, status)
    8. Update proposal status -> APPLIED
    9. Create audit entry
    10. Return result
    """

    def __init__(
        self,
        adapter: SheetAdapterBase,
        repository: DispatchRepository,
        config: Optional[DispatchConfig] = None,
    ):
        """
        Initialize apply service.

        Args:
            adapter: Sheet adapter for reading/writing roster
            repository: Database repository for proposals
            config: Optional dispatch configuration
        """
        self.adapter = adapter
        self.repository = repository
        self.config = config or DispatchConfig()
        self.eligibility_checker = EligibilityChecker(
            rest_hours=self.config.rest_hours,
            max_tours_per_day=self.config.max_tours_per_day,
            max_weekly_hours=self.config.max_weekly_hours,
        )

    async def apply_proposal(
        self,
        tenant_id: int,
        request: ApplyRequest,
        performed_by: str,
    ) -> ApplyResult:
        """
        Apply a proposal to assign a driver to an open shift.

        Implements optimistic concurrency control via fingerprint comparison.

        Args:
            tenant_id: Tenant ID
            request: Apply request with proposal_id, driver_id, fingerprint
            performed_by: User performing the apply (email or ID)

        Returns:
            ApplyResult with success/error details
        """
        logger.info(
            f"Apply request: proposal={request.proposal_id}, "
            f"driver={request.selected_driver_id}, "
            f"force={request.force}"
        )

        # Step 0: Validate sheet contract (prevents silent failures)
        contract_validation = await self.adapter.validate_sheet_contract()
        if not contract_validation.is_valid:
            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="SHEET_CONTRACT_INVALID",
                error_message=contract_validation.error_message,
            )

        # Step 1: Check idempotency
        if request.apply_request_id:
            existing = await self.repository.get_proposal_by_apply_request_id(
                tenant_id, request.apply_request_id
            )
            if existing and existing.status == ProposalStatus.APPLIED:
                logger.info(f"Idempotent request: returning cached result")
                return ApplyResult(
                    success=True,
                    proposal_id=existing.id,
                    selected_driver_id=existing.selected_driver_id or "",
                    selected_driver_name=existing.selected_driver_name or "",
                    applied_at=existing.applied_at,
                    cells_written=[],  # Cached response doesn't repeat cells
                )

        # Step 2: Load proposal and verify status
        proposal = await self.repository.get_proposal(tenant_id, request.proposal_id)
        if not proposal:
            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="PROPOSAL_NOT_FOUND",
                error_message=f"Proposal {request.proposal_id} not found",
            )

        if proposal.status not in (ProposalStatus.GENERATED, ProposalStatus.PROPOSED):
            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="INVALID_STATUS",
                error_message=f"Proposal status is {proposal.status.value}, expected GENERATED or PROPOSED",
            )

        # Step 3: Get latest sheet fingerprint
        scope = FingerprintScope(
            shift_date=proposal.shift_date,
            scope_type=FingerprintScopeType(
                proposal.fingerprint_scope.get("scope_type", "DAY_PM1")
            ),
        )
        latest_fingerprint_data = await self.adapter.get_current_fingerprint(scope)
        latest_fingerprint = latest_fingerprint_data.fingerprint

        # Step 4: Compare fingerprints
        fingerprint_matched = (
            request.expected_plan_fingerprint == latest_fingerprint
        )

        if not fingerprint_matched and not request.force:
            # Compute diff hints to help user understand what changed
            old_data = await self._get_scoped_data_for_fingerprint(
                request.expected_plan_fingerprint, scope
            )
            new_data = await self.adapter.read_scoped_ranges(scope)
            diff_hints = await self.adapter.compute_diff_hints(old_data, new_data, scope)

            # Update proposal with latest fingerprint and hints
            await self.repository.update_proposal_conflict(
                tenant_id,
                request.proposal_id,
                latest_fingerprint=latest_fingerprint,
                hint_diffs=diff_hints.to_dict() if diff_hints else None,
            )

            # Record audit entry for conflict
            await self.repository.record_audit(
                tenant_id=tenant_id,
                proposal_id=request.proposal_id,
                action="CONFLICT",
                performed_by=performed_by,
                selected_driver_id=request.selected_driver_id,
                expected_fingerprint=request.expected_plan_fingerprint,
                actual_fingerprint=latest_fingerprint,
                fingerprint_matched=False,
            )

            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="PLAN_CHANGED",
                error_message="Sheet data has changed since proposal was generated",
                expected_fingerprint=request.expected_plan_fingerprint,
                latest_fingerprint=latest_fingerprint,
                hint_diffs=diff_hints,
            )

        # Step 5: Revalidate driver eligibility
        open_shift = await self._build_open_shift_from_proposal(proposal)
        driver_state = await self._get_driver_state(request.selected_driver_id, proposal.shift_date)

        if not driver_state:
            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="DRIVER_NOT_FOUND",
                error_message=f"Driver {request.selected_driver_id} not found",
            )

        # Check eligibility using existing checker
        eligible_candidates = self.eligibility_checker.filter_eligible_drivers(
            [driver_state], open_shift
        )

        # Find the candidate result for our driver
        driver_candidate = None
        for c in eligible_candidates:
            if c.driver_id == request.selected_driver_id:
                driver_candidate = c
                break

        if not driver_candidate or not driver_candidate.is_eligible:
            disqualifications = driver_candidate.disqualifications if driver_candidate else []

            # Record audit entry for eligibility failure
            await self.repository.record_audit(
                tenant_id=tenant_id,
                proposal_id=request.proposal_id,
                action="REJECT",
                performed_by=performed_by,
                selected_driver_id=request.selected_driver_id,
                expected_fingerprint=request.expected_plan_fingerprint,
                actual_fingerprint=latest_fingerprint,
                fingerprint_matched=fingerprint_matched,
                eligibility_passed=False,
                eligibility_reasons=[d.to_dict() for d in disqualifications],
            )

            return ApplyResult(
                success=False,
                proposal_id=request.proposal_id,
                error_code="NOT_ELIGIBLE",
                error_message=f"Driver {request.selected_driver_id} is not eligible",
                disqualifications=disqualifications,
            )

        # Step 6: Write assignment to sheet
        cells_written = await self.adapter.write_assignment(
            row_index=proposal.source_row_index or 0,
            driver_id=request.selected_driver_id,
            driver_name=driver_state.driver_name,
            status="ASSIGNED",
        )

        # Step 7: Update proposal status to APPLIED
        applied_at = datetime.utcnow()
        await self.repository.update_proposal_to_applied(
            tenant_id=tenant_id,
            proposal_id=request.proposal_id,
            selected_driver_id=request.selected_driver_id,
            selected_driver_name=driver_state.driver_name,
            apply_request_id=request.apply_request_id,
            forced=request.force,
            force_reason=request.force_reason,
            latest_fingerprint=latest_fingerprint,
        )

        # Step 8: Update open shift status
        if proposal.open_shift_id:
            await self.repository.update_open_shift_status(
                tenant_id=tenant_id,
                open_shift_id=proposal.open_shift_id,
                status=OpenShiftStatus.APPLIED,
            )

        # Step 9: Record audit entry
        await self.repository.record_audit(
            tenant_id=tenant_id,
            proposal_id=request.proposal_id,
            action="APPLY",
            performed_by=performed_by,
            selected_driver_id=request.selected_driver_id,
            expected_fingerprint=request.expected_plan_fingerprint,
            actual_fingerprint=latest_fingerprint,
            fingerprint_matched=fingerprint_matched,
            eligibility_passed=True,
            sheet_cells_written=cells_written,
            forced=request.force,
            force_reason=request.force_reason,
        )

        # Invalidate fingerprint cache after write
        self.adapter.invalidate_fingerprint_cache()

        logger.info(
            f"Apply successful: proposal={request.proposal_id}, "
            f"driver={request.selected_driver_id}, "
            f"cells_written={cells_written}"
        )

        return ApplyResult(
            success=True,
            proposal_id=request.proposal_id,
            selected_driver_id=request.selected_driver_id,
            selected_driver_name=driver_state.driver_name,
            applied_at=applied_at,
            cells_written=cells_written,
        )

    async def _get_scoped_data_for_fingerprint(
        self,
        fingerprint: str,
        scope: FingerprintScope,
    ) -> Dict:
        """
        Try to get the original data for a fingerprint.

        In production, we can't reconstruct old data from fingerprint alone.
        This returns empty dict - diff hints will show current state only.
        """
        # Fingerprint is one-way hash, can't reconstruct original data
        # Diff hints will just show what tabs have changes
        return {}

    async def _build_open_shift_from_proposal(
        self,
        proposal: PersistedProposal,
    ) -> OpenShift:
        """Build an OpenShift object from a persisted proposal."""
        return OpenShift(
            id=proposal.open_shift_id or proposal.id,
            shift_date=proposal.shift_date,
            shift_key=proposal.shift_key,
            shift_start=proposal.shift_start or "06:00",
            shift_end=proposal.shift_end or "14:00",
            route_id=proposal.route_id,
            zone=proposal.zone,
            row_index=proposal.source_row_index,
        )

    async def _get_driver_state(
        self,
        driver_id: str,
        target_date: date,
    ) -> Optional[DriverState]:
        """
        Get current state for a driver.

        Reads from sheet to get latest hours, shifts, etc.
        """
        # Read drivers from sheet
        drivers = await self.adapter.read_drivers()

        # Find the target driver
        driver = None
        for d in drivers:
            if d.driver_id == driver_id:
                driver = d
                break

        if not driver:
            return None

        # Compute date range for weekly context
        week_start = target_date - timedelta(days=target_date.weekday())
        week_end = week_start + timedelta(days=6)
        date_range = (week_start, week_end)

        # Read roster for the range
        roster = await self.adapter.read_roster(date_range)

        # Get assignments for this driver
        driver_assignments = [a for a in roster if a.driver_id == driver_id]

        # Calculate weekly hours
        weekly_hours = sum(
            a.duration_hours
            for a in driver_assignments
            if week_start <= a.shift_date <= week_end
        )
        driver.hours_worked_this_week = weekly_hours
        driver.week_start = week_start

        # Get today's shifts
        driver.shifts_today = [a for a in driver_assignments if a.shift_date == target_date]

        # Find last shift end (for rest calculation)
        past_shifts = [a for a in driver_assignments if a.shift_date < target_date]
        if past_shifts:
            past_shifts.sort(key=lambda a: (a.shift_date, a.shift_end), reverse=True)
            last = past_shifts[0]
            driver.last_shift_end = datetime.combine(last.shift_date, last.shift_end)
        else:
            driver.last_shift_end = None

        return driver


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_dispatch_service(
    sheet_config: SheetConfig,
    dispatch_config: Optional[DispatchConfig] = None,
    credentials: Optional[Dict] = None,
) -> DispatchAssistService:
    """
    Create a dispatch service with Google Sheets adapter.

    Args:
        sheet_config: Sheet configuration
        dispatch_config: Optional dispatch configuration
        credentials: Optional service account credentials

    Returns:
        Configured DispatchAssistService
    """
    adapter = GoogleSheetsAdapter(sheet_config, credentials)
    return DispatchAssistService(adapter, dispatch_config)


def create_mock_dispatch_service(
    dispatch_config: Optional[DispatchConfig] = None,
) -> Tuple[DispatchAssistService, MockSheetAdapter]:
    """
    Create a dispatch service with mock adapter (for testing).

    Args:
        dispatch_config: Optional dispatch configuration

    Returns:
        Tuple of (service, mock_adapter)
    """
    adapter = MockSheetAdapter()
    service = DispatchAssistService(adapter, dispatch_config)
    return service, adapter


def create_apply_service(
    sheet_config: SheetConfig,
    repository: DispatchRepository,
    dispatch_config: Optional[DispatchConfig] = None,
    credentials: Optional[Dict] = None,
) -> DispatchApplyService:
    """
    Create an apply service with Google Sheets adapter.

    Args:
        sheet_config: Sheet configuration
        repository: Database repository for proposals
        dispatch_config: Optional dispatch configuration
        credentials: Optional service account credentials

    Returns:
        Configured DispatchApplyService
    """
    adapter = GoogleSheetsAdapter(sheet_config, credentials)
    return DispatchApplyService(adapter, repository, dispatch_config)


def create_mock_apply_service(
    dispatch_config: Optional[DispatchConfig] = None,
) -> Tuple[DispatchApplyService, MockSheetAdapter, MockDispatchRepository]:
    """
    Create an apply service with mock adapters (for testing).

    Args:
        dispatch_config: Optional dispatch configuration

    Returns:
        Tuple of (service, mock_adapter, mock_repository)
    """
    adapter = MockSheetAdapter()
    repository = MockDispatchRepository()
    service = DispatchApplyService(adapter, repository, dispatch_config)
    return service, adapter, repository
