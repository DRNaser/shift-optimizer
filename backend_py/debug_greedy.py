"""Debug: Check what blocks the solver actually receives."""
import json
from datetime import time
from src.domain.models import Tour, Weekday
from src.services.block_builder import build_blocks_greedy

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

print(f"Total tours: {len(tours)}")

# Get greedy blocks (what solver receives)
blocks = build_blocks_greedy(tours, prefer_larger=True)

print(f"\n=== GREEDY BLOCKS (what solver sees) ===")
print(f"Total blocks: {len(blocks)}")
blocks_1er = sum(1 for b in blocks if len(b.tours) == 1)
blocks_2er = sum(1 for b in blocks if len(b.tours) == 2)
blocks_3er = sum(1 for b in blocks if len(b.tours) == 3)
print(f"  1er: {blocks_1er}")
print(f"  2er: {blocks_2er}")
print(f"  3er: {blocks_3er}")

# Count tours covered by greedy blocks
tours_covered = set()
for b in blocks:
    for t in b.tours:
        tours_covered.add(t.id)
        
print(f"\nTours covered by greedy blocks: {len(tours_covered)}/{len(tours)}")

# Check if all tours are covered
uncovered = set(t.id for t in tours) - tours_covered
if uncovered:
    print(f"\n!! UNCOVERED TOURS: {len(uncovered)}")
    print(f"   Sample: {list(uncovered)[:10]}")
else:
    print("\n[OK] All tours covered by greedy blocks")
