"""
SOLVEREIGN Roster Pack - Solve Tool
====================================

Core solver tool for roster generation.

Usage:
    python -m packs.roster.tools.solve --input forecast.csv --output roster.csv --seed 42
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import time as dt_time
from pathlib import Path
from typing import Optional

from ..engine.solver_v2_integration import solve_with_v2_solver
from ..engine.src_compat.models import Tour, Weekday


DAY_MAP = {
    "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7,
    "mo": 1, "di": 2, "mi": 3, "do": 4, "fr": 5, "sa": 6, "so": 7,
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 7,
}

DAY_TO_WEEKDAY = {
    1: Weekday.MONDAY, 2: Weekday.TUESDAY, 3: Weekday.WEDNESDAY,
    4: Weekday.THURSDAY, 5: Weekday.FRIDAY, 6: Weekday.SATURDAY, 7: Weekday.SUNDAY,
}


def parse_forecast_csv(csv_path: str) -> list[dict]:
    """
    Parse forecast CSV into tour instance dicts.

    Expected CSV format:
        day,start_time,end_time,location,qualifications
        Mon,06:00,14:00,Vienna,
        Mon,14:00,22:00,Vienna,Kuehl
    """
    instances = []
    instance_id = 1

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            if not any(row.values()):
                continue

            day_str = row.get("day", row.get("tag", "")).lower()
            day = DAY_MAP.get(day_str)
            if day is None:
                try:
                    day = int(day_str)
                except ValueError:
                    continue

            start_str = row.get("start_time", row.get("start", row.get("von", "")))
            end_str = row.get("end_time", row.get("end", row.get("bis", "")))

            try:
                start_parts = start_str.split(":")
                start_ts = dt_time(int(start_parts[0]), int(start_parts[1]))
                end_parts = end_str.split(":")
                end_ts = dt_time(int(end_parts[0]), int(end_parts[1]))
            except (ValueError, IndexError):
                continue

            location = row.get("location", row.get("depot", "Vienna"))
            quals_str = row.get("qualifications", row.get("skills", ""))
            quals = [q.strip() for q in quals_str.split(",") if q.strip()] if quals_str else []

            instances.append({
                "id": instance_id,
                "day": day,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "location": location,
                "required_qualifications": quals,
            })
            instance_id += 1

    return instances


def solve_roster(
    instances: list[dict],
    seed: int = 42
) -> tuple[list[dict], dict]:
    """
    Run the deterministic solver on tour instances.

    Args:
        instances: List of tour instance dicts
        seed: Random seed for determinism

    Returns:
        Tuple of (assignments, stats)
    """
    assignments = solve_with_v2_solver(instances, seed=seed)

    # Compute stats
    from collections import defaultdict
    instance_lookup = {inst["id"]: inst for inst in instances}

    driver_assignments = defaultdict(list)
    for a in assignments:
        driver_assignments[a["driver_id"]].append(a)

    block_counts = {"1er": 0, "2er": 0, "3er": 0}
    driver_hours = defaultdict(float)

    for driver_id, driver_assns in driver_assignments.items():
        by_day = defaultdict(list)
        for a in driver_assns:
            inst = instance_lookup.get(a["tour_instance_id"], {})
            day = a.get("day") or inst.get("day", 1)
            by_day[day].append(a)

            start = inst.get("start_ts")
            end = inst.get("end_ts")
            if start and end:
                start_min = start.hour * 60 + start.minute
                end_min = end.hour * 60 + end.minute
                if end_min < start_min:
                    end_min += 24 * 60
                driver_hours[driver_id] += (end_min - start_min) / 60

        for day_assns in by_day.values():
            count = len(day_assns)
            if count == 1:
                block_counts["1er"] += 1
            elif count == 2:
                block_counts["2er"] += 1
            elif count >= 3:
                block_counts["3er"] += 1

    fte_count = sum(1 for h in driver_hours.values() if h >= 40)
    pt_count = len(driver_hours) - fte_count

    stats = {
        "total_tours_input": len(instances),
        "total_tours_assigned": len(assignments),
        "total_drivers": len(driver_assignments),
        "fte_drivers": fte_count,
        "pt_drivers": pt_count,
        "block_counts": block_counts,
        "total_hours": round(sum(driver_hours.values()), 1),
    }

    return assignments, stats


def main(args: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Roster Solver"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default="forecast input.csv",
        help="Input forecast CSV path"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output assignments JSON path"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Random seed for determinism (default: 42)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )

    parsed = parser.parse_args(args)

    if not parsed.quiet:
        print(f"SOLVEREIGN Roster Solver (Deterministic)")
        print(f"=" * 40)
        print(f"Input:  {parsed.input}")
        print(f"Seed:   {parsed.seed}")

    # Parse input
    instances = parse_forecast_csv(parsed.input)
    if not instances:
        print("[ERROR] No valid tour instances found!")
        return 1

    if not parsed.quiet:
        print(f"Tours:  {len(instances)}")

    # Solve
    assignments, stats = solve_roster(instances, seed=parsed.seed)

    if not parsed.quiet:
        print(f"\n[OK] Solver completed")
        print(f"     Drivers: {stats['total_drivers']} ({stats['fte_drivers']} FTE, {stats['pt_drivers']} PT)")
        print(f"     Tours:   {stats['total_tours_assigned']}/{stats['total_tours_input']}")
        print(f"     Blocks:  {stats['block_counts']}")

    # Output
    if parsed.output:
        output = {
            "assignments": assignments,
            "stats": stats,
            "seed": parsed.seed,
        }
        with open(parsed.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)
        if not parsed.quiet:
            print(f"     Output:  {parsed.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
