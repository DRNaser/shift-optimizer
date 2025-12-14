"""
Test Solver with Real Data
Parse the tour forecast and run optimizer
"""

import json
import requests
from datetime import date, time

from src.domain.models import Tour, Weekday
from src.services.block_builder import BlockBuilder

# Parse the real tour data
TOUR_DATA = """
MONDAY
04:45-09:15	15
05:00-09:30	10
05:15-09:45	15
05:30-10:00	10
05:45-10:15	8
06:00-10:30	3
06:15-10:45	2
06:30-11:00	2
06:45-11:15	2
07:00-11:30	1
07:15-11:45	2
07:30-12:00	3
07:45-12:15	5
08:00-12:30	5
08:15-12:45	8
08:30-13:00	5
08:45-13:15	5
09:00-13:30	4
09:15-13:45	5
09:30-14:00	2
09:45-14:15	5
10:00-14:30	3
10:15-14:45	3
10:30-15:00	3
10:45-15:15	5
11:00-15:30	5
11:15-15:45	5
11:30-16:00	3
11:45-16:15	2
12:00-16:30	4
12:15-16:45	3
12:30-17:00	2
12:45-17:15	2
13:00-17:30	3
13:15-17:45	2
13:30-18:00	3
13:45-18:15	2
14:00-18:30	5
14:15-18:45	8
14:30-19:00	5
14:45-19:15	5
15:00-19:30	5
15:15-19:45	8
15:30-20:00	8
15:45-20:15	2
16:00-20:30	4
16:15-20:45	3
16:30-21:00	2
16:45-21:15	2
17:00-21:30	4
17:15-21:45	5
17:30-22:00	3
17:45-22:15	5
18:00-22:30	4
18:15-22:45	8
18:30-23:00	6
TUESDAY
04:45-09:15	6
05:00-09:30	6
05:15-09:45	6
05:30-10:00	8
05:45-10:15	7
06:00-10:30	5
06:15-10:45	2
06:30-11:00	2
06:45-11:15	2
07:00-11:30	2
07:15-11:45	2
07:30-12:00	2
07:45-12:15	2
08:00-12:30	2
08:15-12:45	8
08:30-13:00	9
08:45-13:15	6
09:15-13:45	1
09:30-14:00	1
09:45-14:15	1
10:00-14:30	2
10:15-14:45	3
10:30-15:00	7
10:45-15:15	5
11:00-15:30	3
11:45-16:15	2
12:00-16:30	8
12:15-16:45	4
12:45-17:15	2
13:00-17:30	1
13:15-17:45	2
13:45-18:15	2
14:00-18:30	5
14:15-18:45	4
14:30-19:00	10
14:45-19:15	7
15:00-19:30	5
15:30-20:00	2
15:45-20:15	3
16:00-20:30	4
16:15-20:45	3
16:45-21:15	3
17:00-21:30	4
17:15-21:45	3
17:30-22:00	14
17:45-22:15	4
18:00-22:30	6
18:15-22:45	2
18:30-23:00	1
WEDNESDAY
04:45-09:15	8
05:00-09:30	1
05:15-09:45	2
05:30-10:00	14
05:45-10:15	6
06:00-10:30	2
06:45-11:15	2
07:00-11:30	9
07:15-11:45	2
08:00-12:30	1
08:15-12:45	4
08:30-13:00	15
08:45-13:15	4
10:00-14:30	2
10:15-14:45	9
10:30-15:00	11
10:45-15:15	2
11:45-16:15	1
12:00-16:30	8
12:15-16:45	2
12:45-17:15	2
13:00-17:30	10
13:15-17:45	2
14:00-18:30	2
14:15-18:45	2
14:30-19:00	4
14:45-19:15	16
15:00-19:30	4
15:15-19:45	2
15:30-20:00	1
15:45-20:15	2
16:00-20:30	8
16:15-20:45	2
17:00-21:30	2
17:15-21:45	5
17:30-22:00	5
17:45-22:15	16
18:00-22:30	4
18:15-22:45	1
18:30-23:00	1
THURSDAY
04:45-09:15	7
05:00-09:30	3
05:15-09:45	2
05:30-10:00	9
05:45-10:15	9
06:00-10:30	6
06:45-11:15	2
07:00-11:30	2
07:15-11:45	2
07:45-12:15	2
08:00-12:30	2
08:15-12:45	8
08:30-13:00	12
08:45-13:15	8
10:00-14:30	1
10:15-14:45	7
10:30-15:00	1
10:45-15:15	5
11:00-15:30	2
11:45-16:15	5
12:00-16:30	8
12:15-16:45	5
12:45-17:15	1
13:00-17:30	3
13:15-17:45	3
14:00-18:30	4
14:15-18:45	5
14:30-19:00	4
14:45-19:15	4
15:00-19:30	6
15:15-19:45	11
15:30-20:00	3
15:45-20:15	5
16:30-21:00	1
16:45-21:15	3
17:00-21:30	2
17:15-21:45	3
17:30-22:00	11
17:45-22:15	5
18:00-22:30	6
18:30-23:00	3
FRIDAY
04:45-09:15	7
05:00-09:30	3
05:15-09:45	16
05:30-10:00	4
05:45-10:15	4
06:00-10:30	13
06:15-10:45	4
06:45-11:15	2
07:00-11:30	12
07:15-11:45	2
08:00-12:30	5
08:15-12:45	14
08:30-13:00	6
08:45-13:15	13
09:00-13:30	2
09:30-14:00	1
09:45-14:15	1
10:00-14:30	1
10:15-14:45	10
10:30-15:00	9
10:45-15:15	11
11:00-15:30	4
11:15-15:45	2
11:45-16:15	2
12:00-16:30	10
12:15-16:45	3
12:45-17:15	4
13:00-17:30	13
13:15-17:45	3
14:00-18:30	3
14:15-18:45	9
14:30-19:00	6
14:45-19:15	13
15:00-19:30	3
15:15-19:45	3
15:30-20:00	11
15:45-20:15	3
16:00-20:30	4
16:15-20:45	4
16:30-21:00	16
16:45-21:15	4
17:15-21:45	2
17:30-22:00	6
17:45-22:15	5
18:00-22:30	15
18:15-22:45	5
18:30-23:00	4
SATURDAY
05:00-09:30	7
05:15-09:45	2
05:30-10:00	6
05:45-10:15	14
06:00-10:30	6
06:15-10:45	14
06:30-11:00	4
06:45-11:15	4
07:00-11:30	5
07:15-11:45	5
07:30-12:00	14
07:45-12:15	4
08:00-12:30	2
08:30-13:00	4
08:45-13:15	2
09:00-13:30	17
09:15-13:45	1
09:45-14:15	3
10:00-14:30	11
10:15-14:45	3
10:30-15:00	2
10:45-15:15	1
11:00-15:30	3
11:15-15:45	1
11:30-16:00	2
11:45-16:15	4
12:00-16:30	10
12:15-16:45	5
12:30-17:00	6
12:45-17:15	6
13:00-17:30	3
13:15-17:45	1
14:15-18:45	4
14:30-19:00	11
14:45-19:15	3
15:00-19:30	6
15:15-19:45	6
15:30-20:00	8
15:45-20:15	6
16:00-20:30	6
16:15-20:45	6
16:30-21:00	5
16:45-21:15	6
17:00-21:30	2
"""

