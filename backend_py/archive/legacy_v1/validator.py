"""
SHIFT OPTIMIZER - Validator
============================
THE SINGLE SOURCE OF TRUTH for constraint validation.

The Validator decides whether a solution is valid.
NOT the Solver. NOT the Agent.

Every constraint check is explicit. No assumptions.
"""

from collections import defaultdict
from datetime import time
from typing import NamedTuple

from .models import (
    Block,
    Driver,
    DriverAssignment,
    ReasonCode,
    Tour,
    ValidationResult,
    Weekday,
    WeeklyPlan,
)
from .constraints import HARD_CONSTRAINTS


# =============================================================================
# VALIDATION CONTEXT
# =============================================================================

class ValidationContext(NamedTuple):
    """Context for validation - all drivers and their current state."""
    drivers: dict[str, Driver]  # driver_id -> Driver
    driver_weekly_hours: dict[str, float]  # driver_id -> hours worked this week
    driver_daily_blocks: dict[str, dict[Weekday, list[Block]]]  # driver_id -> day -> blocks
    driver_last_end: dict[str, dict[Weekday, time]]  # driver_id -> day -> last tour end time


def create_empty_context(drivers: list[Driver]) -> ValidationContext:
    """Create an empty validation context from driver list."""
    return ValidationContext(
        drivers={d.id: d for d in drivers},
        driver_weekly_hours={d.id: 0.0 for d in drivers},
        driver_daily_blocks={d.id: defaultdict(list) for d in drivers},
        driver_last_end={d.id: {} for d in drivers},
    )


# =============================================================================
# INDIVIDUAL CONSTRAINT VALIDATORS
# =============================================================================

def check_weekly_hours(
    driver: Driver,
    new_block: Block,
    current_weekly_hours: float
) -> tuple[bool, str | None]:
    """
    Check: MAX_WEEKLY_HOURS
    Driver cannot exceed 55h/week (or their personal limit).
    
    Returns: (is_valid, error_message)
    """
    limit = min(HARD_CONSTRAINTS.MAX_WEEKLY_HOURS, driver.max_weekly_hours)
    projected_hours = current_weekly_hours + new_block.total_work_hours
    
    if projected_hours > limit:
        return False, (
            f"Driver {driver.id} would exceed weekly limit: "
            f"{projected_hours:.1f}h > {limit}h (current: {current_weekly_hours:.1f}h, "
            f"block adds: {new_block.total_work_hours:.1f}h)"
        )
    return True, None


def check_daily_span(
    driver: Driver,
    new_block: Block
) -> tuple[bool, str | None]:
    """
    Check: MAX_DAILY_SPAN_HOURS
    Span from first tour start to last tour end ≤14.5h.
    
    Returns: (is_valid, error_message)
    """
    limit = min(HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS, driver.max_daily_span_hours)
    
    if new_block.span_hours > limit:
        return False, (
            f"Block {new_block.id} span exceeds limit: "
            f"{new_block.span_hours:.1f}h > {limit}h "
            f"({new_block.first_start} to {new_block.last_end})"
        )
    return True, None


def check_tours_per_day(
    driver: Driver,
    new_block: Block,
    existing_blocks: list[Block]
) -> tuple[bool, str | None]:
    """
    Check: MAX_TOURS_PER_DAY
    Driver cannot do more than 3 tours per day.
    
    Returns: (is_valid, error_message)
    """
    limit = min(HARD_CONSTRAINTS.MAX_TOURS_PER_DAY, driver.max_tours_per_day)
    current_tours = sum(len(b.tours) for b in existing_blocks)
    projected_tours = current_tours + len(new_block.tours)
    
    if projected_tours > limit:
        return False, (
            f"Driver {driver.id} would exceed daily tour limit on {new_block.day}: "
            f"{projected_tours} > {limit} tours"
        )
    return True, None


def check_blocks_per_day(
    driver: Driver,
    day: Weekday,
    existing_blocks: list[Block]
) -> tuple[bool, str | None]:
    """
    Check: MAX_BLOCKS_PER_DRIVER_PER_DAY
    Driver can have up to 2 blocks per day (split shift).
    
    Returns: (is_valid, error_message)
    """
    if len(existing_blocks) >= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY:
        return False, (
            f"Driver {driver.id} already has {len(existing_blocks)} block(s) on {day}. "
            f"Maximum {HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY} block(s) per day."
        )
    return True, None


