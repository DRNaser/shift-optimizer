"""
Tests for Candidate Finder Service
===================================

Verifies that the candidate finder:
1. Filters illegal drivers (overlap, rest, max_tours)
2. Ranking is deterministic (same input = same output)
3. Respects all hard constraints
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from packs.roster.core.candidate_finder import (
    check_time_overlap,
    check_rest_rule,
    check_max_tours_per_day,
    compute_candidate_score,
    find_candidates_sync,
    TourInfo,
    DriverAssignment,
    CandidateDriver,
)


# =============================================================================
# UNIT TESTS: CONSTRAINT CHECKERS
# =============================================================================

class TestTimeOverlapChecker:
    """Tests for check_time_overlap function."""

    def test_no_overlap_when_tour_after_existing(self):
        """Tour starts after existing ends - no overlap."""
        tour_start = datetime(2024, 1, 1, 14, 0)
        tour_end = datetime(2024, 1, 1, 18, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
            )
        ]

        has_overlap, reason = check_time_overlap(tour_start, tour_end, existing)

        assert has_overlap is False
        assert reason is None

    def test_no_overlap_when_tour_before_existing(self):
        """Tour ends before existing starts - no overlap."""
        tour_start = datetime(2024, 1, 1, 6, 0)
        tour_end = datetime(2024, 1, 1, 10, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 14, 0),
                end_ts=datetime(2024, 1, 1, 18, 0),
            )
        ]

        has_overlap, reason = check_time_overlap(tour_start, tour_end, existing)

        assert has_overlap is False
        assert reason is None

    def test_overlap_when_tour_contains_existing(self):
        """Tour fully contains existing - overlap."""
        tour_start = datetime(2024, 1, 1, 6, 0)
        tour_end = datetime(2024, 1, 1, 20, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 10, 0),
                end_ts=datetime(2024, 1, 1, 14, 0),
            )
        ]

        has_overlap, reason = check_time_overlap(tour_start, tour_end, existing)

        assert has_overlap is True
        assert "tour 1" in reason.lower()

    def test_overlap_when_partial(self):
        """Tour partially overlaps - overlap."""
        tour_start = datetime(2024, 1, 1, 10, 0)
        tour_end = datetime(2024, 1, 1, 16, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 14, 0),
                end_ts=datetime(2024, 1, 1, 18, 0),
            )
        ]

        has_overlap, reason = check_time_overlap(tour_start, tour_end, existing)

        assert has_overlap is True

    def test_no_overlap_with_empty_existing(self):
        """No existing assignments - no overlap."""
        tour_start = datetime(2024, 1, 1, 10, 0)
        tour_end = datetime(2024, 1, 1, 14, 0)

        has_overlap, reason = check_time_overlap(tour_start, tour_end, [])

        assert has_overlap is False

    def test_no_overlap_when_times_missing(self):
        """Missing times - conservative, allow (let later checks handle)."""
        has_overlap, reason = check_time_overlap(None, None, [])

        assert has_overlap is False


class TestRestRuleChecker:
    """Tests for check_rest_rule function."""

    def test_sufficient_rest_before(self):
        """11+ hours rest before tour - OK."""
        tour_start = datetime(2024, 1, 2, 6, 0)
        tour_end = datetime(2024, 1, 2, 14, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 14, 0),  # 16h rest
            )
        ]

        violates, reason = check_rest_rule(tour_start, tour_end, existing)

        assert violates is False

    def test_insufficient_rest_before(self):
        """Less than 11h rest before tour - violation."""
        tour_start = datetime(2024, 1, 1, 20, 0)
        tour_end = datetime(2024, 1, 2, 4, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 6, 0),
                end_ts=datetime(2024, 1, 1, 14, 0),  # 6h rest
            )
        ]

        violates, reason = check_rest_rule(tour_start, tour_end, existing)

        assert violates is True
        assert "6.0h rest" in reason

    def test_insufficient_rest_after(self):
        """Less than 11h rest after tour - violation."""
        tour_start = datetime(2024, 1, 1, 6, 0)
        tour_end = datetime(2024, 1, 1, 14, 0)
        existing = [
            DriverAssignment(
                tour_instance_id=1,
                day=0,
                start_ts=datetime(2024, 1, 1, 20, 0),  # 6h rest
                end_ts=datetime(2024, 1, 2, 4, 0),
            )
        ]

        violates, reason = check_rest_rule(tour_start, tour_end, existing)

        assert violates is True


class TestMaxToursChecker:
    """Tests for check_max_tours_per_day function."""

    def test_under_limit(self):
        """Less than max tours - OK."""
        existing = [
            DriverAssignment(tour_instance_id=1, day=0, start_ts=None, end_ts=None),
            DriverAssignment(tour_instance_id=2, day=0, start_ts=None, end_ts=None),
        ]

        exceeds, reason = check_max_tours_per_day(0, existing, max_tours=3)

        assert exceeds is False

    def test_at_limit(self):
        """At max tours - exceeds (can't add more)."""
        existing = [
            DriverAssignment(tour_instance_id=1, day=0, start_ts=None, end_ts=None),
            DriverAssignment(tour_instance_id=2, day=0, start_ts=None, end_ts=None),
            DriverAssignment(tour_instance_id=3, day=0, start_ts=None, end_ts=None),
        ]

        exceeds, reason = check_max_tours_per_day(0, existing, max_tours=3)

        assert exceeds is True
        assert "3 tours" in reason

    def test_different_day_doesnt_count(self):
        """Tours on different days don't count towards limit."""
        existing = [
            DriverAssignment(tour_instance_id=1, day=0, start_ts=None, end_ts=None),
            DriverAssignment(tour_instance_id=2, day=1, start_ts=None, end_ts=None),
            DriverAssignment(tour_instance_id=3, day=2, start_ts=None, end_ts=None),
        ]

        exceeds, reason = check_max_tours_per_day(0, existing, max_tours=3)

        assert exceeds is False


# =============================================================================
# UNIT TESTS: SCORING
# =============================================================================

class TestCandidateScoring:
    """Tests for compute_candidate_score function."""

    def test_score_higher_for_less_utilized_driver(self):
        """Drivers with fewer hours should score higher."""
        # Driver with 30h
        score_light = compute_candidate_score(
            driver_id=1,
            tour_day=0,
            existing_assignments=[],
            weekly_hours=30.0,
            max_weekly_hours=55,
        )

        # Driver with 50h
        score_heavy = compute_candidate_score(
            driver_id=2,
            tour_day=0,
            existing_assignments=[],
            weekly_hours=50.0,
            max_weekly_hours=55,
        )

        assert score_light > score_heavy

    def test_score_higher_for_same_day_driver(self):
        """Drivers already working that day should score higher (avoid new callouts)."""
        existing_same_day = [
            DriverAssignment(tour_instance_id=1, day=0, start_ts=None, end_ts=None)
        ]

        score_same_day = compute_candidate_score(
            driver_id=1,
            tour_day=0,
            existing_assignments=existing_same_day,
            weekly_hours=30.0,
        )

        score_different_day = compute_candidate_score(
            driver_id=2,
            tour_day=0,
            existing_assignments=[],
            weekly_hours=30.0,
        )

        # Same day bonus should outweigh the penalty for one assignment
        assert score_same_day > score_different_day

    def test_scoring_is_deterministic(self):
        """Same inputs should always produce same score."""
        existing = [
            DriverAssignment(tour_instance_id=1, day=0, start_ts=None, end_ts=None)
        ]

        score1 = compute_candidate_score(1, 0, existing, 30.0)
        score2 = compute_candidate_score(1, 0, existing, 30.0)

        assert score1 == score2

    def test_driver_id_tiebreaker(self):
        """Same conditions but different driver_id should produce different scores."""
        score1 = compute_candidate_score(1, 0, [], 30.0)
        score2 = compute_candidate_score(2, 0, [], 30.0)

        assert score1 != score2
        # Lower driver_id should score slightly higher (tiny penalty)
        assert score1 > score2


# =============================================================================
# INTEGRATION TESTS: CANDIDATE FINDER
# =============================================================================

class TestCandidateFinderSync:
    """Integration tests for find_candidates_sync."""

    def test_filters_out_absent_drivers(self):
        """Absent drivers should not appear as candidates."""
        # Mock cursor
        cursor = MagicMock()

        # Mock driver query - returns 3 drivers
        cursor.fetchall.side_effect = [
            # Available drivers (excluding absent)
            [(1, "Driver A", True), (2, "Driver B", True)],
            # Assignments for available drivers
            [],
        ]

        impacted_tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 8, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=3,  # The absent driver
                block_type="1er",
            )
        ]

        result = find_candidates_sync(
            cursor=cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            impacted_tours=impacted_tours,
            absent_driver_ids={3},  # Driver 3 is absent
            freeze_driver_ids=set(),
        )

        # Should have candidates from drivers 1 and 2, not 3
        candidates = result[100].candidates
        candidate_ids = {c.driver_id for c in candidates}

        assert 3 not in candidate_ids
        assert 1 in candidate_ids or 2 in candidate_ids

    def test_deterministic_ranking(self):
        """Same inputs should always produce same ranking."""
        cursor = MagicMock()

        # Mock returns
        cursor.fetchall.side_effect = [
            [(1, "Driver A", True), (2, "Driver B", True), (3, "Driver C", True)],
            [],  # No existing assignments
        ] * 2  # Run twice

        impacted_tours = [
            TourInfo(
                tour_instance_id=100,
                tour_id="T1",
                day=0,
                start_ts=datetime(2024, 1, 1, 8, 0),
                end_ts=datetime(2024, 1, 1, 12, 0),
                driver_id=99,
                block_type="1er",
            )
        ]

        result1 = find_candidates_sync(
            cursor=cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            impacted_tours=impacted_tours,
            absent_driver_ids={99},
            freeze_driver_ids=set(),
        )

        # Reset mock for second call
        cursor.fetchall.side_effect = [
            [(1, "Driver A", True), (2, "Driver B", True), (3, "Driver C", True)],
            [],
        ]

        result2 = find_candidates_sync(
            cursor=cursor,
            tenant_id=1,
            site_id=1,
            plan_version_id=1,
            impacted_tours=impacted_tours,
            absent_driver_ids={99},
            freeze_driver_ids=set(),
        )

        # Rankings should be identical
        ranking1 = [c.driver_id for c in result1[100].candidates]
        ranking2 = [c.driver_id for c in result2[100].candidates]

        assert ranking1 == ranking2


# =============================================================================
# PROPERTY TESTS (if hypothesis available)
# =============================================================================

try:
    from hypothesis import given, strategies as st

    @given(st.integers(min_value=0, max_value=55))
    def test_score_increases_with_more_capacity(weekly_hours):
        """Score should decrease as weekly_hours increases."""
        score_at_hours = compute_candidate_score(1, 0, [], weekly_hours)
        score_at_more_hours = compute_candidate_score(1, 0, [], weekly_hours + 1)

        if weekly_hours < 55:
            assert score_at_hours > score_at_more_hours

except ImportError:
    pass  # hypothesis not installed, skip property tests
