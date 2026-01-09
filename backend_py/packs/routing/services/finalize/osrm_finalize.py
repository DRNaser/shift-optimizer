# =============================================================================
# SOLVEREIGN Routing Pack - OSRM Finalize Stage
# =============================================================================
# Main orchestrator for post-solve validation using OSRM.
#
# Workflow:
# 1. Query OSRM for each route's consecutive legs
# 2. Compute drift metrics (matrix vs OSRM)
# 3. Run TW forward simulation
# 4. Track fallback usage
# 5. Return verdict: OK / WARN / BLOCK
# =============================================================================

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Literal

from .drift_detector import DriftDetector, DriftReport
from .tw_validator import TWValidator, TWValidationResult, RouteSchedule
from .fallback_tracker import FallbackTracker, FallbackReport


logger = logging.getLogger(__name__)


Verdict = Literal["OK", "WARN", "BLOCK"]


@dataclass
class FinalizeConfig:
    """
    Configuration for OSRM finalize stage.

    Contains timeout budgets and verdict thresholds.
    """
    # Timeout budgets
    timeout_per_route_seconds: float = 10.0
    max_total_seconds: float = 60.0

    # Default service time for TW validation
    default_service_time_seconds: int = 300  # 5 minutes

    # Drift thresholds for OK verdict
    ok_p95_ratio_max: float = 1.15      # 15% drift max
    ok_tw_violations_max: int = 0        # No TW violations
    ok_timeout_rate_max: float = 0.02    # 2% timeout rate max

    # Drift thresholds for WARN verdict
    warn_p95_ratio_max: float = 1.30     # 30% drift max
    warn_tw_violations_max: int = 3       # 3 TW violations max
    warn_timeout_rate_max: float = 0.10   # 10% timeout rate max


@dataclass
class RouteToFinalize:
    """
    Route data for finalize validation.

    Contains all information needed to validate a single route.
    """
    route_id: str
    vehicle_id: str
    departure_time: datetime
    stop_ids: List[str]
    stop_coordinates: Dict[str, Tuple[float, float]]  # stop_id -> (lat, lng)
    time_windows: Dict[str, Tuple[datetime, datetime]]  # stop_id -> (start, end)
    service_times: Dict[str, int]  # stop_id -> seconds
    matrix_leg_times: List[int]  # Matrix times for each leg


@dataclass
class FinalizeResult:
    """
    Complete result of OSRM finalize stage.

    Contains verdict, reports, and artifacts.
    """
    success: bool
    verdict: Verdict
    verdict_reasons: List[str] = field(default_factory=list)

    # Reports
    drift_report: Optional[DriftReport] = None
    tw_validation: Optional[TWValidationResult] = None
    fallback_report: Optional[FallbackReport] = None

    # Timing
    finalize_time_seconds: float = 0.0
    routes_processed: int = 0
    routes_timed_out: int = 0

    # Computed ETAs (for evidence)
    route_etas: Dict[str, List[datetime]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "verdict": self.verdict,
            "verdict_reasons": self.verdict_reasons,
            "timing": {
                "finalize_time_seconds": round(self.finalize_time_seconds, 3),
                "routes_processed": self.routes_processed,
                "routes_timed_out": self.routes_timed_out,
            },
            "drift_report": self.drift_report.to_dict() if self.drift_report else None,
            "tw_validation": self.tw_validation.to_dict() if self.tw_validation else None,
            "fallback_report": self.fallback_report.to_dict() if self.fallback_report else None,
        }


