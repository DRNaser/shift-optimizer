# =============================================================================
# SOLVEREIGN Routing Pack - Coords Quality Gate (STOP-5)
# =============================================================================
# Pilot Gate for coordinate quality validation.
#
# Metrics:
# - %missing_latlng: Orders without lat/lng
# - %resolved_by_h3_zone: Orders with zone/H3 fallback
# - %unresolved: Orders with no location at all
#
# Verdicts:
# - OK: All coords present or resolvable
# - WARN: High fallback rate but all resolvable
# - BLOCK: Unresolved > 0 or missing above threshold
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class CoordsVerdict(str, Enum):
    """Coordinates quality verdict."""
    OK = "OK"
    WARN = "WARN"
    BLOCK = "BLOCK"


class ResolutionMethod(str, Enum):
    """How coords were resolved."""
    LATLNG = "LATLNG"          # Direct lat/lng provided
    H3 = "H3"                  # Resolved via H3 index
    ZONE = "ZONE"              # Resolved via zone/PLZ
    GEOHASH = "GEOHASH"        # Resolved via geohash
    GEOCODED = "GEOCODED"      # Resolved via geocoding
    UNRESOLVED = "UNRESOLVED"  # Could not resolve


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CoordsQualityPolicy:
    """Policy for coords quality gate thresholds."""

    # OK thresholds (all must pass for OK)
    ok_missing_latlng_max: float = 0.00      # 0% missing lat/lng for OK
    ok_fallback_rate_max: float = 0.00       # 0% fallback for OK
    ok_unresolved_max: int = 0               # 0 unresolved for OK

    # WARN thresholds (triggers WARN if exceeded but not BLOCK)
    warn_missing_latlng_max: float = 0.10    # 10% missing lat/lng → WARN
    warn_fallback_rate_max: float = 0.10     # 10% fallback → WARN
    warn_unresolved_max: int = 0             # Any unresolved → BLOCK (not WARN)

    # BLOCK thresholds (triggers BLOCK if exceeded)
    block_missing_latlng_max: float = 0.25   # 25% missing → BLOCK
    block_fallback_rate_max: float = 0.25    # 25% fallback → BLOCK
    block_unresolved_max: int = 0            # ANY unresolved → BLOCK

    # Feature flags
    allow_zone_fallback: bool = True         # Allow zone-based resolution
    allow_h3_fallback: bool = True           # Allow H3-based resolution
    allow_geocoding: bool = False            # Allow geocoding (not for pilot)
    strict_mode: bool = True                 # BLOCK on any unresolved

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok_thresholds": {
                "missing_latlng_max": self.ok_missing_latlng_max,
                "fallback_rate_max": self.ok_fallback_rate_max,
                "unresolved_max": self.ok_unresolved_max,
            },
            "warn_thresholds": {
                "missing_latlng_max": self.warn_missing_latlng_max,
                "fallback_rate_max": self.warn_fallback_rate_max,
                "unresolved_max": self.warn_unresolved_max,
            },
            "block_thresholds": {
                "missing_latlng_max": self.block_missing_latlng_max,
                "fallback_rate_max": self.block_fallback_rate_max,
                "unresolved_max": self.block_unresolved_max,
            },
            "feature_flags": {
                "allow_zone_fallback": self.allow_zone_fallback,
                "allow_h3_fallback": self.allow_h3_fallback,
                "allow_geocoding": self.allow_geocoding,
                "strict_mode": self.strict_mode,
            },
        }


@dataclass
class OrderCoordsStatus:
    """Coords status for a single order."""
    order_id: str
    has_latlng: bool
    has_zone: bool
    has_h3: bool
    resolution_method: ResolutionMethod
    resolved_lat: Optional[float] = None
    resolved_lng: Optional[float] = None
    resolution_notes: str = ""


