"""
Test Portfolio Controller with Real Data
==========================================
Run the portfolio controller with forecast data and display insights.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from time import perf_counter
from datetime import time

# Import domain models
from src.domain.models import Tour, Weekday

# Import insights interface
from src.services.insights import (
    solve_with_insights,
    print_day_analysis,
    print_driver_summary,
    InsightsResult,
)


def create_sample_tours() -> list[Tour]:
    """
    Create sample tour data for testing.
    Based on typical weekly forecast patterns.
    """
    tours = []
    tour_id = 1
    
    # Realistic tour patterns for each day
    day_patterns = {
        Weekday.MONDAY: [
            (time(5, 30), time(10, 0)),
            (time(6, 0), time(10, 30)),
            (time(6, 30), time(11, 0)),
            (time(7, 0), time(11, 30)),
            (time(7, 30), time(12, 0)),
            (time(8, 0), time(12, 30)),
            (time(10, 0), time(14, 30)),
            (time(10, 30), time(15, 0)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
            (time(14, 0), time(18, 30)),
            (time(15, 0), time(19, 30)),
            (time(16, 0), time(20, 30)),
            (time(17, 0), time(21, 30)),
            (time(18, 0), time(22, 30)),
        ],
        Weekday.TUESDAY: [
            (time(5, 30), time(10, 0)),
            (time(6, 0), time(10, 30)),
            (time(6, 30), time(11, 0)),
            (time(7, 0), time(11, 30)),
            (time(8, 0), time(12, 30)),
            (time(9, 0), time(13, 30)),
            (time(10, 0), time(14, 30)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
            (time(14, 0), time(18, 30)),
            (time(15, 0), time(19, 30)),
            (time(16, 0), time(20, 30)),
            (time(17, 0), time(21, 30)),
        ],
        Weekday.WEDNESDAY: [
            (time(5, 30), time(10, 0)),
            (time(6, 0), time(10, 30)),
            (time(6, 30), time(11, 0)),
            (time(7, 0), time(11, 30)),
            (time(8, 0), time(12, 30)),
            (time(9, 0), time(13, 30)),
            (time(10, 0), time(14, 30)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
            (time(14, 0), time(18, 30)),
            (time(15, 0), time(19, 30)),
            (time(16, 0), time(20, 30)),
        ],
        Weekday.THURSDAY: [
            (time(5, 30), time(10, 0)),
            (time(6, 0), time(10, 30)),
            (time(6, 30), time(11, 0)),
            (time(7, 0), time(11, 30)),
            (time(8, 0), time(12, 30)),
            (time(9, 0), time(13, 30)),
            (time(10, 0), time(14, 30)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
            (time(14, 0), time(18, 30)),
            (time(15, 0), time(19, 30)),
            (time(16, 0), time(20, 30)),
            (time(17, 0), time(21, 30)),
        ],
        Weekday.FRIDAY: [
            (time(5, 0), time(9, 30)),
            (time(5, 30), time(10, 0)),
            (time(6, 0), time(10, 30)),
            (time(6, 30), time(11, 0)),
            (time(7, 0), time(11, 30)),
            (time(7, 30), time(12, 0)),
            (time(8, 0), time(12, 30)),
            (time(8, 30), time(13, 0)),
            (time(9, 0), time(13, 30)),
            (time(10, 0), time(14, 30)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
            (time(14, 0), time(18, 30)),
            (time(15, 0), time(19, 30)),
            (time(16, 0), time(20, 30)),
            (time(17, 0), time(21, 30)),
            (time(18, 0), time(22, 30)),
        ],
        Weekday.SATURDAY: [
            (time(6, 0), time(10, 30)),
            (time(7, 0), time(11, 30)),
            (time(8, 0), time(12, 30)),
            (time(9, 0), time(13, 30)),
            (time(10, 0), time(14, 30)),
            (time(11, 0), time(15, 30)),
            (time(12, 0), time(16, 30)),
            (time(13, 0), time(17, 30)),
        ],
    }
    
    # Create tours for each day
    for day, patterns in day_patterns.items():
        for start, end in patterns:
            tour = Tour(
                id=f"T{tour_id:03d}",
                day=day,
                start_time=start,
                end_time=end,
                location="HQ",
                required_qualifications=[]
            )
            tours.append(tour)
            tour_id += 1
    
    return tours


def main():
    print("\n" + "=" * 70)
    print("PORTFOLIO CONTROLLER - INTEGRATION TEST")
    print("=" * 70)
    
    # Create sample tours
    tours = create_sample_tours()
    print(f"\nCreated {len(tours)} sample tours")
    
    # Calculate expected metrics
    total_hours = sum(t.duration_hours for t in tours)
    print(f"Total work hours: {total_hours:.1f}h")
    print(f"Expected drivers: {int(total_hours/53)}-{int(total_hours/42)}")
    
    # Run portfolio optimization with insights
    print("\n" + "-" * 70)
    print("Running Portfolio Optimization...")
    print("-" * 70)
    
    result = solve_with_insights(
        tours=tours,
        time_budget=30.0,
        seed=42,
        verbose=True,
        report_path="logs/test_run_report.json",
    )
    
    # Additional analysis
    print_day_analysis(result)
    print_driver_summary(result, top_n=5)
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print(result.summary())
    
    # Return exit code based on result
    if result.status in ["OK", "COMPLETED", "OPTIMAL", "FEASIBLE"]:
        print("\n[PASS] Test PASSED")
        return 0
    else:
        print(f"\n[FAIL] Test FAILED: {result.status}")
        return 1


if __name__ == "__main__":
    exit(main())
