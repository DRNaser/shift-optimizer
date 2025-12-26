"""
Domain-Specific LNS for Phase 1 Block Selection
================================================

Implements structured neighborhood search moves:
- Move 1: Peak-Day Lane Rebuild
- Move 2: Singleton Eater
- Move 3/4/5: Stubs for future implementation

This module operates at the Phase 1 level (use_block variables),
improving block mix quality (more 3er/2er, fewer avoidable singles).
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
from collections import defaultdict
from time import perf_counter
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class DomainLNSConfig:
    """Configuration for domain-specific LNS."""
    
    # Global settings
    enabled: bool = True
    global_time_limit: float = 60.0
    stagnation_limit: int = 6
    seed: int = 42
    
    # Move 1: Peak-Day Lane Rebuild
    move1_time_budget: float = 15.0
    move1_protection_delta_3er: int = 2
    move1_protection_delta_2er: int = 5
    move1_min_score_threshold: float = 5.0
    move1_min_singles_threshold: int = 10
    
    # Move 2: Singleton Eater
    move2_time_budget: float = 12.0
    move2_avoidable_threshold_abs: int = 20
    move2_avoidable_threshold_pct: float = 0.10
    move2_target_singles_min: int = 80
    move2_target_singles_max: int = 150
    move2_local_singles_delta: int = 5
    
    # Move schedule (per outer loop)
    move1_attempts_per_loop: int = 2
    move2_attempts_per_loop: int = 4


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Phase1Solution:
    """
    Tracks a Phase 1 solution for LNS.
    Best_so_far is maintained as an instance of this class.
    """
    use_block_values: dict = field(default_factory=dict)
    selected_blocks: list = field(default_factory=list)
    
    total_3er: int = 0
    total_2er: int = 0
    total_singles: int = 0
    total_tours: int = 0
    total_splits: int = 0
    
    tours_by_day: dict = field(default_factory=dict)
    chains_3_by_day: dict = field(default_factory=dict)
    chains_2_by_day: dict = field(default_factory=dict)
    singles_by_day: dict = field(default_factory=dict)
    
    singles_with_extension_possible_by_day: dict = field(default_factory=dict)
    
    @property
    def objective_tuple(self) -> tuple:
        return (self.total_3er, self.total_2er, -self.total_singles, -self.total_tours)
    
    def to_log_dict(self) -> dict:
        return {
            "total_3er": self.total_3er,
            "total_2er": self.total_2er,
            "total_singles": self.total_singles,
            "total_tours": self.total_tours,
            "total_splits": self.total_splits,
        }


@dataclass
class MoveResult:
    """Result of a single move attempt."""
    move_id: str
    target_day: Optional[str] = None
    unfixed_block_count: int = 0
    
    delta_3er: int = 0
    delta_2er: int = 0
    delta_singles: int = 0
    delta_tours: int = 0
    
    accepted: bool = False
    reason: str = ""
    solve_status: str = ""
    solve_time_s: float = 0.0
    new_blocks: list = field(default_factory=list)


@dataclass
class DomainLNSResult:
    """
    Complete result from Domain LNS with SEPARATE telemetry fields.
    Never overwrites phase1_status - uses lns_status instead.
    """
    best_solution: Phase1Solution
    
    lns_status: str = "NOT_RUN"
    lns_iterations: int = 0
    lns_moves_accepted: int = 0
    lns_moves_rejected: int = 0
    lns_time_s: float = 0.0
    
    move1_attempts: int = 0
    move1_accepted: int = 0
    move2_attempts: int = 0
    move2_accepted: int = 0
    
    delta_3er_total: int = 0
    delta_2er_total: int = 0
    delta_singles_total: int = 0


# =============================================================================
# TELEMETRY COMPUTATION
# =============================================================================

def compute_phase1_telemetry(
    selected_blocks: list,
    all_blocks: list,
    adjacency_gap_minutes: int = 60,
) -> Phase1Solution:
    """Compute full telemetry from a Phase 1 solution."""
    solution = Phase1Solution()
    solution.selected_blocks = list(selected_blocks)
    
    selected_ids = {b.id for b in selected_blocks}
    for block in all_blocks:
        solution.use_block_values[block.id] = 1 if block.id in selected_ids else 0
    
    for block in selected_blocks:
        n_tours = len(block.tours)
        day = block.day.value if hasattr(block.day, 'value') else str(block.day)
        
        if n_tours >= 3:
            solution.total_3er += 1
            solution.chains_3_by_day[day] = solution.chains_3_by_day.get(day, 0) + 1
        elif n_tours == 2:
            solution.total_2er += 1
            solution.chains_2_by_day[day] = solution.chains_2_by_day.get(day, 0) + 1
            if hasattr(block, 'is_split') and block.is_split:
                solution.total_splits += 1
        else:
            solution.total_singles += 1
            solution.singles_by_day[day] = solution.singles_by_day.get(day, 0) + 1
        
        solution.tours_by_day[day] = solution.tours_by_day.get(day, 0) + n_tours
    
    solution.total_tours = sum(len(b.tours) for b in selected_blocks)
    solution.singles_with_extension_possible_by_day = _compute_extension_possible(
        selected_blocks, all_blocks, adjacency_gap_minutes
    )
    
    return solution


def _compute_extension_possible(selected_blocks: list, all_blocks: list, gap_minutes: int = 60) -> dict:
    """Count singles that have extension possibility."""
    result = defaultdict(int)
    
    singletons = [b for b in selected_blocks if len(b.tours) == 1]
    if not singletons:
        return dict(result)
    
    tour_to_adjacent_blocks = defaultdict(set)
    for block in all_blocks:
        if len(block.tours) <= 1:
            continue
        for tour in block.tours:
            tour_to_adjacent_blocks[tour.id].add(block.id)
    
    for singleton in singletons:
        tour = singleton.tours[0]
        day = singleton.day.value if hasattr(singleton.day, 'value') else str(singleton.day)
        if tour.id in tour_to_adjacent_blocks:
            result[day] += 1
    
    return dict(result)


def build_block_adjacency(all_blocks: list, gap_minutes: int = 60) -> dict:
    """Build adjacency graph: block_id -> set of adjacent block_ids."""
    adjacency = defaultdict(set)
    
    tour_to_blocks = defaultdict(set)
    for block in all_blocks:
        for tour in block.tours:
            tour_to_blocks[tour.id].add(block.id)
    
    for tour_id, block_ids in tour_to_blocks.items():
        for bid in block_ids:
            adjacency[bid].update(block_ids - {bid})
    
    return dict(adjacency)


# =============================================================================
# LEXICOGRAPHIC ACCEPTANCE
# =============================================================================

def is_lexicographically_better(candidate: Phase1Solution, current: Phase1Solution) -> tuple:
    """Check if candidate solution is lexicographically better than current."""
    if candidate.total_3er > current.total_3er:
        return True, f"3er_improved:{current.total_3er}->{candidate.total_3er}"
    if candidate.total_3er < current.total_3er:
        return False, f"rejected:3er_decreased:{current.total_3er}->{candidate.total_3er}"
    
    if candidate.total_2er > current.total_2er:
        return True, f"2er_improved:{current.total_2er}->{candidate.total_2er}"
    if candidate.total_2er < current.total_2er:
        return False, f"rejected:2er_decreased:{current.total_2er}->{candidate.total_2er}"
    
    if candidate.total_singles < current.total_singles:
        return True, f"singles_reduced:{current.total_singles}->{candidate.total_singles}"
    if candidate.total_singles > current.total_singles:
        return False, f"rejected:singles_increased:{current.total_singles}->{candidate.total_singles}"
    
    if candidate.total_tours < current.total_tours:
        return True, f"tours_reduced:{current.total_tours}->{candidate.total_tours}"
    if candidate.total_tours > current.total_tours:
        return False, f"rejected:tours_increased:{current.total_tours}->{candidate.total_tours}"
    
    return False, "rejected:no_improvement"


# =============================================================================
# MOVE 1: PEAK-DAY LANE REBUILD
# =============================================================================

def should_trigger_move1(solution: Phase1Solution, config: DomainLNSConfig) -> tuple:
    """Check if Move 1 should trigger."""
    if not solution.tours_by_day:
        return False, None, 0.0
    
    best_day = None
    best_score = 0.0
    
    for day, tours_count in solution.tours_by_day.items():
        if tours_count == 0:
            continue
        
        chains_3 = solution.chains_3_by_day.get(day, 0)
        singles = solution.singles_by_day.get(day, 0)
        
        ratio_3er = chains_3 / max(1, tours_count)
        score = singles * 2.0 + (1.0 - ratio_3er) * tours_count
        
        if score > best_score:
            best_score = score
            best_day = day
    
    if best_score <= config.move1_min_score_threshold:
        return False, best_day, best_score
    
    best_singles = solution.singles_by_day.get(best_day, 0)
    if best_singles <= config.move1_min_singles_threshold:
        return False, best_day, best_score
    
    return True, best_day, best_score


def compute_move1_neighborhood(solution: Phase1Solution, all_blocks: list, target_day: str) -> tuple:
    """Compute fixed and unfixed block sets for Move 1."""
    fixed_ids = set()
    unfixed_ids = set()
    
    for block in all_blocks:
        day = block.day.value if hasattr(block.day, 'value') else str(block.day)
        if day == target_day:
            unfixed_ids.add(block.id)
        else:
            fixed_ids.add(block.id)
    
    return fixed_ids, unfixed_ids


def get_move1_protection_constraints(solution: Phase1Solution, config: DomainLNSConfig) -> list:
    """Get temporary protection constraints for Move 1."""
    return [
        ("total_3er_var", ">=", solution.total_3er - config.move1_protection_delta_3er),
        ("total_2er_var", ">=", solution.total_2er - config.move1_protection_delta_2er),
    ]


# =============================================================================
# MOVE 2: SINGLETON EATER
# =============================================================================

def should_trigger_move2(solution: Phase1Solution, config: DomainLNSConfig) -> tuple:
    """Check if Move 2 should trigger."""
    avoidable = sum(solution.singles_with_extension_possible_by_day.values())
    
    threshold_abs = config.move2_avoidable_threshold_abs
    threshold_pct = config.move2_avoidable_threshold_pct * solution.total_singles
    
    if avoidable <= threshold_abs and avoidable <= threshold_pct:
        return False, []
    
    target_tours = _select_target_singletons(solution, config)
    return True, target_tours


def _select_target_singletons(solution: Phase1Solution, config: DomainLNSConfig) -> list:
    """Select target singleton tours for Move 2."""
    targets = []
    
    extensible_singletons = []
    for block in solution.selected_blocks:
        if len(block.tours) != 1:
            continue
        day = block.day.value if hasattr(block.day, 'value') else str(block.day)
        if solution.singles_with_extension_possible_by_day.get(day, 0) > 0:
            extensible_singletons.append(block)
    
    def day_priority(block):
        day = block.day.value if hasattr(block.day, 'value') else str(block.day)
        return -solution.tours_by_day.get(day, 0)
    
    extensible_singletons.sort(key=day_priority)
    
    for block in extensible_singletons[:config.move2_target_singles_max]:
        targets.append(block.tours[0].id)
    
    return targets


def compute_move2_neighborhood(
    solution: Phase1Solution, all_blocks: list, target_tour_ids: list, adjacency: dict
) -> tuple:
    """Compute fixed and unfixed block sets for Move 2."""
    unfixed_ids = set()
    
    tour_to_blocks = defaultdict(set)
    for block in all_blocks:
        for tour in block.tours:
            tour_to_blocks[tour.id].add(block.id)
    
    for tour_id in target_tour_ids:
        unfixed_ids.update(tour_to_blocks.get(tour_id, set()))
    
    expanded = set()
    for block_id in unfixed_ids:
        expanded.update(adjacency.get(block_id, set()))
    unfixed_ids.update(expanded)
    
    all_ids = {b.id for b in all_blocks}
    fixed_ids = all_ids - unfixed_ids
    
    return fixed_ids, unfixed_ids


# =============================================================================
# MOVE 3/4/5: STUBS
# =============================================================================

def should_trigger_move3(solution: Phase1Solution, config: DomainLNSConfig) -> tuple:
    """Stub for Move 3 (future implementation)."""
    return False, None


def should_trigger_move4(solution: Phase1Solution, config: DomainLNSConfig) -> tuple:
    """Stub for Move 4 (future implementation)."""
    return False, None


def should_trigger_move5(solution: Phase1Solution, config: DomainLNSConfig) -> tuple:
    """Stub for Move 5 (future implementation)."""
    return False, None


# =============================================================================
# MAIN LNS LOOP
# =============================================================================

def run_domain_lns(
    initial_solution: Phase1Solution,
    all_blocks: list,
    tours: list,
    config: DomainLNSConfig,
    solve_fn: Callable,
    log_fn: Callable[[str], None] = None,
) -> DomainLNSResult:
    """
    Main domain LNS loop for Phase 1 improvement.
    
    Args:
        initial_solution: Starting Phase 1 solution
        all_blocks: All candidate blocks
        tours: All tours
        config: LNS configuration
        solve_fn: Callback (fixed_blocks, hints, temp_constraints, time_limit) -> (status, selected_blocks)
        log_fn: Logging callback
    
    Returns:
        DomainLNSResult with improved solution and telemetry
    """
    def log(msg: str):
        if log_fn:
            log_fn(msg)
        logger.info(msg)
    
    result = DomainLNSResult(best_solution=initial_solution)
    
    if not config.enabled:
        log("Domain LNS: DISABLED")
        result.lns_status = "DISABLED"
        return result
    
    log(f"Domain LNS: Starting with {initial_solution.to_log_dict()}")
    
    start_time = perf_counter()
    deadline = start_time + config.global_time_limit
    
    best_so_far = initial_solution
    initial_3er = initial_solution.total_3er
    initial_2er = initial_solution.total_2er
    initial_singles = initial_solution.total_singles
    
    iterations_without_improvement = 0
    total_iterations = 0
    
    adjacency = build_block_adjacency(all_blocks)
    
    while True:
        elapsed = perf_counter() - start_time
        if elapsed >= config.global_time_limit:
            log(f"Domain LNS: Global time limit reached ({elapsed:.1f}s)")
            result.lns_status = "TIME_LIMIT"
            break
        
        if iterations_without_improvement >= config.stagnation_limit:
            log(f"Domain LNS: Stagnation limit reached ({iterations_without_improvement} iterations)")
            result.lns_status = "STAGNATION"
            break
        
        remaining = deadline - perf_counter()
        if remaining < 2.0:
            log(f"Domain LNS: Insufficient time remaining ({remaining:.1f}s)")
            result.lns_status = "TIME_LIMIT"
            break
        
        # ==== MOVE 1: Peak-Day Lane Rebuild ====
        for _ in range(config.move1_attempts_per_loop):
            if perf_counter() >= deadline - 2.0:
                break
            
            trigger, target_day, score = should_trigger_move1(best_so_far, config)
            if not trigger:
                log(f"Move 1: SKIP (score={score:.1f}, day={target_day})")
                break
            
            result.move1_attempts += 1
            move_result = _execute_move1(
                best_so_far, all_blocks, tours, target_day, score,
                config, solve_fn, adjacency, log
            )
            total_iterations += 1
            
            if move_result.accepted:
                best_so_far = compute_phase1_telemetry(move_result.new_blocks, all_blocks)
                iterations_without_improvement = 0
                result.move1_accepted += 1
                result.lns_moves_accepted += 1
            else:
                iterations_without_improvement += 1
                result.lns_moves_rejected += 1
        
        # ==== MOVE 2: Singleton Eater ====
        for _ in range(config.move2_attempts_per_loop):
            if perf_counter() >= deadline - 2.0:
                break
            
            trigger, target_tours = should_trigger_move2(best_so_far, config)
            if not trigger:
                log(f"Move 2: SKIP (no extensible singletons)")
                break
            
            result.move2_attempts += 1
            move_result = _execute_move2(
                best_so_far, all_blocks, tours, target_tours,
                config, solve_fn, adjacency, log
            )
            total_iterations += 1
            
            if move_result.accepted:
                best_so_far = compute_phase1_telemetry(move_result.new_blocks, all_blocks)
                iterations_without_improvement = 0
                result.move2_accepted += 1
                result.lns_moves_accepted += 1
            else:
                iterations_without_improvement += 1
                result.lns_moves_rejected += 1
        
        if iterations_without_improvement >= config.stagnation_limit:
            break
    
    result.best_solution = best_so_far
    result.lns_iterations = total_iterations
    result.lns_time_s = perf_counter() - start_time
    
    result.delta_3er_total = best_so_far.total_3er - initial_3er
    result.delta_2er_total = best_so_far.total_2er - initial_2er
    result.delta_singles_total = best_so_far.total_singles - initial_singles
    
    if result.lns_moves_accepted > 0 and result.lns_status not in ("TIME_LIMIT", "STAGNATION"):
        result.lns_status = "IMPROVED"
    elif result.lns_status not in ("TIME_LIMIT", "STAGNATION", "DISABLED"):
        result.lns_status = "NO_IMPROVEMENT"
    
    log(f"Domain LNS: Completed {total_iterations} iterations, {result.lns_moves_accepted} accepted")
    log(f"Domain LNS: Final {best_so_far.to_log_dict()}")
    log(f"Domain LNS: lns_status={result.lns_status}, delta_3er={result.delta_3er_total:+d}")
    
    return result


# =============================================================================
# MOVE EXECUTION
# =============================================================================

def _execute_move1(
    solution: Phase1Solution,
    all_blocks: list,
    tours: list,
    target_day: str,
    score: float,
    config: DomainLNSConfig,
    solve_fn: Callable,
    adjacency: dict,
    log: Callable,
) -> MoveResult:
    """Execute Move 1: Peak-Day Lane Rebuild."""
    
    result = MoveResult(move_id="move1", target_day=target_day)
    
    fixed_ids, unfixed_ids = compute_move1_neighborhood(solution, all_blocks, target_day)
    result.unfixed_block_count = len(unfixed_ids)
    
    log(f"Move 1: target_day={target_day}, score={score:.1f}, unfixed={len(unfixed_ids)}")
    
    fixed_values = {bid: solution.use_block_values.get(bid, 0) for bid in fixed_ids}
    hints = dict(solution.use_block_values)
    temp_constraints = get_move1_protection_constraints(solution, config)
    
    move_start = perf_counter()
    try:
        status, new_blocks = solve_fn(fixed_values, hints, temp_constraints, config.move1_time_budget)
        result.solve_time_s = perf_counter() - move_start
        result.solve_status = status
    except Exception as e:
        log(f"Move 1: FAILED with exception: {e}")
        result.solve_status = "EXCEPTION"
        result.reason = f"exception:{e}"
        return result
    
    if status not in ("OPTIMAL", "FEASIBLE"):
        log(f"Move 1: FAILED (status={status})")
        result.reason = f"solve_failed:{status}"
        return result
    
    candidate = compute_phase1_telemetry(new_blocks, all_blocks)
    
    result.delta_3er = candidate.total_3er - solution.total_3er
    result.delta_2er = candidate.total_2er - solution.total_2er
    result.delta_singles = candidate.total_singles - solution.total_singles
    result.delta_tours = candidate.total_tours - solution.total_tours
    
    accepted, reason = is_lexicographically_better(candidate, solution)
    result.accepted = accepted
    result.reason = reason
    
    if accepted:
        result.new_blocks = new_blocks
    
    log(f"Move 1: delta_3er={result.delta_3er:+d}, delta_2er={result.delta_2er:+d}, "
        f"delta_singles={result.delta_singles:+d}, accepted={accepted} ({reason})")
    
    return result


def _execute_move2(
    solution: Phase1Solution,
    all_blocks: list,
    tours: list,
    target_tours: list,
    config: DomainLNSConfig,
    solve_fn: Callable,
    adjacency: dict,
    log: Callable,
) -> MoveResult:
    """Execute Move 2: Singleton Eater."""
    
    result = MoveResult(move_id="move2")
    
    fixed_ids, unfixed_ids = compute_move2_neighborhood(solution, all_blocks, target_tours, adjacency)
    result.unfixed_block_count = len(unfixed_ids)
    
    log(f"Move 2: target_singletons={len(target_tours)}, unfixed={len(unfixed_ids)}")
    
    fixed_values = {bid: solution.use_block_values.get(bid, 0) for bid in fixed_ids}
    hints = dict(solution.use_block_values)
    temp_constraints = []  # Optional push constraint skipped
    
    move_start = perf_counter()
    try:
        status, new_blocks = solve_fn(fixed_values, hints, temp_constraints, config.move2_time_budget)
        result.solve_time_s = perf_counter() - move_start
        result.solve_status = status
    except Exception as e:
        log(f"Move 2: FAILED with exception: {e}")
        result.solve_status = "EXCEPTION"
        result.reason = f"exception:{e}"
        return result
    
    if status not in ("OPTIMAL", "FEASIBLE"):
        log(f"Move 2: FAILED (status={status})")
        result.reason = f"solve_failed:{status}"
        return result
    
    candidate = compute_phase1_telemetry(new_blocks, all_blocks)
    
    result.delta_3er = candidate.total_3er - solution.total_3er
    result.delta_2er = candidate.total_2er - solution.total_2er
    result.delta_singles = candidate.total_singles - solution.total_singles
    result.delta_tours = candidate.total_tours - solution.total_tours
    
    accepted, reason = is_lexicographically_better(candidate, solution)
    result.accepted = accepted
    result.reason = reason
    
    if accepted:
        result.new_blocks = new_blocks
    
    log(f"Move 2: delta_3er={result.delta_3er:+d}, delta_2er={result.delta_2er:+d}, "
        f"delta_singles={result.delta_singles:+d}, accepted={accepted} ({reason})")
    
    return result
