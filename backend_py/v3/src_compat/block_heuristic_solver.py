
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
import random
from v3.src_compat.models import Block, Tour, Weekday
from v3.src_compat.constraints import HARD_CONSTRAINTS

@dataclass
class DriverState:
    id: str
    driver_type: str  # "FTE" or "PT" (initially all generic, then classified)
    blocks: List[Block] = field(default_factory=list)
    day_map: Dict[Weekday, Block] = field(default_factory=dict) # Max 1 block per day
    total_hours: float = 0.0
    
    def can_assign(self, block: Block, check_rest: bool = True, max_hours: float = 55.0) -> bool:
        # 1. Max 1 block per day
        if block.day in self.day_map:
            return False

        # 2. Max Weekly Hours
        if self.total_hours + block.total_work_hours > max_hours:
            return False

        if not check_rest:
            return True

        # 3. 11h Rest Period
        # Check against previous day block
        prev_day = self._get_adj_day(block.day, -1)
        if prev_day and prev_day in self.day_map:
            prev_block = self.day_map[prev_day]
            if not self._check_rest(prev_block, block):
                return False
            # 4. FATIGUE RULE: No 3er -> 3er on consecutive days
            if len(prev_block.tours) == 3 and len(block.tours) == 3:
                return False

        # Check against next day block
        next_day = self._get_adj_day(block.day, 1)
        if next_day and next_day in self.day_map:
            next_block = self.day_map[next_day]
            if not self._check_rest(block, next_block):
                return False
            # 4. FATIGUE RULE: No 3er -> 3er on consecutive days
            if len(block.tours) == 3 and len(next_block.tours) == 3:
                return False

        return True
        
    def assign(self, block: Block):
        self.blocks.append(block)
        self.day_map[block.day] = block
        self.total_hours += block.total_work_hours
        
    def remove(self, block: Block):
        self.blocks.remove(block)
        del self.day_map[block.day]
        self.total_hours -= block.total_work_hours
        
    def replace(self, old_block: Block, new_block: Block):
        if old_block.day != new_block.day:
             raise ValueError("Can only replace blocks on same day")
        self.remove(old_block)
        self.assign(new_block)

    def _check_rest(self, b1: Block, b2: Block) -> bool:
        # b1 is Day D, b2 is Day D+1
        # Rest = (b2.start + 24h) - b1.end >= 11h * 60
        end_mins = b1.last_end.hour * 60 + b1.last_end.minute
        start_mins = b2.first_start.hour * 60 + b2.first_start.minute
        gap_mins = (start_mins + 24 * 60) - end_mins
        return gap_mins >= 11 * 60

    def _get_adj_day(self, day: Weekday, offset: int) -> Optional[Weekday]:
        # Simple German days mapping
        days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
        try:
            idx = days.index(day)
            new_idx = idx + offset
            if 0 <= new_idx < len(days):
                return days[new_idx]
        except ValueError:
            pass # Sunday or invalid
        return None

