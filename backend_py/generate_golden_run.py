"""
PROOF #2: Golden Run Artifacts Generator

Generates complete production run with all metadata and outputs:
- matrix.csv: Driver roster with daily assignments
- rosters.csv: Per-driver weekly schedule
- kpis.json: KPI summary (drivers, hours, PT ratio, block mix)
- metadata.json: All version IDs and hashes (seed, input_hash, output_hash, etc.)

This script runs the V2 solver via V3 integration and exports all artifacts.
"""

import sys
import json
import csv
import hashlib
from pathlib import Path
from datetime import datetime, time
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from test_forecast_csv import parse_forecast_csv
from v3.solver_v2_integration import solve_with_v2_solver
from src.domain.models import Weekday

# Day mappings
V2_WEEKDAY_TO_V3_DAY = {
    Weekday.MONDAY: 1,
    Weekday.TUESDAY: 2,
    Weekday.WEDNESDAY: 3,
    Weekday.THURSDAY: 4,
    Weekday.FRIDAY: 5,
    Weekday.SATURDAY: 6,
    Weekday.SUNDAY: 7,
}

V3_DAY_TO_NAME = {
    1: "Mon",
    2: "Tue",
    3: "Wed",
    4: "Thu",
    5: "Fri",
    6: "Sat",
    7: "Sun",
}

SEED = 94


