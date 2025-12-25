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
from time import monotonic
from dataclasses import dataclass
from typing import Optional

from src.services.roster_column import RosterColumn, BlockInfo, create_roster_from_blocks_pt
from src.services.roster_column import can_add_block_to_roster
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
    rmp_time_limit: float = 15.0,
    seed: int = 42,
    log_fn=None,
    config=None,  # NEW: Pass config for LNS flags
    global_deadline: float = None,  # Monotonic deadline for budget enforcement
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
        config: Optional ConfigV4 for LNS settings
    
    Returns:
        SetPartitionResult with selected rosters and stats
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    start_time = time.time()
    
    log_fn("=" * 70)
    log_fn("SET-PARTITIONING SOLVER - Starting")
    log_fn("=" * 70)
    log_fn(f"Blocks: {len(blocks)}")
    log_fn(f"Max rounds: {max_rounds}")
    log_fn(f"Initial pool target: {initial_pool_size}")
    
    # MANDATORY: Log LNS status immediately for diagnostic visibility
    enable_lns = config and getattr(config, 'enable_lns_low_hour_consolidation', False)
    log_fn(f"LNS enabled: {enable_lns}")
    if enable_lns:
        lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
        lns_threshold = getattr(config, 'lns_low_hour_threshold_h', 30.0)
        lns_k = getattr(config, 'lns_receiver_k_values', (3, 5, 8, 12))
        log_fn(f"  LNS budget: {lns_budget:.1f}s")
        log_fn(f"  LNS threshold: {lns_threshold:.1f}h")
        log_fn(f"  LNS K-values: {lns_k}")
    log_fn("=" * 70)
    
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
    # STEP 2B: FTE-ONLY RMP (PT-first gate)
    # =========================================================================
    log_fn("\nFTE-FIRST: Attempting RMP with FTE-only columns...")
    fte_columns = [c for c in generator.pool.values() if getattr(c, "roster_type", "FTE") != "PT"]
    fte_rmp_result = solve_rmp(
        columns=fte_columns,
        all_block_ids=all_block_ids,
        time_limit=min(10.0, rmp_time_limit),
        log_fn=log_fn,
    )
    if fte_rmp_result["status"] in ("OPTIMAL", "FEASIBLE") and not fte_rmp_result["uncovered_blocks"]:
        log_fn(f"[FTE-FIRST] Full coverage achieved with {fte_rmp_result['num_drivers']} FTE drivers.")
        selected = fte_rmp_result["selected_rosters"]
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
            rounds_used=0,
            total_time=time.time() - start_time,
            rmp_time=0,
            generation_time=generation_time,
        )

    log_fn("[FTE-FIRST] Infeasible or uncovered with FTE-only pool; diagnosing gaps...")
    relaxed_fte = solve_relaxed_rmp(
        columns=fte_columns,
        all_block_ids=all_block_ids,
        time_limit=10.0,
        log_fn=log_fn,
    )
    under_blocks = relaxed_fte.get("under_blocks", [])
    log_fn(f"[FTE-FIRST] Undercovered blocks: {len(under_blocks)}")

    # =========================================================================
    # STEP 2C: Inject PT only for uncovered blocks (incremental)
    # =========================================================================
    pt_gen_start = time.time()
    pt_added = 0
    for block_id in under_blocks[:columns_per_round]:
        col = generator.build_pt_column(block_id, max_blocks=3)
        if col and generator.add_column(col):
            pt_added += 1
    generation_time += time.time() - pt_gen_start
    log_fn(f"\nPT incremental pool: added {pt_added} PT columns for uncovered blocks")

    if pt_added < 50:
        # Bin-pack PT rosters before broad PT generation
        max_pt_hours = getattr(config, "pt_max_week_hours", 30.0) if config else 30.0
        max_pt_minutes = int(max_pt_hours * 60)
        pt_seed_reason = ""
        seed_ids = []
        if under_blocks:
            pt_seed_reason = "under_blocks"
            seed_ids = under_blocks
        else:
            coverage_freq = relaxed_fte.get("coverage_freq", {})
            rare_ids = [bid for bid, freq in coverage_freq.items() if freq <= 2]
            if rare_ids:
                pt_seed_reason = "rare_blocks"
                seed_ids = rare_ids
            else:
                pt_seed_reason = "none"
        seed_blocks = [b for b in block_infos if b.block_id in set(seed_ids)]
        seed_blocks.sort(key=lambda b: (-b.work_min, b.block_id))
        pt_bins: list[list[BlockInfo]] = []
        seed_blocks = seed_blocks[:100]
        for block in seed_blocks:
            placed = False
            for bin_blocks in pt_bins:
                cur_minutes = sum(b.work_min for b in bin_blocks)
                if cur_minutes + block.work_min > max_pt_minutes:
                    continue
                can_add, _ = can_add_block_to_roster(bin_blocks, block, cur_minutes)
                if can_add:
                    bin_blocks.append(block)
                    placed = True
                    break
            if not placed:
                pt_bins.append([block])
            if len(pt_bins) >= 200:
                break
        pt_bin_added = 0
        for bin_blocks in pt_bins:
            column = create_roster_from_blocks_pt(
                roster_id=generator._get_next_roster_id(),
                block_infos=bin_blocks,
            )
            if column and generator.add_column(column):
                pt_bin_added += 1
        log_fn(
            f"PT bin-pack: reason={pt_seed_reason}, seed_size={len(seed_blocks)}, "
            f"sample={seed_ids[:5]}"
        )
        log_fn(f"PT bin-pack: added {pt_bin_added} packed PT columns")

        pt_gen_start = time.time()
        pt_count = generator.generate_pt_pool(target_size=500)
        generation_time += time.time() - pt_gen_start
        log_fn(f"PT broad pool: added {pt_count} PT columns")
    else:
        pt_count = pt_added

    stats = generator.get_pool_stats()
    log_fn(f"\nPool after PT generation:")
    log_fn(f"  Pool size: {stats.get('size', 0)} ({pt_count} PT columns)")
    log_fn(f"  Uncovered blocks: {stats.get('uncovered_blocks', 0)}")

    # =========================================================================
    # STEP 2D: Generate SINGLETON columns (Feasibility Net)
    # One column per block with HIGH COST → ensures RMP always finds a solution
    # =========================================================================
    singleton_start = time.time()
    singleton_count = generator.generate_singleton_columns(penalty_factor=100.0)
    generation_time += time.time() - singleton_start

    stats = generator.get_pool_stats()
    log_fn(f"\nPool after singleton fallback:")
    log_fn(f"  Pool size: {stats.get('size', 0)} (+{singleton_count} singleton)")
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
    max_stale_rounds = 10  # Stop after N rounds w/o improvement
    
    # Adaptive coverage quota
    min_coverage_quota = 5  # Each block should be in at least 5 columns
    
    for round_num in range(1, max_rounds + 1):
        # GLOBAL DEADLINE CHECK
        if global_deadline:
            remaining = global_deadline - monotonic()
            if remaining <= 0:
                log_fn(f"GLOBAL DEADLINE EXCEEDED at round {round_num} - returning best effort")
                break
        
        log_fn(f"\n--- Round {round_num}/{max_rounds} ---")
        log_fn(f"Pool size: {len(generator.pool)}")
        
        # Solve STRICT RMP first
        columns = list(generator.pool.values())
        
        # Cap RMP time limit to remaining budget (don't starve RMP)
        effective_rmp_limit = rmp_time_limit
        if global_deadline:
            remaining = global_deadline - monotonic()
            # Use min of configured limit and remaining time (but at least 1s)
            effective_rmp_limit = min(rmp_time_limit, max(1.0, remaining))
        
        rmp_start = time.time()
        rmp_result = solve_rmp(
            columns=columns,
            all_block_ids=all_block_ids,
            time_limit=effective_rmp_limit,
            log_fn=log_fn,
        )
        rmp_total_time += time.time() - rmp_start
        
        # Check result
        if rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
            if not rmp_result["uncovered_blocks"]:
                log_fn(f"\n[OK] FULL COVERAGE ACHIEVED with {rmp_result['num_drivers']} drivers")
                
                selected = rmp_result["selected_rosters"]
                hours = [r.total_hours for r in selected]
                
                # =========================================================================
                # NEW: LNS ENDGAME (if enabled)
                # =========================================================================
                if config and hasattr(config, 'enable_lns_low_hour_consolidation') and config.enable_lns_low_hour_consolidation:
                    lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS ENDGAME: Low-Hour Pattern Elimination")
                    log_fn(f"{'='*60}")
                    
                    lns_result = _lns_consolidate_low_hour(
                        current_selected=selected,
                        column_pool=generator.pool,  # FULL POOL!
                        all_block_ids=all_block_ids,
                        config=config,
                        time_budget_s=lns_budget,
                        log_fn=log_fn,
                    )
                    
                    if lns_result["status"] == "SUCCESS":
                        selected = lns_result["rosters"]
                        hours = [r.total_hours for r in selected]
                        
                        # LNS SUMMARY LOGGING
                        log_fn(f"\n{'='*60}")
                        log_fn(f"LNS SUMMARY:")
                        log_fn(f"  Status: {lns_result['status']}")
                        log_fn(f"  Patterns killed: {lns_result['stats']['kills_successful']} / {lns_result['stats']['attempts']} attempts")
                        log_fn(f"  Drivers: {lns_result['stats']['initial_drivers']} → {lns_result['stats']['final_drivers']}")
                        log_fn(f"  Low-hour patterns: {lns_result['stats']['initial_lowhour_count']} → {lns_result['stats']['final_lowhour_count']}")
                        log_fn(f"  Shortfall: {lns_result['stats']['initial_shortfall']:.1f}h → {lns_result['stats']['final_shortfall']:.1f}h")
                        log_fn(f"  Time: {lns_result['stats']['time_s']:.1f}s")
                        log_fn(f"{'='*60}")
                    else:
                        log_fn(f"\n{'='*60}")
                        log_fn(f"LNS SUMMARY:")
                        log_fn(f"  Status: {lns_result['status']} - using original solution")
                        log_fn(f"{'='*60}")
                
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
            time_limit=10.0,  # Strict diagnostic limit
            log_fn=log_fn,
        )
        
        # FIX: Gate progress tracking on solver status
        relaxed_status = relaxed.get("status", "UNKNOWN")
        log_fn(f"Relaxed RMP Status: {relaxed_status}")
        
        # Initialize variables for all paths
        under_count = relaxed.get("under_count", 0)
        over_count = relaxed.get("over_count", 0)
        under_blocks = relaxed.get("under_blocks", [])
        over_blocks = relaxed.get("over_blocks", [])
        
        if relaxed_status not in ("OPTIMAL", "FEASIBLE"):
            # UNKNOWN/INFEASIBLE: Check if we have an incumbent solution
            has_incumbent = best_result is not None
            
            if has_incumbent:
                # Incumbent exists - can use as best-effort but log differently
                log_fn(f"Status={relaxed_status} with incumbent available (best-effort)")
                # Don't update best_under_count/best_over_count, but don't count as stagnation
            else:
                # No incumbent yet - treat as no progress
                log_fn(f"UNKNOWN/INFEASIBLE status, no incumbent - skipping progress update")
                rounds_without_progress += 1
                log_fn(f"No progress for {rounds_without_progress} rounds")
        else:
            # Valid OPTIMAL/FEASIBLE status: safe to track progress
            log_fn(f"Relaxed diagnosis: under={under_count}, over={over_count}")
            log_fn(f"Best so far: under={best_under_count}, over={best_over_count}")
            
            # Track progress only on valid status
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
        
        log_fn(f"Generated {len(new_cols)} new columns (pool: {before_pool} -> {len(generator.pool)})")
        
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
    
    # =========================================================================
    # P1: SEEDING SANITY CHECK
    # Verify that seeded columns actually cover all blocks
    # =========================================================================
    seeded_coverage = set()
    for col in generator.pool.values():
        seeded_coverage.update(col.block_ids)
    
    under_blocks = all_block_ids - seeded_coverage
    if under_blocks:
        log_fn(f"WARNING: Seeding gap! {len(under_blocks)} blocks uncovered after seeding")
        log_fn(f"  Missing block IDs: {list(under_blocks)[:10]}...")
        # Trigger targeted repair for missing blocks
        repair_cols = generator.targeted_repair(list(under_blocks), max_attempts=len(under_blocks) * 2)
        log_fn(f"  Targeted repair added {len(repair_cols)} columns")
    else:
        log_fn("Seeding sanity check: OK (all blocks covered)")
    
    # NOTE: RMP retry disabled - goes straight to greedy fallback in caller
    # (The 120s RMP retry rarely succeeds and wastes time)
    
    # Retry RMP with seeded pool
    log_fn("\n" + "=" * 60)
    log_fn("RETRYING RMP WITH GREEDY-SEEDED POOL")
    log_fn("=" * 60)
    
    columns = list(generator.pool.values())
    
    rmp_retry_start = time.time()
    final_rmp_result = solve_rmp(
        columns=columns,
        all_block_ids=all_block_ids,
        time_limit=rmp_time_limit,
        log_fn=log_fn,
    )
    rmp_total_time += time.time() - rmp_retry_start
    
    if final_rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
        if not final_rmp_result["uncovered_blocks"]:
            log_fn(f"\n[OK] FULL COVERAGE ACHIEVED (after seeding) with {final_rmp_result['num_drivers']} drivers")
            
            selected = final_rmp_result["selected_rosters"]
            hours = [r.total_hours for r in selected]
            
            # =========================================================================
            # NEW: LNS ENDGAME (if enabled) - ALSO after greedy-seeding
            # =========================================================================
            if config and hasattr(config, 'enable_lns_low_hour_consolidation') and config.enable_lns_low_hour_consolidation:
                lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
                log_fn(f"\n{'='*60}")
                log_fn(f"LNS ENDGAME: Low-Hour Pattern Elimination")
                log_fn(f"{'='*60}")
                
                lns_result = _lns_consolidate_low_hour(
                    current_selected=selected,
                    column_pool=generator.pool,
                    all_block_ids=all_block_ids,
                    config=config,
                    time_budget_s=lns_budget,
                    log_fn=log_fn,
                )
                
                if lns_result["status"] == "SUCCESS":
                    selected = lns_result["rosters"]
                    hours = [r.total_hours for r in selected]
                    
                    # LNS SUMMARY LOGGING
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS SUMMARY:")
                    log_fn(f"  Status: {lns_result['status']}")
                    log_fn(f"  Patterns killed: {lns_result['stats']['kills_successful']} / {lns_result['stats']['attempts']} attempts")
                    log_fn(f"  Drivers: {lns_result['stats']['initial_drivers']} → {lns_result['stats']['final_drivers']}")
                    log_fn(f"  Low-hour patterns: {lns_result['stats']['initial_lowhour_count']} → {lns_result['stats']['final_lowhour_count']}")
                    log_fn(f"  Shortfall: {lns_result['stats']['initial_shortfall']:.1f}h → {lns_result['stats']['final_shortfall']:.1f}h")
                    log_fn(f"  Time: {lns_result['stats']['time_s']:.1f}s")
                    log_fn(f"{'='*60}")
                else:
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS SUMMARY:")
                    log_fn(f"  Status: {lns_result['status']} - using original solution")
                    log_fn(f"{'='*60}")
            
            return SetPartitionResult(
                status="OK_SEEDED",
                selected_rosters=selected,
                num_drivers=len(selected),
                total_hours=sum(hours),
                hours_min=min(hours) if hours else 0,
                hours_max=max(hours) if hours else 0,
                hours_avg=sum(hours) / len(hours) if hours else 0,
                uncovered_blocks=[],
                pool_size=len(generator.pool),
                rounds_used=max_rounds,
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


# =========================================================================
# LNS ENDGAME: LOW-HOUR PATTERN CONSOLIDATION
# =========================================================================

def _lns_consolidate_low_hour(
    current_selected: list[RosterColumn],
    column_pool: dict[str, RosterColumn],
    all_block_ids: set,
    config,
    time_budget_s: float,
    log_fn,
) -> dict:
    """
    LNS endgame: Eliminate low-hour patterns via column-kill fix-and-reopt.
    
    Uses FULL column_pool (all generated patterns) for candidate columns.
    
    Returns:
        {
            "status": "SUCCESS" | "NO_IMPROVEMENT",
            "rosters": list[RosterColumn],
            "stats": {
                "enabled": True,
                "kills_successful": int,
                "attempts": int,
                "initial_drivers": int,
                "final_drivers": int,
                "initial_lowhour_count": int,
                "final_lowhour_count": int,
                "initial_shortfall": float,
                "final_shortfall": float,
                "time_s": float,
            }
        }
    """
    t0 = time.time()
    threshold = getattr(config, 'lns_low_hour_threshold_h', 30.0)
    attempt_budget = 2.0
    max_attempts = min(30, int(time_budget_s / attempt_budget))
    
    def compute_shortfall(rosters):
        return sum(max(0, threshold - r.total_hours) for r in rosters)
    
    # CRITICAL FIX #3: Only kill FTE rosters, not PT (PT are intentionally <30h)
    low_hour = [
        r for r in current_selected 
        if r.total_hours < threshold and getattr(r, 'roster_type', 'FTE') == 'FTE'
    ]
    
    stats = {
        "enabled": True,
        "kills_successful": 0,
        "attempts": 0,
        "initial_drivers": len(current_selected),
        "final_drivers": len(current_selected),
        "initial_lowhour_count": len(low_hour),
        "final_lowhour_count": len(low_hour),
        "initial_shortfall": compute_shortfall(current_selected),
        "final_shortfall": compute_shortfall(current_selected),
        "time_s": 0.0,
    }
    
    if not low_hour:
        log_fn(f"LNS: No low-hour FTE patterns (<{threshold}h) found")
        return {"status": "NO_IMPROVEMENT", "rosters": current_selected, "stats": stats}
    
    log_fn(f"LNS: Found {len(low_hour)} low-hour FTE patterns (<{threshold}h)")
    log_fn(f"LNS: Budget={time_budget_s:.1f}s, max_attempts={max_attempts}")
    
    # Deterministic candidate sort
    candidates = sorted(low_hour, key=lambda r: (r.total_hours, r.roster_id))
    
    current = list(current_selected)
    kills = 0
    
    for attempt_num, p0 in enumerate(candidates):
        if stats["attempts"] >= max_attempts:
            break
        
        remaining = time_budget_s - (time.time() - t0)
        if remaining < 0.5:
            break
        
        # Try kill with escalating receiver sizes K=[3,5,8,12]
        for K in [3, 5, 8, 12]:
            result = _try_kill_pattern(
                p0=p0,
                current_selected=current,
                column_pool=column_pool,
                all_block_ids=all_block_ids,
                K_receivers=K,
                attempt_budget=min(attempt_budget, remaining),
                config=config,
                log_fn=log_fn,
            )
            
            stats["attempts"] += 1
            
            if result["status"] == "KILLED":
                current = result["rosters"]
                kills += 1
                log_fn(f"  LNS[{stats['attempts']}]: ✓ KILLED {p0.roster_id} ({p0.total_hours:.1f}h) with K={K}, drivers {len(current_selected)}→{len(current)}")
                break  # Success, next candidate
            elif result["status"] == "TIMEOUT":
                log_fn(f"  LNS[{stats['attempts']}]: TIMEOUT {p0.roster_id} K={K}")
                break  # Budget exhausted
            # INFEASIBLE: try larger K
            log_fn(f"  LNS[{stats['attempts']}]: INFEASIBLE {p0.roster_id} K={K} - {result.get('reason', 'unknown')}")
    
    # Final stats
    stats["kills_successful"] = kills
    stats["final_drivers"] = len(current)
    stats["final_lowhour_count"] = sum(1 for r in current if r.total_hours < threshold)
    stats["final_shortfall"] = compute_shortfall(current)
    stats["time_s"] = round(time.time() - t0, 2)
    
    status = "SUCCESS" if kills > 0 else "NO_IMPROVEMENT"
    return {"status": status, "rosters": current, "stats": stats}


def _try_kill_pattern(
    p0: RosterColumn,
    current_selected: list[RosterColumn],
    column_pool: dict[str, RosterColumn],
    all_block_ids: set,
    K_receivers: int,
    attempt_budget: float,
    config,
    log_fn,
) -> dict:
    """
    Try to eliminate pattern p0 via neighborhood destroy-repair.
    
    Returns: {"status": "KILLED" | "INFEASIBLE" | "TIMEOUT", "rosters": [...] | None, "reason": str}
    """
    from ortools.sat.python import cp_model
    
    # A) Deterministic Receiver Selection
    cand_R = [
        (r, 53.0 - r.total_hours, r.roster_id)
        for r in current_selected if r.roster_id != p0.roster_id
    ]
    cand_R.sort(key=lambda x: (-x[1], x[2]))  # free_capacity desc, id asc
    R = [r for r, _, _ in cand_R[:K_receivers]]
    
    # B) Define Neighborhood B
    B = set(p0.block_ids)
    for r in R:
        B.update(r.block_ids)
    
    # C) Filter Candidate Columns C from FULL POOL
    C = {
        rid: col for rid, col in column_pool.items()
        if col.block_ids.issubset(B) and col.is_valid and col.roster_id != p0.roster_id
    }
    
    # D) Coverage Check + B-Expansion with R-Update (CRITICAL FIX #1)
    covered = set()
    for col in C.values():
        covered.update(col.block_ids)
    
    uncov = B - covered
    if uncov:
        # B-EXPANSION: Add blocks determin istically
        expansion = set()
        for rid, col in column_pool.items():
            if any(b in col.block_ids for b in B):
                expansion.update(col.block_ids)
        
        expansion_sorted = sorted(expansion - B)[:200]
        
        # CRITICAL FIX #1: Update R with rosters covering expanded blocks
        # Find which current rosters cover the new expanded blocks
        expanded_blocks_to_add = set(expansion_sorted)
        roster_map = {r.roster_id: r for r in current_selected}
        
        for r in current_selected:
            if r == p0 or r in R:
                continue  # Already in neighborhood
            # Check if this roster covers any expanded block
            if r.block_ids & expanded_blocks_to_add:
                R.append(r)
                log_fn(f"      B-expansion: Added roster {r.roster_id} to R (covers expanded blocks)")
        
        # Now update B
        B.update(expanded_blocks_to_add)
        
        # Rebuild C
        C = {
            rid: col for rid, col in column_pool.items()
            if col.block_ids.issubset(B) and col.is_valid and col.roster_id != p0.roster_id
        }
        
        covered = set()
        for col in C.values():
            covered.update(col.block_ids)
        uncov = B - covered
        
        if uncov:
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"{len(uncov)} uncovered after expansion"}
    
    # CRITICAL FIX #2: Cardinality baseline = 1 + len(R) (after final R)
    baseline_rosters = 1 + len(R)  # p0 + R in current solution
    
    # Logging (FIX #3: Safety logging)
    log_fn(f"    Neighborhood: p0={p0.roster_id}({p0.total_hours:.1f}h), |R|={len(R)}, |B|={len(B)}, |C|={len(C)}")
    log_fn(f"    Baseline rosters in B: {baseline_rosters}, will try: {baseline_rosters-1}")
    
    # E) Build Reduced RMP
    model = cp_model.CpModel()
    x_vars = {}
    
    for rid, col in C.items():
        x_vars[rid] = model.NewBoolVar(f"x_{rid}")
    
    # Coverage for B
    for block_id in B:
        covering = [rid for rid, col in C.items() if block_id in col.block_ids]
        if not covering:
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"block {block_id} no coverage in C"}
        model.Add(sum(x_vars[rid] for rid in covering) == 1)
    
    # F) TRY-1: Aggressive kill (total <= baseline - 1)
    total_selected = sum(x_vars.values())
    model.Add(total_selected <= baseline_rosters - 1)
    
    # Objective: min shortfall
    shortfall_expr = sum(
        x_vars[rid] * max(0, int((30.0 - col.total_hours) * 100))
        for rid, col in C.items()
    )
    model.Minimize(shortfall_expr)
    
    # G) Solve TRY-1
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = attempt_budget
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.seed
    
    model.ClearHints()
    for r in current_selected:
        if r.roster_id in x_vars:
            hint_val = 1 if r in R else 0
            model.AddHint(x_vars[r.roster_id], hint_val)
    
    status_try1 = solver.Solve(model)
    log_fn(f"    TRY-1 (≤{baseline_rosters-1}): status={status_try1}")
    
    if status_try1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # TRY-2: Relax to <= baseline (no kill, just improve)
        model = cp_model.CpModel()
        x_vars = {}
        for rid in C.keys():
            x_vars[rid] = model.NewBoolVar(f"x_{rid}")
        
        for block_id in B:
            covering = [rid for rid, col in C.items() if block_id in col.block_ids]
            model.Add(sum(x_vars[rid] for rid in covering) == 1)
        
        model.Add(sum(x_vars.values()) <= baseline_rosters)  # FIX #2: Use baseline, not |R|+1
        model.Minimize(shortfall_expr)
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = attempt_budget
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = config.seed
        model.ClearHints()
        
        status_try2 = solver.Solve(model)
        log_fn(f"    TRY-2 (≤{baseline_rosters}): status={status_try2}")
        
        if status_try2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"TRY-1={status_try1}, TRY-2={status_try2}"}
    
    # H) Extract
    selected_in_B = [C[rid] for rid in x_vars.keys() if solver.Value(x_vars[rid]) == 1]
    
    # I) Rebuild full solution
    fixed_outside = [r for r in current_selected if r not in R and r != p0]
    new_rosters = fixed_outside + selected_in_B
    
    # J) Validate
    if p0 in new_rosters:
        return {"status": "INFEASIBLE", "rosters": None, "reason": "p0 still in solution"}
    
    if len(new_rosters) > len(current_selected):
        return {"status": "INFEASIBLE", "rosters": None, "reason": f"drivers increased {len(new_rosters)} > {len(current_selected)}"}
    
    covered_all = set()
    for r in new_rosters:
        covered_all.update(r.block_ids)
    if covered_all != all_block_ids:
        missing = all_block_ids - covered_all
        return {"status": "INFEASIBLE", "rosters": None, "reason": f"{len(missing)} blocks missing"}
    
    log_fn(f"    ✓ KILL SUCCESS: {len(current_selected)} → {len(new_rosters)} drivers")
    return {"status": "KILLED", "rosters": new_rosters, "reason": ""}


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
    
    assigned_block_ids = set()
    fte_count = 0
    pt_count = 0
    
    for roster in sorted_rosters:
        # Determine driver type from roster
        driver_type = getattr(roster, 'roster_type', 'FTE')
        
        # Get Block objects - checking for deduplication
        blocks = []
        for block_id in roster.block_ids:
            if block_id in block_lookup and block_id not in assigned_block_ids:
                blocks.append(block_lookup[block_id])
                assigned_block_ids.add(block_id)
        
        # If roster is empty after dedupe, skip it (can happen if fully subsumed)
        if not blocks:
            continue
            
        # Re-calculate hours based on actual assigned blocks
        total_hours = sum(b.total_work_hours for b in blocks)
        days_worked = len(set(b.day.value if hasattr(b.day, 'value') else str(b.day) for b in blocks))
        
        # Create ID
        if driver_type == "PT":
            pt_count += 1
            driver_id = f"PT{pt_count:03d}"
        else:
            fte_count += 1
            driver_id = f"FTE{fte_count:03d}"
        
        # Sort blocks by (day, start)
        blocks.sort(key=lambda b: (
            b.day.value if hasattr(b.day, 'value') else str(b.day),
            b.first_start
        ))
        
        assignments.append(DriverAssignment(
            driver_id=driver_id,
            driver_type=driver_type,
            blocks=blocks,
            total_hours=total_hours,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks),
        ))
    
    return assignments
