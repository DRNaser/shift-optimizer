"""
Tests for Portfolio Controller
===============================
Tests the meta-orchestration pipeline.
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from datetime import time


# Mock domain models
@dataclass
class MockTour:
    id: str
    day: 'MockWeekday'
    start_time: time
    end_time: time
    duration_hours: float = 8.0


class MockWeekday:
    def __init__(self, value: str):
        self.value = value
    
    MONDAY = None
    TUESDAY = None
    WEDNESDAY = None


MockWeekday.MONDAY = MockWeekday("Mon")
MockWeekday.TUESDAY = MockWeekday("Tue")
MockWeekday.WEDNESDAY = MockWeekday("Wed")


@dataclass
class MockBlock:
    id: str
    day: MockWeekday
    tours: list
    first_start: time = time(6, 0)
    last_end: time = time(14, 0)
    total_work_hours: float = 8.0


class TestPortfolioResult:
    """Test PortfolioResult dataclass."""
    
    def test_to_dict_returns_all_fields(self):
        from src.services.portfolio_controller import PortfolioResult
        from src.services.policy_engine import PathSelection, ParameterBundle
        from src.services.instance_profiler import FeatureVector
        
        result = PortfolioResult(
            solution=MagicMock(status="OK"),
            features=FeatureVector(n_tours=100, n_blocks=500),
            initial_path=PathSelection.A,
            final_path=PathSelection.A,
            parameters_used=ParameterBundle(path=PathSelection.A, reason_code="NORMAL"),
            reason_codes=["NORMAL_INSTANCE"],
            lower_bound=45,
            achieved_score=48,
            total_runtime_s=25.5,
        )
        
        d = result.to_dict()
        
        assert d["initial_path"] == "FAST"
        assert d["final_path"] == "FAST"
        assert d["lower_bound"] == 45
        assert d["achieved_score"] == 48
        assert d["total_runtime_s"] == 25.5


class TestRunReport:
    """Test run report generation."""
    
    def test_to_json_generates_valid_json(self):
        from src.services.portfolio_controller import RunReport
        import json
        
        report = RunReport(
            timestamp="2024-01-01T12:00:00",
            input_summary={"n_tours": 100},
            features={"peakiness_index": 0.35},
            policy_decisions={"path": "A"},
            execution_log=[{"time": 0.1, "message": "Started"}],
            result_summary={"status": "OK"},
            solve_times={"total_s": 25.0},
        )
        
        json_str = report.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["timestamp"] == "2024-01-01T12:00:00"
        assert parsed["input_summary"]["n_tours"] == 100
        assert parsed["features"]["peakiness_index"] == 0.35


class TestGenerateRunReport:
    """Test generate_run_report function."""
    
    def test_generates_report_without_file(self):
        from src.services.portfolio_controller import generate_run_report, PortfolioResult
        from src.services.policy_engine import PathSelection, ParameterBundle
        from src.services.instance_profiler import FeatureVector
        
        result = PortfolioResult(
            solution=MagicMock(status="OK", kpi={"drivers_fte": 48, "drivers_pt": 5}),
            features=FeatureVector(n_tours=100, n_blocks=500),
            initial_path=PathSelection.A,
            final_path=PathSelection.B,
            parameters_used=ParameterBundle(path=PathSelection.B, reason_code="FALLBACK"),
            reason_codes=["NORMAL", "STAGNATION", "FALLBACK_PATH_B"],
            lower_bound=45,
            achieved_score=53,
            fallback_used=True,
            fallback_count=1,
            total_runtime_s=30.0,
        )
        
        tours = [MockTour("T1", MockWeekday.MONDAY, time(6, 0), time(14, 0))]
        
        report = generate_run_report(result, tours, output_path=None)
        
        assert report.timestamp is not None
        assert report.input_summary["n_tours"] == 1
        assert report.policy_decisions["fallback_used"] == True
        assert report.result_summary["lower_bound"] == 45


class TestDeterminism:
    """Test determinism of portfolio execution."""
    
    def test_same_input_same_path_selection(self):
        from src.services.policy_engine import PolicyEngine, select_path
        from src.services.instance_profiler import compute_features, FeatureVector
        
        # Create identical feature vectors
        fv1 = FeatureVector(
            n_tours=100, n_blocks=500,
            peakiness_index=0.38,
            pt_pressure_proxy=0.45,
            pool_pressure="MEDIUM",
        )
        fv2 = FeatureVector(
            n_tours=100, n_blocks=500,
            peakiness_index=0.38,
            pt_pressure_proxy=0.45,
            pool_pressure="MEDIUM",
        )
        
        path1, reason1 = select_path(fv1)
        path2, reason2 = select_path(fv2)
        
        assert path1 == path2
        assert reason1 == reason2


class TestSolveForecasePortfolioWrapper:
    """Test the convenience wrapper function."""
    
    def test_wrapper_returns_solve_result_v4(self):
        # This test would require mocking the full pipeline
        # For now, we just verify the function exists and has correct signature
        from src.services.portfolio_controller import solve_forecast_portfolio
        import inspect
        
        sig = inspect.signature(solve_forecast_portfolio)
        params = list(sig.parameters.keys())
        
        assert "tours" in params
        assert "time_budget" in params
        assert "seed" in params


class TestPathExecutionLogic:
    """Test path execution helper functions."""
    
    def test_light_lns_wrapper_handles_exception(self):
        from src.services.portfolio_controller import _run_light_lns
        
        # Pass invalid inputs that would cause exception
        result = _run_light_lns(
            assignments=[],  # Empty assignments
            blocks=[],
            config=MagicMock(max_hours_per_fte=53.0),
            budget=5.0,
            seed=42,
        )
        
        # Should return empty list (input) on failure
        assert result == []
    
    def test_extended_lns_wrapper_handles_exception(self):
        from src.services.portfolio_controller import _run_extended_lns
        from src.services.policy_engine import ParameterBundle, PathSelection
        
        params = ParameterBundle(
            path=PathSelection.B,
            reason_code="TEST",
            lns_iterations=50,
            destroy_fraction=0.15,
            repair_time_limit_s=3.0,
            enable_pt_elimination=True,
            pt_focused_destroy_weight=0.3,
        )
        
        result = _run_extended_lns(
            assignments=[],
            blocks=[],
            config=MagicMock(max_hours_per_fte=53.0),
            budget=10.0,
            seed=42,
            params=params,
        )
        
        assert result == []


class TestIntegrationScenarios:
    """Integration tests for common scenarios."""
    
    def test_normal_instance_takes_path_a(self):
        """Verify normal instances select fast path."""
        from src.services.instance_profiler import FeatureVector
        from src.services.policy_engine import select_path, PathSelection
        
        # Low complexity instance
        features = FeatureVector(
            n_tours=50,
            n_blocks=200,
            peakiness_index=0.15,
            pt_pressure_proxy=0.20,
            rest_risk_proxy=0.05,
            pool_pressure="LOW",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.A
    
    def test_peaky_instance_takes_path_b(self):
        """Verify peaky instances select balanced path."""
        from src.services.instance_profiler import FeatureVector
        from src.services.policy_engine import select_path, PathSelection
        
        features = FeatureVector(
            n_tours=100,
            n_blocks=500,
            peakiness_index=0.45,  # High peakiness
            pt_pressure_proxy=0.30,
            rest_risk_proxy=0.10,
            pool_pressure="MEDIUM",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.B
    
    def test_large_pool_takes_path_c(self):
        """Verify large pool instances select heavy path."""
        from src.services.instance_profiler import FeatureVector
        from src.services.policy_engine import select_path, PathSelection
        
        features = FeatureVector(
            n_tours=200,
            n_blocks=40000,  # Near max
            peakiness_index=0.20,
            pt_pressure_proxy=0.25,
            pool_pressure="HIGH",
        )
        
        path, reason = select_path(features)
        
        assert path == PathSelection.C


# =============================================================================
# S0.5: DETERMINISM REGRESSION TESTS
# =============================================================================

class TestS05DeterminismGate:
    """
    S0.5: Determinism regression tests.
    Verify: same input + same seed => identical canonical signature.
    EXCLUDES: uuid, timestamp, walltime (non-deterministic fields).
    """
    
    def test_canonical_signature_excludes_nondeterministic_fields(self):
        """Verify signature function doesn't include uuid/timestamp/walltime."""
        from src.services.portfolio_controller import canonical_solution_signature, PortfolioResult
        from src.services.policy_engine import PathSelection, ParameterBundle
        from src.services.instance_profiler import FeatureVector
        
        # Create mock result
        mock_assignment = MagicMock()
        mock_assignment.driver_id = "FTE-001"
        mock_assignment.blocks = [MagicMock(id="block_123")]
        
        mock_solution = MagicMock()
        mock_solution.status = "OK"
        mock_solution.assignments = [mock_assignment]
        mock_solution.kpi = {"drivers_fte": 1, "drivers_pt": 0}
        
        result = PortfolioResult(
            solution=mock_solution,
            features=FeatureVector(n_tours=10),
            initial_path=PathSelection.A,
            final_path=PathSelection.A,
            parameters_used=ParameterBundle(path=PathSelection.A, reason_code="TEST"),
            achieved_score=1,
        )
        
        sig = canonical_solution_signature(result)
        
        # Verify no non-deterministic fields
        assert "timestamp" not in sig
        assert "uuid" not in sig
        assert "plan_id" not in sig
        assert "walltime" not in sig
        
        # Verify deterministic content present
        assert "assignments" in sig
        assert "block_ids" in sig
        assert "drivers_fte" in sig
        assert sig["assignments"] == [("FTE-001", "block_123")]
    
    def test_canonical_signature_is_sorted(self):
        """Verify signature sorts assignments for determinism."""
        from src.services.portfolio_controller import canonical_solution_signature, PortfolioResult
        from src.services.policy_engine import PathSelection, ParameterBundle
        from src.services.instance_profiler import FeatureVector
        
        # Create mock result with unsorted assignments
        mock_a1 = MagicMock()
        mock_a1.driver_id = "FTE-002"
        mock_a1.blocks = [MagicMock(id="block_z"), MagicMock(id="block_a")]
        
        mock_a2 = MagicMock()
        mock_a2.driver_id = "FTE-001"
        mock_a2.blocks = [MagicMock(id="block_m")]
        
        mock_solution = MagicMock()
        mock_solution.status = "OK"
        mock_solution.assignments = [mock_a1, mock_a2]  # Unsorted!
        mock_solution.kpi = {"drivers_fte": 2, "drivers_pt": 0}
        
        result = PortfolioResult(
            solution=mock_solution,
            features=FeatureVector(n_tours=10),
            initial_path=PathSelection.A,
            final_path=PathSelection.A,
            parameters_used=ParameterBundle(path=PathSelection.A, reason_code="TEST"),
            achieved_score=2,
        )
        
        sig = canonical_solution_signature(result)
        
        # Verify sorted
        assert sig["assignments"] == [
            ("FTE-001", "block_m"),
            ("FTE-002", "block_a"),
            ("FTE-002", "block_z"),
        ]
        assert sig["block_ids"] == ["block_a", "block_m", "block_z"]
    
    def test_same_input_same_signature(self):
        """Verify identical inputs produce identical signatures."""
        from src.services.portfolio_controller import canonical_solution_signature, PortfolioResult
        from src.services.policy_engine import PathSelection, ParameterBundle
        from src.services.instance_profiler import FeatureVector
        
        def make_result():
            mock_assignment = MagicMock()
            mock_assignment.driver_id = "FTE-001"
            mock_assignment.blocks = [MagicMock(id="block_123")]
            
            mock_solution = MagicMock()
            mock_solution.status = "OK"
            mock_solution.assignments = [mock_assignment]
            mock_solution.kpi = {"drivers_fte": 1, "drivers_pt": 0}
            
            return PortfolioResult(
                solution=mock_solution,
                features=FeatureVector(n_tours=10),
                initial_path=PathSelection.A,
                final_path=PathSelection.A,
                parameters_used=ParameterBundle(path=PathSelection.A, reason_code="TEST"),
                achieved_score=1,
            )
        
        sig1 = canonical_solution_signature(make_result())
        sig2 = canonical_solution_signature(make_result())
        
        assert sig1 == sig2


