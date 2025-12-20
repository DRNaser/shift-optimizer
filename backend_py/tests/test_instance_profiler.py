"""
Tests for Instance Profiler
============================
Tests feature computation from tours and blocks.
"""

import pytest
from datetime import time
from unittest.mock import MagicMock
from dataclasses import dataclass

# Mock the domain models for isolated testing
@dataclass
class MockTour:
    id: str
    day: 'MockWeekday'
    start_time: time
    end_time: time
    duration_hours: float = 8.0


class MockWeekday:
    def __init__(self, value: str):
        self.value = value
    
    MONDAY = None
    TUESDAY = None
    WEDNESDAY = None
    THURSDAY = None
    FRIDAY = None
    SATURDAY = None


MockWeekday.MONDAY = MockWeekday("Mon")
MockWeekday.TUESDAY = MockWeekday("Tue")
MockWeekday.WEDNESDAY = MockWeekday("Wed")
MockWeekday.THURSDAY = MockWeekday("Thu")
MockWeekday.FRIDAY = MockWeekday("Fri")
MockWeekday.SATURDAY = MockWeekday("Sat")


@dataclass
class MockBlock:
    id: str
    day: MockWeekday
    tours: list
    first_start: time = time(6, 0)
    last_end: time = time(14, 0)
    total_work_hours: float = 8.0


class TestFeatureVector:
    """Test FeatureVector dataclass."""
    
    def test_to_dict_returns_all_fields(self):
        from src.services.instance_profiler import FeatureVector
        
        fv = FeatureVector(
            n_tours=100,
            n_blocks=500,
            blocks_per_tour_avg=5.0,
            peakiness_index=0.35,
            pool_pressure="MEDIUM",
            lower_bound_drivers=45,
        )
        
        d = fv.to_dict()
        
        assert d["n_tours"] == 100
        assert d["n_blocks"] == 500
        assert d["blocks_per_tour_avg"] == 5.0
        assert d["peakiness_index"] == 0.35
        assert d["pool_pressure"] == "MEDIUM"
        assert d["lower_bound_drivers"] == 45


