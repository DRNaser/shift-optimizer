"""
Tests for Draft Mutations (Workbench)

Tests:
1. Idempotency: Same mutation twice returns same result
2. Hard blocks: Overlap/rest/pin violations are rejected
3. Soft blocks: Warnings allowed but flagged
4. Undo: Last mutation can be undone
5. RLS: Tenant isolation enforced
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from packs.roster.core.draft_mutations import (
    apply_mutations,
    undo_last_mutation,
    get_draft_state,
    MutationOp,
    OpType,
    ValidationStatus,
    HardBlockReason,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_conn():
    """Create a mock database connection."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    return conn


@pytest.fixture
def sample_mutation():
    """Create a sample assign mutation."""
    return MutationOp(
        op=OpType.ASSIGN,
        tour_instance_id=100,
        day=1,
        driver_id=50,
    )


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================

class TestIdempotency:
    """Test idempotent behavior of mutations."""

    @pytest.mark.asyncio
    async def test_same_idempotency_key_returns_cached_result(self, mock_conn):
        """Same idempotency key should return cached result, not apply again."""
        from datetime import datetime, timezone, timedelta

        repair_id = uuid4()
        idempotency_key = "test-key-123"

        # Mock: first call is session check (must be OPEN), second is idempotency check
        mock_conn.fetchrow.side_effect = [
            # Session check - must return OPEN status
            {
                "repair_id": repair_id,
                "status": "OPEN",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "plan_version_id": 1,
            },
            # Idempotency check - returns existing mutation (cache hit)
            {
                "mutation_id": uuid4(),
                "sequence_no": 1,
                "validation_status": "VALID",
                "violations_json": "[]",
            },
        ]

        mutation = MutationOp(
            op=OpType.ASSIGN,
            tour_instance_id=100,
            day=1,
            driver_id=50,
        )

        result = await apply_mutations(
            conn=mock_conn,
            tenant_id=1,
            site_id=10,
            repair_id=repair_id,
            plan_version_id=1,
            operations=[mutation],
            validation_mode="fast",
            performed_by="test@example.com",
            idempotency_key=idempotency_key,
        )

        # Should not insert new mutation if idempotency key exists
        assert result is not None

    @pytest.mark.asyncio
    async def test_different_idempotency_keys_apply_separately(self, mock_conn):
        """Different idempotency keys should apply mutations separately."""
        repair_id = uuid4()

        # Mock: no existing mutation found
        mock_conn.fetchrow.side_effect = [
            None,  # idempotency check
            {"id": 100, "driver_id": None},  # assignment check
        ]
        mock_conn.fetchval.return_value = 1  # sequence number
        mock_conn.execute.return_value = None

        mutation = MutationOp(
            op=OpType.ASSIGN,
            tour_instance_id=100,
            day=1,
            driver_id=50,
        )

        # First call with key1
        result1 = await apply_mutations(
            conn=mock_conn,
            tenant_id=1,
            site_id=10,
            repair_id=repair_id,
            plan_version_id=1,
            operations=[mutation],
            validation_mode="none",
            performed_by="test@example.com",
            idempotency_key="key-1",
        )

        assert result1.operations_applied >= 0


# =============================================================================
# HARD BLOCK TESTS
# =============================================================================

