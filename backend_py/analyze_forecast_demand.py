"""
Forecast Demand Analysis - Calculate realistic driver lower bound considering peak demand.

This script analyzes the forecast input to determine:
1. Total tours and hours per day
2. Peak concurrent demand per time window
3. Theoretical minimum drivers needed (accounting for peak constraints)
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

def parse_forecast_for_analysis(filepath: str) -> dict:
    """Parse forecast CSV and extract demand patterns."""
    
    days_data = {}
    current_day = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line == ';':
                continue
            
            parts = line.split(';')
            if len(parts) < 2:
                continue
            
            # Check if this is a day header
            first = parts[0].strip()
            if first in ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag']:
                current_day = first
                days_data[current_day] = {'tours': [], 'total_count': 0, 'total_hours': 0}
                continue
            if 'Freitag' in first:
                current_day = 'Freitag'
                days_data[current_day] = {'tours': [], 'total_count': 0, 'total_hours': 0}
                continue
            
            # Parse tour slot
            if current_day and '-' in first:
                try:
                    time_range = first
                    count = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                    
                    start_str, end_str = time_range.split('-')
                    start_h, start_m = map(int, start_str.split(':'))
                    end_h, end_m = map(int, end_str.split(':'))
                    
                    start_min = start_h * 60 + start_m
                    end_min = end_h * 60 + end_m
                    duration_min = end_min - start_min
                    
                    days_data[current_day]['tours'].append({
                        'start_min': start_min,
                        'end_min': end_min,
                        'duration_min': duration_min,
                        'count': count
                    })
                    days_data[current_day]['total_count'] += count
                    days_data[current_day]['total_hours'] += count * duration_min / 60
                except (ValueError, IndexError):
                    continue
    
    return days_data


def calculate_peak_concurrent_demand(tours: list) -> dict:
    """Calculate peak concurrent demand in 30-min windows."""
    
    # Create timeline of concurrent demand
    events = []
    for tour in tours:
        for _ in range(tour['count']):
            events.append((tour['start_min'], 1))   # Tour starts
            events.append((tour['end_min'], -1))    # Tour ends
    
    events.sort(key=lambda x: (x[0], -x[1]))  # Sort by time, starts before ends
    
    max_concurrent = 0
    current_concurrent = 0
    peak_time = 0
    
    timeline = defaultdict(int)
    
    for time, delta in events:
        current_concurrent += delta
        timeline[time] = current_concurrent
        if current_concurrent > max_concurrent:
            max_concurrent = current_concurrent
            peak_time = time
    
    # Find peak windows (early vs late)
    early_peak = 0
    late_peak = 0
    for time, concurrent in timeline.items():
        if time < 12 * 60:  # Before noon
            early_peak = max(early_peak, concurrent)
        else:
            late_peak = max(late_peak, concurrent)
    
    return {
        'max_concurrent': max_concurrent,
        'peak_time': peak_time,
        'early_peak': early_peak,
        'late_peak': late_peak,
    }


def main():
    filepath = Path(__file__).parent.parent / "forecast input.csv"
    print(f"Analyzing: {filepath}")
    print("=" * 70)
    
    days_data = parse_forecast_for_analysis(str(filepath))
    
    total_tours = 0
    total_hours = 0
    day_peaks = {}
    
    print("\n[PER-DAY ANALYSIS]")
    print("-" * 70)
    
    for day, data in days_data.items():
        peak = calculate_peak_concurrent_demand(data['tours'])
        day_peaks[day] = peak
        total_tours += data['total_count']
        total_hours += data['total_hours']
        
        print(f"\n{day}:")
        print(f"  Tours: {data['total_count']}")
        print(f"  Hours: {data['total_hours']:.1f}h")
        print(f"  Peak Concurrent: {peak['max_concurrent']} (at {peak['peak_time']//60:02d}:{peak['peak_time']%60:02d})")
        print(f"  Early Peak (AM): {peak['early_peak']}")
        print(f"  Late Peak (PM):  {peak['late_peak']}")
    
    print("\n" + "=" * 70)
    print("[WEEKLY TOTALS]")
    print("-" * 70)
    print(f"Total Tours: {total_tours}")
    print(f"Total Hours: {total_hours:.1f}h")
    
    # Calculate peak-based lower bound
    max_day_peak = max(p['max_concurrent'] for p in day_peaks.values())
    max_early_peak = max(p['early_peak'] for p in day_peaks.values())
    max_late_peak = max(p['late_peak'] for p in day_peaks.values())
    
    print(f"\nMax Daily Peak: {max_day_peak} concurrent tours")
    print(f"Max Early Peak (all days): {max_early_peak}")
    print(f"Max Late Peak (all days): {max_late_peak}")
    
    print("\n" + "=" * 70)
    print("[DRIVER LOWER BOUNDS]")
    print("-" * 70)
    
    # Method 1: Simple hour-based (ignoring peaks)
    lb_hours = total_hours / 55  # Max FTE hours
    print(f"1. Hour-based LB (/55h max): {lb_hours:.1f} drivers")
    
    # Method 2: Hour-based with target utilization
    lb_target = total_hours / 45  # Target FTE hours
    print(f"2. Hour-based LB (/45h target): {lb_target:.1f} drivers")
    
    # Method 3: Peak-based (must have enough drivers for concurrent demand)
    lb_peak = max_day_peak
    print(f"3. Peak-based LB (max concurrent): {lb_peak} drivers")
    
    # Method 4: Combined (max of peak and hours)
    lb_combined = max(lb_target, lb_peak)
    print(f"4. Combined LB (max of #2 and #3): {lb_combined:.1f} drivers")
    
    print("\n" + "=" * 70)
    print("[RECOMMENDATION]")
    print("-" * 70)
    print(f"Realistic minimum: {lb_combined:.0f}-{lb_combined*1.1:.0f} FTE drivers")
    print(f"With PT buffer:    {lb_combined:.0f} FTE + ~10-20 PT for peak overflow")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
