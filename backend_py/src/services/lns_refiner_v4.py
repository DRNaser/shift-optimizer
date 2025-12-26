"""
LNS REFINER v4 - Assignment Phase Optimization
==============================================
Minimal destroy/repair for v4 solver's assignment phase.

Strategy:
- Phase 1 (block selection) stays untouched
- Phase 2 (greedy assignment) output is refined via LNS
- Destroy: Remove 20-35% of drivers' blocks
- Repair: Small CP-SAT to reassign those blocks optimally

Determinism:
- All randomness seeded
- Sorted iteration over sets
- CP-SAT with fixed search strategy
"""

import random
import logging
import traceback
from dataclasses import dataclass, field
from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday

logger = logging.getLogger("LNS_V4")

# Constants
DAY_MINUTES = 24 * 60  # 1440 minutes per day


def log_progress(msg: str):
    """Print with flush for immediate visibility."""
    print(f"[LNS] {msg}", flush=True)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class LNSConfigV4:
    """Configuration for LNS refinement - Production Settings."""
    # ==========================================================================
    # CORE LOOP SETTINGS
    # ==========================================================================
    max_iterations: int = 300
    repair_time_limit: float = 5.0  # seconds per repair (faster iterations)
    lns_time_limit: float = 60.0    # Global time limit for entire LNS phase
    destroy_fraction: float = 0.15   # Only for random LNS fallback
    seed: int = 42
    
    # Early stopping (only count real failures - structurally feasible neighborhoods)
    early_stop_after_failures: int = 20  # Stop sooner at plateau
    
    # ==========================================================================
    # DRIVER CONSTRAINTS
    # ==========================================================================
    min_hours_per_fte: float = 42.0
    max_hours_per_fte: float = 53.0
    max_daily_span_minutes: int = 14 * 60  # 14 hours
    min_rest_minutes: int = 11 * 60        # 11 hours
    max_tours_per_day: int = 3
    
    # ==========================================================================
    # OBJECTIVE WEIGHTS (Production Hierarchy)
    # ==========================================================================
    w_total_used_driver: int = 10_000      # Baseline cost for using any driver
    w_pt_used: int = 50_000                # PT driver is expensive
    w_new_driver: int = 200_000            # Opening new driver is very expensive
    w_pt_new: int = 200_000                # Opening new PT is extremely expensive
    
    # Soft shaping
    w_tight_rest_11h: int = 200            # Soft penalty if min rest == 11.0h
    w_next_day_two_tours_after_heavy: int = 150  # Prefer 1 tour after heavy day
    
    # Backward compatibility (PT block costs)
    w_pt_weekday_block: int = 500          # Per weekday block to PT
    w_pt_saturday_block: int = 500         # Per Saturday block to PT
    
    # ==========================================================================
    # 3-TOUR HEAVY-DAY RECOVERY
    # ==========================================================================
    min_rest_after_3t_minutes: int = 14 * 60  # 14h rest after 3-tour day (HARD)
    max_next_day_tours_after_3t: int = 2      # Max tours after 3-tour day (HARD)
    target_next_day_tours_after_3t: int = 1   # Prefer 1 tour (SOFT)
    w_next_day_tours_excess: int = 150        # Penalty for 2nd tour after heavy
    
    # ==========================================================================
    # RECEIVER GATE (Critical for avoiding INFEASIBLE)
    # ==========================================================================
    min_alt_receivers_for_pt_elimination: int = 3  # Skip PT if < 3 receivers
    candidate_cap_per_block: int = 60              # Max candidates per block
    
    # ==========================================================================
    # PINNED EJECTION GATE (Prevent orphan ejection)
    # ==========================================================================
    min_receivers_to_eject: int = 5  # Don't eject blocks with <= N receivers
    
    # ==========================================================================
    # ADAPTIVE EJECTION (Escalation strategy: 2→4→8→12)
    # ==========================================================================
    initial_max_ejections: int = 2    # Start with 2 ejections
    max_ejections_cap: int = 12       # Cap at 12 ejections
    
    # ==========================================================================
    # PT ELIMINATION STRATEGY
    # ==========================================================================
    enable_pt_elimination: bool = True
    pt_elimination_fraction: float = 0.3
    max_pt_elimination_drivers: int = 5
    pt_min_hours: float = 9.0  # Minimum hours for PT (soft)
    repair_prefer_fte: bool = True
    
    # ==========================================================================
    # CONSOLIDATION
    # ==========================================================================
    enable_consolidation: bool = True
    max_consolidation_iterations: int = 5


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class BlockInfo:
    """Block info for LNS repair model."""
    block_id: str
    day_idx: int  # 0..6
    start_min: int  # minutes from midnight
    end_min: int
    duration_min: int
    tour_count: int


# =============================================================================
# DRIVER PROFILE CACHE (for fast feasibility checks)
# =============================================================================

@dataclass
class DriverProfile:
    """
    Pre-computed driver profile for fast feasibility checks.
    Built once per iteration, avoids O(n) list rebuilding on each check.
    """
    driver_id: str
    driver_type: str  # "FTE" or "PT"
    week_minutes: int  # Total minutes worked in week
    
    # Per-day data (index 0-6)
    tours_on_day: list[int] = field(default_factory=lambda: [0]*7)
    first_start: list[int] = field(default_factory=lambda: [None]*7)  # First block start
    last_end: list[int] = field(default_factory=lambda: [None]*7)     # Last block end
    blocks_by_day: list[list[tuple]] = field(default_factory=lambda: [[] for _ in range(7)])
    # Each block tuple: (start_min, end_min, tour_count, block_id)
    
    @property
    def heavy_days(self) -> list[bool]:
        """Days with 3 tours (trigger 14h rest rule)."""
        return [t >= 3 for t in self.tours_on_day]


def build_driver_profile(
    driver_id: str,
    driver_type: str,
    blocks: list,  # List of Block objects
    get_day_idx_fn,  # Function to get day index from Weekday
) -> DriverProfile:
    """Build a DriverProfile from a driver's blocks."""
    profile = DriverProfile(
        driver_id=driver_id,
        driver_type=driver_type,
        week_minutes=0,
        tours_on_day=[0]*7,
        first_start=[None]*7,
        last_end=[None]*7,
        blocks_by_day=[[] for _ in range(7)],
    )
    
    for block in blocks:
        day_idx = get_day_idx_fn(block.day)
        start_min = time_to_minutes(block.first_start)
        end_min = time_to_minutes(block.last_end)
        duration = end_min - start_min
        tour_count = len(block.tours) if hasattr(block, 'tours') else 1
        
        profile.week_minutes += duration
        profile.tours_on_day[day_idx] += tour_count
        
        # Update first/last
        if profile.first_start[day_idx] is None or start_min < profile.first_start[day_idx]:
            profile.first_start[day_idx] = start_min
        if profile.last_end[day_idx] is None or end_min > profile.last_end[day_idx]:
            profile.last_end[day_idx] = end_min
        
        profile.blocks_by_day[day_idx].append((start_min, end_min, tour_count, block.id))
    
    return profile


def time_to_minutes(t) -> int:
    """Convert time to minutes from midnight."""
    if hasattr(t, 'hour'):
        return t.hour * 60 + t.minute
    return int(t)


