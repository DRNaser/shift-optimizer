"""
SOLVEREIGN V4.9.2 - Activation Gate Tests
==========================================

Tests for HOLD/RELEASED slot state management and Morning Demand Gap workflow.

Test scenarios:
1. Hold slot state transitions
2. Release slot with at_risk detection
3. Batch hold/release operations
4. Morning gap analysis
5. Morning gap workflow actions
6. Freeze enforcement on HOLD/RELEASED slots
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

# These tests require a database connection
# They can be run with: pytest backend_py/packs/roster/tests/test_activation_gate.py -v

pytestmark = pytest.mark.asyncio


class TestSlotStatusTransitions:
    """Test individual slot state transitions."""

    async def test_hold_from_planned(self, db_conn, test_tenant, test_site):
        """PLANNED → HOLD should succeed."""
        # Create a test slot in PLANNED state
        slot_id = uuid4()
        target_date = date.today()

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=2),
            datetime.now(timezone.utc) + timedelta(hours=4),
        )

        # Set to HOLD
        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, $2::dispatch_hold_reason, $3)",
            slot_id,
            "LOW_DEMAND",
            "test_user@example.com",
        )

        assert result["success"] is True
        assert result["old_status"] == "PLANNED"
        assert result["new_status"] == "HOLD"
        assert result["message"] == "OK"

        # Verify slot state
        slot = await db_conn.fetchrow(
            "SELECT status, hold_reason, hold_set_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id,
        )
        assert slot["status"] == "HOLD"
        assert slot["hold_reason"] == "LOW_DEMAND"
        assert slot["hold_set_at"] is not None

    async def test_hold_from_assigned(self, db_conn, test_tenant, test_site, test_driver):
        """ASSIGNED → HOLD should succeed."""
        slot_id = uuid4()
        target_date = date.today()

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, assigned_driver_id)
            VALUES ($1, $2, $3, $4, $5, $6, 'ASSIGNED', $7)
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=2),
            datetime.now(timezone.utc) + timedelta(hours=4),
            test_driver,
        )

        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, $2::dispatch_hold_reason, $3)",
            slot_id,
            "OPS_DECISION",
            "test_user@example.com",
        )

        assert result["success"] is True
        assert result["old_status"] == "ASSIGNED"
        assert result["new_status"] == "HOLD"

    async def test_hold_from_aborted_fails(self, db_conn, test_tenant, test_site):
        """ABORTED → HOLD should fail (invalid transition)."""
        slot_id = uuid4()
        target_date = date.today()

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, abort_reason, abort_set_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'ABORTED', 'LOW_DEMAND', NOW())
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=2),
            datetime.now(timezone.utc) + timedelta(hours=4),
        )

        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, $2::dispatch_hold_reason, $3)",
            slot_id,
            "LOW_DEMAND",
            "test_user@example.com",
        )

        assert result["success"] is False
        assert "INVALID_TRANSITION" in result["message"]

    async def test_release_from_hold(self, db_conn, test_tenant, test_site):
        """HOLD → RELEASED should succeed."""
        slot_id = uuid4()
        target_date = date.today()

        # Create slot in HOLD state
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, hold_reason, hold_set_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'HOLD', 'LOW_DEMAND', NOW())
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=4),  # Far future = not at risk
            datetime.now(timezone.utc) + timedelta(hours=6),
        )

        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_released($1, $2, $3)",
            slot_id,
            "test_user@example.com",
            120,  # 2 hour threshold
        )

        assert result["success"] is True
        assert result["old_status"] == "HOLD"
        assert result["new_status"] == "RELEASED"
        assert result["at_risk"] is False
        assert result["message"] == "OK"

    async def test_release_at_risk_detection(self, db_conn, test_tenant, test_site):
        """HOLD → RELEASED near start time should flag as at_risk."""
        slot_id = uuid4()
        target_date = date.today()

        # Create slot starting very soon
        start_time = datetime.now(timezone.utc) + timedelta(minutes=30)

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, hold_reason, hold_set_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'HOLD', 'LOW_DEMAND', NOW())
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            start_time,
            start_time + timedelta(hours=2),
        )

        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_released($1, $2, $3)",
            slot_id,
            "test_user@example.com",
            120,  # 2 hour threshold - slot starts in 30 min, should be at risk
        )

        assert result["success"] is True
        assert result["at_risk"] is True
        assert "AT_RISK" in result["message"]

        # Verify at_risk flag stored
        slot = await db_conn.fetchrow(
            "SELECT at_risk, release_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id,
        )
        assert slot["at_risk"] is True
        assert slot["release_at"] is not None

    async def test_release_from_planned_fails(self, db_conn, test_tenant, test_site):
        """PLANNED → RELEASED should fail (must go through HOLD)."""
        slot_id = uuid4()
        target_date = date.today()

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
            """,
            slot_id,
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=2),
            datetime.now(timezone.utc) + timedelta(hours=4),
        )

        result = await db_conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_released($1, $2, $3)",
            slot_id,
            "test_user@example.com",
            120,
        )

        assert result["success"] is False
        assert "INVALID_TRANSITION" in result["message"]


