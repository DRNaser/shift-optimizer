"""
SOLVEREIGN Gurkerl Dispatch Assist - Eligibility Checker
=========================================================

Hard constraint filters for driver eligibility.

Hard Constraints (MUST pass all):
1. Not absent (sick/vacation)
2. 11-hour rest between shifts
3. Max tours per day
4. Weekly hours hard max (55h default)
5. Required skills match
6. Zone match (if applicable)

These are NON-NEGOTIABLE. A driver failing ANY hard constraint
is disqualified from the candidate pool.
"""

import logging
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Tuple

from .models import (
    OpenShift,
    DriverState,
    Candidate,
    Disqualification,
    DisqualificationReason,
    ShiftAssignment,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_REST_HOURS = 11  # Minimum rest between shifts
DEFAULT_MAX_TOURS_PER_DAY = 2  # Maximum shifts per day
DEFAULT_MAX_WEEKLY_HOURS = 55.0  # Hard weekly limit


# =============================================================================
# ELIGIBILITY CHECKER
# =============================================================================

class EligibilityChecker:
    """
    Checks driver eligibility against hard constraints.

    All checks are hard constraints - failing any one disqualifies the driver.
    """

    def __init__(
        self,
        rest_hours: int = DEFAULT_REST_HOURS,
        max_tours_per_day: int = DEFAULT_MAX_TOURS_PER_DAY,
        max_weekly_hours: float = DEFAULT_MAX_WEEKLY_HOURS,
    ):
        """
        Initialize with constraint parameters.

        Args:
            rest_hours: Minimum rest between shifts (default 11)
            max_tours_per_day: Maximum shifts per day (default 2)
            max_weekly_hours: Weekly hours hard limit (default 55)
        """
        self.rest_hours = rest_hours
        self.max_tours_per_day = max_tours_per_day
        self.max_weekly_hours = max_weekly_hours

    def check_eligibility(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Tuple[bool, List[Disqualification]]:
        """
        Check if driver is eligible for a shift.

        Args:
            driver: Current driver state
            shift: The open shift to fill

        Returns:
            Tuple of (is_eligible, list of disqualifications)
        """
        disqualifications: List[Disqualification] = []

        # Check 1: Absence
        absence = self._check_absence(driver, shift.shift_date)
        if absence:
            disqualifications.append(absence)

        # Check 2: Already assigned
        already_assigned = self._check_already_assigned(driver, shift)
        if already_assigned:
            disqualifications.append(already_assigned)

        # Check 3: 11-hour rest
        rest_violation = self._check_rest_constraint(driver, shift)
        if rest_violation:
            disqualifications.append(rest_violation)

        # Check 4: Max tours per day
        max_tours = self._check_max_tours(driver, shift.shift_date)
        if max_tours:
            disqualifications.append(max_tours)

        # Check 5: Weekly hours
        hours_violation = self._check_weekly_hours(driver, shift)
        if hours_violation:
            disqualifications.append(hours_violation)

        # Check 6: Skills
        skill_violation = self._check_skills(driver, shift)
        if skill_violation:
            disqualifications.append(skill_violation)

        # Check 7: Zone
        zone_violation = self._check_zone(driver, shift)
        if zone_violation:
            disqualifications.append(zone_violation)

        is_eligible = len(disqualifications) == 0

        if not is_eligible:
            logger.debug(
                f"Driver {driver.driver_id} disqualified for shift {shift.id}: "
                f"{[d.reason.value for d in disqualifications]}"
            )

        return is_eligible, disqualifications

    def filter_eligible_drivers(
        self,
        drivers: List[DriverState],
        shift: OpenShift,
    ) -> List[Candidate]:
        """
        Filter list of drivers to eligible candidates.

        Args:
            drivers: List of driver states
            shift: The open shift to fill

        Returns:
            List of Candidate objects (eligible and ineligible)
        """
        candidates = []

        for driver in drivers:
            if not driver.is_active:
                continue

            is_eligible, disqualifications = self.check_eligibility(driver, shift)

            # Calculate hours after potential assignment
            hours_after = driver.hours_worked_this_week + shift.duration_hours

            candidate = Candidate(
                driver_id=driver.driver_id,
                driver_name=driver.driver_name,
                is_eligible=is_eligible,
                disqualifications=disqualifications,
                current_weekly_hours=driver.hours_worked_this_week,
                hours_after_assignment=hours_after,
                fairness_score=driver.hours_gap,
            )

            candidates.append(candidate)

        eligible_count = sum(1 for c in candidates if c.is_eligible)
        logger.info(
            f"Eligibility check: {eligible_count}/{len(candidates)} drivers eligible "
            f"for shift {shift.id} on {shift.shift_date}"
        )

        return candidates

    # =========================================================================
    # INDIVIDUAL CONSTRAINT CHECKS
    # =========================================================================

    def _check_absence(
        self,
        driver: DriverState,
        shift_date: date,
    ) -> Optional[Disqualification]:
        """Check if driver is absent on the shift date."""
        absence_type = driver.is_absent_on(shift_date)
        if absence_type:
            return Disqualification(
                reason=DisqualificationReason.ABSENT,
                details=f"Driver is {absence_type.value} on {shift_date}",
                severity=1,  # Hard block
            )
        return None

    def _check_already_assigned(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Optional[Disqualification]:
        """Check if driver is already assigned to a conflicting shift."""
        for existing_shift in driver.shifts_today:
            if existing_shift.shift_date != shift.shift_date:
                continue

            # Check for time overlap
            if self._times_overlap(
                existing_shift.shift_start, existing_shift.shift_end,
                shift.shift_start, shift.shift_end,
            ):
                return Disqualification(
                    reason=DisqualificationReason.ALREADY_ASSIGNED,
                    details=f"Already assigned to shift {existing_shift.id} ({existing_shift.shift_start}-{existing_shift.shift_end})",
                    severity=1,
                )
        return None

    def _check_rest_constraint(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Optional[Disqualification]:
        """Check 11-hour rest constraint between shifts."""
        if not driver.last_shift_end:
            return None

        # Calculate shift start datetime
        shift_start_dt = datetime.combine(shift.shift_date, shift.shift_start)

        # Rest time available
        rest_available = shift_start_dt - driver.last_shift_end
        rest_hours = rest_available.total_seconds() / 3600

        if rest_hours < self.rest_hours:
            return Disqualification(
                reason=DisqualificationReason.INSUFFICIENT_REST,
                details=f"Only {rest_hours:.1f}h rest available (minimum {self.rest_hours}h required)",
                severity=1,
            )
        return None

    def _check_max_tours(
        self,
        driver: DriverState,
        shift_date: date,
    ) -> Optional[Disqualification]:
        """Check maximum tours per day constraint."""
        tours_today = len([s for s in driver.shifts_today if s.shift_date == shift_date])

        if tours_today >= self.max_tours_per_day:
            return Disqualification(
                reason=DisqualificationReason.MAX_DAILY_TOURS,
                details=f"Already has {tours_today} shifts on {shift_date} (max {self.max_tours_per_day})",
                severity=1,
            )
        return None

    def _check_weekly_hours(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Optional[Disqualification]:
        """Check weekly hours hard limit."""
        # Use driver's max or global max (whichever is lower)
        max_hours = min(driver.max_weekly_hours, self.max_weekly_hours)
        hours_after = driver.hours_worked_this_week + shift.duration_hours

        if hours_after > max_hours:
            return Disqualification(
                reason=DisqualificationReason.WEEKLY_HOURS_EXCEEDED,
                details=f"Would have {hours_after:.1f}h this week (max {max_hours:.1f}h)",
                severity=1,
            )
        return None

    def _check_skills(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Optional[Disqualification]:
        """Check if driver has required skills."""
        if not shift.required_skills:
            return None

        missing_skills = [s for s in shift.required_skills if s not in driver.skills]

        if missing_skills:
            return Disqualification(
                reason=DisqualificationReason.SKILL_MISMATCH,
                details=f"Missing skills: {', '.join(missing_skills)}",
                severity=1,
            )
        return None

    def _check_zone(
        self,
        driver: DriverState,
        shift: OpenShift,
    ) -> Optional[Disqualification]:
        """Check if driver works in the shift's zone."""
        if not shift.zone:
            return None

        if not driver.home_zones:
            # No zone restrictions for this driver
            return None

        if shift.zone not in driver.home_zones:
            return Disqualification(
                reason=DisqualificationReason.ZONE_MISMATCH,
                details=f"Shift zone '{shift.zone}' not in driver's zones: {driver.home_zones}",
                severity=1,
            )
        return None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _times_overlap(
        self,
        start1: time, end1: time,
        start2: time, end2: time,
    ) -> bool:
        """Check if two time ranges overlap."""
        # Convert to minutes for easier comparison
        def to_minutes(t: time) -> int:
            return t.hour * 60 + t.minute

        s1, e1 = to_minutes(start1), to_minutes(end1)
        s2, e2 = to_minutes(start2), to_minutes(end2)

        # Handle overnight shifts
        if e1 < s1:
            e1 += 24 * 60
        if e2 < s2:
            e2 += 24 * 60

        # Check overlap
        return not (e1 <= s2 or e2 <= s1)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def check_driver_eligible(
    driver: DriverState,
    shift: OpenShift,
    rest_hours: int = DEFAULT_REST_HOURS,
    max_tours_per_day: int = DEFAULT_MAX_TOURS_PER_DAY,
    max_weekly_hours: float = DEFAULT_MAX_WEEKLY_HOURS,
) -> Tuple[bool, List[Disqualification]]:
    """
    Convenience function to check single driver eligibility.

    Args:
        driver: Driver state
        shift: Open shift
        rest_hours: Minimum rest between shifts
        max_tours_per_day: Maximum shifts per day
        max_weekly_hours: Weekly hours hard limit

    Returns:
        Tuple of (is_eligible, disqualifications)
    """
    checker = EligibilityChecker(
        rest_hours=rest_hours,
        max_tours_per_day=max_tours_per_day,
        max_weekly_hours=max_weekly_hours,
    )
    return checker.check_eligibility(driver, shift)
