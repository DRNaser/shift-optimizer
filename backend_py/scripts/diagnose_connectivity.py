"""
Diagnose Connectivity (Rule 1 Check).
Instruments the actual connectivity between days to see if valid 5-day rosters exist in the search space.
"""
import sys
import os
import logging
from collections import Counter
from pathlib import Path

# Add src to path
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
sys.path.append(str(backend_dir))
sys.path.append(str(backend_dir / "src"))

from test_forecast_csv import parse_forecast_file
from core_v2.duty_factory import DutyFactoryTopK, DutyFactoryCaps
from core_v2.validator.rules import ValidatorV2, RULES
from core_v2.model.duty import DutyV2

logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')
logger = logging.getLogger("ConnectivityDiag")

def calculate_rest(d1: DutyV2, d2: DutyV2) -> int:
    abs_end_1 = d1.day * 1440 + d1.end_min
    abs_start_2 = d2.day * 1440 + d2.start_min
    return abs_start_2 - abs_end_1

def check_connection(d1: DutyV2, d2: DutyV2) -> str:
    if d2.day <= d1.day:
        return "FAIL:SameOrBackwardDay"
    
    rest = calculate_rest(d1, d2)
    if rest < RULES.MIN_REST_MINUTES:
        return f"FAIL:Rest({rest} < {RULES.MIN_REST_MINUTES})"
        
    return "OK"

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_connectivity.py <csv_file>")
        return

    csv_path = sys.argv[1]
    logger.info(f"Loading {csv_path}...")
    
    tours = parse_forecast_file(csv_path)
    logger.info(f"Loaded {len(tours)} tours.")
    
    # 1. Group by day
    tours_by_day = {}
    for t in tours:
        tours_by_day.setdefault(t.day, []).append(t)
        
    # 2. Build Duties (Singletons)
    # We focus on singletons because if atomic duties can't connect, nothing can.
    factory = DutyFactoryTopK(tours_by_day)
    
    duties_by_day = {}
    
    # Generate for all days present
    days = sorted(tours_by_day.keys())
    
    logger.info("Generating duties (Singletons only for connectivity check)...")
    for d in days:
        # Use simple duals (empty) to just get singletons + top K pairs
        # But for connectivity, we mainly care about Singletons forming the "backbone"
        # We can simulate the Factory call
        # Use default caps to avoid runtime error
        all_duties = factory.get_day_duties(d, {})
        
        # OPTIMIZATION: Filter for Singletons Only (Atomic Connectivity)
        # Checking 13k * 8k duties is too slow (100M+ checks).
        # We only need to know if the ATOMS connect.
        duties = [d for d in all_duties if len(d.tour_ids) == 1]
        
        duties_by_day[d] = duties
        logger.info(f"Day {d}: {len(duties)} singletons (of {len(all_duties)} total generated).")

    # 3. Check Connectivity (D -> D+1)
    logger.info("\n--- ADJACENCY REPORT ---")
    
    for i in range(len(days) - 1):
        day_a = days[i]
        day_b = days[i+1]
        
        duties_a = duties_by_day[day_a]
        duties_b = duties_by_day[day_b]
        
        logger.info(f"\nChecking transition Day {day_a} -> Day {day_b}")
        logger.info(f"Duties A: {len(duties_a)} | Duties B: {len(duties_b)}")
        logger.info(f"Potential Arcs: {len(duties_a) * len(duties_b)}")
        
        # Stats
        out_degree = []
        reject_reasons = Counter()
        total_arcs = 0
        
        # Sampling for "dead ends"
        dead_ends = []
        
        for u in duties_a:
            valid_successors = 0
            # Check against ALL B (Exhaustive)
            
            # Optimization: Pre-sort B by start time? 
            # D2.start >= D1.end + 660
            # Since Rest = D2.start + (offset) - D1.end >= 660
            # D2.start >= D1.end + 660 - (offset)
            # We can use binary search but O(N*M) for diagnostic of ~500*500 = 250k is fast enough (0.1s).
            
            first_fail_reason = None
            
            for v in duties_b:
                status = check_connection(u, v)
                if status == "OK":
                    valid_successors += 1
                else:
                    reject_reasons[status] += 1
                    if not first_fail_reason:
                        first_fail_reason = status
            
            out_degree.append(valid_successors)
            total_arcs += valid_successors
            
            if valid_successors == 0:
                dead_ends.append((u, first_fail_reason))
        
        # Report
        zero_out = sum(1 for x in out_degree if x == 0)
        pct_zero = (zero_out / len(duties_a)) * 100 if duties_a else 0
        
        sorted_out = sorted(out_degree)
        p50 = sorted_out[int(0.5 * len(sorted_out))] if sorted_out else 0
        p90 = sorted_out[int(0.9 * len(sorted_out))] if sorted_out else 0
        
        logger.info(f"  Total Valid Arcs: {total_arcs}")
        logger.info(f"  Out-Degree Zero: {zero_out} ({pct_zero:.1f}%)")
        logger.info(f"  Out-Degree P50: {p50} | P90: {p90}")
        
        logger.info("  Top Reject Reasons:")
        for reason, count in reject_reasons.most_common(5):
             logger.info(f"    - {reason}: {count}")
             
        if pct_zero > 10.0:
            logger.warning("  HIGH DEAD-END RATE!")
            logger.info("  Sample Dead Ends (Duty -> First Fail Reason):")
            for d, r in dead_ends[:5]:
                logger.info(f"    - {d.duty_id} (End: {d.end_min}min) -> {r}")

    # 4. EXISTENCE PROOF (DFS)
    logger.info("\n--- EXISTENCE PROOF (Random DFS) ---")
    logger.info("Attempting to construct 6-day rosters...")
    
    full_rosters = []
    attempts = 0
    max_attempts = 1000
    
    import random
    
    # Pre-build adjacency for a subset to speed up DFS?
    # No, just do random walk.
    
    day0_duties = duties_by_day.get(0, [])
    # Shuffle start duties
    random.shuffle(day0_duties)
    
    for start_duty in day0_duties[:max_attempts]:
        path = [start_duty]
        current_duty = start_duty
        
        for k in range(1, len(days)):
            next_day = days[k]
            candidates = duties_by_day.get(next_day, [])
            valid_next = []
            
            # Try to find ONE valid extension
            # Heuristic: shuffle candidates to avoid checking same ones
            # Optimization: check 100 random candidates
            sample_candidates = random.sample(candidates, min(len(candidates), 100))
            
            found = False
            for cand in sample_candidates:
                if check_connection(current_duty, cand) == "OK":
                    current_duty = cand
                    path.append(cand)
                    found = True
                    break
            
            if not found:
                break
        
        if len(path) == len(days):
            full_rosters.append(path)
            if len(full_rosters) >= 10:
                break
                
    logger.info(f"Found {len(full_rosters)} full {len(days)}-day chains out of {max_attempts} attempts.")
    
    if full_rosters:
        logger.info("SUCCESS: The graph contains valid full-week rosters.")
        logger.info("Sample Roster:")
        r = full_rosters[0]
        ids = " -> ".join([d.duty_id for d in r])
        logger.info(f"  {ids}")
        logger.info(f"  Hours: {sum((d.end_min - d.start_min)/60 for d in r):.2f}")
    else:
        logger.error("FAILURE: Could not find ANY full-week roster via random DFS.")
        logger.error("This suggests the graph connectivity is locally fine but globally blocked.")

if __name__ == "__main__":
    main()
