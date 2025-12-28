#!/usr/bin/env python3
"""
experiment_tracking.py
A/B compare v7.0.0-freeze vs v7.1.0 candidate across seeds (and optionally multiple forecasts).

Usage:
  python experiment_tracking.py \
    --baseline-ref v7.0.0-freeze \
    --candidate-ref feature/meta-learning \
    --time-budget 120 \
    --seeds 0-9 \
    --out artifacts/ab_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

ROSTER_CSV_REL = Path("backend_py") / "roster_matrix.csv"
EPS_HOURS = 0.01
FLEX_MAX_HOURS_DEFAULT = 13.5

def run(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout

def ensure_clean_worktree(base_dir: Path, name: str, ref: str) -> Path:
    wt_dir = base_dir / name
    if wt_dir.exists():
        # remove existing worktree
        run(["git", "worktree", "remove", "--force", str(wt_dir)])
    code, out = run(["git", "worktree", "add", str(wt_dir), ref])
    if code != 0:
        raise RuntimeError(f"Failed to create worktree {name} for {ref}:\n{out}")
    return wt_dir

def parse_hours_de(hours_str: str) -> float:
    # "49,50" -> 49.50
    s = hours_str.strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")  # safe for your format
    try:
        return float(s)
    except ValueError:
        return 0.0

@dataclass
class Metrics:
    drivers_raw: int
    drivers_ghost: int
    drivers_active: int
    fte_active: int
    pt_active: int
    pt_core_active: int
    pt_flex_active: int
    hours_total: float
    hours_pt_core: float
    core_pt_share_hours: float
    runtime_s: float
    roster_hash: str

def file_hash(path: Path) -> str:
    # use blake3 if available, else sha256
    data = path.read_bytes()
    try:
        from blake3 import blake3  # type: ignore
        return blake3(data).hexdigest()
    except Exception:
        import hashlib
        return hashlib.sha256(data).hexdigest()

def compute_metrics_from_roster_csv(csv_path: Path, flex_max_hours: float) -> Tuple[Metrics, List[str]]:
    ghosts: List[str] = []
    drivers_raw = 0
    drivers_active = 0
    fte_active = 0
    pt_active = 0
    pt_core_active = 0
    pt_flex_active = 0
    hours_total = 0.0
    hours_pt_core = 0.0

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            drivers_raw += 1
            driver_id = (row.get("Driver ID") or "").strip()
            dtype = (row.get("Type") or "").strip()
            h = parse_hours_de(row.get("Weekly Hours", "") or "")
            worked_days = 0
            for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
                if (row.get(d) or "").strip():
                    worked_days += 1

            is_ghost = (h <= EPS_HOURS) or (worked_days == 0)
            if is_ghost:
                ghosts.append(driver_id or f"row{drivers_raw}")
                continue

            drivers_active += 1
            hours_total += h

            if dtype.upper() == "FTE":
                fte_active += 1
            elif dtype.upper() == "PT":
                pt_active += 1
                if h <= flex_max_hours + EPS_HOURS:
                    pt_flex_active += 1
                else:
                    pt_core_active += 1
                    hours_pt_core += h
            else:
                # unknown type -> treat as active but don't classify
                pass

    drivers_ghost = len(ghosts)
    core_share = (hours_pt_core / hours_total) if hours_total > 0 else 0.0

    m = Metrics(
        drivers_raw=drivers_raw,
        drivers_ghost=drivers_ghost,
        drivers_active=drivers_active,
        fte_active=fte_active,
        pt_active=pt_active,
        pt_core_active=pt_core_active,
        pt_flex_active=pt_flex_active,
        hours_total=hours_total,
        hours_pt_core=hours_pt_core,
        core_pt_share_hours=core_share,
        runtime_s=0.0,  # filled later
        roster_hash=file_hash(csv_path),
    )
    return m, ghosts

def run_one(worktree: Path, time_budget: int, seed: int) -> Tuple[Path, float, str]:
    t0 = time.time()
    cmd = [sys.executable, "backend_py/export_roster_matrix.py", "--time-budget", str(time_budget), "--seed", str(seed)]
    code, out = run(cmd, cwd=worktree)
    t1 = time.time()
    if code != 0:
        raise RuntimeError(f"Run failed in {worktree.name} seed={seed}:\n{out}")
    roster_csv = worktree / ROSTER_CSV_REL
    if not roster_csv.exists():
        raise FileNotFoundError(f"Expected roster CSV not found: {roster_csv}")
    return roster_csv, (t1 - t0), out

def compare(b: Metrics, c: Metrics) -> Dict[str, float]:
    return {
        "drivers_active_delta": c.drivers_active - b.drivers_active,
        "core_pt_share_hours_delta": c.core_pt_share_hours - b.core_pt_share_hours,
        "runtime_delta_s": c.runtime_s - b.runtime_s,
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-ref", default="v7.0.0-freeze")
    ap.add_argument("--candidate-ref", required=True)
    ap.add_argument("--time-budget", type=int, default=120)
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--flex-max-hours", type=float, default=FLEX_MAX_HOURS_DEFAULT)
    ap.add_argument("--out", default="artifacts/ab_report.json")
    args = ap.parse_args()

    # parse seeds
    seeds: List[int] = []
    s = args.seeds.strip()
    if "-" in s:
        a, b = s.split("-", 1)
        seeds = list(range(int(a), int(b) + 1))
    else:
        seeds = [int(x) for x in s.split(",") if x.strip()]

    base_dir = Path(".worktrees")
    base_dir.mkdir(exist_ok=True)

    baseline_wt = ensure_clean_worktree(base_dir, "baseline", args.baseline_ref)
    candidate_wt = ensure_clean_worktree(base_dir, "candidate", args.candidate_ref)

    results = {
        "baseline_ref": args.baseline_ref,
        "candidate_ref": args.candidate_ref,
        "time_budget": args.time_budget,
        "flex_max_hours": args.flex_max_hours,
        "seeds": seeds,
        "runs": [],
    }

    # A/B runs
    for seed in seeds:
        # baseline
        b_csv, b_rt, _ = run_one(baseline_wt, args.time_budget, seed)
        b_metrics, b_ghosts = compute_metrics_from_roster_csv(b_csv, args.flex_max_hours)
        b_metrics.runtime_s = b_rt

        # candidate
        c_csv, c_rt, _ = run_one(candidate_wt, args.time_budget, seed)
        c_metrics, c_ghosts = compute_metrics_from_roster_csv(c_csv, args.flex_max_hours)
        c_metrics.runtime_s = c_rt

        results["runs"].append({
            "seed": seed,
            "baseline": b_metrics.__dict__,
            "candidate": c_metrics.__dict__,
            "delta": compare(b_metrics, c_metrics),
            "baseline_ghosts": b_ghosts,
            "candidate_ghosts": c_ghosts,
            "determinism": {
                "baseline_roster_hash": b_metrics.roster_hash,
                "candidate_roster_hash": c_metrics.roster_hash,
                "baseline_equals_candidate_hash": (b_metrics.roster_hash == c_metrics.roster_hash),
            }
        })

        print(
            f"seed={seed} | "
            f"base active={b_metrics.drivers_active} corePT%={b_metrics.core_pt_share_hours:.3f} rt={b_metrics.runtime_s:.1f}s | "
            f"cand active={c_metrics.drivers_active} corePT%={c_metrics.core_pt_share_hours:.3f} rt={c_metrics.runtime_s:.1f}s"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote report: {out_path}")

if __name__ == "__main__":
    main()
