import subprocess
import json
import statistics
import time
from pathlib import Path

SEEDS = [0, 1, 2, 3, 4]
CMD = ["python", "pt_balance_quality_gate.py", "--input", "forecast-test.txt", "--time-budget", "120"]

def run_seed(seed):
    print(f"\n>>> RUNNING SEED {seed} <<<")
    cmd = CMD + ["--seed", str(seed)]
    if seed == 0:
        # We already updated baseline separately, or we can do it here. 
        # But let's just run standard validation against the baseline we just froze.
        pass
        
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start
    
    print(f"Seed {seed} finished in {duration:.1f}s with code {result.returncode}")
    
    # Extract JSON report
    report_path = Path("artifacts/kpi_report.json")
    if report_path.exists():
        data = json.loads(report_path.read_text())
        return data
    else:
        print("ERROR: No report found")
        print(result.stdout)
        print(result.stderr)
        return None

results = []
for s in SEEDS:
    res = run_seed(s)
    if res:
        results.append(res)

print("\n" + "="*60)
print("ROBUSTNESS SUMMARY (Drivers < 165, PT < 15%)")
print("="*60)

results_data = [r['kpis'] for r in results]
drivers = [k.get('drivers_total', 0) for k in results_data]
pt_shares = [(k.get('pt_share_hours') or 0.0) * 100 for k in results_data]

print(f"Seeds: {SEEDS}")
print(f"Drivers: {drivers}")
if drivers:
    print(f"  Mean: {statistics.mean(drivers):.1f}")
    print(f"  Min:  {min(drivers)}")
    print(f"  Max:  {max(drivers)}")
    if len(drivers) > 1:
        print(f"  Std:  {statistics.stdev(drivers):.2f}")

print(f"PT Share: {pt_shares}")
if pt_shares:
    print(f"  Mean: {statistics.mean(pt_shares):.1f}%")
pass_cnt = sum(1 for k in results_data if k.get('drivers_total', 0) <= 165 and (k.get('pt_share_hours') or 0.0) <= 0.15)
print(f"\nPASS RATE: {pass_cnt}/{len(SEEDS)}")
