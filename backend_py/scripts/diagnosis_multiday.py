"""
Phase 4 Diagnosis: Multi-Day Roster Analysis
Target: Determine if failure is in Pricing (Generation) or Selection (MIP).
Dataset: forecast-test.csv (6 days)
"""
import sys
import os
import json
import logging
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Phase4_Diagnosis")

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv

def main():
    # Load Forecast
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv")
    if not csv_file.exists():
        logger.error("forecast_test.csv not found!")
        return
        
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # Convert to V2
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(f"T_{day_map.get(t.day, 0)}_{t.id}", day_map.get(t.day, 0), t.start_time.hour*60+t.start_time.minute, t.start_time.hour*60+t.start_time.minute+int(t.duration_hours*60), int(t.duration_hours*60)))

    # Diagnosis Config
    config = {
        "run_id": "phase4_diag",
        "week_category": "NORMAL",
        "artifacts_dir": "results/phase4_diag",
        
        "max_cg_iterations": 25,  # Enough to see trend
        "lp_time_limit": 30.0,
        "restricted_mip_var_cap": 25_000,
        "restricted_mip_time_limit": 30.0,
        "mip_time_limit": 120.0,
        "final_subset_cap": 20_000,
        "target_seed_columns": 3000,
        "pricing_time_limit_sec": 60.0, # Increased from 10s to ensure propagation completes
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 1440, # 24h window
            "top_m_start_tours": 50, # Reduced from 300 to prevent graph explosion
            "max_succ_per_tour": 30, # Reduced from 100
            "max_triples_per_tour": 5,
        },
        "export_csv": False
    }
    
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    # Analyze final histograms
    kpis = result.kpis
    
    print("\n" + "=" * 80)
    print("PHASE 4 DIAGNOSIS RESULT")
    print("=" * 80)
    
    # 1. Pool Composition (Generation Health)
    print(f"\n1. POOL COMPOSITION (Generation Analysis)")
    print(f"   Pool Size: {kpis.get('pool_final_size', 0)}")
    print(f"   Pool Days>=4: {kpis.get('pct_pool_days_ge_4', 0):.1f}%")
    print(f"   Pool Days Hist: {kpis.get('pool_days_worked_hist', {})}")
    
    # 2. Selected Composition (Selection Health)
    print(f"\n2. TOP SELECTION (Incumbent Analysis)")
    print(f"   Selected Columns: {kpis.get('drivers_total', 0)}")
    print(f"   Selected Days>=4: {kpis.get('pct_selected_days_ge_4', 0):.1f}%")
    print(f"   Selected Days Hist: {kpis.get('selected_days_worked_hist', {})}")
    print(f"   Avg Days/Driver: {sum(k * v for k, v in kpis.get('selected_days_worked_hist', {}).items()) / max(1, kpis.get('drivers_total', 1)):.2f}")
    
    # 3. Verdict Logic
    pct_pool_ge_4 = kpis.get('pct_pool_days_ge_4', 0)
    pct_selected_ge_4 = kpis.get('pct_selected_days_ge_4', 0)
    
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    
    if pct_pool_ge_4 < 5.0:
        print("-> FAILURE IN PRICING (GENERATION)")
        print("   The pool barely contains multi-day rosters (Days>=4 < 5%).")
        print("   Action: Fix SPPRC linker, candidate generation, or pruning logic.")
    elif pct_selected_ge_4 < 5.0:
        print("-> FAILURE IN SELECTION (MIP)")
        print(f"   Pool has multi-day ({pct_pool_ge_4:.1f}%), but MIP ignores them ({pct_selected_ge_4:.1f}%).")
        print("   Action: Fix Subset Selection or tune Penalties (cost alignment).")
    else:
        print("-> MULTI-DAY GENERATION LOOKS OK")
        print("   Both Pool and Selected have >5% long rosters.")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
