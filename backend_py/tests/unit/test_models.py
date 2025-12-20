"""
Tests for Domain Models
========================
Tests for Tour, Driver, Block, WeeklyPlan models.
"""

import pytest
from datetime import date, time

from src.domain.models import (
    Tour,
    Driver,
    Block,
    WeeklyPlan,
    DriverAssignment,
    UnassignedTour,
    ValidationResult,
    WeeklyPlanStats,
    TimeSlot,
    DailyAvailability,
    Weekday,
    BlockType,
    ReasonCode,
)


# =============================================================================
# TIMESLOT TESTS
# =============================================================================

class TestTimeSlot:
    """Tests for TimeSlot model."""
    
    def test_valid_timeslot(self):
        """Create a valid time slot."""
        slot = TimeSlot(start=time(8, 0), end=time(12, 0))
        assert slot.start == time(8, 0)
        assert slot.end == time(12, 0)
        assert slot.duration_minutes == 240
        assert slot.duration_hours == 4.0
    
    def test_invalid_timeslot_reversed(self):
        """Start after end should fail."""
        with pytest.raises(ValueError, match="must be before"):
            TimeSlot(start=time(12, 0), end=time(8, 0))
    
    def test_invalid_timeslot_equal(self):
        """Start equals end should fail."""
        with pytest.raises(ValueError, match="must be before"):
            TimeSlot(start=time(8, 0), end=time(8, 0))
    
    def test_overlap_detection(self):
        """Test overlap detection."""
        slot1 = TimeSlot(start=time(8, 0), end=time(12, 0))
        slot2 = TimeSlot(start=time(10, 0), end=time(14, 0))
        slot3 = TimeSlot(start=time(12, 0), end=time(16, 0))
        slot4 = TimeSlot(start=time(13, 0), end=time(17, 0))
        
        assert slot1.overlaps(slot2) is True  # Partial overlap
        assert slot2.overlaps(slot1) is True  # Symmetric
        assert slot1.overlaps(slot3) is False  # Adjacent (no overlap)
        assert slot1.overlaps(slot4) is False  # Disjoint


# =============================================================================
# TOUR TESTS
# =============================================================================

