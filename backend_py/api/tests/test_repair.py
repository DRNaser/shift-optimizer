"""
SOLVEREIGN V4.8 - Repair API Tests
===================================

Tests for the Roster Repair MVP endpoints:
- Determinism: Same inputs => same preview result
- Idempotency: Same key + same inputs => same plan_version_id
- Guards: CSRF, idempotency, RBAC, tenant isolation
"""

import pytest
import json
import hashlib
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestRepairDeterminism:
    """Test that repair preview is deterministic."""

    def test_same_inputs_same_output(self):
        """Same absences + seed produce identical preview results."""
        from packs.roster.api.routers.repair import compute_policy_hash

        absences_data = [
            {"driver_id": 77, "from": "2026-01-12T06:00:00Z", "to": "2026-01-12T18:00:00Z", "reason": "SICK"},
            {"driver_id": 88, "from": "2026-01-12T08:00:00Z", "to": "2026-01-12T16:00:00Z", "reason": "VACATION"},
        ]

        # Create mock absence entries
        class MockAbsence:
            def __init__(self, data):
                self.driver_id = data["driver_id"]
                self.from_ts = data["from"]
                self.to_ts = data["to"]
                self.reason = data["reason"]

        absences = [MockAbsence(a) for a in absences_data]

        # Compute policy hash twice
        hash1 = compute_policy_hash(absences, "min_churn", 94)
        hash2 = compute_policy_hash(absences, "min_churn", 94)

        assert hash1 == hash2, "Policy hash must be deterministic"
        assert len(hash1) == 16, "Policy hash should be 16 chars"

    def test_different_seed_different_hash(self):
        """Different seed produces different policy hash."""
        from packs.roster.api.routers.repair import compute_policy_hash

        class MockAbsence:
            def __init__(self):
                self.driver_id = 77
                self.from_ts = "2026-01-12T06:00:00Z"
                self.to_ts = "2026-01-12T18:00:00Z"
                self.reason = "SICK"

        absences = [MockAbsence()]

        hash1 = compute_policy_hash(absences, "min_churn", 94)
        hash2 = compute_policy_hash(absences, "min_churn", 95)

        assert hash1 != hash2, "Different seeds must produce different hashes"

    def test_absence_order_independent(self):
        """Absence order doesn't affect policy hash (sorted internally)."""
        from packs.roster.api.routers.repair import compute_policy_hash

        class MockAbsence:
            def __init__(self, driver_id):
                self.driver_id = driver_id
                self.from_ts = "2026-01-12T06:00:00Z"
                self.to_ts = "2026-01-12T18:00:00Z"
                self.reason = "SICK"

        # Order 1: 77, 88
        absences1 = [MockAbsence(77), MockAbsence(88)]
        hash1 = compute_policy_hash(absences1, "min_churn", 94)

        # Order 2: 88, 77
        absences2 = [MockAbsence(88), MockAbsence(77)]
        hash2 = compute_policy_hash(absences2, "min_churn", 94)

        assert hash1 == hash2, "Absence order should not affect hash"


class TestRepairIdempotency:
    """Test idempotency behavior for repair commit."""

    def test_idempotency_cache_store_retrieve(self):
        """Store and retrieve from idempotency cache (DB-backed)."""
        # Skip this test - requires DB connection for store_db_idempotency
        # The actual functions are check_db_idempotency and store_db_idempotency
        # which require async DB connection
        import pytest
        pytest.skip("Requires DB connection - tested in integration")

    def test_idempotency_cache_miss(self):
        """Non-existent key returns None (DB-backed)."""
        # Skip this test - requires DB connection
        import pytest
        pytest.skip("Requires DB connection - tested in integration")

    def test_idempotency_key_validation(self):
        """Invalid UUID format is rejected."""
        from packs.roster.api.routers.repair import require_repair_idempotency_key
        from fastapi import HTTPException

        # Invalid UUID
        with pytest.raises(HTTPException) as exc_info:
            require_repair_idempotency_key("not-a-uuid")
        assert exc_info.value.status_code == 400
        assert "INVALID_IDEMPOTENCY_KEY" in str(exc_info.value.detail)

    def test_idempotency_key_required(self):
        """Missing idempotency key is rejected."""
        from packs.roster.api.routers.repair import require_repair_idempotency_key
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            require_repair_idempotency_key(None)
        assert exc_info.value.status_code == 400
        assert "IDEMPOTENCY_KEY_REQUIRED" in str(exc_info.value.detail)


