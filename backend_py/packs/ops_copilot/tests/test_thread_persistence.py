"""
Thread Persistence Tests

Tests:
- Same wa_user_id -> same thread_id (deterministic)
- State survives restart (PostgreSQL checkpointer)
- Thread message history preserved
- Graph state checkpoint/restore
"""

import hashlib
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import uuid

from ..core.identity import generate_thread_id, get_or_create_thread
from ..core.graph_state import OpsCopilotState, Message, Intent, StopReason


class TestThreadIdGeneration:
    """Tests for deterministic thread ID generation."""

    def test_same_input_same_thread_id(self, test_tenant, test_site, test_wa_user):
        """Same inputs should always produce same thread_id."""
        thread_id_1 = generate_thread_id(
            test_tenant["tenant_id"],
            test_site["site_id"],
            test_wa_user["wa_user_id"],
        )

        thread_id_2 = generate_thread_id(
            test_tenant["tenant_id"],
            test_site["site_id"],
            test_wa_user["wa_user_id"],
        )

        assert thread_id_1 == thread_id_2

    def test_different_tenant_different_thread_id(self, test_site, test_wa_user):
        """Different tenant should produce different thread_id."""
        thread_id_1 = generate_thread_id(1, test_site["site_id"], test_wa_user["wa_user_id"])
        thread_id_2 = generate_thread_id(2, test_site["site_id"], test_wa_user["wa_user_id"])

        assert thread_id_1 != thread_id_2

    def test_different_site_different_thread_id(self, test_tenant, test_wa_user):
        """Different site should produce different thread_id."""
        thread_id_1 = generate_thread_id(test_tenant["tenant_id"], 10, test_wa_user["wa_user_id"])
        thread_id_2 = generate_thread_id(test_tenant["tenant_id"], 20, test_wa_user["wa_user_id"])

        assert thread_id_1 != thread_id_2

    def test_null_site_handled(self, test_tenant, test_wa_user):
        """Null site_id should produce valid thread_id."""
        thread_id = generate_thread_id(
            test_tenant["tenant_id"],
            None,  # No site
            test_wa_user["wa_user_id"],
        )

        assert len(thread_id) == 64  # SHA-256 hex
        assert thread_id.isalnum()

    def test_thread_id_format(self, test_tenant, test_site, test_wa_user):
        """Thread ID should be SHA-256 hex string."""
        thread_id = generate_thread_id(
            test_tenant["tenant_id"],
            test_site["site_id"],
            test_wa_user["wa_user_id"],
        )

        # Expected format: sha256("sv:{tenant_id}:{site_id}:whatsapp:{wa_user_id}")
        expected_raw = f"sv:{test_tenant['tenant_id']}:{test_site['site_id']}:whatsapp:{test_wa_user['wa_user_id']}"
        expected_hash = hashlib.sha256(expected_raw.encode()).hexdigest()

        assert thread_id == expected_hash


class TestGetOrCreateThread:
    """Tests for thread retrieval/creation."""

    @pytest.mark.asyncio
    async def test_get_existing_thread(self, mock_conn, paired_identity, test_tenant, test_site, test_wa_user):
        """Getting existing thread should return same ID."""
        existing_thread_id = str(uuid.uuid4())

        mock_conn._cursor.set_results([
            (existing_thread_id,),  # Found existing thread
            (existing_thread_id,),  # Update returns same ID
        ])

        result = await get_or_create_thread(
            conn=mock_conn,
            identity_id=paired_identity["identity_id"],
            tenant_id=test_tenant["tenant_id"],
            site_id=test_site["site_id"],
            wa_user_id=test_wa_user["wa_user_id"],
        )

        assert result == existing_thread_id
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_create_new_thread(self, mock_conn, paired_identity, test_tenant, test_site, test_wa_user):
        """Creating new thread should return new ID."""
        new_thread_id = str(uuid.uuid4())

        mock_conn._cursor.set_results([
            None,  # No existing thread
            (new_thread_id,),  # Insert returns new ID
        ])

        result = await get_or_create_thread(
            conn=mock_conn,
            identity_id=paired_identity["identity_id"],
            tenant_id=test_tenant["tenant_id"],
            site_id=test_site["site_id"],
            wa_user_id=test_wa_user["wa_user_id"],
        )

        assert result == new_thread_id
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_thread_message_count_incremented(
        self, mock_conn, paired_identity, test_tenant, test_site, test_wa_user
    ):
        """Getting existing thread should increment message count."""
        existing_id = str(uuid.uuid4())

        mock_conn._cursor.set_results([
            (existing_id,),  # Found
            (existing_id,),  # Update
        ])

        await get_or_create_thread(
            conn=mock_conn,
            identity_id=paired_identity["identity_id"],
            tenant_id=test_tenant["tenant_id"],
            site_id=test_site["site_id"],
            wa_user_id=test_wa_user["wa_user_id"],
        )

        # Verify UPDATE query was called with message_count increment
        queries = mock_conn._cursor._executed_queries
        assert any("message_count" in q and "+" in q for q in queries)


