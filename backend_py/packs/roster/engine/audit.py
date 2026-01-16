"""
SOLVEREIGN V3 Audit Framework
==============================

Automated validation checks for plan versions.
Milestone 5 (M5) partial implementation.
"""

from datetime import datetime, time, timedelta

from .config import config
from .db import (
    create_audit_log,
    get_assignments,
    get_tours_normalized,
    get_plan_version,
)
from .models import AuditCheckName, AuditStatus


class AuditCheck:
    """Base class for audit checks."""

    def __init__(self, plan_version_id: int):
        self.plan_version_id = plan_version_id
        self.check_name = None
        self.status = AuditStatus.PASS
        self.count = 0
        self.details = {}

    def run(self) -> tuple[AuditStatus, int, dict]:
        """
        Run the audit check.
        Returns (status, violation_count, details_dict).
        """
        raise NotImplementedError

    def save(self):
        """Save audit result to database."""
        create_audit_log(
            plan_version_id=self.plan_version_id,
            check_name=self.check_name.value,
            status=self.status.value,
            count=self.count,
            details_json=self.details
        )


class CoverageCheck(AuditCheck):
    """Check that every tour is assigned exactly once."""

    def __init__(self, plan_version_id: int):
        super().__init__(plan_version_id)
        self.check_name = AuditCheckName.COVERAGE

    def run(self) -> tuple[AuditStatus, int, dict]:
        """Verify 100% coverage (every tour assigned exactly once)."""
        # Get plan version to find forecast_version_id
        plan = get_plan_version(self.plan_version_id)
        if not plan:
            self.status = AuditStatus.FAIL
            self.count = 1
            self.details = {"error": "Plan version not found"}
            return self.status, self.count, self.details

        # Get all tours for this forecast
        tours = get_tours_normalized(plan["forecast_version_id"])
        assignments = get_assignments(self.plan_version_id)

        # Count assignments per tour (accounting for template expansion)
        tour_assignment_count = {}
        for assignment in assignments:
            tour_id = assignment["tour_id"]
            tour_assignment_count[tour_id] = tour_assignment_count.get(tour_id, 0) + 1

        # Check coverage
        violations = []
        for tour in tours:
            tour_id = tour["id"]
            expected_count = tour["count"]  # Template expansion
            actual_count = tour_assignment_count.get(tour_id, 0)

            if actual_count != expected_count:
                violations.append({
                    "tour_id": tour_id,
                    "day": tour["day"],
                    "start": str(tour["start_ts"]),
                    "expected_assignments": expected_count,
                    "actual_assignments": actual_count
                })

        if violations:
            self.status = AuditStatus.FAIL
            self.count = len(violations)
            self.details = {
                "violations": violations,
                "total_tours": len(tours),
                "total_assignments": len(assignments)
            }
        else:
            self.status = AuditStatus.PASS
            self.count = 0
            self.details = {
                "total_tours": len(tours),
                "total_assignments": len(assignments),
                "coverage": 1.0
            }

        return self.status, self.count, self.details


