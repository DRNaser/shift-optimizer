#!/usr/bin/env python3
"""Extract Stage 0 baseline metrics from Prometheus endpoint."""
import requests
from datetime import datetime

r = requests.get('http://127.0.0.1:8000/api/v1/metrics')
readyz = requests.get('http://127.0.0.1:8000/api/v1/readyz').json()

metrics = {}
for line in r.text.split('\n'):
    if line.startswith('#') or not line.strip():
        continue
    if ' ' in line:
        parts = line.rsplit(' ', 1)
        metrics[parts[0]] = float(parts[1])

# Extract key metrics
runs = metrics.get('solver_signature_runs_total', 0)
overrun = metrics.get('solver_budget_overrun_total{phase="total"}', 0)
infeasible = metrics.get('solver_infeasible_total', 0)
kept_1er = metrics.get('solver_candidates_kept_total{size="1er"}', 0)
kept_2er = metrics.get('solver_candidates_kept_total{size="2er"}', 0)
kept_3er = metrics.get('solver_candidates_kept_total{size="3er"}', 0)

# Path selection
path_fast = metrics.get('solver_path_selection_total{path="FAST"}', 0)
path_full = metrics.get('solver_path_selection_total{path="FULL"}', 0)
path_fallback = metrics.get('solver_path_selection_total{path="FALLBACK"}', 0)

# Calculate rates
overrun_rate = overrun / max(runs, 1)
infeasible_rate = infeasible / max(runs, 1)

print("=" * 60)
print("STAGE 0 BASELINE EXPORT")
print("=" * 60)
print(f"Timestamp: {datetime.now().isoformat()}")
print(f"git_commit: {readyz.get('git_commit', 'unknown')}")
print(f"app_version: {readyz.get('app_version', 'unknown')}")
print(f"ortools_version: {readyz.get('ortools_version', 'unknown')}")
print()
print("--- KPIs ---")
print(f"A) Run Count: {int(runs)}")
print(f"B) Budget Overrun Rate: {overrun_rate:.4f} ({int(overrun)}/{int(runs)})")
print(f"C) Infeasible Rate: {infeasible_rate:.4f} ({int(infeasible)}/{int(runs)})")
print()
print("--- Candidate Blocks (cumulative) ---")
print(f"   1er kept: {int(kept_1er):,}")
print(f"   2er kept: {int(kept_2er):,}")
print(f"   3er kept: {int(kept_3er):,}")
print(f"D) Starvation Check: kept_2er > 0 = {kept_2er > 0} ({'NO STARVATION' if kept_2er > 0 else 'STARVATION DETECTED'})")
print()
print("--- Path Selection ---")
print(f"E) FAST: {int(path_fast)}")
print(f"   FULL: {int(path_full)}")
print(f"   FALLBACK: {int(path_fallback)}")
print()
print("--- Configuration ---")
print("   Stage: 0 (Flags OFF)")
print("   cap_quota_2er: NOT ACTIVE")
print("=" * 60)
