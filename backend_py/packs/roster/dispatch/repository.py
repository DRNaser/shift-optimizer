"""
SOLVEREIGN Gurkerl Dispatch Assist - Repository Layer
======================================================

Database operations for dispatch proposals and open shifts.

Uses the dispatch schema with RLS tenant isolation.
All operations require tenant context to be set via app.current_tenant_id.
"""

import json
import logging
from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from uuid import UUID

from .models import (
    FingerprintScope,
    FingerprintScopeType,
    FingerprintData,
    DiffHints,
    ApplyResult,
    PersistedProposal,
    Candidate,
    Disqualification,
    DisqualificationReason,
    ProposalStatus,
    OpenShiftStatus,
)

logger = logging.getLogger(__name__)


class DispatchRepository:
    """
    Repository for dispatch lifecycle database operations.

    All operations use RLS via app.current_tenant_id session variable.
    """

    def __init__(self, db_manager):
        """
        Initialize repository.

        Args:
            db_manager: Database manager with tenant_transaction support
        """
        self.db = db_manager

    # =========================================================================
    # OPEN SHIFT OPERATIONS
    # =========================================================================

    async def upsert_open_shift(
        self,
        tenant_id: int,
        shift_date: date,
        shift_key: str,
        shift_start: time,
        shift_end: time,
        zone: Optional[str] = None,
        route_id: Optional[str] = None,
        site_id: Optional[str] = None,
        source_row_index: Optional[int] = None,
        source_revision: Optional[int] = None,
        required_skills: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create or update an open shift (idempotent).

        Args:
            tenant_id: Tenant ID
            shift_date: Date of the shift
            shift_key: Unique key within tenant+date
            shift_start: Shift start time
            shift_end: Shift end time
            zone: Optional zone
            route_id: Optional route ID
            site_id: Optional site UUID
            source_row_index: Row in source sheet
            source_revision: Sheet revision when detected
            required_skills: List of required skills
            metadata: Additional metadata

        Returns:
            UUID of the open shift
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT dispatch.upsert_open_shift(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                    ) AS shift_id
                    """,
                    (
                        tenant_id,
                        shift_date,
                        shift_key,
                        shift_start,
                        shift_end,
                        zone,
                        route_id,
                        UUID(site_id) if site_id else None,
                        source_row_index,
                        source_revision,
                        json.dumps(required_skills or []),
                        json.dumps(metadata or {}),
                    )
                )
                row = await cur.fetchone()
                return str(row["shift_id"])

    async def get_open_shift(
        self,
        tenant_id: int,
        shift_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get an open shift by ID.

        Args:
            tenant_id: Tenant ID
            shift_id: UUID of the shift

        Returns:
            Dict with shift data or None
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, tenant_id, site_id, shift_date, shift_key,
                           shift_start, shift_end, route_id, zone,
                           required_skills, source_system, source_row_index,
                           source_revision, status, detected_at, closed_at,
                           closed_reason, metadata, created_at, updated_at
                    FROM dispatch.dispatch_open_shifts
                    WHERE id = %s
                    """,
                    (UUID(shift_id),)
                )
                row = await cur.fetchone()
                return dict(row) if row else None

    async def update_open_shift_status(
        self,
        tenant_id: int,
        shift_id: str,
        new_status: str,
        closed_reason: Optional[str] = None,
    ) -> bool:
        """
        Update open shift status.

        Args:
            tenant_id: Tenant ID
            shift_id: UUID of the shift
            new_status: New status
            closed_reason: Optional reason if closing

        Returns:
            True if updated
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                if new_status in ('CLOSED', 'INVALIDATED', 'APPLIED'):
                    await cur.execute(
                        """
                        UPDATE dispatch.dispatch_open_shifts
                        SET status = %s, closed_at = NOW(), closed_reason = %s
                        WHERE id = %s
                        RETURNING id
                        """,
                        (new_status, closed_reason, UUID(shift_id))
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE dispatch.dispatch_open_shifts
                        SET status = %s
                        WHERE id = %s
                        RETURNING id
                        """,
                        (new_status, UUID(shift_id))
                    )
                row = await cur.fetchone()
                return row is not None

    # =========================================================================
    # PROPOSAL OPERATIONS
    # =========================================================================

    async def create_proposal(
        self,
        tenant_id: int,
        open_shift_id: str,
        shift_key: str,
        fingerprint: str,
        revision: Optional[int],
        scope: FingerprintScope,
        candidates: List[Candidate],
        site_id: Optional[str] = None,
        generated_by: str = "solvereign",
        config_version: str = "v1",
    ) -> str:
        """
        Create a new proposal with fingerprint.

        Args:
            tenant_id: Tenant ID
            open_shift_id: UUID of the open shift
            shift_key: Shift key for denormalization
            fingerprint: SHA-256 fingerprint of sheet state
            revision: Sheet revision number
            scope: FingerprintScope used
            candidates: List of ranked candidates
            site_id: Optional site UUID
            generated_by: Who generated the proposal
            config_version: Config schema version

        Returns:
            UUID of the created proposal
        """
        # Serialize candidates to JSON
        candidates_json = json.dumps([
            {
                "driver_id": c.driver_id,
                "driver_name": c.driver_name,
                "score": c.score,
                "rank": c.rank,
                "is_eligible": c.is_eligible,
                "reasons": c.reasons,
                "disqualifications": [
                    {"reason": d.reason.value, "details": d.details, "severity": d.severity}
                    for d in c.disqualifications
                ],
                "current_weekly_hours": c.current_weekly_hours,
                "hours_after_assignment": c.hours_after_assignment,
            }
            for c in candidates
        ])

        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO dispatch.dispatch_proposals (
                        tenant_id, site_id, open_shift_id, shift_key,
                        expected_plan_fingerprint, expected_revision, config_version,
                        fingerprint_scope, candidates, status,
                        generated_at, generated_by
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s::jsonb, %s::jsonb, 'GENERATED',
                        NOW(), %s
                    )
                    RETURNING id
                    """,
                    (
                        tenant_id,
                        UUID(site_id) if site_id else None,
                        UUID(open_shift_id),
                        shift_key,
                        fingerprint,
                        revision,
                        config_version,
                        json.dumps(scope.to_dict()),
                        candidates_json,
                        generated_by,
                    )
                )
                row = await cur.fetchone()
                proposal_id = str(row["id"])

                # Update open shift status
                await cur.execute(
                    """
                    UPDATE dispatch.dispatch_open_shifts
                    SET status = 'PROPOSAL_GENERATED'
                    WHERE id = %s AND status = 'DETECTED'
                    """,
                    (UUID(open_shift_id),)
                )

                logger.info(f"Created proposal {proposal_id} for shift {shift_key}")
                return proposal_id

    async def get_proposal(
        self,
        tenant_id: int,
        proposal_id: str,
    ) -> Optional[PersistedProposal]:
        """
        Get a proposal by ID.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal

        Returns:
            PersistedProposal or None
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, tenant_id, site_id, open_shift_id, shift_key,
                           expected_plan_fingerprint, expected_revision, config_version,
                           fingerprint_scope, candidates, status,
                           generated_at, generated_by, proposed_at, proposed_by,
                           applied_at, applied_by, selected_driver_id, selected_driver_name,
                           apply_request_id, forced_apply, force_reason,
                           latest_fingerprint, hint_diffs,
                           invalidated_at, invalidated_reason,
                           created_at, updated_at
                    FROM dispatch.dispatch_proposals
                    WHERE id = %s
                    """,
                    (UUID(proposal_id),)
                )
                row = await cur.fetchone()
                if not row:
                    return None

                return self._row_to_proposal(row)

    async def get_proposal_by_apply_request_id(
        self,
        tenant_id: int,
        apply_request_id: str,
    ) -> Optional[PersistedProposal]:
        """
        Get a proposal by apply_request_id (for idempotency).

        Args:
            tenant_id: Tenant ID
            apply_request_id: UUID idempotency key

        Returns:
            PersistedProposal or None
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, tenant_id, site_id, open_shift_id, shift_key,
                           expected_plan_fingerprint, expected_revision, config_version,
                           fingerprint_scope, candidates, status,
                           generated_at, generated_by, proposed_at, proposed_by,
                           applied_at, applied_by, selected_driver_id, selected_driver_name,
                           apply_request_id, forced_apply, force_reason,
                           latest_fingerprint, hint_diffs,
                           invalidated_at, invalidated_reason,
                           created_at, updated_at
                    FROM dispatch.dispatch_proposals
                    WHERE apply_request_id = %s
                    """,
                    (UUID(apply_request_id),)
                )
                row = await cur.fetchone()
                if not row:
                    return None

                return self._row_to_proposal(row)

    async def update_proposal_to_proposed(
        self,
        tenant_id: int,
        proposal_id: str,
        proposed_by: str,
    ) -> bool:
        """
        Update proposal status from GENERATED to PROPOSED.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal
            proposed_by: Who sent the proposal

        Returns:
            True if updated
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dispatch.dispatch_proposals
                    SET status = 'PROPOSED', proposed_at = NOW(), proposed_by = %s
                    WHERE id = %s AND status = 'GENERATED'
                    RETURNING id
                    """,
                    (proposed_by, UUID(proposal_id))
                )
                row = await cur.fetchone()
                return row is not None

    async def update_proposal_to_applied(
        self,
        tenant_id: int,
        proposal_id: str,
        selected_driver_id: str,
        selected_driver_name: str,
        applied_by: str,
        apply_request_id: Optional[str] = None,
        forced: bool = False,
        force_reason: Optional[str] = None,
    ) -> bool:
        """
        Update proposal status to APPLIED.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal
            selected_driver_id: Chosen driver ID
            selected_driver_name: Chosen driver name
            applied_by: Who applied
            apply_request_id: Idempotency key
            forced: Whether force flag was used
            force_reason: Reason for forcing

        Returns:
            True if updated
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dispatch.dispatch_proposals
                    SET status = 'APPLIED',
                        applied_at = NOW(),
                        applied_by = %s,
                        selected_driver_id = %s,
                        selected_driver_name = %s,
                        apply_request_id = %s,
                        forced_apply = %s,
                        force_reason = %s
                    WHERE id = %s AND status = 'PROPOSED'
                    RETURNING id, open_shift_id
                    """,
                    (
                        applied_by,
                        selected_driver_id,
                        selected_driver_name,
                        UUID(apply_request_id) if apply_request_id else None,
                        forced,
                        force_reason,
                        UUID(proposal_id),
                    )
                )
                row = await cur.fetchone()
                if row:
                    # Also update open shift status
                    await cur.execute(
                        """
                        UPDATE dispatch.dispatch_open_shifts
                        SET status = 'APPLIED', closed_at = NOW(), closed_reason = 'Applied via proposal'
                        WHERE id = %s
                        """,
                        (row["open_shift_id"],)
                    )
                    return True
                return False

    async def update_proposal_conflict(
        self,
        tenant_id: int,
        proposal_id: str,
        latest_fingerprint: str,
        hint_diffs: DiffHints,
    ) -> bool:
        """
        Record a fingerprint conflict on a proposal.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal
            latest_fingerprint: The actual fingerprint found
            hint_diffs: What changed

        Returns:
            True if updated
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dispatch.dispatch_proposals
                    SET latest_fingerprint = %s, hint_diffs = %s::jsonb
                    WHERE id = %s
                    RETURNING id
                    """,
                    (
                        latest_fingerprint,
                        json.dumps(hint_diffs.to_dict()),
                        UUID(proposal_id),
                    )
                )
                row = await cur.fetchone()
                return row is not None

    async def invalidate_proposal(
        self,
        tenant_id: int,
        proposal_id: str,
        reason: str,
    ) -> bool:
        """
        Invalidate a proposal.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal
            reason: Why invalidated

        Returns:
            True if updated
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dispatch.dispatch_proposals
                    SET status = 'INVALIDATED',
                        invalidated_at = NOW(),
                        invalidated_reason = %s
                    WHERE id = %s AND status IN ('GENERATED', 'PROPOSED')
                    RETURNING id
                    """,
                    (reason, UUID(proposal_id))
                )
                row = await cur.fetchone()
                return row is not None

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def record_audit(
        self,
        tenant_id: int,
        proposal_id: str,
        open_shift_id: str,
        action: str,
        performed_by: str,
        selected_driver_id: Optional[str] = None,
        selected_driver_name: Optional[str] = None,
        expected_fingerprint: Optional[str] = None,
        actual_fingerprint: Optional[str] = None,
        fingerprint_matched: Optional[bool] = None,
        fingerprint_scope: Optional[FingerprintScope] = None,
        eligibility_passed: Optional[bool] = None,
        eligibility_reasons: Optional[List[Dict]] = None,
        sheet_cells_written: Optional[List[str]] = None,
        forced: bool = False,
        force_reason: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        apply_request_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """
        Record an audit entry.

        Args:
            tenant_id: Tenant ID
            proposal_id: UUID of the proposal
            open_shift_id: UUID of the open shift
            action: Action type (APPLY, REJECT, CONFLICT, etc.)
            performed_by: Actor
            ... additional fields

        Returns:
            UUID of the audit entry
        """
        async with self.db.tenant_transaction(tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT dispatch.record_apply_audit(
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s::jsonb,
                        %s, %s::jsonb,
                        %s::jsonb,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s
                    ) AS audit_id
                    """,
                    (
                        tenant_id,
                        UUID(proposal_id),
                        UUID(open_shift_id) if open_shift_id else None,
                        action,
                        performed_by,
                        selected_driver_id,
                        selected_driver_name,
                        expected_fingerprint,
                        actual_fingerprint,
                        fingerprint_matched,
                        json.dumps(fingerprint_scope.to_dict()) if fingerprint_scope else None,
                        eligibility_passed,
                        json.dumps(eligibility_reasons) if eligibility_reasons else None,
                        json.dumps(sheet_cells_written) if sheet_cells_written else None,
                        forced,
                        force_reason,
                        error_code,
                        error_message,
                        UUID(apply_request_id) if apply_request_id else None,
                        client_ip,
                        user_agent,
                    )
                )
                row = await cur.fetchone()
                return str(row["audit_id"])

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_proposal(self, row: Dict) -> PersistedProposal:
        """Convert database row to PersistedProposal."""
        # Parse candidates JSON
        candidates_data = row.get("candidates") or []
        if isinstance(candidates_data, str):
            candidates_data = json.loads(candidates_data)

        candidates = []
        for c in candidates_data:
            disqualifications = [
                Disqualification(
                    reason=DisqualificationReason(d["reason"]),
                    details=d.get("details", ""),
                    severity=d.get("severity", 1),
                )
                for d in c.get("disqualifications", [])
            ]
            candidates.append(Candidate(
                driver_id=c["driver_id"],
                driver_name=c["driver_name"],
                score=c.get("score", 0.0),
                rank=c.get("rank", 0),
                is_eligible=c.get("is_eligible", True),
                reasons=c.get("reasons", []),
                disqualifications=disqualifications,
                current_weekly_hours=c.get("current_weekly_hours", 0.0),
                hours_after_assignment=c.get("hours_after_assignment", 0.0),
            ))

        # Parse fingerprint scope
        scope_data = row.get("fingerprint_scope") or {}
        if isinstance(scope_data, str):
            scope_data = json.loads(scope_data)

        scope = FingerprintScope.from_dict(scope_data) if scope_data else None

        # Parse hint_diffs
        hints_data = row.get("hint_diffs")
        if hints_data:
            if isinstance(hints_data, str):
                hints_data = json.loads(hints_data)
            hints = DiffHints(
                roster_changed=hints_data.get("roster_changed", False),
                drivers_changed=hints_data.get("drivers_changed", False),
                absences_changed=hints_data.get("absences_changed", False),
                changed_roster_rows=hints_data.get("changed_roster_rows", []),
            )
        else:
            hints = None

        return PersistedProposal(
            id=str(row["id"]),
            tenant_id=row["tenant_id"],
            open_shift_id=str(row["open_shift_id"]),
            shift_key=row["shift_key"],
            expected_plan_fingerprint=row["expected_plan_fingerprint"],
            expected_revision=row.get("expected_revision"),
            fingerprint_scope=scope,
            config_version=row.get("config_version", "v1"),
            candidates=candidates,
            status=ProposalStatus(row["status"].lower()),
            generated_at=row["generated_at"],
            generated_by=row.get("generated_by", "solvereign"),
            proposed_at=row.get("proposed_at"),
            proposed_by=row.get("proposed_by"),
            applied_at=row.get("applied_at"),
            applied_by=row.get("applied_by"),
            selected_driver_id=row.get("selected_driver_id"),
            selected_driver_name=row.get("selected_driver_name"),
            apply_request_id=str(row["apply_request_id"]) if row.get("apply_request_id") else None,
            forced_apply=row.get("forced_apply", False),
            force_reason=row.get("force_reason"),
            latest_fingerprint=row.get("latest_fingerprint"),
            hint_diffs=hints,
            site_id=str(row["site_id"]) if row.get("site_id") else None,
        )


