#!/usr/bin/env python3
"""
Unit tests for Golden Dataset Manager (Skill 115).

Tests cover:
- Dataset listing
- Dataset loading
- Validation
- Regression suite
- Hash computation
"""

import json
import tempfile
from pathlib import Path
import pytest

from backend_py.skills.golden_datasets import (
    GoldenDatasetManager,
    DatasetNotFoundError,
    DatasetType,
    DatasetManifest,
    ValidationResult,
    Difference,
)


class TestDatasetListing:
    """Test dataset listing functionality."""

    def test_list_empty_when_no_datasets(self):
        """Should return empty list when no datasets exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenDatasetManager(datasets_root=Path(tmpdir))
            datasets = manager.list_datasets()
            assert datasets == []

    def test_list_filters_by_pack(self):
        """Should filter datasets by pack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_registry(root, include_routing=True, include_roster=True)

            manager = GoldenDatasetManager(datasets_root=root)

            routing_only = manager.list_datasets(pack="routing")
            assert all(ds["pack"] == "routing" for ds in routing_only)

            roster_only = manager.list_datasets(pack="roster")
            assert all(ds["pack"] == "roster" for ds in roster_only)


class TestDatasetLoading:
    """Test dataset loading functionality."""

    def test_load_dataset_manifest(self):
        """Should load dataset manifest correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_dataset(root, "routing", "test_dataset")

            manager = GoldenDatasetManager(datasets_root=root)
            manifest = manager.get_dataset("test_dataset", "routing")

            assert manifest.name == "test_dataset"
            assert manifest.pack == "routing"
            assert manifest.type == DatasetType.HAPPY_PATH

    def test_raises_on_missing_dataset(self):
        """Should raise DatasetNotFoundError for missing dataset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenDatasetManager(datasets_root=Path(tmpdir))

            with pytest.raises(DatasetNotFoundError):
                manager.get_dataset("nonexistent", "routing")


class TestValidation:
    """Test dataset validation functionality."""

    def test_validate_passes_with_matching_input(self):
        """Should pass validation when input hash matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_dataset(root, "routing", "test_dataset")

            manager = GoldenDatasetManager(datasets_root=root)
            result = manager.validate_dataset("test_dataset", "routing")

            assert result.passed is True
            assert len(result.differences) == 0

    def test_validate_returns_differences(self):
        """Should return differences when validation fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_dataset(root, "routing", "test_dataset", wrong_hash=True)

            manager = GoldenDatasetManager(datasets_root=root)
            result = manager.validate_dataset("test_dataset", "routing")

            assert result.passed is False
            assert len(result.differences) > 0
            assert result.differences[0].field == "input_hash"


class TestRegression:
    """Test regression suite functionality."""

    def test_regression_all_pass(self):
        """Should report all_passed when all datasets pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_registry(root, include_routing=True, include_roster=False)
            _create_test_dataset(root, "routing", "test1")

            manager = GoldenDatasetManager(datasets_root=root)
            results = manager.validate_all()

            assert results["all_passed"] is True
            assert results["passed"] >= 1
            assert results["failed"] == 0

    def test_regression_reports_failures(self):
        """Should report failures in regression results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_test_registry(root, include_routing=True, include_roster=False)
            _create_test_dataset(root, "routing", "test1", wrong_hash=True)

            manager = GoldenDatasetManager(datasets_root=root)
            results = manager.validate_all()

            assert results["all_passed"] is False
            assert results["failed"] >= 1


class TestHashComputation:
    """Test hash computation functionality."""

    def test_deterministic_hash(self):
        """Should produce same hash for same data."""
        manager = GoldenDatasetManager()

        data = {"key": "value", "number": 123}
        hash1 = manager._compute_hash(data)
        hash2 = manager._compute_hash(data)

        assert hash1 == hash2

    def test_different_hash_for_different_data(self):
        """Should produce different hash for different data."""
        manager = GoldenDatasetManager()

        hash1 = manager._compute_hash({"key": "value1"})
        hash2 = manager._compute_hash({"key": "value2"})

        assert hash1 != hash2


