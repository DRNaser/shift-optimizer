#!/usr/bin/env python3
"""Rewrite BRIDGING_LOOP with correct scoping - use only available variables"""

text = open('src/services/set_partition_solver.py', 'r', encoding='utf-8').read()

# Remove the old broken BRIDGING_LOOP
old_block = '''        # >>> STEP8: BRIDGING_LOOP
        # Check if compressed week (4 active days instead of 5/6)
        _is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4
        if _is_compressed and round_num <= 6:
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
        # <<< STEP8: BRIDGING_LOOP'''

# New BRIDGING_LOOP using only variables available at that scope:
# - columns (list of RosterColumn from generator.pool)  
# - all_block_ids (set of block IDs)
# - generator (RosterColumnGenerator)
# - round_num, features, log_fn
new_block = '''        # >>> STEP8: BRIDGING_LOOP
        # Simplified bridging using block_ids as coverage target (available vars only)
        _is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4
        if _is_compressed and round_num <= 6:
            # Compute block support (how many columns cover each block)
            block_support = _compute_tour_support(columns, all_block_ids, "block_ids")
            support_vals = list(block_support.values())
            
            low_support_blocks = [bid for bid, cnt in block_support.items() if cnt <= 2]
            pct_low = (len(low_support_blocks) / max(1, len(all_block_ids))) * 100.0
            
            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)
            
            log_fn(f"[POOL REPAIR R{round_num}] Block Support:")
            log_fn(f"  blocks support<=2: {len(low_support_blocks)}/{len(all_block_ids)} ({pct_low:.1f}%)")
            log_fn(f"  support min/p10/p50: {support_min}/{support_p10}/{support_p50}")
            
            # Generate anchor-pack variants for low-support blocks
            if low_support_blocks and hasattr(generator, 'generate_anchor_pack_variants'):
                anchors = sorted(low_support_blocks, key=lambda b: block_support[b])[:150]
                new_bridging = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)
                log_fn(f"  generated anchor-pack: {new_bridging}")
        # <<< STEP8: BRIDGING_LOOP'''

text = text.replace(old_block, new_block)

open('src/services/set_partition_solver.py', 'w', encoding='utf-8').write(text)
print("Rewrote BRIDGING_LOOP with correct variable scoping")
