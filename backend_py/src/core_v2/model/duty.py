"""
Core v2 - Duty Model (Day-Internal Work Unit)

A Duty is a combination of 1-3 tours on the SAME day.
Duties are the nodes in the SPPRC pricing graph.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib

from .tour import TourV2, day_name


@dataclass(frozen=True)
class DutyV2:
    """
    Day-internal combination of 1-3 tours.
    
    Immutable. Used as nodes in SPPRC pricing.
    Each duty covers specific tour_ids.
    """
    duty_id: str
    day: int  # 0=Mon..6=Sun
    tour_ids: tuple[str, ...]  # Sorted, immutable - the covered tours
    
    # Timing (derived from constituent tours)
    start_min: int  # First tour start
    end_min: int    # Last tour end
    work_min: int   # Total working minutes
    span_min: int   # end_min - start_min
    
    # Validation status
    valid: bool = True
    invalid_reason: Optional[str] = None
    
    # Block type (for compatibility with v1)
    num_tours: int = 1
    
    def __post_init__(self):
        """Ensure tour_ids is sorted for canonical representation."""
        if self.tour_ids != tuple(sorted(self.tour_ids)):
            object.__setattr__(self, 'tour_ids', tuple(sorted(self.tour_ids)))
    
    @property
    def signature(self) -> str:
        """
        Canonical hash for deduplication.
        
        Based on day + sorted tour_ids.
        """
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
            "day_name": day_name(self.day),
            "tour_ids": list(self.tour_ids),
            "start_min": self.start_min,
            "end_min": self.end_min,
            "work_min": self.work_min,
            "span_min": self.span_min,
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
        """
        Create a Duty from a list of tours.
        
        Tours must be on the same day (not enforced here - caller responsibility).
        """
        if not tours:
            raise ValueError("Cannot create duty from empty tour list")
        
        sorted_tours = sorted(tours, key=lambda t: (t.start_min, t.tour_id))
        day = sorted_tours[0].day
        tour_ids = tuple(t.tour_id for t in sorted_tours)
        
        start_min = min(t.start_min for t in sorted_tours)
        end_min = max(t.end_min for t in sorted_tours)
        work_min = sum(t.duration_min for t in sorted_tours)
        span_min = end_min - start_min
        
        return cls(
            duty_id=duty_id,
            day=day,
            tour_ids=tour_ids,
            start_min=start_min,
            end_min=end_min,
            work_min=work_min,
            span_min=span_min,
            valid=valid,
            invalid_reason=invalid_reason,
            num_tours=len(tours),
        )


def dominates(duty_a: DutyV2, duty_b: DutyV2) -> bool:
    """
    Check if duty_a dominates duty_b (and b should be pruned).
    
    A dominates B if:
    - Same tour coverage
    - A has better or equal span
    - A has better or equal work time
    
    Returns True if A dominates B.
    """
    if set(duty_a.tour_ids) != set(duty_b.tour_ids):
        return False
    return duty_a.span_min <= duty_b.span_min and duty_a.work_min >= duty_b.work_min
