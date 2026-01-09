# =============================================================================
# SOLVEREIGN Routing Pack - FLS Validator
# =============================================================================
# Validates canonical import data against contract schema and business rules.
#
# Gate verdicts:
# - OK: All gates pass
# - WARN: Soft gates failed (proceed with caution)
# - BLOCK: Hard gates failed (cannot proceed)
# =============================================================================

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

try:
    from jsonschema import validate, ValidationError, Draft7Validator
except ImportError:
    validate = None
    ValidationError = Exception
    Draft7Validator = None

from .fls_canonicalize import CanonicalImport, CanonicalOrder

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class GateVerdict(str, Enum):
    """Gate verdict levels."""
    OK = "OK"
    WARN = "WARN"
    BLOCK = "BLOCK"


class GateType(str, Enum):
    """Gate types."""
    HARD = "HARD"
    SOFT = "SOFT"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ValidationGate:
    """Result of a single validation gate."""

    gate_id: str
    gate_type: GateType
    verdict: GateVerdict
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    affected_orders: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_type": self.gate_type.value,
            "verdict": self.verdict.value,
            "message": self.message,
            "details": self.details,
            "affected_orders": self.affected_orders[:10],  # Limit to first 10
            "affected_count": len(self.affected_orders),
        }


@dataclass
class ValidationReport:
    """Complete validation report."""

    validated_at: datetime
    overall_verdict: GateVerdict
    gates: List[ValidationGate] = field(default_factory=list)

    # Statistics
    total_orders: int = 0
    valid_orders: int = 0
    orders_with_warnings: int = 0
    orders_with_errors: int = 0

    # Coords statistics
    coords_present: int = 0
    coords_from_zone: int = 0
    coords_missing: int = 0

    # Duplicate statistics
    duplicate_order_ids: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validated_at": self.validated_at.isoformat(),
            "overall_verdict": self.overall_verdict.value,
            "summary": {
                "total_gates": len(self.gates),
                "hard_gates_passed": sum(
                    1 for g in self.gates
                    if g.gate_type == GateType.HARD and g.verdict == GateVerdict.OK
                ),
                "hard_gates_failed": sum(
                    1 for g in self.gates
                    if g.gate_type == GateType.HARD and g.verdict == GateVerdict.BLOCK
                ),
                "soft_gates_warned": sum(
                    1 for g in self.gates
                    if g.gate_type == GateType.SOFT and g.verdict == GateVerdict.WARN
                ),
            },
            "statistics": {
                "total_orders": self.total_orders,
                "valid_orders": self.valid_orders,
                "orders_with_warnings": self.orders_with_warnings,
                "orders_with_errors": self.orders_with_errors,
                "coords_present": self.coords_present,
                "coords_from_zone": self.coords_from_zone,
                "coords_missing": self.coords_missing,
                "duplicate_order_ids": self.duplicate_order_ids,
            },
            "gates": [g.to_dict() for g in self.gates],
        }


@dataclass
class ValidationResult:
    """Final validation result."""

    success: bool
    verdict: GateVerdict
    report: ValidationReport
    can_proceed: bool  # True if OK or WARN (with approval)
    requires_approval: bool  # True if WARN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "verdict": self.verdict.value,
            "can_proceed": self.can_proceed,
            "requires_approval": self.requires_approval,
            "report": self.report.to_dict(),
        }


# =============================================================================
# VALIDATOR
# =============================================================================

