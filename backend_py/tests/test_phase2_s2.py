"""
S2.5 Phase 2 Greedy Fill-to-Target Tests
========================================
Tests for fill-to-target scoring, block mix ratios, and rerun logic.
"""

import pytest
from datetime import time


class TestS21FillToTargetScore:
    """S2.1: Test fill-to-target scoring."""
    
    def test_fte_threshold_crossing_bonus(self):
        """FTE should get bonus for crossing min threshold."""
        from src.services.forecast_solver_v4 import fill_to_target_score, ConfigV4
        
        config = ConfigV4()._replace(enable_fill_to_target_greedy=True)  # Explicitly enable
        
        # Driver at 40h, adding 4h block crosses threshold
        score_crossing = fill_to_target_score(40.0, 4.0, "FTE", config)
        
        # Driver at 44h, adding 4h block doesn't cross
        score_no_crossing = fill_to_target_score(44.0, 4.0, "FTE", config)
        
        # Crossing should be much better (lower score)
        assert score_crossing < score_no_crossing
    
    def test_fte_distance_to_target(self):
        """FTE should prefer getting closer to target."""
        from src.services.forecast_solver_v4 import fill_to_target_score, ConfigV4
        
        config = ConfigV4()._replace(enable_fill_to_target_greedy=True)
        
        # Driver at 45h, adding block to get closer to 49.5
        score_closer = fill_to_target_score(45.0, 4.0, "FTE", config)  # -> 49h
        score_farther = fill_to_target_score(45.0, 8.0, "FTE", config)  # -> 53h, past target
        
        # Closer should be better
        assert score_closer < score_farther
    
    def test_pt_always_heavily_penalized(self):
        """PT should always have huge penalty compared to FTE."""
        from src.services.forecast_solver_v4 import fill_to_target_score, ConfigV4
        
        config = ConfigV4()._replace(enable_fill_to_target_greedy=True)
        
        score_fte = fill_to_target_score(45.0, 4.0, "FTE", config)
        score_pt = fill_to_target_score(45.0, 4.0, "PT", config)
        
        # PT penalty should be massive
        assert score_pt > score_fte + 1e5
    
    def test_overflow_infeasible(self):
        """Going over max hours should be infeasible."""
        from src.services.forecast_solver_v4 import fill_to_target_score, ConfigV4
        
        config = ConfigV4()._replace(enable_fill_to_target_greedy=True)  # max=53
        
        # 52 + 4 = 56 > max
        score = fill_to_target_score(52.0, 4.0, "FTE", config)
        
        # Should be astronomical
        assert score > 1e8


class TestS22BlockMixRatios:
    """S2.2: Test block mix ratio computation."""
    
    def test_pt_ratio_calculation(self):
        """PT ratio should be correctly calculated."""
        from src.services.forecast_solver_v4 import (
            compute_block_mix_ratios, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        # Mock assignments: 3 FTE, 1 PT
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[t1])
        
        assignments = [
            DriverAssignment("FTE-001", "FTE", [block], 45.0, 5),
            DriverAssignment("FTE-002", "FTE", [block], 48.0, 5),
            DriverAssignment("FTE-003", "FTE", [block], 50.0, 5),
            DriverAssignment("PT-001", "PT", [block], 10.0, 2),
        ]
        
        ratios = compute_block_mix_ratios(assignments, config)
        
        assert ratios["pt_ratio"] == 0.25  # 1/4
        assert ratios["pt_count"] == 1
        assert ratios["total_drivers"] == 4
    
    def test_underfull_ratio_calculation(self):
        """Underfull ratio should count FTE below min hours."""
        from src.services.forecast_solver_v4 import (
            compute_block_mix_ratios, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()  # min=42
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[t1])
        
        # 2 FTE underfull (< 42h), 2 FTE ok
        assignments = [
            DriverAssignment("FTE-001", "FTE", [block], 38.0, 5),  # Underfull
            DriverAssignment("FTE-002", "FTE", [block], 40.0, 5),  # Underfull
            DriverAssignment("FTE-003", "FTE", [block], 45.0, 5),  # OK
            DriverAssignment("FTE-004", "FTE", [block], 48.0, 5),  # OK
        ]
        
        ratios = compute_block_mix_ratios(assignments, config)
        
        assert ratios["underfull_ratio"] == 0.5  # 2/4
        assert ratios["underfull_fte_count"] == 2