class BlockHeuristicSolver:
    def __init__(self, blocks: List[Block]):
        self.all_blocks = blocks
        self.drivers: List[DriverState] = []
        self.unassigned_blocks: List[Block] = []
        
    def solve(self, target_fte_count: int = 145):
        print(f"[Heuristic] Starting solve with {len(self.all_blocks)} blocks...")
        
        # Step 1: Min-Cost Flow Assignment
        self._phase_1_min_cost_flow_assignment()
        print(f"[Heuristic] Phase 1 Flow: {len(self.drivers)} drivers assigned.")
        
        # Step 2: Consolidate (Driver Removal) - Still useful to clean up if flow misses something
        self._phase_2_consolidation()
        print(f"[Heuristic] Phase 2: {len(self.drivers)} drivers remaining.")
        
        # Step 3: PT Elimination
        self._phase_3_pt_elimination()
        print(f"[Heuristic] Phase 3: Final Optimization complete.")
        
        return self.drivers

    def _phase_1_min_cost_flow_assignment(self):
        """
        Builds a Min-Cost Max-Flow network (equivalent to Min Path Cover) to cover all blocks
        with minimal drivers (paths).
        
        Nodes: Source(S), Sink(T), and for each Block B => B_in, B_out.
        Edges:
          S -> B_in  (Cost 0, Cap 1) [Start of a Driver]
          B_out -> T (Cost 0, Cap 1) [End of a Driver]
          B_in -> B_out (Cost -10000, Cap 1) [Covering block reward]
          B_out -> C_in (Cost 10-100, Cap 1) [Transition B -> C if valid]
            - Cost based on quality (gap size, or just 0 for simple path cover)
        
        Wait, standard min path cover in DAG:
        Minimize paths = Minimize starts.
        Bi-partite matching formulation is cleaner for this specific problem "Min Drivers".
        
        Bipartite Graph:
        Left Nodes: Blocks (as potential predecessors)
        Right Nodes: Blocks (as potential successors)
        Edge L_i -> R_j if Block j can follow Block i.
        
        Max Matching M on this graph.
        Number of Paths (Drivers) = Total Blocks - |M|.
        
        We use SimpleMinCostFlow to also pick 'good' connections (low cost) among the max matching.
        
        Network:
          Source -> Left_i (Cap 1, Cost 0)
          Right_i -> Sink (Cap 1, Cost 0)
          Left_i -> Right_j (Cap 1, Cost=transition_cost) if valid(i,j)
        
        Flow Amount = Max Matching Size. We iterate flow?
        Or just push Max Flow.
        Then for every flow i->j, we link them.
        Unmatched Left_i are ends of tours.
        Unmatched Right_j are starts of tours.
        """
        from ortools.graph.python import min_cost_flow
        
        # 1. Setup
        smcf = min_cost_flow.SimpleMinCostFlow()
        
        # Indices
        # 0: Source
        # 1: Sink
        # 2..N+1: Left Nodes (Blocks)
        # N+2..2N+1: Right Nodes (Blocks)
        
        N = len(self.all_blocks)
        source = 0
        sink = 1
        
        # Sort blocks by ID or day/start to ensure deterministic node indices
        # They should be sorted by day/time already from partitioning, but let's be safe
        sorted_blocks = sorted(self.all_blocks, key=lambda b: (b.day.value, b.tours[0].start_time))
        block_map = {b.id: i for i, b in enumerate(sorted_blocks)}
        
        left_offset = 2
        right_offset = 2 + N
        
        # Add Source/Sink edges
        # COST FIX:
        # Source -> Left_i (Start Driver): High Cost (Penalty for new driver) = 100,000
        # Left_i -> Right_i (Cover Block): Huge Reward (Force cover) = -1,000,000
        # Right_i -> Left_j (Link): Low Cost (Gap)
        # Sink -> Source: Cost 0
        
        # New Logic for "nodes":
        # In this bipartite graph, u->v is a LINK.
        # But we need to represent "Block Coverage" vs "Link".
        # Current graph:
        # S -> Left(u) -> Right(v) -> T
        # Flow 1 on S->Left(u) means u is a START.
        # Flow 1 on Left(u)->Right(v) means u->v is a LINK.
        # Flow 1 on Right(v)->T means v is an END.
        
        # Wait, the previous graph was:
        # S -> Left_i [Cap 1, Cost 0]
        # Right_i -> T [Cap 1, Cost 0]
        # Left_i -> Right_j [Link i->j]
        # The internal "Check" was B_in -> B_out? No, that was in docstring.
        # Code: smcf.add_arc(source, left + i, 1, 0)
        
        # Correct Bipartite Matching for Min Path Cover:
        # Minimize edges in matching? No, Maximize edges in matching = Minimize Paths.
        # Each edge (i->j) saves 1 driver.
        # So Edge (i->j) must have Negative Cost (Reward).
        # S->L and R->T can be 0.
        
        # Let's use that simple logic:
        # Reward for Link = -100,000
        # Penalty for Link Quality = +Gap
        # Net Cost = -100,000 + Gap
        
        # If we just do that:
        # S->L cost 0
        # R->T cost 0
        # L->R cost -100,000 + Gap
        # T->S cost 0 (Circulation)
        
        # Then Solver maximizes Links.
        # Total Cost = (-100k + Gap) * Links.
        # 10 Links = -1M. 1 Link = -100k.
        # Solver prefers 10 Links. Correct.
        
        for i in range(N):
            # Source -> Left_i (Supply candidates)
            smcf.add_arc_with_capacity_and_unit_cost(source, left_offset + i, 1, 0)
            
            # Right_i -> Sink (Demand candidates)
            smcf.add_arc_with_capacity_and_unit_cost(right_offset + i, sink, 1, 0)
            
        # Add Transitions
        from collections import defaultdict
        blocks_by_day = defaultdict(list)
        for b in sorted_blocks:
            blocks_by_day[b.day].append(b)
            
        days = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
        
        transition_count = 0
        
        for i, b1 in enumerate(sorted_blocks):
            day_idx = days.index(b1.day)
            
            next_days = []
            if day_idx + 1 < len(days): next_days.append(days[day_idx+1])
            if day_idx + 2 < len(days): next_days.append(days[day_idx+2]) # Gap Day
            
            for next_day in next_days:
                candidates = blocks_by_day[next_day]
                for b2 in candidates:
                    end_mins = b1.last_end.hour * 60 + b1.last_end.minute
                    start_mins = b2.first_start.hour * 60 + b2.first_start.minute
                    
                    day_diff = days.index(next_day) - day_idx
                    total_gap_mins = (start_mins + day_diff * 24 * 60) - end_mins
                    
                    if total_gap_mins < 11 * 60:
                        continue 
                    
                    # FATIGUE RULE:
                    # After a Triple (3er), max next is Double (2er).
                    # 3er -> 3er is FORBIDDEN to prevent burnout.
                    if len(b1.tours) == 3 and len(b2.tours) == 3:
                        continue
                    
                    # Cost: Reward -100,000 for linking + small penalty for gap
                    cost = -100000 + int(total_gap_mins / 60)
                    
                    u = left_offset + i
                    v = right_offset + block_map[b2.id]
                    smcf.add_arc_with_capacity_and_unit_cost(u, v, 1, cost)
                    transition_count += 1
                    
        print(f"[Flow] Graph built: {2*N+2} nodes, {2*N + transition_count} edges.")

        # T -> S (Circulation closes loop)
        # Cost 0. We rely on Link Rewards.
        smcf.add_arc_with_capacity_and_unit_cost(sink, source, N, 0)
        
        # Set node supplies to 0 (Circulation)
        # S and T are just nodes now.
        status = smcf.solve()
        
        if status != smcf.OPTIMAL:
            print("[Flow] Solver failed to find optimal solution!")
            # Fallback to empty (will crash phases, but ok)
            return
            
        print(f"[Flow] Optimal found. Cost: {smcf.optimal_cost()}")
        
        # Reconstruct Paths
        # Edges with flow 1 from Left_i -> Right_j implies b1 -> b2
        
        adj = {}
        matched_rights = set()
        
        for i in range(smcf.num_arcs()):
            if smcf.flow(i) > 0:
                u = smcf.tail(i)
                v = smcf.head(i)
                
                # Check if it is a matching edge (Left -> Right)
                if left_offset <= u < right_offset and right_offset <= v < 2*N+right_offset:
                    # Map back to block indices
                    b1_idx = u - left_offset
                    b2_idx = v - right_offset
                    
                    adj[sorted_blocks[b1_idx].id] = sorted_blocks[b2_idx]
                    matched_rights.add(sorted_blocks[b2_idx].id)
                    
        # Build Drivers (Paths)
        # Start nodes: blocks not in matched_rights
        self.drivers = []
        
        for b in sorted_blocks:
            if b.id not in matched_rights:
                # Start of a chain
                new_driver = DriverState(id=f"D{len(self.drivers)+1:03d}", driver_type="UNK")
                
                curr = b
                while True:
                    # Check verify assignment (should be valid by graph def)
                    # CRITICAL: 55h max weekly hours is a HARD constraint
                    if not new_driver.can_assign(curr, check_rest=False):
                        # 55h limit exceeded! Break the chain and start new driver
                        # This ensures no driver exceeds 55h weekly
                        self.drivers.append(new_driver)
                        new_driver = DriverState(id=f"D{len(self.drivers)+1:03d}", driver_type="UNK")

                    new_driver.assign(curr)
                    
                    if curr.id in adj:
                        curr = adj[curr.id]
                    else:
                        break
                
                self.drivers.append(new_driver)

    def _phase_1_balanced_assignment(self):
        # Legacy
        pass

    def _phase_2_consolidation(self):
        # Iteratively remove drivers with lowest utilization
        improved = True
        while improved:
            improved = False
            # Sort drivers by hours ascending
            sorted_drivers = sorted(self.drivers, key=lambda d: d.total_hours)
            
            for candidate in sorted_drivers:
                # Try to empty this driver
                success = True
                possible_targets = {} 
                
                current_blocks = list(candidate.blocks)
                
                # Find targets for all blocks
                for block in current_blocks:
                    # Potential targets: other drivers, except candidate
                    targets = [d for d in self.drivers if d.id != candidate.id and d.can_assign(block)]
                    if not targets:
                        success = False
                        break
                    target = max(targets, key=lambda d: d.total_hours)
                    possible_targets[block.id] = target
                
                if success:
                    # Execute moves
                    print(f"  [Consolidate] Removing driver {candidate.id} ({candidate.total_hours:.1f}h) - Distributed {len(current_blocks)} blocks")
                    for block in current_blocks:
                        target = possible_targets[block.id]
                        candidate.remove(block)
                        target.assign(block)
                    
                    self.drivers.remove(candidate)
                    improved = True
                    break 

    def _phase_3_pt_elimination(self):
        # Goal: Minimum PT drivers (drivers < 40h)
        # Strategy: Transfers and Swaps
        
        max_passes = 50
        for _ in range(max_passes):
            pt_drivers = [d for d in self.drivers if d.total_hours < 40.0]
            fte_drivers = [d for d in self.drivers if d.total_hours >= 40.0]
            
            if len(pt_drivers) <= 10: 
                 pass

            if not pt_drivers:
                break
                
            progress = False
            
            # Sort PT by hours desc (closest to 40h first)
            pt_drivers.sort(key=lambda d: d.total_hours, reverse=True)
            
            for pt in pt_drivers:
                if pt.total_hours >= 40.0: continue # Might have changed
                
                # 1. Aggressive Transfer: Get block from FTE
                transfer_success = False
                for fte in fte_drivers:
                    # Removed heuristic guard to allow checking all FTEs
                    
                    # Try to find a block to move FTE -> PT
                    for block in list(fte.blocks):
                        if fte.total_hours - block.total_work_hours < 40.0:
                            continue # Constraint: Spender remains >= 40h
                            
                        if pt.can_assign(block):
                            print(f"  [PT-Fix] Transfer {block.id} from {fte.id} ({fte.total_hours:.1f}h) to {pt.id} ({pt.total_hours:.1f}h)")
                            fte.remove(block)
                            pt.assign(block)
                            transfer_success = True
                            progress = True
                            if pt.total_hours >= 40.0:
                                break
                    if transfer_success and pt.total_hours >= 40.0:
                        break
                
                if pt.total_hours >= 40.0:
                    continue # Next PT

                # 2. Day-Swap-Upgrade
                swap_success = False
                for b_pt in list(pt.blocks):
                    for fte in fte_drivers:
                        # Removed heuristic guard
                        
                        if fte.day_map.get(b_pt.day):
                            b_fte = fte.day_map[b_pt.day]
                            
                            if b_fte.total_work_hours <= b_pt.total_work_hours:
                                continue 
                                
                            gain = b_fte.total_work_hours - b_pt.total_work_hours
                            if fte.total_hours - gain < 40.0:
                                continue
                            
                            # Virtual check
                            pt.remove(b_pt)
                            fte.remove(b_fte)
                            
                            legal_pt = pt.can_assign(b_fte)
                            legal_fte = fte.can_assign(b_pt)
                            
                            if legal_pt and legal_fte:
                                print(f"  [PT-Fix] Swap {b_pt.id}<->{b_fte.id} between {pt.id} and {fte.id}. Gain={gain:.1f}h")
                                pt.assign(b_fte)
                                fte.assign(b_pt)
                                swap_success = True
                                progress = True
                                break 
                            else:
                                # Revert
                                pt.assign(b_pt)
                                fte.assign(b_fte)
                    
                    if swap_success: break
            
            if not progress:
                break
