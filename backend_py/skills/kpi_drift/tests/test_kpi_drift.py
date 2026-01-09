#!/usr/bin/env python3
"""
Unit tests for KPI Drift Detector (Skill 116).

Tests cover:
- DriftLevel thresholds
- Exit code mapping
- Metric drift calculation
- Baseline loading
- Baseline protection (write guards)
"""

import json
import tempfile
from pathlib import Path
import pytest

from backend_py.skills.kpi_drift import (
    KPIDriftDetector,
    DriftLevel,
    DriftResult,
    BaselineComputer,
    KPIBaseline,
    MetricBaseline,
)
from backend_py.skills.kpi_drift.baseline import BaselineProtection, InsufficientDataError


class TestDriftLevelThresholds:
    """Test drift level threshold boundaries."""

    def test_ok_level_under_10_percent(self):
        """Drift score < 10% should return OK."""
        detector = KPIDriftDetector()
        level = detector._determine_level(5.0)
        assert level == DriftLevel.OK

    def test_ok_level_at_boundary(self):
        """Drift score exactly at 10% should return WARNING."""
        detector = KPIDriftDetector()
        level = detector._determine_level(10.0)
        assert level == DriftLevel.WARNING

    def test_warning_level_10_to_25(self):
        """Drift score 10-25% should return WARNING."""
        detector = KPIDriftDetector()
        level = detector._determine_level(15.0)
        assert level == DriftLevel.WARNING

    def test_alert_level_25_to_50(self):
        """Drift score 25-50% should return ALERT."""
        detector = KPIDriftDetector()
        level = detector._determine_level(35.0)
        assert level == DriftLevel.ALERT

    def test_incident_level_above_50(self):
        """Drift score > 50% should return INCIDENT."""
        detector = KPIDriftDetector()
        level = detector._determine_level(60.0)
        assert level == DriftLevel.INCIDENT


class TestExitCodes:
    """Test exit code mapping."""

    def test_ok_exit_code_0(self):
        """OK level should have exit code 0."""
        detector = KPIDriftDetector()
        assert detector.EXIT_CODES[DriftLevel.OK] == 0

    def test_warning_exit_code_1(self):
        """WARNING level should have exit code 1."""
        detector = KPIDriftDetector()
        assert detector.EXIT_CODES[DriftLevel.WARNING] == 1

    def test_alert_exit_code_2(self):
        """ALERT level should have exit code 2."""
        detector = KPIDriftDetector()
        assert detector.EXIT_CODES[DriftLevel.ALERT] == 2

    def test_incident_exit_code_3(self):
        """INCIDENT level should have exit code 3."""
        detector = KPIDriftDetector()
        assert detector.EXIT_CODES[DriftLevel.INCIDENT] == 3


class TestMetricDriftCalculation:
    """Test per-metric drift calculation."""

    def test_zero_drift_when_values_equal(self):
        """Identical values should produce zero drift."""
        detector = KPIDriftDetector()
        drift = detector._calculate_metric_drift(
            name="test",
            current=100.0,
            mean=100.0,
            std_dev=0,
            weight=1.0,
        )
        assert drift.percent_change == 0.0
        assert drift.direction == "stable"

    def test_positive_drift_when_higher(self):
        """Higher current value should show higher direction."""
        detector = KPIDriftDetector()
        drift = detector._calculate_metric_drift(
            name="test",
            current=120.0,
            mean=100.0,
            std_dev=0,
            weight=1.0,
        )
        assert drift.percent_change == 20.0
        assert drift.direction == "higher"

    def test_negative_drift_when_lower(self):
        """Lower current value should show lower direction."""
        detector = KPIDriftDetector()
        drift = detector._calculate_metric_drift(
            name="test",
            current=80.0,
            mean=100.0,
            std_dev=0,
            weight=1.0,
        )
        assert drift.percent_change == -20.0
        assert drift.direction == "lower"

    def test_anomaly_on_large_percent_change(self):
        """Changes > 25% should be marked as anomaly."""
        detector = KPIDriftDetector()
        drift = detector._calculate_metric_drift(
            name="test",
            current=130.0,  # 30% increase
            mean=100.0,
            std_dev=0,
            weight=1.0,
        )
        assert drift.is_anomaly is True

    def test_weight_affects_weighted_drift(self):
        """Higher weight should increase weighted drift."""
        detector = KPIDriftDetector()
        drift_low = detector._calculate_metric_drift(
            name="test",
            current=120.0,
            mean=100.0,
            std_dev=0,
            weight=1.0,
        )
        drift_high = detector._calculate_metric_drift(
            name="test",
            current=120.0,
            mean=100.0,
            std_dev=0,
            weight=2.0,
        )
        assert drift_high.weighted_drift > drift_low.weighted_drift


