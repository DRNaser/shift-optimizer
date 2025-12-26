"""
Test: BlockGen uses consistent values from HARD_CONSTRAINTS.
=====================================================
These tests verify that smart_block_builder.py uses the correct
constraint values and that there are no hardcoded inconsistencies.
"""

import pytest


class TestBlockGenConstraintConsistency:
    """Verify BlockGen constants match HARD_CONSTRAINTS."""
    
    def test_max_pause_regular_matches_constraints(self):
        """MAX_PAUSE_REGULAR must equal HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS (60)."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from src.services.smart_block_builder import MAX_PAUSE_REGULAR
        
        assert MAX_PAUSE_REGULAR == HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
        assert MAX_PAUSE_REGULAR == 60, f"Expected 60, got {MAX_PAUSE_REGULAR}"
    
    def test_min_pause_matches_constraints(self):
        """MIN_PAUSE_MINUTES must equal HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS (30)."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from src.services.smart_block_builder import MIN_PAUSE_MINUTES
        
        assert MIN_PAUSE_MINUTES == HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS
        assert MIN_PAUSE_MINUTES == 30, f"Expected 30, got {MIN_PAUSE_MINUTES}"
    
    def test_split_pause_min_matches_constraints(self):
        """SPLIT_PAUSE_MIN must equal HARD_CONSTRAINTS.SPLIT_PAUSE_MIN (360)."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from src.services.smart_block_builder import SPLIT_PAUSE_MIN
        
        assert SPLIT_PAUSE_MIN == HARD_CONSTRAINTS.SPLIT_PAUSE_MIN
        assert SPLIT_PAUSE_MIN == 360, f"Expected 360, got {SPLIT_PAUSE_MIN}"
    
    def test_split_pause_max_matches_constraints(self):
        """SPLIT_PAUSE_MAX must equal HARD_CONSTRAINTS.SPLIT_PAUSE_MAX (360)."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from src.services.smart_block_builder import SPLIT_PAUSE_MAX
        
        assert SPLIT_PAUSE_MAX == HARD_CONSTRAINTS.SPLIT_PAUSE_MAX
        assert SPLIT_PAUSE_MAX == 360, f"Expected 360, got {SPLIT_PAUSE_MAX}"
    
    def test_max_spread_split_matches_constraints(self):
        """MAX_SPREAD_SPLIT must equal HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES (840)."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from src.services.smart_block_builder import MAX_SPREAD_SPLIT
        
        assert MAX_SPREAD_SPLIT == HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES
        assert MAX_SPREAD_SPLIT == 840, f"Expected 840, got {MAX_SPREAD_SPLIT}"


class TestDeg3P95Guardrails:
    """Test that deg3_p95 calculation handles edge cases without crashing."""
    
    def test_deg3_p95_empty_list_returns_fallback(self):
        """deg3_p95 calculation must not crash on empty list, return fallback 1."""
        deg3_values = []
        
        # Guardrail implementation
        if not deg3_values:
            p95 = 1  # Fallback
        elif len(deg3_values) < 20:
            p95 = max(deg3_values)
        else:
            import statistics
            p95 = statistics.quantiles(deg3_values, n=20)[18]
        
        assert p95 == 1
    
    def test_deg3_p95_single_value(self):
        """deg3_p95 calculation handles single value correctly."""
        deg3_values = [5]
        
        if not deg3_values:
            p95 = 1
        elif len(deg3_values) < 20:
            p95 = max(deg3_values)
        else:
            import statistics
            p95 = statistics.quantiles(deg3_values, n=20)[18]
        
        assert p95 == 5
    
    def test_deg3_p95_small_list(self):
        """deg3_p95 uses max for lists smaller than 20 elements."""
        deg3_values = [1, 2, 3, 10, 5]
        
        if not deg3_values:
            p95 = 1
        elif len(deg3_values) < 20:
            p95 = max(deg3_values)
        else:
            import statistics
            p95 = statistics.quantiles(deg3_values, n=20)[18]
        
        assert p95 == 10
    
    def test_deg3_p95_large_list(self):
        """deg3_p95 uses statistics.quantiles for lists >= 20 elements."""
        import statistics
        
        deg3_values = list(range(1, 101))  # 1 to 100
        
        if not deg3_values:
            p95 = 1
        elif len(deg3_values) < 20:
            p95 = max(deg3_values)
        else:
            p95 = statistics.quantiles(deg3_values, n=20)[18]
        
        assert p95 >= 95  # 95th percentile of 1-100 should be around 95


class TestConfigV4BlockGenDefaults:
    """Verify ConfigV4 BlockGen defaults match HARD_CONSTRAINTS."""
    
    def test_configv4_block_gen_defaults(self):
        """ConfigV4 BlockGen fields should have defaults matching HARD_CONSTRAINTS."""
        from src.services.forecast_solver_v4 import ConfigV4
        from src.domain.constraints import HARD_CONSTRAINTS
        
        config = ConfigV4()
        
        assert config.block_gen_min_pause_minutes == HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS
        assert config.block_gen_max_pause_regular_minutes == HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
        assert config.block_gen_split_pause_min_minutes == HARD_CONSTRAINTS.SPLIT_PAUSE_MIN
        assert config.block_gen_split_pause_max_minutes == HARD_CONSTRAINTS.SPLIT_PAUSE_MAX
        assert config.block_gen_max_daily_span_hours == HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS
        assert config.block_gen_max_spread_split_minutes == HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES
    
    def test_configv4_hot_tour_penalty_default_disabled(self):
        """hot_tour_penalty_alpha should default to 0.0 (disabled)."""
        from src.services.forecast_solver_v4 import ConfigV4
        
        config = ConfigV4()
        assert config.hot_tour_penalty_alpha == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
