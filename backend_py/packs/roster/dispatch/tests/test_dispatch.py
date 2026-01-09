"""
SOLVEREIGN Gurkerl Dispatch Assist - Unit Tests
================================================

Tests for dispatch assist components:
- Eligibility checking (hard constraints)
- Candidate scoring (soft ranking)
- Service orchestration

Uses mock data - no external dependencies.
"""

import pytest
from datetime import date, time, datetime, timedelta
from typing import List

from ..models import (
    OpenShift,
    ShiftAssignment,
    DriverState,
    Candidate,
    Disqualification,
    DisqualificationReason,
    ShiftStatus,
)
from ..eligibility import EligibilityChecker, check_driver_eligible
from ..scoring import CandidateScorer, ScoringWeights, score_and_rank
from ..service import DispatchAssistService, create_mock_dispatch_service


# =============================================================================
# TEST DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_open_shift() -> OpenShift:
    """Sample open shift for testing."""
    return OpenShift(
        id="open_2026-01-15_10",
        shift_date=date(2026, 1, 15),
        shift_start=time(6, 0),
        shift_end=time(14, 0),
        route_id="R101",
        zone="WIEN",
        required_skills=[],
        row_index=10,
    )


@pytest.fixture
def sample_driver() -> DriverState:
    """Sample driver for testing."""
    return DriverState(
        driver_id="DRV-001",
        driver_name="Max Mustermann",
        week_start=date(2026, 1, 13),  # Monday
        hours_worked_this_week=32.0,
        tours_this_week=4,
        target_weekly_hours=40.0,
        shifts_today=[],
        last_shift_end=datetime(2026, 1, 14, 18, 0),  # Previous day 6pm
        absences=[],
        skills=["standard"],
        home_zones=["WIEN"],
        is_active=True,
        max_weekly_hours=55.0,
    )


@pytest.fixture
def sample_drivers() -> List[DriverState]:
    """List of sample drivers for testing."""
    return [
        DriverState(
            driver_id="DRV-001",
            driver_name="Max Mustermann",
            week_start=date(2026, 1, 13),
            hours_worked_this_week=32.0,
            target_weekly_hours=40.0,
            skills=["standard"],
            home_zones=["WIEN"],
            is_active=True,
        ),
        DriverState(
            driver_id="DRV-002",
            driver_name="Anna Schmidt",
            week_start=date(2026, 1, 13),
            hours_worked_this_week=45.0,  # Close to max
            target_weekly_hours=40.0,
            skills=["standard", "refrigerated"],
            home_zones=["WIEN", "LINZ"],
            is_active=True,
        ),
        DriverState(
            driver_id="DRV-003",
            driver_name="Peter Wagner",
            week_start=date(2026, 1, 13),
            hours_worked_this_week=20.0,  # Under target
            target_weekly_hours=40.0,
            skills=["standard"],
            home_zones=["WIEN"],
            is_active=True,
        ),
        DriverState(
            driver_id="DRV-004",
            driver_name="Maria Huber",
            week_start=date(2026, 1, 13),
            hours_worked_this_week=38.0,
            target_weekly_hours=40.0,
            absences=[{
                "start_date": "2026-01-15",
                "end_date": "2026-01-16",
                "type": "vacation",
            }],  # On vacation
            skills=["standard"],
            home_zones=["WIEN"],
            is_active=True,
        ),
    ]


# =============================================================================
# ELIGIBILITY TESTS
# =============================================================================

