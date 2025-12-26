#!/usr/bin/env python
"""
DriverCap Feasibility Search Script
====================================
Finds the minimum number of drivers needed to cover all blocks
while respecting 40-50h target, 55h max, 11h rest, 5-day soft.

Usage:
    python scripts/drivercap_search.py --tours-file "forecast input.csv" --start 150
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.stage0_isolation import load_tours_from_csv
from src.services.smart_block_builder import build_weekly_blocks_smart
from src.services.assignment_solver import (
    solve_phase2_assignment,
    find_min_feasible_cap,
    AssignmentConfig,
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="DriverCap Feasibility Search")
    parser.add_argument("--tours-file", type=Path, required=True, 
                        help="Path to tours CSV file")
    parser.add_argument("--start", type=int, default=150,
                        help="Starting driver cap to test")
    parser.add_argument("--step", type=int, default=5,
                        help="Step size for search")
    parser.add_argument("--time-limit", type=float, default=120.0,
                        help="Time limit per solve attempt")
    parser.add_argument("--output", type=Path, 
                        default=Path("results/drivercap_search.json"),
                        help="Output JSON path")
    args = parser.parse_args()
    
    # Load tours
    logger.info(f"Loading tours from: {args.tours_file}")
    tours = load_tours_from_csv(args.tours_file)
    logger.info(f"Loaded {len(tours)} tours")
    
    total_hours = sum(t.duration_hours for t in tours)
    logger.info(f"Total hours: {total_hours:.1f}h")
    logger.info(f"Expected drivers (40-50h): {int(total_hours/50)}-{int(total_hours/40)}")
    
    # Build blocks (Phase 0+1 simulation)
    logger.info("\nBuilding blocks...")
    t0 = perf_counter()
    blocks, block_stats = build_weekly_blocks_smart(tours)
    logger.info(f"Generated {len(blocks)} blocks in {perf_counter()-t0:.1f}s")
    
    # For Phase2, we need selected blocks from Phase1
    # For testing, use a simple greedy selection: prefer multi-tour blocks
    logger.info("\nSimulating Phase1 block selection (greedy)...")
    selected_blocks = simulate_phase1_selection(blocks, tours)
    logger.info(f"Selected {len(selected_blocks)} blocks covering all {len(tours)} tours")
    
    # Run feasibility search
    config = AssignmentConfig(
        time_limit=args.time_limit,
        seed=42,
    )
    
    result = find_min_feasible_cap(
        selected_blocks,
        start_cap=args.start,
        step=args.step,
        config=config,
    )
    
    # Print results
    print("\n" + "=" * 70)
    print("FEASIBILITY SEARCH RESULT")
    print("=" * 70)
    print(f"Status: {result.status}")
    print(f"Feasible: {result.feasible}")
    print(f"Min Drivers: {result.drivers_used}")
    print(f"Hours: min={result.min_hours:.1f}h, max={result.max_hours:.1f}h, avg={result.avg_hours:.1f}h")
    print(f"Under 40h: {result.under40_count} drivers ({result.under40_sum_minutes/60:.1f}h shortfall)")
    print(f"Over 50h: {result.over50_count} drivers ({result.over50_sum_minutes/60:.1f}h excess)")
    print(f"6th day: {result.sixth_day_count} drivers")
    print(f"Solve time: {result.solve_time_s:.1f}s")
    print("=" * 70)
    
    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)
    logger.info(f"Results saved to: {args.output}")
    
    return 0


def simulate_phase1_selection(blocks, tours) -> list:
    """
    Simple greedy block selection for testing.
    Prefers 3er > 2er > 1er, avoids tour overlap.
    """
    # Sort: 3er first, then 2er, then 1er
    sorted_blocks = sorted(blocks, key=lambda b: -len(b.tours))
    
    selected = []
    covered_tours = set()
    
    for block in sorted_blocks:
        block_tour_ids = {t.id for t in block.tours}
        
        # Skip if any tour already covered
        if block_tour_ids & covered_tours:
            continue
        
        selected.append(block)
        covered_tours |= block_tour_ids
        
        # Stop if all tours covered
        if len(covered_tours) == len(tours):
            break
    
    # Check coverage
    all_tour_ids = {t.id for t in tours}
    missing = all_tour_ids - covered_tours
    
    if missing:
        logger.warning(f"Missing {len(missing)} tours after greedy selection!")
        # Add 1er blocks for missing tours
        tour_to_1er = {t.id: b for b in blocks if len(b.tours) == 1 for t in b.tours}
        for tid in missing:
            if tid in tour_to_1er:
                selected.append(tour_to_1er[tid])
                covered_tours.add(tid)
    
    return selected


if __name__ == "__main__":
    sys.exit(main())
