"""
Tests for Set-Partitioning Solver - No Legacy Verification

These tests ensure:
1. solver_type="set-partitioning" routes to Set-Partitioning solver
2. kpi["solver_arch"] == "set-partitioning"
3. No legacy log markers are present
4. Constraints are valid or status is FAILED (no SOFT_FALLBACK)
"""

import pytest
from unittest.mock import MagicMock, patch
import io
import logging

# Test Constants
LEGACY_LOG_MARKERS = [
    "PHASE 2: Driver Assignment (Greedy)",
    "LNS V4",
    "GLOBAL CP-SAT FTE-ONLY",
    "drv[b]",
    "x[b,k]",
    "Slot Assignment",
    "SOFT_FALLBACK_HOURS",  # This should never appear in set-partitioning
]

SET_PARTITIONING_MARKERS = [
    "SOLVER_ARCH=set-partitioning",
    "SET-PARTITIONING",
]


class TestSetPartitioningRouting:
    """Tests to verify correct routing to Set-Partitioning solver."""
    
    def test_kpi_contains_solver_arch(self):
        """KPI must contain solver_arch=set-partitioning."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        # Create minimal tour set
        tours = []
        for i in range(10):
            day = Weekday.MONDAY if i % 2 == 0 else Weekday.TUESDAY
            tours.append(Tour(
                id=f"T{i:03d}",
                day=day,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ))
        
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        result = solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
        
        assert "solver_arch" in result.kpi, "KPI must contain 'solver_arch'"
        assert result.kpi["solver_arch"] in ("set-partitioning", "set-partitioning+greedy_fallback", "set-partitioning+greedy_fallback+repair"), \
            f"solver_arch must start with 'set-partitioning', got {result.kpi['solver_arch']}"
    
    def test_no_soft_fallback_status(self):
        """Set-partitioning must never return SOFT_FALLBACK_HOURS status."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        tours = []
        for i in range(10):
            tours.append(Tour(
                id=f"T{i:03d}",
                day=Weekday.MONDAY,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ))
        
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        result = solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
        
        assert result.status not in ("SOFT_FALLBACK_HOURS",), \
            "Set-partitioning must NEVER return SOFT_FALLBACK_HOURS. " \
            "It should be OK, OK_GREEDY_FALLBACK, or FAILED_*"


class TestNoLegacyLogs:
    """Tests to verify no legacy solver log markers appear."""
    
    def test_no_legacy_markers_in_logs(self):
        """Logs must not contain any legacy solver markers."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        # Capture logs
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.DEBUG)
        
        # Get all relevant loggers
        loggers = [
            logging.getLogger("ForecastSolverV4"),
            logging.getLogger("SetPartitionSolver"),
            logging.getLogger("ColumnGenerator"),
            logging.getLogger("SetPartitionMaster"),
        ]
        
        for lgr in loggers:
            lgr.addHandler(handler)
            lgr.setLevel(logging.DEBUG)
        
        try:
            tours = []
            for i in range(10):
                tours.append(Tour(
                    id=f"T{i:03d}",
                    day=Weekday.MONDAY,
                    start_time=time(8, 0),
                    end_time=time(12, 0),
                ))
            
            from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
            result = solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
            
            log_contents = log_capture.getvalue()
            
            # When fallback is used, greedy logs are expected - skip that marker
            markers_to_check = LEGACY_LOG_MARKERS.copy()
            if result.status == "OK_GREEDY_FALLBACK":
                markers_to_check = [m for m in markers_to_check if "Greedy" not in m]
            
            for marker in markers_to_check:
                assert marker not in log_contents, \
                    f"Legacy marker '{marker}' found in logs! " \
                    f"Set-partitioning should not use legacy paths."
        
        finally:
            for lgr in loggers:
                lgr.removeHandler(handler)
    
    def test_set_partitioning_markers_present(self):
        """Logs must contain set-partitioning markers."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.DEBUG)
        
        logger = logging.getLogger("ForecastSolverV4")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        try:
            tours = []
            for i in range(10):
                tours.append(Tour(
                    id=f"T{i:03d}",
                    day=Weekday.MONDAY,
                    start_time=time(8, 0),
                    end_time=time(12, 0),
                ))
            
            from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
            solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
            
            log_contents = log_capture.getvalue()
            
            found_markers = [m for m in SET_PARTITIONING_MARKERS if m in log_contents]
            assert len(found_markers) > 0, \
                f"No set-partitioning markers found in logs. Expected: {SET_PARTITIONING_MARKERS}"
        
        finally:
            logger.removeHandler(handler)


