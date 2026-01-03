#!/usr/bin/env python3
"""
FORECAST WEEKLY PLANNER CLI
===========================
CLI runner for forecast-only weekly planning.

Usage:
    python scripts/run_forecast_weekly.py --tours forecast.csv
    python scripts/run_forecast_weekly.py --tours forecast.json --output results/
"""

import argparse
import json
import sys
from datetime import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.models import Tour, Weekday
from src.services.forecast_weekly_solver import (
    ForecastConfig,
    solve_forecast_weekly
)
from src.services.weekly_block_builder import get_block_pool_stats, build_weekly_blocks


# =============================================================================
# DATA LOADERS
# =============================================================================

def load_tours_csv(filepath: str) -> list[Tour]:
    """Load tours from CSV file."""
    import csv
    tours = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            tour_id = row.get('id') or row.get('tour_id') or f"T{i+1:03d}"
            day_str = row.get('day') or row.get('weekday') or 'Mon'
            start_str = row.get('start_time') or row.get('start') or '08:00'
            end_str = row.get('end_time') or row.get('end') or '12:00'
            
            day_map = {
                'mon': Weekday.MONDAY, 'monday': Weekday.MONDAY,
                'tue': Weekday.TUESDAY, 'tuesday': Weekday.TUESDAY,
                'wed': Weekday.WEDNESDAY, 'wednesday': Weekday.WEDNESDAY,
                'thu': Weekday.THURSDAY, 'thursday': Weekday.THURSDAY,
                'fri': Weekday.FRIDAY, 'friday': Weekday.FRIDAY,
                'sat': Weekday.SATURDAY, 'saturday': Weekday.SATURDAY,
                'sun': Weekday.SUNDAY, 'sunday': Weekday.SUNDAY,
            }
            day = day_map.get(day_str.lower().strip(), Weekday.MONDAY)
            
            def parse_time(s):
                s = s.strip()
                if ':' in s:
                    parts = s.split(':')
                    return time(int(parts[0]), int(parts[1]))
                return time(int(s), 0)
            
            tours.append(Tour(
                id=tour_id.strip() if isinstance(tour_id, str) else tour_id,
                day=day,
                start_time=parse_time(start_str),
                end_time=parse_time(end_str)
            ))
    
    return tours


def load_tours_json(filepath: str) -> list[Tour]:
    """Load tours from JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    tours = []
    items = data if isinstance(data, list) else data.get('tours', [])
    
    day_map = {v.value: v for v in Weekday}
    # Add lowercase mappings
    day_map.update({
        'mon': Weekday.MONDAY, 'monday': Weekday.MONDAY,
        'tue': Weekday.TUESDAY, 'tuesday': Weekday.TUESDAY,
        'wed': Weekday.WEDNESDAY, 'wednesday': Weekday.WEDNESDAY,
        'thu': Weekday.THURSDAY, 'thursday': Weekday.THURSDAY,
        'fri': Weekday.FRIDAY, 'friday': Weekday.FRIDAY,
        'sat': Weekday.SATURDAY, 'saturday': Weekday.SATURDAY,
        'sun': Weekday.SUNDAY, 'sunday': Weekday.SUNDAY,
    })
    
    for i, item in enumerate(items):
        day_str = item.get('day', 'Mon')
        day = day_map.get(day_str, day_map.get(day_str.lower(), Weekday.MONDAY))
        
        start = item.get('start_time') or item.get('start') or '08:00'
        end = item.get('end_time') or item.get('end') or '12:00'
        
        def parse_time(s):
            if isinstance(s, str) and ':' in s:
                parts = s.split(':')
                return time(int(parts[0]), int(parts[1]))
            return time(8, 0)
        
        tours.append(Tour(
            id=item.get('id', f"T{i+1:03d}"),
            day=day,
            start_time=parse_time(start),
            end_time=parse_time(end)
        ))
    
    return tours


def load_tours(filepath: str) -> list[Tour]:
    """Load tours from CSV or JSON."""
    if filepath.endswith('.csv'):
        return load_tours_csv(filepath)
    else:
        return load_tours_json(filepath)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Forecast Weekly Planner")
    parser.add_argument("--tours", required=True, help="Path to tours file (CSV or JSON)")
    parser.add_argument("--output", default=".", help="Output directory")
    parser.add_argument("--min-hours", type=float, default=42.0, help="Min hours per driver")
    parser.add_argument("--max-hours", type=float, default=53.0, help="Max hours per driver")
    parser.add_argument("--time-limit", type=float, default=30.0, help="Time limit per phase")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    
    # Load tours
    print(f"\nLoading tours from {args.tours}...")
    tours = load_tours(args.tours)
    print(f"  Loaded {len(tours)} tours")
    
    total_hours = sum(t.duration_hours for t in tours)
    print(f"  Total hours: {total_hours:.1f}")
    
    # Configure solver
    config = ForecastConfig(
        min_hours_per_driver=args.min_hours,
        max_hours_per_driver=args.max_hours,
        time_limit_phase1=args.time_limit,
        time_limit_phase2=args.time_limit,
        time_limit_phase3=args.time_limit,
        seed=args.seed
    )
    
    # Solve
    print("\n" + "=" * 60)
    print("FORECAST WEEKLY PLANNER")
    print("=" * 60)
    
    result = solve_forecast_weekly(tours, config)
    
    # Output
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write weekly_plan.json
    with open(output_dir / "weekly_plan.json", 'w') as f:
        json.dump(result.to_weekly_plan_json(), f, indent=2)
    
    # Write kpi_summary.json
    with open(output_dir / "kpi_summary.json", 'w') as f:
        json.dump(result.to_kpi_summary_json(), f, indent=2)
    
    # Write block_pool_report.json
    with open(output_dir / "block_pool_report.json", 'w') as f:
        json.dump(result.block_pool_stats, f, indent=2)
    
    # Print summary
    print("\n" + "=" * 60)
    print("RESULT SUMMARY")
    print("=" * 60)
    kpi = result.kpi
    print(f"Status: {kpi['status']}")
    print(f"Range Feasible: {kpi.get('range_feasible', 'N/A')}")
    print(f"Drivers: {kpi.get('drivers_fte', 0)} FTE + {kpi.get('drivers_pt', 0)} PT")
    print(f"Coverage: {kpi['coverage_rate']*100:.0f}%")
    
    if kpi.get('fte_hours_min'):
        print(f"FTE Hours: min={kpi['fte_hours_min']:.1f}, max={kpi['fte_hours_max']:.1f}, avg={kpi['fte_hours_avg']:.1f}")
        print(f"FTE Fairness Gap: {kpi['fte_fairness_gap']:.1f}h")
    
    if kpi.get('pt_hours_total', 0) > 0:
        print(f"PT Hours Total: {kpi['pt_hours_total']:.1f}h")
    
    print(f"Blocks: {kpi['blocks_3er']}x3er, {kpi['blocks_2er']}x2er, {kpi['blocks_1er']}x1er")
    print(f"Solve Time: {kpi['solve_time_total']:.2f}s")
    
    if kpi.get('fallback_triggered'):
        print(f"\n[WARNING] Fallback triggered!")
        print(f"  Slack under: {kpi['slack_under_total']:.1f}h")
        print(f"  Slack over: {kpi['slack_over_total']:.1f}h")
    
    print(f"\n[OK] Artifacts written to: {output_dir}")
    print(f"  - weekly_plan.json")
    print(f"  - kpi_summary.json")
    print(f"  - block_pool_report.json")


if __name__ == "__main__":
    main()
