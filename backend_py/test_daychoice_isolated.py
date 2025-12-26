"""
Test Day-Choice Phase 2 Solver in Isolation
============================================
Tests the Day-Choice CP-SAT solver independently from the full pipeline.
"""

from datetime import time
from src.domain.models import Block, Tour, Weekday
from src.services.daychoice_solver import solve_phase2_daychoice, DayChoiceConfig

def create_dummy_blocks(num_blocks_per_day=30):
    """Create simple dummy blocks for testing."""
    blocks = []
    block_id = 1
    
    weekdays = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    for day in weekdays:
        for i in range(num_blocks_per_day):
            # Create 1-tour blocks (simple case, avoid cross-midnight)
            start_hour = 6 + (i % 10)  # 6:00 to 15:00 (prevents cross-midnight)
            end_hour = start_hour + 8  # 8h blocks
            
            tour = Tour(
                id=f"T_{block_id}",
                day=day,
                start_time=time(start_hour, 0),
                end_time=time(end_hour, 0),
                location="Depot A"
            )
            
            block = Block(
                id=f"B_{block_id:04d}",
                day=day,
                tours=[tour],
                first_start=tour.start_time,
                last_end=tour.end_time,
                span_minutes=tour.duration_minutes,
                total_work_minutes=tour.duration_minutes,
                pause_minutes=0,
            )
            
            blocks.append(block)
            block_id += 1
    
    return blocks


def test_daychoice():
    """Test Day-Choice solver with dummy blocks."""
    print("=" * 70)
    print("DAY-CHOICE PHASE 2 ISOLATED TEST")
    print("=" * 70)
    
    # Create test blocks
    print("\n1. Creating dummy blocks...")
    blocks = create_dummy_blocks(num_blocks_per_day=30)
    print(f"   Created {len(blocks)} blocks (30 per day × 6 days)")
    
    # Count by day
    from collections import Counter
    day_counts = Counter(b.day for b in blocks)
    print("\n   Blocks by day:")
    for day in [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
               Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]:
        print(f"     {day.value}: {day_counts[day]} blocks")
    
    # Configure Day-Choice
    print("\n2. Configuring Day-Choice solver...")
    config = DayChoiceConfig(
        driver_cap=None,  # Minimize headcount
        min_hours_target=40.0,
        max_hours_target=50.0,
        max_hours_hard=55.0,
        min_rest_minutes=660,  # 11h
        no_consecutive_3er=True,
        time_limit_s=60.0,  # 1 minute for quick test
        seed=42,
    )
    print(f"   Time limit: {config.time_limit_s}s")
    print(f"   Target hours: {config.min_hours_target}h - {config.max_hours_target}h")
    
    # Run Day-Choice
    print("\n3. Running Day-Choice solver...")
    result = solve_phase2_daychoice(
        selected_blocks=blocks,
        config=config,
        log_fn=print,
    )
    
    # Print results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Status: {result.status}")
    print(f"Drivers used: {result.drivers_used}")
    print(f"Avg hours/driver: {result.avg_hours:.1f}h")
    print(f"Under 40h: {result.under40_count}")
    print(f"Over 50h: {result.over50_count}")
    print(f"Rest violations: {result.rest_violations}")
    print(f"3+3 violations: {result.consecutive_3er_violations}")
    print(f"Solve time: {result.solve_time_s:.1f}s")
    
    # Verify success
    if result.status in ["OPTIMAL", "FEASIBLE"]:
        print("\n[SUCCESS] Day-Choice found a solution!")
        
        # Theoretical minimum
        total_hours = sum(b.span_minutes / 60 for b in blocks)
        theoretical_min = int(total_hours / config.max_hours_hard) + 1
        print(f"\nTotal work: {total_hours:.1f}h")
        print(f"Theoretical min drivers (55h): {theoretical_min}")
        print(f"Actual drivers: {result.drivers_used}")
        print(f"Efficiency: {(theoretical_min / result.drivers_used * 100):.1f}%")
        
        # Check constraints
        assert result.rest_violations == 0, "REST VIOLATION DETECTED!"
        assert result.consecutive_3er_violations == 0, "3+3 VIOLATION DETECTED!"
        
        return True
    else:
        print(f"\n[FAILED] Status={result.status}")
        return False


if __name__ == "__main__":
    success = test_daychoice()
    exit(0 if success else 1)
