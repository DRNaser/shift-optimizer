#!/usr/bin/env python3
"""
Step 8 Pool Repair Patch Script (Indentation-Based, No Regex)

Applies minimal, additive changes to implement Pool Repair mechanisms.
Uses indentation-based anchors for robustness across OS and line endings.

Usage:
    python scripts/apply_step8_pool_repair_patch.py          # Apply patches
    python scripts/apply_step8_pool_repair_patch.py --dry-run  # Preview changes
"""

from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass

# ===========================================================================
# CODE BLOCKS (with markers for idempotency)
# ===========================================================================

INCUMBENT_NEIGHBORHOOD_BLOCK = '''    # >>> STEP8: INCUMBENT_NEIGHBORHOOD
    def generate_incumbent_neighborhood(
        self,
        active_days: list[str],
        max_variants: int = 500,
    ) -> int:
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
        
        # Day-Swap
        sorted_rosters = sorted(incumbent_rosters, key=lambda r: r.roster_id)
        variants_1 = 0
        
        for i, r1 in enumerate(sorted_rosters):
            if added >= max_variants:
                break
            for j in range(i + 1, min(i + 11, len(sorted_rosters))):
                r2 = sorted_rosters[j]
                for day_idx in active_day_indices:
                    r1_day = [bid for bid in r1.block_ids 
                              if bid in self.block_by_id and self.block_by_id[bid].day == day_idx]
                    r2_day = [bid for bid in r2.block_ids 
                              if bid in self.block_by_id and self.block_by_id[bid].day == day_idx]
                    
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
                        
                        col = create_roster_from_blocks_pt(
                            roster_id=self._get_next_roster_id(),
                            block_infos=block_infos,
                        )
                        
                        if col and col.is_valid and self.add_column(col):
                            added += 1
                            variants_1 += 1
                            existing_sigs.add(sig)
        
        self.log_fn(f"  Day-Swap: {variants_1}")
        
        # Anchor Repack
        tour_support = {}
        for col in self.pool.values():
            for tid in col.covered_tour_ids:
                tour_support[tid] = tour_support.get(tid, 0) + 1
        
        low_support = sorted([tid for tid, cnt in tour_support.items() if cnt <= 2],
                             key=lambda t: (tour_support.get(t, 0), t))[:50]
        
        variants_2 = 0
        for anchor_tid in low_support:
            if added >= max_variants:
                break
            
            related = [r for r in sorted_rosters if anchor_tid in r.covered_tour_ids]
            if not related or len(related) > 8 or len(related) < 3:
                continue
            
            S_tours = set()
            for r in related:
                S_tours.update(r.covered_tour_ids)
            
            if len(S_tours) > 30:
                continue
            
            S_blocks = [b for b in self.block_infos if any(tid in S_tours for tid in b.tour_ids)]
            if len(S_blocks) < 3:
                continue
            
            day_blocks = {d: [] for d in active_day_indices}
            for b in S_blocks:
                if b.day in active_day_indices:
                    day_blocks[b.day].append(b)
            
            for d in active_day_indices:
                day_blocks[d].sort(key=lambda b: (-b.tours, b.block_id))
            
            for var_idx in range(min(5, max_variants - added)):
                current = []
                current_tours = set()
                current_min = 0
                
                for day in active_day_indices:
                    cands = day_blocks[day]
                    if not cands:
                        continue
                    cand = cands[var_idx % len(cands)]
                    
                    if any(tid in current_tours for tid in cand.tour_ids):
                        continue
                    if current_min + cand.work_min > 55 * 60:
                        continue
                    
                    current.append(cand)
                    current_tours.update(cand.tour_ids)
                    current_min += cand.work_min
                
                if not current or not current_tours:
                    continue
                
                sig = frozenset(current_tours)
                if sig in existing_sigs:
                    continue
                
                col = create_roster_from_blocks_pt(
                    roster_id=self._get_next_roster_id(),
                    block_infos=current,
                )
                
                if col and col.is_valid and self.add_column(col):
                    added += 1
                    variants_2 += 1
                    existing_sigs.add(sig)
        
        self.log_fn(f"  Anchor Repack: {variants_2}")
        self.log_fn(f"[INC NBHD] Total: {added}")
        return added
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD

'''

