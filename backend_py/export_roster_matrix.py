import csv
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.services.portfolio_controller import run_portfolio
from test_forecast_csv import parse_forecast_csv
from src.domain.models import Weekday

def format_time(t):
    return f"{t.hour:02d}:{t.minute:02d}"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Roster Matrix")
    parser.add_argument("--time-budget", type=float, default=60.0, help="Solver time budget in seconds")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    print("=" * 70)
    print("ROSTER MATRIX EXPORTER")
    print("=" * 70)
    
    # Input
    input_file = Path(__file__).parent.parent / "forecast input.csv"
    if not input_file.exists():
        print(f"Error: Input file not found at {input_file}")
        return
        
    print(f"Reading forecast from: {input_file}")
    tours = parse_forecast_csv(str(input_file))
    print(f"Loaded {len(tours)} tours")

    # Solve
    print(f"\nRunning solver (Set-Partitioning V7.0.0, Quality Mode, Budget={args.time_budget}s)...")
    result = run_portfolio(tours, time_budget=args.time_budget, seed=args.seed)
    
    solution = result.solution
    valid_statuses = ["OPTIMAL", "FEASIBLE", "COMPLETED", "OK", "OK_SEEDED"]
    if solution.status not in valid_statuses:
        print(f"Solver failed with status: {solution.status}")
        return

    assignments = solution.assignments
    print(f"\nSolved! Status: {solution.status}")
    print(f"Assignments: {len(assignments)} drivers")

    # Prepare CSV rows
    rows = []
    
    # Sort by Driver Type (FTE first), then Hours (desc), then ID
    assignments.sort(key=lambda a: (0 if a.driver_type == "FTE" else 1, -a.total_hours, a.driver_id))

    headers = ["Driver ID", "Type", "Weekly Hours", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    # Map Weekday enum to header columns
    day_map = {
        Weekday.MONDAY: "Mon",
        Weekday.TUESDAY: "Tue",
        Weekday.WEDNESDAY: "Wed",
        Weekday.THURSDAY: "Thu",
        Weekday.FRIDAY: "Fri",
        Weekday.SATURDAY: "Sat"
    }

    for assignment in assignments:
        row = {
            "Driver ID": assignment.driver_id,
            "Type": assignment.driver_type,
            "Weekly Hours": f"{assignment.total_hours:.2f}".replace('.', ','), # German decimal format
            "Mon": "", "Tue": "", "Wed": "", "Thu": "", "Fri": "", "Sat": ""
        }
        
        for block in assignment.blocks:
            day_str = day_map.get(block.day)
            if day_str:
                start = format_time(block.first_start)
                end = format_time(block.last_end)
                try:
                    b_type = block.block_type.value # e.g. "3er"
                except:
                    b_type = "Block"
                    
                # Check for split
                split_flag = " (Split)" if getattr(block, 'is_split', False) else ""
                
                # Format: "08:00-17:00 (3er)"
                cell_content = f"{start}-{end} ({b_type}{split_flag})"
                row[day_str] = cell_content
        
        rows.append(row)

    # Write CSV
    output_file = Path(__file__).parent / "roster_matrix.csv"
    
    # Use utf-8-sig for Excel compatibility (BOM)
    # Use semicolon delimiter for German Excel
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=";", extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[SUCCESS] Roster Matrix exported to: {output_file}")
    print(f"Total Rows: {len(rows)}")
    
    # Preview
    print("\nPreview (Top 3 FTE):")
    for r in rows[:3]:
        print(f"  {r['Driver ID']} ({r['Type']}, {r['Weekly Hours']}h)")

if __name__ == "__main__":
    main()
