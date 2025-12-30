#!/usr/bin/env python3
"""Fix all anchors in apply_step8_pool_repair_patch.py to match actual file content"""

text = open('scripts/apply_step8_pool_repair_patch.py', 'r', encoding='utf-8').read()

# Fix solver.py anchors to match actual content
replacements = [
    # Enhanced logging anchor
    ('log_fn(f"Selected {num_drivers} rosters (drivers)")', 'rmp_result = solve_rmp('),
    
    # Incumbent call anchor - use actual comment
    ('"# STEP 3: MAIN LOOP - RMP + Column Generation"', '"# STEP 3: MAIN LOOP"'),
    
    # Bridging anchor
    ('"solve_relaxed_rmp("', '"relaxed = solve_relaxed_rmp("'),
]

for old, new in replacements:
    text = text.replace(old, new)

open('scripts/apply_step8_pool_repair_patch.py', 'w', encoding='utf-8').write(text)
print(f"Fixed {len(replacements)} anchors")
