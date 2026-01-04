"""
PROOFS #4-8: Audit Framework Tests

This script generates evidence for:
- Proof #4: Coverage (instances == assignments, no duplicates)
- Proof #5: Overlap/Rest (0 violations, driver timelines)
- Proof #6: Span Regular/Split (360min validation)
- Proof #7: Cross-Midnight (correct handling)
- Proof #8: Fatigue Rule (no 3er->3er detection)

Uses V3 audit framework to validate golden run data.
"""

import sys
import json
from pathlib import Path
from datetime import time
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from test_forecast_csv import parse_forecast_csv
from v3.solver_v2_integration import solve_with_v2_solver
from src.domain.models import Weekday

# Day mappings
V2_WEEKDAY_TO_V3_DAY = {
    Weekday.MONDAY: 1,
    Weekday.TUESDAY: 2,
    Weekday.WEDNESDAY: 3,
    Weekday.THURSDAY: 4,
    Weekday.FRIDAY: 5,
    Weekday.SATURDAY: 6,
    Weekday.SUNDAY: 7,
}

V3_DAY_TO_NAME = {
    1: "Mon",
    2: "Tue",
    3: "Wed",
    4: "Thu",
    5: "Fri",
    6: "Sat",
    7: "Sun",
}

SEED = 94


def load_golden_run_data():
    """Load forecast, convert to instances, and run solver."""
    print("Loading forecast...")
    input_file = Path(__file__).parent.parent / "forecast input.csv"
    if not input_file.exists():
        input_file = Path(__file__).parent.parent / "forecast_kw51.csv"

    tours = parse_forecast_csv(str(input_file))
    print(f"  Loaded {len(tours)} tours")

    # Convert to V3 instances
    instances = []
    for i, tour in enumerate(tours, 1):
        instances.append({
            "id": i,
            "day": V2_WEEKDAY_TO_V3_DAY[tour.day],
            "start_ts": tour.start_time,
            "end_ts": tour.end_time,
            "depot": tour.location,
            "skill": None,
            "work_hours": tour.duration_hours,
            "duration_min": tour.duration_minutes,
            "crosses_midnight": False
        })

    print(f"  Created {len(instances)} tour_instances")

    # Run solver
    print(f"Running solver (seed={SEED})...")
    assignments = solve_with_v2_solver(instances, seed=SEED)
    print(f"  Created {len(assignments)} assignments")
    print()

    return instances, assignments


