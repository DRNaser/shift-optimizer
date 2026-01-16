"""
SOLVEREIGN V3 - V2 Solver Integration Bridge (DETERMINISTIC)
=============================================================

Integrates the V2 Block Heuristic Solver with V3 tour_instances format.

This module provides a bridge between:
- V3 tour_instances (dict format with day=1-7, id, start_ts, end_ts)
- V2 solver (Tour objects, Weekday enum, Block objects, DriverState)

Flow:
    1. Convert V3 tour_instances -> V2 Tour objects
    2. Call partition_tours_into_blocks() with DETERMINISTIC selection
    3. Call BlockHeuristicSolver.solve()
    4. Convert DriverState results -> V3 assignment format

DETERMINISM GUARANTEE (PR-4):
    - NO random.seed(), random.shuffle(), random.choice()
    - Stable sort keys: (day, start_time, end_time, tour_id)
    - Tie-breaking via SHA256(canonical block description) = block_key
    - Running solve N times produces IDENTICAL output

Key Mappings:
    V3 day (1-7) -> V2 Weekday (Mon, Tue, Wed, Thu, Fri, Sat, Sun)
    V3 start_ts/end_ts -> V2 start_time/end_time
    V3 depot -> V2 location
    V3 tour_instance.id -> preserved in metadata for 1:1 mapping
"""

import sys
from pathlib import Path
from datetime import time
from typing import Optional
import hashlib
from collections import defaultdict

# Add parent to path for V2 imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from packs.roster.engine.src_compat.models import Tour, Block, Weekday
from packs.roster.engine.src_compat.smart_block_builder import BlockGenOverrides
from packs.roster.engine.src_compat.block_heuristic_solver import BlockHeuristicSolver


# Day mapping: V3 (1-7) -> V2 Weekday enum
V3_DAY_TO_V2_WEEKDAY = {
    1: Weekday.MONDAY,
    2: Weekday.TUESDAY,
    3: Weekday.WEDNESDAY,
    4: Weekday.THURSDAY,
    5: Weekday.FRIDAY,
    6: Weekday.SATURDAY,
    7: Weekday.SUNDAY,
}

V2_WEEKDAY_TO_V3_DAY = {v: k for k, v in V3_DAY_TO_V2_WEEKDAY.items()}


def solve_with_v2_solver(
    tour_instances: list[dict],
    seed: int = 94  # DEPRECATED: kept for API compatibility, ignored
) -> list[dict]:
    """
    Solve tour assignments using V2 Block Heuristic Solver (DETERMINISTIC).

    Args:
        tour_instances: List of V3 tour instance dicts with:
            - id: int (tour_instance_id)
            - day: int (1-7)
            - start_ts: time
            - end_ts: time
            - depot: str (optional)
            - skill: str (optional)
            - work_hours: float
            - duration_min: int
        seed: DEPRECATED, ignored (kept for API compatibility)

    Returns:
        List of assignment dicts with:
            - driver_id: str (e.g., "D001")
            - tour_instance_id: int
            - day: int (1-7)
            - block_id: str
            - role: str ("PRIMARY")
            - metadata: dict with solver details

    Determinism Guarantee:
        Running this function N times with identical input produces
        IDENTICAL output. No random state involved.
    """
    print(f"[V2 Integration] Converting {len(tour_instances)} tour_instances to V2 format (DETERMINISTIC)...")

    # Step 1: Convert V3 tour_instances -> V2 Tour objects
    tours, instance_map = _convert_instances_to_tours(tour_instances)
    print(f"[V2 Integration] Created {len(tours)} V2 Tour objects")

    # Step 2: Partition tours into blocks using DETERMINISTIC algorithm
    print(f"[V2 Integration] Running DETERMINISTIC partition_tours_into_blocks...")
    blocks = partition_tours_into_blocks(tours)
    print(f"[V2 Integration] Created {len(blocks)} blocks")

    # Step 3: Run BlockHeuristicSolver
    print(f"[V2 Integration] Running BlockHeuristicSolver...")
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve()
    print(f"[V2 Integration] Solver returned {len(drivers)} drivers")

    # Step 4: Convert driver assignments back to V3 format
    assignments = _convert_drivers_to_assignments(drivers, instance_map)
    print(f"[V2 Integration] Created {len(assignments)} V3 assignments")

    return assignments


