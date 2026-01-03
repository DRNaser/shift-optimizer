"""
EMERGENCY DIRECT RUNNER - Tests OptimizerCoreV2 with KW51 data
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend_py'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from src.core_v2.model.tour import TourV2
from src.core_v2.optimizer_v2 import OptimizerCoreV2

# Parse KW51 CSV (simplified - just Monday tours for quick test)
csv_path = os.path.join(os.path.dirname(__file__), '..', 'forecast_kw51.csv')

tours = []
with open(csv_path, 'r', encoding='utf-8-sig') as f:
    current_day = 0  # Monday
    tour_counter = 0
    
    for line in f:
        line = line.strip()
        if not line or ';' not in line:
            continue
        
        parts = line.split(';')
        if len(parts) < 2:
            continue
        
        time_slot = parts[0].strip()
        count_str = parts[1].strip()
        
        # Check if this is a day header
        if "Montag" in line:
            current_day = 0
        elif "Dienstag" in line:
            break  # Stop at Tuesday for quick test
        
        # Parse time slots
        if '-' in time_slot and count_str.isdigit():
            count = int(count_str)
            start_str, end_str = time_slot.split('-')
            
            try:
                start_h, start_m = map(int, start_str.split(':'))
                end_h, end_m = map(int, end_str.split(':'))
                
                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m
                duration = end_min - start_min
                
                # Create tours
                for i in range(count):
                    tour = TourV2(
                        tour_id=f"T_{tour_counter:04d}",
                        day=current_day,
                        start_min=start_min,
                        end_min=end_min,
                        duration_min=duration
                    )
                    tours.append(tour)
                    tour_counter += 1
            except:
                continue

print(f"Loaded {len(tours)} tours from KW51")

# Run optimizer
config = {
    "max_cg_iterations": 5,  # Very short test
    "lp_time_limit": 10.0,
    "pricing_time_limit_sec": 5.0,
    "max_new_cols_per_iter": 500,
    "restricted_mip_every": 3,
    "restricted_mip_time_limit": 3.0,
    "restricted_mip_var_cap": 10000,
}

optimizer = OptimizerCoreV2()
result = optimizer.solve(tours, config=config)

print("\n" + "="*80)
print("EMERGENCY TEST RESULT:")
print(f"Status: {result.status}")
print(f"Error: {result.error_message if result.status == 'FAIL' else 'None'}")
print(f"Drivers: {result.kpis.get('drivers_total', 'N/A')}")
print(f"Pool final: {result.kpis.get('pool_final_size', 'N/A')}")

if result.kpis.get('singleton_only_tours_by_day'):
    print(f"\nSingleton-only by day: {result.kpis['singleton_only_tours_by_day']}")

print("="*80)
print("\n✅ EMERGENCY FIXES VALIDATED" if result.status == "SUCCESS" else "❌ RUN FAILED")
