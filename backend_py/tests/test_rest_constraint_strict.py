"""
TEST STRICT REST CONSTRAINTS
============================
Verifies that the strict 11h rest rule is correctly implemented
in the Central Service and Validator.
"""

import pytest
from datetime import time, date
from src.services.constraints import can_assign_block, MIN_REST_MINUTES
from src.domain.models import Block, Tour, Weekday, Driver, ValidationResult
from src.domain.validator import check_rest_time

# Mock classes
def make_block(block_id: str, day: Weekday, start_str: str, end_str: str) -> Block:
    h1, m1 = map(int, start_str.split(":"))
    h2, m2 = map(int, end_str.split(":"))
    t1 = Tour(id=f"T_{block_id}_1", day=day, start_time=time(h1, m1), end_time=time(h2, m2))
    return Block(id=block_id, day=day, tours=[t1])

def make_driver(driver_id: str) -> Driver:
    return Driver(id=driver_id, name=f"Driver {driver_id}")

# -----------------------------------------------------------------------------
# 1. Central Constraint Service Tests
# -----------------------------------------------------------------------------

def test_can_assign_block_rest_violation():
    """
    Scenario: Day 1 ends 23:00, Day 2 starts 05:30.
    Rest = (05:30 + 24h) - 23:00 = 29.5 - 23.0 = 6.5 hours.
    Expected: REJECT (6.5h < 11h).
    """
    b1 = make_block("B1", Weekday.MONDAY, "14:00", "23:00")
    b2 = make_block("B2", Weekday.TUESDAY, "05:30", "14:00")
    
    # Existing: B1. New: B2.
    allowed, reason = can_assign_block([b1], b2)
    assert not allowed
    assert "Rest Violation" in reason
    assert "6.50h" in reason

def test_can_assign_block_rest_success():
    """
    Scenario: Day 1 ends 18:00, Day 2 starts 05:30.
    Rest = (05:30 + 24h) - 18:00 = 29.5 - 18.0 = 11.5 hours.
    Expected: ACCEPT (11.5h >= 11h).
    """
    b1 = make_block("B1", Weekday.MONDAY, "09:00", "18:00")
    b2 = make_block("B2", Weekday.TUESDAY, "05:30", "14:00")
    
    allowed, reason = can_assign_block([b1], b2)
    assert allowed

def test_can_assign_block_exact_11h():
    """
    Scenario: Day 1 ends 18:30, Day 2 starts 05:30.
    Rest = (29.5 - 18.5) = 11.0 hours.
    Expected: ACCEPT.
    """
    b1 = make_block("B1", Weekday.MONDAY, "09:30", "18:30")
    b2 = make_block("B2", Weekday.TUESDAY, "05:30", "14:30")
    
    allowed, reason = can_assign_block([b1], b2)
    assert allowed

def test_can_assign_block_reverse_order():
    """
    Scenario: Existing is Tuesday 05:30 (B2), insert Monday 23:00 (B1).
    Should detect B1(Mon) -> B2(Tue) violation.
    """
    b1 = make_block("B1", Weekday.MONDAY, "14:00", "23:00")
    b2 = make_block("B2", Weekday.TUESDAY, "05:30", "14:00")
    
    # Existing: B2. Try to add B1.
    allowed, reason = can_assign_block([b2], b1)
    assert not allowed
    assert "Rest Violation" in reason

# -----------------------------------------------------------------------------
# 2. Validator Tests
# -----------------------------------------------------------------------------

def test_validator_check_rest_violation():
    """
    Scenario: Validator function check_rest_time with 23:00 -> 05:30.
    """
    driver = make_driver("D1")
    b_new = make_block("B_NEW", Weekday.TUESDAY, "05:30", "14:00")
    prev_end = time(23, 0) # Monday end
    
    valid, error = check_rest_time(driver, b_new, prev_day_last_end=prev_end, next_day_first_start=None)
    
    assert not valid
    assert "rest violation" in error.lower()
    assert "6.5h" in error

if __name__ == "__main__":
    print("Running tests manually...")
    try:
        test_can_assign_block_rest_violation()
        print("PASS: test_can_assign_block_rest_violation")
        test_can_assign_block_rest_success()
        print("PASS: test_can_assign_block_rest_success")
        test_can_assign_block_exact_11h()
        print("PASS: test_can_assign_block_exact_11h")
        test_can_assign_block_reverse_order()
        print("PASS: test_can_assign_block_reverse_order")
        test_validator_check_rest_violation()
        print("PASS: test_validator_check_rest_violation")
        print("ALL TESTS PASSED")
    except AssertionError as e:
        print(f"FAILED: {e}")
        raise
