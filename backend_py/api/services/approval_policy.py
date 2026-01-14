"""
SOLVEREIGN V4.6 - Approval Policy Service
==========================================

Risk-based approval system with variable approval requirements:
- LOW RISK: Single approver (standard operations)
- HIGH RISK: Two approvers required (publish/freeze/repair >N drivers)
- CRITICAL: Two approvers (rest-time impacts)
- EMERGENCY: Single approver with EMERGENCY_OVERRIDE flag + next-day review

All approvals and overrides are fully audited with correlation_id + evidence JSON.

Usage:
    service = ApprovalPolicyService(conn, tenant_id)

    # Check if action needs approval
    assessment = await service.assess_action("PUBLISH", "PLAN", context)

    # Create approval request
    request_id = await service.request_approval(
        action_type="PUBLISH",
        entity_type="PLAN",
        entity_id=plan_id,
        requested_by="user@example.com",
        action_payload={"plan_id": str(plan_id)},
        evidence={"affected_drivers": driver_list}
    )

    # Submit approval decision
    result = await service.submit_decision(
        request_id=request_id,
        user_id=approver_id,
        decision="APPROVE"
    )

    # Emergency override
    result = await service.emergency_override(
        request_id=request_id,
        user_id=approver_id,
        justification="Urgent coverage needed"
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class RiskAssessment:
    """Result of risk assessment for an action."""
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    risk_score: int  # 0-100
    risk_factors: List[Dict[str, Any]] = field(default_factory=list)
    required_approvals: int = 1
    policy_id: Optional[UUID] = None
    policy_key: Optional[str] = None
    allow_emergency_override: bool = True

    @property
    def needs_two_approvers(self) -> bool:
        return self.required_approvals >= 2

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("HIGH", "CRITICAL")


@dataclass
class ApprovalRequest:
    """Pending or completed approval request."""
    id: UUID
    tenant_id: int
    action_type: str
    entity_type: Optional[str]
    entity_id: Optional[UUID]
    entity_name: Optional[str]
    risk_level: str
    risk_score: int
    required_approvals: int
    current_approvals: int
    status: str
    requested_by: str
    requested_at: datetime
    expires_at: Optional[datetime]
    is_emergency_override: bool = False
    emergency_justification: Optional[str] = None
    correlation_id: Optional[UUID] = None


@dataclass
class ApprovalDecision:
    """Individual approval/rejection decision."""
    id: UUID
    request_id: UUID
    decided_by_user_id: UUID
    decided_by_email: str
    decided_by_role: str
    decision: str  # APPROVE, REJECT
    decision_reason: Optional[str]
    decided_at: datetime


@dataclass
class DecisionResult:
    """Result of submitting a decision."""
    success: bool
    request_id: UUID
    decision: str
    current_approvals: int
    required_approvals: int
    is_complete: bool
    final_status: Optional[str] = None
    error: Optional[str] = None
    action_payload: Optional[Dict] = None


# =============================================================================
# APPROVAL POLICY SERVICE
# =============================================================================

class ApprovalPolicyService:
    """
    Service for managing risk-based approvals.

    Handles:
    - Risk assessment for actions
    - Approval request creation
    - Multi-approver decision processing
    - Emergency override with review queue
    """

    def __init__(self, conn: psycopg.Connection, tenant_id: int):
        """
        Initialize approval service.

        Args:
            conn: Database connection
            tenant_id: Tenant ID for RLS context
        """
        self.conn = conn
        self.tenant_id = tenant_id

    def _set_rls_context(self, cur):
        """Set RLS context for tenant isolation."""
        cur.execute("SELECT set_config('app.current_tenant_id', %s, TRUE)", (str(self.tenant_id),))

    async def assess_action(
        self,
        action_type: str,
        entity_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> RiskAssessment:
        """
        Assess risk level for an action.

        Args:
            action_type: PUBLISH, FREEZE, REPAIR, etc.
            entity_type: PLAN, SNAPSHOT, ROSTER, etc.
            context: Additional context (affected_drivers, near_rest_time, etc.)

        Returns:
            RiskAssessment with risk level and required approvals
        """
        context = context or {}

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            import json
            cur.execute("""
                SELECT auth.assess_action_risk(%s, %s, %s, %s::jsonb)
            """, (
                self.tenant_id,
                action_type,
                entity_type,
                json.dumps(context)
            ))

            result = cur.fetchone()[0]

            return RiskAssessment(
                risk_level=result.get("risk_level", "LOW"),
                risk_score=result.get("risk_score", 0),
                risk_factors=result.get("risk_factors", []),
                required_approvals=result.get("required_approvals", 1),
                policy_id=UUID(result["policy_id"]) if result.get("policy_id") else None,
                policy_key=result.get("policy_key"),
                allow_emergency_override=result.get("allow_emergency_override", True)
            )

    async def request_approval(
        self,
        action_type: str,
        entity_type: str,
        entity_id: UUID,
        entity_name: str,
        requested_by: str,
        action_payload: Dict[str, Any],
        evidence: Optional[Dict[str, Any]] = None,
        request_reason: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Create an approval request.

        Args:
            action_type: Type of action (PUBLISH, FREEZE, etc.)
            entity_type: Entity type (PLAN, SNAPSHOT, etc.)
            entity_id: Entity UUID
            entity_name: Entity display name
            requested_by: Requester email
            action_payload: Payload to execute on approval
            evidence: Impact evidence (affected_drivers, etc.)
            request_reason: Optional reason for request
            context: Risk assessment context

        Returns:
            UUID of created approval request
        """
        import json

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT auth.create_approval_request(
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb
                )
            """, (
                self.tenant_id,
                action_type,
                entity_type,
                str(entity_id),
                entity_name,
                requested_by,
                json.dumps(action_payload),
                json.dumps(evidence or {}),
                request_reason,
                json.dumps(context or {})
            ))

            request_id = cur.fetchone()[0]
            self.conn.commit()

            logger.info(
                f"Created approval request {request_id}: {action_type} on {entity_type} "
                f"by {requested_by}"
            )

            return request_id

    async def get_request(self, request_id: UUID) -> Optional[ApprovalRequest]:
        """
        Get an approval request by ID.

        Args:
            request_id: Request UUID

        Returns:
            ApprovalRequest or None
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT * FROM auth.approval_requests
                WHERE id = %s AND tenant_id = %s
            """, (str(request_id), self.tenant_id))

            row = cur.fetchone()
            if not row:
                return None

            return ApprovalRequest(
                id=row["id"],
                tenant_id=row["tenant_id"],
                action_type=row["action_type"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                entity_name=row["entity_name"],
                risk_level=row["risk_level"],
                risk_score=row["risk_score"],
                required_approvals=row["required_approvals"],
                current_approvals=row["current_approvals"],
                status=row["status"],
                requested_by=row["requested_by"],
                requested_at=row["requested_at"],
                expires_at=row["expires_at"],
                is_emergency_override=row["is_emergency_override"],
                emergency_justification=row["emergency_justification"],
                correlation_id=row["correlation_id"]
            )

    async def get_pending_requests(
        self,
        user_role: str,
        limit: int = 50
    ) -> List[ApprovalRequest]:
        """
        Get pending approval requests for a user.

        Args:
            user_role: User's role for access checking
            limit: Max requests to return

        Returns:
            List of pending ApprovalRequests
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT * FROM auth.get_pending_approvals(%s, %s)
                LIMIT %s
            """, (self.tenant_id, user_role, limit))

            rows = cur.fetchall()

            return [
                ApprovalRequest(
                    id=row["request_id"],
                    tenant_id=self.tenant_id,
                    action_type=row["action_type"],
                    entity_type=row["entity_type"],
                    entity_id=None,
                    entity_name=row["entity_name"],
                    risk_level=row["risk_level"],
                    risk_score=row["risk_score"],
                    required_approvals=row["required_approvals"],
                    current_approvals=row["current_approvals"],
                    status="PENDING",
                    requested_by=row["requested_by"],
                    requested_at=row["requested_at"],
                    expires_at=row["expires_at"]
                )
                for row in rows
            ]

    async def submit_decision(
        self,
        request_id: UUID,
        user_id: UUID,
        user_email: str,
        user_role: str,
        decision: str,  # APPROVE or REJECT
        reason: Optional[str] = None
    ) -> DecisionResult:
        """
        Submit an approval or rejection decision.

        Args:
            request_id: Request UUID
            user_id: Approver user UUID
            user_email: Approver email
            user_role: Approver role
            decision: APPROVE or REJECT
            reason: Optional decision reason

        Returns:
            DecisionResult with completion status
        """
        if decision not in ("APPROVE", "REJECT"):
            return DecisionResult(
                success=False,
                request_id=request_id,
                decision=decision,
                current_approvals=0,
                required_approvals=0,
                is_complete=False,
                error="Invalid decision. Must be APPROVE or REJECT."
            )

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT auth.submit_approval_decision(
                    %s, %s, %s, %s, %s, %s
                )
            """, (
                str(request_id),
                str(user_id),
                user_email,
                user_role,
                decision,
                reason
            ))

            result = cur.fetchone()[0]
            self.conn.commit()

            if result.get("error"):
                logger.warning(f"Decision failed for {request_id}: {result['error']}")
                return DecisionResult(
                    success=False,
                    request_id=request_id,
                    decision=decision,
                    current_approvals=result.get("current_approvals", 0),
                    required_approvals=result.get("required_approvals", 0),
                    is_complete=False,
                    error=result["error"]
                )

            logger.info(
                f"Decision recorded for {request_id}: {decision} by {user_email}, "
                f"complete={result.get('is_complete')}"
            )

            # If approved and complete, fetch action payload
            action_payload = None
            if result.get("is_complete") and result.get("final_status") == "APPROVED":
                req = await self.get_request(request_id)
                if req:
                    with self.conn.cursor(row_factory=dict_row) as cur2:
                        cur2.execute("""
                            SELECT action_payload FROM auth.approval_requests
                            WHERE id = %s
                        """, (str(request_id),))
                        row = cur2.fetchone()
                        if row:
                            action_payload = row["action_payload"]

            return DecisionResult(
                success=True,
                request_id=request_id,
                decision=decision,
                current_approvals=result.get("current_approvals", 0),
                required_approvals=result.get("required_approvals", 0),
                is_complete=result.get("is_complete", False),
                final_status=result.get("final_status"),
                action_payload=action_payload
            )

    async def emergency_override(
        self,
        request_id: UUID,
        user_id: UUID,
        user_email: str,
        justification: str
    ) -> DecisionResult:
        """
        Execute emergency override with mandatory review queue.

        Args:
            request_id: Request UUID
            user_id: Approver user UUID
            user_email: Approver email
            justification: Required justification text

        Returns:
            DecisionResult with action payload to execute
        """
        if not justification or len(justification.strip()) < 10:
            return DecisionResult(
                success=False,
                request_id=request_id,
                decision="EMERGENCY_OVERRIDE",
                current_approvals=0,
                required_approvals=0,
                is_complete=False,
                error="Justification required (minimum 10 characters)"
            )

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT auth.execute_emergency_override(
                    %s, %s, %s, %s
                )
            """, (
                str(request_id),
                str(user_id),
                user_email,
                justification
            ))

            result = cur.fetchone()[0]
            self.conn.commit()

            if result.get("error"):
                logger.warning(f"Emergency override failed for {request_id}: {result['error']}")
                return DecisionResult(
                    success=False,
                    request_id=request_id,
                    decision="EMERGENCY_OVERRIDE",
                    current_approvals=0,
                    required_approvals=0,
                    is_complete=False,
                    error=result["error"]
                )

            logger.warning(
                f"EMERGENCY OVERRIDE executed for {request_id} by {user_email}, "
                f"review due: {result.get('review_due_at')}"
            )

            return DecisionResult(
                success=True,
                request_id=request_id,
                decision="EMERGENCY_OVERRIDE",
                current_approvals=1,
                required_approvals=1,
                is_complete=True,
                final_status="EMERGENCY_OVERRIDE",
                action_payload=result.get("action_payload")
            )

    async def get_pending_reviews(self) -> List[Dict[str, Any]]:
        """
        Get pending emergency override reviews.

        Returns:
            List of reviews needing attention
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT * FROM auth.get_emergency_reviews_pending(%s)
            """, (self.tenant_id,))

            rows = cur.fetchall()

            return [
                {
                    "review_id": row["review_id"],
                    "request_id": row["request_id"],
                    "override_by": row["override_by"],
                    "override_at": row["override_at"].isoformat() if row["override_at"] else None,
                    "action_type": row["action_type"],
                    "action_summary": row["action_summary"],
                    "justification": row["justification"],
                    "review_due_at": row["review_due_at"].isoformat() if row["review_due_at"] else None,
                    "is_overdue": row["is_overdue"]
                }
                for row in rows
            ]

    async def complete_review(
        self,
        review_id: UUID,
        reviewer_email: str,
        outcome: str,  # APPROPRIATE, NEEDS_FOLLOWUP, POLICY_VIOLATION
        notes: Optional[str] = None
    ) -> bool:
        """
        Complete an emergency override review.

        Args:
            review_id: Review UUID
            reviewer_email: Reviewer email
            outcome: Review outcome
            notes: Optional review notes

        Returns:
            True if successful
        """
        if outcome not in ("APPROPRIATE", "NEEDS_FOLLOWUP", "POLICY_VIOLATION"):
            return False

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                UPDATE auth.emergency_review_queue
                SET
                    review_status = CASE
                        WHEN %s = 'APPROPRIATE' THEN 'ACKNOWLEDGED'
                        WHEN %s = 'POLICY_VIOLATION' THEN 'FLAGGED'
                        ELSE 'ESCALATED'
                    END,
                    reviewed_at = NOW(),
                    reviewed_by = %s,
                    review_outcome = %s,
                    review_notes = %s
                WHERE id = %s AND tenant_id = %s
                RETURNING id
            """, (
                outcome, outcome,
                reviewer_email,
                outcome,
                notes,
                str(review_id),
                self.tenant_id
            ))

            result = cur.fetchone()
            self.conn.commit()

            if result:
                logger.info(
                    f"Emergency review {review_id} completed by {reviewer_email}: {outcome}"
                )
                return True

            return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def calculate_risk_context(
    affected_drivers: Optional[List] = None,
    near_rest_time_violations: Optional[List] = None,
    is_freeze_period: bool = False,
    hours_to_deadline: Optional[int] = None
) -> Dict[str, Any]:
    """
    Build risk context dictionary for assessment.

    Args:
        affected_drivers: List of affected driver IDs
        near_rest_time_violations: List of rest-time impacts
        is_freeze_period: Whether in freeze period
        hours_to_deadline: Hours until deadline

    Returns:
        Context dictionary for assess_action()
    """
    context = {}

    if affected_drivers:
        context["affected_drivers"] = len(affected_drivers)

    if near_rest_time_violations:
        context["near_rest_time"] = True

    if is_freeze_period:
        context["is_freeze_period"] = True

    if hours_to_deadline is not None and hours_to_deadline < 4:
        context["near_deadline"] = True

    return context
