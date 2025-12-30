
import re
import os

file_path = 'src/services/set_partition_solver.py'
if not os.path.exists(file_path):
    print(f"Error: {file_path} not found")
    exit(1)

with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace BRIDGING_LOOP with robust version
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
            
            # Bridging Logic (robust)
            added = 0
            built = 0
            
            if low_support_tours and hasattr(generator, 'generate_anchor_pack_variants'):
                # Sort for determinism
                anchors = sorted(low_support_tours, key=lambda t: (tour_support[t], t))[:150]
                
                res = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)

                # Case A: generator returns int
                if isinstance(res, int):
                    added = res
                    built = res # approximate
                # Case B: list
                else:
                    cols = list(res) if res else []
                    built = len(cols)
                    for col in cols:
                        if col.roster_id not in generator.pool:
                            generator.pool[col.roster_id] = col
                            added += 1
                
                dedup_dropped = max(0, built - added)
                log_fn(f"  Bridging: anchors={len(anchors)}, built={built}, added={added}, dedup_dropped={dedup_dropped}")
                log_fn(f"  First 3 anchors: {anchors[:3] if anchors else 'None'}")
        # <<< STEP8: BRIDGING_LOOP"""

pattern = re.compile(r'(\s+)# >>> STEP8: BRIDGING_LOOP.*?# <<< STEP8: BRIDGING_LOOP', re.DOTALL)
match = pattern.search(text)
if match:
    # Preserve leading whitespace of the match (e.g. 8 spaces)
    # The new_block starts with 8 spaces.
    # We replace the entire match.
    text = text.replace(match.group(0), '\n' + new_block)
    print("Replaced BRIDGING_LOOP with robust logic.")
else:
    print("Could not find BRIDGING_LOOP block to replace.")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
