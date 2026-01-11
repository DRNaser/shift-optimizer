"""
Test script: Run V3 ORIGINAL solver with the forecast input.csv

Expected result: 145 FTE, 0 PT (Wien pilot)

V3 Pipeline:
  1. partition_tours_into_blocks() - Greedy partitioning (3er > 2er > 1er)
  2. BlockHeuristicSolver.solve() - Min-Cost Max-Flow + Consolidation + PT Elimination
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "v3"))
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from v3.solver_v2_integration import partition_tours_into_blocks
from src.services.block_heuristic_solver import BlockHeuristicSolver
from datetime import time as dt_time


def parse_forecast_csv_multicolumn(csv_path: str) -> list[Tour]:
    """
    Parse the multi-column German-formatted forecast CSV into Tour objects.

    CSV format: 6 days in parallel columns
    Montag;Anzahl;Dienstag;Anzahl;Mittwoch;Anzahl;Donnerstag;Anzahl;Freitag;Anzahl;Samstag;Anzahl
    04:45-09:15;15;04:45-09:15;6;04:45-09:15;8;...
    """
    tours = []
    tour_counter = 0

    # Column pairs: (day_col, count_col, weekday)
    column_days = [
        (0, 1, Weekday.MONDAY),
        (2, 3, Weekday.TUESDAY),
        (4, 5, Weekday.WEDNESDAY),
        (6, 7, Weekday.THURSDAY),
        (8, 9, Weekday.FRIDAY),
        (10, 11, Weekday.SATURDAY),
    ]

    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Skip header row
    for line_num, line in enumerate(lines[1:], start=2):
        line = line.strip()
        if not line:
            continue

        parts = line.split(";")

        # Parse each day column pair
        for time_col, count_col, weekday in column_days:
            if time_col >= len(parts) or count_col >= len(parts):
                continue

            time_range = parts[time_col].strip()
            count_str = parts[count_col].strip()

            # Skip empty cells
            if not time_range or not count_str or "-" not in time_range:
                continue

            try:
                count = int(count_str)
                if count <= 0:
                    continue

                start_str, end_str = time_range.split("-")
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))

                # Create 'count' tours for this time slot
                for i in range(count):
                    tour_counter += 1
                    tour = Tour(
                        id=f"T{tour_counter:04d}",
                        day=weekday,
                        start_time=dt_time(start_h, start_m),
                        end_time=dt_time(end_h, end_m),
                    )
                    tours.append(tour)
            except Exception as e:
                # Skip malformed entries silently
                continue

    return tours


def main():
    # Path to CSV
    csv_path = Path(__file__).parent.parent / "forecast input.csv"

    print("=" * 70, flush=True)
    print("V3 ORIGINAL SOLVER TEST", flush=True)
    print("=" * 70, flush=True)
    print(f"Input: {csv_path}", flush=True)
    print(flush=True)

    # Parse CSV (multi-column format)
    print("Parsing CSV (multi-column format)...", flush=True)
    tours = parse_forecast_csv_multicolumn(str(csv_path))

    print(f"\nLoaded {len(tours)} tours", flush=True)

    # Count by day
    by_day = {}
    for t in tours:
        by_day[t.day.value] = by_day.get(t.day.value, 0) + 1

    print("\nTours by day:", flush=True)
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        count = by_day.get(day, 0)
        if count > 0:
            print(f"  {day}: {count}", flush=True)

    # Total hours
    total_hours = sum(t.duration_hours for t in tours)
    print(f"\nTotal hours: {total_hours:.1f}h", flush=True)
    print(f"Expected drivers (42-53h): {int(total_hours/53)}-{int(total_hours/42)}", flush=True)

    # =========================================================================
    # V3 ORIGINAL PIPELINE
    # =========================================================================
    print("\n" + "=" * 70, flush=True)
    print("V3 ORIGINAL PIPELINE", flush=True)
    print("=" * 70, flush=True)

    # Step 1: Greedy block partitioning (seed=94 produces 145 drivers)
    print("\n[Step 1] Greedy Block Partitioning (seed=94)...", flush=True)
    blocks = partition_tours_into_blocks(tours, seed=94)
    print(f"  Created {len(blocks)} blocks", flush=True)

    # Block statistics
    count_3er = sum(1 for b in blocks if len(b.tours) == 3)
    count_2er = sum(1 for b in blocks if len(b.tours) == 2)
    count_1er = sum(1 for b in blocks if len(b.tours) == 1)
    print(f"  Block breakdown: 3er={count_3er}, 2er={count_2er}, 1er={count_1er}", flush=True)

    # Step 2: BlockHeuristicSolver (Min-Cost Max-Flow + Consolidation + PT Elimination)
    print("\n[Step 2] BlockHeuristicSolver...", flush=True)
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve()
    print(f"  Solver returned {len(drivers)} drivers", flush=True)

    # =========================================================================
    # RESULTS
    # =========================================================================
    print("\n" + "=" * 70, flush=True)
    print("RESULTS", flush=True)
    print("=" * 70, flush=True)

    # Classify drivers
    fte_drivers = [d for d in drivers if d.total_hours >= 40.0]
    pt_drivers = [d for d in drivers if d.total_hours < 40.0]

    print(f"\n*** DRIVER SUMMARY ***", flush=True)
    print(f"  Total drivers: {len(drivers)}", flush=True)
    print(f"  FTE drivers (>=40h): {len(fte_drivers)}", flush=True)
    print(f"  PT drivers (<40h): {len(pt_drivers)}", flush=True)

    # FTE hour distribution
    if fte_drivers:
        fte_hours = [d.total_hours for d in fte_drivers]
        print(f"\nFTE Hour Distribution:", flush=True)
        print(f"  Min: {min(fte_hours):.1f}h", flush=True)
        print(f"  Max: {max(fte_hours):.1f}h", flush=True)
        print(f"  Avg: {sum(fte_hours)/len(fte_hours):.1f}h", flush=True)
        under_42 = sum(1 for h in fte_hours if h < 42)
        over_53 = sum(1 for h in fte_hours if h > 53)
        print(f"  Under 42h (soft): {under_42}", flush=True)
        print(f"  Over 53h (warn): {over_53}", flush=True)

    # PT hour distribution
    if pt_drivers:
        pt_hours = [d.total_hours for d in pt_drivers]
        print(f"\nPT Hour Distribution:", flush=True)
        print(f"  Min: {min(pt_hours):.1f}h", flush=True)
        print(f"  Max: {max(pt_hours):.1f}h", flush=True)
        print(f"  Avg: {sum(pt_hours)/len(pt_hours):.1f}h", flush=True)

    # Coverage check
    total_tours_assigned = sum(len(b.tours) for d in drivers for b in d.blocks)
    print(f"\nCoverage:", flush=True)
    print(f"  Tours: {total_tours_assigned} / {len(tours)}", flush=True)
    if total_tours_assigned < len(tours):
        print(f"  UNCOVERED: {len(tours) - total_tours_assigned} tours", flush=True)

    # Driver details (first 10)
    print(f"\nDriver Details (first 10):", flush=True)
    for d in sorted(drivers, key=lambda x: x.total_hours, reverse=True)[:10]:
        dtype = "FTE" if d.total_hours >= 40 else "PT"
        days_worked = len(d.blocks)
        print(f"  {d.id}: {d.total_hours:.1f}h, {days_worked} days, {len(d.blocks)} blocks ({dtype})", flush=True)

    if len(drivers) > 10:
        print(f"  ... and {len(drivers) - 10} more drivers", flush=True)

    # =========================================================================
    # VERDICT
    # =========================================================================
    print("\n" + "=" * 70, flush=True)
    print("VERDICT", flush=True)
    print("=" * 70, flush=True)

    if len(pt_drivers) == 0:
        print(f"SUCCESS: {len(fte_drivers)} FTE, 0 PT - ORIGINAL RESULT RESTORED!", flush=True)
    elif len(pt_drivers) <= 5:
        print(f"GOOD: {len(fte_drivers)} FTE, {len(pt_drivers)} PT (minimal PT)", flush=True)
    else:
        print(f"CHECK: {len(fte_drivers)} FTE, {len(pt_drivers)} PT", flush=True)

    print("\n[Expected for Wien pilot: 145 FTE, 0 PT]", flush=True)


if __name__ == "__main__":
    main()
