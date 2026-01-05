"""
SOLVEREIGN V3 - Seed Sweep Optimizer
=====================================

Runs solver with multiple seeds and ranks results to find optimal configuration.

Ranking Criteria (lexicographic):
1. Total Drivers (minimize)
2. PT Ratio (minimize)
3. 3er Block Count (maximize)
4. 1er Block Count (minimize)

Usage:
    from v3.seed_sweep import run_seed_sweep, auto_seed_sweep

    # Manual sweep with specific seeds
    results = run_seed_sweep(tour_instances, seeds=[94, 42, 123, 456])
    best = results[0]
    print(f"Best seed: {best['seed']} with {best['total_drivers']} drivers")

    # Auto sweep - finds best seed automatically
    auto_result = auto_seed_sweep(tour_instances, num_seeds=15)
    print(f"Best: Seed {auto_result['best_seed']} -> {auto_result['best_drivers']} drivers")
"""

import sys
import time as time_module
from pathlib import Path
from datetime import time
from typing import Optional, Callable, List, Dict, Any
from collections import defaultdict
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# CONSTANTS
# =============================================================================

# Default seeds - mix of primes and proven good seeds
DEFAULT_SEEDS = [94, 42, 17, 23, 31, 47, 53, 67, 71, 89, 97, 101, 127, 131, 137]

# Extended seeds for thorough search
EXTENDED_SEEDS = DEFAULT_SEEDS + [
    1, 2, 3, 5, 7, 11, 13, 19, 29, 37, 41, 43, 59, 61, 73, 79, 83,
    103, 107, 109, 113, 139, 149, 151, 157, 163, 167, 173, 179, 181
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SeedSweepResult:
    """Result of a single seed run."""
    seed: int
    total_drivers: int
    fte_drivers: int
    pt_drivers: int
    pt_ratio: float
    block_1er: int
    block_2er_reg: int
    block_2er_split: int
    block_3er: int
    total_hours: float
    avg_hours: float
    max_hours: float
    min_hours: float
    success: bool
    error: Optional[str] = None
    rank: int = 0
    execution_time_ms: int = 0


@dataclass
class AutoSweepResult:
    """Result of auto seed sweep."""
    best_seed: int
    best_drivers: int
    best_result: SeedSweepResult
    all_results: List[SeedSweepResult]
    comparison_table: str
    top_3: List[SeedSweepResult]
    execution_time_ms: int
    seeds_tested: int
    seeds_successful: int
    recommendation: str


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def run_seed_sweep(
    tour_instances: list[dict],
    seeds: list[int] = None,
    progress_callback: Optional[Callable[[int, int, dict], None]] = None,
    parallel: bool = False,
    max_workers: int = 4
) -> list[dict]:
    """
    Run solver with multiple seeds and rank results.

    Args:
        tour_instances: List of tour instance dicts for solving
        seeds: List of seeds to try (default: 15 common seeds)
        progress_callback: Optional callback(current, total, result) for progress updates
        parallel: Whether to run seeds in parallel (faster but uses more CPU)
        max_workers: Max parallel workers (only used if parallel=True)

    Returns:
        List of result dicts sorted by quality (best first)
    """
    from v3.solver_v2_integration import solve_with_v2_solver

    if seeds is None:
        seeds = DEFAULT_SEEDS

    results = []

    if parallel and len(seeds) > 1:
        # Parallel execution
        results = _run_parallel_sweep(tour_instances, seeds, max_workers, progress_callback)
    else:
        # Sequential execution
        for i, seed in enumerate(seeds):
            start_time = time_module.time()
            try:
                # Run solver
                assignments = solve_with_v2_solver(tour_instances, seed=seed)

                # Compute metrics
                metrics = compute_assignment_metrics(assignments, tour_instances)
                metrics["seed"] = seed
                metrics["success"] = True
                metrics["error"] = None
                metrics["execution_time_ms"] = int((time_module.time() - start_time) * 1000)

                results.append(metrics)

                if progress_callback:
                    progress_callback(i + 1, len(seeds), metrics)

            except Exception as e:
                error_result = {
                    "seed": seed,
                    "success": False,
                    "error": str(e),
                    "total_drivers": 9999,  # Worst possible
                    "pt_ratio": 100.0,
                    "block_3er": 0,
                    "block_1er": 9999,
                    "execution_time_ms": int((time_module.time() - start_time) * 1000),
                }
                results.append(error_result)

                if progress_callback:
                    progress_callback(i + 1, len(seeds), error_result)

    # Sort by quality (best first)
    results.sort(key=lambda r: (
        r.get("total_drivers", 9999),      # Minimize drivers
        r.get("pt_ratio", 100),            # Minimize PT ratio
        -r.get("block_3er", 0),            # Maximize 3er blocks
        r.get("block_1er", 9999),          # Minimize 1er blocks
    ))

    # Add rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def _run_parallel_sweep(
    tour_instances: list[dict],
    seeds: list[int],
    max_workers: int,
    progress_callback: Optional[Callable] = None
) -> list[dict]:
    """Run seed sweep in parallel using ThreadPoolExecutor."""
    from v3.solver_v2_integration import solve_with_v2_solver

    results = []
    completed = 0

    def solve_seed(seed: int) -> dict:
        start_time = time_module.time()
        try:
            assignments = solve_with_v2_solver(tour_instances, seed=seed)
            metrics = compute_assignment_metrics(assignments, tour_instances)
            metrics["seed"] = seed
            metrics["success"] = True
            metrics["error"] = None
            metrics["execution_time_ms"] = int((time_module.time() - start_time) * 1000)
            return metrics
        except Exception as e:
            return {
                "seed": seed,
                "success": False,
                "error": str(e),
                "total_drivers": 9999,
                "pt_ratio": 100.0,
                "block_3er": 0,
                "block_1er": 9999,
                "execution_time_ms": int((time_module.time() - start_time) * 1000),
            }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(solve_seed, seed): seed for seed in seeds}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1

            if progress_callback:
                progress_callback(completed, len(seeds), result)

    return results


