import json
import hashlib

with open('rc1_run1.json', 'r', encoding='utf-8') as f:
    d1 = json.load(f)
with open('rc1_run2.json', 'r', encoding='utf-8') as f:
    d2 = json.load(f)

# Hash assignments for determinism
a1 = sorted([str(a) for a in d1.get('assignments', [])])
a2 = sorted([str(a) for a in d2.get('assignments', [])])
h1 = hashlib.sha256('|'.join(a1).encode()).hexdigest()[:16]
h2 = hashlib.sha256('|'.join(a2).encode()).hexdigest()[:16]

# Stats
s1 = d1.get('stats', {})
s2 = d2.get('stats', {})

print("=" * 60)
print("DETERMINISM GATE - EVIDENCE")
print("=" * 60)
print(f"Run1 assignments hash: {h1}")
print(f"Run2 assignments hash: {h2}")
print(f"Run1 drivers: {s1.get('total_drivers')}")
print(f"Run2 drivers: {s2.get('total_drivers')}")
print(f"Run1 tours: {s1.get('total_tours_assigned')}")
print(f"Run2 tours: {s2.get('total_tours_assigned')}")
print(f"Run1 block_counts: {s1.get('block_counts')}")
print(f"Run2 block_counts: {s2.get('block_counts')}")
print("=" * 60)
print("DETERMINISM:", "PASS" if (h1 == h2) else "FAIL")
print("=" * 60)
