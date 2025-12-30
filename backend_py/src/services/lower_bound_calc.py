"""
Lower Bound Calculator

Computes realistic lower bounds on the number of drivers required
using Minimum Path Cover on the DAG (Directed Acyclic Graph) of tours.

Algorithm:
Min Path Cover = N - Max Bipartite Matching
Nodes: Tours
Edges: tour_i -> tour_j if compatible
- In-day: end_i + GAP <= start_j
- Cross-day: end_i + 11h <= start_j

This provides a mathematically proven minimum number of drivers needed
to cover all tours, respecting simple adjacency constraints.
"""

from collections import defaultdict
import datetime

# Day mapping for distance calculation (Mon=0, Tue=1, ... Sun=6)
DAY_MAP = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6
}

class LowerBoundCalculator:
    def __init__(self, blocks: list, min_gap_minutes: int = 30, rest_hours: int = 11):
        self.blocks = blocks
        self.min_gap = min_gap_minutes
        self.rest_gap = rest_hours * 60
        self.day_map = DAY_MAP
        self.tours = sorted(blocks, key=lambda b: (self._get_day_index(b.day), b.start_min))

    def _get_day_index(self, day_val):
        if isinstance(day_val, int):
            return day_val
        # Handle Enum or String
        return self.day_map.get(str(day_val), 0)

    def _blocks_compatible(self, b1, b2) -> int:
        """
        Check compatibility. Returns:
        0: Not compatible
        1: Compatible In-Day (chain)
        2: Compatible Cross-Day (rest)
        """
        d1 = self._get_day_index(b1.day)
        d2 = self._get_day_index(b2.day)
        
        if d1 > d2: return 0 
        
        # In-Day
        if d1 == d2:
            if b1.end_min + self.min_gap <= b2.start_min:
                return 1
            return 0
            
        # Cross-Day
        # Time distance from week start (Mon 00:00)
        t1_end = d1 * 24 * 60 + b1.end_min
        t2_start = d2 * 24 * 60 + b2.start_min
        
        if t1_end + self.rest_gap <= t2_start:
            return 2
        return 0

    def compute_min_path_cover(self, subset_blocks, mode="inday") -> int:
        """
        Compute Min Path Cover for a subset of blocks/tours.
        Result = |Nodes| - |Max Matching|
        """
        n = len(subset_blocks)
        if n == 0: return 0
        
        # Build adjacency for matching
        # adjacency[i] = list of j that can follow i
        adj = defaultdict(list)
        
        # Optimization: subset is sorted by time. Only check j > i
        for i in range(n):
            for j in range(i + 1, n):
                b1 = subset_blocks[i]
                b2 = subset_blocks[j]
                
                check = self._blocks_compatible(b1, b2)
                if mode == "inday":
                    if check == 1: # Strict In-Day
                        adj[i].append(j)
                elif mode == "week":
                    if check >= 1: # Any valid sequence
                        adj[i].append(j)

        # Max Bipartite Matching (Hopcroft-Karp or DFS)
        # Using simple DFS for simplicity (N ~ 1000 is fine)
        match_r = {} # Right node -> Left node
        visited = set()
        
        def dfs(u):
            for v in adj[u]:
                if v in visited: continue
                visited.add(v)
                if v not in match_r or dfs(match_r[v]):
                    match_r[v] = u
                    return True
            return False

        matching_size = 0
        for u in range(n):
            visited = set()
            if dfs(u):
                matching_size += 1
                
        return n - matching_size

    def compute_all(self) -> dict:
        """
        Compute all lower bounds.
        """
        results = {}
        
        # 1. Per-Day In-Chain LB
        # Group by day
        by_day = defaultdict(list)
        for b in self.tours:
            by_day[b.day].append(b)
            
        lb_chain_by_day = {}
        max_daily_lb = 0
        
        for day, d_blocks in by_day.items():
            lb = self.compute_min_path_cover(d_blocks, mode="inday")
            lb_chain_by_day[day] = lb
            max_daily_lb = max(max_daily_lb, lb)
            
        results["lb_chain_by_day"] = lb_chain_by_day
        results["lb_chain_week"] = max_daily_lb
        
        # 2. Start-End Compatibility (Simple approximation logic for rest constraint)
        # Or full week path cover (expensive? N=1272 -> N^2 ~1.6M edges. Doable)
        # Let's try Full Week Min Path Cover
        
        lb_final_network = self.compute_min_path_cover(self.tours, mode="week")
        results["lb_final"] = lb_final_network
        
        # Estimate 'Rest Constraint' impact
        # Difference between sum(daily_lb) and week_lb? Not really.
        # Just use lb_final as the main truth.
        
        results["fleet_peak"] = 0 # Placeholder, usually computed externally
        
        return results

def compute_lower_bounds_wrapper(blocks: list, log_fn=None, fleet_peak: int = 0, total_hours: float = 0.0) -> dict:
    calc = LowerBoundCalculator(blocks)
    res = calc.compute_all()
    
    # Enrich with external LB factors
    import math
    res["fleet_lb"] = fleet_peak
    res["hours_lb"] = math.ceil(total_hours / 55.0) if total_hours > 0 else 0
    res["graph_lb"] = res.get("lb_final", 0)
    
    # Compute Unified Final LB
    # max(Fleet Peak, Hours/55, Graph Min Path Cover)
    res["final_lb"] = max(res["fleet_lb"], res["hours_lb"], res["graph_lb"])
    
    if log_fn:
        # Standardized Breakdown Line (Task A)
        log_fn(f"[LB] fleet={res['fleet_lb']}, hours={res['hours_lb']}, graph={res['graph_lb']}, final={res['final_lb']}")
        
        # Detailed diagnostics if graph dominates
        if res["graph_lb"] > res["fleet_lb"]:
             log_fn(f"[LB] NOTE: Graph LB ({res['graph_lb']}) > Fleet Peak ({res['fleet_lb']}).") 
             log_fn(f"     This implies structural incompatibility (rest/spread constraints) forcing higher driver count.")

    return res