ANCHOR_PACK_BLOCK = '''    # >>> STEP8: ANCHOR_PACK
    def generate_anchor_pack_variants(
        self,
        anchor_tour_ids: list[str],
        max_variants_per_anchor: int = 5,
    ) -> int:
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
                
                other_days = [d for d in range(6) if d != anchor_block.day]
                
                for day_idx in other_days:
                    day_cands = [b for b in self.block_infos 
                                 if b.day == day_idx and not any(tid in current_tours for tid in b.tour_ids)]
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
                
                col = create_roster_from_blocks_pt(
                    roster_id=self._get_next_roster_id(),
                    block_infos=current,
                )
                
                if col and col.is_valid and self.add_column(col):
                    added += 1
                    existing_sigs.add(sig)
        
        self.log_fn(f"[ANCHOR&PACK] {added} variants")
        return added
    # <<< STEP8: ANCHOR_PACK

'''

SUPPORT_HELPERS = '''# >>> STEP8: SUPPORT_HELPERS
def _compute_tour_support(columns, target_ids, coverage_attr):
    """Compute support count for each tour_id."""
    support = {tid: 0 for tid in target_ids}
    for col in columns:
        items = getattr(col, coverage_attr, col.block_ids)
        for tid in items:
            if tid in support:
                support[tid] += 1
    return support


def _simple_percentile(values, p):
    """Simple percentile without numpy."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * p / 100.0)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]
# <<< STEP8: SUPPORT_HELPERS

'''

INCUMBENT_CALL = '''        # >>> STEP8: INCUMBENT_CALL
        if greedy_assignments and is_compressed_week and use_tour_coverage:
            incumbent_count = len([c for c in generator.pool.values() if c.roster_id.startswith('INC_GREEDY_')])
            if incumbent_count > 0:
                log_fn(f"\\n[INCUMBENT NEIGHBORHOOD] {incumbent_count} INC_GREEDY_ columns detected")
                added = generator.generate_incumbent_neighborhood(
                    active_days=features.get("active_days", ["Mon", "Tue", "Wed", "Fri"]),
                    max_variants=500,
                )
                log_fn(f"  Added {added} incumbent variants\\n")
        # <<< STEP8: INCUMBENT_CALL
        
'''

BRIDGING_LOOP = '''        # >>> STEP8: BRIDGING
        if use_tour_coverage and round_num <= 6:
            support_stats = _compute_tour_support(columns, effective_target_ids, effective_coverage_attr)
            
            low_support_tours = [tid for tid, cnt in support_stats.items() if cnt <= 2]
            pct_low = len(low_support_tours) / max(1, len(effective_target_ids)) * 100
            
            support_vals = list(support_stats.values())
            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)
            
            log_fn(f"\\n[POOL REPAIR R{round_num}]")
            log_fn(f"  Tours support<=2: {len(low_support_tours)}/{len(effective_target_ids)} ({pct_low:.1f}%)")
            log_fn(f"  Support min/p10/p50: {support_min}/{support_p10}/{support_p50}")
            
            if round_num == 1:
                best_pct_low = pct_low
                best_p10 = support_p10
            
            anchors = sorted(low_support_tours, key=lambda t: support_stats[t])[:150]
            new_cols = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)
            log_fn(f"  Generated {new_cols} anchor variants (max 750)")
            
            if round_num >= 3:
                pct_improvement = best_pct_low - pct_low
                p10_improvement = support_p10 - best_p10
                
                if pct_improvement < 2.0 and p10_improvement < 1:
                    log_fn(f"[STOP GATE] No improvement 2 rounds (pct_low Δ={pct_improvement:.1f}, p10 Δ={p10_improvement})")
                    if round_num >= 4:
                        break
                else:
                    best_pct_low = min(best_pct_low, pct_low)
                    best_p10 = max(best_p10, support_p10)
        # <<< STEP8: BRIDGING
        
'''

