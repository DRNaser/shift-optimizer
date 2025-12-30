#!/usr/bin/env python3
"""Fix the INCUMBENT_CALL position - move it after greedy_assignments is defined"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Remove the incorrectly positioned INCUMBENT_CALL
old_block = '''
    # >>> STEP8: INCUMBENT_NEIGHBORHOOD_CALL
    if greedy_assignments and is_compressed_week and use_tour_coverage:
        incumbent_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
        if incumbent_cols:
            log_fn(f"[INCUMBENT NEIGHBORHOOD] {len(incumbent_cols)} INC_GREEDY_ columns detected")
            added = generator.generate_incumbent_neighborhood(
                active_days=features.get("active_days", ["Mon", "Tue", "Wed", "Fri"]),
                max_variants=500,
            )
            log_fn(f"  Added {added} incumbent variants")
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD_CALL
'''

text = text.replace(old_block, '')
print("Removed old INCUMBENT_CALL block")

# Now insert it after seed_from_greedy (line ~578)
# Find the correct position: after "seeded_count = generator.seed_from_greedy"
lines = text.split('\n')

new_block = '''
    # >>> STEP8: INCUMBENT_NEIGHBORHOOD_CALL
    incumbent_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
    if incumbent_cols and is_compressed_week and use_tour_coverage:
        log_fn(f"[INCUMBENT NEIGHBORHOOD] {len(incumbent_cols)} INC_GREEDY_ columns detected")
        added = generator.generate_incumbent_neighborhood(
            active_days=features.get("active_days", ["Mon", "Tue", "Wed", "Fri"]) if features else ["Mon", "Tue", "Wed", "Fri"],
            max_variants=500,
        )
        log_fn(f"  Added {added} incumbent variants")
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD_CALL
'''

for i, line in enumerate(lines):
    if 'seeded_count = generator.seed_from_greedy' in line:
        lines.insert(i + 1, new_block)
        print(f"Inserted INCUMBENT_CALL after line {i+1}")
        break

text = '\n'.join(lines)
open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Done!")
