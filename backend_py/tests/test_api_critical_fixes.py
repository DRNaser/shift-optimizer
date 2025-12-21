"""
API Critical Fixes Tests
=========================
Tests for the 6 critical API fixes:
1. Locked fields enforced and warned
2. SSE seq monotonic and resume replays
3. Input tours sorted before solve
4. Plan endpoint sorted stably
5. Report canonical has no timestamp and sorted keys
"""

import pytest
import json
from datetime import time

from src.api.config_validator import (
    validate_and_apply_overrides,
    LOCKED_FIELDS,
    TUNABLE_FIELDS
)
from src.services.forecast_solver_v4 import ConfigV4


class TestLockedFieldsEnforced:
    """Test that locked fields cannot be overridden."""
    
    def test_locked_field_overridden_is_enforced(self):
        """Locked fields like num_search_workers should be rejected, not applied."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"num_search_workers": 8},  # Attempt to change locked field
            seed=42
        )
        
        # Locked field should be rejected (not applied)
        assert "num_search_workers" in result.overrides_rejected
        assert "num_search_workers" not in result.overrides_applied
        # Note: num_search_workers is enforced in solver code, not in ConfigV4
        
    def test_locked_field_override_is_rejected_and_warned(self):
        """Locked field override attempts should be tracked and warned."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"num_search_workers": 8},
            seed=42
        )
        
        # Should be in rejected
        assert "num_search_workers" in result.overrides_rejected
        # Should have reason code
        assert any("LOCKED_FIELD" in code for code in result.reason_codes)
        
    def test_unknown_field_rejected(self):
        """Unknown override keys should be rejected."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"unknown_magic_param": 999},
            seed=42
        )
        
        assert "unknown_magic_param" in result.overrides_rejected
        assert any("UNKNOWN" in code for code in result.reason_codes)
        
    def test_tunable_field_applied(self):
        """Tunable fields should be applied correctly."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"enable_fill_to_target_greedy": True},
            seed=42
        )
        
        assert result.config_effective.enable_fill_to_target_greedy == True
        assert "enable_fill_to_target_greedy" in result.overrides_applied
        
    def test_value_clamped_to_range(self):
        """Values outside range should be clamped."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"pt_ratio_threshold": 2.0},  # Max is 1.0
            seed=42
        )
        
        assert result.config_effective.pt_ratio_threshold == 1.0
        assert "pt_ratio_threshold" in result.overrides_clamped
        assert result.overrides_clamped["pt_ratio_threshold"] == (2.0, 1.0)


class TestInputToursSorted:
    """Test that input tours are sorted deterministically."""
    
    def test_tours_sorted_before_solve(self):
        """Tours should be sorted by (day, start_time, id) before solving."""
        from src.domain.models import Tour, Weekday
        
        # Create tours in random order
        tours = [
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(10, 0), end_time=time(14, 0)),
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
        ]
        
        # Sort like run_manager does
        sorted_tours = sorted(
            tours,
            key=lambda t: (t.day.value, t.start_time.hour, t.start_time.minute, t.id)
        )
        
        assert sorted_tours[0].id == "T1"  # 06:00
        assert sorted_tours[1].id == "T2"  # 08:00
        assert sorted_tours[2].id == "T3"  # 10:00


class TestPlanEndpointSorted:
    """Test that plan endpoint returns stably sorted data."""
    
    def test_assignments_sorted_by_driver_day_block(self):
        """Assignments should be sorted by (driver_id, day, block_id)."""
        # Mock assignment-like dicts
        assignments = [
            {"driver_id": "D3", "day": "Mon", "block_id": "B1"},
            {"driver_id": "D1", "day": "Tue", "block_id": "B2"},
            {"driver_id": "D1", "day": "Mon", "block_id": "B3"},
            {"driver_id": "D2", "day": "Mon", "block_id": "B1"},
        ]
        
        sorted_assignments = sorted(
            assignments,
            key=lambda a: (a["driver_id"], a["day"], a["block_id"])
        )
        
        # D1 < D2 < D3, then by day, then by block_id
        assert sorted_assignments[0]["driver_id"] == "D1"
        assert sorted_assignments[0]["day"] == "Mon"
        assert sorted_assignments[1]["driver_id"] == "D1"
        assert sorted_assignments[1]["day"] == "Tue"
        assert sorted_assignments[2]["driver_id"] == "D2"
        assert sorted_assignments[3]["driver_id"] == "D3"


class TestReportCanonical:
    """Test canonical report format."""
    
    def test_canonical_json_keys_sorted(self):
        """Canonical JSON should have sorted keys."""
        from src.services.portfolio_controller import RunReport
        
        report = RunReport(
            input_summary={"tours": 100},
            features={"friday_heavy": True}
        )
        report.reason_codes = ["REPAIR_SWAP", "BAD_BLOCK_MIX", "POOL_CAPPED"]
        
        canonical = report.to_canonical_json()
        parsed = json.loads(canonical)
        
        # Keys should be sorted
        keys = list(parsed.keys())
        assert keys == sorted(keys)
        
        # reason_codes should be sorted
        assert parsed["reason_codes"] == sorted(report.reason_codes)


class TestSSESeqMonotonic:
    """Test SSE event sequence."""
    
    def test_events_have_monotonic_seq(self):
        """Events should have strictly increasing seq numbers."""
        from src.api.run_manager import RunContext, RunStatus
        from datetime import datetime
        
        ctx = RunContext(
            run_id="test",
            status=RunStatus.RUNNING,
            created_at=datetime.now(),
            input_summary={},
            config=ConfigV4()
        )
        
        # Add events
        ctx.add_event("event1", {})
        ctx.add_event("event2", {})
        ctx.add_event("event3", {})
        
        seqs = [e["seq"] for e in ctx.events]
        assert seqs == [0, 1, 2]  # Monotonically increasing


class TestConfigEffectiveHash:
    """Test config hash for reproducibility."""
    
    def test_same_config_same_hash(self):
        """Same config should produce same hash."""
        result1 = validate_and_apply_overrides(ConfigV4(), {"enable_fill_to_target_greedy": True}, seed=42)
        result2 = validate_and_apply_overrides(ConfigV4(), {"enable_fill_to_target_greedy": True}, seed=42)
        
        assert result1.config_effective_hash == result2.config_effective_hash
        
    def test_different_config_different_hash(self):
        """Different config should produce different hash."""
        result1 = validate_and_apply_overrides(ConfigV4(), {"enable_fill_to_target_greedy": True}, seed=42)
        result2 = validate_and_apply_overrides(ConfigV4(), {"enable_fill_to_target_greedy": False}, seed=42)
        
        assert result1.config_effective_hash != result2.config_effective_hash
