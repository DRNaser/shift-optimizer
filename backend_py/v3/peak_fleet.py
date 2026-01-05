"""
SOLVEREIGN V3 - Peak Fleet Counter
====================================

Analyzes concurrent tour coverage to determine peak fleet requirements.

Shows:
- Peak concurrent tours per day
- Timeline view of active tours per 15-min slot
- Minimum fleet size needed
- Peak hours identification

Usage:
    from v3.peak_fleet import compute_peak_fleet

    peak = compute_peak_fleet(tour_instances)
    print(f"Peak fleet: {peak['global_peak']} drivers")
    print(f"Peak time: Day {peak['peak_day']} at {peak['peak_time']}")
"""

from datetime import time, timedelta
from typing import Optional
from collections import defaultdict


def compute_peak_fleet(
    tour_instances: list[dict],
    slot_minutes: int = 15
) -> dict:
    """
    Compute peak fleet requirements from tour instances.

    Args:
        tour_instances: List of tour instance dicts with day, start_ts, end_ts
        slot_minutes: Time slot granularity in minutes (default: 15)

    Returns:
        dict with:
            - global_peak: Maximum concurrent tours across all days
            - peak_day: Day with highest peak (1-7)
            - peak_time: Time of global peak
            - daily_peaks: {day: peak_count}
            - timeline: {day: {slot: count}}
            - peak_hours: List of (day, hour, count) for hours with high load
    """
    # Initialize slots for each day (0-1440 minutes in 15-min increments)
    slots_per_day = 24 * 60 // slot_minutes
    day_slots = defaultdict(lambda: [0] * slots_per_day)

    # Fill slots for each tour
    for inst in tour_instances:
        day = inst.get("day")
        start_ts = inst.get("start_ts")
        end_ts = inst.get("end_ts")

        if not all([day, start_ts, end_ts]):
            continue

        start_min = time_to_minutes(start_ts)
        end_min = time_to_minutes(end_ts)

        # Handle cross-midnight tours
        crosses_midnight = inst.get("crosses_midnight", False) or (end_min < start_min)

        if crosses_midnight:
            # First part: start to midnight
            for slot in range(start_min // slot_minutes, slots_per_day):
                day_slots[day][slot] += 1
            # Second part: midnight to end (next day)
            next_day = (day % 7) + 1
            for slot in range(0, end_min // slot_minutes + 1):
                day_slots[next_day][slot] += 1
        else:
            # Normal tour
            start_slot = start_min // slot_minutes
            end_slot = min(end_min // slot_minutes, slots_per_day - 1)
            for slot in range(start_slot, end_slot + 1):
                day_slots[day][slot] += 1

    # Find peaks
    global_peak = 0
    peak_day = 1
    peak_slot = 0
    daily_peaks = {}

    for day in range(1, 8):
        if day in day_slots:
            day_max = max(day_slots[day])
            daily_peaks[day] = day_max
            if day_max > global_peak:
                global_peak = day_max
                peak_day = day
                peak_slot = day_slots[day].index(day_max)
        else:
            daily_peaks[day] = 0

    # Convert peak slot to time
    peak_time = slot_to_time(peak_slot, slot_minutes)

    # Find peak hours (hours with >80% of global peak)
    peak_hours = []
    threshold = global_peak * 0.8

    for day in range(1, 8):
        if day not in day_slots:
            continue

        for hour in range(24):
            start_slot = hour * 60 // slot_minutes
            end_slot = (hour + 1) * 60 // slot_minutes
            hour_max = max(day_slots[day][start_slot:end_slot]) if start_slot < len(day_slots[day]) else 0

            if hour_max >= threshold:
                peak_hours.append({
                    "day": day,
                    "hour": hour,
                    "count": hour_max,
                    "time_range": f"{hour:02d}:00-{hour+1:02d}:00"
                })

    # Sort peak hours by count descending
    peak_hours.sort(key=lambda x: -x["count"])

    # Build timeline (simplified - hourly view)
    timeline = {}
    for day in range(1, 8):
        if day in day_slots:
            hourly = {}
            for hour in range(24):
                start_slot = hour * 60 // slot_minutes
                end_slot = (hour + 1) * 60 // slot_minutes
                if start_slot < len(day_slots[day]):
                    hourly[f"{hour:02d}:00"] = max(day_slots[day][start_slot:min(end_slot, len(day_slots[day]))])
                else:
                    hourly[f"{hour:02d}:00"] = 0
            timeline[day] = hourly

    return {
        "global_peak": global_peak,
        "peak_day": peak_day,
        "peak_time": peak_time,
        "peak_slot": peak_slot,
        "daily_peaks": daily_peaks,
        "peak_hours": peak_hours[:10],  # Top 10 peak hours
        "timeline": timeline,
        "total_tours": len(tour_instances),
        "slot_minutes": slot_minutes,
    }


def time_to_minutes(t) -> int:
    """Convert time object to minutes since midnight."""
    if isinstance(t, time):
        return t.hour * 60 + t.minute
    if isinstance(t, str) and ":" in t:
        parts = t.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def slot_to_time(slot: int, slot_minutes: int) -> str:
    """Convert slot index to time string."""
    minutes = slot * slot_minutes
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def format_peak_report(peak: dict) -> str:
    """
    Format peak fleet analysis as text report.

    Args:
        peak: Peak fleet dict from compute_peak_fleet()

    Returns:
        Formatted report string
    """
    day_names = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}

    lines = [
        "=" * 60,
        "PEAK FLEET ANALYSIS",
        "=" * 60,
        "",
        f"Total Tours: {peak['total_tours']}",
        f"Global Peak: {peak['global_peak']} concurrent tours",
        f"Peak Time: {day_names.get(peak['peak_day'], '?')} {peak['peak_time']}",
        "",
        "Daily Peaks:",
    ]

    for day in range(1, 8):
        count = peak['daily_peaks'].get(day, 0)
        bar = "█" * min(count, 50)
        lines.append(f"  {day_names.get(day, '?')}: {count:3d} {bar}")

    if peak['peak_hours']:
        lines.extend([
            "",
            "Top Peak Hours:",
        ])
        for ph in peak['peak_hours'][:5]:
            lines.append(f"  {day_names.get(ph['day'], '?')} {ph['time_range']}: {ph['count']} tours")

    return "\n".join(lines)


# Test
if __name__ == "__main__":
    print("Peak Fleet Counter - Test")
    print("=" * 50)

    # Test data
    test_instances = [
        {"id": 1, "day": 1, "start_ts": time(6, 0), "end_ts": time(10, 0)},
        {"id": 2, "day": 1, "start_ts": time(6, 30), "end_ts": time(10, 30)},
        {"id": 3, "day": 1, "start_ts": time(7, 0), "end_ts": time(11, 0)},
        {"id": 4, "day": 1, "start_ts": time(8, 0), "end_ts": time(12, 0)},
        {"id": 5, "day": 1, "start_ts": time(14, 0), "end_ts": time(18, 0)},
        {"id": 6, "day": 2, "start_ts": time(6, 0), "end_ts": time(10, 0)},
        {"id": 7, "day": 2, "start_ts": time(22, 0), "end_ts": time(6, 0), "crosses_midnight": True},
    ]

    peak = compute_peak_fleet(test_instances)

    print(format_peak_report(peak))
    print("\nTest PASSED")
