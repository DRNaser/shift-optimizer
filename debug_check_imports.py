
import sys
from pathlib import Path
import pt_balance_quality_gate as pt

print("Testing sys.path setup...")
pt._add_repo_to_syspath(Path("."))
print(f"sys.path: {sys.path[:2]}")

try:
    import src.domain.models
    print("Imported src.domain.models")
    from src.domain.models import Tour
    print(f"Imported Tour: {Tour}")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Other error: {e}")

print("Testing object conversion...")
try:
    tours_rows = [pt.TourRow(tour_id="T1", day=0, start_min=0, end_min=60)]
    objs = pt._convert_tours_to_domain_objects(tours_rows)
    print(f"Result len: {len(objs)}")
    if objs:
        print(f"First item type: {type(objs[0])}")
        print(f"First item: {objs[0]}")
        if hasattr(objs[0], "day"):
            print("Item has .day")
        else:
            print("Item missing .day")
except Exception as e:
    print(f"Conversion failed: {e}")