ENHANCED_LOGGING = '''            # >>> STEP8: ENHANCED_LOGGING
            selected_tours = [len(col.covered_tour_ids) for col in rmp_result.get("selected_rosters", [])]
            hist_1 = sum(1 for x in selected_tours if x == 1)
            hist_2_3 = sum(1 for x in selected_tours if 2 <= x <= 3)
            hist_4_6 = sum(1 for x in selected_tours if 4 <= x <= 6)
            hist_7p = sum(1 for x in selected_tours if x >= 7)
            log_fn(f"  Selected histogram: 1={hist_1}, 2-3={hist_2_3}, 4-6={hist_4_6}, 7+={hist_7p}")
            # <<< STEP8: ENHANCED_LOGGING
'''

# ===========================================================================
# INDENTATION-BASED INSERT HELPERS
# ===========================================================================

@dataclass
class InsertSpec:
    file_path: Path
    anchor_def: str
    marker_begin: str
    marker_end: str
    payload: str


def normalize_newlines(s: str) -> tuple[str, str]:
    """Return (text_with_LF, original_newline)."""
    nl = "\\r\\n" if "\\r\\n" in s else "\\n"
    return s.replace("\\r\\n", "\\n"), nl


def already_patched(text: str, marker_begin: str) -> bool:
    return marker_begin in text


def insert_after_def_block(text: str, anchor_def: str, payload: str) -> str:
    """Insert payload after the block starting with anchor_def."""
    lines = text.split("\\n")
    start = None
    for i, line in enumerate(lines):
        if anchor_def in line.replace('\r', ''):
            start = i
            break
    if start is None:
        raise RuntimeError(f"Anchor not found: {anchor_def}")
    
    # Find end: next top-level def/class
    end = None
    for j in range(start + 1, len(lines)):
        l = lines[j]
        l_clean = l.replace('\r', '')
        if l_clean.startswith("def ") or l_clean.startswith("class "):
            end = j
            break
    if end is None:
        end = len(lines)
    
    new_lines = lines[:end] + ["", payload.rstrip("\\n"), ""] + lines[end:]
    return "\\n".join(new_lines)


def insert_after_first_occurrence(text: str, anchor_line_contains: str, payload: str) -> str:
    """Insert payload after first line containing anchor."""
    lines = text.split("\\n")
    for i, line in enumerate(lines):
        if anchor_line_contains in line:
            insert_at = i + 1
            new_lines = lines[:insert_at] + [payload.rstrip("\\n")] + lines[insert_at:]
            return "\\n".join(new_lines)
    raise RuntimeError(f"Anchor line not found containing: {anchor_line_contains}")


def apply_insert(file_text: str, spec: InsertSpec) -> str:
    """Apply insert if not already present."""
    txt, nl = normalize_newlines(file_text)
    if already_patched(txt, spec.marker_begin):
        return file_text
    
    patched = insert_after_def_block(txt, spec.anchor_def, spec.payload)
    return patched.replace("\\n", nl)