def _convert_instances_to_tours(
    tour_instances: list[dict]
) -> tuple[list[Tour], dict[str, int]]:
    """
    Convert V3 tour_instances to V2 Tour objects.

    Returns:
        - List of Tour objects
        - instance_map: {tour_id -> tour_instance_id} for reverse mapping
    """
    tours = []
    instance_map = {}  # tour.id -> tour_instance_id

    for instance in tour_instances:
        # FIX: Pass actual times and crosses_midnight flag to V2 Tour model
        # The Tour model now supports cross-midnight tours natively
        start_ts = instance['start_ts']
        end_ts = instance['end_ts']
        crosses_midnight = instance.get('crosses_midnight', False)

        # Convert day
        v3_day = instance['day']
        if v3_day not in V3_DAY_TO_V2_WEEKDAY:
            print(f"  [WARN] Skipping instance {instance['id']} with invalid day {v3_day}")
            continue

        v2_day = V3_DAY_TO_V2_WEEKDAY[v3_day]

        # Create unique tour ID that embeds instance_id
        tour_id = f"T{instance['id']}"

        # Location/Depot
        location = instance.get('depot', 'DEFAULT') or 'DEFAULT'

        # Qualifications
        qualifications = []
        if instance.get('skill'):
            qualifications = [instance['skill']]

        try:
            tour = Tour(
                id=tour_id,
                day=v2_day,
                start_time=start_ts,
                end_time=end_ts,
                location=location,
                required_qualifications=qualifications,
                crosses_midnight=crosses_midnight
            )
            tours.append(tour)
            instance_map[tour_id] = instance['id']
        except ValueError as e:
            print(f"  [WARN] Skipping invalid tour for instance {instance['id']}: {e}")
            continue

    return tours, instance_map


def _convert_drivers_to_assignments(
    drivers: list,
    instance_map: dict[str, int]
) -> list[dict]:
    """
    Convert V2 DriverState results to V3 assignment format.

    Args:
        drivers: List of DriverState objects from solver
        instance_map: {tour_id -> tour_instance_id}

    Returns:
        List of assignment dicts
    """
    assignments = []

    for driver in drivers:
        driver_id = driver.id  # e.g., "D001"

        for block in driver.blocks:
            block_id = block.id
            v3_day = V2_WEEKDAY_TO_V3_DAY[block.day]

            # Determine block type for metadata
            block_type = f"{len(block.tours)}er"
            if len(block.tours) == 2 and "S" in block_id:
                block_type = "2er-split"
            elif len(block.tours) == 2:
                block_type = "2er-reg"

            for tour in block.tours:
                tour_id = tour.id
                tour_instance_id = instance_map.get(tour_id)

                if tour_instance_id is None:
                    print(f"  [WARN] No instance mapping for tour {tour_id}")
                    continue

                assignments.append({
                    "driver_id": driver_id,
                    "tour_instance_id": tour_instance_id,
                    "day": v3_day,
                    "block_id": block_id,
                    "role": "PRIMARY",
                    "metadata": {
                        "block_type": block_type,
                        "block_tours": len(block.tours),
                        "block_span_minutes": block.span_minutes,
                        "block_work_hours": round(block.total_work_hours, 2),
                        "driver_total_hours": round(driver.total_hours, 2),
                        "driver_type": "FTE" if driver.total_hours >= 40 else "PT"
                    }
                })

    return assignments


def _tour_fingerprint(t: Tour) -> str:
    """
    Generate canonical fingerprint for a tour based on INTRINSIC properties only.

    Does NOT use tour_id (which may be non-canonical across systems).
    Uses only inherent tour attributes:
        - day (weekday value)
        - start_time (HH:MM)
        - end_time (HH:MM)
        - location (depot)
        - qualifications (sorted, joined)

    Returns:
        SHA256[:8] fingerprint string
    """
    quals = "|".join(sorted(t.required_qualifications)) if t.required_qualifications else ""
    canonical = f"{t.day.value}|{t.start_time.strftime('%H:%M')}|{t.end_time.strftime('%H:%M')}|{t.location}|{quals}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def _tour_sort_key(t: Tour) -> tuple:
    """
    Stable sort key for deterministic tour ordering.

    Key components (in priority order):
        1. start_time (minutes from midnight)
        2. end_time (minutes from midnight)
        3. canonical fingerprint (SHA256 of intrinsic properties)
        4. tour.id (for tie-breaking duplicate instances)

    NOTE: tour.id is included LAST to break ties for duplicate instances
    (where intrinsic properties are identical). The tour.id format is
    "T{instance_id}" where instance_id comes from the database, ensuring
    canonical ordering even for duplicates from count > 1 expansion.
    """
    start_min = t.start_time.hour * 60 + t.start_time.minute
    end_min = t.end_time.hour * 60 + t.end_time.minute
    fingerprint = _tour_fingerprint(t)
    # Add tour.id as final tie-breaker for duplicate instances
    return (start_min, end_min, fingerprint, t.id)


