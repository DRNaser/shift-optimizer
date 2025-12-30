"""
Core v2 - Duty Dominance & Pruning

Logic to prune dominated duties.
In a rigid tour system (fixed times), dominance is mostly deduplication.
Start simple, expand if flexible breaks are added later.
"""

from collections import defaultdict
from typing import ValuesView

from ..model.duty import DutyV2


def prune_dominated_duties(duties: list[DutyV2]) -> list[DutyV2]:
    """
    Prune duties that are strictly dominated by others.
    
    For fixed-time tours:
    - If two duties cover the exact same tour IDs:
      - They are likely identical.
      - If not (e.g. different metadata), pick the one with better valid status?
      - Or just deduplicate by signature.
      
    Returns:
        List of non-dominated (unique) duties.
    """
    # Group by signature (which is based on tour_ids)
    # Actually signature includes timing? No, DutyV2.signature is day + sorted_tour_ids.
    # So it merges duties covering same tours.
    best_by_sig = {}
    
    for d in duties:
        sig = d.signature
        if sig not in best_by_sig:
            best_by_sig[sig] = d
        else:
            existing = best_by_sig[sig]
            # Tie-breaking logic (if relevant)
            # Prefer valid over invalid
            if d.valid and not existing.valid:
                best_by_sig[sig] = d
            elif d.valid == existing.valid:
                # Same validity, maybe check span? 
                # (For fixed tours, span is identical, but good to be robust)
                if d.span_min < existing.span_min:
                    best_by_sig[sig] = d
                    
    return list(best_by_sig.values())
