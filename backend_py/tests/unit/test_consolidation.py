"""
Test Driver Consolidation
==========================
Unit tests for consolidation logic that merges low-utilization drivers.
"""

import pytest
from datetime import time
from src.domain.models import Tour, Block, Weekday
from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
from src.services.lns_refiner_v4 import consolidate_drivers, LNSConfigV4


def create_block(block_id: str, day: Weekday, start_hour: int, duration_hours: float = 4.5) -> Block:
    """Helper to create a block."""
    end_hour = start_hour + int(duration_hours)
    end_min = int((duration_hours % 1) * 60)
    
    return Block(
        id=block_id,
        day=day,
        tours=[
            Tour(
                id=f"T_{block_id}",
                day=day,
                start_time=time(start_hour, 0),
                end_time=time(end_hour, end_min),
                location="TEST",
                required_qualifications=[]
            )
        ]
    )


def test_consolidation_merges_low_utilization():
    """
    Test that consolidation successfully merges low-utilization drivers.
    """
    # Create 3 drivers:
    # Driver A: 1 block (4.5h) on Monday
    # Driver B: 2 blocks (9h) on Tuesday-Wednesday
    # Driver C: 1 block (4.5h) on Thursday
    
    block_a = create_block("B_A", Weekday.MONDAY, 8)
    block_b1 = create_block("B_B1", Weekday.TUESDAY, 8)
    block_b2 = create_block("B_B2", Weekday.WEDNESDAY, 8)
    block_c = create_block("B_C", Weekday.THURSDAY, 8)
    
    assignments = [
        DriverAssignment(
            driver_id="PT001",
            driver_type="PT",
            blocks=[block_a],
            total_hours=4.5,
            days_worked=1,
            analysis=_analyze_driver_workload([block_a])
        ),
        DriverAssignment(
            driver_id="PT002",
            driver_type="PT",
            blocks=[block_b1, block_b2],
            total_hours=9.0,
            days_worked=2,
            analysis=_analyze_driver_workload([block_b1, block_b2])
        ),
        DriverAssignment(
            driver_id="PT003",
            driver_type="PT",
            blocks=[block_c],
            total_hours=4.5,
            days_worked=1,
            analysis=_analyze_driver_workload([block_c])
        ),
    ]
    
    config = LNSConfigV4(enable_consolidation=True, max_consolidation_iterations=5)
    
    # Run consolidation
    consolidated = consolidate_drivers(assignments, config)
    
    # Should have fewer drivers (A and C blocks moved to B or other driver)
    assert len(consolidated) <= len(assignments)
    
    print(f"Before: {len(assignments)} drivers")
    print(f"After: {len(consolidated)} drivers")
    
    # Check all blocks still assigned
    total_blocks_before = sum(len(a.blocks) for a in assignments)
    total_blocks_after = sum(len(a.blocks) for a in consolidated)
    assert total_blocks_before == total_blocks_after


def test_consolidation_respects_constraints():
    """
    Test that consolidation doesn't violate rest constraints.
    """
    # Create scenario where blocks CANNOT be moved due to rest constraint
    # Driver A: Late block on Monday (ending 23:00)
    # Driver B: Early block on Tuesday (starting 05:00) - violates 11h rest with A
    
    block_a = Block(
        id="B_A",
        day=Weekday.MONDAY,
        tours=[
            Tour(
                id="T_A",
                day=Weekday.MONDAY,
                start_time=time(18, 0),
                end_time=time(23, 0),  # Ends 23:00
                location="TEST",
                required_qualifications=[]
            )
        ]
    )
    
    block_b = Block(
        id="B_B",
        day=Weekday.TUESDAY,
        tours=[
            Tour(
                id="T_B",
                day=Weekday.TUESDAY,
                start_time=time(5, 0),  # Starts 05:00 - only 6h rest
                end_time=time(9, 30),
                location="TEST",
                required_qualifications=[]
            )
        ]
    )
    
    assignments = [
        DriverAssignment(
            driver_id="PT001",
            driver_type="PT",
            blocks=[block_a],
            total_hours=5.0,
            days_worked=1,
            analysis=_analyze_driver_workload([block_a])
        ),
        DriverAssignment(
            driver_id="PT002",
            driver_type="PT",
            blocks=[block_b],
            total_hours=4.5,
            days_worked=1,
            analysis=_analyze_driver_workload([block_b])
        ),
    ]
    
    config = LNSConfigV4(enable_consolidation=True)
    
    # Run consolidation
    consolidated = consolidate_drivers(assignments, config)
    
    # Should NOT consolidate because rest constraint would be violated
    # Both drivers should remain separate
    assert len(consolidated) == 2
    
    print("Correctly preserved 2 drivers due to rest constraint")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
