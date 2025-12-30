"""
Run Core v2 Shadow Mode (Vertical Slice)

Loads a given dataset (or generates dummy/mock data if needed),
runs OptimizerCoreV2, and reports results.
"""

import sys
import os
import logging
import json
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend_py"))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.adapter import Adapter
from src.domain.models import Tour

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RunV2")

def main():
    logger.info("Starting Core v2 Shadow Runner...")
    
    # 1. Load Data
    # For Vertical Slice, we need realistic data.
    # Do we have a cached dataset?
    # Or can we generate simple dummy tours?
    
    # Try to load verification.json if exists?
    # Or just generate 4 days of tours.
    
    logger.info("Generating Mock KW51 Data (4 days, 100 tours)...")
    tours_v1 = generate_mock_tours(num_tours=100, days=4)
    
    # 2. Convert to v2
    logger.info(f"Converting {len(tours_v1)} v1 tours to v2...")
    adapter = Adapter(tours_v1)
    tours_v2 = adapter.convert_to_v2()
    
    # 3. Configure
    config = {
        "max_cg_iterations": 20,
        "backend": "highspy",
        "mip_time_limit": 30.0
    }
    
    # 4. Run Optimizer
    logger.info("Invoking OptimizerCoreV2...")
    optimizer = OptimizerCoreV2()
    
    try:
        result = optimizer.solve(tours_v2, config)
    except Exception as e:
        logger.error(f"Optimizer Crashed: {e}", exc_info=True)
        return
        
    # 5. Report
    if result.status == "SUCCESS":
        status = result.status
        stats = result.stats
        cols = result.best_columns
        
        logger.info("=" * 40)
        logger.info("SOLUTION FOUND")
        logger.info(f"Drivers: {result.num_drivers}")
        logger.info(f"Runtime: {stats['total_time']:.2f}s")
        logger.info(f"MIP Obj: {stats.get('mip_obj', 0):.2f}")
        
        # Analyze Utilization
        under30 = sum(1 for c in cols if c.hours < 30)
        under20 = sum(1 for c in cols if c.hours < 20)
        total = len(cols)
        
        logger.info(f"Under 30h: {under30} ({under30/total:.1%})")
        logger.info(f"Under 20h: {under20} ({under20/total:.1%})")
        logger.info("=" * 40)
        
        # 6. Convert back (Verify Adapter)
        # result.best_columns are ColumnV2 objects, so we can pass directly.
        rosters_v1 = adapter.convert_to_v1(cols)
        
        # Verify valid conversion
        logger.info(f"Converted back to {len(rosters_v1)} v1 RosterColumns.")
        valid_cnt = sum(1 for r in rosters_v1 if r.is_valid)
        logger.info(f"Valid v1 Rosters: {valid_cnt}/{len(rosters_v1)}")
        
    else:
        logger.error(f"Solve Failed: {result.status}")
        logger.error(f"Reason: {result.stats.get('error')}")

def generate_mock_tours(num_tours=100, days=4):
    """Generate simple tours for testing."""
    tours = []
    import random
    from datetime import time
    from src.domain.models import Weekday
    
    for i in range(num_tours):
        day_idx = i % days
        # Map 0->Mon, etc. assuming 0 based index matching Weekday order
        # Weekday enums are "Mon", "Tue"...
        days_enum = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY]
        day_enum = days_enum[day_idx]
        
        start_min = random.randint(300, 960) # 5am to 4pm
        duration = random.randint(120, 480) # 2h to 8h
        end_min = start_min + duration
        
        # Convert min to time
        start_h, start_m = divmod(start_min, 60)
        s_time = time(start_h, start_m)
        
        # Handle end time (might be > 24h, but time object caps at 23:59)
        # TourV2 supports >24h logic.
        # Tour definition: end_time is time().
        # If cross-midnight, end_time is e.g. 02:00.
        
        end_real_min = end_min % 1440
        end_h, end_m = divmod(end_real_min, 60)
        e_time = time(end_h, end_m)
        
        t = Tour(
            id=f"T_{i}",
            day=day_enum,
            start_time=s_time,
            end_time=e_time,
            location="ZoneA",
            required_qualifications=[]
        )
        tours.append(t)
    return tours

# Helper for reconstruction since we need objects
def col_from_dict(d: dict):
    # Dummy wrapper to pass dict back if needed? 
    # Or just skip back-conversion in this vertical slice check logic.
    pass

if __name__ == "__main__":
    main()
