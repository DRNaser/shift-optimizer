# =============================================================================
# SOLVEREIGN Routing Pack - Golden Dataset Regression Tests
# =============================================================================
# Tests for verifying determinism and consistency of the Wien Pilot pipeline.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_golden_dataset_regression.py -v
# =============================================================================

import pytest
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Import components under test
from backend_py.packs.routing.importers.fls_canonicalize import (
    FLSCanonicalizer,
    CanonicalizeResult,
)
from backend_py.packs.routing.importers.fls_validate import (
    FLSValidator,
    ValidationResult,
    GateVerdict,
)
from backend_py.packs.routing.services.finalize.coords_quality_gate import (
    CoordsQualityGate,
    CoordsQualityPolicy,
    CoordsQualityResult,
    CoordsVerdict,
)


# =============================================================================
# FIXTURES
# =============================================================================

GOLDEN_DATASET_PATH = Path(__file__).parent.parent.parent.parent.parent / \
    "golden_datasets" / "routing" / "wien_pilot_46_vehicles"


@pytest.fixture
def golden_input() -> Dict[str, Any]:
    """Load the golden input file."""
    input_path = GOLDEN_DATASET_PATH / "wien_pilot_small.json"
    if not input_path.exists():
        pytest.skip(f"Golden dataset not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def expected_canonical() -> Dict[str, Any]:
    """Load expected canonical output."""
    expected_path = GOLDEN_DATASET_PATH / "expected_canonical.json"
    if not expected_path.exists():
        pytest.skip(f"Expected canonical not found: {expected_path}")

    with open(expected_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def expected_manifest() -> Dict[str, Any]:
    """Load expected manifest structure."""
    manifest_path = GOLDEN_DATASET_PATH / "expected_manifest.json"
    if not manifest_path.exists():
        pytest.skip(f"Expected manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def canonicalizer() -> FLSCanonicalizer:
    """Create canonicalizer instance."""
    return FLSCanonicalizer()


@pytest.fixture
def validator() -> FLSValidator:
    """Create validator instance."""
    return FLSValidator()


@pytest.fixture
def coords_gate() -> CoordsQualityGate:
    """Create coords quality gate with Wien pilot policy."""
    policy = CoordsQualityPolicy(
        ok_missing_latlng_max=0.00,
        ok_fallback_rate_max=0.00,
        warn_missing_latlng_max=0.10,
        warn_fallback_rate_max=0.10,
        block_missing_latlng_max=0.25,
        block_fallback_rate_max=0.25,
        block_unresolved_max=0,
        allow_zone_fallback=True,
        allow_h3_fallback=True,
        strict_mode=True,
    )
    return CoordsQualityGate(policy)


# =============================================================================
# HASH STABILITY TESTS (Determinism)
# =============================================================================

class TestHashStability:
    """Tests for hash determinism - same input MUST produce same hash."""

    def test_canonical_hash_determinism(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Same input produces identical canonical_hash across multiple runs."""
        # Run canonicalization 3 times
        hashes = []
        for _ in range(3):
            result = canonicalizer.canonicalize(golden_input)
            assert result.success, f"Canonicalization failed: {result.errors}"
            hashes.append(result.canonical_import.canonical_hash)

        # All hashes must be identical
        assert len(set(hashes)) == 1, f"Hash mismatch across runs: {hashes}"

    def test_raw_hash_determinism(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Same input produces identical raw_hash across multiple runs."""
        hashes = []
        for _ in range(3):
            result = canonicalizer.canonicalize(golden_input)
            assert result.success
            hashes.append(result.canonical_import.raw_hash)

        assert len(set(hashes)) == 1, f"Raw hash mismatch: {hashes}"

    def test_canonical_hash_changes_with_input(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Different input produces different canonical_hash."""
        # First run
        result1 = canonicalizer.canonicalize(golden_input)
        assert result1.success

        # Modify input
        modified_input = json.loads(json.dumps(golden_input))
        modified_input["orders"][0]["service_seconds"] = 999

        # Second run with modified input
        result2 = canonicalizer.canonicalize(modified_input)
        assert result2.success

        # Hashes must be different
        assert result1.canonical_import.canonical_hash != \
               result2.canonical_import.canonical_hash


# =============================================================================
# CANONICALIZATION TESTS
# =============================================================================

class TestCanonicalization:
    """Tests for canonicalization correctness."""

    def test_order_count(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Canonicalization produces expected order count."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        expected_count = expected_canonical["expected_stats"]["total_orders"]
        actual_count = len(result.canonical_import.orders)

        assert actual_count == expected_count, \
            f"Order count mismatch: expected {expected_count}, got {actual_count}"

    def test_orders_with_coords(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Correct number of orders with direct coords."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        expected = expected_canonical["expected_stats"]["orders_with_coords"]
        actual = sum(1 for o in result.canonical_import.orders
                    if o.lat is not None and o.lng is not None)

        assert actual == expected, \
            f"Orders with coords mismatch: expected {expected}, got {actual}"

    def test_orders_with_zone(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Correct number of orders with zone fallback."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        expected = expected_canonical["expected_stats"]["orders_with_zone"]
        actual = sum(1 for o in result.canonical_import.orders
                    if o.zone_id is not None and o.lat is None)

        assert actual == expected, \
            f"Orders with zone mismatch: expected {expected}, got {actual}"

    def test_orders_with_h3(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Correct number of orders with H3 fallback."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        expected = expected_canonical["expected_stats"]["orders_with_h3"]
        actual = sum(1 for o in result.canonical_import.orders
                    if o.h3_index is not None and o.lat is None)

        assert actual == expected, \
            f"Orders with H3 mismatch: expected {expected}, got {actual}"

    def test_no_duplicates(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """No duplicate order IDs after canonicalization."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        order_ids = [o.order_id for o in result.canonical_import.orders]

        assert len(order_ids) == len(set(order_ids)), \
            f"Duplicate order IDs found: {[x for x in order_ids if order_ids.count(x) > 1]}"

    def test_timezone_normalization(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Time windows are normalized to UTC."""
        result = canonicalizer.canonicalize(golden_input)
        assert result.success

        # ORD-001: tw_start is 08:00 Vienna = 07:00 UTC (winter time)
        ord_001 = next(o for o in result.canonical_import.orders
                       if o.order_id == "ORD-001")

        # Check hour is 7 (UTC) not 8 (Vienna)
        assert ord_001.tw_start.hour == 7, \
            f"Expected tw_start hour 7 (UTC), got {ord_001.tw_start.hour}"


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestValidation:
    """Tests for validation correctness."""

    def test_validation_passes_golden_input(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        validator: FLSValidator,
    ):
        """Golden input passes validation with expected verdict."""
        can_result = canonicalizer.canonicalize(golden_input)
        assert can_result.success

        val_result = validator.validate(can_result.canonical_import)
        expected_verdict = expected_canonical["expected_verdicts"]["validation"]["verdict"]

        assert val_result.verdict.name == expected_verdict, \
            f"Validation verdict mismatch: expected {expected_verdict}, got {val_result.verdict.name}"

    def test_hard_gates_pass(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        validator: FLSValidator,
    ):
        """All hard gates pass for golden input."""
        can_result = canonicalizer.canonicalize(golden_input)
        val_result = validator.validate(can_result.canonical_import)

        hard_gates = ["ORDER_ID", "TIME_WINDOW", "COORDS_PRESENCE"]
        for gate_name in hard_gates:
            gate_result = next(
                (g for g in val_result.gate_results if gate_name in g.gate_id),
                None
            )
            if gate_result:
                assert gate_result.verdict != GateVerdict.BLOCK, \
                    f"Hard gate {gate_name} BLOCKED: {gate_result.message}"

    def test_validation_determinism(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        validator: FLSValidator,
    ):
        """Validation produces same results across runs."""
        can_result = canonicalizer.canonicalize(golden_input)

        verdicts = []
        for _ in range(3):
            val_result = validator.validate(can_result.canonical_import)
            verdicts.append(val_result.verdict.name)

        assert len(set(verdicts)) == 1, f"Verdict mismatch: {verdicts}"


# =============================================================================
# COORDS QUALITY GATE TESTS
# =============================================================================

class TestCoordsQualityGate:
    """Tests for coords quality gate (STOP-5)."""

    def test_coords_gate_verdict(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        coords_gate: CoordsQualityGate,
    ):
        """Coords gate produces expected verdict."""
        can_result = canonicalizer.canonicalize(golden_input)
        assert can_result.success

        # Mock resolvers that can resolve zone and h3
        def zone_resolver(zone_id: str) -> Optional[tuple]:
            zones = {
                "1220": (48.2300, 16.4400),  # Donaustadt
            }
            return zones.get(zone_id)

        def h3_resolver(h3_index: str) -> Optional[tuple]:
            h3_map = {
                "881f1d4813fffff": (48.1900, 16.3700),  # Landstrasse
            }
            return h3_map.get(h3_index)

        coords_result = coords_gate.evaluate(
            orders=can_result.canonical_import.orders,
            zone_resolver=zone_resolver,
            h3_resolver=h3_resolver,
        )

        expected_verdict = expected_canonical["expected_verdicts"]["coords_quality"]["verdict"]

        assert coords_result.verdict.name == expected_verdict, \
            f"Coords gate verdict mismatch: expected {expected_verdict}, got {coords_result.verdict.name}"

    def test_osrm_finalize_allowed(
        self,
        golden_input: Dict[str, Any],
        expected_canonical: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        coords_gate: CoordsQualityGate,
    ):
        """OSRM finalize is allowed/blocked based on coords quality."""
        can_result = canonicalizer.canonicalize(golden_input)

        def zone_resolver(zone_id: str) -> Optional[tuple]:
            return (48.2300, 16.4400) if zone_id else None

        def h3_resolver(h3_index: str) -> Optional[tuple]:
            return (48.1900, 16.3700) if h3_index else None

        coords_result = coords_gate.evaluate(
            orders=can_result.canonical_import.orders,
            zone_resolver=zone_resolver,
            h3_resolver=h3_resolver,
        )

        expected_osrm = expected_canonical["expected_verdicts"]["coords_quality"]["allows_osrm_finalize"]

        assert coords_result.allows_osrm_finalize == expected_osrm, \
            f"OSRM finalize mismatch: expected {expected_osrm}, got {coords_result.allows_osrm_finalize}"

    def test_unresolved_blocks(
        self,
        canonicalizer: FLSCanonicalizer,
        coords_gate: CoordsQualityGate,
    ):
        """Unresolved orders cause BLOCK in strict mode."""
        # Create input with unresolvable order
        bad_input = {
            "import_metadata": {
                "source": "FLS",
                "export_timestamp": "2026-01-08T06:00:00+01:00",
                "tenant_id": 1,
                "site_id": 1,
            },
            "orders": [
                {
                    "order_id": "BAD-001",
                    "tw_start": "2026-01-08T08:00:00+01:00",
                    "tw_end": "2026-01-08T10:00:00+01:00",
                    "zone_id": "9999",  # Non-existent zone
                }
            ]
        }

        can_result = canonicalizer.canonicalize(bad_input)

        # Resolver returns None for unknown zone
        def zone_resolver(zone_id: str) -> Optional[tuple]:
            return None

        def h3_resolver(h3_index: str) -> Optional[tuple]:
            return None

        coords_result = coords_gate.evaluate(
            orders=can_result.canonical_import.orders,
            zone_resolver=zone_resolver,
            h3_resolver=h3_resolver,
        )

        assert coords_result.verdict == CoordsVerdict.BLOCK, \
            f"Expected BLOCK for unresolved, got {coords_result.verdict.name}"
        assert not coords_result.allows_osrm_finalize


# =============================================================================
# MANIFEST STRUCTURE TESTS
# =============================================================================

class TestManifestStructure:
    """Tests for manifest structure compliance."""

    def test_required_root_keys(self, expected_manifest: Dict[str, Any]):
        """Verify expected manifest defines required root keys."""
        required_keys = expected_manifest["required_keys"]["root"]

        assert "import_run_id" in required_keys
        assert "plan_id" in required_keys
        assert "verdicts" in required_keys
        assert "artifacts" in required_keys

    def test_required_verdict_keys(self, expected_manifest: Dict[str, Any]):
        """Verify expected manifest defines required verdict keys."""
        verdict_keys = expected_manifest["required_keys"]["verdicts"]

        assert "import" in verdict_keys
        assert "coords_quality" in verdict_keys
        assert "drift_gate" in verdict_keys
        assert "final" in verdict_keys

    def test_artifact_structure(self, expected_manifest: Dict[str, Any]):
        """Verify artifact structure requirements."""
        artifacts = expected_manifest["artifact_structure"]

        # Raw blob must have hash
        assert "hash" in artifacts["raw_blob"]["required_fields"]

        # Canonical orders must have order count
        assert "order_count" in artifacts["canonical_orders"]["required_fields"]

        # Validation report must have verdict
        assert "verdict" in artifacts["validation_report"]["required_fields"]

    def test_pipeline_stages(self, expected_manifest: Dict[str, Any]):
        """Verify pipeline stage definitions."""
        stages = expected_manifest["pipeline_stages"]

        stage_names = [s["name"] for s in stages]
        assert "import" in stage_names
        assert "coords_quality" in stage_names
        assert "solve" in stage_names
        assert "finalize" in stage_names
        assert "audit" in stage_names


# =============================================================================
# REGRESSION INVARIANTS
# =============================================================================

class TestRegressionInvariants:
    """Tests for regression invariants that must never break."""

    def test_same_input_same_output(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
        validator: FLSValidator,
    ):
        """Invariant: Same input ALWAYS produces same canonical hash and verdict."""
        results = []
        for i in range(5):
            can_result = canonicalizer.canonicalize(golden_input)
            val_result = validator.validate(can_result.canonical_import)
            results.append({
                "canonical_hash": can_result.canonical_import.canonical_hash,
                "verdict": val_result.verdict.name,
            })

        # All must be identical
        hashes = [r["canonical_hash"] for r in results]
        verdicts = [r["verdict"] for r in results]

        assert len(set(hashes)) == 1, f"Hash instability: {hashes}"
        assert len(set(verdicts)) == 1, f"Verdict instability: {verdicts}"

    def test_order_preservation(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Invariant: Order of orders is preserved during canonicalization."""
        can_result = canonicalizer.canonicalize(golden_input)

        input_ids = [o["order_id"] for o in golden_input["orders"]]
        output_ids = [o.order_id for o in can_result.canonical_import.orders]

        assert input_ids == output_ids, "Order sequence not preserved"

    def test_metadata_preservation(
        self,
        golden_input: Dict[str, Any],
        canonicalizer: FLSCanonicalizer,
    ):
        """Invariant: Import metadata is preserved."""
        can_result = canonicalizer.canonicalize(golden_input)

        assert can_result.canonical_import.tenant_id == \
               golden_input["import_metadata"]["tenant_id"]
        assert can_result.canonical_import.site_id == \
               golden_input["import_metadata"]["site_id"]
        assert can_result.canonical_import.source == \
               golden_input["import_metadata"]["source"]