def fast_can_assign(
    profile: DriverProfile,
    block_day: int,
    block_start: int,
    block_end: int,
    block_tours: int,
    block_duration: int,
    config: 'LNSConfigV4',
) -> tuple[bool, str]:
    """
    Fast feasibility check using pre-computed profile.
    O(k) per check where k = blocks on that day (small).
    
    No list rebuilding, no Block object creation.
    """
    # HARD CONSTRAINTS IMPORT
    from src.domain.constraints import HARD_CONSTRAINTS
    
    # 0. MAX_BLOCKS_PER_DAY check (HARD CONSTRAINT - added to fix violations)
    current_blocks = len(profile.blocks_by_day[block_day])
    if current_blocks >= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY:
        return False, f"blocks_per_day ({current_blocks}+1>{HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY})"
    
    # 1. Overlap check with existing blocks on same day
    for (start, end, _, _) in profile.blocks_by_day[block_day]:
        # Overlap if intervals intersect
        if block_start < end and block_end > start:
            return False, "overlap"
    
    # 2. Tours per day check
    current_tours = profile.tours_on_day[block_day]
    if current_tours + block_tours > config.max_tours_per_day:
        return False, f"tours_per_day ({current_tours}+{block_tours}>{config.max_tours_per_day})"
    
    # 3. Rest from previous day (11h, or 14h after heavy)
    if block_day > 0 and profile.last_end[block_day - 1] is not None:
        prev_end = profile.last_end[block_day - 1]
        rest = (block_start + DAY_MINUTES) - prev_end
        
        # Check if previous day was heavy (3 tours)
        if profile.tours_on_day[block_day - 1] >= 3:
            if rest < config.min_rest_after_3t_minutes:
                return False, f"rest_after_heavy ({rest/60:.1f}h<14h)"
        else:
            if rest < config.min_rest_minutes:
                return False, f"rest_from_prev ({rest/60:.1f}h<11h)"
    
    # 4. Rest to next day
    if block_day < 6 and profile.first_start[block_day + 1] is not None:
        next_start = profile.first_start[block_day + 1]
        rest = (next_start + DAY_MINUTES) - block_end
        if rest < config.min_rest_minutes:
            return False, f"rest_to_next ({rest/60:.1f}h<11h)"
    
    # 5. MAX_WEEKLY_HOURS check (HARD CONSTRAINT - applies to ALL drivers)
    max_weekly_minutes = int(HARD_CONSTRAINTS.MAX_WEEKLY_HOURS * 60)
    if profile.week_minutes + block_duration > max_weekly_minutes:
        return False, f"max_weekly_hours ({(profile.week_minutes + block_duration)/60:.1f}h>{HARD_CONSTRAINTS.MAX_WEEKLY_HOURS}h)"
    
    # 5b. Stricter FTE weekly hours check
    if profile.driver_type == "FTE":
        max_fte_minutes = int(config.max_hours_per_fte * 60)
        if profile.week_minutes + block_duration > max_fte_minutes:
            return False, "weekly_hours_fte"
    
    # 6. Heavy-day recovery: if adding causes heavy day, check next day tours
    if current_tours + block_tours >= 3 and block_day < 6:
        # This would make today a heavy day
        next_day_tours = profile.tours_on_day[block_day + 1]
        if next_day_tours > config.max_next_day_tours_after_3t:
            return False, f"heavy_day_next_tours ({next_day_tours}>{config.max_next_day_tours_after_3t})"
    
    return True, ""


@dataclass 
class DriverState:
    """Driver state for LNS repair model."""
    driver_id: str
    driver_type: str  # "FTE" or "PT"
    fixed_blocks: list[BlockInfo] = field(default_factory=list)
    destroyed_blocks: list[BlockInfo] = field(default_factory=list)
    was_used_in_incumbent: bool = False  # Track if driver was used before destroy
    
    @property
    def fixed_minutes(self) -> int:
        return sum(b.duration_min for b in self.fixed_blocks)
    
    def fixed_minutes_on_day(self, day_idx: int) -> int:
        return sum(b.duration_min for b in self.fixed_blocks if b.day_idx == day_idx)
    
    def fixed_tours_on_day(self, day_idx: int) -> int:
        return sum(b.tour_count for b in self.fixed_blocks if b.day_idx == day_idx)


# =============================================================================
# HELPERS
# =============================================================================

def time_to_minutes(t) -> int:
    """Convert time object to minutes from midnight."""
    return t.hour * 60 + t.minute


def block_to_info(block: Block, day_idx: int) -> BlockInfo:
    """Convert v4 Block to BlockInfo for LNS."""
    try:
        # PERFORMANCE FIX: Disabled excessive introspection logging
        # log_progress(f"  Converting block {block.id} (type={type(block).__name__})")
        # log_progress(f"    Block attributes: {dir(block)}")  # HUGE OVERHEAD!
        # log_progress(f"    Getting first_start...")
        start_min = time_to_minutes(block.first_start)
        # log_progress(f"    first_start OK: {block.first_start}")
        # log_progress(f"    Getting last_end...")
        end_min = time_to_minutes(block.last_end)
        # log_progress(f"    last_end OK: {block.last_end}")
        duration_min = int(block.total_work_hours * 60)
        # log_progress(f"    Block conversion complete: start={start_min}, end={end_min}, duration={duration_min}")
        return BlockInfo(
            block_id=block.id,
            day_idx=day_idx,
            start_min=start_min,
            end_min=end_min,
            duration_min=duration_min,
            tour_count=len(block.tours),
        )
    except AttributeError as e:
        log_progress(f"  ERROR converting block {block.id}: {e}")
        log_progress(f"  Block type: {type(block)}")
        log_progress(f"  Block dir: {dir(block)}")
        log_progress(f"  Traceback: {traceback.format_exc()}")
        raise


def blocks_overlap(b1: BlockInfo, b2: BlockInfo) -> bool:
    """Check if two blocks overlap in time (same day assumed)."""
    return not (b1.end_min <= b2.start_min or b2.end_min <= b1.start_min)


DAY_MAP = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
}


def get_day_idx(day) -> int:
    """Get day index from Weekday or string."""
    if isinstance(day, Weekday):
        return DAY_MAP.get(day.value, 0)
    return DAY_MAP.get(str(day), 0)


# =============================================================================
# DESTROY OPERATOR
# =============================================================================

def destroy_drivers(
    assignments: list,  # list[DriverAssignment]
    fraction: float,
    rng: random.Random,
) -> tuple[list[DriverState], list[BlockInfo]]:
    """
    Destroy a fraction of drivers by removing their blocks.
    
    Returns:
        - driver_states: List of DriverState with fixed/destroyed blocks
        - blocks_to_repair: List of BlockInfo that need reassignment
    """
    log_progress(f"destroy_drivers: {len(assignments)} assignments, fraction={fraction}")
    
    # Sort for determinism
    sorted_assignments = sorted(assignments, key=lambda a: a.driver_id)
    log_progress(f"  Sorted {len(sorted_assignments)} assignments")
    
    # Select drivers to destroy
    num_to_destroy = max(1, int(len(sorted_assignments) * fraction))
    destroy_indices = rng.sample(range(len(sorted_assignments)), min(num_to_destroy, len(sorted_assignments)))
    destroy_set = set(destroy_indices)
    log_progress(f"  Will destroy drivers at indices: {sorted(destroy_set)}")
    
    driver_states = []
    blocks_to_repair = []
    
    for idx, assignment in enumerate(sorted_assignments):
        log_progress(f"  Processing assignment[{idx}]: driver={assignment.driver_id}")
        
        # Track if this driver was used in incumbent (before destroy)
        was_used = len(assignment.blocks) > 0
        
        driver = DriverState(
            driver_id=assignment.driver_id,
            driver_type=assignment.driver_type,
            was_used_in_incumbent=was_used,  # Set flag BEFORE destroying
        )
        
        log_progress(f"    Processing {len(assignment.blocks)} blocks...")
        for block_idx, block in enumerate(sorted(assignment.blocks, key=lambda b: b.id)):
            log_progress(f"      Block[{block_idx}]: id={block.id}")
            day_idx = get_day_idx(block.day)
            block_info = block_to_info(block, day_idx)
            
            if idx in destroy_set:
                driver.destroyed_blocks.append(block_info)
                blocks_to_repair.append(block_info)
                log_progress(f"      -> DESTROYED")
            else:
                driver.fixed_blocks.append(block_info)
                log_progress(f"      -> FIXED")
        
        driver_states.append(driver)
    
    log_progress(f"destroy_drivers COMPLETE: {len(blocks_to_repair)} blocks to repair from {num_to_destroy} drivers")
    return driver_states, blocks_to_repair