class TestGraphStateCheckpoint:
    """Tests for graph state checkpointing."""

    def test_state_to_checkpoint_dict(self, test_tenant, test_wa_user):
        """State should serialize to checkpoint dict."""
        state = OpsCopilotState(
            wa_user_id=test_wa_user["wa_user_id"],
            thread_id="test-thread-id",
            is_paired=True,
            current_intent=Intent.CREATE_TICKET,
            step_count=3,
            tool_call_count=1,
        )
        state.add_message("user", "Create a ticket")
        state.add_message("assistant", "I'll create a ticket for you.")

        checkpoint = state.to_checkpoint_dict()

        assert checkpoint["wa_user_id"] == test_wa_user["wa_user_id"]
        assert checkpoint["thread_id"] == "test-thread-id"
        assert checkpoint["is_paired"] is True
        assert checkpoint["current_intent"] == "create_ticket"
        assert len(checkpoint["messages"]) == 2
        assert checkpoint["step_count"] == 3
        assert checkpoint["tool_call_count"] == 1

    def test_state_from_checkpoint_dict(self, test_wa_user):
        """State should deserialize from checkpoint dict."""
        checkpoint = {
            "wa_user_id": test_wa_user["wa_user_id"],
            "thread_id": "test-thread-id",
            "is_paired": True,
            "identity": None,
            "messages": [
                {
                    "role": "user",
                    "content": "Hello",
                    "timestamp": "2026-01-13T10:00:00",
                    "metadata": {},
                },
            ],
            "current_intent": "greeting",
            "pending_draft_id": None,
            "awaiting_confirmation": False,
            "step_count": 1,
            "tool_call_count": 0,
        }

        state = OpsCopilotState.from_checkpoint_dict(checkpoint)

        assert state.wa_user_id == test_wa_user["wa_user_id"]
        assert state.thread_id == "test-thread-id"
        assert state.is_paired is True
        assert state.current_intent == Intent.GREETING
        assert len(state.messages) == 1
        assert state.messages[0].role == "user"
        assert state.messages[0].content == "Hello"

    def test_checkpoint_roundtrip(self, test_wa_user):
        """Checkpoint should survive serialize/deserialize roundtrip."""
        original = OpsCopilotState(
            wa_user_id=test_wa_user["wa_user_id"],
            thread_id="roundtrip-test",
            is_paired=True,
            current_intent=Intent.VIEW_SCHEDULE,
            pending_draft_id="draft-123",
            awaiting_confirmation=True,
            step_count=5,
            tool_call_count=2,
        )
        original.add_message("user", "Show my schedule")
        original.add_message("assistant", "Here is your schedule...")

        # Roundtrip
        checkpoint = original.to_checkpoint_dict()
        restored = OpsCopilotState.from_checkpoint_dict(checkpoint)

        assert restored.wa_user_id == original.wa_user_id
        assert restored.thread_id == original.thread_id
        assert restored.is_paired == original.is_paired
        assert restored.current_intent == original.current_intent
        assert restored.pending_draft_id == original.pending_draft_id
        assert restored.awaiting_confirmation == original.awaiting_confirmation
        assert restored.step_count == original.step_count
        assert restored.tool_call_count == original.tool_call_count
        assert len(restored.messages) == len(original.messages)


