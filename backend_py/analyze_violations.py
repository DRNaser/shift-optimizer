import json
from collections import defaultdict

with open('diag_run_result.json', 'r') as f:
    data = json.load(f)

# Aggregate by driver
driver_data = defaultdict(lambda: {'blocks_per_day': defaultdict(int), 'total_hours': 0.0, 'all_blocks': []})

for a in data.get('assignments', []):
    driver_id = a.get('driver_id', '')
    block = a.get('block', {})
    day = block.get('day', a.get('day', 'unknown'))
    hours = block.get('total_work_hours', 0)
    
    driver_data[driver_id]['blocks_per_day'][day] += 1
    driver_data[driver_id]['total_hours'] += hours
    driver_data[driver_id]['all_blocks'].append(block.get('id', 'unknown'))

# Show violators
for did in ['PT046', 'PT049', 'PT030', 'PT047', 'PT048']:
    d = driver_data[did]
    print(f"{did}: weekly_hours={d['total_hours']:.1f}h, blocks_per_day={dict(d['blocks_per_day'])}")
    if d['total_hours'] > 55:
        print(f"  -> VIOLATION: weekly hours > 55")
    for day, count in d['blocks_per_day'].items():
        if count > 2:
            print(f"  -> VIOLATION: {count} blocks on {day} > max 2")
