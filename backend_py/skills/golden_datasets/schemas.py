"""
Schema definitions for Golden Dataset Manager.

Defines dataclasses for:
- DatasetManifest: Metadata for a golden dataset
- ExpectedFailure: What failure is expected for known_failure datasets
- ValidationResult: Result of validating a dataset
- Difference: A difference between expected and actual output
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class DatasetType(Enum):
    """Type of golden dataset."""
    HAPPY_PATH = "happy_path"        # Should succeed with all audits PASS
    KNOWN_FAILURE = "known_failure"  # Should fail in specific way
    STRESS_TEST = "stress_test"      # Large-scale performance test
    EDGE_CASE = "edge_case"          # Boundary conditions


@dataclass
class ExpectedFailure:
    """What failure is expected for known_failure datasets."""
    failure_type: str       # "audit_fail", "solver_timeout", "constraint_conflict"
    failure_reason: str     # "REST_VIOLATION", "CAPACITY_EXCEEDED"
    expected_error_pattern: str = ".*"  # Regex to match error message


@dataclass
class DatasetManifest:
    """Manifest for a golden dataset."""
    name: str
    pack: str                          # "routing" or "roster"
    type: DatasetType

    # Versioning
    version: str                       # Semantic version "1.2.3"
    created_at: datetime
    updated_at: datetime
    created_by: str

    # Description
    description: str
    scenario: str                      # What this dataset represents

    # Size metrics
    input_size: Dict[str, int]        # {"stops": 10, "vehicles": 3} or {"tours": 50}

    # Determinism
    solver_seed: int                   # Fixed seed for reproducibility
    input_hash: str                    # SHA256 of input.json

    # Expected outputs
    expected_output_hash: str          # SHA256 of expected outputs
    expected_kpis: Dict[str, Any]     # Coverage, drivers, etc.

    # For known_failure datasets
    expected_failure: Optional[ExpectedFailure] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "pack": self.pack,
            "type": self.type.value if isinstance(self.type, DatasetType) else self.type,
            "version": self.version,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "created_by": self.created_by,
            "description": self.description,
            "scenario": self.scenario,
            "input_size": self.input_size,
            "solver_seed": self.solver_seed,
            "input_hash": self.input_hash,
            "expected_output_hash": self.expected_output_hash,
            "expected_kpis": self.expected_kpis,
            "expected_failure": {
                "failure_type": self.expected_failure.failure_type,
                "failure_reason": self.expected_failure.failure_reason,
                "expected_error_pattern": self.expected_failure.expected_error_pattern,
            } if self.expected_failure else None,
        }


@dataclass
class Difference:
    """A difference between expected and actual output."""
    field: str                         # "routes[0].stops", "kpis.coverage_percent"
    expected: Any
    actual: Any
    severity: str = "minor"            # "critical", "minor"


@dataclass
class ValidationResult:
    """Result of validating a dataset."""
    dataset_name: str
    pack: str
    passed: bool

    # Comparison details
    output_hash_match: bool
    kpi_match: bool
    audit_match: bool

    # If failed, what differed
    differences: List[Difference] = field(default_factory=list)

    # Timing
    solve_duration_ms: int = 0
    validation_duration_ms: int = 0

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "dataset_name": self.dataset_name,
            "pack": self.pack,
            "passed": self.passed,
            "output_hash_match": self.output_hash_match,
            "kpi_match": self.kpi_match,
            "audit_match": self.audit_match,
            "differences": [
                {
                    "field": d.field,
                    "expected": d.expected,
                    "actual": d.actual,
                    "severity": d.severity,
                }
                for d in self.differences
            ],
            "solve_duration_ms": self.solve_duration_ms,
            "validation_duration_ms": self.validation_duration_ms,
        }
