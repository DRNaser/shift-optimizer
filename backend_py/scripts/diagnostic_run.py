#!/usr/bin/env python3
"""
Diagnostic Run - Capture full KPIs for analysis
"""
import os
import os
import sys
import json
import requests

# Fix encoding issues on Windows (cp1252 doesn't support unicode symbols)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    # Python < 3.7 fallback
    pass

import time

def read_json_with_retry(url, retries=10, delay=0.5):
    """Retrieve JSON from URL with retry logic for robustness."""
    last_err = None
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json(), resp
            elif resp.status_code == 404:
                # If 404, maybe it's not written yet? Wait and retry
                pass
            else:
                 # Other error, might be transient
                 pass
        except Exception as e:
            last_err = e
        
        time.sleep(delay)
    
    # Final attempt
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json(), resp
    except Exception as e:
        raise RuntimeError(f"Failed to read/parse {url} after {retries} retries: {e}")


API_PORT = int(os.environ.get("API_PORT", 8000))
API_URL = f"http://localhost:{API_PORT}/api/v1"
INPUT_FILE = r"C:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt"

DAY_MAP = {
    "Montag": "Mon", "Dienstag": "Tue", "Mittwoch": "Wed",
    "Donnerstag": "Thu", "Freitag": "Fri", "Samstag": "Sat", "Sonntag": "Sun"
}

def parse_input(file_path):
    tours = []
    current_day = None
    tour_id_counter = 1
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 1 and parts[0] in DAY_MAP:
                current_day = DAY_MAP[parts[0]]
                continue
            if '\t' in line:
                tokens = line.split('\t')
            else:
                tokens = line.split()
            if len(tokens) < 2:
                continue
            time_range = tokens[0]
            try:
                count = int(tokens[1])
            except ValueError:
                continue
            if '-' not in time_range:
                continue
            start_str, end_str = time_range.split('-')
            for _ in range(count):
                tours.append({
                    "id": f"T{tour_id_counter}",
                    "day": current_day,
                    "start_time": start_str.strip(),
                    "end_time": end_str.strip(),
                    "location": "HUB_A",
                    "required_qualifications": []
                })
                tour_id_counter += 1
    return tours

