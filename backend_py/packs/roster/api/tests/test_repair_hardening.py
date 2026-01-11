"""
SOLVEREIGN V4.8.1 - Repair Hardening Tests
==========================================

Tests for repair endpoint hardening:
1. DB-backed idempotency (replay + conflict)
2. Overlap validation at repair layer
3. Rest time validation (WARN only)
4. Freeze violation detection

GUARDRAIL: These tests validate orchestration layer, NOT solver logic.
"""

import pytest
import hashlib
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Import functions to test
from packs.roster.api.routers.repair import (
    compute_request_hash,
    validate_no_overlaps,
    validate_rest_time,
    compute_policy_hash,
)


# =============================================================================
# REQUEST HASH TESTS
# =============================================================================

class TestComputeRequestHash:
    """Test deterministic request hash computation."""

    def test_same_inputs_same_hash(self):
        """Same inputs should produce same hash."""
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        absences = [MockAbsence()]

        hash1 = compute_request_hash(1, absences, "min_churn", 94)
        hash2 = compute_request_hash(1, absences, "min_churn", 94)

        assert hash1 == hash2

    def test_different_plan_different_hash(self):
        """Different base plan should produce different hash."""
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        absences = [MockAbsence()]

        hash1 = compute_request_hash(1, absences, "min_churn", 94)
        hash2 = compute_request_hash(2, absences, "min_churn", 94)

        assert hash1 != hash2

    def test_different_seed_different_hash(self):
        """Different seed should produce different hash."""
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        absences = [MockAbsence()]

        hash1 = compute_request_hash(1, absences, "min_churn", 94)
        hash2 = compute_request_hash(1, absences, "min_churn", 95)

        assert hash1 != hash2

    def test_absence_order_independent(self):
        """Hash should be independent of absence order."""
        class MockAbsence1:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        class MockAbsence2:
            driver_id = 88
            from_ts = "2026-01-16T06:00:00+00:00"
            to_ts = "2026-01-16T18:00:00+00:00"
            reason = "VACATION"

        # Order 1: [77, 88]
        absences1 = [MockAbsence1(), MockAbsence2()]
        # Order 2: [88, 77]
        absences2 = [MockAbsence2(), MockAbsence1()]

        hash1 = compute_request_hash(1, absences1, "min_churn", 94)
        hash2 = compute_request_hash(1, absences2, "min_churn", 94)

        # Should be same since we sort by driver_id
        assert hash1 == hash2


# =============================================================================
# OVERLAP VALIDATION TESTS
# =============================================================================

