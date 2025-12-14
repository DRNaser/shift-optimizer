"""Debug: Check driver feasibility for greedy blocks."""
import json
from datetime import time
from src.domain.models import Tour, Driver, Weekday
from src.services.block_builder import build_blocks_greedy
from src.domain.constraints import HARD_CONSTRAINTS

# Load test data
data = json.load(open('test_request.json'))

# Convert to Tour objects
day_map = {
    'Mon': Weekday.MONDAY, 'Tue': Weekday.TUESDAY, 'Wed': Weekday.WEDNESDAY,
    'Thu': Weekday.THURSDAY, 'Fri': Weekday.FRIDAY, 'Sat': Weekday.SATURDAY
}

tours = []
for t in data['tours']:
    st = t['start_time'].split(':')
    et = t['end_time'].split(':')
    tours.append(Tour(
        id=t['id'],
        day=day_map[t['day']],
        start_time=time(int(st[0]), int(st[1])),
        end_time=time(int(et[0]), int(et[1]))
    ))

# Create drivers (same as test_real_data.py)
drivers = [
    Driver(id=f'D-{i:03d}', name=f'Fahrer {i}')
    for i in range(1, 139)  # 138 drivers
]

print(f"Tours: {len(tours)}")
print(f"Drivers: {len(drivers)}")

# Get greedy blocks
blocks = build_blocks_greedy(tours, prefer_larger=True)
print(f"Greedy blocks: {len(blocks)}")

# Check feasibility for each block
def is_feasible(block, driver):
    """Quick check if assignment is possible."""
    # Qualifications
    if block.required_qualifications - set(driver.qualifications):
        return False, "qualification"
    # Availability
    if not driver.is_available_on(block.day):
        return False, "availability"
    # Daily span
    if block.span_hours > min(HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS, driver.max_daily_span_hours):
        return False, "daily_span"
    # Block size
    if len(block.tours) > min(HARD_CONSTRAINTS.MAX_TOURS_PER_DAY, driver.max_tours_per_day):
        return False, "block_size"
    return True, None

# Count feasible assignments per block
infeasible_blocks = []
reason_counts = {"qualification": 0, "availability": 0, "daily_span": 0, "block_size": 0}

for block in blocks:
    feasible_count = 0
    for driver in drivers:
        ok, reason = is_feasible(block, driver)
        if ok:
            feasible_count += 1
        elif reason:
            reason_counts[reason] += 1
    
    if feasible_count == 0:
        infeasible_blocks.append(block)

print(f"\n=== FEASIBILITY ANALYSIS ===")
print(f"Blocks with NO feasible driver: {len(infeasible_blocks)}")
print(f"Blocks with at least 1 feasible driver: {len(blocks) - len(infeasible_blocks)}")

if infeasible_blocks:
    print(f"\nInfeasible blocks details:")
    for b in infeasible_blocks[:5]:
        print(f"  Block {b.id}: {b.day.value}, span={b.span_hours:.1f}h, tours={len(b.tours)}")

print(f"\nInfeasibility reasons (total checks: {len(blocks) * len(drivers)}):")
for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
    print(f"  {reason}: {count}")

# Check: if all blocks are feasible for at least 1 driver, why 40% unassigned?
# It must be: weekly hours constraint hits during solving
print(f"\n=== CAPACITY CHECK ===")
total_block_hours = sum(b.total_work_hours for b in blocks)
driver_capacity = len(drivers) * HARD_CONSTRAINTS.MAX_WEEKLY_HOURS
print(f"Total block hours needed: {total_block_hours:.0f}h")
print(f"Driver capacity (138 x 55h): {driver_capacity:.0f}h")
print(f"Ratio: {total_block_hours/driver_capacity*100:.1f}%")

# Break down by day
print(f"\n=== BLOCKS PER DAY ===")
for day in Weekday:
    day_blocks = [b for b in blocks if b.day == day]
    day_hours = sum(b.total_work_hours for b in day_blocks)
    print(f"  {day.value}: {len(day_blocks)} blocks, {day_hours:.0f}h")
