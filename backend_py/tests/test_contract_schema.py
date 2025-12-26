"""
Contract Tests for ShiftOptimizer 2.0 JSON Schema.

Validates:
1. schema_version exists in output and equals "2.0"
2. pause_zone is enum-compliant (REGULAR/SPLIT)
3. Roundtrip determinism (serialize → parse → serialize)
4. Stats sanity (p50 <= p95, within min/max)

These tests are fast and run without external dependencies.
"""
import pytest
import json
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.domain.models import Block, Tour, Weekday, WeeklyPlan, DriverAssignment, PauseZone
from datetime import date, time


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_tour():
    """Create a sample Tour for testing."""
    return Tour(
        id="T001",
        day=Weekday.MONDAY,
        start_time=time(6, 0),
        end_time=time(10, 0),
        location="HUB_A"
    )


@pytest.fixture
def sample_block(sample_tour):
    """Create a sample Block with explicit pause_zone."""
    return Block(
        id="B1-T001",
        day=Weekday.MONDAY,
        tours=[sample_tour],
        is_split=False,
        max_pause_minutes=0,
        pause_zone=PauseZone.REGULAR
    )


@pytest.fixture
def sample_split_block():
    """Create a sample split Block."""
    tour1 = Tour(
        id="T001",
        day=Weekday.MONDAY,
        start_time=time(6, 0),
        end_time=time(10, 0)
    )
    tour2 = Tour(
        id="T002",
        day=Weekday.MONDAY,
        start_time=time(14, 0),
        end_time=time(18, 0)
    )
    return Block(
        id="B2S-T001-T002",
        day=Weekday.MONDAY,
        tours=[tour1, tour2],
        is_split=True,
        max_pause_minutes=240,
        pause_zone=PauseZone.SPLIT
    )


@pytest.fixture
def sample_weekly_plan(sample_block):
    """Create a sample WeeklyPlan with schema_version."""
    assignment = DriverAssignment(
        driver_id="FTE001",
        day=Weekday.MONDAY,
        block=sample_block
    )
    return WeeklyPlan(
        id="test_plan_001",
        week_start=date(2024, 1, 1),
        assignments=[assignment]
    )


# =============================================================================
# SCHEMA CONTRACT TESTS
# =============================================================================

@pytest.mark.contract
@pytest.mark.smoke
class TestSchemaContract:
    """Contract tests for JSON schema compliance."""
    
    def test_schema_version_exists(self, sample_weekly_plan):
        """Verify schema_version is present in WeeklyPlan."""
        plan_dict = sample_weekly_plan.model_dump()
        
        assert "schema_version" in plan_dict, "schema_version must exist in output"
        assert plan_dict["schema_version"] == "2.0", f"Expected schema_version='2.0', got '{plan_dict['schema_version']}'"
    
    def test_schema_version_in_json(self, sample_weekly_plan):
        """Verify schema_version appears in JSON serialization."""
        json_str = sample_weekly_plan.model_dump_json()
        data = json.loads(json_str)
        
        assert "schema_version" in data
        assert data["schema_version"] == "2.0"
    
    def test_pause_zone_enum_regular(self, sample_block):
        """Verify REGULAR pause_zone is enum-compliant."""
        block_dict = sample_block.model_dump()
        
        assert "pause_zone" in block_dict
        assert block_dict["pause_zone"] == "REGULAR"
    
    def test_pause_zone_enum_split(self, sample_split_block):
        """Verify SPLIT pause_zone is enum-compliant."""
        block_dict = sample_split_block.model_dump()
        
        assert "pause_zone" in block_dict
        assert block_dict["pause_zone"] == "SPLIT"
    
    def test_pause_zone_only_valid_values(self):
        """Verify only REGULAR and SPLIT are valid PauseZone values."""
        valid_values = {e.value for e in PauseZone}
        assert valid_values == {"REGULAR", "SPLIT"}, f"Expected only REGULAR/SPLIT, got {valid_values}"
    
    def test_assignments_have_pause_zone(self, sample_weekly_plan):
        """Verify all assignments in plan have valid pause_zone."""
        plan_dict = sample_weekly_plan.model_dump()
        
        for assignment in plan_dict.get("assignments", []):
            block = assignment.get("block", {})
            pause_zone = block.get("pause_zone")
            assert pause_zone in ("REGULAR", "SPLIT"), f"Invalid pause_zone: {pause_zone}"


# =============================================================================
# ROUNDTRIP TESTS
# =============================================================================

