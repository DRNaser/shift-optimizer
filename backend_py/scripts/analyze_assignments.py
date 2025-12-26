#!/usr/bin/env python3
"""Analyze assignment structure"""
import json

with open("diag_run_result.json", "r") as f:
    d = json.load(f)

a = d["assignments"]
print("First 10 assignments:")
for x in a[:10]:
    bt = x["block"]["block_type"]
    bid = x["block"]["id"]
    tours = len(x["block"]["tours"])
    print(f"  Driver: {x['driver_id']:10} Day: {x['day']:3} Block: {bid:25} ({bt}) Tours: {tours}")

# Count by driver
driver_days = {}
for x in a:
    did = x["driver_id"]
    driver_days[did] = driver_days.get(did, 0) + 1

print(f"\nDrivers with most days:")
top = sorted(driver_days.items(), key=lambda x: -x[1])[:10]
for did, days in top:
    print(f"  {did}: {days} days")

print(f"\nSummary:")
print(f"  Assignment objects (driver-day-blocks): {len(a)}")
print(f"  Unique drivers: {len(driver_days)}")
print(f"  Average days per driver: {sum(driver_days.values())/len(driver_days):.1f}")

# Now the real check - count unique blocks
unique_blocks = {}
for x in a:
    bid = x["block"]["id"]
    bt = x["block"]["block_type"]
    unique_blocks[bid] = bt

block_type_counts = {}
for bid, bt in unique_blocks.items():
    block_type_counts[bt] = block_type_counts.get(bt, 0) + 1

print(f"\nActual unique block counts: {block_type_counts}")
total_tours = sum([1 if '1er' in bt else 2 if '2er' in bt else 3 for bt in unique_blocks.values()])
print(f"Total tours from unique blocks: {total_tours}")

# Count actual tours
all_tours = set()
for x in a:
    for t in x["block"]["tours"]:
        all_tours.add(t["id"])
print(f"Unique tour IDs in assignments: {len(all_tours)}")
