import os
import json
import time
import glob

def monitor():
    # Find latest run dir
    base_dir = r"C:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\backend_py\artifacts\v2_shadow"
    all_dirs = sorted(glob.glob(os.path.join(base_dir, "kw51_*")))
    if not all_dirs:
        print("No run directories found.")
        return
        
    latest_dir = all_dirs[-1]
    print(f"Monitoring: {os.path.basename(latest_dir)}")
    
    seen_iters = set()
    
    print(f"{'Iter':<5} | {'LP Obj':<10} | {'Duals':<8} | {'Incumbent':<10} | {'MIP Status':<12} | {'Cols':<6} | {'Added':<6}")
    print("-" * 80)
    
    while True:
        # scan for json files
        files = glob.glob(os.path.join(latest_dir, "snapshot_cg_iter_*.json"))
        files.sort(key=lambda x: int(os.path.basename(x).split('_')[3].split('.')[0]))
        
        for f in files:
            iter_num = int(os.path.basename(f).split('_')[3].split('.')[0])
            if iter_num not in seen_iters:
                try:
                    with open(f, 'r') as fp:
                        data = json.load(fp)
                        
                    lp_obj = data.get("lp_obj", 0.0)
                    duals = data.get("duals_source", "unk")
                    incumbent = data.get("incumbent_drivers", "-")
                    mip_status = data.get("mip_status", "-")
                    cols = data.get("new_cols", 0)
                    added = data.get("added_count", 0)
                    
                    print(f"{iter_num:<5} | {lp_obj:<10.2f} | {duals:<8} | {incumbent:<10} | {mip_status:<12} | {cols:<6} | {added:<6}")
                    seen_iters.add(iter_num)
                except Exception as e:
                    pass # incomplete file usually
                    
        time.sleep(5)

if __name__ == "__main__":
    monitor()
