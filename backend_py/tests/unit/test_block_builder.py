"""
Tests for Block Builder
========================
Tests for tour-to-block transformation.
"""

import pytest
from datetime import time

from src.domain.models import Tour, Block, Weekday, BlockType
from src.services.block_builder import (
    BlockBuilder,
    tours_can_combine,
    build_all_possible_blocks,
    build_blocks_greedy,
)


# =============================================================================
# TOUR COMBINATION TESTS
# =============================================================================

class TestTourCombination:
    """Tests for tours_can_combine function."""
    
    def test_valid_combination(self):
        """Tours with valid gap can combine."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 30))
        
        assert tours_can_combine(t1, t2) is True
    
    def test_different_days_cannot_combine(self):
        """Tours on different days cannot combine."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        t2 = Tour(id="T2", day=Weekday.TUESDAY, start_time=time(12, 30), end_time=time(16, 30))
        
        assert tours_can_combine(t1, t2) is False
    
    def test_overlapping_cannot_combine(self):
        """Overlapping tours cannot combine."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(11, 0), end_time=time(15, 0))
        
        assert tours_can_combine(t1, t2) is False
    
    def test_gap_too_large(self):
        """Tours with gap > 2 hours cannot combine."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(14, 0), end_time=time(18, 0))  # 4h gap
        
        assert tours_can_combine(t1, t2) is False
    
    def test_adjacent_tours(self):
        """Tours with minimum required gap (30 min) can combine."""
        # Note: MIN_PAUSE_BETWEEN_TOURS = 30 minutes required between tours
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 30))  # 30 min gap
        
        assert tours_can_combine(t1, t2) is True
    
    def test_gap_too_small(self):
        """Tours with gap < 30 min cannot combine (MIN_PAUSE_BETWEEN_TOURS)."""
        t1 = Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        t2 = Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 0), end_time=time(16, 0))  # 0 min gap
        
        assert tours_can_combine(t1, t2) is False


# =============================================================================
# BLOCK GENERATION TESTS
# =============================================================================

class TestBlockGeneration:
    """Tests for block generation functions."""
    
    def test_single_tour_generates_single_block(self):
        """One tour generates one 1er block."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        
        blocks = build_all_possible_blocks(tours)
        
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.SINGLE
    
    def test_two_combinable_tours_generates_three_blocks(self):
        """Two combinable tours generate: 2 singles + 1 double = 3 blocks."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(12, 30), end_time=time(16, 30)),
        ]
        
        blocks = build_all_possible_blocks(tours)
        
        # 2 singles + 1 double
        singles = [b for b in blocks if b.block_type == BlockType.SINGLE]
        doubles = [b for b in blocks if b.block_type == BlockType.DOUBLE]
        
        assert len(singles) == 2
        assert len(doubles) == 1
    
    def test_three_combinable_tours(self):
        """Three combinable tours generate all block types."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
        ]
        
        blocks = build_all_possible_blocks(tours)
        
        singles = [b for b in blocks if b.block_type == BlockType.SINGLE]
        doubles = [b for b in blocks if b.block_type == BlockType.DOUBLE]
        triples = [b for b in blocks if b.block_type == BlockType.TRIPLE]
        
        assert len(singles) == 3
        assert len(doubles) == 2  # T1+T2, T2+T3
        assert len(triples) == 1  # T1+T2+T3


# =============================================================================
# GREEDY BLOCK BUILDING TESTS
# =============================================================================

class TestGreedyBlockBuilding:
    """Tests for greedy block building."""
    
    def test_prefers_larger_blocks(self):
        """Greedy should prefer 3er > 2er > 1er."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
        ]
        
        blocks = build_blocks_greedy(tours, prefer_larger=True)
        
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.TRIPLE
    
    def test_each_tour_used_once(self):
        """Each tour should appear in exactly one block."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
            Tour(id="T4", day=Weekday.MONDAY, start_time=time(20, 0), end_time=time(23, 0)),
        ]
        
        blocks = build_blocks_greedy(tours)
        
        used_tour_ids = []
        for block in blocks:
            for tour in block.tours:
                used_tour_ids.append(tour.id)
        
        assert len(used_tour_ids) == len(tours)
        assert len(set(used_tour_ids)) == len(tours)  # No duplicates
    
    def test_handles_non_combinable_tours(self):
        """Non-combinable tours become singles."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),  # 5h gap
        ]
        
        blocks = build_blocks_greedy(tours)
        
        assert len(blocks) == 2
        assert all(b.block_type == BlockType.SINGLE for b in blocks)


# =============================================================================
# BLOCK BUILDER CLASS TESTS
# =============================================================================

class TestBlockBuilder:
    """Tests for BlockBuilder class."""
    
    def test_caches_results(self):
        """Results should be cached."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        ]
        
        builder = BlockBuilder(tours)
        
        blocks1 = builder.all_possible_blocks
        blocks2 = builder.all_possible_blocks
        
        assert blocks1 is blocks2  # Same object (cached)
    
    def test_get_stats(self):
        """Stats should be accurate."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(10, 0)),
            Tour(id="T2", day=Weekday.MONDAY, start_time=time(10, 30), end_time=time(14, 30)),
            Tour(id="T3", day=Weekday.MONDAY, start_time=time(15, 0), end_time=time(19, 0)),
        ]
        
        builder = BlockBuilder(tours)
        stats = builder.get_stats()
        
        assert stats["total_tours"] == 3
        assert stats["blocks_by_type"]["3er"] == 1
    
    def test_get_blocks_by_day(self):
        """Filter blocks by day."""
        tours = [
            Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
            Tour(id="T2", day=Weekday.TUESDAY, start_time=time(8, 0), end_time=time(12, 0)),
        ]
        
        builder = BlockBuilder(tours)
        
        monday_blocks = builder.get_blocks_by_day(Weekday.MONDAY)
        tuesday_blocks = builder.get_blocks_by_day(Weekday.TUESDAY)
        
        assert len(monday_blocks) == 1
        assert len(tuesday_blocks) == 1
        assert monday_blocks[0].day == Weekday.MONDAY