class TestSchemas:
    """Test schema dataclasses."""

    def test_dataset_manifest_to_dict(self):
        """Should convert manifest to dict correctly."""
        from datetime import datetime, timezone

        manifest = DatasetManifest(
            name="test",
            pack="routing",
            type=DatasetType.HAPPY_PATH,
            version="1.0.0",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            created_by="test",
            description="Test dataset",
            scenario="Test scenario",
            input_size={"stops": 10},
            solver_seed=94,
            input_hash="abc123",
            expected_output_hash="def456",
            expected_kpis={"coverage": 100},
            expected_failure=None,
        )

        d = manifest.to_dict()

        assert d["name"] == "test"
        assert d["pack"] == "routing"
        assert d["type"] == "happy_path"

    def test_validation_result_to_dict(self):
        """Should convert validation result to dict correctly."""
        result = ValidationResult(
            dataset_name="test",
            pack="routing",
            passed=True,
            output_hash_match=True,
            kpi_match=True,
            audit_match=True,
            differences=[],
            solve_duration_ms=100,
            validation_duration_ms=200,
        )

        d = result.to_dict()

        assert d["dataset_name"] == "test"
        assert d["passed"] is True


# Helper functions

def _create_test_registry(root: Path, include_routing: bool, include_roster: bool):
    """Create a test registry.json."""
    registry = {
        "version": "1.0.0",
        "updated_at": "2026-01-07T00:00:00Z",
        "datasets": {
            "routing": {"happy_path": [], "known_failures": []},
            "roster": {"happy_path": [], "known_failures": []},
        },
    }

    if include_routing:
        registry["datasets"]["routing"]["happy_path"].append({
            "name": "test1",
            "path": "routing/test1",
            "description": "Test dataset",
            "version": "1.0.0",
        })

    if include_roster:
        registry["datasets"]["roster"]["happy_path"].append({
            "name": "test1",
            "path": "roster/test1",
            "description": "Test dataset",
            "version": "1.0.0",
        })

    root.mkdir(parents=True, exist_ok=True)
    with open(root / "registry.json", "w") as f:
        json.dump(registry, f)


def _create_test_dataset(root: Path, pack: str, name: str, wrong_hash: bool = False):
    """Create a test dataset directory."""
    import hashlib

    dataset_path = root / pack / name
    dataset_path.mkdir(parents=True, exist_ok=True)
    (dataset_path / "expected").mkdir(exist_ok=True)

    # Create input
    input_data = {"stops": [{"id": 1}], "vehicles": [{"id": 1}]}
    with open(dataset_path / "input.json", "w") as f:
        json.dump(input_data, f)

    # Compute hash
    canonical = json.dumps(input_data, sort_keys=True)
    input_hash = hashlib.sha256(canonical.encode()).hexdigest()

    if wrong_hash:
        input_hash = "wrong_hash_for_testing"

    # Create manifest
    manifest = {
        "name": name,
        "pack": pack,
        "type": "happy_path",
        "version": "1.0.0",
        "created_at": "2026-01-07T00:00:00Z",
        "updated_at": "2026-01-07T00:00:00Z",
        "created_by": "test",
        "description": "Test dataset",
        "scenario": "Test scenario",
        "input_size": {"stops": 1, "vehicles": 1},
        "solver_seed": 94,
        "input_hash": input_hash,
        "expected_output_hash": "",
        "expected_kpis": {"coverage": 100},
        "expected_failure": None,
    }
    with open(dataset_path / "manifest.json", "w") as f:
        json.dump(manifest, f)

    # Create expected outputs
    with open(dataset_path / "expected" / "kpis.json", "w") as f:
        json.dump({"coverage": 100}, f)

    with open(dataset_path / "expected" / "audits.json", "w") as f:
        json.dump({"coverage": "PASS"}, f)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