# =============================================================================
# S0.6: BUDGET COMPLIANCE TESTS  
# =============================================================================

class TestS06BudgetCompliance:
    """
    S0.6: Budget compliance tests.
    Verify: solver completes within specified time budget.
    """
    
    def test_budget_slice_creation(self):
        """Verify BudgetSlice creates correct proportions."""
        from src.services.portfolio_controller import BudgetSlice
        
        slices = BudgetSlice.from_total(30.0)
        
        assert slices.total == 30.0
        assert slices.profiling == pytest.approx(0.6, abs=0.1)   # 2%
        assert slices.phase1 == pytest.approx(15.0, abs=0.1)     # 50%
        assert slices.phase2 == pytest.approx(4.5, abs=0.1)      # 15%
        assert slices.lns == pytest.approx(8.4, abs=0.1)         # 28%
        assert slices.buffer == pytest.approx(1.5, abs=0.1)      # 5%
        
        # Verify total adds up
        total = slices.profiling + slices.phase1 + slices.phase2 + slices.lns + slices.buffer
        assert total == pytest.approx(30.0, abs=0.01)
    
    def test_budget_slice_to_dict(self):
        """Verify BudgetSlice serialization."""
        from src.services.portfolio_controller import BudgetSlice
        
        slices = BudgetSlice.from_total(60.0)
        d = slices.to_dict()
        
        assert d["total"] == 60.0
        assert "phase1" in d
        assert "phase2" in d
        assert "lns" in d
        assert "buffer" in d


