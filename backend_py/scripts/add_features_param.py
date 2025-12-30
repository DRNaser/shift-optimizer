#!/usr/bin/env python3
"""Add features parameter to solve_set_partitioning"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Add features parameter before ) -> SetPartitionResult:
old = "    context: Optional[object] = None, # Added run context\n) -> SetPartitionResult:"
new = "    context: Optional[object] = None, # Added run context\n    features: Optional[dict] = None,  # Step 8: Instance features\n) -> SetPartitionResult:"

text = text.replace(old, new)

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Added features parameter")
