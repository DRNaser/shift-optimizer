"""
Core v2 - Fleet Peak Counter

Calculates peak concurrent vehicle count from a solution.
This is DIFFERENT from weekly driver count (MIP objective).
"""

from collections import defaultdict
from typing import Any


def calculate_fleet_peak(solution: list) -> dict[str, Any]:
    """
    Calculate peak concurrent vehicle requirement from final solution.
    
    Uses sweep-line algorithm to find max simultaneous tours at any moment.
    
    Args:
        solution: List of DriverAssignment objects with tours/shifts
        
    Returns:
        {
            "fleet_peak": int,  # Maximum concurrent vehicles needed
            "fleet_peak_by_day": dict[str, int],  # Peak per day
            "fleet_peak_time": str,  # When weekly peak occurs (day + time)
        }
    """
    if not solution:
        return {
            "fleet_peak": 0,
            "fleet_peak_by_day": {},
            "fleet_peak_time": "N/A",
        }
    
    # Aggregate all tour intervals by day
    events_by_day = defaultdict(list)
    
    for assignment in solution:
        # Each assignment has tours across potentially multiple days
        if hasattr(assignment, 'tours'):
            for tour in assignment.tours:
                day = tour.day.name if hasattr(tour.day, 'name') else str(tour.day)
                start_min = tour.start_time.hour * 60 + tour.start_time.minute
                # Calculate end time
                end_min = start_min + int(tour.duration_hours * 60)
                
                # Add events (start = +1, end = -1)
                events_by_day[day].append((start_min, +1, tour.id))
                events_by_day[day].append((end_min, -1, tour.id))
    
    # Calculate peak per day
    fleet_peak_by_day = {}
    global_peak = 0
    global_peak_time = "N/A"
    
    for day, events in events_by_day.items():
        # Sort events by time (tie-break: -1 before +1 to handle exact overlaps correctly)
        events.sort(key=lambda e: (e[0], -e[1]))
        
        concurrent = 0
        day_peak = 0
        day_peak_time = 0
        
        for time_min, delta, tour_id in events:
            concurrent += delta
            if concurrent > day_peak:
                day_peak = concurrent
                day_peak_time = time_min
        
        fleet_peak_by_day[day] = day_peak
        
        if day_peak > global_peak:
            global_peak = day_peak
            # Format time as HH:MM
            hours = day_peak_time // 60
            minutes = day_peak_time % 60
            global_peak_time = f"{day} {hours:02d}:{minutes:02d}"
    
    return {
        "fleet_peak": global_peak,
        "fleet_peak_by_day": dict(fleet_peak_by_day),
        "fleet_peak_time": global_peak_time,
    }


def calculate_fleet_peak_from_tours(tours: list) -> dict[str, Any]:
    """
    Calculate peak concurrent vehicles directly from tour list (before optimization).
    
    Useful for baseline comparison.
    
    Args:
        tours: List of TourV2 or Tour objects
        
    Returns:
        Same format as calculate_fleet_peak
    """
    if not tours:
        return {
            "fleet_peak": 0,
            "fleet_peak_by_day": {},
            "fleet_peak_time": "N/A",
        }
    
    # Aggregate events by day
    events_by_day = defaultdict(list)
    
    for tour in tours:
        # Handle both TourV2 (day as int) and Tour (day as Weekday)
        if hasattr(tour, 'day'):
            day = tour.day.name if hasattr(tour.day, 'name') else f"Day_{tour.day}"
        else:
            day = "Unknown"
        
        # Get start/end times
        if hasattr(tour, 'start_min'):
            # TourV2 format
            start_min = tour.start_min
            end_min = tour.end_min
        elif hasattr(tour, 'start_time'):
            # Tour (v1) format
            start_min = tour.start_time.hour * 60 + tour.start_time.minute
            end_min = start_min + int(tour.duration_hours * 60)
        else:
            continue
        
        tour_id = getattr(tour, 'tour_id', f"tour_{id(tour)}")
        
        events_by_day[day].append((start_min, +1, tour_id))
        events_by_day[day].append((end_min, -1, tour_id))
    
    # Calculate peak per day
    fleet_peak_by_day = {}
    global_peak = 0
    global_peak_time = "N/A"
    
    for day, events in events_by_day.items():
        events.sort(key=lambda e: (e[0], -e[1]))
        
        concurrent = 0
        day_peak = 0
        day_peak_time = 0
        
        for time_min, delta, tour_id in events:
            concurrent += delta
            if concurrent > day_peak:
                day_peak = concurrent
                day_peak_time = time_min
        
        fleet_peak_by_day[day] = day_peak
        
        if day_peak > global_peak:
            global_peak = day_peak
            hours = day_peak_time // 60
            minutes = day_peak_time % 60
            global_peak_time = f"{day} {hours:02d}:{minutes:02d}"
    
    return {
        "fleet_peak": global_peak,
        "fleet_peak_by_day": dict(fleet_peak_by_day),
        "fleet_peak_time": global_peak_time,
    }
