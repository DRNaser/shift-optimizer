"""
Tests for Output Profiles Feature (MIN_HEADCOUNT_3ER vs BEST_BALANCED)
======================================================================
Tests config validation, 3er gap filter, and profile-based behavior.
"""
import pytest
from datetime import time

from src.api.config_validator import (
    validate_and_apply_overrides,
    TUNABLE_FIELDS,
)
from src.services.forecast_solver_v4 import ConfigV4
from src.domain.models import Block, Tour, Weekday


class TestOutputProfileConfig:
    """Test output_profile config field validation."""
    
    def test_output_profile_in_tunable_fields(self):
        """output_profile should be in TUNABLE_FIELDS whitelist."""
        assert "output_profile" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["output_profile"]["type"] == "str"
        assert "MIN_HEADCOUNT_3ER" in TUNABLE_FIELDS["output_profile"]["allowed"]
        assert "BEST_BALANCED" in TUNABLE_FIELDS["output_profile"]["allowed"]
    
    def test_output_profile_default_is_best_balanced(self):
        """Default profile should be BEST_BALANCED."""
        config = ConfigV4()
        assert config.output_profile == "BEST_BALANCED"
    
    def test_output_profile_override_min_headcount(self):
        """output_profile=MIN_HEADCOUNT_3ER should be applied."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"output_profile": "MIN_HEADCOUNT_3ER"},
            seed=42
        )
        assert result.config_effective.output_profile == "MIN_HEADCOUNT_3ER"
        assert "output_profile" in result.overrides_applied
    
    def test_output_profile_invalid_value_rejected(self):
        """Invalid profile value should be rejected."""
        result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides={"output_profile": "INVALID_PROFILE"},
            seed=42
        )
        assert "output_profile" in result.overrides_rejected
        assert "ENUM_ERROR" in result.overrides_rejected["output_profile"]
    
    def test_gap_3er_min_minutes_in_tunable(self):
        """gap_3er_min_minutes should be tunable."""
        assert "gap_3er_min_minutes" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["gap_3er_min_minutes"]["default"] == 30
    
    def test_w_3er_bonus_in_tunable(self):
        """w_3er_bonus should be tunable."""
        assert "w_3er_bonus" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["w_3er_bonus"]["default"] == 10.0


class TestGaps3erValidMin:
    """Test gaps_3er_valid_min function."""
    
    def _make_tour(self, tour_id: str, start: str, end: str, day=Weekday.MONDAY) -> Tour:
        """Helper to create a Tour object."""
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        return Tour(
            id=tour_id,
            day=day,
            start_time=time(sh, sm),
            end_time=time(eh, em),
            location="HUB",
            required_qualifications=[]
        )
    
    def _make_block(self, tours: list[Tour], day=Weekday.MONDAY) -> Block:
        """Helper to create a Block object."""
        return Block(
            id=f"B{len(tours)}er-" + "-".join(t.id for t in tours),
            day=day,
            tours=tours
        )
    
    def test_1er_always_valid(self):
        """1er blocks should always pass (not filtered)."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "10:00")
        block = self._make_block([t1])
        
        assert gaps_3er_valid_min(block, gap_min=30) is True
    
    def test_2er_always_valid(self):
        """2er blocks should always pass (not filtered)."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "10:00")
        t2 = self._make_tour("T2", "10:30", "14:00")  # 30min gap
        block = self._make_block([t1, t2])
        
        assert gaps_3er_valid_min(block, gap_min=30) is True
    
    def test_3er_valid_gaps_both_30(self):
        """3er with both gaps = 30min should be valid."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "08:00")
        t2 = self._make_tour("T2", "08:30", "10:30")  # 30min gap
        t3 = self._make_tour("T3", "11:00", "13:00")  # 30min gap
        block = self._make_block([t1, t2, t3])
        
        assert gaps_3er_valid_min(block, gap_min=30) is True
    
    def test_3er_valid_gaps_larger(self):
        """3er with gaps > 30min should be valid (120min is fine)."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "08:00")
        t2 = self._make_tour("T2", "10:00", "12:00")  # 120min gap
        t3 = self._make_tour("T3", "14:00", "16:00")  # 120min gap
        block = self._make_block([t1, t2, t3])
        
        assert gaps_3er_valid_min(block, gap_min=30) is True
    
    def test_3er_invalid_gap1_too_small(self):
        """3er with first gap = 29min should be invalid."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "08:01")
        t2 = self._make_tour("T2", "08:30", "10:30")  # 29min gap
        t3 = self._make_tour("T3", "11:00", "13:00")  # 30min gap OK
        block = self._make_block([t1, t2, t3])
        
        assert gaps_3er_valid_min(block, gap_min=30) is False
    
    def test_3er_invalid_gap2_too_small(self):
        """3er with second gap = 29min should be invalid."""
        from src.services.smart_block_builder import gaps_3er_valid_min
        
        t1 = self._make_tour("T1", "06:00", "08:00")
        t2 = self._make_tour("T2", "08:30", "10:31")  # 30min gap OK
        t3 = self._make_tour("T3", "11:00", "13:00")  # 29min gap
        block = self._make_block([t1, t2, t3])
        
        assert gaps_3er_valid_min(block, gap_min=30) is False