def check_gap_between_blocks(
    driver: Driver,
    new_block: Block,
    existing_blocks: list[Block]
) -> tuple[bool, str | None]:
    """
    Check: MIN_GAP_BETWEEN_BLOCKS_HOURS
    For split shifts, minimum gap between blocks on same day.
    
    Returns: (is_valid, error_message)
    """
    if not existing_blocks:
        return True, None
    
    min_gap = HARD_CONSTRAINTS.MIN_GAP_BETWEEN_BLOCKS_HOURS
    
    for existing in existing_blocks:
        # Calculate gap between blocks
        new_start_mins = new_block.first_start.hour * 60 + new_block.first_start.minute
        new_end_mins = new_block.last_end.hour * 60 + new_block.last_end.minute
        exist_start_mins = existing.first_start.hour * 60 + existing.first_start.minute
        exist_end_mins = existing.last_end.hour * 60 + existing.last_end.minute
        
        # Check if new block is before or after existing
        if new_end_mins <= exist_start_mins:
            # New block is before existing
            gap_mins = exist_start_mins - new_end_mins
        elif new_start_mins >= exist_end_mins:
            # New block is after existing
            gap_mins = new_start_mins - exist_end_mins
        else:
            # Blocks overlap
            return False, (
                f"Blocks overlap on {new_block.day}: "
                f"new block {new_block.first_start}-{new_block.last_end} "
                f"overlaps with existing {existing.first_start}-{existing.last_end}"
            )
        
        gap_hours = gap_mins / 60.0
        if gap_hours < min_gap:
            return False, (
                f"Insufficient gap between blocks on {new_block.day}: "
                f"{gap_hours:.1f}h < {min_gap}h minimum. "
                f"(new: {new_block.first_start}-{new_block.last_end}, "
                f"existing: {existing.first_start}-{existing.last_end})"
            )
    
    return True, None


def check_rest_time(
    driver: Driver,
    new_block: Block,
    prev_day_last_end: time | None,
    next_day_first_start: time | None
) -> tuple[bool, str | None]:
    """
    Check: MIN_REST_HOURS
    Minimum 11h rest between days.
    
    This checks:
    1. From previous day's last tour end to this block's first start
    2. From this block's last end to next day's first tour start
    
    Returns: (is_valid, error_message)
    """
    limit = min(HARD_CONSTRAINTS.MIN_REST_HOURS, driver.min_rest_hours)
    
    # Check rest from previous day
    if prev_day_last_end is not None:
        # Calculate hours from prev_day_last_end to new_block.first_start
        prev_mins = prev_day_last_end.hour * 60 + prev_day_last_end.minute
        this_mins = new_block.first_start.hour * 60 + new_block.first_start.minute
        # Assuming next day, add 24 hours (1440 minutes)
        rest_minutes = (this_mins + 1440) - prev_mins
        rest_hours = rest_minutes / 60.0
        
        if rest_hours < limit:
            return False, (
                f"Driver {driver.id} rest violation: only {rest_hours:.1f}h rest "
                f"(previous day ended {prev_day_last_end}, block starts {new_block.first_start}). "
                f"Minimum: {limit}h"
            )
    
    # Check rest to next day (if we know next day's schedule)
    if next_day_first_start is not None:
        this_mins = new_block.last_end.hour * 60 + new_block.last_end.minute
        next_mins = next_day_first_start.hour * 60 + next_day_first_start.minute
        rest_minutes = (next_mins + 1440) - this_mins
        rest_hours = rest_minutes / 60.0
        
        if rest_hours < limit:
            return False, (
                f"Driver {driver.id} rest violation: only {rest_hours:.1f}h rest "
                f"(block ends {new_block.last_end}, next day starts {next_day_first_start}). "
                f"Minimum: {limit}h"
            )
    
    return True, None