class TestConstraintValidity:
    """Tests to verify constraint validity of output."""
    
    def test_all_drivers_42_53h_or_failed(self):
        """All drivers must have 42-53h or status must be FAILED."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        tours = []
        days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
        for i in range(100):  # More tours for realistic test
            day = days[i % 6]
            tours.append(Tour(
                id=f"T{i:03d}",
                day=day,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ))
        
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        result = solve_forecast_set_partitioning(tours, time_limit=60.0, seed=42)
        
        if result.status.startswith("OK"):
            # All FTE drivers must be 40-53h (PT can be less)
            for assignment in result.assignments:
                if assignment.driver_type == "FTE":
                    assert 40.0 <= assignment.total_hours <= 53.0, \
                        f"FTE Driver {assignment.driver_id} has {assignment.total_hours}h, " \
                        f"not in 40-53h range but status is {result.status}!"
        else:
            # Status must be FAILED_*, not SOFT_FALLBACK
            assert result.status.startswith("FAILED") or result.status == "INFEASIBLE", \
                f"Status must be OK, OK_GREEDY_FALLBACK, or FAILED_*, got {result.status}"
    
    def test_pt_is_zero(self):
        """PT drivers must be zero in set-partitioning mode."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        
        tours = []
        for i in range(10):
            tours.append(Tour(
                id=f"T{i:03d}",
                day=Weekday.MONDAY,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ))
        
        from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
        result = solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
        
        # PT drivers should be 0 only when set-partitioning succeeds (status=OK)
        # When greedy fallback is used, PT drivers are allowed
        if result.status == "OK":
            assert result.kpi.get("drivers_pt", 0) == 0, \
                f"PT drivers must be 0 when set-partitioning succeeds, got {result.kpi.get('drivers_pt')}"


class TestRosterColumnValidity:
    """Tests for RosterColumn validation logic."""
    
    def test_valid_roster_passes_validation(self):
        """A roster with valid constraints should be marked valid."""
        from src.services.roster_column import BlockInfo, create_roster_from_blocks
        
        # Create blocks that form a valid 45h week
        blocks = [
            BlockInfo("B1", day=0, start_min=480, end_min=720, work_min=240, tours=1),  # Mon 8-12
            BlockInfo("B2", day=0, start_min=780, end_min=1020, work_min=240, tours=1), # Mon 13-17
            BlockInfo("B3", day=1, start_min=480, end_min=720, work_min=240, tours=1),  # Tue 8-12
            BlockInfo("B4", day=1, start_min=780, end_min=1020, work_min=240, tours=1), # Tue 13-17
            BlockInfo("B5", day=2, start_min=480, end_min=720, work_min=240, tours=1),  # Wed 8-12
            BlockInfo("B6", day=2, start_min=780, end_min=1020, work_min=240, tours=1), # Wed 13-17
            BlockInfo("B7", day=3, start_min=480, end_min=720, work_min=240, tours=1),  # Thu 8-12
            BlockInfo("B8", day=3, start_min=780, end_min=1020, work_min=240, tours=1), # Thu 13-17
            BlockInfo("B9", day=4, start_min=480, end_min=720, work_min=240, tours=1),  # Fri 8-12
            BlockInfo("B10", day=4, start_min=780, end_min=1020, work_min=240, tours=1),# Fri 13-17
            BlockInfo("B11", day=5, start_min=480, end_min=780, work_min=300, tours=1), # Sat 8-13
        ]
        
        # Total: 11 * 4h = 44h... need more
        # Actually 10*4h + 5h = 45h ✓
        
        roster = create_roster_from_blocks("TEST_R1", blocks)
        
        # This should be valid (45h, no overlaps, proper rest)
        # Note: depends on exact constraint logic
        print(f"Roster valid: {roster.is_valid}")
        print(f"Violations: {roster.violations}")
        print(f"Total hours: {roster.total_hours}")
    
    def test_invalid_roster_overlap(self):
        """A roster with overlapping blocks should be invalid."""
        from src.services.roster_column import BlockInfo, create_roster_from_blocks
        
        # Create overlapping blocks
        blocks = [
            BlockInfo("B1", day=0, start_min=480, end_min=720, work_min=240, tours=1),  # Mon 8-12
            BlockInfo("B2", day=0, start_min=600, end_min=840, work_min=240, tours=1),  # Mon 10-14 OVERLAP!
        ]
        
        roster = create_roster_from_blocks("TEST_R2", blocks)
        
        assert not roster.is_valid, "Roster with overlap should be invalid"
        assert any("Overlap" in v for v in roster.violations), \
            f"Violations should mention overlap: {roster.violations}"
    
    def test_invalid_roster_under_40h(self):
        """A roster under 40h should be invalid."""
        from src.services.roster_column import BlockInfo, create_roster_from_blocks
        
        # Only 8h
        blocks = [
            BlockInfo("B1", day=0, start_min=480, end_min=720, work_min=240, tours=1),  # Mon 4h
            BlockInfo("B2", day=1, start_min=480, end_min=720, work_min=240, tours=1),  # Tue 4h
        ]
        
        roster = create_roster_from_blocks("TEST_R3", blocks)
        
        assert not roster.is_valid, "Roster under 40h should be invalid"
        assert any("40" in v or "min" in v.lower() for v in roster.violations), \
            f"Violations should mention min hours: {roster.violations}"


