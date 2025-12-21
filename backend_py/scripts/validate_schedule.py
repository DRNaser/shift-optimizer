#!/usr/bin/env python3
"""
Schedule Validator
==================
Validates a schedule JSON against strict hard constraints using the core business logic.
Reconstructs domain objects (WeeklyPlan, Drivers, Blocks) and runs the Validator.
"""

import sys
import os
import json
from datetime import time, date, datetime
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.domain.models import (
    WeeklyPlan, Driver, Block, Tour, DriverAssignment, 
    Weekday, DailyAvailability, TimeSlot
)
from src.domain.constraints import HARD_CONSTRAINTS
from src.domain.validator import validate_weekly_plan

def parse_time(t_str: str) -> time:
    """Parse HH:MM string to time object."""
    h, m = map(int, t_str.split(':')[:2])
    return time(h, m)

def reconstruct_tour(t_data: dict) -> Tour:
    return Tour(
        id=t_data['id'],
        day=Weekday(t_data['day']),
        start_time=parse_time(t_data['start_time']),
        end_time=parse_time(t_data['end_time']),
        location=t_data.get('location', 'DEFAULT'),
        required_qualifications=t_data.get('required_qualifications', [])
    )

def reconstruct_block(b_data: dict) -> Block:
    return Block(
        id=b_data['id'],
        day=Weekday(b_data['day']),
        tours=[reconstruct_tour(t) for t in b_data['tours']],
        driver_id=b_data.get('driver_id'),
        is_split=b_data.get('is_split', False),
        max_pause_minutes=b_data.get('max_pause_minutes', 0)
    )

def reconstruct_assignment(a_data: dict) -> DriverAssignment:
    return DriverAssignment(
        driver_id=a_data['driver_id'],
        day=Weekday(a_data['day']),
        block=reconstruct_block(a_data['block'])
    )

def generate_default_drivers(num_drivers=300) -> list[Driver]:
    """
    Generate the standard driver pool used in diagnostic runs.
    Must match diagnostic_run.py logic for valid validation context.
    """
    drivers = []
    for i in range(1, num_drivers + 1):
        d_id = f"D{i}"
        drivers.append(Driver(
            id=d_id,
            name=f"Driver {i}",
            qualifications=[],
            max_weekly_hours=HARD_CONSTRAINTS.MAX_WEEKLY_HOURS,
            max_daily_span_hours=HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
            max_tours_per_day=HARD_CONSTRAINTS.MAX_TOURS_PER_DAY,
            min_rest_hours=HARD_CONSTRAINTS.MIN_REST_HOURS,
            weekly_availability=[
                DailyAvailability(day=d, available=True) 
                for d in Weekday if d.value != "Sun" # Assuming Sun off by default in diag
            ]
        ))
    return drivers

