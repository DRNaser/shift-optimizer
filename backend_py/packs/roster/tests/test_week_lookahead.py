"""
Tests for Week Lookahead Candidate Finder (V4.9.2 Hardened)
===========================================================

Verifies the week-aware candidate finder:
1. Week window calculation (Mon-Sun)
2. Lookahead starts from TODAY, not week_start
3. Churn calculation (downstream changes, NOT violations)
4. Overtime risk is separate from churn
5. Deterministic ranking with driver_id tiebreaker
6. Frozen day hard-blocking
7. Pinned day handling with allow_multiday_repair

Test Categories:
- test_week_window_*: Week boundary tests
- test_lookahead_*: Lookahead range tests (FIX-1)
- test_churn_*: Churn semantics tests (FIX-2)
- test_ranking_*: Deterministic ranking tests (FIX-3)
- test_frozen_*: Frozen day blocking tests (FIX-4)
- test_pinned_*: Pinned day handling tests (FIX-4)
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Import from the new package structure
from packs.roster.core.week_lookahead import (
    get_week_window,
    get_lookahead_range,
    day_index_from_date,
    check_overlap_week,
    check_rest_week,
    check_max_tours_day,
    check_weekly_hours,
    compute_minimal_churn,
    evaluate_candidate_with_lookahead,
    find_candidates_batch,
    rank_candidates,
    make_ranking_key,
    sort_affected_slots,
    WeekWindow,
    DayAssignment,
    SlotContext,
    CandidateImpact,
    AffectedSlot,
    CandidateBatchResult,
    SlotResult,
    DebugMetrics,
)


# =============================================================================
# UNIT TESTS: WEEK WINDOW CALCULATION
# =============================================================================

class TestWeekWindow:
    """Tests for week window calculation."""

    def test_monday_returns_same_week(self):
        """Monday should be start of its own week."""
        monday = date(2026, 1, 12)  # A Monday
        week = get_week_window(monday)

        assert week.week_start == monday
        assert week.week_end == date(2026, 1, 18)  # Sunday

    def test_wednesday_returns_correct_week(self):
        """Mid-week date should return containing week."""
        wednesday = date(2026, 1, 14)  # A Wednesday
        week = get_week_window(wednesday)

        assert week.week_start == date(2026, 1, 12)  # Monday
        assert week.week_end == date(2026, 1, 18)  # Sunday

    def test_sunday_returns_correct_week(self):
        """Sunday should be end of its week."""
        sunday = date(2026, 1, 18)  # A Sunday
        week = get_week_window(sunday)

        assert week.week_start == date(2026, 1, 12)  # Monday
        assert week.week_end == sunday

    def test_week_contains_all_days(self):
        """Week should contain exactly 7 days."""
        week = get_week_window(date(2026, 1, 15))
        days = week.days_list()

        assert len(days) == 7
        assert days[0].weekday() == 0  # Monday
        assert days[6].weekday() == 6  # Sunday

    def test_day_index_from_date(self):
        """Day index should match weekday (0=Mon, 6=Sun)."""
        monday = date(2026, 1, 12)
        assert day_index_from_date(monday) == 0

        sunday = date(2026, 1, 18)
        assert day_index_from_date(sunday) == 6


# =============================================================================
# UNIT TESTS: LOOKAHEAD RANGE (FIX-1)
# =============================================================================

class TestLookaheadRange:
    """Tests for lookahead range calculation (FIX-1)."""

    def test_lookahead_starts_at_today(self):
        """Lookahead should start from today, not week_start."""
        wednesday = date(2026, 1, 14)  # A Wednesday
        week = get_week_window(wednesday)

        start, end = get_lookahead_range(wednesday, week)

        assert start == wednesday  # TODAY, not Monday
        assert end == week.week_end  # Sunday

    def test_lookahead_on_monday_includes_full_week(self):
        """Monday lookahead should include full week."""
        monday = date(2026, 1, 12)
        week = get_week_window(monday)

        start, end = get_lookahead_range(monday, week)

        assert start == monday
        assert end == date(2026, 1, 18)

    def test_lookahead_on_sunday_includes_only_sunday(self):
        """Sunday lookahead should only include Sunday."""
        sunday = date(2026, 1, 18)
        week = get_week_window(sunday)

        start, end = get_lookahead_range(sunday, week)

        assert start == sunday
        assert end == sunday

    def test_week_days_from_start_date(self):
        """WeekWindow.days_from should return only days from start."""
        week = get_week_window(date(2026, 1, 15))  # Wednesday
        wednesday = date(2026, 1, 14)

        days = week.days_from(wednesday)

        assert len(days) == 5  # Wed, Thu, Fri, Sat, Sun
        assert days[0] == wednesday
        assert days[-1] == week.week_end


# =============================================================================
# UNIT TESTS: CONSTRAINT CHECKERS
# =============================================================================

class TestOverlapChecker:
    """Tests for week-aware overlap checking."""

    def test_no_overlap_when_slots_separate(self):
        """Non-overlapping slots should pass."""
        candidate_start = datetime(2026, 1, 14, 14, 0)
        candidate_end = datetime(2026, 1, 14, 18, 0)

        existing = [
            DayAssignment(
                day_date=date(2026, 1, 14),
                day_index=2,
                tour_instance_id=1,
                start_ts=datetime(2026, 1, 14, 6, 0),
                end_ts=datetime(2026, 1, 14, 12, 0),
            )
        ]

        conflicts = check_overlap_week(candidate_start, candidate_end, existing)
        assert len(conflicts) == 0

    def test_overlap_detected_when_partial(self):
        """Partial overlap should be detected."""
        candidate_start = datetime(2026, 1, 14, 10, 0)
        candidate_end = datetime(2026, 1, 14, 16, 0)

        existing = [
            DayAssignment(
                day_date=date(2026, 1, 14),
                day_index=2,
                tour_instance_id=1,
                start_ts=datetime(2026, 1, 14, 14, 0),
                end_ts=datetime(2026, 1, 14, 18, 0),
            )
        ]

        conflicts = check_overlap_week(candidate_start, candidate_end, existing)
        assert len(conflicts) == 1
        assert conflicts[0][0].tour_instance_id == 1

    def test_overlap_across_days_not_detected(self):
        """Slots on different days should not overlap."""
        candidate_start = datetime(2026, 1, 14, 10, 0)
        candidate_end = datetime(2026, 1, 14, 16, 0)

        existing = [
            DayAssignment(
                day_date=date(2026, 1, 15),  # Different day
                day_index=3,
                tour_instance_id=1,
                start_ts=datetime(2026, 1, 15, 10, 0),
                end_ts=datetime(2026, 1, 15, 16, 0),
            )
        ]

        conflicts = check_overlap_week(candidate_start, candidate_end, existing)
        assert len(conflicts) == 0


class TestRestChecker:
    """Tests for 11-hour rest rule checking."""

    def test_sufficient_rest_passes(self):
        """12+ hours rest should pass."""
        candidate_start = datetime(2026, 1, 15, 6, 0)  # Next day 6am
        candidate_end = datetime(2026, 1, 15, 14, 0)

        existing = [
            DayAssignment(
                day_date=date(2026, 1, 14),
                day_index=2,
                tour_instance_id=1,
                start_ts=datetime(2026, 1, 14, 6, 0),
                end_ts=datetime(2026, 1, 14, 14, 0),  # 16h rest
            )
        ]

        conflicts = check_rest_week(candidate_start, candidate_end, existing)
        assert len(conflicts) == 0

    def test_insufficient_rest_detected(self):
        """Less than 11h rest should be detected."""
        candidate_start = datetime(2026, 1, 14, 20, 0)  # 6h after prev ends
        candidate_end = datetime(2026, 1, 15, 4, 0)

        existing = [
            DayAssignment(
                day_date=date(2026, 1, 14),
                day_index=2,
                tour_instance_id=1,
                start_ts=datetime(2026, 1, 14, 6, 0),
                end_ts=datetime(2026, 1, 14, 14, 0),
            )
        ]

        conflicts = check_rest_week(candidate_start, candidate_end, existing)
        assert len(conflicts) == 1
        assert "6.0h rest" in conflicts[0][1]


class TestMaxToursChecker:
    """Tests for max tours per day checking."""

    def test_under_limit_passes(self):
        """Under max tours should pass."""
        existing = [
            DayAssignment(day_date=date(2026, 1, 14), day_index=2, tour_instance_id=1),
            DayAssignment(day_date=date(2026, 1, 14), day_index=2, tour_instance_id=2),
        ]

        exceeds, reason = check_max_tours_day(date(2026, 1, 14), existing, max_tours=3)
        assert exceeds is False

    def test_at_limit_blocks(self):
        """At max tours should block."""
        existing = [
            DayAssignment(day_date=date(2026, 1, 14), day_index=2, tour_instance_id=1),
            DayAssignment(day_date=date(2026, 1, 14), day_index=2, tour_instance_id=2),
            DayAssignment(day_date=date(2026, 1, 14), day_index=2, tour_instance_id=3),
        ]

        exceeds, reason = check_max_tours_day(date(2026, 1, 14), existing, max_tours=3)
        assert exceeds is True
        assert "3 tours" in reason


# =============================================================================
# UNIT TESTS: CHURN SEMANTICS (FIX-2)
# =============================================================================

class TestChurnSemantics:
    """Tests for churn calculation semantics (FIX-2)."""

    def test_weekly_hours_is_risk_not_churn(self):
        """Weekly hours exceeding limit should return risk, not churn."""
        # check_weekly_hours returns (exceeds_limit, overtime_amount, risk_level, is_hard_fail)
        exceeds, overtime, risk_level, is_hard_fail = check_weekly_hours(50.0, 8.0, max_weekly_hours=55.0)

        assert exceeds is True
        assert overtime == 3.0  # 58 - 55
        assert risk_level == "LOW"  # < 5h

    def test_high_overtime_returns_high_risk(self):
        """High overtime should return HIGH risk level."""
        # check_weekly_hours returns (exceeds_limit, overtime_amount, risk_level, is_hard_fail)
        exceeds, overtime, risk_level, is_hard_fail = check_weekly_hours(50.0, 18.0, max_weekly_hours=55.0)

        assert exceeds is True
        assert overtime == 13.0  # 68 - 55
        assert risk_level == "HIGH"  # > 10h

    def test_minimal_churn_counts_slot_displacements(self):
        """compute_minimal_churn should count slot displacements, not violations."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 14),  # Wednesday
            day_index=2,
            start_ts=datetime(2026, 1, 14, 14, 0),
            end_ts=datetime(2026, 1, 14, 22, 0),  # Ends 10pm
        )

        # Driver has morning shift on Thursday - rest violation
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 15),  # Thursday
                day_index=3,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 15, 6, 0),  # Only 8h rest from 10pm
                end_ts=datetime(2026, 1, 15, 14, 0),
            )
        ]

        result = compute_minimal_churn(
            slot=slot,
            driver_week_assignments=driver_assignments,
            frozen_days=set(),
            pinned_days=set(),
            allow_multiday_repair=True,
        )

        # Should count as 1 churn (one slot needs displacement)
        assert result.churn_count == 1
        assert result.churn_locked_count == 0
        assert len(result.affected_slots) == 1
        assert result.affected_slots[0].reason in ["REST_VIOLATION", "REST_NEXTDAY_FIRST_SLOT"]

    def test_past_day_conflicts_not_counted_as_churn(self):
        """Conflicts on past days should not be counted as churn."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 15),  # Thursday
            day_index=3,
            start_ts=datetime(2026, 1, 15, 6, 0),
            end_ts=datetime(2026, 1, 15, 14, 0),
        )

        # Driver has assignment on Wednesday (past) that would have rest violation
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 14),  # Wednesday (PAST)
                day_index=2,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 14, 14, 0),
                end_ts=datetime(2026, 1, 14, 22, 0),  # Only 8h rest to 6am Thursday
            )
        ]

        result = compute_minimal_churn(
            slot=slot,
            driver_week_assignments=driver_assignments,
            frozen_days=set(),
            pinned_days=set(),
            allow_multiday_repair=True,
        )

        # Past day should NOT count as churn (it's a feasibility blocker, not churn)
        assert result.churn_count == 0
        assert len(result.affected_slots) == 0


# =============================================================================
# UNIT TESTS: DETERMINISTIC RANKING (FIX-3)
# =============================================================================

class TestDeterministicRanking:
    """Tests for deterministic ranking with driver_id tiebreaker (FIX-3)."""

    def test_ranking_key_includes_driver_id(self):
        """Ranking key should include driver_id as final tiebreaker."""
        c = CandidateImpact(
            driver_id=42,
            driver_name="Test",
            feasible_today=True,
            lookahead_ok=True,
            churn_count=0,
            score=10.0,
        )

        key = make_ranking_key(c)

        # Driver ID should be the last element
        assert key[-1] == 42

    def test_same_score_sorted_by_driver_id(self):
        """Candidates with same score should be sorted by driver_id."""
        candidates = [
            CandidateImpact(driver_id=100, driver_name="C", feasible_today=True, churn_count=0, score=10.0),
            CandidateImpact(driver_id=1, driver_name="A", feasible_today=True, churn_count=0, score=10.0),
            CandidateImpact(driver_id=50, driver_name="B", feasible_today=True, churn_count=0, score=10.0),
        ]

        ranked = rank_candidates(candidates)

        # Should be sorted by driver_id when all else equal
        assert ranked[0].driver_id == 1
        assert ranked[1].driver_id == 50
        assert ranked[2].driver_id == 100

    def test_ranking_is_deterministic_on_repeated_calls(self):
        """Same inputs should always produce same ranking."""
        candidates = [
            CandidateImpact(driver_id=3, driver_name="C", feasible_today=True, churn_count=1, score=30.0),
            CandidateImpact(driver_id=1, driver_name="A", feasible_today=True, churn_count=0, score=50.0),
            CandidateImpact(driver_id=2, driver_name="B", feasible_today=True, churn_count=0, score=20.0),
        ]

        # Sort multiple times
        for _ in range(5):
            ranked = rank_candidates(candidates.copy())

            # Order should always be: B (churn=0, score=20, id=2), A (churn=0, score=50, id=1), C (churn=1)
            # Wait - B has score=20 < A's score=50, and they have same churn
            # So order should be: 2 (B), 1 (A), 3 (C)
            assert ranked[0].driver_id == 2
            assert ranked[1].driver_id == 1
            assert ranked[2].driver_id == 3

    def test_affected_slots_sorted_by_date_then_slot_id(self):
        """Affected slots should be sorted by (date, slot_id)."""
        slots = [
            AffectedSlot(date=date(2026, 1, 16), slot_id="S3", tour_instance_id=3, reason="REST"),
            AffectedSlot(date=date(2026, 1, 15), slot_id="S2", tour_instance_id=2, reason="REST"),
            AffectedSlot(date=date(2026, 1, 15), slot_id="S1", tour_instance_id=1, reason="REST"),
        ]

        sorted_slots = sort_affected_slots(slots)

        assert sorted_slots[0].date == date(2026, 1, 15)
        assert sorted_slots[0].slot_id == "S1"
        assert sorted_slots[1].date == date(2026, 1, 15)
        assert sorted_slots[1].slot_id == "S2"
        assert sorted_slots[2].date == date(2026, 1, 16)


# =============================================================================
# UNIT TESTS: FROZEN DAY BLOCKING (FIX-4)
# =============================================================================

class TestFrozenDayBlocking:
    """Tests for frozen day hard-blocking (FIX-4)."""

    @pytest.mark.asyncio
    async def test_frozen_target_day_blocks_all(self):
        """If target day is frozen, no candidates should be feasible."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 14),
            day_index=2,
            start_ts=datetime(2026, 1, 14, 8, 0),
            end_ts=datetime(2026, 1, 14, 12, 0),
        )

        frozen_days = {date(2026, 1, 14)}  # Target day is frozen
        week = get_week_window(date(2026, 1, 14))

        impact = await evaluate_candidate_with_lookahead(
            conn=None,
            tenant_id=1,
            site_id=1,
            driver_id=1,
            driver_name="Test Driver",
            slot=slot,
            week_window=week,
            driver_week_assignments=[],
            driver_current_hours=0.0,
            frozen_days=frozen_days,
            pinned_days=set(),
            allow_multiday_repair=False,
        )

        assert impact.feasible_today is False
        assert "frozen" in " ".join(impact.blockers).lower()

    @pytest.mark.asyncio
    async def test_churn_on_frozen_day_is_locked(self):
        """Churn that would affect frozen days should be locked."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 14),  # Wednesday
            day_index=2,
            start_ts=datetime(2026, 1, 14, 14, 0),
            end_ts=datetime(2026, 1, 14, 22, 0),  # Ends 10pm
        )

        # Driver has morning shift on Thursday that would violate rest
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 15),  # Thursday
                day_index=3,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 15, 6, 0),  # Only 8h rest from 10pm
                end_ts=datetime(2026, 1, 15, 14, 0),
                is_frozen=True,  # This day is frozen
            )
        ]

        frozen_days = {date(2026, 1, 15)}  # Thursday is frozen
        week = get_week_window(date(2026, 1, 14))

        impact = await evaluate_candidate_with_lookahead(
            conn=None,
            tenant_id=1,
            site_id=1,
            driver_id=1,
            driver_name="Test Driver",
            slot=slot,
            week_window=week,
            driver_week_assignments=driver_assignments,
            driver_current_hours=8.0,
            frozen_days=frozen_days,
            pinned_days=set(),
            allow_multiday_repair=True,  # Even with multiday allowed
        )

        # Should have locked churn because Thursday is frozen
        assert impact.churn_locked_count >= 1
        assert impact.lookahead_ok is False


# =============================================================================
# UNIT TESTS: PINNED DAY HANDLING (FIX-4)
# =============================================================================

class TestPinnedDayHandling:
    """Tests for pinned day handling with allow_multiday_repair (FIX-4)."""

    @pytest.mark.asyncio
    async def test_pinned_day_churn_blocked_by_default(self):
        """Churn on pinned days should be blocked by default."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 14),
            day_index=2,
            start_ts=datetime(2026, 1, 14, 14, 0),
            end_ts=datetime(2026, 1, 14, 22, 0),
        )

        # Driver has pinned assignment on Thursday with rest violation
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 15),
                day_index=3,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 15, 6, 0),
                end_ts=datetime(2026, 1, 15, 14, 0),
                is_pinned=True,
            )
        ]

        pinned_days = {date(2026, 1, 15)}
        week = get_week_window(date(2026, 1, 14))

        impact = await evaluate_candidate_with_lookahead(
            conn=None,
            tenant_id=1,
            site_id=1,
            driver_id=1,
            driver_name="Test Driver",
            slot=slot,
            week_window=week,
            driver_week_assignments=driver_assignments,
            driver_current_hours=8.0,
            frozen_days=set(),
            pinned_days=pinned_days,
            allow_multiday_repair=False,  # Default
        )

        # Should have locked churn because pinned and not allowed
        assert impact.churn_locked_count >= 1

    @pytest.mark.asyncio
    async def test_pinned_day_churn_allowed_when_explicit(self):
        """Churn on pinned days should be allowed with allow_multiday_repair=True."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 14),
            day_index=2,
            start_ts=datetime(2026, 1, 14, 14, 0),
            end_ts=datetime(2026, 1, 14, 22, 0),
        )

        # Driver has pinned assignment on Thursday with rest violation
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 15),
                day_index=3,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 15, 6, 0),
                end_ts=datetime(2026, 1, 15, 14, 0),
                is_pinned=True,
            )
        ]

        pinned_days = {date(2026, 1, 15)}
        week = get_week_window(date(2026, 1, 14))

        impact = await evaluate_candidate_with_lookahead(
            conn=None,
            tenant_id=1,
            site_id=1,
            driver_id=1,
            driver_name="Test Driver",
            slot=slot,
            week_window=week,
            driver_week_assignments=driver_assignments,
            driver_current_hours=8.0,
            frozen_days=set(),
            pinned_days=pinned_days,
            allow_multiday_repair=True,  # Explicitly allowed
        )

        # Should have regular churn, not locked
        assert impact.churn_locked_count == 0
        # But should still count as churn
        assert impact.churn_count >= 1


# =============================================================================
# UNIT TESTS: LEXICOGRAPHIC RANKING
# =============================================================================

class TestLexicographicRanking:
    """Tests for lexicographic ranking order."""

    def test_feasible_beats_infeasible(self):
        """Feasible candidates should always rank higher."""
        feasible = CandidateImpact(
            driver_id=1, driver_name="A",
            feasible_today=True,
            churn_count=5,  # High churn
            score=100.0,
        )
        infeasible = CandidateImpact(
            driver_id=2, driver_name="B",
            feasible_today=False,
            churn_count=0,
            score=0.0,
        )

        ranked = rank_candidates([infeasible, feasible])

        assert ranked[0].driver_id == 1  # Feasible first

    def test_zero_churn_beats_any_churn(self):
        """Zero churn should always beat any churn (within feasible)."""
        zero_churn = CandidateImpact(
            driver_id=1, driver_name="A",
            feasible_today=True,
            churn_count=0,
            score=100.0,  # Worse score
        )
        some_churn = CandidateImpact(
            driver_id=2, driver_name="B",
            feasible_today=True,
            churn_count=1,
            score=0.0,  # Better score
        )

        ranked = rank_candidates([some_churn, zero_churn])

        assert ranked[0].driver_id == 1  # Zero churn first despite worse score

    def test_locked_churn_is_hard_block(self):
        """Locked churn (frozen/pinned days) should rank last."""
        no_locked = CandidateImpact(
            driver_id=1, driver_name="A",
            feasible_today=True,
            lookahead_ok=True,
            churn_locked_count=0,
            churn_count=5,
        )
        has_locked = CandidateImpact(
            driver_id=2, driver_name="B",
            feasible_today=True,
            lookahead_ok=False,  # Not OK because of locked
            churn_locked_count=1,
            churn_count=0,
        )

        ranked = rank_candidates([has_locked, no_locked])

        assert ranked[0].driver_id == 1  # No locked churn first

    def test_score_tiebreaker_when_equal_churn(self):
        """Score should only matter when churn is equal."""
        better_score = CandidateImpact(
            driver_id=1, driver_name="A",
            feasible_today=True,
            churn_count=2,
            score=10.0,
        )
        worse_score = CandidateImpact(
            driver_id=2, driver_name="B",
            feasible_today=True,
            churn_count=2,
            score=50.0,
        )

        ranked = rank_candidates([worse_score, better_score])

        assert ranked[0].driver_id == 1  # Better score wins when churn equal


# =============================================================================
# INTEGRATION TESTS: BATCH CANDIDATE FINDER
# =============================================================================

class TestBatchCandidateFinder:
    """Integration tests for find_candidates_batch."""

    @pytest.mark.asyncio
    async def test_batch_returns_frozen_days_list(self):
        """Batch result should include frozen_days list.

        FIXED: Line 507 in batch.py now correctly assigns frozen_days to result.
        """
        conn = AsyncMock()

        # Mock day status - not frozen
        conn.fetchrow.side_effect = [
            None,  # Day not frozen
            {"id": 1},  # Plan version
        ]

        # Mock frozen days query
        conn.fetch.side_effect = [
            [{"day_date": date(2026, 1, 12)}, {"day_date": date(2026, 1, 13)}],  # Frozen days
            [],  # Pinned days
            [],  # Slots
            [],  # Drivers
            [],  # Assignments
        ]

        result = await find_candidates_batch(
            conn=conn,
            tenant_id=1,
            site_id=1,
            target_date=date(2026, 1, 14),
        )

        assert isinstance(result, CandidateBatchResult)
        assert len(result.frozen_days) == 2
        assert date(2026, 1, 12) in result.frozen_days

    @pytest.mark.asyncio
    async def test_batch_returns_debug_metrics(self):
        """Batch result should include debug_metrics when requested AND env flag is set.

        FIXED: Debug metrics are gated by ROSTER_CANDIDATES_DEBUG_METRICS env flag.
        This test patches the env flag to enable debug metrics.
        """
        conn = AsyncMock()

        conn.fetchrow.side_effect = [
            None,  # Day not frozen
            {"id": 1},  # Plan version
        ]

        conn.fetch.side_effect = [
            [],  # Frozen days
            [],  # Pinned days
            [],  # Slots
            [],  # Drivers
            [],  # Assignments
        ]

        # Patch the DEBUG_METRICS_ENABLED flag to True
        with patch("packs.roster.core.week_lookahead.batch.DEBUG_METRICS_ENABLED", True):
            result = await find_candidates_batch(
                conn=conn,
                tenant_id=1,
                site_id=1,
                target_date=date(2026, 1, 14),
                include_debug_metrics=True,
            )

        assert result.debug_metrics is not None
        assert result.debug_metrics.db_query_count >= 1
        assert result.debug_metrics.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_frozen_day_returns_empty_result(self):
        """If target day is frozen, return empty slots."""
        conn = AsyncMock()

        # Target day is frozen
        conn.fetchrow.return_value = {"status": "FROZEN"}

        result = await find_candidates_batch(
            conn=conn,
            tenant_id=1,
            site_id=1,
            target_date=date(2026, 1, 14),
        )

        assert result.is_frozen is True
        assert len(result.slots) == 0


# =============================================================================
# REGRESSION TESTS
# =============================================================================

class TestRegressions:
    """Regression tests for previously fixed issues."""

    def test_overtime_not_counted_as_churn(self):
        """Overtime risk should not inflate churn_count."""
        # This was the original bug - hours cap was counted as violation
        # check_weekly_hours returns (exceeds_limit, overtime_amount, risk_level, is_hard_fail)
        exceeds, overtime, risk_level, is_hard_fail = check_weekly_hours(55.0, 10.0, max_weekly_hours=55.0)

        # Should indicate exceeds but NOT be treated as churn
        assert exceeds is True
        assert overtime == 10.0
        # The overtime amount is returned for risk display,
        # but the calling code should NOT add it to churn_count

    @pytest.mark.asyncio
    async def test_lookahead_evaluates_only_future_days(self):
        """Lookahead should only evaluate future days, not past."""
        slot = SlotContext(
            slot_id="S1",
            tour_instance_id=100,
            day_date=date(2026, 1, 15),  # Thursday
            day_index=3,
            start_ts=datetime(2026, 1, 15, 14, 0),
            end_ts=datetime(2026, 1, 15, 22, 0),
        )

        # Driver has assignments on past days that would cause rest violation
        # if we were checking them
        driver_assignments = [
            DayAssignment(
                day_date=date(2026, 1, 13),  # Monday (PAST)
                day_index=0,
                tour_instance_id=200,
                slot_id="S200",
                start_ts=datetime(2026, 1, 13, 6, 0),
                end_ts=datetime(2026, 1, 13, 14, 0),
            ),
            DayAssignment(
                day_date=date(2026, 1, 17),  # Saturday (FUTURE)
                day_index=5,
                tour_instance_id=300,
                slot_id="S300",
                start_ts=datetime(2026, 1, 17, 6, 0),  # Rest OK from Thursday 10pm
                end_ts=datetime(2026, 1, 17, 14, 0),
            )
        ]

        week = get_week_window(date(2026, 1, 15))

        impact = await evaluate_candidate_with_lookahead(
            conn=None,
            tenant_id=1,
            site_id=1,
            driver_id=1,
            driver_name="Test Driver",
            slot=slot,
            week_window=week,
            driver_week_assignments=driver_assignments,
            driver_current_hours=16.0,
            frozen_days=set(),
            pinned_days=set(),
            allow_multiday_repair=True,
        )

        # Past assignments should not create churn
        # Saturday has sufficient rest (32h from Thursday 10pm to Saturday 6am)
        assert impact.churn_count == 0
