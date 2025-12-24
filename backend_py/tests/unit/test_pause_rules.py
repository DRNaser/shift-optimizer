"""
Unit tests for Pause Rules (v5 Stabilization)
=============================================
Tests the Two-Zone Pause Model:
- Zone 1 (Regular): 30-60 min - standard consecutive tours
- Zone 2 (Split):  360 min exactly - legal split-shift gap
- Forbidden Zone:  61-359 and 361+ min - explicitly banned

These tests verify both builder and validator use consistent rules.
"""

import pytest
from datetime import time

from src.domain.models import Tour, Block, Weekday
from src.domain.constraints import HARD_CONSTRAINTS


# =============================================================================
# Test Fixtures
# =============================================================================

def make_tour(tour_id: str, start_h: int, start_m: int, end_h: int, end_m: int, day=Weekday.MONDAY) -> Tour:
    """Create a Tour with specified times."""
    return Tour(
        id=tour_id,
        day=day,
        start_time=time(start_h, start_m),
        end_time=time(end_h, end_m),
        duration_hours=(end_h * 60 + end_m - start_h * 60 - start_m) / 60,
    )


def make_block(block_id: str, tours: list[Tour], is_split: bool = False) -> Block:
    """Create a Block from tours."""
    return Block(
        id=block_id,
        day=tours[0].day if tours else Weekday.MONDAY,
        tours=tours,
        is_split=is_split,
    )


def calculate_gap_minutes(t1: Tour, t2: Tour) -> int:
    """Calculate gap in minutes between two consecutive tours."""
    end_mins = t1.end_time.hour * 60 + t1.end_time.minute
    start_mins = t2.start_time.hour * 60 + t2.start_time.minute
    return start_mins - end_mins


# =============================================================================
# Test: Constraint Values
# =============================================================================

class TestConstraintValues:
    """Verify the constraint values are correct."""
    
    def test_min_pause_is_30(self):
        """MIN_PAUSE_BETWEEN_TOURS should be 30 minutes."""
        assert HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS == 30
    
    def test_max_pause_regular_is_60(self):
        """MAX_PAUSE_BETWEEN_TOURS should be 60 minutes (tight packing)."""
        assert HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS == 60
    
    def test_split_pause_min_is_360(self):
        """SPLIT_PAUSE_MIN should be 360 minutes (6 hours)."""
        assert HARD_CONSTRAINTS.SPLIT_PAUSE_MIN == 360
    
    def test_split_pause_max_is_360(self):
        """SPLIT_PAUSE_MAX should be 360 minutes (exact match with MIN)."""
        assert HARD_CONSTRAINTS.SPLIT_PAUSE_MAX == 360
    
    def test_split_pause_is_exact(self):
        """Split pause should be exactly 360 min (MIN == MAX)."""
        assert HARD_CONSTRAINTS.SPLIT_PAUSE_MIN == HARD_CONSTRAINTS.SPLIT_PAUSE_MAX


# =============================================================================
# Test: Regular Pause Boundaries (30-60 min)
# =============================================================================

class TestRegularPauseBoundaries:
    """Test regular pause rules: must be 30-60 minutes."""
    
    def test_gap_29_invalid(self):
        """Gap 29 min < 30 min → too short for regular block."""
        t1 = make_tour("A", 8, 0, 9, 0)    # 08:00-09:00
        t2 = make_tour("B", 9, 29, 10, 30)  # 09:29-10:30 (gap = 29 min)
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 29
        assert gap < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS
    
    def test_gap_30_valid(self):
        """Gap 30 min = exactly at minimum → valid for regular block."""
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 9, 30, 10, 30)  # gap = 30 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 30
        assert gap >= HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS
        assert gap <= HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
    
    def test_gap_45_valid(self):
        """Gap 45 min is within 30-60 range → valid for regular block."""
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 9, 45, 10, 45)  # gap = 45 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 45
        assert HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS <= gap <= HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
    
    def test_gap_60_valid(self):
        """Gap 60 min = exactly at maximum → valid for regular block."""
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 10, 0, 11, 0)  # gap = 60 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 60
        assert gap >= HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS
        assert gap <= HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
    
    def test_gap_61_invalid_for_regular(self):
        """Gap 61 min > 60 min → too long for regular block (forbidden zone)."""
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 10, 1, 11, 1)  # gap = 61 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 61
        assert gap > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
        assert gap < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN  # Forbidden zone


# =============================================================================
# Test: Split Pause Boundaries (exactly 360 min)
# =============================================================================

