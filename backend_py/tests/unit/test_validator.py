"""
Tests for Validator
====================
Tests for the SINGLE SOURCE OF TRUTH constraint validation.
Each hard constraint is tested individually.
"""

import pytest
from datetime import time

from src.domain.models import (
    Tour,
    Driver,
    Block,
    DriverAssignment,
    DailyAvailability,
    Weekday,
    ReasonCode,
)
from src.domain.validator import (
    Validator,
    ValidationContext,
    create_empty_context,
    check_weekly_hours,
    check_daily_span,
    check_tours_per_day,
    check_blocks_per_day,
    check_rest_time,
    check_no_overlap,
    check_qualifications,
    check_availability,
    validate_block_structure,
    can_assign,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_driver() -> Driver:
    """Create a standard test driver."""
    return Driver(
        id="D001",
        name="Test Driver",
        qualifications=["CAT-B", "ADR"],
        max_weekly_hours=55.0,
        max_daily_span_hours=14.5,
        max_tours_per_day=3,
        min_rest_hours=11.0
    )


@pytest.fixture
def sample_tour() -> Tour:
    """Create a standard test tour."""
    return Tour(
        id="T001",
        day=Weekday.MONDAY,
        start_time=time(8, 0),
        end_time=time(12, 0),
        required_qualifications=["CAT-B"]
    )


@pytest.fixture
def sample_block(sample_tour: Tour) -> Block:
    """Create a standard test block."""
    return Block(
        id="B001",
        day=Weekday.MONDAY,
        tours=[sample_tour]
    )


# =============================================================================
# CONSTRAINT 1: MAX WEEKLY HOURS
# =============================================================================

class TestWeeklyHoursConstraint:
    """Tests for MAX_WEEKLY_HOURS constraint."""
    
    def test_under_limit(self, sample_driver: Driver, sample_block: Block):
        """Assignment under limit should pass."""
        valid, error = check_weekly_hours(sample_driver, sample_block, current_weekly_hours=40.0)
        assert valid is True
        assert error is None
    
    def test_at_limit(self, sample_driver: Driver, sample_block: Block):
        """Assignment at exact limit should pass."""
        # 4h block + 51h current = 55h exactly
        valid, error = check_weekly_hours(sample_driver, sample_block, current_weekly_hours=51.0)
        assert valid is True
    
    def test_over_limit(self, sample_driver: Driver, sample_block: Block):
        """Assignment over limit should fail."""
        # 4h block + 52h current = 56h > 55h
        valid, error = check_weekly_hours(sample_driver, sample_block, current_weekly_hours=52.0)
        assert valid is False
        assert "exceed weekly limit" in error.lower()
    
    def test_respects_driver_personal_limit(self, sample_block: Block):
        """Should respect driver's personal limit if lower than global."""
        driver = Driver(id="D1", name="Part-timer", max_weekly_hours=30.0)
        valid, error = check_weekly_hours(driver, sample_block, current_weekly_hours=27.0)
        assert valid is False  # 27 + 4 = 31 > 30


# =============================================================================
# CONSTRAINT 2: MAX DAILY SPAN
# =============================================================================

class TestDailySpanConstraint:
    """Tests for MAX_DAILY_SPAN_HOURS constraint."""
    
    def test_under_limit(self, sample_driver: Driver):
        """Block with span under limit should pass."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(18, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])  # 12h span
        
        valid, error = check_daily_span(sample_driver, block)
        assert valid is True
    
    def test_at_limit(self, sample_driver: Driver):
        """Block with span at limit should pass."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(19, 30))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])  # 14.5h span
        
        valid, error = check_daily_span(sample_driver, block)
        assert valid is True
    
    def test_over_limit(self, sample_driver: Driver):
        """Block with span over limit should fail."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(20, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])  # 15h span
        
        valid, error = check_daily_span(sample_driver, block)
        assert valid is False
        assert "span exceeds limit" in error.lower()


# =============================================================================
# CONSTRAINT 3: MAX TOURS PER DAY
# =============================================================================

class TestToursPerDayConstraint:
    """Tests for MAX_TOURS_PER_DAY constraint."""
    
    def test_within_limit(self, sample_driver: Driver):
        """Adding tours within limit should pass."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        new_block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])
        
        existing_tour = Tour(id="T0", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(7, 0))
        existing_block = Block(id="B0", day=Weekday.MONDAY, tours=[existing_tour])
        
        valid, error = check_tours_per_day(sample_driver, new_block, [existing_block])
        assert valid is True  # 1 existing + 1 new = 2 ≤ 3
    
    def test_at_limit(self, sample_driver: Driver):
        """Adding tours to reach limit should pass."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0))
        new_block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])
        
        t1 = Tour(id="T01", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(7, 0))
        t2 = Tour(id="T02", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        existing = Block(id="B0", day=Weekday.MONDAY, tours=[t1, t2])
        
        valid, error = check_tours_per_day(sample_driver, new_block, [existing])
        assert valid is True  # 2 existing + 1 new = 3 = limit
    
    def test_over_limit(self, sample_driver: Driver):
        """Adding tours beyond limit should fail."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(16, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(16, 30), end_time=time(18, 0))
        new_block = Block(id="B1", day=Weekday.MONDAY, tours=[t1, t2])
        
        te1 = Tour(id="T01", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(7, 0))
        te2 = Tour(id="T02", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        existing = Block(id="B0", day=Weekday.MONDAY, tours=[te1, te2])
        
        valid, error = check_tours_per_day(sample_driver, new_block, [existing])
        assert valid is False  # 2 existing + 2 new = 4 > 3


# =============================================================================
# CONSTRAINT 4: ONE BLOCK PER DAY
# =============================================================================

class TestBlocksPerDayConstraint:
    """Tests for MAX_BLOCKS_PER_DRIVER_PER_DAY constraint (split shifts)."""
    
    def test_first_block(self, sample_driver: Driver):
        """First block on a day should pass."""
        valid, error = check_blocks_per_day(sample_driver, Weekday.MONDAY, [])
        assert valid is True
    
    def test_second_block_passes_with_gap(self, sample_driver: Driver, sample_block: Block):
        """Second block on same day should pass (split shift, max 2 blocks/day)."""
        valid, error = check_blocks_per_day(sample_driver, Weekday.MONDAY, [sample_block])
        assert valid is True  # Now allows 2 blocks per day
    
    def test_third_block_fails(self, sample_driver: Driver, sample_block: Block):
        """Third block on same day should fail."""
        block2 = Block(
            id="B002",
            day=Weekday.MONDAY,
            tours=[Tour(id="T002", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0))]
        )
        valid, error = check_blocks_per_day(sample_driver, Weekday.MONDAY, [sample_block, block2])
        assert valid is False
        assert "already has 2 block(s)" in error.lower()


# =============================================================================
# CONSTRAINT 5: MIN REST TIME
# =============================================================================

class TestRestTimeConstraint:
    """Tests for MIN_REST_HOURS constraint."""
    
    def test_sufficient_rest(self, sample_driver: Driver, sample_block: Block):
        """With sufficient rest should pass."""
        # Previous day ended at 18:00, new block starts at 08:00
        # Rest = 24 - 18 + 8 = 14h > 11h
        prev_end = time(18, 0)
        valid, error = check_rest_time(sample_driver, sample_block, prev_end, None)
        assert valid is True
    
    def test_insufficient_rest(self, sample_driver: Driver):
        """With insufficient rest should fail."""
        # Block starts at 05:00, need 11h rest
        tour = Tour(id="T1", day=Weekday.TUESDAY, start_time=time(5, 0), end_time=time(9, 0))
        block = Block(id="B1", day=Weekday.TUESDAY, tours=[tour])
        
        # Previous day ended at 21:00
        # Rest = 24 - 21 + 5 = 8h < 11h
        prev_end = time(21, 0)
        valid, error = check_rest_time(sample_driver, block, prev_end, None)
        assert valid is False
        assert "rest violation" in error.lower()
    
    def test_no_previous_day(self, sample_driver: Driver, sample_block: Block):
        """No previous day data should pass."""
        valid, error = check_rest_time(sample_driver, sample_block, None, None)
        assert valid is True


# =============================================================================
# CONSTRAINT 6: NO OVERLAP
# =============================================================================

class TestNoOverlapConstraint:
    """Tests for NO_TOUR_OVERLAP constraint."""
    
    def test_no_overlap(self):
        """Non-overlapping tours should pass."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 0))
        
        valid, error = check_no_overlap([tour1, tour2])
        assert valid is True
    
    def test_overlap_detected(self):
        """Overlapping tours should fail."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(11, 0), end_time=time(15, 0))
        
        valid, error = check_no_overlap([tour1, tour2])
        assert valid is False
        assert "overlap" in error.lower()


# =============================================================================
# CONSTRAINT 7: QUALIFICATIONS
# =============================================================================

class TestQualificationConstraint:
    """Tests for QUALIFICATION_REQUIRED constraint."""
    
    def test_has_qualifications(self, sample_driver: Driver, sample_block: Block):
        """Driver with required qualifications should pass."""
        valid, error = check_qualifications(sample_driver, sample_block)
        assert valid is True
    
    def test_missing_qualification(self, sample_driver: Driver):
        """Driver missing qualifications should fail."""
        tour = Tour(
            id="T1",
            day=Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
            required_qualifications=["CAT-C"]  # Driver only has CAT-B
        )
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])
        
        valid, error = check_qualifications(sample_driver, block)
        assert valid is False
        assert "missing qualifications" in error.lower()


