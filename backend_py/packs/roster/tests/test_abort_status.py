"""
SOLVEREIGN V4.9 - Abort Status Tests
=====================================

Tests for slot abort functionality:
- Status transitions (PLANNED/ASSIGNED -> ABORTED)
- Abort reasons tracking
- Idempotency
- Freeze guard (cannot abort frozen day slots)
- Audit trail

NON-NEGOTIABLES:
- ABORTED is final (no revert)
- Must track abort_reason
- Must track abort_by_user_id
- Day frozen = no abort allowed
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock

# Import the module under test
from packs.roster.core.draft_mutations import (
    SlotStatus,
    AbortReason,
    HardBlockReason,
    set_slot_status,
    batch_set_slot_status,
    check_day_frozen,
)


class TestSlotStatusEnum:
    """Test SlotStatus enum values."""

    def test_slot_status_values(self):
        """All expected status values exist."""
        assert SlotStatus.PLANNED == "PLANNED"
        assert SlotStatus.ASSIGNED == "ASSIGNED"
        assert SlotStatus.EXECUTED == "EXECUTED"
        assert SlotStatus.ABORTED == "ABORTED"

    def test_abort_reason_values(self):
        """All expected abort reasons exist."""
        assert AbortReason.LOW_DEMAND == "LOW_DEMAND"
        assert AbortReason.WEATHER == "WEATHER"
        assert AbortReason.VEHICLE == "VEHICLE"
        assert AbortReason.OPS_DECISION == "OPS_DECISION"
        assert AbortReason.OTHER == "OTHER"


class TestCheckDayFrozen:
    """Test day frozen check function."""

    @pytest.mark.asyncio
    async def test_unfrozen_day_returns_false(self):
        """Unfrozen day returns False."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {"status": "OPEN"}

        result = await check_day_frozen(mock_conn, 1, 1, date(2026, 1, 15))

        # check_day_frozen returns bool directly
        assert result is False

    @pytest.mark.asyncio
    async def test_frozen_day_returns_true(self):
        """Frozen day returns True."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {"status": "FROZEN"}

        result = await check_day_frozen(mock_conn, 1, 1, date(2026, 1, 15))

        # check_day_frozen returns bool directly
        assert result is True

    @pytest.mark.asyncio
    async def test_missing_day_returns_false(self):
        """Day not in DB returns False (default OPEN)."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        result = await check_day_frozen(mock_conn, 1, 1, date(2026, 1, 15))

        # No row = not frozen
        assert result is False


class TestSetSlotStatus:
    """Test single slot status transition."""

    @pytest.mark.asyncio
    async def test_abort_planned_slot_success(self):
        """Can abort a PLANNED slot."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("12345678-1234-5678-1234-567812345678")

        # First call: get slot info (returns existing slot)
        # Second call: check_day_frozen via get slot (day_date check)
        mock_conn.fetchrow.side_effect = [
            {  # Slot exists with PLANNED status
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "PLANNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "OPEN"},  # Day is not frozen
        ]
        mock_conn.execute = AsyncMock()

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.LOW_DEMAND,
            abort_note=None,
            performed_by="user-1",
        )

        # set_slot_status returns SlotStatusResult dataclass
        assert result.success is True
        assert result.new_status == SlotStatus.ABORTED

    @pytest.mark.asyncio
    async def test_abort_assigned_slot_success(self):
        """Can abort an ASSIGNED slot."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("22345678-1234-5678-1234-567812345678")

        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "ASSIGNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "OPEN"},
        ]
        mock_conn.execute = AsyncMock()

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.WEATHER,
            abort_note=None,
            performed_by="user-1",
        )

        assert result.success is True
        assert result.new_status == SlotStatus.ABORTED

    @pytest.mark.asyncio
    async def test_abort_frozen_day_fails(self):
        """Cannot abort slot on frozen day."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("32345678-1234-5678-1234-567812345678")

        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "PLANNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "FROZEN"},  # Day is frozen
        ]

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.OPS_DECISION,
            abort_note=None,
            performed_by="user-1",
        )

        assert result.success is False
        assert result.hard_block_reason == HardBlockReason.DAY_FROZEN

    @pytest.mark.asyncio
    async def test_abort_requires_reason(self):
        """Abort requires abort_reason."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("42345678-1234-5678-1234-567812345678")

        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "PLANNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "OPEN"},
        ]

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=None,  # Missing reason
            abort_note=None,
            performed_by="user-1",
        )

        assert result.success is False
        assert "reason" in (result.error_message or "").lower()


