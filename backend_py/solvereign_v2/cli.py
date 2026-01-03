"""
Solvereign V2 - Command Line Interface

Usage:
    python -m solvereign_v2.cli --input data/forecast.csv --output results/run_001
"""

import argparse
import json
import csv
import logging
import sys
from pathlib import Path
from datetime import datetime

from .types import TourV2
from .optimizer import Optimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SolvereIgnCLI")


def load_forecast_csv(path: str) -> list[TourV2]:
    """Load forecast from CSV file."""
    tours = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Expected columns: tour_id, day, start_min, end_min, duration_min, [num_drivers_needed]
            tour_id = row.get("tour_id", row.get("id", ""))
            day = int(row.get("day", 0))
            start_min = int(row.get("start_min", row.get("start", 0)))
            end_min = int(row.get("end_min", row.get("end", 0)))
            duration_min = int(row.get("duration_min", end_min - start_min))
            
            # Handle driver multiplicity
            num_drivers = int(row.get("num_drivers_needed", row.get("drivers", 1)))
            
            for i in range(num_drivers):
                instance_id = f"{tour_id}_{i+1}" if num_drivers > 1 else tour_id
                tour = TourV2(
                    tour_id=instance_id,
                    day=day,
                    start_min=start_min,
                    end_min=end_min,
                    duration_min=duration_min,
                )
                tours.append(tour)
    
    logger.info(f"Loaded {len(tours)} tours from {path}")
    return tours


def write_roster_csv(columns: list, output_path: str):
    """Write roster solution to CSV."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "driver_id", "driver_type", "day", "duty_id", "duty_start", "duty_end",
            "tour_ids", "work_min", "hours", "days_worked"
        ])
        
        for i, col in enumerate(columns):
            driver_type = "FTE" if col.hours >= 40.0 else "PT"
            driver_id = f"D_{driver_type}{i+1:03d}"
            
            for duty in col.duties:
                writer.writerow([
                    driver_id,
                    driver_type,
                    duty.day,
                    duty.duty_id,
                    duty.start_min,
                    duty.end_min,
                    "|".join(duty.tour_ids),
                    duty.work_min,
                    f"{col.hours:.1f}",
                    col.days_worked,
                ])
    
    logger.info(f"Wrote roster to {output_path}")


def write_manifest(result, output_path: str, input_path: str, config: dict):
    """Write run manifest JSON."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "run_id": result.run_id,
        "timestamp": datetime.now().isoformat(),
        "input_file": input_path,
        "status": result.status,
        "is_valid": result.is_valid,
        "config": config,
        "kpis": result.kpis,
        "proof": {
            "coverage_pct": result.proof.coverage_pct,
            "total_tours": result.proof.total_tours,
            "covered_tours": result.proof.covered_tours,
            "artificial_used_final": result.proof.artificial_used_final,
        },
    }
    
    if result.error_code:
        manifest["error"] = {
            "code": result.error_code,
            "message": result.error_message,
        }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"Wrote manifest to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Solvereign V2 Optimizer - Driver Scheduling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m solvereign_v2.cli --input data/forecast.csv
    python -m solvereign_v2.cli --input data/forecast.csv --output results/run_001
    python -m solvereign_v2.cli --input data/forecast.csv --max-iter 50 --mip-time 600
        """
    )
    
    parser.add_argument("--input", "-i", required=True, help="Input forecast CSV file")
    parser.add_argument("--output", "-o", default="results", help="Output directory")
    parser.add_argument("--run-id", default=None, help="Run ID (default: timestamp)")
    
    # Solver config
    parser.add_argument("--max-iter", type=int, default=30, help="Max CG iterations")
    parser.add_argument("--lp-time", type=float, default=10.0, help="LP time limit (seconds)")
    parser.add_argument("--mip-time", type=float, default=300.0, help="MIP time limit (seconds)")
    parser.add_argument("--target-seeds", type=int, default=5000, help="Target seed columns")
    
    args = parser.parse_args()
    
    # Generate run ID
    run_id = args.run_id or datetime.now().strftime("sv2_%Y%m%d_%H%M%S")
    
    # Load tours
    try:
        tours = load_forecast_csv(args.input)
    except Exception as e:
        logger.error(f"Failed to load input: {e}")
        sys.exit(1)
    
    if not tours:
        logger.error("No tours found in input file")
        sys.exit(1)
    
    # Build config
    config = {
        "max_cg_iterations": args.max_iter,
        "lp_time_limit": args.lp_time,
        "mip_time_limit": args.mip_time,
        "target_seed_columns": args.target_seeds,
    }
    
    # Run optimizer
    optimizer = Optimizer()
    result = optimizer.solve(tours, config, run_id)
    
    # Prepare output paths
    output_dir = Path(args.output) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    roster_path = output_dir / "roster.csv"
    manifest_path = output_dir / "manifest.json"
    
    # Write outputs
    if result.status == "SUCCESS":
        write_roster_csv(result.selected_columns, str(roster_path))
    
    write_manifest(result, str(manifest_path), args.input, config)
    
    # GUARD: Validate output artifacts
    try:
        from src.core_v2.guards import OutputContract
        valid, issues = OutputContract.validate_output(run_id, str(output_dir))
        if not valid:
            logger.warning(f"[GUARD] OutputContract issues: {issues}")
    except ImportError:
        pass  # Guards not available in solvereign_v2 package
    except Exception as e:
        logger.warning(f"[GUARD] OutputContract validation failed: {e}")
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"  SOLVEREIGN V2 - {result.status}")
    print("=" * 60)
    
    if result.status == "SUCCESS":
        print(f"  Drivers:     {result.num_drivers}")
        print(f"  FTE:         {result.kpis.get('drivers_fte', 'N/A')}")
        print(f"  PT:          {result.kpis.get('drivers_pt', 'N/A')} ({result.kpis.get('pt_share_pct', 0):.1f}%)")
        print(f"  Avg Hours:   {result.kpis.get('avg_hours', 0):.1f}")
        print(f"  Coverage:    {result.proof.coverage_pct:.1f}%")
        print(f"  Time:        {result.kpis.get('total_time', 0):.1f}s")
        print(f"  Output:      {output_dir}")
    else:
        print(f"  Error: {result.error_code}")
        print(f"  Message: {result.error_message}")
    
    print("=" * 60 + "\n")
    
    sys.exit(0 if result.status == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
