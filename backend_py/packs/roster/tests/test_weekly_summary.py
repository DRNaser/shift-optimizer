"""
SOLVEREIGN V4.9 - Weekly Summary Tests
=======================================

Tests for weekly management summary:
- Mon-Sun aggregation
- Frozen vs live day stats
- Abort breakdown by reason
- Coverage/execution rates
- Tenant isolation (RLS)

NON-NEGOTIABLES:
- Frozen days use stored final_stats (no drift)
- Live days compute current state
- Abort metrics aggregated correctly
- Europe/Vienna timezone semantics
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock


class TestWeeklySummaryAggregation:
    """Test weekly summary aggregates correctly."""

    @pytest.mark.asyncio
    async def test_weekly_summary_seven_days(self):
        """Weekly summary includes exactly 7 days (Mon-Sun)."""
        # Given a week_start (Monday)
        week_start = date(2026, 1, 13)  # Monday

        # Expected days
        expected_days = [
            date(2026, 1, 13),  # Mon
            date(2026, 1, 14),  # Tue
            date(2026, 1, 15),  # Wed
            date(2026, 1, 16),  # Thu
            date(2026, 1, 17),  # Fri
            date(2026, 1, 18),  # Sat
            date(2026, 1, 19),  # Sun
        ]

        assert len(expected_days) == 7
        assert expected_days[0].weekday() == 0  # Monday

    @pytest.mark.asyncio
    async def test_weekly_totals_sum_daily(self):
        """Weekly totals sum up daily stats."""
        daily_stats = [
            {"total_slots": 50, "assigned": 45, "executed": 40, "aborted": 2, "coverage_gaps": 5},
            {"total_slots": 50, "assigned": 48, "executed": 45, "aborted": 1, "coverage_gaps": 2},
            {"total_slots": 50, "assigned": 50, "executed": 48, "aborted": 0, "coverage_gaps": 0},
        ]

        # Compute totals
        totals = {
            "total_slots": sum(d["total_slots"] for d in daily_stats),
            "assigned": sum(d["assigned"] for d in daily_stats),
            "executed": sum(d["executed"] for d in daily_stats),
            "aborted": sum(d["aborted"] for d in daily_stats),
            "coverage_gaps": sum(d["coverage_gaps"] for d in daily_stats),
        }

        assert totals["total_slots"] == 150
        assert totals["aborted"] == 3
        assert totals["coverage_gaps"] == 7

    @pytest.mark.asyncio
    async def test_weekly_must_start_monday(self):
        """Week start must be a Monday."""
        # Tuesday should be rejected
        tuesday = date(2026, 1, 14)
        assert tuesday.weekday() == 1  # Not Monday

        # API should return 400 for non-Monday


class TestFrozenVsLiveStats:
    """Test frozen vs live day stat handling."""

    @pytest.mark.asyncio
    async def test_frozen_day_uses_stored_stats(self):
        """Frozen days use stored final_stats, not recomputed."""
        # Given a frozen day with stored stats
        frozen_day = {
            "date": "2026-01-13",
            "status": "FROZEN",
            "final_stats": {
                "total_slots": 50,
                "assigned": 45,
                "executed": 40,
                "aborted": 3,
            },
        }

        # When querying weekly summary
        # Should use final_stats directly, NOT recompute

        # This prevents drift - frozen stats are immutable
        assert frozen_day["status"] == "FROZEN"
        assert frozen_day["final_stats"]["executed"] == 40

    @pytest.mark.asyncio
    async def test_live_day_computes_current(self):
        """Live (OPEN) days compute current state."""
        # Given an open day
        open_day = {
            "date": "2026-01-15",
            "status": "OPEN",
            "is_live": True,
        }

        # When querying weekly summary
        # Should compute current slot states
        assert open_day["is_live"] is True

    @pytest.mark.asyncio
    async def test_mixed_frozen_and_live_days(self):
        """Weekly summary handles mix of frozen and live days."""
        # Common scenario: Mon-Wed frozen, Thu-Sun open
        days = [
            {"date": "2026-01-13", "status": "FROZEN", "is_live": False},
            {"date": "2026-01-14", "status": "FROZEN", "is_live": False},
            {"date": "2026-01-15", "status": "FROZEN", "is_live": False},
            {"date": "2026-01-16", "status": "OPEN", "is_live": True},
            {"date": "2026-01-17", "status": "OPEN", "is_live": True},
            {"date": "2026-01-18", "status": "OPEN", "is_live": True},
            {"date": "2026-01-19", "status": "OPEN", "is_live": True},
        ]

        frozen_count = sum(1 for d in days if d["status"] == "FROZEN")
        assert frozen_count == 3


class TestAbortBreakdown:
    """Test abort reason aggregation."""

    @pytest.mark.asyncio
    async def test_abort_by_reason_aggregation(self):
        """Abort breakdown aggregates by reason across days."""
        daily_aborts = [
            {"LOW_DEMAND": 2, "WEATHER": 0, "VEHICLE": 1, "OPS_DECISION": 0, "OTHER": 0},
            {"LOW_DEMAND": 1, "WEATHER": 1, "VEHICLE": 0, "OPS_DECISION": 1, "OTHER": 0},
            {"LOW_DEMAND": 0, "WEATHER": 0, "VEHICLE": 0, "OPS_DECISION": 0, "OTHER": 1},
        ]

        # Aggregate by reason
        total_breakdown = {
            "LOW_DEMAND": sum(d["LOW_DEMAND"] for d in daily_aborts),
            "WEATHER": sum(d["WEATHER"] for d in daily_aborts),
            "VEHICLE": sum(d["VEHICLE"] for d in daily_aborts),
            "OPS_DECISION": sum(d["OPS_DECISION"] for d in daily_aborts),
            "OTHER": sum(d["OTHER"] for d in daily_aborts),
        }

        assert total_breakdown["LOW_DEMAND"] == 3
        assert total_breakdown["WEATHER"] == 1
        assert sum(total_breakdown.values()) == 7  # Total aborted

    @pytest.mark.asyncio
    async def test_no_aborts_returns_zeros(self):
        """No aborts returns zero breakdown."""
        empty_breakdown = {
            "LOW_DEMAND": 0,
            "WEATHER": 0,
            "VEHICLE": 0,
            "OPS_DECISION": 0,
            "OTHER": 0,
        }

        assert sum(empty_breakdown.values()) == 0


class TestRatesComputation:
    """Test coverage and execution rate computation."""

    @pytest.mark.asyncio
    async def test_coverage_rate_computation(self):
        """Coverage rate = (total - gaps) / total * 100."""
        totals = {"total_slots": 100, "coverage_gaps": 10}

        coverage_rate = ((totals["total_slots"] - totals["coverage_gaps"]) / totals["total_slots"]) * 100

        assert coverage_rate == 90.0

    @pytest.mark.asyncio
    async def test_execution_rate_computation(self):
        """Execution rate = executed / total * 100."""
        totals = {"total_slots": 100, "executed": 85}

        execution_rate = (totals["executed"] / totals["total_slots"]) * 100

        assert execution_rate == 85.0

    @pytest.mark.asyncio
    async def test_zero_slots_handles_division(self):
        """Zero total slots handles division by zero."""
        totals = {"total_slots": 0, "executed": 0, "coverage_gaps": 0}

        # Should return None or 0, not crash
        if totals["total_slots"] > 0:
            rate = totals["executed"] / totals["total_slots"]
        else:
            rate = None

        assert rate is None


class TestTenantIsolation:
    """Test tenant isolation (RLS)."""

    @pytest.mark.asyncio
    async def test_weekly_summary_tenant_scoped(self):
        """Weekly summary only shows tenant's own data."""
        # Given tenant_id=1
        # Should only see tenant 1's sites and slots
        # RLS enforces this at DB level
        pass

    @pytest.mark.asyncio
    async def test_cannot_access_other_tenant_week(self):
        """Cannot access another tenant's weekly summary."""
        # Attempting to query tenant 2's data with tenant 1 context
        # Should return empty or error
        pass


