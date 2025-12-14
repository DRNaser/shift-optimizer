"""
BLOCK BUILDER PERFORMANCE ANALYSIS
===================================
Diagnose why the solver hung with real forecast data.
"""

import json
import sys
import time
from pathlib import Path
from datetime import time as dt_time
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from src.domain.constraints import HARD_CONSTRAINTS

DAY_MAP = {
    "Mon": Weekday.MONDAY,
    "Tue": Weekday.TUESDAY,
    "Wed": Weekday.WEDNESDAY,
    "Thu": Weekday.THURSDAY,
    "Fri": Weekday.FRIDAY,
    "Sat": Weekday.SATURDAY,
    "Sun": Weekday.SUNDAY,
}


def parse_time(t: str) -> dt_time:
    h, m = t.split(":")
    return dt_time(int(h), int(m))


def load_forecast_json(path: Path) -> list[Tour]:
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


def analyze_adjacency(tours: list[Tour], day: Weekday) -> dict:
    """Analyze adjacency for a single day."""
    day_tours = [t for t in tours if t.day == day]
    day_tours.sort(key=lambda t: t.start_time)
    
    n = len(day_tours)
    if n == 0:
        return {"tours": 0}
    
    # Count how many tours each tour can follow
    MAX_PAUSE = 120  # 2 hours
    MIN_PAUSE = 0
    
    followers_count = []
    total_pairs = 0
    
    for i, t1 in enumerate(day_tours):
        t1_end = t1.end_time.hour * 60 + t1.end_time.minute
        count = 0
        
        for j, t2 in enumerate(day_tours):
            if i == j:
                continue
            t2_start = t2.start_time.hour * 60 + t2.start_time.minute
            gap = t2_start - t1_end
            
            if MIN_PAUSE <= gap <= MAX_PAUSE:
                count += 1
                total_pairs += 1
        
        followers_count.append(count)
    
    avg_followers = sum(followers_count) / len(followers_count) if followers_count else 0
    max_followers = max(followers_count) if followers_count else 0
    
    # Estimate 3er combinations: sum over all tours of (followers * their followers)
    # This is O(n * k^2) where k = average followers
    estimated_3er = 0
    for i, t1 in enumerate(day_tours):
        t1_end = t1.end_time.hour * 60 + t1.end_time.minute
        
        for j, t2 in enumerate(day_tours):
            if i == j:
                continue
            t2_start = t2.start_time.hour * 60 + t2.start_time.minute
            gap = t2_start - t1_end
            
            if MIN_PAUSE <= gap <= MAX_PAUSE:
                # t2 can follow t1, count t2's followers
                t2_end = t2.end_time.hour * 60 + t2.end_time.minute
                
                for k, t3 in enumerate(day_tours):
                    if k in (i, j):
                        continue
                    t3_start = t3.start_time.hour * 60 + t3.start_time.minute
                    gap2 = t3_start - t2_end
                    
                    if MIN_PAUSE <= gap2 <= MAX_PAUSE:
                        estimated_3er += 1
    
    return {
        "tours": n,
        "avg_followers": round(avg_followers, 1),
        "max_followers": max_followers,
        "valid_pairs_2er": total_pairs // 2,  # Each pair counted twice
        "estimated_3er": estimated_3er,
        "estimated_total": n + (total_pairs // 2) + estimated_3er,
    }


def main():
    forecast_path = Path(__file__).parent.parent / "forecast-test.json"
    
    if not forecast_path.exists():
        print(f"File not found: {forecast_path}")
        return 1
    
    print("Loading tours...")
    tours = load_forecast_json(forecast_path)
    print(f"Total tours: {len(tours)}")
    
    print(f"\n{'='*70}")
    print("ADJACENCY ANALYSIS")
    print(f"{'='*70}")
    print(f"MAX_PAUSE between tours: 120 minutes")
    print(f"MAX_DAILY_SPAN: {HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS}h")
    
    total_1er = 0
    total_2er = 0
    total_3er = 0
    
    for day in [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, 
                Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]:
        print(f"\nAnalyzing {day.value}...")
        start = time.time()
        stats = analyze_adjacency(tours, day)
        elapsed = time.time() - start
        
        print(f"  Tours: {stats['tours']}")
        print(f"  Avg followers per tour: {stats['avg_followers']}")
        print(f"  Max followers: {stats['max_followers']}")
        print(f"  Valid 2er pairs: {stats['valid_pairs_2er']:,}")
        print(f"  Valid 3er combinations: {stats['estimated_3er']:,}")
        print(f"  Total blocks: {stats['estimated_total']:,}")
        print(f"  Analysis time: {elapsed:.2f}s")
        
        total_1er += stats['tours']
        total_2er += stats['valid_pairs_2er']
        total_3er += stats['estimated_3er']
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total 1er blocks: {total_1er:,}")
    print(f"Total 2er blocks: {total_2er:,}")
    print(f"Total 3er blocks: {total_3er:,}")
    print(f"GRAND TOTAL: {total_1er + total_2er + total_3er:,} blocks")
    
    # Estimate solver complexity
    drivers = 150
    block_vars = (total_1er + total_2er + total_3er) * drivers
    print(f"\nCP-SAT Variables (blocks × drivers): {block_vars:,}")
    
    if block_vars > 10_000_000:
        print("[CRITICAL] Too many variables! Need more aggressive filtering.")
    elif block_vars > 1_000_000:
        print("[WARNING] High variable count. May be slow.")
    else:
        print("[OK] Variable count manageable.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
