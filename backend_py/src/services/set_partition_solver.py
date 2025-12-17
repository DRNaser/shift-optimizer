"""
Set-Partition Solver - Main Solve Loop

Orchestrates the full Set-Partitioning / Crew Scheduling pipeline:

1. Build blocks from tours (reuse Phase 1)
2. Generate initial column pool
3. Loop:
   a. Solve RMP
   b. If FEASIBLE with full coverage → DONE
   c. If uncovered: generate new columns targeting uncovered blocks
   d. If no new columns generated → FAIL
4. Convert selected rosters to DriverAssignments
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

from src.services.roster_column import RosterColumn, BlockInfo
from src.services.roster_column_generator import (
    RosterColumnGenerator, create_block_infos_from_blocks
)
from src.services.set_partition_master import solve_rmp, solve_relaxed_rmp, analyze_uncovered

logger = logging.getLogger("SetPartitionSolver")


@dataclass
class SetPartitionResult:
    """Result of Set-Partitioning solve."""
    status: str  # "OK" | "INFEASIBLE" | "FAILED_COVERAGE" | "FAILED_MAX_ROUNDS"
    selected_rosters: list[RosterColumn]
    num_drivers: int
    total_hours: float
    hours_min: float
    hours_max: float
    hours_avg: float
    uncovered_blocks: list[str]
    pool_size: int
    rounds_used: int
    total_time: float
    rmp_time: float
    generation_time: float


def solve_set_partitioning(
    blocks: list,
    max_rounds: int = 100,
    initial_pool_size: int = 5000,
    columns_per_round: int = 200,
    rmp_time_limit: float = 60.0,
    seed: int = 42,
    log_fn=None,
) -> SetPartitionResult:
    """
    Solve the crew scheduling problem using Set-Partitioning.
    
    Args:
        blocks: List of Block objects (from Phase 1)
        max_rounds: Maximum generation/solve rounds
        initial_pool_size: Target size for initial column pool
        columns_per_round: Columns to generate per round
        rmp_time_limit: RMP solver time limit per solve
        seed: Random seed for determinism
        log_fn: Logging function
    
    Returns:
        SetPartitionResult with selected rosters and stats
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    start_time = time.time()
    
    log_fn("=" * 70)
    log_fn("SET-PARTITIONING SOLVER")
    log_fn("=" * 70)
    log_fn(f"Blocks: {len(blocks)}")
    log_fn(f"Max rounds: {max_rounds}")
    log_fn(f"Initial pool target: {initial_pool_size}")
    
    # =========================================================================
    # STEP 1: Convert blocks to BlockInfo
    # =========================================================================
    log_fn("\nConverting blocks to BlockInfo...")
    block_infos = create_block_infos_from_blocks(blocks)
    all_block_ids = set(b.block_id for b in block_infos)
    
    total_work_hours = sum(b.work_min for b in block_infos) / 60.0
    log_fn(f"Total work hours: {total_work_hours:.1f}h")
    log_fn(f"Expected drivers (40-53h): {int(total_work_hours/53)} - {int(total_work_hours/40)}")
    
    # =========================================================================
    # STEP 2: Generate initial column pool
    # =========================================================================
    generator = RosterColumnGenerator(
        block_infos=block_infos,
        seed=seed,
        pool_cap=50000,  # Allow large pool
        log_fn=log_fn,
    )
    
    gen_start = time.time()
    generator.generate_initial_pool(target_size=initial_pool_size)
    generation_time = time.time() - gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nInitial FTE pool stats:")
    log_fn(f"  Pool size: {stats.get('size', 0)}")
    log_fn(f"  Uncovered blocks: {stats.get('uncovered_blocks', 0)}")
    
    # =========================================================================
    # STEP 2B: Generate PT columns for hard-to-cover blocks
    # =========================================================================
    pt_gen_start = time.time()
    pt_count = generator.generate_pt_pool(target_size=500)
    generation_time += time.time() - pt_gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nPool after PT generation:")
    log_fn(f"  Pool size: {stats.get('size', 0)} ({pt_count} PT columns)")
    log_fn(f"  Uncovered blocks: {stats.get('uncovered_blocks', 0)}")
    
    if stats.get('size', 0) == 0:
        log_fn("ERROR: Could not generate any valid columns!")
        return SetPartitionResult(
            status="FAILED_NO_COLUMNS",
            selected_rosters=[],
            num_drivers=0,
            total_hours=0,
            hours_min=0,
            hours_max=0,
            hours_avg=0,
            uncovered_blocks=list(all_block_ids),
            pool_size=0,
            rounds_used=0,
            total_time=time.time() - start_time,
            rmp_time=0,
            generation_time=generation_time,
        )
    
    # =========================================================================
    # STEP 3: MAIN LOOP - RMP + Column Generation
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("MAIN SOLVE LOOP")
    log_fn("=" * 60)
    
    rmp_total_time = 0
    best_result = None
    
    # Progress tracking for adaptive stopping
    best_under_count = len(all_block_ids)  # Start with worst case
    best_over_count = len(all_block_ids)
    rounds_without_progress = 0
    max_stale_rounds = 5  # Stop after N rounds w/o improvement
    
    # Adaptive coverage quota
    min_coverage_quota = 5  # Each block should be in at least 5 columns
    
    for round_num in range(1, max_rounds + 1):
        log_fn(f"\n--- Round {round_num}/{max_rounds} ---")
        log_fn(f"Pool size: {len(generator.pool)}")
        
        # Solve STRICT RMP first
        columns = list(generator.pool.values())
        
        rmp_start = time.time()
        rmp_result = solve_rmp(
            columns=columns,
            all_block_ids=all_block_ids,
            time_limit=rmp_time_limit,
            log_fn=log_fn,
        )
        rmp_total_time += time.time() - rmp_start
        
        # Check result
        if rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
            if not rmp_result["uncovered_blocks"]:
                log_fn(f"\n✓✓✓ FULL COVERAGE ACHIEVED with {rmp_result['num_drivers']} drivers ✓✓✓")
                
                selected = rmp_result["selected_rosters"]
                hours = [r.total_hours for r in selected]
                
                return SetPartitionResult(
                    status="OK",
                    selected_rosters=selected,
                    num_drivers=len(selected),
                    total_hours=sum(hours),
                    hours_min=min(hours) if hours else 0,
                    hours_max=max(hours) if hours else 0,
                    hours_avg=sum(hours) / len(hours) if hours else 0,
                    uncovered_blocks=[],
                    pool_size=len(generator.pool),
                    rounds_used=round_num,
                    total_time=time.time() - start_time,
                    rmp_time=rmp_total_time,
                    generation_time=generation_time,
                )
            else:
                log_fn(f"RMP feasible but {len(rmp_result['uncovered_blocks'])} blocks uncovered")
                best_result = rmp_result
        
        # =====================================================================
        # RMP INFEASIBLE or has uncovered -> use RELAXED RMP for diagnosis
        # =====================================================================
        relaxed = solve_relaxed_rmp(
            columns=columns,
            all_block_ids=all_block_ids,
            time_limit=min(rmp_time_limit, 30.0),
            log_fn=log_fn,
        )
        
        under_count = relaxed.get("under_count", 0)
        over_count = relaxed.get("over_count", 0)
        under_blocks = relaxed.get("under_blocks", [])
        over_blocks = relaxed.get("over_blocks", [])
        
        log_fn(f"Relaxed diagnosis: under={under_count}, over={over_count}")
        log_fn(f"Best so far: under={best_under_count}, over={best_over_count}")
        
        # Track progress
        improved = False
        if under_count < best_under_count:
            best_under_count = under_count
            improved = True
        if over_count < best_over_count:
            best_over_count = over_count
            improved = True
        
        if improved:
            rounds_without_progress = 0
            log_fn(f"Progress! New best: under={best_under_count}, over={best_over_count}")
        else:
            rounds_without_progress += 1
            log_fn(f"No progress for {rounds_without_progress} rounds")
        
        # Check stopping condition
        if rounds_without_progress >= max_stale_rounds:
            log_fn(f"\nNo improvement for {max_stale_rounds} rounds - stopping")
            break
        
        # Perfect relaxation = exact partition exists!
        if under_count == 0 and over_count == 0:
            log_fn("Relaxed RMP shows exact partition possible! Re-checking strict RMP...")
            # The strict RMP should work now; if not, something's wrong
            continue
        
        # =====================================================================
        # TARGETED COLUMN GENERATION
        # =====================================================================
        before_pool = len(generator.pool)
        gen_start = time.time()
        
        # Build avoid_set from high-frequency + over_blocks
        coverage_freq = relaxed.get("coverage_freq", {})
        high_freq_threshold = 50  # Blocks in many columns cause collisions
        high_freq_blocks = {
            bid for bid, freq in coverage_freq.items() 
            if freq > high_freq_threshold
        }
        avoid_set = set(over_blocks) | high_freq_blocks
        
        # Get rare blocks that need more coverage  
        rare_blocks = generator.get_rare_blocks(min_coverage=min_coverage_quota)
        
        # Priority seeds: under_blocks first, then rare_blocks
        target_seeds = under_blocks + [b for b in rare_blocks if b not in under_blocks]
        
        log_fn(f"Target seeds: {len(target_seeds)} (under: {len(under_blocks)}, rare: {len(rare_blocks)})")
        log_fn(f"Avoid set: {len(avoid_set)} blocks")
        
        # Targeted generation
        new_cols = generator.targeted_repair(
            target_blocks=target_seeds[:columns_per_round],
            avoid_set=avoid_set,
            max_attempts=columns_per_round * 2,
        )
        generation_time += time.time() - gen_start
        
        log_fn(f"Generated {len(new_cols)} new columns (pool: {before_pool} → {len(generator.pool)})")
        
        # Fallback: try swap builder if no new columns
        if len(generator.pool) == before_pool:
            log_fn("No new columns from targeted repair, trying swap builder...")
            gen_start = time.time()
            swaps = generator.swap_builder(max_attempts=columns_per_round)
            generation_time += time.time() - gen_start
            log_fn(f"Swap builder generated {len(swaps)} columns")
        
        # Increase coverage quota if we're stagnating
        if rounds_without_progress >= 2:
            min_coverage_quota = min(min_coverage_quota + 2, 20)
            log_fn(f"Increased min coverage quota to {min_coverage_quota}")
    

    # =========================================================================
    # GREEDY-SEEDING FALLBACK
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("SET-PARTITIONING STALLED - TRYING GREEDY-SEEDING")
    log_fn("=" * 60)
    
    final_uncovered = generator.get_uncovered_blocks()
    log_fn(f"Uncovered blocks: {len(final_uncovered)}")
    
    # Run greedy to get a known-feasible solution
    from src.services.forecast_solver_v4 import assign_drivers_greedy, ConfigV4
    
    # Get original blocks from block_infos
    original_blocks = blocks  # blocks passed to function
    
    greedy_config = ConfigV4(seed=seed)
    log_fn("Running greedy assignment for seeding...")
    
    greedy_assignments, greedy_stats = assign_drivers_greedy(original_blocks, greedy_config)
    log_fn(f"Greedy result: {len(greedy_assignments)} drivers")
    
    # Seed the pool with greedy columns
    seeded = generator.seed_from_greedy(greedy_assignments)
    log_fn(f"Seeded {seeded} columns from greedy solution")
    
    # Retry RMP with seeded pool
    log_fn("\n" + "=" * 60)
    log_fn("RETRYING RMP WITH GREEDY-SEEDED POOL")
    log_fn("=" * 60)
    
    columns = list(generator.pool.values())
    
    rmp_start = time.time()
    final_rmp_result = solve_rmp(
        columns=columns,
        all_block_ids=all_block_ids,
        time_limit=rmp_time_limit * 2,  # Give more time for final attempt
        log_fn=log_fn,
    )
    rmp_total_time += time.time() - rmp_start
    
    # Check final result
    if final_rmp_result["status"] in ("OPTIMAL", "FEASIBLE") and not final_rmp_result["uncovered_blocks"]:
        log_fn("\n✓✓✓ GREEDY-SEEDED RMP SUCCESS ✓✓✓")
        
        selected = final_rmp_result["selected_rosters"]
        hours = [r.total_hours for r in selected]
        
        return SetPartitionResult(
            status="OK_GREEDY_SEEDED",
            selected_rosters=selected,
            num_drivers=len(selected),
            total_hours=sum(hours),
            hours_min=min(hours) if hours else 0,
            hours_max=max(hours) if hours else 0,
            hours_avg=sum(hours) / len(hours) if hours else 0,
            uncovered_blocks=[],
            pool_size=len(generator.pool),
            rounds_used=round_num,
            total_time=time.time() - start_time,
            rmp_time=rmp_total_time,
            generation_time=generation_time,
        )
    
    # If still failed, return INFEASIBLE with greedy info
    log_fn("\n" + "=" * 60)
    log_fn("SET-PARTITIONING FAILED (even with greedy-seeding)")
    log_fn("=" * 60)
    
    final_status = "FAILED_COVERAGE" if len(final_uncovered) > 0 else "INFEASIBLE"
    if final_status == "INFEASIBLE":
        log_fn("All blocks are coverable, but no exact partition was found")
    
    return SetPartitionResult(
        status=final_status,
        selected_rosters=best_result["selected_rosters"] if best_result else [],
        num_drivers=best_result["num_drivers"] if best_result else 0,
        total_hours=sum(r.total_hours for r in best_result["selected_rosters"]) if best_result else 0,
        hours_min=min(r.total_hours for r in best_result["selected_rosters"]) if best_result and best_result["selected_rosters"] else 0,
        hours_max=max(r.total_hours for r in best_result["selected_rosters"]) if best_result and best_result["selected_rosters"] else 0,
        hours_avg=0,
        uncovered_blocks=final_uncovered,
        pool_size=len(generator.pool),
        rounds_used=round_num,
        total_time=time.time() - start_time,
        rmp_time=rmp_total_time,
        generation_time=generation_time,
    )


