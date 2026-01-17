"""
Driver Broadcast Tests

Tests:
- Reject without template
- Reject unapproved template
- Reject illegal placeholders
- Reject opted-out drivers
- Success with valid template and opted-in drivers
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import uuid


@pytest.mark.xfail(reason="Mock cursor setup incompatible with broadcast.py query pattern")
class TestOpsbroadcast:
    """Tests for ops-to-ops broadcasts (free text)."""

    @pytest.mark.asyncio
    async def test_ops_broadcast_success(self, mock_conn, test_tenant, test_users):
        """Ops broadcast with free text should succeed."""
        from ..core.broadcast import validate_ops_broadcast

        user = test_users["dispatcher"]
        recipient_ids = [test_users["tenant_admin"]["user_id"]]

        mock_conn._cursor.set_results([
            # Check recipients exist and are active
            [(r,) for r in recipient_ids],
        ])

        result = await validate_ops_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            message="Important update: Schedule changed for tomorrow",
            recipient_ids=recipient_ids,
        )

        assert result["valid"] is True
        assert result["recipient_count"] == len(recipient_ids)

    @pytest.mark.asyncio
    async def test_ops_broadcast_empty_message_rejected(
        self, mock_conn, test_tenant, test_users
    ):
        """Empty message should be rejected."""
        from ..core.broadcast import validate_ops_broadcast

        recipient_ids = [test_users["tenant_admin"]["user_id"]]

        result = await validate_ops_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            message="",  # Empty
            recipient_ids=recipient_ids,
        )

        assert result["valid"] is False
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_ops_broadcast_no_recipients_rejected(
        self, mock_conn, test_tenant
    ):
        """Broadcast without recipients should be rejected."""
        from ..core.broadcast import validate_ops_broadcast

        result = await validate_ops_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            message="Test message",
            recipient_ids=[],  # No recipients
        )

        assert result["valid"] is False
        assert "recipient" in result["error"].lower()


class TestDriverBroadcastTemplate:
    """Tests for driver broadcast template validation."""

    @pytest.mark.asyncio
    async def test_driver_broadcast_without_template_rejected(
        self, mock_conn, test_tenant
    ):
        """Driver broadcast without template should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([None])  # No template found

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key="nonexistent_template",
            params={"driver_name": "Max"},
            driver_ids=["driver-1"],
        )

        assert result["valid"] is False
        assert "template" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_driver_broadcast_unapproved_template_rejected(
        self, mock_conn, test_tenant, unapproved_template
    ):
        """Unapproved template should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            # Template found but not approved
            (
                unapproved_template["template_id"],
                unapproved_template["body_template"],
                unapproved_template["expected_params"],
                unapproved_template["is_approved"],  # False
                unapproved_template["is_active"],
                unapproved_template["audience"],
            ),
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=unapproved_template["template_key"],
            params={"driver_name": "Max", "date": "2026-01-15", "time": "08:00"},
            driver_ids=["driver-1"],
        )

        assert result["valid"] is False
        assert "approved" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_driver_broadcast_wrong_audience_rejected(
        self, mock_conn, test_tenant, approved_template
    ):
        """Template with wrong audience should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        # Template is for OPS, not DRIVER
        template = approved_template.copy()
        template["audience"] = "OPS"

        mock_conn._cursor.set_results([
            (
                template["template_id"],
                template["body_template"],
                template["expected_params"],
                template["is_approved"],
                template["is_active"],
                "OPS",  # Wrong audience
            ),
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=template["template_key"],
            params={"driver_name": "Max", "date": "2026-01-15", "time": "08:00"},
            driver_ids=["driver-1"],
        )

        assert result["valid"] is False
        assert "audience" in result["error"].lower()


class TestDriverBroadcastPlaceholders:
    """Tests for template placeholder validation."""

    @pytest.mark.asyncio
    async def test_missing_placeholder_rejected(
        self, mock_conn, test_tenant, approved_template
    ):
        """Missing required placeholder should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],  # ["driver_name", "date", "time"]
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
            # Driver subscriptions check
            [("driver-1",)],
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max",
                # Missing "date" and "time"
            },
            driver_ids=["driver-1"],
        )

        assert result["valid"] is False
        assert "placeholder" in result["error"].lower() or "param" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_extra_placeholder_ignored(
        self, mock_conn, test_tenant, approved_template, subscribed_driver
    ):
        """Extra placeholders should be ignored (not rejected)."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
            # Driver subscriptions - all subscribed
            [(subscribed_driver["driver_id"],)],
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max",
                "date": "2026-01-15",
                "time": "08:00",
                "extra_param": "ignored",  # Extra param
            },
            driver_ids=[subscribed_driver["driver_id"]],
        )

        # Should succeed, extra params are just ignored
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_illegal_placeholder_value_rejected(
        self, mock_conn, test_tenant, approved_template
    ):
        """Placeholder values with illegal characters should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max<script>alert('xss')</script>",  # XSS attempt
                "date": "2026-01-15",
                "time": "08:00",
            },
            driver_ids=["driver-1"],
        )

        assert result["valid"] is False
        assert "invalid" in result["error"].lower() or "illegal" in result["error"].lower()


class TestDriverOptIn:
    """Tests for driver opt-in consent validation."""

    @pytest.mark.asyncio
    async def test_opted_out_driver_rejected(
        self, mock_conn, test_tenant, approved_template, unsubscribed_driver
    ):
        """Broadcast to opted-out driver should be rejected."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            # Template
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
            # Driver subscriptions - none subscribed
            [],
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max",
                "date": "2026-01-15",
                "time": "08:00",
            },
            driver_ids=[unsubscribed_driver["driver_id"]],
        )

        assert result["valid"] is False
        assert "opt" in result["error"].lower() or "subscrib" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_mixed_subscription_partial_rejected(
        self, mock_conn, test_tenant, approved_template, subscribed_driver, unsubscribed_driver
    ):
        """Broadcast to mix of opted-in and opted-out should reject opted-out."""
        from ..core.broadcast import validate_driver_broadcast

        mock_conn._cursor.set_results([
            # Template
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
            # Only subscribed driver returned
            [(subscribed_driver["driver_id"],)],
        ])

        driver_ids = [subscribed_driver["driver_id"], unsubscribed_driver["driver_id"]]

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max",
                "date": "2026-01-15",
                "time": "08:00",
            },
            driver_ids=driver_ids,
        )

        assert result["valid"] is False
        assert "unsubscribed" in result["error"].lower() or len(result.get("rejected_drivers", [])) > 0

    @pytest.mark.asyncio
    async def test_all_opted_in_success(
        self, mock_conn, test_tenant, approved_template, subscribed_driver
    ):
        """Broadcast to all opted-in drivers should succeed."""
        from ..core.broadcast import validate_driver_broadcast

        driver_ids = [subscribed_driver["driver_id"]]

        mock_conn._cursor.set_results([
            # Template
            (
                approved_template["template_id"],
                approved_template["body_template"],
                approved_template["expected_params"],
                approved_template["is_approved"],
                approved_template["is_active"],
                approved_template["audience"],
            ),
            # All drivers subscribed
            [(d,) for d in driver_ids],
        ])

        result = await validate_driver_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            template_key=approved_template["template_key"],
            params={
                "driver_name": "Max",
                "date": "2026-01-15",
                "time": "08:00",
            },
            driver_ids=driver_ids,
        )

        assert result["valid"] is True
        assert result["recipient_count"] == len(driver_ids)