def check_no_overlap(tours: list[Tour]) -> tuple[bool, str | None]:
    """
    Check: NO_TOUR_OVERLAP
    Tours within a block cannot overlap.
    
    Returns: (is_valid, error_message)
    """
    if not HARD_CONSTRAINTS.NO_TOUR_OVERLAP:
        return True, None
    
    for i, tour1 in enumerate(tours):
        for tour2 in tours[i + 1:]:
            if tour1.overlaps(tour2):
                return False, (
                    f"Tours overlap: {tour1.id} ({tour1.start_time}-{tour1.end_time}) "
                    f"and {tour2.id} ({tour2.start_time}-{tour2.end_time})"
                )
    return True, None


def check_qualifications(
    driver: Driver,
    block: Block
) -> tuple[bool, str | None]:
    """
    Check: QUALIFICATION_REQUIRED
    Driver must have all required qualifications.
    
    Returns: (is_valid, error_message)
    """
    if not HARD_CONSTRAINTS.QUALIFICATION_REQUIRED:
        return True, None
    
    missing = block.required_qualifications - set(driver.qualifications)
    if missing:
        return False, (
            f"Driver {driver.id} missing qualifications for block {block.id}: "
            f"{', '.join(missing)}"
        )
    return True, None


def check_availability(
    driver: Driver,
    block: Block
) -> tuple[bool, str | None]:
    """
    Check: AVAILABILITY_REQUIRED
    Driver must be available on the day.
    
    Returns: (is_valid, error_message)
    """
    if not HARD_CONSTRAINTS.AVAILABILITY_REQUIRED:
        return True, None
    
    if not driver.is_available_on(block.day):
        return False, (
            f"Driver {driver.id} is not available on {block.day}"
        )
    
    # TODO: Check specific time slots if defined
    return True, None


# =============================================================================
# BLOCK VALIDATION
# =============================================================================

def validate_block_structure(block: Block) -> ValidationResult:
    """
    Validate a block's internal structure (independent of driver).
    
    Checks:
    - Tour count within limits
    - Tours on same day
    - No overlaps
    - Tours sorted by time
    """
    violations: list[str] = []
    warnings: list[str] = []
    
    # Check tour count
    if len(block.tours) < HARD_CONSTRAINTS.MIN_TOURS_PER_BLOCK:
        violations.append(
            f"Block {block.id} has too few tours: {len(block.tours)} < "
            f"{HARD_CONSTRAINTS.MIN_TOURS_PER_BLOCK}"
        )
    
    if len(block.tours) > HARD_CONSTRAINTS.MAX_TOURS_PER_BLOCK:
        violations.append(
            f"Block {block.id} has too many tours: {len(block.tours)} > "
            f"{HARD_CONSTRAINTS.MAX_TOURS_PER_BLOCK}"
        )
    
    # Check all tours on same day
    days = set(t.day for t in block.tours)
    if len(days) > 1:
        violations.append(
            f"Block {block.id} spans multiple days: {days}"
        )
    
    # Check no overlaps
    valid, error = check_no_overlap(block.tours)
    if not valid and error:
        violations.append(error)
    
    # Check tours are sorted
    sorted_tours = sorted(block.tours, key=lambda t: t.start_time)
    if block.tours != sorted_tours:
        warnings.append(f"Block {block.id}: Tours not sorted by start time")
    
    # Check pause gaps between tours (TWO-ZONE LOGIC)
    # Regular blocks: 30-60 min gap (tighter packing in v5)
    # Split blocks: 360 min gap exactly (6h mandatory)
    for i in range(len(block.tours) - 1):
        t1 = block.tours[i]
        t2 = block.tours[i + 1]
        gap_mins = (t2.start_time.hour * 60 + t2.start_time.minute) - \
                   (t1.end_time.hour * 60 + t1.end_time.minute)
        
        # Minimum gap applies to all blocks
        if gap_mins < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
            violations.append(
                f"Block {block.id}: Gap between {t1.id} and {t2.id} is {gap_mins}min, "
                f"minimum is {HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS}min"
            )
        
        # Maximum gap depends on block type (regular vs split)
        # Split block detection: is_split flag or B2S- prefix in ID
        is_split_block = getattr(block, 'is_split', False) or block.id.startswith('B2S-')
        
        if is_split_block:
            # Split zone: 240-360 min
            if gap_mins < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN:
                violations.append(
                    f"Block {block.id}: Split block gap {gap_mins}min below minimum "
                    f"{HARD_CONSTRAINTS.SPLIT_PAUSE_MIN}min"
                )
            elif gap_mins > HARD_CONSTRAINTS.SPLIT_PAUSE_MAX:
                violations.append(
                    f"Block {block.id}: Split block gap {gap_mins}min exceeds maximum "
                    f"{HARD_CONSTRAINTS.SPLIT_PAUSE_MAX}min"
                )
            # Check spread (first_start -> last_end)
            spread_mins = block.span_minutes
            if spread_mins > HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES:
                violations.append(
                    f"Block {block.id}: Split block spread {spread_mins}min exceeds maximum "
                    f"{HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES}min"
                )
        else:
            # Regular zone: 30-60 min
            if gap_mins > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS:
                violations.append(
                    f"Block {block.id}: Gap between {t1.id} and {t2.id} is {gap_mins}min, "
                    f"maximum is {HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS}min"
                )
            # Forbidden zone check (61-359 min)
            if HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS < gap_mins < HARD_CONSTRAINTS.SPLIT_PAUSE_MIN:
                violations.append(
                    f"Block {block.id}: Gap {gap_mins}min in forbidden zone "
                    f"({HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS+1}-{HARD_CONSTRAINTS.SPLIT_PAUSE_MIN-1}min)"
                )
    
    return ValidationResult(
        is_valid=len(violations) == 0,
        hard_violations=violations,
        warnings=warnings
    )


