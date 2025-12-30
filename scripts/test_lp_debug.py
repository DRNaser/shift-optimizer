"""
Debug Test: Minimal LP build/solve test for hang diagnosis.
Tests: A) Tue-only (394 tours), B) Tue+Wed
"""

import sys
import os
import logging
from datetime import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend_py"))

from src.core_v2.model.tour import TourV2
from src.core_v2.model.duty import DutyV2
from src.core_v2.model.column import ColumnV2
from src.core_v2.pool.store import ColumnPoolStore
from src.core_v2.master.master_lp import MasterLP
from src.core_v2.model.weektype import WeekCategory

logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DebugLP")


def create_mock_tours(day: int, count: int) -> list[TourV2]:
    """Create mock tours for a given day."""
    tours = []
    for i in range(count):
        # Spread tours across the day (5am - 11pm)
        start_min = 300 + (i * 1080 // count)  # 300 = 5:00
        end_min = start_min + 240 + (i % 5) * 30  # 4-6 hour tours
        end_min = min(end_min, 1380)  # Cap at 23:00
        duration = end_min - start_min
        
        tour = TourV2(
            tour_id=f"T_d{day}_{i:04d}",
            day=day,
            start_min=start_min,
            end_min=end_min,
            duration_min=duration,
        )
        tours.append(tour)
    return tours


def create_singleton_columns(tours: list[TourV2]) -> list[ColumnV2]:
    """Create one singleton column per tour."""
    cols = []
    for tour in tours:
        duty = DutyV2.from_tours(
            duty_id=f"duty_{tour.tour_id}",
            tours=[tour]
        )
        col = ColumnV2.from_duties(
            col_id=f"col_{duty.duty_id}",
            duties=[duty],
            origin="test_singleton"
        )
        cols.append(col)
    return cols


def test_minimal_lp(tours: list[TourV2], test_name: str):
    """Run minimal LP build/solve test."""
    logger.info("=" * 60)
    logger.info(f"TEST: {test_name}")
    logger.info(f"Tours: {len(tours)}")
    logger.info("=" * 60)
    
    # Create columns
    columns = create_singleton_columns(tours)
    logger.info(f"Created {len(columns)} singleton columns")
    
    # Get all tour IDs
    all_tour_ids = [t.tour_id for t in tours]
    logger.info(f"Tour IDs: {len(all_tour_ids)}")
    
    # Build LP
    logger.info("-" * 40)
    logger.info("Building LP...")
    
    try:
        master_lp = MasterLP(columns, all_tour_ids)
        master_lp.build(WeekCategory.COMPRESSED, debug=True)
        logger.info("LP Build: SUCCESS")
    except Exception as e:
        logger.error(f"LP Build: FAILED - {e}")
        return
    
    # Solve LP
    logger.info("-" * 40)
    logger.info("Solving LP...")
    
    try:
        result = master_lp.solve(time_limit=10.0, debug=True)
        logger.info(f"LP Solve: {result['status']}")
        logger.info(f"  Objective: {result.get('objective', 'N/A')}")
        logger.info(f"  Runtime: {result.get('runtime', 'N/A'):.2f}s")
        logger.info(f"  Artificial: {result.get('artificial_used', 'N/A')}")
        logger.info(f"  Build Stats: {result.get('build_stats', {})}")
    except Exception as e:
        logger.error(f"LP Solve: FAILED - {e}", exc_info=True)
    
    logger.info("=" * 60)


def main():
    logger.info("LP HANG DEBUG TEST")
    logger.info("=" * 60)
    
    # Test A: Tue-only (394 tours)
    tue_tours = create_mock_tours(day=1, count=394)
    test_minimal_lp(tue_tours, "Tue-only (394 tours)")
    
    # Test B: Tue + Wed (394 + 266 = 660 tours)
    wed_tours = create_mock_tours(day=2, count=266)
    combined_tours = tue_tours + wed_tours
    test_minimal_lp(combined_tours, "Tue+Wed (660 tours)")
    
    # Test C: Full KW51 scale (1272 tours)
    mon_tours = create_mock_tours(day=0, count=290)
    fri_tours = create_mock_tours(day=4, count=322)
    full_tours = mon_tours + tue_tours + wed_tours + fri_tours
    test_minimal_lp(full_tours, "Full KW51 (1272 tours)")
    
    logger.info("ALL TESTS COMPLETE")


if __name__ == "__main__":
    main()
