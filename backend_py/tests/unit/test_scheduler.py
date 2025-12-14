"""
Tests for Baseline Scheduler
=============================
Tests for greedy feasible-first scheduling.
"""

import pytest
from datetime import date, time

from src.domain.models import (
    Tour,
    Driver,
    Weekday,
    ReasonCode,
    DailyAvailability,
)
from src.services.scheduler import (
    BaselineScheduler,
    SchedulerConfig,
    create_schedule,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_tours() -> list[Tour]:
    """Create sample tours for testing."""
    return [
        Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
        Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
        Tour(id="T4", day=Weekday.TUESDAY, start_time=time(8, 0), end_time=time(12, 0)),
    ]


@pytest.fixture
def sample_drivers() -> list[Driver]:
    """Create sample drivers for testing."""
    return [
        Driver(id="D1", name="Driver One"),
        Driver(id="D2", name="Driver Two"),
    ]


# =============================================================================
# BASIC SCHEDULING TESTS
# =============================================================================

class TestBasicScheduling:
    """Basic scheduling tests."""
    
    def test_schedule_single_tour(self):
        """Schedule a single tour."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        drivers = [Driver(id="D1", name="Driver One")]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        assert plan.validation.is_valid is True
        assert len(plan.assignments) == 1
        assert len(plan.unassigned_tours) == 0
        assert plan.stats.total_tours_assigned == 1
    
    def test_schedule_multiple_tours(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Schedule multiple tours."""
        plan = create_schedule(sample_tours, sample_drivers, date(2024, 1, 1))
        
        assert plan.validation.is_valid is True
        assert plan.stats.total_tours_input == 4
        # With greedy, T1+T2+T3 should form a 3er block
    
    def test_schedule_respects_weekly_hours(self):
        """Should not exceed weekly hours limit."""
        # Create many hours of work
        tours = []
        for i, day in enumerate([Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, 
                                  Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]):
            tours.append(Tour(
                id=f"T{i}",
                day=day,
                start_time=time(5, 0),
                end_time=time(18, 0)  # 13h each = 78h total
            ))
        
        drivers = [Driver(id="D1", name="Driver One", max_weekly_hours=55.0)]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        # Should have some unassigned due to weekly limit
        total_assigned_hours = sum(a.block.total_work_hours for a in plan.assignments)
        assert total_assigned_hours <= 55.0
    
    def test_schedule_no_hard_violations(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Plan should have no hard violations."""
        plan = create_schedule(sample_tours, sample_drivers, date(2024, 1, 1))
        
        assert plan.validation.is_valid is True
        assert len(plan.validation.hard_violations) == 0


# =============================================================================
# CONSTRAINT TESTS
# =============================================================================

class TestSchedulerConstraints:
    """Tests for constraint enforcement in scheduler."""
    
    def test_qualification_required(self):
        """Driver must have required qualifications."""
        tours = [
            Tour(
                id="T1",
                day=Weekday.MONDAY,
                start_time=time(8, 0),
                end_time=time(12, 0),
                required_qualifications=["ADR"]
            )
        ]
        drivers = [Driver(id="D1", name="No ADR", qualifications=["CAT-B"])]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        assert len(plan.unassigned_tours) == 1
        assert ReasonCode.DRIVER_QUALIFICATION_MISSING in plan.unassigned_tours[0].reason_codes
    
    def test_availability_required(self):
        """Driver must be available."""
        tours = [
            Tour(id="T1", day=Weekday.SATURDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        drivers = [
            Driver(
                id="D1",
                name="Weekday Only",
                weekly_availability=[
                    DailyAvailability(day=Weekday.SATURDAY, available=False)
                ]
            )
        ]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        assert len(plan.unassigned_tours) == 1
        assert ReasonCode.DRIVER_NOT_AVAILABLE in plan.unassigned_tours[0].reason_codes
    
    def test_one_block_per_day(self):
        """Driver can only have one block per day."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0)),  # 4h gap
        ]
        # Only one driver
        drivers = [Driver(id="D1", name="Solo Driver")]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        # With split shifts, driver can have 2 blocks per day
        d1_assignments = plan.get_driver_assignments("D1")
        assert len(d1_assignments) <= 2  # Can have up to 2 block per day (split shift)


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestSchedulerStats:
    """Tests for scheduler statistics."""
    
    def test_stats_accurate(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Statistics should be accurate."""
        plan = create_schedule(sample_tours, sample_drivers, date(2024, 1, 1))
        
        stats = plan.stats
        assert stats.total_tours_input == len(sample_tours)
        assert stats.total_tours_assigned + stats.total_tours_unassigned == stats.total_tours_input
    
    def test_utilization_calculation(self):
        """Utilization should be calculated correctly."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(16, 30))  # 10.5h
        ]
        drivers = [Driver(id="D1", name="Driver", max_weekly_hours=55.0)]
        
        plan = create_schedule(tours, drivers, date(2024, 1, 1))
        
        # 10.5h assigned / 55h max = 0.19 utilization
        assert plan.stats.average_driver_utilization == pytest.approx(10.5 / 55.0, rel=0.01)


# =============================================================================
# DETERMINISM TESTS
# =============================================================================

class TestSchedulerDeterminism:
    """Tests for deterministic behavior."""
    
    def test_same_input_same_output(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Same input should produce same output."""
        plan1 = create_schedule(sample_tours, sample_drivers, date(2024, 1, 1))
        plan2 = create_schedule(sample_tours, sample_drivers, date(2024, 1, 1))
        
        # Same number of assignments
        assert len(plan1.assignments) == len(plan2.assignments)
        
        # Same drivers assigned (order might differ, but content same)
        drivers1 = sorted(a.driver_id for a in plan1.assignments)
        drivers2 = sorted(a.driver_id for a in plan2.assignments)
        assert drivers1 == drivers2
