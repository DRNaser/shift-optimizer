"""
Unit tests for Domain LNS (Phase 1 Block Selection Improvement).

Tests:
1. Lexicographic acceptance logic
2. LNS never returns UNKNOWN as final status
3. Move trigger conditions
"""

import pytest
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# IMPORTS FROM MODULE UNDER TEST
# =============================================================================

from src.services.domain_lns import (
    DomainLNSConfig,
    Phase1Solution,
    DomainLNSResult,
    MoveResult,
    is_lexicographically_better,
    should_trigger_move1,
    should_trigger_move2,
    compute_phase1_telemetry,
    run_domain_lns,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_solution():
    """Create a sample Phase1Solution for testing."""
    sol = Phase1Solution()
    sol.total_3er = 10
    sol.total_2er = 20
    sol.total_singles = 50
    sol.total_tours = 100
    sol.tours_by_day = {"Mon": 30, "Tue": 25, "Wed": 20, "Thu": 15, "Fri": 10}
    sol.chains_3_by_day = {"Mon": 5, "Tue": 3, "Wed": 2, "Thu": 0, "Fri": 0}
    sol.singles_by_day = {"Mon": 10, "Tue": 12, "Wed": 15, "Thu": 8, "Fri": 5}
    sol.singles_with_extension_possible_by_day = {"Mon": 5, "Tue": 8, "Wed": 10, "Thu": 3, "Fri": 0}
    return sol


@pytest.fixture
def default_config():
    """Create default DomainLNSConfig."""
    return DomainLNSConfig()


# =============================================================================
# TEST: LEXICOGRAPHIC ACCEPTANCE
# =============================================================================

class TestLexicographicAcceptance:
    """Ensure strict lexicographic ordering: 3er > 2er > singles > tours."""
    
    def test_accept_when_3er_increases(self):
        """Candidate that increases 3er should be accepted."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 11  # +1 improvement
        candidate.total_2er = 18  # worse
        candidate.total_singles = 55  # worse
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is True
        assert "3er" in reason
    
    def test_reject_when_3er_decreases(self):
        """Candidate that decreases 3er must be rejected, even if other metrics improve."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 9   # worse
        candidate.total_2er = 25  # better
        candidate.total_singles = 40  # better
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is False
        assert "rejected" in reason
        assert "3er" in reason
    
    def test_accept_when_2er_increases_3er_equal(self):
        """When 3er equal, accept if 2er increases."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 10  # equal
        candidate.total_2er = 22  # +2 improvement
        candidate.total_singles = 50
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is True
        assert "2er" in reason
    
    def test_reject_when_2er_decreases_3er_equal(self):
        """When 3er equal, reject if 2er decreases."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 10  # equal
        candidate.total_2er = 18  # worse
        candidate.total_singles = 40  # better
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is False
        assert "rejected" in reason
    
    def test_accept_when_singles_decrease_others_equal(self):
        """When 3er and 2er equal, accept if singles decrease."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 10
        candidate.total_2er = 20
        candidate.total_singles = 45  # -5 improvement
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is True
        assert "singles" in reason
    
    def test_reject_when_all_equal(self):
        """When all metrics equal, reject (no improvement)."""
        current = Phase1Solution()
        current.total_3er = 10
        current.total_2er = 20
        current.total_singles = 50
        current.total_tours = 100
        
        candidate = Phase1Solution()
        candidate.total_3er = 10
        candidate.total_2er = 20
        candidate.total_singles = 50
        candidate.total_tours = 100
        
        accepted, reason = is_lexicographically_better(candidate, current)
        assert accepted is False
        assert "no_improvement" in reason


# =============================================================================
# TEST: LNS NEVER RETURNS UNKNOWN
# =============================================================================

class TestLNSNeverReturnsUnknown:
    """Ensure LNS wrapper never returns UNKNOWN as final status."""
    
    def test_disabled_returns_disabled_status(self, sample_solution):
        """When disabled, should return DISABLED status, not UNKNOWN."""
        config = DomainLNSConfig(enabled=False)
        
        def mock_solve_fn(fixed, hints, constraints, time_limit):
            return "UNKNOWN", []
        
        result = run_domain_lns(sample_solution, [], [], config, mock_solve_fn)
        
        assert result.lns_status == "DISABLED"
        assert result.lns_status != "UNKNOWN"
    
    def test_fallback_to_best_on_solve_failure(self, sample_solution):
        """If all solves fail, return original solution, not UNKNOWN."""
        config = DomainLNSConfig(
            enabled=True,
            global_time_limit=5.0,
            stagnation_limit=2,
        )
        
        # Mock solve that always returns UNKNOWN
        call_count = [0]
        def mock_solve_fn(fixed, hints, constraints, time_limit):
            call_count[0] += 1
            return "UNKNOWN", []
        
        result = run_domain_lns(sample_solution, [], [], config, mock_solve_fn)
        
        # Should return STAGNATION or NO_IMPROVEMENT, never UNKNOWN
        assert result.lns_status in ("STAGNATION", "NO_IMPROVEMENT", "TIME_LIMIT")
        assert result.lns_status != "UNKNOWN"
        # Original solution should be preserved
        assert result.best_solution.total_3er == sample_solution.total_3er
    
    def test_valid_statuses_only(self, sample_solution):
        """Result status must be one of the defined values."""
        valid_statuses = {"DISABLED", "IMPROVED", "NO_IMPROVEMENT", "TIME_LIMIT", "STAGNATION"}
        
        config = DomainLNSConfig(enabled=True, global_time_limit=2.0)
        
        def mock_solve_fn(fixed, hints, constraints, time_limit):
            return "FEASIBLE", []
        
        result = run_domain_lns(sample_solution, [], [], config, mock_solve_fn)
        
        assert result.lns_status in valid_statuses


# =============================================================================
# TEST: MOVE TRIGGERING
# =============================================================================

class TestMoveTriggering:
    """Test move trigger conditions."""
    
    def test_move1_skipped_when_score_low(self, default_config):
        """Move 1 should not trigger when peak day score <= threshold."""
        sol = Phase1Solution()
        sol.tours_by_day = {"Mon": 10}
        sol.chains_3_by_day = {"Mon": 8}  # High ratio
        sol.singles_by_day = {"Mon": 2}   # Low singles
        
        triggered, target_day, score = should_trigger_move1(sol, default_config)
        
        # Score = 2*2.0 + (1-0.8)*10 = 4.0 + 2.0 = 6.0, but singles too low
        assert triggered is False
    
    def test_move1_triggers_on_high_score(self, default_config):
        """Move 1 should trigger when score is high enough."""
        sol = Phase1Solution()
        sol.tours_by_day = {"Mon": 100}
        sol.chains_3_by_day = {"Mon": 10}  # 10% ratio
        sol.singles_by_day = {"Mon": 30}   # High singles
        
        triggered, target_day, score = should_trigger_move1(sol, default_config)
        
        # Score = 30*2.0 + (1-0.1)*100 = 60 + 90 = 150
        assert triggered is True
        assert target_day == "Mon"
        assert score > default_config.move1_min_score_threshold
    
    def test_move2_skipped_when_avoidable_low(self, default_config):
        """Move 2 should not trigger when avoidable singles is low."""
        sol = Phase1Solution()
        sol.singles_with_extension_possible_by_day = {"Mon": 5, "Tue": 5}  # 10 total
        sol.total_singles = 200  # 5% avoidable
        
        triggered, target_tours = should_trigger_move2(sol, default_config)
        
        # 10 <= 20 (abs) AND 10 <= 0.10*200=20 (pct), so should not trigger
        assert triggered is False
    
    def test_move2_triggers_on_high_avoidable(self, default_config):
        """Move 2 should trigger when avoidable singles exceeds threshold."""
        sol = Phase1Solution()
        sol.singles_with_extension_possible_by_day = {"Mon": 15, "Tue": 10}  # 25 total
        sol.total_singles = 100
        sol.selected_blocks = []  # Empty for this test
        sol.tours_by_day = {"Mon": 50, "Tue": 30}
        
        triggered, target_tours = should_trigger_move2(sol, default_config)
        
        # 25 > 20 (abs threshold), so should trigger
        assert triggered is True


# =============================================================================
# TEST: SEPARATE TELEMETRY
# =============================================================================

class TestSeparateTelemetry:
    """Ensure LNS uses separate telemetry fields."""
    
    def test_result_has_lns_specific_fields(self, sample_solution):
        """DomainLNSResult should have lns_status, lns_iterations, etc."""
        config = DomainLNSConfig(enabled=True, global_time_limit=1.0)
        
        def mock_solve_fn(fixed, hints, constraints, time_limit):
            return "FEASIBLE", []
        
        result = run_domain_lns(sample_solution, [], [], config, mock_solve_fn)
        
        # Check that LNS-specific fields exist and are populated
        assert hasattr(result, 'lns_status')
        assert hasattr(result, 'lns_iterations')
        assert hasattr(result, 'lns_moves_accepted')
        assert hasattr(result, 'lns_time_s')
        assert hasattr(result, 'delta_3er_total')
        
        # These should NOT be named phase1_*
        assert not hasattr(result, 'phase1_status')
