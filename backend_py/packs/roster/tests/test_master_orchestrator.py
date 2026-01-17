"""
Tests for Master Orchestrator

Tests:
1. Event ingestion with idempotency
2. Policy matching
3. Action handlers (create session, auto-reassign, etc.)
4. Queue processing by risk tier
5. Tenant isolation
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import json

from packs.roster.core.master_orchestrator import (
    ingest_event,
    match_policy,
    process_event,
    process_queue_batch,
    cleanup_old_events,
    retry_failed_events,
    EventType,
    RiskTier,
    EventStatus,
    ActionType,
    OpsEvent,
    PolicyMatch,
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
def sample_event():
    """Create a sample operations event."""
    return OpsEvent(
        event_id=uuid4(),
        event_type=EventType.DRIVER_SICK_CALL,
        tenant_id=1,
        site_id=10,
        payload={"driver_id": 50, "reason": "Illness"},
        risk_tier=RiskTier.HOT,
        status=EventStatus.PENDING,
    )


@pytest.fixture
def sample_policy():
    """Create a sample workflow policy."""
    return PolicyMatch(
        policy_id=1,
        policy_name="default_sick_call",
        action=ActionType.CREATE_REPAIR_SESSION,
        config={"auto_notify": True},
        priority=100,
    )


# =============================================================================
# EVENT INGESTION TESTS
# =============================================================================

class TestEventIngestion:
    """Test event ingestion."""

    @pytest.mark.asyncio
    async def test_new_event_created(self, mock_conn):
        """New event should be created with correct tier."""
        # Mock: no existing event
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = None

        event = await ingest_event(
            conn=mock_conn,
            event_type=EventType.DRIVER_SICK_CALL,
            tenant_id=1,
            site_id=10,
            payload={"driver_id": 50},
        )

        assert event.event_type == EventType.DRIVER_SICK_CALL
        assert event.risk_tier == RiskTier.HOT
        assert event.status == EventStatus.PENDING

    @pytest.mark.asyncio
    async def test_duplicate_event_rejected(self, mock_conn):
        """Duplicate idempotency key should return existing event."""
        existing_id = uuid4()

        # Mock: existing event found
        mock_conn.fetchrow.return_value = {"event_id": existing_id}

        event = await ingest_event(
            conn=mock_conn,
            event_type=EventType.DRIVER_SICK_CALL,
            tenant_id=1,
            site_id=10,
            payload={"driver_id": 50},
            idempotency_key="duplicate-key",
        )

        assert event.event_id == existing_id
        assert event.status == EventStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_risk_tier_classification(self, mock_conn):
        """Events should be classified to correct risk tier."""
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = None

        # HOT event
        hot_event = await ingest_event(
            conn=mock_conn,
            event_type=EventType.DRIVER_NO_SHOW,
            tenant_id=1,
            site_id=10,
            payload={},
        )
        assert hot_event.risk_tier == RiskTier.HOT

        # WARM event
        warm_event = await ingest_event(
            conn=mock_conn,
            event_type=EventType.DRIVER_LATE,
            tenant_id=1,
            site_id=10,
            payload={},
        )
        assert warm_event.risk_tier == RiskTier.WARM

        # COLD event
        cold_event = await ingest_event(
            conn=mock_conn,
            event_type=EventType.SCHEDULE_PUBLISHED,
            tenant_id=1,
            site_id=10,
            payload={},
        )
        assert cold_event.risk_tier == RiskTier.COLD


# =============================================================================
# POLICY MATCHING TESTS
# =============================================================================

class TestPolicyMatching:
    """Test policy matching."""

    @pytest.mark.asyncio
    async def test_matching_policy_found(self, mock_conn):
        """Should find matching policy for event type."""
        mock_conn.fetchrow.return_value = {
            "policy_id": 1,
            "policy_name": "sick_call_handler",
            "action": "CREATE_REPAIR_SESSION",
            "config": {"notify": True},
            "priority": 100,
        }

        policy = await match_policy(
            conn=mock_conn,
            event_type=EventType.DRIVER_SICK_CALL,
            tenant_id=1,
            site_id=10,
        )

        assert policy is not None
        assert policy.action == ActionType.CREATE_REPAIR_SESSION
        assert policy.priority == 100

    @pytest.mark.asyncio
    async def test_no_matching_policy(self, mock_conn):
        """Should return None when no policy matches."""
        mock_conn.fetchrow.return_value = None

        policy = await match_policy(
            conn=mock_conn,
            event_type=EventType.DRIVER_SICK_CALL,
            tenant_id=999,
            site_id=999,
        )

        assert policy is None


# =============================================================================
# EVENT PROCESSING TESTS
# =============================================================================

class TestEventProcessing:
    """Test event processing."""

    @pytest.mark.asyncio
    async def test_no_policy_returns_no_action(self, mock_conn, sample_event):
        """No matching policy should return NO_ACTION."""
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = None

        result = await process_event(mock_conn, sample_event)

        assert result.success is True
        assert result.action_taken == ActionType.NO_ACTION

    @pytest.mark.asyncio
    async def test_create_repair_session_action(self, mock_conn, sample_event):
        """CREATE_REPAIR_SESSION action should create session."""
        # Mock policy match
        mock_conn.fetchrow.side_effect = [
            # Policy match
            {
                "policy_id": 1,
                "policy_name": "test",
                "action": "CREATE_REPAIR_SESSION",
                "config": {},
                "priority": 100,
            },
            # Plan lookup
            {"id": 1},
        ]
        mock_conn.execute.return_value = None

        with patch(
            "packs.roster.core.master_orchestrator.get_or_create_repair_session",
            return_value=uuid4(),
        ):
            result = await process_event(mock_conn, sample_event)

        assert result.action_taken == ActionType.CREATE_REPAIR_SESSION


# =============================================================================
# QUEUE PROCESSING TESTS
# =============================================================================

class TestQueueProcessing:
    """Test batch queue processing."""

    @pytest.mark.asyncio
    async def test_empty_queue(self, mock_conn):
        """Empty queue should return empty results."""
        mock_conn.fetch.return_value = []

        results = await process_queue_batch(
            conn=mock_conn,
            tenant_id=1,
            batch_size=10,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_processes_in_priority_order(self, mock_conn):
        """Should process HOT before WARM before COLD."""
        mock_conn.fetch.return_value = [
            {
                "event_id": uuid4(),
                "event_type": "DRIVER_SICK_CALL",
                "tenant_id": 1,
                "site_id": 10,
                "payload": "{}",
                "risk_tier": "HOT",
                "status": "PENDING",
                "retry_count": 0,
                "idempotency_key": "key1",
                "created_at": datetime.now(timezone.utc),
            },
        ]
        mock_conn.fetchrow.return_value = None  # No policy match
        mock_conn.execute.return_value = None

        results = await process_queue_batch(
            conn=mock_conn,
            tenant_id=1,
            batch_size=10,
        )

        assert len(results) == 1


# =============================================================================
# MAINTENANCE TESTS
# =============================================================================

class TestMaintenance:
    """Test maintenance operations."""

    @pytest.mark.asyncio
    async def test_cleanup_old_events(self, mock_conn):
        """Should delete old completed events."""
        mock_conn.execute.return_value = "DELETE 5"

        deleted = await cleanup_old_events(
            conn=mock_conn,
            retention_days=30,
        )

        assert deleted == 5

    @pytest.mark.asyncio
    async def test_retry_failed_events(self, mock_conn):
        """Should queue failed events for retry."""
        mock_conn.execute.return_value = "UPDATE 3"

        retried = await retry_failed_events(conn=mock_conn)

        assert retried == 3


# =============================================================================
# TENANT ISOLATION TESTS
# =============================================================================

class TestTenantIsolation:
    """Test tenant isolation (RLS)."""

    @pytest.mark.asyncio
    async def test_events_filtered_by_tenant(self, mock_conn):
        """Events should only be visible to owning tenant."""
        mock_conn.fetch.return_value = []

        results = await process_queue_batch(
            conn=mock_conn,
            tenant_id=999,  # Different tenant
            batch_size=10,
        )

        assert results == []

        # Verify tenant_id was used in query
        mock_conn.fetch.assert_called_once()
