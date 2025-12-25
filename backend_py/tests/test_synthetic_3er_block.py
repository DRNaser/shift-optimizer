"""
Synthetic Minimal Test: Verify 3er Block Generation and Usage
==============================================================

This test creates 3 tours that are GUARANTEED to be combinable:
- Tour A: 04:45-09:15 (4.5 hours)
- Tour B: 09:45-14:15 (4.5 hours, gap 30 min = MIN_PAUSE)
- Tour C: 14:45-19:15 (4.5 hours, gap 30 min = MIN_PAUSE)

Expected Behavior:
1. BlockBuilder MUST create exactly 1 3er block (A+B+C)
2. BlockBuilder may also create 2er blocks (A+B, B+C) and 1er blocks
3. CP-SAT MUST use the 3er block when 1 driver is available

If this test fails:
- Problem is in Block-Builder rules or time parsing
- NOT in real-world data complexity
"""

import pytest
from datetime import date, time

from src.domain.models import Tour, Driver, Weekday
from src.services.block_builder import BlockBuilder
from src.services.cpsat_solver import create_cpsat_schedule, CPSATConfig


class TestSynthetic3erBlock:
    """Minimal reproducible test for 3er block generation."""

    @pytest.fixture
    def synthetic_tours(self):
        """Create 3 tours designed to form perfect 3er block."""
        return [
            Tour(
                id="SYNTH-A",
                day=Weekday.MONDAY,
                start_time=time(4, 45),
                end_time=time(9, 15),
            ),
            Tour(
                id="SYNTH-B",
                day=Weekday.MONDAY,
                start_time=time(9, 45),  # 30 min gap after A
                end_time=time(14, 15),
            ),
            Tour(
                id="SYNTH-C",
                day=Weekday.MONDAY,
                start_time=time(14, 45),  # 30 min gap after B
                end_time=time(19, 15),
            ),
        ]

    @pytest.fixture
    def single_driver(self):
        """Create one driver with standard constraints."""
        return [
            Driver(
                id="SYNTH-D1",
                name="Test Driver 1",
            )
        ]

    def test_block_builder_creates_3er_candidate(self, synthetic_tours):
        """CRITICAL: Block builder must generate at least one 3er block."""
        builder = BlockBuilder(synthetic_tours)
        all_blocks = builder.all_possible_blocks

        # Count blocks by type
        blocks_1er = [b for b in all_blocks if len(b.tours) == 1]
        blocks_2er = [b for b in all_blocks if len(b.tours) == 2]
        blocks_3er = [b for b in all_blocks if len(b.tours) == 3]

        print(f"\n=== BLOCK BUILDER RESULTS ===")
        print(f"1er blocks: {len(blocks_1er)}")
        print(f"2er blocks: {len(blocks_2er)}")
        print(f"3er blocks: {len(blocks_3er)}")

        # Expected: 3 single blocks, 2 double blocks, 1 triple block
        assert len(blocks_1er) == 3, "Should create 3 single-tour blocks"
        assert len(blocks_2er) == 2, "Should create 2 two-tour blocks (A+B, B+C)"
        assert len(blocks_3er) == 1, "MUST create 1 three-tour block (A+B+C)"

        # Verify the 3er contains all three tours
        triple_block = blocks_3er[0]
        tour_ids = {t.id for t in triple_block.tours}
        assert tour_ids == {"SYNTH-A", "SYNTH-B", "SYNTH-C"}, \
            "3er block must contain all three tours"

    def test_solver_uses_3er_block(self, synthetic_tours, single_driver):
        """CRITICAL: CP-SAT must prefer the 3er block over separate blocks."""
        config = CPSATConfig(
            time_limit_seconds=10,
            optimize=True,
            prefer_larger_blocks=True,
        )

        plan = create_cpsat_schedule(
            tours=synthetic_tours,
            drivers=single_driver,
            week_start=date(2024, 12, 9),  # Monday
            config=config,
        )

        print(f"\n=== SOLVER RESULTS ===")
        print(f"Valid: {plan.validation.is_valid}")
        print(f"Tours assigned: {plan.stats.total_tours_assigned}/3")
        print(f"Block counts: {plan.stats.block_counts}")

        # Must be valid
        assert plan.validation.is_valid, "Solution must be valid"

        # Must assign all 3 tours
        assert plan.stats.total_tours_assigned == 3, \
            "All 3 tours must be assigned"

        # Must use exactly 1 block (the 3er)
        total_blocks = sum(plan.stats.block_counts.values())
        assert total_blocks == 1, "Should use exactly 1 block"

        # That block must be a 3er
        assert plan.stats.block_counts.get("3er", 0) == 1, \
            "Must use the 3er block, not multiple smaller blocks"

    def test_greedy_also_prefers_3er(self, synthetic_tours):
        """Greedy algorithm should also prefer the 3er block."""
        builder = BlockBuilder(synthetic_tours)
        greedy_blocks = builder.greedy_blocks

        print(f"\n=== GREEDY RESULTS ===")
        print(f"Total blocks: {len(greedy_blocks)}")
        print(f"Block types: ", end="")
        for block in greedy_blocks:
            print(f"{len(block.tours)}er ", end="")
        print()

        # Greedy should also pick the 3er
        assert len(greedy_blocks) == 1, "Greedy should use 1 block"
        assert len(greedy_blocks[0].tours) == 3, \
            "Greedy should prefer the 3er block"