# =============================================================================
# ASSIGNMENT VALIDATION
# =============================================================================

def validate_assignment(
    assignment: DriverAssignment,
    context: ValidationContext
) -> ValidationResult:
    """
    Validate a single driver-block assignment against all constraints.
    
    This is called BEFORE adding an assignment to check feasibility.
    """
    violations: list[str] = []
    warnings: list[str] = []
    
    driver = context.drivers.get(assignment.driver_id)
    if driver is None:
        violations.append(f"Unknown driver: {assignment.driver_id}")
        return ValidationResult(is_valid=False, hard_violations=violations)
    
    block = assignment.block
    day = assignment.day
    
    # First validate block structure
    block_result = validate_block_structure(block)
    violations.extend(block_result.hard_violations)
    warnings.extend(block_result.warnings)
    
    # Check blocks per day
    existing_blocks = context.driver_daily_blocks[driver.id].get(day, [])
    valid, error = check_blocks_per_day(driver, day, existing_blocks)
    if not valid and error:
        violations.append(error)
    
    # Check weekly hours
    current_hours = context.driver_weekly_hours[driver.id]
    valid, error = check_weekly_hours(driver, block, current_hours)
    if not valid and error:
        violations.append(error)
    
    # Check daily span
    valid, error = check_daily_span(driver, block)
    if not valid and error:
        violations.append(error)
    
    # Check tours per day
    valid, error = check_tours_per_day(driver, block, existing_blocks)
    if not valid and error:
        violations.append(error)
    
    # Check qualifications
    valid, error = check_qualifications(driver, block)
    if not valid and error:
        violations.append(error)
    
    # Check availability
    valid, error = check_availability(driver, block)
    if not valid and error:
        violations.append(error)
    
    # Check rest time (simplified - check previous day only)
    prev_day = get_previous_day(day)
    prev_day_end = context.driver_last_end[driver.id].get(prev_day)
    valid, error = check_rest_time(driver, block, prev_day_end, None)
    if not valid and error:
        violations.append(error)
    
    return ValidationResult(
        is_valid=len(violations) == 0,
        hard_violations=violations,
        warnings=warnings
    )


