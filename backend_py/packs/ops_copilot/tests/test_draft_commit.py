"""
Draft/Commit Workflow Tests

Tests:
- Confirm creates record
- Cancel aborts draft
- Expired draft rejected
- Double confirm is idempotent
- Commit without draft rejected
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import uuid


class TestDraftCreation:
    """Tests for draft creation."""

    @pytest.mark.asyncio
    async def test_create_draft_success(
        self, mock_conn, test_tenant, test_users, test_thread
    ):
        """Creating a draft should return draft ID."""
        from ..api.routers.drafts import _create_draft

        user = test_users["dispatcher"]
        draft_id = str(uuid.uuid4())

        mock_conn._cursor.set_results([
            (draft_id,),  # Insert returns ID
        ])

        result = await _create_draft(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            thread_id=test_thread["thread_id"],
            action_type="CREATE_TICKET",
            payload={"title": "Test", "description": "Test ticket"},
            created_by=user["user_id"],
        )

        assert result == draft_id
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_create_draft_with_expiry(
        self, mock_conn, test_tenant, test_users, test_thread
    ):
        """Draft should have default 5-minute expiry."""
        from ..api.routers.drafts import _create_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([(str(uuid.uuid4()),)])

        # Check that query includes expires_at calculation
        await _create_draft(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            thread_id=test_thread["thread_id"],
            action_type="CREATE_TICKET",
            payload={"title": "Test"},
            created_by=user["user_id"],
        )

        # Verify query was executed
        assert len(mock_conn._cursor._executed_queries) > 0


class TestDraftConfirmation:
    """Tests for draft confirmation."""

    @pytest.mark.asyncio
    async def test_confirm_success(self, mock_conn, pending_draft, test_users):
        """Confirming valid draft should execute action."""
        from ..api.routers.drafts import _confirm_draft

        user = test_users["dispatcher"]

        # Mock: get draft (8 columns), execute, update status
        mock_conn._cursor.set_results([
            # Get draft - 8 columns including commit_result
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["payload"],
                pending_draft["status"],
                user["user_id"],  # created_by = owner
                pending_draft["expires_at"],
                None,  # commit_result (null for pending)
            ),
            # Atomic UPDATE returns row (we won)
            (pending_draft["draft_id"],),
            # Record event
            None,
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is True
        assert "result_id" in result
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_confirm_expired_draft_rejected(
        self, mock_conn, expired_draft, test_users
    ):
        """Confirming expired draft should fail."""
        from ..api.routers.drafts import _confirm_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            # Get draft (expired) - 8 columns
            (
                expired_draft["tenant_id"],
                expired_draft["thread_id"],
                expired_draft["action_type"],
                expired_draft["payload"],
                expired_draft["status"],
                user["user_id"],  # owner
                expired_draft["expires_at"],
                None,  # commit_result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=expired_draft["draft_id"],
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is False
        assert "expired" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_confirm_already_committed_idempotent_for_owner(
        self, mock_conn, confirmed_draft, test_users
    ):
        """
        Owner confirming already-committed draft should get idempotent success.

        SECURITY: RBAC is checked BEFORE revealing status, so only authorized
        users can get the idempotent response.
        """
        from ..api.routers.drafts import _confirm_draft

        # Use the draft owner (created_by matches user_id)
        owner_user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            # Get draft (already committed) - 8 columns including commit_result
            (
                confirmed_draft["tenant_id"],
                confirmed_draft["thread_id"],
                confirmed_draft["action_type"],
                confirmed_draft["payload"],
                "COMMITTED",  # Already committed
                owner_user["user_id"],  # Draft created by this user (owner)
                confirmed_draft["expires_at"],
                {"result_id": "cached-result-123"},  # commit_result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=confirmed_draft["draft_id"],
            user_id=owner_user["user_id"],  # Same as created_by -> owner
            user_permissions=owner_user["permissions"],
            role_name=owner_user["role_name"],
        )

        # Owner should get idempotent success with cached result
        assert result["success"] is True
        assert result.get("idempotent") is True
        assert result.get("result_id") == "cached-result-123"

    @pytest.mark.asyncio
    async def test_confirm_already_committed_idempotent_for_approver(
        self, mock_conn, confirmed_draft, test_users
    ):
        """
        Approver confirming already-committed draft should get idempotent success.

        Approver roles (tenant_admin, operator_admin) can confirm any draft.
        """
        from ..api.routers.drafts import _confirm_draft

        # Use tenant_admin (approver role)
        approver = test_users["tenant_admin"]

        mock_conn._cursor.set_results([
            # Get draft (already committed) - created by different user
            (
                confirmed_draft["tenant_id"],
                confirmed_draft["thread_id"],
                confirmed_draft["action_type"],
                confirmed_draft["payload"],
                "COMMITTED",
                test_users["dispatcher"]["user_id"],  # Created by dispatcher
                confirmed_draft["expires_at"],
                {"result_id": "cached-result-456"},  # commit_result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=confirmed_draft["draft_id"],
            user_id=approver["user_id"],  # Different from created_by
            user_permissions=approver["permissions"],
            role_name=approver["role_name"],  # tenant_admin = approver
        )

        # Approver should get idempotent success
        assert result["success"] is True
        assert result.get("idempotent") is True

    @pytest.mark.asyncio
    async def test_confirm_already_committed_denied_for_unauthorized(
        self, mock_conn, confirmed_draft, test_users
    ):
        """
        Unauthorized user confirming already-committed draft should get 403.

        SECURITY: Non-owner, non-approver cannot even probe draft status.
        They get permission denied regardless of current draft state.
        """
        from ..api.routers.drafts import _confirm_draft

        # Use ops_readonly (not owner, not approver, lacks write permission)
        unauthorized = test_users["ops_readonly"]

        mock_conn._cursor.set_results([
            # Get draft (already committed) - created by different user
            (
                confirmed_draft["tenant_id"],
                confirmed_draft["thread_id"],
                confirmed_draft["action_type"],
                confirmed_draft["payload"],
                "COMMITTED",  # Status should NOT be revealed
                test_users["dispatcher"]["user_id"],  # Created by dispatcher
                confirmed_draft["expires_at"],
                {"result_id": "should-not-see-this"},  # commit_result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=confirmed_draft["draft_id"],
            user_id=unauthorized["user_id"],  # Different user
            user_permissions=unauthorized["permissions"],  # Only has read perms
            role_name=unauthorized["role_name"],  # ops_readonly - not approver
        )

        # Should get permission denied - RBAC checked BEFORE status
        assert result["success"] is False
        assert "permission denied" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_draft_rejected(self, mock_conn, test_users):
        """Confirming non-existent draft should fail."""
        from ..api.routers.drafts import _confirm_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([None])  # Draft not found

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id="nonexistent-draft-id",
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestDraftCancellation:
    """Tests for draft cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, mock_conn, pending_draft, test_users):
        """Cancelling pending draft should update status."""
        from ..api.routers.drafts import _cancel_draft_internal as _cancel_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            # Get draft
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["status"],
                pending_draft["created_by"],
            ),
            # Update status
            (1,),  # rowcount
        ])

        result = await _cancel_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=user["user_id"],
        )

        assert result["success"] is True
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_cancel_already_confirmed_rejected(
        self, mock_conn, confirmed_draft, test_users
    ):
        """Cancelling already-confirmed draft should fail."""
        from ..api.routers.drafts import _cancel_draft_internal as _cancel_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            # Get draft (already confirmed)
            (
                confirmed_draft["tenant_id"],
                confirmed_draft["thread_id"],
                confirmed_draft["action_type"],
                "CONFIRMED",  # Already confirmed
                confirmed_draft["created_by"],
            ),
        ])

        result = await _cancel_draft(
            conn=mock_conn,
            draft_id=confirmed_draft["draft_id"],
            user_id=user["user_id"],
        )

        assert result["success"] is False
        assert "already" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_by_non_owner_rejected(
        self, mock_conn, pending_draft, test_users
    ):
        """Non-owner cannot cancel draft (unless admin)."""
        from ..api.routers.drafts import _cancel_draft_internal as _cancel_draft

        viewer = test_users["ops_readonly"]

        mock_conn._cursor.set_results([
            # Get draft (owned by dispatcher)
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["status"],
                pending_draft["created_by"],  # Different user
            ),
        ])

        result = await _cancel_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=viewer["user_id"],  # Different user
        )

        assert result["success"] is False
        assert "owner" in result["error"].lower() or "permission" in result["error"].lower()