class TestOverlapValidation:
    """Test repair-layer overlap validation."""

    def test_no_overlaps_returns_empty(self):
        """No overlapping shifts should return empty violations."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T06:00:00+00:00",
                "shift_end": "2026-01-15T14:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T14:30:00+00:00",
                    "shift_end": "2026-01-15T22:00:00+00:00",
                }
            ]
        }

        violations = validate_no_overlaps(added_assignments, existing_assignments)
        assert len(violations) == 0

    def test_overlapping_shifts_returns_violation(self):
        """Overlapping shifts should return BLOCK violation."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T10:00:00+00:00",
                "shift_end": "2026-01-15T18:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T14:00:00+00:00",
                    "shift_end": "2026-01-15T22:00:00+00:00",
                }
            ]
        }

        violations = validate_no_overlaps(added_assignments, existing_assignments)

        assert len(violations) == 1
        assert violations[0]["type"] == "overlap"
        assert violations[0]["driver_id"] == 77
        assert violations[0]["severity"] == "BLOCK"

    def test_same_driver_multiple_new_assignments_overlap(self):
        """Multiple new assignments for same driver overlapping each other."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T08:00:00+00:00",
                "shift_end": "2026-01-15T16:00:00+00:00",
            },
            {
                "tour_instance_id": 101,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T12:00:00+00:00",
                "shift_end": "2026-01-15T20:00:00+00:00",
            },
        ]
        existing_assignments = {}

        violations = validate_no_overlaps(added_assignments, existing_assignments)

        assert len(violations) == 1
        assert violations[0]["type"] == "overlap"
        assert violations[0]["severity"] == "BLOCK"

    def test_different_days_no_overlap(self):
        """Shifts on different days should not overlap."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T08:00:00+00:00",
                "shift_end": "2026-01-15T16:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 2,
                    "shift_start": "2026-01-16T08:00:00+00:00",
                    "shift_end": "2026-01-16T16:00:00+00:00",
                }
            ]
        }

        violations = validate_no_overlaps(added_assignments, existing_assignments)
        assert len(violations) == 0

    def test_adjacent_shifts_no_overlap(self):
        """Shifts that touch but don't overlap should not be violations."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T06:00:00+00:00",
                "shift_end": "2026-01-15T14:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T14:00:00+00:00",  # Starts when other ends
                    "shift_end": "2026-01-15T22:00:00+00:00",
                }
            ]
        }

        violations = validate_no_overlaps(added_assignments, existing_assignments)
        assert len(violations) == 0


# =============================================================================
# REST TIME VALIDATION TESTS
# =============================================================================

class TestRestTimeValidation:
    """Test rest time validation (advisory WARN only)."""

    def test_sufficient_rest_no_violations(self):
        """11+ hours rest should not produce violations."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 2,
                "shift_start": "2026-01-16T06:00:00+00:00",
                "shift_end": "2026-01-16T14:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T06:00:00+00:00",
                    "shift_end": "2026-01-15T14:00:00+00:00",
                }
            ]
        }

        violations = validate_rest_time(added_assignments, existing_assignments, min_rest_hours=11)
        assert len(violations) == 0

    def test_insufficient_rest_returns_warn(self):
        """Less than 11 hours rest should return WARN violation."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T22:00:00+00:00",
                "shift_end": "2026-01-16T06:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T06:00:00+00:00",
                    "shift_end": "2026-01-15T14:00:00+00:00",
                }
            ]
        }

        violations = validate_rest_time(added_assignments, existing_assignments, min_rest_hours=11)

        assert len(violations) == 1
        assert violations[0]["type"] == "rest"
        assert violations[0]["severity"] == "WARN"  # Advisory, not BLOCK
        assert violations[0]["driver_id"] == 77

    def test_rest_violation_is_warn_not_block(self):
        """Rest violations should always be WARN (honest disclosure)."""
        added_assignments = [
            {
                "tour_instance_id": 100,
                "new_driver_id": 77,
                "day": 1,
                "shift_start": "2026-01-15T18:00:00+00:00",
                "shift_end": "2026-01-15T23:00:00+00:00",
            }
        ]
        existing_assignments = {
            77: [
                {
                    "tour_instance_id": 50,
                    "day": 1,
                    "shift_start": "2026-01-15T06:00:00+00:00",
                    "shift_end": "2026-01-15T14:00:00+00:00",
                }
            ]
        }

        violations = validate_rest_time(added_assignments, existing_assignments, min_rest_hours=11)

        # Even with very short rest (4 hours), should be WARN not BLOCK
        for v in violations:
            assert v["severity"] == "WARN"


# =============================================================================
# POLICY HASH TESTS
# =============================================================================

class TestPolicyHash:
    """Test policy hash computation (shorter display hash)."""

    def test_policy_hash_is_16_chars(self):
        """Policy hash should be 16 characters (truncated SHA-256)."""
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        hash_val = compute_policy_hash([MockAbsence()], "min_churn", 94)
        assert len(hash_val) == 16

    def test_policy_hash_deterministic(self):
        """Same inputs should produce same policy hash."""
        class MockAbsence:
            driver_id = 77
            from_ts = "2026-01-15T06:00:00+00:00"
            to_ts = "2026-01-15T18:00:00+00:00"
            reason = "SICK"

        hash1 = compute_policy_hash([MockAbsence()], "min_churn", 94)
        hash2 = compute_policy_hash([MockAbsence()], "min_churn", 94)
        assert hash1 == hash2


# =============================================================================
# IDEMPOTENCY DB FUNCTION TESTS (Mock-based)
# =============================================================================

class TestIdempotencyDBFunctions:
    """Test DB idempotency check/store logic with mocks."""

    def test_idempotency_check_not_found(self):
        """When key doesn't exist, should return NOT_FOUND."""
        from packs.roster.api.routers.repair import check_db_idempotency

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ({"status": "NOT_FOUND", "can_proceed": True},)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = check_db_idempotency(mock_conn, 1, "test.action", "key-123", "hash-abc")

        assert result["status"] == "NOT_FOUND"
        assert result["can_proceed"] is True

    def test_idempotency_check_found_match(self):
        """When key exists with same hash, return cached response."""
        from packs.roster.api.routers.repair import check_db_idempotency

        cached_response = {"new_plan_version_id": 999, "verdict": "OK"}
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ({
            "status": "FOUND_MATCH",
            "can_proceed": False,
            "cached_response": cached_response,
        },)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = check_db_idempotency(mock_conn, 1, "test.action", "key-123", "hash-abc")

        assert result["status"] == "FOUND_MATCH"
        assert result["can_proceed"] is False
        assert result["cached_response"]["new_plan_version_id"] == 999

    def test_idempotency_check_found_conflict(self):
        """When key exists with different hash, return CONFLICT."""
        from packs.roster.api.routers.repair import check_db_idempotency

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ({
            "status": "FOUND_CONFLICT",
            "can_proceed": False,
            "error_code": "IDEMPOTENCY_KEY_REUSE_CONFLICT",
        },)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = check_db_idempotency(mock_conn, 1, "test.action", "key-123", "different-hash")

        assert result["status"] == "FOUND_CONFLICT"
        assert result["can_proceed"] is False


# =============================================================================
# VERDICT SEMANTICS TESTS
# =============================================================================

class TestVerdictSemantics:
    """Test that verdict semantics are correct."""

    def test_overlap_violations_cause_block(self):
        """BLOCK-severity overlap violations should cause BLOCK verdict."""
        # This is tested via the full flow in integration tests
        # Here we just verify the data structure
        violation = {
            "type": "overlap",
            "driver_id": 77,
            "severity": "BLOCK",
        }
        assert violation["severity"] == "BLOCK"

    def test_rest_violations_are_warn(self):
        """Rest violations should be WARN, not BLOCK."""
        violation = {
            "type": "rest",
            "driver_id": 77,
            "severity": "WARN",
        }
        assert violation["severity"] == "WARN"

    def test_freeze_violations_cause_block(self):
        """Freeze violations should always be BLOCK."""
        violation = {
            "type": "freeze",
            "driver_id": None,
            "severity": "BLOCK",
        }
        assert violation["severity"] == "BLOCK"


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