def can_assign(
    driver: Driver,
    block: Block,
    context: ValidationContext
) -> tuple[bool, list[ReasonCode], str]:
    """
    Quick check if assignment is possible.
    Returns (can_assign, reason_codes, explanation).
    
    Used by scheduler to filter candidates efficiently.
    """
    reasons: list[ReasonCode] = []
    explanations: list[str] = []
    
    day = block.day
    existing_blocks = context.driver_daily_blocks[driver.id].get(day, [])
    current_hours = context.driver_weekly_hours[driver.id]
    
    # Check blocks per day
    if len(existing_blocks) >= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY:
        reasons.append(ReasonCode.BLOCK_ALREADY_ASSIGNED)
        explanations.append(f"Already has {HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY} blocks on {day}")
    
    # Check gap between blocks (for split shifts)
    if existing_blocks:
        min_gap = HARD_CONSTRAINTS.MIN_GAP_BETWEEN_BLOCKS_HOURS
        for existing in existing_blocks:
            new_start_mins = block.first_start.hour * 60 + block.first_start.minute
            new_end_mins = block.last_end.hour * 60 + block.last_end.minute
            exist_start_mins = existing.first_start.hour * 60 + existing.first_start.minute
            exist_end_mins = existing.last_end.hour * 60 + existing.last_end.minute
            
            if new_end_mins <= exist_start_mins:
                gap_mins = exist_start_mins - new_end_mins
            elif new_start_mins >= exist_end_mins:
                gap_mins = new_start_mins - exist_end_mins
            else:
                reasons.append(ReasonCode.DRIVER_DAILY_SPAN_LIMIT)
                explanations.append(f"Block overlaps with existing on {day}")
                break
            
            if gap_mins / 60.0 < min_gap:
                reasons.append(ReasonCode.DRIVER_REST_VIOLATION)
                explanations.append(f"Gap between blocks < {min_gap}h")
                break
    
    # Check weekly hours
    limit = min(HARD_CONSTRAINTS.MAX_WEEKLY_HOURS, driver.max_weekly_hours)
    if current_hours + block.total_work_hours > limit:
        reasons.append(ReasonCode.DRIVER_WEEKLY_LIMIT)
        explanations.append(f"Would exceed {limit}h weekly limit")
    
    # Check daily span
    limit = min(HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS, driver.max_daily_span_hours)
    if block.span_hours > limit:
        reasons.append(ReasonCode.DRIVER_DAILY_SPAN_LIMIT)
        explanations.append(f"Block span {block.span_hours:.1f}h > {limit}h limit")
    
    # Check qualifications
    missing = block.required_qualifications - set(driver.qualifications)
    if missing:
        reasons.append(ReasonCode.DRIVER_QUALIFICATION_MISSING)
        explanations.append(f"Missing: {', '.join(missing)}")
    
    # Check availability
    if not driver.is_available_on(day):
        reasons.append(ReasonCode.DRIVER_NOT_AVAILABLE)
        explanations.append(f"Not available on {day}")
    
    # Check rest time
    prev_day = get_previous_day(day)
    prev_end = context.driver_last_end[driver.id].get(prev_day)
    if prev_end:
        limit = min(HARD_CONSTRAINTS.MIN_REST_HOURS, driver.min_rest_hours)
        prev_mins = prev_end.hour * 60 + prev_end.minute
        this_mins = block.first_start.hour * 60 + block.first_start.minute
        rest_hours = ((this_mins + 1440) - prev_mins) / 60.0
        if rest_hours < limit:
            reasons.append(ReasonCode.DRIVER_REST_VIOLATION)
            explanations.append(f"Only {rest_hours:.1f}h rest (need {limit}h)")
    
    return len(reasons) == 0, reasons, "; ".join(explanations)


# =============================================================================
# FULL PLAN VALIDATION
# =============================================================================

