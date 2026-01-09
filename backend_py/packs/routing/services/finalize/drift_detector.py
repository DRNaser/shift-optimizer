# =============================================================================
# SOLVEREIGN Routing Pack - Drift Detector
# =============================================================================
# Computes drift metrics between static matrix times and OSRM live times.
#
# Used by OSRMFinalizeStage to detect discrepancies that could invalidate
# a solved plan.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import statistics


@dataclass
class LegDrift:
    """
    Drift information for a single route leg.

    Compares matrix time vs OSRM time for one leg of a route.
    """
    from_stop_id: str
    to_stop_id: str
    t_matrix_seconds: int       # Time from static matrix
    t_osrm_seconds: int         # Time from OSRM
    ratio: float                # t_osrm / max(1, t_matrix)
    delta_seconds: int          # t_osrm - t_matrix

    @property
    def drift_percent(self) -> float:
        """Drift as percentage (100 = double the time)."""
        return (self.ratio - 1.0) * 100

    @property
    def is_underestimate(self) -> bool:
        """Matrix underestimated travel time (OSRM > matrix)."""
        return self.ratio > 1.0

    @property
    def is_overestimate(self) -> bool:
        """Matrix overestimated travel time (OSRM < matrix)."""
        return self.ratio < 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "from_stop_id": self.from_stop_id,
            "to_stop_id": self.to_stop_id,
            "t_matrix_seconds": self.t_matrix_seconds,
            "t_osrm_seconds": self.t_osrm_seconds,
            "ratio": round(self.ratio, 4),
            "delta_seconds": self.delta_seconds,
            "drift_percent": round(self.drift_percent, 2),
        }


@dataclass
class DriftReport:
    """
    Complete drift report for a solved plan.

    Contains per-leg drift data and aggregate statistics.
    Used for drift gate evaluation and evidence tracking.
    """
    plan_id: str
    matrix_version: str
    osrm_map_hash: str
    computed_at: datetime

    # Aggregate statistics
    total_legs: int
    legs_with_osrm: int         # Legs that got OSRM response
    legs_with_timeout: int      # Legs where OSRM timed out
    legs_with_fallback: int     # Legs using fallback

    # Ratio statistics
    mean_ratio: float
    median_ratio: float
    p95_ratio: float
    max_ratio: float
    min_ratio: float
    std_ratio: float

    # Per-leg data
    legs: List[LegDrift] = field(default_factory=list)

    # Worst offenders (top N by ratio)
    worst_underestimates: List[LegDrift] = field(default_factory=list)
    worst_overestimates: List[LegDrift] = field(default_factory=list)

    @property
    def timeout_rate(self) -> float:
        """Rate of timeouts (0.0 - 1.0)."""
        if self.total_legs == 0:
            return 0.0
        return self.legs_with_timeout / self.total_legs

    @property
    def fallback_rate(self) -> float:
        """Rate of fallback usage (0.0 - 1.0)."""
        if self.total_legs == 0:
            return 0.0
        return self.legs_with_fallback / self.total_legs

    @property
    def osrm_coverage_rate(self) -> float:
        """Rate of legs with successful OSRM response."""
        if self.total_legs == 0:
            return 0.0
        return self.legs_with_osrm / self.total_legs

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "plan_id": self.plan_id,
            "matrix_version": self.matrix_version,
            "osrm_map_hash": self.osrm_map_hash,
            "computed_at": self.computed_at.isoformat(),
            "aggregations": {
                "total_legs": self.total_legs,
                "legs_with_osrm": self.legs_with_osrm,
                "legs_with_timeout": self.legs_with_timeout,
                "legs_with_fallback": self.legs_with_fallback,
                "timeout_rate": round(self.timeout_rate, 4),
                "fallback_rate": round(self.fallback_rate, 4),
                "osrm_coverage_rate": round(self.osrm_coverage_rate, 4),
            },
            "statistics": {
                "mean_ratio": round(self.mean_ratio, 4),
                "median_ratio": round(self.median_ratio, 4),
                "p95_ratio": round(self.p95_ratio, 4),
                "max_ratio": round(self.max_ratio, 4),
                "min_ratio": round(self.min_ratio, 4),
                "std_ratio": round(self.std_ratio, 4),
            },
            "worst_underestimates": [
                leg.to_dict() for leg in self.worst_underestimates
            ],
            "worst_overestimates": [
                leg.to_dict() for leg in self.worst_overestimates
            ],
            "legs": [leg.to_dict() for leg in self.legs],
        }