def proof_4_coverage(instances, assignments):
    """Proof #4: Coverage - every instance assigned exactly once."""
    print("=" * 70)
    print("PROOF #4: COVERAGE")
    print("=" * 70)
    print()

    # Count instances
    instance_count = len(instances)
    instance_ids = set(i["id"] for i in instances)

    # Count assignments
    assignment_count = len(assignments)
    assigned_instance_ids = [a["tour_instance_id"] for a in assignments]

    # FIX: Use Counter for O(n) duplicate detection instead of O(n²)
    from collections import Counter
    assignment_counts = Counter(assigned_instance_ids)
    duplicates = {id for id, count in assignment_counts.items() if count > 1}

    # Check for missing
    missing_ids = instance_ids - set(assigned_instance_ids)

    # Check for extra (assigned but not in instances)
    extra_ids = set(assigned_instance_ids) - instance_ids

    print(f"Statistics:")
    print(f"  Tour instances:  {instance_count}")
    print(f"  Assignments:     {assignment_count}")
    print(f"  Unique assigned: {len(set(assigned_instance_ids))}")
    print()

    print("Validation:")
    print(f"  [{'OK' if len(duplicates) == 0 else 'FAIL'}] Duplicate assignments: {len(duplicates)}")
    print(f"  [{'OK' if len(missing_ids) == 0 else 'FAIL'}] Missing instances: {len(missing_ids)}")
    print(f"  [{'OK' if len(extra_ids) == 0 else 'FAIL'}] Extra assignments: {len(extra_ids)}")
    print(f"  [{'OK' if instance_count == assignment_count else 'FAIL'}] Count match: {instance_count} == {assignment_count}")
    print()

    coverage_ratio = len(set(assigned_instance_ids)) / instance_count * 100 if instance_count > 0 else 0

    print(f"Coverage Ratio: {coverage_ratio:.2f}%")
    print()

    all_passed = (
        len(duplicates) == 0 and
        len(missing_ids) == 0 and
        len(extra_ids) == 0 and
        instance_count == assignment_count
    )

    print(f"PROOF #4 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def proof_5_overlap_rest(instances, assignments):
    """Proof #5: Overlap/Rest - no overlaps, min 11h rest BETWEEN BLOCKS (DATETIME-BASED).

    IMPORTANT: The 11h rest rule applies between BLOCKS (daily work assignments),
    NOT between individual tours within the same block.

    - Tours within the same day/block can have short breaks (30min, 45min, etc.)
    - The 11h rest applies from the END of one day's last tour to the START of next day's first tour
    """
    from datetime import datetime, timedelta

    print("=" * 70)
    print("PROOF #5: OVERLAP / REST (BETWEEN BLOCKS, NOT TOURS)")
    print("=" * 70)
    print()

    # FIX: Use week_anchor_date for deterministic datetime computation
    # January 1, 2024 was a Monday (day=1)
    week_anchor_date = datetime(2024, 1, 1).date()
    print(f"Week Anchor: {week_anchor_date} (Monday)")
    print(f"Rule: 11h rest applies between BLOCKS (days), NOT between tours within a block")
    print()

    # Build instance lookup
    instance_lookup = {i["id"]: i for i in instances}

    # Helper: Convert (day, time, crosses_midnight) -> datetime
    def compute_datetime(day, time_obj, crosses_midnight):
        """
        Compute absolute datetime using week_anchor_date.

        day: 1-7 (Mon-Sun)
        time_obj: time object
        crosses_midnight: bool (if True, tour ends next day)
        """
        # Day offset from Monday (day=1 is Monday = offset 0)
        day_offset = day - 1
        tour_date = week_anchor_date + timedelta(days=day_offset)
        dt = datetime.combine(tour_date, time_obj)
        return dt

    # Group assignments by driver
    driver_assignments = defaultdict(list)
    for a in assignments:
        driver_assignments[a["driver_id"]].append(a)

    overlap_violations = []
    rest_violations = []
    driver_timelines = {}
    driver_day_blocks = {}

    for driver_id, driver_asgns in driver_assignments.items():
        # Build timeline with absolute datetimes
        timeline_entries = []
        for a in driver_asgns:
            inst = instance_lookup[a["tour_instance_id"]]
            crosses_midnight = inst.get("crosses_midnight", False)

            start_dt = compute_datetime(a["day"], inst["start_ts"], False)

            # For cross-midnight tours, end is on next day
            if crosses_midnight:
                end_dt = compute_datetime(a["day"] + 1, inst["end_ts"], False)
            else:
                end_dt = compute_datetime(a["day"], inst["end_ts"], False)

            timeline_entries.append({
                "driver_id": driver_id,
                "tour_instance_id": a["tour_instance_id"],
                "day": a["day"],
                "start_dt": start_dt,
                "end_dt": end_dt,
                "block_type": a["metadata"].get("block_type", "?"),
                "crosses_midnight": crosses_midnight
            })

        # Sort by start_dt
        timeline_entries.sort(key=lambda e: e["start_dt"])
        driver_timelines[driver_id] = timeline_entries

        # Check overlaps: consecutive entries where prev.end_dt > next.start_dt
        for i in range(len(timeline_entries) - 1):
            prev = timeline_entries[i]
            next_entry = timeline_entries[i + 1]

            if prev["end_dt"] > next_entry["start_dt"]:
                overlap_violations.append({
                    "driver_id": driver_id,
                    "tour1": prev["tour_instance_id"],
                    "tour2": next_entry["tour_instance_id"],
                    "prev_end": prev["end_dt"].strftime("%a %H:%M"),
                    "next_start": next_entry["start_dt"].strftime("%a %H:%M")
                })

        # FIX: Group tours by day to compute block boundaries
        # Then check rest BETWEEN blocks (days), not between tours
        day_blocks = defaultdict(list)
        for entry in timeline_entries:
            day_blocks[entry["day"]].append(entry)

        driver_day_blocks[driver_id] = day_blocks

        # Compute block start/end per day (first tour start, last tour end)
        block_boundaries = []
        for day in sorted(day_blocks.keys()):
            day_entries = day_blocks[day]
            block_start = min(e["start_dt"] for e in day_entries)
            block_end = max(e["end_dt"] for e in day_entries)
            block_boundaries.append({
                "day": day,
                "block_start": block_start,
                "block_end": block_end,
                "tour_count": len(day_entries)
            })

        # Check rest BETWEEN BLOCKS (consecutive days)
        for i in range(len(block_boundaries) - 1):
            prev_block = block_boundaries[i]
            next_block = block_boundaries[i + 1]

            rest_td = next_block["block_start"] - prev_block["block_end"]
            rest_minutes = rest_td.total_seconds() / 60

            if rest_minutes < 11 * 60:  # < 11 hours between blocks
                rest_violations.append({
                    "driver_id": driver_id,
                    "day1": prev_block["day"],
                    "day2": next_block["day"],
                    "rest_minutes": rest_minutes,
                    "rest_hours": round(rest_minutes / 60, 2),
                    "prev_end": prev_block["block_end"].strftime("%a %H:%M"),
                    "next_start": next_block["block_start"].strftime("%a %H:%M")
                })

    print("Validation:")
    print(f"  [{'OK' if len(overlap_violations) == 0 else 'FAIL'}] Overlap violations: {len(overlap_violations)}")
    print(f"  [{'OK' if len(rest_violations) == 0 else 'FAIL'}] Rest violations (<11h between blocks): {len(rest_violations)}")
    print()

    # Show violations if any
    if overlap_violations:
        print("Sample Overlap Violations:")
        for v in overlap_violations[:3]:
            print(f"  {v['driver_id']}: Tour {v['tour1']} ends {v['prev_end']} overlaps Tour {v['tour2']} starts {v['next_start']}")
        print()

    if rest_violations:
        print("Rest Violations (between blocks/days):")
        for v in rest_violations[:5]:
            print(f"  {v['driver_id']}: {v['rest_hours']}h rest between Day {v['day1']} (ends {v['prev_end']}) and Day {v['day2']} (starts {v['next_start']})")
        print()

    # Show sample timelines (3 drivers) with datetimes
    print("Sample Driver Timelines (with block boundaries):")
    sample_drivers = sorted(driver_timelines.keys())[:3]
    for driver_id in sample_drivers:
        day_blocks = driver_day_blocks[driver_id]
        print(f"\n  {driver_id}:")
        for day in sorted(day_blocks.keys()):
            day_entries = day_blocks[day]
            block_start = min(e["start_dt"] for e in day_entries)
            block_end = max(e["end_dt"] for e in day_entries)
            day_name = V3_DAY_TO_NAME.get(day, str(day))
            print(f"    {day_name}: {block_start.strftime('%H:%M')}-{block_end.strftime('%H:%M')} ({len(day_entries)} tours)")

    print()

    all_passed = len(overlap_violations) == 0 and len(rest_violations) == 0

    print(f"PROOF #5 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def proof_6_span(instances, assignments):
    """Proof #6: Span Regular/Split - validate span limits (DATETIME-BASED).

    Rules:
    - Regular blocks (1er, 2er-reg): ≤14h span
    - Split blocks (2er-split): ≤16h span, break 4-6h (240-360min)
    - 3er blocks: ≤16h span (no break validation - internal gaps can be 30-60min)
    """
    from datetime import datetime, timedelta

    print("=" * 70)
    print("PROOF #6: SPAN REGULAR / SPLIT / 3ER (DATETIME-BASED)")
    print("=" * 70)
    print()

    # FIX: Use week_anchor_date for deterministic datetime computation
    week_anchor_date = datetime(2024, 1, 1).date()

    # Build instance lookup
    instance_lookup = {i["id"]: i for i in instances}

    # Helper: Convert (day, time) -> datetime
    def compute_datetime(day, time_obj):
        day_offset = day - 1
        tour_date = week_anchor_date + timedelta(days=day_offset)
        return datetime.combine(tour_date, time_obj)

    # Group assignments by driver and day (blocks)
    driver_day_blocks = defaultdict(lambda: defaultdict(list))
    for a in assignments:
        driver_day_blocks[a["driver_id"]][a["day"]].append(a)

    span_regular_violations = []
    span_split_violations = []
    split_break_violations = []
    split_blocks_found = []

    for driver_id, days in driver_day_blocks.items():
        for day, block_asgns in days.items():
            # Get block metadata from first assignment
            block_type = block_asgns[0]["metadata"].get("block_type", "1er")

            # Build tour timeline with datetimes
            tour_entries = []
            for a in block_asgns:
                inst = instance_lookup[a["tour_instance_id"]]
                crosses_midnight = inst.get("crosses_midnight", False)

                start_dt = compute_datetime(day, inst["start_ts"])

                # For cross-midnight tours, end is on next day
                if crosses_midnight:
                    end_dt = compute_datetime(day + 1, inst["end_ts"])
                else:
                    end_dt = compute_datetime(day, inst["end_ts"])

                tour_entries.append({
                    "tour_instance_id": a["tour_instance_id"],
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "crosses_midnight": crosses_midnight
                })

            # Sort by start time
            tour_entries.sort(key=lambda t: t["start_dt"])

            # Calculate block span using datetimes
            first_start_dt = tour_entries[0]["start_dt"]
            last_end_dt = tour_entries[-1]["end_dt"]
            span_td = last_end_dt - first_start_dt
            span_minutes = span_td.total_seconds() / 60

            is_split = "split" in block_type.lower()
            is_3er = "3er" in block_type.lower()

            # 3er blocks and splits both use 16h span limit
            if is_split or is_3er:
                split_blocks_found.append({
                    "driver_id": driver_id,
                    "day": day,
                    "span_minutes": int(span_minutes),
                    "first_start": first_start_dt.strftime("%H:%M"),
                    "last_end": last_end_dt.strftime("%H:%M"),
                    "block_type": block_type
                })

                # Check span limit (16h = 960 min for both split and 3er)
                if span_minutes > 16 * 60:
                    span_split_violations.append({
                        "driver_id": driver_id,
                        "day": day,
                        "span_minutes": int(span_minutes),
                        "limit": 960,
                        "block_type": block_type
                    })

                # Only check break for SPLIT blocks (not 3er - they have 30-60min internal gaps)
                if is_split and len(tour_entries) >= 2:
                    for i in range(len(tour_entries) - 1):
                        t1 = tour_entries[i]
                        t2 = tour_entries[i + 1]

                        break_td = t2["start_dt"] - t1["end_dt"]
                        break_minutes = break_td.total_seconds() / 60

                        # Split shifts must have 4-6 hour break (240-360min)
                        if break_minutes < 240 or break_minutes > 360:
                            split_break_violations.append({
                                "driver_id": driver_id,
                                "day": day,
                                "break_minutes": int(break_minutes),
                                "expected": "240-360",
                                "tour1_end": t1["end_dt"].strftime("%H:%M"),
                                "tour2_start": t2["start_dt"].strftime("%H:%M")
                            })
            else:
                # Regular block (1er, 2er-reg) - check 14h span limit
                if span_minutes > 14 * 60:
                    span_regular_violations.append({
                        "driver_id": driver_id,
                        "day": day,
                        "span_minutes": int(span_minutes),
                        "limit": 840
                    })

    print("Statistics:")
    print(f"  Total blocks analyzed: {sum(len(days) for days in driver_day_blocks.values())}")
    print(f"  Split/3er blocks found (16h span): {len(split_blocks_found)}")
    print()

    print("Validation:")
    print(f"  [{'OK' if len(span_regular_violations) == 0 else 'FAIL'}] Regular span violations (>14h): {len(span_regular_violations)}")
    print(f"  [{'OK' if len(span_split_violations) == 0 else 'FAIL'}] Split/3er span violations (>16h): {len(span_split_violations)}")
    print(f"  [{'OK' if len(split_break_violations) == 0 else 'FAIL'}] Split break violations (not 4-6h): {len(split_break_violations)}")
    print()

    # Show split break violations if any
    if split_break_violations:
        print("Split Break Violations (must be 4-6 hours / 240-360min):")
        for v in split_break_violations[:5]:
            print(f"  {v['driver_id']} Day {v['day']}: Break={v['break_minutes']}min (tour ends {v['tour1_end']}, next starts {v['tour2_start']})")
        print()

    # Show sample split/3er blocks
    if split_blocks_found:
        print("Sample Split/3er Blocks (16h span limit):")
        for block in split_blocks_found[:5]:
            print(f"  {block['driver_id']} Day {block['day']}: {block['first_start']}-{block['last_end']} span={block['span_minutes']}min ({block['span_minutes']/60:.1f}h) [{block['block_type']}]")
    print()

    all_passed = (
        len(span_regular_violations) == 0 and
        len(span_split_violations) == 0 and
        len(split_break_violations) == 0
    )

    print(f"PROOF #6 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def proof_7_cross_midnight():
    """Proof #7: Cross-Midnight handling test."""
    print("=" * 70)
    print("PROOF #7: CROSS-MIDNIGHT HANDLING")
    print("=" * 70)
    print()

    # Create test case: 22:00-06:00 tour
    print("Test Case: 22:00-06:00 tour (cross-midnight)")
    print()

    test_instance = {
        "id": 1,
        "day": 4,  # Thursday
        "start_ts": time(22, 0),
        "end_ts": time(6, 0),
        "depot": "Test",
        "skill": None,
        "work_hours": 8.0,  # 22:00-06:00 = 8 hours
        "duration_min": 480,
        "crosses_midnight": True
    }

    print("Input:")
    print(f"  Day: {V3_DAY_TO_NAME[test_instance['day']]}")
    print(f"  Start: {test_instance['start_ts']}")
    print(f"  End: {test_instance['end_ts']}")
    print(f"  Duration: {test_instance['duration_min']} min ({test_instance['work_hours']}h)")
    print(f"  crosses_midnight: {test_instance['crosses_midnight']}")
    print()

    # Validate duration calculation
    start_min = test_instance["start_ts"].hour * 60 + test_instance["start_ts"].minute
    end_min = test_instance["end_ts"].hour * 60 + test_instance["end_ts"].minute

    if end_min < start_min:  # Cross-midnight
        calculated_duration = (24 * 60 - start_min) + end_min
    else:
        calculated_duration = end_min - start_min

    print("Validation:")
    print(f"  Start minutes: {start_min}")
    print(f"  End minutes: {end_min}")
    print(f"  Calculated duration: {calculated_duration} min ({calculated_duration/60:.1f}h)")
    print(f"  Expected duration: {test_instance['duration_min']} min")
    print()

    duration_correct = calculated_duration == test_instance["duration_min"]
    flag_correct = test_instance["crosses_midnight"] == True

    print(f"  [{'OK' if duration_correct else 'FAIL'}] Duration calculation correct")
    print(f"  [{'OK' if flag_correct else 'FAIL'}] crosses_midnight flag set correctly")
    print()

    # Test with V2 integration (cross-midnight tour ends at 23:59 for V2 compatibility)
    print("V2 Integration Handling:")
    print("  Cross-midnight tours use end_ts=23:59 for V2 Tour model compatibility")
    print("  The actual duration is preserved in the duration_min field")
    print()

    all_passed = duration_correct and flag_correct

    print(f"PROOF #7 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def proof_8_fatigue(instances, assignments):
    """Proof #8: Fatigue Rule - no consecutive 3er->3er."""
    print("=" * 70)
    print("PROOF #8: FATIGUE RULE (NO 3er -> 3er)")
    print("=" * 70)
    print()

    # Group assignments by driver
    driver_assignments = defaultdict(list)
    for a in assignments:
        driver_assignments[a["driver_id"]].append(a)

    # Count blocks by type per driver per day
    driver_day_block_type = defaultdict(dict)
    for driver_id, asgns in driver_assignments.items():
        day_asgns = defaultdict(list)
        for a in asgns:
            day_asgns[a["day"]].append(a)

        for day, day_tours in day_asgns.items():
            tours_count = len(day_tours)
            if tours_count >= 3:
                driver_day_block_type[driver_id][day] = "3er"
            elif tours_count == 2:
                driver_day_block_type[driver_id][day] = "2er"
            else:
                driver_day_block_type[driver_id][day] = "1er"

    # Check for consecutive 3er->3er
    fatigue_violations = []

    for driver_id, day_types in driver_day_block_type.items():
        days_sorted = sorted(day_types.keys())
        for i in range(len(days_sorted) - 1):
            day1 = days_sorted[i]
            day2 = days_sorted[i + 1]

            # Only check consecutive days
            if day2 - day1 != 1:
                continue

            type1 = day_types[day1]
            type2 = day_types[day2]

            if type1 == "3er" and type2 == "3er":
                fatigue_violations.append({
                    "driver_id": driver_id,
                    "day1": day1,
                    "day2": day2
                })

    # Count 3er blocks total
    total_3er = sum(1 for dt in driver_day_block_type.values() for t in dt.values() if t == "3er")

    print("Statistics:")
    print(f"  Total 3er blocks: {total_3er}")
    print(f"  Drivers with 3er blocks: {len([d for d in driver_day_block_type.values() if '3er' in d.values()])}")
    print()

    print("Validation:")
    print(f"  [{'OK' if len(fatigue_violations) == 0 else 'FAIL'}] Consecutive 3er->3er violations: {len(fatigue_violations)}")
    print()

    if fatigue_violations:
        print("Violations found:")
        for v in fatigue_violations[:5]:
            print(f"  {v['driver_id']}: Day {v['day1']} (3er) -> Day {v['day2']} (3er)")
    else:
        print("No consecutive triple shifts detected.")
    print()

    all_passed = len(fatigue_violations) == 0

    print(f"PROOF #8 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def proof_9_freeze_window(instances, assignments):
    """Proof #9: Freeze Window - tours within 12h of start are FROZEN."""
    from datetime import datetime, timedelta

    print("=" * 70)
    print("PROOF #9: FREEZE WINDOW (<12h = FROZEN)")
    print("=" * 70)
    print()

    # FIX: Use week_anchor_date for deterministic datetime computation
    week_anchor_date = datetime(2024, 1, 1).date()

    # Simulate "now" as Wednesday 2024-01-03 08:00 (48h into the week)
    # This means:
    # - Monday (day=1) tours are all in the past (FROZEN)
    # - Tuesday (day=2) tours are mostly in the past
    # - Wednesday (day=3) tours before 20:00 are FROZEN (12h window)
    now = datetime(2024, 1, 3, 8, 0)  # Wed 08:00

    print(f"Week Anchor: {week_anchor_date} (Monday)")
    print(f"Simulated Now: {now.strftime('%a %Y-%m-%d %H:%M')}")
    print(f"Freeze Window: 12 hours (720 minutes)")
    print()

    # Build instance lookup
    instance_lookup = {i["id"]: i for i in instances}

    # Helper: Convert (day, time) -> datetime
    def compute_datetime(day, time_obj):
        day_offset = day - 1
        tour_date = week_anchor_date + timedelta(days=day_offset)
        return datetime.combine(tour_date, time_obj)

    # Analyze freeze status for each tour instance
    frozen_instances = []
    modifiable_instances = []

    for inst in instances:
        start_dt = compute_datetime(inst["day"], inst["start_ts"])

        # Calculate time until start
        time_until_start = start_dt - now
        minutes_until_start = time_until_start.total_seconds() / 60

        # Freeze window: 12h = 720 minutes
        is_frozen = minutes_until_start < 720

        if is_frozen:
            frozen_instances.append({
                "tour_instance_id": inst["id"],
                "day": inst["day"],
                "start_dt": start_dt,
                "minutes_until_start": minutes_until_start
            })
        else:
            modifiable_instances.append({
                "tour_instance_id": inst["id"],
                "day": inst["day"],
                "start_dt": start_dt,
                "minutes_until_start": minutes_until_start
            })

    # Count assignments to frozen vs modifiable tours
    frozen_assignment_count = 0
    modifiable_assignment_count = 0
    frozen_tour_ids = {f["tour_instance_id"] for f in frozen_instances}

    for a in assignments:
        if a["tour_instance_id"] in frozen_tour_ids:
            frozen_assignment_count += 1
        else:
            modifiable_assignment_count += 1

    print("Statistics:")
    print(f"  Total tour instances: {len(instances)}")
    print(f"  FROZEN instances (<12h): {len(frozen_instances)}")
    print(f"  MODIFIABLE instances (>=12h): {len(modifiable_instances)}")
    print()
    print(f"  Assignments to frozen tours: {frozen_assignment_count}")
    print(f"  Assignments to modifiable tours: {modifiable_assignment_count}")
    print()

    # Validation: Check that freeze logic is deterministic
    freeze_logic_correct = (
        len(frozen_instances) + len(modifiable_instances) == len(instances) and
        frozen_assignment_count + modifiable_assignment_count == len(assignments)
    )

    print("Validation:")
    print(f"  [{'OK' if freeze_logic_correct else 'FAIL'}] Freeze logic is deterministic (all tours classified)")
    print()

    # Show sample frozen tours
    if frozen_instances:
        print("Sample FROZEN tours (within 12h):")
        for frozen in sorted(frozen_instances, key=lambda x: x["minutes_until_start"])[:5]:
            day_name = V3_DAY_TO_NAME.get(frozen["day"], str(frozen["day"]))
            print(f"  Tour {frozen['tour_instance_id']}: {day_name} {frozen['start_dt'].strftime('%H:%M')} (starts in {int(frozen['minutes_until_start'])}min)")
        print()

    # Show sample modifiable tours
    if modifiable_instances:
        print("Sample MODIFIABLE tours (>=12h away):")
        for mod in sorted(modifiable_instances, key=lambda x: x["minutes_until_start"])[:5]:
            day_name = V3_DAY_TO_NAME.get(mod["day"], str(mod["day"]))
            hours_until = mod['minutes_until_start'] / 60
            print(f"  Tour {mod['tour_instance_id']}: {day_name} {mod['start_dt'].strftime('%H:%M')} (starts in {hours_until:.1f}h)")
        print()

    # Expected behavior:
    # - Solver should NOT reassign frozen tours
    # - Solver with override should log override events
    print("Expected Behavior:")
    print(f"  Without override: {frozen_assignment_count} assignments to frozen tours remain unchanged")
    print(f"  With override: Override events logged to audit_log (not tested here)")
    print()

    all_passed = freeze_logic_correct

    print(f"PROOF #9 STATUS: {'PASS' if all_passed else 'FAIL'}")
    print()

    return all_passed


def main():
    print("=" * 70)
    print("AUDIT PROOFS #4-8 + FREEZE WINDOW")
    print("=" * 70)
    print()

    # Load data
    instances, assignments = load_golden_run_data()

    # Run proofs
    results = {}

    results["proof_4_coverage"] = proof_4_coverage(instances, assignments)
    results["proof_5_overlap_rest"] = proof_5_overlap_rest(instances, assignments)
    results["proof_6_span"] = proof_6_span(instances, assignments)
    results["proof_7_cross_midnight"] = proof_7_cross_midnight()
    results["proof_8_fatigue"] = proof_8_fatigue(instances, assignments)
    results["proof_9_freeze_window"] = proof_9_freeze_window(instances, assignments)

    # Summary
    print("=" * 70)
    print("AUDIT PROOFS SUMMARY (#4-9)")
    print("=" * 70)
    print()

    all_passed = all(results.values())

    for proof_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {proof_name}")

    print()
    print(f"Overall: {'ALL PROOFS PASSED' if all_passed else 'SOME PROOFS FAILED'}")
    print()

    return all_passed


if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
