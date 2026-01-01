"""
Roster Column Generator - ALNS Heuristic for Column Generation

Generates valid RosterColumns (42-53h, all constraints satisfied) for 
the Set-Partitioning master problem.

Moves:
1. Build-from-seed: Start with one block, greedily add compatible blocks
2. Repair-uncovered: Generate columns targeting uncovered blocks
3. Swap builder: Exchange blocks between two rosters
"""

import logging
import random
from collections import defaultdict
from typing import Optional, List, Set, Dict

from src.services.roster_column import (
    RosterColumn, BlockInfo, create_roster_from_blocks, create_roster_from_blocks_pt,
    can_add_block_to_roster, MIN_WEEK_HOURS, MAX_WEEK_HOURS
)

logger = logging.getLogger("ColumnGenerator")

MIN_WEEK_MINUTES = int(MIN_WEEK_HOURS * 60)  # 2520
MAX_WEEK_MINUTES = int(MAX_WEEK_HOURS * 60)  # 3180


class RosterColumnGenerator:
    """
    Heuristic column generator for Set-Partitioning.
    
    Generates valid 42-53h rosters that satisfy all hard constraints.
    """
    
    def __init__(
        self,
        block_infos: list[BlockInfo],
        seed: int = 42,
        pool_cap: int = 20000,
        log_fn=None,
    ):
        """
        Initialize generator with block info.
        
        Args:
            block_infos: List of all available blocks
            seed: Random seed for determinism
            pool_cap: Maximum number of columns in pool
            log_fn: Logging function
        """
        self.block_infos = block_infos
        self.block_by_id = {b.block_id: b for b in block_infos}
        self.seed = seed
        self.rng = random.Random(seed)
        self.pool_cap = pool_cap
        self.log_fn = log_fn or (lambda msg: logger.info(msg))
        
        # Column pool: signature -> RosterColumn
        self.pool: dict[tuple, RosterColumn] = {}
        self.next_roster_id = 0
        
        # Index: block_id -> set of roster signatures containing it
        self.block_to_rosters: dict[str, set[tuple]] = defaultdict(set)
        
        # Conflict scoring: blocks with high overlap counts
        self._compute_conflict_scores()

    def detect_peak_relief_days(self) -> tuple[list[str], list[str]]:
        """
        Dynamically identify Peak days (high load) and Relief days (low load).
        Returns (peak_days, relief_days).
        """
        day_load = defaultdict(int)
        for b in self.block_infos:
            day_load[b.day] += b.work_min
            
        # Sort days by load
        sorted_days = sorted(day_load.items(), key=lambda x: -x[1])
        
        if not sorted_days:
            return ([], [])
            
        # Top 2 are Peak, Bottom 2 are Relief
        peak_days = [d for d, _ in sorted_days[:2]]
        relief_days = [d for d, _ in sorted_days[-2:]]
        
        return peak_days, relief_days

    def generate_peak_relief_columns(self, target_count: int = 2000) -> int:
        """
        Generate columns based on "Peak-ON / Relief-OFF" templates.
        
        Strategy:
        1. Identify Peak & Relief days.
        2. Template A: Peak-ON / Relief-OFF (Standard load balancing)
        3. Template B: Peak-ON / (Peak+1)-OFF (Adjacency-Aware for Absorption)
        
        Args:
            target_count: Max columns to generate via this method.
            
        Returns:
            Number of valid columns added.
        """
        peak_days, relief_days = self.detect_peak_relief_days()
        if not peak_days:
            return 0
            
        self.log_fn(f"Template Families: Peak={peak_days}, Relief={relief_days}")
        
        generated = 0
        attempts = 0
        max_attempts = target_count * 3
        
        # Helper for next day logic
        days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        def get_next_day(d):
            try:
                idx = days_order.index(d)
                return days_order[(idx + 1) % 7]
            except ValueError:
                return None
        
        # Determine specific OFF days needed for Adjacency (Peak + 1)
        # e.g. Friday Peak -> Saturday Off
        adjacency_off_days = set()
        for p in peak_days:
            nxt = get_next_day(p)
            if nxt: adjacency_off_days.add(nxt)
            
        # Prioritize seeds on Peak days
        peak_seeds = [b for b in self.block_infos if b.day in peak_days]
        # Sort by length (longest first) to fill hours quickly
        peak_seeds.sort(key=lambda b: -b.work_min)
        
        import random
        rng = random.Random(self.seed + 1) # distinct stream
        
        for seed in peak_seeds:
            if generated >= target_count or attempts >= max_attempts:
                break
                
            attempts += 1
            
            # Select Template Strategy
            # 60% Adjacency-Aware (Peak+1 OFF) - Critical for Absorption
            # 40% Standard Relief (Relief OFF) - Good for overall balancing
            
            excluded_days = set()
            strategy = "adjacency" if rng.random() < 0.6 else "relief"
            
            if strategy == "adjacency":
                # Find the day AFTER this seed's day
                nxt = get_next_day(seed.day)
                if nxt: excluded_days.add(nxt)
            else:
                # Relief OFF
                if relief_days:
                    if rng.random() < 0.5:
                        excluded_days.add(rng.choice(relief_days))
                    else:
                        excluded_days.update(relief_days)
            
            # Build column
            current_blocks = [seed]
            current_minutes = seed.work_min
            target_min_minutes = 42.0 * 60
            
            # Candidates: NOT on excluded days, NOT seed
            # Sort: Uncovered first, then Best Fit
            candidates = [
                b for b in self.block_infos 
                if b.day not in excluded_days and b.block_id != seed.block_id
            ]
            
            # Shuffle slightly to avoid determinism loops
            rng.shuffle(candidates)
            
            # Greedily add to reach FTE hours
            for cand in candidates:
                if current_minutes >= MAX_WEEK_MINUTES:
                    break
                
                can_add, _ = can_add_block_to_roster(current_blocks, cand, current_minutes)
                if can_add:
                    current_blocks.append(cand)
                    current_minutes += cand.work_min
            
            # Only keep if FTE grade
            if current_minutes >= target_min_minutes:
                 roster = create_roster_from_blocks(
                    roster_id=self._get_next_roster_id(),
                    block_infos=current_blocks,
                 )
                 if roster.is_valid and self.add_column(roster):
                     generated += 1
                     
        self.log_fn(f"Template Families generated: {generated} columns (prioritized Adjacency-Aware)")
        return generated
    
    def _compute_conflict_scores(self):
        """Compute conflict scores for blocks (higher = more overlaps)."""
        self.conflict_scores: dict[str, int] = {}
        
        # Group blocks by day
        day_blocks = defaultdict(list)
        for b in self.block_infos:
            day_blocks[b.day].append(b)
        
        # Count overlapping pairs
        for day, blocks in day_blocks.items():
            for i, b1 in enumerate(blocks):
                for b2 in blocks[i + 1:]:
                    # Check overlap
                    if not (b1.end_min <= b2.start_min or b1.start_min >= b2.end_min):
                        self.conflict_scores[b1.block_id] = self.conflict_scores.get(b1.block_id, 0) + 1
                        self.conflict_scores[b2.block_id] = self.conflict_scores.get(b2.block_id, 0) + 1
        
        self.log_fn(f"Conflict scores computed: {len(self.conflict_scores)} blocks with conflicts")
    
    def _get_next_roster_id(self) -> str:
        """Generate deterministic roster ID."""
        rid = f"R{self.next_roster_id:05d}"
        self.next_roster_id += 1
        return rid
    
    def add_column(self, column: RosterColumn) -> bool:
        """
        Add column to pool if valid and not duplicate.
        
        Returns True if added, False if invalid/duplicate/pool full.
        """
        if not column.is_valid:
            return False
        
        if column.signature in self.pool:
            return False  # Duplicate
        
        if len(self.pool) >= self.pool_cap:
            return False  # Pool full
        
        # QUALITY: Hard-cap singleton columns to prevent pool pollution
        # BUT: Allow singletons for blocks that have NO OTHER coverage (essential for feasibility)
        # Increased to 2000 to ensure EVERY block has a safety singleton for strict Elastic RMP
        SINGLETON_CAP = 2000
        if column.num_blocks == 1:
            # Check if this singleton covers a block that has no other coverage
            block_id = list(column.block_ids)[0]
            has_other_coverage = block_id in self.block_to_rosters and len(self.block_to_rosters[block_id]) > 0
            
            if has_other_coverage:
                # Block is already covered by other columns - apply cap
                singleton_count = sum(1 for c in self.pool.values() if c.num_blocks == 1)
                if singleton_count >= SINGLETON_CAP:
                    return False  # Singleton cap reached, and block has other coverage
            # Else: Block has NO coverage - always allow this singleton for feasibility
        
        self.pool[column.signature] = column
        
        # Update index
        for block_id in column.block_ids:
            self.block_to_rosters[block_id].add(column.signature)
        
        return True

    
    def get_uncovered_blocks(self) -> list[str]:
        """Get block IDs that are not in any column."""
        coverage = {block_id: len(sigs) for block_id, sigs in self.block_to_rosters.items()}
        return [bid for bid in self.block_by_id if bid not in coverage or coverage[bid] == 0]
    
    # =========================================================================
    # MOVE 1: BUILD-FROM-SEED
    # =========================================================================
    
    def build_from_seed(
        self,
        seed_block_id: str,
        prioritize_uncovered: bool = True,
    ) -> Optional[RosterColumn]:
        """
        Build a valid roster starting from a seed block.
        
        Greedily adds compatible blocks until 42-53h is reached.
        
        Args:
            seed_block_id: Block ID to start with
            prioritize_uncovered: If True, prefer blocks not yet covered
        
        Returns:
            Valid RosterColumn or None if couldn't reach 42h
        """
        if seed_block_id not in self.block_by_id:
            return None
        
        seed_block = self.block_by_id[seed_block_id]
        current_blocks = [seed_block]
        current_minutes = seed_block.work_min
        
        # Get candidates (all blocks except seed)
        candidates = [b for b in self.block_infos if b.block_id != seed_block_id]
        
        # Sort candidates: uncovered first, then by work_min descending
        def sort_key(b: BlockInfo) -> tuple:
            is_uncovered = len(self.block_to_rosters.get(b.block_id, set())) == 0
            conflict = self.conflict_scores.get(b.block_id, 0)
            return (
                0 if (prioritize_uncovered and is_uncovered) else 1,
                -conflict,  # High conflict first (harder to cover)
                -b.work_min,  # Longer blocks first
            )
        
        candidates = sorted(candidates, key=sort_key)
        
        # Determine target duration for this roster (dynamic packing)
        # Aim for 48h - 56h to maximize efficiency and reach ~150 drivers
        target_minutes = self.rng.randint(int(48 * 60), MAX_WEEK_MINUTES)

        # Greedily add blocks
        for cand in candidates:
            if current_minutes >= target_minutes:
                break
            
            if current_minutes + cand.work_min > MAX_WEEK_MINUTES:
                continue
            
            can_add, reason = can_add_block_to_roster(current_blocks, cand, current_minutes)
            if can_add:
                current_blocks.append(cand)
                current_minutes += cand.work_min
        
        # Note: Minimum hours are now a soft cost, not hard rejection
        # create_roster_from_blocks will validate other constraints
        
        # Create and validate roster
        roster = create_roster_from_blocks(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None

    def generate_collapse_candidates(
        self,
        rosters: list[RosterColumn],
        max_attempts: int = 200,
        tours_limit: int = 3
    ) -> list[RosterColumn]:
        """
        [Step 11] 3-to-2 Collapse Neighborhood.
        Attempt to take 3 short rosters and repartition their blocks into 2 valid rosters.
        Focuses on COMPRESSED week improvement.
        """
        # 1. Identify short rosters
        shorts = [r for r in rosters if len(r.covered_tour_ids) <= tours_limit]
        if len(shorts) < 3:
            return []
            
        candidates = []
        
        # Determine strictness of validity (same as build_from_seed)
        # We assume blocks are from valid rosters so they are individually valid.
        
        for _ in range(max_attempts):
            if len(shorts) < 3: break
            triplet = self.rng.sample(shorts, 3)
            
            # Collect unique blocks
            all_blocks = []
            seen = set()
            for r in triplet:
                for bid in r.block_ids:
                    if bid in self.block_by_id and bid not in seen:
                        b = self.block_by_id[bid]
                        all_blocks.append(b)
                        seen.add(bid)
            
            # Constraints
            total_min = sum(b.work_min for b in all_blocks)
            if total_min < 2 * MIN_WEEK_MINUTES: 
                # Impossible to form 2 valid FTE rosters
                continue
                
            # Heuristic partitioning:
            # Shuffle blocks and fill R1, then R2.
            # Try 5 shuffles.
            success = False
            
            for _ in range(5):
                shuffled = list(all_blocks)
                self.rng.shuffle(shuffled)
                
                r1_blocks = []
                r2_blocks = []
                cur_min_1 = 0.0
                
                # Build R1
                r1_blocks.append(shuffled[0])
                cur_min_1 += shuffled[0].work_min
                
                remaining = shuffled[1:]
                # Sort remaining by time to help sequential fill?
                remaining.sort(key=lambda b: b.start_time)
                
                rejected = []
                
                for cand in remaining:
                    if cur_min_1 > MAX_WEEK_MINUTES:
                        rejected.append(cand)
                        continue
                        
                    can, _ = can_add_block_to_roster(r1_blocks, cand, cur_min_1)
                    if can:
                        r1_blocks.append(cand)
                        cur_min_1 += cand.work_min
                    else:
                        rejected.append(cand)
                
                # Check R1 validity (soft check min hours)
                if cur_min_1 < MIN_WEEK_MINUTES:
                    # Too short, fail
                    continue
                    
                # R1 looks good. Build R2 from rejected.
                if not rejected:
                    # 3->1 collapse! Amazing.
                    c1 = create_roster_from_blocks(self._get_next_roster_id(), r1_blocks)
                    if c1.is_valid:
                        candidates.append(c1)
                        success = True
                        break
                else:
                    # Try to build R2
                    rejected.sort(key=lambda b: b.start_time)
                    r2_blocks = [rejected[0]]
                    cur_min_2 = rejected[0].work_min
                    valid_r2 = True
                    
                    for cand in rejected[1:]:
                        can, _ = can_add_block_to_roster(r2_blocks, cand, cur_min_2)
                        if can:
                            r2_blocks.append(cand)
                            cur_min_2 += cand.work_min
                        else:
                            valid_r2 = False
                            break
                    
                    if valid_r2 and MIN_WEEK_MINUTES <= cur_min_2 <= MAX_WEEK_MINUTES:
                         # Success!
                         c1 = create_roster_from_blocks(self._get_next_roster_id(), r1_blocks)
                         c2 = create_roster_from_blocks(self._get_next_roster_id(), r2_blocks)
                         if c1.is_valid and c2.is_valid:
                             candidates.append(c1)
                             candidates.append(c2)
                             success = True
                             break
            
            if success:
                # Move to next attempt
                pass

        return candidates
    
    # =========================================================================
    # MOVE 2: REPAIR-UNCOVERED
    # =========================================================================
    
    def repair_uncovered(self, max_attempts: int = 50) -> list[RosterColumn]:
        """
        Generate columns targeting currently uncovered blocks.
        
        Returns list of valid new columns.
        """
        uncovered = self.get_uncovered_blocks()
        if not uncovered:
            return []
        
        self.log_fn(f"Repair-uncovered: {len(uncovered)} blocks need coverage")
        
        new_columns = []
        attempts = 0
        
        # Sort uncovered by conflict score (highest first = hardest to cover)
        uncovered_sorted = sorted(
            uncovered,
            key=lambda bid: -self.conflict_scores.get(bid, 0)
        )
        
        for seed_id in uncovered_sorted:
            if attempts >= max_attempts:
                break
            
            attempts += 1
            column = self.build_from_seed(seed_id, prioritize_uncovered=True)
            
            if column and self.add_column(column):
                new_columns.append(column)
        
        return new_columns
    
    def get_coverage_frequency(self) -> dict[str, int]:
        """Return block_id -> count of columns containing it."""
        return {
            bid: len(sigs) 
            for bid, sigs in self.block_to_rosters.items()
        }
    
    def get_quality_coverage(self) -> dict:
        """
        Compute QUALITY coverage metrics.
        
        Returns dict with:
        - covered_by_fte: blocks covered by at least one FTE-grade column (>=40h)
        - covered_by_multi_block: blocks covered by at least one non-singleton column
        - covered_by_fte_ratio: ratio of blocks with FTE coverage
        - covered_by_multi_ratio: ratio of blocks with multi-block coverage
        - total_blocks: total block count
        
        Key insight: "covered by singleton" is NOT quality coverage.
        """
        all_blocks = set(self.block_by_id.keys())
        covered_by_fte = set()
        covered_by_multi = set()
        
        for col in self.pool.values():
            is_fte = col.total_hours >= 40.0
            is_multi = col.num_blocks >= 2
            
            for bid in col.block_ids:
                if is_fte:
                    covered_by_fte.add(bid)
                if is_multi:
                    covered_by_multi.add(bid)
        
        total = len(all_blocks)
        
        return {
            "covered_by_fte": len(covered_by_fte),
            "covered_by_multi_block": len(covered_by_multi),
            "covered_by_fte_ratio": len(covered_by_fte) / total if total > 0 else 0,
            "covered_by_multi_ratio": len(covered_by_multi) / total if total > 0 else 0,
            "total_blocks": total,
            "fte_uncovered": [bid for bid in all_blocks if bid not in covered_by_fte],
        }
    
    def get_pool_stats(self) -> dict:
        """
        Compute pool quality statistics for instrumentation.
        
        Returns dict with:
        - pool_total: total columns
        - pool_fte_band: columns with 42-53h (ideal FTE range)
        - pool_near_fte: columns with 38-42h (near FTE, consolidation candidates)
        - pool_pt_low: columns with <38h (PT quality)
        - pool_singletons: columns with only 1 block
        - hours_min/max/avg, blocks_per_roster_avg, uncovered_blocks, rare_covered_blocks
        """
        pool_total = len(self.pool)
        if pool_total == 0:
            return {
                "pool_total": 0,
                "pool_fte_band": 0,
                "pool_near_fte": 0,
                "pool_pt_low": 0,
                "pool_singletons": 0,
                "hours_min": 0,
                "hours_max": 0,
                "hours_avg": 0,
                "blocks_per_roster_avg": 0,
                "uncovered_blocks": len(self.block_by_id),
                "rare_covered_blocks": 0,
                "size": 0,
                "fte_columns": 0,
                "singletons": 0,
            }
        
        hours = [c.total_hours for c in self.pool.values()]
        blocks_per_roster = [c.num_blocks for c in self.pool.values()]
        
        pool_fte_band = 0
        pool_near_fte = 0
        pool_pt_low = 0
        pool_singletons = 0
        
        for col in self.pool.values():
            col_hours = col.total_hours
            
            if col.num_blocks == 1:
                pool_singletons += 1
            
            if 42.0 <= col_hours <= 53.0:
                pool_fte_band += 1
            elif 38.0 <= col_hours < 42.0:
                pool_near_fte += 1
            elif col_hours < 38.0:
                pool_pt_low += 1
        
        coverage = {block_id: len(sigs) for block_id, sigs in self.block_to_rosters.items()}
        uncovered = [bid for bid in self.block_by_id if bid not in coverage or coverage[bid] == 0]
        rare_covered = [bid for bid, cnt in coverage.items() if cnt <= 2]
        
        return {
            "pool_total": pool_total,
            "pool_fte_band": pool_fte_band,
            "pool_near_fte": pool_near_fte,
            "pool_pt_low": pool_pt_low,
            "pool_singletons": pool_singletons,
            "hours_min": min(hours),
            "hours_max": max(hours),
            "hours_avg": sum(hours) / len(hours),
            "blocks_per_roster_avg": sum(blocks_per_roster) / len(blocks_per_roster),
            "uncovered_blocks": len(uncovered),
            "rare_covered_blocks": len(rare_covered),
            "size": pool_total,
            "fte_columns": pool_fte_band,
            "singletons": pool_singletons,
        }
    
    def get_rare_blocks(self, min_coverage: int = 5) -> list[str]:
        """Get blocks with coverage < min_coverage, sorted by rarity (lowest first)."""
        freq = self.get_coverage_frequency()
        rare = [
            (bid, freq.get(bid, 0)) 
            for bid in self.block_by_id 
            if freq.get(bid, 0) < min_coverage
        ]
        rare.sort(key=lambda x: x[1])
        return [bid for bid, _ in rare]

    def merge_low_hour_into_hosts(
        self,
        low_hour_rosters: list[RosterColumn],
        max_attempts: int = 500,
        target_min_hours: float = 30.0,
        target_max_hours: float = 45.0,
    ) -> list[RosterColumn]:
        """
        Merge low-hour rosters into compatible host rosters to create higher-hour columns.
        
        This solves the "227 drivers @ 25h avg" problem by creating columns that replace
        singletons (4.5h, 9h) with merged columns (30-45h).
        
        Strategy:
        1. For each low_hour roster r_low (e.g., 4.5h, 9h):
           - Extract its blocks
           - Find compatible other blocks from pool that can be added
           - Build merged column with target_min_hours <= hours <= target_max_hours
        2. Return merged columns (pool size limited to max_attempts)
        
        Args:
            low_hour_rosters: Rosters with hours < 30 (candidates for merging)
            max_attempts: Maximum merged columns to generate
            target_min_hours: Minimum hours for merged column (default 30h)
            target_max_hours: Maximum hours for merged column (default 45h)
        
        Returns:
            List of new merged RosterColumns
        """
        if not low_hour_rosters:
            return []
        
        merged_columns = []
        attempts = 0
        
        # Sort low-hour rosters by hours (lowest first - most impactful to merge)
        sorted_low = sorted(low_hour_rosters, key=lambda r: r.total_hours)[:50]  # Limit candidates
        
        # Group available blocks by day for efficient lookup
        blocks_by_day = defaultdict(list)
        for b in self.block_infos:
            blocks_by_day[b.day].append(b)
        
        for r_low in sorted_low:
            if attempts >= max_attempts:
                break
            
            # Get blocks from low-hour roster
            low_blocks = [self.block_by_id[bid] for bid in r_low.block_ids if bid in self.block_by_id]
            if not low_blocks:
                continue
            
            # Collect days already used by low-hour roster
            low_days = set(b.day for b in low_blocks)
            
            # Try to build a merged column by adding more blocks
            current_blocks = list(low_blocks)
            current_minutes = sum(b.work_min for b in current_blocks)
            target_min_minutes = int(target_min_hours * 60)
            target_max_minutes = int(target_max_hours * 60)
            
            # Try adding blocks from other days first (less likely to conflict)
            other_days = [d for d in blocks_by_day.keys() if d not in low_days]
            same_days = list(low_days)
            
            # Prioritize other days, then same days
            day_order = other_days + same_days
            
            for day in day_order:
                if current_minutes >= target_max_minutes:
                    break
                
                # Get candidates for this day, sorted by work_min descending
                day_candidates = sorted(
                    blocks_by_day[day],
                    key=lambda b: -b.work_min
                )
                
                for cand in day_candidates:
                    if cand.block_id in r_low.block_ids:
                        continue  # Skip blocks already in roster
                    
                    if current_minutes + cand.work_min > target_max_minutes:
                        continue
                    
                    can_add, _ = can_add_block_to_roster(current_blocks, cand, current_minutes)
                    if can_add:
                        current_blocks.append(cand)
                        current_minutes += cand.work_min
                        
                        # Check if we've reached target
                        if current_minutes >= target_min_minutes:
                            break
            
            # Create merged roster if it meets threshold
            if current_minutes >= target_min_minutes:
                merged_roster = create_roster_from_blocks(
                    roster_id=self._get_next_roster_id(),
                    block_infos=current_blocks,
                )
                
                if merged_roster.is_valid and self.add_column(merged_roster):
                    merged_columns.append(merged_roster)
                    attempts += 1
        
        if merged_columns:
            self.log_fn(f"[MERGE-LOW] Generated {len(merged_columns)} merged columns (target: {target_min_hours}-{target_max_hours}h)")
        
        return merged_columns


    
    def targeted_repair(
        self,
        target_blocks: list[str],
        avoid_set: set[str] = None,
        max_attempts: int = 100,
    ) -> list[RosterColumn]:
        """
        Generate columns specifically for target_blocks,
        avoiding blocks in avoid_set to reduce collisions.
        
        Args:
            target_blocks: Block IDs to use as seeds (priority order)
            avoid_set: Block IDs to avoid when building rosters
            max_attempts: Max generation attempts
            
        Returns:
            List of newly generated valid columns
        """
        if not target_blocks:
            return []
        
        avoid_set = avoid_set or set()
        
        self.log_fn(f"Targeted repair: {len(target_blocks)} seeds, {len(avoid_set)} avoided")
        
        new_columns = []
        attempts = 0
        
        for seed_id in target_blocks:
            if attempts >= max_attempts:
                break
            if seed_id not in self.block_by_id:
                continue
            
            attempts += 1
            column = self.build_from_seed_diversified(
                seed_block_id=seed_id,
                avoid_set=avoid_set,
                prefer_rare=True,
            )
            
            if column and self.add_column(column):
                new_columns.append(column)
        
        self.log_fn(f"Targeted repair generated: {len(new_columns)} columns")
        return new_columns
    
    def build_from_seed_diversified(
        self,
        seed_block_id: str,
        avoid_set: set[str] = None,
        prefer_rare: bool = True,
    ) -> Optional[RosterColumn]:
        """
        Build roster avoiding high-frequency blocks in avoid_set.
        Prefer blocks with low coverage frequency for diversity.
        
        Args:
            seed_block_id: Starting block
            avoid_set: Block IDs to avoid (high-frequency/collision blocks)
            prefer_rare: If True, prioritize blocks with low coverage
            
        Returns:
            Valid RosterColumn or None
        """
        if seed_block_id not in self.block_by_id:
            return None
        
        avoid_set = avoid_set or set()
        
        seed_block = self.block_by_id[seed_block_id]
        current_blocks = [seed_block]
        current_minutes = seed_block.work_min
        
        # Get coverage frequency for rarity scoring
        coverage_freq = self.get_coverage_frequency()
        
        # Get candidates (all blocks except seed and avoid_set)
        candidates = [
            b for b in self.block_infos 
            if b.block_id != seed_block_id and b.block_id not in avoid_set
        ]
        
        # Sort: rare blocks first (low coverage), then by work_min
        def sort_key(b: BlockInfo) -> tuple:
            freq = coverage_freq.get(b.block_id, 0)
            is_uncovered = freq == 0
            conflict = self.conflict_scores.get(b.block_id, 0)
            return (
                0 if is_uncovered else 1,      # Uncovered first
                freq if prefer_rare else 0,    # Then rare blocks (low freq first)
                -conflict,                      # High conflict next (harder to cover)
                -b.work_min,                    # Longer blocks first
            )
        
        candidates = sorted(candidates, key=sort_key)
        
        # Greedily add blocks
        for cand in candidates:
            if current_minutes >= MIN_WEEK_MINUTES:
                break
            
            if current_minutes + cand.work_min > MAX_WEEK_MINUTES:
                continue
            
            can_add, reason = can_add_block_to_roster(current_blocks, cand, current_minutes)
            if can_add:
                current_blocks.append(cand)
                current_minutes += cand.work_min
        
        # Note: Minimum hours are now a soft cost, not hard rejection
        # create_roster_from_blocks will validate other constraints
        
        # Create and validate roster
        roster = create_roster_from_blocks(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None

    
    def generate_merge_repair_columns_capaware(
        self,
        anchor_tours: list[str],
        max_cols: int = 400,
    ) -> int:
        """
        Step 14: Cap-Aware Merge Repair.
        Build new dense rosters that include anchor tours by merging short incumbents.
        Deterministic. Uses can_add_block_to_roster incremental validator.
        Returns number of UNIQUE columns added to pool.
        """
        if not anchor_tours:
            return 0
            
        generated_count = 0
        anchor_set = set(anchor_tours)
        
        # 1. Identify short incumbents (<= 3 tours)
        # Prefer rosters with INC_GREEDY_ prefix or similar
        incumbent_shorts = []
        other_shorts = []
        
        for col in self.pool.values():
            if len(col.covered_tour_ids) <= 3:
                if col.roster_id.startswith(("INC_GREEDY_", "SNAP_", "BEST_")):
                    incumbent_shorts.append(col)
                else:
                    other_shorts.append(col)
        
        # Sort for determinism
        incumbent_shorts.sort(key=lambda c: c.roster_id)
        other_shorts.sort(key=lambda c: c.roster_id)
        
        candidates = incumbent_shorts + other_shorts
        if not candidates:
            return 0
            
        # 2. Filter base rosters that contain at least one anchor tour
        base_rosters = [c for c in candidates if any(t in anchor_set for t in c.covered_tour_ids)]
        
        self.log_fn(f"[CAP-MERGE] Found {len(base_rosters)} base rosters hitting anchors")
        
        # 3. Attempt merges
        # Strategy: Take a base roster, try to add blocks from 1-2 other candidates
        
        # Pre-compute block objects for speed
        roster_blocks = {}
        for c in candidates:
            blocks = []
            for bid in c.block_ids:
                if bid in self.block_by_id:
                    blocks.append(self.block_by_id[bid])
            roster_blocks[c.signature] = blocks
            
        attempts = 0
        max_attempts = max_cols * 5
        
        for base in base_rosters:
            if generated_count >= max_cols or attempts >= max_attempts:
                break
                
            base_b_objs = roster_blocks.get(base.signature)
            if not base_b_objs: continue
            
            # Try to merge with other candidates
            # Sort candidates by length (shortest first) to pack tightly
            current_blocks = list(base_b_objs)
            current_min = base.total_hours * 60
            
            merged_something = False
            
            # Inner loop: iterate through candidates to find merge partners
            # Limit scan to avoid N^2 explosion
            for partner in candidates:
                if partner.signature == base.signature:
                    continue
                    
                # Skip if hours Would exceed max immediately
                if current_min + (partner.total_hours * 60) > MAX_WEEK_MINUTES:
                    continue
                
                partner_b_objs = roster_blocks.get(partner.signature)
                if not partner_b_objs: continue
                
                # Check compatibility of all blocks in partner
                valid_merge = True
                temp_blocks = list(current_blocks)
                temp_min = current_min
                
                for b in partner_b_objs:
                    can_add, _ = can_add_block_to_roster(temp_blocks, b, temp_min)
                    if can_add:
                        temp_blocks.append(b)
                        temp_min += b.work_min
                    else:
                        valid_merge = False
                        break
                
                if valid_merge:
                    current_blocks = temp_blocks
                    current_min = temp_min
                    merged_something = True
                    # If we reached FTE range, stop merging and try to add
                    if current_min >= MIN_WEEK_MINUTES:
                        break
            
            attempts += 1
            
            if merged_something and current_min >= MIN_WEEK_MINUTES:
                # Create new roster
                new_roster = create_roster_from_blocks(
                    self._get_next_roster_id(),
                    current_blocks
                )
                if new_roster.is_valid and self.add_column(new_roster):
                    generated_count += 1
                    
        return generated_count

    
    def swap_builder(self, max_attempts: int = 100) -> list[RosterColumn]:
        """
        Try to create new valid columns by exchanging blocks between pairs.
        
        Pick two existing columns, try swapping blocks between them,
        check if both results are still valid.
        
        Returns list of new valid columns.
        """
        if len(self.pool) < 2:
            return []
        
        columns = list(self.pool.values())
        new_columns = []
        
        for _ in range(max_attempts):
            # Pick two random columns
            c1, c2 = self.rng.sample(columns, 2)
            
            # Pick random blocks to swap
            b1_ids = list(c1.block_ids)
            b2_ids = list(c2.block_ids)
            
            if not b1_ids or not b2_ids:
                continue
            
            swap_b1_id = self.rng.choice(b1_ids)
            swap_b2_id = self.rng.choice(b2_ids)
            
            if swap_b1_id == swap_b2_id:
                continue
            
            # Create new block lists
            new_b1_ids = [bid for bid in b1_ids if bid != swap_b1_id] + [swap_b2_id]
            new_b2_ids = [bid for bid in b2_ids if bid != swap_b2_id] + [swap_b1_id]
            
            # Build rosters
            new_blocks_1 = [self.block_by_id[bid] for bid in new_b1_ids if bid in self.block_by_id]
            new_blocks_2 = [self.block_by_id[bid] for bid in new_b2_ids if bid in self.block_by_id]
            
            roster1 = create_roster_from_blocks(self._get_next_roster_id(), new_blocks_1)
            roster2 = create_roster_from_blocks(self._get_next_roster_id(), new_blocks_2)
            
            if roster1.is_valid and self.add_column(roster1):
                new_columns.append(roster1)
            
            if roster2.is_valid and self.add_column(roster2):
                new_columns.append(roster2)
        
        return new_columns
    
    # =========================================================================
    # MOVE 4: TARGETED HOUR-RANGE GENERATION (NEW)
    # =========================================================================
    
    def build_from_seed_targeted(
        self,
        seed_block_id: str,
        target_hour_range: tuple[float, float] = (45, 50),
        prioritize_uncovered: bool = True,
    ) -> Optional[RosterColumn]:
        """
        Build a roster targeting a specific hour range.
        
        Used for multi-stage column generation:
        - Stage 1: (45, 50) - high quality FTEs (packed rosters)
        - Stage 2: (40, 45) - medium FTEs
        - Stage 3: (35, 40) - allow lower hours
        
        Args:
            seed_block_id: Block ID to start with
            target_hour_range: (min_hours, max_hours) target
            prioritize_uncovered: If True, prefer blocks not yet covered
            
        Returns:
            Valid RosterColumn within target range or None
        """
        if seed_block_id not in self.block_by_id:
            return None
        
        min_target_min = int(target_hour_range[0] * 60)
        max_target_min = int(target_hour_range[1] * 60)
        
        seed_block = self.block_by_id[seed_block_id]
        current_blocks = [seed_block]
        current_minutes = seed_block.work_min
        
        # Get candidates (all blocks except seed)
        candidates = [b for b in self.block_infos if b.block_id != seed_block_id]
        
        # Get coverage frequency for uncovered detection
        coverage_freq = self.get_coverage_frequency()
        
        # Sort candidates: uncovered first, then by work_min to reach target fast
        def sort_key(b: BlockInfo) -> tuple:
            is_uncovered = coverage_freq.get(b.block_id, 0) == 0
            conflict = self.conflict_scores.get(b.block_id, 0)
            return (
                0 if (prioritize_uncovered and is_uncovered) else 1,
                -conflict,  # High conflict first (harder to cover)
                -b.work_min,  # Longer blocks first (pack quickly)
            )
        
        candidates = sorted(candidates, key=sort_key)
        
        # Greedily add blocks until target range reached
        for cand in candidates:
            # Stop if we've reached max target
            if current_minutes >= max_target_min:
                break
            
            # Skip if would exceed max hours
            if current_minutes + cand.work_min > MAX_WEEK_MINUTES:
                continue
            
            can_add, reason = can_add_block_to_roster(current_blocks, cand, current_minutes)
            if can_add:
                current_blocks.append(cand)
                current_minutes += cand.work_min
        
        # Check if we reached minimum target
        if current_minutes < min_target_min:
            return None  # Failed to reach target range
        
        # Create and validate roster
        roster = create_roster_from_blocks(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None
    
    def get_pool_stats(self) -> dict:
        """Return statistics about the current pool."""
        total = len(self.pool)
        singletons = sum(1 for c in self.pool.values() if c.num_blocks == 1)
        fte_count = sum(1 for c in self.pool.values() if c.total_hours >= 40.0)
        
        return {
            "pool_total": total,
            "singletons": singletons,
            "fte_columns": fte_count,
            "singleton_ratio": singletons / total if total else 0
        }

    def get_quality_coverage(self, ignore_singletons: bool = False, min_hours: float = 0.0) -> float:
        """
        Calculate the percentage of blocks covered by at least one valid column.
        
        Args:
            ignore_singletons: If True, only count blocks covered by columns with >1 blocks.
            min_hours: If >0, only count blocks covered by columns with >= min_hours.
        """
        covered_blocks = set()
        for col in self.pool.values():
            if ignore_singletons and col.num_blocks == 1:
                continue
            if min_hours > 0 and col.total_hours < min_hours:
                continue
            
            covered_blocks.update(col.block_ids)
            
        return len(covered_blocks) / len(self.block_infos) if self.block_infos else 0.0

    # =========================================================================
    # STEP 15B: FORECAST-AWARE GENERATION
    # =========================================================================
    
    def generate_sparse_window_seeds(self, max_concurrent: int = 2) -> int:
        """
        Step 15B: Targets 'thin tail' blocks in sparsely occupied time windows.
        Identifies time buckets with <= max_concurrent blocks active.
        """
        stats = {
            "identified_sparse": 0,
            "added_columns": 0,
            "failed_columns": 0
        }
        
        try:
            # Build Occupancy Map: (Day, Bucket) -> Count
            occupancy = defaultdict(int) 
            for b in self.block_infos:
                d = b.day
                start_bucket = b.start_min // 15
                end_bucket = b.end_min // 15
                for i in range(start_bucket, end_bucket):
                    occupancy[(d, i)] += 1
                    
            # Find Sparse Blocks
            sparse_blocks = set()
            for b in self.block_infos:
                d = b.day
                start_bucket = b.start_min // 15
                end_bucket = b.end_min // 15
                buckets = range(start_bucket, end_bucket)
                if any(occupancy[(d, i)] <= max_concurrent for i in buckets):
                    sparse_blocks.add(b.block_id)
                    
            stats["identified_sparse"] = len(sparse_blocks)
            self.log_fn(f"[SPARSE-GEN] Identified {len(sparse_blocks)} blocks in thin windows")
            
            # Build columns from these seeds
            added = 0
            sorted_ids = sorted(list(sparse_blocks))
            
            for bid in sorted_ids:
                 col = self.build_from_seed_diversified(
                     seed_block_id=bid,
                     prefer_rare=True,
                     avoid_set=set() 
                 )
                 if col and self.add_column(col):
                     added += 1
                 else:
                     stats["failed_columns"] += 1
                     
            stats["added_columns"] = added
            self.log_fn(f"[SPARSE-GEN] Added {added} columns")
            return added
            
        finally:
            # Dump Stats to Artifact
            try:
                import json
                import os
                artifact_path = r"C:\Users\n.zaher\.gemini\antigravity\brain\ca05176a-833c-4592-af77-ceeeba361ffa\step15b_sparse_stats.json"
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w") as f:
                    json.dump(stats, f, indent=2)
            except Exception as e:
                self.log_fn(f"[SPARSE-GEN] Failed to write stats: {e}")

    def generate_friday_absorbers(self) -> int:
        """
        Step 15B: Targets Friday unpaired/short blocks.
        Attempts to combine Fri (4.5h) with Mon-Thu (9h+) to reach FTE.
        """
        stats = {
            "found_friday_shorts": 0,
            "candidates_per_day": {},
            "added_columns": 0
        }
        
        try:
            # Find Friday blocks < 5h
            fri_shorts = [b for b in self.block_infos if b.day == 4 and b.work_min < 300]
            stats["found_friday_shorts"] = len(fri_shorts)
            
            if not fri_shorts:
                return 0
                
            self.log_fn(f"[FRI-ABSORB] Found {len(fri_shorts)} short Friday blocks")
            added = 0
            
            # Sort by ID
            fri_shorts.sort(key=lambda b: b.block_id)
            
            for fri_b in fri_shorts:
                 current_blocks = [fri_b]
                 current_min = fri_b.work_min
                 
                 # Greedily finding longest possible blocks on Mon-Thu
                 for day in [0, 1, 2, 3]: # Mon, Tue, Wed, Thu
                     cands = [b for b in self.block_infos if b.day == day and b.work_min >= 480] # >= 8h
                     
                     if str(day) not in stats["candidates_per_day"]:
                         stats["candidates_per_day"][str(day)] = 0
                     stats["candidates_per_day"][str(day)] += len(cands)
                     
                     if not cands: continue
                     
                     # Sort desc length
                     cands.sort(key=lambda b: -b.work_min)
                     
                     best_b = None
                     for cand in cands:
                         can_add, _ = can_add_block_to_roster(current_blocks, cand, current_min)
                         if can_add:
                             best_b = cand
                             break
                     
                     if best_b:
                         current_blocks.append(best_b)
                         current_min += best_b.work_min
                     
                 if current_min >= 2400: # 40h
                     roster = create_roster_from_blocks(self._get_next_roster_id(), current_blocks)
                     if roster.is_valid and self.add_column(roster):
                         added += 1
                         
            stats["added_columns"] = added
            self.log_fn(f"[FRI-ABSORB] Added {added} columns")
            return added
            
        finally:
            try:
                import json
                import os
                artifact_path = r"C:\Users\n.zaher\.gemini\antigravity\brain\ca05176a-833c-4592-af77-ceeeba361ffa\step15b_friday_stats.json"
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w") as f:
                    json.dump(stats, f, indent=2)
            except Exception as e:
                self.log_fn(f"[FRI-ABSORB] Failed to write stats: {e}")

    def generate_multistage_pool(
        self,
        stages: list[tuple[str, tuple[float, float], int]] = None,
    ) -> dict:
        """
        Generate columns in multiple stages targeting different hour ranges.
        
        This produces better-packed rosters by first trying high-hour targets.
        
        Args:
            stages: List of (stage_name, (min_h, max_h), target_count)
                Default: [
                    ("high_quality", (47, 53), 3000),
                    ("medium", (42, 47), 2000),
                    ("fill_gaps", (35, 42), 1000),
                ]
        
        Returns:
            Dict with per-stage statistics
        """
        if stages is None:
            stages = [
                ("high_quality", (47, 53), 3000),
                ("medium", (42, 47), 2000),
                ("fill_gaps", (35, 42), 1000),
            ]
        
        self.log_fn("=" * 60)
        self.log_fn("MULTI-STAGE COLUMN GENERATION")
        self.log_fn("=" * 60)
        
        stats = {"stages": []}

        # NEW: Generate Peak/Relief Templates FIRST
        # This seeds the pool with "structurally correct" columns
        n_templates = self.generate_peak_relief_columns(target_count=2000)
        stats["template_columns"] = n_templates
        
        for stage_name, hour_range, target_count in stages:
            stage_start = len(self.pool)
            generated = 0
            
            self.log_fn(f"\nStage: {stage_name} ({hour_range[0]}-{hour_range[1]}h), target={target_count}")
            
            # Sort blocks by conflict score (hardest first)
            sorted_blocks = sorted(
                self.block_infos,
                key=lambda b: -self.conflict_scores.get(b.block_id, 0)
            )
            
            # Generate columns for this stage
            for block in sorted_blocks:
                if generated >= target_count:
                    break
                
                column = self.build_from_seed_targeted(
                    seed_block_id=block.block_id,
                    target_hour_range=hour_range,
                    prioritize_uncovered=True,
                )
                
                if column and self.add_column(column):
                    generated += 1
            
            stage_new = len(self.pool) - stage_start
            uncovered = len(self.get_uncovered_blocks())
            
            # Compute QUALITY coverage (not just "any coverage")
            fte_ratio = self.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
            multi_ratio = self.get_quality_coverage(ignore_singletons=True)
            
            self.log_fn(f"  Generated: {stage_new} columns, uncovered: {uncovered}")
            self.log_fn(f"  Quality: FTE coverage={fte_ratio:.1%}, multi-block={multi_ratio:.1%}")
            
            stats["stages"].append({
                "name": stage_name,
                "hour_range": hour_range,
                "target": target_count,
                "generated": stage_new,
                "pool_size": len(self.pool),
                "uncovered": uncovered,
                "fte_coverage_ratio": fte_ratio,
                "multi_block_ratio": multi_ratio,
            })
            
            # FIXED: Early exit only when QUALITY coverage is high
            # "Covered by singleton" is NOT quality coverage!
            if fte_ratio >= 0.95 and multi_ratio >= 0.90:
                self.log_fn(f"  [OK] High quality coverage! FTE={fte_ratio:.1%}, multi={multi_ratio:.1%}")
                self.log_fn(f"  Stopping early with quality guarantee.")
                break
            elif uncovered == 0 and fte_ratio < 0.95:
                self.log_fn(f"  [WARN] All blocks covered but FTE ratio only {fte_ratio:.1%}")
                self.log_fn(f"  Continuing to generate more FTE-quality columns...")
        
        # Log final pool stats
        # Log final pool stats
        pool_stats = self.get_pool_stats()
        fte_coverage = self.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
        
        stats["total_pool_size"] = len(self.pool)
        stats["final_uncovered"] = len(self.get_uncovered_blocks())
        stats["final_fte_ratio"] = fte_coverage
        stats["pool_stats"] = pool_stats
        
        self.log_fn(f"\nMulti-stage complete: {stats['total_pool_size']} columns, {stats['final_uncovered']} uncovered")
        self.log_fn(f"Pool quality: FTE columns={pool_stats['fte_columns']}, singletons={pool_stats['singletons']}")
        
        return stats

    
    # =========================================================================
    # INITIAL POOL GENERATION
    # =========================================================================
    
    def generate_initial_pool(self, target_size: int = 5000) -> int:
        """
        Generate initial column pool.
        
        Returns number of valid columns generated.
        """
        self.log_fn("=" * 60)
        self.log_fn("GENERATING INITIAL COLUMN POOL")
        self.log_fn("=" * 60)
        
        # Sort all blocks by conflict score (hardest first)
        sorted_blocks = sorted(
            self.block_infos,
            key=lambda b: -self.conflict_scores.get(b.block_id, 0)
        )
        
        generated = 0
        
        # Build from each block as seed
        for block in sorted_blocks:
            if len(self.pool) >= target_size:
                break
            
            column = self.build_from_seed(block.block_id, prioritize_uncovered=True)
            if column and self.add_column(column):
                generated += 1
        
        self.log_fn(f"Initial pool: {len(self.pool)} columns, {generated} generated")
        
        # Check coverage
        stats = self.get_pool_stats()
        self.log_fn(f"Hours range: {stats.get('hours_min', 0):.1f}h - {stats.get('hours_max', 0):.1f}h")
        self.log_fn(f"Uncovered blocks: {stats.get('uncovered_blocks', 0)}")
        
        return generated
    
    def targeted_repair(
        self,
        target_blocks: List[str],
        avoid_set: Set[str],
        max_attempts: int = 100
    ) -> List[RosterColumn]:
        """
        Generate columns strictly targeting specific blocks (e.g. PT blocks).
        Uses 'build_from_seed_targeted' to force FTE creation around these blocks.
        """
        new_columns = []
        attempts = 0
        
        # Ranges to try for repair: FTE first, then pure PT if needed
        strategies = [
            ((47, 53), True),   # Try high-hour FTE first
            ((42, 47), True),   # Then medium FTE
            ((35, 42), False),  # Then low-hour FTE
        ]
        
        for block_id in target_blocks:
            if attempts >= max_attempts:
                break
                
            if block_id not in self.block_by_id:
                continue
                
            # Try to build FTE column around this block
            for (min_h, max_h), prioritize_uncovered in strategies:
                col = self.build_from_seed_targeted(
                    seed_block_id=block_id,
                    target_hour_range=(min_h, max_h),
                    prioritize_uncovered=prioritize_uncovered
                )
                
                if col:
                    if self.add_column(col):
                        new_columns.append(col)
                        attempts += 1
                        break # Success for this block, move to next
        
        return new_columns

    def generate_columns(
        self,
        rounds: int = 10,
        columns_per_round: int = 100,
    ) -> int:
        """
        Run multiple rounds of column generation.
        
        Returns total number of new columns added.
        """
        total_new = 0
        
        for r in range(rounds):
            new_this_round = 0
            
            # Repair uncovered
            new_columns = self.repair_uncovered(max_attempts=columns_per_round // 2)
            new_this_round += len(new_columns)
            
            # Swap builder
            new_columns = self.swap_builder(max_attempts=columns_per_round // 2)
            new_this_round += len(new_columns)
            
            total_new += new_this_round
            
            if new_this_round == 0:
                self.log_fn(f"Round {r + 1}: No new columns, stopping early")
                break
            
            self.log_fn(f"Round {r + 1}: +{new_this_round} columns (pool: {len(self.pool)})")
        
        return total_new

    # =========================================================================
    # PT COLUMN GENERATION
    # =========================================================================
    
    def build_pt_column(
        self,
        seed_block_id: str,
        max_blocks: int = 3,
    ) -> Optional[RosterColumn]:
        """
        Build a PT (Part-Time) column with <40h.
        
        Targets Saturday and late-evening blocks that are hard to fit in FTE rosters.
        
        Args:
            seed_block_id: Starting block
            max_blocks: Maximum blocks in the PT roster
            
        Returns:
            Valid PT RosterColumn or None
        """
        if seed_block_id not in self.block_by_id:
            return None
        
        seed_block = self.block_by_id[seed_block_id]
        current_blocks = [seed_block]
        current_minutes = seed_block.work_min
        
        # Get candidates prioritizing uncovered blocks
        candidates = [b for b in self.block_infos if b.block_id != seed_block_id]
        
        # Sort: uncovered first, same day first (PT often works 1-2 days)
        coverage_freq = self.get_coverage_frequency()
        
        def sort_key(b: BlockInfo) -> tuple:
            freq = coverage_freq.get(b.block_id, 0)
            same_day = 0 if b.day == seed_block.day else 1
            return (freq, same_day, -b.work_min)
        
        candidates = sorted(candidates, key=sort_key)
        
        # Add blocks up to max_blocks (keep PT rosters small)
        for cand in candidates:
            if len(current_blocks) >= max_blocks:
                break
            
            # PT rosters stay under 40h (2400 min)
            if current_minutes + cand.work_min > MIN_WEEK_MINUTES:
                continue
            
            can_add, _ = can_add_block_to_roster(current_blocks, cand, current_minutes)
            if can_add:
                current_blocks.append(cand)
                current_minutes += cand.work_min
        
        # PT roster must have at least some work
        if current_minutes < 60:  # At least 1 hour
            return None
        
        # Create PT roster
        roster = create_roster_from_blocks_pt(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None
    
    def generate_pt_pool(self, target_size: int = 500) -> int:
        """
        Generate PT columns targeting hard-to-cover blocks.
        
        Focuses on:
        - Saturday blocks
        - Late evening blocks (end > 20:00)
        - Uncovered blocks
        
        Returns number of PT columns generated.
        """
        self.log_fn("Generating PT column pool...")
        
        generated = 0
        
        # Find hard-to-cover blocks: Saturday, late, uncovered
        saturday_blocks = [b for b in self.block_infos if b.day == 5]  # Saturday = 5
        late_blocks = [b for b in self.block_infos if b.end_min > 20 * 60]  # After 20:00
        uncovered = self.get_uncovered_blocks()
        
        # Priority order: uncovered Saturday > uncovered late > all Saturday
        priority_seeds = []
        for bid in uncovered:
            if bid in [b.block_id for b in saturday_blocks]:
                priority_seeds.append(bid)
        for bid in uncovered:
            if bid in [b.block_id for b in late_blocks] and bid not in priority_seeds:
                priority_seeds.append(bid)
        for b in saturday_blocks:
            if b.block_id not in priority_seeds:
                priority_seeds.append(b.block_id)
        
        # Generate PT columns
        for seed_id in priority_seeds:
            if generated >= target_size:
                break
            
            column = self.build_pt_column(seed_id, max_blocks=3)
            if column and self.add_column(column):
                generated += 1
        
        self.log_fn(f"Generated {generated} PT columns")
        return generated
    
    def seed_from_greedy(self, greedy_assignments: list) -> int:
        """
        Add columns to pool from a known-feasible greedy solution.
        
        This guarantees the RMP can reproduce the greedy solution exactly,
        then optimize from there.
        
        Args:
            greedy_assignments: List of DriverAssignment from greedy solver
            
        Returns:
            Number of columns added
        """
        self.log_fn(f"Seeding pool from {len(greedy_assignments)} greedy assignments...")
        
        added = 0
        
        for assignment in greedy_assignments:
            # Get block IDs from the assignment
            block_ids = []
            for block in assignment.blocks:
                if hasattr(block, 'id'):
                    block_ids.append(block.id)
                elif hasattr(block, 'block_id'):
                    block_ids.append(block.block_id)
            
            if not block_ids:
                continue
            
            # Get BlockInfo objects
            block_infos = [self.block_by_id[bid] for bid in block_ids if bid in self.block_by_id]
            
            if not block_infos:
                continue
            
            # CRITICAL: Mark with INC_GREEDY_ prefix
            incumbent_count = len([c for c in self.pool.values() if c.roster_id.startswith('INC_GREEDY_')])
            incumbent_id = f"INC_GREEDY_{incumbent_count:04d}"
            
            # Create column based on driver type
            total_hours = sum(b.work_min for b in block_infos) / 60.0
            
            if assignment.driver_type == "PT" or total_hours < MIN_WEEK_HOURS:
                column = create_roster_from_blocks_pt(
                    roster_id=incumbent_id,
                    block_infos=block_infos,
                )
            else:
                column = create_roster_from_blocks(
                    roster_id=incumbent_id,
                    block_infos=block_infos,
                )
            
            if column and self.add_column(column):
                added += 1
        
        self.log_fn(f"Seeded {added} columns from greedy solution")
        return added


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
    def generate_merge_repair_columns(self, selected_rosters: list[RosterColumn], budget: int = 500) -> list[RosterColumn]:
        """
        Merge Repair (Type C): Combines two 'short' rosters into one longer roster to reduce headcount.
        Targets rosters with <= 3 tours (especially 1-2 tours).
        Determinstic pairwise merge attempt.
        """
        # 1. Filter Short Rosters
        def get_tours(r):
            return sum(t for _, t, _, _ in r.day_stats)
            
        short_rosters = [r for r in selected_rosters if get_tours(r) <= 3]
        short_rosters.sort(key=lambda r: (get_tours(r), r.roster_id)) # Sort by size (asc), then ID
        
        if not short_rosters or len(short_rosters) < 2:
            return []
            
        self.log_fn(f"[MERGE REPAIR] Found {len(short_rosters)} short rosters (<=3 tours). Scanning pairs (Budget={budget})...")
        
        built_columns = []
        attempts = 0
        success = 0
        
        # 2. Pairwise Merge Loop
        for i in range(len(short_rosters)):
            if attempts >= budget:
                break
                
            r1 = short_rosters[i]
            r1_tours = set(r1.covered_tour_ids)
            r1_blocks = [self.block_by_id[bid] for bid in r1.block_ids if bid in self.block_by_id]
            
            # Use 'stride' or limited lookahead to catch diverse pairs if loop is large
            # But simple N^2 on short list is probably fine if list is small (~200).
            # If list is large (>500), we hit budget fast.
            
            for j in range(i + 1, len(short_rosters)):
                if attempts >= budget:
                    break
                    
                r2 = short_rosters[j]
                
                # Check for shared blocks or tours (Disjoint check)
                if not r1_tours.isdisjoint(r2.covered_tour_ids):
                    continue
                
                # Optimization: Block ID overlap check (should match tours, but safe to check)
                if not r1.block_ids.isdisjoint(r2.block_ids):
                    continue

                attempts += 1
                
                # Check Merge Validity
                r2_blocks = [self.block_by_id[bid] for bid in r2.block_ids if bid in self.block_by_id]
                combined_blocks = sorted(r1_blocks + r2_blocks, key=lambda b: (b.day, b.start_min))
                
                # Try to build roster
                col = create_roster_from_blocks_pt(
                    roster_id=self._get_next_roster_id(), 
                    block_infos=combined_blocks
                )
                
                if col and col.is_valid:
                    built_columns.append(col)
                    success += 1
        
        if success > 0:
            self.log_fn(f"[MERGE REPAIR] Attempts: {attempts}, Merged: {success} new columns")
            
        return built_columns

    def generate_anchor_pack_variants(self, anchor_tour_ids, max_variants_per_anchor=5):
        """
        Generate diverse variants around anchor tours (low support).
        Returns list of RosterColumns (to be added by solver).
        """
        self.log_fn(f"[ANCHOR&PACK] {len(anchor_tour_ids)} anchors, {max_variants_per_anchor} vars/anchor...")
        built_columns = []
        
        # Debug counters
        stats = {
            "attempts": 0,
            "no_anchor_blocks": 0,
            "no_candidates_for_day": 0,
            "validation_fail_hard": 0,
            "validation_fail_hours": 0,
            "built_ok": 0
        }

        # Prepare day cache for fast lookup
        day_blocks_map = defaultdict(list)
        for b in self.block_infos:
            day_blocks_map[b.day].append(b)
        # Pre-sort to avoid repeated sorting
        for d in day_blocks_map:
            # Sort by tours (dense) then work_min (long)
            day_blocks_map[d].sort(key=lambda b: (-b.tours, -b.work_min, b.block_id))

        active_days = sorted(list(day_blocks_map.keys()))
        if not active_days:
            return []

        # Limit debug logging
        debug_anchors = list(anchor_tour_ids)[:3]

        for i, anchor_tid in enumerate(anchor_tour_ids):
            # multiple anchors? no, one anchor tid generally maps to one or a few blocks
            # Look up blocks - ensure robust tour_id checking
            anchor_blocks = [b for b in self.block_infos if anchor_tid in getattr(b, 'tour_ids', ())]
            
            if not anchor_blocks:
                stats["no_anchor_blocks"] += 1
                if anchor_tid in debug_anchors:
                    self.log_fn(f"[DEBUG] Anchor {anchor_tid}: No blocks found! (Total blocks checked: {len(self.block_infos)})")
                continue
            
            if anchor_tid in debug_anchors:
                self.log_fn(f"[DEBUG] Anchor {anchor_tid}: Found {len(anchor_blocks)} start blocks. First: {anchor_blocks[0].block_id} (Day {anchor_blocks[0].day}, Tours: {len(anchor_blocks[0].tour_ids)})")

            # Use top anchor blocks
            anchor_blocks.sort(key=lambda b: (-b.tours, -b.work_min, b.block_id))
            
            variants_generated = 0
            for anchor_block in anchor_blocks[:2]: # Try top 2 anchor blocks
                if variants_generated >= max_variants_per_anchor:
                    break

                for v in range(max_variants_per_anchor):
                    if variants_generated >= max_variants_per_anchor:
                        break
                    
                    stats["attempts"] += 1
                    current = [anchor_block]
                    current_tours = set(anchor_block.tour_ids)
                    current_min = anchor_block.work_min
                    
                    # Diversity logic: Force sub-optimal on one day
                    forced_day_idx = v % len(active_days)
                    forced_day = active_days[forced_day_idx]
                    forced_rank = 1 + (v // len(active_days))
                    
                    for day in active_days:
                        if day == anchor_block.day:
                            continue
                            
                        # Candidates for this day
                        # Must strictly not overlap current tours (greedy check)
                        cands = [b for b in day_blocks_map[day] if not any(tid in current_tours for tid in getattr(b, 'tour_ids', ()))]
                        
                        if not cands:
                            stats["no_candidates_for_day"] += 1
                            continue
                        
                        # Pick based on diversity rule
                        pick_idx = forced_rank if day == forced_day else 0
                        
                        if pick_idx >= len(cands):
                           pick_idx = 0
                           
                        # SEARCH for first valid candidate starting at pick_idx
                        cand_found = None
                        search_order = cands[pick_idx:] + cands[:pick_idx]
                        
                        for cand in search_order[:50]: # Limit search
                            can_add, reason = can_add_block_to_roster(current, cand, current_min)
                            if can_add:
                                cand_found = cand
                                break
                        
                        if cand_found:
                            current.append(cand_found)
                            current_tours.update(cand_found.tour_ids)
                            current_min += cand_found.work_min
                    
                    # Create column
                    col = create_roster_from_blocks_pt(roster_id=self._get_next_roster_id(), block_infos=current)
                    if col and col.is_valid:
                        built_columns.append(col)
                        variants_generated += 1
                        stats["built_ok"] += 1
                    else:
                        stats["validation_fail_hard"] += 1

        self.log_fn(f"[ANCHOR&PACK] Built {len(built_columns)} vars. Stats: {stats}")
        return built_columns
    # <<< STEP8: ANCHOR_PACK

    def generate_singleton_columns(self, penalty_factor: float = 100.0) -> int:
        """
        Generate one singleton column per block (emergency coverage).
        
        These columns cover exactly ONE block each and have very high cost.
        This guarantees RMP always finds a feasible solution (worst case:
        use all singleton columns = one driver per block).
        
        Note: penalty_factor is informational - actual penalty is set in solve_rmp
        by detecting singleton columns (those with exactly 1 block).
        
        Args:
            penalty_factor: Documentation only - penalty multiplier for RMP objective
            
        Returns:
            Number of singleton columns added
        """
        self.log_fn(f"Generating singleton fallback columns (penalty={penalty_factor}x)...")
        
        added = 0
        for block_info in self.block_infos:
            # Create minimal PT column with just this one block
            column = create_roster_from_blocks_pt(
                roster_id=self._get_next_roster_id(),
                block_infos=[block_info],
            )
            
            if column and column.is_valid:
                # Singleton columns are identified by num_blocks == 1 in solve_rmp
                if self.add_column(column):
                    added += 1
        
        self.log_fn(f"Singleton columns added: {added}")
        return added


def create_block_infos_from_blocks(blocks: list) -> list[BlockInfo]:
    """
    Convert Block objects to BlockInfo for the generator.
    
    Handles both Block and other block-like objects.
    """
    block_infos = []
    
    for b in blocks:
        # Get block ID
        if hasattr(b, 'id'):
            block_id = b.id
        elif hasattr(b, 'block_id'):
            block_id = b.block_id
        else:
            block_id = str(id(b))
        
        # Get day index
        if hasattr(b, 'day_idx'):
            day = b.day_idx
        elif hasattr(b, 'day'):
            day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
            if hasattr(b.day, 'value'):
                day = day_map.get(b.day.value, 0)
            else:
                day = day_map.get(str(b.day), 0)
        else:
            day = 0
        
        # Get start time (minutes from midnight)
        if hasattr(b, 'start_min'):
            start_min = b.start_min
        elif hasattr(b, 'first_start'):
            t = b.first_start
            start_min = t.hour * 60 + t.minute if hasattr(t, 'hour') else 0
        else:
            start_min = 0
        
        # Get end time (minutes from midnight)
        if hasattr(b, 'end_min'):
            end_min = b.end_min
        elif hasattr(b, 'last_end'):
            t = b.last_end
            end_min = t.hour * 60 + t.minute if hasattr(t, 'hour') else 0
        else:
            end_min = 0
        
        # Get work minutes
        if hasattr(b, 'work_min'):
            work_min = b.work_min
        elif hasattr(b, 'total_work_hours'):
            work_min = int(b.total_work_hours * 60)
        else:
            work_min = 0
        
        # Get tours count
        if hasattr(b, 'tours'):
            tours = len(b.tours)
        elif hasattr(b, 'tour_count'):
            tours = b.tour_count
        else:
            tours = 1
        
        # Get tour IDs
        tour_ids = []
        if hasattr(b, 'tours') and b.tours:
            for t in b.tours:
                if hasattr(t, 'id'):
                    tour_ids.append(t.id)
                elif hasattr(t, 'tour_id'):
                    tour_ids.append(t.tour_id)
                elif isinstance(t, str):
                    tour_ids.append(t)
        elif hasattr(b, 'tour_ids') and b.tour_ids:
             tour_ids = list(b.tour_ids)

        block_infos.append(BlockInfo(
            block_id=block_id,
            day=day,
            start_min=start_min,
            end_min=end_min,
            work_min=work_min,
            tours=tours,
            tour_ids=tuple(tour_ids),
        ))
    
    return block_infos
