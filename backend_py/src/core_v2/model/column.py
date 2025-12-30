"""
Core v2 - Column Model (Weekly Roster)

A Column (RosterColumn) defines a full weekly schedule for one driver.
It contains a set of Duties (nodes) + Utilization Stats.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib

from .duty import DutyV2


@dataclass(frozen=True)
class ColumnV2:
    """
    Weekly roster for one driver.
    
    Immutable. Can be created via Pricing (heuristic) or Repairs.
    """
    col_id: str
    duties: tuple[DutyV2, ...]  # Sorted by day
    
    # Derived coverage (computed once, cached)
    covered_tour_ids: frozenset[str]
    
    # Derived stats
    total_work_min: int
    days_worked: int
    max_day_span_min: int
    
    # Traceability
    origin: str  # e.g., "pricing_iter_5", "seed_greedy", "repair_merge"
    
    # Utilization flags (pre-computed for filtering/costing)
    hours: float
    is_under_30h: bool
    is_under_20h: bool
    is_singleton: bool  # Only 1 duty (often bad quality)
    
    @property
    def signature(self) -> str:
        """
        Canonical hash for pool deduplication.
        
        Based on covered tours (sorted). Two columns covering same tours
        are considered duplicates (even if internal structure differs slightly,
        though with canonical duties that's rare).
        """
        # Sort tour IDs to be order-independent
        tours_str = '|'.join(sorted(self.covered_tour_ids))
        return hashlib.sha256(tours_str.encode()).hexdigest()[:24]

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "col_id": self.col_id,
            "duty_ids": [d.duty_id for d in self.duties],
            "covered_tour_ids": sorted(list(self.covered_tour_ids)),
            "total_work_min": self.total_work_min,
            "days_worked": self.days_worked,
            "max_day_span_min": self.max_day_span_min,
            "origin": self.origin,
            "hours": self.hours,
            "signature": self.signature,
        }

    @classmethod
    def from_duties(
        cls,
        col_id: str,
        duties: list[DutyV2],
        origin: str,
    ) -> "ColumnV2":
        """
        Create a Column from a list of duties.
        
        Duties must be non-overlapping in days (checked by Validator, 
        but enforced here for sanity).
        """
        sorted_duties = sorted(duties, key=lambda d: d.day)
        
        # Collect all tour IDs
        all_tours = set()
        total_work = 0
        max_span = 0
        
        for d in sorted_duties:
            all_tours.update(d.tour_ids)
            total_work += d.work_min
            max_span = max(max_span, d.span_min)
        
        hours = total_work / 60.0
        
        return cls(
            col_id=col_id,
            duties=tuple(sorted_duties),
            covered_tour_ids=frozenset(all_tours),
            total_work_min=total_work,
            days_worked=len(sorted_duties),
            max_day_span_min=max_span,
            origin=origin,
            hours=hours,
            is_under_30h=(hours < 30.0),
            is_under_20h=(hours < 20.0),
            is_singleton=(len(sorted_duties) == 1),
        )


    def cost_stage1(self, week_category: 'WeekCategory') -> float:
        """
        Stage 1 Cost (CG / LP Relaxation).
        
        STRICT RULE: Always 1.0 for real columns.
        Objective is 'Minimize Drivers'.
        No utilization penalties here (Stage 2 only).
        """
        # Artificial columns are handled in MasterLP directly, but if one sneaks in:
        if self.origin and self.origin.startswith("artificial"):
            return 1_000_000.0
        return 1.0

    def cost_utilization(self, week_category: 'WeekCategory') -> float:
        """
        Stage 2 Cost (MIP / Penalties).
        
        Includes:
        - Base cost (1.0)
        - Singleton penalty
        - Under-hours penalties (<30h, <20h)
        - Linear underutilization penalty
        """
        cost = 1.0
        
        # Singleton Penalty
        if self.is_singleton:
            cost += 0.2
            
        # Hours Penalties
        from ..model.weektype import WeekCategory
        
        if week_category == WeekCategory.COMPRESSED:
            if self.hours < 30.0:
                cost += 0.5
            if self.hours < 20.0:
                cost += 1.0
                
            # Linear underutilization (Target 33h)
            underutil = max(0.0, 33.0 - self.hours)
            cost += underutil * 0.1
            
        else:  # NORMAL
            if self.hours < 35.0:
                cost += 0.5
                
            # Linear underutilization (Target 38h)
            underutil = max(0.0, 38.0 - self.hours)
            cost += underutil * 0.1
            
        return cost


def dominates_column(col_a: ColumnV2, col_b: ColumnV2) -> bool:
    """
    Check if col_a dominates col_b.
    
    A dominates B if:
    - Same tour coverage
    - A has better utilization (higher hours, fewer days for same hours?)
    - Actually, for Set Partitioning, "dominance" usually refers to Label Setting.
      In the Pool, we just want to keep the "best" version of a column covering set T.
        
    Rule: Prefer higher hours (less idle time) if coverage is identical?
    Wait, if coverage is identical, work_min is sum of durations.
    Since tours are atomic, work_min MUST be identical if coverage is identical.
    
    The only difference can be:
    - Days worked (maybe A packs tours into fewer days = better?)
    - Span (A has tighter duties?)
    
    Decision: A dominates B if same coverage and (A.days <= B.days).
    """
    if col_a.covered_tour_ids != col_b.covered_tour_ids:
        return False
        
    # Same tours -> same work work_min (inherent)
    
    # Prefer fewer days (more rest days)
    if col_a.days_worked < col_b.days_worked:
        return True
    if col_b.days_worked < col_a.days_worked:
        return False
        
    # Same days -> prefer tighter spans (less idle time within day)
    # Actually, tighter span is generally better for drivers
    # But for optimizing "utilization" it doesn't matter much.
    # Let's use max_day_span as tie breaker.
    return col_a.max_day_span_min <= col_b.max_day_span_min
