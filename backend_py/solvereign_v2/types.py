"""
Solvereign V2 - Core Types

Extracted and cleaned domain types for the optimizer.
Migrated from src/core_v2/model/tour.py and src/core_v2/model/duty.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import hashlib


class Weekday(str, Enum):
    """Days of the week for scheduling."""
    MONDAY = "Mon"
    TUESDAY = "Tue"
    WEDNESDAY = "Wed"
    THURSDAY = "Thu"
    FRIDAY = "Fri"
    SATURDAY = "Sat"
    SUNDAY = "Sun"


class WeekCategory(str, Enum):
    """Week classification for solver configuration."""
    NORMAL = "NORMAL"           # 6-7 active days
    COMPRESSED = "COMPRESSED"   # 4-5 active days
    SHORT_WEEK = "SHORT_WEEK"   # 1-3 active days


# Day name mapping for readability
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_name(day_idx: int) -> str:
    """Convert day index to name."""
    return DAY_NAMES[day_idx] if 0 <= day_idx < 7 else f"Day{day_idx}"


@dataclass(frozen=True, order=True)
class TourV2:
    """
    Atomic tour - the coverage unit for Set-Partitioning.
    
    Immutable. All times in minutes from midnight (0-1440).
    Cross-midnight supported via end_min > 1440 convention.
    """
    tour_id: str
    day: int  # 0=Mon, 1=Tue, ..., 5=Sat, 6=Sun
    start_min: int  # 0..1440
    end_min: int    # 0..2880 (cross-midnight: +1440)
    duration_min: int
    
    # Optional features
    window_id: Optional[str] = field(default=None, compare=False)
    station: Optional[str] = field(default=None, compare=False)
    qualifications: tuple[str, ...] = field(default=(), compare=False)
    
    def __post_init__(self):
        """Validate tour invariants."""
        if self.day < 0 or self.day > 6:
            raise ValueError(f"Invalid day: {self.day}")
        if self.start_min < 0 or self.start_min > 1440:
            raise ValueError(f"Invalid start_min: {self.start_min}")
        if self.end_min < self.start_min:
            raise ValueError(f"end_min ({self.end_min}) < start_min ({self.start_min})")
    
    @property
    def signature(self) -> str:
        """Canonical hash for deduplication."""
        data = f"{self.tour_id}|{self.day}|{self.start_min}|{self.end_min}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    @property
    def is_cross_midnight(self) -> bool:
        """True if tour ends after midnight."""
        return self.end_min > 1440
    
    @property
    def start_hhmm(self) -> str:
        """Human-readable start time."""
        h, m = divmod(self.start_min, 60)
        return f"{h:02d}:{m:02d}"
    
    @property
    def end_hhmm(self) -> str:
        """Human-readable end time."""
        total = self.end_min % 1440
        h, m = divmod(total, 60)
        suffix = "+1" if self.end_min > 1440 else ""
        return f"{h:02d}:{m:02d}{suffix}"
    
    def overlaps(self, other: "TourV2") -> bool:
        """Check if this tour overlaps with another on same day."""
        if self.day != other.day:
            return False
        return not (self.end_min <= other.start_min or other.end_min <= self.start_min)
    
    def to_dict(self) -> dict:
        """Serialize to dict for JSON export."""
        return {
            "tour_id": self.tour_id,
            "day": self.day,
            "start_min": self.start_min,
            "end_min": self.end_min,
            "duration_min": self.duration_min,
            "window_id": self.window_id,
            "station": self.station,
            "qualifications": list(self.qualifications),
        }


@dataclass(frozen=True)
class DutyV2:
    """
    Day-internal combination of 1-3 tours.
    
    Immutable. Used as nodes in SPPRC pricing.
    """
    duty_id: str
    day: int
    tour_ids: tuple[str, ...]
    
    start_min: int
    end_min: int
    work_min: int
    span_min: int
    max_gap_min: int = 0
    
    valid: bool = True
    invalid_reason: Optional[str] = None
    num_tours: int = 1
    
    # For logging
    day_name: str = field(default="", compare=False)
    
    def __post_init__(self):
        """Ensure tour_ids is sorted and set day_name."""
        if self.tour_ids != tuple(sorted(self.tour_ids)):
            object.__setattr__(self, 'tour_ids', tuple(sorted(self.tour_ids)))
        if not self.day_name:
            object.__setattr__(self, 'day_name', day_name(self.day))
    
    @property
    def signature(self) -> str:
        """Canonical hash for deduplication."""
        data = f"{self.day}|{'|'.join(sorted(self.tour_ids))}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    @property
    def is_singleton(self) -> bool:
        """True if duty has only 1 tour."""
        return len(self.tour_ids) == 1
    
    @property
    def hours(self) -> float:
        """Work time in hours."""
        return self.work_min / 60.0
    
    @property
    def span_hours(self) -> float:
        """Span in hours."""
        return self.span_min / 60.0
    
    @property
    def start_hhmm(self) -> str:
        """Human-readable start time."""
        h, m = divmod(self.start_min, 60)
        return f"{h:02d}:{m:02d}"
    
    @property
    def end_hhmm(self) -> str:
        """Human-readable end time."""
        total = self.end_min % 1440
        h, m = divmod(total, 60)
        suffix = "+1" if self.end_min > 1440 else ""
        return f"{h:02d}:{m:02d}{suffix}"
    
    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "duty_id": self.duty_id,
            "day": self.day,
            "day_name": self.day_name,
            "tour_ids": list(self.tour_ids),
            "start_min": self.start_min,
            "end_min": self.end_min,
            "work_min": self.work_min,
            "span_min": self.span_min,
            "max_gap_min": self.max_gap_min,
            "valid": self.valid,
            "num_tours": self.num_tours,
            "signature": self.signature,
        }
    
    @classmethod
    def from_tours(
        cls,
        duty_id: str,
        tours: list[TourV2],
        valid: bool = True,
        invalid_reason: Optional[str] = None,
    ) -> "DutyV2":
        """Create a Duty from a list of tours."""
        if not tours:
            raise ValueError("Cannot create duty from empty tour list")
        
        sorted_tours = sorted(tours, key=lambda t: (t.start_min, t.tour_id))
        day = sorted_tours[0].day
        tour_ids = tuple(t.tour_id for t in sorted_tours)
        
        start_min = min(t.start_min for t in sorted_tours)
        end_min = max(t.end_min for t in sorted_tours)
        work_min = sum(t.duration_min for t in sorted_tours)
        span_min = end_min - start_min
        
        max_gap_min = 0
        if len(sorted_tours) > 1:
            gaps = []
            for i in range(len(sorted_tours) - 1):
                gap = sorted_tours[i+1].start_min - sorted_tours[i].end_min
                gaps.append(max(0, gap))
            if gaps:
                max_gap_min = max(gaps)
        
        return cls(
            duty_id=duty_id,
            day=day,
            tour_ids=tour_ids,
            start_min=start_min,
            end_min=end_min,
            work_min=work_min,
            span_min=span_min,
            max_gap_min=max_gap_min,
            valid=valid,
            invalid_reason=invalid_reason,
            num_tours=len(tours),
        )
