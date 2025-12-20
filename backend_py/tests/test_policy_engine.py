"""
Tests for Policy Engine
========================
Tests path selection rules and parameter adaptation.
"""

import pytest
from dataclasses import dataclass


class TestPathSelection:
    """Test path selection rules."""
    
    def test_normal_instance_selects_path_a(self):
        from src.services.policy_engine import select_path, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.20,  # Low
            pt_pressure_proxy=0.30,  # Low
            rest_risk_proxy=0.05,  # Low
            pool_pressure="LOW",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.A
        assert reason == ReasonCode.NORMAL_INSTANCE
    
    def test_high_peakiness_selects_path_b(self):
        from src.services.policy_engine import select_path, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.40,  # High (>= 0.35)
            pt_pressure_proxy=0.30,  # Low
            pool_pressure="LOW",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.B
        assert reason == ReasonCode.PEAKY_HIGH
    
    def test_high_pt_pressure_selects_path_b(self):
        from src.services.policy_engine import select_path, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.20,  # Low
            pt_pressure_proxy=0.55,  # High (>= 0.5)
            pool_pressure="LOW",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.B
        assert reason == ReasonCode.PEAKY_OR_PT_PRESSURE
    
    def test_high_pool_pressure_selects_path_c(self):
        from src.services.policy_engine import select_path, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.40,  # High (but pool takes precedence)
            pt_pressure_proxy=0.60,  # High
            pool_pressure="HIGH",  # Highest priority
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.C
        assert reason == ReasonCode.POOL_TOO_LARGE
    
    def test_high_rest_risk_selects_path_b(self):
        from src.services.policy_engine import select_path, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.20,  # Low
            pt_pressure_proxy=0.30,  # Low
            rest_risk_proxy=0.20,  # High (>= 0.15)
            pool_pressure="LOW",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.B
        assert reason == ReasonCode.REST_RISK_HIGH


class TestParameterSelection:
    """Test parameter adaptation based on path and features."""
    
    def test_path_a_uses_light_lns(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(n_tours=100, n_blocks=500)
        params = select_parameters(features, PathSelection.A, "NORMAL_INSTANCE", 30.0)
        
        assert params.path == PathSelection.A
        assert params.lns_iterations <= 100
        assert params.destroy_fraction <= 0.15
        assert params.sp_enabled == False
    
    def test_path_b_uses_extended_lns(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(n_tours=100, n_blocks=500)
        params = select_parameters(features, PathSelection.B, "PEAKY_HIGH", 30.0)
        
        assert params.path == PathSelection.B
        assert params.lns_iterations >= 200
        assert params.destroy_fraction >= 0.15
        assert params.pt_focused_destroy_weight >= 0.4
        assert params.sp_enabled == False
    
    def test_path_c_enables_sp(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(n_tours=100, n_blocks=500, pool_pressure="HIGH")
        params = select_parameters(features, PathSelection.C, "POOL_TOO_LARGE", 60.0)
        
        assert params.path == PathSelection.C
        assert params.sp_enabled == True
        assert params.column_gen_quota > 0
        assert params.pool_cap > 0
    
    def test_short_budget_increases_epsilon(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(n_tours=100, n_blocks=500)
        
        short_params = select_parameters(features, PathSelection.A, "NORMAL", 10.0)
        long_params = select_parameters(features, PathSelection.A, "NORMAL", 120.0)
        
        assert short_params.epsilon > long_params.epsilon
    
    def test_large_instance_increases_daymin_buffer(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        small = FeatureVector(n_tours=100, n_blocks=300)
        large = FeatureVector(n_tours=600, n_blocks=3000)
        
        small_params = select_parameters(small, PathSelection.A, "NORMAL", 30.0)
        large_params = select_parameters(large, PathSelection.A, "NORMAL", 30.0)
        
        assert large_params.daymin_buffer > small_params.daymin_buffer


class TestFallbackLogic:
    """Test fallback path selection."""
    
    def test_fallback_from_a_to_b(self):
        from src.services.policy_engine import get_fallback_path, PathSelection, ReasonCode
        
        next_path, reason = get_fallback_path(PathSelection.A)
        
        assert next_path == PathSelection.B
        assert reason == ReasonCode.FALLBACK_PATH_B
    
    def test_fallback_from_b_to_c(self):
        from src.services.policy_engine import get_fallback_path, PathSelection, ReasonCode
        
        next_path, reason = get_fallback_path(PathSelection.B)
        
        assert next_path == PathSelection.C
        assert reason == ReasonCode.FALLBACK_PATH_C
    
    def test_no_fallback_from_c(self):
        from src.services.policy_engine import get_fallback_path, PathSelection
        
        next_path, reason = get_fallback_path(PathSelection.C)
        
        assert next_path is None


class TestShouldFallback:
    """Test fallback trigger conditions."""
    
    def test_stagnation_triggers_fallback(self):
        from src.services.policy_engine import should_fallback, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            stagnation_iters=20,
            repair_failure_threshold=0.3,
        )
        
        should, reason = should_fallback(
            iterations_without_improvement=25,  # > 20
            repair_failure_rate=0.1,
            params=params,
        )
        
        assert should == True
        assert "STAGNATION" in reason
    
    def test_high_repair_failure_triggers_fallback(self):
        from src.services.policy_engine import should_fallback, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            stagnation_iters=20,
            repair_failure_threshold=0.3,
        )
        
        should, reason = should_fallback(
            iterations_without_improvement=5,  # Low
            repair_failure_rate=0.35,  # > 0.3
            params=params,
        )
        
        assert should == True
    
    def test_good_progress_no_fallback(self):
        from src.services.policy_engine import should_fallback, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            stagnation_iters=20,
            repair_failure_threshold=0.3,
        )
        
        should, reason = should_fallback(
            iterations_without_improvement=5,
            repair_failure_rate=0.1,
            params=params,
        )
        
        assert should == False


class TestEarlyStop:
    """Test early stop conditions."""
    
    def test_good_enough_triggers_early_stop(self):
        from src.services.policy_engine import should_early_stop, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            epsilon=0.02,  # 2% gap
        )
        
        should, reason = should_early_stop(
            current_score=102,
            lower_bound=100,  # Gap = 2/100 = 2% = epsilon
            daymin_achieved=False,
            params=params,
        )
        
        assert should == True
        assert "GOOD_ENOUGH" in reason
    
    def test_near_daymin_triggers_early_stop(self):
        from src.services.policy_engine import should_early_stop, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            epsilon=0.02,
        )
        
        should, reason = should_early_stop(
            current_score=110,
            lower_bound=100,  # Gap = 10%
            daymin_achieved=True,  # But daymin achieved
            params=params,
        )
        
        assert should == True
        assert "DAYMIN" in reason
    
    def test_gap_too_large_no_early_stop(self):
        from src.services.policy_engine import should_early_stop, ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.A,
            reason_code="NORMAL",
            epsilon=0.02,
        )
        
        should, reason = should_early_stop(
            current_score=110,
            lower_bound=100,  # Gap = 10% > 2%
            daymin_achieved=False,
            params=params,
        )
        
        assert should == False