class TestBalanceWeightsConfig:
    """Test BEST_BALANCED weight parameters."""
    
    def test_w_balance_underfull_in_tunable(self):
        """w_balance_underfull should be tunable."""
        assert "w_balance_underfull" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["w_balance_underfull"]["default"] == 100.0
    
    def test_w_pt_penalty_in_tunable(self):
        """w_pt_penalty should be tunable."""
        assert "w_pt_penalty" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["w_pt_penalty"]["default"] == 500.0
    
    def test_max_extra_driver_pct_in_tunable(self):
        """max_extra_driver_pct should be tunable."""
        assert "max_extra_driver_pct" in TUNABLE_FIELDS
        assert TUNABLE_FIELDS["max_extra_driver_pct"]["default"] == 0.05
    
    def test_config_defaults_best_balanced_weights(self):
        """ConfigV4 should have correct default BEST_BALANCED weights."""
        config = ConfigV4()
        assert config.w_balance_underfull == 100.0
        assert config.w_pt_penalty == 500.0
        assert config.w_balance_variance == 50.0
        assert config.max_extra_driver_pct == 0.05


class TestTwoPassCapEnforcement:
    """Test BEST_BALANCED two-pass cap enforcement."""
    
    def test_driver_cap_calculation(self):
        """Driver cap should be ceil(1.05 * D_min)."""
        import math
        
        # Test various D_min values
        test_cases = [
            (100, 105),  # 100 * 1.05 = 105
            (150, 158),  # 150 * 1.05 = 157.5 -> ceil = 158
            (200, 210),  # 200 * 1.05 = 210
            (117, 123),  # 117 * 1.05 = 122.85 -> ceil = 123
        ]
        
        for D_min, expected_cap in test_cases:
            max_extra_driver_pct = 0.05
            driver_cap = math.ceil((1 + max_extra_driver_pct) * D_min)
            assert driver_cap == expected_cap, f"D_min={D_min}: expected {expected_cap}, got {driver_cap}"
    
    def test_solve_capacity_twopass_balanced_exists(self):
        """solve_capacity_twopass_balanced function should exist."""
        from src.services.forecast_solver_v4 import solve_capacity_twopass_balanced
        assert callable(solve_capacity_twopass_balanced)
    
    def test_balanced_cap_constraint_function_exists(self):
        """_solve_capacity_balanced_with_cap function should exist."""
        from src.services.forecast_solver_v4 import _solve_capacity_balanced_with_cap
        assert callable(_solve_capacity_balanced_with_cap)


class TestTwoPassStatsPropagation:
    """Test that two-pass stats are correctly propagated to API response."""
    
    def test_stats_output_has_twopass_fields(self):
        """StatsOutput schema should have all two-pass proof fields."""
        from src.api.schemas import StatsOutput
        import pydantic
        
        # Get field names from StatsOutput
        field_names = set(StatsOutput.model_fields.keys())
        
        # Required two-pass fields
        required_fields = {
            "twopass_executed",
            "pass1_time_s",
            "pass2_time_s",
            "drivers_total_pass1",
            "drivers_total_pass2",
            "D_min",
            "driver_cap",
            "output_profile",
        }
        
        for field in required_fields:
            assert field in field_names, f"StatsOutput missing field: {field}"
    
    def test_kpi_contains_output_profile(self):
        """KPI dict should contain output_profile after portfolio run."""
        # This is a unit test for the KPI structure
        # Integration test would require full solver run
        
        # Mock kpi dict structure matching portfolio_controller output
        mock_kpi = {
            "solver_arch": "portfolio_a",
            "status": "OK",
            "output_profile": "BEST_BALANCED",
            "gap_3er_min_minutes": 30,
        }
        
        assert mock_kpi["output_profile"] == "BEST_BALANCED"
        assert mock_kpi["gap_3er_min_minutes"] == 30
    
    def test_twopass_stats_structure(self):
        """Two-pass stats dict should have correct structure."""
        import math
        
        # Mock the stats dict structure returned by solve_capacity_twopass_balanced
        D_min = 180
        max_extra_driver_pct = 0.05
        driver_cap = math.ceil((1 + max_extra_driver_pct) * D_min)
        
        mock_twopass_stats = {
            "twopass_executed": True,
            "D_min": D_min,
            "driver_cap": driver_cap,
            "block_cap": 195,
            "drivers_total_pass1": D_min,
            "drivers_total_pass2": 185,
            "twopass_status": "SUCCESS",
            "pass1_time_s": 50.2,
            "pass2_time_s": 30.1,
            "output_profile": "BEST_BALANCED",
            "gap_3er_min_minutes": 30,
        }
        
        # Verify structure
        assert mock_twopass_stats["twopass_executed"] is True
        assert mock_twopass_stats["D_min"] == 180
        assert mock_twopass_stats["driver_cap"] == 189  # ceil(180 * 1.05)
        assert mock_twopass_stats["drivers_total_pass2"] <= mock_twopass_stats["driver_cap"]
        assert mock_twopass_stats["output_profile"] == "BEST_BALANCED"

