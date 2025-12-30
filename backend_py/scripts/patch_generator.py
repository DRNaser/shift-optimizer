#!/usr/bin/env python3
"""Insert Step 8 patches into roster_column_generator.py"""

text = open('src/services/roster_column_generator.py', 'r', encoding='utf-8').read()

if '# >>> STEP8: INCUMBENT_NEIGHBORHOOD' in text:
    print("Already patched - skipping")
    exit(0)

lines = text.split('\n')

# Find seed_from_greedy method
INCUMBENT_SEED_FIX = '''        # CRITICAL: Mark with INC_GREEDY_ prefix for incumbent identification
        incumbent_count = len([c for c in self.pool.values() if c.roster_id.startswith('INC_GREEDY_')])
        incumbent_id = f"INC_GREEDY_{incumbent_count:04d}"
        
        # Create column based on driver type'''

# Find and patch the seed_from_greedy method to use INC_GREEDY_ prefix
for i, line in enumerate(lines):
    if 'roster_id=self._get_next_roster_id(),' in line and i > 1100:
        # Replace with incumbent_id
        lines[i] = line.replace('self._get_next_roster_id()', 'incumbent_id')
        print(f"Fixed roster_id at line {i+1}")

# Also need to insert incumbent_count before the first usage
for i, line in enumerate(lines):
    if '# Create column based on driver type' in line and i > 1100 and i < 1200:
        # Insert the incumbent ID calculation before this
        lines[i] = '''            # CRITICAL: Mark with INC_GREEDY_ prefix
            incumbent_count = len([c for c in self.pool.values() if c.roster_id.startswith('INC_GREEDY_')])
            incumbent_id = f"INC_GREEDY_{incumbent_count:04d}"
            
            # Create column based on driver type'''
        print(f"Inserted INC_GREEDY_ logic at line {i+1}")
        break

# Find generate_singleton_columns to insert methods before it
METHODS = '''
    # >>> STEP8: INCUMBENT_NEIGHBORHOOD
    def generate_incumbent_neighborhood(self, active_days, max_variants=500):
        """Generate column families around greedy incumbent (INC_GREEDY_ only)."""
        incumbent_rosters = [col for col in self.pool.values() 
                             if col.roster_id.startswith('INC_GREEDY_')]
        if not incumbent_rosters:
            self.log_fn("[INC NBHD] No INC_GREEDY_ columns")
            return 0
        self.log_fn(f"[INC NBHD] Generating variants around {len(incumbent_rosters)} incumbents...")
        added = 0
        day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5}
        active_day_indices = [day_map[d] for d in active_days if d in day_map]
        existing_sigs = {col.covered_tour_ids for col in self.pool.values()}
        sorted_rosters = sorted(incumbent_rosters, key=lambda r: r.roster_id)
        for i, r1 in enumerate(sorted_rosters):
            if added >= max_variants:
                break
            for j in range(i + 1, min(i + 11, len(sorted_rosters))):
                r2 = sorted_rosters[j]
                for day_idx in active_day_indices:
                    r1_day = [bid for bid in r1.block_ids if bid in self.block_by_id and self.block_by_id[bid].day == day_idx]
                    r2_day = [bid for bid in r2.block_ids if bid in self.block_by_id and self.block_by_id[bid].day == day_idx]
                    if not r1_day and not r2_day:
                        continue
                    new_r1 = [bid for bid in r1.block_ids if bid not in r1_day] + r2_day
                    new_r2 = [bid for bid in r2.block_ids if bid not in r2_day] + r1_day
                    for new_bids in [new_r1, new_r2]:
                        if added >= max_variants:
                            break
                        block_infos = [self.block_by_id[bid] for bid in new_bids if bid in self.block_by_id]
                        if not block_infos:
                            continue
                        total_min = sum(b.work_min for b in block_infos)
                        if total_min > 55 * 60:
                            continue
                        tour_ids = set()
                        valid = True
                        for b in block_infos:
                            for tid in b.tour_ids:
                                if tid in tour_ids:
                                    valid = False
                                    break
                                tour_ids.add(tid)
                            if not valid:
                                break
                        if not valid or not tour_ids:
                            continue
                        sig = frozenset(tour_ids)
                        if sig in existing_sigs:
                            continue
                        col = create_roster_from_blocks_pt(roster_id=self._get_next_roster_id(), block_infos=block_infos)
                        if col and col.is_valid and self.add_column(col):
                            added += 1
                            existing_sigs.add(sig)
        self.log_fn(f"[INC NBHD] Total: {added}")
        return added
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD

    # >>> STEP8: ANCHOR_PACK
    def generate_anchor_pack_variants(self, anchor_tour_ids, max_variants_per_anchor=5):
        """Generate variants around anchor tours (low support)."""
        self.log_fn(f"[ANCHOR&PACK] {len(anchor_tour_ids)} anchors...")
        added = 0
        existing_sigs = {col.covered_tour_ids for col in self.pool.values()}
        for anchor_tid in anchor_tour_ids:
            anchor_blocks = [b for b in self.block_infos if anchor_tid in b.tour_ids]
            if not anchor_blocks:
                continue
            anchor_blocks.sort(key=lambda b: (-b.tours, -b.work_min, b.block_id))
            for anchor_block in anchor_blocks[:3]:
                if added >= len(anchor_tour_ids) * max_variants_per_anchor:
                    break
                current = [anchor_block]
                current_tours = set(anchor_block.tour_ids)
                current_min = anchor_block.work_min
                for day_idx in [d for d in range(6) if d != anchor_block.day]:
                    day_cands = [b for b in self.block_infos if b.day == day_idx and not any(tid in current_tours for tid in b.tour_ids)]
                    if not day_cands:
                        continue
                    day_cands.sort(key=lambda b: (-b.tours, -b.work_min, b.block_id))
                    for cand in day_cands[:2]:
                        if current_min + cand.work_min > 55 * 60:
                            continue
                        if any(tid in current_tours for tid in cand.tour_ids):
                            continue
                        current.append(cand)
                        current_tours.update(cand.tour_ids)
                        current_min += cand.work_min
                        break
                if not current_tours:
                    continue
                sig = frozenset(current_tours)
                if sig in existing_sigs:
                    continue
                col = create_roster_from_blocks_pt(roster_id=self._get_next_roster_id(), block_infos=current)
                if col and col.is_valid and self.add_column(col):
                    added += 1
                    existing_sigs.add(sig)
        self.log_fn(f"[ANCHOR&PACK] {added} variants")
        return added
    # <<< STEP8: ANCHOR_PACK
'''

text = '\n'.join(lines)
lines = text.split('\n')

for i, line in enumerate(lines):
    if 'def generate_singleton_columns(self, penalty_factor' in line:
        lines.insert(i, METHODS)
        print(f"Inserted methods before line {i+1}")
        break

text = '\n'.join(lines)
open('src/services/roster_column_generator.py', 'w', encoding='utf-8').write(text)
print("Done!")
