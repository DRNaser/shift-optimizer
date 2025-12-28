#!/usr/bin/env python3
"""
validate_promotion_gates.py
Automated gate checker for v7.1.0 promotion from ab_report.json

Usage:
  python validate_promotion_gates.py artifacts/ab_report.json
  
Exit codes:
  0 = All gates PASS
  1 = One or more gates FAIL
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

GATES = {
    "core_pt_share_hours": {
        "name": "Core PT Share (Maintain or Improve)",
        "check": lambda b, c: c <= b,
        "critical": True,
    },
    "runtime_s": {
        "name": "Runtime (≤ baseline + 5%)",
        "check": lambda b, c: c <= b * 1.05,
        "critical": True,
    },
    "drivers_active": {
        "name": "Active Drivers (Within ±3)",
        "check": lambda b, c: abs(c - b) <= 3,
        "critical": False,
    },
}

def check_gates(report: Dict[str, Any]) -> bool:
    """Check all promotion gates. Returns True if all critical gates pass."""
    
    runs = report.get("runs", [])
    if not runs:
        print("❌ No runs found in report")
        return False
    
    all_critical_pass = True
    gate_results: Dict[str, List[bool]] = {k: [] for k in GATES}
    
    print("=" * 70)
    print("PROMOTION GATE VALIDATION")
    print("=" * 70)
    print(f"Baseline: {report['baseline_ref']}")
    print(f"Candidate: {report['candidate_ref']}")
    print(f"Seeds: {report['seeds']}")
    print()
    
    # Check each run
    for run in runs:
        seed = run["seed"]
        baseline = run["baseline"]
        candidate = run["candidate"]
        
        print(f"Seed {seed}:")
        for gate_key, gate_def in GATES.items():
            b_val = baseline.get(gate_key, 0)
            c_val = candidate.get(gate_key, 0)
            passed = gate_def["check"](b_val, c_val)
            gate_results[gate_key].append(passed)
            
            status = "✅" if passed else "❌"
            critical_mark = "(CRITICAL)" if gate_def["critical"] else ""
            
            if gate_key == "runtime_s":
                delta_pct = ((c_val - b_val) / b_val * 100) if b_val > 0 else 0
                print(f"  {status} {gate_def['name']} {critical_mark}: {b_val:.1f}s → {c_val:.1f}s ({delta_pct:+.1f}%)")
            elif gate_key == "core_pt_share_hours":
                b_pct = b_val * 100
                c_pct = c_val * 100
                delta_pct = c_pct - b_pct
                print(f"  {status} {gate_def['name']} {critical_mark}: {b_pct:.2f}% → {c_pct:.2f}% ({delta_pct:+.2f}pp)")
            else:
                print(f"  {status} {gate_def['name']} {critical_mark}: {b_val} → {c_val}")
            
            if gate_def["critical"] and not passed:
                all_critical_pass = False
        print()
    
    # Summary
    print("=" * 70)
    print("GATE SUMMARY")
    print("=" * 70)
    
    for gate_key, gate_def in GATES.items():
        results = gate_results[gate_key]
        pass_count = sum(results)
        total = len(results)
        pass_rate = (pass_count / total * 100) if total > 0 else 0
        
        all_pass = all(results)
        status = "✅ PASS" if all_pass else "❌ FAIL"
        critical_mark = "(CRITICAL)" if gate_def["critical"] else ""
        
        print(f"{status} {critical_mark} {gate_def['name']}: {pass_count}/{total} seeds ({pass_rate:.0f}%)")
    
    print()
    print("=" * 70)
    if all_critical_pass:
        print("✅ PROMOTION APPROVED: All critical gates passed")
        print("=" * 70)
        return True
    else:
        print("❌ PROMOTION BLOCKED: One or more critical gates failed")
        print("=" * 70)
        return False

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path, help="Path to ab_report.json")
    args = ap.parse_args()
    
    if not args.report.exists():
        print(f"❌ Report not found: {args.report}")
        return 1
    
    report = json.loads(args.report.read_text(encoding="utf-8"))
    
    if check_gates(report):
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())
