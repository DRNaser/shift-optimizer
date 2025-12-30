"""
Test: Repair trigger on zero-support detection.

This test verifies that:
1. Zero-support is correctly identified
2. The status ZERO_SUPPORT is returned (not generic INFEASIBLE)
3. Repair would be triggered (Repair A)
"""

import pytest


class MockRosterColumn:
    """Mock RosterColumn for testing."""
    
    def __init__(self, roster_id: str, covered_items: list[str], total_minutes: float):
        self.roster_id = roster_id
        self.covered_tour_ids = set(covered_items)
        self.block_ids = set(covered_items)
        self.total_minutes = total_minutes
        self.is_valid = True


class TestRepairTriggerZeroSupport:
    """Tests for zero-support detection and repair triggering."""
    
    def test_zero_support_single_tour_missing(self):
        """Single tour with no column coverage should trigger ZERO_SUPPORT."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        target_ids = {"T1", "T2", "T3_MISSING"}
        
        columns = [
            MockRosterColumn("COL_12", ["T1", "T2"], 1800),
            # T3_MISSING has no coverage!
        ]
        
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=100,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "ZERO_SUPPORT"
        assert "T3_MISSING" in result["zero_support_tours"]
    
    def test_zero_support_multiple_tours_missing(self):
        """Multiple tours without coverage should all be reported."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        target_ids = {"A", "B", "MISS1", "MISS2"}
        
        columns = [
            MockRosterColumn("COL_AB", ["A", "B"], 1800),
        ]
        
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=100,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "ZERO_SUPPORT"
        assert "MISS1" in result["zero_support_tours"]
        assert "MISS2" in result["zero_support_tours"]
    
    def test_empty_pool_is_zero_support(self):
        """Empty column pool should return ZERO_SUPPORT."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        result = solve_rmp_feasible_under_cap(
            columns=[],
            target_ids={"A", "B"},
            coverage_attr="covered_tour_ids",
            driver_cap=100,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "ZERO_SUPPORT"
        assert set(result["zero_support_tours"]) == {"A", "B"}
    
    def test_partial_coverage_detected(self):
        """Some tours covered, some not - should report uncovered ones."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        target_ids = {"X", "Y", "Z"}
        
        columns = [
            MockRosterColumn("COL_X", ["X"], 900),
            MockRosterColumn("COL_Y", ["Y"], 900),
            # Z not covered!
        ]
        
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=100,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "ZERO_SUPPORT"
        assert "Z" in result["zero_support_tours"]
        assert "X" not in result["zero_support_tours"]
        assert "Y" not in result["zero_support_tours"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
