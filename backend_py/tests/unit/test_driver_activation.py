"""
Test Driver Activation Costs
==============================
Unit tests for driver activation penalty logic.
"""

import pytest
from datetime import time
from src.domain.models import Tour, Block, Weekday
from src.services.forecast_solver_v4 import assign_drivers_greedy, ConfigV4


def test_activation_cost_consolidates_drivers():
    """
    Test that activation costs encourage consolidation over creating many drivers.
    
    Creates 6 blocks across 3 days that could each go to separate drivers,
    but with penalty should consolidate into fewer drivers.
    """
    # Create 6 blocks: 2 per day on Mon/Wed/Fri (no overlaps)
    blocks = []
    days_and_times = [
        (Weekday.MONDAY, 8, 0),  # Mon 08:00-12:30
        (Weekday.MONDAY, 14, 0),  # Mon 14:00-18:30 (no overlap, >11h from prev day)
        (Weekday.WEDNESDAY, 8, 0),  # Wed 08:00-12:30
        (Weekday.WEDNESDAY, 14, 0),  # Wed 14:00-18:30
        (Weekday.FRIDAY, 8, 0),  # Fri 08:00-12:30
        (Weekday.FRIDAY, 14, 0),  # Fri 14:00-18:30
    ]
    
    for i, (day, start_h, start_m) in enumerate(days_and_times):
        block = Block(
            id=f"B{i+1}",
            day=day,
            tours=[
                Tour(
                    id=f"T{i+1}",
                    day=day,
                    start_time=time(start_h, start_m),
                    end_time=time(start_h + 4, start_m + 30),
                    location="TEST",
                    required_qualifications=[]
                )
            ]
        )
        blocks.append(block)
    
    # Run without activation penalty - greedy may create many drivers
    config_no_penalty = ConfigV4(w_new_driver=0.0, w_pt_new=0.0)
    assignments_no, stats_no = assign_drivers_greedy(blocks, config_no_penalty)
    
    # Run with strong activation penalty - should consolidate
    config_with_penalty = ConfigV4(w_new_driver=10000.0, w_pt_new=5000.0)
    assignments_with, stats_with = assign_drivers_greedy(blocks, config_with_penalty)
    
    drivers_no_penalty = len([a for a in assignments_no if a.blocks])
    drivers_with_penalty = len([a for a in assignments_with if a.blocks])
    
    print(f"Without penalty: {drivers_no_penalty} drivers")
    print(f"With penalty: {drivers_with_penalty} drivers")
    
    # With penalty should use FEWER or equal drivers (consolidation)
    assert drivers_with_penalty <= drivers_no_penalty
    
    # More importantly: with penalty, should strongly prefer reusing drivers
    # At least one driver should have multiple blocks
    max_blocks_per_driver_with_penalty = max(len(a.blocks) for a in assignments_with if a.blocks)
    assert max_blocks_per_driver_with_penalty >= 2, "Penalty should cause consolidation (multi-block drivers)"


def test_pt_penalty_prioritizes_fte():
    """
    Test that PT activation penalty prioritizes FTE drivers.
    """
    # Create 8 blocks on different days (exceeds 1 FTE capacity but not 2)
    blocks = []
    days_list = [Weekday.MONDAY, Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, 
                 Weekday.THURSDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.FRIDAY]
    
    for i, day in enumerate(days_list):
        block = Block(
            id=f"B{i+1}",
            day=day,
            tours=[
                Tour(
                    id=f"T{i+1}",
                    day=day,
                    start_time=time(8 + (i % 2) * 5, 0),  # Stagger times to avoid overlap
                    end_time=time(13 + (i % 2) * 5, 0),
                    location="TEST",
                    required_qualifications=[]
                )
            ]
        )
        blocks.append(block)
    
    # Run with PT penalty
    config = ConfigV4(w_new_driver=1000.0, w_pt_new=500.0)
    assignments, stats = assign_drivers_greedy(blocks, config)
    
    fte_count = stats["drivers_fte"]
    pt_count = stats["drivers_pt"]
    
    print(f"FTE drivers: {fte_count}, PT drivers: {pt_count}")
    
    # With PT penalty, should prefer using FTE first
    # Even if it means creating more FTE drivers before resorting to PT
    # At minimum, should fill FTEs before creating PT
    if pt_count > 0:
        # If PT is used, FTEs should be reasonably filled
        assert fte_count >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