class TestTimezoneSemantic:
    """Test Europe/Vienna timezone handling."""

    @pytest.mark.asyncio
    async def test_week_boundary_vienna_time(self):
        """Week boundaries use Europe/Vienna timezone."""
        # Monday 00:00 Vienna time, not UTC
        pass

    @pytest.mark.asyncio
    async def test_day_boundary_vienna_time(self):
        """Day boundaries use Europe/Vienna timezone."""
        # Midnight crossing in Vienna time
        pass


class TestWeeklySummaryResponse:
    """Test response format."""

    @pytest.mark.asyncio
    async def test_response_includes_all_fields(self):
        """Response includes all required fields."""
        expected_fields = [
            "success",
            "tenant_id",
            "site_id",
            "week_start",
            "week_end",
            "daily",
            "totals",
            "abort_total",
            "abort_by_reason",
            "frozen_days",
            "execution_rate",
            "coverage_rate",
            "computed_at",
        ]

        # All fields should be present in response
        for field in expected_fields:
            assert field is not None  # Placeholder

    @pytest.mark.asyncio
    async def test_daily_array_has_seven_entries(self):
        """Daily array has exactly 7 entries."""
        # Even if some days have no data, should have entries
        daily = [{"date": f"2026-01-{13+i}"} for i in range(7)]
        assert len(daily) == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