# =============================================================================
# AUTO SEED SWEEP
# =============================================================================

def auto_seed_sweep(
    tour_instances: list[dict],
    num_seeds: int = 15,
    use_extended: bool = False,
    parallel: bool = True,
    max_workers: int = 4,
    progress_callback: Optional[Callable[[int, int, dict], None]] = None
) -> AutoSweepResult:
    """
    Automatically find the best seed by running multiple seeds and comparing.

    Args:
        tour_instances: List of tour instance dicts
        num_seeds: Number of seeds to test (default: 15)
        use_extended: Use extended seed list for more thorough search
        parallel: Run seeds in parallel (faster)
        max_workers: Max parallel workers
        progress_callback: Optional progress callback

    Returns:
        AutoSweepResult with best seed and comparison data
    """
    start_time = time_module.time()

    # Select seeds
    seed_pool = EXTENDED_SEEDS if use_extended else DEFAULT_SEEDS
    seeds_to_test = seed_pool[:min(num_seeds, len(seed_pool))]

    # Add some random seeds if we need more
    if num_seeds > len(seeds_to_test):
        random_seeds = [random.randint(1, 1000) for _ in range(num_seeds - len(seeds_to_test))]
        seeds_to_test = list(set(seeds_to_test + random_seeds))[:num_seeds]

    # Run sweep
    results = run_seed_sweep(
        tour_instances,
        seeds=seeds_to_test,
        progress_callback=progress_callback,
        parallel=parallel,
        max_workers=max_workers
    )

    # Convert to SeedSweepResult objects
    sweep_results = []
    for r in results:
        sweep_results.append(SeedSweepResult(
            seed=r.get("seed", 0),
            total_drivers=r.get("total_drivers", 9999),
            fte_drivers=r.get("fte_drivers", 0),
            pt_drivers=r.get("pt_drivers", 0),
            pt_ratio=r.get("pt_ratio", 100.0),
            block_1er=r.get("block_1er", 0),
            block_2er_reg=r.get("block_2er_reg", 0),
            block_2er_split=r.get("block_2er_split", 0),
            block_3er=r.get("block_3er", 0),
            total_hours=r.get("total_hours", 0),
            avg_hours=r.get("avg_hours", 0),
            max_hours=r.get("max_hours", 0),
            min_hours=r.get("min_hours", 0),
            success=r.get("success", False),
            error=r.get("error"),
            rank=r.get("rank", 0),
            execution_time_ms=r.get("execution_time_ms", 0),
        ))

    # Get best result
    best = sweep_results[0] if sweep_results else None
    top_3 = sweep_results[:3]
    successful = [r for r in sweep_results if r.success]

    # Generate comparison table
    comparison_table = format_comparison_table(sweep_results[:10])

    # Generate recommendation
    if best and best.success:
        recommendation = _generate_recommendation(best, sweep_results)
    else:
        recommendation = "Keine erfolgreichen Seeds gefunden. Bitte Solver-Konfiguration pruefen."

    execution_time = int((time_module.time() - start_time) * 1000)

    return AutoSweepResult(
        best_seed=best.seed if best else 0,
        best_drivers=best.total_drivers if best else 9999,
        best_result=best,
        all_results=sweep_results,
        comparison_table=comparison_table,
        top_3=top_3,
        execution_time_ms=execution_time,
        seeds_tested=len(seeds_to_test),
        seeds_successful=len(successful),
        recommendation=recommendation,
    )


