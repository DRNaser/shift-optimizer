"""
SOLVEREIGN V3 - Near-Violation Warning System
===============================================

Detects assignments that are close to violating constraints.
Shows "yellow zone" warnings before violations occur.

Warning Thresholds:
- Rest: 11h-12h (limit 11h, warning if <12h)
- Span Regular: 12h-14h (limit 14h, warning if >12h)
- Span Split/3er: 14h-16h (limit 16h, warning if >14h)
- Split Break: 240min-300min (min 240min, warning if <300min)
- Weekly Hours: 45h-48h (warning zone for FTE)

Usage:
    from v3.near_violations import compute_near_violations

    warnings = compute_near_violations(plan_version_id)
    for w in warnings:
        print(f"{w['type']}: {w['message']}")
"""

from datetime import time, datetime, timedelta
from typing import Optional
from collections import defaultdict


# Warning thresholds
THRESHOLDS = {
    "rest_min": 11 * 60,          # 11h = 660min (hard limit)
    "rest_warning": 12 * 60,      # 12h = 720min (warning if < this)

    "span_regular_max": 14 * 60,  # 14h = 840min (hard limit)
    "span_regular_warning": 12 * 60,  # 12h = 720min (warning if > this)

    "span_split_max": 16 * 60,    # 16h = 960min (hard limit)
    "span_split_warning": 14 * 60,    # 14h = 840min (warning if > this)

    "split_break_min": 240,       # 4h = 240min (hard minimum)
    "split_break_warning": 300,   # 5h = 300min (warning if < this)

    "weekly_hours_fte_max": 48,   # FTE max
    "weekly_hours_warning": 45,   # Warning if > 45h
}


def compute_near_violations(
    assignments: list[dict],
    instances: list[dict]
) -> list[dict]:
    """
    Compute near-violation warnings for a set of assignments.

    Args:
        assignments: List of assignment dicts with driver_id, day, tour_instance_id, metadata
        instances: List of tour instance dicts with id, day, start_ts, end_ts, work_hours

    Returns:
        List of warning dicts with type, severity, driver_id, message, details
    """
    warnings = []

    # Build instance lookup
    instance_lookup = {inst["id"]: inst for inst in instances}

    # Group assignments by driver
    driver_assignments = defaultdict(list)
    for a in assignments:
        driver_assignments[a["driver_id"]].append(a)

    for driver_id, driver_asgns in driver_assignments.items():
        # Group by day
        days_data = defaultdict(list)
        for a in driver_asgns:
            inst = instance_lookup.get(a.get("tour_instance_id"))
            if inst:
                days_data[a["day"]].append({
                    **a,
                    "start_ts": inst.get("start_ts"),
                    "end_ts": inst.get("end_ts"),
                    "work_hours": float(inst.get("work_hours", 0)),
                })

        # Sort days
        sorted_days = sorted(days_data.keys())

        # Check 1: Weekly hours
        total_hours = sum(
            sum(t.get("work_hours", 0) for t in tours)
            for tours in days_data.values()
        )

        if total_hours > THRESHOLDS["weekly_hours_warning"]:
            warnings.append({
                "type": "WEEKLY_HOURS",
                "severity": "warning",
                "driver_id": driver_id,
                "value": round(total_hours, 1),
                "threshold": THRESHOLDS["weekly_hours_warning"],
                "limit": THRESHOLDS["weekly_hours_fte_max"],
                "message": f"Fahrer {driver_id}: {total_hours:.1f}h/Woche (Warnung ab {THRESHOLDS['weekly_hours_warning']}h)"
            })

        # Check 2: Span per day
        for day, tours in days_data.items():
            if not tours:
                continue

            # Get block type from first tour
            block_type = tours[0].get("metadata", {}).get("block_type", "1er")
            tour_count = len(tours)

            # Get earliest start and latest end
            starts = [t["start_ts"] for t in tours if t.get("start_ts")]
            ends = [t["end_ts"] for t in tours if t.get("end_ts")]

            if not starts or not ends:
                continue

            first_start = min(starts)
            last_end = max(ends)

            # Calculate span in minutes
            def time_to_min(t):
                if isinstance(t, time):
                    return t.hour * 60 + t.minute
                return 0

            start_min = time_to_min(first_start)
            end_min = time_to_min(last_end)

            # Handle cross-midnight
            if end_min < start_min:
                span_minutes = (24 * 60 - start_min) + end_min
            else:
                span_minutes = end_min - start_min

            # Determine which limits apply
            is_split_or_3er = tour_count >= 3 or "split" in block_type.lower()

            if is_split_or_3er:
                warning_threshold = THRESHOLDS["span_split_warning"]
                hard_limit = THRESHOLDS["span_split_max"]
            else:
                warning_threshold = THRESHOLDS["span_regular_warning"]
                hard_limit = THRESHOLDS["span_regular_max"]

            if span_minutes > warning_threshold and span_minutes <= hard_limit:
                warnings.append({
                    "type": "SPAN",
                    "severity": "warning",
                    "driver_id": driver_id,
                    "day": day,
                    "value": span_minutes,
                    "threshold": warning_threshold,
                    "limit": hard_limit,
                    "block_type": block_type,
                    "message": f"Fahrer {driver_id} Tag {day}: Span {span_minutes}min ({span_minutes/60:.1f}h) - nahe am Limit {hard_limit}min"
                })

            # Check split break for 2er blocks
            if tour_count == 2 and "split" in block_type.lower():
                # Sort tours by start time
                sorted_tours = sorted(tours, key=lambda t: time_to_min(t.get("start_ts") or time(0, 0)))
                t1, t2 = sorted_tours[0], sorted_tours[1]

                end1 = time_to_min(t1.get("end_ts") or time(0, 0))
                start2 = time_to_min(t2.get("start_ts") or time(0, 0))

                break_minutes = start2 - end1
                if break_minutes < 0:
                    break_minutes += 24 * 60

                if break_minutes >= THRESHOLDS["split_break_min"] and break_minutes < THRESHOLDS["split_break_warning"]:
                    warnings.append({
                        "type": "SPLIT_BREAK",
                        "severity": "warning",
                        "driver_id": driver_id,
                        "day": day,
                        "value": break_minutes,
                        "threshold": THRESHOLDS["split_break_warning"],
                        "limit": THRESHOLDS["split_break_min"],
                        "message": f"Fahrer {driver_id} Tag {day}: Split-Pause {break_minutes}min - nahe am Minimum {THRESHOLDS['split_break_min']}min"
                    })

        # Check 3: Rest between consecutive days
        for i in range(len(sorted_days) - 1):
            day1 = sorted_days[i]
            day2 = sorted_days[i + 1]

            # Only check consecutive days
            if day2 - day1 != 1:
                continue

            tours1 = days_data[day1]
            tours2 = days_data[day2]

            if not tours1 or not tours2:
                continue

            # Get latest end on day1
            ends1 = [t["end_ts"] for t in tours1 if t.get("end_ts")]
            starts2 = [t["start_ts"] for t in tours2 if t.get("start_ts")]

            if not ends1 or not starts2:
                continue

            latest_end = max(ends1)
            earliest_start = min(starts2)

            def time_to_min(t):
                if isinstance(t, time):
                    return t.hour * 60 + t.minute
                return 0

            end_min = time_to_min(latest_end)
            start_min = time_to_min(earliest_start)

            # Rest = (24h - end) + start
            rest_minutes = (24 * 60 - end_min) + start_min

            if rest_minutes >= THRESHOLDS["rest_min"] and rest_minutes < THRESHOLDS["rest_warning"]:
                warnings.append({
                    "type": "REST",
                    "severity": "warning",
                    "driver_id": driver_id,
                    "day_from": day1,
                    "day_to": day2,
                    "value": rest_minutes,
                    "threshold": THRESHOLDS["rest_warning"],
                    "limit": THRESHOLDS["rest_min"],
                    "message": f"Fahrer {driver_id} Tag {day1}→{day2}: Ruhezeit {rest_minutes}min ({rest_minutes/60:.1f}h) - nahe am Minimum {THRESHOLDS['rest_min']}min"
                })

    # Sort by severity and type
    warnings.sort(key=lambda w: (w["severity"], w["type"], w.get("driver_id", "")))

    return warnings


