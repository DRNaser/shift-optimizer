# =============================================================================
# SOLVEREIGN Routing Pack - Route Auditor
# =============================================================================
# Post-solve audit checks for route quality validation.
#
# Audit Checks:
# 1. COVERAGE - Every stop assigned exactly once (or has unassigned reason)
# 2. TIME_WINDOW - Hard TW violations = FAIL, soft = WARN
# 3. SHIFT_FEASIBILITY - Route start/end within vehicle shift
# 4. SKILLS_COMPLIANCE - Required skills satisfied
# 5. OVERLAP - No stop assigned to multiple vehicles
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set, Any

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class AuditCheckName(str, Enum):
    """Names for audit checks (stable API contract)."""
    COVERAGE = "COVERAGE"
    TIME_WINDOW = "TIME_WINDOW"
    SHIFT_FEASIBILITY = "SHIFT_FEASIBILITY"
    SKILLS_COMPLIANCE = "SKILLS_COMPLIANCE"
    OVERLAP = "OVERLAP"


class AuditStatus(str, Enum):
    """Audit check status."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AuditViolation:
    """Single audit violation."""
    entity_type: str  # "stop", "vehicle", "route"
    entity_id: str
    message: str
    severity: str  # "error", "warning", "info"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class AuditCheck:
    """Result of a single audit check."""
    name: AuditCheckName
    status: AuditStatus
    violation_count: int
    violations: List[AuditViolation] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "violation_count": self.violation_count,
            "violations": [v.to_dict() for v in self.violations],
            "details": self.details,
        }


@dataclass
class AuditResult:
    """Complete audit result for a plan."""
    plan_id: str
    all_passed: bool
    checks_run: int
    checks_passed: int
    checks_warned: int
    checks_failed: int
    results: Dict[AuditCheckName, AuditCheck] = field(default_factory=dict)
    audited_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "all_passed": self.all_passed,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_warned": self.checks_warned,
            "checks_failed": self.checks_failed,
            "results": {k.value: v.to_dict() for k, v in self.results.items()},
            "audited_at": self.audited_at.isoformat(),
        }


# =============================================================================
# INPUT DATA CLASSES (for type hints)
# =============================================================================

@dataclass
class AuditStop:
    """Stop data for auditing."""
    id: str
    tw_start: datetime
    tw_end: datetime
    tw_is_hard: bool
    required_skills: List[str]
    requires_two_person: bool


@dataclass
class AuditVehicle:
    """Vehicle data for auditing."""
    id: str
    shift_start_at: datetime
    shift_end_at: datetime
    skills: List[str]
    team_size: int


@dataclass
class AuditAssignment:
    """Assignment data for auditing."""
    stop_id: str
    vehicle_id: str
    arrival_at: datetime
    departure_at: datetime
    sequence_index: int


@dataclass
class AuditUnassigned:
    """Unassigned stop data for auditing."""
    stop_id: str
    reason_code: str
    reason_details: Optional[str] = None


# =============================================================================
# ROUTE AUDITOR
# =============================================================================

class RouteAuditor:
    """
    Post-solve route quality auditor.

    Runs 5 mandatory checks:
    1. COVERAGE - Every stop assigned exactly once
    2. TIME_WINDOW - Arrival within time windows
    3. SHIFT_FEASIBILITY - Route within vehicle shifts
    4. SKILLS_COMPLIANCE - Skills and 2-person requirements met
    5. OVERLAP - No duplicate assignments

    Usage:
        auditor = RouteAuditor()
        result = auditor.audit(
            plan_id="plan-123",
            stops=stops,
            vehicles=vehicles,
            assignments=assignments,
            unassigned=unassigned
        )

        if not result.all_passed:
            for check_name, check in result.results.items():
                if check.status == AuditStatus.FAIL:
                    print(f"FAIL: {check_name}")
                    for v in check.violations:
                        print(f"  - {v.message}")
    """

    def __init__(
        self,
        hard_tw_tolerance_min: int = 0,
        soft_tw_tolerance_min: int = 15,
        shift_tolerance_min: int = 5,
    ):
        """
        Initialize auditor with tolerances.

        Args:
            hard_tw_tolerance_min: Grace period for hard TW (0 = strict)
            soft_tw_tolerance_min: Grace period for soft TW warnings
            shift_tolerance_min: Grace period for shift boundary checks
        """
        self.hard_tw_tolerance_min = hard_tw_tolerance_min
        self.soft_tw_tolerance_min = soft_tw_tolerance_min
        self.shift_tolerance_min = shift_tolerance_min

    def audit(
        self,
        plan_id: str,
        stops: List[AuditStop],
        vehicles: List[AuditVehicle],
        assignments: List[AuditAssignment],
        unassigned: List[AuditUnassigned],
    ) -> AuditResult:
        """
        Run all audit checks on a plan.

        Args:
            plan_id: The plan being audited
            stops: All stops in the scenario
            vehicles: All vehicles in the scenario
            assignments: All stop assignments
            unassigned: All unassigned stops with reasons

        Returns:
            AuditResult with all check results
        """
        # Build lookup maps
        stops_by_id = {s.id: s for s in stops}
        vehicles_by_id = {v.id: v for v in vehicles}
        assignments_by_stop = {a.stop_id: a for a in assignments}
        unassigned_by_stop = {u.stop_id: u for u in unassigned}

        # Run all checks
        checks: Dict[AuditCheckName, AuditCheck] = {}

        checks[AuditCheckName.COVERAGE] = self._check_coverage(
            stops, assignments_by_stop, unassigned_by_stop
        )

        checks[AuditCheckName.TIME_WINDOW] = self._check_time_windows(
            stops_by_id, assignments
        )

        checks[AuditCheckName.SHIFT_FEASIBILITY] = self._check_shift_feasibility(
            vehicles_by_id, assignments
        )

        checks[AuditCheckName.SKILLS_COMPLIANCE] = self._check_skills_compliance(
            stops_by_id, vehicles_by_id, assignments
        )

        checks[AuditCheckName.OVERLAP] = self._check_overlap(assignments)

        # Compute summary
        checks_passed = sum(1 for c in checks.values() if c.status == AuditStatus.PASS)
        checks_warned = sum(1 for c in checks.values() if c.status == AuditStatus.WARN)
        checks_failed = sum(1 for c in checks.values() if c.status == AuditStatus.FAIL)

        all_passed = checks_failed == 0

        return AuditResult(
            plan_id=plan_id,
            all_passed=all_passed,
            checks_run=len(checks),
            checks_passed=checks_passed,
            checks_warned=checks_warned,
            checks_failed=checks_failed,
            results=checks,
        )

    # =========================================================================
    # CHECK 1: COVERAGE
    # =========================================================================

    def _check_coverage(
        self,
        stops: List[AuditStop],
        assignments_by_stop: Dict[str, AuditAssignment],
        unassigned_by_stop: Dict[str, AuditUnassigned],
    ) -> AuditCheck:
        """
        Check that every stop is either assigned or has an unassigned reason.

        FAIL if:
        - Stop is neither assigned nor has unassigned reason
        - Stop is both assigned AND in unassigned list
        """
        violations: List[AuditViolation] = []
        assigned_count = 0
        unassigned_count = 0
        missing_count = 0
        duplicate_count = 0

        for stop in stops:
            is_assigned = stop.id in assignments_by_stop
            is_unassigned = stop.id in unassigned_by_stop

            if is_assigned and is_unassigned:
                # Duplicate - both assigned and unassigned
                violations.append(AuditViolation(
                    entity_type="stop",
                    entity_id=stop.id,
                    message=f"Stop {stop.id} is both assigned and marked unassigned",
                    severity="error",
                    details={
                        "vehicle_id": assignments_by_stop[stop.id].vehicle_id,
                        "unassigned_reason": unassigned_by_stop[stop.id].reason_code,
                    }
                ))
                duplicate_count += 1

            elif is_assigned:
                assigned_count += 1

            elif is_unassigned:
                unassigned_count += 1

            else:
                # Missing - neither assigned nor unassigned
                violations.append(AuditViolation(
                    entity_type="stop",
                    entity_id=stop.id,
                    message=f"Stop {stop.id} is neither assigned nor has unassigned reason",
                    severity="error",
                ))
                missing_count += 1

        # Determine status
        if violations:
            status = AuditStatus.FAIL
        elif unassigned_count > 0:
            status = AuditStatus.WARN  # All accounted for, but some unassigned
        else:
            status = AuditStatus.PASS

        return AuditCheck(
            name=AuditCheckName.COVERAGE,
            status=status,
            violation_count=len(violations),
            violations=violations,
            details={
                "total_stops": len(stops),
                "assigned_count": assigned_count,
                "unassigned_count": unassigned_count,
                "missing_count": missing_count,
                "duplicate_count": duplicate_count,
                "coverage_percentage": round(
                    assigned_count / len(stops) * 100, 2
                ) if stops else 0.0,
            }
        )

    # =========================================================================
    # CHECK 2: TIME WINDOW
    # =========================================================================

    def _check_time_windows(
        self,
        stops_by_id: Dict[str, AuditStop],
        assignments: List[AuditAssignment],
    ) -> AuditCheck:
        """
        Check time window compliance.

        FAIL if: Hard TW violated (arrival outside tw_start..tw_end)
        WARN if: Soft TW violated or arrival close to boundary
        """
        violations: List[AuditViolation] = []
        hard_violations = 0
        soft_violations = 0
        on_time_count = 0

        for assignment in assignments:
            stop = stops_by_id.get(assignment.stop_id)
            if not stop:
                continue

            arrival = assignment.arrival_at

            # Check if arrival is within time window
            early_minutes = 0
            late_minutes = 0

            if arrival < stop.tw_start:
                early_minutes = int((stop.tw_start - arrival).total_seconds() / 60)

            if arrival > stop.tw_end:
                late_minutes = int((arrival - stop.tw_end).total_seconds() / 60)

            if stop.tw_is_hard:
                # Hard time window
                tolerance = timedelta(minutes=self.hard_tw_tolerance_min)

                if arrival < stop.tw_start - tolerance:
                    violations.append(AuditViolation(
                        entity_type="stop",
                        entity_id=stop.id,
                        message=f"Stop {stop.id}: arrival {early_minutes}min early (hard TW)",
                        severity="error",
                        details={
                            "arrival_at": arrival.isoformat(),
                            "tw_start": stop.tw_start.isoformat(),
                            "tw_end": stop.tw_end.isoformat(),
                            "early_minutes": early_minutes,
                            "tw_type": "hard",
                        }
                    ))
                    hard_violations += 1

                elif arrival > stop.tw_end + tolerance:
                    violations.append(AuditViolation(
                        entity_type="stop",
                        entity_id=stop.id,
                        message=f"Stop {stop.id}: arrival {late_minutes}min late (hard TW)",
                        severity="error",
                        details={
                            "arrival_at": arrival.isoformat(),
                            "tw_start": stop.tw_start.isoformat(),
                            "tw_end": stop.tw_end.isoformat(),
                            "late_minutes": late_minutes,
                            "tw_type": "hard",
                        }
                    ))
                    hard_violations += 1

                else:
                    on_time_count += 1

            else:
                # Soft time window
                tolerance = timedelta(minutes=self.soft_tw_tolerance_min)

                if arrival < stop.tw_start - tolerance:
                    violations.append(AuditViolation(
                        entity_type="stop",
                        entity_id=stop.id,
                        message=f"Stop {stop.id}: arrival {early_minutes}min early (soft TW)",
                        severity="warning",
                        details={
                            "arrival_at": arrival.isoformat(),
                            "tw_start": stop.tw_start.isoformat(),
                            "tw_end": stop.tw_end.isoformat(),
                            "early_minutes": early_minutes,
                            "tw_type": "soft",
                        }
                    ))
                    soft_violations += 1

                elif arrival > stop.tw_end + tolerance:
                    violations.append(AuditViolation(
                        entity_type="stop",
                        entity_id=stop.id,
                        message=f"Stop {stop.id}: arrival {late_minutes}min late (soft TW)",
                        severity="warning",
                        details={
                            "arrival_at": arrival.isoformat(),
                            "tw_start": stop.tw_start.isoformat(),
                            "tw_end": stop.tw_end.isoformat(),
                            "late_minutes": late_minutes,
                            "tw_type": "soft",
                        }
                    ))
                    soft_violations += 1

                else:
                    on_time_count += 1

        # Determine status
        if hard_violations > 0:
            status = AuditStatus.FAIL
        elif soft_violations > 0:
            status = AuditStatus.WARN
        else:
            status = AuditStatus.PASS

        total_checked = len(assignments)
        return AuditCheck(
            name=AuditCheckName.TIME_WINDOW,
            status=status,
            violation_count=hard_violations + soft_violations,
            violations=violations,
            details={
                "total_checked": total_checked,
                "on_time_count": on_time_count,
                "hard_violations": hard_violations,
                "soft_violations": soft_violations,
                "on_time_percentage": round(
                    on_time_count / total_checked * 100, 2
                ) if total_checked else 0.0,
            }
        )

    # =========================================================================
    # CHECK 3: SHIFT FEASIBILITY
    # =========================================================================

    def _check_shift_feasibility(
        self,
        vehicles_by_id: Dict[str, AuditVehicle],
        assignments: List[AuditAssignment],
    ) -> AuditCheck:
        """
        Check that routes fit within vehicle shifts.

        FAIL if:
        - First stop arrival before shift start
        - Last stop departure after shift end
        """
        violations: List[AuditViolation] = []

        # Group assignments by vehicle
        assignments_by_vehicle: Dict[str, List[AuditAssignment]] = {}
        for a in assignments:
            if a.vehicle_id not in assignments_by_vehicle:
                assignments_by_vehicle[a.vehicle_id] = []
            assignments_by_vehicle[a.vehicle_id].append(a)

        # Sort each vehicle's assignments by sequence
        for vehicle_id in assignments_by_vehicle:
            assignments_by_vehicle[vehicle_id].sort(key=lambda x: x.sequence_index)

        vehicles_checked = 0
        vehicles_ok = 0

        for vehicle_id, vehicle_assignments in assignments_by_vehicle.items():
            vehicle = vehicles_by_id.get(vehicle_id)
            if not vehicle or not vehicle_assignments:
                continue

            vehicles_checked += 1

            first_assignment = vehicle_assignments[0]
            last_assignment = vehicle_assignments[-1]

            tolerance = timedelta(minutes=self.shift_tolerance_min)
            vehicle_ok = True

            # Check shift start
            if first_assignment.arrival_at < vehicle.shift_start_at - tolerance:
                early_minutes = int(
                    (vehicle.shift_start_at - first_assignment.arrival_at).total_seconds() / 60
                )
                violations.append(AuditViolation(
                    entity_type="vehicle",
                    entity_id=vehicle_id,
                    message=f"Vehicle {vehicle_id}: route starts {early_minutes}min before shift",
                    severity="error",
                    details={
                        "first_arrival": first_assignment.arrival_at.isoformat(),
                        "shift_start": vehicle.shift_start_at.isoformat(),
                        "early_minutes": early_minutes,
                    }
                ))
                vehicle_ok = False

            # Check shift end
            if last_assignment.departure_at > vehicle.shift_end_at + tolerance:
                late_minutes = int(
                    (last_assignment.departure_at - vehicle.shift_end_at).total_seconds() / 60
                )
                violations.append(AuditViolation(
                    entity_type="vehicle",
                    entity_id=vehicle_id,
                    message=f"Vehicle {vehicle_id}: route ends {late_minutes}min after shift",
                    severity="error",
                    details={
                        "last_departure": last_assignment.departure_at.isoformat(),
                        "shift_end": vehicle.shift_end_at.isoformat(),
                        "late_minutes": late_minutes,
                    }
                ))
                vehicle_ok = False

            if vehicle_ok:
                vehicles_ok += 1

        # Determine status
        if violations:
            status = AuditStatus.FAIL
        else:
            status = AuditStatus.PASS

        return AuditCheck(
            name=AuditCheckName.SHIFT_FEASIBILITY,
            status=status,
            violation_count=len(violations),
            violations=violations,
            details={
                "vehicles_checked": vehicles_checked,
                "vehicles_ok": vehicles_ok,
                "vehicles_with_violations": vehicles_checked - vehicles_ok,
            }
        )

    # =========================================================================
    # CHECK 4: SKILLS COMPLIANCE
    # =========================================================================

    def _check_skills_compliance(
        self,
        stops_by_id: Dict[str, AuditStop],
        vehicles_by_id: Dict[str, AuditVehicle],
        assignments: List[AuditAssignment],
    ) -> AuditCheck:
        """
        Check skills and 2-person requirements.

        FAIL if:
        - Stop requires skill that vehicle doesn't have
        - Stop requires 2-person but vehicle has team_size < 2
        """
        violations: List[AuditViolation] = []
        skill_violations = 0
        two_person_violations = 0
        compliant_count = 0

        for assignment in assignments:
            stop = stops_by_id.get(assignment.stop_id)
            vehicle = vehicles_by_id.get(assignment.vehicle_id)

            if not stop or not vehicle:
                continue

            is_compliant = True

            # Check skills
            if stop.required_skills:
                vehicle_skills = set(vehicle.skills)
                required_skills = set(stop.required_skills)
                missing_skills = required_skills - vehicle_skills

                if missing_skills:
                    violations.append(AuditViolation(
                        entity_type="stop",
                        entity_id=stop.id,
                        message=f"Stop {stop.id}: vehicle {vehicle.id} missing skills {missing_skills}",
                        severity="error",
                        details={
                            "vehicle_id": vehicle.id,
                            "required_skills": list(required_skills),
                            "vehicle_skills": list(vehicle_skills),
                            "missing_skills": list(missing_skills),
                        }
                    ))
                    skill_violations += 1
                    is_compliant = False

            # Check 2-person requirement
            if stop.requires_two_person and vehicle.team_size < 2:
                violations.append(AuditViolation(
                    entity_type="stop",
                    entity_id=stop.id,
                    message=f"Stop {stop.id}: requires 2-person but vehicle {vehicle.id} has team_size={vehicle.team_size}",
                    severity="error",
                    details={
                        "vehicle_id": vehicle.id,
                        "requires_two_person": True,
                        "vehicle_team_size": vehicle.team_size,
                    }
                ))
                two_person_violations += 1
                is_compliant = False

            if is_compliant:
                compliant_count += 1

        # Determine status
        if violations:
            status = AuditStatus.FAIL
        else:
            status = AuditStatus.PASS

        total_checked = len(assignments)
        return AuditCheck(
            name=AuditCheckName.SKILLS_COMPLIANCE,
            status=status,
            violation_count=len(violations),
            violations=violations,
            details={
                "total_checked": total_checked,
                "compliant_count": compliant_count,
                "skill_violations": skill_violations,
                "two_person_violations": two_person_violations,
            }
        )

    # =========================================================================
    # CHECK 5: OVERLAP
    # =========================================================================

    def _check_overlap(
        self,
        assignments: List[AuditAssignment],
    ) -> AuditCheck:
        """
        Check for duplicate stop assignments.

        FAIL if: Same stop assigned to multiple vehicles
        """
        violations: List[AuditViolation] = []

        # Track which vehicles each stop is assigned to
        stop_vehicles: Dict[str, List[str]] = {}

        for assignment in assignments:
            if assignment.stop_id not in stop_vehicles:
                stop_vehicles[assignment.stop_id] = []
            stop_vehicles[assignment.stop_id].append(assignment.vehicle_id)

        # Find duplicates
        duplicate_count = 0
        for stop_id, vehicle_ids in stop_vehicles.items():
            if len(vehicle_ids) > 1:
                violations.append(AuditViolation(
                    entity_type="stop",
                    entity_id=stop_id,
                    message=f"Stop {stop_id} assigned to multiple vehicles: {vehicle_ids}",
                    severity="error",
                    details={
                        "vehicle_ids": vehicle_ids,
                        "assignment_count": len(vehicle_ids),
                    }
                ))
                duplicate_count += 1

        # Determine status
        if violations:
            status = AuditStatus.FAIL
        else:
            status = AuditStatus.PASS

        return AuditCheck(
            name=AuditCheckName.OVERLAP,
            status=status,
            violation_count=len(violations),
            violations=violations,
            details={
                "total_stops": len(stop_vehicles),
                "unique_assignments": len(stop_vehicles) - duplicate_count,
                "duplicate_assignments": duplicate_count,
            }
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def audit_plan(
    plan_id: str,
    stops: List[Dict],
    vehicles: List[Dict],
    assignments: List[Dict],
    unassigned: List[Dict],
    **kwargs,
) -> AuditResult:
    """
    Convenience function to audit a plan from dict data.

    Converts dicts to dataclasses and runs audit.
    """
    # Convert dicts to dataclasses
    audit_stops = [
        AuditStop(
            id=s["id"],
            tw_start=s["tw_start"] if isinstance(s["tw_start"], datetime) else datetime.fromisoformat(s["tw_start"]),
            tw_end=s["tw_end"] if isinstance(s["tw_end"], datetime) else datetime.fromisoformat(s["tw_end"]),
            tw_is_hard=s.get("tw_is_hard", True),
            required_skills=s.get("required_skills", []),
            requires_two_person=s.get("requires_two_person", False),
        )
        for s in stops
    ]

    audit_vehicles = [
        AuditVehicle(
            id=v["id"],
            shift_start_at=v["shift_start_at"] if isinstance(v["shift_start_at"], datetime) else datetime.fromisoformat(v["shift_start_at"]),
            shift_end_at=v["shift_end_at"] if isinstance(v["shift_end_at"], datetime) else datetime.fromisoformat(v["shift_end_at"]),
            skills=v.get("skills", []),
            team_size=v.get("team_size", 1),
        )
        for v in vehicles
    ]

    audit_assignments = [
        AuditAssignment(
            stop_id=a["stop_id"],
            vehicle_id=a["vehicle_id"],
            arrival_at=a["arrival_at"] if isinstance(a["arrival_at"], datetime) else datetime.fromisoformat(a["arrival_at"]),
            departure_at=a["departure_at"] if isinstance(a["departure_at"], datetime) else datetime.fromisoformat(a["departure_at"]),
            sequence_index=a.get("sequence_index", 0),
        )
        for a in assignments
    ]

    audit_unassigned = [
        AuditUnassigned(
            stop_id=u["stop_id"],
            reason_code=u["reason_code"],
            reason_details=u.get("reason_details"),
        )
        for u in unassigned
    ]

    auditor = RouteAuditor(**kwargs)
    return auditor.audit(
        plan_id=plan_id,
        stops=audit_stops,
        vehicles=audit_vehicles,
        assignments=audit_assignments,
        unassigned=audit_unassigned,
    )