def _block_key(tours: list[Tour]) -> str:
    """
    Generate SHA256 block_key from canonical block description.

    Canonical format uses tour fingerprints (NOT tour_ids):
        "fingerprint1|fingerprint2|..." (sorted)

    This provides deterministic tie-breaking when multiple valid blocks exist,
    and is stable across different database states.
    """
    # Sort by fingerprint, then concatenate
    fingerprints = sorted(_tour_fingerprint(t) for t in tours)
    canonical = "|".join(fingerprints)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _select_deterministic(candidates: list, key_fn) -> any:
    """
    Deterministically select from candidates using stable sort.

    Instead of random.choice(), we sort by key_fn and take first.
    This ensures identical selection across all runs.
    """
    if not candidates:
        return None
    sorted_cands = sorted(candidates, key=key_fn)
    return sorted_cands[0]


def partition_tours_into_blocks(
    tours: list[Tour],
    seed: int = 94  # DEPRECATED: kept for API compatibility, ignored
) -> list[Block]:
    """
    DETERMINISTIC partition of tours into blocks using stable sort keys.

    This is the core V2 partitioning logic, refactored for determinism (PR-4).
    NO random.seed(), random.shuffle(), or random.choice() - guaranteed reproducible.

    Priority:
        1. 3er blocks (triples)
        2. 2er-regular blocks (30-60min gaps)
        3. 2er-split blocks (exactly 240-360min gaps)
        4. 1er blocks (singletons)

    Determinism Strategy:
        - Tours sorted by stable key: (start_time, end_time, tour_id)
        - Candidate selection uses first-by-stable-key (not random)
        - Block IDs include SHA256 hash for unique identification

    Args:
        tours: List of Tour objects
        seed: DEPRECATED, ignored (kept for API compatibility)

    Returns:
        List of Block objects (disjoint partition)
    """
    if seed != 94:
        print(f"[Partitioning] WARNING: seed parameter is DEPRECATED and ignored (deterministic mode)")
    print(f"[Partitioning] DETERMINISTIC mode, {len(tours)} tours...")

    tours_by_day = defaultdict(list)
    for t in tours:
        tours_by_day[t.day].append(t)

    final_blocks = []

    # Process days in deterministic order (sorted by day enum value)
    for day in sorted(tours_by_day.keys(), key=lambda d: d.value):
        day_tours = tours_by_day[day]

        # Sort by stable key for deterministic processing order
        day_tours.sort(key=_tour_sort_key)
        active_tours = set(t.id for t in day_tours)

        def calc_gap(t1, t2):
            """Calculate gap in minutes between two tours."""
            e = t1.end_time.hour * 60 + t1.end_time.minute
            s = t2.start_time.hour * 60 + t2.start_time.minute
            return s - e

        def is_reg(gap):
            """Check if gap qualifies for regular 2er (30-60min)."""
            return 30 <= gap <= 60

        def is_split(gap):
            """Check if gap qualifies for split 2er (4-6 hours / 240-360min)."""
            return 240 <= gap <= 360

        def mark_used(ts):
            """Remove tours from active set."""
            for t in ts:
                active_tours.discard(t.id)

        # Phase 1: 3er blocks (DETERMINISTIC)
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]

            for i in range(len(curr)):
                t1 = curr[i]
                candidates_t2 = []
                for j in range(i + 1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g):  # 3er-chain: NUR 30-60min Gaps
                        candidates_t2.append(t2)

                if not candidates_t2:
                    continue

                # DETERMINISTIC: sort by stable key instead of random.shuffle
                candidates_t2.sort(key=_tour_sort_key)

                for t2 in candidates_t2:
                    # Find t3 candidates
                    candidates_t3 = []
                    for t3 in curr:
                        if t3.start_time <= t2.end_time:
                            continue
                        g2 = calc_gap(t2, t3)
                        if is_reg(g2):  # 3er-chain: NUR 30-60min Gaps
                            # Check span - 3er blocks use 16h span limit
                            span = (t3.end_time.hour * 60 + t3.end_time.minute) - \
                                   (t1.start_time.hour * 60 + t1.start_time.minute)
                            if span <= 16 * 60:  # 16h max span for 3er
                                candidates_t3.append(t3)

                    if candidates_t3:
                        # DETERMINISTIC: select first by stable key instead of random.choice
                        t3 = _select_deterministic(candidates_t3, _tour_sort_key)
                        block_hash = _block_key([t1, t2, t3])
                        blk = Block(
                            id=f"B3-{t1.id}-{block_hash}",
                            day=day,
                            tours=[t1, t2, t3]
                        )
                        final_blocks.append(blk)
                        mark_used([t1, t2, t3])
                        found = True
                        break
                if found:
                    break
            if not found:
                break

        # Phase 2: 2er-regular blocks (DETERMINISTIC)
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i + 1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g):
                        span = (t2.end_time.hour * 60 + t2.end_time.minute) - \
                               (t1.start_time.hour * 60 + t1.start_time.minute)
                        if span <= 14 * 60:  # 14h max span for regular
                            cands.append(t2)

                if cands:
                    # DETERMINISTIC: select first by stable key instead of random.choice
                    t2 = _select_deterministic(cands, _tour_sort_key)
                    block_hash = _block_key([t1, t2])
                    blk = Block(
                        id=f"B2R-{t1.id}-{block_hash}",
                        day=day,
                        tours=[t1, t2]
                    )
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found:
                break

        # Phase 3: 2er-split blocks (DETERMINISTIC)
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i + 1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_split(g):
                        span = (t2.end_time.hour * 60 + t2.end_time.minute) - \
                               (t1.start_time.hour * 60 + t1.start_time.minute)
                        if span <= 16 * 60:  # 16h max span for split
                            cands.append(t2)
                if cands:
                    # DETERMINISTIC: select first by stable key instead of random.choice
                    t2 = _select_deterministic(cands, _tour_sort_key)
                    block_hash = _block_key([t1, t2])
                    blk = Block(
                        id=f"B2S-{t1.id}-{block_hash}",
                        day=day,
                        tours=[t1, t2]
                    )
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found:
                break

        # Phase 4: 1er (singletons) - already deterministic by sorted order
        curr_day_tours = [t for t in day_tours if t.id in active_tours]
        for t in curr_day_tours:
            block_hash = _block_key([t])
            blk = Block(
                id=f"B1-{t.id}-{block_hash}",
                day=day,
                tours=[t]
            )
            final_blocks.append(blk)
            active_tours.discard(t.id)

    # Summary
    count_3er = sum(1 for b in final_blocks if len(b.tours) == 3)
    count_2er = sum(1 for b in final_blocks if len(b.tours) == 2)
    count_1er = sum(1 for b in final_blocks if len(b.tours) == 1)
    print(f"[Partitioning] Result: {len(final_blocks)} blocks (3er:{count_3er}, 2er:{count_2er}, 1er:{count_1er})")

    return final_blocks


