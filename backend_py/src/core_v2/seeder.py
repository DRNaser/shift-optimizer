"""
Core v2 - Greedy Weekly Seeder (BLOCK-FIRST STRATEGY!)

Matches Manual Planning Approach:
1. GREEDY block formation per day (Template Priority: Late > Early > Wide)
2. Build multi-day rosters from BLOCKS (Generous Greedy Search)
3. LP chooses best combinations
"""

import logging
from typing import Dict, List, Set
from collections import defaultdict

from .model.tour import TourV2
from .model.duty import DutyV2
from .model.column import ColumnV2
from .duty_factory import DutyFactoryTopK, DutyFactoryCaps
from .validator.rules import ValidatorV2

logger = logging.getLogger("Seeder")


class GreedyWeeklySeeder:
    """Greedy block-based seeder matching manual planning."""
    
    def __init__(self, tours_by_day: Dict[int, List[TourV2]], factory: DutyFactoryTopK, validator: ValidatorV2, target_seeds: int = 5000):
        self.tours_by_day = tours_by_day
        self.factory = factory
        self.validator = validator
        self.target_seeds = target_seeds
    
    def generate_seeds(self) -> List[ColumnV2]:
        """
        BLOCK-FIRST GREEDY STRATEGY.
        Step 1: Form daily blocks (Late > Early > Wide)
        Step 2: Build multi-day rosters from blocks (Depth 50)
        Step 3: Return columns
        """
        logger.info("="*60)
        logger.info("BLOCK-FIRST GREEDY SEEDING (Template Priority)")
        logger.info("="*60)
        
        # Step 1: Form daily blocks
        blocks_by_day = self._form_daily_blocks_greedy()
        
        # Step 2: Build multi-day from blocks
        multi_day = self._build_multi_day_from_blocks(blocks_by_day)
        
        # Step 3: Singleton fallback
        singletons = self._singleton_fallback(blocks_by_day)
        
        all_cols = multi_day + singletons
        logger.info(f"TOTAL: {len(multi_day)} multi-day + {len(singletons)} singletons = {len(all_cols)}")
        
        # Cap
        if len(all_cols) > self.target_seeds:
            all_cols = all_cols[:self.target_seeds]
        
        return all_cols
    
    def _form_daily_blocks_greedy(self) -> Dict[int, List[DutyV2]]:
        """
        GREEDY block formation with TEMPLATE PRIORITY.
        
        Priority:
        1. LATE Blocks (Start >= 11:00) - Critical sinks
        2. EARLY Blocks (End <= 17:00) - Good sources
        3. WIDE Blocks (Remainder) - Hard to chain
        """
        blocks_by_day = {}
        zero_duals = {}
        for day_tours in self.tours_by_day.values():
            for t in day_tours:
                zero_duals[t.tour_id] = 0.0
        
        caps = DutyFactoryCaps()
        
        for day in sorted(self.tours_by_day.keys()):
            all_duties = self.factory.get_day_duties(day, zero_duals, caps)
            
            # Filter to 2er/3er only
            candidates = [d for d in all_duties if d.num_tours >= 2]
            
            # Categorize
            late = []
            early = []
            wide = []
            
            for d in candidates:
                start_h = d.start_min / 60.0
                end_h = d.end_min / 60.0
                
                if start_h >= 11.0:
                    late.append(d)
                elif end_h <= 17.0:
                    early.append(d)
                else:
                    wide.append(d)
            
            # Sort greedy by work
            late.sort(key=lambda x: x.work_min, reverse=True)
            early.sort(key=lambda x: x.work_min, reverse=True)
            wide.sort(key=lambda x: x.work_min, reverse=True)
            
            selected = []
            covered: Set[str] = set()
            
            def add_blocks(block_list):
                for d in block_list:
                    if not any(tid in covered for tid in d.tour_ids):
                        selected.append(d)
                        covered.update(d.tour_ids)
            
            # PRIORITY ORDER
            add_blocks(late)
            add_blocks(early)
            add_blocks(wide)
            
            # Fallback 1er
            d1 = [d for d in all_duties if d.num_tours == 1]
            for duty in d1:
                if duty.tour_ids[0] not in covered:
                    selected.append(duty)
                    covered.add(duty.tour_ids[0])
            
            blocks_by_day[day] = selected
            
            cnt_l = len([x for x in selected if x in late])
            cnt_e = len([x for x in selected if x in early])
            cnt_w = len([x for x in selected if x in wide])
            logger.info(f"Day {day}: {cnt_l} Late, {cnt_e} Early, {cnt_w} Wide")
        
        return blocks_by_day
    
    def _build_multi_day_from_blocks(self, blocks_by_day: Dict[int, List[DutyV2]]) -> List[ColumnV2]:
        """Build 2-5 day chains using Generous Greedy Search (Depth 50)."""
        cols = []
        cid = [0]
        
        # Use ALL selected blocks for chaining (including 1er)
        # This is critical for Wide -> Late(1er) transitions!
        good_blocks = blocks_by_day
        
        days = sorted(self.tours_by_day.keys())
        
        # 5-day chains
        for i in range(len(days) - 4):
            for d0 in good_blocks[days[i]][:50]:
                for d1 in good_blocks[days[i+1]][:50]:
                    if not self.validator.can_chain_days(d0, d1): continue
                    for d2 in good_blocks[days[i+2]][:50]:
                        if not self.validator.can_chain_days(d1, d2): continue
                        for d3 in good_blocks[days[i+3]][:50]:
                            if not self.validator.can_chain_days(d2, d3): continue
                            for d4 in good_blocks[days[i+4]][:50]:
                                if not self.validator.can_chain_days(d3, d4): continue
                                col = ColumnV2.from_duties(f"B5_{cid[0]}", [d0,d1,d2,d3,d4], "block5")
                                cols.append(col)
                                cid[0] += 1
        logger.info(f"Built {len(cols)} 5-day block chains")
        
        # 3-day chains
        for i in range(len(days) - 2):
            for d0 in good_blocks[days[i]][:50]:
                for d1 in good_blocks[days[i+1]][:50]:
                    if not self.validator.can_chain_days(d0, d1): continue
                    for d2 in good_blocks[days[i+2]][:50]:
                        if not self.validator.can_chain_days(d1, d2): continue
                        col = ColumnV2.from_duties(f"B3_{cid[0]}", [d0,d1,d2], "block3")
                        cols.append(col)
                        cid[0] += 1
        logger.info(f"Built {len(cols) - len([c for c in cols if 'B5' in c.col_id])} 3-day block chains")
        
        # 2-day
        for i in range(len(days) - 1):
            for d0 in good_blocks[days[i]][:50]:
                for d1 in good_blocks[days[i+1]][:50]:
                    if not self.validator.can_chain_days(d0, d1): continue
                    col = ColumnV2.from_duties(f"B2_{cid[0]}", [d0,d1], "block2")
                    cols.append(col)
                    cid[0] += 1
        
        return cols
    
    def _singleton_fallback(self, blocks_by_day: Dict[int, List[DutyV2]]) -> List[ColumnV2]:
        cols = []
        cid = 0
        for day, duties in blocks_by_day.items():
            for d in duties:
                if d.num_tours >= 2:
                    col = ColumnV2.from_duties(f"BS_{cid}", [d], "blocksing")
                    cols.append(col)
                    cid += 1
        return cols
