"""
Core v2 - SPPRC Label (Pricing State)

Represents a partial path (partial roster) in the pricing graph.
Implements dominance logic for determining "Pareto-optimal" partial paths.
"""

from dataclasses import dataclass, field
from ..model.duty import DutyV2


@dataclass(frozen=True)
class Label:
    """
    SPPRC Label state.
    Immutable to allow hashing (though usually not hashed).
    """
    # Path tracking
    path: tuple[str, ...]  # Sequence of duty_ids
    last_duty: DutyV2      # For edge checking
    
    # Resources / State
    total_work_min: int
    days_worked: int
    
    # Cost (Accumulated Reduced Cost)
    # RC = (Real Cost) - (Duals)
    reduced_cost: float
    
    # Covered Tours (for uniqueness/debug, not strictly needed for RC if linear)
    # But needed if we have constraints on specific tours? Set-Partitioning handles that.
    # We mainly track coverage to avoid cycles? (No cycles in DAG time-ordered graph).
    # So coverage is just implicit.
    
    def dominates(self, other: "Label") -> bool:
        """
        Check if this label dominates 'other'.
        
        Dominance Rule:
        A dominates B if:
        1. A.reduced_cost <= B.reduced_cost
        2. A.total_work_min >= B.total_work_min (More work is better to avoid underutil penalty)
        3. A.days_worked <= B.days_worked (Fewer days is better for same work)
        4. A ends at same node? (Handled by bucketing labels per node)
           Wait, graph nodes are Duties. 
           We prune labels AT the same duty? 
           NO, we prune labels at the same DAY (bucketed by day).
           Whatever partial path ending on Day D, can trigger extend to Day D+1.
           BUT they must be comparable.
           If Label A ends at Duty X (Day D) and Label B ends at Duty Y (Day D).
           Can A dominate B?
           Only if X and Y allow EXACTLY same extensions?
           No, Duty X and Y are different nodes.
           Extensions depend on X.end_time vs Next.start_time.
           So we can only dominate labels ending at the SAME DUTY?
           
           Strict SPPRC: Prune at Node. So yes, same last_duty.
           But here we might have too many nodes (duties).
           
           Alternative: "Bucket dominance" at Day level?
           If A ends at Day D (Duty X), B ends at Day D (Duty Y).
           If X.end_time <= Y.end_time (earlier finish = flexible)
           AND work/RC better...
           Maybe. But `can_chain` depends on specific rest.
           Safe bet: Prune only at SAME DUTY.
        
        So dominance only applies if self.last_duty == other.last_duty.
        """
        if self.last_duty is not other.last_duty:
             # Should not happen if we bucket by duty, but safety check
             return False
             
        # 1. Reduced Cost (lower is better)
        if self.reduced_cost > other.reduced_cost:
            return False
            
        # 2. Work (higher is better to clear penalties)
        if self.total_work_min < other.total_work_min:
            return False
            
        # 3. Days (lower is better, nice to have)
        if self.days_worked > other.days_worked:
            return False
            
        return True