@dataclass
class CoordsQualityResult:
    """Result of coords quality gate evaluation."""

    verdict: CoordsVerdict
    evaluated_at: datetime = field(default_factory=datetime.now)

    # Metrics
    total_orders: int = 0
    orders_with_latlng: int = 0
    orders_resolved_by_zone: int = 0
    orders_resolved_by_h3: int = 0
    orders_unresolved: int = 0

    # Rates
    missing_latlng_rate: float = 0.0
    fallback_rate: float = 0.0
    unresolved_rate: float = 0.0

    # Details
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unresolved_orders: List[str] = field(default_factory=list)

    # Policy used
    policy: Optional[CoordsQualityPolicy] = None

    @property
    def is_ok(self) -> bool:
        return self.verdict == CoordsVerdict.OK

    @property
    def is_blocked(self) -> bool:
        return self.verdict == CoordsVerdict.BLOCK

    @property
    def allows_osrm_finalize(self) -> bool:
        """Whether OSRM finalize can be used."""
        return self.verdict != CoordsVerdict.BLOCK and self.unresolved_rate == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "metrics": {
                "total_orders": self.total_orders,
                "orders_with_latlng": self.orders_with_latlng,
                "orders_resolved_by_zone": self.orders_resolved_by_zone,
                "orders_resolved_by_h3": self.orders_resolved_by_h3,
                "orders_unresolved": self.orders_unresolved,
            },
            "rates": {
                "missing_latlng_rate": round(self.missing_latlng_rate, 4),
                "fallback_rate": round(self.fallback_rate, 4),
                "unresolved_rate": round(self.unresolved_rate, 4),
            },
            "reasons": self.reasons,
            "warnings": self.warnings,
            "unresolved_orders": self.unresolved_orders[:20],  # Limit
            "unresolved_count": len(self.unresolved_orders),
            "allows_osrm_finalize": self.allows_osrm_finalize,
            "policy": self.policy.to_dict() if self.policy else None,
        }


class CoordsQualityError(Exception):
    """Exception raised when coords quality gate blocks."""

    def __init__(
        self,
        message: str,
        verdict: CoordsVerdict,
        result: CoordsQualityResult,
    ):
        super().__init__(message)
        self.verdict = verdict
        self.result = result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "CoordsQualityError",
            "message": str(self),
            "verdict": self.verdict.value,
            "result": self.result.to_dict(),
        }


# =============================================================================
# COORDS QUALITY GATE
# =============================================================================