def destroy_pt_drivers(
    assignments: list,  # list[DriverAssignment]
    config: 'LNSConfigV4',
    rng: random.Random,
) -> tuple[list[DriverState], list[BlockInfo]]:
    """
    PT-TARGETED DESTROY: Specifically targets PT drivers for elimination.
    
    Strategy:
    1. Prioritize low-utilization PT drivers (hours < pt_min_hours)
    2. Fall back to random PT if no low-util PT found
    3. Destroy selected PT drivers completely, redistribute their blocks
    
    This enables LNS to focus optimization on PT reduction.
    
    Returns:
        - driver_states: List of DriverState with fixed/destroyed blocks
        - blocks_to_repair: List of BlockInfo that need reassignment
    """
    log_progress(f"destroy_pt_drivers: {len(assignments)} assignments")
    
    # Separate PT and FTE drivers
    pt_drivers = [a for a in assignments if a.driver_type == "PT" and a.blocks]
    fte_drivers = [a for a in assignments if a.driver_type == "FTE"]
    
    log_progress(f"  PT drivers: {len(pt_drivers)}, FTE drivers: {len(fte_drivers)}")
    
    if not pt_drivers:
        log_progress("  No PT drivers to destroy, falling back to random destroy")
        return destroy_drivers(assignments, config.destroy_fraction, rng)
    
    # Prioritize low-utilization PT (under pt_min_hours)
    low_util_pt = [a for a in pt_drivers if a.total_hours < config.pt_min_hours]
    log_progress(f"  Low-utilization PT (< {config.pt_min_hours}h): {len(low_util_pt)}")
    
    # Select PT drivers to destroy
    if low_util_pt:
        # Prefer destroying low-util PT
        candidates = low_util_pt
    else:
        # All PT are well-utilized, pick random PT
        candidates = pt_drivers
    
    # Number to destroy: be more aggressive to enable consolidation
    # Destroy at least 3 or 30% of candidates, capped at max_pt_elimination_drivers
    num_to_destroy = max(3, int(len(candidates) * config.pt_elimination_fraction))
    num_to_destroy = min(num_to_destroy, config.max_pt_elimination_drivers, len(candidates))
    
    # Sort by hours (ascending) so we pick lowest-util first, then sample
    sorted_candidates = sorted(candidates, key=lambda a: a.total_hours)
    selected_pt = sorted_candidates[:num_to_destroy]  # Take lowest utilization
    
    # If we want some randomness, use rng.sample instead:
    # selected_pt = rng.sample(candidates, num_to_destroy)
    
    selected_ids = {a.driver_id for a in selected_pt}
    
    log_progress(f"  Destroying {len(selected_pt)} PT drivers: {list(selected_ids)}")
    for pt in selected_pt:
        log_progress(f"    {pt.driver_id}: {pt.total_hours:.1f}h, {len(pt.blocks)} blocks")
    
    # Build driver states
    driver_states = []
    blocks_to_repair = []
    
    for assignment in sorted(assignments, key=lambda a: a.driver_id):
        was_used = len(assignment.blocks) > 0
        is_destroyed = assignment.driver_id in selected_ids
        
        driver = DriverState(
            driver_id=assignment.driver_id,
            driver_type=assignment.driver_type,
            was_used_in_incumbent=was_used,
        )
        
        for block in sorted(assignment.blocks, key=lambda b: b.id):
            day_idx = get_day_idx(block.day)
            block_info = block_to_info(block, day_idx)
            
            if is_destroyed:
                driver.destroyed_blocks.append(block_info)
                blocks_to_repair.append(block_info)
            else:
                driver.fixed_blocks.append(block_info)
        
        driver_states.append(driver)
    
    log_progress(f"destroy_pt_drivers COMPLETE: {len(blocks_to_repair)} blocks from {len(selected_pt)} PT drivers")
    return driver_states, blocks_to_repair


def destroy_pt_with_ejections(
    assignments: list,  # list[DriverAssignment]
    config: 'LNSConfigV4',
    rng: random.Random,
) -> tuple[list[DriverState], list[BlockInfo], set]:
    """
    EJECTION CHAIN DESTROY: Proper PT elimination with blocking block ejection.
    
    Strategy:
    1. Select a PT singleton (1 block or low hours)
    2. Find best target FTE driver (lowest hours)
    3. Identify why PT block doesn't fit (rest, hours, tours conflict)
    4. Eject blocking blocks from target driver
    5. Create repair set = {PT block} + {ejected blocks}
    6. Ban the PT driver from repair candidates
    
    Returns:
        - driver_states: List of DriverState with fixed/destroyed blocks
        - blocks_to_repair: List of BlockInfo that need reassignment
        - banned_driver_ids: Set of driver IDs that should be banned from repair
    """
    log_progress("destroy_pt_with_ejections: Starting ejection chain analysis")
    
    # Find PT singletons (best candidates for elimination)
    pt_singletons = [a for a in assignments if a.driver_type == "PT" and len(a.blocks) == 1]
    pt_low_util = [a for a in assignments if a.driver_type == "PT" and a.total_hours < config.pt_min_hours]
    
    # Combine and deduplicate
    pt_candidates = {a.driver_id: a for a in pt_singletons + pt_low_util}
    
    if not pt_candidates:
        log_progress("  No PT singletons or low-util PT, falling back to random destroy")
        states, blocks = destroy_drivers(assignments, config.destroy_fraction, rng)
        return states, blocks, set()
    
    log_progress(f"  Found {len(pt_candidates)} PT elimination candidates")
    
    # ==========================================================================
    # RECEIVER GATE: Skip PT if it has < min_alt_receivers feasible receivers
    # ==========================================================================
    # Build quick lookup of all driver states (excluding PT candidates) to check receiver count
    non_pt_assignments = [a for a in assignments if a.driver_id not in pt_candidates]
    
    # Sort PT candidates by hours (lowest first - easiest to eliminate)
    sorted_pt = sorted(pt_candidates.values(), key=lambda a: a.total_hours)
    
    # ==========================================================================
    # BUILD DRIVER PROFILES ONCE (major optimization - O(n) instead of O(n³))
    # ==========================================================================
    profiles = {}
    for a in non_pt_assignments:
        profiles[a.driver_id] = build_driver_profile(
            a.driver_id, a.driver_type, a.blocks, get_day_idx
        )
    
    target_pt = None
    target_pt_block_info = None
    
    for pt_candidate in sorted_pt:
        if len(pt_candidate.blocks) == 0:
            continue
        
        pt_block = pt_candidate.blocks[0]
        pt_block_info = block_to_info(pt_block, get_day_idx(pt_block.day))
        
        # Extract block params for fast_can_assign
        b_day = pt_block_info.day_idx
        b_start = pt_block_info.start_min
        b_end = pt_block_info.end_min
        b_tours = pt_block_info.tour_count
        b_duration = pt_block_info.duration_min
        
        # Count feasible receivers using cached profiles (FAST)
        receiver_count = 0
        for profile in profiles.values():
            allowed, _ = fast_can_assign(
                profile, b_day, b_start, b_end, b_tours, b_duration, config
            )
            if allowed:
                receiver_count += 1
                # Early stop if we have enough receivers
                if receiver_count >= config.min_alt_receivers_for_pt_elimination:
                    break
        
        log_progress(f"  PT {pt_candidate.driver_id}: {receiver_count}+ feasible receivers")
        
        # Check against receiver gate
        if receiver_count >= config.min_alt_receivers_for_pt_elimination:
            target_pt = pt_candidate
            target_pt_block_info = pt_block_info
            log_progress(f"  SELECTED: {target_pt.driver_id} ({target_pt.total_hours:.1f}h) with {receiver_count}+ receivers")
            break
        else:
            log_progress(f"  SKIPPED: {pt_candidate.driver_id} has only {receiver_count} receivers (< {config.min_alt_receivers_for_pt_elimination})")
    
    if target_pt is None:
        log_progress("  No eliminable PT found (all have < min receivers), falling back to random destroy")
        states, blocks = destroy_drivers(assignments, config.destroy_fraction, rng)
        return states, blocks, set()
    
    target_pt_block = target_pt.blocks[0]
    log_progress(f"  PT Block: {target_pt_block.id} Day {get_day_idx(target_pt_block.day)}")
    
    # Find potential target FTE drivers (sorted by lowest hours = most capacity)
    fte_drivers = [a for a in assignments if a.driver_type == "FTE" and a.blocks]
    fte_drivers.sort(key=lambda a: a.total_hours)
    
    blocks_to_repair = [target_pt_block_info]
    ejected_blocks = []
    banned_driver_ids = {target_pt.driver_id}  # Ban the PT driver
    
    # Try to find an FTE that can absorb with ejections
    for fte in fte_drivers[:10]:  # Check top 10 FTEs with most capacity
        # Convert FTE blocks to BlockInfo for analysis
        fte_block_infos = [block_to_info(b, get_day_idx(b.day)) for b in fte.blocks]
        
        # Find blocking blocks
        blocking = find_blocking_blocks(
            target_pt_block_info,
            fte_block_infos,
            fte.total_hours,
            config
        )
        
        if blocking:
            log_progress(f"  FTE {fte.driver_id}: {len(blocking)} blocking blocks")
            # Add blocking blocks to repair set
            for block_info in blocking:
                if block_info not in ejected_blocks:
                    ejected_blocks.append(block_info)
            break  # Found a target FTE with blocking blocks
    
    # Add ejected blocks to repair set
    blocks_to_repair.extend(ejected_blocks)
    
    log_progress(f"  Ejection set: 1 PT block + {len(ejected_blocks)} ejected = {len(blocks_to_repair)} total")
    
    # ==========================================================================
    # PRE-CHECK: Verify repair blocks have multiple receivers (not orphan-bound)
    # ==========================================================================
    # Build temporary driver states to check feasibility
    temp_driver_states = []
    for assignment in assignments:
        if assignment.driver_id in banned_driver_ids:
            continue
        temp_state = DriverState(
            driver_id=assignment.driver_id,
            driver_type=assignment.driver_type,
            was_used_in_incumbent=len(assignment.blocks) > 0,
        )
        ejected_block_ids = {b.block_id for b in ejected_blocks}
        for block in assignment.blocks:
            block_info = block_to_info(block, get_day_idx(block.day))
            if block.id not in ejected_block_ids:
                temp_state.fixed_blocks.append(block_info)
        temp_driver_states.append(temp_state)
    
    # Check receiver counts
    for block in blocks_to_repair:
        receivers = []
        for d in temp_driver_states:
            allowed, _ = can_driver_receive_block(d, block, config)
            if allowed:
                receivers.append(d.driver_id)
        if len(receivers) <= 2:
            log_progress(f"  WARNING: Block {block.block_id} has only {len(receivers)} receivers - may be orphan-bound")
    
    # Build driver states
    driver_states = []
    ejected_block_ids = {b.block_id for b in ejected_blocks}
    
    for assignment in sorted(assignments, key=lambda a: a.driver_id):
        was_used = len(assignment.blocks) > 0
        is_banned = assignment.driver_id in banned_driver_ids
        
        driver = DriverState(
            driver_id=assignment.driver_id,
            driver_type=assignment.driver_type,
            was_used_in_incumbent=was_used,
        )
        
        for block in sorted(assignment.blocks, key=lambda b: b.id):
            day_idx = get_day_idx(block.day)
            block_info = block_to_info(block, day_idx)
            
            if is_banned or block.id in ejected_block_ids:
                driver.destroyed_blocks.append(block_info)
            else:
                driver.fixed_blocks.append(block_info)
        
        driver_states.append(driver)
    
    log_progress(f"destroy_pt_with_ejections COMPLETE: {len(blocks_to_repair)} blocks, {len(banned_driver_ids)} banned")
    return driver_states, blocks_to_repair, banned_driver_ids