def convert_rosters_to_assignments(
    selected_rosters: list[RosterColumn],
    block_lookup: dict,
) -> list:
    """
    Convert selected RosterColumns to DriverAssignment objects.
    
    Args:
        selected_rosters: List of selected RosterColumn
        block_lookup: Dict of block_id -> Block object
    
    Returns:
        List of DriverAssignment objects
    """
    from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
    
    assignments = []
    
    # Sort rosters by hours descending for deterministic ordering
    sorted_rosters = sorted(selected_rosters, key=lambda r: -r.total_hours)
    fte_count = 0
    pt_count = 0
    
    for roster in sorted_rosters:
        # Determine driver type from roster
        driver_type = getattr(roster, 'roster_type', 'FTE')
        
        if driver_type == "PT":
            pt_count += 1
            driver_id = f"PT{pt_count:03d}"
        else:
            fte_count += 1
            driver_id = f"FTE{fte_count:03d}"
        
        # Get Block objects
        blocks = []
        for block_id in roster.block_ids:
            if block_id in block_lookup:
                blocks.append(block_lookup[block_id])
        
        # Sort blocks by (day, start)
        blocks = sorted(blocks, key=lambda b: (
            b.day.value if hasattr(b.day, 'value') else str(b.day),
            b.first_start
        ))
        
        total_hours = roster.total_hours
        days_worked = len(set(b.day.value if hasattr(b.day, 'value') else str(b.day) for b in blocks))
        
        assignments.append(DriverAssignment(
            driver_id=driver_id,
            driver_type=driver_type,
            blocks=blocks,
            total_hours=total_hours,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks),
        ))
    
    return assignments
