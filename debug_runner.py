
import sys
from pathlib import Path
import pt_balance_quality_gate as pt

print("Imported successfully.")
inp = Path("forecast-test.txt")
try:
    tours = pt.parse_forecast_matrix(inp)
    print(f"Parsed {len(tours)} tours.")
except Exception as e:
    print(f"Error: {e}")

# Check _parse_time_range behavior
try:
    print(f"Time check: {pt._parse_time_range('04:45-09:15')}")
except Exception as e:
    print(f"Time check failed: {e}")