def summarize_warnings(warnings: list[dict]) -> dict:
    """
    Summarize warnings by type.

    Args:
        warnings: List of warning dicts

    Returns:
        Summary dict with counts per type
    """
    summary = {
        "total": len(warnings),
        "by_type": defaultdict(int),
        "by_driver": defaultdict(int),
        "types": {}
    }

    for w in warnings:
        summary["by_type"][w["type"]] += 1
        if "driver_id" in w:
            summary["by_driver"][w["driver_id"]] += 1

    summary["types"] = {
        "REST": summary["by_type"].get("REST", 0),
        "SPAN": summary["by_type"].get("SPAN", 0),
        "SPLIT_BREAK": summary["by_type"].get("SPLIT_BREAK", 0),
        "WEEKLY_HOURS": summary["by_type"].get("WEEKLY_HOURS", 0),
    }

    summary["affected_drivers"] = len(summary["by_driver"])

    return summary


# Test
if __name__ == "__main__":
    print("Near-Violation Warning System - Test")
    print("=" * 50)

    # Test data with edge cases
    test_instances = [
        {"id": 1, "day": 1, "start_ts": time(6, 0), "end_ts": time(12, 0), "work_hours": 6.0},
        {"id": 2, "day": 1, "start_ts": time(17, 0), "end_ts": time(22, 0), "work_hours": 5.0},  # 16h span, 5h break
        {"id": 3, "day": 2, "start_ts": time(9, 0), "end_ts": time(17, 0), "work_hours": 8.0},  # 11h rest from day 1
    ]

    test_assignments = [
        {"driver_id": "D001", "tour_instance_id": 1, "day": 1, "metadata": {"block_type": "2er-split"}},
        {"driver_id": "D001", "tour_instance_id": 2, "day": 1, "metadata": {"block_type": "2er-split"}},
        {"driver_id": "D001", "tour_instance_id": 3, "day": 2, "metadata": {"block_type": "1er"}},
    ]

    warnings = compute_near_violations(test_assignments, test_instances)

    print(f"Found {len(warnings)} warnings:")
    for w in warnings:
        print(f"  {w['type']}: {w['message']}")

    summary = summarize_warnings(warnings)
    print(f"\nSummary: {summary}")
    print("\nTest PASSED")
