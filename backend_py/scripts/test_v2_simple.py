"""
SIMPLE Core V2 Direct Test - Uses working verify pattern + AdapterV2

Tests comprehensive seeder with Core V2 engine.
"""

import sys
import os
from pathlib import Path

sys.path.append(os.getcwd())

# Use the working verify script's CSV parsing
from scripts.verify_quality_forecast_test import parse_forecast_csv, analyze_result

# Import Core V2 adapter
from src.api.adapter_v2 import AdapterV2
from src.services.forecast_solver_v4 import ConfigV4

CSV_PATH = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv"

print("="*60)
print("CORE V2 DIRECT TEST (Comprehensive Seeder)")
print("="*60)

# Load tours using working parser
print(f"\nLoading: {CSV_PATH}")
tours = parse_forecast_csv(CSV_PATH)
print(f"Loaded {len(tours)} tours\n")

# Call Core V2 directly
print("Running Core V2...")
config = ConfigV4(target_ftes=200, seed=42)

result = AdapterV2.run_optimizer_v2_adapter(
    tours=tours,
    time_budget=300.0,
    seed=42,
    config=config
)

print("\n" + "="*60)
print("ANALYZING RESULTS...")
print("="*60)

# Use working analyzer
analyze_result(result)

print("\n" + "="*60)
print("VERIFICATION COMPLETE")
print("="*60)