class OSRMFinalizeStage:
    """
    OSRM Finalize Stage orchestrator.

    Validates solved plans by comparing matrix times with OSRM live times.
    Detects drift and time window violations.

    Usage:
        stage = OSRMFinalizeStage(config, osrm_provider)
        result = stage.finalize(plan_id, routes, matrix_version)
    """

    def __init__(
        self,
        config: FinalizeConfig,
        osrm_provider: Any,  # OSRMProvider from travel_time
    ):
        """
        Initialize finalize stage.

        Args:
            config: Finalize configuration
            osrm_provider: OSRM provider for live travel times
        """
        self.config = config
        self.osrm_provider = osrm_provider

        # Internal components
        self._drift_detector = DriftDetector()
        self._tw_validator = TWValidator(
            default_service_time=config.default_service_time_seconds
        )
        self._fallback_tracker = FallbackTracker()

    def finalize(
        self,
        plan_id: str,
        routes: List[RouteToFinalize],
        matrix_version: str,
    ) -> FinalizeResult:
        """
        Run finalize validation on solved plan.

        Args:
            plan_id: ID of the solved plan
            routes: Routes to validate
            matrix_version: Version of static matrix used in solve

        Returns:
            FinalizeResult with verdict and reports
        """
        start_time = time.perf_counter()
        self._fallback_tracker.reset()

        logger.info(
            f"Starting OSRM finalize for plan {plan_id} "
            f"with {len(routes)} routes"
        )

        # Get OSRM map hash
        try:
            osrm_status = self.osrm_provider.get_osrm_status()
            osrm_map_hash = osrm_status.map_hash
        except Exception as e:
            logger.error(f"Failed to get OSRM status: {e}")
            osrm_map_hash = "unknown"

        # Process routes with time budget
        all_matrix_times: List[Dict[str, Any]] = []
        all_osrm_times: List[Dict[str, Any]] = []
        route_schedules: List[RouteSchedule] = []
        osrm_travel_times: Dict[str, Dict[str, int]] = {}
        route_etas: Dict[str, List[datetime]] = {}
        routes_processed = 0
        routes_timed_out = 0

        remaining_budget = self.config.max_total_seconds
        total_legs = sum(len(r.stop_ids) - 1 for r in routes if len(r.stop_ids) > 1)
        self._fallback_tracker.set_total_legs(total_legs)

        for route in routes:
            if remaining_budget <= 0:
                logger.warning(
                    f"Time budget exhausted after {routes_processed} routes"
                )
                break

            route_start = time.perf_counter()

            # Get consecutive times from OSRM
            waypoints = [
                route.stop_coordinates[stop_id]
                for stop_id in route.stop_ids
                if stop_id in route.stop_coordinates
            ]

            if len(waypoints) < 2:
                routes_processed += 1
                continue

            try:
                osrm_result = self.osrm_provider.get_consecutive_times(
                    waypoints=waypoints,
                    timeout_override=min(
                        self.config.timeout_per_route_seconds,
                        remaining_budget
                    )
                )

                if osrm_result.timed_out:
                    routes_timed_out += 1
                    # Record timeout fallback events
                    for i in range(len(route.stop_ids) - 1):
                        self._fallback_tracker.record_timeout(
                            from_stop_id=route.stop_ids[i],
                            to_stop_id=route.stop_ids[i + 1],
                            duration_computed=0,
                            distance_computed=0,
                            request_time_ms=(time.perf_counter() - route_start) * 1000,
                        )
                elif osrm_result.used_fallback:
                    # Record fallback events
                    for i, (dur, dist) in enumerate(
                        zip(osrm_result.leg_durations, osrm_result.leg_distances)
                    ):
                        self._fallback_tracker.record_event(
                            from_stop_id=route.stop_ids[i],
                            to_stop_id=route.stop_ids[i + 1],
                            fallback_level="HAVERSINE",
                            reason="OSRM_ERROR",
                            duration_computed=dur,
                            distance_computed=dist,
                        )

                # Collect times for drift analysis
                for i in range(len(route.stop_ids) - 1):
                    from_stop = route.stop_ids[i]
                    to_stop = route.stop_ids[i + 1]

                    # Matrix time
                    matrix_time = (
                        route.matrix_leg_times[i]
                        if i < len(route.matrix_leg_times)
                        else 0
                    )
                    all_matrix_times.append({
                        'from_stop_id': from_stop,
                        'to_stop_id': to_stop,
                        'duration_seconds': matrix_time,
                    })

                    # OSRM time
                    osrm_time = (
                        osrm_result.leg_durations[i]
                        if i < len(osrm_result.leg_durations)
                        else 0
                    )
                    all_osrm_times.append({
                        'from_stop_id': from_stop,
                        'to_stop_id': to_stop,
                        'duration_seconds': osrm_time,
                        'timed_out': osrm_result.timed_out,
                        'used_fallback': osrm_result.used_fallback,
                    })

                    # Build travel times dict for TW validation
                    if from_stop not in osrm_travel_times:
                        osrm_travel_times[from_stop] = {}
                    osrm_travel_times[from_stop][to_stop] = osrm_time

                # Build route schedule for TW validation
                route_schedules.append(RouteSchedule(
                    route_id=route.route_id,
                    vehicle_id=route.vehicle_id,
                    departure_time=route.departure_time,
                    stops=route.stop_ids,
                    time_windows=route.time_windows,
                    service_times=route.service_times,
                ))

                # Compute ETAs for this route
                if not osrm_result.timed_out:
                    etas = self._compute_route_etas(
                        departure_time=route.departure_time,
                        stop_ids=route.stop_ids,
                        leg_durations=osrm_result.leg_durations,
                        service_times=route.service_times,
                        time_windows=route.time_windows,
                    )
                    route_etas[route.route_id] = etas

            except Exception as e:
                logger.error(f"Error processing route {route.route_id}: {e}")
                routes_timed_out += 1

            routes_processed += 1
            route_elapsed = time.perf_counter() - route_start
            remaining_budget -= route_elapsed

        # Compute drift report
        drift_report = self._drift_detector.compute_drift(
            plan_id=plan_id,
            matrix_version=matrix_version,
            osrm_map_hash=osrm_map_hash,
            matrix_times=all_matrix_times,
            osrm_times=all_osrm_times,
        )

        # Validate time windows
        tw_validation = self._tw_validator.validate(
            plan_id=plan_id,
            routes=route_schedules,
            travel_times=osrm_travel_times,
        )

        # Get fallback report
        fallback_report = self._fallback_tracker.get_report(plan_id)

        # Compute verdict
        verdict, reasons = self._compute_verdict(
            drift_report=drift_report,
            tw_validation=tw_validation,
            fallback_report=fallback_report,
        )

        finalize_time = time.perf_counter() - start_time

        logger.info(
            f"Finalize complete for plan {plan_id}: "
            f"verdict={verdict}, time={finalize_time:.2f}s, "
            f"routes={routes_processed}, timed_out={routes_timed_out}"
        )

        return FinalizeResult(
            success=True,
            verdict=verdict,
            verdict_reasons=reasons,
            drift_report=drift_report,
            tw_validation=tw_validation,
            fallback_report=fallback_report,
            finalize_time_seconds=finalize_time,
            routes_processed=routes_processed,
            routes_timed_out=routes_timed_out,
            route_etas=route_etas,
        )

    def _compute_verdict(
        self,
        drift_report: DriftReport,
        tw_validation: TWValidationResult,
        fallback_report: FallbackReport,
    ) -> Tuple[Verdict, List[str]]:
        """
        Compute verdict based on drift, TW violations, and timeouts.

        Returns:
            (verdict, reasons) tuple
        """
        reasons: List[str] = []

        # Check for BLOCK conditions
        if drift_report.p95_ratio > self.config.warn_p95_ratio_max:
            reasons.append(
                f"P95 drift ratio {drift_report.p95_ratio:.2f} exceeds BLOCK threshold "
                f"{self.config.warn_p95_ratio_max}"
            )

        if tw_validation.violations_count > self.config.warn_tw_violations_max:
            reasons.append(
                f"TW violations {tw_validation.violations_count} exceed BLOCK threshold "
                f"{self.config.warn_tw_violations_max}"
            )

        if fallback_report.timeout_rate > self.config.warn_timeout_rate_max:
            reasons.append(
                f"Timeout rate {fallback_report.timeout_rate:.2%} exceeds BLOCK threshold "
                f"{self.config.warn_timeout_rate_max:.2%}"
            )

        if reasons:
            return "BLOCK", reasons

        # Check for WARN conditions
        warn_reasons: List[str] = []

        if drift_report.p95_ratio > self.config.ok_p95_ratio_max:
            warn_reasons.append(
                f"P95 drift ratio {drift_report.p95_ratio:.2f} exceeds OK threshold "
                f"{self.config.ok_p95_ratio_max}"
            )

        if tw_validation.violations_count > self.config.ok_tw_violations_max:
            warn_reasons.append(
                f"TW violations {tw_validation.violations_count} exceed OK threshold "
                f"{self.config.ok_tw_violations_max}"
            )

        if fallback_report.timeout_rate > self.config.ok_timeout_rate_max:
            warn_reasons.append(
                f"Timeout rate {fallback_report.timeout_rate:.2%} exceeds OK threshold "
                f"{self.config.ok_timeout_rate_max:.2%}"
            )

        if warn_reasons:
            return "WARN", warn_reasons

        return "OK", ["All checks passed"]

    def _compute_route_etas(
        self,
        departure_time: datetime,
        stop_ids: List[str],
        leg_durations: List[int],
        service_times: Dict[str, int],
        time_windows: Dict[str, Tuple[datetime, datetime]],
    ) -> List[datetime]:
        """
        Compute ETAs for each stop using OSRM times.

        Uses same forward simulation as TW validator.
        """
        etas: List[datetime] = []
        current_time = departure_time

        for i, stop_id in enumerate(stop_ids):
            # Travel time from previous stop
            if i > 0 and i - 1 < len(leg_durations):
                travel_time = leg_durations[i - 1]
                arrival_time = current_time + timedelta(seconds=travel_time)
            else:
                arrival_time = current_time

            etas.append(arrival_time)

            # Compute departure time for next stop
            tw = time_windows.get(stop_id)
            if tw:
                start_service = max(arrival_time, tw[0])
            else:
                start_service = arrival_time

            service_time = service_times.get(stop_id, self.config.default_service_time_seconds)
            current_time = start_service + timedelta(seconds=service_time)

        return etas
