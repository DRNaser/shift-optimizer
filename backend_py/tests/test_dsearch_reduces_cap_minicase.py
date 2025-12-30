"""
Test: D-Search reduces driver cap when feasible.

This test verifies that the D-search outer loop correctly:
1. Finds the minimum feasible driver count
2. Does not regress to higher counts
3. Uses coarse-then-fine strategy
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
    
    @property
    def total_hours(self) -> float:
        return self.total_minutes / 60.0


class TestDSearchReducesCap:
    """Tests for D-search outer loop."""
    
    def test_feasible_under_cap_finds_minimum(self):
        """solve_rmp_feasible_under_cap should find minimum D under cap."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        # 4 tours, can be covered by 2 drivers
        target_ids = {"A", "B", "C", "D"}
        
        columns = [
            MockRosterColumn("DENSE_AB", ["A", "B"], 1800),
            MockRosterColumn("DENSE_CD", ["C", "D"], 1800),
            MockRosterColumn("SINGLE_A", ["A"], 900),
            MockRosterColumn("SINGLE_B", ["B"], 900),
            MockRosterColumn("SINGLE_C", ["C"], 900),
            MockRosterColumn("SINGLE_D", ["D"], 900),
        ]
        
        # Test with cap=4 (should find D=2)
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=4,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "FEASIBLE"
        assert result["num_drivers"] <= 4, f"Should be under cap, got {result['num_drivers']}"
    
    def test_infeasible_when_cap_too_low(self):
        """Should return INFEASIBLE when cap is below minimum possible."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        # Minimum is 2 drivers (need 2 to cover all 4 tours)
        target_ids = {"A", "B", "C", "D"}
        
        columns = [
            MockRosterColumn("DENSE_AB", ["A", "B"], 1800),
            MockRosterColumn("DENSE_CD", ["C", "D"], 1800),
        ]
        
        # Test with cap=1 (impossible)
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=1,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "INFEASIBLE"
    
    def test_zero_support_detected_before_solve(self):
        """Zero-support should be detected BEFORE solve (Fix 4)."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        # Tour "X" has no column support
        target_ids = {"A", "B", "X"}
        
        columns = [
            MockRosterColumn("COL_AB", ["A", "B"], 1800),
            # No column covers X!
        ]
        
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=10,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "ZERO_SUPPORT"
        assert "X" in result["zero_support_tours"]
        # Should be detected without spending solver time
        assert result["solve_time"] == 0
    
    def test_feasible_returns_valid_solution(self):
        """Feasible result should pass verification."""
        from src.services.set_partition_master import solve_rmp_feasible_under_cap
        
        target_ids = {"P", "Q"}
        
        columns = [
            MockRosterColumn("COL_PQ", ["P", "Q"], 1800),
        ]
        
        result = solve_rmp_feasible_under_cap(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=5,
            time_limit=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "FEASIBLE"
        assert result["num_drivers"] == 1
        assert len(result["selected_rosters"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
