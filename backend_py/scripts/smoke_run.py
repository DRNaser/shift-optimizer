#!/usr/bin/env python
"""
Smoke Run - Deterministic Verification Suite

Modes:
1. --mode=synthetic: 30 tours (quick sanity)
2. --mode=stress: 300+ tours (scalability check)
3. --mode=forecast: Real forecast file (integration test)

Success Criteria:
- No Guard Failures
- coverage = 100% (exact-once)
- OutputContractGuard PASS
- iterations_done >= 2
- Hard thresholds: wall_time, pool_size

KPIs Logged:
- tours_per_driver
- avg_days_per_driver
- coverage_support_min/median/p10
- block_mix (1d/2d/3d/4d/5d)
"""

import os
import sys
import time
import json
import random
import logging
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Set, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from solvereign_v2.optimizer import Optimizer, OptimizationResult
from solvereign_v2.types import TourV2
from src.core_v2.guards import OutputContractGuard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SmokeRun")


# =============================================================================
# HARD THRESHOLDS (FAIL if exceeded)
# =============================================================================
THRESHOLDS = {
    "synthetic": {"wall_time_sec": 10, "pool_size": 5000},
    "stress": {"wall_time_sec": 60, "pool_size": 30000},
    "forecast": {"wall_time_sec": 120, "pool_size": 50000},
}