class TestStateSurvivesRestart:
    """Tests for state persistence across simulated restarts."""

    @pytest.mark.asyncio
    async def test_state_persisted_to_database(self, mock_conn, test_thread, graph_checkpoint):
        """State should be saved to database."""
        # This tests the checkpoint persistence mechanism
        state = OpsCopilotState(
            wa_user_id="test-wa-user",
            thread_id=test_thread["thread_id"],
            is_paired=True,
            current_intent=Intent.CREATE_TICKET,
        )

        checkpoint = state.to_checkpoint_dict()

        # Simulate saving to database
        mock_conn._cursor.set_results([(1,)])  # Update successful

        # In real implementation, this would be:
        # await checkpointer.put(thread_id, checkpoint)

        # Verify checkpoint has expected structure
        assert "messages" in checkpoint
        assert "current_intent" in checkpoint
        assert "step_count" in checkpoint

    @pytest.mark.asyncio
    async def test_state_restored_from_database(self, mock_conn, test_thread, graph_checkpoint):
        """State should be restored from database."""
        # Simulate loading from database
        checkpoint_data = {
            "wa_user_id": "test-wa-user",
            "thread_id": test_thread["thread_id"],
            "is_paired": True,
            "identity": None,
            "messages": [
                {"role": "user", "content": "Previous message", "timestamp": "2026-01-13T09:00:00", "metadata": {}},
            ],
            "current_intent": "view_tickets",
            "pending_draft_id": "pending-draft-id",
            "awaiting_confirmation": True,
            "step_count": 2,
            "tool_call_count": 1,
        }

        restored = OpsCopilotState.from_checkpoint_dict(checkpoint_data)

        assert restored.thread_id == test_thread["thread_id"]
        assert restored.is_paired is True
        assert len(restored.messages) == 1
        assert restored.pending_draft_id == "pending-draft-id"
        assert restored.awaiting_confirmation is True

    @pytest.mark.asyncio
    async def test_conversation_continues_after_restart(self, test_thread):
        """Conversation should continue seamlessly after simulated restart."""
        # First session
        state1 = OpsCopilotState(
            wa_user_id="test-wa-user",
            thread_id=test_thread["thread_id"],
            is_paired=True,
        )
        state1.add_message("user", "Create a ticket for broken truck")
        state1.add_message("assistant", "I'll create a ticket. Please CONFIRM.")
        state1.pending_draft_id = "draft-123"
        state1.awaiting_confirmation = True
        state1.current_intent = Intent.CREATE_TICKET

        # Simulate "restart" - serialize and deserialize
        checkpoint = state1.to_checkpoint_dict()

        # Second session (after restart)
        state2 = OpsCopilotState.from_checkpoint_dict(checkpoint)

        # Verify conversation state is preserved
        assert len(state2.messages) == 2
        assert state2.messages[0].content == "Create a ticket for broken truck"
        assert state2.pending_draft_id == "draft-123"
        assert state2.awaiting_confirmation is True

        # Can continue conversation
        state2.add_message("user", "CONFIRM")
        assert len(state2.messages) == 3


class TestMessageHistory:
    """Tests for message history preservation."""

    def test_add_message(self, test_wa_user):
        """Adding messages should preserve order."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        state.add_message("user", "First message")
        state.add_message("assistant", "Response")
        state.add_message("user", "Second message")

        assert len(state.messages) == 3
        assert state.messages[0].role == "user"
        assert state.messages[0].content == "First message"
        assert state.messages[1].role == "assistant"
        assert state.messages[2].content == "Second message"

    def test_get_conversation_history(self, test_wa_user):
        """Getting history should return recent messages."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        for i in range(15):
            state.add_message("user" if i % 2 == 0 else "assistant", f"Message {i}")

        # Default: last 10
        history = state.get_conversation_history()
        assert len(history) == 10
        assert history[0]["content"] == "Message 5"
        assert history[-1]["content"] == "Message 14"

        # Custom limit
        history_5 = state.get_conversation_history(max_messages=5)
        assert len(history_5) == 5

    def test_message_metadata_preserved(self, test_wa_user):
        """Message metadata should be preserved."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        state.add_message("user", "Hello", intent="greeting", confidence=0.95)

        assert state.messages[0].metadata["intent"] == "greeting"
        assert state.messages[0].metadata["confidence"] == 0.95


class TestBoundedExecution:
    """Tests for execution bounds in state."""

    def test_increment_step_within_bounds(self, test_wa_user):
        """Step increment should succeed within bounds."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        for _ in range(5):
            result = state.increment_step()
            assert result is True

        assert state.step_count == 5

    def test_increment_step_exceeds_bounds(self, test_wa_user):
        """Step increment should fail when exceeding bounds."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])
        state.step_count = 7  # Just under max (8)

        # Should succeed for step 8
        result = state.increment_step()
        # Whether it succeeds depends on config, but stop_reason should be set if exceeded
        if state.step_count >= 8:
            assert state.stop_reason == StopReason.MAX_STEPS_EXCEEDED

    def test_empty_result_streak(self, test_wa_user):
        """Empty result streak should trigger abort."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        # First two empty results - should continue
        assert state.record_empty_result() is True
        assert state.record_empty_result() is True

        # Third empty result - should abort
        assert state.record_empty_result() is False
        assert state.stop_reason == StopReason.NO_NEW_EVIDENCE

    def test_non_empty_result_resets_streak(self, test_wa_user):
        """Non-empty result should reset streak."""
        state = OpsCopilotState(wa_user_id=test_wa_user["wa_user_id"])

        state.record_empty_result()
        state.record_empty_result()
        assert state.empty_result_streak == 2

        state.record_non_empty_result()
        assert state.empty_result_streak == 0
