# =============================================================================
# SOLVEREIGN Routing Pack - Fallback Tracker
# =============================================================================
# Tracks fallback usage during OSRM finalize for evidence and monitoring.
#
# Records when and why fallback (Haversine) was used instead of OSRM.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal
from collections import Counter


FallbackLevel = Literal["HAVERSINE", "H3", "ZONE", "GEOHASH", "PLZ"]
FallbackReason = Literal[
    "OSRM_TIMEOUT",
    "OSRM_ERROR",
    "OSRM_UNAVAILABLE",
    "MATRIX_MISS",
    "COORDINATE_INVALID",
    "CIRCUIT_BREAKER_OPEN",
]


@dataclass
class FallbackEvent:
    """
    A single fallback event.

    Records one instance of fallback usage during finalize.
    """
    from_stop_id: str
    to_stop_id: str
    fallback_level: FallbackLevel
    reason: FallbackReason
    occurred_at: datetime
    duration_computed: int      # Fallback-computed duration in seconds
    distance_computed: int      # Fallback-computed distance in meters
    request_time_ms: float = 0.0  # Time spent before fallback

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "from_stop_id": self.from_stop_id,
            "to_stop_id": self.to_stop_id,
            "fallback_level": self.fallback_level,
            "reason": self.reason,
            "occurred_at": self.occurred_at.isoformat(),
            "duration_computed": self.duration_computed,
            "distance_computed": self.distance_computed,
            "request_time_ms": round(self.request_time_ms, 2),
        }


@dataclass
class FallbackReport:
    """
    Complete fallback report for a finalize operation.

    Aggregates all fallback events and provides statistics.
    """
    plan_id: str
    generated_at: datetime

    # Counts
    total_legs: int
    fallback_count: int
    timeout_count: int
    error_count: int

    # By level
    fallback_by_level: Dict[str, int] = field(default_factory=dict)

    # By reason
    fallback_by_reason: Dict[str, int] = field(default_factory=dict)

    # Sample events (not all events to avoid huge reports)
    sample_events: List[FallbackEvent] = field(default_factory=list)

    # Full events (for detailed analysis)
    events: List[FallbackEvent] = field(default_factory=list)

    @property
    def fallback_rate(self) -> float:
        """Rate of legs using fallback (0.0 - 1.0)."""
        if self.total_legs == 0:
            return 0.0
        return self.fallback_count / self.total_legs

    @property
    def timeout_rate(self) -> float:
        """Rate of legs that timed out (0.0 - 1.0)."""
        if self.total_legs == 0:
            return 0.0
        return self.timeout_count / self.total_legs

    @property
    def error_rate(self) -> float:
        """Rate of legs with errors (0.0 - 1.0)."""
        if self.total_legs == 0:
            return 0.0
        return self.error_count / self.total_legs

    @property
    def has_fallbacks(self) -> bool:
        """Whether any fallbacks occurred."""
        return self.fallback_count > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "plan_id": self.plan_id,
            "generated_at": self.generated_at.isoformat(),
            "statistics": {
                "total_legs": self.total_legs,
                "fallback_count": self.fallback_count,
                "timeout_count": self.timeout_count,
                "error_count": self.error_count,
                "fallback_rate": round(self.fallback_rate, 4),
                "timeout_rate": round(self.timeout_rate, 4),
                "error_rate": round(self.error_rate, 4),
            },
            "fallback_by_level": self.fallback_by_level,
            "fallback_by_reason": self.fallback_by_reason,
            "sample_events": [e.to_dict() for e in self.sample_events],
        }


