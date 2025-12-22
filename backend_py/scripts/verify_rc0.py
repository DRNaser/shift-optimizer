#!/usr/bin/env python3
"""
RC0 Verification Script - QUALITY-FIRST Reproducible Run
=========================================================
Executes a full reproducible run with QUALITY profile and validates output.
Use this as a single-command RC check.

PREREQUISITES:
    1. Start the API server FIRST:
       ```
       cd backend_py
       uvicorn src.main:app --host 0.0.0.0 --port 8000
       ```
    2. Then run this script in a separate terminal:
       ```
       python scripts/verify_rc0.py
       ```

QUALITY PROFILE:
- Time budget: 3600s+ (Unbounded Intention) - Resource window, not hard limit
- pass2_min_time_s: 30s - Guaranteed Pass-2 execution
- Deterministic: seed=42, num_workers=1
- Two-Pass: twopass_executed must be True

Usage:
    python scripts/verify_rc0.py [--quick]     # Quick mode: 120s budget (CI)
    python scripts/verify_rc0.py               # Quality mode: Unbounded/3600s (Release)

Outputs:
    - diag_run_result.json
    - artifacts/rc0/weekly_plan.json (golden output)
    - artifacts/rc0/validation.json
    - artifacts/rc0/README.md
"""
import subprocess
import json
import sys
import os
import shutil
import re
from datetime import datetime
from pathlib import Path
import requests

# Configuration
API_PORT = int(os.environ.get("API_PORT", 8000))
API_URL = f"http://localhost:{API_PORT}/api/v1"
QUALITY_TIME_BUDGET = int(os.environ.get("QUALITY_TIME_BUDGET", 3600))  # 1 hour default, overridable
QUICK_TIME_BUDGET = 120     # CI mode
PASS2_MIN_TIME_S = 30.0     # Guaranteed Pass-2 time
OUTPUT_PROFILE = "BEST_BALANCED"
RESULT_FILE = "diag_run_result.json"
DIAG_SCRIPT = "scripts/diagnostic_run.py"
VALIDATE_SCRIPT = "scripts/validate_schedule.py"
ARTIFACTS_DIR = "artifacts/rc0"

# Expected KPI ranges (QUALITY targets)
EXPECTED_COVERAGE = 1.0
EXPECTED_DRIVERS_MIN = 155
EXPECTED_DRIVERS_MAX = 185
EXPECTED_VIOLATIONS = 0


def check_api_server():
    """Check if API server is running on STRICTLY the configured port."""
    # Method 1: API Endpoint
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        if resp.status_code == 200:
            return True
    except:
        pass

    # Method 2: Root Health (some deploys use /health on same port)
    try:
        resp = requests.get(f"http://localhost:{API_PORT}/health", timeout=5)
        if resp.status_code == 200:
            return True
    except:
        pass
        
    return False


def run_cmd(cmd, capture=True):
    """Run a command and return result."""
    print(f"Running: {' '.join(cmd)}")
    # If capture is False, stdout/stderr go to parent (console)
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        result = subprocess.run(cmd, text=True)
    return result


