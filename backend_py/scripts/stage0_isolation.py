#!/usr/bin/env python
"""
Stage0 Isolation Test Script
============================
Tests block generation with different Gap configurations to find optimal settings.

This script runs block generation phase (Phase 0) in isolation with various
override configurations and compares the results:
- V0: Default (30-60 min regular, 360 split)
- V1: GAP_75 (30-75 min regular)
- V2: GAP_90 (30-90 min regular)
- V3: SPLIT_FLEX (360-480 split min)

NEW: Also runs Stage0 Set-Packing to find maximum disjoint 3er selection.

Output: Comparative statistics showing impact on 3er/2er/1er block counts.

Usage:
    python scripts/stage0_isolation.py [--tours-file PATH] [--with-packing]
"""

import argparse
import json
import logging
import sys
from datetime import time
from pathlib import Path
from time import perf_counter

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.models import Tour, Weekday
from src.services.smart_block_builder import (
    build_weekly_blocks_smart,
    BlockGenOverrides,
    DEFAULT_BLOCKGEN_OVERRIDES,
)
from src.services.stage0_solver import solve_stage0_3er_packing

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# TOUR LOADERS
# =============================================================================

DAY_MAP = {
    "Montag": Weekday.MONDAY,
    "Dienstag": Weekday.TUESDAY,
    "Mittwoch": Weekday.WEDNESDAY,
    "Donnerstag": Weekday.THURSDAY,
    "Freitag": Weekday.FRIDAY,
    "Samstag": Weekday.SATURDAY,
}


def load_tours_from_csv(csv_path: Path) -> list[Tour]:
    """
    Load tours from forecast input CSV.
    
    Format:
    Montag;Anzahl
    04:45-09:15;15
    ...
    
    Each row = time window with count -> expand to N individual tours.
    """
    import csv
    
    tours = []
    tour_id = 0
    current_day = None
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row or not row[0].strip():
                continue
            
            first_col = row[0].strip()
            
            # Check if this is a day header
            for day_name, day_enum in DAY_MAP.items():
                if first_col.startswith(day_name):
                    current_day = day_enum
                    break
            else:
                # Parse time window and count
                if '-' in first_col and current_day:
                    try:
                        time_range = first_col
                        count = int(row[1].strip()) if len(row) > 1 and row[1].strip() else 1
                        
                        start_str, end_str = time_range.split('-')
                        start_h, start_m = map(int, start_str.strip().split(':'))
                        end_h, end_m = map(int, end_str.strip().split(':'))
                        
                        start_time_obj = time(start_h, start_m)
                        end_time_obj = time(end_h, end_m)
                        
                        # Calculate duration
                        start_mins = start_h * 60 + start_m
                        end_mins = end_h * 60 + end_m
                        duration_hours = (end_mins - start_mins) / 60.0
                        
                        # Create N tours for this window
                        for i in range(count):
                            tour_id += 1
                            tours.append(Tour(
                                id=f"T{tour_id:04d}",
                                day=current_day,
                                start_time=start_time_obj,
                                end_time=end_time_obj,
                                duration_hours=duration_hours,
                            ))
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Skipping invalid row: {row} - {e}")
    
    return tours


def load_tours_from_json(json_path: Path) -> list[Tour]:
    """Load tours from JSON file (forecast_medium.json format)."""
    DAY_MAP_SHORT = {
        "Mon": Weekday.MONDAY,
        "Tue": Weekday.TUESDAY,
        "Wed": Weekday.WEDNESDAY,
        "Thu": Weekday.THURSDAY,
        "Fri": Weekday.FRIDAY,
        "Sat": Weekday.SATURDAY,
    }
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    tours = []
    for t in data.get("tours", []):
        day_str = t.get("day", "Mon")
        day = DAY_MAP_SHORT.get(day_str, Weekday.MONDAY)
        
        start_str = t.get("start", "00:00")
        end_str = t.get("end", "00:00")
        
        start_h, start_m = map(int, start_str.split(':'))
        end_h, end_m = map(int, end_str.split(':'))
        
        start_mins = start_h * 60 + start_m
        end_mins = end_h * 60 + end_m
        duration_hours = (end_mins - start_mins) / 60.0
        
        tours.append(Tour(
            id=t.get("id", f"T{len(tours)+1:04d}"),
            day=day,
            start_time=time(start_h, start_m),
            end_time=time(end_h, end_m),
            duration_hours=duration_hours,
        ))
    
    return tours


# =============================================================================
# TEST CONFIGURATIONS
# =============================================================================

