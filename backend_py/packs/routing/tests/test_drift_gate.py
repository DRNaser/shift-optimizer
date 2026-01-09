# =============================================================================
# SOLVEREIGN Routing Pack - Drift Gate Tests
# =============================================================================
# Tests for drift gate policy enforcement.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_drift_gate.py -v
# =============================================================================

from datetime import datetime

import pytest

from backend_py.packs.routing.services.finalize.drift_gate import (
    DriftGate,
    DriftGatePolicy,
    DriftGateResult,
    DriftGateError,
)
from backend_py.packs.routing.services.finalize.drift_detector import DriftReport
from backend_py.packs.routing.services.finalize.tw_validator import TWValidationResult
from backend_py.packs.routing.services.finalize.fallback_tracker import FallbackReport


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def default_policy() -> DriftGatePolicy:
    """Default drift gate policy."""
    return DriftGatePolicy()


@pytest.fixture
def strict_policy() -> DriftGatePolicy:
    """Strict policy with lower thresholds."""
    return DriftGatePolicy(
        ok_p95_ratio_max=1.10,
        ok_tw_violations_max=0,
        ok_timeout_rate_max=0.01,
        warn_p95_ratio_max=1.20,
        warn_tw_violations_max=1,
        warn_timeout_rate_max=0.05,
    )


@pytest.fixture
def relaxed_policy() -> DriftGatePolicy:
    """Relaxed policy with higher thresholds."""
    return DriftGatePolicy(
        ok_p95_ratio_max=1.30,
        ok_tw_violations_max=5,
        ok_timeout_rate_max=0.10,
        warn_p95_ratio_max=1.50,
        warn_tw_violations_max=10,
        warn_timeout_rate_max=0.20,
    )


@pytest.fixture
def ok_drift_report() -> DriftReport:
    """Drift report that should pass OK threshold."""
    return DriftReport(
        plan_id='plan_1',
        matrix_version='v1',
        osrm_map_hash='abc123',
        computed_at=datetime.now(),
        total_legs=100,
        legs_with_osrm=98,
        legs_with_timeout=1,
        legs_with_fallback=1,
        mean_ratio=1.05,
        median_ratio=1.04,
        p95_ratio=1.12,
        max_ratio=1.25,
        min_ratio=0.90,
        std_ratio=0.05,
    )


@pytest.fixture
def warn_drift_report() -> DriftReport:
    """Drift report that should trigger WARN."""
    return DriftReport(
        plan_id='plan_1',
        matrix_version='v1',
        osrm_map_hash='abc123',
        computed_at=datetime.now(),
        total_legs=100,
        legs_with_osrm=95,
        legs_with_timeout=3,
        legs_with_fallback=2,
        mean_ratio=1.18,
        median_ratio=1.15,
        p95_ratio=1.22,  # Above ok_p95_ratio_max (1.15), below warn (1.30)
        max_ratio=1.45,
        min_ratio=0.85,
        std_ratio=0.10,
    )


@pytest.fixture
def block_drift_report() -> DriftReport:
    """Drift report that should trigger BLOCK."""
    return DriftReport(
        plan_id='plan_1',
        matrix_version='v1',
        osrm_map_hash='abc123',
        computed_at=datetime.now(),
        total_legs=100,
        legs_with_osrm=80,
        legs_with_timeout=15,
        legs_with_fallback=5,
        mean_ratio=1.35,
        median_ratio=1.30,
        p95_ratio=1.45,  # Above warn_p95_ratio_max (1.30)
        max_ratio=2.50,
        min_ratio=0.70,
        std_ratio=0.25,
    )


@pytest.fixture
def ok_tw_validation() -> TWValidationResult:
    """TW validation with no violations."""
    return TWValidationResult(
        plan_id='plan_1',
        validated_at=datetime.now(),
        routes_validated=10,
        stops_checked=50,
        violations_count=0,
        violations=[],
        total_violation_seconds=0,
        max_violation_seconds=0,
    )


@pytest.fixture
def warn_tw_validation() -> TWValidationResult:
    """TW validation with warnings."""
    return TWValidationResult(
        plan_id='plan_1',
        validated_at=datetime.now(),
        routes_validated=10,
        stops_checked=50,
        violations_count=2,  # Above ok (0), below warn (3)
        violations=[],
        total_violation_seconds=600,
        max_violation_seconds=300,
    )


