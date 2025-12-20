"""
INSTANCE PROFILER - Feature Extraction for Portfolio Controller
===============================================================
Computes deterministic features from forecast/instance data
for path selection and parameter adaptation.

All features are computed deterministically (no randomness).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from src.domain.models import Block, Tour, Weekday

logger = logging.getLogger("InstanceProfiler")


# =============================================================================
# FEATURE VECTOR
# =============================================================================

@dataclass
class FeatureVector:
    """
    Deterministic features extracted from a forecast instance.
    Used by PolicyEngine to select solver path and parameters.
    """
    # Instance size metrics
    n_tours: int = 0
    n_blocks: int = 0
    blocks_per_tour_avg: float = 0.0
    
    # Difficulty metrics
    peakiness_index: float = 0.0       # 0-1: concentration of work in peak windows
    rest_risk_proxy: float = 0.0       # late→early transition potential
    pt_pressure_proxy: float = 0.0     # peak windows vs template capacity
    
    # Capacity metrics
    pool_pressure: str = "LOW"         # "LOW" | "MEDIUM" | "HIGH"
    coverage_density: float = 0.0      # avg blocks covering each tour
    
    # Day-specific lower bounds (from day-min solve)
    daymin_mon: int = 0
    daymin_tue: int = 0
    daymin_wed: int = 0
    daymin_thu: int = 0
    daymin_fri: int = 0
    daymin_sat: int = 0
    
    # Total lower bound (max of daymins)
    lower_bound_drivers: int = 0
    
    # Time budget classification
    time_budget_class: str = "MEDIUM"  # "SMALL" | "MEDIUM" | "LARGE"
    time_budget_seconds: float = 30.0
    
    # Block mix
    blocks_1er: int = 0
    blocks_2er: int = 0
    blocks_3er: int = 0
    
    # Additional metrics
    total_work_hours: float = 0.0
    expected_drivers_min: int = 0      # total_hours / 53
    expected_drivers_max: int = 0      # total_hours / 42

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "n_tours": self.n_tours,
            "n_blocks": self.n_blocks,
            "blocks_per_tour_avg": round(self.blocks_per_tour_avg, 2),
            "peakiness_index": round(self.peakiness_index, 3),
            "rest_risk_proxy": round(self.rest_risk_proxy, 3),
            "pt_pressure_proxy": round(self.pt_pressure_proxy, 3),
            "pool_pressure": self.pool_pressure,
            "coverage_density": round(self.coverage_density, 2),
            "daymin_mon": self.daymin_mon,
            "daymin_tue": self.daymin_tue,
            "daymin_wed": self.daymin_wed,
            "daymin_thu": self.daymin_thu,
            "daymin_fri": self.daymin_fri,
            "daymin_sat": self.daymin_sat,
            "lower_bound_drivers": self.lower_bound_drivers,
            "time_budget_class": self.time_budget_class,
            "time_budget_seconds": self.time_budget_seconds,
            "blocks_1er": self.blocks_1er,
            "blocks_2er": self.blocks_2er,
            "blocks_3er": self.blocks_3er,
            "total_work_hours": round(self.total_work_hours, 1),
            "expected_drivers_min": self.expected_drivers_min,
            "expected_drivers_max": self.expected_drivers_max,
        }


# =============================================================================
# FEATURE COMPUTATION
# =============================================================================

def compute_features(
    tours: list[Tour],
    blocks: list[Block],
    time_budget: float = 30.0,
    max_blocks: int = 50000,
) -> FeatureVector:
    """
    Compute all features from tours and blocks.
    
    Args:
        tours: List of Tour objects
        blocks: List of Block objects (after smart capping)
        time_budget: Total time budget in seconds
        max_blocks: Maximum block limit from config
    
    Returns:
        FeatureVector with all computed features
    """
    logger.info(f"Computing features: {len(tours)} tours, {len(blocks)} blocks")
    
    features = FeatureVector()
    
    # Basic counts
    features.n_tours = len(tours)
    features.n_blocks = len(blocks)
    features.time_budget_seconds = time_budget
    
    if not tours:
        return features
    
    # Blocks per tour average
    features.blocks_per_tour_avg = len(blocks) / len(tours) if tours else 0.0
    
    # Block mix
    features.blocks_1er = sum(1 for b in blocks if len(b.tours) == 1)
    features.blocks_2er = sum(1 for b in blocks if len(b.tours) == 2)
    features.blocks_3er = sum(1 for b in blocks if len(b.tours) == 3)
    
    # Total work hours
    features.total_work_hours = sum(t.duration_hours for t in tours)
    features.expected_drivers_min = int(features.total_work_hours / 53)
    features.expected_drivers_max = int(features.total_work_hours / 42) + 1
    
    # Pool pressure
    pool_ratio = len(blocks) / max_blocks if max_blocks > 0 else 0.0
    if pool_ratio >= 0.8:
        features.pool_pressure = "HIGH"
    elif pool_ratio >= 0.5:
        features.pool_pressure = "MEDIUM"
    else:
        features.pool_pressure = "LOW"
    
    # Time budget classification
    if time_budget <= 15.0:
        features.time_budget_class = "SMALL"
    elif time_budget <= 60.0:
        features.time_budget_class = "MEDIUM"
    else:
        features.time_budget_class = "LARGE"
    
    # Peakiness index (concentration of tours in peak windows)
    features.peakiness_index = _compute_peakiness(tours)
    
    # Rest risk proxy (late→early transitions)
    features.rest_risk_proxy = _compute_rest_risk(tours)
    
    # PT pressure proxy (peak demand vs capacity)
    features.pt_pressure_proxy = _compute_pt_pressure(tours)
    
    # Coverage density
    features.coverage_density = _compute_coverage_density(tours, blocks)
    
    # Day minimums (geometric lower bounds)
    daymin = _compute_day_minimums(tours)
    features.daymin_mon = daymin.get("Mon", 0)
    features.daymin_tue = daymin.get("Tue", 0)
    features.daymin_wed = daymin.get("Wed", 0)
    features.daymin_thu = daymin.get("Thu", 0)
    features.daymin_fri = daymin.get("Fri", 0)
    features.daymin_sat = daymin.get("Sat", 0)
    features.lower_bound_drivers = max(daymin.values()) if daymin else 0
    
    logger.info(f"Features computed: peakiness={features.peakiness_index:.2f}, "
                f"pool_pressure={features.pool_pressure}, "
                f"lower_bound={features.lower_bound_drivers}")
    
    return features


def _compute_peakiness(tours: list[Tour]) -> float:
    """
    Compute peakiness index: ratio of tours in busiest 3-hour windows.
    
    Higher peakiness = more concentrated demand = harder to schedule.
    """
    if not tours:
        return 0.0
    
    # Group tours by start hour
    hour_counts = defaultdict(int)
    for tour in tours:
        if hasattr(tour, 'start_time') and tour.start_time:
            hour = tour.start_time.hour
            hour_counts[hour] += 1
    
    if not hour_counts:
        return 0.0
    
    # Find top-3 hours by tour count
    sorted_counts = sorted(hour_counts.values(), reverse=True)
    top_3_sum = sum(sorted_counts[:3])
    
    # Peakiness = fraction of tours in top-3 hours
    peakiness = top_3_sum / len(tours)
    
    return peakiness


def _compute_rest_risk(tours: list[Tour]) -> float:
    """
    Compute rest risk proxy: count of potential late→early transitions.
    
    A late tour (ending >= 22:00) followed by an early tour (starting <= 07:00)
    next day creates rest constraint pressure.
    """
    if not tours:
        return 0.0
    
    # Group tours by day
    tours_by_day = defaultdict(list)
    for tour in tours:
        if hasattr(tour, 'day'):
            day_val = tour.day.value if hasattr(tour.day, 'value') else str(tour.day)
            tours_by_day[day_val].append(tour)
    
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    risk_count = 0
    
    for i, day in enumerate(day_order[:-1]):
        next_day = day_order[i + 1]
        
        # Count late tours today (end >= 22:00 = 1320 min)
        late_tours = sum(
            1 for t in tours_by_day.get(day, [])
            if hasattr(t, 'end_time') and t.end_time and t.end_time.hour >= 22
        )
        
        # Count early tours tomorrow (start <= 07:00 = 420 min)
        early_tours = sum(
            1 for t in tours_by_day.get(next_day, [])
            if hasattr(t, 'start_time') and t.start_time and t.start_time.hour <= 7
        )
        
        # Potential conflicts = min of late/early pairs
        risk_count += min(late_tours, early_tours)
    
    # Normalize by total tours
    return risk_count / len(tours) if tours else 0.0


def _compute_pt_pressure(tours: list[Tour]) -> float:
    """
    Compute PT pressure proxy: ratio of peak window demand to template capacity.
    
    High PT pressure means we'll likely need PT drivers for peak coverage.
    """
    if not tours:
        return 0.0
    
    # Count tours in typical peak windows (06:00-09:00, 15:00-18:00)
    peak_tours = 0
    for tour in tours:
        if hasattr(tour, 'start_time') and tour.start_time:
            hour = tour.start_time.hour
            if 6 <= hour <= 9 or 15 <= hour <= 18:
                peak_tours += 1
    
    # Estimate template capacity (simplified: 60% of tours can fit in non-peak)
    # PT pressure = how much peak exceeds this
    non_peak_capacity = 0.6 * len(tours)
    peak_demand = peak_tours
    
    if non_peak_capacity >= peak_demand:
        return 0.0
    
    # Excess as ratio
    return min(1.0, (peak_demand - non_peak_capacity) / len(tours))


def _compute_coverage_density(tours: list[Tour], blocks: list[Block]) -> float:
    """
    Compute coverage density: average number of blocks covering each tour.
    
    Higher density = more solver flexibility but larger search space.
    """
    if not tours or not blocks:
        return 0.0
    
    # Build tour -> blocks covering it
    tour_coverage = defaultdict(int)
    for block in blocks:
        if hasattr(block, 'tours'):
            for tour in block.tours:
                tour_id = tour.id if hasattr(tour, 'id') else str(tour)
                tour_coverage[tour_id] += 1
    
    if not tour_coverage:
        return 0.0
    
    return sum(tour_coverage.values()) / len(tour_coverage)


def _compute_day_minimums(tours: list[Tour]) -> dict[str, int]:
    """
    Compute geometric lower bounds for each day.
    
    Uses max concurrent tours as a simple lower bound for required drivers.
    """
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    daymin = {}
    
    # Group tours by day
    tours_by_day = defaultdict(list)
    for tour in tours:
        if hasattr(tour, 'day'):
            day_val = tour.day.value if hasattr(tour.day, 'value') else str(tour.day)
            tours_by_day[day_val].append(tour)
    
    for day in day_order:
        day_tours = tours_by_day.get(day, [])
        if not day_tours:
            daymin[day] = 0
            continue
        
        # Sweep line for max concurrent tours
        events = []
        for tour in day_tours:
            if hasattr(tour, 'start_time') and hasattr(tour, 'end_time'):
                start = tour.start_time.hour * 60 + tour.start_time.minute
                end = tour.end_time.hour * 60 + tour.end_time.minute
                events.append((start, 1))   # +1 at start
                events.append((end, -1))    # -1 at end
        
        if not events:
            daymin[day] = len(day_tours)  # Fallback: count tours
            continue
        
        # Sort: by time, ends before starts at same time
        events.sort(key=lambda x: (x[0], -x[1]))
        
        current = 0
        max_concurrent = 0
        for _, delta in events:
            current += delta
            max_concurrent = max(max_concurrent, current)
        
        daymin[day] = max_concurrent
    
    return daymin


# =============================================================================
# PROFILER CLASS (for stateful usage)
# =============================================================================

class InstanceProfiler:
    """
    Stateful profiler that caches computed features.
    """
    
    def __init__(self, max_blocks: int = 50000):
        self.max_blocks = max_blocks
        self._cache: Optional[FeatureVector] = None
        self._cache_key: tuple = ()
    
    def profile(
        self,
        tours: list[Tour],
        blocks: list[Block],
        time_budget: float = 30.0,
    ) -> FeatureVector:
        """
        Profile an instance, using cache if available.
        """
        cache_key = (len(tours), len(blocks), time_budget)
        
        if cache_key == self._cache_key and self._cache is not None:
            logger.debug("Using cached features")
            return self._cache
        
        features = compute_features(tours, blocks, time_budget, self.max_blocks)
        self._cache = features
        self._cache_key = cache_key
        
        return features
    
    def clear_cache(self):
        """Clear the feature cache."""
        self._cache = None
        self._cache_key = ()