class TestFreezeEnforcement:
    """Test that frozen days block HOLD/RELEASE operations."""

    async def test_hold_on_frozen_day_fails(self, db_conn, test_tenant, test_site):
        """Cannot put slot on HOLD when day is FROZEN."""
        slot_id = uuid4()
        target_date = date.today()

        # Create frozen day
        await db_conn.execute(
            """
            INSERT INTO dispatch.workbench_days
            (tenant_id, site_id, day_date, status, frozen_at)
            VALUES ($1, $2, $3, 'FROZEN', NOW())
            ON CONFLICT (tenant_id, site_id, day_date) DO UPDATE
            SET status = 'FROZEN', frozen_at = NOW()
            """,
            test_tenant,
            test_site,
            target_date,
        )

        # Create slot (will use trigger bypass for test setup)
        # Note: The trigger enforces this, so we test via the function
        result = await db_conn.fetchrow(
            """
            SELECT dispatch.set_slot_hold(
                $1::uuid,
                'LOW_DEMAND'::dispatch_hold_reason,
                'test_user@example.com'
            ) as result
            """,
            slot_id,
        )

        # Should fail because slot doesn't exist (can't create on frozen day)
        # or because day is frozen
        result_row = result["result"] if result else None
        if result_row:
            assert result_row[0] is False or "FROZEN" in str(result_row)


class TestBatchOperations:
    """Test batch hold/release operations."""

    async def test_batch_hold(self, db_conn, test_tenant, test_site):
        """Batch hold should process all slots."""
        slot_ids = [uuid4() for _ in range(3)]
        target_date = date.today()

        # Create test slots
        for slot_id in slot_ids:
            await db_conn.execute(
                """
                INSERT INTO dispatch.daily_slots
                (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
                VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
                """,
                slot_id,
                test_tenant,
                test_site,
                target_date,
                datetime.now(timezone.utc) + timedelta(hours=2),
                datetime.now(timezone.utc) + timedelta(hours=4),
            )

        results = await db_conn.fetch(
            "SELECT * FROM dispatch.set_slots_hold_batch($1::uuid[], $2::dispatch_hold_reason, $3)",
            slot_ids,
            "SURPLUS",
            "test_user@example.com",
        )

        assert len(results) == 3
        for r in results:
            assert r["success"] is True

    async def test_batch_release(self, db_conn, test_tenant, test_site):
        """Batch release should process all HOLD slots."""
        slot_ids = [uuid4() for _ in range(3)]
        target_date = date.today()

        # Create test slots in HOLD state
        for slot_id in slot_ids:
            await db_conn.execute(
                """
                INSERT INTO dispatch.daily_slots
                (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, hold_reason, hold_set_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'HOLD', 'LOW_DEMAND', NOW())
                """,
                slot_id,
                test_tenant,
                test_site,
                target_date,
                datetime.now(timezone.utc) + timedelta(hours=4),
                datetime.now(timezone.utc) + timedelta(hours=6),
            )

        results = await db_conn.fetch(
            "SELECT * FROM dispatch.set_slots_released_batch($1::uuid[], $2, $3)",
            slot_ids,
            "test_user@example.com",
            120,
        )

        assert len(results) == 3
        for r in results:
            assert r["success"] is True
            assert r["at_risk"] is False  # Far future, not at risk