def validate_file(file_path: str):
    print(f"\nVALIDATING: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Handle both raw plan JSON and full run output
    if "assignments" in data:
        plan_data = data
    elif "run" in data and "plan" in data["run"]:
        plan_data = data["run"]["plan"]
    else:
        # Fallback: maybe it's the plan dict directly
        plan_data = data

    if "assignments" not in plan_data:
        print("ERROR: Could not find 'assignments' list in JSON.")
        return

    # Reconstruct assignments
    assignments = []
    for idx, a_data in enumerate(plan_data['assignments']):
        try:
            assignments.append(reconstruct_assignment(a_data))
        except Exception as e:
            print(f"Error parsing assignment {idx}: {e}")
            continue
            
    # Reconstruct WeeklyPlan
    # We create a dummy plan object to hold assignments
    plan = WeeklyPlan(
        id="validation_reconstruct",
        week_start=date.today(), # Dummy
        assignments=assignments
    )
    
    # Generate Drivers
    # NOTE: Diagnostic run effectively ignores input drivers and uses its own pool logic if needed,
    # or the input drivers were D1..D300.
    # However, output has IDs like FTE001. We must trust the assignment IDs.
    drivers_map = {d.id: d for d in generate_default_drivers(300)}
    
    # Ensure all assigned drivers exist in map
    unknown_drivers = []
    for a in assignments:
        if a.driver_id not in drivers_map:
            # Create a default driver for validation
            # Heuristic: if ID starts with PT, max hours might be less?
            # For now, validation against HARD max (55h) is safe.
            new_driver = Driver(
                id=a.driver_id,
                name=f"Generated {a.driver_id}",
                qualifications=[], # Assume qualified
                max_weekly_hours=HARD_CONSTRAINTS.MAX_WEEKLY_HOURS,
                max_daily_span_hours=HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
                max_tours_per_day=HARD_CONSTRAINTS.MAX_TOURS_PER_DAY,
                min_rest_hours=HARD_CONSTRAINTS.MIN_REST_HOURS,
                weekly_availability=[
                    DailyAvailability(day=d, available=True) 
                    for d in Weekday
                ]
            )
            drivers_map[a.driver_id] = new_driver
            unknown_drivers.append(a.driver_id)
            
    if unknown_drivers:
        print(f"Warning: Found {len(unknown_drivers)} drivers not in default pool (e.g. {unknown_drivers[0]}). Created default profiles.")

    drivers = list(drivers_map.values())
    
    # Run Validation
    print(f"Checking {len(assignments)} assignments against {len(drivers)} drivers...")
    result = validate_weekly_plan(plan, drivers)
    
    print("\n" + "="*60)
    print("VALIDATION REPORT")
    print("="*60)
    
    if result.is_valid:
        print("Status: VALID [OK]")
    else:
        print("Status: INVALID [FAIL]")
        
    print(f"Hard Violations: {len(result.hard_violations)}")
    print(f"Warnings: {len(result.warnings)}")
    
    if result.hard_violations:
        print("\nVIOLATIONS:")
        for v in result.hard_violations[:20]:
            print(f"  - {v}")
        if len(result.hard_violations) > 20:
            print(f"  ... and {len(result.hard_violations) - 20} more")
            
    # Calculate stats
    print("\n" + "="*60)
    print("DISTRIBUTION STATS")
    print("="*60)
    
    driver_hours = {}
    driver_days = {}
    
    for a in assignments:
        did = a.driver_id
        hrs = a.block.total_work_hours
        driver_hours[did] = driver_hours.get(did, 0) + hrs
        driver_days[did] = driver_days.get(did, 0) + 1
        
    if driver_hours:
        hours = list(driver_hours.values())
        print(f"Weekly Hours: Min={min(hours):.1f}, Avg={sum(hours)/len(hours):.1f}, Max={max(hours):.1f}")
        
    if driver_days:
        days = list(driver_days.values())
        print(f"Days Worked:  Min={min(days)}, Avg={sum(days)/len(days):.1f}, Max={max(days)}")
        
    # Check coverage
    total_tours = sum(len(a.block.tours) for a in assignments)
    print(f"Total Tours Covered: {total_tours}")
    
    # Split Statistics (detect via is_split flag OR B2S- prefix)
    print("\n" + "="*60)
    print("SPLIT-SHIFT STATISTICS")
    print("="*60)
    
    # Detect split blocks by is_split flag OR B2S- prefix (JSON doesn't preserve is_split)
    def is_split_block(block):
        return getattr(block, 'is_split', False) or block.id.startswith('B2S-')
    
    split_blocks = [a.block for a in assignments if is_split_block(a.block)]
    regular_blocks = [a.block for a in assignments if not is_split_block(a.block) and len(a.block.tours) > 1]
    
    print(f"Split Blocks: {len(split_blocks)}")
    print(f"Regular Multi-Tour Blocks: {len(regular_blocks)}")
    if len(assignments) > 0:
        split_share = len(split_blocks) / len(assignments) * 100
        print(f"Split Share: {split_share:.1f}%")
    
    if split_blocks:
        spreads = sorted([b.span_minutes for b in split_blocks])
        pauses = [b.max_pause_minutes for b in split_blocks]
        
        # Percentiles for spread
        n = len(spreads)
        p50_idx = n // 2
        p95_idx = int(n * 0.95)
        p50_spread = spreads[p50_idx] if n > 0 else 0
        p95_spread = spreads[min(p95_idx, n-1)] if n > 0 else 0
        
        print(f"Split Spread: Min={min(spreads)}, Avg={sum(spreads)/n:.0f}, Max={max(spreads)} min")
        print(f"  p50={p50_spread}, p95={p95_spread} min")
        print(f"Split Pause:  Min={min(pauses)}, Avg={sum(pauses)/len(pauses):.0f}, Max={max(pauses)} min")
    
    # Two-Zone Validation (additional check)
    print("\n" + "="*60)
    print("TWO-ZONE PAUSE VALIDATION")
    print("="*60)
    
    zone_violations = []
    for a in assignments:
        block = a.block
        if len(block.tours) < 2:
            continue
        
        # Calculate actual gap
        for i in range(len(block.tours) - 1):
            t1_end = block.tours[i].end_time.hour * 60 + block.tours[i].end_time.minute
            t2_start = block.tours[i+1].start_time.hour * 60 + block.tours[i+1].start_time.minute
            gap = t2_start - t1_end
            
            # Check zone compliance
            in_regular = HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS <= gap <= HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS
            in_split = HARD_CONSTRAINTS.SPLIT_PAUSE_MIN <= gap <= HARD_CONSTRAINTS.SPLIT_PAUSE_MAX
            in_forbidden = 121 <= gap <= 239
            
            if in_forbidden:
                zone_violations.append(f"Block {block.id}: gap {gap}min in FORBIDDEN zone (121-239)")
            elif not in_regular and not in_split:
                if gap > HARD_CONSTRAINTS.SPLIT_PAUSE_MAX:
                    zone_violations.append(f"Block {block.id}: gap {gap}min exceeds split max ({HARD_CONSTRAINTS.SPLIT_PAUSE_MAX})")
    
    if zone_violations:
        print(f"Zone Violations: {len(zone_violations)}")
        for v in zone_violations[:10]:
            print(f"  - {v}")
        if len(zone_violations) > 10:
            print(f"  ... and {len(zone_violations) - 10} more")
    else:
        print("Zone Violations: 0 [OK]")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_schedule.py <path_to_json>")
        sys.exit(1)
        
    validate_file(sys.argv[1])
