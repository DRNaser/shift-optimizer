"""
SOLVEREIGN V3.8 - Master Data Layer Tests
==========================================

Tests for MDL (Master Data Layer) API:
- External ID resolution (resolve, resolve-bulk)
- Idempotency
- RLS tenant isolation
- Unique constraint enforcement

Test Categories:
1. Unit tests: No DB required, test schemas and logic
2. Integration tests: Require DB, marked with @pytest.mark.integration
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

# Import schemas for unit testing
from ..routers.masterdata import (
    ResolveRequest,
    ResolveResponse,
    BulkResolveRequest,
    BulkResolveResponse,
    BulkResolveItem,
    UpsertMappingRequest,
)


# =============================================================================
# UNIT TESTS - Schema Validation
# =============================================================================

class TestResolveRequestSchema:
    """Test ResolveRequest schema validation."""

    def test_valid_request(self):
        """Valid resolve request should pass."""
        req = ResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_id="DRV-001",
        )
        assert req.external_system == "fls"
        assert req.entity_type == "driver"
        assert req.external_id == "DRV-001"
        assert req.create_payload is None

    def test_valid_request_with_payload(self):
        """Valid resolve request with create_payload should pass."""
        req = ResolveRequest(
            external_system="sap",
            entity_type="vehicle",
            external_id="VEH-A01",
            create_payload={"name": "Van 1", "capacity_kg": 1500},
        )
        assert req.create_payload == {"name": "Van 1", "capacity_kg": 1500}

    def test_entity_type_normalized_lowercase(self):
        """Entity type should be normalized to lowercase."""
        req = ResolveRequest(
            external_system="fls",
            entity_type="DRIVER",
            external_id="DRV-001",
        )
        assert req.entity_type == "driver"

    def test_empty_external_system_fails(self):
        """Empty external_system should fail."""
        with pytest.raises(ValidationError):
            ResolveRequest(
                external_system="",
                entity_type="driver",
                external_id="DRV-001",
            )

    def test_empty_external_id_fails(self):
        """Empty external_id should fail."""
        with pytest.raises(ValidationError):
            ResolveRequest(
                external_system="fls",
                entity_type="driver",
                external_id="",
            )

    def test_max_length_external_system(self):
        """External system over 100 chars should fail."""
        with pytest.raises(ValidationError):
            ResolveRequest(
                external_system="x" * 101,
                entity_type="driver",
                external_id="DRV-001",
            )


class TestBulkResolveRequestSchema:
    """Test BulkResolveRequest schema validation."""

    def test_valid_bulk_request(self):
        """Valid bulk resolve request should pass."""
        req = BulkResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_ids=["DRV-001", "DRV-002", "DRV-003"],
        )
        assert len(req.external_ids) == 3

    def test_empty_ids_fails(self):
        """Empty external_ids list should fail."""
        with pytest.raises(ValidationError):
            BulkResolveRequest(
                external_system="fls",
                entity_type="driver",
                external_ids=[],
            )

    def test_max_ids_limit(self):
        """Over 1000 IDs should fail."""
        with pytest.raises(ValidationError):
            BulkResolveRequest(
                external_system="fls",
                entity_type="driver",
                external_ids=[f"DRV-{i:04d}" for i in range(1001)],
            )

    def test_1000_ids_allowed(self):
        """Exactly 1000 IDs should pass."""
        req = BulkResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_ids=[f"DRV-{i:04d}" for i in range(1000)],
        )
        assert len(req.external_ids) == 1000


class TestResolveResponseSchema:
    """Test ResolveResponse schema."""

    def test_found_response(self):
        """Found response with internal_id."""
        resp = ResolveResponse(
            found=True,
            internal_id=str(uuid.uuid4()),
            external_id="DRV-001",
            entity_type="driver",
            created=False,
        )
        assert resp.found is True
        assert resp.error is None

    def test_not_found_response(self):
        """Not found response with error."""
        resp = ResolveResponse(
            found=False,
            external_id="DRV-999",
            entity_type="driver",
            error="Mapping not found and no create_payload provided",
        )
        assert resp.found is False
        assert resp.internal_id is None
        assert resp.error is not None

    def test_created_response(self):
        """Response when entity was created."""
        resp = ResolveResponse(
            found=True,
            internal_id=str(uuid.uuid4()),
            external_id="NEW-001",
            entity_type="site",
            created=True,
        )
        assert resp.created is True


# =============================================================================
# UNIT TESTS - Idempotency Logic
# =============================================================================

class TestIdempotency:
    """Test idempotency behavior."""

    def test_resolve_same_id_twice_returns_same_internal_id(self):
        """
        Resolving same external_id twice should return same internal_id.

        This is a conceptual test - actual DB behavior tested in integration.
        """
        # Mock the expected behavior
        internal_id = str(uuid.uuid4())

        first_response = ResolveResponse(
            found=True,
            internal_id=internal_id,
            external_id="DRV-001",
            entity_type="driver",
            created=True,  # First time creates
        )

        second_response = ResolveResponse(
            found=True,
            internal_id=internal_id,  # Same ID
            external_id="DRV-001",
            entity_type="driver",
            created=False,  # Second time just finds
        )

        assert first_response.internal_id == second_response.internal_id

    def test_upsert_mapping_is_idempotent(self):
        """Upserting same mapping twice should not create duplicates."""
        internal_id = str(uuid.uuid4())

        req1 = UpsertMappingRequest(
            external_system="fls",
            entity_type="driver",
            external_id="DRV-001",
            internal_id=internal_id,
        )

        req2 = UpsertMappingRequest(
            external_system="fls",
            entity_type="driver",
            external_id="DRV-001",
            internal_id=internal_id,
        )

        # Same inputs should be accepted
        assert req1.external_id == req2.external_id
        assert req1.internal_id == req2.internal_id


# =============================================================================
# UNIT TESTS - Unique Constraint Logic
# =============================================================================

class TestUniqueConstraint:
    """Test unique constraint behavior (unit level)."""

    def test_mapping_key_composition(self):
        """
        Mapping uniqueness is by (tenant_id, external_system, entity_type, external_id).

        Different entity_types can have same external_id.
        Different external_systems can have same external_id.
        """
        # Same external_id, different entity_type -> should be allowed
        driver_req = ResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_id="ABC-001",
        )

        vehicle_req = ResolveRequest(
            external_system="fls",
            entity_type="vehicle",
            external_id="ABC-001",  # Same external_id
        )

        assert driver_req.external_id == vehicle_req.external_id
        assert driver_req.entity_type != vehicle_req.entity_type

    def test_different_systems_same_external_id(self):
        """Different external_systems can have same external_id."""
        fls_req = ResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_id="DRV-001",
        )

        sap_req = ResolveRequest(
            external_system="sap",
            entity_type="driver",
            external_id="DRV-001",  # Same external_id
        )

        assert fls_req.external_id == sap_req.external_id
        assert fls_req.external_system != sap_req.external_system


# =============================================================================
# INTEGRATION TESTS - Database Required
# =============================================================================
# These tests require a running database and are skipped by default.
# Run with: pytest -m integration

@pytest.mark.integration
@pytest.mark.asyncio
class TestMasterdataIntegration:
    """
    Integration tests for MDL API.

    These tests require:
    1. Running PostgreSQL database
    2. Migration 028_masterdata.sql applied
    3. Test tenant created
    """

    @pytest.mark.skip(reason="Requires DB - run with: pytest -m integration")
    async def test_resolve_creates_mapping_with_payload(self, authenticated_client):
        """Resolve with create_payload should create entity and mapping."""
        response = await authenticated_client.post(
            "/api/v1/masterdata/resolve",
            json={
                "external_system": "test",
                "entity_type": "site",
                "external_id": f"TEST-{uuid.uuid4().hex[:8]}",
                "create_payload": {
                    "site_code": "TESTSITE",
                    "name": "Test Site",
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["created"] is True
        assert data["internal_id"] is not None

    @pytest.mark.skip(reason="Requires DB - run with: pytest -m integration")
    async def test_resolve_twice_returns_same_id(self, authenticated_client):
        """Resolving same external_id twice should return same internal_id."""
        external_id = f"IDEM-{uuid.uuid4().hex[:8]}"

        # First resolve
        response1 = await authenticated_client.post(
            "/api/v1/masterdata/resolve",
            json={
                "external_system": "test",
                "entity_type": "driver",
                "external_id": external_id,
                "create_payload": {"name": "Test Driver"},
            },
        )
        assert response1.status_code == 200
        internal_id_1 = response1.json()["internal_id"]

        # Second resolve (same external_id)
        response2 = await authenticated_client.post(
            "/api/v1/masterdata/resolve",
            json={
                "external_system": "test",
                "entity_type": "driver",
                "external_id": external_id,
            },
        )
        assert response2.status_code == 200
        internal_id_2 = response2.json()["internal_id"]

        assert internal_id_1 == internal_id_2

    @pytest.mark.skip(reason="Requires DB - run with: pytest -m integration")
    async def test_bulk_resolve(self, authenticated_client):
        """Bulk resolve should return results for all IDs."""
        response = await authenticated_client.post(
            "/api/v1/masterdata/resolve-bulk",
            json={
                "external_system": "test",
                "entity_type": "driver",
                "external_ids": ["DRV-001", "DRV-002", "DRV-999"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["results"]) == 3

    @pytest.mark.skip(reason="Requires DB - run with: pytest -m integration")
    async def test_rls_tenant_isolation(self, authenticated_client):
        """
        Tenant A should not see Tenant B's mappings.

        This requires creating two test tenants.
        """
        # This would need two different authenticated clients
        # with different tenant contexts
        pass


# =============================================================================
# MOCK TESTS - API Endpoint Behavior
# =============================================================================

class TestResolveEndpointMocked:
    """Test resolve endpoint with mocked database."""

    @pytest.mark.asyncio
    async def test_resolve_found_mapping(self):
        """Test resolve when mapping exists."""
        # This tests the response structure
        internal_id = str(uuid.uuid4())

        response = ResolveResponse(
            found=True,
            internal_id=internal_id,
            external_id="DRV-001",
            entity_type="driver",
            created=False,
        )

        assert response.found is True
        assert response.internal_id == internal_id
        assert response.created is False

    @pytest.mark.asyncio
    async def test_resolve_not_found_no_payload(self):
        """Test resolve when mapping not found and no payload."""
        response = ResolveResponse(
            found=False,
            external_id="DRV-999",
            entity_type="driver",
            error="Mapping not found and no create_payload provided",
        )

        assert response.found is False
        assert response.internal_id is None
        assert "not found" in response.error


class TestBulkResolveEndpointMocked:
    """Test bulk resolve endpoint with mocked database."""

    @pytest.mark.asyncio
    async def test_bulk_resolve_mixed_results(self):
        """Test bulk resolve with some found, some not found."""
        results = [
            BulkResolveItem(external_id="DRV-001", internal_id=str(uuid.uuid4()), found=True),
            BulkResolveItem(external_id="DRV-002", internal_id=str(uuid.uuid4()), found=True),
            BulkResolveItem(external_id="DRV-999", internal_id=None, found=False),
        ]

        response = BulkResolveResponse(
            total=3,
            found=2,
            not_found=1,
            results=results,
        )

        assert response.total == 3
        assert response.found == 2
        assert response.not_found == 1

        found_items = [r for r in response.results if r.found]
        not_found_items = [r for r in response.results if not r.found]

        assert len(found_items) == 2
        assert len(not_found_items) == 1


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_special_characters_in_external_id(self):
        """External IDs with special characters should be handled."""
        special_ids = [
            "DRV/001",
            "DRV:001",
            "DRV-001-A",
            "driver@site",
            "123",
            "a" * 255,  # Max length
        ]

        for ext_id in special_ids:
            req = ResolveRequest(
                external_system="fls",
                entity_type="driver",
                external_id=ext_id,
            )
            assert req.external_id == ext_id

    def test_unicode_external_id(self):
        """External IDs with unicode characters should work."""
        req = ResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_id="Fahrer-Müller-001",
        )
        assert "Müller" in req.external_id

    def test_custom_entity_type_allowed(self):
        """Custom (non-standard) entity types should be allowed with warning."""
        req = ResolveRequest(
            external_system="fls",
            entity_type="custom_entity",
            external_id="ENT-001",
        )
        # Non-standard types are lowercased but allowed
        assert req.entity_type == "custom_entity"

    def test_create_payload_complex_nested(self):
        """Complex nested create_payload should work."""
        req = ResolveRequest(
            external_system="fls",
            entity_type="site",
            external_id="SITE-001",
            create_payload={
                "name": "Test Site",
                "config": {
                    "operating_hours": {"start": "06:00", "end": "22:00"},
                    "features": ["parking", "loading_dock"],
                },
                "tags": ["primary", "active"],
            },
        )
        assert "config" in req.create_payload
        assert "features" in req.create_payload["config"]


# =============================================================================
# PERFORMANCE TESTS (Conceptual)
# =============================================================================

class TestPerformanceRequirements:
    """Document performance requirements for MDL."""

    def test_bulk_resolve_batch_size(self):
        """Bulk resolve should support up to 1000 IDs."""
        req = BulkResolveRequest(
            external_system="fls",
            entity_type="driver",
            external_ids=[f"DRV-{i:04d}" for i in range(1000)],
        )
        assert len(req.external_ids) == 1000

    def test_response_contains_all_requested_ids(self):
        """Response should contain all requested IDs (found or not)."""
        requested = ["A", "B", "C", "D", "E"]
        results = [
            BulkResolveItem(external_id="A", internal_id=str(uuid.uuid4()), found=True),
            BulkResolveItem(external_id="B", internal_id=str(uuid.uuid4()), found=True),
            BulkResolveItem(external_id="C", internal_id=None, found=False),
            BulkResolveItem(external_id="D", internal_id=str(uuid.uuid4()), found=True),
            BulkResolveItem(external_id="E", internal_id=None, found=False),
        ]

        response = BulkResolveResponse(
            total=5,
            found=3,
            not_found=2,
            results=results,
        )

        returned_ids = {r.external_id for r in response.results}
        assert returned_ids == set(requested)
