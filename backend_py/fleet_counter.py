#!/usr/bin/env python3
"""
fleet_counter.py
================
Fleet Counter - Peak Vehicle Demand Analysis

Derives the maximum number of simultaneously active tours from tour data.
Simultaneously active tours = simultaneously bound vehicles.
Vehicle handovers are automatically accounted for (vehicle freed when tour ends).

Usage:
  python fleet_counter.py [--turnaround 5] [--interval 15] [--export]

Algorithm: Sweep-Line (O(n log n))
  - For each tour: Event (start, +1) and (end, -1)
  - Sort events by time, ends before starts at same time
  - Track running count, record peak
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class DayPeak:
    """Peak vehicle demand for a single day."""
    day: Weekday
    peak_count: int
    peak_time: time
    
    def __str__(self) -> str:
        return f"{self.day.value}: {self.peak_count} vehicles @ {self.peak_time.strftime('%H:%M')}"


@dataclass
class FleetPeakSummary:
    """Complete fleet peak analysis result."""
    day_peaks: Dict[Weekday, DayPeak]
    global_peak_count: int
    global_peak_day: Weekday
    global_peak_time: time
    total_tours: int
    turnaround_minutes: int
    
    def to_dict(self) -> dict:
        return {
            "day_peaks": {d.value: {"count": p.peak_count, "time": p.peak_time.strftime("%H:%M")} 
                         for d, p in self.day_peaks.items()},
            "global_peak": {
                "count": self.global_peak_count,
                "day": self.global_peak_day.value,
                "time": self.global_peak_time.strftime("%H:%M"),
            },
            "total_tours": self.total_tours,
            "turnaround_minutes": self.turnaround_minutes,
        }


@dataclass
class TimelinePoint:
    """A point in the fleet timeline."""
    time: time
    active_count: int


# =============================================================================
# CORE ALGORITHM: SWEEP-LINE
# =============================================================================

def _time_to_minutes(t: time) -> int:
    """Convert time to minutes since midnight."""
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> time:
    """Convert minutes since midnight to time."""
    minutes = minutes % (24 * 60)  # Handle overflow
    return time(hour=minutes // 60, minute=minutes % 60)


def _apply_turnaround(end_time: time, turnaround_minutes: int) -> time:
    """Apply turnaround offset to end time."""
    if turnaround_minutes == 0:
        return end_time
    end_mins = _time_to_minutes(end_time) + turnaround_minutes
    return _minutes_to_time(end_mins)


def compute_fleet_peaks(
    tours: List[Tour],
    turnaround_minutes: int = 0
) -> FleetPeakSummary:
    """
    Compute peak vehicle demand using sweep-line algorithm.
    
    Args:
        tours: List of Tour objects to analyze
        turnaround_minutes: Optional vehicle turnaround delay (end time offset)
    
    Returns:
        FleetPeakSummary with per-day and global peaks
    """
    # Day order for determinism
    DAY_ORDER = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    # Group tours by day
    tours_by_day: Dict[Weekday, List[Tour]] = {d: [] for d in DAY_ORDER}
    for tour in tours:
        if tour.day in tours_by_day:
            tours_by_day[tour.day].append(tour)
    
    day_peaks: Dict[Weekday, DayPeak] = {}
    
    for day in DAY_ORDER:
        day_tours = tours_by_day[day]
        if not day_tours:
            # No tours on this day
            day_peaks[day] = DayPeak(day=day, peak_count=0, peak_time=time(0, 0))
            continue
        
        # Build events: (time_minutes, delta, tour_id)
        # delta: +1 for start, -1 for end
        # Sort order: time ASC, then delta ASC (so -1 comes before +1 at same time)
        events: List[Tuple[int, int, str]] = []
        for tour in day_tours:
            start_mins = _time_to_minutes(tour.start_time)
            end_time = _apply_turnaround(tour.end_time, turnaround_minutes)
            end_mins = _time_to_minutes(end_time)
            
            events.append((start_mins, 1, tour.id))  # +1 = start
            events.append((end_mins, -1, tour.id))   # -1 = end
        
        # Sort: time ASC, delta ASC (ends before starts), then tour_id for determinism
        events.sort(key=lambda e: (e[0], e[1], e[2]))
        
        # Sweep through events
        active = 0
        peak = 0
        peak_time_mins = 0
        
        for time_mins, delta, _ in events:
            if delta == 1:  # Start event
                active += 1
                if active > peak:
                    peak = active
                    peak_time_mins = time_mins
            else:  # End event
                active -= 1
        
        day_peaks[day] = DayPeak(
            day=day,
            peak_count=peak,
            peak_time=_minutes_to_time(peak_time_mins)
        )
    
    # Find global peak
    global_peak_day = max(day_peaks.values(), key=lambda p: (p.peak_count, p.day.value))
    
    return FleetPeakSummary(
        day_peaks=day_peaks,
        global_peak_count=global_peak_day.peak_count,
        global_peak_day=global_peak_day.day,
        global_peak_time=global_peak_day.peak_time,
        total_tours=len(tours),
        turnaround_minutes=turnaround_minutes,
    )


def compute_fleet_profile(
    tours: List[Tour],
    interval_minutes: int = 15,
    turnaround_minutes: int = 0
) -> Dict[Weekday, List[TimelinePoint]]:
    """
    Compute fleet timeline profile (active vehicle count per interval).
    
    Args:
        tours: List of Tour objects to analyze
        interval_minutes: Sampling interval (default 15 min)
        turnaround_minutes: Optional vehicle turnaround delay
    
    Returns:
        Dict mapping Weekday to list of TimelinePoints
    """
    DAY_ORDER = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    # Group tours by day
    tours_by_day: Dict[Weekday, List[Tour]] = {d: [] for d in DAY_ORDER}
    for tour in tours:
        if tour.day in tours_by_day:
            tours_by_day[tour.day].append(tour)
    
    profiles: Dict[Weekday, List[TimelinePoint]] = {}
    
    for day in DAY_ORDER:
        day_tours = tours_by_day[day]
        timeline: List[TimelinePoint] = []
        
        # Sample at each interval
        for mins in range(0, 24 * 60, interval_minutes):
            sample_time = _minutes_to_time(mins)
            active = 0
            
            for tour in day_tours:
                start_mins = _time_to_minutes(tour.start_time)
                end_time = _apply_turnaround(tour.end_time, turnaround_minutes)
                end_mins = _time_to_minutes(end_time)
                
                # Tour is active if start <= sample < end
                if start_mins <= mins < end_mins:
                    active += 1
            
            if active > 0:  # Only include non-zero points
                timeline.append(TimelinePoint(time=sample_time, active_count=active))
        
        profiles[day] = timeline
    
    return profiles


# =============================================================================
# OUTPUT FORMATTERS
# =============================================================================

def print_ascii_summary(summary: FleetPeakSummary) -> None:
    """Print ASCII box summary."""
    DAY_ORDER = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    print("+-----------------------------------------+")
    print("| FLEET COUNTER (Peak Vehicle Demand)     |")
    print("+-----------------------------------------+")
    
    for day in DAY_ORDER:
        peak = summary.day_peaks.get(day)
        if peak:
            is_global = (day == summary.global_peak_day)
            marker = " <- PEAK" if is_global else ""
            time_str = peak.peak_time.strftime("%H:%M")
            line = f"| {day.value}: {peak.peak_count:3d} vehicles @ {time_str}{marker}"
            print(f"{line:<42}|")
    
    print("+-----------------------------------------+")
    global_time = summary.global_peak_time.strftime("%H:%M")
    global_line = f"| GLOBAL PEAK: {summary.global_peak_count} vehicles ({summary.global_peak_day.value} {global_time})"
    print(f"{global_line:<42}|")
    
    if summary.turnaround_minutes > 0:
        turnaround_line = f"| (Turnaround: {summary.turnaround_minutes} min)"
        print(f"{turnaround_line:<42}|")
    
    print("+-----------------------------------------+")


def export_peak_summary_csv(summary: FleetPeakSummary, output_path: Path) -> None:
    """Export peak summary to CSV."""
    DAY_ORDER = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Day", "Peak Vehicles", "Peak Time", "Is Global Peak"])
        
        for day in DAY_ORDER:
            peak = summary.day_peaks.get(day)
            if peak:
                is_global = "Yes" if day == summary.global_peak_day else "No"
                writer.writerow([
                    day.value,
                    peak.peak_count,
                    peak.peak_time.strftime("%H:%M"),
                    is_global
                ])
    
    print(f"[EXPORT] Peak summary -> {output_path}")


def export_profile_csv(
    profiles: Dict[Weekday, List[TimelinePoint]],
    interval_minutes: int,
    output_path: Path
) -> None:
    """Export fleet profile timeline to CSV."""
    DAY_ORDER = [
        Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY
    ]
    
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Day", "Time", "Active Vehicles"])
        
        for day in DAY_ORDER:
            for point in profiles.get(day, []):
                writer.writerow([
                    day.value,
                    point.time.strftime("%H:%M"),
                    point.active_count
                ])
    
    print(f"[EXPORT] Fleet profile ({interval_minutes}min) -> {output_path}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fleet Counter - Analyze peak vehicle demand from tour data"
    )
    parser.add_argument(
        "--turnaround", type=int, default=0,
        help="Vehicle turnaround time in minutes (default: 0)"
    )
    parser.add_argument(
        "--interval", type=int, default=15,
        help="Profile sampling interval in minutes (default: 15)"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export CSV files (fleet_peak_summary.csv, fleet_profile_Xmin.csv)"
    )
    parser.add_argument(
        "--input", type=Path, default=None,
        help="Input CSV file (default: ../forecast input.csv)"
    )
    args = parser.parse_args()
    
    # Load tours
    from test_forecast_csv import parse_forecast_csv
    
    input_file = args.input
    if input_file is None:
        input_file = Path(__file__).parent.parent / "forecast input.csv"
    
    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        return 1
    
    print(f"Loading tours from: {input_file}")
    tours = parse_forecast_csv(str(input_file))
    print(f"Loaded {len(tours)} tours")
    print()
    
    # Compute peaks
    summary = compute_fleet_peaks(tours, turnaround_minutes=args.turnaround)
    
    # Print ASCII summary
    print_ascii_summary(summary)
    print()
    
    # Export if requested
    if args.export:
        output_dir = Path(__file__).parent
        
        # Peak summary
        export_peak_summary_csv(summary, output_dir / "fleet_peak_summary.csv")
        
        # Profile
        profiles = compute_fleet_profile(
            tours,
            interval_minutes=args.interval,
            turnaround_minutes=args.turnaround
        )
        export_profile_csv(
            profiles,
            args.interval,
            output_dir / f"fleet_profile_{args.interval}min.csv"
        )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