class CoordsQualityGate:
    """
    Pilot Gate STOP-5: Coordinates Quality Gate.

    Evaluates coordinate completeness and resolution quality.
    Determines whether OSRM finalize can be used.

    Usage:
        gate = CoordsQualityGate()
        result = gate.evaluate(orders)

        if result.verdict == CoordsVerdict.BLOCK:
            raise CoordsQualityError("Coords gate blocked", result.verdict, result)
        elif result.verdict == CoordsVerdict.WARN:
            logger.warning("Coords gate warned, requires approval")

        if result.allows_osrm_finalize:
            # Run OSRM finalize
        else:
            # Use matrix-only mode
    """

    def __init__(self, policy: Optional[CoordsQualityPolicy] = None):
        """
        Initialize coords quality gate.

        Args:
            policy: Custom policy (or use defaults)
        """
        self.policy = policy or CoordsQualityPolicy()

    def evaluate(
        self,
        orders: List[Dict[str, Any]],
        zone_resolver: Optional[Any] = None,
        h3_resolver: Optional[Any] = None,
    ) -> CoordsQualityResult:
        """
        Evaluate coords quality for a list of orders.

        Args:
            orders: List of order dicts with lat/lng/zone_id/h3_index
            zone_resolver: Optional resolver for zone → coords
            h3_resolver: Optional resolver for H3 → coords

        Returns:
            CoordsQualityResult with verdict and metrics
        """
        result = CoordsQualityResult(
            evaluated_at=datetime.now(),
            verdict=CoordsVerdict.OK,  # Assume OK until proven otherwise
            policy=self.policy,
        )

        if not orders:
            result.verdict = CoordsVerdict.BLOCK
            result.reasons.append("No orders provided")
            return result

        result.total_orders = len(orders)

        # Analyze each order
        orders_with_latlng = 0
        orders_zone = 0
        orders_h3 = 0
        orders_unresolved = 0
        unresolved_list = []

        for order in orders:
            status = self._analyze_order(order, zone_resolver, h3_resolver)

            if status.has_latlng:
                orders_with_latlng += 1
            elif status.resolution_method == ResolutionMethod.ZONE:
                orders_zone += 1
            elif status.resolution_method == ResolutionMethod.H3:
                orders_h3 += 1
            elif status.resolution_method == ResolutionMethod.UNRESOLVED:
                orders_unresolved += 1
                unresolved_list.append(status.order_id)

        # Update metrics
        result.orders_with_latlng = orders_with_latlng
        result.orders_resolved_by_zone = orders_zone
        result.orders_resolved_by_h3 = orders_h3
        result.orders_unresolved = orders_unresolved
        result.unresolved_orders = unresolved_list

        # Calculate rates
        total = result.total_orders
        result.missing_latlng_rate = (total - orders_with_latlng) / total if total > 0 else 0
        result.fallback_rate = (orders_zone + orders_h3) / total if total > 0 else 0
        result.unresolved_rate = orders_unresolved / total if total > 0 else 0

        # Evaluate against policy
        result = self._apply_policy(result)

        return result

    def _analyze_order(
        self,
        order: Dict[str, Any],
        zone_resolver: Optional[Any],
        h3_resolver: Optional[Any],
    ) -> OrderCoordsStatus:
        """Analyze coords status for a single order."""
        order_id = order.get("order_id", "unknown")

        # Check for direct lat/lng
        lat = order.get("lat")
        lng = order.get("lng")
        has_latlng = lat is not None and lng is not None and lat != 0 and lng != 0

        # Check for zone
        zone_id = order.get("zone_id")
        has_zone = bool(zone_id)

        # Check for H3
        h3_index = order.get("h3_index")
        has_h3 = bool(h3_index)

        # Determine resolution method
        if has_latlng:
            return OrderCoordsStatus(
                order_id=order_id,
                has_latlng=True,
                has_zone=has_zone,
                has_h3=has_h3,
                resolution_method=ResolutionMethod.LATLNG,
                resolved_lat=lat,
                resolved_lng=lng,
            )

        # Try H3 fallback
        if has_h3 and self.policy.allow_h3_fallback:
            resolved = self._resolve_h3(h3_index, h3_resolver)
            if resolved:
                return OrderCoordsStatus(
                    order_id=order_id,
                    has_latlng=False,
                    has_zone=has_zone,
                    has_h3=True,
                    resolution_method=ResolutionMethod.H3,
                    resolved_lat=resolved[0],
                    resolved_lng=resolved[1],
                    resolution_notes=f"Resolved via H3 {h3_index}",
                )

        # Try zone fallback
        if has_zone and self.policy.allow_zone_fallback:
            resolved = self._resolve_zone(zone_id, zone_resolver)
            if resolved:
                return OrderCoordsStatus(
                    order_id=order_id,
                    has_latlng=False,
                    has_zone=True,
                    has_h3=has_h3,
                    resolution_method=ResolutionMethod.ZONE,
                    resolved_lat=resolved[0],
                    resolved_lng=resolved[1],
                    resolution_notes=f"Resolved via zone {zone_id}",
                )

        # Unresolved
        return OrderCoordsStatus(
            order_id=order_id,
            has_latlng=False,
            has_zone=has_zone,
            has_h3=has_h3,
            resolution_method=ResolutionMethod.UNRESOLVED,
            resolution_notes="No resolution method available",
        )

    def _resolve_h3(
        self,
        h3_index: str,
        resolver: Optional[Any],
    ) -> Optional[tuple]:
        """Resolve H3 index to lat/lng."""
        if resolver:
            try:
                return resolver.resolve(h3_index)
            except Exception:
                pass

        # Basic H3 resolution (centroid)
        try:
            import h3
            lat, lng = h3.h3_to_geo(h3_index)
            return (lat, lng)
        except ImportError:
            pass
        except Exception:
            pass

        return None

    def _resolve_zone(
        self,
        zone_id: str,
        resolver: Optional[Any],
    ) -> Optional[tuple]:
        """Resolve zone/PLZ to lat/lng centroid."""
        if resolver:
            try:
                return resolver.resolve(zone_id)
            except Exception:
                pass

        # Could implement PLZ → centroid lookup here
        # For now, return None (zone without resolver)
        return None

    def _apply_policy(self, result: CoordsQualityResult) -> CoordsQualityResult:
        """Apply policy thresholds to determine verdict."""
        policy = self.policy
        reasons = []
        warnings = []

        # Check for BLOCK conditions first
        # BLOCK if any unresolved (strict mode)
        if policy.strict_mode and result.orders_unresolved > 0:
            reasons.append(
                f"BLOCK: {result.orders_unresolved} unresolved orders "
                f"(strict mode requires 0)"
            )

        # BLOCK if unresolved exceeds threshold
        if result.orders_unresolved > policy.block_unresolved_max:
            reasons.append(
                f"BLOCK: {result.orders_unresolved} unresolved orders "
                f"exceeds threshold {policy.block_unresolved_max}"
            )

        # BLOCK if missing lat/lng rate too high
        if result.missing_latlng_rate > policy.block_missing_latlng_max:
            reasons.append(
                f"BLOCK: Missing lat/lng rate {result.missing_latlng_rate:.1%} "
                f"exceeds {policy.block_missing_latlng_max:.1%}"
            )

        # BLOCK if fallback rate too high
        if result.fallback_rate > policy.block_fallback_rate_max:
            reasons.append(
                f"BLOCK: Fallback rate {result.fallback_rate:.1%} "
                f"exceeds {policy.block_fallback_rate_max:.1%}"
            )

        if reasons:
            result.verdict = CoordsVerdict.BLOCK
            result.reasons = reasons
            return result

        # Check for WARN conditions
        # WARN if missing lat/lng rate above ok threshold
        if result.missing_latlng_rate > policy.ok_missing_latlng_max:
            warnings.append(
                f"Missing lat/lng rate {result.missing_latlng_rate:.1%} "
                f"exceeds OK threshold {policy.ok_missing_latlng_max:.1%}"
            )

        # WARN if fallback rate above ok threshold
        if result.fallback_rate > policy.ok_fallback_rate_max:
            warnings.append(
                f"Fallback rate {result.fallback_rate:.1%} "
                f"exceeds OK threshold {policy.ok_fallback_rate_max:.1%}"
            )

        if warnings:
            result.verdict = CoordsVerdict.WARN
            result.warnings = warnings
            result.reasons = ["WARN: Coords quality below optimal"]
            return result

        # All OK
        result.verdict = CoordsVerdict.OK
        result.reasons = ["All coords present or resolvable"]
        return result

    def check_and_raise(
        self,
        orders: List[Dict[str, Any]],
        zone_resolver: Optional[Any] = None,
        h3_resolver: Optional[Any] = None,
    ) -> CoordsQualityResult:
        """
        Evaluate and raise exception if blocked.

        Args:
            orders: List of orders
            zone_resolver: Optional zone resolver
            h3_resolver: Optional H3 resolver

        Returns:
            CoordsQualityResult if OK or WARN

        Raises:
            CoordsQualityError if BLOCK
        """
        result = self.evaluate(orders, zone_resolver, h3_resolver)

        if result.verdict == CoordsVerdict.BLOCK:
            raise CoordsQualityError(
                message=f"Coords quality gate blocked: {'; '.join(result.reasons)}",
                verdict=result.verdict,
                result=result,
            )

        return result