def find_blocking_blocks(
    pt_block: BlockInfo,
    fte_blocks: list[BlockInfo],
    fte_total_hours: float,
    config: 'LNSConfigV4'
) -> list[BlockInfo]:
    """
    Find which blocks in FTE's schedule prevent inserting the PT block.
    
    Checks:
    1. Rest conflicts (11h, or 14h after heavy day)
    2. Same-day overlap
    3. Weekly hours would exceed max
    
    Returns list of blocking blocks to eject.
    """
    blocking = []
    pt_day = pt_block.day_idx
    
    # Check same-day conflicts (overlap or span)
    same_day_blocks = [b for b in fte_blocks if b.day_idx == pt_day]
    for b in same_day_blocks:
        if blocks_overlap(pt_block, b):
            blocking.append(b)
            continue
        # Check span violation
        combined_start = min(pt_block.start_min, b.start_min)
        combined_end = max(pt_block.end_min, b.end_min)
        if combined_end - combined_start > config.max_daily_span_minutes:
            blocking.append(b)
    
    # Check previous day rest conflict
    prev_day_blocks = [b for b in fte_blocks if b.day_idx == pt_day - 1]
    for b in prev_day_blocks:
        rest = (pt_block.start_min + 1440) - b.end_min
        # Check if previous day was heavy (3+ tours)
        prev_day_tours = sum(blk.tour_count for blk in prev_day_blocks)
        min_rest = config.min_rest_after_3t_minutes if prev_day_tours >= 3 else config.min_rest_minutes
        if rest < min_rest:
            blocking.append(b)
    
    # Check next day rest conflict
    next_day_blocks = [b for b in fte_blocks if b.day_idx == pt_day + 1]
    for b in next_day_blocks:
        rest = (b.start_min + 1440) - pt_block.end_min
        # Check if today would become heavy with PT block
        today_tours = sum(blk.tour_count for blk in same_day_blocks) + pt_block.tour_count
        min_rest = config.min_rest_after_3t_minutes if today_tours >= 3 else config.min_rest_minutes
        if rest < min_rest:
            blocking.append(b)
    
    # Check hours conflict - if adding PT would exceed max, eject smallest block
    pt_duration_hours = pt_block.duration_min / 60.0
    if fte_total_hours + pt_duration_hours > config.max_hours_per_fte:
        excess_hours = fte_total_hours + pt_duration_hours - config.max_hours_per_fte
        # Find smallest block(s) to eject to make room
        sorted_by_duration = sorted(fte_blocks, key=lambda b: b.duration_min)
        ejected_hours = 0
        for b in sorted_by_duration:
            if b not in blocking:
                blocking.append(b)
                ejected_hours += b.duration_min / 60.0
                if ejected_hours >= excess_hours:
                    break
    
    # Limit to max 3 ejections to keep problem small
    return blocking[:3]


# =============================================================================
# PRE-REPAIR DIAGNOSTICS
# =============================================================================

def diagnose_fixed_schedule(
    candidate_drivers: list[DriverState],
    config: LNSConfigV4,
) -> list[str]:
    """
    Check if the fixed schedule itself violates repair constraints.
    
    Returns list of violations found.
    """
    violations = []
    
    for d in candidate_drivers:
        # Check 1: tours per day <= max_tours_per_day
        for day_idx in range(7):
            fixed_tours = d.fixed_tours_on_day(day_idx)
            if fixed_tours > config.max_tours_per_day:
                violations.append(
                    f"[CONSTRAINT MISMATCH] Driver {d.driver_id} Day {day_idx}: "
                    f"{fixed_tours} tours > max {config.max_tours_per_day}"
                )
        
        # Check 2: weekly hours <= max (FTE only)
        if d.driver_type == "FTE":
            max_minutes = int(config.max_hours_per_fte * 60)
            if d.fixed_minutes > max_minutes:
                violations.append(
                    f"[CONSTRAINT MISMATCH] FTE {d.driver_id}: "
                    f"{d.fixed_minutes/60:.1f}h > max {config.max_hours_per_fte}h"
                )
        
        # Check 3: daily span <= max - DISABLED (split-shifts exceed span but are valid)
        # for day_idx in range(7):
        #     day_blocks = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
        #     if len(day_blocks) >= 2:
        #         min_start = min(fb.start_min for fb in day_blocks)
        #         max_end = max(fb.end_min for fb in day_blocks)
        #         span = max_end - min_start
        #         if span > config.max_daily_span_minutes:
        #             violations.append(
        #                 f"[CONSTRAINT MISMATCH] Driver {d.driver_id} Day {day_idx}: "
        #                 f"span {span/60:.1f}h > max {config.max_daily_span_minutes/60:.1f}h"
        #             )
    
    return violations