class TestBaselineLoading:
    """Test baseline loading from JSON file."""

    def test_load_from_temp_file(self):
        """Should load baseline from JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "roster": {
                    "test_tenant": {
                        "total_drivers": 100,
                        "coverage_pct": 100.0,
                    }
                }
            }, f)
            f.flush()

            detector = KPIDriftDetector(baselines_path=Path(f.name))
            baseline = detector._load_baseline("test_tenant", "roster")

            assert baseline is not None
            assert baseline["total_drivers"] == 100
            assert baseline["coverage_pct"] == 100.0

    def test_missing_tenant_returns_none(self):
        """Missing tenant should return None."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"roster": {}}, f)
            f.flush()

            detector = KPIDriftDetector(baselines_path=Path(f.name))
            baseline = detector._load_baseline("nonexistent", "roster")

            assert baseline is None

    def test_missing_pack_returns_none(self):
        """Missing pack should return None."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"roster": {"tenant": {"value": 1}}}, f)
            f.flush()

            detector = KPIDriftDetector(baselines_path=Path(f.name))
            baseline = detector._load_baseline("tenant", "routing")

            assert baseline is None


class TestDriftResultSerialization:
    """Test DriftResult to_dict serialization."""

    def test_to_dict_contains_all_fields(self):
        """to_dict should include all DriftResult fields."""
        result = DriftResult(
            tenant_code="test",
            pack="roster",
            solve_id="solve-123",
            timestamp="2026-01-01T00:00:00Z",
            drift_score=15.0,
            drift_level=DriftLevel.WARNING,
            metric_drifts={},
            top_drifters=["drivers"],
            baseline_sample_count=10,
            baseline_computed_at="2025-12-01T00:00:00Z",
            exit_code=1,
        )

        d = result.to_dict()

        assert d["tenant_code"] == "test"
        assert d["pack"] == "roster"
        assert d["drift_score"] == 15.0
        assert d["drift_level"] == "WARNING"
        assert d["exit_code"] == 1


class TestBaselineProtection:
    """Test baseline write protection."""

    def test_automation_cannot_write(self):
        """Automation should be blocked from writing baselines."""
        protection = BaselineProtection()

        allowed, reason = protection.can_write_baseline(
            user="automation@system",
            role="AUTOMATION",
            is_automation=True,
        )

        assert allowed is False
        assert "Automation" in reason

    def test_planner_cannot_write(self):
        """PLANNER role should be blocked."""
        protection = BaselineProtection()

        allowed, reason = protection.can_write_baseline(
            user="planner@example.com",
            role="PLANNER",
            is_automation=False,
        )

        assert allowed is False
        assert "APPROVER" in reason

    def test_approver_can_write(self):
        """APPROVER role should be allowed."""
        protection = BaselineProtection()

        allowed, reason = protection.can_write_baseline(
            user="approver@example.com",
            role="APPROVER",
            is_automation=False,
        )

        assert allowed is True

    def test_tenant_admin_can_write(self):
        """TENANT_ADMIN role should be allowed."""
        protection = BaselineProtection()

        allowed, reason = protection.can_write_baseline(
            user="admin@example.com",
            role="TENANT_ADMIN",
            is_automation=False,
        )

        assert allowed is True


class TestBaselineComputer:
    """Test baseline computation."""

    def test_compute_baseline_from_history(self):
        """Should compute baseline statistics from history."""
        computer = BaselineComputer()

        history = [
            {"total_drivers": 100, "coverage_pct": 100.0},
            {"total_drivers": 105, "coverage_pct": 99.0},
            {"total_drivers": 95, "coverage_pct": 100.0},
        ]

        baseline = computer.compute_baseline_from_history(
            tenant_code="test",
            pack="roster",
            historical_kpis=history,
        )

        assert baseline.tenant_code == "test"
        assert baseline.pack == "roster"
        assert baseline.sample_count == 3
        assert "total_drivers" in baseline.metrics
        assert baseline.metrics["total_drivers"].mean == 100.0

    def test_insufficient_data_raises_error(self):
        """Should raise error if not enough data points."""
        computer = BaselineComputer()
        # Override min_samples for this test
        computer.min_samples = 5

        history = [
            {"total_drivers": 100},
            {"total_drivers": 105},
        ]

        with pytest.raises(InsufficientDataError):
            computer.compute_baseline_from_history(
                tenant_code="test",
                pack="roster",
                historical_kpis=history,
            )


class TestIntegration:
    """Integration tests for full drift check flow."""

    def test_full_drift_check_ok(self):
        """Full flow with no drift should return OK."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "roster": {
                    "gurkerl": {
                        "total_drivers": 145,
                        "coverage_pct": 100.0,
                        "fte_ratio": 1.0,
                        "max_weekly_hours": 54,
                    }
                }
            }, f)
            f.flush()

            detector = KPIDriftDetector(baselines_path=Path(f.name))
            result = detector.check_drift(
                tenant_code="gurkerl",
                pack="roster",
                current_kpis={
                    "total_drivers": 145,
                    "coverage_pct": 100.0,
                    "fte_ratio": 1.0,
                    "max_weekly_hours": 54,
                },
            )

            assert result.drift_level == DriftLevel.OK
            assert result.exit_code == 0

    def test_full_drift_check_with_drift(self):
        """Full flow with drift should return appropriate level."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "roster": {
                    "gurkerl": {
                        "total_drivers": 145,
                        "coverage_pct": 100.0,
                    }
                }
            }, f)
            f.flush()

            detector = KPIDriftDetector(baselines_path=Path(f.name))
            result = detector.check_drift(
                tenant_code="gurkerl",
                pack="roster",
                current_kpis={
                    "total_drivers": 160,  # ~10% drift
                    "coverage_pct": 95.0,  # 5% drift
                },
            )

            # With no std_dev in baseline, any deviation triggers z_score=3
            # which results in higher drift scores - verify non-OK response
            assert result.drift_level != DriftLevel.OK
            assert result.exit_code > 0
            assert len(result.top_drifters) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
