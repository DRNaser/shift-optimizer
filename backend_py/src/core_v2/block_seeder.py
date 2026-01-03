"""
Block-Based Seeder - Replicate Manual Planning Strategy

Manual Planning Strategy:
1. For each day: Form BLOCKS (3er first, then 2er, then 1er as fallback)
2. Use these blocks to build multi-day rosters
3. LP chooses which multi-day roster combinations

Current Problem:
- DutyFactory creates ALL possible 1er/2er/3er combinations
- LP can choose 1er (easier) even when 3er possible
- Result: Too many singletons!

New Strategy:
- GREEDY BLOCK FORMATION first (per day)
- Only offer these blocks to multi-day builder
- Force utilization!
"""

import logging
from typing import Dict, List, Set
from collections import defaultdict

from ..model.tour import TourV2
from ..model.duty import DutyV2
from ..model.column import ColumnV2
from ..duty_factory import DutyFactoryTopK, DutyFactoryCaps
from ..validator.rules import ValidatorV2

logger = logging.getLogger("BlockSeeder")


class BlockBasedSeeder:
    """
    Greedy block formation seeder matching manual planning strategy.
    
    Step 1: Form daily blocks (3er > 2er > 1er)
    Step 2: Combine blocks into multi-day rosters
    Step 3: Return only block-based columns
    """
    
    def __init__(self, tours_by_day: Dict[int, List[TourV2]], factory: DutyFactoryTopK, validator: ValidatorV2):
        self.tours_by_day = tours_by_day
        self.factory = factory
        self.validator = validator
        self.sorted_days = sorted(tours_by_day.keys())
    
    def generate_seeds(self) -> List[ColumnV2]:
        """
        Generate seed columns using block-first strategy.
        
        Returns ONLY columns built from greedy blocks.
        """
        logger.info("="*60)
        logger.info("BLOCK-BASED SEEDER: Manual Planning Strategy")
        logger.info("="*60)
        
        # Step 1: Form daily blocks (GREEDY!)
        blocks_by_day = self._form_daily_blocks()
        
        # Step 2: Multi-day combinations
        multi_day_cols = self._build_multi_day_from_blocks(blocks_by_day)
        
        # Step 3: Singleton fallback (only for uncovered tours)
        singleton_cols = self._generate_singleton_fallbacks(blocks_by_day)
        
        all_cols = multi_day_cols + singleton_cols
        
        logger.info(f"Block Seeder Generated: {len(multi_day_cols)} multi-day + {len(singleton_cols)} singletons = {len(all_cols)} total")
        
        return all_cols
    
    def _form_daily_blocks(self) -> Dict[int, List[DutyV2]]:
        """
        GREEDY block formation for each day.
        
        Strategy (matches manual planning):
        1. Try to form 3er-blocks (maximize coverage)
        2. Try to form 2er-blocks (for remainders)
        3. Leave 1er as last resort (will be singletons)
        
        Returns:
            Dict[day] -> List of SELECTED duties (3er > 2er > 1er)
        """
        blocks_by_day = {}
        
        for day in self.sorted_days:
            day_tours = self.tours_by_day[day]
            logger.info(f"\n--- Day {day}: {len(day_tours)} tours ---")
            
            # Get ALL possible duties from factory (no bias yet)
            zero_duals = {t.tour_id: 0.0 for t in day_tours}
            caps = DutyFactoryCaps()
            all_duties = self.factory.get_day_duties(day, zero_duals, caps)
            
            # Separate by type
            duties_3er = [d for d in all_duties if d.num_tours == 3]
            duties_2er = [d for d in all_duties if d.num_tours == 2]
            duties_1er = [d for d in all_duties if d.num_tours == 1]
            
            logger.info(f"  Available: {len(duties_3er)} 3er, {len(duties_2er)} 2er, {len(duties_1er)} 1er")
            
            # GREEDY SELECTION
            selected_duties = []
            covered_tours: Set[str] = set()
            
            # 1. FIRST: Greedy 3er (max coverage per duty)
            for duty in sorted(duties_3er, key=lambda d: (d.work_min, len(d.tour_ids)), reverse=True):
                # Check if any tour already covered
                if any(tid in covered_tours for tid in duty.tour_ids):
                    continue
                # Select this 3er block!
                selected_duties.append(duty)
                covered_tours.update(duty.tour_ids)
            
            logger.info(f"  Selected {len([d for d in selected_duties if d.num_tours == 3])} 3er-blocks, covered {len(covered_tours)} tours")
            
            # 2. THEN: Greedy 2er (for remaining tours)
            for duty in sorted(duties_2er, key=lambda d: (d.work_min, len(d.tour_ids)), reverse=True):
                if any(tid in covered_tours for tid in duty.tour_ids):
                    continue
                selected_duties.append(duty)
                covered_tours.update(duty.tour_ids)
            
            logger.info(f"  Selected {len([d for d in selected_duties if d.num_tours == 2])} 2er-blocks, covered {len(covered_tours)} tours")
            
            # 3. LAST RESORT: 1er (for remaining tours)
            for duty in duties_1er:
                if duty.tour_ids[0] not in covered_tours:
                    selected_duties.append(duty)
                    covered_tours.update(duty.tour_ids)
            
            logger.info(f"  Selected {len([d for d in selected_duties if d.num_tours == 1])} 1er-blocks (fallback)")
            logger.info(f"  TOTAL: {len(selected_duties)} blocks covering {len(covered_tours)}/{len(day_tours)} tours")
            
            blocks_by_day[day] = selected_duties
        
        return blocks_by_day
    
    def _build_multi_day_from_blocks(self, blocks_by_day: Dict[int, List[DutyV2]]) -> List[ColumnV2]:
        """
        Build multi-day columns from daily blocks.
        
        Strategy:
        - Try 5-day chains
        - Try 4-day chains
        - Try 3-day chains
        - Try 2-day chains
        
        Focus on HIGH-UTILIZATION blocks (3er/2er preferred)
        """
        columns = []
        col_id_counter = [0]  # Mutable counter
        
        # Identify "good" blocks (2er/3er) for multi-day
        high_util_blocks = defaultdict(list)
        for day, duties in blocks_by_day.items():
            # Prefer 3er and 2er blocks
            good_blocks = [d for d in duties if d.num_tours >= 2]
            high_util_blocks[day] = good_blocks
        
        # Try to build 5-day chains from high-util blocks
        for start_day in range(min(self.sorted_days), max(self.sorted_days) - 3):
            days_range = range(start_day, start_day + 5)
            
            # Check if all days have blocks
            if not all(d in high_util_blocks and len(high_util_blocks[d]) > 0 for d in days_range):
                continue
            
            # Try combinations (take first available from each day for simplicity)
            for d0 in high_util_blocks[start_day][:3]:  # Limit combinations
                for d1 in high_util_blocks[start_day + 1][:3]:
                    if not self.validator.can_chain_days(d0, d1):
                        continue
                    for d2 in high_util_blocks[start_day + 2][:3]:
                        if not self.validator.can_chain_days(d1, d2):
                            continue
                        for d3 in high_util_blocks[start_day + 3][:3]:
                            if not self.validator.can_chain_days(d2, d3):
                                continue
                            for d4 in high_util_blocks[start_day + 4][:3]:
                                if not self.validator.can_chain_days(d3, d4):
                                    continue
                                
                                # Valid 5-day chain!
                                col = ColumnV2.from_duties(
                                    col_id=f"BLOCK5_{col_id_counter[0]}",
                                    duties=[d0, d1, d2, d3, d4],
                                    origin="block_seeder_5day"
                                )
                                columns.append(col)
                                col_id_counter[0] += 1
        
        # Try 3-day and 2-day chains (similar logic, simplified)
        for start_day in range(min(self.sorted_days), max(self.sorted_days) - 1):
            # 3-day
            if start_day + 2 <= max(self.sorted_days):
                for d0 in high_util_blocks[start_day][:5]:
                    for d1 in high_util_blocks[start_day + 1][:5]:
                        if not self.validator.can_chain_days(d0, d1):
                            continue
                        for d2 in high_util_blocks[start_day + 2][:5]:
                            if not self.validator.can_chain_days(d1, d2):
                                continue
                            col = ColumnV2.from_duties(
                                col_id=f"BLOCK3_{col_id_counter[0]}",
                                duties=[d0, d1, d2],
                                origin="block_seeder_3day"
                            )
                            columns.append(col)
                            col_id_counter[0] += 1
            
            # 2-day
            for d0 in high_util_blocks[start_day][:10]:
                for d1 in high_util_blocks[start_day + 1][:10]:
                    if not self.validator.can_chain_days(d0, d1):
                        continue
                    col = ColumnV2.from_duties(
                        col_id=f"BLOCK2_{col_id_counter[0]}",
                        duties=[d0, d1],
                        origin="block_seeder_2day"
                    )
                    columns.append(col)
                    col_id_counter[0] += 1
        
        logger.info(f"  Multi-day from blocks: {len(columns)} columns")
        return columns
    
    def _generate_singleton_fallbacks(self, blocks_by_day: Dict[int, List[DutyV2]]) -> List[ColumnV2]:
        """
        Singleton columns ONLY for blocks that couldn't be multi-day connected.
        
        Prefer 3er/2er singleton days over 1er.
        """
        columns = []
        col_id = 0
        
        for day, duties in blocks_by_day.items():
            # Only create singletons for HIGH-UTIL blocks (2er/3er)
            for duty in duties:
                if duty.num_tours >= 2:  # Only 2er/3er singletons
                    col = ColumnV2.from_duties(
                        col_id=f"BLOCKSINGLE_{col_id}",
                        duties=[duty],
                        origin="block_seeder_singleton"
                    )
                    columns.append(col)
                    col_id += 1
        
        logger.info(f"  Block singletons (2er/3er only): {len(columns)} columns")
        return columns