class OverlapCheck(AuditCheck):
    """Check that no driver has overlapping tour assignments."""

    def __init__(self, plan_version_id: int):
        super().__init__(plan_version_id)
        self.check_name = AuditCheckName.OVERLAP

    def run(self) -> tuple[AuditStatus, int, dict]:
        """Verify no driver works overlapping tours."""
        plan = get_plan_version(self.plan_version_id)
        if not plan:
            self.status = AuditStatus.FAIL
            self.count = 1
            self.details = {"error": "Plan version not found"}
            return self.status, self.count, self.details

        tours = {t["id"]: t for t in get_tours_normalized(plan["forecast_version_id"])}
        assignments = get_assignments(self.plan_version_id)

        # Group assignments by driver
        driver_assignments = {}
        for assignment in assignments:
            driver_id = assignment["driver_id"]
            if driver_id not in driver_assignments:
                driver_assignments[driver_id] = []
            driver_assignments[driver_id].append(assignment)

        # Check for overlaps
        violations = []
        for driver_id, driver_tours in driver_assignments.items():
            # Sort by day and start time
            driver_tours_sorted = sorted(
                driver_tours,
                key=lambda a: (a["day"], tours[a["tour_id"]]["start_ts"])
            )

            # Check consecutive tours for overlap
            for i in range(len(driver_tours_sorted) - 1):
                curr_assignment = driver_tours_sorted[i]
                next_assignment = driver_tours_sorted[i + 1]

                curr_tour = tours[curr_assignment["tour_id"]]
                next_tour = tours[next_assignment["tour_id"]]

                # Same day check
                if curr_assignment["day"] == next_assignment["day"]:
                    if self._tours_overlap(curr_tour, next_tour):
                        violations.append({
                            "driver_id": driver_id,
                            "day": curr_assignment["day"],
                            "tour1": {
                                "id": curr_tour["id"],
                                "start": str(curr_tour["start_ts"]),
                                "end": str(curr_tour["end_ts"])
                            },
                            "tour2": {
                                "id": next_tour["id"],
                                "start": str(next_tour["start_ts"]),
                                "end": str(next_tour["end_ts"])
                            }
                        })

        if violations:
            self.status = AuditStatus.FAIL
            self.count = len(violations)
            self.details = {"violations": violations}
        else:
            self.status = AuditStatus.PASS
            self.count = 0
            self.details = {"drivers_checked": len(driver_assignments)}

        return self.status, self.count, self.details

    def _tours_overlap(self, tour1: dict, tour2: dict) -> bool:
        """Check if two tours overlap in time."""
        start1 = tour1["start_ts"]
        end1 = tour1["end_ts"]
        start2 = tour2["start_ts"]
        end2 = tour2["end_ts"]

        # Convert to comparable format
        if isinstance(start1, str):
            start1 = datetime.strptime(start1, "%H:%M:%S").time()
        if isinstance(end1, str):
            end1 = datetime.strptime(end1, "%H:%M:%S").time()
        if isinstance(start2, str):
            start2 = datetime.strptime(start2, "%H:%M:%S").time()
        if isinstance(end2, str):
            end2 = datetime.strptime(end2, "%H:%M:%S").time()

        # Check overlap: tour1.end > tour2.start AND tour1.start < tour2.end
        return end1 > start2 and start1 < end2


class RestCheck(AuditCheck):
    """Check that drivers have ≥11h rest between consecutive blocks."""

    def __init__(self, plan_version_id: int):
        super().__init__(plan_version_id)
        self.check_name = AuditCheckName.REST

    def run(self) -> tuple[AuditStatus, int, dict]:
        """Verify ≥11h rest between consecutive day assignments."""
        plan = get_plan_version(self.plan_version_id)
        if not plan:
            self.status = AuditStatus.FAIL
            self.count = 1
            self.details = {"error": "Plan version not found"}
            return self.status, self.count, self.details

        tours = {t["id"]: t for t in get_tours_normalized(plan["forecast_version_id"])}
        assignments = get_assignments(self.plan_version_id)

        # Group by driver
        driver_assignments = {}
        for assignment in assignments:
            driver_id = assignment["driver_id"]
            if driver_id not in driver_assignments:
                driver_assignments[driver_id] = []
            driver_assignments[driver_id].append(assignment)

        violations = []
        for driver_id, driver_tours in driver_assignments.items():
            # Sort by day
            driver_tours_sorted = sorted(driver_tours, key=lambda a: a["day"])

            # Check consecutive days
            for i in range(len(driver_tours_sorted) - 1):
                curr_assignment = driver_tours_sorted[i]
                next_assignment = driver_tours_sorted[i + 1]

                # Only check consecutive days
                if next_assignment["day"] == curr_assignment["day"] + 1:
                    curr_block_end = self._get_block_end_time(
                        curr_assignment, tours, driver_tours_sorted
                    )
                    next_block_start = self._get_block_start_time(
                        next_assignment, tours, driver_tours_sorted
                    )

                    rest_minutes = self._calculate_rest_minutes(curr_block_end, next_block_start)

                    if rest_minutes < 660:  # 11 hours = 660 minutes
                        violations.append({
                            "driver_id": driver_id,
                            "day_from": curr_assignment["day"],
                            "day_to": next_assignment["day"],
                            "block_end": str(curr_block_end),
                            "block_start": str(next_block_start),
                            "rest_minutes": rest_minutes,
                            "required_minutes": 660
                        })

        if violations:
            self.status = AuditStatus.FAIL
            self.count = len(violations)
            self.details = {"violations": violations}
        else:
            self.status = AuditStatus.PASS
            self.count = 0
            self.details = {"drivers_checked": len(driver_assignments)}

        return self.status, self.count, self.details

    def _get_block_end_time(self, assignment: dict, tours: dict, all_assignments: list) -> time:
        """Get the end time of a block (latest tour end on that day)."""
        day = assignment["day"]
        block_id = assignment["block_id"]

        # Find all tours in this block
        block_tours = [a for a in all_assignments if a["day"] == day and a["block_id"] == block_id]

        # Get latest end time
        max_end = None
        for a in block_tours:
            tour = tours[a["tour_id"]]
            end_ts = tour["end_ts"]
            if isinstance(end_ts, str):
                end_ts = datetime.strptime(end_ts, "%H:%M:%S").time()

            if max_end is None or end_ts > max_end:
                max_end = end_ts

        return max_end

    def _get_block_start_time(self, assignment: dict, tours: dict, all_assignments: list) -> time:
        """Get the start time of a block (earliest tour start on that day)."""
        day = assignment["day"]
        block_id = assignment["block_id"]

        # Find all tours in this block
        block_tours = [a for a in all_assignments if a["day"] == day and a["block_id"] == block_id]

        # Get earliest start time
        min_start = None
        for a in block_tours:
            tour = tours[a["tour_id"]]
            start_ts = tour["start_ts"]
            if isinstance(start_ts, str):
                start_ts = datetime.strptime(start_ts, "%H:%M:%S").time()

            if min_start is None or start_ts < min_start:
                min_start = start_ts

        return min_start

    def _calculate_rest_minutes(self, end_time: time, start_time: time) -> int:
        """Calculate rest minutes between two times (overnight)."""
        # Convert to datetime for calculation
        day1 = datetime.combine(datetime.today(), end_time)
        day2 = datetime.combine(datetime.today() + timedelta(days=1), start_time)

        rest_delta = day2 - day1
        return int(rest_delta.total_seconds() / 60)


