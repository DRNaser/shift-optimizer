"""
Core v2 - SPPRC Pricing Engine

Generates columns with negative reduced cost using Label Setting algorithm.
Graph: DAG (Day 0 -> Day 1 -> ... -> Day N).
Nodes: Duties.
"""

import logging
import math
from typing import Optional, Any

from ..model.duty import DutyV2
from ..model.column import ColumnV2
from ..model.weektype import WeekCategory
from ..validator.rules import ValidatorV2
from .label import Label

logger = logging.getLogger("SPPRC")


class SPPRCPricer:
    """
    Shortest Path Resource Constrained algorithm.
    Finds valid schedules (paths) with negative reduced cost.
    """
    
    def __init__(
        self, 
        duties_by_day: dict[int, list[DutyV2]],
        week_category: WeekCategory = WeekCategory.NORMAL
    ):
        self.duties_by_day = duties_by_day
        self.sorted_days = sorted(duties_by_day.keys())
        self.week_category = week_category
        
        # Hyperparams
        self.max_labels_per_node = 50   # Keep top K labels per duty per step
        self.pruning_active = True

    def price(
        self, 
        duals: dict[str, float],
        max_new_cols: int = 500
    ) -> list[ColumnV2]:
        """
        Generate negative reduced cost columns.
        
        Args:
            duals: Map tour_id -> float (shadow price)
            max_new_cols: Limit specific number of columns to return
        """
        # Labels bucketed by Day -> DutyID -> List[Label]
        # Since graph is DAG by day, we just process days in order.
        
        # 1. Initialize (Day 0..N)
        # Seed labels for single duties on their respective days
        # A partial roster can start on any day.
        
        # We maintain "active labels" list for current expansion frontier?
        # Actually, simpler:
        # labels[day][duty_id] = [Label, ...]
        
        labels_by_day: dict[int, dict[str, list[Label]]] = {
            d: {} for d in self.sorted_days
        }
        
        # 0. Generate "Start" labels (duties acting as start of roster)
        for day in self.sorted_days:
            for duty in self.duties_by_day[day]:
                rc = self._calc_reduced_cost_duty(duty, duals)
                # Note: This RC excludes global penalties (weekly hours) which are non-additive.
                # We handle global penalties by checking them at end? 
                # OR we add partial penalties if possible?
                # Linear penalties (e.g. cost per hour under target) can be additive?
                # "Under 30h" is a step function.
                # We can't model step function perfectly in additive RC unless we check it at finish.
                # We rely on "work_min" dominance to keep paths that MIGHT satisfy it.
                
                lab = Label(
                    path=(duty.duty_id,),
                    last_duty=duty,
                    total_work_min=duty.work_min,
                    days_worked=1,
                    reduced_cost=rc
                )
                if duty.duty_id not in labels_by_day[day]:
                    labels_by_day[day][duty.duty_id] = []
                labels_by_day[day][duty.duty_id].append(lab)

        # 1. Propagate Forward (Dynamic Programming)
        for i, current_day in enumerate(self.sorted_days):
            # For each duty in current day...
            if current_day not in labels_by_day: continue
            
            for duty_id, current_labels in labels_by_day[current_day].items():
                
                # Prune before expanding (keep diverse set)
                # Dominance check already done? Do it again just in case?
                # self._prune_dominated()
                
                # Try to extend to future days
                start_next_idx = i + 1
                for next_day_idx in range(start_next_idx, len(self.sorted_days)):
                    next_day = self.sorted_days[next_day_idx]
                    
                    # Optimization: Don't skip too many days? Max gap?
                    # RULES.MAX_DUTIES_PER_WEEK constraint implies we shouldn't skip too much if we want hours?
                    # But legal gap can be anything.
                    
                    for next_duty in self.duties_by_day[next_day]:
                        # Check connectivity
                        # But wait, we have a list of labels ending at `duty_id`.
                        # Connectivity depends on `duty_id` vs `next_duty`.
                        # Since all labels here end at `duty_id` (= `current_labels[0].last_duty`),
                        # we can check connectivity ONCE for the group.
                        prev_duty = current_labels[0].last_duty
                        
                        if ValidatorV2.can_chain_days(prev_duty, next_duty):
                            # Extension valid. Extend ALL labels.
                            duty_rc_delta = self._calc_reduced_cost_duty(next_duty, duals)
                            
                            for lab in current_labels:
                                new_rc = lab.reduced_cost + duty_rc_delta
                                new_work = lab.total_work_min + next_duty.work_min
                                new_days = lab.days_worked + 1
                                
                                new_lab = Label(
                                    path=lab.path + (next_duty.duty_id,),
                                    last_duty=next_duty,
                                    total_work_min=new_work,
                                    days_worked=new_days,
                                    reduced_cost=new_rc
                                )
                                
                                if next_duty.duty_id not in labels_by_day[next_day]:
                                    labels_by_day[next_day][next_duty.duty_id] = []
                                
                                # Add and Prune immediately to keep list small
                                self._add_with_dominance(
                                    labels_by_day[next_day][next_duty.duty_id],
                                    new_lab
                                )

        # 2. Collect Final Columns
        candidates = []
        for day in self.sorted_days:
            for d_id, labs in labels_by_day[day].items():
                for lab in labs:
                    # Finalize Cost (Apply Global Penalties)
                    final_rc = self._finalize_rc(lab)
                    
                    if final_rc < -1e-5: # Negative Reduced Cost
                        candidates.append((final_rc, lab))
        
        # 3. Sort and Select Top-K
        candidates.sort(key=lambda x: x[0]) # Lowest RC first
        selected_candidates = candidates[:max_new_cols]
        
        # Convert to Columns
        # Need to reconstruct full duty objects from IDs?
        # Label has `path` (IDs).
        # We need a map ID->Duty?
        # Or Label could store list of duties? Tuple of strings is lighter.
        # Let's verify we can reconstruct.
        # We have duties_by_day. I can build a lookup map in init.
        
        # Hack: Just rebuild map now
        duty_map = {}
        for dlist in self.duties_by_day.values():
            for d in dlist:
                duty_map[d.duty_id] = d
                
        result_cols = []
        for rc, lab in selected_candidates:
            duties = [duty_map[did] for did in lab.path]
            col = ColumnV2.from_duties(
                col_id=f"prc_{lab.path[0]}_{lab.path[-1]}", # Temp ID, will be hashed anyway
                duties=duties,
                origin="pricing"
            )
            result_cols.append(col)
            
        return result_cols

    def _calc_reduced_cost_duty(self, duty: DutyV2, duals: dict) -> float:
        """
        RC contribution of a single duty.
        Delta = BaseCost(Duty) - Sum(Duals)
        
        BaseCost is amortized?
        Driver cost is 1.0 globally.
        Let's say per-day cost is 0.0?
        And we add 1.0 at the end (for "Is Active")?
        Yes, adding 1.0 at start (first duty) or end is correct.
        Let's add 1.0/N? No, N is unknown.
        Let's add 1.0 to the "Start Label" or "Finalize".
        Let's do Finalize.
        So here: Delta = 0 - Sum(Duals).
        """
        dual_sum = sum(duals.get(tid, 0.0) for tid in duty.tour_ids)
        return -dual_sum

    def _finalize_rc(self, lab: Label) -> float:
        """
        Apply global costs (Base + Penalties) to get final RC.
        """
        # 1. Base Driver Cost
        cost = 1.0
        
        # 2. Utilization Penalties (Non-additive)
        hours = lab.total_work_min / 60.0
        
        if self.week_category == WeekCategory.COMPRESSED:
            # Stage 4 Objective: Min Sum Underutil (Target 33h)
            # Stage 2 Gate: < 30h hard penalty
            underutil = max(0.0, 33.0 - hours)
            cost += underutil * 0.1 # Small weight to guide generation towards fuller rosters
            
            if hours < 30.0: cost += 0.5 # Harder penalty for gate
            if hours < 20.0: cost += 1.0
        else: # NORMAL
            underutil = max(0.0, 38.0 - hours)
            cost += underutil * 0.1
            
            if hours < 35.0: cost += 0.5
            
        if len(lab.path) == 1:
            cost += 0.2
            
        # 3. Accumulated RC from duties (which was just -Duals)
        return cost + lab.reduced_cost

    def _add_with_dominance(self, existing: list[Label], new_lab: Label):
        """
        Add new_lab to existing list, keeping it Pareto-optimal.
        """
        # Check if dominated by any existing
        for ex in existing:
            if ex.dominates(new_lab):
                return # Reject
        
        # Remove any existing dominated by new
        # "existing[:] = ..." modifies list in place
        existing[:] = [ex for ex in existing if not new_lab.dominates(ex)]
        
        existing.append(new_lab)
        
        # Safety Cap
        if len(existing) > self.max_labels_per_node:
            # Heuristic prune: Sort by RC and keep best
            existing.sort(key=lambda l: l.reduced_cost)
            del existing[self.max_labels_per_node:]
