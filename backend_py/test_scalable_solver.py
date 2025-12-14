"""
TEST SCALABLE SOLVER
====================
Tests the v3 solver with real forecast data.
"""

import json
import sys
from pathlib import Path
from datetime import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from src.services.forecast_weekly_solver_v3 import (
    ForecastWeeklySolverV3,
    ForecastConfigV3,
    solve_forecast_v3
)

# Weekday mapping
DAY_MAP = {
    "Mon": Weekday.MONDAY,
    "Tue": Weekday.TUESDAY,
    "Wed": Weekday.WEDNESDAY,
    "Thu": Weekday.THURSDAY,
    "Fri": Weekday.FRIDAY,
    "Sat": Weekday.SATURDAY,
    "Sun": Weekday.SUNDAY,
}


def parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))


def load_forecast_json(path: Path) -> list[Tour]:
    """Load tours from JSON file."""
    with open(path) as f:
        data = json.load(f)
    
    tours = []
    for t in data["tours"]:
        tours.append(Tour(
            id=t["id"],
            day=DAY_MAP[t["day"]],
            start_time=parse_time(t["start"]),
            end_time=parse_time(t["end"]),
            location="DEFAULT",
            required_qualifications=[]
        ))
    
    return tours


def main():
    # Find forecast file
    if len(sys.argv) > 1:
        forecast_path = Path(sys.argv[1])
    else:
        # Default to converted forecast
        forecast_path = Path(__file__).parent.parent / "forecast-test.json"
    
    if not forecast_path.exists():
        print(f"Forecast file not found: {forecast_path}")
        print("Run convert_real_forecast.py first to create the JSON file.")
        return 1
    
    print(f"\n{'='*70}")
    print(f"SCALABLE SOLVER TEST")
    print(f"{'='*70}")
    print(f"Forecast file: {forecast_path}")
    
    # Load tours
    tours = load_forecast_json(forecast_path)
    print(f"Tours loaded: {len(tours)}")
    
    # Configure for performance
    config = ForecastConfigV3(
        time_limit_per_phase=120.0,  # 2 minutes per phase
        num_workers=8,
        pt_reserve_count=10,  # More PT for large problems
        max_blocks_per_day=30_000,
    )
    
    # Solve
    result = solve_forecast_v3(tours, config)
    
    # Print results
    print(f"\n{'='*70}")
    print(f"RESULTS")
    print(f"{'='*70}")
    
    kpi = result.kpi
    print(f"Status: {kpi.get('status', result.status)}")
    print(f"Drivers: {kpi.get('drivers_fte', 0)} FTE + {kpi.get('drivers_pt', 0)} PT")
    print(f"Total hours: {kpi.get('total_hours', 0):.1f}h")
    
    if kpi.get('drivers_fte', 0) > 0:
        print(f"FTE hours: min={kpi.get('fte_hours_min', 0):.1f}h, max={kpi.get('fte_hours_max', 0):.1f}h, avg={kpi.get('fte_hours_avg', 0):.1f}h")
    
    print(f"PT hours: {kpi.get('pt_hours_total', 0):.1f}h")
    print(f"Blocks: 1er={kpi.get('blocks_1er', 0)}, 2er={kpi.get('blocks_2er', 0)}, 3er={kpi.get('blocks_3er', 0)}")
    
    print(f"\nSolve times:")
    for phase, t in result.solve_times.items():
        print(f"  {phase}: {t:.2f}s")
    print(f"  TOTAL: {sum(result.solve_times.values()):.2f}s")
    
    # Save result
    output_path = forecast_path.with_suffix('.result.json')
    with open(output_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)
    print(f"\nResult saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