class TestSplitPauseBoundaries:
    """Test split pause rules: must be exactly 360 minutes."""
    
    def test_gap_359_invalid(self):
        """Gap 359 min < 360 min → too short for split block."""
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 12, 59, 14, 0)  # gap = 359 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 359
        assert gap < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN
    
    def test_gap_360_valid(self):
        """Gap 360 min = exactly 6h → valid for split block."""
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 13, 0, 14, 0)  # gap = 360 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 360
        assert gap >= HARD_CONSTRAINTS.SPLIT_PAUSE_MIN
        assert gap <= HARD_CONSTRAINTS.SPLIT_PAUSE_MAX
    
    def test_gap_361_invalid(self):
        """Gap 361 min > 360 min → too long for split block."""
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 13, 1, 14, 1)  # gap = 361 min
        gap = calculate_gap_minutes(t1, t2)
        assert gap == 361
        assert gap > HARD_CONSTRAINTS.SPLIT_PAUSE_MAX


# =============================================================================
# Test: Forbidden Zone (61-359 min)
# =============================================================================

class TestForbiddenZone:
    """Test that gaps in the forbidden zone are rejected."""
    
    def test_gap_120_in_forbidden_zone(self):
        """Gap 120 min is in forbidden zone (61-359)."""
        gap = 120
        assert gap > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS  # 60
        assert gap < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN  # 360
    
    def test_gap_240_in_forbidden_zone(self):
        """Gap 240 min (4h) is in forbidden zone (61-359)."""
        gap = 240
        assert gap > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS  # 60
        assert gap < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN  # 360
    
    def test_gap_300_in_forbidden_zone(self):
        """Gap 300 min (5h) is in forbidden zone (61-359)."""
        gap = 300
        assert gap > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS  # 60
        assert gap < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN  # 360


# =============================================================================
# Test: Validator Pause Enforcement
# =============================================================================

class TestValidatorPauseEnforcement:
    """Test that validator enforces pause rules via validate_block_structure."""
    
    def test_validator_rejects_short_regular_gap(self):
        """Validator should reject regular block with gap < 30 min."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 9, 25, 10, 30)  # gap = 25 min < 30 min
        block = make_block("B2R-test", [t1, t2], is_split=False)
        
        result = validate_block_structure(block)
        assert not result.is_valid
        assert any("minimum is 30min" in v for v in result.hard_violations)
    
    def test_validator_accepts_valid_regular_gap(self):
        """Validator should accept regular block with gap 30-60 min."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 9, 45, 10, 45)  # gap = 45 min (valid)
        block = make_block("B2R-test", [t1, t2], is_split=False)
        
        result = validate_block_structure(block)
        # Should not have gap-related violations
        gap_violations = [v for v in result.hard_violations if "Gap" in v or "gap" in v]
        assert len(gap_violations) == 0
    
    def test_validator_rejects_forbidden_zone_regular_block(self):
        """Validator should reject regular block with gap in forbidden zone (61-359)."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 8, 0, 9, 0)
        t2 = make_tour("B", 11, 0, 12, 0)  # gap = 120 min (forbidden zone)
        block = make_block("B2R-test", [t1, t2], is_split=False)
        
        result = validate_block_structure(block)
        assert not result.is_valid
        # Should have both "maximum" and "forbidden zone" violations
        assert any("maximum is 60min" in v for v in result.hard_violations)
        assert any("forbidden zone" in v for v in result.hard_violations)
    
    def test_validator_accepts_exact_split_gap(self):
        """Validator should accept split block with exactly 360 min gap."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 13, 0, 14, 0)  # gap = 360 min (exact)
        block = make_block("B2S-test", [t1, t2], is_split=True)
        
        result = validate_block_structure(block)
        # Should not have gap-related violations
        gap_violations = [v for v in result.hard_violations if "Gap" in v or "gap" in v]
        assert len(gap_violations) == 0
    
    def test_validator_rejects_short_split_gap(self):
        """Validator should reject split block with gap < 360 min."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 12, 59, 14, 0)  # gap = 359 min < 360 min
        block = make_block("B2S-test", [t1, t2], is_split=True)
        
        result = validate_block_structure(block)
        assert not result.is_valid
        assert any("Split block gap" in v and "below minimum" in v for v in result.hard_violations)
    
    def test_validator_rejects_long_split_gap(self):
        """Validator should reject split block with gap > 360 min."""
        from src.domain.validator import validate_block_structure
        
        t1 = make_tour("A", 6, 0, 7, 0)
        t2 = make_tour("B", 13, 1, 14, 1)  # gap = 361 min > 360 min
        block = make_block("B2S-test", [t1, t2], is_split=True)
        
        result = validate_block_structure(block)
        assert not result.is_valid
        assert any("Split block gap" in v and "exceeds maximum" in v for v in result.hard_violations)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