class TestSynthetic3erWithMultipleDrivers:
    """Test 3er block with multiple drivers available."""

    @pytest.fixture
    def synthetic_tours(self):
        """Same 3 tours as above."""
        return [
            Tour(id="SYNTH-A", day=Weekday.MONDAY, 
                 start_time=time(4, 45), end_time=time(9, 15)),
            Tour(id="SYNTH-B", day=Weekday.MONDAY,
                 start_time=time(9, 45), end_time=time(14, 15)),
            Tour(id="SYNTH-C", day=Weekday.MONDAY,
                 start_time=time(14, 45), end_time=time(19, 15)),
        ]

    @pytest.fixture
    def three_drivers(self):
        """Create 3 drivers."""
        return [
            Driver(id=f"SYNTH-D{i}", name=f"Test Driver {i}")
            for i in range(1, 4)
        ]

    def test_solver_still_prefers_3er_with_multiple_drivers(
        self, synthetic_tours, three_drivers
    ):
        """
        Even with 3 drivers available, solver should prefer:
        - 1 driver with 3er block (ideal)
        
        Over:
        - 3 drivers with 1er blocks each (wastes drivers)
        - 2 drivers with 2er + 1er (suboptimal)
        """
        config = CPSATConfig(
            time_limit_seconds=10,
            optimize=True,
            prefer_larger_blocks=True,
        )

        plan = create_cpsat_schedule(
            tours=synthetic_tours,
            drivers=three_drivers,
            week_start=date(2024, 12, 9),
            config=config,
        )

        print(f"\n=== SOLVER WITH 3 DRIVERS ===")
        print(f"Drivers used: {plan.stats.total_drivers}")
        print(f"Block counts: {plan.stats.block_counts}")

        assert plan.validation.is_valid, "Solution must be valid"
        assert plan.stats.total_tours_assigned == 3, "All tours assigned"

        # Should use only 1 driver (minimize drivers)
        assert plan.stats.total_drivers == 1, \
            "Should use only 1 driver (not waste 2 or 3 drivers)"

        # Should use the 3er block
        assert plan.stats.block_counts.get("3er", 0) == 1, \
            "Should use 3er block (not split into smaller blocks)"


class TestSyntheticEdgeCases:
    """Test edge cases with slightly different gaps."""

    def test_max_gap_3er_block(self):
        """Test 3er with MAX_PAUSE gap."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from datetime import datetime, timedelta
        max_pause = HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
        def add_minutes(base: time, minutes: int) -> time:
            return (datetime.combine(date.today(), base) + timedelta(minutes=minutes)).time()
        tours = [
            Tour(id="EDGE-A", day=Weekday.MONDAY,
                 start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="EDGE-B", day=Weekday.MONDAY,
                 start_time=add_minutes(time(10, 0), max_pause),
                 end_time=add_minutes(time(14, 0), max_pause)),  # MAX gap
            Tour(id="EDGE-C", day=Weekday.MONDAY,
                 start_time=add_minutes(time(14, 0), 2 * max_pause),
                 end_time=add_minutes(time(18, 0), 2 * max_pause)),  # MAX gap
        ]

        builder = BlockBuilder(tours)
        blocks_3er = [b for b in builder.all_possible_blocks if len(b.tours) == 3]

        print(f"\n=== MAX GAP TEST ===")
        print(f"3er blocks with max gaps: {len(blocks_3er)}")

        assert len(blocks_3er) == 1, \
            "Should create 3er block even with max gap"

    def test_gap_too_large_prevents_3er(self):
        """Test that gap > MAX_PAUSE prevents 3er block."""
        from src.domain.constraints import HARD_CONSTRAINTS
        from datetime import datetime, timedelta
        max_pause = HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
        def add_minutes(base: time, minutes: int) -> time:
            return (datetime.combine(date.today(), base) + timedelta(minutes=minutes)).time()
        tours = [
            Tour(id="TOOLARGE-A", day=Weekday.MONDAY,
                 start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="TOOLARGE-B", day=Weekday.MONDAY,
                 start_time=add_minutes(time(10, 0), max_pause + 5),
                 end_time=add_minutes(time(14, 0), max_pause + 5)),  # too large
            Tour(id="TOOLARGE-C", day=Weekday.MONDAY,
                 start_time=add_minutes(time(14, 0), 2 * max_pause + 10),
                 end_time=add_minutes(time(18, 0), 2 * max_pause + 10)),
        ]

        builder = BlockBuilder(tours)
        blocks_3er = [b for b in builder.all_possible_blocks if len(b.tours) == 3]

        print(f"\n=== GAP TOO LARGE TEST ===")
        print(f"3er blocks with too-large gap: {len(blocks_3er)}")

        assert len(blocks_3er) == 0, \
            "Should NOT create 3er block when gap > MAX_PAUSE"