def parse_tours():
    """Parse tour data into API format."""
    tours = []
    current_day = None
    tour_id = 1
    
    DAY_MAP = {
        'MONDAY': 'Mon',
        'TUESDAY': 'Tue', 
        'WEDNESDAY': 'Wed',
        'THURSDAY': 'Thu',
        'FRIDAY': 'Fri',
        'SATURDAY': 'Sat',
        'SUNDAY': 'Sun',
    }
    
    for line in TOUR_DATA.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
            
        # Check if this is a day header
        if line.upper() in DAY_MAP:
            current_day = DAY_MAP[line.upper()]
            continue
        
        # Parse time slot and count
        if current_day and '\t' in line:
            parts = line.split('\t')
            if len(parts) == 2:
                time_range = parts[0].strip()
                try:
                    count = int(parts[1].strip())
                except ValueError:
                    continue
                    
                if '-' in time_range:
                    start_time, end_time = time_range.split('-')
                    
                    # Create {count} tours for this slot
                    for i in range(count):
                        tours.append({
                            'id': f'T-{tour_id:04d}',
                            'day': current_day,
                            'start_time': start_time.strip(),
                            'end_time': end_time.strip(),
                        })
                        tour_id += 1
    
    return tours


def create_drivers(count: int):
    """Create driver list."""
    return [
        {'id': f'D-{i:03d}', 'name': f'Fahrer {i}'}
        for i in range(1, count + 1)
    ]


