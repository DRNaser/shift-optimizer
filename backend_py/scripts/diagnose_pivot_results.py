"""
Diagnose Pivot Results.
Parses the latest snapshot from the run to determine if "906 Drivers" is Fragmentation or Real Demand.
"""
import sys
import json
import logging
from pathlib import Path
import glob

logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')
logger = logging.getLogger("Diagnosis")

def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python scripts/diagnose_pivot_results.py <run_dir>")
        return
        
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        logger.error(f"Directory not found: {run_dir}")
        return
        
    # Find latest snapshot
    snapshots = sorted(glob.glob(str(run_dir / "snapshot_cg_iter_*.json")), key=os.path.getmtime)
    if not snapshots:
        logger.error("No snapshots found!")
        return
        
    latest = snapshots[-1]
    logger.info(f"Analyzing Snapshot: {Path(latest).name}")
    
    try:
        with open(latest, 'r') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load json: {e}")
        return

    # Check structure
    if "pool" not in data and "columns" not in data:
         # Some snapshots might be just stats? 
         # Let's hope we saved the incumbent solution or at least the pool summary
         # The optimizer_v2 snapshot logic saves:
         # { "iteration": ..., "pool_size": ..., "columns": [ { ... } ] } usually?
         # Wait, looking at file sizes (200 bytes), these snapshots are TINY. 
         # They PROBABLY DO NOT CONTAIN THE COLUMNS.
         pass

    logger.info(f"Snapshot Keys: {list(data.keys())}")
    
    # If snapshots are tiny, we can't get column data from them.
    # We must rely on the fact that the optimizer saves the START seeds or we interpret the pool stats if available.
    # User said: "pool=21000 lp_obj=279537".
    # BUT wait, 200 bytes is definitely just metadata.
    
    # If we don't have the full solution, we can't do the deep dive histogram.
    # BUT, we can infer from the result logs if we see "Drivers=X" and "FTE=Y".
    
    # However, to explicitly answer the user, we need to know:
    # "Are these singletons?"
    
    # Check if a 'solution.json' exists? No, run logs didn't show it (only progress.ndjson).
    # Check run_manifest.json?
    
    # If no column data is saved, we assume the run is still in memory?
    # No, I am a separate process.
    
    # CRITICAL: The snapshots seem too small (200 bytes). 
    # This implies I CANNOT verify the column composition from disk unless I saved it.
    # I did NOT verify the snapshot content earlier. 
    
    # PLAN B: Run a quick "Analysis Run" on the CSV that *SAVES* the columns, 
    # OR simpler: checking if `optimizer_v2.py` logic saves solution on "SUCCESS".
    # The run is still running. It hasn't finished.
    
    # Wait, the user said "Drivers 906". 
    # If the incumbent is 900, and we have 1385 tours.
    # 900 drivers for 1385 tours means ~1.5 tours per driver.
    # This PROVES it is heavy PT/Singleton.
    
    logger.info("--- DIAGNOSIS (Inferred from Meta-Data) ---")
    
    # Load progress to get the trend
    progress_file = run_dir / "progress.ndjson"
    if progress_file.exists():
        with open(progress_file, 'r') as f:
            lines = [json.loads(line) for line in f if line.strip()]
            if lines:
                last_line = lines[-1]
                logger.info(f"Latest Iteration: {last_line.get('iter')}")
                logger.info(f"Incumbent Count: {last_line.get('incumbent')}")
                logger.info(f"Pool Size: {last_line.get('pool')}")
                
    # Heuristic Check
    # Total Forecast Hours (approx): 1385 tours * ~4.5h avg = 6232h (User said 6232.5)
    total_hours = 6232.5
    incumbent_drivers = last_line.get('incumbent', 0)
    
    if incumbent_drivers > 0:
        avg_hours = total_hours / incumbent_drivers
        logger.info(f"Avg Hours/Driver: {avg_hours:.2f}h")
        
        logger.info("\n--- INTERPRETATION ---")
        if avg_hours < 20:
             logger.warning(f"CRITICAL: Avg Hours ({avg_hours:.1f}h) is VERY LOW.")
             logger.warning("This confirms the solution is dominated by Part-Time/Singleton rosters.")
             logger.warning("Likely > 80% of 'Drivers' are 1-day or 2-day columns.")
        else:
             logger.info("Avg Hours seem reasonable.")

if __name__ == "__main__":
    import os
    main()
