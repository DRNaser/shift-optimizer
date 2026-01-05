"""
SOLVEREIGN V3.3a API - Plan Endpoint Tests
==========================================
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_solve_requires_auth(client: AsyncClient):
    """Test that solving requires authentication."""
    response = await client.post(
        "/api/v1/plans/solve",
        json={"forecast_version_id": 1}
    )

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_get_plan_requires_auth(client: AsyncClient):
    """Test that getting plan details requires authentication."""
    response = await client.get("/api/v1/plans/1")

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_get_plan_kpis_requires_auth(client: AsyncClient):
    """Test that getting plan KPIs requires authentication."""
    response = await client.get("/api/v1/plans/1/kpis")

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_get_plan_audit_requires_auth(client: AsyncClient):
    """Test that getting audit results requires authentication."""
    response = await client.get("/api/v1/plans/1/audit")

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_lock_plan_requires_auth(client: AsyncClient):
    """Test that locking plans requires authentication."""
    response = await client.post(
        "/api/v1/plans/1/lock",
        json={"locked_by": "test_user"}
    )

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_export_plan_requires_auth(client: AsyncClient):
    """Test that exporting plans requires authentication."""
    response = await client.get("/api/v1/plans/1/export/csv")

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_export_invalid_format(client: AsyncClient, auth_headers):
    """Test that invalid export format is rejected."""
    response = await client.get(
        "/api/v1/plans/1/export/invalid",
        headers=auth_headers
    )

    # 400 Bad Request for invalid format OR 401 if tenant not found
    assert response.status_code in (400, 401, 404)


@pytest.mark.asyncio
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
    # Missing locked_by
    response = await client.post(
        "/api/v1/plans/1/lock",
        headers=auth_headers,
        json={}
    )

    assert response.status_code == 422  # Validation error

    # Empty locked_by
    response = await client.post(
        "/api/v1/plans/1/lock",
        headers=auth_headers,
        json={"locked_by": ""}
    )

    assert response.status_code == 422  # Validation error
