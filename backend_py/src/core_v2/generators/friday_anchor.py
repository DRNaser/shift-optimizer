"""
Friday-Anchor-Pack Generator (B2)

Generates multi-day columns anchored on Friday-morning bottleneck tours.
This addresses the singleton dependency problem by creating multi-day rosters
that include problematic Friday tours.

Strategies:
- Move 1: Cross-day packing (Friday + Mon/Tue/Wed)
- Move 2: Intra-day packing (Friday 2er/3er blocks)
"""
from typing import List, Set
from ..model.tour import TourV2
from ..model.duty import DutyV2
from ..model.column import ColumnV2
from ..validator.rules import ValidatorV2


def generate_friday_anchor_columns(
    friday_anchor_tours: List[TourV2],
    tours_by_day: dict[int, List[TourV2]],
    max_columns: int = 1000
) -> List[ColumnV2]:
    """
    Generate multi-day columns using Friday tours as anchors.
    
    Args:
        friday_anchor_tours: Friday tours to use as anchors (low-support tours)
        tours_by_day: All tours grouped by day
        max_columns: Maximum number of columns to generate
    
    Returns:
        List of ColumnV2 objects with Friday anchors
    """
    columns = []
    col_id_counter = 0
    
    # Move 1: Cross-day packing (Friday + other days)
    for anchor in friday_anchor_tours:
        # Try pairing with Mon/Tue/Wed tours
        for day in [0, 1, 2]:  # Monday, Tuesday, Wednesday
            if day not in tours_by_day:
                continue
                
            for candidate_tour in tours_by_day[day]:
                # Create 2-day column: Other day + Friday
                duties = []
                
                # Day 1 duty (Mon/Tue/Wed)
                d1 = DutyV2(
                    duty_id=f"D_{day}_{candidate_tour.tour_id}",
                    day=day,
                    start_min=candidate_tour.start_min,
                    end_min=candidate_tour.end_min,
                    tour_ids=(candidate_tour.tour_id,),
                    work_min=candidate_tour.duration_min,
                    span_min=candidate_tour.duration_min
                )
                
                # Friday duty
                d2 = DutyV2(
                    duty_id=f"D_4_{anchor.tour_id}",
                    day=4,
                    start_min=anchor.start_min,
                    end_min=anchor.end_min,
                    tour_ids=(anchor.tour_id,),
                    work_min=anchor.duration_min,
                    span_min=anchor.duration_min
                )
                
                duties = [d1, d2]
                
                # Validate: Check 11h rest, max span, etc.
                # Simple validation: duties on different days, no overlap
                if _validate_cross_day_roster(duties):
                    col = ColumnV2.from_duties(
                        col_id=f"FriAnchor_{col_id_counter}",
                        duties=duties,
                        origin="friday_anchor_cross_day"
                    )
                    columns.append(col)
                    col_id_counter += 1
                    
                    if len(columns) >= max_columns:
                        return columns
    
    # Move 2: Intra-day packing (Friday 2er/3er on same day)
    if 4 in tours_by_day:
        friday_tours = tours_by_day[4]
        
        for anchor in friday_anchor_tours:
            # Try pairing with other Friday tours
            for other_tour in friday_tours:
                if other_tour.tour_id == anchor.tour_id:
                    continue
                
                # Check if they can be combined (pause rules)
                if _can_pair_intraday(anchor, other_tour):
                    # Create Friday 2er duty
                    combined_tour_ids = (anchor.tour_id, other_tour.tour_id)
                    start = min(anchor.start_min, other_tour.start_min)
                    end = max(anchor.end_min, other_tour.end_min)
                    work = anchor.duration_min + other_tour.duration_min
                    span = end - start
                    
                    duty = DutyV2(
                        duty_id=f"D_fri_2er_{col_id_counter}",
                        day=4,
                        start_min=start,
                        end_min=end,
                        tour_ids=combined_tour_ids,
                        work_min=work,
                        span_min=span
                    )
                    
                    # Create 1-day column with this Friday 2er
                    col = ColumnV2.from_duties(
                        col_id=f"FriAnchor_{col_id_counter}",
                        duties=[duty],
                        origin="friday_anchor_intraday"
                    )
                    columns.append(col)
                    col_id_counter += 1
                    
                    if len(columns) >= max_columns:
                        return columns
    
    return columns


def _validate_cross_day_roster(duties: List[DutyV2]) -> bool:
    """
    Validate cross-day roster (simple version).
    
    Checks:
    - Duties on different days
    - No same-day overlap
    """
    days = [d.day for d in duties]
    if len(days) != len(set(days)):
        return False  # Same day duties
    
    return True


def _can_pair_intraday(tour1: TourV2, tour2: TourV2) -> bool:
    """
    Check if two Friday tours can be paired into a 2er block.
    
    Rules:
    - Minimum pause: 30 min
    - Maximum pause: 90 min (regular) or 360 min (split)
    - No overlap
    """
    if tour1.start_min < tour2.start_min:
        first, second = tour1, tour2
    else:
        first, second = tour2, tour1
    
    # Check overlap
    if first.end_min > second.start_min:
        return False
    
    # Check pause
    pause = second.start_min - first.end_min
    
    # Regular pause (30-90 min) or split pause (360 min)
    if (30 <= pause <= 90) or (pause == 360):
        return True
    
    return False
