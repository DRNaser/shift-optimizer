"""
S1.5 Phase 1 Packability Quality Tests
======================================
Tests for tour_has_multi, packability metrics, and cost adjustments.
"""

import pytest
from datetime import time


class TestS11TourHasMulti:
    """S1.1: Test tour_has_multi precompute."""
    
    def test_tour_with_multi_returns_true(self):
        """Tour covered by 2er/3er block should return True."""
        from src.services.forecast_solver_v4 import compute_tour_has_multi
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        t2 = Tour(id="T002", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 0))
        tours = [t1, t2]
        
        # 1er for T001, 2er covering both
        blocks = [
            Block(id="B1-001", day=Weekday.MONDAY, tours=[t1]),  # 1er
            Block(id="B2-001-002", day=Weekday.MONDAY, tours=[t1, t2]),  # 2er
        ]
        
        result = compute_tour_has_multi(blocks, tours)
        
        assert result["T001"] == True, "T001 should have multi option"
        assert result["T002"] == True, "T002 should have multi option"
    
    def test_tour_only_1er_returns_false(self):
        """Tour covered ONLY by 1er blocks should return False."""
        from src.services.forecast_solver_v4 import compute_tour_has_multi
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        tours = [t1]
        
        # Only 1er blocks
        blocks = [
            Block(id="B1-001-a", day=Weekday.MONDAY, tours=[t1]),
            Block(id="B1-001-b", day=Weekday.MONDAY, tours=[t1]),
        ]
        
        result = compute_tour_has_multi(blocks, tours)
        
        assert result["T001"] == False, "T001 has no multi option"


class TestS14PackabilityMetrics:
    """S1.4: Test packability metrics computation."""
    
    def test_forced_1er_rate_calculation(self):
        """Forced 1er rate should be correct."""
        from src.services.forecast_solver_v4 import compute_packability_metrics
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        t2 = Tour(id="T002", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 0))
        tours = [t1, t2]
        
        # T001 has both 1er and 2er, T002 only has 1er (forced)
        all_blocks = [
            Block(id="B1-001", day=Weekday.MONDAY, tours=[t1]),
            Block(id="B2-001-002", day=Weekday.MONDAY, tours=[t1, t2]),
            Block(id="B1-002", day=Weekday.MONDAY, tours=[t2]),
        ]
        
        # Solution uses 1er for both
        selected_blocks = [
            Block(id="B1-001", day=Weekday.MONDAY, tours=[t1]),
            Block(id="B1-002", day=Weekday.MONDAY, tours=[t2]),
        ]
        
        metrics = compute_packability_metrics(selected_blocks, all_blocks, tours)
        
        # Only T002 is "forced" (no multi available in pool - wait, T002 is in 2er too)
        # Actually both T001 and T002 are in the 2er, so forced_1er = 0
        assert metrics["forced_1er_count"] == 0
        assert metrics["total_tours"] == 2
    
    def test_missed_3er_opps_detection(self):
        """Should detect when 1er is used despite 3er being available."""
        from src.services.forecast_solver_v4 import compute_packability_metrics
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        t2 = Tour(id="T002", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 0))
        t3 = Tour(id="T003", day=Weekday.MONDAY, start_time=time(14, 30), end_time=time(18, 0))
        tours = [t1, t2, t3]
        
        # Pool has 1er for each AND a 3er
        all_blocks = [
            Block(id="B1-001", day=Weekday.MONDAY, tours=[t1]),
            Block(id="B1-002", day=Weekday.MONDAY, tours=[t2]),
            Block(id="B1-003", day=Weekday.MONDAY, tours=[t3]),
            Block(id="B3-all", day=Weekday.MONDAY, tours=[t1, t2, t3]),  # 3er
        ]
        
        # Solution uses 1er for all (missing 3er opportunity)
        selected_blocks = [
            Block(id="B1-001", day=Weekday.MONDAY, tours=[t1]),
            Block(id="B1-002", day=Weekday.MONDAY, tours=[t2]),
            Block(id="B1-003", day=Weekday.MONDAY, tours=[t3]),
        ]
        
        metrics = compute_packability_metrics(selected_blocks, all_blocks, tours)
        
        # All 3 tours missed 3er opportunity
        assert metrics["missed_3er_opps_count"] == 3


class TestS12S13CostAdjustments:
    """S1.2-S1.3: Test cost adjustments for packability."""
    
    def test_1er_with_alternative_penalty(self):
        """1er block should get penalty if tour has multi option."""
        from src.services.forecast_solver_v4 import (
            compute_packability_cost_adjustments, ConfigV4
        )
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        config = ConfigV4()
        
        block_1er = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
        
        # Tour HAS multi option
        tour_has_multi = {"T001": True}
        adjustment = compute_packability_cost_adjustments(block_1er, tour_has_multi, config)
        
        assert adjustment > 0, "Should have penalty for 1er when multi exists"
    
    def test_1er_without_alternative_no_penalty(self):
        """1er block should NOT get penalty if tour has no multi option."""
        from src.services.forecast_solver_v4 import (
            compute_packability_cost_adjustments, ConfigV4
        )
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        config = ConfigV4()
        
        block_1er = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
        
        # Tour has NO multi option
        tour_has_multi = {"T001": False}
        adjustment = compute_packability_cost_adjustments(block_1er, tour_has_multi, config)
        
        # Only 3er/2er bonuses apply (which are negative), no 1er penalty
        assert adjustment == 0, "No penalty for forced 1er"
    
    def test_3er_bonus(self):
        """3er block should get bonus (negative adjustment)."""
        from src.services.forecast_solver_v4 import (
            compute_packability_cost_adjustments, ConfigV4
        )
        from src.domain.models import Block, Tour, Weekday
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        t2 = Tour(id="T002", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 0))
        t3 = Tour(id="T003", day=Weekday.MONDAY, start_time=time(14, 30), end_time=time(18, 0))
        config = ConfigV4()
        
        block_3er = Block(id="B3-all", day=Weekday.MONDAY, tours=[t1, t2, t3])
        
        tour_has_multi = {"T001": True, "T002": True, "T003": True}
        adjustment = compute_packability_cost_adjustments(block_3er, tour_has_multi, config)
        
        assert adjustment < 0, "3er should get bonus (negative cost)"


class TestS15Determinism:
    """S1.5: Verify packability functions are deterministic."""
    
    def test_tour_has_multi_deterministic(self):
        """Same input should produce identical output."""
        from src.services.forecast_solver_v4 import compute_tour_has_multi
        from src.domain.models import Block, Tour, Weekday
        
        def create_input():
            tours = [
                Tour(id=f"T{i:03d}", day=Weekday.MONDAY, start_time=time(6+i, 0), end_time=time(10+i, 0))
                for i in range(10)
            ]
            blocks = [
                Block(id=f"B1-T{i:03d}", day=Weekday.MONDAY, tours=[tours[i]])
                for i in range(10)
            ]
            # Add some 2ers
            for i in range(0, 8, 2):
                blocks.append(Block(
                    id=f"B2-T{i:03d}-T{i+1:03d}",
                    day=Weekday.MONDAY,
                    tours=[tours[i], tours[i+1]]
                ))
            return blocks, tours
        
        blocks1, tours1 = create_input()
        blocks2, tours2 = create_input()
        
        result1 = compute_tour_has_multi(blocks1, tours1)
        result2 = compute_tour_has_multi(blocks2, tours2)
        
        # Must be identical
        assert result1 == result2, "Determinism violated"
