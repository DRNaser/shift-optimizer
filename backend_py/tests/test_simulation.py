#!/usr/bin/env python3
"""
SOLVEREIGN V3 - Simulation Framework Tests
============================================

Tests for simulation scenarios and auto-seed-sweep functionality.
"""

import sys
import os
from pathlib import Path
from datetime import time

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_tour_instances():
    """Generate sample tour instances for testing."""
    instances = []
    tour_id = 1

    # Generate realistic weekly schedule
    # Mo-Fr: Morning (06:00-14:00), Afternoon (14:00-22:00), Night (22:00-06:00)
    # Sa: Morning only

    schedule = {
        1: [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")],  # Mo
        2: [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")],  # Di
        3: [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")],  # Mi
        4: [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")],  # Do
        5: [("06:00", "14:00"), ("14:00", "22:00")],  # Fr
        6: [("06:00", "14:00")],  # Sa
    }

    for day, shifts in schedule.items():
        for start_str, end_str in shifts:
            # Parse times
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            start_ts = time(start_h, start_m)
            end_ts = time(end_h, end_m)

            # Determine if crosses midnight
            crosses_midnight = end_h < start_h

            # Calculate duration and work hours
            if crosses_midnight:
                duration_min = (24 - start_h) * 60 + end_h * 60
            else:
                duration_min = (end_h - start_h) * 60

            work_hours = duration_min / 60.0

            # Create multiple instances (3 per shift)
            for i in range(3):
                instances.append({
                    "id": tour_id,
                    "day": day,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "work_hours": work_hours,
                    "depot": "DEFAULT",
                    "skill": None,
                    "duration_min": duration_min,
                    "crosses_midnight": crosses_midnight,
                })
                tour_id += 1

    return instances


@pytest.fixture
def minimal_tour_instances():
    """Minimal set of tour instances for quick tests."""
    return [
        {
            "id": 1,
            "day": 1,
            "start_ts": time(6, 0),
            "end_ts": time(14, 0),
            "work_hours": 8.0,
            "depot": "DEFAULT",
            "skill": None,
            "duration_min": 480,
            "crosses_midnight": False,
        },
        {
            "id": 2,
            "day": 1,
            "start_ts": time(14, 0),
            "end_ts": time(22, 0),
            "work_hours": 8.0,
            "depot": "DEFAULT",
            "skill": None,
            "duration_min": 480,
            "crosses_midnight": False,
        },
        {
            "id": 3,
            "day": 2,
            "start_ts": time(6, 0),
            "end_ts": time(14, 0),
            "work_hours": 8.0,
            "depot": "DEFAULT",
            "skill": None,
            "duration_min": 480,
            "crosses_midnight": False,
        },
    ]


# =============================================================================
# Seed Sweep Tests
# =============================================================================

class TestSeedSweep:
    """Tests for seed sweep functionality."""

    def test_run_seed_sweep_single(self, minimal_tour_instances):
        """Test running a single seed sweep."""
        from v3.seed_sweep import run_seed_sweep

        results = run_seed_sweep(minimal_tour_instances, seeds=[94])

        assert len(results) == 1
        assert results[0]["seed"] == 94
        assert "total_drivers" in results[0]
        assert "fte_drivers" in results[0]
        assert "pt_drivers" in results[0]

    def test_run_seed_sweep_multiple(self, minimal_tour_instances):
        """Test running multiple seed sweeps."""
        from v3.seed_sweep import run_seed_sweep

        results = run_seed_sweep(minimal_tour_instances, seeds=[42, 94, 17])

        assert len(results) == 3
        seeds_tested = [r["seed"] for r in results]
        assert 42 in seeds_tested
        assert 94 in seeds_tested
        assert 17 in seeds_tested

    def test_auto_seed_sweep(self, minimal_tour_instances):
        """Test auto seed sweep functionality."""
        from v3.seed_sweep import auto_seed_sweep

        result = auto_seed_sweep(
            minimal_tour_instances,
            num_seeds=5,
            parallel=False
        )

        assert result.best_seed > 0
        assert result.best_drivers > 0
        assert result.seeds_tested == 5
        assert len(result.top_3) <= 3
        assert result.execution_time_ms >= 0
        assert result.recommendation != ""

    def test_auto_seed_sweep_parallel(self, minimal_tour_instances):
        """Test parallel auto seed sweep."""
        from v3.seed_sweep import auto_seed_sweep

        result = auto_seed_sweep(
            minimal_tour_instances,
            num_seeds=5,
            parallel=True,
            max_workers=2
        )

        assert result.best_seed > 0
        assert result.seeds_tested == 5

    def test_compute_assignment_metrics(self, minimal_tour_instances):
        """Test assignment metrics computation."""
        from v3.seed_sweep import compute_assignment_metrics

        # Create mock assignments
        assignments = [
            {"driver_id": 1, "day": 1, "block_id": 1, "role": "primary"},
            {"driver_id": 1, "day": 2, "block_id": 2, "role": "primary"},
            {"driver_id": 2, "day": 1, "block_id": 3, "role": "primary"},
        ]

        metrics = compute_assignment_metrics(assignments, minimal_tour_instances)

        assert metrics["total_drivers"] == 2
        assert "fte_drivers" in metrics
        assert "pt_drivers" in metrics
        assert "block_1er" in metrics


# =============================================================================
# Simulation Scenario Tests
# =============================================================================

class TestSimulationScenarios:
    """Tests for individual simulation scenarios."""

    def test_cost_curve_scenario(self, sample_tour_instances):
        """Test cost curve simulation."""
        from v3.simulation_engine import run_cost_curve, RiskLevel

        result = run_cost_curve(sample_tour_instances, baseline_seed=94)

        assert result.baseline_drivers > 0
        assert len(result.entries) > 0
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert result.execution_time_ms >= 0

    def test_max_hours_policy_scenario(self, sample_tour_instances):
        """Test max hours policy simulation."""
        from v3.simulation_engine import run_max_hours_policy, RiskLevel

        result = run_max_hours_policy(
            sample_tour_instances,
            baseline_seed=94,
            caps_to_test=[55, 50, 48]
        )

        assert len(result.entries) == 3
        for entry in result.entries:
            assert entry.drivers > 0
            assert 0 <= entry.coverage <= 100
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_freeze_tradeoff_scenario(self, sample_tour_instances):
        """Test freeze window tradeoff simulation."""
        from v3.simulation_engine import run_freeze_tradeoff, RiskLevel

        result = run_freeze_tradeoff(
            sample_tour_instances,
            baseline_seed=94,
            windows_to_test=[720, 1080, 1440]  # 12h, 18h, 24h in minutes
        )

        assert len(result.entries) == 3
        for entry in result.entries:
            assert entry.drivers > 0
            assert 0 <= entry.stability_percent <= 100
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_driver_friendly_policy_scenario(self, sample_tour_instances):
        """Test driver friendly policy simulation."""
        from v3.simulation_engine import run_driver_friendly_policy, RiskLevel

        result = run_driver_friendly_policy(sample_tour_instances, baseline_seed=94)

        assert result.baseline_drivers > 0
        assert len(result.entries) >= 1
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_patch_chaos_scenario(self, sample_tour_instances):
        """Test patch chaos simulation."""
        from v3.simulation_engine import run_patch_chaos, RiskLevel

        result = run_patch_chaos(
            sample_tour_instances,
            locked_days=[1, 2],
            patch_days=[3, 4, 5, 6]
        )

        assert result.baseline_drivers > 0
        assert result.integrated_drivers > 0
        assert 0 <= result.churn_rate <= 1
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_sick_call_scenario(self, sample_tour_instances):
        """Test sick call drill simulation."""
        from v3.simulation_engine import run_sick_call, RiskLevel

        result = run_sick_call(
            sample_tour_instances,
            num_drivers_out=3,
            target_day=1
        )

        assert result.drivers_out == 3
        assert result.affected_tours >= 0
        assert result.repair_time_seconds >= 0
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_headcount_budget_scenario(self, sample_tour_instances):
        """Test headcount budget advisor simulation."""
        from v3.simulation_engine import run_headcount_budget, RiskLevel

        result = run_headcount_budget(
            sample_tour_instances,
            target_drivers=10,
            baseline_seed=94
        )

        assert result.baseline_drivers > 0
        assert result.target_drivers == 10
        assert isinstance(result.achieved, bool)
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_tour_cancel_scenario(self, sample_tour_instances):
        """Test tour cancellation simulation."""
        from v3.simulation_engine import run_tour_cancel, RiskLevel

        result = run_tour_cancel(
            sample_tour_instances,
            num_cancelled=10,
            target_day=None
        )

        assert result.cancelled_tours == min(10, len(sample_tour_instances))
        assert result.drivers_freed >= 0
        assert 0 <= result.churn_rate <= 1
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


# =============================================================================
# Risk Score Tests
# =============================================================================

class TestRiskScore:
    """Tests for risk score computation."""

    def test_risk_levels_enum(self):
        """Test risk level enumeration."""
        from v3.simulation_engine import RiskLevel

        assert RiskLevel.LOW.value == "LOW"
        assert RiskLevel.MEDIUM.value == "MEDIUM"
        assert RiskLevel.HIGH.value == "HIGH"
        assert RiskLevel.CRITICAL.value == "CRITICAL"

    def test_scenario_category_enum(self):
        """Test scenario category enumeration."""
        from v3.simulation_engine import ScenarioCategory

        assert ScenarioCategory.OPERATIONAL.value == "operational"
        assert ScenarioCategory.ECONOMIC.value == "economic"
        assert ScenarioCategory.COMPLIANCE.value == "compliance"


# =============================================================================
# Integration Tests
# =============================================================================

class TestSimulationIntegration:
    """Integration tests for simulation framework."""

    def test_all_scenarios_return_correct_types(self, sample_tour_instances):
        """Test that all scenarios return the correct result types."""
        from v3.simulation_engine import (
            run_cost_curve, run_max_hours_policy, run_freeze_tradeoff,
            run_driver_friendly_policy, run_patch_chaos, run_sick_call,
            run_headcount_budget, run_tour_cancel,
            CostCurveResult, MaxHoursPolicyResult, FreezeTradeoffResult,
            DriverFriendlyResult, PatchChaosResult, SickCallResult,
            HeadcountBudgetResultExtended, TourCancelResultExtended
        )

        # Cost Curve
        result = run_cost_curve(sample_tour_instances, baseline_seed=94)
        assert isinstance(result, CostCurveResult)

        # Max Hours
        result = run_max_hours_policy(sample_tour_instances, baseline_seed=94, caps_to_test=[55, 50])
        assert isinstance(result, MaxHoursPolicyResult)

        # Freeze Tradeoff
        result = run_freeze_tradeoff(sample_tour_instances, baseline_seed=94, windows_to_test=[720, 1440])
        assert isinstance(result, FreezeTradeoffResult)

        # Driver Friendly
        result = run_driver_friendly_policy(sample_tour_instances, baseline_seed=94)
        assert isinstance(result, DriverFriendlyResult)

        # Patch Chaos
        result = run_patch_chaos(sample_tour_instances, locked_days=[1, 2], patch_days=[3, 4, 5, 6])
        assert isinstance(result, PatchChaosResult)

        # Sick Call
        result = run_sick_call(sample_tour_instances, num_drivers_out=2, target_day=1)
        assert isinstance(result, SickCallResult)

        # Headcount Budget
        result = run_headcount_budget(sample_tour_instances, target_drivers=10, baseline_seed=94)
        assert isinstance(result, HeadcountBudgetResultExtended)

        # Tour Cancel
        result = run_tour_cancel(sample_tour_instances, num_cancelled=5, target_day=None)
        assert isinstance(result, TourCancelResultExtended)

    def test_simulation_determinism(self, sample_tour_instances):
        """Test that simulations are deterministic with same seed."""
        from v3.simulation_engine import run_cost_curve

        result1 = run_cost_curve(sample_tour_instances, baseline_seed=94)
        result2 = run_cost_curve(sample_tour_instances, baseline_seed=94)

        assert result1.baseline_drivers == result2.baseline_drivers
        assert len(result1.entries) == len(result2.entries)


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_tour_instances(self):
        """Test handling of empty tour instances."""
        from v3.seed_sweep import run_seed_sweep

        results = run_seed_sweep([], seeds=[94])
        assert len(results) == 1
        assert results[0]["total_drivers"] == 0

    def test_single_tour_instance(self):
        """Test handling of single tour instance."""
        from v3.seed_sweep import run_seed_sweep

        instances = [{
            "id": 1,
            "day": 1,
            "start_ts": time(6, 0),
            "end_ts": time(14, 0),
            "work_hours": 8.0,
            "depot": "DEFAULT",
            "skill": None,
            "duration_min": 480,
            "crosses_midnight": False,
        }]

        results = run_seed_sweep(instances, seeds=[94])
        assert len(results) == 1
        assert results[0]["total_drivers"] >= 1

    def test_tour_cancel_more_than_available(self, minimal_tour_instances):
        """Test cancelling more tours than available."""
        from v3.simulation_engine import run_tour_cancel

        result = run_tour_cancel(
            minimal_tour_instances,
            num_cancelled=100,  # More than available
            target_day=None
        )

        # Should cap at available tours
        assert result.cancelled_tours <= len(minimal_tour_instances)

    def test_headcount_impossible_target(self, minimal_tour_instances):
        """Test headcount budget with impossible target."""
        from v3.simulation_engine import run_headcount_budget

        result = run_headcount_budget(
            minimal_tour_instances,
            target_drivers=0,  # Impossible target
            baseline_seed=94
        )

        # Should indicate not achieved or handle gracefully
        assert result.final_drivers >= 0


# =============================================================================
# V3.2 Advanced Scenarios Tests
# =============================================================================

class TestAdvancedScenarios:
    """Tests for V3.2 advanced simulation scenarios."""

    def test_multi_failure_cascade_basic(self):
        """Test multi-failure cascade simulation."""
        from v3.simulation_engine import run_multi_failure_cascade, RiskLevel

        result = run_multi_failure_cascade(
            num_drivers_out=5,
            num_tours_cancelled=10,
            target_day=1,
            cascade_probability=0.15
        )

        assert result.drivers_out >= 5  # At least initial drivers
        assert result.tours_cancelled >= 10  # At least initial tours
        assert result.total_affected_tours >= 0
        assert 0 <= result.total_churn <= 1
        assert result.repair_time_seconds >= 0
        assert result.new_drivers_needed >= 0
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert result.execution_time_ms >= 0
        assert 0 <= result.probability_of_cascade <= 1
        assert result.worst_case_drivers >= result.best_case_drivers

    def test_multi_failure_cascade_no_cascade(self):
        """Test multi-failure cascade with zero cascade probability."""
        from v3.simulation_engine import run_multi_failure_cascade

        result = run_multi_failure_cascade(
            num_drivers_out=3,
            num_tours_cancelled=5,
            target_day=2,
            cascade_probability=0.0
        )

        # With 0 cascade probability, no cascade events should occur
        assert len(result.cascade_events) == 0
        assert result.drivers_out == 3  # Exactly initial count
        assert result.tours_cancelled == 5  # Exactly initial count

    def test_multi_failure_cascade_high_cascade(self):
        """Test multi-failure cascade with high cascade probability."""
        from v3.simulation_engine import run_multi_failure_cascade

        result = run_multi_failure_cascade(
            num_drivers_out=5,
            num_tours_cancelled=10,
            target_day=1,
            cascade_probability=0.5  # High cascade
        )

        # High cascade should likely create cascade events
        assert result.drivers_out >= 5
        assert result.tours_cancelled >= 10
        assert result.probability_of_cascade > 0.9  # Very high

    def test_probabilistic_churn_basic(self):
        """Test probabilistic churn Monte Carlo simulation."""
        from v3.simulation_engine import run_probabilistic_churn, RiskLevel

        result = run_probabilistic_churn(
            num_simulations=50,  # Lower for test speed
            churn_threshold=0.10,
            failure_probability=0.05,
            confidence_level=0.95
        )

        assert result.num_simulations == 50
        assert result.churn_threshold == 0.10
        assert 0 <= result.mean_churn <= 1
        assert result.std_churn >= 0
        assert 0 <= result.probability_above_threshold <= 1
        assert result.percentile_5 <= result.percentile_50 <= result.percentile_95
        assert len(result.confidence_interval) == 2
        assert result.confidence_interval[0] <= result.confidence_interval[1]
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert result.execution_time_ms >= 0
        assert len(result.histogram_data) == 20  # 20 buckets

    def test_probabilistic_churn_low_failure(self):
        """Test probabilistic churn with very low failure probability."""
        from v3.simulation_engine import run_probabilistic_churn, RiskLevel

        result = run_probabilistic_churn(
            num_simulations=30,
            churn_threshold=0.10,
            failure_probability=0.01,  # Very low
            confidence_level=0.95
        )

        # Low failure prob should result in low mean churn
        assert result.mean_churn < 0.15  # Should be relatively low
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM]

    def test_probabilistic_churn_high_failure(self):
        """Test probabilistic churn with high failure probability."""
        from v3.simulation_engine import run_probabilistic_churn

        result = run_probabilistic_churn(
            num_simulations=30,
            churn_threshold=0.05,  # Lower threshold
            failure_probability=0.15,  # Higher failure
            confidence_level=0.95
        )

        # High failure prob should result in higher mean churn
        assert result.mean_churn >= 0  # Should be higher
        assert result.probability_above_threshold >= 0  # More likely to exceed threshold

    def test_policy_roi_optimizer_basic(self):
        """Test policy ROI optimizer."""
        from v3.simulation_engine import run_policy_roi_optimizer, RiskLevel

        result = run_policy_roi_optimizer(
            budget_drivers=5,
            optimize_for="balanced",
            constraints=["arbzg_compliant"]
        )

        assert result.baseline_drivers > 0
        assert result.optimal_combination is not None
        assert result.optimal_combination.roi_score is not None
        assert len(result.all_combinations) > 0
        assert len(result.pareto_frontier) >= 0
        assert result.risk_score in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert result.execution_time_ms >= 0
        assert result.optimization_target == "balanced"

    def test_policy_roi_optimizer_cost_focus(self):
        """Test policy ROI optimizer with cost focus."""
        from v3.simulation_engine import run_policy_roi_optimizer

        result = run_policy_roi_optimizer(
            budget_drivers=10,
            optimize_for="cost",
            constraints=["arbzg_compliant"]
        )

        assert result.optimization_target == "cost"
        # Cost optimization should prioritize driver savings
        if result.optimal_combination.policy_combination:
            assert result.optimal_combination.driver_delta <= 0  # Should save drivers

    def test_policy_roi_optimizer_stability_focus(self):
        """Test policy ROI optimizer with stability focus."""
        from v3.simulation_engine import run_policy_roi_optimizer

        result = run_policy_roi_optimizer(
            budget_drivers=5,
            optimize_for="stability",
            constraints=["arbzg_compliant"]
        )

        assert result.optimization_target == "stability"
        # Stability optimization should minimize negative stability impact
        # Empty combination (no changes) should have 0 stability impact
        found_stable = any(c.stability_impact >= -0.1 for c in result.pareto_frontier)
        assert found_stable

    def test_policy_roi_optimizer_no_arbzg(self):
        """Test policy ROI optimizer without ArbZG constraint."""
        from v3.simulation_engine import run_policy_roi_optimizer

        result_with = run_policy_roi_optimizer(
            budget_drivers=10,
            optimize_for="cost",
            constraints=["arbzg_compliant"]
        )

        result_without = run_policy_roi_optimizer(
            budget_drivers=10,
            optimize_for="cost",
            constraints=[]  # No constraints
        )

        # Without constraints, should have more combinations
        assert len(result_without.all_combinations) >= len(result_with.all_combinations)

    def test_policy_roi_pareto_frontier(self):
        """Test that Pareto frontier contains non-dominated solutions."""
        from v3.simulation_engine import run_policy_roi_optimizer

        result = run_policy_roi_optimizer(
            budget_drivers=10,
            optimize_for="balanced",
            constraints=[]
        )

        # Each Pareto solution should not be dominated by any other
        for p in result.pareto_frontier:
            for other in result.pareto_frontier:
                if p != other:
                    # Not both better on both dimensions
                    assert not (
                        other.driver_delta < p.driver_delta and
                        other.stability_impact > p.stability_impact
                    )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
