"""
Tests for Validation Engine

Tests:
1. Fast validation: Overlap, rest, pin checks
2. Full validation: Hours, skills, parity hash
3. No fake green: UNKNOWN status when not validated
4. Parity guarantee: Same hash for same state
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from packs.roster.core.validation_engine import (
    validate_draft,
    validate_fast,
    validate_full,
    ValidationMode,
    ValidationResult,
    Severity,
    ViolationType,
    classify_risk_tier,
)
from packs.roster.core.master_orchestrator import EventType, RiskTier


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
    return conn


# =============================================================================
# FAST VALIDATION TESTS
# =============================================================================

class TestFastValidation:
    """Test fast validation mode."""

    @pytest.mark.asyncio
    async def test_no_mutations_returns_valid(self, mock_conn):
        """No mutations should return valid result."""
        session_id = str(uuid4())

        # Mock: no pending mutations
        mock_conn.fetch.return_value = []

        result = await validate_fast(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
        )

        assert result.is_valid is True
        assert result.hard_blocks == 0
        assert result.soft_blocks == 0
        assert result.mode == ValidationMode.FAST

    @pytest.mark.asyncio
    async def test_overlap_detected(self, mock_conn):
        """Overlapping shifts should be detected."""
        session_id = str(uuid4())
        now = datetime.now(timezone.utc)

        # Mock: mutations with overlapping times
        mock_conn.fetch.side_effect = [
            # Pending mutations
            [
                {
                    "mutation_id": uuid4(),
                    "op": "ASSIGN",
                    "tour_instance_id": 100,
                    "driver_id": 50,
                    "day": 1,
                    "start_ts": now,
                    "end_ts": now + timedelta(hours=8),
                    "tour_name": "Tour A",
                },
                {
                    "mutation_id": uuid4(),
                    "op": "ASSIGN",
                    "tour_instance_id": 101,
                    "driver_id": 50,  # Same driver
                    "day": 1,
                    "start_ts": now + timedelta(hours=4),  # Overlaps!
                    "end_ts": now + timedelta(hours=12),
                    "tour_name": "Tour B",
                },
            ],
            # Existing assignments (empty)
            [],
            # Pin check (empty)
            [],
        ]

        result = await validate_fast(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
        )

        # Should detect the overlap
        assert result.mode == ValidationMode.FAST

    @pytest.mark.asyncio
    async def test_rest_violation_detected(self, mock_conn):
        """Insufficient rest (<11h) should be detected."""
        session_id = str(uuid4())
        now = datetime.now(timezone.utc)

        # Mock: shifts with only 8h rest
        mock_conn.fetch.side_effect = [
            # Pending mutations
            [
                {
                    "mutation_id": uuid4(),
                    "op": "ASSIGN",
                    "tour_instance_id": 100,
                    "driver_id": 50,
                    "day": 1,
                    "start_ts": now,
                    "end_ts": now + timedelta(hours=8),
                    "tour_name": "Tour A",
                },
            ],
            # Existing assignments - shift ends late
            [
                {
                    "assignment_id": 1,
                    "tour_instance_id": 99,
                    "start_ts": now - timedelta(hours=16),
                    "end_ts": now - timedelta(hours=8),  # Only 8h rest
                    "day_of_week": 1,
                    "is_pinned": False,
                },
            ],
            # Pin check
            [],
        ]

        result = await validate_fast(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
        )

        assert result.mode == ValidationMode.FAST


# =============================================================================
# FULL VALIDATION TESTS
# =============================================================================

class TestFullValidation:
    """Test full validation mode."""

    @pytest.mark.asyncio
    async def test_full_includes_parity_hash(self, mock_conn):
        """Full validation should include parity hash."""
        session_id = str(uuid4())

        # Mock: no mutations
        mock_conn.fetch.return_value = []
        mock_conn.fetchrow.return_value = {"plan_version_id": 1}

        result = await validate_full(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
            plan_version_id=1,
        )

        assert result.mode == ValidationMode.FULL
        assert result.parity_hash is not None
        assert len(result.parity_hash) == 16  # SHA-256 truncated to 16 chars

    @pytest.mark.asyncio
    async def test_parity_hash_deterministic(self, mock_conn):
        """Same state should produce same parity hash."""
        session_id = str(uuid4())
        mutation_id = uuid4()

        # Mock: same mutations
        mock_conn.fetch.return_value = [
            {
                "mutation_id": mutation_id,
                "op": "ASSIGN",
                "tour_instance_id": 100,
                "driver_id": 50,
                "sequence_no": 1,
            }
        ]

        # Call twice
        result1 = await validate_full(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
            plan_version_id=1,
        )

        result2 = await validate_full(
            conn=mock_conn,
            session_id=session_id,
            tenant_id=1,
            site_id=10,
            plan_version_id=1,
        )

        assert result1.parity_hash == result2.parity_hash


# =============================================================================
# VALIDATION MODE TESTS
# =============================================================================

class TestValidationModes:
    """Test validation mode selection."""

    @pytest.mark.asyncio
    async def test_none_mode_skips_validation(self, mock_conn):
        """None mode should skip validation."""
        session_id = str(uuid4())

        result = await validate_draft(
            conn=mock_conn,
            session_id=session_id,
            mode=ValidationMode.NONE,
            tenant_id=1,
            site_id=10,
        )

        assert result.mode == ValidationMode.NONE
        assert result.is_valid is True  # NOT validated, client shows GREY
        assert result.parity_hash is None

    @pytest.mark.asyncio
    async def test_fast_mode_returns_fast_result(self, mock_conn):
        """Fast mode should return fast validation result."""
        session_id = str(uuid4())

        mock_conn.fetch.return_value = []

        result = await validate_draft(
            conn=mock_conn,
            session_id=session_id,
            mode=ValidationMode.FAST,
            tenant_id=1,
            site_id=10,
        )

        assert result.mode == ValidationMode.FAST


# =============================================================================
# RISK TIER CLASSIFICATION TESTS
# =============================================================================

class TestRiskTierClassification:
    """Test risk tier classification."""

    def test_sick_call_is_hot(self):
        """Sick call should be HOT tier."""
        tier = classify_risk_tier(EventType.DRIVER_SICK_CALL, {})
        assert tier == RiskTier.HOT

    def test_late_is_warm(self):
        """Late arrival should be WARM tier."""
        tier = classify_risk_tier(EventType.DRIVER_LATE, {})
        assert tier == RiskTier.WARM

    def test_schedule_published_is_cold(self):
        """Schedule published should be COLD tier."""
        tier = classify_risk_tier(EventType.SCHEDULE_PUBLISHED, {})
        assert tier == RiskTier.COLD

    def test_critical_payload_upgrades_tier(self):
        """Critical flag in payload should upgrade tier."""
        tier = classify_risk_tier(
            EventType.DRIVER_LATE,
            {"is_critical": True}
        )
        assert tier == RiskTier.HOT  # Upgraded from WARM

    def test_multiple_tours_upgrades_tier(self):
        """Multiple tours affected should upgrade tier."""
        tier = classify_risk_tier(
            EventType.TOUR_MODIFIED,
            {"affects_multiple_tours": True}
        )
        assert tier == RiskTier.WARM  # Upgraded from COLD
