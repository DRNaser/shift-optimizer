"""
SOLVEREIGN V3 Time Normalizer
==============================

Centralized time handling for cross-midnight, timezone, and minute-offset.
All audit and peak-fleet modules should use this for consistent time logic.

Key Concepts:
    - Linear Time Axis: All times converted to minutes from week start
    - Cross-Midnight: Handled by adding 24h when end < start
    - Week Anchor: Monday 00:00 as reference point

Usage:
    from packs.roster.engine.time_normalizer import TimeNormalizer, TimeRange

    tn = TimeNormalizer(week_anchor=date(2026, 1, 6))

    # Convert tour times
    range1 = tn.normalize_tour(day=1, start=time(22,0), end=time(6,0))
    range2 = tn.normalize_tour(day=2, start=time(8,0), end=time(16,0))

    # Check overlap
    if range1.overlaps(range2):
        print("Tours overlap!")

    # Check rest period
    rest_minutes = range2.start - range1.end
    if rest_minutes < 11 * 60:
        print("Rest violation!")
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple


# ============================================================================
# TIME RANGE (Core Data Structure)
# ============================================================================

@dataclass
class TimeRange:
    """
    A time range on the linear week axis.

    All values in minutes from week start (Monday 00:00 = 0).
    """
    start: int  # Minutes from week start
    end: int    # Minutes from week start

    # Original values for debugging
    day: int = 0
    start_ts: Optional[time] = None
    end_ts: Optional[time] = None
    crosses_midnight: bool = False

    @property
    def duration(self) -> int:
        """Duration in minutes."""
        return self.end - self.start

    @property
    def span_hours(self) -> float:
        """Duration in hours."""
        return self.duration / 60.0

    def overlaps(self, other: TimeRange) -> bool:
        """
        Check if this range overlaps with another.

        Uses half-open interval logic: [start, end)
        """
        return self.start < other.end and self.end > other.start

    def gap_to(self, other: TimeRange) -> int:
        """
        Minutes between end of this range and start of other.

        Positive = gap exists (other starts after this ends)
        Negative = overlap (other starts before this ends)
        """
        return other.start - self.end

    def contains(self, minute: int) -> bool:
        """Check if a specific minute is within this range."""
        return self.start <= minute < self.end

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "day": self.day,
            "start_ts": str(self.start_ts) if self.start_ts else None,
            "end_ts": str(self.end_ts) if self.end_ts else None,
            "crosses_midnight": self.crosses_midnight,
        }


# ============================================================================
# TIME NORMALIZER (Main Class)
# ============================================================================

class TimeNormalizer:
    """
    Centralized time normalization for SOLVEREIGN.

    Converts (day, time) pairs to linear minutes from week start,
    handling cross-midnight correctly.
    """

    # Minutes per day
    MINUTES_PER_DAY = 24 * 60  # 1440

    # Week length in minutes
    WEEK_MINUTES = 7 * 24 * 60  # 10080

    def __init__(self, week_anchor: Optional[date] = None):
        """
        Initialize normalizer with optional week anchor.

        Args:
            week_anchor: Monday of the week (for datetime conversions)
        """
        self.week_anchor = week_anchor

    def day_to_offset(self, day: int) -> int:
        """
        Convert day number to minute offset.

        Args:
            day: Day number 1-7 (Mo=1, So=7)

        Returns:
            Minutes from Monday 00:00
        """
        return (day - 1) * self.MINUTES_PER_DAY

    def time_to_minutes(self, t: time) -> int:
        """Convert time to minutes from midnight."""
        return t.hour * 60 + t.minute

    def normalize_tour(
        self,
        day: int,
        start: time,
        end: time,
        crosses_midnight: Optional[bool] = None
    ) -> TimeRange:
        """
        Normalize a tour's time range.

        Args:
            day: Day number 1-7
            start: Start time
            end: End time
            crosses_midnight: Explicit flag (auto-detected if None)

        Returns:
            TimeRange on linear axis
        """
        # Auto-detect cross-midnight if not specified
        if crosses_midnight is None:
            crosses_midnight = end < start

        # Calculate start minutes
        start_minutes = self.day_to_offset(day) + self.time_to_minutes(start)

        # Calculate end minutes (handle cross-midnight)
        end_minutes = self.day_to_offset(day) + self.time_to_minutes(end)
        if crosses_midnight:
            end_minutes += self.MINUTES_PER_DAY  # Add 24 hours

        return TimeRange(
            start=start_minutes,
            end=end_minutes,
            day=day,
            start_ts=start,
            end_ts=end,
            crosses_midnight=crosses_midnight,
        )

    def normalize_instance(self, instance: dict) -> TimeRange:
        """
        Normalize a tour instance dict.

        Args:
            instance: Dict with day, start_ts, end_ts, crosses_midnight

        Returns:
            TimeRange on linear axis
        """
        return self.normalize_tour(
            day=instance['day'],
            start=instance['start_ts'],
            end=instance['end_ts'],
            crosses_midnight=instance.get('crosses_midnight', False),
        )

    def minute_to_datetime(self, minute: int) -> Optional[datetime]:
        """
        Convert minute offset to datetime.

        Requires week_anchor to be set.
        """
        if not self.week_anchor:
            return None
        return datetime.combine(
            self.week_anchor, time(0, 0)
        ) + timedelta(minutes=minute)

    def datetime_to_minute(self, dt: datetime) -> Optional[int]:
        """
        Convert datetime to minute offset.

        Requires week_anchor to be set.
        """
        if not self.week_anchor:
            return None
        delta = dt - datetime.combine(self.week_anchor, time(0, 0))
        return int(delta.total_seconds() / 60)

    def minute_to_day_time(self, minute: int) -> Tuple[int, time]:
        """
        Convert minute offset back to (day, time).

        Returns:
            Tuple of (day 1-7, time)
        """
        day = (minute // self.MINUTES_PER_DAY) + 1
        day_minute = minute % self.MINUTES_PER_DAY
        return day, time(day_minute // 60, day_minute % 60)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_overlap(ranges: List[TimeRange]) -> List[Tuple[TimeRange, TimeRange]]:
    """
    Find all overlapping pairs in a list of time ranges.

    Returns:
        List of (range1, range2) tuples that overlap
    """
    overlaps = []
    sorted_ranges = sorted(ranges, key=lambda r: r.start)

    for i, r1 in enumerate(sorted_ranges):
        for r2 in sorted_ranges[i+1:]:
            if r2.start >= r1.end:
                break  # No more overlaps possible
            if r1.overlaps(r2):
                overlaps.append((r1, r2))

    return overlaps


def compute_rest_between(range1: TimeRange, range2: TimeRange) -> int:
    """
    Compute rest period between two ranges.

    Assumes range1 ends before range2 starts.

    Returns:
        Rest period in minutes (negative if overlap)
    """
    return range2.start - range1.end


def compute_span(ranges: List[TimeRange]) -> int:
    """
    Compute total span from earliest start to latest end.

    Returns:
        Span in minutes
    """
    if not ranges:
        return 0
    return max(r.end for r in ranges) - min(r.start for r in ranges)


def compute_gaps(ranges: List[TimeRange]) -> List[int]:
    """
    Compute gaps between consecutive ranges (sorted by start).

    Returns:
        List of gap durations in minutes
    """
    if len(ranges) < 2:
        return []

    sorted_ranges = sorted(ranges, key=lambda r: r.start)
    gaps = []

    for i in range(1, len(sorted_ranges)):
        gap = sorted_ranges[i].start - sorted_ranges[i-1].end
        gaps.append(gap)

    return gaps


def find_concurrent_tours(
    ranges: List[TimeRange],
    sample_interval: int = 15
) -> Tuple[int, int]:
    """
    Find peak concurrent tours using interval sampling.

    Args:
        ranges: List of tour time ranges
        sample_interval: Sampling interval in minutes

    Returns:
        Tuple of (peak_count, peak_minute)
    """
    if not ranges:
        return 0, 0

    min_start = min(r.start for r in ranges)
    max_end = max(r.end for r in ranges)

    peak_count = 0
    peak_minute = min_start

    for minute in range(min_start, max_end, sample_interval):
        count = sum(1 for r in ranges if r.contains(minute))
        if count > peak_count:
            peak_count = count
            peak_minute = minute

    return peak_count, peak_minute


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_rest_between_days(
    day1_end: TimeRange,
    day2_start: TimeRange,
    min_rest_minutes: int = 660
) -> Tuple[bool, int]:
    """
    Validate rest period between two days.

    Args:
        day1_end: Last tour of day 1
        day2_start: First tour of day 2
        min_rest_minutes: Minimum rest (default 11h = 660min)

    Returns:
        Tuple of (is_valid, actual_rest_minutes)
    """
    rest = compute_rest_between(day1_end, day2_start)
    return rest >= min_rest_minutes, rest


def validate_span(
    ranges: List[TimeRange],
    max_span_minutes: int,
    block_type: str = "regular"
) -> Tuple[bool, int]:
    """
    Validate total span of ranges.

    Args:
        ranges: List of ranges in a block
        max_span_minutes: Maximum allowed span
        block_type: For error messages

    Returns:
        Tuple of (is_valid, actual_span_minutes)
    """
    span = compute_span(ranges)
    return span <= max_span_minutes, span


def validate_gaps(
    ranges: List[TimeRange],
    min_gap: int,
    max_gap: int,
    block_type: str = "regular"
) -> Tuple[bool, List[int]]:
    """
    Validate gaps between consecutive ranges.

    Args:
        ranges: List of ranges
        min_gap: Minimum gap in minutes
        max_gap: Maximum gap in minutes

    Returns:
        Tuple of (is_valid, gap_list)
    """
    gaps = compute_gaps(ranges)
    valid = all(min_gap <= g <= max_gap for g in gaps)
    return valid, gaps


# ============================================================================
# BLOCK CLASSIFICATION
# ============================================================================

def classify_block(ranges: List[TimeRange]) -> str:
    """
    Classify a block based on tour count and gaps.

    Returns:
        Block type: "1er", "2er-reg", "2er-split", "3er-chain"
    """
    n = len(ranges)

    if n == 1:
        return "1er"
    elif n == 2:
        gaps = compute_gaps(ranges)
        if gaps and 240 <= gaps[0] <= 360:
            return "2er-split"
        return "2er-reg"
    elif n >= 3:
        return "3er-chain"

    return "1er"


def get_span_limit(block_type: str) -> int:
    """
    Get span limit for block type.

    Returns:
        Span limit in minutes
    """
    if block_type in ("3er-chain", "2er-split"):
        return 960  # 16 hours
    return 840  # 14 hours


def get_gap_limits(block_type: str) -> Tuple[int, int]:
    """
    Get gap limits for block type.

    Returns:
        Tuple of (min_gap, max_gap) in minutes
    """
    if block_type == "2er-split":
        return 240, 360  # 4-6 hours
    return 30, 60  # 30-60 minutes