@pytest.fixture
def block_tw_validation() -> TWValidationResult:
    """TW validation that should block."""
    return TWValidationResult(
        plan_id='plan_1',
        validated_at=datetime.now(),
        routes_validated=10,
        stops_checked=50,
        violations_count=5,  # Above warn (3)
        violations=[],
        total_violation_seconds=3000,
        max_violation_seconds=1200,
    )


@pytest.fixture
def ok_fallback_report() -> FallbackReport:
    """Fallback report with low rates."""
    return FallbackReport(
        plan_id='plan_1',
        generated_at=datetime.now(),
        total_legs=100,
        fallback_count=1,
        timeout_count=1,
        error_count=0,
    )


@pytest.fixture
def warn_fallback_report() -> FallbackReport:
    """Fallback report that triggers warning."""
    return FallbackReport(
        plan_id='plan_1',
        generated_at=datetime.now(),
        total_legs=100,
        fallback_count=8,  # 8% > ok (5%), < warn (15%)
        timeout_count=5,   # 5% > ok (2%), < warn (10%)
        error_count=3,
    )


@pytest.fixture
def block_fallback_report() -> FallbackReport:
    """Fallback report that triggers block."""
    return FallbackReport(
        plan_id='plan_1',
        generated_at=datetime.now(),
        total_legs=100,
        fallback_count=20,  # 20% > warn (15%)
        timeout_count=15,   # 15% > warn (10%)
        error_count=5,
    )


# =============================================================================
# POLICY TESTS
# =============================================================================

class TestDriftGatePolicy:
    """Tests for DriftGatePolicy configuration."""

    def test_default_policy_values(self, default_policy):
        """Test default policy has expected values."""
        assert default_policy.ok_p95_ratio_max == 1.15
        assert default_policy.ok_tw_violations_max == 0
        assert default_policy.ok_timeout_rate_max == 0.02
        assert default_policy.warn_p95_ratio_max == 1.30
        assert default_policy.warn_tw_violations_max == 3
        assert default_policy.warn_timeout_rate_max == 0.10

    def test_policy_to_dict(self, default_policy):
        """Test policy serialization."""
        data = default_policy.to_dict()

        assert 'ok_thresholds' in data
        assert 'warn_thresholds' in data
        assert 'hard_limits' in data
        assert 'feature_flags' in data
        assert data['ok_thresholds']['p95_ratio_max'] == 1.15


# =============================================================================
# OK VERDICT TESTS
# =============================================================================

