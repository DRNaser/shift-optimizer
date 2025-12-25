from datetime import time

from src.domain.models import Tour, Weekday
from src.services.domain_lns import (
    DomainLnsContext,
    compute_forced_1er_tours,
    objective_vector,
    run_domain_lns,
)
from src.services.forecast_solver_v4 import ConfigV4, solve_capacity_phase
from src.services.smart_block_builder import build_weekly_blocks_smart, build_block_index


def _make_tours() -> list[Tour]:
    return [
        Tour(id="T1", day=Weekday.MONDAY, start_time=time(6, 0), end_time=time(8, 0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=time(8, 30), end_time=time(10, 30)),
        Tour(id="T3", day=Weekday.MONDAY, start_time=time(11, 0), end_time=time(13, 0)),
        Tour(id="T4", day=Weekday.TUESDAY, start_time=time(6, 0), end_time=time(8, 0)),
        Tour(id="T5", day=Weekday.TUESDAY, start_time=time(8, 30), end_time=time(10, 30)),
        Tour(id="T6", day=Weekday.WEDNESDAY, start_time=time(7, 0), end_time=time(9, 0)),
    ]


def _solve_phase1(tours: list[Tour]):
    blocks, _ = build_weekly_blocks_smart(tours)
    block_index = build_block_index(blocks)
    config = ConfigV4(time_limit_phase1=3.0, seed=7)
    selected, stats = solve_capacity_phase(blocks, tours, block_index, config)
    return blocks, block_index, config, selected, stats


def _assert_coverage(tours: list[Tour], selected_blocks):
    covered = {}
    for block in selected_blocks:
        for tour in block.tours:
            covered.setdefault(tour.id, 0)
            covered[tour.id] += 1
    for tour in tours:
        assert covered.get(tour.id, 0) == 1


def test_domain_lns_never_regresses_objective():
    tours = _make_tours()
    blocks, block_index, config, selected, _ = _solve_phase1(tours)
    ctx = DomainLnsContext(config=config, tours=tours, block_index=block_index)

    _, report = run_domain_lns(
        ctx,
        blocks,
        selected,
        time_budget=1.0,
        seed=11,
    )

    assert report["best_so_far_never_regresses"] is True


def test_singleton_destroy_does_not_increase_avoidable_1er():
    tours = _make_tours()
    blocks, block_index, config, selected, _ = _solve_phase1(tours)
    config = config._replace(
        domain_lns_force_operator="SINGLETON",
        domain_lns_repair_iter_seconds=0.5,
    )
    ctx = DomainLnsContext(config=config, tours=tours, block_index=block_index)

    forced_1er = compute_forced_1er_tours(tours, block_index)
    initial_vec = objective_vector(selected)
    initial_avoidable = max(0, initial_vec["count_1er"] - forced_1er)

    improved, _ = run_domain_lns(
        ctx,
        blocks,
        selected,
        time_budget=1.0,
        seed=2,
    )

    improved_vec = objective_vector(improved)
    improved_avoidable = max(0, improved_vec["count_1er"] - forced_1er)
    assert improved_avoidable <= initial_avoidable


def test_phase1_plus_domain_lns_feasible_and_covers_tours():
    tours = _make_tours()
    blocks, block_index, config, selected, _ = _solve_phase1(tours)
    config = config._replace(domain_lns_repair_iter_seconds=0.5)
    ctx = DomainLnsContext(config=config, tours=tours, block_index=block_index)

    improved, _ = run_domain_lns(
        ctx,
        blocks,
        selected,
        time_budget=1.0,
        seed=3,
    )

    _assert_coverage(tours, improved)