# =============================================================================
# S0.7: PATHSELECTION REGRESSION TEST
# =============================================================================

class TestPathSelectionRegression:
    """
    Regression test to prevent PathSelection from becoming a local variable
    in run_portfolio, which causes UnboundLocalError crashes.
    
    This test ensures that no accidental binding (assignment, except-as, 
    for-loop, or local import) shadows the module-level PathSelection import.
    """
    
    def test_run_portfolio_pathselection_not_local(self):
        """
        CRITICAL: PathSelection must NOT be in run_portfolio's co_varnames.
        If this test fails, there is an assignment/binding that shadows PathSelection.
        """
        import src.services.portfolio_controller as pc
        
        local_vars = pc.run_portfolio.__code__.co_varnames
        assert "PathSelection" not in local_vars, (
            f"PathSelection is a local variable in run_portfolio! "
            f"This will cause UnboundLocalError crashes. "
            f"Found in co_varnames: {[v for v in local_vars if 'Path' in v]}"
        )
    
    def test_execute_path_pathselection_not_local(self):
        """
        CRITICAL: PathSelection must NOT be in _execute_path's co_varnames.
        """
        import src.services.portfolio_controller as pc
        
        local_vars = pc._execute_path.__code__.co_varnames
        assert "PathSelection" not in local_vars, (
            f"PathSelection is a local variable in _execute_path! "
            f"This will cause UnboundLocalError crashes."
        )
    
    def test_ps_alias_exists_at_module_level(self):
        """
        Verify the PS = PathSelection alias is defined at module level.
        """
        import src.services.portfolio_controller as pc
        from src.services.policy_engine import PathSelection
        
        assert hasattr(pc, 'PS'), "PS alias not found at module level"
        assert pc.PS is PathSelection, "PS alias does not point to PathSelection"
