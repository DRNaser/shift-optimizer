#!/usr/bin/env python3
"""Analyze KPI reporting consistency"""
import json

with open("diag_run_result.json", "r") as f:
    d = json.load(f)

stats = d.get("stats", {})
assignments = d.get("assignments", [])

print("=" * 60)
print("KPI CONSISTENCY CHECK")
print("=" * 60)

# From stats
print("\n[STATS SECTION]")
print(f"  total_drivers: {stats.get('total_drivers')}")
print(f"  total_tours_input: {stats.get('total_tours_input')}")
print(f"  total_tours_assigned: {stats.get('total_tours_assigned')}")
print(f"  total_tours_unassigned: {stats.get('total_tours_unassigned')}")
print(f"  assignment_rate: {stats.get('assignment_rate')}")

block_counts = stats.get("block_counts", {})
print(f"\n  block_counts.1er: {block_counts.get('1er', 0)}")
print(f"  block_counts.2er: {block_counts.get('2er', 0)}")
print(f"  block_counts.3er: {block_counts.get('3er', 0)}")

# Calculate tours from block counts
tours_from_blocks = (
    block_counts.get('1er', 0) * 1 +
    block_counts.get('2er', 0) * 2 +
    block_counts.get('3er', 0) * 3
)
print(f"\n  CALCULATED tours from blocks: {tours_from_blocks}")
print(f"  (1*{block_counts.get('1er', 0)} + 2*{block_counts.get('2er', 0)} + 3*{block_counts.get('3er', 0)})")

# From actual assignments
print("\n[ASSIGNMENTS SECTION - ACTUAL DATA]")
print(f"  Number of assignment objects: {len(assignments)}")

unique_drivers = set(a["driver_id"] for a in assignments)
print(f"  Unique drivers: {len(unique_drivers)}")

# Count blocks and tours from actual assignments
blocks_by_type = {"1er": 0, "2er": 0, "3er": 0}
actual_blocks = {}
total_tours_in_assignments = 0

for a in assignments:
    block = a.get("block", {})
    block_id = block.get("id")
    block_type = block.get("block_type", "")
    tours = block.get("tours", [])
    
    if block_id not in actual_blocks:
        actual_blocks[block_id] = block_type
        blocks_by_type[block_type] = blocks_by_type.get(block_type, 0) + 1
    
    total_tours_in_assignments += len(tours)

print(f"  Unique blocks: {len(actual_blocks)}")
print(f"  Actual block counts: {blocks_by_type}")
print(f"  Total tours in assignment blocks: {total_tours_in_assignments}")

# Calculate expected tours from actual blocks
actual_tours_from_blocks = (
    blocks_by_type.get("1er", 0) * 1 +
    blocks_by_type.get("2er", 0) * 2 +
    blocks_by_type.get("3er", 0) * 3
)
print(f"  CALCULATED tours from actual blocks: {actual_tours_from_blocks}")

print("\n" + "=" * 60)
print("DISCREPANCY ANALYSIS")
print("=" * 60)
print(f"\nStats says tours_assigned = {stats.get('total_tours_assigned')}")
print(f"Stats block_counts → {tours_from_blocks} tours")
print(f"Actual assignments → {total_tours_in_assignments} tours in blocks")
print(f"Actual unique blocks → {actual_tours_from_blocks} tours")

if tours_from_blocks != stats.get('total_tours_assigned'):
    print(f"\n⚠️  MISMATCH: block_counts ({tours_from_blocks}) ≠ total_tours_assigned ({stats.get('total_tours_assigned')})")
    print("   This suggests block_counts may include candidates, not final assignments")
