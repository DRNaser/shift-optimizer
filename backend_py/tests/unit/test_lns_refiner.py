"""
Tests for LNS Refiner
======================
Tests for Large Neighborhood Search refinement.
"""

import pytest
from datetime import date, time

from src.domain.models import (
    Tour,
    Driver,
    Weekday,
    BlockType,
)
from src.services.cpsat_solver import create_cpsat_schedule, CPSATConfig
from src.services.lns_refiner import (
    LNSRefiner,
    LNSConfig,
    DestroyStrategy,
    destroy_random,
    destroy_by_day,
    destroy_by_driver,
    destroy_worst,
    refine_schedule,
    calculate_objective,
)
import random


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
        Tour(id="T6", day=Weekday.WEDNESDAY, start_time=time(7, 0), end_time=time(11, 0)),
    ]


@pytest.fixture
def sample_drivers() -> list[Driver]:
    """Create sample drivers for testing."""
    return [
        Driver(id="D1", name="Driver One"),
        Driver(id="D2", name="Driver Two"),
    ]


@pytest.fixture
def initial_plan(sample_tours: list[Tour], sample_drivers: list[Driver]):
    """Create initial plan using CP-SAT."""
    config = CPSATConfig(time_limit_seconds=5.0, seed=42)
    return create_cpsat_schedule(sample_tours, sample_drivers, date(2024, 1, 1), config)


# =============================================================================
# DESTROY OPERATOR TESTS
# =============================================================================

class TestDestroyOperators:
    """Tests for destroy operators."""
    
    def test_destroy_random(self, initial_plan):
        """Random destroy should remove some blocks."""
        rng = random.Random(42)
        result = destroy_random(initial_plan.assignments, 0.5, rng)
        
        assert len(result.kept_assignments) < len(initial_plan.assignments)
        assert len(result.destroyed_blocks) > 0
        assert len(result.freed_tours) > 0
    
    def test_destroy_random_respects_locks(self, initial_plan):
        """Random destroy should respect locked blocks."""
        if not initial_plan.assignments:
            pytest.skip("No assignments to test")
        
        locked = {initial_plan.assignments[0].block.id}
        rng = random.Random(42)
        result = destroy_random(initial_plan.assignments, 0.9, rng, locked)
        
        # Locked block should be in kept
        kept_ids = {a.block.id for a in result.kept_assignments}
        assert locked.issubset(kept_ids)
    
    def test_destroy_by_day(self, initial_plan):
        """Day destroy should remove all blocks on a day."""
        rng = random.Random(42)
        result = destroy_by_day(initial_plan.assignments, rng)
        
        if result.destroyed_blocks:
            # All destroyed should be same day
            destroyed_days = {b.day for b in result.destroyed_blocks}
            assert len(destroyed_days) == 1
    
    def test_destroy_by_driver(self, initial_plan):
        """Driver destroy should remove all blocks for a driver."""
        rng = random.Random(42)
        result = destroy_by_driver(initial_plan.assignments, rng)
        
        if result.destroyed_blocks:
            # All destroyed should be same driver
            destroyed_drivers = {b.driver_id for b in result.destroyed_blocks}
            assert len(destroyed_drivers) == 1
    
    def test_destroy_worst(self, initial_plan):
        """Worst destroy should remove smallest blocks first."""
        result = destroy_worst(initial_plan.assignments, 0.3)
        
        if result.destroyed_blocks:
            # Destroyed blocks should be among the smallest
            destroyed_sizes = [len(b.tours) for b in result.destroyed_blocks]
            kept_sizes = [len(a.block.tours) for a in result.kept_assignments]
            
            # Average destroyed size should be <= average kept size
            if kept_sizes:
                avg_destroyed = sum(destroyed_sizes) / len(destroyed_sizes)
                avg_kept = sum(kept_sizes) / len(kept_sizes)
                assert avg_destroyed <= avg_kept + 0.5  # Small tolerance


# =============================================================================
# LNS REFINER TESTS
# =============================================================================

class TestLNSRefiner:
    """Tests for LNS refiner."""
    
    def test_refiner_maintains_validity(
        self,
        initial_plan,
        sample_tours: list[Tour],
        sample_drivers: list[Driver]
    ):
        """Refined plan should be valid."""
        config = LNSConfig(max_iterations=3, seed=42)
        refined = refine_schedule(initial_plan, sample_tours, sample_drivers, config)
        
        # Should still be valid
        assert refined.validation.is_valid is True
    
    def test_refiner_does_not_decrease_objective(
        self,
        initial_plan,
        sample_tours: list[Tour],
        sample_drivers: list[Driver]
    ):
        """LNS should not accept worse solutions."""
        config = LNSConfig(max_iterations=5, seed=42, accept_equal=False)
        
        initial_obj = calculate_objective(initial_plan)
        refined = refine_schedule(initial_plan, sample_tours, sample_drivers, config)
        refined_obj = calculate_objective(refined)
        
        assert refined_obj >= initial_obj
    
    def test_refiner_with_different_strategies(
        self,
        initial_plan,
        sample_tours: list[Tour],
        sample_drivers: list[Driver]
    ):
        """Test all destroy strategies."""
        for strategy in DestroyStrategy:
            config = LNSConfig(
                max_iterations=2,
                destroy_strategy=strategy,
                seed=42
            )
            refined = refine_schedule(initial_plan, sample_tours, sample_drivers, config)
            
            assert refined is not None
            assert refined.validation.is_valid is True
    
    def test_refiner_respects_locks(
        self,
        initial_plan,
        sample_tours: list[Tour],
        sample_drivers: list[Driver]
    ):
        """Locked blocks should remain unchanged."""
        if not initial_plan.assignments:
            pytest.skip("No assignments to test")
        
        locked = {initial_plan.assignments[0].block.id}
        config = LNSConfig(max_iterations=5, seed=42)
        
        refined = refine_schedule(
            initial_plan,
            sample_tours,
            sample_drivers,
            config,
            locked_blocks=locked
        )
        
        # Locked block should still be assigned
        refined_block_ids = {a.block.id for a in refined.assignments}
        assert locked.issubset(refined_block_ids)
    
    def test_refiner_history_tracked(
        self,
        initial_plan,
        sample_tours: list[Tour],
        sample_drivers: list[Driver]
    ):
        """Refiner should track iteration history."""
        config = LNSConfig(max_iterations=3, seed=42)
        refiner = LNSRefiner(initial_plan, sample_tours, sample_drivers, config)
        refiner.refine()
        
        assert len(refiner.history) > 0


# =============================================================================
# OBJECTIVE CALCULATION TESTS
# =============================================================================

class TestObjectiveCalculation:
    """Tests for objective calculation."""
    
    def test_objective_increases_with_more_tours(self, sample_drivers):
        """More assigned tours should increase objective."""
        # Create two plans with different tour counts
        tours1 = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        tours2 = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 30)),
        ]
        
        config = CPSATConfig(time_limit_seconds=5.0)
        plan1 = create_cpsat_schedule(tours1, sample_drivers, date(2024, 1, 1), config)
        plan2 = create_cpsat_schedule(tours2, sample_drivers, date(2024, 1, 1), config)
        
        obj1 = calculate_objective(plan1)
        obj2 = calculate_objective(plan2)
        
        assert obj2 > obj1
