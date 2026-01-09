# =============================================================================
# SOLVEREIGN Routing Pack - Time Window Validator
# =============================================================================
# Forward simulation to detect time window violations using OSRM times.
#
# Simulates route execution: arrival_i = depart_{i-1} + travel_time
# Compares against time windows to detect violations.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


@dataclass
class TWViolation:
    """
    A single time window violation.

    Represents a stop where the simulated arrival time exceeds
    the time window end.
    """
    stop_id: str
    vehicle_id: str
    route_position: int         # Position in route (0-indexed)
    arrival_at: datetime        # Simulated arrival time
    tw_start: datetime          # Time window start
    tw_end: datetime            # Time window end
    violation_seconds: int      # Seconds late (arrival - tw_end)

    @property
    def violation_minutes(self) -> float:
        """Violation in minutes."""
        return self.violation_seconds / 60.0

    @property
    def is_severe(self) -> bool:
        """Severe violation (more than 15 minutes late)."""
        return self.violation_seconds > 900

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "stop_id": self.stop_id,
            "vehicle_id": self.vehicle_id,
            "route_position": self.route_position,
            "arrival_at": self.arrival_at.isoformat(),
            "tw_start": self.tw_start.isoformat(),
            "tw_end": self.tw_end.isoformat(),
            "violation_seconds": self.violation_seconds,
            "violation_minutes": round(self.violation_minutes, 1),
            "is_severe": self.is_severe,
        }


