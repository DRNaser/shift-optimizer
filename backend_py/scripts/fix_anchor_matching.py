#!/usr/bin/env python3
"""Fix anchor matching in apply_step8_pool_repair_patch.py"""

text = open('scripts/apply_step8_pool_repair_patch.py', 'r', encoding='utf-8').read()

# Fix: use 'in' instead of 'startswith' for anchor matching
text = text.replace(
    "if line.replace('\\r', '').startswith(anchor_def):",
    "if anchor_def in line.replace('\\r', ''):"
)

open('scripts/apply_step8_pool_repair_patch.py', 'w', encoding='utf-8').write(text)
print("Fixed anchor matching (startswith -> contains)")