CONFIGURATIONS = {
    "V0_DEFAULT": BlockGenOverrides(
        min_pause_minutes=30,
        max_pause_regular_minutes=60,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
    ),
    "V1_GAP_75": BlockGenOverrides(
        min_pause_minutes=30,
        max_pause_regular_minutes=75,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
    ),
    "V2_GAP_90": BlockGenOverrides(
        min_pause_minutes=30,
        max_pause_regular_minutes=90,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
    ),
    "V3_SPLIT_FLEX": BlockGenOverrides(
        min_pause_minutes=30,
        max_pause_regular_minutes=60,
        split_pause_min_minutes=300,  # Allow 5h splits
        split_pause_max_minutes=420,  # Up to 7h splits
    ),
    "V4_WIDE": BlockGenOverrides(
        min_pause_minutes=25,
        max_pause_regular_minutes=90,
        split_pause_min_minutes=300,
        split_pause_max_minutes=420,
    ),
}


def create_demo_tours() -> list[Tour]:
    """Create a demo set of tours with realistic gaps for 2er/3er blocks."""
    tours = []
    tour_id = 0
    
    # Create tours for each weekday with realistic gaps
    for day in [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, 
                Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]:
        
        # Pattern 1: Dense morning block (3 tours with 30-45 min gaps)
        # Tour 1: 06:00-08:00
        # Tour 2: 08:30-10:30 (30 min gap)
        # Tour 3: 11:00-13:00 (30 min gap) 
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(6, 0), end_time=time(8, 0), duration_hours=2.0))
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(8, 30), end_time=time(10, 30), duration_hours=2.0))
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(11, 0), end_time=time(13, 0), duration_hours=2.0))
        
        # Pattern 2: Afternoon block (2 tours with 45 min gap)
        # Tour 4: 14:00-16:00
        # Tour 5: 16:45-18:45 (45 min gap)
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(14, 0), end_time=time(16, 0), duration_hours=2.0))
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(16, 45), end_time=time(18, 45), duration_hours=2.0))
        
        # Pattern 3: Evening tour (split-compatible with morning)
        # Tour 6: 19:00-21:00 (split gap from Tour 1 = 11h, from Tour 2 = 8.5h, from Tour 3 = 6h exact!)
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(19, 0), end_time=time(21, 0), duration_hours=2.0))
        
        # Pattern 4: Early morning tour
        # Tour 7: 05:00-06:00 (can combine with Tour 1 if gap allows)
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(5, 0), end_time=time(6, 0), duration_hours=1.0))
        
        # Pattern 5: Mid-afternoon standalone (wider gaps)
        # Tour 8: 12:00-13:30 (gap from Tour 3 may allow connection)
        tour_id += 1
        tours.append(Tour(id=f"T{tour_id:04d}", day=day, start_time=time(13, 30), end_time=time(14, 30), duration_hours=1.0))
    
    return tours


