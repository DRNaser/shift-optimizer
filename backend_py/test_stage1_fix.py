"""
Test Stage-1 Infeasibility Fix for KW51
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

from test_forecast_csv import parse_forecast_csv
from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2

# Load tours
csv_path = Path(__file__).parent.parent / "forecast_kw51_filtered.csv"
print(f"Loading tours from: {csv_path}")

tours_v1 = parse_forecast_csv(str(csv_path))
print(f"Loaded {len(tours_v1)} V1 tours")

# Convert to V2
from src.domain.models import Weekday
day_map = {
    Weekday.MONDAY: 0,
    Weekday.TUESDAY: 1,
    Weekday.WEDNESDAY: 2,
    Weekday.THURSDAY: 3,
    Weekday.FRIDAY: 4,
    Weekday.SATURDAY: 5,
    Weekday.SUNDAY: 6,
}

tours_v2 = []
for t in tours_v1:
    day = day_map.get(t.day, 0)
    start_min = t.start_time.hour * 60 + t.start_time.minute
    duration_min = int(t.duration_hours * 60)
    end_min = start_min + duration_min
    
    tv2 = TourV2(
        tour_id=f"T_{day}_{t.id}",
        day=day,
        start_min=start_min,
        end_min=end_min,
        duration_min=duration_min,
    )
    tours_v2.append(tv2)

print(f"Converted to {len(tours_v2)} V2 tours")

# Run optimizer with improved settings
config = {
    "max_cg_iterations": 25,  # 25 iterations for deep dive
    "lp_time_limit": 60.0,   
    "restricted_mip_var_cap": 20_000,
    "restricted_mip_time_limit": 30.0,
    "mip_time_limit": 120.0,  
    "target_seed_columns": 5000,
    "pricing_time_limit_sec": 12.0,  # Increased for aggressive search
    "duty_caps": {
        "max_gap_minutes": 600,    # 10h Gap for Splits
        "top_m_start_tours": 500,  # Deep search
        "max_succ_per_tour": 50,
    }
}

print("\n" + "=" * 70)
print("Running OptimizerCoreV2 (30 iterations)...")
print("=" * 70)

optimizer = OptimizerCoreV2()
result = optimizer.solve(tours_v2, config, run_id="test_quality")

print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)
print(f"Status: {result.status}")
print(f"Error: {result.error_code} - {result.error_message}")

if result.status == "SUCCESS":
    kpis = result.kpis
    print(f"\n--- KEY METRICS ---")
    print(f"drivers_total: {kpis.get('drivers_total', 0)}")
    print(f"PT Share: {kpis.get('pt_share_pct', 0):.1f}%")
    print(f"Coverage: {result.proof.coverage_pct:.1f}%")
    print(f"CG Iterations: {kpis.get('cg_iterations', 0)}")
    print(f"Runtime: {kpis.get('total_time', 0):.1f}s")
    
    # Block mix from selected columns
    print(f"\n--- BLOCK MIX ---")
    hist = kpis.get('selected_days_worked_hist', {})
    print(f"Days worked histogram: {hist}")
    
    # Calculate 1er/2er/3er from solution
    solution = result.solution
    block_counts = {"1er": 0, "2er": 0, "3er+": 0}
    for a in solution:
        for b in a.blocks:
            tours_in_block = len(getattr(b, 'tours', [])) if hasattr(b, 'tours') else 1
            if tours_in_block == 1:
                block_counts["1er"] += 1
            elif tours_in_block == 2:
                block_counts["2er"] += 1
            else:
                block_counts["3er+"] += 1
    print(f"Block counts: {block_counts}")
    
    # Support histogram
    print(f"\n--- SUPPORT STATS ---")
    print(f"singleton_only_tours_by_day: {kpis.get('singleton_only_tours_by_day', {})}")
    print(f"top_bottleneck_tours: {kpis.get('top_bottleneck_tours', [])[:5]}")
else:
    print("Logs (last 20):")
    for log in result.logs[-20:]:
        print(f"  {log}")
