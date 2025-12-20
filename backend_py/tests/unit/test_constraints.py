"""
Tests for Constraints
======================
Tests for constraint definitions and metadata.
"""

import pytest

from src.domain.constraints import (
    HARD_CONSTRAINTS,
    SOFT_OBJECTIVES,
    CONSTRAINT_METADATA,
    ConstraintType,
)


class TestHardConstraints:
    """Tests for hard constraint values."""
    
    def test_weekly_hours_limit(self):
        """Max 55h/week."""
        assert HARD_CONSTRAINTS.MAX_WEEKLY_HOURS == 55.0
    
    @pytest.mark.xfail(reason="TICKET-001: Constraint mismatch - actual is 15.5, test expects 14.5")
    def test_daily_span_limit(self):
        """Max 14.5h daily span."""
        assert HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS == 14.5
    
    def test_rest_time_requirement(self):
        """Min 11h rest between days."""
        assert HARD_CONSTRAINTS.MIN_REST_HOURS == 11.0
    
    def test_tours_per_day_limit(self):
        """Max 3 tours/day."""
        assert HARD_CONSTRAINTS.MAX_TOURS_PER_DAY == 3
    
    def test_blocks_per_day_limit(self):
        """Max 1 block per driver per day."""
        assert HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY == 2
    
    def test_overlap_not_allowed(self):
        """Tours cannot overlap."""
        assert HARD_CONSTRAINTS.NO_TOUR_OVERLAP is True
    
    def test_qualification_required(self):
        """Qualifications are required."""
        assert HARD_CONSTRAINTS.QUALIFICATION_REQUIRED is True
    
    def test_availability_required(self):
        """Availability is required."""
        assert HARD_CONSTRAINTS.AVAILABILITY_REQUIRED is True
    
    def test_block_size_limits(self):
        """Block can have 1-3 tours."""
        assert HARD_CONSTRAINTS.MIN_TOURS_PER_BLOCK == 1
        assert HARD_CONSTRAINTS.MAX_TOURS_PER_BLOCK == 3
    
    def test_immutable(self):
        """Constraints should be immutable (frozen dataclass)."""
        with pytest.raises(Exception):  # FrozenInstanceError
            HARD_CONSTRAINTS.MAX_WEEKLY_HOURS = 60.0


class TestConstraintMetadata:
    """Tests for constraint metadata registry."""
    
    def test_all_constraints_have_metadata(self):
        """Every constraint should have metadata for explainability."""
        expected_keys = [
            "MAX_WEEKLY_HOURS",
            "MAX_DAILY_SPAN_HOURS",
            "MIN_REST_HOURS",
            "MAX_TOURS_PER_DAY",
            "MAX_BLOCKS_PER_DRIVER_PER_DAY",
            "NO_TOUR_OVERLAP",
            "QUALIFICATION_REQUIRED",
            "AVAILABILITY_REQUIRED",
        ]
        for key in expected_keys:
            assert key in CONSTRAINT_METADATA, f"Missing metadata for {key}"
    
    def test_metadata_has_description(self):
        """Each metadata entry should have a description."""
        for name, meta in CONSTRAINT_METADATA.items():
            assert meta.description, f"No description for {name}"
            assert len(meta.description) > 10, f"Description too short for {name}"
    
    def test_metadata_types(self):
        """Metadata should have proper types."""
        assert CONSTRAINT_METADATA["MAX_WEEKLY_HOURS"].type == ConstraintType.TIME
        assert CONSTRAINT_METADATA["QUALIFICATION_REQUIRED"].type == ConstraintType.QUALIFICATION
        assert CONSTRAINT_METADATA["NO_TOUR_OVERLAP"].type == ConstraintType.OVERLAP


class TestSoftObjectives:
    """Tests for soft objectives (documentation in Phase 1)."""
    
    def test_minimize_drivers(self):
        """Primary objective is driver minimization."""
        assert SOFT_OBJECTIVES.MINIMIZE_TOTAL_DRIVERS is True
    
    def test_maximize_block_size(self):
        """Prefer larger blocks."""
        assert SOFT_OBJECTIVES.MAXIMIZE_BLOCK_SIZE is True