# Test function
if __name__ == "__main__":
    print("="*70)
    print("V2 Solver Integration - Test Mode")
    print("="*70)

    # Create test tour_instances
    test_instances = [
        {
            "id": 1,
            "day": 1,  # Monday
            "start_ts": time(6, 0),
            "end_ts": time(10, 0),
            "depot": "West",
            "skill": None,
            "work_hours": 4.0,
            "duration_min": 240,
            "crosses_midnight": False
        },
        {
            "id": 2,
            "day": 1,  # Monday
            "start_ts": time(10, 45),  # 45min gap from tour 1
            "end_ts": time(14, 45),
            "depot": "West",
            "skill": None,
            "work_hours": 4.0,
            "duration_min": 240,
            "crosses_midnight": False
        },
        {
            "id": 3,
            "day": 2,  # Tuesday
            "start_ts": time(8, 0),
            "end_ts": time(12, 0),
            "depot": "Nord",
            "skill": None,
            "work_hours": 4.0,
            "duration_min": 240,
            "crosses_midnight": False
        },
    ]

    assignments = solve_with_v2_solver(test_instances, seed=94)

    print("\nAssignments:")
    for a in assignments:
        print(f"  Driver {a['driver_id']}: Tour {a['tour_instance_id']} on Day {a['day']} ({a['metadata']['block_type']})")
