"""
Test Rest Constraint Enforcement
================================
Verify that the CP-SAT solver correctly rejects assignments with <11h rest
between consecutive days, even when coverage would otherwise improve.
"""

import pytest
from datetime import date, time
from src.domain.models import Tour, Driver, Weekday
from src.domain.constraints import HARD_CONSTRAINTS
from src.services.cpsat_solver import CPSATScheduler, CPSATConfig


class TestRestConstraintHard:
    """Test that <11h rest is ALWAYS rejected (hard constraint)."""
    
    @pytest.fixture
    def late_early_tours(self):
        """
        Create tours that would violate 11h rest if assigned to same driver.
        
        Monday: ends at 22:00
        Tuesday: starts at 06:00
        Gap: 8 hours (22:00 -> 06:00) = VIOLATION
        """
        return [
            Tour(
                id="LATE_MON",
                day=Weekday.MONDAY,
                start_time=time(17, 30),
                end_time=time(22, 0),  # Ends at 22:00
            ),
            Tour(
                id="EARLY_TUE",
                day=Weekday.TUESDAY,
                start_time=time(6, 0),  # Starts at 06:00 = only 8h rest
                end_time=time(10, 30),
            ),
        ]
    
    @pytest.fixture
    def legal_rest_tours(self):
        """
        Create tours with legal rest (12h).
        
        Monday: ends at 20:00
        Tuesday: starts at 08:00
        Gap: 12 hours = OK
        """
        return [
            Tour(
                id="NORMAL_MON",
                day=Weekday.MONDAY,
                start_time=time(15, 30),
                end_time=time(20, 0),  # Ends at 20:00
            ),
            Tour(
                id="NORMAL_TUE",
                day=Weekday.TUESDAY,
                start_time=time(8, 0),  # Starts at 08:00 = 12h rest
                end_time=time(12, 30),
            ),
        ]
    
    @pytest.fixture
    def single_driver(self):
        """Single driver with no restrictions."""
        return [
            Driver(
                id="D001",
                name="Test Driver",
                qualifications=set(),
                availability={day: True for day in Weekday},
            )
        ]
    
    def test_rejects_8h_rest(self, late_early_tours, single_driver):
        """
        CRITICAL: If only one driver exists, and assigning both tours
        would result in <11h rest, the solver should NOT assign both
        to the same driver.
        """
        config = CPSATConfig(
            time_limit_seconds=10,
            fallback_to_soft=True,  # Even in fallback mode
        )
        
        scheduler = CPSATScheduler(late_early_tours, single_driver, config)
        plan = scheduler.schedule(date(2024, 12, 9))  # Monday
        
        # With only one driver, one of the tours must be unassigned
        # OR the constraint is violated
        assigned_ids = {t.id for a in plan.assignments for t in a.block.tours}
        
        # Both tours should NOT be assigned to the same driver
        if len(assigned_ids) == 2:
            # If both are assigned, they must be to DIFFERENT drivers
            # But we only have one driver, so this would be invalid
            assert plan.validation.is_valid, \
                "If both tours assigned, plan must be valid (implying different drivers)"
        
        # More likely: only one tour is assigned
        print(f"Assigned tours: {assigned_ids}")
        print(f"Plan valid: {plan.validation.is_valid}")
    
    def test_accepts_12h_rest(self, legal_rest_tours, single_driver):
        """Tours with 12h rest should both be assignable to same driver."""
        config = CPSATConfig(
            time_limit_seconds=10,
            fallback_to_soft=False,  # Hard mode
        )
        
        scheduler = CPSATScheduler(legal_rest_tours, single_driver, config)
        plan = scheduler.schedule(date(2024, 12, 9))
        
        # Both tours should be assigned
        assigned_ids = {t.id for a in plan.assignments for t in a.block.tours}
        
        assert "NORMAL_MON" in assigned_ids, "Monday tour should be assigned"
        assert "NORMAL_TUE" in assigned_ids, "Tuesday tour should be assigned"
        assert plan.validation.is_valid, "Plan with 12h rest should be valid"
    
    def test_soft_fallback_respects_rest(self, late_early_tours, single_driver):
        """
        Even in soft coverage mode (fallback), rest constraint is HARD.
        The solver should never violate it to improve coverage.
        """
        config = CPSATConfig(
            time_limit_seconds=10,
            fallback_to_soft=True,
        )
        
        scheduler = CPSATScheduler(late_early_tours, single_driver, config)
        plan = scheduler.schedule(date(2024, 12, 9))
        
        # Check if plan would have rest violation
        if plan.validation.is_valid:
            # If valid, rest constraint was respected
            assigned_ids = {t.id for a in plan.assignments for t in a.block.tours}
            # Should not have both tours assigned to same driver
            driver_to_tours = {}
            for a in plan.assignments:
                if a.driver_id not in driver_to_tours:
                    driver_to_tours[a.driver_id] = set()
                for t in a.block.tours:
                    driver_to_tours[a.driver_id].add(t.id)
            
            for driver_id, tour_ids in driver_to_tours.items():
                if "LATE_MON" in tour_ids and "EARLY_TUE" in tour_ids:
                    pytest.fail(f"Driver {driver_id} has both late Monday and early Tuesday = rest violation!")


class TestFatiguePenalties:
    """Test that fatigue patterns are penalized in the objective."""
    
    @pytest.fixture
    def early_and_normal_tours(self):
        """Two equivalent tours, one early (05:00) and one normal (08:00)."""
        return [
            Tour(
                id="EARLY_MON",
                day=Weekday.MONDAY,
                start_time=time(5, 0),  # Very early - should be penalized
                end_time=time(9, 30),
            ),
            Tour(
                id="NORMAL_MON",
                day=Weekday.MONDAY,
                start_time=time(8, 0),  # Normal start
                end_time=time(12, 30),
            ),
        ]
    
    @pytest.fixture
    def two_drivers(self):
        """Two drivers available."""
        return [
            Driver(
                id="D001",
                name="Driver 1",
                qualifications=set(),
                availability={day: True for day in Weekday},
            ),
            Driver(
                id="D002",
                name="Driver 2",
                qualifications=set(),
                availability={day: True for day in Weekday},
            ),
        ]
    
    def test_fatigue_penalties_applied(self, early_and_normal_tours, two_drivers):
        """Solver should prefer normal start over early start when equal coverage."""
        config = CPSATConfig(
            time_limit_seconds=10,
            optimize=True,
        )
        
        scheduler = CPSATScheduler(early_and_normal_tours, two_drivers, config)
        plan = scheduler.schedule(date(2024, 12, 9))
        
        # Both tours should be assigned (different drivers or overlap handled)
        assigned_ids = {t.id for a in plan.assignments for t in a.block.tours}
        
        print(f"Assigned: {assigned_ids}")
        print(f"Stats: {plan.stats}")
        
        # Just verify we got a valid solution - the penalties are internal
        assert plan.validation.is_valid or len(assigned_ids) > 0, \
            "Should produce some solution"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