class TestComputeFeatures:
    """Test compute_features function."""
    
    def test_empty_tours_returns_empty_features(self):
        from src.services.instance_profiler import compute_features
        
        features = compute_features([], [], time_budget=30.0)
        
        assert features.n_tours == 0
        assert features.n_blocks == 0
        assert features.peakiness_index == 0.0
    
    def test_basic_counts(self):
        from src.services.instance_profiler import compute_features
        
        tours = [
            MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(14, 0), 8.0),
            MockTour("T2", MockWeekday.MONDAY, time(7, 0), time(15, 0), 8.0),
            MockTour("T3", MockWeekday.TUESDAY, time(6, 0), time(14, 0), 8.0),
        ]
        
        blocks = [
            MockBlock("B1", MockWeekday.MONDAY, [tours[0]]),
            MockBlock("B2", MockWeekday.MONDAY, [tours[1]]),
            MockBlock("B3", MockWeekday.TUESDAY, [tours[2]]),
            MockBlock("B4", MockWeekday.MONDAY, [tours[0], tours[1]]),
        ]
        
        features = compute_features(tours, blocks, time_budget=30.0, max_blocks=50000)
        
        assert features.n_tours == 3
        assert features.n_blocks == 4
        assert features.blocks_per_tour_avg == pytest.approx(4/3, rel=0.01)
    
    def test_pool_pressure_classification(self):
        from src.services.instance_profiler import compute_features
        
        tours = [MockTour(f"T{i}", MockWeekday.MONDAY, time(6, 0), time(14, 0)) for i in range(10)]
        
        # Low pressure: 100 blocks / 1000 max = 10%
        blocks_low = [MockBlock(f"B{i}", MockWeekday.MONDAY, [tours[0]]) for i in range(100)]
        features = compute_features(tours, blocks_low, max_blocks=1000)
        assert features.pool_pressure == "LOW"
        
        # Medium pressure: 600 blocks / 1000 max = 60%
        blocks_med = [MockBlock(f"B{i}", MockWeekday.MONDAY, [tours[0]]) for i in range(600)]
        features = compute_features(tours, blocks_med, max_blocks=1000)
        assert features.pool_pressure == "MEDIUM"
        
        # High pressure: 850 blocks / 1000 max = 85%
        blocks_high = [MockBlock(f"B{i}", MockWeekday.MONDAY, [tours[0]]) for i in range(850)]
        features = compute_features(tours, blocks_high, max_blocks=1000)
        assert features.pool_pressure == "HIGH"
    
    def test_time_budget_classification(self):
        from src.services.instance_profiler import compute_features
        
        tours = [MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(14, 0))]
        blocks = [MockBlock("B1", MockWeekday.MONDAY, [tours[0]])]
        
        # Small budget
        features = compute_features(tours, blocks, time_budget=10.0)
        assert features.time_budget_class == "SMALL"
        
        # Medium budget
        features = compute_features(tours, blocks, time_budget=30.0)
        assert features.time_budget_class == "MEDIUM"
        
        # Large budget
        features = compute_features(tours, blocks, time_budget=120.0)
        assert features.time_budget_class == "LARGE"
    
    def test_block_mix_counts(self):
        from src.services.instance_profiler import compute_features
        
        tours = [
            MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(10, 0)),
            MockTour("T2", MockWeekday.MONDAY, time(10, 30), time(14, 0)),
            MockTour("T3", MockWeekday.MONDAY, time(14, 30), time(18, 0)),
        ]
        
        blocks = [
            MockBlock("B1", MockWeekday.MONDAY, [tours[0]]),  # 1er
            MockBlock("B2", MockWeekday.MONDAY, [tours[1]]),  # 1er
            MockBlock("B3", MockWeekday.MONDAY, [tours[2]]),  # 1er
            MockBlock("B4", MockWeekday.MONDAY, [tours[0], tours[1]]),  # 2er
            MockBlock("B5", MockWeekday.MONDAY, [tours[0], tours[1], tours[2]]),  # 3er
        ]
        
        features = compute_features(tours, blocks)
        
        assert features.blocks_1er == 3
        assert features.blocks_2er == 1
        assert features.blocks_3er == 1


class TestInstanceProfiler:
    """Test InstanceProfiler class."""
    
    def test_caching(self):
        from src.services.instance_profiler import InstanceProfiler
        
        profiler = InstanceProfiler(max_blocks=50000)
        
        tours = [MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(14, 0))]
        blocks = [MockBlock("B1", MockWeekday.MONDAY, [tours[0]])]
        
        # First call computes
        features1 = profiler.profile(tours, blocks, 30.0)
        
        # Second call with same params uses cache
        features2 = profiler.profile(tours, blocks, 30.0)
        
        assert features1 is features2  # Same object from cache
    
    def test_cache_invalidation_on_different_params(self):
        from src.services.instance_profiler import InstanceProfiler
        
        profiler = InstanceProfiler(max_blocks=50000)
        
        tours = [MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(14, 0))]
        blocks = [MockBlock("B1", MockWeekday.MONDAY, [tours[0]])]
        
        features1 = profiler.profile(tours, blocks, 30.0)
        features2 = profiler.profile(tours, blocks, 60.0)  # Different budget
        
        assert features1 is not features2  # New computation


class TestDeterminism:
    """Test that feature computation is deterministic."""
    
    def test_same_input_same_output(self):
        from src.services.instance_profiler import compute_features
        
        tours = [
            MockTour(f"T{i}", MockWeekday.MONDAY, time(6 + i % 12, 0), time(14 + i % 6, 0), 8.0)
            for i in range(50)
        ]
        blocks = [
            MockBlock(f"B{i}", MockWeekday.MONDAY, [tours[i % len(tours)]])
            for i in range(100)
        ]
        
        features1 = compute_features(tours, blocks, time_budget=30.0)
        features2 = compute_features(tours, blocks, time_budget=30.0)
        
        assert features1.to_dict() == features2.to_dict()
