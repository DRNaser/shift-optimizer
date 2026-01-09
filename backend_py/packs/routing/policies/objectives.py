# =============================================================================
# SOLVEREIGN Routing Pack - Objective Profiles
# =============================================================================
# Objective weights per vertical.
#
# Different verticals have different optimization priorities:
# - MediaMarkt: High volume, km/min focus
# - HDL Plus: Low volume, on-time/risk focus
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ObjectiveProfile:
    """
    Objective weights for the solver.

    The solver minimizes:
    cost = unassigned_penalty * num_unassigned
         + time_window_penalty * tw_violations
         + distance_cost_per_km * total_km
         + overtime_penalty * overtime_hours
         - slack_bonus * total_slack
    """
    name: str

    # Hard constraint penalties (very high = near-mandatory)
    unassigned_penalty: int = 1_000_000      # Cost for each unassigned stop
    time_window_penalty: int = 100_000       # Cost for time window violation

    # Soft objective costs
    distance_cost_per_km: int = 100          # Cost per kilometer driven
    duration_cost_per_min: int = 10          # Cost per minute of route time
    overtime_penalty: int = 10_000           # Cost per minute of overtime

    # Bonuses (negative cost)
    slack_bonus: int = 10                    # Bonus per minute of slack (buffer)
    on_time_bonus: int = 100                 # Bonus for on-time arrival

    # Churn penalties (for repair)
    reassignment_penalty: int = 10_000       # Cost for moving stop to different vehicle
    resequence_penalty: int = 1_000          # Cost for changing stop sequence

    def describe(self) -> str:
        """Human-readable description of the profile."""
        if self.name == "MEDIAMARKT_DELIVERY":
            return "High-volume delivery: minimize distance and maximize stops per vehicle"
        elif self.name == "HDL_MONTAGE":
            return "Precision montage: strict time windows, maximize buffer time"
        else:
            return f"Custom profile: {self.name}"


# =============================================================================
# OBJECTIVE PROFILES (per Vertical)
# =============================================================================

OBJECTIVE_PROFILES: Dict[str, ObjectiveProfile] = {

    # =========================================================================
    # MediaMarkt: Delivery-focused
    # =========================================================================
    # High volume (many stops), distance/time efficiency matters most
    # Time windows are important but have some flexibility
    # Unassigned stops are very costly (each is lost revenue)

    "MEDIAMARKT_DELIVERY": ObjectiveProfile(
        name="MEDIAMARKT_DELIVERY",

        # Hard constraints
        unassigned_penalty=1_000_000,        # Very high - every stop matters
        time_window_penalty=100_000,         # High but not maximum

        # Soft objectives - distance/time focus
        distance_cost_per_km=100,            # High - minimize driving
        duration_cost_per_min=10,            # Medium
        overtime_penalty=10_000,             # Medium - some overtime OK

        # Slack is less important for delivery
        slack_bonus=10,                      # Low - don't over-optimize buffer
        on_time_bonus=100,                   # Medium

        # Churn for repair
        reassignment_penalty=5_000,          # Lower - flexibility for repair
        resequence_penalty=500,
    ),

    # =========================================================================
    # HDL Plus: Montage-focused
    # =========================================================================
    # Low volume (few stops), on-time is critical (customer waiting)
    # Time windows are hard constraints - violations = lost customer
    # Risk buffers matter - montage can run long

    "HDL_MONTAGE": ObjectiveProfile(
        name="HDL_MONTAGE",

        # Hard constraints - stricter time windows
        unassigned_penalty=1_000_000,        # Very high
        time_window_penalty=500_000,         # VERY high - on-time is critical

        # Soft objectives - time window adherence focus
        distance_cost_per_km=10,             # Low - distance less important
        duration_cost_per_min=5,             # Low
        overtime_penalty=100_000,            # High - montage can run late

        # Slack is critical for montage
        slack_bonus=1_000,                   # High - maximize buffer
        on_time_bonus=500,                   # High

        # Churn for repair - more restrictive
        reassignment_penalty=20_000,         # High - customer expects specific time
        resequence_penalty=2_000,
    ),

    # =========================================================================
    # Balanced: Default profile
    # =========================================================================
    # Balanced between delivery and montage priorities

    "BALANCED": ObjectiveProfile(
        name="BALANCED",

        unassigned_penalty=1_000_000,
        time_window_penalty=200_000,

        distance_cost_per_km=50,
        duration_cost_per_min=8,
        overtime_penalty=50_000,

        slack_bonus=100,
        on_time_bonus=200,

        reassignment_penalty=10_000,
        resequence_penalty=1_000,
    ),
}

# Default profile
DEFAULT_PROFILE = OBJECTIVE_PROFILES["BALANCED"]


def get_profile_for_vertical(vertical: str) -> ObjectiveProfile:
    """
    Get objective profile for a vertical.

    Args:
        vertical: "MEDIAMARKT" or "HDL_PLUS"

    Returns:
        ObjectiveProfile for the vertical
    """
    if vertical.upper() == "MEDIAMARKT":
        return OBJECTIVE_PROFILES["MEDIAMARKT_DELIVERY"]
    elif vertical.upper() == "HDL_PLUS":
        return OBJECTIVE_PROFILES["HDL_MONTAGE"]
    else:
        return DEFAULT_PROFILE


def list_profiles() -> list[str]:
    """List available profile names."""
    return list(OBJECTIVE_PROFILES.keys())