def _generate_recommendation(best: SeedSweepResult, all_results: List[SeedSweepResult]) -> str:
    """Generate a recommendation based on the sweep results."""
    successful = [r for r in all_results if r.success]

    if len(successful) < 2:
        return f"Seed {best.seed} ist der einzige erfolgreiche Seed."

    # Check variance in results
    driver_counts = [r.total_drivers for r in successful]
    min_drivers = min(driver_counts)
    max_drivers = max(driver_counts)
    variance = max_drivers - min_drivers

    if variance == 0:
        return f"Alle Seeds ergeben {min_drivers} Fahrer. Seed {best.seed} empfohlen."
    elif variance <= 2:
        return f"Geringe Varianz ({min_drivers}-{max_drivers} Fahrer). Seed {best.seed} mit {best.total_drivers} Fahrern empfohlen."
    elif variance <= 5:
        return f"Moderate Varianz ({min_drivers}-{max_drivers} Fahrer). Seed {best.seed} spart {max_drivers - best.total_drivers} Fahrer gegenueber schlechtestem."
    else:
        return f"Hohe Varianz ({min_drivers}-{max_drivers} Fahrer)! Seed {best.seed} ist {max_drivers - best.total_drivers} Fahrer besser als Worst-Case."


def format_comparison_table(results: List[SeedSweepResult]) -> str:
    """Format results as a comparison table."""
    if not results:
        return "Keine Ergebnisse"

    lines = [
        "+" + "-"*8 + "+" + "-"*10 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*10 + "+",
        "| Seed   | Fahrer   | FTE    | PT%    | 3er    | 1er    | Status   |",
        "+" + "-"*8 + "+" + "-"*10 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*10 + "+",
    ]

    for r in results:
        if r.success:
            status = "OK"
            lines.append(
                f"| {r.seed:<6} | {r.total_drivers:<8} | {r.fte_drivers:<6} | "
                f"{r.pt_ratio:<6.1f} | {r.block_3er:<6} | {r.block_1er:<6} | {status:<8} |"
            )
        else:
            lines.append(
                f"| {r.seed:<6} | {'ERROR':<8} | {'-':<6} | "
                f"{'-':<6} | {'-':<6} | {'-':<6} | {'FAIL':<8} |"
            )

    lines.append("+" + "-"*8 + "+" + "-"*10 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*10 + "+")

    return "\n".join(lines)


