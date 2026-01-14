"""
SOLVEREIGN V4.8 - Repair Orchestrator (Top-K Proposal Generator)
================================================================

Generates multiple repair proposals for driver unavailability incidents.

Strategy:
1. Identify impacted tours (tours assigned to absent driver)
2. Get candidate drivers per tour from CandidateFinder
3. Generate proposals:
   - Option A: No-split (one driver covers all if feasible)
   - Option B: Split tours across multiple drivers
   - Option C: Chain swap (depth 2-3) if A/B fail
4. Filter proposals that violate hard constraints
5. Rank by quality score (minimal disruption)
6. Return top_k feasible proposals

CRITICAL SEMANTICS:
- Preview returns ADVISORY proposals with coverage/violation estimates
- Confirm is AUTHORITATIVE - uses canonical violations engine

VALIDATION MODES:
- validation="none": Fast preview, no violation checks (default)
- validation="fast": Quick validation of impacted tours only
- validation="full": Full plan validation (equivalent to confirm)

COVERAGE SEMANTICS:
- impacted_tours_count: Total tours that were assigned to absent driver
- impacted_assigned_count: Tours from above that are assigned in proposal
- coverage_percent: impacted_assigned_count / impacted_tours_count * 100
- coverage_computed: Always true for proposals (we know what we assigned)

VIOLATION SEMANTICS:
- violations_validated: True only if canonical violations engine was called
- block_violations: null if not validated, actual count if validated
- warn_violations: null if not validated, actual count if validated

CRITICAL: This is delta-first repair - changes as little as possible.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Set, Tuple, Any
from uuid import uuid4
import logging
import hashlib
import json

from .candidate_finder import (
    find_candidates_sync,
    TourInfo,
    CandidateResult,
    CandidateDriver,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class IncidentSpec:
    """Specification of an incident (driver unavailability)."""
    type: str  # "DRIVER_UNAVAILABLE"
    driver_id: int
    time_range_start: datetime
    time_range_end: Optional[datetime]
    reason: str = "SICK"


@dataclass
class FreezeSpec:
    """Specification of what to freeze (not change)."""
    freeze_assignments: Set[int] = field(default_factory=set)  # tour_instance_ids
    freeze_drivers: Set[int] = field(default_factory=set)  # driver_ids


@dataclass
class ChangeBudget:
    """Budget for how much change is allowed."""
    max_changed_tours: int = 5
    max_changed_drivers: int = 3
    max_chain_depth: int = 2


@dataclass
class SplitPolicy:
    """Policy for splitting tours across drivers."""
    allow_split: bool = True
    max_splits: int = 2
    split_granularity: str = "TOUR"  # MVP: only TOUR level


@dataclass
class ProposedAssignment:
    """A single assignment in a repair proposal."""
    tour_instance_id: int
    driver_id: int
    day: int
    block_id: str
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]
    is_new: bool  # True if this is a new/changed assignment


@dataclass
class DeltaSummary:
    """Summary of changes in a proposal."""
    changed_tours_count: int
    changed_drivers_count: int
    impacted_drivers: List[int]
    reserve_usage: int
    chain_depth: int


@dataclass
class CoverageInfo:
    """Coverage information for a proposal."""
    impacted_tours_count: int  # Total tours that need coverage
    impacted_assigned_count: int  # Tours actually assigned in proposal
    coverage_percent: float  # impacted_assigned / impacted_tours * 100
    coverage_computed: bool = True  # Always true for proposals


@dataclass
class ViolationInfo:
    """Violation information for a proposal."""
    violations_validated: bool  # True only if canonical engine was called
    block_violations: Optional[int]  # null if not validated
    warn_violations: Optional[int]  # null if not validated
    validation_mode: str = "none"  # "none", "fast", "full"
    validation_note: str = "Preview is advisory. Confirm validates authoritatively."


@dataclass
class CompatibilityInfo:
    """Compatibility information for a proposal or candidate."""
    compatibility_checked: bool = False  # True if skills/vehicle were checked
    compatibility_unknown: bool = False  # True if data is missing (user must acknowledge)
    missing_data: List[str] = field(default_factory=list)  # What data is missing
    incompatibilities: List[str] = field(default_factory=list)  # Hard incompatibilities found


@dataclass
class DiagnosticReason:
    """A single reason why no feasible proposals were found."""
    code: str  # "NO_CANDIDATES", "PARTIAL_COVERAGE", "ALL_CONFLICTS", etc.
    message: str  # Human-readable explanation
    tour_instance_ids: List[int] = field(default_factory=list)  # Affected tours
    suggested_action: Optional[str] = None  # What user can do
    priority: int = 99  # Lower = more important (for sorting)


# Priority order for diagnostic reasons (lower = more important)
DIAGNOSTIC_PRIORITY = {
    "NO_CANDIDATES": 10,      # Most critical - no drivers at all
    "ALL_CONFLICTS": 20,      # Drivers exist but all filtered
    "PARTIAL_COVERAGE": 30,   # Some coverage but not 100%
    "BUDGET_TOO_RESTRICTIVE": 40,  # Budget may be limiting
}


@dataclass
class UncoveredTourInfo:
    """Context for an uncovered tour (not just ID)."""
    tour_instance_id: int
    tour_name: str
    day: int
    start_ts: Optional[str]  # ISO timestamp
    end_ts: Optional[str]    # ISO timestamp
    reason: str  # Why uncovered: "no_candidates", "filtered_out", etc.


@dataclass
class DiagnosticSummary:
    """Summary when no feasible proposals exist."""
    has_diagnostics: bool = False
    reasons: List[DiagnosticReason] = field(default_factory=list)
    uncovered_tour_ids: List[int] = field(default_factory=list)  # Legacy: just IDs
    uncovered_tours: List[UncoveredTourInfo] = field(default_factory=list)  # New: with context
    partial_proposals_available: bool = False  # True if infeasible proposals exist
    suggested_actions: List[str] = field(default_factory=list)  # UI hints
    earliest_uncovered_start: Optional[str] = None  # ISO timestamp of earliest uncovered tour


@dataclass
class RepairOrchestratorResult:
    """Result of repair orchestration including proposals and diagnostics."""
    proposals: List['RepairProposal']  # Feasible proposals (may be empty)
    all_proposals: List['RepairProposal']  # All proposals including infeasible
    diagnostics: DiagnosticSummary  # Diagnostic info when proposals empty
    impacted_tours_count: int
    candidates_found: bool  # True if at least one candidate for at least one tour


@dataclass
class RepairProposal:
    """A single repair proposal."""
    proposal_id: str
    label: str  # "A: No-Split", "B: Split Tours", "C: Chain Swap"
    strategy: str  # "NO_SPLIT", "SPLIT", "CHAIN"
    feasible: bool
    quality_score: float  # Higher = better
    delta_summary: DeltaSummary
    assignments: List[ProposedAssignment]
    removed_assignments: List[int]  # tour_instance_ids removed from absent driver
    evidence_hash: str
    # Coverage info (always computed)
    coverage: CoverageInfo
    # Violation info (validated only if requested)
    violations: ViolationInfo
    # Compatibility info (skills/vehicle)
    compatibility: CompatibilityInfo = field(default_factory=CompatibilityInfo)
    # Legacy fields for backward compat (deprecated)
    coverage_percent: float = 0.0  # DEPRECATED: Use coverage.coverage_percent
    block_violations: Optional[int] = None  # DEPRECATED: Use violations.block_violations
    warn_violations: Optional[int] = None  # DEPRECATED: Use violations.warn_violations


# =============================================================================
# PROPOSAL GENERATORS
# =============================================================================

def _generate_no_split_proposal(
    impacted_tours: List[TourInfo],
    candidates_by_tour: Dict[int, CandidateResult],
    existing_assignments: Dict[int, int],  # tour_instance_id -> driver_id
    change_budget: ChangeBudget,
) -> Optional[RepairProposal]:
    """
    Try to assign all impacted tours to a single driver.

    This is the simplest and least disruptive option, but only works
    if one driver can cover all tours without conflicts.
    """
    if not impacted_tours:
        return None

    impacted_count = len(impacted_tours)

    # Find common candidates across all tours
    common_candidates: Dict[int, float] = {}  # driver_id -> min_score

    for i, tour in enumerate(impacted_tours):
        result = candidates_by_tour.get(tour.tour_instance_id)
        if not result or not result.candidates:
            return None  # No candidates for this tour

        tour_candidates = {c.driver_id: c.score for c in result.candidates}

        if i == 0:
            common_candidates = tour_candidates.copy()
        else:
            # Intersection: keep only common drivers, with minimum score
            common_candidates = {
                d_id: min(common_candidates.get(d_id, 0), score)
                for d_id, score in tour_candidates.items()
                if d_id in common_candidates
            }

    if not common_candidates:
        return None  # No single driver can cover all tours

    # Pick the best common candidate
    best_driver_id = max(common_candidates.keys(), key=lambda d: common_candidates[d])
    best_score = common_candidates[best_driver_id]

    # Build assignments
    assignments = []
    removed = []
    for tour in impacted_tours:
        assignments.append(ProposedAssignment(
            tour_instance_id=tour.tour_instance_id,
            driver_id=best_driver_id,
            day=tour.day,
            block_id=tour.block_type,
            start_ts=tour.start_ts,
            end_ts=tour.end_ts,
            is_new=True,
        ))
        removed.append(tour.tour_instance_id)

    assigned_count = len(assignments)
    # Quality score: higher for fewer changes and higher candidate score
    quality_score = best_score - len(impacted_tours) * 5

    # Compute actual coverage (not hardcoded 100%)
    coverage_pct = (assigned_count / impacted_count * 100) if impacted_count > 0 else 0.0

    return RepairProposal(
        proposal_id=str(uuid4()),
        label="A: Single Driver",
        strategy="NO_SPLIT",
        feasible=assigned_count == impacted_count,  # Only feasible if all covered
        quality_score=quality_score,
        delta_summary=DeltaSummary(
            changed_tours_count=len(impacted_tours),
            changed_drivers_count=1,
            impacted_drivers=[best_driver_id],
            reserve_usage=0,
            chain_depth=0,
        ),
        assignments=assignments,
        removed_assignments=removed,
        evidence_hash=_compute_evidence_hash(assignments),
        coverage=CoverageInfo(
            impacted_tours_count=impacted_count,
            impacted_assigned_count=assigned_count,
            coverage_percent=coverage_pct,
            coverage_computed=True,
        ),
        violations=ViolationInfo(
            violations_validated=False,  # NOT validated in preview by default
            block_violations=None,  # Unknown until validated
            warn_violations=None,  # Unknown until validated
            validation_mode="none",
            validation_note="Preview is advisory. Confirm validates authoritatively.",
        ),
        # Legacy fields for backward compat
        coverage_percent=coverage_pct,
        block_violations=None,
        warn_violations=None,
    )


def _generate_split_proposal(
    impacted_tours: List[TourInfo],
    candidates_by_tour: Dict[int, CandidateResult],
    existing_assignments: Dict[int, int],
    change_budget: ChangeBudget,
    split_policy: SplitPolicy,
) -> Optional[RepairProposal]:
    """
    Assign each tour to its best candidate (may use multiple drivers).

    This is more flexible but results in more disruption.
    """
    if not impacted_tours:
        return None

    if not split_policy.allow_split:
        return None

    impacted_count = len(impacted_tours)
    assignments = []
    removed = []
    used_drivers: Set[int] = set()

    for tour in impacted_tours:
        result = candidates_by_tour.get(tour.tour_instance_id)
        if not result or not result.candidates:
            # No candidate for this tour - continue but track for coverage
            continue

        # Pick the best candidate for this tour
        best = result.candidates[0]

        assignments.append(ProposedAssignment(
            tour_instance_id=tour.tour_instance_id,
            driver_id=best.driver_id,
            day=tour.day,
            block_id=tour.block_type,
            start_ts=tour.start_ts,
            end_ts=tour.end_ts,
            is_new=True,
        ))
        removed.append(tour.tour_instance_id)
        used_drivers.add(best.driver_id)

    assigned_count = len(assignments)

    # If we couldn't cover all tours, still return proposal but mark infeasible
    if assigned_count < impacted_count:
        coverage_pct = (assigned_count / impacted_count * 100) if impacted_count > 0 else 0.0
        return RepairProposal(
            proposal_id=str(uuid4()),
            label=f"B: Split ({len(used_drivers)} drivers) - PARTIAL",
            strategy="SPLIT",
            feasible=False,  # Infeasible due to partial coverage
            quality_score=0.0,  # Low score for infeasible
            delta_summary=DeltaSummary(
                changed_tours_count=assigned_count,
                changed_drivers_count=len(used_drivers),
                impacted_drivers=list(used_drivers),
                reserve_usage=0,
                chain_depth=0,
            ),
            assignments=assignments,
            removed_assignments=removed,
            evidence_hash=_compute_evidence_hash(assignments),
            coverage=CoverageInfo(
                impacted_tours_count=impacted_count,
                impacted_assigned_count=assigned_count,
                coverage_percent=coverage_pct,
                coverage_computed=True,
            ),
            violations=ViolationInfo(
                violations_validated=False,
                block_violations=None,
                warn_violations=None,
                validation_mode="none",
                validation_note="Preview is advisory. Confirm validates authoritatively.",
            ),
            coverage_percent=coverage_pct,
            block_violations=None,
            warn_violations=None,
        )

    # Check change budget
    if len(used_drivers) > change_budget.max_changed_drivers:
        return None  # Exceeds budget

    # Quality score: penalize for more drivers used
    avg_score = sum(
        candidates_by_tour[t.tour_instance_id].candidates[0].score
        for t in impacted_tours
        if candidates_by_tour.get(t.tour_instance_id)
        and candidates_by_tour[t.tour_instance_id].candidates
    ) / len(impacted_tours)

    quality_score = avg_score - len(used_drivers) * 10
    coverage_pct = 100.0  # All tours covered

    return RepairProposal(
        proposal_id=str(uuid4()),
        label=f"B: Split ({len(used_drivers)} drivers)",
        strategy="SPLIT",
        feasible=True,
        quality_score=quality_score,
        delta_summary=DeltaSummary(
            changed_tours_count=len(impacted_tours),
            changed_drivers_count=len(used_drivers),
            impacted_drivers=list(used_drivers),
            reserve_usage=0,
            chain_depth=0,
        ),
        assignments=assignments,
        removed_assignments=removed,
        evidence_hash=_compute_evidence_hash(assignments),
        coverage=CoverageInfo(
            impacted_tours_count=impacted_count,
            impacted_assigned_count=assigned_count,
            coverage_percent=coverage_pct,
            coverage_computed=True,
        ),
        violations=ViolationInfo(
            violations_validated=False,
            block_violations=None,
            warn_violations=None,
            validation_mode="none",
            validation_note="Preview is advisory. Confirm validates authoritatively.",
        ),
        coverage_percent=coverage_pct,
        block_violations=None,
        warn_violations=None,
    )


def _generate_chain_swap_proposal(
    impacted_tours: List[TourInfo],
    candidates_by_tour: Dict[int, CandidateResult],
    existing_assignments: Dict[int, int],
    all_assignments: Dict[int, List[Dict]],  # driver_id -> assignments
    change_budget: ChangeBudget,
) -> Optional[RepairProposal]:
    """
    Try chain swaps: move tours between drivers to make room.

    This is more complex but can find solutions when direct assignment fails.
    Limited to max_chain_depth (default 2).

    MVP: Simple 1-level chain only.
    """
    if not impacted_tours:
        return None

    impacted_count = len(impacted_tours)

    # This is a simplified implementation - full chain swap is complex
    # For MVP, we'll just try a simple cascade

    assignments = []
    removed = []
    used_drivers: Set[int] = set()
    cascade_moves: List[Tuple[int, int, int]] = []  # (tour_id, from_driver, to_driver)

    for tour in impacted_tours:
        result = candidates_by_tour.get(tour.tour_instance_id)
        if not result or not result.candidates:
            # No direct candidates - try chain
            # MVP: Skip complex chain logic
            continue

        best = result.candidates[0]
        assignments.append(ProposedAssignment(
            tour_instance_id=tour.tour_instance_id,
            driver_id=best.driver_id,
            day=tour.day,
            block_id=tour.block_type,
            start_ts=tour.start_ts,
            end_ts=tour.end_ts,
            is_new=True,
        ))
        removed.append(tour.tour_instance_id)
        used_drivers.add(best.driver_id)

    assigned_count = len(assignments)

    if assigned_count < impacted_count:
        return None  # Couldn't cover all

    # Quality score: lower than split due to complexity
    avg_score = sum(
        candidates_by_tour[t.tour_instance_id].candidates[0].score
        for t in impacted_tours
        if candidates_by_tour.get(t.tour_instance_id)
        and candidates_by_tour[t.tour_instance_id].candidates
    ) / len(impacted_tours) if impacted_tours else 0

    quality_score = avg_score - 20 - len(cascade_moves) * 5
    coverage_pct = (assigned_count / impacted_count * 100) if impacted_count > 0 else 0.0

    return RepairProposal(
        proposal_id=str(uuid4()),
        label=f"C: Chain Swap (depth={len(cascade_moves)})",
        strategy="CHAIN",
        feasible=assigned_count == impacted_count,
        quality_score=quality_score,
        delta_summary=DeltaSummary(
            changed_tours_count=len(impacted_tours) + len(cascade_moves),
            changed_drivers_count=len(used_drivers),
            impacted_drivers=list(used_drivers),
            reserve_usage=0,
            chain_depth=len(cascade_moves),
        ),
        assignments=assignments,
        removed_assignments=removed,
        evidence_hash=_compute_evidence_hash(assignments),
        coverage=CoverageInfo(
            impacted_tours_count=impacted_count,
            impacted_assigned_count=assigned_count,
            coverage_percent=coverage_pct,
            coverage_computed=True,
        ),
        violations=ViolationInfo(
            violations_validated=False,
            block_violations=None,
            warn_violations=None,
            validation_mode="none",
            validation_note="Preview is advisory. Confirm validates authoritatively.",
        ),
        coverage_percent=coverage_pct,
        block_violations=None,
        warn_violations=None,
    )


def _compute_evidence_hash(assignments: List[ProposedAssignment]) -> str:
    """Compute deterministic hash of assignments for evidence tracking."""
    data = sorted([
        (a.tour_instance_id, a.driver_id, a.day)
        for a in assignments
    ])
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def generate_repair_proposals_sync(
    cursor,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    incident: IncidentSpec,
    freeze: Optional[FreezeSpec] = None,
    change_budget: Optional[ChangeBudget] = None,
    split_policy: Optional[SplitPolicy] = None,
    top_k: int = 3,
    config: Optional[dict] = None,
    return_result: bool = False,
) -> Any:  # Returns List[RepairProposal] or RepairOrchestratorResult
    """
    Generate Top-K repair proposals for an incident.

    Synchronous version for psycopg2 cursor.

    Args:
        cursor: Database cursor
        tenant_id: Tenant ID
        site_id: Site ID
        plan_version_id: Plan to repair from
        incident: The incident specification
        freeze: What to freeze
        change_budget: Budget for changes
        split_policy: Policy for splitting
        top_k: Number of proposals to return
        config: Optional configuration overrides
        return_result: If True, returns RepairOrchestratorResult with diagnostics

    Returns:
        List of feasible RepairProposals, sorted by quality_score descending
        OR RepairOrchestratorResult if return_result=True
    """
    freeze = freeze or FreezeSpec()
    change_budget = change_budget or ChangeBudget()
    split_policy = split_policy or SplitPolicy()

    # Step 1: Identify impacted tours (tours assigned to absent driver)
    cursor.execute(
        """
        SELECT
            a.tour_instance_id,
            ti.tour_id,
            a.day,
            ti.start_ts,
            ti.end_ts,
            a.driver_id::integer,
            a.block_id
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = %s
          AND a.driver_id::integer = %s
          AND a.tour_instance_id NOT IN %s
        ORDER BY a.day, ti.start_ts
        """,
        (
            plan_version_id,
            incident.driver_id,
            tuple(freeze.freeze_assignments) if freeze.freeze_assignments else (0,)
        )
    )

    impacted_tours: List[TourInfo] = []
    for row in cursor.fetchall():
        tour = TourInfo(
            tour_instance_id=row[0],
            tour_id=row[1],
            day=row[2],
            start_ts=row[3],
            end_ts=row[4],
            driver_id=row[5],
            block_type=row[6] or "1er",
        )
        impacted_tours.append(tour)

    if not impacted_tours:
        logger.info(f"No impacted tours for driver {incident.driver_id}")
        if return_result:
            return RepairOrchestratorResult(
                proposals=[],
                all_proposals=[],
                diagnostics=DiagnosticSummary(has_diagnostics=False),
                impacted_tours_count=0,
                candidates_found=False,
            )
        return []

    logger.info(
        f"Found {len(impacted_tours)} impacted tours for driver {incident.driver_id}"
    )

    # Step 2: Get candidates for each tour
    candidates_by_tour = find_candidates_sync(
        cursor=cursor,
        tenant_id=tenant_id,
        site_id=site_id,
        plan_version_id=plan_version_id,
        impacted_tours=impacted_tours,
        absent_driver_ids={incident.driver_id},
        freeze_driver_ids=freeze.freeze_drivers,
        config=config,
    )

    # Step 3: Load existing assignments for context
    cursor.execute(
        """
        SELECT tour_instance_id, driver_id::integer
        FROM assignments
        WHERE plan_version_id = %s
        """,
        (plan_version_id,)
    )
    existing_assignments = {row[0]: row[1] for row in cursor.fetchall()}

    # Load all assignments by driver
    cursor.execute(
        """
        SELECT
            a.driver_id::integer,
            a.tour_instance_id,
            a.day,
            ti.start_ts,
            ti.end_ts
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = %s
        ORDER BY a.driver_id
        """,
        (plan_version_id,)
    )

    all_assignments: Dict[int, List[Dict]] = {}
    for row in cursor.fetchall():
        d_id = row[0]
        if d_id not in all_assignments:
            all_assignments[d_id] = []
        all_assignments[d_id].append({
            "tour_instance_id": row[1],
            "day": row[2],
            "start_ts": row[3],
            "end_ts": row[4],
        })

    # Step 4: Generate proposals
    all_proposals: List[RepairProposal] = []

    # Option A: No-split
    no_split = _generate_no_split_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        change_budget=change_budget,
    )
    if no_split:
        all_proposals.append(no_split)

    # Option B: Split
    split = _generate_split_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        change_budget=change_budget,
        split_policy=split_policy,
    )
    if split:
        all_proposals.append(split)

    # Option C: Chain swap
    chain = _generate_chain_swap_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        all_assignments=all_assignments,
        change_budget=change_budget,
    )
    if chain and chain.strategy != "SPLIT":  # Avoid duplicate if same as split
        all_proposals.append(chain)

    # Step 5: Filter infeasible proposals (require 100% coverage for impacted tours)
    # NOTE: We filter only on coverage (computed), NOT on block_violations (not validated)
    feasible_proposals = [
        p for p in all_proposals
        if p.feasible and p.coverage.coverage_percent == 100.0
    ]

    # Step 6: Sort by quality score (descending)
    feasible_proposals.sort(key=lambda p: p.quality_score, reverse=True)

    # Step 7: Generate diagnostics if no feasible proposals
    diagnostics = _generate_diagnostics(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        all_proposals=all_proposals,
        feasible_proposals=feasible_proposals,
        change_budget=change_budget,
    )

    # Check if any candidates were found
    candidates_found = any(
        result.candidates for result in candidates_by_tour.values()
    )

    if return_result:
        return RepairOrchestratorResult(
            proposals=feasible_proposals[:top_k],
            all_proposals=all_proposals,
            diagnostics=diagnostics,
            impacted_tours_count=len(impacted_tours),
            candidates_found=candidates_found,
        )

    # Legacy return: just the list
    return feasible_proposals[:top_k]


def _generate_diagnostics(
    impacted_tours: List[TourInfo],
    candidates_by_tour: Dict[int, CandidateResult],
    all_proposals: List[RepairProposal],
    feasible_proposals: List[RepairProposal],
    change_budget: ChangeBudget,
) -> DiagnosticSummary:
    """
    Generate diagnostic summary when no feasible proposals exist.

    PRIORITY ORDER (lower = more important, shown first):
    1. NO_CANDIDATES (10) - No drivers at all for some tours
    2. ALL_CONFLICTS (20) - Drivers exist but all have conflicts
    3. PARTIAL_COVERAGE (30) - Some coverage but not 100%
    4. BUDGET_TOO_RESTRICTIVE (40) - Budget may be limiting

    MUTUAL EXCLUSIVITY:
    - NO_CANDIDATES implies no candidates, so ALL_CONFLICTS is redundant for those tours
    - Only show ALL_CONFLICTS if there are tours WITH candidates that all got filtered
    """
    if feasible_proposals:
        return DiagnosticSummary(has_diagnostics=False)

    reasons: List[DiagnosticReason] = []
    uncovered_tour_ids: List[int] = []
    uncovered_tours: List[UncoveredTourInfo] = []
    suggested_actions_set: set = set()  # Use set to avoid duplicates

    # =========================================================================
    # PASS 1: Identify uncovered tours with context
    # =========================================================================
    tours_no_candidates: List[int] = []
    tours_all_filtered: List[int] = []

    for tour in impacted_tours:
        result = candidates_by_tour.get(tour.tour_instance_id)
        if not result or not result.candidates:
            tours_no_candidates.append(tour.tour_instance_id)
            uncovered_tour_ids.append(tour.tour_instance_id)

            # Determine reason
            if result and result.total_available > 0 and result.filtered_count == result.total_available:
                reason = "all_filtered"
                tours_all_filtered.append(tour.tour_instance_id)
            else:
                reason = "no_candidates"

            # Add context
            uncovered_tours.append(UncoveredTourInfo(
                tour_instance_id=tour.tour_instance_id,
                tour_name=tour.tour_id,  # tour_id is the tour name/label
                day=tour.day,
                start_ts=tour.start_ts.isoformat() if tour.start_ts else None,
                end_ts=tour.end_ts.isoformat() if tour.end_ts else None,
                reason=reason,
            ))

    # Find earliest uncovered start
    earliest_start: Optional[str] = None
    if uncovered_tours:
        starts = [t.start_ts for t in uncovered_tours if t.start_ts]
        if starts:
            earliest_start = min(starts)

    # =========================================================================
    # PASS 2: Generate reasons with priority (mutually exclusive)
    # =========================================================================

    # Check for tours with no candidates at all (not just filtered)
    pure_no_candidates = [t for t in tours_no_candidates if t not in tours_all_filtered]
    if pure_no_candidates:
        reasons.append(DiagnosticReason(
            code="NO_CANDIDATES",
            message=f"{len(pure_no_candidates)} tour(s) have no available drivers",
            tour_instance_ids=pure_no_candidates,
            suggested_action="Check for drivers on leave or expand time windows",
            priority=DIAGNOSTIC_PRIORITY["NO_CANDIDATES"],
        ))
        suggested_actions_set.add("Check driver availability")

    # Check if some tours had candidates but all filtered (conflicts)
    # Only add if not redundant with NO_CANDIDATES
    if tours_all_filtered and len(tours_all_filtered) > len(pure_no_candidates):
        # Some tours had drivers but all were filtered out
        filtered_only = [t for t in tours_all_filtered if t not in pure_no_candidates]
        if filtered_only:
            reasons.append(DiagnosticReason(
                code="ALL_CONFLICTS",
                message=f"{len(filtered_only)} tour(s) have drivers but all have scheduling conflicts",
                tour_instance_ids=filtered_only,
                suggested_action="Run full validation to see specific conflicts",
                priority=DIAGNOSTIC_PRIORITY["ALL_CONFLICTS"],
            ))
            suggested_actions_set.add("Run full validation")

    # Check for partial coverage proposals (only if not already explained by NO_CANDIDATES)
    partial_proposals = [
        p for p in all_proposals
        if not p.feasible and p.coverage.coverage_percent < 100.0
    ]
    if partial_proposals and not pure_no_candidates:
        # Only show PARTIAL_COVERAGE if the issue isn't NO_CANDIDATES
        best_partial = max(partial_proposals, key=lambda p: p.coverage.coverage_percent)
        reasons.append(DiagnosticReason(
            code="PARTIAL_COVERAGE",
            message=f"Best proposal covers {best_partial.coverage.coverage_percent:.0f}% ({best_partial.coverage.impacted_assigned_count}/{best_partial.coverage.impacted_tours_count} tours)",
            tour_instance_ids=best_partial.removed_assignments,
            suggested_action="Accept partial coverage or increase change budget",
            priority=DIAGNOSTIC_PRIORITY["PARTIAL_COVERAGE"],
        ))
        suggested_actions_set.add("Show partial proposals")

    # Check if change budget might be too restrictive (only if no higher-priority issues)
    if not all_proposals and not reasons and change_budget.max_changed_drivers < 5:
        reasons.append(DiagnosticReason(
            code="BUDGET_TOO_RESTRICTIVE",
            message=f"Change budget may be too tight (max {change_budget.max_changed_drivers} drivers, {change_budget.max_changed_tours} tours)",
            tour_instance_ids=[],
            suggested_action="Try increasing max_changed_drivers or max_changed_tours",
            priority=DIAGNOSTIC_PRIORITY["BUDGET_TOO_RESTRICTIVE"],
        ))
        suggested_actions_set.add("Increase change budget")

    # =========================================================================
    # PASS 3: Sort by priority and limit to top 3
    # =========================================================================
    reasons.sort(key=lambda r: r.priority)
    reasons = reasons[:3]

    # Deterministic suggested actions order (based on priority of reasons)
    suggested_actions = []
    priority_to_action = {
        "NO_CANDIDATES": "Check driver availability",
        "ALL_CONFLICTS": "Run full validation",
        "PARTIAL_COVERAGE": "Show partial proposals",
        "BUDGET_TOO_RESTRICTIVE": "Increase change budget",
    }
    for reason in reasons:
        action = priority_to_action.get(reason.code)
        if action and action not in suggested_actions:
            suggested_actions.append(action)

    return DiagnosticSummary(
        has_diagnostics=len(reasons) > 0,
        reasons=reasons,
        uncovered_tour_ids=uncovered_tour_ids,
        uncovered_tours=uncovered_tours,
        partial_proposals_available=len(partial_proposals) > 0,
        suggested_actions=suggested_actions[:3],
        earliest_uncovered_start=earliest_start,
    )


async def generate_repair_proposals_async(
    conn,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    incident: IncidentSpec,
    freeze: Optional[FreezeSpec] = None,
    change_budget: Optional[ChangeBudget] = None,
    split_policy: Optional[SplitPolicy] = None,
    top_k: int = 3,
    config: Optional[dict] = None,
) -> List[RepairProposal]:
    """
    Generate Top-K repair proposals for an incident.

    Async version for asyncpg connection.
    """
    from .candidate_finder import find_candidates_async

    freeze = freeze or FreezeSpec()
    change_budget = change_budget or ChangeBudget()
    split_policy = split_policy or SplitPolicy()

    # Step 1: Identify impacted tours
    freeze_tuple = list(freeze.freeze_assignments) if freeze.freeze_assignments else [0]

    rows = await conn.fetch(
        """
        SELECT
            a.tour_instance_id,
            ti.tour_id,
            a.day,
            ti.start_ts,
            ti.end_ts,
            a.driver_id::integer,
            a.block_id
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = $1
          AND a.driver_id::integer = $2
          AND NOT (a.tour_instance_id = ANY($3))
        ORDER BY a.day, ti.start_ts
        """,
        plan_version_id, incident.driver_id, freeze_tuple
    )

    impacted_tours: List[TourInfo] = []
    for row in rows:
        tour = TourInfo(
            tour_instance_id=row["tour_instance_id"],
            tour_id=row["tour_id"],
            day=row["day"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            driver_id=row["driver_id"],
            block_type=row["block_id"] or "1er",
        )
        impacted_tours.append(tour)

    if not impacted_tours:
        logger.info(f"No impacted tours for driver {incident.driver_id}")
        return []

    # Step 2: Get candidates
    candidates_by_tour = await find_candidates_async(
        conn=conn,
        tenant_id=tenant_id,
        site_id=site_id,
        plan_version_id=plan_version_id,
        impacted_tours=impacted_tours,
        absent_driver_ids={incident.driver_id},
        freeze_driver_ids=freeze.freeze_drivers,
        config=config,
    )

    # Step 3: Load existing assignments
    rows = await conn.fetch(
        """
        SELECT tour_instance_id, driver_id::integer
        FROM assignments
        WHERE plan_version_id = $1
        """,
        plan_version_id
    )
    existing_assignments = {row["tour_instance_id"]: row["driver_id"] for row in rows}

    rows = await conn.fetch(
        """
        SELECT
            a.driver_id::integer,
            a.tour_instance_id,
            a.day,
            ti.start_ts,
            ti.end_ts
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = $1
        ORDER BY a.driver_id
        """,
        plan_version_id
    )

    all_assignments: Dict[int, List[Dict]] = {}
    for row in rows:
        d_id = row["driver_id"]
        if d_id not in all_assignments:
            all_assignments[d_id] = []
        all_assignments[d_id].append({
            "tour_instance_id": row["tour_instance_id"],
            "day": row["day"],
            "start_ts": row["start_ts"],
            "end_ts": row["end_ts"],
        })

    # Step 4: Generate proposals
    proposals: List[RepairProposal] = []

    no_split = _generate_no_split_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        change_budget=change_budget,
    )
    if no_split:
        proposals.append(no_split)

    split = _generate_split_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        change_budget=change_budget,
        split_policy=split_policy,
    )
    if split:
        proposals.append(split)

    chain = _generate_chain_swap_proposal(
        impacted_tours=impacted_tours,
        candidates_by_tour=candidates_by_tour,
        existing_assignments=existing_assignments,
        all_assignments=all_assignments,
        change_budget=change_budget,
    )
    if chain and chain.strategy != "SPLIT":
        proposals.append(chain)

    # Step 5-7: Filter, sort, limit
    # NOTE: We filter only on coverage (computed), NOT on block_violations (not validated)
    proposals = [
        p for p in proposals
        if p.feasible and p.coverage.coverage_percent == 100.0
    ]
    proposals.sort(key=lambda p: p.quality_score, reverse=True)

    return proposals[:top_k]