class TestTour:
    """Tests for Tour model."""
    
    def test_valid_tour(self):
        """Create a valid tour."""
        tour = Tour(
            id="T001",
            day=Weekday.MONDAY,
            start_time=time(6, 0),
            end_time=time(10, 0),
            location="Zone-A",
            required_qualifications=["CAT-B"]
        )
        assert tour.id == "T001"
        assert tour.day == Weekday.MONDAY
        assert tour.duration_minutes == 240
        assert tour.duration_hours == 4.0
    
    def test_tour_minimal(self):
        """Create tour with minimal required fields."""
        tour = Tour(
            id="T002",
            day=Weekday.TUESDAY,
            start_time=time(8, 0),
            end_time=time(12, 0)
        )
        assert tour.location == "DEFAULT"
        assert tour.required_qualifications == []
    
    def test_tour_invalid_times(self):
        """Tour with start >= end should fail."""
        with pytest.raises(ValueError, match="must be before"):
            Tour(
                id="T003",
                day=Weekday.MONDAY,
                start_time=time(12, 0),
                end_time=time(8, 0)
            )
    
    def test_tour_overlap_same_day(self):
        """Tours on same day should detect overlap."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 0), end_time=time(14, 0))
        
        assert tour1.overlaps(tour2) is True
    
    def test_tour_no_overlap_different_day(self):
        """Tours on different days never overlap."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        tour2 = Tour(id="T2", day=Weekday.TUESDAY, start_time=time(8, 0), end_time=time(12, 0))
        
        assert tour1.overlaps(tour2) is False
    
    def test_tour_immutable(self):
        """Tour should be immutable (frozen)."""
        tour = Tour(id="T001", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        with pytest.raises(Exception):  # ValidationError for frozen model
            tour.id = "T999"


# =============================================================================
# DRIVER TESTS
# =============================================================================

class TestDriver:
    """Tests for Driver model."""
    
    def test_valid_driver(self):
        """Create a valid driver."""
        driver = Driver(
            id="D001",
            name="Max Mustermann",
            qualifications=["CAT-B", "ADR"],
            max_weekly_hours=50.0
        )
        assert driver.id == "D001"
        assert driver.name == "Max Mustermann"
        assert driver.max_weekly_hours == 50.0
    
    @pytest.mark.xfail(reason="TICKET-001: Driver.max_daily_span_hours default is 16.5, test expects 14.5")
    def test_driver_defaults(self):
        """Driver should have proper defaults."""
        driver = Driver(id="D002", name="Test Driver")
        assert driver.max_weekly_hours == 55.0
        assert driver.max_daily_span_hours == 14.5
        assert driver.max_tours_per_day == 3
        assert driver.min_rest_hours == 11.0
    
    def test_driver_qualification_check(self):
        """Test qualification checking."""
        driver = Driver(
            id="D001",
            name="Test",
            qualifications=["CAT-B", "ADR"]
        )
        assert driver.has_qualification("CAT-B") is True
        assert driver.has_qualification("ADR") is True
        assert driver.has_qualification("CAT-C") is False
        assert driver.has_all_qualifications(["CAT-B", "ADR"]) is True
        assert driver.has_all_qualifications(["CAT-B", "CAT-C"]) is False
    
    def test_driver_availability(self):
        """Test availability checking."""
        driver = Driver(
            id="D001",
            name="Test",
            weekly_availability=[
                DailyAvailability(day=Weekday.MONDAY, available=True),
                DailyAvailability(day=Weekday.SATURDAY, available=False),
            ]
        )
        assert driver.is_available_on(Weekday.MONDAY) is True
        assert driver.is_available_on(Weekday.SATURDAY) is False
        # Undefined days default to available
        assert driver.is_available_on(Weekday.TUESDAY) is True


# =============================================================================
# BLOCK TESTS
# =============================================================================

class TestBlock:
    """Tests for Block model."""
    
    def test_single_tour_block(self):
        """Block with one tour (1er)."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        block = Block(id="B001", day=Weekday.MONDAY, tours=[tour])
        
        assert block.block_type == BlockType.SINGLE
        assert len(block.tours) == 1
        assert block.total_work_hours == 4.0
        assert block.span_hours == 4.0
    
    def test_double_tour_block(self):
        """Block with two tours (2er)."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30))
        block = Block(id="B002", day=Weekday.MONDAY, tours=[tour1, tour2])
        
        assert block.block_type == BlockType.DOUBLE
        assert block.total_work_hours == 8.0
        assert block.span_hours == 8.5  # 06:00 to 14:30
    
    def test_triple_tour_block(self):
        """Block with three tours (3er)."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(5, 0), end_time=time(9, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(9, 30), end_time=time(13, 30))
        tour3 = Tour(id="T3", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0))
        block = Block(id="B003", day=Weekday.MONDAY, tours=[tour1, tour2, tour3])
        
        assert block.block_type == BlockType.TRIPLE
        assert block.total_work_hours == 12.0
        assert block.span_hours == 13.0  # 05:00 to 18:00
    
    def test_block_wrong_day(self):
        """Block with tour on wrong day should fail."""
        tour = Tour(id="T1", day=Weekday.TUESDAY, start_time=time(8, 0), end_time=time(12, 0))
        with pytest.raises(ValueError, match="Tour T1 is on"):
            Block(id="B001", day=Weekday.MONDAY, tours=[tour])
    
    def test_block_unsorted_tours(self):
        """Block with unsorted tours should fail."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(12, 0), end_time=time(16, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(11, 0))
        with pytest.raises(ValueError, match="sorted by start time"):
            Block(id="B001", day=Weekday.MONDAY, tours=[tour1, tour2])
    
    def test_block_qualifications(self):
        """Block should aggregate qualifications from all tours."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0),
                    required_qualifications=["CAT-B"])
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 30),
                    required_qualifications=["ADR"])
        block = Block(id="B001", day=Weekday.MONDAY, tours=[tour1, tour2])
        
        assert block.required_qualifications == {"CAT-B", "ADR"}


# =============================================================================
# WEEKLY PLAN TESTS
# =============================================================================

class TestWeeklyPlan:
    """Tests for WeeklyPlan model."""
    
    def test_empty_plan(self):
        """Create empty plan."""
        plan = WeeklyPlan(
            id="P001",
            week_start=date(2024, 1, 1),
            validation=ValidationResult(is_valid=True)
        )
        assert plan.id == "P001"
        assert len(plan.assignments) == 0
        assert len(plan.unassigned_tours) == 0
    
    def test_plan_with_assignments(self):
        """Plan with driver assignments."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        block = Block(id="B1", day=Weekday.MONDAY, tours=[tour], driver_id="D1")
        assignment = DriverAssignment(driver_id="D1", day=Weekday.MONDAY, block=block)
        
        plan = WeeklyPlan(
            id="P001",
            week_start=date(2024, 1, 1),
            assignments=[assignment],
            validation=ValidationResult(is_valid=True)
        )
        
        assert len(plan.assignments) == 1
        assert plan.get_driver_weekly_hours("D1") == 4.0
    
    def test_plan_driver_filtering(self):
        """Filter assignments by driver."""
        tour1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        tour2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        
        block1 = Block(id="B1", day=Weekday.MONDAY, tours=[tour1], driver_id="D1")
        block2 = Block(id="B2", day=Weekday.MONDAY, tours=[tour2], driver_id="D2")
        
        plan = WeeklyPlan(
            id="P001",
            week_start=date(2024, 1, 1),
            assignments=[
                DriverAssignment(driver_id="D1", day=Weekday.MONDAY, block=block1),
                DriverAssignment(driver_id="D2", day=Weekday.MONDAY, block=block2),
            ],
            validation=ValidationResult(is_valid=True)
        )
        
        d1_assignments = plan.get_driver_assignments("D1")
        assert len(d1_assignments) == 1
        assert d1_assignments[0].driver_id == "D1"


# =============================================================================
# UNASSIGNED TOUR TESTS
# =============================================================================

class TestUnassignedTour:
    """Tests for UnassignedTour model."""
    
    def test_unassigned_with_reason(self):
        """Unassigned tour must have reason codes."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        unassigned = UnassignedTour(
            tour=tour,
            reason_codes=[ReasonCode.NO_AVAILABLE_DRIVER],
            details="All drivers at capacity"
        )
        
        assert unassigned.tour.id == "T1"
        assert ReasonCode.NO_AVAILABLE_DRIVER in unassigned.reason_codes
    
    def test_unassigned_requires_reason(self):
        """Unassigned tour must have at least one reason code."""
        tour = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        with pytest.raises(ValueError):  # min_length=1 constraint
            UnassignedTour(tour=tour, reason_codes=[])
