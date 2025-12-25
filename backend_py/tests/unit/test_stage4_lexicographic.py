from datetime import time

from src.domain.models import Tour, Weekday
from src.services.smart_block_builder import build_weekly_blocks_smart, build_block_index
from src.services.forecast_solver_v4 import ConfigV4, solve_capacity_phase, _pause_zone_value


def test_stage4_prefers_split_over_singles():
    tours = [
        Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=time(16, 0), end_time=time(20, 0)),
    ]

    blocks, block_stats = build_weekly_blocks_smart(tours, output_profile="BEST_BALANCED")
    block_index = build_block_index(blocks)

    config = ConfigV4(time_limit_phase1=10.0, max_blocks=5000, output_profile="BEST_BALANCED")
    selected, stats = solve_capacity_phase(
        blocks,
        tours,
        block_index,
        config,
        block_scores=block_stats.get("block_scores", {}),
        block_props=block_stats.get("block_props", {}),
        time_limit=5.0,
    )

    assert len(selected) == 1
    assert len(selected[0].tours) == 2
    assert _pause_zone_value(selected[0]) == "SPLIT"
    assert stats["stage4_subsolve_statuses"]["min_1er"] in ("OPTIMAL", "FEASIBLE")
