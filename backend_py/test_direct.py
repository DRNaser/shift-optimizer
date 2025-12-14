"""Test optimizer directly (bypass API)"""
from datetime import date, time
import json

from src.domain.models import Tour, Driver, Weekday
from src.services.cpsat_solver import create_cpsat_schedule, CPSATConfig

# Load test request
with open('test_request.json') as f:
    data = json.load(f)

# Convert to domain objects
day_map = {'Mon': Weekday.MONDAY, 'Tue': Weekday.TUESDAY, 'Wed': Weekday.WEDNESDAY,
           'Thu': Weekday.THURSDAY, 'Fri': Weekday.FRIDAY, 'Sat': Weekday.SATURDAY}

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

drivers = [Driver(id=d['id'], name=d['name']) for d in data['drivers']]

print(f"Tours: {len(tours)}")
print(f"Drivers: {len(drivers)}")

# Run optimizer directly
config = CPSATConfig(
    time_limit_seconds=60,
    optimize=True
)

print("\nRunning CP-SAT solver directly...")
plan = create_cpsat_schedule(tours, drivers, date(2024, 12, 9), config)

print(f"\n=== RESULTS ===")
print(f"Valid: {plan.validation.is_valid}")
print(f"Tours assigned: {plan.stats.total_tours_assigned}/{plan.stats.total_tours_input}")
print(f"Assignment rate: {plan.stats.assignment_rate*100:.1f}%")
print(f"Drivers used: {plan.stats.total_drivers}")

print(f"\nBlock types:")
for btype, count in plan.stats.block_counts.items():
    print(f"  {btype}: {count}")