def ensure_artifacts_dir():
    """Create artifacts directory if needed."""
    path = Path(ARTIFACTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def main():
    # Parse args
    quick_mode = "--quick" in sys.argv
    time_budget = QUICK_TIME_BUDGET if quick_mode else QUALITY_TIME_BUDGET
    mode_name = "QUICK" if quick_mode else "QUALITY"
    
    print("=" * 70)
    print(f"ShiftOptimizer v2.0.0-rc0 Verification ({mode_name} MODE)")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    budget_label = "Unbounded Intent"
    if quick_mode:
        budget_label = "CI Mode"
    elif time_budget < 3600:
        budget_label = f"Quality (Custom Budget)"
        
    print(f"Time Budget: {time_budget}s ({budget_label})")
    print(f"Pass-2 Min Time: {PASS2_MIN_TIME_S}s (guaranteed)")
    print(f"Output Profile: {OUTPUT_PROFILE}")
    print(f"Seed: 42 (deterministic)")
    print(f"Target Port: {API_PORT}")
    print()
    
    # Ensure we're in backend_py
    if not os.path.exists("src") and os.path.exists("../src"):
        os.chdir("..")
    
    # PRE-FLIGHT CHECK: API Server STRICT
    print(f"[0/5] Checking API server on port {API_PORT}...")
    if not check_api_server():
        print()
        print("=" * 70)
        print(f"ERROR: API server not accessible on port {API_PORT}!")
        print("=" * 70)
        print()
        print("Possible causes:")
        print(f"1. Server not started or crashed.")
        print(f"2. Server running on different port (configure via API_PORT).")
        print()
        print("To start correctly:")
        print(f"  uvicorn src.main:app --host 0.0.0.0 --port {API_PORT}")
        print()
        return 1
    print("  API server: OK")
    print()
    
    # Step 1: Run diagnostic
    print(f"[1/5] Running solver ({mode_name} profile)...")
    cmd = [
        sys.executable, DIAG_SCRIPT,
        "--time_budget", str(time_budget),
        "--output_profile", OUTPUT_PROFILE,
        "--pass2_min_time_s", str(PASS2_MIN_TIME_S)
    ]
    # Use capture=False so output streams to console
    result = run_cmd(cmd, capture=False)
    if result.returncode != 0:
        print(f"FAIL: Solver failed with exit code {result.returncode}")
        print(result.stderr)
        if "unrecognized arguments" in result.stderr and "--pass2_min_time_s" in result.stderr:
             print("\nCRITICAL: diagnostic_run.py does not support --pass2_min_time_s!")
             print("Please apply the diagnostic tool patch first.")
        return 1
    
    # Step 2: Load result
    print("[2/5] Loading result...")
    if not os.path.exists(RESULT_FILE):
        print(f"FAIL: Result file not found: {RESULT_FILE}")
        return 1
    
    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Step 3: Validating Contract - STRICT
    print("[3/5] Validating contract (schema_version, pause_zone)...")
    errors = []
    warnings = []
    
    # Check schema_version STRICT (No fallback logic permitted)
    schema_version = data.get("schema_version")
    if schema_version is None:
        errors.append("schema_version MISSING in root response")
    elif schema_version != "2.0":
        errors.append(f"schema_version mismatch: expected '2.0', got {repr(schema_version)}")
    
    # Check assignments presence
    assignments = data.get("assignments", [])
    if not assignments:
        errors.append("No assignments provided in output")
    
    # Check assignment/block shape robustly
    missing_pause_zone = 0
    invalid_pause_zone = 0
    split_blocks = 0
    
    for i, a in enumerate(assignments):
        # Normalize: find the actual block object(s)
        # Case A: assignment["block"] (standard)
        # Case B: assignment is the block (flat)
        # Case C: assignment["blocks"] (list)
        
        target_blocks = []
        if "blocks" in a and isinstance(a["blocks"], list):
            target_blocks = a["blocks"]
        elif "block" in a and isinstance(a["block"], dict):
            target_blocks = [a["block"]]
        else:
            # Assume flat structure
            target_blocks = [a]
            
        if not target_blocks:
             # Should rarely happen if assignment exists but block/blocks is empty?
             pass

        for block in target_blocks:
            # Handle case where block is just a string arg (defensive)
            if not isinstance(block, dict):
                continue
                
            pz = block.get("pause_zone")
            
            if pz is None:
                missing_pause_zone += 1
            elif pz == "SPLIT":
                split_blocks += 1
            elif pz == "REGULAR":
                pass
            else:
                invalid_pause_zone += 1
                
    if missing_pause_zone > 0:
        errors.append(f"{missing_pause_zone} blocks missing 'pause_zone' field")
    if invalid_pause_zone > 0:
        errors.append(f"{invalid_pause_zone} blocks have invalid value for 'pause_zone' (must be REGULAR/SPLIT)")
    
    # Check KPIs
    stats = data.get("stats", {})
    tours_assigned = stats.get("total_tours_assigned", 0)
    tours_input = stats.get("total_tours_input", 1)
    coverage = tours_assigned / max(tours_input, 1)
    
    if coverage < EXPECTED_COVERAGE:
        errors.append(f"Coverage: {coverage*100:.1f}% (expected 100%)")
    
    drivers = stats.get("total_drivers", 0)
    # Range check is a warning in Quality mode (we want minimum)
    if drivers < EXPECTED_DRIVERS_MIN or drivers > EXPECTED_DRIVERS_MAX:
        msg = f"Driver count {drivers} outside expected range {EXPECTED_DRIVERS_MIN}-{EXPECTED_DRIVERS_MAX}"
        if drivers < EXPECTED_DRIVERS_MIN:
            msg += " (POSITIVE: Below expected minimum!)"
        warnings.append(msg)
    
    # QUALITY-FIRST: twopass_executed MUST be True
    twopass = stats.get("twopass_executed")
    if twopass is not True:
        msg = f"twopass_executed={twopass}"
        if not quick_mode:
            errors.append(msg + " (MUST be True in QUALITY mode)")
        else:
            warnings.append(msg)
    
    # Step 4: Run validator (Robust Parsing)
    print("[4/5] Running validator...")
    cmd = [sys.executable, VALIDATE_SCRIPT, RESULT_FILE]
    val_res = run_cmd(cmd)
    validation_output = val_res.stdout
    
    validator_failed = False
    
    if val_res.returncode != 0:
        errors.append(f"Validator crashed (exit code {val_res.returncode})")
        validator_failed = True
    else:
        # Robust Regex Parsing for Status
        status_match = re.search(r"Status:\s*([A-Z_]+)(?:.*\[(.*?)\])?", validation_output)
        if status_match:
            status_code = status_match.group(1)
            if status_code not in ["VALID", "OK"]:
                errors.append(f"Validator Status: {status_code} (expected VALID)")
                validator_failed = True
        else:
             # Fallback warning if text changes, but exit code was 0
             warnings.append("Could not parse Validator Status string (Format change?)")
        
        # Robust Parsing for Violations
        # Pattern: "Zone Violations: <number>"
        zone_match = re.search(r"Zone Violations:\s*(\d+)", validation_output)
        if zone_match:
            z_count = int(zone_match.group(1))
            if z_count > 0:
                errors.append(f"Zone Violations: {z_count}")
                validator_failed = True
        else:
             # Only warn if we can't find it
             if "Zone Violations" in validation_output: # It's there but regex failed?
                 warnings.append("Could not parse Zone Violations count")
    
    # Step 5: Save artifacts
    print("[5/5] Saving golden artifacts...")
    artifacts_path = ensure_artifacts_dir()
    
    # 5a. Weekly Plan
    golden_plan = artifacts_path / "weekly_plan.json"
    shutil.copy(RESULT_FILE, golden_plan)
    
    # 5b. Validation JSON
    golden_validation = artifacts_path / "validation.json"
    validation_data = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode_name,
        "config": {
            "time_budget": time_budget,
            "pass2_min_time_s": PASS2_MIN_TIME_S,
            "seed": 42,
            "port": API_PORT
        },
        "kpi": {
            "schema_version": schema_version,
            "coverage_pct": round(coverage * 100, 2),
            "drivers_total": drivers,
            "split_blocks": split_blocks,
            "twopass_executed": twopass,
            "pass1_time_s": stats.get("pass1_time_s"),
            "pass2_time_s": stats.get("pass2_time_s")
        },
        "quality": {
            "errors": errors,
            "warnings": warnings,
            "validator_ok": not validator_failed
        }
    }
    with open(golden_validation, "w", encoding="utf-8") as f:
        json.dump(validation_data, f, indent=2)
    
    # 5c. README
    readme_path = artifacts_path / "README.md"
    readme_content = f"""# RC0 Verification Artifacts
    
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Mode:** {mode_name}
**Intent:** {'Unbounded Quality' if not quick_mode else 'Quick CI'}

## Run Metrics
- **Drivers:** {drivers}
- **Split Blocks:** {split_blocks}
- **Pass 2 Executed:** {twopass} (Guarantee: {PASS2_MIN_TIME_S}s)
- **Schema Version:** {schema_version}

## Status
- **Contract:** {"✅ Valid" if not errors else "❌ Invalid"}
- **Validator:** {"✅ OK" if not validator_failed else "❌ Failed"}

## Files
- `weekly_plan.json`: The generated plan.
- `validation.json`: Machine-readable metrics.
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    # Final Report
    print()
    print("=" * 70)
    print(f"RC0 VERIFICATION REPORT ({mode_name} MODE)")
    print("=" * 70)
    print(f"Schema Version:  {schema_version}")
    print(f"Drivers:         {drivers}")
    print(f"Split Blocks:    {split_blocks}")
    print(f"Pass-2 Executed: {twopass}")
    print()
    
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  [!] {w}")
        print()
    
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  [X] {e}")
        print()
        print("VERIFICATION FAILED")
        return 1
    
    print(f"Artifacts saved to: {ARTIFACTS_DIR}")
    print("VERIFICATION PASSED [OK]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
