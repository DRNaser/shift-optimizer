"""
Stage0 Isolation: Disjoint 3er packing with block generation overrides.

Runs variants V0..V5, prints a sortable table and writes JSON report.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from datetime import time as dt_time
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ortools.sat.python import cp_model

from src.domain.models import Tour, Weekday
from src.services.smart_block_builder import BlockGenOverrides, generate_all_blocks


DAY_MAP = {
    "Montag": Weekday.MONDAY,
    "Dienstag": Weekday.TUESDAY,
    "Mittwoch": Weekday.WEDNESDAY,
    "Donnerstag": Weekday.THURSDAY,
    "Freitag": Weekday.FRIDAY,
    "Freitag ": Weekday.FRIDAY,  # Handle trailing space
    "Samstag": Weekday.SATURDAY,
    "Sonntag": Weekday.SUNDAY,
}


def parse_forecast_csv(csv_path: Path) -> list[Tour]:
    tours: list[Tour] = []
    tour_counter = 0
    current_day: Weekday | None = None

    with csv_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line == ";":
                continue

            parts = line.split(";")
            if len(parts) < 2:
                continue

            col1 = parts[0].strip()
            col2 = parts[1].strip()

            # Check if this is a day header
            day_match = None
            for day_name, weekday in DAY_MAP.items():
                if col1.startswith(day_name):
                    day_match = weekday
                    break

            if day_match:
                current_day = day_match
                continue

            # Parse time range and count
            if current_day and "-" in col1 and col2.isdigit():
                time_range = col1
                count = int(col2)
                start_str, end_str = time_range.split("-")
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))

                for _ in range(count):
                    tour_counter += 1
                    tours.append(
                        Tour(
                            id=f"T{tour_counter:04d}",
                            day=current_day,
                            start_time=dt_time(start_h, start_m),
                            end_time=dt_time(end_h, end_m),
                        )
                    )

    return tours


def greedy_pack(blocks_3er: list[Any]) -> list[int]:
    selected_indices: list[int] = []
    used_tours: set[str] = set()
    sorted_blocks = sorted(
        enumerate(blocks_3er),
        key=lambda item: (item[1].day.value, item[1].span_minutes, item[1].id),
    )
    for idx, block in sorted_blocks:
        tour_ids = [tour.id for tour in block.tours]
        if any(tid in used_tours for tid in tour_ids):
            continue
        selected_indices.append(idx)
        used_tours.update(tour_ids)
    return selected_indices


def solve_stage0_3er(blocks_3er: list[Any], time_limit: float) -> dict[str, Any]:
    model = cp_model.CpModel()
    block_vars = [model.NewBoolVar(f"b{i}") for i in range(len(blocks_3er))]

    tours_to_blocks: dict[str, list[int]] = {}
    for idx, block in enumerate(blocks_3er):
        for tour in block.tours:
            tours_to_blocks.setdefault(tour.id, []).append(idx)

    for block_ids in tours_to_blocks.values():
        model.Add(sum(block_vars[i] for i in block_ids) <= 1)

    model.Maximize(sum(block_vars))

    greedy_selection = greedy_pack(blocks_3er)
    for idx in greedy_selection:
        model.AddHint(block_vars[idx], 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0

    status = solver.Solve(model)
    greedy_obj = len(greedy_selection)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        obj = int(solver.ObjectiveValue())
        bound = int(solver.BestObjectiveBound())
    else:
        obj = greedy_obj
        bound = int(solver.BestObjectiveBound())

    gap = 0.0
    if bound > 0:
        gap = (bound - obj) / bound

    return {
        "status": solver.StatusName(status),
        "objective": obj,
        "best_bound": bound,
        "gap": gap,
        "greedy_obj": greedy_obj,
    }


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    values_sorted = sorted(values)
    idx = int(round((len(values_sorted) - 1) * pct))
    return values_sorted[idx]


def collect_deg3_stats(blocks_3er: list[Any], tours: list[Tour], hot_k: int) -> dict[str, Any]:
    deg3 = {tour.id: 0 for tour in tours}
    for block in blocks_3er:
        for tour in block.tours:
            deg3[tour.id] += 1

    deg3_vals = list(deg3.values())
    max_deg = max(deg3_vals) if deg3_vals else 0
    p95 = percentile(deg3_vals, 0.95)

    top_tours = sorted(deg3.items(), key=lambda item: (-item[1], item[0]))[:hot_k]
    hot_ids = {tour_id for tour_id, _ in top_tours}

    hot_block_hits = 0
    for block in blocks_3er:
        if any(tour.id in hot_ids for tour in block.tours):
            hot_block_hits += 1

    hot_block_share = hot_block_hits / len(blocks_3er) if blocks_3er else 0.0

    return {
        "deg3_max": max_deg,
        "deg3_p95": p95,
        "deg3_values": deg3_vals,
        "top_tours": top_tours,
        "hot_block_share": hot_block_share,
    }


def build_variants() -> list[dict[str, Any]]:
    return [
        {
            "id": "V0",
            "label": "baseline",
            "overrides": BlockGenOverrides(),
        },
        {
            "id": "V1",
            "label": "max_gap_75",
            "overrides": BlockGenOverrides(max_pause_regular=75),
        },
        {
            "id": "V2",
            "label": "max_gap_90",
            "overrides": BlockGenOverrides(max_pause_regular=90),
        },
        {
            "id": "V3",
            "label": "max_gap_90_span_16h",
            "overrides": BlockGenOverrides(max_pause_regular=90, max_daily_span_hours=16.0),
        },
        {
            "id": "V4",
            "label": "max_gap_90_span_16h_split_960",
            "overrides": BlockGenOverrides(
                max_pause_regular=90,
                max_daily_span_hours=16.0,
                max_spread_split_minutes=960,
            ),
        },
        {
            "id": "V5",
            "label": "max_gap_90_span_16h_split_960_gap300_420",
            "overrides": BlockGenOverrides(
                max_pause_regular=90,
                max_daily_span_hours=16.0,
                max_spread_split_minutes=960,
                split_pause_min=300,
                split_pause_max=420,
            ),
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=Path(__file__).parent.parent.parent / "forecast input.csv")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent.parent / "artifacts" / "stage0_isolation")
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--hot-k", type=int, default=10)
    args = parser.parse_args()

    tours = parse_forecast_csv(args.csv)
    if not tours:
        raise SystemExit(f"No tours parsed from {args.csv}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "input_csv": str(args.csv),
        "tour_count": len(tours),
        "variants": [],
    }

    rows = []
    for variant in build_variants():
        overrides = variant["overrides"]
        print(f"\n[{variant['id']}] Generating blocks ({variant['label']})...", flush=True)
        blocks = generate_all_blocks(tours, block_gen_overrides=overrides)
        blocks_3er = [b for b in blocks if len(b.tours) == 3]
        print(f"[{variant['id']}] 3er candidates: {len(blocks_3er):,}", flush=True)

        deg_stats = collect_deg3_stats(blocks_3er, tours, args.hot_k)
        print(f"[{variant['id']}] Solving Stage0 (time_limit={args.time_limit}s)...", flush=True)
        stage0 = solve_stage0_3er(blocks_3er, args.time_limit)

        unique_tours_in_3er = sum(1 for degree in deg_stats["deg3_values"] if degree > 0)
        row = {
            "variant": variant["id"],
            "label": variant["label"],
            "raw_3er": len(blocks_3er),
            "unique_tours_in_3er": unique_tours_in_3er,
            "deg3_max": deg_stats["deg3_max"],
            "deg3_p95": deg_stats["deg3_p95"],
            "hot_block_share": deg_stats["hot_block_share"],
            "stage0_obj": stage0["objective"],
            "best_bound": stage0["best_bound"],
            "gap": stage0["gap"],
        }

        report["variants"].append(
            {
                **row,
                "status": stage0["status"],
                "greedy_obj": stage0["greedy_obj"],
                "overrides": asdict(overrides),
                "top_tours": deg_stats["top_tours"],
            }
        )
        rows.append(row)

    rows_sorted = sorted(rows, key=lambda r: (r["stage0_obj"], r["raw_3er"]), reverse=True)

    headers = [
        "variant",
        "label",
        "raw_3er",
        "unique_tours_in_3er",
        "deg3_max",
        "deg3_p95",
        "hot_block_share",
        "stage0_obj",
        "best_bound",
        "gap",
    ]

    print("\nStage0 Isolation Summary")
    print(" | ".join(headers))
    print("-" * 120)
    for row in rows_sorted:
        print(
            f"{row['variant']} | {row['label']} | {row['raw_3er']} | {row['unique_tours_in_3er']} | "
            f"{row['deg3_max']} | {row['deg3_p95']} | "
            f"{row['hot_block_share']:.3f} | {row['stage0_obj']} | {row['best_bound']} | {row['gap']:.3f}"
        )

    output_path = args.output_dir / "stage0_isolation_report.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {output_path}")


if __name__ == "__main__":
    main()