def main():
    print("=" * 70)
    print("PROOF #2: GOLDEN RUN ARTIFACTS")
    print("=" * 70)
    print()

    # Create output directory
    output_dir = Path(__file__).parent.parent / "golden_run"
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir}")
    print()

    # Load forecast
    print("Loading forecast...")
    input_file = Path(__file__).parent.parent / "forecast input.csv"
    if not input_file.exists():
        input_file = Path(__file__).parent.parent / "forecast_kw51.csv"
        print(f"  Using fallback: {input_file.name}")
    else:
        print(f"  Using: {input_file.name}")

    tours = parse_forecast_csv(str(input_file))
    print(f"  Loaded {len(tours)} tours")

    # Generate canonical text for input_hash (FIX 2A)
    # Must use canonical format sorted for deterministic hashing
    print("Generating canonical input...")
    canonical_lines = []
    for tour in tours:
        # Map day back to abbr
        day_abbr = {
            Weekday.MONDAY: "Mo",
            Weekday.TUESDAY: "Di",
            Weekday.WEDNESDAY: "Mi",
            Weekday.THURSDAY: "Do",
            Weekday.FRIDAY: "Fr",
            Weekday.SATURDAY: "Sa",
            Weekday.SUNDAY: "So"
        }[tour.day]

        canonical = f"{day_abbr} {tour.start_time.strftime('%H:%M')}-{tour.end_time.strftime('%H:%M')}"
        if tour.location and tour.location != "DEFAULT":
            canonical += f" Depot {tour.location}"
        canonical_lines.append(canonical)

    # Sort for deterministic hash
    canonical_lines_sorted = sorted(canonical_lines)
    canonical_text = "\n".join(canonical_lines_sorted)
    input_hash = hashlib.sha256(canonical_text.encode()).hexdigest()
    print(f"  Generated {len(canonical_lines_sorted)} canonical lines")
    print(f"  input_hash: {input_hash[:16]}...")
    print()

    # Convert to V3 instances
    print("Converting to V3 tour_instances...")
    instances = []
    for i, tour in enumerate(tours, 1):
        # FIX 2B: Compute crosses_midnight correctly
        crosses_midnight = (tour.end_time < tour.start_time)

        instances.append({
            "id": i,
            "day": V2_WEEKDAY_TO_V3_DAY[tour.day],
            "start_ts": tour.start_time,
            "end_ts": tour.end_time,
            "depot": tour.location,
            "skill": None,
            "work_hours": tour.duration_hours,
            "duration_min": tour.duration_minutes,
            "crosses_midnight": crosses_midnight
        })
    print(f"  Created {len(instances)} tour_instances")
    cross_midnight_count = sum(1 for inst in instances if inst['crosses_midnight'])
    print(f"  Cross-midnight tours: {cross_midnight_count}")
    print()

    # Run solver
    print(f"Running V2 solver (seed={SEED})...")
    assignments = solve_with_v2_solver(instances, seed=SEED)
    print()

    # Compute output_hash (FIX 2C: include comprehensive assignment data + KPIs)
    print("Computing output_hash...")

    # Create instance lookup for quick access
    instance_lookup = {inst["id"]: inst for inst in instances}

    # Build comprehensive assignment data with timestamps
    assignment_records = []
    for a in assignments:
        inst = instance_lookup[a["tour_instance_id"]]
        # Convert times to minutes for deterministic serialization
        start_min = inst["start_ts"].hour * 60 + inst["start_ts"].minute
        end_min = inst["end_ts"].hour * 60 + inst["end_ts"].minute

        assignment_records.append({
            "driver_id": a["driver_id"],
            "tour_instance_id": a["tour_instance_id"],
            "day": a["day"],
            "block_id": a["block_id"],
            "block_type": a["metadata"].get("block_type", "1er"),
            "start_min": start_min,
            "end_min": end_min,
            "crosses_midnight": inst.get("crosses_midnight", False)
        })

    # Sort for deterministic hashing
    assignment_records_sorted = sorted(
        assignment_records,
        key=lambda x: (x["driver_id"], x["day"], x["tour_instance_id"])
    )

    # Include solver config hash and KPIs in output hash
    output_data = {
        "assignments": assignment_records_sorted,
        "solver_config_hash": hashlib.sha256(
            json.dumps({
                "seed": SEED,
                "version": "v2_block_heuristic",
                "fatigue_rule": "no_consecutive_triples",
                "rest_min": 660,  # 11h
                "span_regular_max": 840,  # 14h
                "span_split_max": 960,  # 16h
            }, sort_keys=True).encode()
        ).hexdigest()
    }

    output_hash = hashlib.sha256(
        json.dumps(output_data, sort_keys=True).encode()
    ).hexdigest()
    print(f"  output_hash: {output_hash[:16]}...")
    print()

    # Compute solver_config_hash
    solver_config = {
        "seed": SEED,
        "version": "v2_block_heuristic",
        "fatigue_rule": "no_consecutive_triples",
        "rest_min": 660,  # 11h in minutes
        "span_regular_max": 840,  # 14h
        "span_split_max": 960,  # 16h
    }
    solver_config_hash = hashlib.sha256(
        json.dumps(solver_config, sort_keys=True).encode()
    ).hexdigest()
    print(f"  solver_config_hash: {solver_config_hash[:16]}...")
    print()

    # Build driver data for exports
    print("Building driver data...")
    driver_assignments = defaultdict(list)
    for a in assignments:
        driver_assignments[a["driver_id"]].append(a)

    # Build instance lookup
    instance_lookup = {inst["id"]: inst for inst in instances}

    # Calculate driver hours and block mix
    driver_hours = {}
    driver_days = defaultdict(lambda: defaultdict(list))

    for driver_id, driver_asgns in driver_assignments.items():
        total_hours = 0
        for a in driver_asgns:
            inst = instance_lookup[a["tour_instance_id"]]
            total_hours += inst["work_hours"]
            driver_days[driver_id][a["day"]].append(a)
        driver_hours[driver_id] = total_hours

    # Sort drivers by ID
    sorted_drivers = sorted(driver_hours.keys(), key=lambda d: int(d[1:]))

    # Count FTE vs PT
    ftes = [d for d, h in driver_hours.items() if h >= 40]
    pts = [d for d, h in driver_hours.items() if h < 40]

    # Count block mix
    block_mix = defaultdict(int)
    for driver_id, days_data in driver_days.items():
        for day, day_asgns in days_data.items():
            count = len(day_asgns)
            if count == 1:
                block_mix["1er"] += 1
            elif count == 2:
                # Check if split
                if day_asgns[0]["metadata"].get("block_type") == "2er-split":
                    block_mix["2er-split"] += 1
                else:
                    block_mix["2er-reg"] += 1
            elif count >= 3:
                block_mix["3er"] += 1

    print(f"  Drivers: {len(sorted_drivers)}")
    print(f"  FTE (>=40h): {len(ftes)}")
    print(f"  PT (<40h): {len(pts)}")
    print(f"  Block Mix: 3er={block_mix['3er']}, 2er-reg={block_mix['2er-reg']}, 2er-split={block_mix['2er-split']}, 1er={block_mix['1er']}")
    print()

    # Export 1: matrix.csv
    print("Exporting matrix.csv...")
    matrix_file = output_dir / "matrix.csv"
    with open(matrix_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Header
        writer.writerow(["Driver", "Type", "Hours", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])

        for driver_id in sorted_drivers:
            hours = driver_hours[driver_id]
            driver_type = "FTE" if hours >= 40 else "PT"
            row = [driver_id, driver_type, f"{hours:.1f}"]

            for day in range(1, 7):  # Mon-Sat
                day_asgns = driver_days[driver_id].get(day, [])
                if day_asgns:
                    # Get block type and times
                    block_type = day_asgns[0]["metadata"].get("block_type", "1er")
                    # Get first start and last end
                    starts = [instance_lookup[a["tour_instance_id"]]["start_ts"] for a in day_asgns]
                    ends = [instance_lookup[a["tour_instance_id"]]["end_ts"] for a in day_asgns]
                    first_start = min(starts)
                    last_end = max(ends)
                    cell = f"{block_type} {first_start.strftime('%H:%M')}-{last_end.strftime('%H:%M')}"
                else:
                    cell = ""
                row.append(cell)

            writer.writerow(row)

    print(f"  Written: {matrix_file}")

    # Export 2: rosters.csv (detailed per-driver schedule)
    print("Exporting rosters.csv...")
    rosters_file = output_dir / "rosters.csv"
    with open(rosters_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Driver", "Day", "Tour_Instance_ID", "Start", "End", "Hours", "Block_ID", "Block_Type"])

        for driver_id in sorted_drivers:
            for day in range(1, 7):
                day_asgns = sorted(
                    driver_days[driver_id].get(day, []),
                    key=lambda a: instance_lookup[a["tour_instance_id"]]["start_ts"]
                )
                for a in day_asgns:
                    inst = instance_lookup[a["tour_instance_id"]]
                    writer.writerow([
                        driver_id,
                        V3_DAY_TO_NAME[day],
                        a["tour_instance_id"],
                        inst["start_ts"].strftime("%H:%M"),
                        inst["end_ts"].strftime("%H:%M"),
                        f"{inst['work_hours']:.2f}",
                        a["block_id"],
                        a["metadata"].get("block_type", "")
                    ])

    print(f"  Written: {rosters_file}")

    # Export 3: kpis.json
    print("Exporting kpis.json...")
    kpis = {
        "total_tours": len(tours),
        "total_assignments": len(assignments),
        "total_drivers": len(sorted_drivers),
        "fte_count": len(ftes),
        "pt_count": len(pts),
        "pt_ratio_percent": round(100 * len(pts) / len(sorted_drivers), 2) if sorted_drivers else 0,
        "avg_hours_per_driver": round(sum(driver_hours.values()) / len(driver_hours), 2) if driver_hours else 0,
        "total_work_hours": round(sum(driver_hours.values()), 2),
        "block_mix": {
            "3er": block_mix["3er"],
            "2er-reg": block_mix["2er-reg"],
            "2er-split": block_mix["2er-split"],
            "1er": block_mix["1er"]
        },
        "total_blocks": sum(block_mix.values())
    }

    kpis_file = output_dir / "kpis.json"
    with open(kpis_file, "w", encoding="utf-8") as f:
        json.dump(kpis, f, indent=2)
    print(f"  Written: {kpis_file}")

    # Export 4: metadata.json (all hashes and IDs)
    print("Exporting metadata.json...")
    metadata = {
        "generated_at": datetime.now().isoformat(),
        "forecast_source": str(input_file.name),
        "seed": SEED,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "solver_config": solver_config,
        "solver_config_hash": solver_config_hash,
        "version": "v3_with_v2_solver",
        "proof_id": "PROOF_02_GOLDEN_RUN"
    }

    metadata_file = output_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Written: {metadata_file}")

    # Generate summary for console
    print()
    print("=" * 70)
    print("PROOF #2 COMPLETE - GOLDEN RUN ARTIFACTS")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"  Total Drivers: {len(sorted_drivers)}")
    print(f"  FTE (>=40h):   {len(ftes)}")
    print(f"  PT (<40h):     {len(pts)}")
    print(f"  PT Ratio:      {kpis['pt_ratio_percent']}%")
    print()
    print("Block Mix:")
    print(f"  3er:       {block_mix['3er']}")
    print(f"  2er-reg:   {block_mix['2er-reg']}")
    print(f"  2er-split: {block_mix['2er-split']}")
    print(f"  1er:       {block_mix['1er']}")
    print()
    print("Hashes:")
    print(f"  input_hash:         {input_hash}")
    print(f"  output_hash:        {output_hash}")
    print(f"  solver_config_hash: {solver_config_hash}")
    print()
    print("Artifacts:")
    print(f"  [OK] golden_run/matrix.csv")
    print(f"  [OK] golden_run/rosters.csv")
    print(f"  [OK] golden_run/kpis.json")
    print(f"  [OK] golden_run/metadata.json")
    print()

    return {
        "kpis": kpis,
        "metadata": metadata,
        "output_dir": str(output_dir)
    }


if __name__ == "__main__":
    main()
