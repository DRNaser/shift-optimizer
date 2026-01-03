"""
Reproduction: Gap Day Linking Bug
Verifies if a Friday evening tour can link to a Monday afternoon tour.
With current logic (search_start clamped to 0, window 12h), Monday afternoon (>12:00) should be unreachable.
"""
from src.core_v2.model.duty import DutyV2
from src.core_v2.model.tour import TourV2
from src.core_v2.pricing.spprc import SPPRCPricer
from src.core_v2.duty_factory import DutyFactoryTopK

def test_gap_linking():
    # 1. Setup Tours
    # Friday 14:00 - 20:00 (End 1200)
    t_fri = TourV2("T_FRI", day=4, start_min=840, end_min=1200, duration_min=360)
    d_fri = DutyV2.from_tours("D_FRI", [t_fri])

    # Monday 13:00 - 19:00 (Start 780, End 1140)
    t_mon = TourV2("T_MON", day=0, start_min=780, end_min=1140, duration_min=360)
    d_mon = DutyV2.from_tours("D_MON", [t_mon])
    
    # 2. Setup SPPRC manually
    tours_map = {0: [t_mon], 4: [t_fri]}
    factory = DutyFactoryTopK(tours_map)
    pricer = SPPRCPricer(factory)
    
    # 3. Simulate Checking Logic (from spprc.py)
    # days_diff from Fri(4) to Mon(0 next week) is usually treated as...
    # Wait, SPPRC sorted_days depends on input.
    # If we pass [0, 1, 2, 3, 4], Fri is day 4. Mon is Day 0 (next week? No, Day 0 is first day).
    # SPPRC Graph is DAG: Day 0 -> Day 1 -> ...
    # So to test Fri->Mon, we need Fri as Day 0 and Mon as Day 3 (gap=3).
    
    # Let's map Fri=0, Sat=1, Sun=2, Mon=3.
    object.__setattr__(t_fri, 'day', 0)
    object.__setattr__(t_mon, 'day', 3)
    
    # Manually check logic
    prev_end = t_fri.end_min # 1200
    days_diff = 3
    min_rest = 660
    window = 720
    
    min_start_rel = prev_end + min_rest - (days_diff * 1440)
    # 1200 + 660 - 4320 = 1860 - 4320 = -2460
    
    search_start = max(0, min_start_rel) # 0
    search_end = search_start + window   # 720 (12:00)
    
    mon_start = t_mon.start_min # 780 (13:00)
    
    print(f"Fri End: {prev_end}")
    print(f"Mon Start: {mon_start}")
    print(f"Rel Start Calc: {min_start_rel}")
    print(f"Window: [{search_start}, {search_end}]")
    
    if search_start <= mon_start <= search_end:
        print("RESULT: SUCCESS - Linkable")
    else:
        print(f"RESULT: FAIL - Not Linkable (Start {mon_start} outside window)")

if __name__ == "__main__":
    test_gap_linking()