def apply_insert_after_line(file_text: str, anchor_line: str, marker_begin: str, payload: str) -> str:
    """Apply insert after specific line."""
    txt, nl = normalize_newlines(file_text)
    if already_patched(txt, marker_begin):
        return file_text
    
    patched = insert_after_first_occurrence(txt, anchor_line, payload)
    return patched.replace("\\n", nl)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    dry_run = '--dry-run' in sys.argv
    
    if dry_run:
        print("[DRY RUN] Preview mode - no files will be modified\\n")
    
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent
    generator_file = backend_dir / "src" / "services" / "roster_column_generator.py"
    solver_file = backend_dir / "src" / "services" / "set_partition_solver.py"
    
    print("[*] Step 8 Pool Repair Patch (Indentation-Based)\\n")
    
    # Patch 1: roster_column_generator.py
    print(f"[*] Processing: {generator_file}")
    
    try:
        gen_text = generator_file.read_text(encoding='utf-8')
        
        # Insert after seed_from_greedy
        spec1 = InsertSpec(
            file_path=generator_file,
            anchor_def="    def seed_from_greedy",
            marker_begin="# >>> STEP8: INCUMBENT_NEIGHBORHOOD",
            marker_end="# <<< STEP8: INCUMBENT_NEIGHBORHOOD",
            payload=INCUMBENT_NEIGHBORHOOD_BLOCK,
        )
        gen_text = apply_insert(gen_text, spec1)
        
        spec2 = InsertSpec(
            file_path=generator_file,
            anchor_def="    def generate_incumbent_neighborhood" if "# >>> STEP8: INCUMBENT_NEIGHBORHOOD" in gen_text else "    def seed_from_greedy",
            marker_begin="# >>> STEP8: ANCHOR_PACK",
            marker_end="# <<< STEP8: ANCHOR_PACK",
            payload=ANCHOR_PACK_BLOCK,
        )
        gen_text = apply_insert(gen_text, spec2)
        
        if not dry_run:
            generator_file.write_text(gen_text, encoding='utf-8')
        
        print("  [+] Added: generate_incumbent_neighborhood")
        print("  [+] Added: generate_anchor_pack_variants")
    except Exception as e:
        print(f"  [X] Error: {e}")
        return False
    
    # Patch 2: set_partition_solver.py
    print(f"\\n[*] Processing: {solver_file}")
    
    try:
        solver_text = solver_file.read_text(encoding='utf-8')
        
        # Support helpers before solve_set_partitioning
        solver_text = apply_insert_after_line(
            solver_text,
            "def solve_set_partitioning(",
            "# >>> STEP8: SUPPORT_HELPERS",
            SUPPORT_HELPERS
        )
        
        # Incumbent call after "STEP 3: MAIN LOOP"
        solver_text = apply_insert_after_line(
            solver_text,
            "# STEP 3: MAIN LOOP",
            "# >>> STEP8: INCUMBENT_CALL",
            INCUMBENT_CALL
        )
        
        # Bridging after relaxed solve
        solver_text = apply_insert_after_line(
            solver_text,
            "relaxed = solve_relaxed_rmp(",
            "# >>> STEP8: BRIDGING",
            BRIDGING_LOOP
        )
        
        # Enhanced logging after "Selected X rosters"
        solver_text = apply_insert_after_line(
            solver_text,
            'rmp_result = solve_rmp(',
            "# >>> STEP8: ENHANCED_LOGGING",
            ENHANCED_LOGGING
        )
        
        if not dry_run:
            solver_file.write_text(solver_text, encoding='utf-8')
        
        print("  [+] Added: _compute_tour_support, _simple_percentile")
        print("  [+] Added: Incumbent neighborhood call")
        print("  [+] Added: Bridging loop (6 rounds max)")
        print("  [+] Added: Enhanced logging")
    except Exception as e:
        print(f"  [X] Error: {e}")
        return False
    
    # Summary
    print("\\n" + "="*60)
    if dry_run:
        print("[OK] Dry run complete - no files modified")
    else:
        print("[OK] Step 8 Pool Repair applied successfully!")
    
    print("\\nNext steps:")
    print("  1. Run: python backend_py/run_kw51.py --time-budget 180")
    print("  2. Check logs for [INC NBHD], [POOL REPAIR R1-6]")
    print("  3. Target progression: 448 -> <320 -> <260 -> <236")
    print("="*60)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