def run_isolation_test(
    tours: list[Tour],
    config_name: str,
    overrides: BlockGenOverrides,
    with_packing: bool = False,
) -> dict:
    """Run block generation with given overrides and return statistics."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Running: {config_name}")
    logger.info(f"{'='*60}")
    logger.info(f"Overrides: {overrides.to_log_dict()}")
    
    start = perf_counter()
    blocks, stats = build_weekly_blocks_smart(
        tours,
        overrides=overrides,
        enable_diag=True,
    )
    elapsed = perf_counter() - start
    
    # Count block types
    count_1er = sum(1 for b in blocks if len(b.tours) == 1)
    count_2er_reg = sum(1 for b in blocks if len(b.tours) == 2 and not b.is_split)
    count_2er_split = sum(1 for b in blocks if len(b.tours) == 2 and b.is_split)
    count_3er = sum(1 for b in blocks if len(b.tours) == 3)
    blocks_3er = [b for b in blocks if len(b.tours) == 3]
    
    result = {
        "config_name": config_name,
        "overrides": overrides.to_log_dict(),
        "tours_count": len(tours),
        "blocks_total": len(blocks),
        "blocks_1er": count_1er,
        "blocks_2er_reg": count_2er_reg,
        "blocks_2er_split": count_2er_split,
        "blocks_3er": count_3er,
        "time_s": round(elapsed, 3),
        "stats": stats,
    }
    
    logger.info(f"Results: 1er={count_1er}, 2er_reg={count_2er_reg}, "
                f"2er_split={count_2er_split}, 3er={count_3er}")
    logger.info(f"Total blocks: {len(blocks)} in {elapsed:.2f}s")
    
    # Optional: Run Set-Packing to find max disjoint 3er
    if with_packing and blocks_3er:
        logger.info(f"\n[Set-Packing] Solving for max disjoint 3er...")
        packing_result = solve_stage0_3er_packing(
            blocks_3er=blocks_3er,
            tours=tours,
            time_limit=10.0,
            seed=42,
        )
        result["packing"] = packing_result.to_dict()
        result["max_disjoint_3er"] = packing_result.raw_3er_obj
        result["deg3_max"] = packing_result.deg3_max
        result["deg3_p95"] = packing_result.deg3_p95
        
        logger.info(f"[Set-Packing] Max disjoint 3er: {packing_result.raw_3er_obj} (of {count_3er} candidates)")
        logger.info(f"[Set-Packing] deg3_max={packing_result.deg3_max}, deg3_p95={packing_result.deg3_p95:.1f}")
    
    return result


def run_all_tests(tours: list[Tour], with_packing: bool = False) -> list[dict]:
    """Run all configuration tests and return results."""
    results = []
    
    logger.info("\n" + "="*70)
    logger.info("STAGE0 ISOLATION TEST - Block Generation Comparison")
    if with_packing:
        logger.info("  [With Set-Packing enabled]")
    logger.info("="*70)
    logger.info(f"Tours: {len(tours)}")
    
    for config_name, overrides in CONFIGURATIONS.items():
        result = run_isolation_test(tours, config_name, overrides, with_packing)
        results.append(result)
    
    return results


def print_comparison_table(results: list[dict], with_packing: bool = False):
    """Print a comparison table of all results."""
    logger.info("\n" + "="*85)
    logger.info("COMPARISON TABLE")
    logger.info("="*85)
    
    # Header (with optional packing columns)
    if with_packing:
        header = f"{'Config':<15} {'1er':>6} {'2er_R':>7} {'2er_S':>7} {'3er':>6} {'Max3':>5} {'deg3':>5} {'Total':>7}"
    else:
        header = f"{'Config':<15} {'1er':>6} {'2er_R':>7} {'2er_S':>7} {'3er':>6} {'Total':>7} {'Time':>6}"
    logger.info(header)
    logger.info("-" * 85)
    
    # Rows
    for r in results:
        if with_packing and 'max_disjoint_3er' in r:
            row = (f"{r['config_name']:<15} "
                   f"{r['blocks_1er']:>6} "
                   f"{r['blocks_2er_reg']:>7} "
                   f"{r['blocks_2er_split']:>7} "
                   f"{r['blocks_3er']:>6} "
                   f"{r['max_disjoint_3er']:>5} "
                   f"{r['deg3_max']:>5} "
                   f"{r['blocks_total']:>7}")
        else:
            row = (f"{r['config_name']:<15} "
                   f"{r['blocks_1er']:>6} "
                   f"{r['blocks_2er_reg']:>7} "
                   f"{r['blocks_2er_split']:>7} "
                   f"{r['blocks_3er']:>6} "
                   f"{r['blocks_total']:>7} "
                   f"{r['time_s']:>5.2f}s")
        logger.info(row)
    
    # Find best configurations
    if results:
        best_3er = max(results, key=lambda x: x['blocks_3er'])
        logger.info("-" * 85)
        logger.info(f"BEST 3er candidates: {best_3er['config_name']} with {best_3er['blocks_3er']} blocks")
        
        if with_packing and 'max_disjoint_3er' in results[0]:
            best_max = max(results, key=lambda x: x.get('max_disjoint_3er', 0))
            logger.info(f"BEST max disjoint: {best_max['config_name']} with {best_max['max_disjoint_3er']} disjoint 3er")
    
    logger.info("="*85)


def save_results(results: list[dict], output_path: Path):
    """Save results to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Stage0 Isolation Test")
    parser.add_argument("--tours-file", type=Path, help="Path to tours CSV or JSON file")
    parser.add_argument("--output", type=Path, default=Path("results/stage0_isolation.json"),
                        help="Output JSON path")
    parser.add_argument("--with-packing", action="store_true",
                        help="Run Stage0 Set-Packing to find max disjoint 3er")
    args = parser.parse_args()
    
    # Load or create tours
    if args.tours_file and args.tours_file.exists():
        logger.info(f"Loading tours from: {args.tours_file}")
        
        suffix = args.tours_file.suffix.lower()
        if suffix == '.csv':
            tours = load_tours_from_csv(args.tours_file)
        elif suffix == '.json':
            tours = load_tours_from_json(args.tours_file)
        else:
            logger.error(f"Unsupported file format: {suffix}")
            return 1
        
        logger.info(f"Loaded {len(tours)} tours from file")
    else:
        logger.info("Using demo tours (no file provided)")
        tours = create_demo_tours()
    
    # Run tests
    results = run_all_tests(tours, with_packing=args.with_packing)
    
    # Print comparison
    print_comparison_table(results, with_packing=args.with_packing)
    
    # Save results
    save_results(results, args.output)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
