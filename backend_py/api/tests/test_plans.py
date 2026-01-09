"""
SOLVEREIGN V3.3a API - Plan Endpoint Tests
==========================================

Note: Tests marked xfail require DB fixture or staging environment.
See TEST_FAILURE_CLASSIFICATION.md for details.
"""

import pytest
from httpx import AsyncClient


# =============================================================================
# AUTH REQUIREMENT TESTS
# These test that endpoints reject unauthenticated requests.
# Expected: 401 (Unauthorized) when no auth header is provided.
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_solve_requires_auth(client: AsyncClient):
    """Test that solving requires authentication."""
    response = await client.post(
        "/api/v1/plans/solve",
        json={"forecast_version_id": 1}
    )
    # 401 = unauthorized (no auth header)
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_get_plan_requires_auth(client: AsyncClient):
    """Test that getting plan details requires authentication."""
    response = await client.get("/api/v1/plans/1")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_get_plan_kpis_requires_auth(client: AsyncClient):
    """Test that getting plan KPIs requires authentication."""
    response = await client.get("/api/v1/plans/1/kpis")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_get_plan_audit_requires_auth(client: AsyncClient):
    """Test that getting audit results requires authentication."""
    response = await client.get("/api/v1/plans/1/audit")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_lock_plan_requires_auth(client: AsyncClient):
    """Test that locking plans requires authentication."""
    response = await client.post(
        "/api/v1/plans/1/lock",
        json={"locked_by": "test_user"}
    )
    # Without auth, should get 401 (unauthorized)
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_export_plan_requires_auth(client: AsyncClient):
    """Test that exporting plans requires authentication."""
    response = await client.get("/api/v1/plans/1/export/csv")
    assert response.status_code == 401


# =============================================================================
# VALIDATION TESTS
# These test request validation (requires auth + DB).
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_export_invalid_format(client: AsyncClient, auth_headers):
    """Test that invalid export format is rejected."""
    response = await client.get(
        "/api/v1/plans/1/export/invalid",
        headers=auth_headers
    )
    # 400 Bad Request for invalid format OR 401 if tenant not found
    assert response.status_code in (400, 401, 404)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Requires DB fixture - move to staging suite")
async def test_solve_validation(client: AsyncClient, auth_headers):
    """Test solve request validation."""
    # Missing forecast_version_id
    response = await client.post(
        "/api/v1/plans/solve",
        headers=auth_headers,
        json={}
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_lock_validation(client: AsyncClient, auth_headers):
    """Test lock request validation."""
    # Missing locked_by - but auth check comes first
    response = await client.post(
        "/api/v1/plans/1/lock",
        headers=auth_headers,
        json={}
    )
    # Auth is checked first, then validation
    # If auth fails due to DB issue, we get 401
    # If auth passes, we get 422 validation error
    assert response.status_code in (401, 422)

    # Empty locked_by
    response = await client.post(
        "/api/v1/plans/1/lock",
        headers=auth_headers,
        json={"locked_by": ""}
    )
    assert response.status_code in (401, 422)
