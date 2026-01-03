"""
Quick Test Script for Hard Iteration Logging & Snapshot Verification
Supports both .txt (tab-delimited) and .csv (semicolon-delimited) formats
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2

def parse_forecast_file(filepath: str) -> list:
    """Parse German forecast file (supports .txt with tabs or .csv with semicolons)."""
    DAY_MAP = {
        "Montag": 0, "Dienstag": 1, "Mittwoch": 2, "Donnerstag": 3,
        "Freitag": 4, "Samstag": 5, "Sonntag": 6,
    }
    
    # Auto-detect delimiter based on file extension
    delimiter = ';' if filepath.endswith('.csv') else '\t'
    
    tours = []
    current_day = None
    tour_id_counter = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(delimiter)
            day_name = parts[0].strip()
            
            if day_name in DAY_MAP:
                current_day = DAY_MAP[day_name]
                continue
            
            if current_day is None:
                continue
            
            if len(parts) != 2:
                continue
            
            time_range = parts[0].strip()
            try:
                count = int(parts[1].strip())
            except ValueError:
                continue
            
            if '-' not in time_range:
                continue
            
            start_str, end_str = time_range.split('-')
            start_h, start_m = map(int, start_str.split(':'))
            end_h, end_m = map(int, end_str.split(':'))
            
            start_min = start_h * 60 + start_m
            end_min = end_h * 60 + end_m
            duration_min = end_min - start_min
            
            for i in range(count):
                tour = TourV2(
                    tour_id=f"T_{current_day}_{tour_id_counter:04d}",
                    day=current_day,
                    start_min=start_min,
                    end_min=end_min,
                    duration_min=duration_min
                )
                tours.append(tour)
                tour_id_counter += 1
    
    return tours


if __name__ == "__main__":
    print("="*80)
    print("HARD ITERATION LOGGING & SNAPSHOT TEST")
    print("="*80)
    print()
    
    # Try CSV first, then fallback to TXT
    test_file = Path(__file__).parent.parent / "forecast_test.csv"
    if not test_file.exists():
        test_file = Path(__file__).parent.parent / "forecast-test.txt"
    
    if not test_file.exists():
        print(f"[X] No test file found!")
        sys.exit(1)
    
    print(f"[*] Loading test data from: {test_file}")
    tours = parse_forecast_file(str(test_file))
    print(f"[OK] Loaded {len(tours)} tours")
    print()
    
    tours_by_day = {}
    for t in tours:
        tours_by_day.setdefault(t.day, []).append(t)
    
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in sorted(tours_by_day.keys()):
        print(f"   Day {day} ({day_names[day]}): {len(tours_by_day[day])} tours")
    print()
    
    artifacts_dir = Path(__file__).parent / "test_artifacts"
    
    config = {
        "artifacts_dir": str(artifacts_dir),
        "max_cg_iterations": 25,  # Full optimization run
        "lp_time_limit": 30.0,
        "restricted_mip_time_limit": 5.0,
        "mip_time_limit": 120.0,  # 2 min for final MIP
        "target_seed_columns": 1000,
        "pricing_time_limit_sec": 5.0,
        "duty_caps": {
            "max_multi_duties_per_day": 8000,
            "top_m_start_tours": 200,
            "max_succ_per_tour": 25,
            "max_triples_per_tour": 5,
        },
    }
    
    print("[*] Starting optimizer with TEST configuration:")
    print(f"   - Iterations: {config['max_cg_iterations']}")
    print(f"   - Artifacts: {artifacts_dir}")
    print()
    print("-"*80)
    print()
    
    optimizer = OptimizerCoreV2()
    result = optimizer.solve(tours, config, run_id="test_hard_logging")
    
    print()
    print("-"*80)
    print()
    print("[*] VERIFICATION RESULTS:")
    print()
    
    checks = []
    
    if artifacts_dir.exists():
        checks.append(("[OK]", "Artifact directory created"))
    else:
        checks.append(("[X]", "Artifact directory missing"))
    
    manifest_file = artifacts_dir / "run_manifest.json"
    if manifest_file.exists():
        checks.append(("[OK]", "run_manifest.json exists"))
    else:
        checks.append(("[X]", "run_manifest.json missing"))
    
    progress_file = artifacts_dir / "progress.ndjson"
    if progress_file.exists():
        try:
            with open(progress_file, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
            iter_count = len(lines)
            checks.append(("[OK]", f"progress.ndjson with {iter_count} lines (NDJSON format)"))
            
            # Validate NDJSON format (each line should be valid JSON)
            print("   Sample progress entries (NDJSON format):")
            for idx, line in enumerate(lines[:2], 1):  # Show first 2
                try:
                    entry = json.loads(line)
                    print(f"   Line {idx}: ITER={entry.get('iter')} pool={entry.get('pool')} lp_obj={entry.get('lp_obj')} incumbent={entry.get('incumbent')}")
                except json.JSONDecodeError as e:
                    print(f"   Line {idx}: INVALID JSON - {e}")
            print()
        except Exception as e:
            checks.append(("[X]", f"progress.ndjson invalid: {e}"))
    else:
        checks.append(("[X]", "progress.ndjson missing"))
    
    snapshots = list(artifacts_dir.glob("snapshot_cg_iter_*.json"))
    if snapshots:
        checks.append(("[OK]", f"Snapshots created ({len(snapshots)} files)"))
        print(f"   Snapshot intervals: {sorted([int(s.stem.split('_')[-1]) for s in snapshots])}")
        for snap in sorted(snapshots)[:3]:
            print(f"   [SNAP] {snap.name}")
            try:
                with open(snap, 'r') as f:
                    snap_data = json.load(f)
                print(f"      Iteration: {snap_data.get('iteration')}")
                print(f"      LP Obj: {snap_data.get('lp_objective', 0):.2f}")
                print(f"      Pool: {snap_data.get('pool_size')}")
                print(f"      Incumbent: {snap_data.get('incumbent_drivers')}")
            except Exception as e:
                print(f"      [X] Error: {e}")
        print()
    else:
        checks.append(("[X]", "No snapshots found"))
    
    print()
    print("[*] CHECKLIST:")
    for status, desc in checks:
        print(f"{status} {desc}")
    
    print()
    print("="*80)
    print("RESULT:", result.status)
    if result.status == "SUCCESS":
        print(f"Drivers: {result.kpis.get('drivers_total', 'N/A')}")
        print(f"MIP Obj: {result.kpis.get('mip_obj', 'N/A'):.2f}")
    else:
        print(f"Error: {result.error_message}")
    print("="*80)