class TestS23RerunTrigger:
    """S2.3: Test rerun trigger logic."""
    
    def test_trigger_on_high_pt_ratio(self):
        """Should trigger rerun when pt_ratio > threshold."""
        from src.services.forecast_solver_v4 import should_trigger_rerun, ConfigV4
        
        config = ConfigV4()._replace(enable_bad_block_mix_rerun=True)
        
        block_mix = {"pt_ratio": 0.30, "underfull_ratio": 0.10}
        
        should, reason = should_trigger_rerun(block_mix, config, False, 10.0)
        
        assert should == True
        assert "PT_RATIO_HIGH" in reason
    
    def test_trigger_on_high_underfull_ratio(self):
        """Should trigger rerun when underfull_ratio > threshold."""
        from src.services.forecast_solver_v4 import should_trigger_rerun, ConfigV4
        
        config = ConfigV4()._replace(enable_bad_block_mix_rerun=True)
        
        block_mix = {"pt_ratio": 0.10, "underfull_ratio": 0.20}
        
        should, reason = should_trigger_rerun(block_mix, config, False, 10.0)
        
        assert should == True
        assert "UNDERFULL_RATIO_HIGH" in reason
    
    def test_no_rerun_if_already_reran(self):
        """Should NOT trigger if already_reran is True."""
        from src.services.forecast_solver_v4 import should_trigger_rerun, ConfigV4
        
        config = ConfigV4()._replace(enable_bad_block_mix_rerun=True)
        
        block_mix = {"pt_ratio": 0.50, "underfull_ratio": 0.50}  # Bad mix
        
        should, reason = should_trigger_rerun(block_mix, config, True, 10.0)
        
        assert should == False
        assert "MAX_RERUN_REACHED" in reason
    
    def test_no_rerun_if_insufficient_budget(self):
        """Should NOT trigger if budget_left < min_rerun_budget."""
        from src.services.forecast_solver_v4 import should_trigger_rerun, ConfigV4
        
        config = ConfigV4()._replace(enable_bad_block_mix_rerun=True)
        
        block_mix = {"pt_ratio": 0.50}
        
        should, reason = should_trigger_rerun(block_mix, config, False, 3.0)  # Low budget
        
        assert should == False
        assert "INSUFFICIENT_BUDGET" in reason
    
    def test_no_rerun_if_mix_ok(self):
        """Should NOT trigger if ratios are acceptable."""
        from src.services.forecast_solver_v4 import should_trigger_rerun, ConfigV4
        
        config = ConfigV4()._replace(enable_bad_block_mix_rerun=True)
        
        block_mix = {"pt_ratio": 0.10, "underfull_ratio": 0.05}  # Good mix
        
        should, reason = should_trigger_rerun(block_mix, config, False, 10.0)
        
        assert should == False
        assert reason == "MIX_OK"


class TestS25Determinism:
    """S2.5: Verify Phase 2 functions are deterministic."""
    
    def test_fill_to_target_deterministic(self):
        """Same inputs should produce identical scores."""
        from src.services.forecast_solver_v4 import fill_to_target_score, ConfigV4
        
        config = ConfigV4()
        
        score1 = fill_to_target_score(45.0, 4.0, "FTE", config)
        score2 = fill_to_target_score(45.0, 4.0, "FTE", config)
        
        assert score1 == score2
    
    def test_block_mix_deterministic(self):
        """Same assignments should produce identical ratios."""
        from src.services.forecast_solver_v4 import (
            compute_block_mix_ratios, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        def make_assignments():
            t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
            block = Block(id="B1", day=Weekday.MONDAY, tours=[t1])
            return [
                DriverAssignment("FTE-001", "FTE", [block], 45.0, 5),
                DriverAssignment("PT-001", "PT", [block], 10.0, 2),
            ]
        
        ratios1 = compute_block_mix_ratios(make_assignments(), config)
        ratios2 = compute_block_mix_ratios(make_assignments(), config)
        
        assert ratios1 == ratios2
