"""
S3.4 Phase 3 Repair Upgrades Tests
==================================
Tests for bounded PT→FTE swaps, determinism, and budget compliance.
"""

import pytest
from datetime import time


class TestS31MovesHappen:
    """S3.4: Test that repair moves actually happen when legal."""
    
    def test_pt_block_moves_to_underfull_fte(self):
        """
        Construct small instance where PT block can legally move to underfull FTE.
        Assert: moves_applied >= 1.
        """
        from src.services.forecast_solver_v4 import (
            repair_pt_to_fte_swaps, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()  # min=42, target=49.5
        
        # Create a simple block
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(14, 0))
        block = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
        
        # FTE with 38h (underfull)
        fte = DriverAssignment(
            driver_id="FTE-001",
            driver_type="FTE",
            blocks=[],  # Empty, can receive
            total_hours=38.0,
            days_worked=4,
        )
        
        # PT with one 8h block (block.total_work_hours calculated from tours)
        pt = DriverAssignment(
            driver_id="PT-001",
            driver_type="PT",
            blocks=[block],
            total_hours=8.0,
            days_worked=1,
        )
        
        assignments = [fte, pt]
        
        # Use simple always-True feasibility check
        def always_ok(existing_blocks, new_block):
            return True
        
        updated, stats = repair_pt_to_fte_swaps(assignments, config, can_assign_fn=always_ok)
        
        # Should have made a move
        assert stats.moves_applied >= 1, f"Expected at least 1 move, got {stats.moves_applied}"
        assert "REPAIR_SWAP" in stats.reason_codes


class TestS31BoundRespected:
    """S3.4: Test that BLOCK_LIMIT is respected."""
    
    def test_block_limit_stops_moves(self):
        """Assert: moves_applied <= BLOCK_LIMIT."""
        from src.services.forecast_solver_v4 import (
            repair_pt_to_fte_swaps, ConfigV4, DriverAssignment, REPAIR_BLOCK_LIMIT
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        # Create 200 blocks for PT (more than BLOCK_LIMIT)
        blocks = []
        for i in range(200):
            t = Tour(id=f"T{i:03d}", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(7, 0))
            b = Block(id=f"B-{i:03d}", day=Weekday.MONDAY, tours=[t])
            blocks.append(b)
        
        # FTE that can receive unlimited
        fte = DriverAssignment(
            driver_id="FTE-001",
            driver_type="FTE",
            blocks=[],
            total_hours=20.0,  # Very underfull
            days_worked=3,
        )
        
        # PT with many blocks
        pt = DriverAssignment(
            driver_id="PT-001",
            driver_type="PT",
            blocks=blocks,
            total_hours=200.0,
            days_worked=5,
        )
        
        assignments = [fte, pt]
        
        # Use always-ok feasibility (unrealistic but tests bound)
        def always_ok(existing_blocks, new_block):
            return True
        
        # Force max_hours high
        updated, stats = repair_pt_to_fte_swaps(assignments, config._replace(max_hours_per_fte=500.0), can_assign_fn=always_ok)
        
        # Should respect BLOCK_LIMIT
        assert stats.moves_applied <= REPAIR_BLOCK_LIMIT, f"Exceeded BLOCK_LIMIT: {stats.moves_applied}"


class TestS32Determinism:
    """S3.4: Test deterministic tie-break ordering."""
    
    def test_same_input_same_output(self):
        """Same input should produce identical results."""
        from src.services.forecast_solver_v4 import (
            repair_pt_to_fte_swaps, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        def create_input():
            t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(14, 0))
            block = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
            
            fte = DriverAssignment("FTE-001", "FTE", [], 38.0, 4)
            pt = DriverAssignment("PT-001", "PT", [block], 8.0, 1)
            
            return [fte, pt]
        
        def always_ok(existing_blocks, new_block):
            return True
        
        updated1, stats1 = repair_pt_to_fte_swaps(create_input(), config, can_assign_fn=always_ok)
        updated2, stats2 = repair_pt_to_fte_swaps(create_input(), config, can_assign_fn=always_ok)
        
        # Stats must be identical
        assert stats1.moves_applied == stats2.moves_applied
        assert stats1.pt_before == stats2.pt_before
        assert stats1.pt_after == stats2.pt_after
        
        # Block IDs must be identical
        ids1 = sorted([b.id for a in updated1 for b in a.blocks])
        ids2 = sorted([b.id for a in updated2 for b in a.blocks])
        assert ids1 == ids2


class TestS33NoUnboundedLoop:
    """S3.4: Test that repair stops on no progress."""
    
    def test_stops_when_no_progress(self):
        """Repair should stop quickly when no moves are possible."""
        from src.services.forecast_solver_v4 import (
            repair_pt_to_fte_swaps, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(14, 0))
        block = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
        
        # FTE already at max hours
        fte = DriverAssignment("FTE-001", "FTE", [], 53.0, 5)  # At max
        pt = DriverAssignment("PT-001", "PT", [block], 8.0, 1)
        
        assignments = [fte, pt]
        
        # Feasibility always False (simulates no valid moves)
        def never_ok(existing_blocks, new_block):
            return False
        
        updated, stats = repair_pt_to_fte_swaps(assignments, config, can_assign_fn=never_ok)
        
        # Should stop with NO_PROGRESS
        assert stats.moves_applied == 0
        assert "NO_PROGRESS" in stats.reason_codes


class TestS34RepairStats:
    """S3.4: Test RepairStats populates correctly."""
    
    def test_stats_before_after(self):
        """Stats should correctly count before/after."""
        from src.services.forecast_solver_v4 import (
            repair_pt_to_fte_swaps, ConfigV4, DriverAssignment
        )
        from src.domain.models import Block, Tour, Weekday
        
        config = ConfigV4()
        
        t1 = Tour(id="T001", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(14, 0))
        block = Block(id="B1-001", day=Weekday.MONDAY, tours=[t1])
        
        # 1 underfull FTE, 1 PT
        fte = DriverAssignment("FTE-001", "FTE", [], 38.0, 4)  # Underfull
        pt = DriverAssignment("PT-001", "PT", [block], 8.0, 1)
        
        assignments = [fte, pt]
        
        def always_ok(existing_blocks, new_block):
            return True
        
        updated, stats = repair_pt_to_fte_swaps(assignments, config, can_assign_fn=always_ok)
        
        # Initial counts
        assert stats.pt_before == 1
        assert stats.underfull_fte_before == 1
        
        # After repair (PT eliminated, FTE now has hours)
        # PT should be 0 if block moved, underfull could be 0 if hours crossed threshold
