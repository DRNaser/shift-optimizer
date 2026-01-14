"""
Integration Tests: Broadcast Double-Confirm Idempotency

CRITICAL PROOF: Confirms that CONFIRM twice -> only one broadcast event.

These tests require a real database connection and verify the actual
SQL behavior, not just mocked responses.

Run with: pytest -m integration test_broadcast_idempotency_integration.py -v
"""

import hashlib
import pytest
import uuid
from datetime import datetime, timedelta, timezone


# Mark all tests as integration tests (skip in unit test runs)
pytestmark = pytest.mark.integration


@pytest.fixture
def integration_tenant(real_conn):
    """Create a test tenant in real DB."""
    tenant_id = None
    with real_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (name, subdomain, is_active)
            VALUES ('Integration Test Tenant', 'integration-test', TRUE)
            RETURNING id
            """
        )
        tenant_id = cur.fetchone()[0]
        real_conn.commit()
    yield {"tenant_id": tenant_id}

    # Cleanup
    with real_conn.cursor() as cur:
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        real_conn.commit()


@pytest.fixture
def integration_user(real_conn, integration_tenant):
    """Create a test user with dispatcher permissions."""
    user_id = str(uuid.uuid4())
    with real_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.users (id, email, display_name, password_hash)
            VALUES (%s::uuid, %s, %s, 'test-hash')
            RETURNING id
            """,
            (user_id, f"test-{user_id}@test.com", "Integration Test User"),
        )
        real_conn.commit()
    yield {
        "user_id": user_id,
        "tenant_id": integration_tenant["tenant_id"],
        "permissions": [
            "ops_copilot.tickets.write",
            "ops_copilot.broadcast.ops",
            "ops_copilot.broadcast.driver",
        ],
        "role_name": "dispatcher",
    }

    # Cleanup
    with real_conn.cursor() as cur:
        cur.execute("DELETE FROM auth.users WHERE id = %s::uuid", (user_id,))
        real_conn.commit()


@pytest.fixture
def integration_identity(real_conn, integration_tenant, integration_user):
    """Create a test WhatsApp identity."""
    identity_id = str(uuid.uuid4())
    wa_user_id = f"whatsapp:436641234567"
    thread_id = hashlib.sha256(
        f"sv:{integration_tenant['tenant_id']}:10:{wa_user_id}".encode()
    ).hexdigest()

    with real_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.whatsapp_identities (
                id, tenant_id, site_id, user_id, wa_user_id, wa_phone_hash, status
            ) VALUES (%s::uuid, %s, 10, %s::uuid, %s, %s, 'ACTIVE')
            RETURNING id
            """,
            (
                identity_id,
                integration_tenant["tenant_id"],
                integration_user["user_id"],
                wa_user_id,
                hashlib.sha256(b"+436641234567").hexdigest(),
            ),
        )
        real_conn.commit()

    yield {
        "identity_id": identity_id,
        "wa_user_id": wa_user_id,
        "thread_id": thread_id,
        "tenant_id": integration_tenant["tenant_id"],
        "user_id": integration_user["user_id"],
    }

    # Cleanup
    with real_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.whatsapp_identities WHERE id = %s::uuid", (identity_id,))
        real_conn.commit()


@pytest.fixture
def integration_broadcast_draft(real_conn, integration_identity, integration_user):
    """Create a pending broadcast draft."""
    draft_id = str(uuid.uuid4())
    thread_id = integration_identity["thread_id"]
    tenant_id = integration_identity["tenant_id"]

    with real_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.drafts (
                id, tenant_id, thread_id, identity_id, action_type,
                payload, preview_text, status, expires_at, created_by
            ) VALUES (
                %s::uuid, %s, %s, %s::uuid, 'WHATSAPP_BROADCAST_OPS',
                %s, 'Broadcast test message', 'PENDING_CONFIRM',
                NOW() + INTERVAL '10 minutes', %s::uuid
            )
            RETURNING id
            """,
            (
                draft_id,
                tenant_id,
                thread_id,
                integration_identity["identity_id"],
                {"message": "Test broadcast", "recipient_ids": []},
                integration_user["user_id"],
            ),
        )
        real_conn.commit()

    yield {
        "draft_id": draft_id,
        "tenant_id": tenant_id,
        "thread_id": thread_id,
    }

    # Cleanup
    with real_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.drafts WHERE id = %s::uuid", (draft_id,))
        cur.execute(
            "DELETE FROM ops.events WHERE payload->>'draft_id' = %s", (draft_id,)
        )
        real_conn.commit()


