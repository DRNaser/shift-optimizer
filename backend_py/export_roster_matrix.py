#!/usr/bin/env python3
"""
SOLVEREIGN V3 Roster Matrix Export Script
=========================================

Standalone CLI for CI/CD workflows to run the solver and export results.

Usage:
    python backend_py/export_roster_matrix.py --time-budget 120 --seed 42

Outputs:
    backend_py/roster_matrix.csv - Driver x Day roster grid
    backend_py/solver_metrics.json - KPIs (FTE, PT, hours, etc.)

Input:
    Expects "forecast input.csv" in working directory (CI fixture)
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import time as dt_time
from pathlib import Path

# Ensure module paths are available
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "v3"))

try:
    from src.domain.models import Tour, Weekday
    from v3.solver_v2_integration import partition_tours_into_blocks
    from src.services.block_heuristic_solver import BlockHeuristicSolver
except ImportError as e:
    print(f"ERROR: Could not import solver modules: {e}")
    print("Make sure you're running from the project root with all dependencies installed.")
    sys.exit(2)


# Day name mapping
DAY_NAMES = {
    1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"
}


def parse_forecast_csv(file_path: str) -> list:
    """
    Parse the German-formatted forecast CSV into Tour objects.

    Supports two formats:
    1. Multi-column format (6 day columns with time;count pairs)
    2. Single-column format (Day headers with time;count rows)
    """
    tours = []
    tour_counter = 0

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Forecast file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.strip().split("\n")

    # Detect format: single-column (day headers) or multi-column
    is_single_column = any(
        line.strip().lower().startswith(day)
        for line in lines[:5]
        for day in ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
    )

    if is_single_column:
        tours = _parse_single_column_format(lines)
    else:
        tours = _parse_multi_column_format(lines)

    print(f"[PARSE] Loaded {len(tours)} tours from forecast")
    return tours


def _parse_single_column_format(lines: list) -> list:
    """Parse single-column format with day headers."""
    tours = []
    tour_counter = 0
    current_day = None

    day_mapping = {
        "montag": Weekday.MONDAY,
        "dienstag": Weekday.TUESDAY,
        "mittwoch": Weekday.WEDNESDAY,
        "donnerstag": Weekday.THURSDAY,
        "freitag": Weekday.FRIDAY,
        "samstag": Weekday.SATURDAY,
        "sonntag": Weekday.SUNDAY,
    }

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Check for day header
        for day_name, weekday in day_mapping.items():
            if line.lower().startswith(day_name):
                current_day = weekday
                break
        else:
            # Parse time;count row
            if current_day and ";" in line:
                parts = line.split(";")
                if len(parts) >= 2:
                    time_range = parts[0].strip()
                    count_str = parts[1].strip()

                    if "-" in time_range and count_str.isdigit():
                        try:
                            count = int(count_str)
                            if count > 0:
                                start_str, end_str = time_range.split("-")
                                start_h, start_m = map(int, start_str.split(":"))
                                end_h, end_m = map(int, end_str.split(":"))

                                for i in range(count):
                                    tour_counter += 1
                                    tour = Tour(
                                        id=f"T{tour_counter:04d}",
                                        day=current_day,
                                        start_time=dt_time(start_h, start_m),
                                        end_time=dt_time(end_h, end_m),
                                    )
                                    tours.append(tour)
                        except (ValueError, IndexError):
                            pass

    return tours


def _parse_multi_column_format(lines: list) -> list:
    """Parse multi-column format (6 days in columns)."""
    tours = []
    tour_counter = 0

    column_days = [
        (0, 1, Weekday.MONDAY),
        (2, 3, Weekday.TUESDAY),
        (4, 5, Weekday.WEDNESDAY),
        (6, 7, Weekday.THURSDAY),
        (8, 9, Weekday.FRIDAY),
        (10, 11, Weekday.SATURDAY),
    ]

    for line in lines[1:]:  # Skip header
        line = line.strip()
        if not line:
            continue

        parts = line.split(";")

        for time_col, count_col, weekday in column_days:
            if time_col >= len(parts) or count_col >= len(parts):
                continue

            time_range = parts[time_col].strip()
            count_str = parts[count_col].strip()

            if not time_range or not count_str or "-" not in time_range:
                continue

            try:
                count = int(count_str)
                if count <= 0:
                    continue

                start_str, end_str = time_range.split("-")
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))

                for i in range(count):
                    tour_counter += 1
                    tour = Tour(
                        id=f"T{tour_counter:04d}",
                        day=weekday,
                        start_time=dt_time(start_h, start_m),
                        end_time=dt_time(end_h, end_m),
                    )
                    tours.append(tour)
            except (ValueError, IndexError):
                continue

    return tours


def run_solver(tours: list, seed: int = 42) -> tuple:
    """
    Run the V3 solver and return drivers and metrics.

    Returns:
        (drivers, metrics_dict)
    """
    print(f"[SOLVER] Running with seed={seed}, tours={len(tours)}")

    # Step 1: Partition tours into blocks
    blocks = partition_tours_into_blocks(tours, seed=seed)
    print(f"[SOLVER] Created {len(blocks)} blocks")

    # Step 2: Run solver
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve()
    print(f"[SOLVER] Solution: {len(drivers)} drivers")

    # Step 3: Compute metrics
    fte_drivers = [d for d in drivers if d.total_hours >= 40.0]
    pt_drivers = [d for d in drivers if d.total_hours < 40.0]

    total_hours = sum(d.total_hours for d in drivers)
    total_tours_assigned = sum(
        len(b.tours) for d in drivers for b in d.blocks
    )

    metrics = {
        "seed": seed,
        "total_drivers": len(drivers),
        "fte_drivers": len(fte_drivers),
        "pt_drivers": len(pt_drivers),
        "pt_ratio": round(len(pt_drivers) / len(drivers) * 100, 2) if drivers else 0,
        "total_hours": round(total_hours, 2),
        "total_tours": len(tours),
        "total_tours_assigned": total_tours_assigned,
        "coverage": round(total_tours_assigned / len(tours) * 100, 2) if tours else 0,
        "avg_hours_per_driver": round(total_hours / len(drivers), 2) if drivers else 0,
    }

    return drivers, metrics


def export_roster_matrix(drivers: list, output_path: str) -> str:
    """
    Export roster matrix to CSV (driver x day grid).

    Returns:
        SHA256 hash of the exported file
    """
    # Build driver schedule matrix
    matrix = defaultdict(lambda: defaultdict(list))
    driver_hours = defaultdict(float)

    for driver in drivers:
        driver_id = driver.id
        driver_hours[driver_id] = driver.total_hours

        for block in driver.blocks:
            # Get day from first tour in block
            if block.tours:
                day_num = _weekday_to_day_num(block.tours[0].day)

                # Format time range
                start = min(t.start_time for t in block.tours)
                end = max(t.end_time for t in block.tours)
                time_str = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
                matrix[driver_id][day_num].append(time_str)

    # Sort drivers by ID
    sorted_drivers = sorted(matrix.keys())

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow(["Driver", "Mo", "Di", "Mi", "Do", "Fr", "Sa", "So", "Total Hours"])

        # Data rows
        for driver_id in sorted_drivers:
            row = [driver_id]
            for day in range(1, 8):
                tours = matrix[driver_id].get(day, [])
                row.append(" | ".join(tours) if tours else "")
            row.append(f"{driver_hours[driver_id]:.1f}")
            writer.writerow(row)

    # Compute hash
    with open(output_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    return file_hash


def _weekday_to_day_num(weekday: Weekday) -> int:
    """Convert Weekday enum to day number (1-7)."""
    mapping = {
        Weekday.MONDAY: 1,
        Weekday.TUESDAY: 2,
        Weekday.WEDNESDAY: 3,
        Weekday.THURSDAY: 4,
        Weekday.FRIDAY: 5,
        Weekday.SATURDAY: 6,
        Weekday.SUNDAY: 7,
    }
    return mapping.get(weekday, 1)


def main():
    parser = argparse.ArgumentParser(
        description="Run solver and export roster matrix for CI/CD"
    )
    parser.add_argument(
        "--time-budget",
        type=int,
        default=120,
        help="Time budget in seconds (for future use, currently ignored)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Solver seed for deterministic results"
    )
    parser.add_argument(
        "--input",
        default="forecast input.csv",
        help="Input forecast CSV file"
    )
    parser.add_argument(
        "--output-dir",
        default="backend_py",
        help="Output directory for results"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("SOLVEREIGN V3 - Roster Matrix Export")
    print("=" * 60)
    print(f"Input: {args.input}")
    print(f"Seed: {args.seed}")
    print(f"Time Budget: {args.time_budget}s")
    print("=" * 60)

    # Parse forecast
    try:
        tours = parse_forecast_csv(args.input)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    if not tours:
        print("ERROR: No tours parsed from forecast file")
        sys.exit(2)

    # Run solver
    drivers, metrics = run_solver(tours, seed=args.seed)

    if not drivers:
        print("ERROR: Solver returned no drivers")
        sys.exit(1)

    # Export roster matrix
    matrix_path = os.path.join(args.output_dir, "roster_matrix.csv")
    os.makedirs(args.output_dir, exist_ok=True)
    roster_hash = export_roster_matrix(drivers, matrix_path)

    # Add hash to metrics
    metrics["roster_hash"] = roster_hash

    # Export metrics
    metrics_path = os.path.join(args.output_dir, "solver_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # Print summary
    print("\n--- Results ---")
    print(f"FTE Drivers: {metrics['fte_drivers']}")
    print(f"PT Drivers: {metrics['pt_drivers']}")
    print(f"Total Hours: {metrics['total_hours']}")
    print(f"Coverage: {metrics['coverage']}%")
    print(f"Roster Hash: {roster_hash[:32]}...")
    print(f"\nExported: {matrix_path}")
    print(f"Metrics: {metrics_path}")

    # Exit with appropriate code
    if metrics['coverage'] < 100:
        print(f"\nWARNING: Coverage < 100% ({metrics['coverage']}%)")
        sys.exit(1)

    print("\n[SUCCESS] Export complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
