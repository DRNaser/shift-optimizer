"""
SOLVEREIGN V4.9.2 - Week Window Types & Helpers
================================================

Week boundary calculation and basic data structures for lookahead.

Split from week_lookahead.py for maintainability.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Set


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class AffectedSlot:
    """
    A slot affected by a candidate assignment.

    Reasons:
    - REST_VIOLATION: 11-hour rest rule would be broken
    - REST_NEXTDAY_FIRST_SLOT: Rest violation only affects first slot next day
    - OVERLAP: Direct time overlap with existing assignment
    - MAX_TOURS: Driver would exceed max tours per day
    - HOURS_EXCEEDED: Weekly hours limit exceeded (soft - overtime risk)
    - PINNED: Slot is pinned and multiday repair not allowed
    - FROZEN: Slot is on a frozen day (hard block)
    """
    date: date
    slot_id: str
    tour_instance_id: int
    reason: str
    current_driver_id: Optional[int] = None
    severity: str = "WARN"  # "HARD" (frozen/pinned) or "WARN" (can be repaired)


@dataclass
class WeekWindow:
    """Week boundary for lookahead (Mon-Sun)."""
    week_start: date  # Always Monday
    week_end: date    # Always Sunday

    def contains(self, d: date) -> bool:
        """Check if date is within this week."""
        return self.week_start <= d <= self.week_end

    def days_list(self) -> List[date]:
        """Return list of all days in the week."""
        return [self.week_start + timedelta(days=i) for i in range(7)]

    def days_from(self, start_date: date) -> List[date]:
        """Return list of days from start_date to week_end (inclusive)."""
        if start_date > self.week_end:
            return []
        clamped_start = max(start_date, self.week_start)
        days = []
        current = clamped_start
        while current <= self.week_end:
            days.append(current)
            current += timedelta(days=1)
        return days


@dataclass
class DayAssignment:
    """A single assignment for a driver on a specific day."""
    day_date: date
    day_index: int  # 0=Mon, 6=Sun
    tour_instance_id: int
    slot_id: Optional[str] = None
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    is_frozen: bool = False
    is_pinned: bool = False  # Per-assignment pin, not day-level


@dataclass
class SlotContext:
    """Context for a slot that needs candidates."""
    slot_id: str
    tour_instance_id: int
    day_date: date
    day_index: int
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    duration_minutes: int = 0
    current_driver_id: Optional[int] = None
    is_open: bool = True  # Needs assignment
    is_at_risk: bool = False  # Has risk/violation


# =============================================================================
# WEEK WINDOW HELPERS
# =============================================================================

def get_week_window(day_date: date) -> WeekWindow:
    """
    Get the week window (Mon-Sun) containing the given date.

    Args:
        day_date: Any date within the target week

    Returns:
        WeekWindow with week_start (Monday) and week_end (Sunday)
    """
    # day_date.weekday() returns 0=Mon, 6=Sun
    days_since_monday = day_date.weekday()
    week_start = day_date - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)

    return WeekWindow(week_start=week_start, week_end=week_end)


def day_index_from_date(d: date) -> int:
    """Convert date to day index (0=Mon, 6=Sun)."""
    return d.weekday()


def get_lookahead_range(day_date: date, week_window: WeekWindow) -> tuple[date, date]:
    """
    Get the lookahead evaluation range.

    CRITICAL: Lookahead starts from TODAY (day_date), not week_start.
    We don't care about past days for churn calculation.

    Returns:
        (lookahead_start, lookahead_end) where:
        - lookahead_start = day_date (today)
        - lookahead_end = week_end (Sunday)
    """
    return (day_date, week_window.week_end)
