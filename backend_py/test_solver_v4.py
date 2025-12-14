"""
TEST SOLVER V4
"""

import json
import sys
from pathlib import Path
from datetime import time

sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import solve_forecast_v4, ConfigV4

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


def main():
    forecast_path = Path(__file__).parent.parent / "forecast-test.json"
    
    if not forecast_path.exists():
        print(f"File not found: {forecast_path}")
        return 1
    
    print("Loading tours...")
    with open(forecast_path) as f:
        data = json.load(f)
    
    tours = [
        Tour(
            id=t["id"],
            day=DAY_MAP[t["day"]],
            start_time=parse_time(t["start"]),
            end_time=parse_time(t["end"]),
            location="DEFAULT",
            required_qualifications=[]
        )
        for t in data["tours"]
    ]
    
    print(f"Loaded {len(tours)} tours")
    
    # Solve
    config = ConfigV4(
        time_limit_phase1=180.0,  # 3 min for phase 1
        time_limit_phase2=60.0,
    )
    result = solve_forecast_v4(tours, config)
    
    print(f"\n{'='*60}")
    print("FINAL RESULT")
    print(f"{'='*60}")
    print(f"Status: {result.status}")
    print(f"Drivers: {result.kpi.get('drivers_fte', 0)} FTE + {result.kpi.get('drivers_pt', 0)} PT")
    print(f"FTE hours: {result.kpi.get('fte_hours_min', 0)}-{result.kpi.get('fte_hours_max', 0)}h")
    print(f"Blocks: {result.kpi.get('blocks_1er', 0)} 1er, {result.kpi.get('blocks_2er', 0)} 2er, {result.kpi.get('blocks_3er', 0)} 3er")
    print(f"Total time: {result.solve_times.get('total', 0):.2f}s")
    
    # Save result
    output_path = forecast_path.with_suffix('.v4_result.json')
    with open(output_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)
    print(f"\nResult saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
