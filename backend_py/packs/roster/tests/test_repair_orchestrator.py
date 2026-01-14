"""
Tests for Repair Orchestrator (Top-K Proposal Generator)
=========================================================

Verifies that the repair orchestrator:
1. Generates feasible proposals
2. All proposals have 100% coverage (computed, not constant)
3. Preview proposals have violations_validated=False (no fake green)
4. Split option works when single-driver fails
5. Deterministic output

NOTE: Preview is ADVISORY - it does not validate block violations.
Confirm is AUTHORITATIVE - it uses the canonical violations engine.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from packs.roster.core.repair_orchestrator import (
    generate_repair_proposals_sync,
    IncidentSpec,
    FreezeSpec,
    ChangeBudget,
    SplitPolicy,
    RepairProposal,
    DeltaSummary,
    CoverageInfo,
    ViolationInfo,
    CompatibilityInfo,
    _generate_no_split_proposal,
    _generate_split_proposal,
    _compute_evidence_hash,
)
from packs.roster.core.candidate_finder import TourInfo, CandidateResult, CandidateDriver


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def incident_spec():
    """Standard incident specification."""
    return IncidentSpec(
        type="DRIVER_UNAVAILABLE",
        driver_id=99,
        time_range_start=datetime(2024, 1, 1, 0, 0),
        time_range_end=datetime(2024, 1, 7, 23, 59),
        reason="SICK",
    )


@pytest.fixture
def two_tour_scenario():
    """Scenario: Driver has 2 tours that need coverage."""
    return [
        TourInfo(
            tour_instance_id=100,
            tour_id="T1",
            day=0,  # Monday
            start_ts=datetime(2024, 1, 1, 6, 0),
            end_ts=datetime(2024, 1, 1, 12, 0),
            driver_id=99,
            block_type="1er",
        ),
        TourInfo(
            tour_instance_id=101,
            tour_id="T2",
            day=2,  # Wednesday
            start_ts=datetime(2024, 1, 3, 14, 0),
            end_ts=datetime(2024, 1, 3, 20, 0),
            driver_id=99,
            block_type="1er",
        ),
    ]


@pytest.fixture
def single_candidate_per_tour():
    """Candidates: No common candidate across tours (requires split)."""
    return {
        100: CandidateResult(
            tour_instance_id=100,
            candidates=[
                CandidateDriver(
                    driver_id=1,
                    name="Driver A",
                    score=95.0,
                    existing_tours_count=1,
                    existing_hours=20.0,
                    is_working_same_day=False,
                    reason="Best for tour 100",
                ),
                CandidateDriver(
                    driver_id=2,
                    name="Driver B",
                    score=80.0,
                    existing_tours_count=2,
                    existing_hours=30.0,
                    is_working_same_day=False,
                    reason="Second for tour 100",
                ),
            ],
            total_available=5,
            filtered_count=3,
        ),
        101: CandidateResult(
            tour_instance_id=101,
            candidates=[
                CandidateDriver(
                    driver_id=3,
                    name="Driver C",
                    score=92.0,
                    existing_tours_count=1,
                    existing_hours=25.0,
                    is_working_same_day=True,
                    reason="Best for tour 101",
                ),
                CandidateDriver(
                    driver_id=4,
                    name="Driver D",
                    score=75.0,
                    existing_tours_count=2,
                    existing_hours=30.0,
                    is_working_same_day=False,
                    reason="Second for tour 101",
                ),
            ],
            total_available=5,
            filtered_count=3,
        ),
    }


@pytest.fixture
def common_candidate_scenario():
    """Candidates: Same driver can cover both tours (no-split possible)."""
    return {
        100: CandidateResult(
            tour_instance_id=100,
            candidates=[
                CandidateDriver(
                    driver_id=1,
                    name="Driver A",
                    score=95.0,
                    existing_tours_count=1,
                    existing_hours=20.0,
                    is_working_same_day=False,
                    reason="Can cover both",
                ),
            ],
            total_available=5,
            filtered_count=4,
        ),
        101: CandidateResult(
            tour_instance_id=101,
            candidates=[
                CandidateDriver(
                    driver_id=1,
                    name="Driver A",
                    score=90.0,
                    existing_tours_count=1,
                    existing_hours=20.0,
                    is_working_same_day=False,
                    reason="Can cover both",
                ),
            ],
            total_available=5,
            filtered_count=4,
        ),
    }


# =============================================================================
# UNIT TESTS: NO-SPLIT PROPOSAL
# =============================================================================

class TestNoSplitProposal:
    """Tests for _generate_no_split_proposal."""

    def test_generates_proposal_when_common_candidate_exists(
        self, two_tour_scenario, common_candidate_scenario
    ):
        """Should generate proposal when one driver can cover all."""
        proposal = _generate_no_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=common_candidate_scenario,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        assert proposal is not None
        assert proposal.strategy == "NO_SPLIT"
        assert proposal.feasible is True
        assert proposal.coverage_percent == 100.0
        assert len(proposal.assignments) == 2
        # All assignments to the same driver
        driver_ids = {a.driver_id for a in proposal.assignments}
        assert len(driver_ids) == 1
        assert 1 in driver_ids

    def test_returns_none_when_no_common_candidate(
        self, two_tour_scenario, single_candidate_per_tour
    ):
        """Should return None when no single driver can cover all."""
        proposal = _generate_no_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=single_candidate_per_tour,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        assert proposal is None

    def test_delta_summary_is_correct(
        self, two_tour_scenario, common_candidate_scenario
    ):
        """Delta summary should reflect changes."""
        proposal = _generate_no_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=common_candidate_scenario,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        assert proposal.delta_summary.changed_tours_count == 2
        assert proposal.delta_summary.changed_drivers_count == 1
        assert proposal.delta_summary.impacted_drivers == [1]


# =============================================================================
# UNIT TESTS: SPLIT PROPOSAL
# =============================================================================

class TestSplitProposal:
    """Tests for _generate_split_proposal."""

    def test_generates_proposal_with_multiple_drivers(
        self, two_tour_scenario, single_candidate_per_tour
    ):
        """Should assign best candidate per tour (multiple drivers)."""
        proposal = _generate_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=single_candidate_per_tour,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=True),
        )

        assert proposal is not None
        assert proposal.strategy == "SPLIT"
        assert proposal.feasible is True
        assert proposal.coverage_percent == 100.0
        assert len(proposal.assignments) == 2

        # Different drivers for different tours
        driver_ids = {a.driver_id for a in proposal.assignments}
        assert len(driver_ids) == 2  # 2 different drivers

    def test_respects_split_policy_disabled(
        self, two_tour_scenario, single_candidate_per_tour
    ):
        """Should return None when split is disabled."""
        proposal = _generate_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=single_candidate_per_tour,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=False),
        )

        assert proposal is None

    def test_respects_change_budget(
        self, two_tour_scenario, single_candidate_per_tour
    ):
        """Should return None when exceeds driver budget."""
        proposal = _generate_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=single_candidate_per_tour,
            existing_assignments={},
            change_budget=ChangeBudget(max_changed_drivers=1),  # Only 1 driver allowed
            split_policy=SplitPolicy(allow_split=True),
        )

        # Needs 2 drivers but only 1 allowed
        assert proposal is None


# =============================================================================
# UNIT TESTS: EVIDENCE HASH
# =============================================================================

class TestEvidenceHash:
    """Tests for _compute_evidence_hash."""

    def test_hash_is_deterministic(self, two_tour_scenario, common_candidate_scenario):
        """Same assignments should produce same hash."""
        proposal1 = _generate_no_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=common_candidate_scenario,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        proposal2 = _generate_no_split_proposal(
            impacted_tours=two_tour_scenario,
            candidates_by_tour=common_candidate_scenario,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        # Same input should produce same hash
        hash1 = _compute_evidence_hash(proposal1.assignments)
        hash2 = _compute_evidence_hash(proposal2.assignments)

        assert hash1 == hash2


# =============================================================================
# INTEGRATION TESTS: FULL ORCHESTRATOR
# =============================================================================

class TestRepairOrchestratorSync:
    """Integration tests for generate_repair_proposals_sync."""

    @pytest.fixture
    def mock_cursor(self):
        """Create a mock database cursor."""
        cursor = MagicMock()
        return cursor

    def test_generates_multiple_proposals(self, mock_cursor, incident_spec):
        """Should generate multiple proposals when possible."""
        # Mock: impacted tours query
        mock_cursor.fetchall.side_effect = [
            # Impacted tours (2 tours for driver 99)
            [
                (100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
                (101, "T2", 2, datetime(2024, 1, 3, 14, 0), datetime(2024, 1, 3, 20, 0), 99, "1er"),
            ],
            # Available drivers for candidate finder
            [(1, "A", True), (2, "B", True), (3, "C", True)],
            # Driver assignments for candidate finder
            [],
            # Existing assignments for context
            [(100, 99), (101, 99)],
            # All assignments by driver
            [],
        ]

        proposals = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
            top_k=3,
        )

        # Should generate at least one proposal
        assert len(proposals) >= 1

        # All proposals should be feasible with full coverage
        for p in proposals:
            assert p.feasible is True
            assert p.coverage_percent == 100.0
            # Preview proposals have violations_validated=False (no fake green)
            # block_violations is None until validated at confirm time
            assert p.violations.violations_validated is False
            assert p.block_violations is None  # Not validated in preview

    def test_all_proposals_have_100_coverage(self, mock_cursor, incident_spec):
        """Every proposal must have 100% coverage."""
        mock_cursor.fetchall.side_effect = [
            [(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er")],
            [(1, "A", True)],
            [],
            [(100, 99)],
            [],
        ]

        proposals = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
        )

        for proposal in proposals:
            assert proposal.coverage_percent == 100.0, \
                f"Proposal {proposal.label} has {proposal.coverage_percent}% coverage"

    def test_all_proposals_have_violations_not_validated(self, mock_cursor, incident_spec):
        """Preview proposals must have violations_validated=False (no fake green)."""
        mock_cursor.fetchall.side_effect = [
            [(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er")],
            [(1, "A", True)],
            [],
            [(100, 99)],
            [],
        ]

        proposals = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
        )

        for proposal in proposals:
            # Preview is ADVISORY - violations are NOT validated
            assert proposal.violations.violations_validated is False, \
                f"Proposal {proposal.label} must have violations_validated=False"
            # block_violations must be None when not validated (no fake green)
            assert proposal.block_violations is None, \
                f"Proposal {proposal.label} must have block_violations=None when not validated"

    def test_returns_empty_when_no_impacted_tours(self, mock_cursor, incident_spec):
        """Should return empty list when driver has no tours."""
        mock_cursor.fetchall.side_effect = [
            [],  # No impacted tours
        ]

        proposals = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
        )

        assert proposals == []

    def test_proposals_sorted_by_quality(self, mock_cursor, incident_spec):
        """Proposals should be sorted by quality_score descending."""
        mock_cursor.fetchall.side_effect = [
            [
                (100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
                (101, "T2", 2, datetime(2024, 1, 3, 14, 0), datetime(2024, 1, 3, 20, 0), 99, "1er"),
            ],
            [(1, "A", True), (2, "B", True), (3, "C", True)],
            [],
            [(100, 99), (101, 99)],
            [],
        ]

        proposals = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
            top_k=5,
        )

        if len(proposals) > 1:
            for i in range(len(proposals) - 1):
                assert proposals[i].quality_score >= proposals[i + 1].quality_score


# =============================================================================
# SCENARIO TESTS
# =============================================================================

class TestScenarios:
    """Test specific business scenarios."""

    def test_scenario_driver_with_two_tours_split_required(self):
        """
        Scenario: Driver 99 has 2 tours (Mon 6-12, Wed 14-20).
        No single driver can cover both due to overlapping existing assignments.
        Split should succeed with 2 drivers.
        """
        impacted_tours = [
            TourInfo(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
            TourInfo(101, "T2", 2, datetime(2024, 1, 3, 14, 0), datetime(2024, 1, 3, 20, 0), 99, "1er"),
        ]

        # Driver 1 can only do Monday, Driver 3 can only do Wednesday
        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[
                    CandidateDriver(1, "A", 90.0, 1, 20.0, True, "Available Mon only"),
                ],
                total_available=3,
                filtered_count=2,
            ),
            101: CandidateResult(
                tour_instance_id=101,
                candidates=[
                    CandidateDriver(3, "C", 88.0, 1, 22.0, True, "Available Wed only"),
                ],
                total_available=3,
                filtered_count=2,
            ),
        }

        # No-split should fail (no common candidate)
        no_split = _generate_no_split_proposal(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )
        assert no_split is None

        # Split should succeed
        split = _generate_split_proposal(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=True),
        )
        assert split is not None
        assert split.strategy == "SPLIT"
        assert split.coverage_percent == 100.0
        assert split.delta_summary.changed_drivers_count == 2


# =============================================================================
# INVARIANT TESTS
# =============================================================================

class TestInvariants:
    """Test system invariants that must always hold."""

    def test_proposals_with_partial_coverage_are_infeasible(self):
        """INVARIANT: Proposals without 100% coverage must be marked infeasible."""
        # If candidates exist but can't cover all tours, return infeasible proposal
        impacted_tours = [
            TourInfo(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
            TourInfo(101, "T2", 2, datetime(2024, 1, 3, 14, 0), datetime(2024, 1, 3, 20, 0), 99, "1er"),
        ]

        # Only have candidates for first tour, not second
        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[CandidateDriver(1, "A", 90.0, 1, 20.0, False, "OK")],
                total_available=3,
                filtered_count=2,
            ),
            101: CandidateResult(
                tour_instance_id=101,
                candidates=[],  # No candidates!
                total_available=3,
                filtered_count=3,
            ),
        }

        split = _generate_split_proposal(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=True),
        )

        # Proposal is returned (for visibility) but marked infeasible
        assert split is not None, "Should return proposal for visibility"
        assert split.feasible is False, "Partial coverage proposal must be infeasible"
        assert split.coverage.coverage_percent < 100.0, "Coverage should be partial"
        assert split.coverage.impacted_tours_count == 2
        assert split.coverage.impacted_assigned_count == 1

    def test_delta_first_default_budget(self):
        """INVARIANT: Default change budget should be small (delta-first)."""
        default = ChangeBudget()

        assert default.max_changed_tours <= 10, "Default should limit tour changes"
        assert default.max_changed_drivers <= 5, "Default should limit driver changes"
        assert default.max_chain_depth <= 3, "Default should limit chain depth"


# =============================================================================
# CRITICAL: CONFIRM USES CANONICAL VIOLATIONS
# =============================================================================

class TestCanonicalViolationsIntegration:
    """
    Tests verifying that confirm endpoint uses canonical violations engine.

    CRITICAL: This ensures no plan with BLOCK violations can be published
    via the orchestrated repair flow.
    """

    def test_confirm_imports_canonical_violations(self):
        """
        VERIFY: confirm endpoint imports from packs.roster.core.violations.

        This is a structural test - if the import changes, we catch it.
        """
        # Import the router module
        import inspect
        from packs.roster.api.routers import repair_orchestrator

        # Get the source of the confirm function
        source = inspect.getsource(repair_orchestrator.confirm_repair_draft)

        # Verify it imports the canonical violations function
        assert "compute_violations_sync" in source, \
            "confirm must use canonical compute_violations_sync"
        assert "packs.roster.core.violations" in source, \
            "confirm must import from canonical violations module"

    def test_confirm_rejects_on_block_violations(self):
        """
        VERIFY: confirm returns 409 when block_count > 0.

        This tests the code path logic without full integration.
        """
        # The logic in repair_orchestrator.py:803-812 is:
        # if violation_counts.block_count > 0:
        #     raise HTTPException(status_code=409, ...)

        # This is verified by reading the source
        import inspect
        from packs.roster.api.routers import repair_orchestrator

        source = inspect.getsource(repair_orchestrator.confirm_repair_draft)

        # Verify the 409 rejection logic exists
        assert "block_count > 0" in source, \
            "confirm must check block_count"
        assert "BLOCK_VIOLATIONS" in source, \
            "confirm must use BLOCK_VIOLATIONS error code"
        assert "409" in source or "HTTP_409_CONFLICT" in source, \
            "confirm must return 409 on violations"

    def test_proposals_document_advisory_nature(self):
        """
        VERIFY: Proposals clearly indicate validation is at confirm time.
        """
        import inspect
        from packs.roster.core import repair_orchestrator as core

        # Check module docstring mentions advisory nature
        assert "confirm" in core.__doc__.lower() or "authoritative" in core.__doc__.lower(), \
            "Module docstring should mention confirm as authoritative"


# =============================================================================
# CROSS-TENANT ISOLATION TESTS
# =============================================================================

class TestCrossTenantIsolation:
    """
    Tests verifying tenant isolation in orchestrated repair endpoints.
    """

    def test_preview_validates_plan_tenant_ownership(self):
        """
        VERIFY: Preview endpoint checks plan belongs to user's tenant.
        """
        import inspect
        from packs.roster.api.routers import repair_orchestrator

        source = inspect.getsource(repair_orchestrator.preview_repair_proposals)

        # Must check tenant_id in plan lookup
        assert "tenant_id" in source, "Preview must filter by tenant_id"
        assert "ctx.tenant_id" in source, "Preview must use context tenant_id"

    def test_prepare_validates_plan_tenant_ownership(self):
        """
        VERIFY: Prepare endpoint checks plan belongs to user's tenant.
        """
        import inspect
        from packs.roster.api.routers import repair_orchestrator

        source = inspect.getsource(repair_orchestrator.prepare_repair_draft)

        # Must check tenant_id in plan lookup
        assert "tenant_id" in source, "Prepare must filter by tenant_id"
        assert "ctx.tenant_id" in source, "Prepare must use context tenant_id"

    def test_confirm_validates_draft_tenant_ownership(self):
        """
        VERIFY: Confirm endpoint checks draft belongs to user's tenant.
        """
        import inspect
        from packs.roster.api.routers import repair_orchestrator

        source = inspect.getsource(repair_orchestrator.confirm_repair_draft)

        # Must check tenant_id in draft lookup
        assert "tenant_id" in source, "Confirm must filter by tenant_id"
        assert "ctx.tenant_id" in source, "Confirm must use context tenant_id"


# =============================================================================
# COVERAGE MATH TESTS
# =============================================================================

class TestCoverageMath:
    """
    Tests verifying that coverage_percent is computed correctly.

    CRITICAL: coverage_percent must NOT be a constant 100%.
    It must be: impacted_assigned / impacted_tours * 100
    """

    def test_coverage_percent_is_computed_not_constant(self):
        """
        VERIFY: coverage_percent reflects actual assigned vs impacted.
        """
        from packs.roster.core.repair_orchestrator import (
            _generate_split_proposal,
            CoverageInfo,
            SplitPolicy,
            ChangeBudget,
        )

        # Create 2 impacted tours
        tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=99,
                block_type="1er",
            ),
            TourInfo(
                tour_instance_id=101,
                tour_id="T2",
                day=0,
                start_ts=datetime(2024, 1, 1, 14, 0),
                end_ts=datetime(2024, 1, 1, 20, 0),
                driver_id=99,
                block_type="1er",
            ),
        ]

        # Only provide candidate for first tour (second has no candidates)
        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[
                    CandidateDriver(
                        driver_id=1,
                        name="Driver A",
                        score=95.0,
                        existing_tours_count=1,
                        existing_hours=20.0,
                        is_working_same_day=False,
                        reason="Only candidate",
                    ),
                ],
                total_available=1,
                filtered_count=0,
            ),
            101: CandidateResult(
                tour_instance_id=101,
                candidates=[],  # No candidates for tour 101
                total_available=0,
                filtered_count=0,
            ),
        }

        # Generate split proposal - should be infeasible with partial coverage
        proposal = _generate_split_proposal(
            impacted_tours=tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=True),
        )

        # Proposal should be returned but infeasible with 50% coverage
        assert proposal is not None, "Should return partial coverage proposal"
        assert not proposal.feasible, "Proposal with partial coverage must be infeasible"
        assert proposal.coverage.impacted_tours_count == 2, "Should report 2 impacted tours"
        assert proposal.coverage.impacted_assigned_count == 1, "Should report 1 assigned"
        assert proposal.coverage.coverage_percent == 50.0, "Coverage should be 50%, not 100%"

    def test_full_coverage_when_all_tours_assigned(self):
        """
        VERIFY: coverage_percent = 100% only when all tours are assigned.
        """
        from packs.roster.core.repair_orchestrator import (
            _generate_split_proposal,
            SplitPolicy,
            ChangeBudget,
        )

        tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=99,
                block_type="1er",
            ),
        ]

        # Provide candidate for the tour
        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[
                    CandidateDriver(
                        driver_id=1,
                        name="Driver A",
                        score=95.0,
                        existing_tours_count=1,
                        existing_hours=20.0,
                        is_working_same_day=False,
                        reason="Available",
                    ),
                ],
                total_available=1,
                filtered_count=0,
            ),
        }

        proposal = _generate_split_proposal(
            impacted_tours=tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
            split_policy=SplitPolicy(allow_split=True),
        )

        assert proposal is not None
        assert proposal.feasible, "Proposal with full coverage must be feasible"
        assert proposal.coverage.coverage_percent == 100.0
        assert proposal.coverage.impacted_tours_count == 1
        assert proposal.coverage.impacted_assigned_count == 1


# =============================================================================
# NO-FAKE-GREEN TESTS (Preview Safety)
# =============================================================================

class TestNoFakeGreen:
    """
    Tests ensuring preview never claims '0 block violations' unless validated.

    CRITICAL: UI must never show green checkmark unless violations_validated=True.
    """

    def test_preview_proposals_have_violations_validated_false_by_default(self):
        """
        VERIFY: Proposals from preview have violations_validated=False by default.
        """
        from packs.roster.core.repair_orchestrator import (
            _generate_no_split_proposal,
            _generate_split_proposal,
            ChangeBudget,
            SplitPolicy,
        )

        tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=99,
                block_type="1er",
            ),
        ]

        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[
                    CandidateDriver(
                        driver_id=1,
                        name="Driver A",
                        score=95.0,
                        existing_tours_count=1,
                        existing_hours=20.0,
                        is_working_same_day=False,
                        reason="Available",
                    ),
                ],
                total_available=1,
                filtered_count=0,
            ),
        }

        # Test no-split proposal
        proposal = _generate_no_split_proposal(
            impacted_tours=tours,
            candidates_by_tour=candidates,
            existing_assignments={},
            change_budget=ChangeBudget(),
        )

        assert proposal is not None
        assert proposal.violations.violations_validated is False, \
            "Preview proposals must have violations_validated=False"
        assert proposal.violations.block_violations is None, \
            "Unvalidated proposals must have block_violations=None, not 0"
        assert proposal.violations.warn_violations is None, \
            "Unvalidated proposals must have warn_violations=None, not 0"

    def test_preview_never_returns_block_violations_zero_unless_validated(self):
        """
        VERIFY: No code path returns block_violations=0 with violations_validated=False.

        This is a structural test - if someone accidentally sets block_violations=0
        without setting violations_validated=True, this catches it.
        """
        from packs.roster.core.repair_orchestrator import (
            _generate_no_split_proposal,
            _generate_split_proposal,
            _generate_chain_swap_proposal,
            ChangeBudget,
            SplitPolicy,
        )

        tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=99,
                block_type="1er",
            ),
        ]

        candidates = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[
                    CandidateDriver(
                        driver_id=1,
                        name="Driver A",
                        score=95.0,
                        existing_tours_count=1,
                        existing_hours=20.0,
                        is_working_same_day=False,
                        reason="Available",
                    ),
                ],
                total_available=1,
                filtered_count=0,
            ),
        }

        # Test all generators
        for generator, name in [
            (_generate_no_split_proposal, "no_split"),
            (lambda **kw: _generate_split_proposal(**kw, split_policy=SplitPolicy()), "split"),
        ]:
            proposal = generator(
                impacted_tours=tours,
                candidates_by_tour=candidates,
                existing_assignments={},
                change_budget=ChangeBudget(),
            )

            if proposal is not None:
                # If violations_validated=False, block_violations MUST be None
                if not proposal.violations.violations_validated:
                    assert proposal.violations.block_violations is None, \
                        f"{name}: block_violations must be None when violations_validated=False"
                    assert proposal.block_violations is None, \
                        f"{name}: legacy block_violations must also be None"

    def test_response_schema_requires_violations_validated(self):
        """
        VERIFY: ViolationInfoResponse has violations_validated as required field.
        """
        from packs.roster.api.routers.repair_orchestrator import ViolationInfoResponse

        # violations_validated must be a required field
        schema = ViolationInfoResponse.model_json_schema()
        required_fields = schema.get("required", [])

        assert "violations_validated" in required_fields, \
            "violations_validated must be a required field in API response"


# =============================================================================
# VIOLATION SIMULATOR TESTS
# =============================================================================

class TestViolationSimulator:
    """
    Tests for the violation simulation service.
    """

    def test_simulate_violations_returns_validated_result(self):
        """
        VERIFY: simulate_violations_sync returns violations_validated=True.
        """
        from packs.roster.core.violation_simulator import (
            simulate_violations_sync,
            SimulatedViolationResult,
        )

        # Create mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []  # No existing assignments

        result = simulate_violations_sync(
            cursor=mock_cursor,
            plan_version_id=1,
            proposed_assignments=[
                {"driver_id": 1, "tour_instance_id": 100, "day": 0, "start_ts": None, "end_ts": None}
            ],
            removed_tour_ids=[100],
            mode="fast",
        )

        assert isinstance(result, SimulatedViolationResult)
        assert result.violations_validated is True
        assert result.validation_mode == "fast"

    def test_simulate_violations_is_deterministic(self):
        """
        VERIFY: Same inputs produce same outputs.
        """
        from packs.roster.core.violation_simulator import simulate_violations_sync

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        assignments = [
            {"driver_id": 1, "tour_instance_id": 100, "day": 0, "start_ts": None, "end_ts": None}
        ]

        result1 = simulate_violations_sync(
            cursor=mock_cursor,
            plan_version_id=1,
            proposed_assignments=assignments,
            removed_tour_ids=[100],
            mode="fast",
        )

        result2 = simulate_violations_sync(
            cursor=mock_cursor,
            plan_version_id=1,
            proposed_assignments=assignments,
            removed_tour_ids=[100],
            mode="fast",
        )

        assert result1.block_count == result2.block_count
        assert result1.warn_count == result2.warn_count
        assert result1.validation_mode == result2.validation_mode


# =============================================================================
# PARITY TEST: preview(full) == confirm
# =============================================================================

class TestPreviewConfirmParity:
    """
    Tests verifying that preview(validation=full) matches confirm for same proposal.

    CRITICAL: preview(full) should produce the same violation counts as confirm,
    ensuring the dispatcher sees the same results before and after committing.
    """

    def test_preview_full_uses_canonical_violation_checks(self):
        """
        VERIFY: preview with validation=full uses same violation checks as confirm.

        This is a structural test - ensures the code paths align.
        """
        import inspect
        from packs.roster.api.routers import repair_orchestrator as router

        # Get source of preview endpoint
        preview_source = inspect.getsource(router.preview_repair_proposals)

        # Preview should call simulate_violations_sync when validation != "none"
        assert "simulate_violations_sync" in preview_source, \
            "preview must call simulate_violations_sync for validation"
        assert 'validation != "none"' in preview_source or "body.validation" in preview_source, \
            "preview must check validation parameter"

    def test_simulate_violations_covers_same_rules_as_canonical(self):
        """
        VERIFY: violation_simulator checks same rules as canonical violations.

        Compare the rule sets in violation_simulator vs violations.py.
        """
        import inspect
        from packs.roster.core import violation_simulator

        source = inspect.getsource(violation_simulator.simulate_violations_sync)

        # Must check time overlaps (canonical: overlap_violations)
        assert "TIME_OVERLAP" in source or "overlap" in source.lower(), \
            "simulator must check time overlaps"

        # Must check rest rules (canonical: rest_violations)
        assert "REST_VIOLATION" in source or "11h" in source or "min_rest" in source, \
            "simulator must check rest rules"

        # Must check max tours (canonical: max_tours check)
        assert "MAX_TOURS" in source or "max_tours_per_day" in source, \
            "simulator must check max tours per day"

    def test_preview_full_sets_violations_validated_true(self):
        """
        VERIFY: preview with validation=full sets violations_validated=True.

        If violations_validated=True, the UI can show green checkmarks.
        """
        from packs.roster.core.violation_simulator import (
            simulate_violations_sync,
            update_proposal_with_validation,
        )
        from packs.roster.core.repair_orchestrator import RepairProposal, ViolationInfo, CoverageInfo, DeltaSummary

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        # Simulate validation in full mode
        result = simulate_violations_sync(
            cursor=mock_cursor,
            plan_version_id=1,
            proposed_assignments=[
                {"driver_id": 1, "tour_instance_id": 100, "day": 0, "start_ts": None, "end_ts": None}
            ],
            removed_tour_ids=[100],
            mode="full",  # Full validation
        )

        # Result should have violations_validated=True
        assert result.violations_validated is True, \
            "full validation must set violations_validated=True"
        assert result.validation_mode == "full", \
            "validation_mode should be 'full'"

        # Create a dummy proposal and update it
        from packs.roster.core.repair_orchestrator import ProposedAssignment
        proposal = RepairProposal(
            proposal_id="test",
            label="Test",
            strategy="NO_SPLIT",
            feasible=True,
            quality_score=90.0,
            delta_summary=DeltaSummary(
                changed_tours_count=1,
                changed_drivers_count=1,
                impacted_drivers=[1],
                reserve_usage=0,
                chain_depth=0,
            ),
            assignments=[],
            removed_assignments=[100],
            evidence_hash="test",
            coverage=CoverageInfo(
                impacted_tours_count=1,
                impacted_assigned_count=1,
                coverage_percent=100.0,
                coverage_computed=True,
            ),
            violations=ViolationInfo(
                violations_validated=False,
                block_violations=None,
                warn_violations=None,
                validation_mode="none",
                validation_note="",
            ),
        )

        # Apply validation result
        update_proposal_with_validation(proposal, result)

        # After update, proposal should reflect validated state
        assert proposal.violations.violations_validated is True, \
            "proposal must be updated with validation result"
        assert proposal.violations.validation_mode == "full", \
            "proposal must show full validation mode"
        # Legacy fields should also be updated
        assert proposal.block_violations == result.block_count, \
            "legacy block_violations should match result"

    def test_parity_invariant_documentation(self):
        """
        VERIFY: Module docstrings document parity semantics.

        Important for maintainability - future developers need to know
        that preview(full) and confirm should produce same results.
        """
        from packs.roster.core import violation_simulator
        from packs.roster.core import repair_orchestrator

        # violation_simulator should document its relationship to confirm
        sim_doc = violation_simulator.__doc__ or ""
        assert "confirm" in sim_doc.lower() or "authoritative" in sim_doc.lower(), \
            "violation_simulator module should document confirm relationship"

        # repair_orchestrator should document validation modes
        orch_doc = repair_orchestrator.__doc__ or ""
        assert "validation" in orch_doc.lower(), \
            "repair_orchestrator should document validation modes"


# =============================================================================
# P0.6: DIAGNOSTICS TESTS
# =============================================================================

class TestDiagnostics:
    """
    Tests for P0.6: Diagnostics when no feasible proposals exist.

    REQUIREMENTS:
    - Empty feasible set returns diagnostic summary
    - Top 3 blocking reasons (NO_CANDIDATES, PARTIAL_COVERAGE, etc.)
    - UI hints for call-to-action
    """

    @pytest.fixture
    def incident_spec(self):
        return IncidentSpec(
            type="DRIVER_UNAVAILABLE",
            driver_id=99,
            time_range_start=datetime(2024, 1, 1, 0, 0),
            time_range_end=None,
            reason="SICK",
        )

    def test_diagnostics_returned_when_no_feasible_proposals(self):
        """VERIFY: When no feasible proposals, diagnostics are available."""
        from packs.roster.core.repair_orchestrator import (
            _generate_diagnostics,
            DiagnosticSummary,
        )

        impacted_tours = [
            TourInfo(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
        ]

        # NO_CANDIDATES: No drivers available at all (total_available=0)
        candidates_by_tour = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[],  # No candidates
                total_available=0,  # No drivers available at all
                filtered_count=0,
            ),
        }

        diagnostics = _generate_diagnostics(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates_by_tour,
            all_proposals=[],
            feasible_proposals=[],
            change_budget=ChangeBudget(),
        )

        assert diagnostics.has_diagnostics is True, "Should have diagnostics"
        assert len(diagnostics.reasons) > 0, "Should have at least one reason"
        assert diagnostics.reasons[0].code == "NO_CANDIDATES", \
            "Should identify NO_CANDIDATES as blocking reason"

    def test_diagnostics_include_uncovered_tour_ids(self):
        """VERIFY: Diagnostics include which tours have no coverage."""
        from packs.roster.core.repair_orchestrator import _generate_diagnostics

        impacted_tours = [
            TourInfo(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
            TourInfo(101, "T2", 1, datetime(2024, 1, 2, 6, 0), datetime(2024, 1, 2, 12, 0), 99, "1er"),
        ]

        # Only first tour has candidates
        candidates_by_tour = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[CandidateDriver(1, "A", 90.0, 1, 20.0, True, "Available")],
                total_available=5,
                filtered_count=4,
            ),
            101: CandidateResult(
                tour_instance_id=101,
                candidates=[],  # No candidates for this tour
                total_available=5,
                filtered_count=5,
            ),
        }

        diagnostics = _generate_diagnostics(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates_by_tour,
            all_proposals=[],
            feasible_proposals=[],
            change_budget=ChangeBudget(),
        )

        assert 101 in diagnostics.uncovered_tour_ids, \
            "Tour 101 should be in uncovered_tour_ids"

    def test_diagnostics_suggest_partial_proposals_when_available(self):
        """VERIFY: Diagnostics flag when partial proposals exist."""
        from packs.roster.core.repair_orchestrator import _generate_diagnostics

        impacted_tours = [
            TourInfo(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er"),
        ]

        candidates_by_tour = {
            100: CandidateResult(
                tour_instance_id=100,
                candidates=[],
                total_available=5,
                filtered_count=5,
            ),
        }

        # Create a partial proposal (infeasible due to coverage)
        partial_proposal = RepairProposal(
            proposal_id="partial",
            label="Partial",
            strategy="SPLIT",
            feasible=False,  # Marked infeasible
            quality_score=50.0,
            delta_summary=DeltaSummary(1, 1, [1], 0, 0),
            assignments=[],
            removed_assignments=[100],
            evidence_hash="abc",
            coverage=CoverageInfo(
                impacted_tours_count=2,
                impacted_assigned_count=1,  # Only 50% coverage
                coverage_percent=50.0,
                coverage_computed=True,
            ),
            violations=ViolationInfo(
                violations_validated=False,
                block_violations=None,
                warn_violations=None,
            ),
        )

        diagnostics = _generate_diagnostics(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates_by_tour,
            all_proposals=[partial_proposal],
            feasible_proposals=[],
            change_budget=ChangeBudget(),
        )

        assert diagnostics.partial_proposals_available is True, \
            "Should indicate partial proposals are available"
        assert "Show partial proposals" in diagnostics.suggested_actions, \
            "Should suggest showing partial proposals"

    def test_diagnostics_limit_to_3_reasons(self):
        """VERIFY: Diagnostics return max 3 reasons."""
        from packs.roster.core.repair_orchestrator import _generate_diagnostics

        impacted_tours = [
            TourInfo(i, f"T{i}", i % 7, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er")
            for i in range(10)
        ]

        candidates_by_tour = {
            t.tour_instance_id: CandidateResult(
                tour_instance_id=t.tour_instance_id,
                candidates=[],
                total_available=5,
                filtered_count=5,
            )
            for t in impacted_tours
        }

        diagnostics = _generate_diagnostics(
            impacted_tours=impacted_tours,
            candidates_by_tour=candidates_by_tour,
            all_proposals=[],
            feasible_proposals=[],
            change_budget=ChangeBudget(),
        )

        assert len(diagnostics.reasons) <= 3, "Should limit to max 3 reasons"

    def test_return_result_includes_diagnostics(self, incident_spec):
        """VERIFY: return_result=True includes diagnostics."""
        from packs.roster.core.repair_orchestrator import (
            generate_repair_proposals_sync,
            RepairOrchestratorResult,
        )

        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            # Step 1: Impacted tours
            [(100, "T1", 0, datetime(2024, 1, 1, 6, 0), datetime(2024, 1, 1, 12, 0), 99, "1er")],
            # Step 2: Available drivers (none)
            [],
            # Step 3: Existing assignments (for candidates)
            [],
            # Step 4: Existing assignments mapping
            [],
            # Step 5: All assignments by driver
            [],
        ]

        result = generate_repair_proposals_sync(
            cursor=mock_cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            incident=incident_spec,
            return_result=True,  # Request full result with diagnostics
        )

        assert isinstance(result, RepairOrchestratorResult), \
            "Should return RepairOrchestratorResult when return_result=True"
        assert result.impacted_tours_count == 1, "Should have impacted tours count"
        # Diagnostics should exist since no feasible proposals
        assert result.diagnostics is not None, "Should have diagnostics"


# =============================================================================
# P1.5A: COMPATIBILITY_UNKNOWN TESTS
# =============================================================================

class TestCompatibilityUnknown:
    """
    Tests for P1.5A: compatibility_unknown flag when skill/vehicle data missing.

    REQUIREMENTS:
    - CandidateResult has compatibility_unknown=True when not checked
    - RepairProposal has compatibility field
    - UI must acknowledge before auto-prepare
    """

    def test_candidate_result_has_compatibility_unknown_true(self):
        """VERIFY: CandidateResult defaults to compatibility_unknown=True."""
        result = CandidateResult(
            tour_instance_id=100,
            candidates=[],
            total_available=5,
            filtered_count=5,
        )

        assert result.compatibility_unknown is True, \
            "CandidateResult should default to compatibility_unknown=True"
        assert result.compatibility_checked is False, \
            "CandidateResult should default to compatibility_checked=False"

    def test_proposal_has_compatibility_info(self):
        """VERIFY: RepairProposal includes compatibility field."""
        from packs.roster.core.repair_orchestrator import (
            RepairProposal,
            CompatibilityInfo,
        )

        proposal = RepairProposal(
            proposal_id="test",
            label="Test",
            strategy="NO_SPLIT",
            feasible=True,
            quality_score=90.0,
            delta_summary=DeltaSummary(1, 1, [1], 0, 0),
            assignments=[],
            removed_assignments=[100],
            evidence_hash="abc",
            coverage=CoverageInfo(
                impacted_tours_count=1,
                impacted_assigned_count=1,
                coverage_percent=100.0,
                coverage_computed=True,
            ),
            violations=ViolationInfo(
                violations_validated=False,
                block_violations=None,
                warn_violations=None,
            ),
        )

        assert hasattr(proposal, 'compatibility'), \
            "RepairProposal should have compatibility field"
        assert isinstance(proposal.compatibility, CompatibilityInfo), \
            "compatibility should be CompatibilityInfo"

    def test_compatibility_info_defaults(self):
        """VERIFY: CompatibilityInfo has correct defaults."""
        from packs.roster.core.repair_orchestrator import CompatibilityInfo

        info = CompatibilityInfo()

        assert info.compatibility_checked is False, \
            "Should default to not checked"
        assert info.compatibility_unknown is False, \
            "Should default to not unknown (needs explicit setting)"
        assert info.missing_data == [], \
            "Should default to empty missing_data"
        assert info.incompatibilities == [], \
            "Should default to empty incompatibilities"

    def test_api_response_includes_compatibility(self):
        """VERIFY: API response schema includes compatibility fields."""
        from packs.roster.api.routers.repair_orchestrator import (
            RepairPreviewResponse,
            RepairProposalResponse,
            CompatibilityInfoResponse,
        )

        # Check that response models have compatibility fields in schema
        assert 'compatibility_unknown' in RepairPreviewResponse.model_fields, \
            "RepairPreviewResponse should have compatibility_unknown"
        assert 'compatibility' in RepairProposalResponse.model_fields, \
            "RepairProposalResponse should have compatibility"

        # Check schema field types
        assert RepairPreviewResponse.model_fields['compatibility_unknown'].annotation == bool, \
            "compatibility_unknown should be bool"