def diagnose_block_receivers(
    blocks_to_repair: list[BlockInfo],
    candidate_drivers: list[DriverState],
    config: LNSConfigV4,
) -> dict:
    """
    For each repair block, count how many candidate drivers can receive it.
    
    Returns:
        {
            "orphans": [(block_id, top_reasons), ...],  # blocks with 0 receivers
            "receiver_counts": [(block_id, count), ...],
            "total_feasible": bool,
        }
    """
    result = {
        "orphans": [],
        "receiver_counts": [],
        "total_feasible": True,
    }
    
    for block in blocks_to_repair:
        receivers = []
        rejection_reasons = {}  # reason -> count
        
        for d in candidate_drivers:
            allowed, reason = can_driver_receive_block(d, block, config)
            if allowed:
                receivers.append(d.driver_id)
            else:
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        
        result["receiver_counts"].append((block.block_id, len(receivers)))
        
        if len(receivers) == 0:
            result["total_feasible"] = False
            # Get top 3 rejection reasons
            sorted_reasons = sorted(rejection_reasons.items(), key=lambda x: -x[1])[:3]
            result["orphans"].append((block.block_id, sorted_reasons))
    
    return result


def can_driver_receive_block(
    driver: DriverState,
    block: BlockInfo,
    config: LNSConfigV4,
) -> tuple[bool, str]:
    """
    Check if driver can receive this block, using the SAME constraints as repair model.
    
    Checks:
    1. Overlap with fixed blocks
    2. Tours per day <= max
    3. Daily span <= max
    4. Rest between days >= min
    5. Weekly hours <= max (FTE)
    """
    block_day = block.day_idx
    
    # 1. Overlap check
    fixed_on_day = [fb for fb in driver.fixed_blocks if fb.day_idx == block_day]
    for fb in fixed_on_day:
        if blocks_overlap(block, fb):
            return False, "overlap"
    
    # 2. Tours per day check
    fixed_tours = driver.fixed_tours_on_day(block_day)
    if fixed_tours + block.tour_count > config.max_tours_per_day:
        return False, f"tours_per_day ({fixed_tours}+{block.tour_count}>{config.max_tours_per_day})"
    
    # 3. Daily span check - DISABLED (causes orphan blocks for split-shifts)
    # Split-shifts have 16h+ span but only ~9h work - span is only for reporting
    # if fixed_on_day:
    #     fixed_start = min(fb.start_min for fb in fixed_on_day)
    #     fixed_end = max(fb.end_min for fb in fixed_on_day)
    #     combined_start = min(fixed_start, block.start_min)
    #     combined_end = max(fixed_end, block.end_min)
    #     if combined_end - combined_start > config.max_daily_span_minutes:
    #         return False, "span"
    
    # 4. Rest check (11h between consecutive days)
    # Check rest from previous day to this block
    prev_day_blocks = [fb for fb in driver.fixed_blocks if fb.day_idx == block_day - 1]
    if prev_day_blocks:
        prev_day_end = max(fb.end_min for fb in prev_day_blocks)
        rest = (block.start_min + DAY_MINUTES) - prev_day_end
        if rest < config.min_rest_minutes:
            return False, f"rest_from_prev ({rest/60:.1f}h<11h)"
    
    # Check rest from this block to next day
    next_day_blocks = [fb for fb in driver.fixed_blocks if fb.day_idx == block_day + 1]
    if next_day_blocks:
        next_day_start = min(fb.start_min for fb in next_day_blocks)
        rest = (next_day_start + DAY_MINUTES) - block.end_min
        if rest < config.min_rest_minutes:
            return False, f"rest_to_next ({rest/60:.1f}h<11h)"
    
    # 5. Weekly hours check (FTE only)
    if driver.driver_type == "FTE":
        max_minutes = int(config.max_hours_per_fte * 60)
        if driver.fixed_minutes + block.duration_min > max_minutes:
            return False, "weekly_hours"
    
    return True, ""


# =============================================================================
# REPAIR OPERATOR (CP-SAT)
# =============================================================================