class TestPolicyEngine:
    """Test PolicyEngine stateful class."""
    
    def test_select_stores_state(self):
        from src.services.policy_engine import PolicyEngine, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        engine = PolicyEngine()
        features = FeatureVector(n_tours=100, n_blocks=500)
        
        params = engine.select(features, 30.0)
        
        assert engine.current_path is not None
        assert engine.current_params is not None
        assert len(engine.reason_codes) > 0
    
    def test_trigger_fallback_updates_state(self):
        from src.services.policy_engine import PolicyEngine, PathSelection, ReasonCode
        from src.services.instance_profiler import FeatureVector
        
        engine = PolicyEngine()
        features = FeatureVector(n_tours=100, n_blocks=500, pool_pressure="LOW")
        
        engine.select(features, 30.0)
        initial_path = engine.current_path
        
        new_params = engine.trigger_fallback(ReasonCode.STAGNATION)
        
        assert engine.current_path != initial_path
        assert engine.fallback_count == 1
        assert ReasonCode.STAGNATION in engine.reason_codes
    
    def test_get_summary(self):
        from src.services.policy_engine import PolicyEngine
        from src.services.instance_profiler import FeatureVector
        
        engine = PolicyEngine()
        features = FeatureVector(n_tours=100, n_blocks=500)
        
        engine.select(features, 30.0)
        summary = engine.get_summary()
        
        assert "final_path" in summary
        assert "reason_codes" in summary
        assert "fallback_count" in summary
        assert "parameters" in summary


class TestDeterminism:
    """Test that policy decisions are deterministic."""
    
    def test_same_features_same_path(self):
        from src.services.policy_engine import select_path
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.38,
            pt_pressure_proxy=0.45,
            pool_pressure="MEDIUM",
        )
        
        path1, reason1 = select_path(features)
        path2, reason2 = select_path(features)
        
        assert path1 == path2
        assert reason1 == reason2
    
    def test_same_features_same_params(self):
        from src.services.policy_engine import select_parameters, PathSelection
        from src.services.instance_profiler import FeatureVector
        
        features = FeatureVector(n_tours=100, n_blocks=500)
        
        params1 = select_parameters(features, PathSelection.B, "PEAKY", 30.0)
        params2 = select_parameters(features, PathSelection.B, "PEAKY", 30.0)
        
        assert params1.to_dict() == params2.to_dict()