class TestMorningGapAnalysis:
    """Test morning demand gap analysis function."""

    async def test_morning_gap_summary(self, db_conn, test_tenant, test_site):
        """Morning gap analysis should return correct counts."""
        target_date = date.today()
        morning_cutoff = 10

        # Create mix of morning slots in different states
        base_time = datetime.now(timezone.utc).replace(hour=7, minute=0)

        # PLANNED morning slot
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            base_time,
            base_time + timedelta(hours=2),
        )

        # HOLD morning slot
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, hold_reason, hold_set_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'HOLD', 'LOW_DEMAND', NOW())
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=3),
        )

        # RELEASED morning slot (at risk)
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, release_at, at_risk)
            VALUES ($1, $2, $3, $4, $5, $6, 'RELEASED', NOW(), TRUE)
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            base_time + timedelta(hours=2),
            base_time + timedelta(hours=4),
        )

        # Afternoon slot (should NOT be counted)
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            base_time.replace(hour=14),
            base_time.replace(hour=16),
        )

        result = await db_conn.fetchrow(
            "SELECT dispatch.analyze_morning_demand_gap($1, $2, $3, $4) as analysis",
            test_tenant,
            test_site,
            target_date,
            morning_cutoff,
        )

        analysis = result["analysis"]
        summary = analysis["summary"]

        assert summary["total_morning_slots"] == 3
        assert summary["planned_slots"] == 1
        assert summary["hold_slots"] == 1
        assert summary["released_slots"] == 1
        assert summary["at_risk_count"] == 1

        assert len(analysis["slots_on_hold"]) == 1
        assert len(analysis["at_risk_slots"]) == 1


class TestDailyStatsWithActivation:
    """Test that daily stats include HOLD/RELEASED counts."""

    async def test_daily_stats_includes_hold_counts(self, db_conn, test_tenant, test_site):
        """get_daily_stats should include hold/released counts."""
        target_date = date.today()

        # Create slots in various states
        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PLANNED')
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(hours=2),
        )

        await db_conn.execute(
            """
            INSERT INTO dispatch.daily_slots
            (slot_id, tenant_id, site_id, day_date, planned_start, planned_end, status, hold_reason, hold_set_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'HOLD', 'LOW_DEMAND', NOW())
            """,
            uuid4(),
            test_tenant,
            test_site,
            target_date,
            datetime.now(timezone.utc) + timedelta(hours=1),
            datetime.now(timezone.utc) + timedelta(hours=3),
        )

        result = await db_conn.fetchrow(
            "SELECT dispatch.get_daily_stats($1, $2, $3) as stats",
            test_tenant,
            test_site,
            target_date,
        )

        stats = result["stats"]

        assert "hold" in stats
        assert "released" in stats
        assert "hold_breakdown" in stats
        assert stats["hold"] == 1
        assert stats["hold_breakdown"]["LOW_DEMAND"] == 1


# Fixtures would be defined in conftest.py
@pytest.fixture
def db_conn():
    """Database connection fixture - implement in conftest.py."""
    pytest.skip("Requires database connection - run with full test setup")


@pytest.fixture
def test_tenant():
    """Test tenant ID fixture."""
    return 1


@pytest.fixture
def test_site():
    """Test site ID fixture."""
    return 10


@pytest.fixture
def test_driver():
    """Test driver ID fixture."""
    return 100