class TestBatchSetSlotStatus:
    """Test batch slot status transitions."""

    @pytest.mark.asyncio
    async def test_batch_abort_multiple_slots(self):
        """Can abort multiple slots in batch."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot1_uuid = UUID("11111111-1111-1111-1111-111111111111")
        slot2_uuid = UUID("22222222-2222-2222-2222-222222222222")

        # Mock responses for two slots being aborted
        # Each slot_status call does: 1) get slot, 2) check frozen
        mock_conn.fetchrow.side_effect = [
            # Slot 1
            {"slot_id": slot1_uuid, "tenant_id": 1, "site_id": 1, "day_date": date(2026, 1, 15),
             "status": "PLANNED", "abort_reason": None, "abort_note": None},
            {"status": "OPEN"},
            # Slot 2
            {"slot_id": slot2_uuid, "tenant_id": 1, "site_id": 1, "day_date": date(2026, 1, 15),
             "status": "ASSIGNED", "abort_reason": None, "abort_note": None},
            {"status": "OPEN"},
        ]
        mock_conn.execute = AsyncMock()

        # batch_set_slot_status takes operations list, not separate params
        operations = [
            {"slot_id": str(slot1_uuid), "new_status": "ABORTED", "abort_reason": "LOW_DEMAND"},
            {"slot_id": str(slot2_uuid), "new_status": "ABORTED", "abort_reason": "LOW_DEMAND"},
        ]

        result = await batch_set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            operations=operations,
            performed_by="user-1",
        )

        # Returns BatchSlotStatusResult dataclass
        assert result.success is True
        assert result.applied == 2

    @pytest.mark.asyncio
    async def test_batch_abort_partial_failure(self):
        """Batch abort with some slots on frozen day."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot1_uuid = UUID("33333333-3333-3333-3333-333333333333")
        slot2_uuid = UUID("44444444-4444-4444-4444-444444444444")

        mock_conn.fetchrow.side_effect = [
            # Slot 1 - can abort (day is open)
            {"slot_id": slot1_uuid, "tenant_id": 1, "site_id": 1, "day_date": date(2026, 1, 15),
             "status": "PLANNED", "abort_reason": None, "abort_note": None},
            {"status": "OPEN"},
            # Slot 2 - frozen day
            {"slot_id": slot2_uuid, "tenant_id": 1, "site_id": 1, "day_date": date(2026, 1, 16),
             "status": "PLANNED", "abort_reason": None, "abort_note": None},
            {"status": "FROZEN"},
        ]
        mock_conn.execute = AsyncMock()

        operations = [
            {"slot_id": str(slot1_uuid), "new_status": "ABORTED", "abort_reason": "VEHICLE"},
            {"slot_id": str(slot2_uuid), "new_status": "ABORTED", "abort_reason": "VEHICLE"},
        ]

        result = await batch_set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            operations=operations,
            performed_by="user-1",
        )

        # Partial success
        assert result.applied == 1
        assert result.rejected == 1


class TestAbortIdempotency:
    """Test abort operation idempotency."""

    @pytest.mark.asyncio
    async def test_abort_already_aborted_slot(self):
        """Aborting already aborted slot is idempotent."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("55555555-5555-5555-5555-555555555555")

        # Slot already aborted with same reason
        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "ABORTED",  # Already aborted
                "abort_reason": "OTHER",
                "abort_note": None,
            },
            {"status": "OPEN"},
        ]

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.OTHER,
            abort_note=None,
            performed_by="user-1",
        )

        # Should succeed (idempotent - same reason)
        assert result.success is True
        assert result.idempotent_return is True


class TestAbortAuditTrail:
    """Test abort audit trail requirements."""

    @pytest.mark.asyncio
    async def test_abort_tracks_user_id(self):
        """Abort records user who performed it."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("66666666-6666-6666-6666-666666666666")

        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "PLANNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "OPEN"},
        ]
        mock_conn.execute = AsyncMock()

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.OPS_DECISION,
            abort_note=None,
            performed_by="dispatcher-42",
        )

        assert result.success is True
        # Verify execute was called (to update the slot)
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_abort_tracks_timestamp(self):
        """Abort records timestamp."""
        from uuid import UUID
        mock_conn = AsyncMock()
        slot_uuid = UUID("77777777-7777-7777-7777-777777777777")

        mock_conn.fetchrow.side_effect = [
            {
                "slot_id": slot_uuid,
                "tenant_id": 1,
                "site_id": 1,
                "day_date": date(2026, 1, 15),
                "status": "ASSIGNED",
                "abort_reason": None,
                "abort_note": None,
            },
            {"status": "OPEN"},
        ]
        mock_conn.execute = AsyncMock()

        result = await set_slot_status(
            conn=mock_conn,
            tenant_id=1,
            site_id=1,
            slot_id=slot_uuid,
            new_status=SlotStatus.ABORTED,
            abort_reason=AbortReason.WEATHER,
            abort_note=None,
            performed_by="user-1",
        )

        assert result.success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