class TestOkVerdict:
    """Tests for OK verdict scenarios."""

    def test_all_ok_metrics(
        self,
        default_policy,
        ok_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test OK verdict when all metrics pass."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "OK"
        assert result.is_allowed is True
        assert result.is_blocked is False
        assert len(result.reasons) == 1
        assert "passed" in result.reasons[0].lower()

    def test_ok_with_relaxed_policy(
        self,
        relaxed_policy,
        warn_drift_report,
        warn_tw_validation,
        warn_fallback_report,
    ):
        """Test OK verdict with relaxed policy."""
        gate = DriftGate(relaxed_policy)
        result = gate.evaluate(
            drift_report=warn_drift_report,
            tw_validation=warn_tw_validation,
            fallback_report=warn_fallback_report,
        )

        # With relaxed policy, these should pass OK
        assert result.verdict == "OK"

    def test_ok_with_no_data_optional(self):
        """Test OK when data is optional and not provided."""
        policy = DriftGatePolicy(
            require_drift_report=False,
            require_tw_validation=False,
        )
        gate = DriftGate(policy)
        result = gate.evaluate()

        assert result.verdict == "OK"


# =============================================================================
# WARN VERDICT TESTS
# =============================================================================

class TestWarnVerdict:
    """Tests for WARN verdict scenarios."""

    def test_warn_on_p95_drift(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test WARN when P95 drift exceeds OK threshold."""
        drift_report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=100,
            legs_with_osrm=98,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.10,
            median_ratio=1.08,
            p95_ratio=1.20,  # Above ok (1.15), below warn (1.30)
            max_ratio=1.40,
            min_ratio=0.90,
            std_ratio=0.08,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "WARN"
        assert "P95 drift ratio" in result.warnings[0]

    def test_warn_on_tw_violations(
        self,
        default_policy,
        ok_drift_report,
        ok_fallback_report,
    ):
        """Test WARN when TW violations exceed OK threshold."""
        tw_validation = TWValidationResult(
            plan_id='plan_1',
            validated_at=datetime.now(),
            routes_validated=10,
            stops_checked=50,
            violations_count=2,  # Above ok (0), below warn (3)
            violations=[],
            total_violation_seconds=500,
            max_violation_seconds=250,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "WARN"
        assert "TW violations" in result.warnings[0]

    def test_warn_on_timeout_rate(
        self,
        default_policy,
        ok_drift_report,
        ok_tw_validation,
    ):
        """Test WARN when timeout rate exceeds OK threshold."""
        fallback_report = FallbackReport(
            plan_id='plan_1',
            generated_at=datetime.now(),
            total_legs=100,
            fallback_count=3,
            timeout_count=5,  # 5% > ok (2%), < warn (10%)
            error_count=0,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=fallback_report,
        )

        assert result.verdict == "WARN"
        assert "Timeout rate" in result.warnings[0]

    def test_warn_multiple_issues(
        self,
        default_policy,
        warn_drift_report,
        warn_tw_validation,
        warn_fallback_report,
    ):
        """Test WARN with multiple threshold exceedances."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=warn_drift_report,
            tw_validation=warn_tw_validation,
            fallback_report=warn_fallback_report,
        )

        assert result.verdict == "WARN"
        assert len(result.warnings) >= 2  # Multiple issues


# =============================================================================
# BLOCK VERDICT TESTS
# =============================================================================

class TestBlockVerdict:
    """Tests for BLOCK verdict scenarios."""

    def test_block_on_high_p95_drift(
        self,
        default_policy,
        block_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test BLOCK when P95 drift exceeds WARN threshold."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=block_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert result.is_blocked is True
        assert "P95 drift ratio" in result.reasons[0]
        assert "BLOCK" in result.reasons[0]

    def test_block_on_tw_violations(
        self,
        default_policy,
        ok_drift_report,
        block_tw_validation,
        ok_fallback_report,
    ):
        """Test BLOCK when TW violations exceed WARN threshold."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=block_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert "TW violations" in result.reasons[0]

    def test_block_on_timeout_rate(
        self,
        default_policy,
        ok_drift_report,
        ok_tw_validation,
        block_fallback_report,
    ):
        """Test BLOCK when timeout rate exceeds WARN threshold."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=block_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert "Timeout rate" in result.reasons[0]

    def test_block_on_hard_limit_max_ratio(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test BLOCK when max ratio exceeds hard limit."""
        drift_report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=100,
            legs_with_osrm=98,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.10,
            median_ratio=1.08,
            p95_ratio=1.10,  # OK threshold
            max_ratio=3.5,   # Above hard limit (3.0)
            min_ratio=0.90,
            std_ratio=0.20,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert "hard limit" in result.reasons[0].lower()

    def test_block_on_hard_limit_tw_violation(
        self,
        default_policy,
        ok_drift_report,
        ok_fallback_report,
    ):
        """Test BLOCK when TW violation seconds exceed hard limit."""
        tw_validation = TWValidationResult(
            plan_id='plan_1',
            validated_at=datetime.now(),
            routes_validated=10,
            stops_checked=50,
            violations_count=1,
            violations=[],
            total_violation_seconds=5000,
            max_violation_seconds=4000,  # Above hard limit (3600s)
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert "hard limit" in result.reasons[0].lower()

    def test_block_on_missing_required_drift_report(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test BLOCK when required drift report is missing."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=None,  # Missing
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
        assert "Drift report is required" in result.reasons[0]


# =============================================================================
# CHECK AND RAISE TESTS
# =============================================================================

class TestCheckAndRaise:
    """Tests for check_and_raise method."""

    def test_check_and_raise_ok(
        self,
        default_policy,
        ok_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test check_and_raise returns result on OK."""
        gate = DriftGate(default_policy)
        result = gate.check_and_raise(
            drift_report=ok_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "OK"
        assert result.is_allowed

    def test_check_and_raise_warn(
        self,
        default_policy,
        warn_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test check_and_raise returns result on WARN (default)."""
        gate = DriftGate(default_policy)
        result = gate.check_and_raise(
            drift_report=warn_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "WARN"
        assert result.is_allowed

    def test_check_and_raise_warn_raises_when_configured(
        self,
        warn_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test check_and_raise raises on WARN when configured."""
        policy = DriftGatePolicy(raise_on_warn=True)
        gate = DriftGate(policy)

        with pytest.raises(DriftGateError) as exc_info:
            gate.check_and_raise(
                drift_report=warn_drift_report,
                tw_validation=ok_tw_validation,
                fallback_report=ok_fallback_report,
            )

        assert exc_info.value.verdict == "WARN"

    def test_check_and_raise_block_raises(
        self,
        default_policy,
        block_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test check_and_raise raises DriftGateError on BLOCK."""
        gate = DriftGate(default_policy)

        with pytest.raises(DriftGateError) as exc_info:
            gate.check_and_raise(
                drift_report=block_drift_report,
                tw_validation=ok_tw_validation,
                fallback_report=ok_fallback_report,
            )

        assert exc_info.value.verdict == "BLOCK"
        assert len(exc_info.value.reasons) > 0


# =============================================================================
# DRIFT GATE ERROR TESTS
# =============================================================================

class TestDriftGateError:
    """Tests for DriftGateError exception."""

    def test_error_attributes(self, block_drift_report, ok_tw_validation):
        """Test DriftGateError attributes."""
        error = DriftGateError(
            message="Test error",
            verdict="BLOCK",
            reasons=["Reason 1", "Reason 2"],
            drift_report=block_drift_report,
            tw_validation=ok_tw_validation,
        )

        assert str(error) == "Test error"
        assert error.verdict == "BLOCK"
        assert len(error.reasons) == 2
        assert error.drift_report is not None

    def test_error_to_dict(self, block_drift_report, ok_tw_validation, ok_fallback_report):
        """Test DriftGateError serialization."""
        error = DriftGateError(
            message="Test error",
            verdict="BLOCK",
            reasons=["Reason 1"],
            drift_report=block_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        data = error.to_dict()

        assert data['error'] == 'DriftGateError'
        assert data['verdict'] == 'BLOCK'
        assert len(data['reasons']) == 1
        assert data['drift_report'] is not None


# =============================================================================
# RESULT TESTS
# =============================================================================

class TestDriftGateResult:
    """Tests for DriftGateResult dataclass."""

    def test_result_to_dict(
        self,
        default_policy,
        ok_drift_report,
        ok_tw_validation,
        ok_fallback_report,
    ):
        """Test result serialization."""
        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=ok_drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        data = result.to_dict()

        assert 'verdict' in data
        assert 'is_allowed' in data
        assert 'metrics' in data
        assert 'policy' in data
        assert data['verdict'] == 'OK'

    def test_result_properties(self):
        """Test result properties."""
        result_ok = DriftGateResult(verdict="OK")
        result_warn = DriftGateResult(verdict="WARN")
        result_block = DriftGateResult(verdict="BLOCK")

        assert result_ok.is_allowed is True
        assert result_ok.is_blocked is False

        assert result_warn.is_allowed is True
        assert result_warn.is_blocked is False

        assert result_block.is_allowed is False
        assert result_block.is_blocked is True


# =============================================================================
# BOUNDARY TESTS
# =============================================================================

class TestBoundaryValues:
    """Tests for boundary values at thresholds."""

    def test_exactly_at_ok_threshold(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test verdict when exactly at OK threshold."""
        drift_report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=100,
            legs_with_osrm=98,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.10,
            median_ratio=1.08,
            p95_ratio=1.15,  # Exactly at OK threshold
            max_ratio=1.20,
            min_ratio=0.90,
            std_ratio=0.05,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        # At the threshold should pass OK
        assert result.verdict == "OK"

    def test_just_above_ok_threshold(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test WARN when just above OK threshold."""
        drift_report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=100,
            legs_with_osrm=98,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.10,
            median_ratio=1.08,
            p95_ratio=1.16,  # Just above OK threshold (1.15)
            max_ratio=1.20,
            min_ratio=0.90,
            std_ratio=0.05,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "WARN"

    def test_just_above_warn_threshold(self, default_policy, ok_tw_validation, ok_fallback_report):
        """Test BLOCK when just above WARN threshold."""
        drift_report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=100,
            legs_with_osrm=98,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.20,
            median_ratio=1.18,
            p95_ratio=1.31,  # Just above WARN threshold (1.30)
            max_ratio=1.50,
            min_ratio=0.90,
            std_ratio=0.10,
        )

        gate = DriftGate(default_policy)
        result = gate.evaluate(
            drift_report=drift_report,
            tw_validation=ok_tw_validation,
            fallback_report=ok_fallback_report,
        )

        assert result.verdict == "BLOCK"