class AuditFramework:
    """
    Run all audit checks for a plan version.
    Milestone 5 (M5) core implementation.
    """

    def __init__(self, plan_version_id: int):
        self.plan_version_id = plan_version_id
        self.checks = []

        # Register checks if enabled
        if config.AUDIT_CHECK_COVERAGE:
            self.checks.append(CoverageCheck(plan_version_id))

        if config.AUDIT_CHECK_OVERLAP:
            self.checks.append(OverlapCheck(plan_version_id))

        if config.AUDIT_CHECK_REST:
            self.checks.append(RestCheck(plan_version_id))

        # TODO: Add SPAN_REGULAR, SPAN_SPLIT, REPRODUCIBILITY, FATIGUE checks

    def run_all_checks(self, save_to_db: bool = True) -> dict:
        """
        Run all enabled audit checks.

        Returns:
            Summary dict with check results
        """
        results = {}
        all_passed = True

        for check in self.checks:
            status, count, details = check.run()

            results[check.check_name.value] = {
                "status": status.value,
                "violation_count": count,
                "details": details
            }

            if status == AuditStatus.FAIL:
                all_passed = False

            if save_to_db:
                check.save()

        summary = {
            "plan_version_id": self.plan_version_id,
            "all_passed": all_passed,
            "checks_run": len(self.checks),
            "checks_passed": sum(1 for r in results.values() if r["status"] == "PASS"),
            "checks_failed": sum(1 for r in results.values() if r["status"] == "FAIL"),
            "results": results
        }

        return summary


# ============================================================================
# Convenience Functions
# ============================================================================

def audit_plan(plan_version_id: int, save_to_db: bool = True) -> dict:
    """
    Run all audit checks for a plan version.

    Usage:
        from packs.roster.engine.audit import audit_plan

        audit_results = audit_plan(plan_version_id=123)
        if audit_results["all_passed"]:
            print("Plan ready for release!")
        else:
            print(f"Failed checks: {audit_results['checks_failed']}")
    """
    framework = AuditFramework(plan_version_id)
    return framework.run_all_checks(save_to_db)


def can_release_plan(plan_version_id: int) -> tuple[bool, list[str]]:
    """
    Check if plan can be released (wrapper around db.can_release).

    Returns:
        (can_release, list_of_blocking_checks)
    """
    from .db import can_release
    return can_release(plan_version_id)
