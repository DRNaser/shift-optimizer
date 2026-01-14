"""
Ops-Copilot Test Fixtures

Provides reusable fixtures for testing the Ops-Copilot pack.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Generator, Optional
from unittest.mock import MagicMock, AsyncMock

import pytest


# =============================================================================
# Mock Database Connection
# =============================================================================


class MockCursor:
    """Mock database cursor for testing."""

    def __init__(self):
        self._results = []
        self._result_index = 0
        self._executed_queries = []
        self._executed_params = []

    def execute(self, query: str, params: tuple = None):
        """Record executed query and params."""
        self._executed_queries.append(query)
        self._executed_params.append(params)

    def fetchone(self):
        """Return next single result."""
        if self._result_index < len(self._results):
            result = self._results[self._result_index]
            self._result_index += 1
            return result
        return None

    def fetchall(self):
        """Return all remaining results."""
        results = self._results[self._result_index:]
        self._result_index = len(self._results)
        return results

    def set_results(self, results: list):
        """Set results to return from queries."""
        self._results = results
        self._result_index = 0


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self):
        self._cursor = MockCursor()
        self._committed = False
        self._rolled_back = False

    def cursor(self):
        """Return context manager for cursor."""
        return MockCursorContext(self._cursor)

    def commit(self):
        """Mark as committed."""
        self._committed = True

    def rollback(self):
        """Mark as rolled back."""
        self._rolled_back = True


class MockCursorContext:
    """Context manager for mock cursor."""

    def __init__(self, cursor: MockCursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_conn() -> MockConnection:
    """Provide a mock database connection."""
    return MockConnection()


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def test_tenant() -> Dict[str, Any]:
    """Provide test tenant data."""
    return {
        "tenant_id": 1,
        "tenant_name": "Test Logistics",
        "subdomain": "test-logistics",
    }


@pytest.fixture
def test_site(test_tenant) -> Dict[str, Any]:
    """Provide test site data."""
    return {
        "site_id": 10,
        "tenant_id": test_tenant["tenant_id"],
        "site_name": "Wien Depot",
        "timezone": "Europe/Vienna",
    }


@pytest.fixture
def test_users(test_tenant, test_site) -> Dict[str, Dict[str, Any]]:
    """Provide test users with different roles."""
    tenant_id = test_tenant["tenant_id"]
    site_id = test_site["site_id"]

    return {
        "platform_admin": {
            "user_id": str(uuid.uuid4()),
            "email": "admin@solvereign.com",
            "display_name": "Platform Admin",
            "role_name": "platform_admin",
            "tenant_id": None,  # Platform-wide
            "site_id": None,
            "permissions": [
                "platform.tenants.write",
                "platform.users.write",
                "ops_copilot.pairing.manage",
            ],
        },
        "tenant_admin": {
            "user_id": str(uuid.uuid4()),
            "email": "tenant_admin@test.com",
            "display_name": "Tenant Admin",
            "role_name": "tenant_admin",
            "tenant_id": tenant_id,
            "site_id": None,
            "permissions": [
                "ops_copilot.pairing.manage",
                "ops_copilot.tickets.write",
                "ops_copilot.audit.write",
                "ops_copilot.broadcast.ops",
                "ops_copilot.broadcast.driver",
            ],
        },
        "dispatcher": {
            "user_id": str(uuid.uuid4()),
            "email": "dispatcher@test.com",
            "display_name": "Dispatcher User",
            "role_name": "dispatcher",
            "tenant_id": tenant_id,
            "site_id": site_id,
            "permissions": [
                "ops_copilot.tickets.write",
                "ops_copilot.audit.write",
                "ops_copilot.broadcast.ops",
            ],
        },
        "ops_readonly": {
            "user_id": str(uuid.uuid4()),
            "email": "viewer@test.com",
            "display_name": "Viewer User",
            "role_name": "ops_readonly",
            "tenant_id": tenant_id,
            "site_id": site_id,
            "permissions": [
                "ops_copilot.tickets.read",
            ],
        },
    }


@pytest.fixture
def test_wa_user() -> Dict[str, str]:
    """Provide test WhatsApp user data."""
    phone = "+436641234567"
    return {
        "wa_user_id": f"whatsapp:{phone.replace('+', '')}",
        "wa_phone_hash": hashlib.sha256(phone.encode()).hexdigest(),
        "phone": phone,
    }


@pytest.fixture
def otp_pair() -> tuple:
    """Generate a valid OTP and its hash."""
    otp = "".join(secrets.choice("0123456789") for _ in range(6))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    return otp, otp_hash


@pytest.fixture
def pending_invite(test_tenant, test_users, otp_pair) -> Dict[str, Any]:
    """Provide a pending pairing invite."""
    otp, otp_hash = otp_pair
    user = test_users["dispatcher"]

    return {
        "invite_id": str(uuid.uuid4()),
        "tenant_id": test_tenant["tenant_id"],
        "user_id": user["user_id"],
        "otp_plain": otp,
        "otp_hash": otp_hash,
        "status": "PENDING",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "max_attempts": 3,
        "attempt_count": 0,
        "created_by": test_users["tenant_admin"]["user_id"],
    }


@pytest.fixture
def expired_invite(pending_invite) -> Dict[str, Any]:
    """Provide an expired pairing invite."""
    invite = pending_invite.copy()
    invite["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    return invite


@pytest.fixture
def exhausted_invite(pending_invite) -> Dict[str, Any]:
    """Provide an invite with exhausted attempts."""
    invite = pending_invite.copy()
    invite["attempt_count"] = invite["max_attempts"]
    return invite


@pytest.fixture
def paired_identity(test_tenant, test_site, test_users, test_wa_user) -> Dict[str, Any]:
    """Provide a paired WhatsApp identity."""
    user = test_users["dispatcher"]

    return {
        "identity_id": str(uuid.uuid4()),
        "wa_user_id": test_wa_user["wa_user_id"],
        "wa_phone_hash": test_wa_user["wa_phone_hash"],
        "tenant_id": test_tenant["tenant_id"],
        "site_id": test_site["site_id"],
        "user_id": user["user_id"],
        "status": "ACTIVE",
        "paired_via": "OTP",
        "paired_at": datetime.now(timezone.utc) - timedelta(days=7),
    }


# =============================================================================
# Draft Fixtures
# =============================================================================


@pytest.fixture
def pending_draft(test_tenant, test_users) -> Dict[str, Any]:
    """Provide a pending draft for confirmation."""
    user = test_users["dispatcher"]

    return {
        "draft_id": str(uuid.uuid4()),
        "tenant_id": test_tenant["tenant_id"],
        "thread_id": hashlib.sha256(b"test-thread").hexdigest(),
        "action_type": "CREATE_TICKET",
        "payload": {
            "title": "Test Ticket",
            "description": "This is a test ticket",
            "category": "GENERAL",
            "priority": "MEDIUM",
        },
        "status": "PENDING_CONFIRM",
        "created_by": user["user_id"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }


@pytest.fixture
def expired_draft(pending_draft) -> Dict[str, Any]:
    """Provide an expired draft."""
    draft = pending_draft.copy()
    draft["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    return draft


@pytest.fixture
def confirmed_draft(pending_draft) -> Dict[str, Any]:
    """Provide a confirmed draft."""
    draft = pending_draft.copy()
    draft["status"] = "CONFIRMED"
    draft["confirmed_at"] = datetime.now(timezone.utc)
    return draft


# =============================================================================
# Broadcast Fixtures
# =============================================================================


@pytest.fixture
def approved_template(test_tenant) -> Dict[str, Any]:
    """Provide an approved broadcast template."""
    return {
        "template_id": str(uuid.uuid4()),
        "tenant_id": test_tenant["tenant_id"],
        "template_key": "shift_reminder",
        "audience": "DRIVER",
        "body_template": "Hallo {{driver_name}}, deine Schicht beginnt am {{date}} um {{time}}.",
        "expected_params": ["driver_name", "date", "time"],
        "is_approved": True,
        "is_active": True,
    }


@pytest.fixture
def unapproved_template(approved_template) -> Dict[str, Any]:
    """Provide an unapproved template."""
    template = approved_template.copy()
    template["is_approved"] = False
    return template


@pytest.fixture
def subscribed_driver(test_tenant) -> Dict[str, Any]:
    """Provide a subscribed driver."""
    return {
        "subscription_id": str(uuid.uuid4()),
        "tenant_id": test_tenant["tenant_id"],
        "driver_id": str(uuid.uuid4()),
        "wa_identity_id": str(uuid.uuid4()),
        "is_subscribed": True,
        "subscribed_at": datetime.now(timezone.utc) - timedelta(days=30),
    }


@pytest.fixture
def unsubscribed_driver(subscribed_driver) -> Dict[str, Any]:
    """Provide an unsubscribed driver."""
    driver = subscribed_driver.copy()
    driver["is_subscribed"] = False
    driver["unsubscribed_at"] = datetime.now(timezone.utc) - timedelta(days=1)
    return driver


# =============================================================================
# Thread / State Fixtures
# =============================================================================


@pytest.fixture
def test_thread(test_tenant, test_site, paired_identity) -> Dict[str, Any]:
    """Provide a test conversation thread."""
    thread_id = hashlib.sha256(
        f"sv:{test_tenant['tenant_id']}:{test_site['site_id']}:whatsapp:{paired_identity['wa_user_id']}".encode()
    ).hexdigest()

    return {
        "id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "tenant_id": test_tenant["tenant_id"],
        "site_id": test_site["site_id"],
        "identity_id": paired_identity["identity_id"],
        "message_count": 5,
        "last_message_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def graph_checkpoint(test_thread) -> Dict[str, Any]:
    """Provide a graph state checkpoint."""
    return {
        "checkpoint_ns": "ops_copilot",
        "checkpoint_id": str(uuid.uuid4()),
        "channel_values": {
            "messages": [],
            "current_intent": "unknown",
            "step_count": 0,
            "tool_call_count": 0,
        },
        "channel_versions": {
            "messages": 1,
            "current_intent": 1,
        },
    }


# =============================================================================
# HMAC Fixtures
# =============================================================================


@pytest.fixture
def webhook_secret() -> str:
    """Provide a test webhook secret."""
    return "test-webhook-secret-12345"


@pytest.fixture
def valid_hmac_request(webhook_secret) -> Dict[str, Any]:
    """Provide a valid HMAC-signed webhook request."""
    import hmac as hmac_module

    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    body = b'{"from":"whatsapp:436641234567","body":"Hello"}'

    message = f"{timestamp}|{body.decode()}"
    signature = hmac_module.new(
        webhook_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    return {
        "body": body,
        "timestamp": timestamp,
        "signature": signature,
        "secret": webhook_secret,
    }


@pytest.fixture
def invalid_hmac_request(valid_hmac_request) -> Dict[str, Any]:
    """Provide an invalid HMAC-signed request."""
    request = valid_hmac_request.copy()
    request["signature"] = "invalid_signature_12345"
    return request


@pytest.fixture
def expired_hmac_request(webhook_secret) -> Dict[str, Any]:
    """Provide an expired HMAC-signed request."""
    import hmac as hmac_module

    # Timestamp from 10 minutes ago (past tolerance)
    timestamp = str(int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()))
    body = b'{"from":"whatsapp:436641234567","body":"Hello"}'

    message = f"{timestamp}|{body.decode()}"
    signature = hmac_module.new(
        webhook_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    return {
        "body": body,
        "timestamp": timestamp,
        "signature": signature,
        "secret": webhook_secret,
    }


# =============================================================================
# Helper Functions
# =============================================================================


def generate_otp() -> tuple:
    """Generate a random OTP and its hash."""
    otp = "".join(secrets.choice("0123456789") for _ in range(6))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    return otp, otp_hash


def hash_phone(phone: str) -> str:
    """Hash a phone number."""
    normalized = phone.strip().replace(" ", "").replace("-", "")
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_thread_id(tenant_id: int, site_id: Optional[int], wa_user_id: str) -> str:
    """Generate deterministic thread ID."""
    raw = f"sv:{tenant_id}:{site_id or 0}:whatsapp:{wa_user_id}"
    return hashlib.sha256(raw.encode()).hexdigest()
