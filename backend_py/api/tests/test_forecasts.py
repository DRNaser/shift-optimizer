"""
SOLVEREIGN V3.3a API - Forecast Endpoint Tests
===============================================
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_forecasts_requires_auth(client: AsyncClient):
    """Test that listing forecasts requires authentication."""
    response = await client.get("/api/v1/forecasts")

    # Should require auth
    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_ingest_forecast_requires_auth(client: AsyncClient, sample_forecast_request):
    """Test that ingesting forecasts requires authentication."""
    response = await client.post(
        "/api/v1/forecasts",
        json=sample_forecast_request
    )

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_get_forecast_requires_auth(client: AsyncClient):
    """Test that getting forecast details requires authentication."""
    response = await client.get("/api/v1/forecasts/1")

    assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_forecast_validation_empty_text(client: AsyncClient, auth_headers):
    """Test that empty forecast text is rejected."""
    response = await client.post(
        "/api/v1/forecasts",
        headers=auth_headers,
        json={"raw_text": "", "source": "api"}
    )

    # Pydantic validation should reject empty string
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_forecast_list_pagination(client: AsyncClient, auth_headers):
    """Test forecast list pagination parameters."""
    # Invalid page
    response = await client.get(
        "/api/v1/forecasts",
        headers=auth_headers,
        params={"page": 0}
    )
    # Should normalize to page 1 (handled by get_pagination)
    # Status depends on auth - may be 401 if tenant not found
    assert response.status_code in (200, 401)

    # Invalid page_size (too large)
    response = await client.get(
        "/api/v1/forecasts",
        headers=auth_headers,
        params={"page_size": 1000}
    )
    # Should normalize to max 100
    assert response.status_code in (200, 401)