def repair_assignments(
    driver_states: list[DriverState],
    blocks_to_repair: list[BlockInfo],
    config: LNSConfigV4,
    seed: int,
    banned_driver_ids: set = None,  # Drivers that should NOT receive any blocks
    iter_time_limit: float = None,  # S0.7: Time limit for this iteration (respects global budget)
) -> dict[str, str]:
    """
    Repair by reassigning blocks using small CP-SAT.
    
    Args:
        banned_driver_ids: Drivers that are completely excluded from candidates
                          (used to enforce PT elimination)
        iter_time_limit: Optional time limit for this specific iteration.
                        If provided, caps the solver time to respect global budget.
    
    Returns:
        block_id -> driver_id mapping
    """
    if not blocks_to_repair:
        return {}
    
    if banned_driver_ids is None:
        banned_driver_ids = set()
    
    model = cp_model.CpModel()
    
    # Sort for determinism
    blocks = sorted(blocks_to_repair, key=lambda b: b.block_id)
    drivers = sorted(driver_states, key=lambda d: d.driver_id)
    
    # Include drivers as candidates, EXCLUDING banned drivers
    all_candidates = [
        d for d in drivers 
        if d.driver_id not in banned_driver_ids and (d.fixed_blocks or d.destroyed_blocks or d.driver_type == "FTE")
    ]
    
    # ==========================================================================
    # CANDIDATE PRUNING: Only include drivers that can receive at least one block
    # ==========================================================================
    # This reduces CP-SAT symmetry and improves solve speed
    feasible_drivers = set()
    for b in blocks:
        block_receivers = []
        for d in all_candidates:
            allowed, _ = can_driver_receive_block(d, b, config)
            if allowed:
                block_receivers.append(d.driver_id)
        # Cap receivers per block to avoid too many candidates
        feasible_drivers.update(block_receivers[:config.candidate_cap_per_block])
    
    candidate_drivers = [d for d in all_candidates if d.driver_id in feasible_drivers]
    
    # Track which drivers are destroyed PT (for extreme penalty)
    destroyed_pt_ids = {d.driver_id for d in drivers if d.driver_type == "PT" and d.destroyed_blocks and not d.fixed_blocks}
    
    logger.info(f"Repair: {len(blocks)} blocks, {len(candidate_drivers)} candidates (pruned from {len(all_candidates)}, {len(destroyed_pt_ids)} destroyed PT)")
    
    # ==========================================================================
    # PRE-REPAIR DIAGNOSTICS
    # ==========================================================================
    
    # 1. Check if fixed schedule violates repair constraints
    violations = diagnose_fixed_schedule(candidate_drivers, config)
    if violations:
        logger.warning(f"FIXED SCHEDULE VIOLATIONS: {len(violations)} found")
        for v in violations[:5]:  # Log first 5
            logger.warning(f"  {v}")
        if len(violations) > 5:
            logger.warning(f"  ... and {len(violations) - 5} more")
    
    # 2. Check receiver count per block
    diag = diagnose_block_receivers(blocks, candidate_drivers, config)
    
    for block_id, count in diag["receiver_counts"]:
        if count <= 5:  # Low receiver count is concerning
            logger.warning(f"Block {block_id}: only {count} feasible receivers")
    
    # 3. If any block has 0 receivers, neighborhood is provably infeasible
    if diag["orphans"]:
        logger.warning(f"INFEASIBLE NEIGHBORHOOD: {len(diag['orphans'])} orphan blocks")
        for block_id, reasons in diag["orphans"]:
            logger.warning(f"  Block {block_id} has 0 receivers. Top reasons: {reasons}")
        # Don't waste time on CP-SAT - return empty mapping
        return {}
    
    # Variables
    # x[b,d] = 1 if block b assigned to driver d
    x = {}
    for b in blocks:
        for d in candidate_drivers:
            x[b.block_id, d.driver_id] = model.NewBoolVar(f"x_{b.block_id}_{d.driver_id}")
    
    # used[d] = 1 if driver d has at least one repair block
    used = {}
    for d in candidate_drivers:
        used[d.driver_id] = model.NewBoolVar(f"used_{d.driver_id}")
    
    # ==========================================================================
    # Constraints
    # ==========================================================================
    
    # 1. Each block assigned to exactly one driver
    for b in blocks:
        model.Add(sum(x[b.block_id, d.driver_id] for d in candidate_drivers) == 1)
    
    # 2. Link used[d] >= x[b,d]
    for d in candidate_drivers:
        for b in blocks:
            model.Add(used[d.driver_id] >= x[b.block_id, d.driver_id])
    
    # 3. No overlap on same day
    for d in candidate_drivers:
        for day_idx in range(7):
            day_blocks = [b for b in blocks if b.day_idx == day_idx]
            # Add fixed blocks for this driver on this day
            fixed_on_day = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
            
            # Check conflicts between repair blocks
            for i, b1 in enumerate(day_blocks):
                for b2 in day_blocks[i+1:]:
                    if blocks_overlap(b1, b2):
                        model.Add(x[b1.block_id, d.driver_id] + x[b2.block_id, d.driver_id] <= 1)
                
                # Check conflicts with fixed blocks
                for fb in fixed_on_day:
                    if blocks_overlap(b1, fb):
                        model.Add(x[b1.block_id, d.driver_id] == 0)
    
    # 4. Weekly hours constraint (FTE only)
    for d in candidate_drivers:
        if d.driver_type == "FTE":
            max_minutes = int(config.max_hours_per_fte * 60)
            repair_minutes = sum(
                b.duration_min * x[b.block_id, d.driver_id] for b in blocks
            )
            model.Add(repair_minutes + d.fixed_minutes <= max_minutes)
    
    # 5. Max tours per day AND Max blocks per day (HARD CONSTRAINT)
    from src.domain.constraints import HARD_CONSTRAINTS
    
    for d in candidate_drivers:
        for day_idx in range(7):
            day_blocks = [b for b in blocks if b.day_idx == day_idx]
            from_repair = sum(x[b.block_id, d.driver_id] for b in day_blocks)
            
            # A) Tours per day
            repair_tours = sum(b.tour_count * x[b.block_id, d.driver_id] for b in day_blocks)
            fixed_tours = d.fixed_tours_on_day(day_idx)
            model.Add(repair_tours + fixed_tours <= config.max_tours_per_day)
            
            # B) Blocks per day (Max 2) - CRITICAL FIX
            # Count fixed blocks on this day
            fixed_blocks_count = len([fb for fb in d.fixed_blocks if fb.day_idx == day_idx])
            model.Add(from_repair + fixed_blocks_count <= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY)

    # 5b. Weekly hours check (ALL drivers - Max 55h) - CRITICAL FIX
    max_weekly_minutes_hard = int(HARD_CONSTRAINTS.MAX_WEEKLY_HOURS * 60)
    for d in candidate_drivers:
        repair_minutes = sum(
            b.duration_min * x[b.block_id, d.driver_id] for b in blocks
        )
        model.Add(repair_minutes + d.fixed_minutes <= max_weekly_minutes_hard)
    
    # 6. Daily span constraint - DISABLED
    # Split-shifts (06:00-10:30 + 18:00-22:30) have 16h30 span but only 9h work.
    # Enforcing 14h span creates orphan blocks with only 1 receiver.
    # Span is now only for reporting/KPI, not feasibility.
    # If needed, use max_segments_per_day (max 2 blocks/day) instead.
    #
    # for d in candidate_drivers:
    #     for day_idx in range(7):
    #         day_blocks = [b for b in blocks if b.day_idx == day_idx]
    #         fixed_on_day = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
    #         if fixed_on_day:
    #             fixed_start = min(fb.start_min for fb in fixed_on_day)
    #             fixed_end = max(fb.end_min for fb in fixed_on_day)
    #             for b in day_blocks:
    #                 combined_start = min(fixed_start, b.start_min)
    #                 combined_end = max(fixed_end, b.end_min)
    #                 if combined_end - combined_start > config.max_daily_span_minutes:
    #                     model.Add(x[b.block_id, d.driver_id] == 0)

    # 7. Inter-day rest constraint (11h minimum between consecutive days)
    # We must check:
    # - Repair Day D vs Repair Day D+1
    # - Repair Day D vs Fixed Day D+1
    # - Fixed Day D vs Repair Day D+1
    
    # Pre-calculate start/end in global minutes (relative to D0 00:00) not needed
    # We can just use: (Start(D+1) + 24*60) - End(D) >= MinRest
    
    min_rest = config.min_rest_minutes
    
    for d in candidate_drivers:
        for day_idx in range(6):  # Check 0->1, 1->2, ..., 5->6
            # Get blocks for Day D and Day D+1
            d0_repair = [b for b in blocks if b.day_idx == day_idx]
            d1_repair = [b for b in blocks if b.day_idx == day_idx + 1]
            
            d0_fixed = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
            d1_fixed = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx + 1]
            
            # Case A: Repair D vs Repair D+1
            for b0 in d0_repair:
                for b1 in d1_repair:
                    # Check rest
                    rest_val = (b1.start_min + 1440) - b0.end_min
                    if rest_val < min_rest:
                        # Cannot assign both to this driver
                        model.Add(x[b0.block_id, d.driver_id] + x[b1.block_id, d.driver_id] <= 1)
            
            # Case B: Repair D vs Fixed D+1
            for b0 in d0_repair:
                for fb1 in d1_fixed:
                    rest_val = (fb1.start_min + 1440) - b0.end_min
                    if rest_val < min_rest:
                        # Cannot assign b0 to this driver
                        model.Add(x[b0.block_id, d.driver_id] == 0)
            
            # Case C: Fixed D vs Repair D+1
            for fb0 in d0_fixed:
                for b1 in d1_repair:
                    rest_val = (b1.start_min + 1440) - fb0.end_min
                    if rest_val < min_rest:
                        # Cannot assign b1 to this driver
                        model.Add(x[b1.block_id, d.driver_id] == 0)
    
    # ==========================================================================
    # Objective: minimize weighted cost including PT usage and activation penalties
    # ==========================================================================
    # Calculate cost for each driver
    cost_vars = []
    for d in candidate_drivers:
        # Base cost: w_total_used_driver if driver is used (dominant baseline)
        base_cost = int(config.w_total_used_driver) * used[d.driver_id]
        
        # PT usage penalty (applies to ANY PT driver)
        pt_usage_penalty = int(config.w_pt_used) if d.driver_type == "PT" else 0
        
        # Activation penalty: only for drivers NOT in incumbent
        activation_penalty = 0
        if not d.was_used_in_incumbent:
            activation_penalty = int(config.w_new_driver)
            if d.driver_type == "PT":
                activation_penalty += int(config.w_pt_new)
        
        # EXTREME PENALTY for destroyed PT drivers - we want to eliminate them!
        # Only use them if absolutely no other option exists
        destroyed_pt_penalty = 500_000 if d.driver_id in destroyed_pt_ids else 0
        
        # Total weight × used[d]
        weight = pt_usage_penalty + activation_penalty + destroyed_pt_penalty
        
        # Cost = base_cost + (weight × used[d])
        cost_vars.append(base_cost + weight * used[d.driver_id])
    
    # PT weekday penalty: per-block cost for assigning blocks to PT on weekdays
    assign_cost = []
    for b in blocks:
        for d in candidate_drivers:
            if d.driver_type == "PT":
                # day_idx: 0=Mon, 1=Tue, ..., 5=Sat, 6=Sun
                is_saturday = (b.day_idx == 5)
                penalty = config.w_pt_saturday_block if is_saturday else config.w_pt_weekday_block
                if penalty:
                    assign_cost.append(penalty * x[b.block_id, d.driver_id])
    
    # Combined objective: driver costs + assignment costs
    model.Minimize(sum(cost_vars) + sum(assign_cost))
    
    # ==========================================================================
    # Solve (with dynamic time limit based on block count)
    # ==========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    
    # Dynamic time limit: small repairs are fast, large repairs get more time
    num_blocks = len(blocks)
    if num_blocks < 10:
        base_limit = 2.0
    elif num_blocks < 50:
        base_limit = 10.0
    else:
        base_limit = config.repair_time_limit
    
    # S0.7: Respect iteration time limit if provided (global budget enforcement)
    if iter_time_limit is not None and iter_time_limit > 0:
        time_limit = min(base_limit, iter_time_limit)
        if time_limit < 1.0:
            # Not enough time to run a meaningful repair
            logger.warning(f"Repair skipped: iter_time_limit={iter_time_limit:.1f}s too small")
            return {}
    else:
        time_limit = base_limit
    
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.search_branching = cp_model.FIXED_SEARCH
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    
    status = solver.Solve(model)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning(f"Repair failed with status {status}, keeping original")
        return {}
    
    # Extract solution
    result = {}
    for b in blocks:
        for d in candidate_drivers:
            if solver.Value(x[b.block_id, d.driver_id]):
                result[b.block_id] = d.driver_id
                break
    
    drivers_used = sum(1 for d in candidate_drivers if solver.Value(used[d.driver_id]))
    logger.info(f"Repair complete: {len(result)} blocks assigned to {drivers_used} drivers")
    
    return result


