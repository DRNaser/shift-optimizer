"""
Core v2 - Tour Model (Atomic, Immutable)

THE COVERAGE UNIT: Each tour must be covered exactly once.
This is the fundamental audit trail element.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib


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
    
    # Optional features for compatibility/future
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
        """
        Canonical hash for deduplication.
        
        Deterministic: same tour → same signature.
        """
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
    
    @classmethod
    def from_dict(cls, data: dict) -> "TourV2":
        """Deserialize from dict."""
        return cls(
            tour_id=data["tour_id"],
            day=data["day"],
            start_min=data["start_min"],
            end_min=data["end_min"],
            duration_min=data["duration_min"],
            window_id=data.get("window_id"),
            station=data.get("station"),
            qualifications=tuple(data.get("qualifications", [])),
        )


# Day name mapping for readability
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_name(day_idx: int) -> str:
    """Convert day index to name."""
    return DAY_NAMES[day_idx] if 0 <= day_idx < 7 else f"Day{day_idx}"