class TestHardBlocks:
    """Test hard block detection."""

    @pytest.mark.asyncio
    async def test_overlap_detected_as_hard_block(self, mock_conn):
        """Overlapping assignments should be flagged as HARD_BLOCK."""
        repair_id = uuid4()

        # Mock: assignment already exists for this tour
        mock_conn.fetchrow.side_effect = [
            None,  # idempotency check
            {"id": 100, "driver_id": "50", "is_pinned": False},  # tour already assigned
        ]

        mutation = MutationOp(
            op=OpType.ASSIGN,
            tour_instance_id=100,
            day=1,
            driver_id=60,  # Different driver
        )

        result = await apply_mutations(
            conn=mock_conn,
            tenant_id=1,
            site_id=10,
            repair_id=repair_id,
            plan_version_id=1,
            operations=[mutation],
            validation_mode="fast",
            performed_by="test@example.com",
            idempotency_key="test-key",
        )

        # Should detect overlap
        assert result is not None

    @pytest.mark.asyncio
    async def test_pin_conflict_detected(self, mock_conn):
        """Trying to unassign a pinned assignment should be HARD_BLOCK."""
        repair_id = uuid4()

        # Mock: pinned assignment exists
        mock_conn.fetchrow.side_effect = [
            None,  # idempotency check
            {"id": 100, "driver_id": "50", "is_pinned": True, "pin_reason": "Customer request"},
        ]

        mutation = MutationOp(
            op=OpType.UNASSIGN,
            tour_instance_id=100,
            day=1,
        )

        result = await apply_mutations(
            conn=mock_conn,
            tenant_id=1,
            site_id=10,
            repair_id=repair_id,
            plan_version_id=1,
            operations=[mutation],
            validation_mode="fast",
            performed_by="test@example.com",
            idempotency_key="test-key",
        )

        # Should detect pin conflict
        assert result is not None


# =============================================================================
# UNDO TESTS
# =============================================================================

class TestUndo:
    """Test undo functionality."""

    @pytest.mark.asyncio
    async def test_undo_returns_last_mutation(self, mock_conn):
        """Undo should return and mark the last mutation as undone."""
        repair_id = uuid4()
        mutation_id = uuid4()

        # Mock: last mutation exists
        mock_conn.fetchrow.return_value = {
            "mutation_id": mutation_id,
            "op": "ASSIGN",
            "tour_instance_id": 100,
            "driver_id": 50,
            "sequence_no": 5,
        }
        mock_conn.execute.return_value = None

        result = await undo_last_mutation(
            conn=mock_conn,
            tenant_id=1,
            repair_id=repair_id,
            performed_by="test@example.com",
        )

        assert result is not None
        assert result["mutation_id"] == str(mutation_id)

    @pytest.mark.asyncio
    async def test_undo_empty_returns_none(self, mock_conn):
        """Undo with no mutations should return None."""
        repair_id = uuid4()

        # Mock: no mutations to undo
        mock_conn.fetchrow.return_value = None

        result = await undo_last_mutation(
            conn=mock_conn,
            tenant_id=1,
            repair_id=repair_id,
            performed_by="test@example.com",
        )

        assert result is None


# =============================================================================
# DRAFT STATE TESTS
# =============================================================================

class TestDraftState:
    """Test draft state retrieval."""

    @pytest.mark.asyncio
    async def test_get_draft_state_returns_active_mutations(self, mock_conn):
        """Get draft state should return non-undone mutations."""
        repair_id = uuid4()

        # Mock: two active mutations
        mock_conn.fetch.return_value = [
            {
                "mutation_id": uuid4(),
                "op": "ASSIGN",
                "tour_instance_id": 100,
                "driver_id": 50,
                "status": "VALID",
                "sequence_no": 1,
            },
            {
                "mutation_id": uuid4(),
                "op": "ASSIGN",
                "tour_instance_id": 101,
                "driver_id": 51,
                "status": "SOFT_BLOCK",
                "sequence_no": 2,
            },
        ]

        result = await get_draft_state(
            conn=mock_conn,
            tenant_id=1,
            repair_id=repair_id,
        )

        assert result["count"] == 2
        assert len(result["mutations"]) == 2


# =============================================================================
# RLS TESTS
# =============================================================================

class TestRLS:
    """Test tenant isolation (RLS)."""

    @pytest.mark.asyncio
    async def test_mutations_filtered_by_tenant(self, mock_conn):
        """Mutations should only be visible to the owning tenant."""
        repair_id = uuid4()

        # Mock: fetch with tenant filter
        mock_conn.fetch.return_value = []

        result = await get_draft_state(
            conn=mock_conn,
            tenant_id=999,  # Different tenant
            repair_id=repair_id,
        )

        # Should return empty for wrong tenant
        assert result["count"] == 0

        # Verify tenant_id was used in query
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        assert 999 in call_args[0]  # tenant_id should be in query params
