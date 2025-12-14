"""Analyze greedy block builder output"""
from src.services.block_builder import build_blocks_greedy
from src.domain.models import Tour, Weekday
from datetime import time
import json

# Load test request
with open('test_request.json') as f:
    data = json.load(f)

# Convert to Tour objects
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

print(f"Total tours: {len(tours)}")

# Generate greedy blocks
print("Generating greedy blocks (prefer_larger=True)...")
blocks = build_blocks_greedy(tours, prefer_larger=True)

# Count by type
by_type = {1: 0, 2: 0, 3: 0}
for b in blocks:
    by_type[len(b.tours)] = by_type.get(len(b.tours), 0) + 1

print(f"\n=== GREEDY BLOCKS ===")
print(f"1er blocks: {by_type[1]}")
print(f"2er blocks: {by_type[2]}")
print(f"3er blocks: {by_type[3]}")
print(f"Total: {len(blocks)}")

# Show distribution by day
print(f"\n=== BY DAY ===")
for day in [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]:
    day_blocks = [b for b in blocks if b.day == day]
    day_1er = sum(1 for b in day_blocks if len(b.tours) == 1)
    day_2er = sum(1 for b in day_blocks if len(b.tours) == 2)
    day_3er = sum(1 for b in day_blocks if len(b.tours) == 3)
    total_tours = sum(len(b.tours) for b in day_blocks)
    print(f"{day.value}: {total_tours} tours -> 3er:{day_3er} 2er:{day_2er} 1er:{day_1er}")

# Show sample 3er blocks
print(f"\n=== SAMPLE 3er BLOCKS (first 10) ===")
triple_blocks = [b for b in blocks if len(b.tours) == 3]
for b in triple_blocks[:10]:
    tours_str = ' + '.join(f"{t.start_time.strftime('%H:%M')}-{t.end_time.strftime('%H:%M')}" for t in b.tours)
    print(f"  {b.day.value}: {tours_str}")
