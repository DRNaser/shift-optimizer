"""
SOLVEREIGN V3 Fatigue Rule Unit Tests
======================================

Tests for the fatigue rule: No consecutive 3er→3er days.

Edge Cases Covered:
    1. Regular case: 3er on Mo, 3er on Di → FAIL
    2. Split case: 3er on Mo (with split), 3er on Di → FAIL
    3. Cross-midnight case: 3er ending Mo 02:00 (from So 22:00), 3er on Di → PASS (not consecutive)
    4. Day gap: 3er on Mo, 3er on Mi → PASS (Di is gap)
    5. Mixed blocks: 3er on Mo, 2er on Di, 3er on Mi → PASS
    6. Single 3er: 3er on Mo only → PASS
    7. 3er→3er at week boundary: 3er on Sa, 3er on So → FAIL
"""

import pytest
from datetime import time, date
from typing import List, Dict

# Import schemas and time normalizer
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from packs.roster.engine.schemas import Segment, Duty, BlockType, NormalizedTime
from packs.roster.engine.time_normalizer import TimeNormalizer, TimeRange


# ============================================================================
# TEST FIXTURES
# ============================================================================

def create_segment(day: int, start_hour: int, end_hour: int, crosses_midnight: bool = False) -> Segment:
    """Create a test segment."""
    tn = TimeNormalizer()
    start_ts = time(start_hour, 0)
    end_ts = time(end_hour, 0)

    return Segment(
        tour_instance_id=1,
        day=day,
        start_ts=start_ts,
        end_ts=end_ts,
        crosses_midnight=crosses_midnight,
        start=NormalizedTime.from_day_time(day, start_ts, False),
        end=NormalizedTime.from_day_time(day, end_ts, crosses_midnight),
        duration_min=(end_hour - start_hour) * 60 if not crosses_midnight else ((24 - start_hour) + end_hour) * 60,
        work_hours=(end_hour - start_hour) if not crosses_midnight else ((24 - start_hour) + end_hour),
    )


def create_3er_duty(day: int, driver: str = "D001") -> Duty:
    """Create a 3er duty (3 segments with 30-60min gaps)."""
    # 06:00-10:00, 10:45-14:00, 14:45-18:00
    segments = [
        create_segment(day, 6, 10),
        create_segment(day, 11, 14),
        create_segment(day, 15, 18),
    ]
    # Update normalized times for gaps
    segments[1].start = NormalizedTime.from_day_time(day, time(11, 0), False)
    segments[1].end = NormalizedTime.from_day_time(day, time(14, 0), False)
    segments[2].start = NormalizedTime.from_day_time(day, time(15, 0), False)
    segments[2].end = NormalizedTime.from_day_time(day, time(18, 0), False)

    return Duty(
        driver_id=driver,
        day=day,
        block_id=f"D{day}_B1",
        segments=segments,
        block_type=BlockType.TRIPLE,
    )


def create_2er_duty(day: int, driver: str = "D001") -> Duty:
    """Create a 2er-reg duty (2 segments with 30-60min gap)."""
    segments = [
        create_segment(day, 6, 10),
        create_segment(day, 11, 15),
    ]
    segments[1].start = NormalizedTime.from_day_time(day, time(11, 0), False)
    segments[1].end = NormalizedTime.from_day_time(day, time(15, 0), False)

    return Duty(
        driver_id=driver,
        day=day,
        block_id=f"D{day}_B1",
        segments=segments,
        block_type=BlockType.DOUBLE_REG,
    )


def create_3er_split_duty(day: int, driver: str = "D001") -> Duty:
    """Create a 3er duty with split (long break between segments)."""
    # 06:00-10:00, 15:00-18:00, 19:00-22:00 (5h break after first)
    segments = [
        create_segment(day, 6, 10),
        create_segment(day, 15, 18),
        create_segment(day, 19, 22),
    ]
    segments[1].start = NormalizedTime.from_day_time(day, time(15, 0), False)
    segments[1].end = NormalizedTime.from_day_time(day, time(18, 0), False)
    segments[2].start = NormalizedTime.from_day_time(day, time(19, 0), False)
    segments[2].end = NormalizedTime.from_day_time(day, time(22, 0), False)

    return Duty(
        driver_id=driver,
        day=day,
        block_id=f"D{day}_B1",
        segments=segments,
        block_type=BlockType.TRIPLE,  # Still 3er, but with split-like gap
    )


def create_cross_midnight_3er(day: int, driver: str = "D001") -> Duty:
    """Create a 3er duty that crosses midnight."""
    # Starts on day-1 evening, ends on day early morning
    # 18:00-22:00 (day-1), 22:30-02:00 (cross), 02:30-06:00 (day)
    prev_day = day - 1 if day > 1 else 7

    segments = [
        create_segment(prev_day, 18, 22),
        # Cross-midnight segment
        Segment(
            tour_instance_id=2,
            day=prev_day,
            start_ts=time(22, 30),
            end_ts=time(2, 0),
            crosses_midnight=True,
            start=NormalizedTime.from_day_time(prev_day, time(22, 30), False),
            end=NormalizedTime.from_day_time(prev_day, time(2, 0), True),
            duration_min=210,  # 3.5 hours
            work_hours=3.5,
        ),
        create_segment(day, 3, 6),  # Early morning segment
    ]
    segments[2].start = NormalizedTime.from_day_time(day, time(3, 0), False)
    segments[2].end = NormalizedTime.from_day_time(day, time(6, 0), False)

    return Duty(
        driver_id=driver,
        day=prev_day,  # Duty belongs to the starting day
        block_id=f"D{prev_day}_B1",
        segments=segments,
        block_type=BlockType.TRIPLE,
    )