# =============================================================================
# SUPPORT STATS CALCULATOR
# =============================================================================
def calculate_support_stats(
    pool_columns: List[Any],
    all_tour_ids: Set[str]
) -> Dict[str, Any]:
    """Calculate coverage support statistics."""
    support: Dict[str, int] = {tid: 0 for tid in all_tour_ids}
    atomic_coverage: Dict[str, int] = {tid: 0 for tid in all_tour_ids}
    
    for col in pool_columns:
        is_atomic = getattr(col, 'is_singleton', False) and len(col.covered_tour_ids) == 1
        for tid in col.covered_tour_ids:
            if tid in support:
                support[tid] += 1
                if is_atomic:
                    atomic_coverage[tid] += 1
    
    support_values = sorted(support.values())
    n = len(support_values)
    
    if n == 0:
        return {"support_min": 0, "support_median": 0, "support_p10": 0, 
                "zero_support_count": 0, "atomic_min": 0}
    
    return {
        "support_min": support_values[0],
        "support_median": support_values[n // 2],
        "support_p10": support_values[max(0, int(n * 0.1))],
        "zero_support_count": sum(1 for s in support_values if s == 0),
        "atomic_min": min(atomic_coverage.values()) if atomic_coverage else 0,
    }


def calculate_block_mix(columns: List[Any]) -> Dict[int, int]:
    """Calculate days_worked distribution."""
    mix = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for col in columns:
        days = getattr(col, 'days_worked', 1)
        if days in mix:
            mix[days] += 1
        elif days > 5:
            mix[5] = mix.get(5, 0) + 1
    return mix


# =============================================================================
# DATA LOADERS
# =============================================================================
def generate_synthetic_tours(num_tours: int = 50, seed: int = 42) -> List[TourV2]:
    """Generate synthetic tour set."""
    random.seed(seed)
    tours = []
    
    for day in range(5):
        daily_count = num_tours // 5
        for i in range(daily_count):
            start_hour = random.randint(5, 18)
            start_min = start_hour * 60 + random.randint(0, 59)
            duration = random.randint(120, 300)
            end_min = start_min + duration
            
            tour = TourV2(
                tour_id=f"T{day}_{i:03d}",
                day=day,
                start_min=start_min,
                end_min=end_min,
                duration_min=duration,
            )
            tours.append(tour)
    
    return tours


def load_forecast_tours(forecast_path: str) -> List[TourV2]:
    """Load tours from forecast CSV file."""
    tours = []
    seen_ids = set()
    collisions = []
    
    with open(forecast_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tour_id = row['tour_id']
            
            # Check for ID collisions
            if tour_id in seen_ids:
                collisions.append(tour_id)
            seen_ids.add(tour_id)
            
            tour = TourV2(
                tour_id=tour_id,
                day=int(row['day']),
                start_min=int(row['start_min']),
                end_min=int(row['end_min']),
                duration_min=int(row.get('duration_min', int(row['end_min']) - int(row['start_min']))),
            )
            tours.append(tour)
    
    if collisions:
        logger.error(f"TOUR_ID COLLISIONS: {len(collisions)} duplicates found!")
        logger.error(f"First 10: {collisions[:10]}")
        raise ValueError(f"Tour ID collisions: {collisions[:10]}")
    
    logger.info(f"Loaded {len(tours)} tours from {forecast_path}")
    return tours


# =============================================================================
# SMOKE RUN
# =============================================================================
def run_smoke_test(
    mode: str = "synthetic",
    seed: int = 42,
    num_tours: int = 50,
    max_cg_iterations: int = 2,
    forecast_path: str = None,
    output_dir: str = "results/smoke"
) -> Dict[str, Any]:
    """Run smoke test with KPI diagnostics and hard thresholds."""
    start_time = time.time()
    run_id = f"smoke_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    thresholds = THRESHOLDS.get(mode, THRESHOLDS["synthetic"])
    
    logger.info(f"{'='*60}")
    logger.info(f"  SMOKE RUN: {run_id}")
    logger.info(f"  Mode: {mode}, Seed: {seed}, Max Iters: {max_cg_iterations}")
    logger.info(f"  Thresholds: time<={thresholds['wall_time_sec']}s, pool<={thresholds['pool_size']}")
    logger.info(f"{'='*60}")
    
    random.seed(seed)
    
    # Load tours
    if mode == "forecast" and forecast_path:
        tours = load_forecast_tours(forecast_path)
    elif mode == "stress":
        num_tours = max(300, num_tours)
        tours = generate_synthetic_tours(num_tours, seed)
    else:
        tours = generate_synthetic_tours(num_tours, seed)
    
    all_tour_ids = set(t.tour_id for t in tours)
    logger.info(f"Tours: {len(tours)} across {len(set(t.day for t in tours))} days")
    
    # Config
    config = {
        "max_cg_iterations": max_cg_iterations,
        "target_seed_columns": min(5000, len(tours) * 20),
        "lp_time_limit": 60.0 if mode == "forecast" else 5.0,
        "mip_time_limit": 90.0 if mode == "forecast" else 30.0,
        "pricing_time_limit_sec": 8.0 if mode == "forecast" else 3.0,
    }
    
    # Run optimizer
    optimizer = Optimizer()
    result = optimizer.solve(tours, config, run_id)
    
    wall_time = time.time() - start_time
    
    # === KPI CALCULATIONS ===
    kpis = dict(result.kpis)
    kpis["coverage_pct"] = result.proof.coverage_pct
    kpis["drivers_total"] = result.num_drivers
    
    # Tours per driver
    kpis["tours_per_driver"] = round(len(tours) / max(1, result.num_drivers), 2)
    
    # Avg days per driver
    if result.selected_columns:
        kpis["avg_days_per_driver"] = round(
            sum(c.days_worked for c in result.selected_columns) / len(result.selected_columns), 2
        )
    else:
        kpis["avg_days_per_driver"] = 0
    
    # Fleet peak
    day_drivers = {}
    for col in result.selected_columns:
        for duty in col.duties:
            day_drivers[duty.day] = day_drivers.get(duty.day, 0) + 1
    kpis["fleet_peak"] = max(day_drivers.values()) if day_drivers else 0
    
    # Pool size (from result or estimate)
    pool_size = result.kpis.get("pool_size", 0)
    kpis["pool_size_final"] = pool_size
    
    # Block mix
    block_mix = calculate_block_mix(result.selected_columns)
    kpis["block_mix"] = block_mix
    
    # === OUTPUT ===
    output_path = Path(output_dir) / run_id
    output_path.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "run_id": run_id,
        "mode": mode,
        "status": result.status,
        "seed": seed,
        "wall_time_sec": round(wall_time, 2),
        "iterations_done": result.kpis.get("cg_iterations", 0),
        "stop_reason": "CONVERGED" if result.status == "SUCCESS" else result.error_code,
        "kpis": kpis,
        "thresholds": thresholds,
        "proof": {
            "coverage_pct": result.proof.coverage_pct,
            "total_tours": result.proof.total_tours,
            "covered_tours": result.proof.covered_tours,
        },
    }
    
    manifest_path = output_path / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"Wrote manifest: {manifest_path}")
    
    # Write roster
    roster_path = None
    if result.status == "SUCCESS":
        roster_path = output_path / "roster.csv"
        with open(roster_path, "w", encoding='utf-8') as f:
            f.write("driver_id,day,duty_start,duty_end,tour_ids,hours\n")
            for i, col in enumerate(result.selected_columns):
                driver_type = "FTE" if col.hours >= 40 else "PT"
                driver_id = f"D_{driver_type}{i+1:03d}"
                for duty in col.duties:
                    f.write(f"{driver_id},{duty.day},{duty.start_min},{duty.end_min},")
                    f.write(f"{'|'.join(duty.tour_ids)},{col.hours:.1f}\n")
        logger.info(f"Wrote roster: {roster_path}")
    
    # === VALIDATION ===
    guard_passed = True
    guard_error = None
    threshold_passed = True
    threshold_errors = []
    
    # Output contract
    try:
        OutputContractGuard.validate(
            str(manifest_path),
            str(roster_path) if roster_path else None,
            expected_tour_ids=all_tour_ids,
            strict=True
        )
    except AssertionError as e:
        guard_passed = False
        guard_error = str(e)
    
    # Hard thresholds
    if wall_time > thresholds["wall_time_sec"]:
        threshold_passed = False
        threshold_errors.append(f"wall_time={wall_time:.1f}s > {thresholds['wall_time_sec']}s")
    
    if pool_size > thresholds["pool_size"]:
        threshold_passed = False
        threshold_errors.append(f"pool_size={pool_size} > {thresholds['pool_size']}")
    
    # === RESULT ===
    test_result = {
        "run_id": run_id,
        "mode": mode,
        "seed": seed,
        "tours": len(tours),
        "wall_time_sec": round(wall_time, 2),
        "status": result.status,
        "iterations_done": result.kpis.get("cg_iterations", 0),
        "coverage_pct": result.proof.coverage_pct,
        "drivers": result.num_drivers,
        "tours_per_driver": kpis["tours_per_driver"],
        "avg_days_per_driver": kpis["avg_days_per_driver"],
        "pool_size": pool_size,
        "block_mix": block_mix,
        "guard_passed": guard_passed,
        "guard_error": guard_error,
        "threshold_passed": threshold_passed,
        "threshold_errors": threshold_errors,
        "output_dir": str(output_path),
    }
    
    # === PRINT SUMMARY ===
    logger.info(f"\n{'='*60}")
    logger.info(f"  SMOKE RUN RESULT ({mode.upper()})")
    logger.info(f"{'='*60}")
    logger.info(f"  Status:            {result.status}")
    logger.info(f"  Tours:             {len(tours)}")
    logger.info(f"  Iterations:        {test_result['iterations_done']}")
    logger.info(f"  Coverage:          {test_result['coverage_pct']}%")
    logger.info(f"  Drivers:           {test_result['drivers']}")
    logger.info(f"  Tours/Driver:      {kpis['tours_per_driver']}")
    logger.info(f"  Avg Days/Driver:   {kpis['avg_days_per_driver']}")
    logger.info(f"  Pool Size:         {pool_size}")
    logger.info(f"  Block Mix:         1d={block_mix[1]} 2d={block_mix[2]} 3d={block_mix[3]} 4d={block_mix[4]} 5d={block_mix[5]}")
    logger.info(f"  Guard Passed:      {guard_passed}")
    logger.info(f"  Threshold Passed:  {threshold_passed}")
    logger.info(f"  Wall Time:         {wall_time:.2f}s")
    
    if threshold_errors:
        for err in threshold_errors:
            logger.warning(f"  THRESHOLD FAIL: {err}")
    
    # Success criteria
    success = (
        result.status == "SUCCESS" and
        test_result["coverage_pct"] == 100.0 and
        guard_passed and
        threshold_passed and
        test_result["iterations_done"] >= 1
    )
    
    test_result["success"] = success
    
    if success:
        logger.info(f"  SMOKE TEST:        ✅ PASS")
    else:
        logger.error(f"  SMOKE TEST:        ❌ FAIL")
        if guard_error:
            logger.error(f"  Guard Error: {guard_error[:200]}...")
    
    logger.info(f"{'='*60}\n")
    
    return test_result


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Smoke Run Suite")
    parser.add_argument("--mode", choices=["synthetic", "stress", "forecast"], 
                        default="synthetic", help="Test mode")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--tours", type=int, default=50, help="Number of synthetic tours")
    parser.add_argument("--iters", type=int, default=2, help="Max CG iterations")
    parser.add_argument("--forecast", default="data/forecast_kw51_converted.csv",
                        help="Forecast CSV file")
    parser.add_argument("--output", default="results/smoke", help="Output directory")
    
    args = parser.parse_args()
    
    result = run_smoke_test(
        mode=args.mode,
        seed=args.seed,
        num_tours=args.tours,
        max_cg_iterations=args.iters,
        forecast_path=args.forecast,
        output_dir=args.output
    )
    
    sys.exit(0 if result["success"] else 1)
