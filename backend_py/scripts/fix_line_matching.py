#!/usr/bin/env python3
"""Fix line matching in apply_step8_pool_repair_patch.py"""

text = open('scripts/apply_step8_pool_repair_patch.py', 'r', encoding='utf-8').read()

# Fix line matching - only remove \r, not all whitespace
text = text.replace(
    "if line.rstrip().startswith(anchor_def):",
    "if line.replace('\\r', '').startswith(anchor_def):"
)

text = text.replace(
    "if l.rstrip().startswith(\"def \") or l.rstrip().startswith(\"class \"):",
    "l_clean = l.replace('\\r', '')\n        if l_clean.startswith(\"def \") or l_clean.startswith(\"class \"):"
)

open('scripts/apply_step8_pool_repair_patch.py', 'w', encoding='utf-8').write(text)
print("Fixed line matching in patch script")
