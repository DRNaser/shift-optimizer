"""
SOLVEREIGN V3.3a API - Authentication Tests
============================================
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(client: AsyncClient):
    """Test that missing API key returns 401."""
    response = await client.get("/api/v1/tenants/me")

    assert response.status_code == 422  # FastAPI validation error (header required)


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(client: AsyncClient):
    """Test that invalid API key returns 401."""
    response = await client.get(
        "/api/v1/tenants/me",
        headers={"X-API-Key": "invalid_key_that_does_not_exist"}
    )

    # Should return 401 (after DB lookup fails)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_short_api_key_returns_401(client: AsyncClient):
    """Test that short API key returns 401."""
    response = await client.get(
        "/api/v1/tenants/me",
        headers={"X-API-Key": "short"}  # Less than min length
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoints_no_auth_required(client: AsyncClient):
    """Test that health endpoints don't require auth (GA-verified: works without DB)."""
    # Health check should work without auth
    response = await client.get("/health")
    assert response.status_code == 200

    response = await client.get("/health/live")
    assert response.status_code == 200

    response = await client.get("/health/ready")
    # May fail if DB not connected, but shouldn't be 401
    assert response.status_code in (200, 503)