# =============================================================================
# APPLY REPAIR
# =============================================================================

def apply_repair(
    original_assignments: list,  # list[DriverAssignment]
    block_mapping: dict[str, str],  # block_id -> driver_id
) -> list:
    """
    Apply repair result to create new assignments.
    """
    from src.services.forecast_solver_v4 import DriverAssignment
    
    if not block_mapping:
        return original_assignments
    
    # Build driver -> blocks map
    driver_blocks = {}
    for assignment in original_assignments:
        driver_blocks[assignment.driver_id] = {
            "driver_type": assignment.driver_type,
            "blocks": [],
        }
    
    # Assign blocks based on repair mapping
    for assignment in original_assignments:
        for block in assignment.blocks:
            if block.id in block_mapping:
                target_driver = block_mapping[block.id]
            else:
                target_driver = assignment.driver_id
            
            if target_driver not in driver_blocks:
                driver_blocks[target_driver] = {
                    "driver_type": "FTE" if target_driver.startswith("FTE") else "PT",
                    "blocks": [],
                }
            driver_blocks[target_driver]["blocks"].append(block)
    
    # Build new assignments
    new_assignments = []
    for driver_id in sorted(driver_blocks.keys()):
        data = driver_blocks[driver_id]
        if data["blocks"]:
            total_hours = sum(b.total_work_hours for b in data["blocks"])
            days = len(set(b.day.value for b in data["blocks"]))
            new_assignments.append(DriverAssignment(
                driver_id=driver_id,
                driver_type=data["driver_type"],
                blocks=sorted(data["blocks"], key=lambda b: (b.day.value, b.first_start)),
                total_hours=total_hours,
                days_worked=days,
            ))
    
    return new_assignments


# =============================================================================
# CONSOLIDATION
# =============================================================================

def consolidate_drivers(
    assignments: list,  # list[DriverAssignment]
    config: LNSConfigV4,
) -> list:
    """
    Attempt to consolidate low-utilization drivers by moving their blocks to others.
    
    Strategy:
    1. Sort drivers by total hours (ascending)
    2. For each low-utilization driver (< 9h):
       - Try to reassign all blocks to other drivers
       - If all blocks can move, remove driver
    3. Repeat until no more consolidations or max iterations
    
    Returns:
        Consolidated list of assignments
    """
    from src.services.constraints import can_assign_block
    
    if not config.enable_consolidation:
        return assignments
    
    log_progress(f"[CONSOLIDATE] Starting with {len(assignments)} drivers")
    
    improved = True
    iteration = 0
    
    while improved and iteration < config.max_consolidation_iterations:
        iteration += 1
        improved = False
        
        # Sort drivers by total hours (ascending) - target low-utilization first
        # Add driver_id as secondary key for determinism
        sorted_assignments = sorted(
            assignments,
            key=lambda a: (a.total_hours, a.driver_id)
        )
        
        for candidate_idx, candidate in enumerate(sorted_assignments):
            # Only consolidate drivers with < 9 hours (typically PT with 1-2 segments)
            if candidate.total_hours >= 9.0:
                break  # Rest are higher utilization
            
            if not candidate.blocks:
                continue  # Skip empty drivers
            
            log_progress(f"[CONSOLIDATE] Trying to merge driver {candidate.driver_id} ({candidate.total_hours:.1f}h, {len(candidate.blocks)} blocks)")
            
            # Try to reassign all blocks to other drivers
            reassignments = {}  # block_id -> target_driver_id
            
            for block in candidate.blocks:
                found_target = False
                
                # Type-aware target selection: for PT candidates, prefer FTE targets
                # Sort targets: FTE first, then by hours, then by driver_id (deterministic)
                targets = [a for a in sorted_assignments if sorted_assignments.index(a) != candidate_idx]
                targets = sorted(
                    targets,
                    key=lambda a: (
                        a.driver_type != "FTE",  # FTE first (False < True)
                        a.total_hours,           # Lower hours first
                        a.driver_id              # Deterministic tiebreaker
                    )
                )
                
                # Try all other drivers
                for other in targets:
                    
                    # Check if this driver can take the block
                    # Build list of blocks the target driver would have after reassignments
                    target_blocks = [b for b in other.blocks]
                    
                    # Add already-planned reassignments to this driver
                    for reassigned_block in candidate.blocks:
                        if reassignments.get(reassigned_block.id) == other.driver_id:
                            target_blocks.append(reassigned_block)
                    
                    # Check constraint
                    allowed, reason = can_assign_block(target_blocks, block)
                    
                    if allowed:
                        # FTE hour check
                        if other.driver_type == "FTE":
                            new_hours = other.total_hours + block.total_work_hours
                            # Add hours from other reassignments too
                            for reassigned_block in candidate.blocks:
                                if reassignments.get(reassigned_block.id) == other.driver_id:
                                    new_hours += reassigned_block.total_work_hours
                            
                            if new_hours > config.max_hours_per_fte:
                                continue  # Would exceed FTE limit
                        
                        # This driver can take it
                        reassignments[block.id] = other.driver_id
                        found_target = True
                        break
                
                if not found_target:
                    # Cannot move all blocks - abort consolidation of this driver
                    log_progress(f"[CONSOLIDATE] Cannot move block {block.id}, aborting merge")
                    reassignments = {}
                    break
            
            # If we successfully planned reassignment of ALL blocks, apply it
            if reassignments and len(reassignments) == len(candidate.blocks):
                log_progress(f"[CONSOLIDATE] Merging {candidate.driver_id} into other drivers")
                
                # Apply reassignments
                new_assignments = []
                for assignment in sorted_assignments:
                    if assignment.driver_id == candidate.driver_id:
                        # Skip the consolidated driver
                        continue
                    
                    # Collect blocks for this driver
                    blocks = list(assignment.blocks)
                    for block in candidate.blocks:
                        if reassignments.get(block.id) == assignment.driver_id:
                            blocks.append(block)
                    
                    if blocks:
                        # Rebuild assignment
                        from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
                        total_hours = sum(b.total_work_hours for b in blocks)
                        days = len(set(b.day.value for b in blocks))
                        new_assignments.append(DriverAssignment(
                            driver_id=assignment.driver_id,
                            driver_type=assignment.driver_type,
                            blocks=sorted(blocks, key=lambda b: (b.day.value, b.first_start)),
                            total_hours=total_hours,
                            days_worked=days,
                            analysis=_analyze_driver_workload(blocks)
                        ))
                
                assignments = new_assignments
                improved = True
                log_progress(f"[CONSOLIDATE] Success! Now {len(assignments)} drivers")
                break  # Restart with new sorted list
    
    log_progress(f"[CONSOLIDATE] Finished after {iteration} iterations, {len(assignments)} drivers remain")
    return assignments


# =============================================================================
# SCORING FOR ACCEPTANCE
# =============================================================================

def score_assignments(assignments: list) -> tuple:
    """
    Calculate lexicographic score for LNS acceptance.
    
    Lower score = better.
    Priority order: TOTAL DRIVERS > PT count > PT single-segment > tight rests
    
    HEADCOUNT REDUCTION IS PRIMARY - never increase total drivers to reduce PT!
    PT reduction is secondary - only reduce PT if it doesn't increase headcount.
    
    Returns:
        (total_driver_count, pt_count, pt_single_segment, tight_rest_count)
    """
    used = [a for a in assignments if a.blocks]
    
    driver_cnt = len(used)
    pt_cnt = sum(1 for a in used if a.driver_type == "PT")
    pt_single = sum(1 for a in used if a.driver_type == "PT" and len(a.blocks) == 1)
    
    # Count tight rests (exactly 11.0h)
    tight_rest = 0
    for a in used:
        analysis = getattr(a, "analysis", None)
        if analysis and analysis.get("min_rest_hours") == 11.0:
            tight_rest += 1
    
    # TOTAL DRIVERS is PRIMARY, then PT count
    return (driver_cnt, pt_cnt, pt_single, tight_rest)


