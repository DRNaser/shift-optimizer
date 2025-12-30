#!/usr/bin/env python3
"""Fix is_compressed_week - define it based on features before use"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Find the BRIDGING_LOOP block and add is_compressed_week check before it
old_block = '''        # >>> STEP8: BRIDGING_LOOP
        if is_compressed_week and round_num <= 6:'''

new_block = '''        # >>> STEP8: BRIDGING_LOOP
        # Check if compressed week (4 active days instead of 5/6)
        _is_compressed = features is not None and len(features.get("active_days", [])) <= 4
        if _is_compressed and round_num <= 6:'''

text = text.replace(old_block, new_block)

# Also fix the INCUMBENT_CALL if it still references is_compressed_week
text = text.replace('if incumbent_cols and is_compressed_week and use_tour_coverage:', 
                    'if incumbent_cols:')

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Fixed is_compressed_week reference")
