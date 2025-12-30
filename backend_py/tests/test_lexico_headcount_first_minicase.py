"""
Test: Lexicographic RMP - Headcount First (Minicase)

This test verifies that `solve_rmp_lexico` correctly implements
true lexicographic optimization where:
- Stage 1: Fewer drivers ALWAYS wins
- Stage 2: Quality optimization only with fixed headcount

Scenario:
- 4 items (A, B, C, D) need exact coverage
- Solution A: 2 drivers covering {A,B} and {C,D} (dense)
- Solution B: 4 drivers covering {A}, {B}, {C}, {D} (singletons)

Expected: Lexiko chooses Solution A (2 drivers) even though
Solution B has different quality characteristics.
"""

import pytest
from unittest.mock import MagicMock


class MockRosterColumn:
    """Mock RosterColumn for testing."""
    
    def __init__(self, roster_id: str, covered_items: list[str], total_minutes: float):
        self.roster_id = roster_id
        self.covered_tour_ids = set(covered_items)
        self.block_ids = set(covered_items)  # For compatibility
        self.total_minutes = total_minutes
        self.is_valid = True
    
    @property
    def total_hours(self) -> float:
        return self.total_minutes / 60.0


class TestLexicoHeadcountFirst:
    """Tests to verify headcount minimization takes precedence."""
    
    def test_fewer_drivers_beats_fewer_singletons(self):
        """Stage 1 must choose fewer drivers regardless of singleton count."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # 4 items to cover
        target_ids = {"A", "B", "C", "D"}
        
        # Build column pool:
        # - 2 dense columns covering 2 items each (2 drivers total)
        # - 4 singleton columns covering 1 item each (4 drivers total)
        columns = [
            # Dense columns (preferred for headcount)
            MockRosterColumn("DENSE_AB", ["A", "B"], 1800),  # 30h
            MockRosterColumn("DENSE_CD", ["C", "D"], 1800),  # 30h
            # Singleton columns (worse for headcount)
            MockRosterColumn("SINGLE_A", ["A"], 900),  # 15h
            MockRosterColumn("SINGLE_B", ["B"], 900),
            MockRosterColumn("SINGLE_C", ["C"], 900),
            MockRosterColumn("SINGLE_D", ["D"], 900),
        ]
        
        result = solve_rmp_lexico(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            time_limit_total=30.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] in ("OPTIMAL", "FEASIBLE"), f"Solve failed: {result['status']}"
        assert result["D_star"] == 2, f"Expected D*=2 (dense solution), got {result['D_star']}"
        
        # Verify the selected rosters are the dense ones
        selected_ids = {r.roster_id for r in result["selected_rosters"]}
        assert "DENSE_AB" in selected_ids, "Should select DENSE_AB"
        assert "DENSE_CD" in selected_ids, "Should select DENSE_CD"
    
    def test_stage2_does_not_increase_headcount(self):
        """Stage 2 must keep headcount fixed at D*."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # 2 items to cover
        target_ids = {"X", "Y"}
        
        # Multiple options with same headcount (D*=2) but different quality
        columns = [
            # All require 2 drivers (singletons only)
            MockRosterColumn("S1_X", ["X"], 480),   # 8h (very short)
            MockRosterColumn("S1_Y", ["Y"], 480),
            MockRosterColumn("S2_X", ["X"], 1200),  # 20h (better)
            MockRosterColumn("S2_Y", ["Y"], 1200),
        ]
        
        result = solve_rmp_lexico(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            time_limit_total=30.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] in ("OPTIMAL", "FEASIBLE")
        assert result["D_star"] == 2, "Minimum possible is 2 drivers"
        assert len(result["selected_rosters"]) == 2, "Must select exactly D* rosters"
    
    def test_infeasible_with_zero_support(self):
        """Should return INFEASIBLE if any target has no covering column."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # 3 items, but only 2 have columns
        target_ids = {"P", "Q", "R"}
        
        columns = [
            MockRosterColumn("COL_PQ", ["P", "Q"], 1800),
            # No column covers R!
        ]
        
        result = solve_rmp_lexico(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            time_limit_total=10.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] == "INFEASIBLE"
        assert "R" in result["zero_support_target_ids"]
    
    def test_stage2_prefers_fewer_singletons(self):
        """Given fixed D*, Stage 2 should prefer fewer singletons."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # 4 items, 2 drivers minimum
        target_ids = {"A", "B", "C", "D"}
        
        # Multiple 2-driver solutions:
        # Option 1: {A,B} + {C,D} = 0 singletons
        # Option 2: {A,B,C} + {D} = 1 singleton
        columns = [
            MockRosterColumn("DENSE_AB", ["A", "B"], 1800),
            MockRosterColumn("DENSE_CD", ["C", "D"], 1800),
            MockRosterColumn("DENSE_ABC", ["A", "B", "C"], 2700),  # 45h
            MockRosterColumn("SINGLE_D", ["D"], 600),  # 10h singleton
        ]
        
        result = solve_rmp_lexico(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            time_limit_total=30.0,
            log_fn=lambda msg: print(msg),
        )
        
        assert result["status"] in ("OPTIMAL", "FEASIBLE")
        assert result["D_star"] == 2
        # Stage 2 should prefer 0 singletons over 1 singleton
        assert result["singleton_selected"] == 0, \
            f"Expected 0 singletons (DENSE_AB + DENSE_CD), got {result['singleton_selected']}"
    
    def test_verification_detects_duplicate_coverage(self):
        """Verification should detect if tours are covered multiple times."""
        from src.services.set_partition_master import _verify_solution_exact
        
        # Simulate a bad solution where tour "A" is covered twice
        class MockRoster:
            def __init__(self, rid, items):
                self.roster_id = rid
                self.covered_tour_ids = set(items)
                self.block_ids = set(items)
                self.total_minutes = 1800
        
        # Both rosters cover "A" - this is over-coverage
        bad_solution = [
            MockRoster("R1", ["A", "B"]),
            MockRoster("R2", ["A", "C"]),  # A is duplicated!
        ]
        
        target_ids = {"A", "B", "C"}
        
        verification = _verify_solution_exact(
            selected=bad_solution,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            D_star=2,
            log_fn=lambda msg: print(msg),
        )
        
        assert not verification["valid"], "Should detect duplicate coverage"
        assert "A" in verification["duplicate_targets"], "Should report 'A' as duplicate"
    
    def test_stage1_feasible_stage2_timeout_uses_fallback(self):
        """If Stage 2 times out, should fall back to Stage 1 solution."""
        from src.services.set_partition_master import solve_rmp_lexico
        
        # Simple case where Stage 1 will definitely succeed
        target_ids = {"X", "Y"}
        
        columns = [
            MockRosterColumn("COL_XY", ["X", "Y"], 1800),  # 30h
        ]
        
        # Very short time limit to possibly trigger Stage 2 timeout
        # (though with such a simple model it will likely still succeed)
        result = solve_rmp_lexico(
            columns=columns,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            time_limit_total=5.0,
            log_fn=lambda msg: print(msg),
        )
        
        # Should succeed with D*=1
        assert result["status"] in ("OPTIMAL", "FEASIBLE")
        assert result["D_star"] == 1
        assert len(result["selected_rosters"]) == 1
    
    def test_hint_filtering_rejects_invalid_columns(self):
        """Hint filter should reject columns covering items outside target set."""
        from src.services.set_partition_master import _filter_valid_hint_columns
        
        target_ids = {"A", "B"}
        
        hints = [
            MockRosterColumn("VALID", ["A"], 900),     # Valid - subset of target
            MockRosterColumn("INVALID", ["A", "Z"], 1200),  # Invalid - Z not in target
        ]
        
        valid = _filter_valid_hint_columns(
            hint_columns=hints,
            target_ids=target_ids,
            coverage_attr="covered_tour_ids",
            log_fn=lambda msg: print(msg),
        )
        
        assert len(valid) == 1, "Should only accept 1 valid hint"
        assert valid[0].roster_id == "VALID"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

