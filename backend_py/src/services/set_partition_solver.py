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

from src.services.roster_column import RosterColumn, BlockInfo
from src.services.roster_column_generator import (
    RosterColumnGenerator, create_block_infos_from_blocks
)
from src.services.set_partition_master import solve_rmp, solve_relaxed_rmp, analyze_uncovered

logger = logging.getLogger("SetPartitionSolver")

# >>> STEP8: SUPPORT_HELPERS (TOP-LEVEL)
def _compute_tour_support(columns, target_ids, coverage_attr):
    support = {tid: 0 for tid in target_ids}
    for col in columns:
        items = getattr(col, coverage_attr, col.block_ids)
        for tid in items:
            if tid in support:
                support[tid] += 1
    return support


def _simple_percentile(values, p):
    if not values:
        return 0
    vals = sorted(values)
    idx = int(len(vals) * p / 100.0)
    if idx < 0:
        idx = 0
    if idx >= len(vals):
        idx = len(vals) - 1
    return vals[idx]
# <<< STEP8: SUPPORT_HELPERS



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
    max_rounds: int = 500,  # OPTIMIZED: 100→500 for better convergence
    initial_pool_size: int = 10000,  # OPTIMIZED: 5000→10000 for more diverse columns
    columns_per_round: int = 300,  # OPTIMIZED: 200→300 for faster coverage
    rmp_time_limit: float = 45.0,  # QUALITY: 15→45s for better solutions
    seed: int = 42,
    log_fn=None,
    config=None,  # NEW: Pass config for LNS flags
    global_deadline: float = None,  # Monotonic deadline for budget enforcement
    context: Optional[object] = None, # Added run context
    features: Optional[dict] = None,  # Step 8: Instance features
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
    # QUALITY: Enable LNS by default (can be overridden via config)
    enable_lns = True if config is None else getattr(config, 'enable_lns_low_hour_consolidation', True)
    log_fn(f"LNS enabled: {enable_lns}")
    if enable_lns:
        lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
        lns_threshold = getattr(config, 'lns_low_hour_threshold_h', 30.0)
        lns_k = getattr(config, 'lns_receiver_k_values', (3, 5, 8, 12))
        log_fn(f"  LNS budget: {lns_budget:.1f}s")
        log_fn(f"  LNS threshold: {lns_threshold:.1f}h")
        log_fn(f"  LNS K-values: {lns_k}")
    log_fn("=" * 70)

    # Emit Phase Start
    if context and hasattr(context, "emit_progress"):
        context.emit_progress("phase_start", "Starting Set Partitioning", phase="phase2_assignments")

    
    # =========================================================================
    # STEP 1: Convert blocks to BlockInfo
    # =========================================================================
    log_fn("\nConverting blocks to BlockInfo...")
    block_infos = create_block_infos_from_blocks(blocks)
    all_block_ids = set(b.block_id for b in block_infos)
    
    # >>> STEP8: EXTRACT TOUR IDS
    all_tour_ids = set()
    for b in block_infos:
        all_tour_ids.update(b.tour_ids)
    log_fn(f"Unique tours: {len(all_tour_ids)}")
    # <<< STEP8: EXTRACT TOUR IDS
    
    total_work_hours = sum(b.work_min for b in block_infos) / 60.0
    log_fn(f"Total work hours: {total_work_hours:.1f}h")
    log_fn(f"Expected drivers (40-53h): {int(total_work_hours/53)} - {int(total_work_hours/40)}")
    # =========================================================================
    # STEP 2: Generate initial column pool using MULTI-STAGE generation
    # This produces better-packed rosters by first trying high-hour targets
    # =========================================================================
    generator = RosterColumnGenerator(
        block_infos=block_infos,
        seed=seed,
        pool_cap=50000,  # Allow large pool
        log_fn=log_fn,
    )
    
    gen_start = time.time()
    
    # OPTIMIZED: Use multi-stage generation for better FTE utilization
    multistage_stats = generator.generate_multistage_pool(
        stages=[
            ("high_quality_FTE", (47, 53), 4000),   # Pack 47-53h rosters first
            ("medium_FTE", (42, 47), 3000),         # Then 42-47h
            ("fill_gaps", (30, 42), 2000),          # Allow lower hours for remaining
        ]
    )
    
    # Also run standard generation for diversity
    generator.generate_initial_pool(target_size=initial_pool_size // 2)
    generation_time = time.time() - gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nMulti-stage FTE pool stats:")
    log_fn(f"  Pool size: {stats.get('size', 0)}")
    log_fn(f"  Uncovered blocks: {stats.get('uncovered_blocks', 0)}")
    log_fn(f"  Multi-stage: {multistage_stats['total_pool_size']} columns in {len(multistage_stats['stages'])} stages")

    
    # =========================================================================
    # STEP 2B: Generate PT columns for hard-to-cover blocks
    # =========================================================================
    pt_gen_start = time.time()
    pt_count = generator.generate_pt_pool(target_size=500)
    generation_time += time.time() - pt_gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nPool after PT generation:")
    log_fn(f"  Pool size: {stats.get('pool_total', 0)} ({pt_count} PT columns)")
    log_fn(f"  Uncovered blocks: {len(generator.get_uncovered_blocks())}")
    
    # =========================================================================
    # STEP 2C: Generate SINGLETON columns (Feasibility Net)
    # One column per block with HIGH COST → ensures RMP always finds a solution
    # =========================================================================
    singleton_start = time.time()
    singleton_count = generator.generate_singleton_columns(penalty_factor=100.0)
    generation_time += time.time() - singleton_start
    
    stats = generator.get_pool_stats()
    pool_size = stats.get('pool_total', 0)
    log_fn(f"\nPool after singleton fallback:")
    log_fn(f"  Pool size: {pool_size} (+{singleton_count} singleton)")
    log_fn(f"  Uncovered blocks: {len(generator.get_uncovered_blocks())}")
    
    if pool_size == 0:
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
        
        # Emit RMP Round Start
        if context and hasattr(context, "emit_progress"):
             context.emit_progress("rmp_solve", f"Round {round_num}: Solving RMP (Pool: {len(generator.pool)})", 
                                   phase="phase2_assignments", step=f"Round {round_num}",
                                   metrics={"pool_size": len(generator.pool), "round": round_num})

        
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
                
                def create_result(rosters, status_code):
                    return SetPartitionResult(
                        status=status_code,
                        selected_rosters=rosters,
                        num_drivers=len(rosters),
                        total_hours=sum(r.total_hours for r in rosters),
                        hours_min=min(r.total_hours for r in rosters) if rosters else 0,
                        hours_max=max(r.total_hours for r in rosters) if rosters else 0,
                        hours_avg=sum(r.total_hours for r in rosters) / len(rosters) if rosters else 0,
                        uncovered_blocks=[],
                        pool_size=len(generator.pool),
                        rounds_used=round_num,
                        total_time=time.time() - start_time,
                        rmp_time=rmp_total_time,
                        generation_time=generation_time,
                    )
                
                # =================================================================
                # CHECK QUALITY: If too many PT drivers, DO NOT STOP!
                # =================================================================
                num_pt = sum(1 for r in selected if r.total_hours < 40.0)
                pt_ratio = num_pt / len(selected) if selected else 0
                
                # Check Pool Quality (Coverage by FTE columns)
                # User Requirement: Early stop only if coverage_by_fte_columns >= 95%
                pool_quality = generator.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
                # User Requirement: Early stop only if coverage_by_fte_columns >= 95%
                pool_quality = generator.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
                log_fn(f"Pool Quality (FTE Coverage): {pool_quality:.1%} | PT Share: {pt_ratio:.1%} | Stale: {rounds_without_progress}")

                 # Emit RMP Metrics & Stall Check
                if context and hasattr(context, "emit_progress"):
                    context.emit_progress("rmp_round", f"Round {round_num} stats", 
                                          phase="phase2_assignments", step=f"Round {round_num}",
                                          metrics={
                                             "drivers_total": len(selected),
                                             "drivers_fte": sum(1 for r in selected if r.total_hours >= 40),
                                             "drivers_pt": num_pt,
                                             "pool_size": len(generator.pool),
                                             "uncovered": 0,
                                             "pool_quality_pct": round(pool_quality * 100, 1)
                                          })
                    # Check for stall/improvement
                    if hasattr(context, "check_improvement"):
                        status_check = context.check_improvement(round_num, len(selected), 0) # 0 uncovered
                        if status_check == "stall_abort":
                             log_fn("Context signalled STALL ABORT")
                             rounds_without_progress = 999 

                
                # Condition for stopping:
                # 1. Excellent Quality: Very low PT share AND Good Pool Quality
                # 2. Stagnation: No progress for many rounds AND Good Pool Quality (don't give up if pool is bad)
                quality_ok = pool_quality >= 0.95
                pt_ok = num_pt <= len(selected) * 0.02
                stalling = rounds_without_progress > 20  # Increased from 15
                
                if (pt_ok and quality_ok) or (stalling and quality_ok):
                     log_fn(f"\n[OK] Stopping with {num_pt} PT drivers ({pt_ratio:.1%} share) and {pool_quality:.1%} FTE coverage")
                     return create_result(selected, "OK")
                
                log_fn(f"\n[CONT] Full coverage but {num_pt} PT drivers ({pt_ratio:.1%} share) - Optimization continuing...")
                log_fn(f"      Targeting blocks covered by PT drivers for better consolidation")
                
                # Identify blocks covered by PTs to target them for repair
                pt_blocks = []
                for r in selected:
                     if r.total_hours < 40.0:
                         pt_blocks.extend(r.block_ids)
                
                # Override under_blocks for the generation phase
                # We skip solve_relaxed_rmp since we are feasible
                under_blocks = pt_blocks
                over_blocks = []
                
                # Jump to generation
                goto_generation = True
            else:
                 log_fn(f"RMP feasible but {len(rmp_result['uncovered_blocks'])} blocks uncovered")
                 best_result = rmp_result
                 goto_generation = False
        else:
             goto_generation = False
        
        # =====================================================================
        # RMP INFEASIBLE or has uncovered -> use RELAXED RMP for diagnosis
        # =====================================================================
        # Initialize variables to avoid UnboundLocalError
        under_count = 0
        over_count = 0
        under_blocks = []
        over_blocks = []
        
        if not goto_generation:
            relaxed = solve_relaxed_rmp(
                columns=columns,
                all_block_ids=all_block_ids,
                # time_limit=10.0, # Removed strict limit
                time_limit=effective_rmp_limit, # Use remaining budget
                log_fn=log_fn,
            )
            
            # FIX: Gate progress tracking on solver status
            relaxed_status = relaxed.get("status", "UNKNOWN")
            log_fn(f"Relaxed RMP Status: {relaxed_status}")
            
            # Initialize variables for all paths
            under_blocks = relaxed.get("under_blocks", [])
            over_blocks = relaxed.get("over_blocks", [])
            
            # Progress tracking logic...
            under_count = relaxed.get("under_count", 0)
            over_count = relaxed.get("over_count", 0)
        # >>> STEP8: BRIDGING_LOOP
        # Check if compressed week
        _is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4
        if _is_compressed and round_num <= 6:
            # SWITCH TO TOUR-BASED COVERAGE
            log_fn(f"[POOL REPAIR R{round_num}] Coverage Mode: TOUR (Target: {len(all_tour_ids)})")
            
            tour_support = _compute_tour_support(columns, all_tour_ids, "covered_tour_ids")
            support_vals = list(tour_support.values())
            
            low_support_tours = [tid for tid, cnt in tour_support.items() if cnt <= 2]
            
            pct_low = (len(low_support_tours) / max(1, len(all_tour_ids))) * 100.0
            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)
            
            # ALSO LOG BLOCK STATS (for comparison)
            block_support = _compute_tour_support(columns, all_block_ids, "block_ids")
            bs_vals = list(block_support.values())
            bs_low = len([b for b, c in block_support.items() if c <= 2])
            bs_pct = (bs_low / max(1, len(all_block_ids))) * 100.0
            bs_min = min(bs_vals) if bs_vals else 0
            bs_p10 = _simple_percentile(bs_vals, 10)
            bs_p50 = _simple_percentile(bs_vals, 50)
            
            log_fn(f"  % tours support<=2: {len(low_support_tours)}/{len(all_tour_ids)} ({pct_low:.1f}%)")
            log_fn(f"  tour support min/p10/p50: {support_min}/{support_p10}/{support_p50}")
            
            log_fn(f"  % blocks support<=2: {bs_low}/{len(all_block_ids)} ({bs_pct:.1f}%)")
            log_fn(f"  block support min/p10/p50: {bs_min}/{bs_p10}/{bs_p50}")
            
            # Bridging Logic (robust)
            added = 0
            built = 0
            
            if low_support_tours and hasattr(generator, 'generate_anchor_pack_variants'):
                # Sort for determinism
                anchors = sorted(low_support_tours, key=lambda t: (tour_support[t], t))[:150]
                
                res = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)

                # Case A: generator returns int
                if isinstance(res, int):
                    added = res
                    built = res # approximate
                # Case B: list
                else:
                    cols = list(res) if res else []
                    built = len(cols)
                    for col in cols:
                        if col.roster_id not in generator.pool:
                            generator.pool[col.roster_id] = col
                            added += 1
                
                dedup_dropped = max(0, built - added)
                log_fn(f"  Bridging: anchors={len(anchors)}, built={built}, added={added}, dedup_dropped={dedup_dropped}")
                log_fn(f"  First 3 anchors: {anchors[:3] if anchors else 'None'}")
        # <<< STEP8: BRIDGING_LOOP

            
            # Emit RMP Metrics (Infeasible/Relaxed)
            if context and hasattr(context, "emit_progress"):
                context.emit_progress("rmp_round", f"Round {round_num} (Relaxed)", 
                                        phase="phase2_assignments", step=f"Round {round_num}",
                                        metrics={
                                            "drivers_total": 0, # Unknown
                                            "uncovered": len(under_blocks),
                                            "pool_size": len(generator.pool),
                                            "round": round_num
                                        })

        else:
            # Force generation by bypassing "Perfect relaxation" check
            under_count = 999 
            log_fn(f"Skipping Relaxed RMP validation to force generation for {len(pt_blocks)} blocks.")
            relaxed_status = "OPTIMAL" # Fake status to pass checks if needed
            rounds_without_progress = 0 # Reset progression as we are actively optimizing quality
            relaxed = {} # Initialize empty to avoid UnboundLocalError
            
            # Logic to maintain structure
            if relaxed_status in ("OPTIMAL", "FEASIBLE"):
                rounds_without_progress = 0
            else:
                rounds_without_progress += 1

        
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
    seeded_count = generator.seed_from_greedy(greedy_assignments)

    # >>> STEP8: INCUMBENT_NEIGHBORHOOD_CALL
    incumbent_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
    if incumbent_cols:
        log_fn(f"[INCUMBENT NEIGHBORHOOD] {len(incumbent_cols)} INC_GREEDY_ columns detected")
        added = generator.generate_incumbent_neighborhood(
            active_days=getattr(features, "active_days", ["Mon", "Tue", "Wed", "Fri"]) if features else ["Mon", "Tue", "Wed", "Fri"],
            max_variants=500,
        )
        log_fn(f"  Added {added} incumbent variants")
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD_CALL

    log_fn(f"Seeded {seeded_count} columns from greedy solution")
    
    # FAILURE RECOVERY: Collect the greedy columns to pass as HINTS
    # This guarantees RMP starts with a feasible solution
    greedy_hint_columns = []
    pool_values = list(generator.pool.values())
    
    for assignment in greedy_assignments:
        # Reconstruct block IDs for matching
        block_ids = frozenset(b.id if hasattr(b, 'id') else b.block_id for b in assignment.blocks)
        
        # Find matching column in pool (it should exist now)
        matching_col = None
        for col in pool_values:
            if frozenset(col.block_ids) == block_ids:
                matching_col = col
                break
        
        if matching_col:
            greedy_hint_columns.append(matching_col)
    
    log_fn(f"Prepared {len(greedy_hint_columns)} hint columns for RMP warm-start")

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
    
    # Retry RMP with seeded pool AND hints
    log_fn("\n" + "=" * 60)
    log_fn("RETRYING RMP WITH GREEDY-SEEDED POOL + HINTS")
    log_fn("=" * 60)
    
    columns = list(generator.pool.values())
    
    rmp_retry_start = time.time()
    final_rmp_result = solve_rmp(
        columns=columns,
        all_block_ids=all_block_ids,
        time_limit=rmp_time_limit,
        log_fn=log_fn,
        hint_columns=greedy_hint_columns,  # CRITICAL FIX: Pass hints!
    )

    rmp_total_time += time.time() - rmp_retry_start
    
    if final_rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
        if not final_rmp_result["uncovered_blocks"]:
            rmp_drivers = final_rmp_result['num_drivers']
            greedy_drivers = len(greedy_assignments)
            
            log_fn(f"\n[COMPARISON] RMP: {rmp_drivers} drivers vs Greedy: {greedy_drivers} drivers")
            
            # =====================================================================
            # BEST-OF-TWO: Use whichever solution has fewer drivers
            # This is critical because RMP may hit time limits and return suboptimal
            # =====================================================================
            if greedy_drivers < rmp_drivers:
                log_fn(f"[DECISION] Using GREEDY solution (fewer drivers)")
                log_fn(f"  Greedy: {greedy_drivers} drivers")
                log_fn(f"  RMP: {rmp_drivers} drivers (rejected)")
                
                # Convert greedy assignments to SetPartitionResult format
                from src.services.roster_column import create_roster_from_blocks, BlockInfo
                
                greedy_rosters = []
                for assignment in greedy_assignments:
                    # Find existing column that matches, or create placeholder
                    block_ids = frozenset(b.id if hasattr(b, 'id') else b.block_id for b in assignment.blocks)
                    matching_col = None
                    for col in generator.pool.values():
                        if frozenset(col.block_ids) == block_ids:
                            matching_col = col
                            break
                    
                    if matching_col:
                        greedy_rosters.append(matching_col)
                    else:
                        # Create a minimal placeholder roster column
                        for col in generator.pool.values():
                            if any(bid in col.block_ids for bid in block_ids):
                                # Best effort - should not happen if seeding worked
                                greedy_rosters.append(col)
                                break
                
                # Use the seeded columns that match greedy assignments
                # This is a safe fallback that ensures we return valid columns
                selected = final_rmp_result["selected_rosters"]  # Keep RMP as fallback
                if len(greedy_rosters) >= greedy_drivers * 0.9:
                    selected = greedy_rosters
                
                hours = [r.total_hours for r in selected] if selected else [0]
                
                return SetPartitionResult(
                    status="OK_GREEDY_BETTER",
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


# =============================================================================
# SWAP CONSOLIDATION POST-PROCESSING
# =============================================================================

def swap_consolidation(
    assignments: list,
    blocks_lookup: dict = None,
    max_iterations: int = 100,
    min_hours_target: float = 42.0,
    max_hours_target: float = 53.0,
    log_fn=None,
) -> tuple:
    """
    Post-processing: consolidate underutilized drivers through block swaps.
    
    Algorithm:
    1. Identify low-hour drivers (<45h)
    2. Identify high-hour drivers (>48h)
    3. Try swapping blocks between them to:
       a) Eliminate low-hour drivers entirely (give their blocks away)
       b) Balance hours more evenly
    4. Remove drivers with no blocks
    
    Args:
        assignments: List of DriverAssignment objects
        blocks_lookup: Dict mapping block_id -> Block object (for constraint checking)
        max_iterations: Maximum swap iterations
        min_hours_target: Soft minimum hours for FTE drivers
        max_hours_target: Maximum hours constraint
        log_fn: Logging function
    
    Returns:
        (optimized_assignments, stats_dict)
    """
    from src.services.constraints import can_assign_block
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("SWAP CONSOLIDATION POST-PROCESSING")
    log_fn("=" * 60)
    
    stats = {
        "initial_drivers": len(assignments),
        "initial_fte": sum(1 for a in assignments if a.driver_type == "FTE"),
        "initial_pt": sum(1 for a in assignments if a.driver_type == "PT"),
        "moves_attempted": 0,
        "moves_successful": 0,
        "drivers_eliminated": 0,
    }
    
    if not assignments:
        stats["final_drivers"] = 0
        return assignments, stats
    
    # Build mutable state
    driver_blocks = {a.driver_id: list(a.blocks) for a in assignments}
    driver_types = {a.driver_id: a.driver_type for a in assignments}
    
    def compute_hours(blocks):
        return sum(b.total_work_hours for b in blocks)
    
    def get_days(blocks):
        return {b.day.value if hasattr(b.day, 'value') else str(b.day) for b in blocks}
    
    def can_receive_block(receiver_blocks, new_block, current_hours):
        """Check if receiver can accept the block."""
        new_hours = current_hours + new_block.total_work_hours
        if new_hours > max_hours_target:
            return False
        
        # Check day overlap
        receiver_days = get_days(receiver_blocks)
        block_day = new_block.day.value if hasattr(new_block.day, 'value') else str(new_block.day)
        
        # Check time overlap on same day
        for rb in receiver_blocks:
            rb_day = rb.day.value if hasattr(rb.day, 'value') else str(rb.day)
            if rb_day == block_day:
                # Check time overlap
                if not (new_block.last_end <= rb.first_start or new_block.first_start >= rb.last_end):
                    return False
        
        return True
    
    iterations = 0
    progress = True
    
    while progress and iterations < max_iterations:
        progress = False
        iterations += 1
        
        # Get current driver hours
        driver_hours = {did: compute_hours(blocks) for did, blocks in driver_blocks.items()}
        
        # Find candidates for elimination: Low-hour FTEs AND all PT drivers
        low_hour_drivers = [
            did for did, hours in driver_hours.items()
            if driver_blocks[did] and (
                (driver_types.get(did) == "FTE" and hours < min_hours_target) or
                (driver_types.get(did) == "PT")
            )
        ]
        
        # Find high-hour FTE drivers (can potentially give blocks away)
        high_hour_drivers = [
            did for did, hours in driver_hours.items()
            if hours > 48.0 and driver_types.get(did) == "FTE" and driver_blocks[did]
        ]
        
        # Sort low-hour by hours ascending (eliminate smallest first)
        low_hour_drivers.sort(key=lambda d: driver_hours[d])
        
        for low_did in low_hour_drivers[:10]:  # Limit per iteration
            low_blocks = driver_blocks.get(low_did, [])
            if not low_blocks:
                continue
            
            # Try to give all blocks to other drivers
            blocks_to_move = list(low_blocks)
            all_moved = True
            
            for block in blocks_to_move:
                stats["moves_attempted"] += 1
                
                # Find best receiver (has room and can accept)
                best_receiver = None
                best_score = float('inf')
                
                # Consider all other FTE drivers as receivers
                for other_did in driver_blocks:
                    if other_did == low_did:
                        continue
                    if driver_types.get(other_did) != "FTE":
                        continue
                    
                    other_blocks = driver_blocks[other_did]
                    other_hours = driver_hours.get(other_did, 0)
                    
                    if can_receive_block(other_blocks, block, other_hours):
                        # Score: prefer receivers that need hours
                        new_hours = other_hours + block.total_work_hours
                        distance_to_target = abs(new_hours - 49.5)  # Prefer ~49.5h
                        
                        if distance_to_target < best_score:
                            best_score = distance_to_target
                            best_receiver = other_did
                
                if best_receiver:
                    # Move the block
                    driver_blocks[low_did].remove(block)
                    driver_blocks[best_receiver].append(block)
                    driver_hours[best_receiver] = compute_hours(driver_blocks[best_receiver])
                    stats["moves_successful"] += 1
                    progress = True
                else:
                    all_moved = False
            
            # Check if driver is now empty
            if not driver_blocks.get(low_did):
                stats["drivers_eliminated"] += 1
                log_fn(f"  Eliminated driver {low_did}")
    
    # Remove empty drivers
    final_assignments = []
    from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
    
    fte_count = 0
    pt_count = 0
    
    for did in sorted(driver_blocks.keys()):
        blocks = driver_blocks[did]
        if not blocks:
            continue
        
        dtype = driver_types[did]
        total_hours = compute_hours(blocks)
        days_worked = len(get_days(blocks))
        
        # Renumber drivers
        if dtype == "PT":
            pt_count += 1
            new_id = f"PT{pt_count:03d}"
        else:
            fte_count += 1
            new_id = f"FTE{fte_count:03d}"
        
        # Sort blocks
        blocks.sort(key=lambda b: (
            b.day.value if hasattr(b.day, 'value') else str(b.day),
            b.first_start
        ))
        
        final_assignments.append(DriverAssignment(
            driver_id=new_id,
            driver_type=dtype,
            blocks=blocks,
            total_hours=total_hours,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks),
        ))
    
    stats["final_drivers"] = len(final_assignments)
    stats["final_fte"] = sum(1 for a in final_assignments if a.driver_type == "FTE")
    stats["final_pt"] = sum(1 for a in final_assignments if a.driver_type == "PT")
    stats["iterations"] = iterations
    
    log_fn(f"Swap consolidation: {stats['initial_drivers']} -> {stats['final_drivers']} drivers")
    log_fn(f"  Moves: {stats['moves_successful']}/{stats['moves_attempted']} successful")
    log_fn(f"  Eliminated: {stats['drivers_eliminated']} drivers")
    log_fn("=" * 60)
    
    return final_assignments, stats
