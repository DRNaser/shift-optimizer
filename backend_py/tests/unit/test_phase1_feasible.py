from datetime import time as dt_time

from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import ConfigV4, solve_capacity_phase
from src.services.smart_block_builder import build_block_index, build_weekly_blocks_smart


def test_phase1_returns_feasible_solution():
    tours = [
        Tour(id="T1", day=Weekday.MONDAY, start_time=dt_time(8, 0), end_time=dt_time(9, 0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=dt_time(9, 30), end_time=dt_time(10, 30)),
        Tour(id="T3", day=Weekday.TUESDAY, start_time=dt_time(8, 0), end_time=dt_time(9, 0)),
    ]
    blocks, stats = build_weekly_blocks_smart(tours)
    block_index = build_block_index(blocks)
    config = ConfigV4(time_limit_phase1=2.0, seed=42)

    selected, phase1_stats = solve_capacity_phase(
        blocks=blocks,
        tours=tours,
        block_index=block_index,
        config=config,
        block_scores=stats.get("block_scores"),
        block_props=stats.get("block_props"),
        time_limit=2.0,
    )

    assert phase1_stats.get("phase1_status") in {"OPTIMAL", "FEASIBLE"}
    covered = {t.id for b in selected for t in b.tours}
    assert {t.id for t in tours} <= covered