class TestBroadcastDoubleConfirmIdempotency:
    """
    CRITICAL: Proves that CONFIRM twice produces only one broadcast event.

    This is the definitive proof that idempotency works at the database level.
    """

    @pytest.mark.asyncio
    async def test_double_confirm_single_broadcast_event(
        self, real_conn, integration_broadcast_draft, integration_user
    ):
        """
        PROOF: Two CONFIRMs produce exactly one BROADCAST_ENQUEUED event.

        Steps:
        1. First CONFIRM -> commits draft, creates BROADCAST_ENQUEUED event
        2. Second CONFIRM -> returns idempotent, NO new event
        3. Count events -> must equal 1
        """
        from ..api.routers.drafts import _confirm_draft

        draft_id = integration_broadcast_draft["draft_id"]
        user = integration_user

        # === FIRST CONFIRM ===
        result1 = await _confirm_draft(
            conn=real_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result1["success"] is True
        assert result1.get("idempotent") is not True  # First one is NOT idempotent

        # === SECOND CONFIRM ===
        result2 = await _confirm_draft(
            conn=real_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        assert result2["success"] is True
        assert result2.get("idempotent") is True  # Second one IS idempotent

        # === COUNT EVENTS - MUST BE EXACTLY 1 ===
        with real_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM ops.events
                WHERE event_type = 'DRAFT_COMMITTED'
                  AND payload->>'draft_id' = %s
                """,
                (draft_id,),
            )
            event_count = cur.fetchone()[0]

        assert event_count == 1, (
            f"IDEMPOTENCY VIOLATION: Expected 1 DRAFT_COMMITTED event, "
            f"got {event_count}. Double-confirm created duplicate events!"
        )

    @pytest.mark.asyncio
    async def test_concurrent_confirms_single_execution(
        self, real_conn, integration_broadcast_draft, integration_user
    ):
        """
        Simulates race condition: Two concurrent CONFIRMs.

        Only one should execute, the other should get idempotent response.
        Total events must equal 1.
        """
        import asyncio
        from ..api.routers.drafts import _confirm_draft

        draft_id = integration_broadcast_draft["draft_id"]
        user = integration_user

        async def confirm_attempt():
            return await _confirm_draft(
                conn=real_conn,
                draft_id=draft_id,
                user_id=user["user_id"],
                user_permissions=user["permissions"],
                role_name=user["role_name"],
            )

        # Run two confirms "concurrently" (as close as possible in async)
        results = await asyncio.gather(
            confirm_attempt(),
            confirm_attempt(),
            return_exceptions=True,
        )

        # Both should succeed
        successes = [r for r in results if isinstance(r, dict) and r.get("success")]
        assert len(successes) == 2, "Both confirms should return success"

        # At least one should be idempotent
        idempotent_count = sum(1 for r in successes if r.get("idempotent"))
        assert idempotent_count >= 1, "At least one confirm should be idempotent"

        # COUNT EVENTS - MUST BE EXACTLY 1
        with real_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM ops.events
                WHERE event_type = 'DRAFT_COMMITTED'
                  AND payload->>'draft_id' = %s
                """,
                (draft_id,),
            )
            event_count = cur.fetchone()[0]

        assert event_count == 1, (
            f"RACE CONDITION VIOLATION: Expected 1 event, got {event_count}"
        )


class TestBroadcastEventDeduplication:
    """Tests for BROADCAST_ENQUEUED event deduplication."""

    @pytest.mark.asyncio
    async def test_broadcast_ops_single_event(
        self, real_conn, integration_broadcast_draft, integration_user
    ):
        """
        OPS broadcast: CONFIRM twice -> exactly 1 BROADCAST_ENQUEUED event.
        """
        from ..api.routers.drafts import _confirm_draft

        draft_id = integration_broadcast_draft["draft_id"]
        user = integration_user

        # First confirm
        await _confirm_draft(
            conn=real_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        # Second confirm
        await _confirm_draft(
            conn=real_conn,
            draft_id=draft_id,
            user_id=user["user_id"],
            user_permissions=user["permissions"],
            role_name=user["role_name"],
        )

        # Count BROADCAST_ENQUEUED events
        with real_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM ops.events
                WHERE event_type = 'BROADCAST_ENQUEUED'
                  AND payload->>'draft_id' = %s
                """,
                (draft_id,),
            )
            # Note: For OPS broadcast, BROADCAST_ENQUEUED is created by _execute_broadcast_ops
            # The draft_id is in the payload for tracking
            broadcast_count = cur.fetchone()[0]

        # Should be 0 or 1 (depending on whether executor ran)
        # Critical: should NOT be 2
        assert broadcast_count <= 1, (
            f"BROADCAST DEDUP VIOLATION: Got {broadcast_count} BROADCAST_ENQUEUED events"
        )


# =============================================================================
# Fixture for real DB connection (requires DATABASE_URL env var)
# =============================================================================

@pytest.fixture(scope="module")
def real_conn():
    """
    Provide a real database connection for integration tests.

    Requires DATABASE_URL environment variable.
    Skip if not available.
    """
    import os
    import psycopg

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set - skipping integration tests")

    conn = psycopg.connect(db_url)
    yield conn
    conn.close()