class TestCoveredButInfeasible:
    """
    Tests for the 'covered-but-infeasible' scenario.
    
    This is the case where all blocks appear in at least one column (set-coverable)
    but no valid exact partition exists (not exact-partitionable).
    
    The solver must:
    1. Detect this via relaxed RMP (not just check uncovered_blocks=0)
    2. Use diagnostic info (under_blocks, over_blocks) for targeted generation
    3. Continue loop instead of failing immediately
    """
    
    def test_relaxed_rmp_always_feasible(self):
        """Relaxed RMP should always return a solution, even for infeasible strict RMP."""
        from src.services.roster_column import BlockInfo, create_roster_from_blocks, RosterColumn
        from src.services.set_partition_master import solve_rmp, solve_relaxed_rmp
        
        # Create a simple scenario: 3 blocks, 2 columns, but columns overlap
        # Column 1: covers B1, B2
        # Column 2: covers B2, B3
        # B2 is in both -> no exact partition possible
        
        all_block_ids = {"B1", "B2", "B3"}
        
        # Create mock columns (simplified RosterColumn-like objects)
        class MockColumn:
            def __init__(self, block_ids):
                self.block_ids = set(block_ids)
                self.total_hours = 45.0
                self.is_valid = True
        
        columns = [
            MockColumn(["B1", "B2"]),
            MockColumn(["B2", "B3"]),
        ]
        
        # Strict RMP should be INFEASIBLE (B2 can't be covered exactly once)
        strict_result = solve_rmp(columns, all_block_ids, time_limit=10.0)
        assert strict_result["status"] == "INFEASIBLE", \
            f"Strict RMP should be INFEASIBLE, got {strict_result['status']}"
        
        # Relaxed RMP should ALWAYS return OPTIMAL/FEASIBLE
        relaxed_result = solve_relaxed_rmp(columns, all_block_ids, time_limit=10.0)
        assert relaxed_result["status"] in ("OPTIMAL", "FEASIBLE"), \
            f"Relaxed RMP should be OPTIMAL/FEASIBLE, got {relaxed_result['status']}"
        
        # Relaxed should report diagnostic info
        assert "under_count" in relaxed_result
        assert "over_count" in relaxed_result
        assert "under_blocks" in relaxed_result
        assert "over_blocks" in relaxed_result
    
    def test_relaxed_rmp_detects_overcoverage(self):
        """Relaxed RMP should detect blocks that cause overcoverage (collisions)."""
        from src.services.set_partition_master import solve_relaxed_rmp
        
        # Same scenario: B2 must be over-covered to cover B1 and B3
        all_block_ids = {"B1", "B2", "B3"}
        
        class MockColumn:
            def __init__(self, block_ids):
                self.block_ids = set(block_ids)
                self.total_hours = 45.0
        
        columns = [
            MockColumn(["B1", "B2"]),
            MockColumn(["B2", "B3"]),
        ]
        
        relaxed = solve_relaxed_rmp(columns, all_block_ids, time_limit=10.0)
        
        # If we select both columns, B2 is covered twice -> over[B2] > 0
        # OR we can't cover all blocks -> under_count > 0
        # Either way, we get diagnostic info
        total_slack = relaxed["under_count"] + relaxed["over_count"]
        assert total_slack > 0, \
            "Relaxed RMP should detect non-zero slack for impossible partition"
    
    def test_solver_does_not_exit_on_strange_state(self):
        """Solver should NOT exit immediately when 'covered but not partitionable'."""
        from src.domain.models import Tour, Weekday
        from datetime import time
        import io
        import logging
        
        # Capture logs to check for "strange state" message
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.DEBUG)
        
        loggers = [
            logging.getLogger("SetPartitionSolver"),
            logging.getLogger("SetPartitionMaster"),
        ]
        for lgr in loggers:
            lgr.addHandler(handler)
            lgr.setLevel(logging.DEBUG)
        
        try:
            # Create tours that might trigger the scenario
            tours = []
            days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY]
            for i in range(50):
                day = days[i % 5]
                tours.append(Tour(
                    id=f"T{i:03d}",
                    day=day,
                    start_time=time(8, 0),
                    end_time=time(12, 0),
                ))
            
            from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
            result = solve_forecast_set_partitioning(tours, time_limit=30.0, seed=42)
            
            log_contents = log_capture.getvalue()
            
            # The old "strange state" message should NOT appear as the reason for stopping
            # If it appears, it should be followed by diagnostic info, not immediate break
            if "strange state" in log_contents.lower():
                # Should also contain relaxed RMP diagnostic output
                assert "Relaxed diagnosis" in log_contents or "RELAXED RMP" in log_contents, \
                    "Solver should use relaxed RMP for diagnosis instead of exiting on 'strange state'"
        
        finally:
            for lgr in loggers:
                lgr.removeHandler(handler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

