"""
TEST SMART BLOCK BUILDER
========================
Tests the P1 smart block builder on real forecast.
"""

import json
import sys
from pathlib import Path
from datetime import time

sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from src.services.smart_block_builder import build_weekly_blocks_smart

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
    
    # Build with smart capping
    blocks, stats = build_weekly_blocks_smart(
        tours,
        k_per_tour=30,
        global_top_n=20_000,
    )
    
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Total blocks: {stats['total_blocks']:,}")
    print(f"  1er: {stats['blocks_1er']:,}")
    print(f"  2er: {stats['blocks_2er']:,}")
    print(f"  3er: {stats['blocks_3er']:,}")
    print(f"\nDegree stats:")
    print(f"  Min: {stats['min_degree']}")
    print(f"  Max: {stats['max_degree']}")
    print(f"  Avg: {stats['avg_degree']}")
    print(f"\nBuild time: {stats['build_time_seconds']:.2f}s")
    
    # Estimate solver complexity
    n_drivers = 150
    n_vars = stats['total_blocks'] * n_drivers
    print(f"\nCP-SAT variables estimate: {n_vars:,}")
    
    if n_vars < 5_000_000:
        print("[OK] Variable count is manageable")
    else:
        print("[WARNING] Still high, may need P2 refactoring")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
