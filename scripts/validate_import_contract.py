#!/usr/bin/env python3
"""
SOLVEREIGN V3.7 - Import Contract Validator
============================================

Validates roster input files against the import contract schema.
Supports JSON and CSV formats.

Exit Codes:
    0 = Valid, no errors or warnings
    1 = Valid with warnings
    2 = Invalid, hard gate failures

Usage:
    python scripts/validate_import_contract.py --input data.json
    python scripts/validate_import_contract.py --input tours.csv --format csv
    python scripts/validate_import_contract.py --input data.json --output canonical.json
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# CONSTANTS
# =============================================================================

VERSION = "1.0.0"

TENANT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
SITE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
TIME_PATTERN = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")

# Austria bounding box (for coordinate validation)
LAT_MIN, LAT_MAX = 46.3, 49.1
LNG_MIN, LNG_MAX = 9.5, 17.2


# =============================================================================
# DATA CLASSES
# =============================================================================

class GateType(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class ValidationResult:
    gate_id: str
    gate_type: GateType
    status: ValidationStatus
    message: str
    line: Optional[int] = None
    field: Optional[str] = None
    external_id: Optional[str] = None


@dataclass
class ValidationReport:
    status: ValidationStatus = ValidationStatus.PASS
    input_file: str = ""
    input_hash: str = ""
    hard_gates_passed: int = 0
    hard_gates_failed: int = 0
    soft_gates_passed: int = 0
    soft_gates_warnings: int = 0
    results: List[ValidationResult] = field(default_factory=list)
    tours_count: int = 0
    drivers_count: int = 0
    vehicles_count: int = 0
    total_instances: int = 0


# =============================================================================
# VALIDATOR
# =============================================================================

class ImportContractValidator:
    """Validates roster import data against the contract schema."""

    def __init__(self, strict: bool = False, verbose: bool = False):
        self.strict = strict  # Treat warnings as errors
        self.verbose = verbose
        self.report = ValidationReport()

    def validate(self, data: Dict[str, Any], input_file: str = "") -> ValidationReport:
        """Validate import data."""
        self.report = ValidationReport(input_file=input_file)

        # Calculate input hash
        self.report.input_hash = self._compute_hash(json.dumps(data, sort_keys=True))

        # Run hard gates
        self._validate_hard_gates(data)

        # Run soft gates (only if hard gates pass)
        if self.report.hard_gates_failed == 0:
            self._validate_soft_gates(data)

        # Calculate summary
        self._calculate_summary(data)

        # Determine final status
        if self.report.hard_gates_failed > 0:
            self.report.status = ValidationStatus.FAIL
        elif self.report.soft_gates_warnings > 0:
            self.report.status = ValidationStatus.WARN if not self.strict else ValidationStatus.FAIL
        else:
            self.report.status = ValidationStatus.PASS

        return self.report

    def _validate_hard_gates(self, data: Dict[str, Any]) -> None:
        """Run hard gate validations (FAIL if violated)."""

        # HG-001: tenant_code required and valid
        tenant_code = data.get("tenant_code")
        if not tenant_code:
            self._add_result("HG-001", GateType.HARD, ValidationStatus.FAIL,
                           "Required field 'tenant_code' is missing", field="tenant_code")
        elif not TENANT_CODE_PATTERN.match(tenant_code):
            self._add_result("HG-001", GateType.HARD, ValidationStatus.FAIL,
                           f"Invalid tenant_code format: '{tenant_code}'", field="tenant_code")
        else:
            self._add_result("HG-001", GateType.HARD, ValidationStatus.PASS,
                           "tenant_code valid", field="tenant_code")

        # HG-002: site_code required and valid
        site_code = data.get("site_code")
        if not site_code:
            self._add_result("HG-002", GateType.HARD, ValidationStatus.FAIL,
                           "Required field 'site_code' is missing", field="site_code")
        elif not SITE_CODE_PATTERN.match(site_code):
            self._add_result("HG-002", GateType.HARD, ValidationStatus.FAIL,
                           f"Invalid site_code format: '{site_code}'", field="site_code")
        else:
            self._add_result("HG-002", GateType.HARD, ValidationStatus.PASS,
                           "site_code valid", field="site_code")

        # HG-003: week_anchor_date required and is Monday
        anchor = data.get("week_anchor_date")
        if not anchor:
            self._add_result("HG-003", GateType.HARD, ValidationStatus.FAIL,
                           "Required field 'week_anchor_date' is missing", field="week_anchor_date")
        else:
            try:
                anchor_date = datetime.strptime(anchor, "%Y-%m-%d")
                if anchor_date.weekday() != 0:  # 0 = Monday
                    self._add_result("HG-003", GateType.HARD, ValidationStatus.FAIL,
                                   f"week_anchor_date '{anchor}' is not a Monday", field="week_anchor_date")
                else:
                    self._add_result("HG-003", GateType.HARD, ValidationStatus.PASS,
                                   "week_anchor_date is valid Monday", field="week_anchor_date")
            except ValueError:
                self._add_result("HG-003", GateType.HARD, ValidationStatus.FAIL,
                               f"Invalid date format: '{anchor}' (expected YYYY-MM-DD)", field="week_anchor_date")

        # HG-004: At least 1 tour
        tours = data.get("tours", [])
        if not tours or len(tours) == 0:
            self._add_result("HG-004", GateType.HARD, ValidationStatus.FAIL,
                           "At least one tour is required", field="tours")
        else:
            self._add_result("HG-004", GateType.HARD, ValidationStatus.PASS,
                           f"Found {len(tours)} tour(s)", field="tours")

        # HG-005: Unique external_ids
        external_ids = {}
        for i, tour in enumerate(tours):
            ext_id = tour.get("external_id")
            if ext_id in external_ids:
                self._add_result("HG-005", GateType.HARD, ValidationStatus.FAIL,
                               f"Duplicate external_id '{ext_id}' at lines {external_ids[ext_id]+1}, {i+1}",
                               line=i+1, field="external_id", external_id=ext_id)
            elif ext_id:
                external_ids[ext_id] = i

        if not any(r.gate_id == "HG-005" and r.status == ValidationStatus.FAIL for r in self.report.results):
            self._add_result("HG-005", GateType.HARD, ValidationStatus.PASS,
                           "All external_ids are unique", field="external_id")

        # Validate each tour
        for i, tour in enumerate(tours):
            self._validate_tour(tour, i + 1)

    def _validate_tour(self, tour: Dict[str, Any], line: int) -> None:
        """Validate a single tour."""
        ext_id = tour.get("external_id", f"<line {line}>")

        # HG-006: day between 1-7
        day = tour.get("day")
        if day is None:
            self._add_result("HG-006", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': missing required field 'day'",
                           line=line, field="day", external_id=ext_id)
        elif not isinstance(day, int) or day < 1 or day > 7:
            self._add_result("HG-006", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': day {day} must be integer 1-7",
                           line=line, field="day", external_id=ext_id)

        # HG-007: start_time valid
        start_time = tour.get("start_time")
        if not start_time:
            self._add_result("HG-007", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': missing required field 'start_time'",
                           line=line, field="start_time", external_id=ext_id)
        elif not TIME_PATTERN.match(start_time):
            self._add_result("HG-007", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': invalid start_time '{start_time}' (expected HH:MM)",
                           line=line, field="start_time", external_id=ext_id)

        # HG-008: end_time valid
        end_time = tour.get("end_time")
        if not end_time:
            self._add_result("HG-008", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': missing required field 'end_time'",
                           line=line, field="end_time", external_id=ext_id)
        elif not TIME_PATTERN.match(end_time):
            self._add_result("HG-008", GateType.HARD, ValidationStatus.FAIL,
                           f"Tour '{ext_id}': invalid end_time '{end_time}' (expected HH:MM)",
                           line=line, field="end_time", external_id=ext_id)

    def _validate_soft_gates(self, data: Dict[str, Any]) -> None:
        """Run soft gate validations (WARN if violated)."""
        tours = data.get("tours", [])

        for i, tour in enumerate(tours):
            ext_id = tour.get("external_id", f"<line {i+1}>")
            line = i + 1

            # SG-001: count default
            if "count" not in tour or tour.get("count") is None:
                self._add_result("SG-001", GateType.SOFT, ValidationStatus.WARN,
                               f"Tour '{ext_id}': count defaulted to 1",
                               line=line, field="count", external_id=ext_id)

            # SG-002: depot default
            if "depot" not in tour or not tour.get("depot"):
                self._add_result("SG-002", GateType.SOFT, ValidationStatus.WARN,
                               f"Tour '{ext_id}': depot defaulted to 'default'",
                               line=line, field="depot", external_id=ext_id)

            # SG-003: skill default
            if "skill" not in tour or not tour.get("skill"):
                self._add_result("SG-003", GateType.SOFT, ValidationStatus.WARN,
                               f"Tour '{ext_id}': skill defaulted to 'standard'",
                               line=line, field="skill", external_id=ext_id)

            # SG-004: unusual duration
            start_time = tour.get("start_time")
            end_time = tour.get("end_time")
            if start_time and end_time:
                duration = self._calculate_duration(start_time, end_time)
                if duration <= 0:
                    self._add_result("SG-004", GateType.SOFT, ValidationStatus.WARN,
                                   f"Tour '{ext_id}': zero or negative duration (crosses midnight?)",
                                   line=line, field="duration", external_id=ext_id)
                elif duration > 16 * 60:  # >16 hours
                    self._add_result("SG-004", GateType.SOFT, ValidationStatus.WARN,
                                   f"Tour '{ext_id}': duration {duration//60}h may be unusual",
                                   line=line, field="duration", external_id=ext_id)

            # SG-005: coordinates out of bounds
            lat = tour.get("lat")
            lng = tour.get("lng")
            if lat is not None and lng is not None:
                if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                    self._add_result("SG-005", GateType.SOFT, ValidationStatus.WARN,
                                   f"Tour '{ext_id}': coordinates ({lat}, {lng}) outside Austria region",
                                   line=line, field="coordinates", external_id=ext_id)
            elif (lat is not None) != (lng is not None):  # One provided but not both
                self._add_result("SG-005", GateType.SOFT, ValidationStatus.WARN,
                               f"Tour '{ext_id}': incomplete coordinates (both lat and lng required)",
                               line=line, field="coordinates", external_id=ext_id)

    def _calculate_duration(self, start: str, end: str) -> int:
        """Calculate duration in minutes (simple, doesn't handle cross-midnight)."""
        start_parts = start.split(":")
        end_parts = end.split(":")
        start_min = int(start_parts[0]) * 60 + int(start_parts[1])
        end_min = int(end_parts[0]) * 60 + int(end_parts[1])
        return end_min - start_min

    def _calculate_summary(self, data: Dict[str, Any]) -> None:
        """Calculate summary statistics."""
        tours = data.get("tours", [])
        self.report.tours_count = len(tours)
        self.report.drivers_count = len(data.get("drivers", []))
        self.report.vehicles_count = len(data.get("vehicles", []))

        # Calculate total instances (sum of counts)
        total = 0
        for tour in tours:
            count = tour.get("count", 1)
            total += count if isinstance(count, int) and count > 0 else 1
        self.report.total_instances = total

    def _add_result(self, gate_id: str, gate_type: GateType, status: ValidationStatus,
                    message: str, **kwargs) -> None:
        """Add a validation result."""
        result = ValidationResult(
            gate_id=gate_id,
            gate_type=gate_type,
            status=status,
            message=message,
            **kwargs
        )
        self.report.results.append(result)

        if gate_type == GateType.HARD:
            if status == ValidationStatus.PASS:
                self.report.hard_gates_passed += 1
            else:
                self.report.hard_gates_failed += 1
        else:
            if status == ValidationStatus.PASS:
                self.report.soft_gates_passed += 1
            else:
                self.report.soft_gates_warnings += 1

        if self.verbose:
            status_icon = "✅" if status == ValidationStatus.PASS else ("⚠️" if status == ValidationStatus.WARN else "❌")
            print(f"  {status_icon} [{gate_id}] {message}")

    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash."""
        return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


# =============================================================================
# CANONICALIZER
# =============================================================================

class ImportCanonicalizer:
    """Converts validated import data to canonical format."""

    def canonicalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert to canonical format with defaults applied."""
        canonical = {
            "schema_version": VERSION,
            "tenant_code": data["tenant_code"],
            "site_code": data["site_code"],
            "week_anchor_date": data["week_anchor_date"],
            "service_code": data.get("service_code", "default"),
            "tours": [],
            "drivers": [],
            "vehicles": [],
            "metadata": data.get("metadata", {}),
        }

        # Canonicalize tours
        for tour in data.get("tours", []):
            canonical["tours"].append(self._canonicalize_tour(tour))

        # Canonicalize drivers
        for driver in data.get("drivers", []):
            canonical["drivers"].append(self._canonicalize_driver(driver))

        # Canonicalize vehicles
        for vehicle in data.get("vehicles", []):
            canonical["vehicles"].append(self._canonicalize_vehicle(vehicle))

        # Add canonical hash
        canonical["canonical_hash"] = self._compute_hash(canonical)

        return canonical

    def _canonicalize_tour(self, tour: Dict[str, Any]) -> Dict[str, Any]:
        """Apply defaults to tour."""
        return {
            "external_id": tour["external_id"],
            "day": tour["day"],
            "start_time": tour["start_time"],
            "end_time": tour["end_time"],
            "count": tour.get("count", 1),
            "depot": tour.get("depot", "default"),
            "skill": tour.get("skill", "standard"),
            "priority": tour.get("priority", 5),
            "lat": tour.get("lat"),
            "lng": tour.get("lng"),
            "volume": tour.get("volume"),
            "notes": tour.get("notes"),
        }

    def _canonicalize_driver(self, driver: Dict[str, Any]) -> Dict[str, Any]:
        """Apply defaults to driver."""
        return {
            "external_id": driver["external_id"],
            "name": driver["name"],
            "skills": driver.get("skills", ["standard"]),
            "depot": driver.get("depot", "default"),
            "max_hours_week": driver.get("max_hours_week", 48),
            "contract_type": driver.get("contract_type", "full_time"),
            "unavailable_days": driver.get("unavailable_days", []),
        }

    def _canonicalize_vehicle(self, vehicle: Dict[str, Any]) -> Dict[str, Any]:
        """Apply defaults to vehicle."""
        return {
            "external_id": vehicle["external_id"],
            "type": vehicle.get("type", "default"),
            "capacity": vehicle.get("capacity"),
            "depot": vehicle.get("depot", "default"),
        }

    def _compute_hash(self, data: Dict[str, Any]) -> str:
        """Compute hash of canonical data (excluding the hash field itself)."""
        data_copy = {k: v for k, v in data.items() if k != "canonical_hash"}
        content = json.dumps(data_copy, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


# =============================================================================
# CSV PARSER
# =============================================================================

class CSVParser:
    """Parses CSV input to JSON format."""

    def parse_tours_csv(self, file_path: Path, tenant_code: str, site_code: str,
                        week_anchor_date: str) -> Dict[str, Any]:
        """Parse tours CSV file."""
        tours = []

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                tour = {
                    "external_id": row.get("external_id", "").strip(),
                    "day": self._parse_int(row.get("day")),
                    "start_time": row.get("start_time", "").strip(),
                    "end_time": row.get("end_time", "").strip(),
                }

                # Optional fields
                if row.get("count"):
                    tour["count"] = self._parse_int(row.get("count"))
                if row.get("depot"):
                    tour["depot"] = row.get("depot").strip()
                if row.get("skill"):
                    tour["skill"] = row.get("skill").strip()
                if row.get("priority"):
                    tour["priority"] = self._parse_int(row.get("priority"))
                if row.get("lat"):
                    tour["lat"] = self._parse_float(row.get("lat"))
                if row.get("lng"):
                    tour["lng"] = self._parse_float(row.get("lng"))
                if row.get("volume"):
                    tour["volume"] = self._parse_float(row.get("volume"))
                if row.get("notes"):
                    tour["notes"] = row.get("notes").strip()

                tours.append(tour)

        return {
            "tenant_code": tenant_code,
            "site_code": site_code,
            "week_anchor_date": week_anchor_date,
            "tours": tours,
        }

    def _parse_int(self, value: Optional[str]) -> Optional[int]:
        if value is None or value.strip() == "":
            return None
        try:
            return int(value.strip())
        except ValueError:
            return None

    def _parse_float(self, value: Optional[str]) -> Optional[float]:
        if value is None or value.strip() == "":
            return None
        try:
            return float(value.strip())
        except ValueError:
            return None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Import Contract Validator"
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input file (JSON or CSV)"
    )

    parser.add_argument(
        "--format", "-f",
        choices=["json", "csv"],
        default="json",
        help="Input format (default: json)"
    )

    parser.add_argument(
        "--output", "-o",
        help="Output file for canonical JSON"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    # CSV-specific options
    parser.add_argument("--tenant-code", help="Tenant code (required for CSV)")
    parser.add_argument("--site-code", help="Site code (required for CSV)")
    parser.add_argument("--week-anchor-date", help="Week anchor date (required for CSV)")

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(2)

    # Load input data
    if args.format == "csv":
        if not all([args.tenant_code, args.site_code, args.week_anchor_date]):
            print("ERROR: --tenant-code, --site-code, and --week-anchor-date required for CSV format")
            sys.exit(2)

        csv_parser = CSVParser()
        data = csv_parser.parse_tours_csv(
            input_path,
            args.tenant_code,
            args.site_code,
            args.week_anchor_date
        )
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    # Validate
    print("=" * 70)
    print("SOLVEREIGN IMPORT CONTRACT VALIDATOR")
    print("=" * 70)
    print(f"Input:   {args.input}")
    print(f"Format:  {args.format}")
    print(f"Strict:  {args.strict}")
    print("=" * 70)
    print()

    validator = ImportContractValidator(strict=args.strict, verbose=args.verbose)
    report = validator.validate(data, str(input_path))

    # Print summary
    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Status:           {report.status.value}")
    print(f"Hard Gates:       {report.hard_gates_passed} passed, {report.hard_gates_failed} failed")
    print(f"Soft Gates:       {report.soft_gates_passed} passed, {report.soft_gates_warnings} warnings")
    print(f"Tours:            {report.tours_count}")
    print(f"Total Instances:  {report.total_instances}")
    print(f"Input Hash:       {report.input_hash[:50]}...")
    print("=" * 70)

    # Print failures and warnings
    failures = [r for r in report.results if r.status == ValidationStatus.FAIL]
    warnings = [r for r in report.results if r.status == ValidationStatus.WARN]

    if failures:
        print()
        print("FAILURES:")
        for r in failures:
            loc = f" (line {r.line})" if r.line else ""
            print(f"  ❌ [{r.gate_id}] {r.message}{loc}")

    if warnings:
        print()
        print("WARNINGS:")
        for r in warnings[:10]:  # Limit to first 10
            loc = f" (line {r.line})" if r.line else ""
            print(f"  ⚠️  [{r.gate_id}] {r.message}{loc}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more warnings")

    # Generate canonical output if requested
    if args.output and report.status != ValidationStatus.FAIL:
        canonicalizer = ImportCanonicalizer()
        canonical = canonicalizer.canonicalize(data)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(canonical, f, indent=2, sort_keys=True)

        print()
        print(f"Canonical output: {args.output}")

    # Write JSON report
    report_dict = {
        "status": report.status.value,
        "input_file": report.input_file,
        "input_hash": report.input_hash,
        "validation": {
            "hard_gates": {
                "passed": report.hard_gates_passed,
                "failed": report.hard_gates_failed,
            },
            "soft_gates": {
                "passed": report.soft_gates_passed,
                "warnings": report.soft_gates_warnings,
            },
            "results": [
                {
                    "gate": r.gate_id,
                    "type": r.gate_type.value,
                    "status": r.status.value,
                    "message": r.message,
                    "line": r.line,
                    "field": r.field,
                    "external_id": r.external_id,
                }
                for r in report.results
                if r.status != ValidationStatus.PASS  # Only include non-PASS results
            ]
        },
        "summary": {
            "tours": report.tours_count,
            "drivers": report.drivers_count,
            "vehicles": report.vehicles_count,
            "total_instances": report.total_instances,
        }
    }

    # Exit code
    if report.status == ValidationStatus.PASS:
        print()
        print("✅ Validation PASSED")
        sys.exit(0)
    elif report.status == ValidationStatus.WARN:
        print()
        print("⚠️  Validation PASSED with warnings")
        sys.exit(1)
    else:
        print()
        print("❌ Validation FAILED")
        sys.exit(2)


if __name__ == "__main__":
    main()
