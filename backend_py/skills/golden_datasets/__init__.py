"""Golden Dataset Manager - Versioned test fixtures for regression testing."""

from .schemas import (
    DatasetType,
    DatasetManifest,
    ExpectedFailure,
    ValidationResult,
    Difference,
)
from .manager import GoldenDatasetManager, DatasetNotFoundError

__all__ = [
    "DatasetType",
    "DatasetManifest",
    "ExpectedFailure",
    "ValidationResult",
    "Difference",
    "GoldenDatasetManager",
    "DatasetNotFoundError",
]