class TestRepairGuards:
    """Test security guards for repair endpoints."""

    def test_preview_requires_tenant_context(self):
        """Preview endpoint requires tenant context."""
        # This would be tested via integration test with actual HTTP client
        # Here we verify the dependency is declared
        from packs.roster.api.routers.repair import repair_preview
        import inspect

        sig = inspect.signature(repair_preview)
        params = list(sig.parameters.keys())
        assert "ctx" in params, "Preview must have ctx parameter for tenant context"

    def test_commit_requires_csrf(self):
        """Commit endpoint requires CSRF check dependency."""
        from packs.roster.api.routers.repair import router

        # Find the commit route (path includes router prefix)
        commit_route = None
        for route in router.routes:
            if hasattr(route, 'path') and route.path.endswith("/commit"):
                commit_route = route
                break

        assert commit_route is not None, "Commit route must exist"
        # Check dependencies include CSRF
        deps = [str(d.dependency) for d in commit_route.dependencies]
        csrf_found = any("csrf" in d.lower() for d in deps)
        assert csrf_found, "Commit must have CSRF dependency"

    def test_commit_requires_idempotency(self):
        """Commit endpoint requires idempotency key."""
        from packs.roster.api.routers.repair import repair_commit
        import inspect

        sig = inspect.signature(repair_commit)
        params = list(sig.parameters.keys())
        assert "idempotency_key" in params, "Commit must require idempotency_key"


class TestRepairEvidence:
    """Test evidence generation for repair operations."""

    def test_evidence_id_generation(self):
        """Evidence ID is unique and properly formatted."""
        from packs.roster.api.routers.repair import generate_repair_evidence_id

        id1 = generate_repair_evidence_id()
        id2 = generate_repair_evidence_id()

        assert id1.startswith("repair_"), "Evidence ID must start with repair_"
        assert id1 != id2, "Each evidence ID must be unique"

    def test_evidence_ref_generation(self):
        """Evidence reference path is properly formatted."""
        from packs.roster.api.routers.repair import generate_repair_evidence_ref

        ref = generate_repair_evidence_ref(
            tenant_id=1,
            site_id=10,
            action="repair_preview",
            entity_id=123
        )

        assert ref.startswith("evidence/"), "Must be in evidence directory"
        assert "roster_repair_preview" in ref, "Must include action name"
        assert "1_10" in ref, "Must include tenant_site"
        assert "123" in ref, "Must include entity_id"
        assert ref.endswith(".json"), "Must be JSON file"


class TestRepairAudit:
    """Test audit event recording for repair operations."""

    def test_audit_event_recorded(self):
        """Repair operations record audit events."""
        from packs.roster.api.routers.repair import record_repair_audit_event

        # Mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

        # Mock user context
        mock_user = Mock()
        mock_user.user_id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.tenant_id = 1
        mock_user.site_id = 10
        mock_user.active_tenant_id = None
        mock_user.active_site_id = None

        # Record event
        record_repair_audit_event(
            conn=mock_conn,
            event_type="roster.repair.commit",
            user=mock_user,
            details={"plan_id": 123, "verdict": "OK"},
        )

        # Verify SQL was executed
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "INSERT INTO auth.audit_log" in sql
        assert params[0] == "roster.repair.commit"
        assert params[1] == "user-123"
        assert params[2] == "test@example.com"


class TestRepairTenantIsolation:
    """Test tenant isolation for repair operations."""

    def test_repair_uses_tenant_from_context(self):
        """Repair must use tenant_id from user context, not request."""
        from packs.roster.api.routers.repair import run_greedy_repair
        from fastapi import HTTPException

        # Mock connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

        # Plan not found for wrong tenant
        mock_cursor.fetchone.return_value = None

        # Mock absence
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-12T06:00:00Z"
            to_ts = "2026-01-12T18:00:00Z"
            reason = "SICK"

        # Should raise 404 when plan not found for tenant
        with pytest.raises(HTTPException) as exc_info:
            run_greedy_repair(
                conn=mock_conn,
                tenant_id=1,
                site_id=10,
                base_plan_version_id=999,
                absences=[MockAbsence()],
                objective="min_churn",
                seed=94,
            )

        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail).lower()


class TestRepairSchemas:
    """Test Pydantic schema validation."""

    def test_absence_entry_schema(self):
        """AbsenceEntry schema validates correctly."""
        from packs.roster.api.routers.repair import AbsenceEntry

        # Valid entry
        entry = AbsenceEntry(
            driver_id=77,
            from_ts="2026-01-12T06:00:00Z",
            to_ts="2026-01-12T18:00:00Z",
            reason="SICK"
        )
        assert entry.driver_id == 77
        assert entry.reason == "SICK"

    def test_repair_preview_request_schema(self):
        """RepairPreviewRequest schema validates correctly."""
        from packs.roster.api.routers.repair import RepairPreviewRequest, AbsenceEntry

        request = RepairPreviewRequest(
            base_plan_version_id=123,
            absences=[
                AbsenceEntry(
                    driver_id=77,
                    from_ts="2026-01-12T06:00:00Z",
                    to_ts="2026-01-12T18:00:00Z",
                    reason="SICK"
                )
            ],
            objective="min_churn",
            seed=94
        )
        assert request.base_plan_version_id == 123
        assert len(request.absences) == 1

    def test_repair_preview_request_requires_absences(self):
        """RepairPreviewRequest requires at least one absence."""
        from packs.roster.api.routers.repair import RepairPreviewRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RepairPreviewRequest(
                base_plan_version_id=123,
                absences=[],  # Empty list should fail
                objective="min_churn",
                seed=94
            )