def main():
    # Parse tours
    tours_data = parse_tours()
    print(f"[*] Total tours parsed: {len(tours_data)}")
    
    # Count by day
    day_counts = {}
    for t in tours_data:
        day_counts[t['day']] = day_counts.get(t['day'], 0) + 1
    
    print("\n[*] Tours per day:")
    for day in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']:
        print(f"  {day}: {day_counts.get(day, 0)}")
    
    # =================================================================
    # NEW: BLOCK BUILDER DEBUG ANALYSIS
    # =================================================================
    print("\n" + "=" * 70)
    print("BLOCK BUILDER ANALYSIS (Before Solver)")
    print("=" * 70)
    
    # Convert to Tour objects for BlockBuilder
    day_map = {
        'Mon': Weekday.MONDAY, 'Tue': Weekday.TUESDAY, 'Wed': Weekday.WEDNESDAY,
        'Thu': Weekday.THURSDAY, 'Fri': Weekday.FRIDAY, 'Sat': Weekday.SATURDAY
    }
    
    tour_objects = []
    for t in tours_data:
        st = t['start_time'].split(':')
        et = t['end_time'].split(':')
        tour_objects.append(Tour(
            id=t['id'],
            day=day_map[t['day']],
            start_time=time(int(st[0]), int(st[1])),
            end_time=time(int(et[0]), int(et[1]))
        ))
    
    # Run Block Builder analysis
    builder = BlockBuilder(tour_objects)
    stats_builder = builder.get_stats()
    
    print(f"\n[*] Block Generation Stats:")
    print(f"    Total possible blocks: {stats_builder['total_possible_blocks']}")
    print(f"    Blocks by type:")
    for btype, count in stats_builder['blocks_by_type'].items():
        print(f"      {btype}: {count}")
    
    # Analyze combination failures
    failures = builder.analyze_combination_failures(sample_size=10)
    print(f"\n[*] Combination Analysis:")
    print(f"    Total tour pairs: {failures['total_pairs_analyzed']}")
    print(f"    Successful combinations: {failures['successful_combinations']} ({failures['successful_combinations']/failures['total_pairs_analyzed']*100:.1f}%)")
    print(f"    Rejections: {failures['total_rejections']}")
    print(f"    \n    Rejection reasons:")
    for reason, count in sorted(failures['rejection_reasons'].items(), key=lambda x: x[1], reverse=True):
        pct = (count / failures['total_pairs_analyzed']) * 100
        print(f"      {reason}: {count} ({pct:.1f}%)")
    
    # Critical warning if no 3er blocks
    if stats_builder['blocks_by_type']['3er'] == 0:
        print(f"\n    [WARNING] NO 3er blocks can be generated from this data!")
        print(f"    Top rejection: {max(failures['rejection_reasons'].items(), key=lambda x: x[1])[0]}")
    else:
        potential_3er_pct = (stats_builder['blocks_by_type']['3er'] / len(tours_data)) * 100
        print(f"\n    [OK] {stats_builder['blocks_by_type']['3er']} 3er blocks available ({potential_3er_pct:.1f}% of tours if all used)")
    
    print("\n" + "=" * 70)
    
    # Create drivers (estimated: tours / 6 days / 2 blocks per day)
    estimated_drivers = max(20, len(tours_data) // 10)
    drivers = create_drivers(estimated_drivers)
    print(f"\n[*] Drivers created: {len(drivers)}")
    
    # Build request
    request = {
        'tours': tours_data,
        'drivers': drivers,
        'week_start': '2024-12-09',
        'solver_type': 'cpsat',
        'time_limit_seconds': 60,
        'prefer_larger_blocks': True,
    }
    
    # Save request for inspection
    with open('test_request.json', 'w') as f:
        json.dump(request, f, indent=2)
    print("\n[*] Request saved to test_request.json")
    
    # Try to call API
    print("\n[*] Calling optimizer API...")
    try:
        response = requests.post(
            'http://localhost:8000/api/v1/schedule',
            json=request,
            timeout=120
        )
        
        if response.ok:
            result = response.json()
            print(f"\n[OK] OPTIMIZATION COMPLETE!")
            print(f"   Solver: {result['solver_type']}")
            print(f"   Valid: {result['validation']['is_valid']}")
            print(f"\n[*] Stats:")
            stats = result['stats']
            print(f"   Tours assigned: {stats['total_tours_assigned']}/{stats['total_tours_input']}")
            print(f"   Assignment rate: {stats['assignment_rate']*100:.1f}%")
            print(f"   Drivers used: {stats['total_drivers']}")
            print(f"   Avg utilization: {stats['average_driver_utilization']*100:.1f}%")
            print(f"\n[*] Block types:")
            for btype, count in stats['block_counts'].items():
                print(f"   {btype}: {count}")
            
            # =================================================================
            # SOLVER USAGE ANALYSIS
            # =================================================================
            print(f"\n" + "=" * 70)
            print("SOLVER USAGE ANALYSIS")
            print("=" * 70)
            
            # Get available vs used 3er blocks
            available_3er = stats_builder['blocks_by_type']['3er']
            used_3er = stats['block_counts'].get('3er', 0)
            
            # Calculate unique tours in 3er candidates
            unique_tours_in_3er_candidates = set()
            for block in builder.all_possible_blocks:
                if len(block.tours) == 3:
                    for tour in block.tours:
                        unique_tours_in_3er_candidates.add(tour.id)
            
            # Calculate usage ratio and coverage
            usage_ratio = used_3er / max(available_3er, 1)
            tours_in_used_3er = used_3er * 3  # Each 3er covers 3 tours
            coverage_pct = (tours_in_used_3er / len(tours_data)) * 100 if tours_data else 0
            
            print(f"\n[*] 3er Block Metrics:")
            print(f"    Available: {available_3er} blocks")
            print(f"    Used: {used_3er} blocks")
            print(f"    Usage ratio: {usage_ratio:.1%}")
            print(f"    \n    Unique tours in 3er candidates: {len(unique_tours_in_3er_candidates)}/{len(tours_data)} ({len(unique_tours_in_3er_candidates)/len(tours_data)*100:.1f}%)")
            print(f"    Tours covered via 3er: {tours_in_used_3er}/{len(tours_data)} ({coverage_pct:.1f}%)")
            
            # Interpretation
            print(f"\n[*] Interpretation:")
            if available_3er == 0:
                print(f"    >> DATA PROBLEM: No 3er blocks possible (Overlaps/Gaps in forecast)")
                print(f"    >> See rejection reasons above")
            elif available_3er > 0 and used_3er == 0:
                print(f"    >> SOLVER PROBLEM: {available_3er} 3er candidates but NONE used")
                print(f"    >> Check Objective weights or Constraints blocking 3er")
            elif usage_ratio < 0.2 and available_3er > 10:
                print(f"    >> SOLVER SELECTIVE: Many 3er available but low usage ({usage_ratio:.1%})")
                print(f"    >> Likely other constraints or driver limits blocking")
            elif usage_ratio >= 0.2:
                print(f"    >> NORMAL/GOOD: {usage_ratio:.1%} of available 3er blocks used")
            
            print("\n" + "=" * 70 + "\n")
            
            if result['unassigned_tours']:
                print(f"\n[!] Unassigned tours: {len(result['unassigned_tours'])}")
            
            # Save result
            with open('test_result.json', 'w') as f:
                json.dump(result, f, indent=2)
            print("\n[*] Result saved to test_result.json")
            
        else:
            print(f"[ERROR] API Error: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("[ERROR] Could not connect to API. Is the backend running?")
        print("   Start with: python -m uvicorn src.main:app --reload")
    except Exception as e:
        print(f"[ERROR] Error: {e}")


if __name__ == '__main__':
    main()
