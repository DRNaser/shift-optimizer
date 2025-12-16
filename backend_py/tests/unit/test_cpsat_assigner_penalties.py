"""
Tests for CP-SAT assignment penalty tuning
"""

from datetime import time

from src.domain.models import Block, Tour, Weekday
from src.services.cpsat_assigner import assign_drivers_cpsat
from src.services.forecast_solver_v4 import ConfigV4


def _make_block(block_id: str, day: Weekday, start: time, end: time) -> Block:
    return Block(
        id=block_id,
        day=day,
        tours=[
            Tour(
                id=f"T_{block_id}",
                day=day,
                start_time=start,
                end_time=end,
            )
        ],
    )


def test_pt_underutilization_penalized_in_stats():
    """Tiny PT activations should be surfaced in stats for monitoring."""

    # Block requires PT because it exceeds the FTE weekly max in this config
    block = _make_block(
        "B1",
        Weekday.MONDAY,
        start=time(8, 0),
        end=time(12, 0),
    )

    config = ConfigV4(
        min_hours_per_fte=3.0,
        max_hours_per_fte=3.0,
        pt_min_hours=8.0,
        time_limit_phase2=5.0,
    )

    assignments, stats = assign_drivers_cpsat([block], config, warm_start=None, time_limit=5.0)

    assert len(assignments) == 1
    assert assignments[0].driver_type == "PT"

    # Under-utilization should capture the 4h shortfall against the 8h PT target
    assert stats["pt_under_util_minutes"] == 240
    # PT day tracking should count the working day
    assert stats["pt_working_days"] == 1