class FallbackTracker:
    """
    Tracks fallback events during OSRM finalize.

    Collects fallback events and generates reports for evidence.
    """

    def __init__(self, max_sample_events: int = 20):
        """
        Initialize fallback tracker.

        Args:
            max_sample_events: Max events to include in sample (for report size)
        """
        self.max_sample_events = max_sample_events
        self._events: List[FallbackEvent] = []
        self._total_legs = 0

    def record_event(
        self,
        from_stop_id: str,
        to_stop_id: str,
        fallback_level: FallbackLevel,
        reason: FallbackReason,
        duration_computed: int,
        distance_computed: int,
        request_time_ms: float = 0.0,
    ) -> None:
        """
        Record a fallback event.

        Args:
            from_stop_id: Origin stop ID
            to_stop_id: Destination stop ID
            fallback_level: Level of fallback used
            reason: Why fallback was needed
            duration_computed: Duration from fallback method
            distance_computed: Distance from fallback method
            request_time_ms: Time spent before fallback
        """
        event = FallbackEvent(
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            fallback_level=fallback_level,
            reason=reason,
            occurred_at=datetime.now(),
            duration_computed=duration_computed,
            distance_computed=distance_computed,
            request_time_ms=request_time_ms,
        )
        self._events.append(event)

    def record_timeout(
        self,
        from_stop_id: str,
        to_stop_id: str,
        duration_computed: int,
        distance_computed: int,
        request_time_ms: float,
    ) -> None:
        """Record a timeout event with Haversine fallback."""
        self.record_event(
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            fallback_level="HAVERSINE",
            reason="OSRM_TIMEOUT",
            duration_computed=duration_computed,
            distance_computed=distance_computed,
            request_time_ms=request_time_ms,
        )

    def record_error(
        self,
        from_stop_id: str,
        to_stop_id: str,
        duration_computed: int,
        distance_computed: int,
    ) -> None:
        """Record an error event with Haversine fallback."""
        self.record_event(
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            fallback_level="HAVERSINE",
            reason="OSRM_ERROR",
            duration_computed=duration_computed,
            distance_computed=distance_computed,
        )

    def record_matrix_miss(
        self,
        from_stop_id: str,
        to_stop_id: str,
        duration_computed: int,
        distance_computed: int,
    ) -> None:
        """Record a matrix miss with fallback."""
        self.record_event(
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            fallback_level="HAVERSINE",
            reason="MATRIX_MISS",
            duration_computed=duration_computed,
            distance_computed=distance_computed,
        )

    def set_total_legs(self, total: int) -> None:
        """Set total number of legs being processed."""
        self._total_legs = total

    def get_report(self, plan_id: str) -> FallbackReport:
        """
        Generate fallback report.

        Args:
            plan_id: ID of the plan being finalized

        Returns:
            FallbackReport with all statistics and sample events
        """
        # Count by level
        level_counts: Counter = Counter()
        for event in self._events:
            level_counts[event.fallback_level] += 1

        # Count by reason
        reason_counts: Counter = Counter()
        for event in self._events:
            reason_counts[event.reason] += 1

        # Timeout and error counts
        timeout_count = sum(
            1 for e in self._events if e.reason == "OSRM_TIMEOUT"
        )
        error_count = sum(
            1 for e in self._events
            if e.reason in ("OSRM_ERROR", "OSRM_UNAVAILABLE", "CIRCUIT_BREAKER_OPEN")
        )

        # Sample events
        sample_events = self._events[:self.max_sample_events]

        return FallbackReport(
            plan_id=plan_id,
            generated_at=datetime.now(),
            total_legs=self._total_legs,
            fallback_count=len(self._events),
            timeout_count=timeout_count,
            error_count=error_count,
            fallback_by_level=dict(level_counts),
            fallback_by_reason=dict(reason_counts),
            sample_events=sample_events,
            events=self._events,
        )

    def reset(self) -> None:
        """Reset tracker for new finalize operation."""
        self._events = []
        self._total_legs = 0

    @property
    def event_count(self) -> int:
        """Number of fallback events recorded."""
        return len(self._events)

    @property
    def has_events(self) -> bool:
        """Whether any fallback events were recorded."""
        return len(self._events) > 0
