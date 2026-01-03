"""
Split-Chain Seeder: O1+O3 Unified Implementation

Generates 5-day chains of split-shift patterns based on manual planning analysis.
Pattern: Early morning (04:00-09:00) + Evening (17:00-22:00) = 45h/week
"""

from typing import Optional
from .model.tour import TourV2
from .model.duty import DutyV2
from .model.column import ColumnV2


def generate_split_chain_seeds(
    tours_by_day: dict[int, list[TourV2]],
    duty_factory,
    can_chain_days_func
) -> list[ColumnV2]:
    """
    O1+O3 UNIFIED: Split-Chain Seeder
    
    Based on manual planning analysis (traindata.xlsx):
    - 72% of days use 2-tour patterns
    - 26.5% are split shifts with ~6h gaps
    - Early + evening pairing creates 45h/week (vs 22.5h single-tour)
    
    Args:
        tours_by_day: Tours grouped by day
        duty_factory: Factory to create duties
        can_chain_days_func: Validator function for chaining
    
    Returns:
        List of ColumnV2 (5-day split-shift chains)
    """
    cols = []
    
    # Constants from manual analysis
    MAX_SPAN_HOURS = 11.5  # Conservative buffer below 12h
    MIN_GAP_HOURS = 3.0
    MAX_GAP_HOURS = 8.0
    EARLY_END_MIN = 540  # 09:00 (expanded from 07:00)
    EVENING_START_MIN = 1020  # 17:00
    EVENING_END_MIN = 1320  # 22:00
    
    # Helper: Find evening tour on specific day
    def find_evening_tour(day: int) -> Optional[TourV2]:
        if day not in tours_by_day:
            return None
        candidates = [t for t in tours_by_day[day]
                     if EVENING_START_MIN <= t.start_min <= EVENING_END_MIN]
        if not candidates:
            return None
        # Prefer earlier evening starts (minimize span)
        candidates.sort(key=lambda t: t.start_min)
        return candidates[0]
    
    # Helper: Find similar early tour on another day
    def find_similar_early_tour(day: int, ref_start_min: int) -> Optional[TourV2]:
        if day not in tours_by_day:
            return None
        candidates = [t for t in tours_by_day[day]
                     if abs(t.start_min - ref_start_min) <= 45  # +/- 45 min
                     and t.start_min < EARLY_END_MIN]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(t.start_min - ref_start_min))
        return candidates[0]
    
    # Find all early tours on Monday (day 0)
    early_tours_mon = []
    if 0 in tours_by_day:
        early_tours_mon = [t for t in tours_by_day[0]
                          if t.start_min < EARLY_END_MIN]
    
    if not early_tours_mon:
        return []
    
    # Build split-chains
    for early_mon in early_tours_mon:
        # Find evening tour on Monday
        evening_mon = find_evening_tour(0)
        if not evening_mon:
            continue
        
        # Check span and gap constraints
        span_min = evening_mon.end_min - early_mon.start_min
        gap_min = evening_mon.start_min - early_mon.end_min
        
        if span_min > MAX_SPAN_HOURS * 60:
            continue
        if gap_min < MIN_GAP_HOURS * 60 or gap_min > MAX_GAP_HOURS * 60:
            continue
        
        # Create Monday duty (early + evening)
        duty_mon = duty_factory.create_duty_from_tours(
            day=0,
            tour_ids=[early_mon.tour_id, evening_mon.tour_id]
        )
        if not duty_mon:
            continue
        
        # Build chain for Tue-Fri (days 1-4)
        duties = {0: duty_mon}
        
        for day in range(1, 5):
            early_day = find_similar_early_tour(day, early_mon.start_min)
            evening_day = find_evening_tour(day)
            
            if not early_day or not evening_day:
                break
            
            # Create split duty for this day
            duty_day = duty_factory.create_duty_from_tours(
                day=day,
                tour_ids=[early_day.tour_id, evening_day.tour_id]
            )
            if not duty_day:
                break
            
            duties[day] = duty_day
        
        # Require at least 4 days
        if len(duties) < 4:
            continue
        
        # Validate chainability
        day_seq = sorted(duties.keys())
        duty_list = [duties[d] for d in day_seq]
        
        if not can_chain_days_func(duty_list):
            continue
        
        # Create column
        col = ColumnV2(
            duties=duty_list,
            days_worked=len(duty_list),
            total_hours=sum(d.total_hours for d in duty_list)
        )
        cols.append(col)
    
    return cols
