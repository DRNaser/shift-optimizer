"""
Simple debug test to check if driver_cap=150 is set correctly
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Tour, Weekday
from test_forecast_csv import parse_forecast_csv
from src.services.forecast_solver_v4 import ConfigV4
from src.services.portfolio_controller import solve_forecast_portfolio

# Parse input
input_file = Path(__file__).parent.parent / "forecast input.csv"
tours = parse_forecast_csv(str(input_file))
print(f"Loaded {len(tours)} tours")

# Create config with 150-FTE fixed pool
config = ConfigV4(
    seed=42,
    num_workers=1,
    time_limit_phase1=20.0,
    time_limit_phase2=40.0,
    use_fixed_fte_pool=True,
    num_fte_pool=150,
    fte_min_hours=40.0,
)

print(f"\nConfig:")
print(f"  use_fixed_fte_pool: {config.use_fixed_fte_pool}")
print(f"  num_fte_pool: {config.num_fte_pool}")
print(f"  fte_min_hours: {config.fte_min_hours}")
print()

# Run portfolio controller
result = solve_forecast_portfolio(tours, config)

print(f"\nResult status: {result.get('status')}")
print(f"Assignments: {len(result.get('assignments', []))}")

# Count FTE and PT
assignments = result.get('assignments', [])
fte = [a for a in assignments if a.driver_type == "FTE"]
pt = [a for a in assignments if a.driver_type == "PT"]

print(f"\nFTE: {len(fte)}")
print(f"PT: {len(pt)}")

if fte:
    fte_under40 = [a for a in fte if a.total_hours < 40.0]
    print(f"FTE < 40h: {len(fte_under40)}")
    print(f"FTE hours: min={min(a.total_hours for a in fte):.1f}, avg={sum(a.total_hours for a in fte)/len(fte):.1f}, max={max(a.total_hours for a in fte):.1f}")