class TestEligibilityChecker:
    """Tests for eligibility checking."""

    def test_eligible_driver_passes(self, sample_open_shift, sample_driver):
        """Driver with no constraints violated should be eligible."""
        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is True
        assert len(disqualifications) == 0

    def test_absent_driver_disqualified(self, sample_open_shift, sample_driver):
        """Driver on leave should be disqualified."""
        sample_driver.absences = [{
            "start_date": "2026-01-15",
            "end_date": "2026-01-15",
            "type": "sick",
        }]

        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert len(disqualifications) == 1
        assert disqualifications[0].reason == DisqualificationReason.ABSENT

    def test_insufficient_rest_disqualified(self, sample_open_shift, sample_driver):
        """Driver without 11h rest should be disqualified."""
        # Shift ends at 2am same day (only 4h before 6am shift)
        sample_driver.last_shift_end = datetime(2026, 1, 15, 2, 0)

        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert any(d.reason == DisqualificationReason.INSUFFICIENT_REST for d in disqualifications)

    def test_max_tours_exceeded(self, sample_open_shift, sample_driver):
        """Driver with max tours already should be disqualified."""
        # Already has 2 shifts today
        sample_driver.shifts_today = [
            ShiftAssignment(
                id="existing_1",
                shift_date=date(2026, 1, 15),
                shift_start=time(14, 0),
                shift_end=time(18, 0),
            ),
            ShiftAssignment(
                id="existing_2",
                shift_date=date(2026, 1, 15),
                shift_start=time(19, 0),
                shift_end=time(23, 0),
            ),
        ]

        checker = EligibilityChecker(max_tours_per_day=2)
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert any(d.reason == DisqualificationReason.MAX_DAILY_TOURS for d in disqualifications)

    def test_weekly_hours_exceeded(self, sample_open_shift, sample_driver):
        """Driver exceeding 55h should be disqualified."""
        sample_driver.hours_worked_this_week = 52.0  # 52 + 8 = 60 > 55

        checker = EligibilityChecker(max_weekly_hours=55.0)
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert any(d.reason == DisqualificationReason.WEEKLY_HOURS_EXCEEDED for d in disqualifications)

    def test_skill_mismatch_disqualified(self, sample_open_shift, sample_driver):
        """Driver missing required skills should be disqualified."""
        sample_open_shift.required_skills = ["refrigerated"]
        sample_driver.skills = ["standard"]  # No refrigerated

        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert any(d.reason == DisqualificationReason.SKILL_MISMATCH for d in disqualifications)

    def test_zone_mismatch_disqualified(self, sample_open_shift, sample_driver):
        """Driver in wrong zone should be disqualified."""
        sample_open_shift.zone = "LINZ"
        sample_driver.home_zones = ["WIEN"]  # Not LINZ

        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(sample_driver, sample_open_shift)

        assert is_eligible is False
        assert any(d.reason == DisqualificationReason.ZONE_MISMATCH for d in disqualifications)

    def test_filter_eligible_drivers(self, sample_open_shift, sample_drivers):
        """Filter should return candidates with eligibility status."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(sample_drivers, sample_open_shift)

        assert len(candidates) == 4  # All drivers returned
        eligible_count = sum(1 for c in candidates if c.is_eligible)
        assert eligible_count == 3  # DRV-004 is on vacation


# =============================================================================
# SCORING TESTS
# =============================================================================

class TestCandidateScorer:
    """Tests for candidate scoring."""

    def test_under_target_driver_scores_better(self, sample_open_shift, sample_drivers):
        """Driver under target hours should score better than over target."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(sample_drivers, sample_open_shift)

        scorer = CandidateScorer()
        driver_states = {d.driver_id: d for d in sample_drivers}
        ranked = scorer.score_candidates(candidates, sample_open_shift, driver_states)

        # Get eligible candidates only
        eligible = [c for c in ranked if c.is_eligible]

        # DRV-003 (20h worked) should rank higher than DRV-002 (45h worked)
        drv003 = next(c for c in eligible if c.driver_id == "DRV-003")
        drv002 = next((c for c in eligible if c.driver_id == "DRV-002"), None)

        if drv002:  # May be disqualified if over 55h
            assert drv003.rank < drv002.rank or drv003.score < drv002.score

    def test_top_candidates_returns_n(self, sample_open_shift, sample_drivers):
        """get_top_candidates should return specified number."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(sample_drivers, sample_open_shift)

        scorer = CandidateScorer()
        driver_states = {d.driver_id: d for d in sample_drivers}
        ranked = scorer.score_candidates(candidates, sample_open_shift, driver_states)

        top_2 = scorer.get_top_candidates(ranked, n=2)
        assert len(top_2) <= 2

    def test_ineligible_candidates_have_inf_score(self, sample_open_shift, sample_drivers):
        """Ineligible candidates should have infinity score."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(sample_drivers, sample_open_shift)

        scorer = CandidateScorer()
        driver_states = {d.driver_id: d for d in sample_drivers}
        ranked = scorer.score_candidates(candidates, sample_open_shift, driver_states)

        ineligible = [c for c in ranked if not c.is_eligible]
        for c in ineligible:
            assert c.score == float('inf')

    def test_reasons_generated(self, sample_open_shift, sample_drivers):
        """Eligible candidates should have reasons for their ranking."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(sample_drivers, sample_open_shift)

        scorer = CandidateScorer()
        driver_states = {d.driver_id: d for d in sample_drivers}
        ranked = scorer.score_candidates(candidates, sample_open_shift, driver_states)

        eligible = [c for c in ranked if c.is_eligible]
        for c in eligible:
            assert len(c.reasons) > 0


# =============================================================================
# SERVICE TESTS
# =============================================================================

class TestDispatchAssistService:
    """Tests for the dispatch assist service."""

    @pytest.mark.asyncio
    async def test_detect_open_shifts(self):
        """Service should detect open shifts from roster."""
        service, adapter = create_mock_dispatch_service()

        # Set up mock data
        adapter.set_roster([
            ShiftAssignment(
                id="shift_1",
                shift_date=date(2026, 1, 15),
                shift_start=time(6, 0),
                shift_end=time(14, 0),
                driver_id="DRV-001",
                status=ShiftStatus.ASSIGNED,
            ),
            ShiftAssignment(
                id="shift_2",
                shift_date=date(2026, 1, 15),
                shift_start=time(14, 0),
                shift_end=time(22, 0),
                driver_id=None,  # Open!
                status=ShiftStatus.OPEN,
            ),
        ])

        open_shifts = await service.detect_open_shifts()

        assert len(open_shifts) == 1
        assert "shift_2" in open_shifts[0].id

    @pytest.mark.asyncio
    async def test_suggest_candidates(self):
        """Service should suggest candidates for open shift."""
        service, adapter = create_mock_dispatch_service()

        # Set up mock data
        adapter.set_roster([
            ShiftAssignment(
                id="shift_1",
                shift_date=date(2026, 1, 15),
                shift_start=time(6, 0),
                shift_end=time(14, 0),
                driver_id="DRV-001",
                status=ShiftStatus.ASSIGNED,
            ),
        ])

        adapter.set_drivers([
            DriverState(
                driver_id="DRV-001",
                driver_name="Max Mustermann",
                week_start=date(2026, 1, 13),
                hours_worked_this_week=32.0,
                target_weekly_hours=40.0,
                is_active=True,
            ),
            DriverState(
                driver_id="DRV-002",
                driver_name="Anna Schmidt",
                week_start=date(2026, 1, 13),
                hours_worked_this_week=20.0,
                target_weekly_hours=40.0,
                is_active=True,
            ),
        ])

        open_shift = OpenShift(
            id="open_test",
            shift_date=date(2026, 1, 15),
            shift_start=time(14, 0),
            shift_end=time(22, 0),
        )

        candidates = await service.suggest_candidates(open_shift)

        assert len(candidates) == 2
        # Best candidate should be ranked first
        assert candidates[0].rank == 1

    @pytest.mark.asyncio
    async def test_generate_proposals(self):
        """Service should generate proposals for all open shifts."""
        service, adapter = create_mock_dispatch_service()

        adapter.set_roster([
            ShiftAssignment(
                id="shift_1",
                shift_date=date(2026, 1, 15),
                shift_start=time(6, 0),
                shift_end=time(14, 0),
                driver_id=None,
                status=ShiftStatus.OPEN,
            ),
            ShiftAssignment(
                id="shift_2",
                shift_date=date(2026, 1, 15),
                shift_start=time(14, 0),
                shift_end=time(22, 0),
                driver_id=None,
                status=ShiftStatus.OPEN,
            ),
        ])

        adapter.set_drivers([
            DriverState(
                driver_id="DRV-001",
                driver_name="Max Mustermann",
                week_start=date(2026, 1, 13),
                is_active=True,
            ),
        ])

        proposals = await service.generate_proposals()

        assert len(proposals) == 2

    @pytest.mark.asyncio
    async def test_run_full_workflow(self):
        """Full workflow should detect, suggest, and optionally write."""
        service, adapter = create_mock_dispatch_service()

        adapter.set_roster([
            ShiftAssignment(
                id="shift_1",
                shift_date=date(2026, 1, 15),
                shift_start=time(6, 0),
                shift_end=time(14, 0),
                driver_id=None,
                status=ShiftStatus.OPEN,
            ),
        ])

        adapter.set_drivers([
            DriverState(
                driver_id="DRV-001",
                driver_name="Max Mustermann",
                week_start=date(2026, 1, 13),
                is_active=True,
            ),
        ])

        result = await service.run_full_workflow(write_to_sheet=True)

        assert result["open_shifts"] == 1
        assert result["proposals"] == 1
        assert result["written"] == 1
        assert len(adapter.proposals_written) == 1


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_shift_at_midnight_boundary(self, sample_driver):
        """Shift crossing midnight should handle time correctly."""
        shift = OpenShift(
            id="night_shift",
            shift_date=date(2026, 1, 15),
            shift_start=time(22, 0),
            shift_end=time(6, 0),  # Next day
        )

        # 8h shift (22:00 - 06:00)
        assert shift.duration_hours == 8.0


class TestOvernightRestConstraint:
    """Critical tests for 11h rest constraint across day boundaries."""

    def test_rest_overnight_sufficient(self):
        """Driver ending 22:00 should be eligible for 10:00 next day (12h rest)."""
        driver = DriverState(
            driver_id="DRV-NIGHT",
            driver_name="Night Driver",
            week_start=date(2026, 1, 13),
            last_shift_end=datetime(2026, 1, 14, 22, 0),  # Ends 22:00
            is_active=True,
        )

        shift = OpenShift(
            id="morning_shift",
            shift_date=date(2026, 1, 15),  # Next day
            shift_start=time(10, 0),       # Starts 10:00 = 12h rest
            shift_end=time(18, 0),
        )

        checker = EligibilityChecker(rest_hours=11)
        is_eligible, disqualifications = checker.check_eligibility(driver, shift)

        assert is_eligible is True
        rest_violations = [d for d in disqualifications if d.reason == DisqualificationReason.INSUFFICIENT_REST]
        assert len(rest_violations) == 0

    def test_rest_overnight_insufficient(self):
        """Driver ending 22:00 should NOT be eligible for 06:00 next day (8h rest)."""
        driver = DriverState(
            driver_id="DRV-NIGHT",
            driver_name="Night Driver",
            week_start=date(2026, 1, 13),
            last_shift_end=datetime(2026, 1, 14, 22, 0),  # Ends 22:00
            is_active=True,
        )

        shift = OpenShift(
            id="early_shift",
            shift_date=date(2026, 1, 15),  # Next day
            shift_start=time(6, 0),        # Starts 06:00 = only 8h rest
            shift_end=time(14, 0),
        )

        checker = EligibilityChecker(rest_hours=11)
        is_eligible, disqualifications = checker.check_eligibility(driver, shift)

        assert is_eligible is False
        rest_violations = [d for d in disqualifications if d.reason == DisqualificationReason.INSUFFICIENT_REST]
        assert len(rest_violations) == 1
        assert "8.0h rest available" in rest_violations[0].details

    def test_rest_exactly_11_hours(self):
        """Driver with exactly 11h rest should be eligible (boundary case)."""
        driver = DriverState(
            driver_id="DRV-EXACT",
            driver_name="Exact Driver",
            week_start=date(2026, 1, 13),
            last_shift_end=datetime(2026, 1, 14, 19, 0),  # Ends 19:00
            is_active=True,
        )

        shift = OpenShift(
            id="exact_shift",
            shift_date=date(2026, 1, 15),  # Next day
            shift_start=time(6, 0),        # Starts 06:00 = exactly 11h rest
            shift_end=time(14, 0),
        )

        checker = EligibilityChecker(rest_hours=11)
        is_eligible, disqualifications = checker.check_eligibility(driver, shift)

        assert is_eligible is True

    def test_rest_weekend_boundary_friday_to_monday(self):
        """Driver ending Friday night should have enough rest for Monday morning."""
        driver = DriverState(
            driver_id="DRV-WEEKEND",
            driver_name="Weekend Driver",
            week_start=date(2026, 1, 13),
            last_shift_end=datetime(2026, 1, 17, 23, 0),  # Friday 23:00
            is_active=True,
        )

        shift = OpenShift(
            id="monday_shift",
            shift_date=date(2026, 1, 20),  # Monday (3 days later)
            shift_start=time(6, 0),
            shift_end=time(14, 0),
        )

        checker = EligibilityChecker(rest_hours=11)
        is_eligible, disqualifications = checker.check_eligibility(driver, shift)

        assert is_eligible is True  # 55+ hours rest

    def test_rest_same_day_split_shift(self):
        """Same day shift with insufficient gap should be blocked."""
        driver = DriverState(
            driver_id="DRV-SPLIT",
            driver_name="Split Driver",
            week_start=date(2026, 1, 13),
            last_shift_end=datetime(2026, 1, 15, 10, 0),  # Same day 10:00
            is_active=True,
        )

        shift = OpenShift(
            id="afternoon_shift",
            shift_date=date(2026, 1, 15),  # Same day
            shift_start=time(14, 0),       # 4h gap only
            shift_end=time(22, 0),
        )

        checker = EligibilityChecker(rest_hours=11)
        is_eligible, disqualifications = checker.check_eligibility(driver, shift)

        assert is_eligible is False
        rest_violations = [d for d in disqualifications if d.reason == DisqualificationReason.INSUFFICIENT_REST]
        assert len(rest_violations) == 1

    def test_driver_with_no_home_zone(self, sample_open_shift):
        """Driver with no zone restrictions should be eligible for any zone."""
        driver = DriverState(
            driver_id="DRV-FLEX",
            driver_name="Flex Driver",
            week_start=date(2026, 1, 13),
            home_zones=[],  # No zone restriction
            is_active=True,
        )

        sample_open_shift.zone = "ANY_ZONE"

        checker = EligibilityChecker()
        is_eligible, disqualifications = checker.check_eligibility(driver, sample_open_shift)

        # Should not be disqualified for zone
        zone_disq = [d for d in disqualifications if d.reason == DisqualificationReason.ZONE_MISMATCH]
        assert len(zone_disq) == 0

    def test_empty_driver_list(self, sample_open_shift):
        """Empty driver list should return empty candidates."""
        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers([], sample_open_shift)
        assert len(candidates) == 0

    def test_all_drivers_ineligible(self, sample_open_shift):
        """All ineligible should still return candidates with disqualifications."""
        drivers = [
            DriverState(
                driver_id="DRV-001",
                driver_name="Sick Driver",
                week_start=date(2026, 1, 13),
                absences=[{
                    "start_date": "2026-01-15",
                    "end_date": "2026-01-15",
                    "type": "sick",
                }],
                is_active=True,
            ),
        ]

        checker = EligibilityChecker()
        candidates = checker.filter_eligible_drivers(drivers, sample_open_shift)

        assert len(candidates) == 1
        assert candidates[0].is_eligible is False
        assert len(candidates[0].disqualifications) > 0
