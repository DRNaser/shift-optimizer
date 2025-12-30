#!/usr/bin/env python3
"""Insert Step 8 patches into set_partition_solver.py at correct locations"""

# Read file
text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Check if already patched
if '# >>> STEP8: SUPPORT_HELPERS' in text:
    print("Already patched - skipping")
    exit(0)

lines = text.split('\n')

# ============================================================
# PATCH A: SUPPORT_HELPERS after line 28 (logger line)
# ============================================================
SUPPORT_HELPERS = '''
# >>> STEP8: SUPPORT_HELPERS (TOP-LEVEL)
def _compute_tour_support(columns, target_ids, coverage_attr):
    support = {tid: 0 for tid in target_ids}
    for col in columns:
        items = getattr(col, coverage_attr, col.block_ids)
        for tid in items:
            if tid in support:
                support[tid] += 1
    return support


def _simple_percentile(values, p):
    if not values:
        return 0
    vals = sorted(values)
    idx = int(len(vals) * p / 100.0)
    if idx < 0:
        idx = 0
    if idx >= len(vals):
        idx = len(vals) - 1
    return vals[idx]
# <<< STEP8: SUPPORT_HELPERS
'''

# Find logger line
for i, line in enumerate(lines):
    if 'logger = logging.getLogger("SetPartitionSolver")' in line:
        lines.insert(i + 1, SUPPORT_HELPERS)
        print(f"[A] Inserted SUPPORT_HELPERS after line {i+1}")
        break

# ============================================================
# PATCH B: INCUMBENT_CALL before RMP loop
# ============================================================
INCUMBENT_CALL = '''
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

# Rebuild text after first insert
text = '\n'.join(lines)
lines = text.split('\n')

# Find RMP loop line
for i, line in enumerate(lines):
    if 'for round_num in range(1, max_rounds + 1):' in line:
        lines.insert(i, INCUMBENT_CALL)
        print(f"[B] Inserted INCUMBENT_CALL before line {i+1}")
        break

# ============================================================
# PATCH C: BRIDGING_LOOP after relaxed solve result extraction
# ============================================================
BRIDGING_LOOP = '''
        # >>> STEP8: BRIDGING_LOOP
        if use_tour_coverage and round_num <= 6:
            support_stats = _compute_tour_support(columns, effective_target_ids, effective_coverage_attr)
            support_vals = list(support_stats.values())

            low_support_tours = [tid for tid, cnt in support_stats.items() if cnt <= 2]
            pct_low = (len(low_support_tours) / max(1, len(effective_target_ids))) * 100.0

            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)

            log_fn(f"[POOL REPAIR R{round_num}] Support:")
            log_fn(f"  tours support<=2: {len(low_support_tours)}/{len(effective_target_ids)} ({pct_low:.1f}%)")
            log_fn(f"  support min/p10/p50: {support_min}/{support_p10}/{support_p50}")

            anchors = sorted(low_support_tours, key=lambda t: support_stats[t])[:150]
            new_bridging = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)
            log_fn(f"  generated anchor-pack: {new_bridging}")
        # <<< STEP8: BRIDGING_LOOP
'''

# Rebuild text after second insert
text = '\n'.join(lines)
lines = text.split('\n')

# Find "over_count = relaxed.get" line (after relaxed solve result extraction)
for i, line in enumerate(lines):
    if 'over_count = relaxed.get("over_count", 0)' in line:
        lines.insert(i + 1, BRIDGING_LOOP)
        print(f"[C] Inserted BRIDGING_LOOP after line {i+1}")
        break

# Write back
text = '\n'.join(lines)
open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Done!")
