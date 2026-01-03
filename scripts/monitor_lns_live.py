
import os
import json
import glob
import time
from pathlib import Path

BASE_DIR = Path(r"C:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\backend_py\artifacts\v2_shadow")

def get_latest_run_dir():
    dirs = glob.glob(str(BASE_DIR / "kw51_*"))
    if not dirs:
        return None
    return max(dirs, key=os.path.getmtime)

def monitor():
    run_dir = get_latest_run_dir()
    if not run_dir:
        print("No run directory found.")
        return

    print(f"Monitoring LNS in: {run_dir}")
    print("-" * 60)
    print(f"{'Iter':<5} | {'Mode':<12} | {'Frac':<5} | {'Status':<10} | {'Drivers':<10} | {'Time':<5}")
    print("-" * 60)
    
    seen_iters = set()
    
    while True:
        files = glob.glob(os.path.join(run_dir, "snapshot_lns_iter_*.json"))
        files.sort(key=lambda x: int(os.path.basename(x).split('_')[-1].split('.')[0]))
        
        for f in files:
            fname = os.path.basename(f)
            if fname in seen_iters:
                continue
                
            try:
                with open(f, 'r') as fh:
                    data = json.load(fh)
                    
                i = data.get("iter", "?")
                mode = data.get("mode", "?")
                frac = data.get("frac", "?")
                status = data.get("status", "?")
                d_new = data.get("drivers_new", "N/A")
                d_old = "N/A" # Need to track best or infer?
                t = f"{data.get('time', 0):.1f}s"
                
                print(f"{i:<5} | {mode:<12} | {frac:<5} | {status:<10} | {d_new:<10} | {t:<5}")
                seen_iters.add(fname)
            except Exception as e:
                print(f"Error reading {fname}: {e}")
                
        time.sleep(5)

if __name__ == "__main__":
    monitor()
