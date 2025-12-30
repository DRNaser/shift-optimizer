#!/usr/bin/env python3
"""Fix use_tour_coverage in BRIDGING_LOOP - use is_compressed_week instead"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Replace use_tour_coverage with is_compressed_week in the BRIDGING_LOOP
text = text.replace(
    'if use_tour_coverage and round_num <= 6:',
    'if is_compressed_week and round_num <= 6:'
)

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Fixed: use_tour_coverage -> is_compressed_week")