class DriftDetector:
    """
    Computes drift metrics between static matrix and OSRM times.

    Used by OSRMFinalizeStage to detect discrepancies in travel times.
    """

    def __init__(self, top_n_worst: int = 5):
        """
        Initialize drift detector.

        Args:
            top_n_worst: Number of worst offenders to track
        """
        self.top_n_worst = top_n_worst

    def compute_drift(
        self,
        plan_id: str,
        matrix_version: str,
        osrm_map_hash: str,
        matrix_times: List[Dict[str, Any]],
        osrm_times: List[Dict[str, Any]],
    ) -> DriftReport:
        """
        Compute drift between matrix times and OSRM times.

        Args:
            plan_id: ID of the solved plan
            matrix_version: Version of static matrix used
            osrm_map_hash: Hash of OSRM map used
            matrix_times: List of {from_stop_id, to_stop_id, duration_seconds}
            osrm_times: List of {from_stop_id, to_stop_id, duration_seconds,
                                 timed_out, used_fallback}

        Returns:
            DriftReport with per-leg drift and aggregate statistics
        """
        # Build lookup for OSRM times
        osrm_lookup: Dict[str, Dict[str, Any]] = {}
        for entry in osrm_times:
            key = f"{entry['from_stop_id']}|{entry['to_stop_id']}"
            osrm_lookup[key] = entry

        # Compute per-leg drift
        legs: List[LegDrift] = []
        ratios: List[float] = []
        legs_with_osrm = 0
        legs_with_timeout = 0
        legs_with_fallback = 0

        for matrix_entry in matrix_times:
            from_stop = matrix_entry['from_stop_id']
            to_stop = matrix_entry['to_stop_id']
            t_matrix = matrix_entry['duration_seconds']

            key = f"{from_stop}|{to_stop}"
            osrm_entry = osrm_lookup.get(key)

            if osrm_entry is None:
                # No OSRM data for this leg
                continue

            if osrm_entry.get('timed_out', False):
                legs_with_timeout += 1
                continue

            if osrm_entry.get('used_fallback', False):
                legs_with_fallback += 1

            t_osrm = osrm_entry['duration_seconds']
            legs_with_osrm += 1

            # Compute ratio (avoid division by zero)
            ratio = t_osrm / max(1, t_matrix)
            delta = t_osrm - t_matrix

            leg = LegDrift(
                from_stop_id=from_stop,
                to_stop_id=to_stop,
                t_matrix_seconds=t_matrix,
                t_osrm_seconds=t_osrm,
                ratio=ratio,
                delta_seconds=delta,
            )
            legs.append(leg)
            ratios.append(ratio)

        # Compute aggregate statistics
        total_legs = len(matrix_times)

        if ratios:
            mean_ratio = statistics.mean(ratios)
            median_ratio = statistics.median(ratios)
            std_ratio = statistics.stdev(ratios) if len(ratios) > 1 else 0.0
            sorted_ratios = sorted(ratios)
            p95_idx = int(len(sorted_ratios) * 0.95)
            p95_ratio = sorted_ratios[min(p95_idx, len(sorted_ratios) - 1)]
            max_ratio = max(ratios)
            min_ratio = min(ratios)
        else:
            mean_ratio = 1.0
            median_ratio = 1.0
            std_ratio = 0.0
            p95_ratio = 1.0
            max_ratio = 1.0
            min_ratio = 1.0

        # Find worst offenders
        sorted_by_ratio = sorted(legs, key=lambda x: x.ratio, reverse=True)
        worst_underestimates = [
            leg for leg in sorted_by_ratio[:self.top_n_worst]
            if leg.ratio > 1.0
        ]

        sorted_by_ratio_asc = sorted(legs, key=lambda x: x.ratio)
        worst_overestimates = [
            leg for leg in sorted_by_ratio_asc[:self.top_n_worst]
            if leg.ratio < 1.0
        ]

        return DriftReport(
            plan_id=plan_id,
            matrix_version=matrix_version,
            osrm_map_hash=osrm_map_hash,
            computed_at=datetime.now(),
            total_legs=total_legs,
            legs_with_osrm=legs_with_osrm,
            legs_with_timeout=legs_with_timeout,
            legs_with_fallback=legs_with_fallback,
            mean_ratio=mean_ratio,
            median_ratio=median_ratio,
            p95_ratio=p95_ratio,
            max_ratio=max_ratio,
            min_ratio=min_ratio,
            std_ratio=std_ratio,
            legs=legs,
            worst_underestimates=worst_underestimates,
            worst_overestimates=worst_overestimates,
        )

    def compute_drift_from_consecutive(
        self,
        plan_id: str,
        matrix_version: str,
        osrm_map_hash: str,
        route_id: str,
        stop_ids: List[str],
        matrix_leg_times: List[int],
        osrm_leg_times: List[int],
        timed_out: bool = False,
        used_fallback: bool = False,
    ) -> DriftReport:
        """
        Compute drift from consecutive times (simpler interface).

        Used when route stop sequence is already known.

        Args:
            plan_id: ID of the solved plan
            matrix_version: Version of static matrix
            osrm_map_hash: Hash of OSRM map
            route_id: Route identifier
            stop_ids: List of stop IDs in route order
            matrix_leg_times: Matrix time for each leg (N-1 values)
            osrm_leg_times: OSRM time for each leg (N-1 values)
            timed_out: Whether OSRM timed out
            used_fallback: Whether fallback was used

        Returns:
            DriftReport for this route
        """
        if len(stop_ids) < 2:
            return DriftReport(
                plan_id=plan_id,
                matrix_version=matrix_version,
                osrm_map_hash=osrm_map_hash,
                computed_at=datetime.now(),
                total_legs=0,
                legs_with_osrm=0,
                legs_with_timeout=0,
                legs_with_fallback=0,
                mean_ratio=1.0,
                median_ratio=1.0,
                p95_ratio=1.0,
                max_ratio=1.0,
                min_ratio=1.0,
                std_ratio=0.0,
                legs=[],
                worst_underestimates=[],
                worst_overestimates=[],
            )

        # Build matrix_times and osrm_times for compute_drift
        matrix_times = []
        osrm_times = []

        for i in range(len(stop_ids) - 1):
            from_stop = stop_ids[i]
            to_stop = stop_ids[i + 1]

            matrix_times.append({
                'from_stop_id': from_stop,
                'to_stop_id': to_stop,
                'duration_seconds': matrix_leg_times[i] if i < len(matrix_leg_times) else 0,
            })

            osrm_times.append({
                'from_stop_id': from_stop,
                'to_stop_id': to_stop,
                'duration_seconds': osrm_leg_times[i] if i < len(osrm_leg_times) else 0,
                'timed_out': timed_out,
                'used_fallback': used_fallback,
            })

        return self.compute_drift(
            plan_id=plan_id,
            matrix_version=matrix_version,
            osrm_map_hash=osrm_map_hash,
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )
