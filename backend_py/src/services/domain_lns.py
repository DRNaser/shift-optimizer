from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import logging
import random
from typing import Iterable

from src.domain.models import Block, Tour
from src.services.forecast_solver_v4 import ConfigV4, _solve_capacity_single_cap

logger = logging.getLogger("DomainLNS")


@dataclass(frozen=True)
class DomainLnsContext:
    config: ConfigV4
    tours: list[Tour]
    block_index: dict[str, list[Block]]
    block_scores: dict[str, float] | None = None
    block_props: dict[str, dict] | None = None


def objective_vector(blocks: Iterable[Block]) -> dict:
    selected = list(blocks)
    count_3er = sum(1 for b in selected if len(b.tours) == 3)
    count_2er_regular = sum(
        1 for b in selected if len(b.tours) == 2 and b.pause_zone_value == "REGULAR"
    )
    count_2er_split = sum(
        1 for b in selected if len(b.tours) == 2 and b.pause_zone_value == "SPLIT"
    )
    count_1er = sum(1 for b in selected if len(b.tours) == 1)
    return {
        "count_3er": count_3er,
        "count_2er_regular": count_2er_regular,
        "count_2er_split": count_2er_split,
        "count_1er": count_1er,
        "total_blocks": len(selected),
    }


def compare_objective_vector(current: dict, candidate: dict) -> int:
    """
    Compare two objective vectors.

    Returns:
        1 if candidate is better,
        0 if equal,
        -1 if worse
    """
    current_main = (
        current["count_3er"],
        current["count_2er_regular"],
        current["count_2er_split"],
        -current["count_1er"],
    )
    candidate_main = (
        candidate["count_3er"],
        candidate["count_2er_regular"],
        candidate["count_2er_split"],
        -candidate["count_1er"],
    )
    if candidate_main > current_main:
        return 1
    if candidate_main < current_main:
        return -1
    if candidate["total_blocks"] < current["total_blocks"]:
        return 1
    if candidate["total_blocks"] > current["total_blocks"]:
        return -1
    return 0


def compute_forced_1er_tours(tours: list[Tour], block_index: dict[str, list[Block]]) -> int:
    forced = 0
    for tour in tours:
        pool = block_index.get(tour.id, [])
        sizes = {len(b.tours) for b in pool}
        if sizes == {1}:
            forced += 1
    return forced


def run_domain_lns(
    ctx: DomainLnsContext,
    blocks: list[Block],
    initial_solution: list[Block],
    time_budget: float,
    seed: int,
) -> tuple[list[Block], dict]:
    config = ctx.config
    tours = ctx.tours
    block_index = ctx.block_index
    block_scores = ctx.block_scores
    block_props = ctx.block_props

    start_time = perf_counter()
    rng = random.Random(seed)

    best_solution = list(initial_solution)
    best_vector = objective_vector(best_solution)
    initial_vector = dict(best_vector)
    best_stats = None

    operator_stats = {}
    iteration_logs = []
    best_improvement = {
        "count_3er": 0,
        "count_2er_regular": 0,
        "count_2er_split": 0,
        "count_1er": 0,
        "total_blocks": 0,
    }
    best_so_far_never_regresses = True
    regression_reason = None

    operator_weights = {
        "DAY_PEAK": 0.4,
        "LANE": 0.35,
        "SINGLETON": 0.25,
    }

    def pick_operator() -> str:
        forced = getattr(config, "domain_lns_force_operator", None)
        if forced:
            return forced
        roll = rng.random()
        cumulative = 0.0
        for name, weight in operator_weights.items():
            cumulative += weight
            if roll <= cumulative:
                return name
        return "DAY_PEAK"

    def clamp_destroy_size(size: int) -> int:
        min_destroy = getattr(config, "domain_lns_min_destroy_blocks", 50)
        max_destroy = getattr(config, "domain_lns_max_destroy_blocks", 400)
        return max(min_destroy, min(max_destroy, size))

    def expand_destroy_set(base_blocks: list[Block]) -> set[str]:
        destroy_ids = {b.id for b in base_blocks}
        tour_ids = {t.id for b in base_blocks for t in b.tours}
        for tour_id in tour_ids:
            for candidate in block_index.get(tour_id, []):
                destroy_ids.add(candidate.id)
        return destroy_ids

    def select_peak_day() -> str | None:
        day_counts = {}
        for tour in tours:
            day_counts[tour.day.value] = day_counts.get(tour.day.value, 0) + 1
        if not day_counts:
            return None
        return max(day_counts.items(), key=lambda x: x[1])[0]

    def day_peak_destroy(selected: list[Block]) -> list[Block]:
        peak_day = select_peak_day()
        if not peak_day:
            return []
        peak_window_start = 10 * 60
        peak_window_end = 22 * 60 + 30
        day_blocks = [b for b in selected if b.day.value == peak_day]
        if not day_blocks:
            return []
        peak_window_blocks = []
        for block in day_blocks:
            for tour in block.tours:
                start_min = tour.start_time.hour * 60 + tour.start_time.minute
                if peak_window_start <= start_min <= peak_window_end:
                    peak_window_blocks.append(block)
                    break
        return peak_window_blocks or day_blocks

    def lane_destroy(selected: list[Block]) -> list[Block]:
        lane_windows = [
            (5 * 60, 8 * 60),
            (8 * 60, 11 * 60),
            (11 * 60, 14 * 60),
            (14 * 60, 17 * 60),
        ]
        window = lane_windows[rng.randrange(len(lane_windows))]
        start_min, end_min = window
        lane_blocks = []
        lane_tours = []
        for block in selected:
            for tour in block.tours:
                tour_start = tour.start_time.hour * 60 + tour.start_time.minute
                if start_min <= tour_start <= end_min:
                    lane_blocks.append(block)
                    lane_tours.append(tour)
                    break
        if not lane_tours:
            return lane_blocks
        chainable_tours = set()
        for tour in lane_tours:
            end_minute = tour.end_time.hour * 60 + tour.end_time.minute
            for candidate in tours:
                if candidate.day != tour.day:
                    continue
                cand_start = candidate.start_time.hour * 60 + candidate.start_time.minute
                if end_minute + 30 <= cand_start <= end_minute + 60:
                    chainable_tours.add(candidate.id)
        for tour_id in chainable_tours:
            for candidate in block_index.get(tour_id, []):
                lane_blocks.append(candidate)
        return lane_blocks

    def singleton_destroy(selected: list[Block]) -> list[Block]:
        return [b for b in selected if len(b.tours) == 1]

    destroy_map = {
        "DAY_PEAK": day_peak_destroy,
        "LANE": lane_destroy,
        "SINGLETON": singleton_destroy,
    }

    iter_count = 0
    total_time_budget = max(0.0, time_budget)
    while perf_counter() - start_time < total_time_budget:
        iter_start = perf_counter()
        remaining = total_time_budget - (iter_start - start_time)
        if remaining <= 0:
            break

        operator = pick_operator()
        destroy_fn = destroy_map[operator]
        base_destroy = destroy_fn(best_solution)
        base_destroy = list({b.id: b for b in base_destroy}.values())
        if not base_destroy:
            logger.info("Domain LNS: empty destroy set, stopping")
            break

        target_size = clamp_destroy_size(int(len(best_solution) * getattr(
            config, "domain_lns_destroy_fraction_default", 0.2
        )))
        if len(base_destroy) > target_size:
            base_destroy = rng.sample(base_destroy, target_size)

        if len(base_destroy) < target_size and len(base_destroy) < len(best_solution):
            extra_needed = target_size - len(base_destroy)
            remaining_blocks = [b for b in best_solution if b not in base_destroy]
            extra_blocks = rng.sample(
                remaining_blocks,
                min(extra_needed, len(remaining_blocks)),
            )
            base_destroy.extend(extra_blocks)

        destroy_ids = expand_destroy_set(base_destroy)

        max_destroy = getattr(config, "domain_lns_max_destroy_blocks", 400)
        while len(destroy_ids) > max_destroy and len(base_destroy) > 1:
            base_destroy.pop()
            destroy_ids = expand_destroy_set(base_destroy)

        current_solution_ids = {b.id for b in best_solution}
        fixed_use = {}
        for block in blocks:
            if block.id not in destroy_ids:
                fixed_use[block.id] = 1 if block.id in current_solution_ids else 0

        protected_3er = {
            b.id for b in best_solution if len(b.tours) == 3 and b.id not in destroy_ids
        }
        for block_id in protected_3er:
            fixed_use[block_id] = 1

        iter_time_limit = min(
            getattr(config, "domain_lns_repair_iter_seconds", 1.0),
            max(0.1, remaining),
        )
        hint_use = current_solution_ids

        result = _solve_capacity_single_cap(
            blocks,
            tours,
            block_index,
            config,
            block_scores=block_scores,
            block_props=block_props,
            time_limit=iter_time_limit,
            fixed_use=fixed_use,
            hint_use=hint_use,
        )

        iter_count += 1
        if result is None or result[0] is None:
            iteration_logs.append({
                "operator": operator,
                "destroy_size": len(destroy_ids),
                "status": "FAILED",
                "objective_before": dict(best_vector),
                "objective_after": None,
                "delta": None,
            })
            continue

        candidate_solution, candidate_stats = result
        candidate_vector = objective_vector(candidate_solution)
        comparison = compare_objective_vector(best_vector, candidate_vector)

        delta = {
            key: candidate_vector[key] - best_vector[key]
            for key in best_vector.keys()
        }

        iteration_logs.append({
            "operator": operator,
            "destroy_size": len(destroy_ids),
            "status": candidate_stats.get("status", "UNKNOWN"),
            "objective_before": dict(best_vector),
            "objective_after": dict(candidate_vector),
            "delta": delta,
        })

        operator_stats.setdefault(operator, {"count": 0, "delta_sum": {k: 0 for k in delta}})
        operator_stats[operator]["count"] += 1
        for key in delta:
            operator_stats[operator]["delta_sum"][key] += delta[key]

        if comparison > 0:
            logger.info(
                "Domain LNS accepted: %s -> %s",
                best_vector,
                candidate_vector,
            )
            best_solution = candidate_solution
            best_vector = candidate_vector
            best_stats = candidate_stats
            best_improvement = {
                key: best_vector[key] - initial_vector[key]
                for key in best_vector.keys()
            }
        else:
            logger.info(
                "Domain LNS rejected: %s -> %s",
                best_vector,
                candidate_vector,
            )

        if comparison > 0 and compare_objective_vector(initial_vector, best_vector) < 0:
            best_so_far_never_regresses = False
            regression_reason = "Best solution regressed below initial objective"

    lns_time_spent = perf_counter() - start_time

    operator_summary = {}
    for name, stats in operator_stats.items():
        count = stats["count"]
        delta_sum = stats["delta_sum"]
        operator_summary[name] = {
            "count": count,
            "avg_delta": {
                key: round(delta_sum[key] / count, 3) if count else 0
                for key in delta_sum
            },
        }

    lns_report = {
        "lns_iterations": iter_count,
        "lns_best_improvement_vector": best_improvement,
        "lns_operator_stats": operator_summary,
        "lns_time_spent": round(lns_time_spent, 2),
        "best_so_far_never_regresses": best_so_far_never_regresses,
        "regression_reason": regression_reason,
        "iteration_logs": iteration_logs,
    }

    if best_stats is not None:
        lns_report["solution_stats"] = best_stats

    return best_solution, lns_report
