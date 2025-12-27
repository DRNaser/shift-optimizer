"""
Reproduction script for the FTE/PT classification bug in the greedy fallback.

This script verifies that:
1. assign_drivers_greedy can create an FTE with < 40 hours (the bug).
2. rebalance_to_min_fte_hours correctly reclassifies such drivers to PT.
"""

import sys
from datetime import time as dt_time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.domain.models import Tour, Weekday
from src.services.smart_block_builder import build_weekly_blocks_smart
from src.services.forecast_solver_v4 import (
    ConfigV4,
    assign_drivers_greedy,
    rebalance_to_min_fte_hours,
)


def test_greedy_fallback_reclassification():
    """
    Test that underfilled FTEs are reclassified to PT after rebalance_to_min_fte_hours.
    """
    # Create a set of tours that cannot fill a 40h FTE week (e.g., 20 hours total)
    # 5 tours × 4 hours = 20 hours
    tours = []
    for i in range(5):
        day = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY][i]
        tours.append(
            Tour(
                id=f"tour_{i+1}",
                day=day,
                start_time=dt_time(8, 0),
                end_time=dt_time(12, 0),  # 4 hour tour
                location="TestLoc",
            )
        )

    # Build blocks from tours
    config = ConfigV4()
    blocks, _ = build_weekly_blocks_smart(tours, config)
    
    if not blocks:
        print("ERROR: No blocks generated from tours.")
        return False

    print(f"Generated {len(blocks)} blocks, total hours: {sum(b.total_work_hours for b in blocks):.1f}h")

    # Run greedy assignment
    assignments, _ = assign_drivers_greedy(blocks, config)
    
    if not assignments:
        print("ERROR: No assignments from greedy solver.")
        return False

    # Check for underfilled FTEs (the bug)
    underfilled_ftes_before = [
        a for a in assignments if a.driver_type == "FTE" and a.total_hours < 40.0
    ]
    print(f"\n--- Before rebalance_to_min_fte_hours ---")
    for a in assignments:
        print(f"  {a.driver_id}: {a.driver_type}, {a.total_hours:.1f}h")
    
    if underfilled_ftes_before:
        print(f"\nBUG CONFIRMED: {len(underfilled_ftes_before)} FTE(s) with < 40h before fix.")
    else:
        print("\nNo underfilled FTEs before fix (bug may not be reproducible with this data).")

    # Apply the fix
    assignments_fixed, stats = rebalance_to_min_fte_hours(assignments, 40.0, 53.0)
    
    print(f"\n--- After rebalance_to_min_fte_hours ---")
    for a in assignments_fixed:
        print(f"  {a.driver_id}: {a.driver_type}, {a.total_hours:.1f}h")
    print(f"\nRepair stats: {stats}")

    # Verify fix: no FTE should have < 40h
    underfilled_ftes_after = [
        a for a in assignments_fixed if a.driver_type == "FTE" and a.total_hours < 40.0
    ]
    
    if underfilled_ftes_after:
        print(f"\nFAILED: Still have {len(underfilled_ftes_after)} underfilled FTE(s) after fix!")
        return False
    else:
        print("\nPASSED: All FTEs have >= 40h or were reclassified to PT.")
        return True


if __name__ == "__main__":
    success = test_greedy_fallback_reclassification()
    sys.exit(0 if success else 1)