# =============================================================================
# MAIN LNS REFINER
# =============================================================================

def refine_assignments_v4(
    assignments: list,  # list[DriverAssignment]
    config: LNSConfigV4 = None,
    remaining_fn: callable = None,  # Global deadline function from portfolio controller
) -> list:
    """
    Refine v4 driver assignments using LNS.
    
    Iteratively destroys part of the assignment and repairs with CP-SAT.
    Early stopping: stops if no improvement after N consecutive failures.
    
    Args:
        assignments: List of DriverAssignment to refine
        config: LNS configuration
        remaining_fn: Optional callable returning seconds remaining in global budget.
                     If provided, LNS will respect this as hard deadline.
    """
    log_progress("=" * 60)
    log_progress("LNS V4 REFINEMENT START")
    log_progress("=" * 60)
    
    if config is None:
        config = LNSConfigV4()
        log_progress("Using default config")
    
    log_progress(f"Config: iterations={config.max_iterations}, destroy={config.destroy_fraction}")
    log_progress(f"Early stopping after {config.early_stop_after_failures} consecutive failures")
    log_progress(f"Input: {len(assignments)} driver assignments")
    
    if not assignments:
        log_progress("No assignments to refine, returning empty")
        return assignments
    
    # Log input structure
    for i, a in enumerate(assignments[:3]):  # First 3 only
        log_progress(f"  Assignment[{i}]: driver={a.driver_id}, type={a.driver_type}, blocks={len(a.blocks)}")
        for j, block in enumerate(a.blocks[:2]):  # First 2 blocks only
            log_progress(f"    Block[{j}]: id={block.id}, type={type(block).__name__}")
    
    if len(assignments) > 3:
        log_progress(f"  ... and {len(assignments) - 3} more assignments")
    
    
    best_assignments = assignments
    best_score = score_assignments(assignments)
    
    # Log initial distribution metrics
    pt_initial = len([a for a in assignments if a.driver_type == "PT" and a.blocks])
    pt_single_initial = len([a for a in assignments if a.driver_type == "PT" and len(a.blocks) == 1 and a.blocks])
    pt_low_util_initial = len([a for a in assignments if a.driver_type == "PT" and a.total_hours <= 4.5 and a.blocks])
    
    log_progress(f"Initial driver count: {best_score[0]}")
    log_progress(f"  PT drivers: {pt_initial}")
    log_progress(f"  PT with single segment: {pt_single_initial}")
    log_progress(f"  PT with <=4.5h: {pt_low_util_initial}")
    log_progress(f"Initial score: {best_score}")
    
    consecutive_failures = 0
    
    # Time tracking for global time limit
    import time
    start_time = time.time()
    lns_time_limit = config.lns_time_limit
    
    # Log budget info
    if remaining_fn:
        global_remaining = remaining_fn()
        effective_limit = min(lns_time_limit, global_remaining)
        log_progress(f"Budget: lns_slice={lns_time_limit:.1f}s, global_remaining={global_remaining:.1f}s, effective={effective_limit:.1f}s")
    else:
        effective_limit = lns_time_limit
        log_progress(f"Budget: lns_slice={lns_time_limit:.1f}s (no global deadline)")
    
    for iteration in range(config.max_iterations):
        # Check global deadline FIRST (hard enforcement)
        if remaining_fn:
            global_remaining = remaining_fn()
            if global_remaining <= 0:
                log_progress(f"GLOBAL BUDGET EXHAUSTED (remaining={global_remaining:.1f}s), stopping LNS")
                break
        
        # Check local time limit
        elapsed = time.time() - start_time
        if elapsed >= lns_time_limit:
            log_progress(f"LNS slice limit reached ({elapsed:.1f}s >= {lns_time_limit}s), stopping")
            break
        
        # Calculate time available for this iteration's repair
        iter_remaining = lns_time_limit - elapsed
        if remaining_fn:
            iter_remaining = min(iter_remaining, remaining_fn())
        
        # Deterministic seed per iteration
        iter_seed = config.seed + iteration
        iter_rng = random.Random(iter_seed)
        
        log_progress(f"\n--- Iteration {iteration + 1}/{config.max_iterations} ({elapsed:.1f}s, remain={iter_remaining:.1f}s) ---")
        
        # Destroy: Use ejection chain if PT elimination enabled, otherwise random
        banned_driver_ids = set()  # Drivers that cannot receive blocks
        
        if config.enable_pt_elimination:
            # Check if there are PT drivers to target
            pt_count = len([a for a in best_assignments if a.driver_type == "PT" and a.blocks])
            if pt_count > 0:
                log_progress(f"  Using ejection chain destroy ({pt_count} PT drivers)")
                driver_states, blocks_to_repair, banned_driver_ids = destroy_pt_with_ejections(
                    best_assignments,
                    config,
                    iter_rng,
                )
            else:
                log_progress("  No PT drivers, using random destroy")
                driver_states, blocks_to_repair = destroy_drivers(
                    best_assignments,
                    config.destroy_fraction,
                    iter_rng,
                )
        else:
            # Standard random destroy
            driver_states, blocks_to_repair = destroy_drivers(
                best_assignments,
                config.destroy_fraction,
                iter_rng,
            )
        
        if not blocks_to_repair:
            logger.info("No blocks to repair, skipping iteration")
            consecutive_failures += 1
            if consecutive_failures >= config.early_stop_after_failures:
                log_progress(f"EARLY STOP: {consecutive_failures} consecutive failures, stopping LNS")
                break
            continue
        
        # Repair (with banned drivers excluded from candidates)
        # S0.7: Pass iter_remaining to cap CP-SAT time to global budget
        block_mapping = repair_assignments(
            driver_states,
            blocks_to_repair,
            config,
            iter_seed,
            banned_driver_ids=banned_driver_ids,
            iter_time_limit=iter_remaining,  # Respect global deadline
        )
        
        if not block_mapping:
            logger.info("Repair failed, keeping best")
            consecutive_failures += 1
            if consecutive_failures >= config.early_stop_after_failures:
                log_progress(f"EARLY STOP: {consecutive_failures} consecutive failures, stopping LNS")
                break
            continue
        
        # Apply and evaluate
        new_assignments = apply_repair(best_assignments, block_mapping)
        
        # Consolidate low-utilization drivers
        if config.enable_consolidation:
            new_assignments = consolidate_drivers(new_assignments, config)
        
        new_score = score_assignments(new_assignments)
        
        # Accept if score is strictly better (lexicographic comparison)
        if new_score < best_score:
            logger.info(f"Accepted: score {new_score} < {best_score}")
            best_assignments = new_assignments
            best_score = new_score
            consecutive_failures = 0  # Reset on improvement
        else:
            logger.info(f"Rejected: score {new_score} >= {best_score}")
            consecutive_failures += 1
            if consecutive_failures >= config.early_stop_after_failures:
                log_progress(f"EARLY STOP: {consecutive_failures} consecutive failures, stopping LNS")
                break
    
    
    # Log final distribution metrics
    pt_final = len([a for a in best_assignments if a.driver_type == "PT" and a.blocks])
    pt_single_final = len([a for a in best_assignments if a.driver_type == "PT" and len(a.blocks) == 1 and a.blocks])
    pt_low_util_final = len([a for a in best_assignments if a.driver_type == "PT" and a.total_hours <= 4.5 and a.blocks])
    
    logger.info("=" * 60)
    logger.info(f"LNS V4 COMPLETE")
    logger.info(f"Final score: {best_score} (driver_count, pt_count, pt_single, tight_rest)")
    logger.info(f"  Drivers: {best_score[0]} (PT: {best_score[1]})")
    logger.info(f"  PT drivers: {pt_initial} -> {pt_final}")
    logger.info(f"  PT with single segment: {pt_single_initial} -> {pt_single_final}")
    logger.info(f"  PT with <=4.5h: {pt_low_util_initial} -> {pt_low_util_final}")
    logger.info("=" * 60)
    
    return best_assignments

