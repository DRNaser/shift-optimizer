"""
Test: Lexicographic RMP - No Regression Smoke Test

This test ensures that the lexicographic RMP integration
does not cause regressions in 6-day (normal) weeks:
- Driver count within baseline tolerance
- Zero violations
- Status starts with "OK"

The lexiko path should only activate for compressed weeks (<=4 days).
Normal 6-day weeks should use the standard solver path.
"""

import pytest
from datetime import time as dtime


class TestLexikoNoRegression:
    """Smoke tests to verify no regression from lexiko integration."""
    
    def test_6day_week_stable_driver_count(self):
        """6-day week should produce stable results within tolerance."""
        from src.domain.models import Tour, Weekday
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        
        # Create a realistic 6-day week with 100 tours
        tours = []
        days = [
            Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
            Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
        ]
        
        for i in range(100):
            day = days[i % 6]
            # Stagger start times for variety
            hour = 6 + (i % 12)
            tours.append(Tour(
                id=f"T{i:03d}",
                day=day,
                start_time=dtime(hour, 0),
                end_time=dtime(hour + 4, 0),  # 4-hour tours
            ))
        
        result = solve_forecast_set_partitioning(
            tours=tours,
            time_limit=60.0,
            seed=42,
        )
        
        # Verify result status
        assert result.status.startswith("OK"), \
            f"Expected OK status, got {result.status}"
        
        # Verify driver count is reasonable (not zero, not exploding)
        drivers_total = result.kpi.get("drivers_total", 0)
        assert drivers_total > 0, "Must have at least 1 driver"
        assert drivers_total < 100, f"Too many drivers: {drivers_total} (expected << 100)"
    
    def test_6day_week_zero_violations(self):
        """6-day week should have zero violations."""
        from src.domain.models import Tour, Weekday
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        
        tours = []
        days = [
            Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
            Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
        ]
        
        for i in range(50):
            day = days[i % 6]
            tours.append(Tour(
                id=f"V{i:03d}",
                day=day,
                start_time=dtime(9, 0),
                end_time=dtime(13, 0),
            ))
        
        result = solve_forecast_set_partitioning(
            tours=tours,
            time_limit=45.0,
            seed=42,
        )
        
        # Check violations
        violations_total = result.kpi.get("violations_total", 0)
        assert violations_total == 0, \
            f"Expected 0 violations, got {violations_total}"
    
    def test_lexiko_function_directly_with_empty_pool(self):
        """solve_rmp_lexico should handle empty pool gracefully."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        result = solve_rmp_lexico(
            columns=[],
            target_ids={"A", "B"},
            coverage_attr="covered_tour_ids",
            time_limit_total=5.0,
            log_fn=lambda msg: None,
        )
        
        assert result["status"] == "INFEASIBLE"
        assert result["D_star"] == 0
        assert len(result["selected_rosters"]) == 0
    
    def test_lexiko_function_returns_expected_keys(self):
        """solve_rmp_lexico should return all expected keys."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # Minimal viable test
        class MockCol:
            def __init__(self, rid, items):
                self.roster_id = rid
                self.covered_tour_ids = set(items)
                self.block_ids = set(items)
                self.total_minutes = 1800
        
        columns = [MockCol("C1", ["X"])]
        
        result = solve_rmp_lexico(
            columns=columns,
            target_ids={"X"},
            coverage_attr="covered_tour_ids",
            time_limit_total=10.0,
            log_fn=lambda msg: None,
        )
        
        # Verify all expected keys are present
        expected_keys = [
            "status", "status_stage1", "status_stage2", "D_star",
            "selected_rosters", "singleton_selected", "short_roster_selected",
            "avg_tours_per_roster", "avg_hours", "zero_support_target_ids",
            "solve_time_stage1", "solve_time_stage2",
        ]
        
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
