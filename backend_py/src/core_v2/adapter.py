"""
Core v2 - Adapter Layer

Bridges v1 Domain Models (Tours, Blocks) with v2 Canonical Models.
Allows v2 to run within the existing v1 pipeline (Shadow Mode).
"""

from typing import List, Optional
import uuid

# v1 Imports (using absolute references as per project structure)
from src.domain.models import Tour as TourV1
from src.domain.models import Block as BlockV1
# DutyV1 does not exist, Block is the equivalent
# RosterColumn is in services, not domain
from src.services.roster_column import RosterColumn as RosterColumnV1, BlockInfo, create_roster_from_blocks
# from src.domain.shared.time_util import TimeUtil

# v2 Imports
from .model.tour import TourV2
from .model.column import ColumnV2
from .model.duty import DutyV2


class Adapter:
    """
    Static adapter methods to convert between v1 and v2 models.
    """
    
    @staticmethod
    def to_v2_tours(v1_tours: List[TourV1]) -> List[TourV2]:
        """Convert v1 Tours to v2 Tours."""
        tours_v2 = []
        
        # Helper for day conversion
        day_map = {
            "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6
        }
        
        for t in v1_tours:
            # v1 Tour fields: id, day (Weekday enum), start_time (time), end_time (time)
            
            # Map Day
            # t.day might be Weekday enum or string
            day_str = str(t.day.value) if hasattr(t.day, 'value') else str(t.day)
            day_idx = day_map.get(day_str, 0)
            
            # Map Times
            # t.start_time is datetime.time
            start_min = t.start_time.hour * 60 + t.start_time.minute
            end_min = t.end_time.hour * 60 + t.end_time.minute
            
            # Handle Cross-Midnight (if end < start, assume +24h)
            if end_min < start_min:
                end_min += 1440
                
            dur = end_min - start_min
            
            t2 = TourV2(
                tour_id=t.id, # Map id -> tour_id
                day=day_idx,
                start_min=start_min,
                end_min=end_min,
                duration_min=dur,
                window_id=getattr(t, 'location', None), # Map location -> window_id/station?
                station=getattr(t, 'location', "DEFAULT"),
                qualifications=tuple(getattr(t, 'required_qualifications', []))
            )
            tours_v2.append(t2)
        return tours_v2

    @staticmethod
    def to_v1_solution(v2_columns: List[ColumnV2]) -> List[RosterColumnV1]:
        """
        Convert v2 Columns back to v1 RosterColumns via BlockInfo.
        """
        rosters_v1 = []
        
        for col_idx, col in enumerate(v2_columns):
            driver_id = f"V2_DRV_{col_idx:03d}"
            
            block_infos = []
            
            for d2 in col.duties:
                # Create BlockInfo (lightweight v1 struct)
                # BlockInfo(block_id, day, start_min, end_min, work_min, tours, tour_ids)
                
                safe_id = d2.duty_id.replace("|", "_")
                
                bi = BlockInfo(
                    block_id=f"B_{safe_id}",
                    day=d2.day,
                    start_min=d2.start_min,
                    end_min=d2.end_min,
                    work_min=d2.work_min,
                    tours=len(d2.tour_ids),
                    tour_ids=tuple(d2.tour_ids)
                )
                block_infos.append(bi)
            
            # Use factory to create validated RosterColumn
            rc = create_roster_from_blocks(
                roster_id=driver_id,
                block_infos=block_infos
            )
            rosters_v1.append(rc)
            
        return rosters_v1

    # Stateful version (better)
    def __init__(self, original_tours_v1: List[TourV1]):
        self.v1_map = {t.id: t for t in original_tours_v1}
        
    def convert_to_v2(self) -> List[TourV2]:
        return Adapter.to_v2_tours(list(self.v1_map.values()))
        
    def convert_to_v1(self, v2_columns: List[ColumnV2]) -> List[RosterColumnV1]:
        return Adapter.to_v1_solution(v2_columns)