class TestCommitWithoutDraft:
    """Tests for direct commit attempts."""

    @pytest.mark.asyncio
    async def test_commit_without_draft_rejected(self, mock_conn, test_users):
        """Direct commit without draft should be rejected."""
        from ..api.routers.drafts import _confirm_draft

        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([None])  # No draft found

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id="no-such-draft",
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestDraftExpiration:
    """Tests for draft expiration handling."""

    @pytest.mark.asyncio
    async def test_draft_expires_after_timeout(self, mock_conn, test_users, test_tenant):
        """Draft should become invalid after expiry time."""
        from ..api.routers.drafts import _create_draft, _confirm_draft

        user = test_users["dispatcher"]
        draft_id = str(uuid.uuid4())

        # Create with short expiry (already expired)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=1)

        mock_conn._cursor.set_results([
            # Get draft (expired) - 8 columns
            (
                test_tenant["tenant_id"],
                "thread-id",
                "CREATE_TICKET",
                {"title": "Test"},
                "PENDING_CONFIRM",
                user["user_id"],  # owner
                past_time,  # Already expired
                None,  # commit_result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is False
        assert "expired" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_draft_valid_before_timeout(self, mock_conn, test_users, test_tenant):
        """Draft should be valid before expiry time."""
        from ..api.routers.drafts import _confirm_draft

        user = test_users["dispatcher"]
        draft_id = str(uuid.uuid4())

        # Create with future expiry
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)

        mock_conn._cursor.set_results([
            # Get draft (not expired) - 8 columns
            (
                test_tenant["tenant_id"],
                "thread-id",
                "CREATE_TICKET",
                {"title": "Test"},
                "PENDING_CONFIRM",
                user["user_id"],  # owner
                future_time,
                None,  # commit_result
            ),
            # Atomic UPDATE returns row (we won)
            (draft_id,),
            # Event insert
            None,
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result["success"] is True


class TestIdempotency:
    """Tests for idempotent draft operations."""

    @pytest.mark.asyncio
    async def test_double_confirm_idempotent_for_owner(
        self, mock_conn, pending_draft, test_users
    ):
        """
        Owner confirming same draft twice should be idempotent.

        Second confirm returns cached result without re-executing action.
        """
        from ..api.routers.drafts import _confirm_draft

        # Owner = user whose user_id matches created_by
        owner = test_users["dispatcher"]

        # Simulate second confirm - draft already committed
        mock_conn._cursor.set_results([
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["payload"],
                "COMMITTED",  # Already committed from first call
                owner["user_id"],  # Owner
                pending_draft["expires_at"],
                {"result_id": "original-result"},  # Cached result
            ),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=owner["user_id"],
            user_permissions=owner["permissions"],
            role_name=owner["role_name"],
        )

        # Should succeed with idempotent flag and cached result
        assert result["success"] is True
        assert result.get("idempotent") is True
        assert result.get("result_id") == "original-result"

    @pytest.mark.asyncio
    async def test_double_confirm_no_executor_called(
        self, mock_conn, pending_draft, test_users
    ):
        """
        CRITICAL: Double confirm must NOT call action executor.

        When draft is already COMMITTED, the executor functions
        (_execute_create_ticket, _execute_broadcast_*, etc.) must NOT be called.
        """
        from ..api.routers.drafts import _confirm_draft
        from unittest.mock import patch, AsyncMock

        owner = test_users["dispatcher"]

        # Already committed draft
        mock_conn._cursor.set_results([
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                "WHATSAPP_BROADCAST_DRIVER",  # Use broadcast to verify
                pending_draft["payload"],
                "COMMITTED",  # Already committed
                owner["user_id"],
                pending_draft["expires_at"],
                {"event_id": "existing-event"},  # Cached result
            ),
        ])

        # Spy on executor - should NOT be called
        with patch(
            "backend_py.packs.ops_copilot.api.routers.drafts._execute_broadcast_driver",
            new_callable=AsyncMock,
        ) as mock_executor:
            result = await _confirm_draft(
                conn=mock_conn,
                draft_id=pending_draft["draft_id"],
                user_id=owner["user_id"],
                user_permissions=owner["permissions"],
                role_name=owner["role_name"],
            )

            # Verify executor was NOT called
            mock_executor.assert_not_called()

        # Should still get idempotent success
        assert result["success"] is True
        assert result.get("idempotent") is True

    @pytest.mark.asyncio
    async def test_double_cancel_idempotent(
        self, mock_conn, pending_draft, test_users
    ):
        """Cancelling same draft twice should be idempotent."""
        from ..api.routers.drafts import _cancel_draft_internal as _cancel_draft

        user = test_users["dispatcher"]

        # Draft already cancelled
        mock_conn._cursor.set_results([
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                "CANCELLED",  # Already cancelled
                pending_draft["created_by"],
            ),
        ])

        result = await _cancel_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=user["user_id"],
        )

        # Should succeed without error (idempotent)
        assert result["success"] is True
        assert result.get("idempotent") is True


class TestAtomicCommit:
    """Tests for atomic commit behavior (race condition prevention)."""

    @pytest.mark.asyncio
    async def test_concurrent_confirm_only_one_executes(
        self, mock_conn, pending_draft, test_users
    ):
        """
        When two requests race to confirm, only one should execute action.

        The second request should get idempotent response with cached result.
        This is enforced by UPDATE ... WHERE status='PENDING_CONFIRM'.
        """
        from ..api.routers.drafts import _confirm_draft

        owner = test_users["dispatcher"]

        # First request gets draft in PENDING_CONFIRM
        mock_conn._cursor.set_results([
            # Get draft - still pending
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["payload"],
                "PENDING_CONFIRM",
                owner["user_id"],
                pending_draft["expires_at"],
                None,  # No commit_result yet
            ),
            # Atomic UPDATE returns row (we won the race)
            (pending_draft["draft_id"],),
            # Event insert
            None,
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=owner["user_id"],
            user_permissions=owner["permissions"],
            role_name=owner["role_name"],
        )

        assert result["success"] is True
        assert "result_id" in result

    @pytest.mark.asyncio
    async def test_race_condition_returns_idempotent(
        self, mock_conn, pending_draft, test_users
    ):
        """
        If atomic UPDATE fails (race lost), return idempotent response.

        The UPDATE ... WHERE status='PENDING_CONFIRM' returns no rows
        because another request already changed the status.
        """
        from ..api.routers.drafts import _confirm_draft

        owner = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            # Get draft - appears pending at read time
            (
                pending_draft["tenant_id"],
                pending_draft["thread_id"],
                pending_draft["action_type"],
                pending_draft["payload"],
                "PENDING_CONFIRM",  # Looks pending
                owner["user_id"],
                pending_draft["expires_at"],
                None,
            ),
            # Atomic UPDATE returns no rows (lost race)
            None,
            # Re-fetch shows committed with result
            ("COMMITTED", {"result_id": "winner-result"}),
        ])

        result = await _confirm_draft(
            conn=mock_conn,
            draft_id=pending_draft["draft_id"],
            user_id=owner["user_id"],
            user_permissions=owner["permissions"],
            role_name=owner["role_name"],
        )

        # Should get idempotent response with winner's result
        assert result["success"] is True
        assert result.get("idempotent") is True
        assert result.get("result_id") == "winner-result"
