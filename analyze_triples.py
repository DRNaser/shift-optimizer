import sys
from pathlib import Path
from collections import defaultdict

# Add backend path
sys.path.insert(0, str(Path(__file__).parent / "backend_py"))

from run_block_heuristic import partition_tours_into_blocks
from src.services.block_heuristic_solver import BlockHeuristicSolver
from src.services.smart_block_builder import BlockGenOverrides
from test_forecast_csv import parse_forecast_csv
from src.domain.models import Weekday

def analyze_triples():
    print("re-calculating schedule (Seed 94)...")
    
    input_file = Path(__file__).parent / "forecast input.csv" 
    if not input_file.exists():
        input_file = Path(__file__).parent / "forecast_kw51.csv"
        
    tours = parse_forecast_csv(str(input_file))
    
    overrides = BlockGenOverrides(
        max_pause_regular_minutes=60,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
        max_daily_span_hours=16.0,
        enable_split_blocks=True
    )
    
    # Generate Blocks
    blocks = partition_tours_into_blocks(tours, overrides)
    
    # Solve
    solver = BlockHeuristicSolver(blocks)
    drivers = solver.solve()
    
    # Analyze Chains
    print("\n=== TRIPLE (3er) BLOCK CHAIN ANALYSIS ===")
    
    chain_counts = defaultdict(int)
    max_c_all = 0
    longest_chain_driver = None
    
    days_order = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
    
    for d in drivers:
        # Get list of types ordered by day
        types = []
        for day in days_order:
            if day in d.day_map:
                b = d.day_map[day]
                if len(b.tours) == 3:
                    types.append("3er")
                else:
                    types.append("Other")
            else:
                types.append("Off")
                
        # Count consecutive "3er"
        current_chain = 0
        max_c = 0
        for t in types:
            if t == "3er":
                current_chain += 1
            else:
                if current_chain > 1:
                    chain_counts[current_chain] += 1
                if current_chain > max_c: max_c = current_chain
                current_chain = 0
        
        # End of week check
        if current_chain > 1:
            chain_counts[current_chain] += 1
        if current_chain > max_c: max_c = current_chain
            
        if max_c > max_c_all:
            max_c_all = max_c
            longest_chain_driver = d.id

    print(f"Total Drivers: {len(drivers)}")
    print(f"Max Consecutive 3-er Days: {max_c_all}")
    
    print("\nFrequency of Consecutive 3-er Chains:")
    for chain_len in sorted(chain_counts.keys()):
        print(f" - {chain_len} days in a row: {chain_counts[chain_len]} occurrences")
        
    print("\nNote: '3er' blocks are typically 9-10h of work.")
    if max_c_all >= 3:
        print("WARNING: Some drivers have 3+ hard days in a row.")

if __name__ == "__main__":
    analyze_triples()