# =============================================================================
# CONSTRAINT 8: AVAILABILITY
# =============================================================================

class TestAvailabilityConstraint:
    """Tests for AVAILABILITY_REQUIRED constraint."""
    
    def test_available(self, sample_driver: Driver, sample_block: Block):
        """Available driver should pass."""
        valid, error = check_availability(sample_driver, sample_block)
        assert valid is True  # Default is available
    
    def test_not_available(self):
        """Unavailable driver should fail."""
        driver = Driver(
            id="D1",
            name="Weekend Only",
            weekly_availability=[
                DailyAvailability(day=Weekday.MONDAY, available=False)
            ]
        )
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour])
        
        valid, error = check_availability(driver, block)
        assert valid is False
        assert "not available" in error.lower()


# =============================================================================
# VALIDATOR CLASS TESTS
# =============================================================================

class TestValidator:
    """Tests for the Validator class itself."""
    
    def test_can_assign_valid(self, sample_driver: Driver, sample_block: Block):
        """Valid assignment should return True."""
        validator = Validator([sample_driver])
        can, reasons, explanation = validator.can_assign(sample_driver.id, sample_block)
        
        assert can is True
        assert len(reasons) == 0
    
    def test_can_assign_invalid_driver(self, sample_block: Block):
        """Unknown driver should fail."""
        validator = Validator([])
        can, reasons, explanation = validator.can_assign("UNKNOWN", sample_block)
        
        assert can is False
        assert ReasonCode.NO_AVAILABLE_DRIVER in reasons
    
    def test_validate_and_commit(self, sample_driver: Driver, sample_block: Block):
        """Valid assignment should commit to context."""
        validator = Validator([sample_driver])
        
        result = validator.validate_and_commit(sample_driver.id, sample_block)
        
        assert result.is_valid is True
        stats = validator.get_driver_stats(sample_driver.id)
        assert stats["weekly_hours"] == 4.0
    
    def test_third_block_same_day_fails(self, sample_driver: Driver):
        """Third block on same day should fail (max 2 for split shift)."""
        validator = Validator([sample_driver])
        
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        block1 = Block(id="B1", day=Weekday.MONDAY, tours=[tour1])
        
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0))
        block2 = Block(id="B2", day=Weekday.MONDAY, tours=[tour2])
        
        tour3 = Tour(id="T3", day=Weekday.MONDAY, start_time=time(20, 0), end_time=time(23, 0))
        block3 = Block(id="B3", day=Weekday.MONDAY, tours=[tour3])
        
        result1 = validator.validate_and_commit(sample_driver.id, block1)
        assert result1.is_valid is True
        
        result2 = validator.validate_and_commit(sample_driver.id, block2)
        assert result2.is_valid is True  # Now allowed (split shift)
        
        # Third block should fail
        can, reasons, _ = validator.can_assign(sample_driver.id, block3)
        assert can is False
        assert ReasonCode.BLOCK_ALREADY_ASSIGNED in reasons
    
    def test_weekly_hours_accumulate(self, sample_driver: Driver):
        """Hours should accumulate across days."""
        validator = Validator([sample_driver])
        
        # Add blocks on different days
        for i, day in enumerate([Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY]):
            tour = Tour(id=f"T{i}", day=day, start_time=time(8, 0), end_time=time(18, 0))
            block = Block(id=f"B{i}", day=day, tours=[tour])
            result = validator.validate_and_commit(sample_driver.id, block)
            assert result.is_valid is True
        
        stats = validator.get_driver_stats(sample_driver.id)
        assert stats["weekly_hours"] == 30.0  # 3 days × 10h
    
    def test_reset_clears_context(self, sample_driver: Driver, sample_block: Block):
        """Reset should clear all accumulated state."""
        validator = Validator([sample_driver])
        
        validator.validate_and_commit(sample_driver.id, sample_block)
        assert validator.get_driver_stats(sample_driver.id)["weekly_hours"] == 4.0
        
        validator.reset()
        assert validator.get_driver_stats(sample_driver.id)["weekly_hours"] == 0.0