def generate_drivers(num_drivers=300):
    drivers = []
    for i in range(1, num_drivers + 1):
        drivers.append({
            "id": f"D{i}",
            "name": f"Driver {i}",
            "qualifications": [],
            "max_weekly_hours": 55.0,
            "max_daily_span_hours": 14.0,
            "max_tours_per_day": 3,
            "min_rest_hours": 11.0,
            "available_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        })
    return drivers

def main():
    # Parse CLI arguments
    import argparse
    parser = argparse.ArgumentParser(description="Diagnostic run for Shift Optimizer")
    parser.add_argument("--output_profile", type=str, default="BEST_BALANCED",
                        choices=["MIN_HEADCOUNT_3ER", "BEST_BALANCED"],
                        help="Output profile: MIN_HEADCOUNT_3ER or BEST_BALANCED")
    parser.add_argument("--gap_3er_min", type=int, default=30,
                        help="Min gap for 3er blocks (MIN_HEADCOUNT_3ER only)")
    parser.add_argument("--time_budget", type=int, default=180,
                        help="Time budget in seconds")
    parser.add_argument("--pass2_min_time_s", type=float, default=30.0,
                        help="Minimum time guarantee for Pass-2 optimization")
    args = parser.parse_args()
    
    print("=" * 60)
    print("DIAGNOSTIC RUN - Full KPI Analysis")
    print("=" * 60)
    
    tours = parse_input(INPUT_FILE)
    drivers = generate_drivers(300)
    
    print(f"Tours: {len(tours)}")
    print(f"Drivers pool: {len(drivers)}")
    print(f"Output Profile: {args.output_profile}")
    
    # Build config overrides with profile selection
    config_overrides = {
        # ==========================================================================
        # MAIN PATH TEST: BEST_BALANCED -> SetPart + LNS
        # ==========================================================================
        # "solver_mode": "SETPART",  # Removed: relying on BEST_BALANCED forcing logic
        
        # Standard config
        "cap_quota_2er": 0.30,
        "enable_fill_to_target_greedy": True,
        "enable_bad_block_mix_rerun": True,
        "enable_diag_block_caps": False,
        "output_profile": args.output_profile, # Should be BEST_BALANCED
        "gap_3er_min_minutes": args.gap_3er_min,
        "pass2_min_time_s": args.pass2_min_time_s,
        
        # LNS ENDGAME: Low-Hour Pattern Consolidation (NEW Set-Part LNS)
        "enable_lns_low_hour_consolidation": True, 
        "lns_time_budget_s": 30.0,
        "lns_low_hour_threshold_h": 30.0,
    }
    
    payload = {
        "week_start": "2024-01-01",
        "tours": tours,
        "drivers": drivers,
        "run": {
            "time_budget_seconds": args.time_budget,
            "seed": 42,
            "config_overrides": config_overrides
        }
    }
    
    print("\nConfig Overrides:")
    for k, v in config_overrides.items():
        print(f"  {k}: {v}")
    print(f"\nTime Budget: {args.time_budget}s")
    print("\nStarting solver...")
    
    try:
        resp = requests.post(f"{API_URL}/runs", json=payload, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        run_id = result.get("run_id", "unknown")
        print(f"\nRun ID: {run_id}")
        
        # Poll for completion - solver runs async
        import time
        # Dynamic wait based on budget (default 300s is likely too short for Quality runs)
        # Use budget + 60s overhead, or at least 300s
        dynamic_wait = args.time_budget + 120
        max_wait = max(300, dynamic_wait)
        
        poll_interval = 5
        waited = 0
        
        print(f"  Polling for completion (timeout={max_wait}s)...")
        
        while waited < max_wait:
            status_resp = requests.get(f"{API_URL}/runs/{run_id}", timeout=10)
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                current_status = status_data.get("status", "UNKNOWN")
                print(f"  Status: {current_status} (waited {waited}s)")
                
                if current_status in ["COMPLETED", "FAILED", "CANCELLED"]:
                    break
            
            time.sleep(poll_interval)
            waited += poll_interval
        
        if waited >= max_wait:
            print(f"TIMEOUT: Run did not complete within {max_wait}s")
            return
        
        # Fetch the plan with retry
        try:
             plan, plan_resp = read_json_with_retry(f"{API_URL}/runs/{run_id}/plan")
        except Exception as e:
             print(f"ERROR reading plan: {e}")
             return

        if plan:

            
            print("\n" + "=" * 60)
            print("RUN RESULT")
            print("=" * 60)
            
            # Extract KPIs
            stats = plan.get("stats", {})
            validation = plan.get("validation", {})
            
            print(f"\nStatus: {validation.get('is_valid', 'unknown')}")
            print(f"\nKPIs:")
            print(f"  drivers_total:    {stats.get('total_drivers', 'N/A')}")
            print(f"  tours_input:      {stats.get('total_tours_input', 'N/A')}")
            print(f"  tours_assigned:   {stats.get('total_tours_assigned', 'N/A')}")
            print(f"  coverage_rate:    {stats.get('assignment_rate', 'N/A')}")
            print(f"  avg_work_hours:   {stats.get('average_work_hours', 'N/A'):.1f}h")
            print(f"  utilization:      {stats.get('average_driver_utilization', 0) * 100:.1f}%")
            
            block_counts = stats.get("block_counts", {})
            print(f"\nBlock Mix (final solution):")
            print(f"  blocks_1er: {block_counts.get('1er', 0)}")
            print(f"  blocks_2er: {block_counts.get('2er', 0)}")
            print(f"  blocks_3er: {block_counts.get('3er', 0)}")
            # New Stat
            print(f"  candidates_3er_pre_cap: {stats.get('candidates_3er_pre_cap', 'N/A')}")
            
            # SPLIT-SPECIFIC STATS (computed from assignments)
            assignments = plan.get("assignments", [])
            b2_split = sum(1 for a in assignments if a.get("block", {}).get("id", "").startswith("B2S-"))
            b2_reg = block_counts.get('2er', 0) - b2_split
            b1 = block_counts.get('1er', 0)
            b3 = block_counts.get('3er', 0)
            
            print(f"\nSplit Block Stats:")
            print(f"  blocks_2er_reg:   {b2_reg}")
            print(f"  blocks_2er_split: {b2_split}")
            split_total = len([a for a in assignments])
            split_share = (b2_split / split_total * 100) if split_total > 0 else 0
            print(f"  split_share:      {split_share:.1f}% of driver-days")
            
            # Output Profile Info
            print(f"\nOutput Profile Info:")
            print(f"  output_profile: {stats.get('output_profile', 'N/A')}")
            print(f"  gap_3er_min_minutes: {stats.get('gap_3er_min_minutes', 'N/A')}")
            
            # Tour Shares (by tours, not blocks)
            tour_share_1er = stats.get('tour_share_1er')
            tour_share_2er = stats.get('tour_share_2er')
            tour_share_3er = stats.get('tour_share_3er')
            print(f"\nTour Shares (by tours):")
            print(f"  tour_share_1er: {tour_share_1er*100:.1f}%" if tour_share_1er else "  tour_share_1er: N/A")
            print(f"  tour_share_2er: {tour_share_2er*100:.1f}%" if tour_share_2er else "  tour_share_2er: N/A")
            print(f"  tour_share_3er: {tour_share_3er*100:.1f}%" if tour_share_3er else "  tour_share_3er: N/A")
            
            # MATH CHECK: Verify block mix units (SPLIT-AWARE)
            total_blocks_chk = b1 + b2_reg + b2_split + b3
            tours_covered_chk = b1 + 2*(b2_reg + b2_split) + 3*b3
            
            print(f"\nMATHEMATICAL SANITY CHECK (Split-Aware):")
            print(f"  Sum(blocks) = {b1} + {b2_reg} + {b2_split} + {b3} = {total_blocks_chk}")
            print(f"  Sum(tours)  = {b1} + 2*({b2_reg}+{b2_split}) + 3*{b3} = {tours_covered_chk}")
            
            tours_input = stats.get('total_tours_input', 0)
            if tours_covered_chk == tours_input:
                print(f"  -> MATCHES INPUT TOURS ({tours_input}) [OK]")
            else:
                print(f"  -> MISMATCH input tours ({tours_input}) [WARNING]")
            
            # MUSS-CHECK: blocks_total consistency
            blocks_total_reported = block_counts.get('1er', 0) + block_counts.get('2er', 0) + block_counts.get('3er', 0)
            if total_blocks_chk == blocks_total_reported:
                print(f"  -> blocks_total == Sum(b*) [OK]")
            else:
                print(f"  -> blocks_total MISMATCH [WARNING]")
                
            # BEST_BALANCED Two-Pass Metrics
            # NOTE: D_pass1 is the pass-1 heuristic result (not a true lower bound)
            # Pass-2 may find a better solution under driver_cap constraint
            D_pass1 = stats.get('D_pass1_seed', stats.get('D_min'))  # Use new key, fallback to legacy
            driver_cap = stats.get('driver_cap')
            day_spread = stats.get('day_spread')
            twopass_executed = stats.get('twopass_executed')
            pass1_time = stats.get('pass1_time_s')
            pass2_time = stats.get('pass2_time_s')
            drivers_pass1 = stats.get('drivers_total_pass1')
            drivers_pass2 = stats.get('drivers_total_pass2')
            
            if D_pass1 is not None or twopass_executed:
                print(f"\nBEST_BALANCED Two-Pass Metrics:")
                print(f"  twopass_executed:    {twopass_executed}")
                print(f"  twopass_status:      {stats.get('twopass_status')}")
                print(f"  D_pass1_seed:        {D_pass1}  (heuristic, not lower bound)")
                print(f"  driver_cap (+5%):    {driver_cap}")
                print(f"  actual_drivers:      {stats.get('total_drivers', 'N/A')}")
                print(f"  day_spread (var):    {day_spread}")
                if pass1_time is not None:
                    print(f"  pass1_time_s:        {pass1_time:.1f}")
                if pass2_time is not None:
                    print(f"  pass2_time_s:        {pass2_time:.1f}")
                if drivers_pass1 is not None:
                    print(f"  drivers_pass1:       {drivers_pass1}")
                if drivers_pass2 is not None:
                    print(f"  drivers_pass2:       {drivers_pass2}")
                
                failure_reason = stats.get('diagnostics_failure_reason')
                if failure_reason:
                    print(f"  FAILURE REASON:      {failure_reason}")
                
                # Check cap enforcement
                total_drivers = stats.get('total_drivers', 0)
                if total_drivers and driver_cap:
                    if total_drivers <= driver_cap:
                        print(f"  CAP ENFORCED: OK ({total_drivers} <= {driver_cap})")
                    else:
                        print(f"  CAP VIOLATED: FAIL ({total_drivers} > {driver_cap})")
            
            # Fetch run report for packability metrics
            report_resp = requests.get(f"{API_URL}/runs/{run_id}/report", timeout=10)
            if report_resp.status_code == 200:
                report = report_resp.json()
                print(f"DEBUG: Report keys: {list(report.keys())}")
                if "kpi" in report:
                    print(f"DEBUG: KPI keys: {list(report['kpi'].keys())}")
                    if "traceback" in report["kpi"]:
                        print(f"\nSERVER TRACEBACK:\n{report['kpi']['traceback']}")
                        
                result_summary = report.get("result_summary", {})
                
                # FULL EFFECTIVE CONFIG DUMP
                print(f"\n{'='*60}")
                print("EFFECTIVE CONFIG (after overrides)")
                print("="*60)
                
                config = report.get("config", {})
                kpi_config = report.get("kpi", {})
                
                # Key config params to dump (FULL DUMP)
                sorted_keys = sorted(config.keys())
                for key in sorted_keys:
                    val = config[key]
                    # Skip huge lists/dicts if any, but usually config is flat-ish
                    if isinstance(val, (list, dict)) and len(str(val)) > 200:
                         print(f"  {key}: <truncated, len={len(val)}>")
                    else:
                         print(f"  {key}: {val}")
                
                # Packability metrics (try stats first, then report)
                print(f"\n{'='*60}")
                print("PACKABILITY DIAGNOSTICS")
                print("="*60)
                
                # Check stats (from /plan) first - this is the new standard
                if "forced_1er_rate" in stats:
                    kpi = stats
                    print("DEBUG: Using packability metrics from /plan stats")
                elif "kpi" in report:
                    kpi = report["kpi"]
                    print("DEBUG: Using packability metrics from /report kpi")
                elif "result_summary" in report:
                    kpi = report.get("result_summary", {})
                    print("DEBUG: Using packability metrics from /report result_summary")
                else:
                    kpi = {}
                
                forced_1er_rate = kpi.get("forced_1er_rate")
                forced_1er_count = kpi.get("forced_1er_count", "N/A")
                missed_3er = kpi.get("missed_3er_opps_count", "N/A")
                missed_2er = kpi.get("missed_2er_opps_count", "N/A")
                missed_multi = kpi.get("missed_multi_opps_count", "N/A")
                
                # Handle potential None values if metric exists but is None
                if forced_1er_rate is None: forced_1er_rate = "N/A"
                
                if isinstance(forced_1er_rate, float):
                    print(f"  forced_1er_rate: {forced_1er_rate*100:.1f}%")
                else:
                    print(f"  forced_1er_rate: {forced_1er_rate}")
                print(f"  forced_1er_count: {forced_1er_count}")
                print(f"  missed_3er_opps: {missed_3er}")
                print(f"  missed_2er_opps: {missed_2er}")
                print(f"  missed_multi_opps: {missed_multi}")
                
                # Analysis
                total_tours = stats.get("total_tours_input", 1385)
                blocks_1er = block_counts.get('1er', 0)
                
                if isinstance(forced_1er_rate, float) and isinstance(missed_multi, int):
                    print(f"\nDIAGNOSIS:")
                    if forced_1er_rate > 0.20:
                        print(f"  -> HIGH forced_1er_rate ({forced_1er_rate*100:.0f}%) indicates TSGen/Constraints issue")
                        print(f"     (Tours are not combinable due to timing gaps)")
                    elif missed_multi > blocks_1er * 0.3:
                        print(f"  -> HIGH missed_multi_opps ({missed_multi}) indicates Objective/Selection issue")
                        print(f"     (Solver not using available multi-tour blocks)")
                    else:
                        print(f"  -> Block mix appears reasonable")
            
            # Save full result for analysis
            with open("diag_run_result.json", "w") as f:
                json.dump(plan, f, indent=2)
            print("\nFull result saved to: diag_run_result.json")
            
        else:
            print(f"Failed to fetch plan: {plan_resp.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
