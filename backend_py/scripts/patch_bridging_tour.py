
import re
import os

file_path = 'src/services/set_partition_solver.py'
if not os.path.exists(file_path):
    print(f"Error: {file_path} not found")
    exit(1)

with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Insert all_tour_ids logic if missing
if 'all_tour_ids =' not in text:
    anchor = '    all_block_ids = set(b.block_id for b in block_infos)'
    insertion = '''    all_block_ids = set(b.block_id for b in block_infos)
    
    # >>> STEP8: EXTRACT TOUR IDS
    all_tour_ids = set()
    for b in block_infos:
        all_tour_ids.update(b.tour_ids)
    log_fn(f"Unique tours: {len(all_tour_ids)}")
    # <<< STEP8: EXTRACT TOUR IDS'''
    
    text = text.replace(anchor, insertion)
    print("Inserted all_tour_ids logic.")
else:
    print("all_tour_ids logic already present.")

# 2. Replace BRIDGING_LOOP
# Using exact string replacement for robustness
old_block = """        # >>> STEP8: BRIDGING_LOOP
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
        # <<< STEP8: BRIDGING_LOOP"""

new_block = """        # >>> STEP8: BRIDGING_LOOP
        # Check if compressed week
        _is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4
        if _is_compressed and round_num <= 6:
            # SWITCH TO TOUR-BASED COVERAGE
            log_fn(f"[POOL REPAIR R{round_num}] Coverage Mode: TOUR (Target: {len(all_tour_ids)})")
            
            tour_support = _compute_tour_support(columns, all_tour_ids, "covered_tour_ids")
            support_vals = list(tour_support.values())
            
            low_support_tours = [tid for tid, cnt in tour_support.items() if cnt <= 2]
            
            pct_low = (len(low_support_tours) / max(1, len(all_tour_ids))) * 100.0
            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)
            
            # ALSO LOG BLOCK STATS (for comparison)
            block_support = _compute_tour_support(columns, all_block_ids, "block_ids")
            bs_vals = list(block_support.values())
            bs_low = len([b for b, c in block_support.items() if c <= 2])
            bs_pct = (bs_low / max(1, len(all_block_ids))) * 100.0
            bs_min = min(bs_vals) if bs_vals else 0
            bs_p10 = _simple_percentile(bs_vals, 10)
            bs_p50 = _simple_percentile(bs_vals, 50)
            
            log_fn(f"  % tours support<=2: {len(low_support_tours)}/{len(all_tour_ids)} ({pct_low:.1f}%)")
            log_fn(f"  tour support min/p10/p50: {support_min}/{support_p10}/{support_p50}")
            
            log_fn(f"  % blocks support<=2: {bs_low}/{len(all_block_ids)} ({bs_pct:.1f}%)")
            log_fn(f"  block support min/p10/p50: {bs_min}/{bs_p10}/{bs_p50}")
            
            # Bridging Logic
            dedup_added = 0
            if low_support_tours and hasattr(generator, 'generate_anchor_pack_variants'):
                anchors = sorted(low_support_tours, key=lambda t: tour_support[t])[:150]
                new_cols = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)
                dedup_added = new_cols 
                
                log_fn(f"  Bridging: anchors={len(anchors)}, new_cols={new_cols}, dedup_added={dedup_added}")
        # <<< STEP8: BRIDGING_LOOP"""

if old_block in text:
    text = text.replace(old_block, new_block)
    print("Replaced BRIDGING_LOOP.")
else:
    print("Could not find exact BRIDGING_LOOP block. Check whitespace/content.")
    # Fallback to regex if exact match fails
    pattern = re.compile(r'(\s+)# >>> STEP8: BRIDGING_LOOP.*?# <<< STEP8: BRIDGING_LOOP', re.DOTALL)
    match = pattern.search(text)
    if match:
        print("Used regex fallback.")
        text = text.replace(match.group(0), new_block.replace('\n', '\n' + match.group(1).lstrip('\n')))
        # Simplified: Regex match includes '        # >>>'. replacement includes '        # >>>'.
        # Just replace match with new_block
        text = text.replace(match.group(0), '\n' + new_block) if not text[match.start()-1] == '\n' else text.replace(match.group(0), new_block)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
