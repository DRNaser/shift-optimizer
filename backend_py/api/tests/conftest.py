"""
SOLVEREIGN V3.3a API - Test Fixtures
====================================

Pytest fixtures for API testing.
"""

import hashlib
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from ..main import app
from ..database import DatabaseManager


# =============================================================================
# TEST API KEY
# =============================================================================

TEST_API_KEY = "test_api_key_for_unit_testing_only_32chars"
TEST_API_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def api_key():
    """Test API key."""
    return TEST_API_KEY


@pytest.fixture
def auth_headers(api_key):
    """Headers with API key authentication."""
    return {"X-API-Key": api_key}


@pytest_asyncio.fixture
async def client():
    """
    Async test client for API testing.

    Uses httpx AsyncClient with ASGI transport.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authenticated_client(client, auth_headers):
    """
    Authenticated test client.

    All requests include X-API-Key header.
    """
    # Create a wrapper that adds auth headers
    original_request = client.request

    async def authenticated_request(method, url, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.update(auth_headers)
        return await original_request(method, url, headers=headers, **kwargs)

    client.request = authenticated_request
    yield client


# =============================================================================
# DATABASE FIXTURES (for integration tests)
# =============================================================================

@pytest_asyncio.fixture
async def db_manager():
    """
    Database manager for integration tests.

    Initializes connection pool and cleans up after test.
    """
    manager = DatabaseManager()
    await manager.initialize()
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def test_tenant(db_manager):
    """
    Create a test tenant for integration tests.

    Returns:
        Tuple of (tenant_id, api_key)
    """
    async with db_manager.transaction() as conn:
        async with conn.cursor() as cur:
            # Check if test tenant exists
            await cur.execute(
                "SELECT id FROM tenants WHERE name = 'test_tenant'"
            )
            existing = await cur.fetchone()

            if existing:
                tenant_id = existing["id"]
            else:
                # Create test tenant
                await cur.execute(
                    """
                    INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                    VALUES ('test_tenant', %s, TRUE, '{"tier": "test"}'::jsonb)
                    RETURNING id
                    """,
                    (TEST_API_KEY_HASH,)
                )
                result = await cur.fetchone()
                tenant_id = result["id"]

    yield tenant_id, TEST_API_KEY

    # Cleanup: Remove test data (optional, depends on test isolation strategy)
    # async with db_manager.transaction() as conn:
    #     async with conn.cursor() as cur:
    #         await cur.execute("DELETE FROM tenants WHERE name = 'test_tenant'")


# =============================================================================
# SAMPLE DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_forecast_text():
    """Sample forecast text for testing."""
    return """Mo 06:00-14:00 3 Fahrer Depot Nord
Mo 14:00-22:00 2 Fahrer
Di 08:00-16:00
Mi 06:00-10:00 + 15:00-19:00
Do 22:00-06:00
Fr 06:00-14:00 5 Fahrer
"""


@pytest.fixture
def sample_forecast_request(sample_forecast_text):
    """Sample forecast ingest request."""
    return {
        "raw_text": sample_forecast_text,
        "source": "api",
        "week_anchor_date": "2026-01-05",  # Monday
        "notes": "Test forecast",
    }