def validate_weekly_plan(
    plan: WeeklyPlan,
    drivers: list[Driver]
) -> ValidationResult:
    """
    Validate an entire weekly plan.
    
    This is the FINAL validation before accepting a plan.
    """
    violations: list[str] = []
    warnings: list[str] = []
    
    # Build context from existing assignments
    context = create_empty_context(drivers)
    
    # Validate each assignment
    for assignment in plan.assignments:
        result = validate_assignment(assignment, context)
        violations.extend(result.hard_violations)
        warnings.extend(result.warnings)
        
        # Update context with this assignment
        driver_id = assignment.driver_id
        day = assignment.day
        block = assignment.block
        
        context.driver_weekly_hours[driver_id] += block.total_work_hours
        context.driver_daily_blocks[driver_id][day].append(block)
        
        # Update last end time for rest checks
        existing_end = context.driver_last_end[driver_id].get(day)
        if existing_end is None or block.last_end > existing_end:
            context.driver_last_end[driver_id][day] = block.last_end
    
    # Cross-day rest validation
    for driver_id in context.drivers:
        for day in Weekday:
            blocks = context.driver_daily_blocks[driver_id].get(day, [])
            if not blocks:
                continue
            
            # Get last end of this day
            last_end = max(b.last_end for b in blocks)
            
            # Get first start of next day
            next_day = get_next_day(day)
            next_blocks = context.driver_daily_blocks[driver_id].get(next_day, [])
            if not next_blocks:
                continue
            
            first_start = min(b.first_start for b in next_blocks)
            
            # Check rest
            driver = context.drivers[driver_id]
            limit = min(HARD_CONSTRAINTS.MIN_REST_HOURS, driver.min_rest_hours)
            
            last_mins = last_end.hour * 60 + last_end.minute
            first_mins = first_start.hour * 60 + first_start.minute
            rest_hours = ((first_mins + 1440) - last_mins) / 60.0
            
            if rest_hours < limit:
                violations.append(
                    f"Driver {driver_id}: only {rest_hours:.1f}h rest between "
                    f"{day} (ends {last_end}) and {next_day} (starts {first_start}). "
                    f"Minimum: {limit}h"
                )
    
    return ValidationResult(
        is_valid=len(violations) == 0,
        hard_violations=violations,
        warnings=warnings
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_previous_day(day: Weekday) -> Weekday:
    """Get the previous day of the week."""
    days = list(Weekday)
    idx = days.index(day)
    return days[(idx - 1) % 7]


def get_next_day(day: Weekday) -> Weekday:
    """Get the next day of the week."""
    days = list(Weekday)
    idx = days.index(day)
    return days[(idx + 1) % 7]


# =============================================================================
# PUBLIC API
# =============================================================================

class Validator:
    """
    Main validation interface.
    
    THE SINGLE SOURCE OF TRUTH for constraint compliance.
    """
    
    def __init__(self, drivers: list[Driver]):
        self.drivers = {d.id: d for d in drivers}
        self.context = create_empty_context(drivers)
    
    def reset(self) -> None:
        """Reset context to empty state."""
        self.context = create_empty_context(list(self.drivers.values()))
    
    def can_assign(
        self, 
        driver_id: str, 
        block: Block
    ) -> tuple[bool, list[ReasonCode], str]:
        """
        Check if assignment is feasible.
        Does NOT modify state.
        """
        driver = self.drivers.get(driver_id)
        if driver is None:
            return False, [ReasonCode.NO_AVAILABLE_DRIVER], f"Unknown driver: {driver_id}"
        return can_assign(driver, block, self.context)
    
    def validate_and_commit(
        self, 
        driver_id: str, 
        block: Block
    ) -> ValidationResult:
        """
        Validate assignment and commit if valid.
        MODIFIES state if successful.
        """
        driver = self.drivers.get(driver_id)
        if driver is None:
            return ValidationResult(
                is_valid=False,
                hard_violations=[f"Unknown driver: {driver_id}"]
            )
        
        assignment = DriverAssignment(
            driver_id=driver_id,
            day=block.day,
            block=block
        )
        
        result = validate_assignment(assignment, self.context)
        
        if result.is_valid:
            # Commit the assignment to context
            self.context.driver_weekly_hours[driver_id] += block.total_work_hours
            self.context.driver_daily_blocks[driver_id][block.day].append(block)
            
            existing_end = self.context.driver_last_end[driver_id].get(block.day)
            if existing_end is None or block.last_end > existing_end:
                self.context.driver_last_end[driver_id][block.day] = block.last_end
        
        return result
    
    def validate_plan(self, plan: WeeklyPlan) -> ValidationResult:
        """
        Validate complete plan (stateless - doesn't use/modify context).
        """
        return validate_weekly_plan(plan, list(self.drivers.values()))
    
    def get_driver_stats(self, driver_id: str) -> dict:
        """Get current stats for a driver."""
        return {
            "weekly_hours": self.context.driver_weekly_hours.get(driver_id, 0.0),
            "daily_blocks": {
                day.value: len(blocks)
                for day, blocks in self.context.driver_daily_blocks.get(driver_id, {}).items()
            }
        }
