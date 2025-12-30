#!/usr/bin/env python3
"""Fix the Singleton generation mistake - revert incorrect incumbent_id usage"""

text = open('src/services/roster_column_generator.py', 'r', encoding='utf-8').read()

# The problem: patch_generator.py replaced ALL occurrences of self._get_next_roster_id()
# including in generate_singleton_columns. We need to restore those.

# Count how many incumbent_id are in the file
count_before = text.count('roster_id=incumbent_id')
print(f"Found {count_before} occurrences of roster_id=incumbent_id")

# Find generate_singleton_columns and restore the roster_id lines within it
lines = text.split('\n')
in_singleton_method = False
fixed = 0

for i, line in enumerate(lines):
    if 'def generate_singleton_columns' in line:
        in_singleton_method = True
    if in_singleton_method and 'roster_id=incumbent_id' in line:
        lines[i] = line.replace('roster_id=incumbent_id', 'roster_id=self._get_next_roster_id()')
        fixed += 1
    # Exit singleton method when we hit another def at same indent
    if in_singleton_method and 'def ' in line and 'generate_singleton_columns' not in line:
        in_singleton_method = False

text = '\n'.join(lines)
open('src/services/roster_column_generator.py', 'w', encoding='utf-8').write(text)
print(f"Fixed {fixed} incorrect replacements in generate_singleton_columns")