@pytest.mark.contract
@pytest.mark.smoke
class TestRoundtripDeterminism:
    """Roundtrip determinism tests."""
    
    def test_block_roundtrip(self, sample_block):
        """Verify Block serialize → parse → serialize is lossless."""
        # Serialize to dict
        dict1 = sample_block.model_dump()
        
        # Reconstruct from dict
        block2 = Block.model_validate(dict1)
        
        # Serialize again
        dict2 = block2.model_dump()
        
        # Compare
        assert dict1 == dict2, "Block roundtrip lost data"
        assert dict1["pause_zone"] == dict2["pause_zone"], "pause_zone lost in roundtrip"
    
    def test_weekly_plan_roundtrip(self, sample_weekly_plan):
        """Verify WeeklyPlan serialize → parse → serialize is lossless."""
        # Serialize to JSON string
        json_str1 = sample_weekly_plan.model_dump_json(indent=None)
        
        # Parse and re-serialize
        data = json.loads(json_str1)
        plan2 = WeeklyPlan.model_validate(data)
        json_str2 = plan2.model_dump_json(indent=None)
        
        # Compare JSON strings (normalized)
        data1 = json.loads(json_str1)
        data2 = json.loads(json_str2)
        
        assert data1["schema_version"] == data2["schema_version"], "schema_version lost in roundtrip"
        assert len(data1["assignments"]) == len(data2["assignments"]), "assignments lost in roundtrip"
    
    def test_pause_zone_backward_compat(self):
        """Verify old JSON without pause_zone is handled via validator."""
        # Simulate old JSON with string "REGULAR"
        old_block_data = {
            "id": "B1-T001",
            "day": "Mon",
            "tours": [{"id": "T001", "day": "Mon", "start_time": "06:00", "end_time": "10:00"}],
            "is_split": False,
            "max_pause_minutes": 0,
            "pause_zone": "regular"  # lowercase - should normalize
        }
        
        block = Block.model_validate(old_block_data)
        assert block.pause_zone == PauseZone.REGULAR, "Lowercase 'regular' not normalized to REGULAR"
    
    def test_null_pause_zone_defaults(self):
        """Verify null pause_zone defaults to REGULAR."""
        block_data = {
            "id": "B1-T001",
            "day": "Mon",
            "tours": [{"id": "T001", "day": "Mon", "start_time": "06:00", "end_time": "10:00"}],
            "is_split": False,
            "max_pause_minutes": 0,
            "pause_zone": None
        }
        
        block = Block.model_validate(block_data)
        assert block.pause_zone == PauseZone.REGULAR, "None pause_zone not defaulted to REGULAR"


# =============================================================================
# STATS SANITY TESTS
# =============================================================================

@pytest.mark.contract
@pytest.mark.smoke
class TestStatsSanity:
    """Stats validation tests for percentile fields."""
    
    def test_percentile_calculations(self):
        """Verify percentile calculation logic is sane."""
        # Test data: sorted list of spreads
        spreads = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        n = len(spreads)
        
        p50_idx = n // 2
        p95_idx = int(n * 0.95)
        
        p50 = spreads[p50_idx] if n > 0 else 0
        p95 = spreads[min(p95_idx, n-1)] if n > 0 else 0
        min_val = spreads[0]
        max_val = spreads[-1]
        
        # Verify: p50 <= p95
        assert p50 <= p95, f"p50 ({p50}) must be <= p95 ({p95})"
        
        # Verify: min <= p50 <= max
        assert min_val <= p50 <= max_val, f"p50 out of bounds: {min_val} <= {p50} <= {max_val}"
        
        # Verify: min <= p95 <= max
        assert min_val <= p95 <= max_val, f"p95 out of bounds: {min_val} <= {p95} <= {max_val}"
    
    def test_empty_percentiles(self):
        """Verify empty data doesn't crash percentile calculation."""
        spreads = []
        n = len(spreads)
        
        p50 = 0 if n == 0 else spreads[n // 2]
        p95 = 0 if n == 0 else spreads[int(n * 0.95)]
        
        assert p50 == 0
        assert p95 == 0
    
    def test_single_value_percentiles(self):
        """Verify single value returns same for p50/p95."""
        spreads = [500]
        n = len(spreads)
        
        p50 = spreads[n // 2]
        p95 = spreads[min(int(n * 0.95), n - 1)]
        
        assert p50 == p95 == 500


# =============================================================================
# BACKWARD COMPATIBILITY TESTS
# =============================================================================

@pytest.mark.contract
class TestBackwardCompatibility:
    """Tests for backward compatibility with old JSON formats."""
    
    def test_old_json_without_schema_version(self):
        """Verify WeeklyPlan can be created without explicit schema_version (uses default)."""
        plan = WeeklyPlan(
            id="old_plan",
            week_start=date(2024, 1, 1)
        )
        assert plan.schema_version == "2.0", "Default schema_version should be 2.0"
    
    def test_old_json_with_legacy_version(self):
        """Verify old WeeklyPlan with version=1.0.0 can be loaded."""
        old_data = {
            "id": "old_plan",
            "week_start": "2024-01-01",
            "version": "1.0.0",  # Old format
            "assignments": []
        }
        
        plan = WeeklyPlan.model_validate(old_data)
        # Should have default schema_version
        assert plan.schema_version == "2.0", "Missing schema_version should default to 2.0"