class FLSValidator:
    """
    Validates canonical import data against contract and business rules.

    Gates:
    - HARD gates: Must pass or import is BLOCKED
    - SOFT gates: Warn but allow with approval

    Usage:
        validator = FLSValidator()
        result = validator.validate(canonical_import)
        if result.verdict == GateVerdict.BLOCK:
            # Cannot proceed
        elif result.verdict == GateVerdict.WARN:
            # Proceed with approval
        else:
            # OK to proceed
    """

    # Known service codes (for soft gate)
    KNOWN_SERVICE_CODES: Set[str] = {
        "DELIVERY", "PICKUP", "SERVICE", "RETURN", "EXCHANGE",
        "INSTALL", "REPAIR", "COLLECT", "EXPRESS", "STANDARD",
    }

    # Austria bounding box
    AUSTRIA_BOUNDS = {
        "lat_min": 46.0,
        "lat_max": 49.5,
        "lng_min": 9.0,
        "lng_max": 18.0,
    }

    def __init__(
        self,
        schema_path: Optional[Path] = None,
        max_duplicate_warning: int = 10,
        max_missing_coords_warning: float = 0.05,  # 5% warning threshold
        max_missing_coords_block: float = 0.20,    # 20% block threshold
    ):
        """
        Initialize validator.

        Args:
            schema_path: Path to JSON schema file (optional)
            max_duplicate_warning: Max duplicate order_ids before warning
            max_missing_coords_warning: Threshold for missing coords warning
            max_missing_coords_block: Threshold for missing coords block
        """
        self.schema_path = schema_path
        self.schema = None
        self.max_duplicate_warning = max_duplicate_warning
        self.max_missing_coords_warning = max_missing_coords_warning
        self.max_missing_coords_block = max_missing_coords_block

        if schema_path and schema_path.exists():
            with open(schema_path) as f:
                self.schema = json.load(f)

    def validate(self, canonical_import: CanonicalImport) -> ValidationResult:
        """
        Validate canonical import.

        Args:
            canonical_import: Canonical import to validate

        Returns:
            ValidationResult with verdict and report
        """
        gates: List[ValidationGate] = []

        # Run all validation gates
        gates.append(self._gate_order_ids(canonical_import))
        gates.append(self._gate_time_windows(canonical_import))
        gates.append(self._gate_coords_presence(canonical_import))
        gates.append(self._gate_coords_range(canonical_import))
        gates.append(self._gate_duplicates(canonical_import))
        gates.append(self._gate_service_codes(canonical_import))
        gates.append(self._gate_service_duration(canonical_import))
        gates.append(self._gate_metadata(canonical_import))

        # Determine overall verdict
        has_block = any(
            g.gate_type == GateType.HARD and g.verdict == GateVerdict.BLOCK
            for g in gates
        )
        has_warn = any(g.verdict == GateVerdict.WARN for g in gates)

        if has_block:
            overall_verdict = GateVerdict.BLOCK
        elif has_warn:
            overall_verdict = GateVerdict.WARN
        else:
            overall_verdict = GateVerdict.OK

        # Build report
        report = ValidationReport(
            validated_at=datetime.now(),
            overall_verdict=overall_verdict,
            gates=gates,
            total_orders=canonical_import.total_orders,
            valid_orders=sum(
                1 for o in canonical_import.orders
                if o.has_coords() or o.has_zone_fallback()
            ),
            orders_with_warnings=sum(
                1 for o in canonical_import.orders
                if o.had_coords_issue
            ),
            orders_with_errors=sum(
                1 for o in canonical_import.orders
                if not o.has_coords() and not o.has_zone_fallback()
            ),
            coords_present=canonical_import.orders_with_coords,
            coords_from_zone=canonical_import.orders_with_zone,
            coords_missing=canonical_import.orders_missing_location,
            duplicate_order_ids=len(canonical_import.duplicate_order_ids),
        )

        return ValidationResult(
            success=overall_verdict != GateVerdict.BLOCK,
            verdict=overall_verdict,
            report=report,
            can_proceed=overall_verdict != GateVerdict.BLOCK,
            requires_approval=overall_verdict == GateVerdict.WARN,
        )

    def _gate_order_ids(self, ci: CanonicalImport) -> ValidationGate:
        """HARD GATE: All orders must have order_id."""
        missing = [
            o.order_id for o in ci.orders
            if not o.order_id or o.order_id.strip() == ""
        ]

        if missing:
            return ValidationGate(
                gate_id="GATE_ORDER_ID",
                gate_type=GateType.HARD,
                verdict=GateVerdict.BLOCK,
                message=f"{len(missing)} orders missing order_id",
                affected_orders=missing,
            )

        return ValidationGate(
            gate_id="GATE_ORDER_ID",
            gate_type=GateType.HARD,
            verdict=GateVerdict.OK,
            message="All orders have order_id",
            details={"total": len(ci.orders)},
        )

    def _gate_time_windows(self, ci: CanonicalImport) -> ValidationGate:
        """HARD GATE: All orders must have valid time windows."""
        invalid = []

        for o in ci.orders:
            if o.tw_start is None or o.tw_end is None:
                invalid.append(o.order_id)
            elif o.tw_end <= o.tw_start:
                invalid.append(o.order_id)

        if invalid:
            return ValidationGate(
                gate_id="GATE_TIME_WINDOW",
                gate_type=GateType.HARD,
                verdict=GateVerdict.BLOCK,
                message=f"{len(invalid)} orders have invalid time windows",
                affected_orders=invalid,
            )

        return ValidationGate(
            gate_id="GATE_TIME_WINDOW",
            gate_type=GateType.HARD,
            verdict=GateVerdict.OK,
            message="All time windows valid",
            details={"total": len(ci.orders)},
        )

    def _gate_coords_presence(self, ci: CanonicalImport) -> ValidationGate:
        """HARD GATE: Orders must have coords OR zone/h3 fallback."""
        missing = [
            o.order_id for o in ci.orders
            if not o.has_coords() and not o.has_zone_fallback()
        ]

        if not ci.orders:
            return ValidationGate(
                gate_id="GATE_COORDS_PRESENCE",
                gate_type=GateType.HARD,
                verdict=GateVerdict.BLOCK,
                message="No orders in import",
            )

        missing_rate = len(missing) / len(ci.orders)

        if len(missing) > 0 and missing_rate >= self.max_missing_coords_block:
            return ValidationGate(
                gate_id="GATE_COORDS_PRESENCE",
                gate_type=GateType.HARD,
                verdict=GateVerdict.BLOCK,
                message=f"{len(missing)} orders ({missing_rate:.1%}) missing coords/zone",
                details={
                    "missing_count": len(missing),
                    "missing_rate": round(missing_rate, 4),
                    "threshold": self.max_missing_coords_block,
                },
                affected_orders=missing,
            )

        if len(missing) > 0 and missing_rate >= self.max_missing_coords_warning:
            return ValidationGate(
                gate_id="GATE_COORDS_PRESENCE",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(missing)} orders ({missing_rate:.1%}) missing coords/zone",
                details={
                    "missing_count": len(missing),
                    "missing_rate": round(missing_rate, 4),
                    "threshold": self.max_missing_coords_warning,
                },
                affected_orders=missing,
            )

        if len(missing) > 0:
            return ValidationGate(
                gate_id="GATE_COORDS_PRESENCE",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(missing)} orders missing coords (using zone fallback)",
                affected_orders=missing,
            )

        return ValidationGate(
            gate_id="GATE_COORDS_PRESENCE",
            gate_type=GateType.HARD,
            verdict=GateVerdict.OK,
            message="All orders have coords or zone fallback",
            details={
                "with_coords": ci.orders_with_coords,
                "with_zone": ci.orders_with_zone,
            },
        )

    def _gate_coords_range(self, ci: CanonicalImport) -> ValidationGate:
        """SOFT GATE: Coordinates should be within Austria bounds."""
        out_of_bounds = []

        for o in ci.orders:
            if o.lat is not None and o.lng is not None:
                if not (
                    self.AUSTRIA_BOUNDS["lat_min"] <= o.lat <= self.AUSTRIA_BOUNDS["lat_max"] and
                    self.AUSTRIA_BOUNDS["lng_min"] <= o.lng <= self.AUSTRIA_BOUNDS["lng_max"]
                ):
                    out_of_bounds.append(o.order_id)

        if out_of_bounds:
            return ValidationGate(
                gate_id="GATE_COORDS_RANGE",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(out_of_bounds)} orders have coords outside Austria",
                details={"bounds": self.AUSTRIA_BOUNDS},
                affected_orders=out_of_bounds,
            )

        return ValidationGate(
            gate_id="GATE_COORDS_RANGE",
            gate_type=GateType.SOFT,
            verdict=GateVerdict.OK,
            message="All coordinates within Austria bounds",
        )

    def _gate_duplicates(self, ci: CanonicalImport) -> ValidationGate:
        """SOFT GATE: Warn on duplicate order_ids."""
        if len(ci.duplicate_order_ids) > self.max_duplicate_warning:
            return ValidationGate(
                gate_id="GATE_DUPLICATE_ORDER_ID",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(ci.duplicate_order_ids)} duplicate order_ids (high)",
                affected_orders=ci.duplicate_order_ids,
            )

        if ci.duplicate_order_ids:
            return ValidationGate(
                gate_id="GATE_DUPLICATE_ORDER_ID",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(ci.duplicate_order_ids)} duplicate order_ids",
                affected_orders=ci.duplicate_order_ids,
            )

        return ValidationGate(
            gate_id="GATE_DUPLICATE_ORDER_ID",
            gate_type=GateType.SOFT,
            verdict=GateVerdict.OK,
            message="No duplicate order_ids",
        )

    def _gate_service_codes(self, ci: CanonicalImport) -> ValidationGate:
        """SOFT GATE: Service codes should be recognized."""
        unknown = [
            o.order_id for o in ci.orders
            if o.service_code not in self.KNOWN_SERVICE_CODES
        ]

        if unknown:
            return ValidationGate(
                gate_id="GATE_SERVICE_CODE",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(unknown)} orders have unknown service_code",
                affected_orders=unknown,
            )

        return ValidationGate(
            gate_id="GATE_SERVICE_CODE",
            gate_type=GateType.SOFT,
            verdict=GateVerdict.OK,
            message="All service codes recognized",
        )

    def _gate_service_duration(self, ci: CanonicalImport) -> ValidationGate:
        """SOFT GATE: Service duration should be reasonable."""
        suspicious = []

        for o in ci.orders:
            if o.service_seconds < 60:
                suspicious.append(o.order_id)
            elif o.service_seconds > 7200:  # > 2 hours
                suspicious.append(o.order_id)

        if suspicious:
            return ValidationGate(
                gate_id="GATE_SERVICE_DURATION",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"{len(suspicious)} orders have unusual service duration",
                affected_orders=suspicious,
            )

        return ValidationGate(
            gate_id="GATE_SERVICE_DURATION",
            gate_type=GateType.SOFT,
            verdict=GateVerdict.OK,
            message="All service durations reasonable",
        )

    def _gate_metadata(self, ci: CanonicalImport) -> ValidationGate:
        """SOFT GATE: Metadata should be complete."""
        issues = []

        if not ci.tenant_id:
            issues.append("Missing tenant_id")
        if not ci.site_id:
            issues.append("Missing site_id")
        if not ci.plan_date:
            issues.append("Missing plan_date")

        if issues:
            return ValidationGate(
                gate_id="GATE_METADATA",
                gate_type=GateType.SOFT,
                verdict=GateVerdict.WARN,
                message=f"Incomplete metadata: {', '.join(issues)}",
                details={"issues": issues},
            )

        return ValidationGate(
            gate_id="GATE_METADATA",
            gate_type=GateType.SOFT,
            verdict=GateVerdict.OK,
            message="Metadata complete",
        )

    def validate_against_schema(
        self,
        raw_data: Dict[str, Any],
    ) -> ValidationResult:
        """
        Validate raw data against JSON schema.

        Args:
            raw_data: Raw import data

        Returns:
            ValidationResult
        """
        if validate is None:
            logger.warning("jsonschema not installed, skipping schema validation")
            return ValidationResult(
                success=True,
                verdict=GateVerdict.WARN,
                report=ValidationReport(
                    validated_at=datetime.now(),
                    overall_verdict=GateVerdict.WARN,
                    gates=[ValidationGate(
                        gate_id="GATE_SCHEMA",
                        gate_type=GateType.SOFT,
                        verdict=GateVerdict.WARN,
                        message="jsonschema not installed, skipped",
                    )],
                ),
                can_proceed=True,
                requires_approval=True,
            )

        if self.schema is None:
            logger.warning("No schema loaded, skipping schema validation")
            return ValidationResult(
                success=True,
                verdict=GateVerdict.WARN,
                report=ValidationReport(
                    validated_at=datetime.now(),
                    overall_verdict=GateVerdict.WARN,
                    gates=[ValidationGate(
                        gate_id="GATE_SCHEMA",
                        gate_type=GateType.SOFT,
                        verdict=GateVerdict.WARN,
                        message="No schema loaded, skipped",
                    )],
                ),
                can_proceed=True,
                requires_approval=True,
            )

        try:
            validate(raw_data, self.schema)
            return ValidationResult(
                success=True,
                verdict=GateVerdict.OK,
                report=ValidationReport(
                    validated_at=datetime.now(),
                    overall_verdict=GateVerdict.OK,
                    gates=[ValidationGate(
                        gate_id="GATE_SCHEMA",
                        gate_type=GateType.HARD,
                        verdict=GateVerdict.OK,
                        message="Schema validation passed",
                    )],
                ),
                can_proceed=True,
                requires_approval=False,
            )
        except ValidationError as e:
            return ValidationResult(
                success=False,
                verdict=GateVerdict.BLOCK,
                report=ValidationReport(
                    validated_at=datetime.now(),
                    overall_verdict=GateVerdict.BLOCK,
                    gates=[ValidationGate(
                        gate_id="GATE_SCHEMA",
                        gate_type=GateType.HARD,
                        verdict=GateVerdict.BLOCK,
                        message=f"Schema validation failed: {e.message}",
                        details={"path": list(e.absolute_path)},
                    )],
                ),
                can_proceed=False,
                requires_approval=False,
            )
