
import logging
import sys
import os
from pathlib import Path

# Add backend_py to path
base_dir = Path(__file__).resolve().parent.parent / "backend_py"
sys.path.append(str(base_dir))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.run.manifest import RunContext
from src.core_v2.model.column import ColumnV2
from src.core_v2.model.duty import DutyV2
from src.core_v2.pool.store import ColumnPoolStore
from src.core_v2.contracts.result import CoreV2Result
from dataclasses import dataclass
from unittest.mock import MagicMock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LNS_TEST")

def test_lns():
    # 1. Setup Mock Pool
    pool = ColumnPoolStore()
    columns = []
    
    # Tours T0..T9
    for i in range(10):
        # Create Singleton
        d = MagicMock(spec=DutyV2)
        d.tour_ids = {f"T{i}"}
        d.days_worked = {0}
        d.day = 0
        d.work_min = 480
        d.start_min = 480
        d.end_min = 960
        d.duty_id = f"D_S_{i}"
        
        c = ColumnV2(
            duties=[d],
            col_id=f"C_S_{i}",
            covered_tour_ids={f"T{i}"},
            total_work_min=480,
            days_worked={0},
            max_day_span_min=480,
            origin="test",
            hours=8.0,
            is_under_30h=True,
            is_under_20h=True,
            is_singleton=True
        )
        pool.add(c)
        columns.append(c)
        
    # Create Pairs (T0+T1, T2+T3, ...)
    pairs = []
    for i in range(0, 10, 2):
        d = MagicMock(spec=DutyV2)
        d.tour_ids = {f"T{i}", f"T{i+1}"}
        d.days_worked = {0}
        d.day = 0
        d.work_min = 480
        d.start_min = 480
        d.end_min = 960
        d.duty_id = f"D_P_{i}"
        
        c = ColumnV2(
            duties=[d],
            col_id=f"C_P_{i}",
            covered_tour_ids={f"T{i}", f"T{i+1}"},
            total_work_min=960,
            days_worked={0},
            max_day_span_min=480,
            origin="test",
            hours=16.0,
            is_under_30h=True,
            is_under_20h=True,
            is_singleton=False
        )
        
        pool.add(c)
        columns.append(c) # Indices 10..14
        pairs.append(c)

    # 2. Setup Incumbent (The 10 Singletons)
    # This is a bad solution (10 drivers).
    # LNS should find the 5 Pairs (5 drivers).
    incumbent = columns[:10] 
    
    optimizer = OptimizerCoreV2()
    
    # Mock Context
    ctx = MagicMock()
    ctx.manifest.run_id = "test_run"
    ctx.manifest.week_category.name = "NORMAL"
    ctx.manifest.active_days_count = 5
    ctx.artifact_dir = "./test_artifacts"
    ctx.save_snapshot = MagicMock()
    
    # Config
    config = {
        "lns_iterations": 5,
        "lns_iter_time_limit_s": 5,
        "lns_destroy_frac_schedule": [0.5], # Destroy 50%
    }
    
    def log_fn(msg):
        print(msg)
        
    print(f"Pool Size: {pool.size}")
    print(f"Incumbent Size: {len(incumbent)}")
    
    # 3. Run LNS
    best_cols = optimizer._run_lns_phase(ctx, pool, incumbent, log_fn, config)
    
    print(f"Best LNS Size: {len(best_cols)}")
    
    # 4. Verify
    if len(best_cols) < len(incumbent):
        print("PASS: LNS improved solution")
    else:
        print("FAIL: LNS did not improve")
        
    # Verify strict coverage of T0..T9
    covered = set()
    for c in best_cols:
        covered.update(c.covered_tour_ids)
    
    assert len(covered) == 10, f"Coverage check failed: {len(covered)}/10"
    print("PASS: Coverage valid")

if __name__ == "__main__":
    try:
        test_lns()
    except Exception as e:
        logger.exception("Test Failed")
        sys.exit(1)
