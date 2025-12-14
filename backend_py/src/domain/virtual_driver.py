"""
VIRTUAL DRIVER MODEL
====================
Virtual driver generation for forecast-only planning.
"""

from dataclasses import dataclass
from src.domain.models import Weekday


@dataclass
class VirtualDriver:
    """
    Virtual driver for forecast-only planning.
    No availability restrictions - available all days.
    """
    id: str
    min_weekly_hours: float = 42.0
    max_weekly_hours: float = 53.0
    
    @property
    def available_days(self) -> list[Weekday]:
        """Virtual drivers available all days."""
        return list(Weekday)
    
    def __hash__(self):
        return hash(self.id)


def generate_virtual_drivers(
    k: int,
    min_hours: float = 42.0,
    max_hours: float = 53.0
) -> list[VirtualDriver]:
    """
    Generate K virtual drivers.
    
    Args:
        k: Number of drivers to generate
        min_hours: Minimum weekly hours (default 42)
        max_hours: Maximum weekly hours (default 53)
        
    Returns:
        List of VirtualDriver instances with IDs V001...V{k}
    """
    return [
        VirtualDriver(
            id=f"V{i:03d}",
            min_weekly_hours=min_hours,
            max_weekly_hours=max_hours
        )
        for i in range(1, k + 1)
    ]


def compute_driver_bounds(total_hours: float, min_per_driver: float = 42.0, max_per_driver: float = 53.0) -> tuple[int, int]:
    """
    Compute min/max number of drivers needed.
    
    Args:
        total_hours: Total work hours from all tours
        min_per_driver: Minimum hours per driver (default 42)
        max_per_driver: Maximum hours per driver (default 53)
        
    Returns:
        (K_min, K_max) tuple:
        - K_min: Minimum drivers needed (if all work max hours)
        - K_max: Maximum drivers needed (if all work min hours)
    """
    import math
    
    if total_hours <= 0:
        return (0, 0)
    
    # K_min = ceil(total / max_per_driver)
    k_min = math.ceil(total_hours / max_per_driver)
    
    # K_max = ceil(total / min_per_driver) 
    # Cap at reasonable upper bound (+30% of k_min)
    k_max_raw = math.ceil(total_hours / min_per_driver)
    k_max_capped = max(k_min, min(k_max_raw, int(k_min * 1.3) + 1))
    
    return (k_min, k_max_capped)
