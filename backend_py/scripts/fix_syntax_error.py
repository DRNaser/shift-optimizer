#!/usr/bin/env python3
"""Fix syntax error in set_partition_solver.py caused by patch"""

import re

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Find and remove the malformed log_fn line
text = re.sub(
    r'log_fn\(.*?STEP8: SUPPORT_HELPERS.*?\n',
    '# >>> STEP8: SUPPORT_HELPERS\n',
    text,
    flags=re.DOTALL
)

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Fixed syntax error in set_partition_solver.py")
