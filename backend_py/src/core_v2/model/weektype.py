"""
Core v2 - Week Type & Gates

Defines week categories (NORMAL, COMPRESSED) and their
hard utilization gates.
"""

from dataclasses import dataclass
from enum import Enum, auto


class WeekCategory(str, Enum):
    NORMAL = "NORMAL"          # 5-6 active days (standard)
    COMPRESSED = "COMPRESSED"  # 1-4 active days (e.g. KW51)
    SHORT = "SHORT"            # 1-2 days (unlikely but possible)


@dataclass(frozen=True)
class UtilizationGates:
    """Quality gates that a solution MUST pass."""
    
    # Hard Gates (Fail if violated)
    max_under_30h_percent: float  # e.g., 10.0%
    max_under_20h_percent: float  # e.g., 3.0% (kill bad duties)
    
    # Soft Targets (Warn if violated)
    target_avg_hours: float
    
    @classmethod
    def for_category(cls, category: WeekCategory) -> "UtilizationGates":
        """Factory for week-specific gates."""
        if category == WeekCategory.COMPRESSED:
            return cls(
                max_under_30h_percent=10.0,
                max_under_20h_percent=3.0,
                target_avg_hours=30.0,  # Lower target for compressed weeks
            )
        elif category == WeekCategory.SHORT:
            return cls(
                max_under_30h_percent=100.0, # Relaxed
                max_under_20h_percent=100.0,
                target_avg_hours=15.0,
            )
        else:  # NORMAL
            return cls(
                max_under_30h_percent=5.0,   # Stricter
                max_under_20h_percent=1.0,
                target_avg_hours=38.0,
            )


def classify_week(active_days_count: int) -> WeekCategory:
    """Determine week category from active day count."""
    if active_days_count <= 2:
        return WeekCategory.SHORT
    elif active_days_count <= 4:
        return WeekCategory.COMPRESSED
    else:
        return WeekCategory.NORMAL