@dataclass
class TWValidationResult:
    """
    Complete time window validation result.

    Contains all violations found during forward simulation.
    """
    plan_id: str
    validated_at: datetime

    # Statistics
    total_stops: int
    total_routes: int
    routes_validated: int
    violations_count: int
    severe_violations_count: int

    # Violations by severity
    violations: List[TWViolation] = field(default_factory=list)

    # Routes with violations
    routes_with_violations: List[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Whether any violations were found."""
        return self.violations_count > 0

    @property
    def has_severe_violations(self) -> bool:
        """Whether any severe violations were found."""
        return self.severe_violations_count > 0

    @property
    def violation_rate(self) -> float:
        """Rate of stops with violations."""
        if self.total_stops == 0:
            return 0.0
        return self.violations_count / self.total_stops

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "plan_id": self.plan_id,
            "validated_at": self.validated_at.isoformat(),
            "statistics": {
                "total_stops": self.total_stops,
                "total_routes": self.total_routes,
                "routes_validated": self.routes_validated,
                "violations_count": self.violations_count,
                "severe_violations_count": self.severe_violations_count,
                "violation_rate": round(self.violation_rate, 4),
            },
            "routes_with_violations": self.routes_with_violations,
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass
class RouteSchedule:
    """
    Route schedule for TW validation.

    Contains vehicle, stops, time windows, and service times.
    """
    route_id: str
    vehicle_id: str
    departure_time: datetime    # When vehicle leaves depot
    stops: List[str]            # Stop IDs in order
    time_windows: Dict[str, Tuple[datetime, datetime]]  # stop_id -> (start, end)
    service_times: Dict[str, int]  # stop_id -> service time in seconds


class TWValidator:
    """
    Time window validator using forward simulation.

    Simulates route execution with OSRM travel times to detect
    time window violations that wouldn't be caught by matrix times.
    """

    def __init__(self, default_service_time: int = 300):
        """
        Initialize TW validator.

        Args:
            default_service_time: Default service time in seconds (5 min)
        """
        self.default_service_time = default_service_time

    def validate(
        self,
        plan_id: str,
        routes: List[RouteSchedule],
        travel_times: Dict[str, Dict[str, int]],
    ) -> TWValidationResult:
        """
        Validate time windows for all routes.

        Forward simulation: For each stop i:
            arrival_i = depart_{i-1} + travel_time[i-1][i]
            depart_i = max(arrival_i, tw_start_i) + service_time_i

        Args:
            plan_id: ID of the plan being validated
            routes: List of route schedules
            travel_times: Dict[from_stop][to_stop] -> duration_seconds

        Returns:
            TWValidationResult with violations
        """
        all_violations: List[TWViolation] = []
        routes_with_violations: List[str] = []
        total_stops = 0

        for route in routes:
            violations = self._validate_route(route, travel_times)
            total_stops += len(route.stops)

            if violations:
                all_violations.extend(violations)
                routes_with_violations.append(route.route_id)

        severe_count = sum(1 for v in all_violations if v.is_severe)

        return TWValidationResult(
            plan_id=plan_id,
            validated_at=datetime.now(),
            total_stops=total_stops,
            total_routes=len(routes),
            routes_validated=len(routes),
            violations_count=len(all_violations),
            severe_violations_count=severe_count,
            violations=all_violations,
            routes_with_violations=routes_with_violations,
        )

    def _validate_route(
        self,
        route: RouteSchedule,
        travel_times: Dict[str, Dict[str, int]],
    ) -> List[TWViolation]:
        """
        Validate time windows for a single route.

        Args:
            route: Route schedule
            travel_times: Dict[from_stop][to_stop] -> duration_seconds

        Returns:
            List of violations for this route
        """
        violations: List[TWViolation] = []

        if not route.stops:
            return violations

        # Start from depot departure
        current_time = route.departure_time
        prev_stop: Optional[str] = None

        for position, stop_id in enumerate(route.stops):
            # Get travel time from previous stop (or depot)
            if prev_stop is not None:
                travel_time = self._get_travel_time(
                    travel_times, prev_stop, stop_id
                )
                arrival_time = current_time + timedelta(seconds=travel_time)
            else:
                arrival_time = current_time

            # Check time window
            tw = route.time_windows.get(stop_id)
            if tw:
                tw_start, tw_end = tw

                if arrival_time > tw_end:
                    # Violation: arrived after TW end
                    violation_seconds = int(
                        (arrival_time - tw_end).total_seconds()
                    )
                    violations.append(TWViolation(
                        stop_id=stop_id,
                        vehicle_id=route.vehicle_id,
                        route_position=position,
                        arrival_at=arrival_time,
                        tw_start=tw_start,
                        tw_end=tw_end,
                        violation_seconds=violation_seconds,
                    ))

                # Departure is max(arrival, tw_start) + service_time
                service_time = route.service_times.get(
                    stop_id, self.default_service_time
                )
                start_service = max(arrival_time, tw_start)
                current_time = start_service + timedelta(seconds=service_time)
            else:
                # No time window - just add service time
                service_time = route.service_times.get(
                    stop_id, self.default_service_time
                )
                current_time = arrival_time + timedelta(seconds=service_time)

            prev_stop = stop_id

        return violations

    def _get_travel_time(
        self,
        travel_times: Dict[str, Dict[str, int]],
        from_stop: str,
        to_stop: str,
    ) -> int:
        """Get travel time between two stops."""
        if from_stop in travel_times and to_stop in travel_times[from_stop]:
            return travel_times[from_stop][to_stop]
        return 0

    def validate_consecutive(
        self,
        plan_id: str,
        route_id: str,
        vehicle_id: str,
        departure_time: datetime,
        stop_ids: List[str],
        osrm_leg_times: List[int],
        time_windows: Dict[str, Tuple[datetime, datetime]],
        service_times: Optional[Dict[str, int]] = None,
    ) -> TWValidationResult:
        """
        Validate time windows using consecutive leg times (simpler interface).

        Args:
            plan_id: Plan ID
            route_id: Route ID
            vehicle_id: Vehicle ID
            departure_time: When vehicle departs depot
            stop_ids: Stop IDs in route order
            osrm_leg_times: OSRM travel times for each leg (N-1 values)
            time_windows: stop_id -> (tw_start, tw_end)
            service_times: stop_id -> service time in seconds

        Returns:
            TWValidationResult for this route
        """
        # Build travel_times dict from consecutive times
        travel_times: Dict[str, Dict[str, int]] = {}

        for i in range(len(stop_ids) - 1):
            from_stop = stop_ids[i]
            to_stop = stop_ids[i + 1]

            if from_stop not in travel_times:
                travel_times[from_stop] = {}
            travel_times[from_stop][to_stop] = osrm_leg_times[i] if i < len(osrm_leg_times) else 0

        # Create route schedule
        route = RouteSchedule(
            route_id=route_id,
            vehicle_id=vehicle_id,
            departure_time=departure_time,
            stops=stop_ids,
            time_windows=time_windows,
            service_times=service_times or {},
        )

        return self.validate(plan_id, [route], travel_times)
