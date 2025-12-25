"""
Roster Column Generator - ALNS Heuristic for Column Generation

Generates valid RosterColumns (soft 40h target, <=55h max) for 
the Set-Partitioning master problem.

Moves:
1. Build-from-seed: Start with one block, greedily add compatible blocks
2. Repair-uncovered: Generate columns targeting uncovered blocks
3. Swap builder: Exchange blocks between two rosters
"""

import logging
import random
from collections import defaultdict
from typing import Optional

from src.services.roster_column import (
    RosterColumn, BlockInfo, create_roster_from_blocks, create_roster_from_blocks_pt,
    can_add_block_to_roster, MIN_WEEK_HOURS, MAX_WEEK_HOURS
)

logger = logging.getLogger("ColumnGenerator")

MIN_WEEK_MINUTES = int(MIN_WEEK_HOURS * 60)  # 2400 (soft target for FTE, hard cap for PT)
MAX_WEEK_MINUTES = int(MAX_WEEK_HOURS * 60)  # 3180


class RosterColumnGenerator:
    """
    Heuristic column generator for Set-Partitioning.
    
    Generates rosters that satisfy hard constraints with a soft 40h target.
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
        
        self.pool[column.signature] = column
        
        # Update index
        for block_id in column.block_ids:
            self.block_to_rosters[block_id].add(column.signature)
        
        return True
    
    def get_pool_stats(self) -> dict:
        """Get statistics about the column pool."""
        if not self.pool:
            return {"size": 0}
        
        hours = [c.total_hours for c in self.pool.values()]
        blocks_per_roster = [c.num_blocks for c in self.pool.values()]
        
        # Coverage frequency
        coverage = {block_id: len(sigs) for block_id, sigs in self.block_to_rosters.items()}
        uncovered = [bid for bid in self.block_by_id if bid not in coverage or coverage[bid] == 0]
        rare_covered = [bid for bid, cnt in coverage.items() if cnt <= 2]
        
        return {
            "size": len(self.pool),
            "hours_min": min(hours),
            "hours_max": max(hours),
            "hours_avg": sum(hours) / len(hours),
            "blocks_per_roster_avg": sum(blocks_per_roster) / len(blocks_per_roster),
            "uncovered_blocks": len(uncovered),
            "rare_covered_blocks": len(rare_covered),
        }
    
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
        
        # Create and validate roster
        roster = create_roster_from_blocks(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None
    
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
        
        # Create and validate roster
        roster = create_roster_from_blocks(
            roster_id=self._get_next_roster_id(),
            block_infos=current_blocks,
        )
        
        return roster if roster.is_valid else None

    
    # =========================================================================
    # MOVE 3: SWAP BUILDER
    # =========================================================================
    
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
            
            # Create column based on driver type
            if assignment.driver_type == "PT":
                column = create_roster_from_blocks_pt(
                    roster_id=self._get_next_roster_id(),
                    block_infos=block_infos,
                )
            else:
                column = create_roster_from_blocks(
                    roster_id=self._get_next_roster_id(),
                    block_infos=block_infos,
                )
            
            if column and self.add_column(column):
                added += 1
        
        self.log_fn(f"Seeded {added} columns from greedy solution")
        return added

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
        
        block_infos.append(BlockInfo(
            block_id=block_id,
            day=day,
            start_min=start_min,
            end_min=end_min,
            work_min=work_min,
            tours=tours,
        ))
    
    return block_infos
