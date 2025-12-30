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
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend_py"))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.adapter import Adapter
from src.domain.models import Tour

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RunV2")


def main():
    logger.info("=" * 60)
    logger.info("Starting Core v2 Shadow Runner...")
    logger.info("=" * 60)
    
    # 1. Load Data
    logger.info("Generating Mock KW51 Data (4 days, 100 tours)...")
    tours_v1 = generate_mock_tours(num_tours=100, days=4)
    
    # 2. Convert to v2
    logger.info(f"Converting {len(tours_v1)} v1 tours to v2...")
    adapter = Adapter(tours_v1)
    tours_v2 = adapter.convert_to_v2()
    
    # 3. Configure
    run_id = f"shadow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    artifacts_dir = os.path.join(os.getcwd(), "artifacts", "v2_shadow", run_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    
    config = {
        "max_cg_iterations": 20,
        "backend": "highspy",
        "mip_time_limit": 30.0,
        "artifacts_dir": artifacts_dir,
    }
    
    # 4. Run Optimizer
    logger.info("Invoking OptimizerCoreV2...")
    optimizer = OptimizerCoreV2()
    
    try:
        result = optimizer.solve(tours_v2, config, run_id=run_id)
    except Exception as e:
        logger.error(f"Optimizer Crashed: {e}", exc_info=True)
        return
        
    # 5. Report
    logger.info("=" * 60)
    logger.info(f"STATUS: {result.status}")
    if result.error_code:
        logger.error(f"ERROR: {result.error_code} - {result.error_message}")
    logger.info("=" * 60)
    
    if result.status == "SUCCESS":
        logger.info("SOLUTION FOUND")
        logger.info(f"Drivers: {result.num_drivers}")
        logger.info(f"Runtime: {result.kpis.get('total_time', 0):.2f}s")
        logger.info(f"MIP Obj: {result.kpis.get('mip_obj', 0):.2f}")
        
        # Proof Checks
        logger.info("-" * 40)
        logger.info("VERIFICATION CHECKS:")
        
        # Check 1: Coverage
        coverage_ok = result.proof.coverage_pct == 100.0
        logger.info(f"  [{'PASS' if coverage_ok else 'FAIL'}] Coverage: {result.proof.coverage_pct:.1f}%")
        
        # Check 2: Artificial Columns
        artificial_ok = result.proof.artificial_used_final == 0
        logger.info(f"  [{'PASS' if artificial_ok else 'FAIL'}] Artificial Final: {result.proof.artificial_used_final} (LP: {result.proof.artificial_used_lp})")
        
        # Check 3: Utilization (FTE >= 40h)
        fte_min = result.kpis.get("fte_hours_min", 0)
        util_ok = fte_min >= 40.0 or result.kpis.get("drivers_fte", 0) == 0
        logger.info(f"  [{'PASS' if util_ok else 'WARN'}] FTE Hours Min: {fte_min:.1f}h")
        
        logger.info("-" * 40)
        
        # Analyze Utilization
        solution = result.solution
        under30 = sum(1 for a in solution if a.total_hours < 30)
        under20 = sum(1 for a in solution if a.total_hours < 20)
        total = len(solution)
        
        if total > 0:
            logger.info(f"Under 30h: {under30} ({under30/total:.1%})")
            logger.info(f"Under 20h: {under20} ({under20/total:.1%})")
        
        logger.info("=" * 60)
        
        # Save run_manifest.json
        manifest = result.to_dict()
        manifest["verification"] = {
            "coverage": "PASS" if coverage_ok else "FAIL",
            "artificial": "PASS" if artificial_ok else "FAIL",
            "utilization": "PASS" if util_ok else "WARN",
        }
        manifest_path = os.path.join(artifacts_dir, "run_manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, default=str)
        logger.info(f"Manifest saved: {manifest_path}")
        
    else:
        logger.error(f"Solve Failed: {result.status}")
        logger.error(f"Reason: {result.error_code} - {result.error_message}")


def generate_mock_tours(num_tours=100, days=4):
    """Generate simple tours for testing."""
    tours = []
    import random
    from datetime import time
    from src.domain.models import Weekday
    
    random.seed(42)  # Deterministic
    
    for i in range(num_tours):
        day_idx = i % days
        days_enum = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY]
        day_enum = days_enum[day_idx]
        
        start_min = random.randint(300, 960)  # 5am to 4pm
        duration = random.randint(120, 480)  # 2h to 8h
        end_min = start_min + duration
        
        # Convert min to time
        start_h, start_m = divmod(start_min, 60)
        s_time = time(start_h, start_m)
        
        end_real_min = end_min % 1440
        end_h, end_m = divmod(end_real_min, 60)
        e_time = time(end_h, end_m)
        
        t = Tour(
            id=f"T_{i:03d}",
            day=day_enum,
            start_time=s_time,
            end_time=e_time,
            location="ZoneA",
            required_qualifications=[]
        )
        tours.append(t)
    return tours


if __name__ == "__main__":
    main()
