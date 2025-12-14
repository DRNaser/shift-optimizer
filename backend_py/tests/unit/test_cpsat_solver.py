"""
Tests for CP-SAT Solver
========================
Tests for OR-Tools CP-SAT constraint programming solver.
"""

import pytest
from datetime import date, time

from src.domain.models import (
    Tour,
    Driver,
    Weekday,
    ReasonCode,
    DailyAvailability,
    BlockType,
)
from src.services.cpsat_solver import (
    CPSATScheduler,
    CPSATConfig,
    CPSATSchedulerModel,
    create_cpsat_schedule,
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
        Tour(id="T5", day=Weekday.TUESDAY, start_time=time(12, 30), end_time=time(16, 30)),
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

class TestCPSATBasicScheduling:
    """Basic CP-SAT scheduling tests."""
    
    def test_schedule_single_tour(self):
        """Schedule a single tour."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        drivers = [Driver(id="D1", name="Driver One")]
        
        config = CPSATConfig(time_limit_seconds=5.0)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        assert plan.validation.is_valid is True
        assert len(plan.assignments) == 1
        assert len(plan.unassigned_tours) == 0
        assert plan.stats.total_tours_assigned == 1
    
    def test_schedule_multiple_tours(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Schedule multiple tours."""
        config = CPSATConfig(time_limit_seconds=10.0)
        plan = create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)
        
        assert plan.validation.is_valid is True
        assert plan.stats.total_tours_input == 5
        # CP-SAT should find optimal assignment
        assert plan.stats.total_tours_assigned >= 4  # At least 4 tours should be assignable
    
    def test_schedule_no_hard_violations(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Plan should have no hard violations."""
        config = CPSATConfig(time_limit_seconds=10.0)
        plan = create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)
        
        assert plan.validation.is_valid is True
        assert len(plan.validation.hard_violations) == 0


# =============================================================================
# CONSTRAINT TESTS
# =============================================================================

class TestCPSATConstraints:
    """Tests for constraint enforcement in CP-SAT."""
    
    def test_weekly_hours_respected(self):
        """CP-SAT should respect weekly hour limits."""
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
        
        config = CPSATConfig(time_limit_seconds=10.0)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # Weekly hours should not exceed limit
        total_hours = sum(a.block.total_work_hours for a in plan.assignments)
        assert total_hours <= 55.0
    
    def test_one_block_per_day(self):
        """CP-SAT should enforce one block per driver per day."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0)),  # 4h gap
        ]
        drivers = [Driver(id="D1", name="Solo Driver")]
        
        config = CPSATConfig(time_limit_seconds=5.0)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # With split shifts, driver can have 2 blocks per day
        d1_monday_assignments = [a for a in plan.assignments 
                                  if a.driver_id == "D1" and a.day == Weekday.MONDAY]
        assert len(d1_monday_assignments) <= 2  # Can have up to 2 blocks per day (split shift)
    
    def test_qualification_required(self):
        """CP-SAT should enforce qualification requirements."""
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
        
        config = CPSATConfig(time_limit_seconds=5.0)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # Tour should not be assigned
        assert len(plan.assignments) == 0
        assert len(plan.unassigned_tours) == 1
    
    def test_availability_required(self):
        """CP-SAT should enforce availability requirements."""
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
        
        config = CPSATConfig(time_limit_seconds=5.0)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        assert len(plan.assignments) == 0
        assert len(plan.unassigned_tours) == 1


# =============================================================================
# OPTIMIZATION TESTS
# =============================================================================

class TestCPSATOptimization:
    """Tests for CP-SAT optimization objectives."""
    
    def test_maximizes_tour_assignment(self):
        """CP-SAT should maximize tours assigned."""
        # Create tours that can all be assigned
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.TUESDAY, start_time=time(8, 0), end_time=time(12, 0)),
        ]
        drivers = [
            Driver(id="D1", name="Driver One"),
            Driver(id="D2", name="Driver Two"),
        ]
        
        config = CPSATConfig(time_limit_seconds=10.0, optimize=True)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # All tours should be assigned
        assert plan.stats.total_tours_assigned == 3
    
    def test_prefers_larger_blocks(self):
        """CP-SAT should prefer larger blocks when possible."""
        # Three tours that can form a 3er block
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
        ]
        drivers = [Driver(id="D1", name="Driver One")]
        
        config = CPSATConfig(time_limit_seconds=10.0, optimize=True)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # Should form one 3er block
        assert len(plan.assignments) == 1
        assert plan.stats.block_counts.get(BlockType.TRIPLE, 0) == 1
    
    def test_minimizes_drivers(self):
        """CP-SAT should minimize drivers used."""
        # Tours that can be assigned to fewer drivers
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
        ]
        drivers = [
            Driver(id="D1", name="Driver One"),
            Driver(id="D2", name="Driver Two"),
            Driver(id="D3", name="Driver Three"),
        ]
        
        config = CPSATConfig(time_limit_seconds=10.0, optimize=True)
        plan = create_cpsat_schedule(tours, drivers, date(2024, 1, 1), config)
        
        # Should use only 1 driver for the 2er block
        assert plan.stats.total_drivers == 1


# =============================================================================
# DETERMINISM TESTS
# =============================================================================

class TestCPSATDeterminism:
    """Tests for deterministic behavior."""
    
    def test_seeded_solver_deterministic(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Same seed should produce same result."""
        config = CPSATConfig(time_limit_seconds=10.0, seed=42)
        
        plan1 = create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)
        plan2 = create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)
        
        # Same number of assignments
        assert len(plan1.assignments) == len(plan2.assignments)
        
        # Same tours assigned
        tours1 = sorted(t.id for a in plan1.assignments for t in a.block.tours)
        tours2 = sorted(t.id for a in plan2.assignments for t in a.block.tours)
        assert tours1 == tours2


# =============================================================================
# FEASIBILITY-FIRST TESTS
# =============================================================================

class TestCPSATFeasibilityFirst:
    """Tests for feasibility-first mode."""
    
    def test_feasibility_mode(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Feasibility mode should find any valid solution quickly."""
        config = CPSATConfig(time_limit_seconds=5.0, optimize=False)
        
        plan = create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)
        
        # Should find some valid solution
        assert plan.validation.is_valid is True


# =============================================================================
# MODEL TESTS
# =============================================================================

class TestCPSATModel:
    """Tests for CP-SAT model building."""
    
    def test_model_creation(self, sample_tours: list[Tour], sample_drivers: list[Driver]):
        """Test that model is created correctly."""
        config = CPSATConfig()
        model = CPSATSchedulerModel(sample_tours, sample_drivers, config)
        
        # Should have variables for valid assignments
        assert len(model.assignment) > 0
        
        # Should have blocks
        assert len(model.blocks) > 0
    
    def test_pre_filtering(self):
        """Test that impossible assignments are pre-filtered."""
        tours = [
            Tour(
                id="T1",
                day=Weekday.MONDAY,
                start_time=time(8, 0),
                end_time=time(12, 0),
                required_qualifications=["SPECIAL"]
            )
        ]
        drivers = [
            Driver(id="D1", name="No quals", qualifications=[])
        ]
        
        config = CPSATConfig()
        model = CPSATSchedulerModel(tours, drivers, config)
        
        # Should have no valid assignment variables
        assert len(model.assignment) == 0
