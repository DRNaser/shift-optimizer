"""
Test: Lock Endpoint Violation Re-Check (P1 Fix)
==============================================

Tests that the lock endpoint re-checks violations LIVE before locking.

Requirements:
- test_lock_rejected_when_violations_present -> 409 + payload contains violations
- test_lock_succeeds_when_clean -> 200
- test_lock_idempotent_when_already_locked -> 200 + idempotent + no extra audit rows
- test_lock_denied_for_unauthorized -> 403 (RBAC-first)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import the lock endpoint function for testing
from backend_py.api.routers.plans import lock_plan, LockRequest


class MockCursor:
    """Mock async cursor for testing."""

    def __init__(self, results_sequence):
        """results_sequence: list of results for each fetchone/fetchall call."""
        self.results = iter(results_sequence)
        self.executed_queries = []
        self.executed_params = []

    async def execute(self, query, params=None):
        self.executed_queries.append(query)
        self.executed_params.append(params)

    async def fetchone(self):
        try:
            return next(self.results)
        except StopIteration:
            return None

    async def fetchall(self):
        try:
            return next(self.results)
        except StopIteration:
            return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockConnection:
    """Mock async connection for testing."""

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockDB:
    """Mock DatabaseManager for testing."""

    def __init__(self, cursor):
        self._cursor = cursor

    def tenant_transaction(self, tenant_id):
        return MockConnection(self._cursor)


class MockUser:
    """Mock Entra user context."""

    def __init__(
        self,
        user_id="user-123",
        email="approver@test.com",
        name="Test Approver",
        tenant_id=1,
        roles=None,
        is_app_token=False,
        app_id=None,
    ):
        self.user_id = user_id
        self.email = email
        self.name = name
        self.tenant_id = tenant_id
        self.roles = roles or ["APPROVER"]
        self.is_app_token = is_app_token
        self.app_id = app_id


@pytest.mark.asyncio
async def test_lock_rejected_when_violations_present():
    """
    Test that lock returns 409 when BLOCK violations are present.

    Expected:
    - HTTP 409 Conflict
    - Response contains code="VIOLATIONS_PRESENT"
    - Response contains violations list
    """
    # Setup: Plan exists in DRAFT status with audit passed, but has violations
    plan_result = {
        "id": 1,
        "status": "DRAFT",
        "audit_failed_count": 0,
        "locked_at": None,
        "locked_by": None,
    }

    # Violations query returns BLOCK violations
    violations_result = [
        {
            "violation_type": "OVERLAP",
            "severity": "BLOCK",
            "driver_id": "D001",
            "day": "MON",
            "message": "Driver D001 has overlapping assignments on MON",
        },
        {
            "violation_type": "UNASSIGNED",
            "severity": "BLOCK",
            "driver_id": "NONE",
            "day": "TUE",
            "message": "Tour T001 on TUE has no driver",
        },
    ]

    cursor = MockCursor([plan_result, violations_result])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await lock_plan(
                plan_id=1,
                request=request,
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert detail["code"] == "VIOLATIONS_PRESENT"
        assert detail["block_count"] == 2
        assert len(detail["violations"]) == 2
        assert detail["violations"][0]["type"] == "OVERLAP"
        assert detail["violations"][0]["severity"] == "BLOCK"


@pytest.mark.asyncio
async def test_lock_succeeds_when_clean():
    """
    Test that lock succeeds when no BLOCK violations are present.

    Expected:
    - HTTP 200 OK
    - Response contains status="LOCKED"
    - idempotent=False
    """
    # Setup: Plan in DRAFT, no violations
    plan_result = {
        "id": 1,
        "status": "DRAFT",
        "audit_failed_count": 0,
        "locked_at": None,
        "locked_by": None,
    }

    # No violations
    violations_result = []

    # Lock update returns locked_at
    lock_result = {"locked_at": datetime.now(timezone.utc)}

    # Audit log insert (no return needed)
    audit_result = None

    cursor = MockCursor([plan_result, violations_result, lock_result, None, audit_result])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test", notes="Test lock")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        response = await lock_plan(
            plan_id=1,
            request=request,
            user=user,
            db=db,
        )

        assert response.status == "LOCKED"
        assert response.plan_version_id == 1
        assert response.idempotent is False
        assert "locked successfully" in response.message


@pytest.mark.asyncio
async def test_lock_idempotent_when_already_locked():
    """
    Test that locking an already-locked plan returns idempotent response.

    Expected:
    - HTTP 200 OK
    - idempotent=True
    - No additional database writes (audit log, etc.)
    """
    # Setup: Plan already LOCKED
    locked_at = datetime.now(timezone.utc)
    plan_result = {
        "id": 1,
        "status": "LOCKED",
        "audit_failed_count": 0,
        "locked_at": locked_at,
        "locked_by": "previous-user@test.com",
    }

    cursor = MockCursor([plan_result])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        response = await lock_plan(
            plan_id=1,
            request=request,
            user=user,
            db=db,
        )

        assert response.status == "LOCKED"
        assert response.idempotent is True
        assert response.locked_by == "previous-user@test.com"
        assert "already locked" in response.message

        # Verify no additional queries after the SELECT
        # Only one query should have been executed (the SELECT)
        assert len(cursor.executed_queries) == 1


@pytest.mark.asyncio
async def test_lock_denied_for_unauthorized_app_token():
    """
    Test that M2M/app tokens cannot lock plans.

    Expected:
    - HTTP 403 Forbidden
    - Error detail contains APP_TOKEN_NOT_ALLOWED
    - No plan state revealed
    """
    # App token user
    user = MockUser(is_app_token=True, app_id="app-123")
    request = LockRequest(locked_by="test")

    # DB not even accessed for app tokens (fails early)
    cursor = MockCursor([])
    db = MockDB(cursor)

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await lock_plan(
                plan_id=1,
                request=request,
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "APP_TOKEN_NOT_ALLOWED"

        # Verify no DB access occurred (RBAC-first)
        assert len(cursor.executed_queries) == 0


@pytest.mark.asyncio
async def test_lock_respects_warn_violations():
    """
    Test that WARN violations don't block locking (only BLOCK does).

    Expected:
    - HTTP 200 OK even with WARN violations
    - WARN count logged but not blocking
    """
    # Setup: Plan in DRAFT with only WARN violations
    plan_result = {
        "id": 1,
        "status": "DRAFT",
        "audit_failed_count": 0,
        "locked_at": None,
        "locked_by": None,
    }

    # Only WARN violations (should not block)
    violations_result = [
        {
            "violation_type": "REST",
            "severity": "WARN",
            "driver_id": "D001",
            "day": None,
            "message": "Driver D001 may have rest violations",
        },
    ]

    lock_result = {"locked_at": datetime.now(timezone.utc)}

    cursor = MockCursor([plan_result, violations_result, lock_result, None, None])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        response = await lock_plan(
            plan_id=1,
            request=request,
            user=user,
            db=db,
        )

        assert response.status == "LOCKED"
        assert response.idempotent is False


@pytest.mark.asyncio
async def test_lock_blocked_when_tenant_scope_blocked():
    """
    Test that lock fails when tenant has active S0/S1 escalation.

    Expected:
    - ServiceBlockedError raised
    - No plan state revealed
    """
    user = MockUser()
    request = LockRequest(locked_by="test")

    cursor = MockCursor([])
    db = MockDB(cursor)

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=True):
        from backend_py.api.exceptions import ServiceBlockedError

        with pytest.raises(ServiceBlockedError):
            await lock_plan(
                plan_id=1,
                request=request,
                user=user,
                db=db,
            )

        # Verify no DB access (blocked before query)
        assert len(cursor.executed_queries) == 0


@pytest.mark.asyncio
async def test_lock_404_when_plan_not_found():
    """
    Test that lock returns 404 when plan doesn't exist or belongs to different tenant.
    """
    plan_result = None  # No plan found

    cursor = MockCursor([plan_result])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        from backend_py.api.exceptions import PlanNotFoundError

        with pytest.raises(PlanNotFoundError):
            await lock_plan(
                plan_id=999,
                request=request,
                user=user,
                db=db,
            )


@pytest.mark.asyncio
async def test_lock_422_when_audit_failed():
    """
    Test that lock fails when plan has failed audits.
    """
    plan_result = {
        "id": 1,
        "status": "DRAFT",
        "audit_failed_count": 2,  # Has failed audits
        "locked_at": None,
        "locked_by": None,
    }

    cursor = MockCursor([plan_result])
    db = MockDB(cursor)
    user = MockUser()
    request = LockRequest(locked_by="test")

    with patch("backend_py.api.routers.plans.is_scope_blocked", return_value=False):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await lock_plan(
                plan_id=1,
                request=request,
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 422
        assert "failed audits" in str(exc_info.value.detail)


# ============================================================================
# Run commands:
#   pytest backend_py/packs/roster/tests/test_lock_recheck_violations.py -v
# ============================================================================
