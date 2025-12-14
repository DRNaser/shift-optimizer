"""
REAL FORECAST CONVERTER
=======================
Converts tab-separated forecast format (with counts) to JSON format for the solver.

Input format:
    Montag    Anzahl
    04:45-09:15    15
    ...

Output format:
    {"tours": [{"id": "T001", "day": "Mon", "start": "04:45", "end": "09:15"}, ...]}
"""

import json
import re
from pathlib import Path
from datetime import datetime


# Day name mapping (German -> solver format)
DAY_MAP = {
    "montag": "Mon",
    "dienstag": "Tue",
    "mittwoch": "Wed",
    "donnerstag": "Thu",
    "freitag": "Fri",
    "samstag": "Sat",
    "sonntag": "Sun",
}


def parse_forecast_file(filepath: str | Path) -> dict:
    """
    Parse the real forecast file and expand to individual tours.
    
    Args:
        filepath: Path to the forecast text file
        
    Returns:
        Dictionary with tours list and statistics
    """
    filepath = Path(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tours = []
    stats = {
        "total_tours": 0,
        "total_hours": 0.0,
        "tours_by_day": {},
        "time_slots_by_day": {},
    }
    
    current_day = None
    tour_counter = 1
    
    # Time pattern: HH:MM-HH:MM
    time_pattern = re.compile(r'^(\d{2}:\d{2})-(\d{2}:\d{2})\s+(\d+)$')
    
    for line in content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Check if this is a day header
        first_word = line.split()[0].lower().rstrip('\t')
        if first_word in DAY_MAP:
            current_day = DAY_MAP[first_word]
            stats["tours_by_day"][current_day] = 0
            stats["time_slots_by_day"][current_day] = 0
            continue
        
        # Try to parse time slot
        # Handle tab separation
        parts = line.split('\t')
        if len(parts) >= 2:
            time_part = parts[0].strip()
            count_part = parts[-1].strip()
            
            # Parse time range
            time_match = re.match(r'(\d{2}:\d{2})-(\d{2}:\d{2})', time_part)
            if time_match and count_part.isdigit():
                start_time = time_match.group(1)
                end_time = time_match.group(2)
                count = int(count_part)
                
                if current_day is None:
                    continue
                
                # Calculate duration
                start_h, start_m = map(int, start_time.split(':'))
                end_h, end_m = map(int, end_time.split(':'))
                duration_hours = (end_h * 60 + end_m - start_h * 60 - start_m) / 60
                
                stats["time_slots_by_day"][current_day] = stats.get("time_slots_by_day", {}).get(current_day, 0) + 1
                
                # Expand count to individual tours
                for i in range(count):
                    tour_id = f"T{tour_counter:04d}"
                    tours.append({
                        "id": tour_id,
                        "day": current_day,
                        "start": start_time,
                        "end": end_time,
                    })
                    tour_counter += 1
                    stats["total_tours"] += 1
                    stats["total_hours"] += duration_hours
                    stats["tours_by_day"][current_day] = stats["tours_by_day"].get(current_day, 0) + 1
    
    return {
        "description": f"Real forecast converted from {filepath.name}",
        "tours": tours,
        "stats": stats,
    }


def calculate_driver_requirements(total_hours: float, min_per_driver: float = 42.0, max_per_driver: float = 53.0) -> dict:
    """Calculate FTE driver requirements."""
    import math
    
    k_min = math.ceil(total_hours / max_per_driver)
    k_max = math.floor(total_hours / min_per_driver)
    
    return {
        "k_min": k_min,
        "k_max": k_max,
        "is_feasible": k_min <= k_max,
        "total_hours": total_hours,
        "hours_per_driver_if_k_min": round(total_hours / k_min, 2) if k_min > 0 else 0,
        "hours_per_driver_if_k_max": round(total_hours / k_max, 2) if k_max > 0 else 0,
    }


def analyze_complexity(stats: dict) -> dict:
    """Analyze solver complexity for this forecast."""
    tours_by_day = stats["tours_by_day"]
    
    # Block generation complexity per day
    complexity = {}
    total_blocks_estimate = 0
    total_3er_combinations = 0
    
    for day, n in tours_by_day.items():
        # 1er blocks: O(n)
        blocks_1er = n
        
        # 2er blocks: O(n^2) in worst case, but filtering reduces this
        blocks_2er_max = n * (n - 1) // 2
        
        # 3er blocks: O(n^3) in worst case
        blocks_3er_max = n * (n - 1) * (n - 2) // 6
        
        day_total = blocks_1er + blocks_2er_max + blocks_3er_max
        total_blocks_estimate += day_total
        total_3er_combinations += blocks_3er_max
        
        complexity[day] = {
            "tours": n,
            "blocks_1er": blocks_1er,
            "blocks_2er_max": blocks_2er_max,
            "blocks_3er_max": blocks_3er_max,
            "total_max": day_total,
        }
    
    return {
        "per_day": complexity,
        "total_blocks_max": total_blocks_estimate,
        "total_3er_max": total_3er_combinations,
        "feasibility_warning": total_blocks_estimate > 100000,
    }


def main():
    import sys
    
    if len(sys.argv) < 2:
        # Default to forecast-test.txt in current directory
        input_file = Path(__file__).parent / "forecast-test.txt"
        if not input_file.exists():
            print("Usage: python convert_real_forecast.py <forecast_file.txt>")
            sys.exit(1)
    else:
        input_file = Path(sys.argv[1])
    
    print(f"\n{'='*70}")
    print(f"REAL FORECAST CONVERTER")
    print(f"{'='*70}")
    print(f"\nInput file: {input_file}")
    
    # Parse and convert
    result = parse_forecast_file(input_file)
    stats = result["stats"]
    
    print(f"\n--- STATISTICS ---")
    print(f"Total tours: {stats['total_tours']}")
    print(f"Total hours: {stats['total_hours']:.1f}h")
    print(f"\nTours by day:")
    for day, count in stats["tours_by_day"].items():
        print(f"  {day}: {count} tours")
    
    # Driver requirements
    print(f"\n--- DRIVER REQUIREMENTS ---")
    reqs = calculate_driver_requirements(stats["total_hours"])
    print(f"k_min (at 53h): {reqs['k_min']} drivers")
    print(f"k_max (at 42h): {reqs['k_max']} drivers")
    print(f"Feasible: {reqs['is_feasible']}")
    if reqs['is_feasible']:
        print(f"Driver range: {reqs['k_min']}-{reqs['k_max']} FTE")
    
    # Complexity analysis
    print(f"\n--- COMPLEXITY ANALYSIS ---")
    complexity = analyze_complexity(stats)
    print(f"Total blocks (worst case): {complexity['total_blocks_max']:,}")
    print(f"Total 3er combinations: {complexity['total_3er_max']:,}")
    
    if complexity["feasibility_warning"]:
        print(f"\n[WARNING] High complexity! Consider optimizations:")
        print(f"  - Reduce block search window")
        print(f"  - Pre-filter non-combinable tours")
        print(f"  - Use hierarchical solving")
    
    print(f"\nPer day:")
    for day, data in complexity["per_day"].items():
        print(f"  {day}: {data['tours']} tours -> max {data['total_max']:,} blocks")
    
    # Save output
    output_file = input_file.with_suffix('.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "description": result["description"],
            "tours": result["tours"],
        }, f, indent=2)
    
    print(f"\n--- OUTPUT ---")
    print(f"JSON saved to: {output_file}")
    print(f"Tours exported: {len(result['tours'])}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