# =============================================================================
# MOCK REPOSITORY (for testing)
# =============================================================================

class MockDispatchRepository:
    """
    Mock repository for testing without database.
    """

    def __init__(self):
        self.open_shifts: Dict[str, Dict[str, Any]] = {}
        self.proposals: Dict[str, PersistedProposal] = {}
        self.audits: List[Dict[str, Any]] = []
        self._counter = 0

    def _generate_uuid(self) -> str:
        """Generate a mock UUID."""
        self._counter += 1
        return f"mock-uuid-{self._counter:06d}"

    async def upsert_open_shift(self, tenant_id: int, **kwargs) -> str:
        """Mock upsert open shift."""
        shift_key = f"{kwargs['shift_date']}_{kwargs['shift_key']}"
        existing_key = next(
            (k for k, v in self.open_shifts.items()
             if v.get("tenant_id") == tenant_id and v.get("shift_key") == kwargs["shift_key"]
             and v.get("shift_date") == kwargs["shift_date"]),
            None
        )
        if existing_key:
            self.open_shifts[existing_key].update(kwargs)
            return existing_key
        shift_id = self._generate_uuid()
        self.open_shifts[shift_id] = {"id": shift_id, "tenant_id": tenant_id, "status": "DETECTED", **kwargs}
        return shift_id

    async def get_open_shift(self, tenant_id: int, shift_id: str) -> Optional[Dict[str, Any]]:
        """Mock get open shift."""
        shift = self.open_shifts.get(shift_id)
        if shift and shift.get("tenant_id") == tenant_id:
            return shift
        return None

    async def create_proposal(self, tenant_id: int, **kwargs) -> str:
        """Mock create proposal."""
        proposal_id = self._generate_uuid()
        proposal = PersistedProposal(
            id=proposal_id,
            tenant_id=tenant_id,
            open_shift_id=kwargs["open_shift_id"],
            shift_key=kwargs["shift_key"],
            expected_plan_fingerprint=kwargs["fingerprint"],
            expected_revision=kwargs.get("revision"),
            fingerprint_scope=kwargs.get("scope"),
            candidates=kwargs.get("candidates", []),
            status=ProposalStatus.GENERATED,
        )
        self.proposals[proposal_id] = proposal
        return proposal_id

    async def get_proposal(self, tenant_id: int, proposal_id: str) -> Optional[PersistedProposal]:
        """Mock get proposal."""
        proposal = self.proposals.get(proposal_id)
        if proposal and proposal.tenant_id == tenant_id:
            return proposal
        return None

    async def get_proposal_by_apply_request_id(
        self, tenant_id: int, apply_request_id: str
    ) -> Optional[PersistedProposal]:
        """Mock idempotency check."""
        for proposal in self.proposals.values():
            if proposal.tenant_id == tenant_id and proposal.apply_request_id == apply_request_id:
                return proposal
        return None

    async def update_proposal_to_proposed(
        self, tenant_id: int, proposal_id: str, proposed_by: str
    ) -> bool:
        """Mock update to proposed."""
        proposal = self.proposals.get(proposal_id)
        if proposal and proposal.status == ProposalStatus.GENERATED:
            proposal.status = ProposalStatus.PROPOSED
            proposal.proposed_by = proposed_by
            proposal.proposed_at = datetime.now()
            return True
        return False

    async def update_proposal_to_applied(
        self,
        tenant_id: int,
        proposal_id: str,
        selected_driver_id: str,
        selected_driver_name: str,
        applied_by: str,
        **kwargs
    ) -> bool:
        """Mock update to applied."""
        proposal = self.proposals.get(proposal_id)
        if proposal and proposal.status == ProposalStatus.PROPOSED:
            proposal.status = ProposalStatus.APPLIED
            proposal.selected_driver_id = selected_driver_id
            proposal.selected_driver_name = selected_driver_name
            proposal.applied_by = applied_by
            proposal.applied_at = datetime.now()
            proposal.apply_request_id = kwargs.get("apply_request_id")
            proposal.forced_apply = kwargs.get("forced", False)
            proposal.force_reason = kwargs.get("force_reason")
            return True
        return False

    async def record_audit(self, tenant_id: int, **kwargs) -> str:
        """Mock record audit."""
        audit_id = self._generate_uuid()
        self.audits.append({"audit_id": audit_id, "tenant_id": tenant_id, **kwargs})
        return audit_id
