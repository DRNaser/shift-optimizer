#!/usr/bin/env python3
"""Fix FeatureVector access - use getattr instead of .get()"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Fix FeatureVector access 
text = text.replace(
    '_is_compressed = features is not None and len(features.get("active_days", [])) <= 4',
    '_is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4'
)

text = text.replace(
    'active_days=features.get("active_days", ["Mon", "Tue", "Wed", "Fri"]) if features else ["Mon", "Tue", "Wed", "Fri"]',
    'active_days=getattr(features, "active_days", ["Mon", "Tue", "Wed", "Fri"]) if features else ["Mon", "Tue", "Wed", "Fri"]'
)

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Fixed FeatureVector access")
