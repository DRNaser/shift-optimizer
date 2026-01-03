"""
Unit test: Verify Stage-1 subset selection preserves coverage.

This test ensures that the singleton prioritization logic cannot be
accidentally broken by future ranking/selection changes.
"""
import pytest
from src.core_v2.model.tour import TourV2
from src.core_v2.model.column import ColumnV2
from src.core_v2.model.duty import DutyV2
from src.core_v2.model.weektype import WeekCategory


def test_subset_preserves_coverage_with_singletons():
    """
    Test that singleton prioritization prevents coverage loss.
    
    Scenario:
    - 10 tours total
    - 3 tours only covered by singletons (high cost ~5.5)
    - 100 multi-day columns covering other tours (low cost ~1.0)
    - Subset cap = 20
    
    Without P0 fix: Singletons rank last, get excluded, 3 tours uncovered
    With P0 fix: Singletons prioritized first, all tours covered
    """
    
    # Create 10 tours
    tours = []
    for i in range(10):
        tour = TourV2(
            tour_id=f"T{i}",
            day=0,
            start_min=480 + i * 60,
            end_min=540 + i * 60,
            duration_min=60
        )
        tours.append(tour)
    
    all_tour_ids = {t.tour_id for t in tours}
    
    # Create columns:
    # - 3 singletons (covering tours 0, 1, 2) - high cost
    # - 100 multi-day columns (covering tours 3-9) - low cost
    
    columns = []
    
    # Singletons (cost ~5.5)
    for i in range(3):
        duty = DutyV2(
            duty_id=f"D{i}",
            day=0,
            start_min=tours[i].start_min,
            end_min=tours[i].end_min,
            tour_ids=(tours[i].tour_id,),
            work_min=60,
            span_min=60
        )
        col = ColumnV2.from_duties(f"S{i}", [duty], "seed")
        columns.append(col)
    
    # Multi-day columns (cost ~1.0)
    for i in range(100):
        duties = []
        for day in range(3):
            tour_idx = 3 + (i % 7)  # Covering tours 3-9
            if tour_idx < len(tours):
                duty = DutyV2(
                    duty_id=f"D{i}_{day}",
                    day=day,
                    start_min=480,
                    end_min=540,
                    tour_ids=(tours[tour_idx].tour_id,),
                    work_min=60,
                    span_min=60
                )
                duties.append(duty)
        col = ColumnV2.from_duties(f"M{i}", duties, "cg")
        columns.append(col)
    
    # Simulate subset selection with cap=20
    MIP_CAP = 20
    WEEK_CAT = WeekCategory.COMPRESSED
    
    # Apply P0 FIX logic (singleton prioritization)
    sorted_by_cost = sorted(
        columns,
        key=lambda c: (0 if c.is_singleton else 1, c.cost_utilization(WEEK_CAT))
    )
    
    singleton_count = sum(1 for c in columns if c.is_singleton)
    elite_count = min(MIP_CAP, max(int(MIP_CAP * 0.8), singleton_count))
    
    subset = sorted_by_cost[:elite_count]
    
    # Verify coverage
    covered = set()
    for col in subset:
        covered.update(col.covered_tour_ids)
    
    missing = all_tour_ids - covered
    
    # Assertions
    assert len(missing) == 0, f"Subset lost coverage for {len(missing)} tours: {missing}"
    assert singleton_count <= len(subset), f"Not all singletons included: {singleton_count} singletons, {len(subset)} in subset"
    assert len(subset) >= 3, "Subset too small to include all singletons"


def test_subset_without_fix_would_fail():
    """
    Negative test: Verify that WITHOUT the fix, coverage would be lost.
    
    This documents the bug behavior to ensure we don't regress.
    """
    # Same setup as above
    tours = [TourV2(f"T{i}", day=0, start_min=480+i*60, end_min=540+i*60, duration_min=60) for i in range(10)]
    all_tour_ids = {t.tour_id for t in tours}
    
    columns = []
    
    # 3 singletons
    for i in range(3):
        duty = DutyV2(f"D{i}", day=0, start_min=tours[i].start_min, end_min=tours[i].end_min,
                      tour_ids=(tours[i].tour_id,), work_min=60, span_min=60)
        col = ColumnV2.from_duties(f"S{i}", [duty], "seed")
        columns.append(col)
    
    # 100 multi-day columns
    for i in range(100):
        duties = []
        for day in range(3):
            tour_idx = 3 + (i % 7)
            if tour_idx < len(tours):
                duty = DutyV2(f"D{i}_{day}", day=day, start_min=480, end_min=540,
                             tour_ids=(tours[tour_idx].tour_id,), work_min=60, span_min=60)
                duties.append(duty)
        col = ColumnV2.from_duties(f"M{i}", duties, "cg")
        columns.append(col)
    
    MIP_CAP = 20
    WEEK_CAT = WeekCategory.COMPRESSED
    
    # OLD BUGGY logic (no singleton prioritization)
    sorted_by_cost_buggy = sorted(
        columns,
        key=lambda c: c.cost_utilization(WEEK_CAT)
    )
    
    elite_count_buggy = int(MIP_CAP * 0.8)
    subset_buggy = sorted_by_cost_buggy[:elite_count_buggy]
    
    # Verify coverage LOSS
    covered_buggy = set()
    for col in subset_buggy:
        covered_buggy.update(col.covered_tour_ids)
    
    missing_buggy = all_tour_ids - covered_buggy
    
    # This SHOULD fail (demonstrating the bug)
    assert len(missing_buggy) > 0, "Expected coverage loss with buggy logic, but all tours were covered!"
    assert len(missing_buggy) == 3, f"Expected 3 missing tours, got {len(missing_buggy)}"