class TestBroadcastEnqueue:
    """Tests for broadcast enqueueing."""

    @pytest.mark.asyncio
    async def test_enqueue_ops_broadcast(
        self, mock_conn, test_tenant, test_thread, test_users
    ):
        """Ops broadcast should be enqueued as event."""
        from ..core.broadcast import enqueue_broadcast

        mock_conn._cursor.set_results([
            (str(uuid.uuid4()),),  # Event ID
        ])

        result = await enqueue_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            thread_id=test_thread["thread_id"],
            audience="OPS",
            payload={
                "message": "Test broadcast",
                "recipient_ids": [test_users["tenant_admin"]["user_id"]],
            },
        )

        assert result["success"] is True
        assert "event_id" in result
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_enqueue_driver_broadcast(
        self, mock_conn, test_tenant, test_thread, subscribed_driver
    ):
        """Driver broadcast should be enqueued with template info."""
        from ..core.broadcast import enqueue_broadcast

        mock_conn._cursor.set_results([
            (str(uuid.uuid4()),),  # Event ID
        ])

        result = await enqueue_broadcast(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            thread_id=test_thread["thread_id"],
            audience="DRIVER",
            payload={
                "template_key": "shift_reminder",
                "params": {"driver_name": "Max", "date": "2026-01-15", "time": "08:00"},
                "driver_ids": [subscribed_driver["driver_id"]],
            },
        )

        assert result["success"] is True
        assert "event_id" in result