# ============================================================================
# FATIGUE CHECK IMPLEMENTATION
# ============================================================================

def check_fatigue_violation(duties: List[Duty]) -> List[Dict]:
    """
    Check for consecutive 3er→3er violations.

    A violation occurs when:
    1. Two 3er blocks are on consecutive days
    2. For the same driver

    Args:
        duties: List of duties to check

    Returns:
        List of violations with details
    """
    violations = []

    # Group duties by driver
    by_driver: Dict[str, List[Duty]] = {}
    for duty in duties:
        if duty.driver_id not in by_driver:
            by_driver[duty.driver_id] = []
        by_driver[duty.driver_id].append(duty)

    # Check each driver
    for driver_id, driver_duties in by_driver.items():
        # Sort by day (considering cross-midnight)
        driver_duties_sorted = sorted(driver_duties, key=lambda d: d.day)

        # Find 3er blocks
        triple_days = [d for d in driver_duties_sorted if d.block_type == BlockType.TRIPLE]

        # Check for consecutive 3er days
        for i in range(len(triple_days) - 1):
            duty1 = triple_days[i]
            duty2 = triple_days[i + 1]

            # Check if days are consecutive
            day1 = duty1.day
            day2 = duty2.day

            # Handle week wrap (So=7 → Mo=1)
            is_consecutive = (
                (day2 == day1 + 1) or
                (day1 == 7 and day2 == 1)
            )

            if is_consecutive:
                violations.append({
                    "driver_id": driver_id,
                    "day1": day1,
                    "day2": day2,
                    "block_id1": duty1.block_id,
                    "block_id2": duty2.block_id,
                    "rule": "FATIGUE",
                    "description": f"Consecutive 3er→3er on days {day1} and {day2}",
                })

    return violations


# ============================================================================
# TEST CASES
# ============================================================================

class TestFatigueRule:
    """Test cases for the fatigue rule."""

    def test_consecutive_3er_violation(self):
        """Test 1: 3er on Mo, 3er on Di → FAIL"""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday
            create_3er_duty(day=2, driver="D001"),  # Tuesday
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 1
        assert violations[0]["driver_id"] == "D001"
        assert violations[0]["day1"] == 1
        assert violations[0]["day2"] == 2

    def test_3er_with_split_consecutive(self):
        """Test 2: 3er with split on Mo, 3er on Di → FAIL"""
        duties = [
            create_3er_split_duty(day=1, driver="D001"),  # Monday with split
            create_3er_duty(day=2, driver="D001"),  # Tuesday
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 1
        assert violations[0]["day1"] == 1
        assert violations[0]["day2"] == 2

    def test_cross_midnight_not_consecutive(self):
        """Test 3: Cross-midnight 3er, 3er on day after → Depends on duty day assignment"""
        # Cross-midnight duty starting Sunday evening
        # If duty.day = 7 (Sunday), then Tuesday (day=2) is NOT consecutive
        duties = [
            create_cross_midnight_3er(day=1, driver="D001"),  # Starts Sunday, ends Monday
            create_3er_duty(day=2, driver="D001"),  # Tuesday
        ]

        violations = check_fatigue_violation(duties)

        # The cross-midnight duty is assigned to day 7 (Sunday)
        # Tuesday (day 2) is not consecutive to Sunday (day 7)
        # So no violation expected in this case
        # Note: This depends on how the duty day is assigned for cross-midnight
        assert len(violations) == 0

    def test_day_gap_no_violation(self):
        """Test 4: 3er on Mo, 3er on Mi → PASS (Di is gap)"""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday
            create_3er_duty(day=3, driver="D001"),  # Wednesday
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 0

    def test_mixed_blocks_no_violation(self):
        """Test 5: 3er on Mo, 2er on Di, 3er on Mi → PASS"""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday 3er
            create_2er_duty(day=2, driver="D001"),  # Tuesday 2er
            create_3er_duty(day=3, driver="D001"),  # Wednesday 3er
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 0

    def test_single_3er_no_violation(self):
        """Test 6: 3er on Mo only → PASS"""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday only
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 0

    def test_week_boundary_violation(self):
        """Test 7: 3er on Sa, 3er on So → FAIL"""
        duties = [
            create_3er_duty(day=6, driver="D001"),  # Saturday
            create_3er_duty(day=7, driver="D001"),  # Sunday
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 1
        assert violations[0]["day1"] == 6
        assert violations[0]["day2"] == 7

    def test_different_drivers_no_violation(self):
        """Two different drivers can have consecutive 3er days."""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday D001
            create_3er_duty(day=2, driver="D002"),  # Tuesday D002
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 0

    def test_multiple_violations(self):
        """Driver with three consecutive 3er days → 2 violations."""
        duties = [
            create_3er_duty(day=1, driver="D001"),  # Monday
            create_3er_duty(day=2, driver="D001"),  # Tuesday
            create_3er_duty(day=3, driver="D001"),  # Wednesday
        ]

        violations = check_fatigue_violation(duties)

        assert len(violations) == 2
        assert violations[0]["day1"] == 1 and violations[0]["day2"] == 2
        assert violations[1]["day1"] == 2 and violations[1]["day2"] == 3

    def test_week_wrap_so_mo(self):
        """Test So→Mo across week boundary → FAIL if same week."""
        # Note: In practice, this would be across two different weeks
        # But if planning a single week, So→Mo within the week is violation
        duties = [
            create_3er_duty(day=7, driver="D001"),  # Sunday
            create_3er_duty(day=1, driver="D001"),  # Monday (next week, but in same plan)
        ]

        violations = check_fatigue_violation(duties)

        # Depends on interpretation: if both in same plan, it's a violation
        # Our implementation treats day 7 → day 1 as consecutive
        assert len(violations) == 1


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