def compute_assignment_metrics(
    assignments: list[dict],
    tour_instances: list[dict]
) -> dict:
    """
    Compute quality metrics from assignments.

    Args:
        assignments: List of assignment dicts
        tour_instances: List of tour instance dicts

    Returns:
        Metrics dict
    """
    # Build instance lookup
    instance_lookup = {inst["id"]: inst for inst in tour_instances}

    # Group by driver
    driver_hours = defaultdict(float)
    driver_blocks = defaultdict(lambda: defaultdict(list))

    for a in assignments:
        driver_id = a["driver_id"]
        day = a["day"]
        inst = instance_lookup.get(a.get("tour_instance_id"))
        if inst:
            driver_hours[driver_id] += float(inst.get("work_hours", 0))
        driver_blocks[driver_id][day].append(a)

    # Count drivers and PT
    total_drivers = len(driver_hours)
    fte_drivers = sum(1 for h in driver_hours.values() if h >= 40)
    pt_drivers = total_drivers - fte_drivers
    pt_ratio = (100.0 * pt_drivers / total_drivers) if total_drivers > 0 else 0

    # Count block types
    block_1er = 0
    block_2er_reg = 0
    block_2er_split = 0
    block_3er = 0

    for driver_id, days in driver_blocks.items():
        for day, asgns in days.items():
            if len(asgns) == 1:
                block_1er += 1
            elif len(asgns) == 2:
                block_type = asgns[0].get("metadata", {}).get("block_type", "")
                if "split" in block_type.lower():
                    block_2er_split += 1
                else:
                    block_2er_reg += 1
            elif len(asgns) >= 3:
                block_3er += 1

    total_blocks = block_1er + block_2er_reg + block_2er_split + block_3er
    total_hours = sum(driver_hours.values())
    avg_hours = total_hours / total_drivers if total_drivers > 0 else 0

    return {
        "total_drivers": total_drivers,
        "fte_drivers": fte_drivers,
        "pt_drivers": pt_drivers,
        "pt_ratio": round(pt_ratio, 2),
        "total_hours": round(total_hours, 1),
        "avg_hours": round(avg_hours, 2),
        "total_assignments": len(assignments),
        "total_blocks": total_blocks,
        "block_1er": block_1er,
        "block_2er_reg": block_2er_reg,
        "block_2er_split": block_2er_split,
        "block_3er": block_3er,
    }


def format_leaderboard(results: list[dict]) -> str:
    """
    Format results as a text leaderboard.

    Args:
        results: Sorted list of sweep results

    Returns:
        Formatted leaderboard string
    """
    lines = [
        "=" * 80,
        "SEED SWEEP LEADERBOARD",
        "=" * 80,
        "",
        f"{'Rank':<6} {'Seed':<8} {'Drivers':<10} {'FTE':<6} {'PT%':<8} {'3er':<6} {'2er':<6} {'1er':<6} {'Status'}",
        "-" * 80
    ]

    for r in results[:20]:
        if r.get("success", True):
            lines.append(
                f"{r['rank']:<6} {r['seed']:<8} {r['total_drivers']:<10} "
                f"{r.get('fte_drivers', 0):<6} {r['pt_ratio']:<8.1f} "
                f"{r.get('block_3er', 0):<6} {r.get('block_2er_reg', 0) + r.get('block_2er_split', 0):<6} "
                f"{r.get('block_1er', 0):<6} OK"
            )
        else:
            lines.append(
                f"{r['rank']:<6} {r['seed']:<8} {'ERROR':<10} "
                f"{'':<6} {'':<8} "
                f"{'':<6} {'':<6} "
                f"{'':<6} {r.get('error', 'Unknown')[:20]}"
            )

    lines.extend([
        "-" * 80,
        f"Best seed: {results[0]['seed']} with {results[0]['total_drivers']} drivers"
    ])

    return "\n".join(lines)


# Test
if __name__ == "__main__":
    print("Seed Sweep Optimizer - Test Mode")
    print("=" * 50)

    # Create minimal test data
    test_instances = [
        {"id": 1, "day": 1, "start_ts": time(6, 0), "end_ts": time(10, 0), "work_hours": 4.0, "depot": "A", "skill": None, "duration_min": 240, "crosses_midnight": False},
        {"id": 2, "day": 1, "start_ts": time(10, 45), "end_ts": time(14, 45), "work_hours": 4.0, "depot": "A", "skill": None, "duration_min": 240, "crosses_midnight": False},
        {"id": 3, "day": 2, "start_ts": time(8, 0), "end_ts": time(16, 0), "work_hours": 8.0, "depot": "A", "skill": None, "duration_min": 480, "crosses_midnight": False},
    ]

    def progress(current, total, result):
        status = "OK" if result.get("success") else "FAIL"
        drivers = result.get("total_drivers", "?")
        print(f"  [{current}/{total}] Seed {result['seed']}: {drivers} drivers - {status}")

    print("\nRunning seed sweep with 5 seeds...")
    results = run_seed_sweep(test_instances, seeds=[94, 42, 17], progress_callback=progress)

    print("\n" + format_leaderboard(results))
    print("\nTest complete!")
