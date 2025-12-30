"""
Core v2 - Duty Builder

Enumerates all valid daily duties (1, 2, or 3 tours).
"""

from typing import Optional
from itertools import combinations
import logging

from ..model.tour import TourV2
from ..model.duty import DutyV2
from ..validator.rules import ValidatorV2, RULES
from .dominance import prune_dominated_duties

logger = logging.getLogger("DutyBuilder")


class DutyBuilder:
    """
    Constructs all legal 1/2/3-tour duties for a given day.
    """
    
    def __init__(self, validator: type[ValidatorV2] = ValidatorV2):
        self.validator = validator

    def build_duties_for_day(self, day: int, tours: list[TourV2]) -> list[DutyV2]:
        """
        Generate all valid duties for the given day.
        
        Args:
            day: Day index (0-6)
            tours: List of tours for this day
            
        Returns:
            List of valid, unique DutyV2 objects.
        """
        if not tours:
            return []
            
        # Filter tours for this day just in case
        day_tours = [t for t in tours if t.day == day]
        # Sort by start time for efficient combination
        day_tours.sort(key=lambda t: t.start_min)
        
        duties: list[DutyV2] = []
        
        # 1. Single Tours (1er)
        # Always generate these to ensure every tour can be covered (fallback)
        for t in day_tours:
            duties.append(self._create_duty([t]))
            
        # 2. Pairs (2er) - 2 tours
        # O(N^2) but N per day is small (~50-200)
        for i, t1 in enumerate(day_tours):
            for t2 in day_tours[i+1:]:
                # Optimization: fail fast on simple overlap
                if t2.start_min < t1.end_min:
                    continue # Valid because sorted by start_min -> t2 starts later or same, if overlap, invalid.
                             # Actually sorted by start, so t2 >= t1 start.
                             # If overlap strict, t2.start < t1.end checks it.
                
                if self.validator.can_chain_intraday(t1, t2):
                    # Check composite valid (span, count)
                    duty = self._create_duty([t1, t2])
                    is_valid, _ = self.validator.validate_duty(duty)
                    if is_valid:
                        duties.append(duty)
        
        # 3. Triples (3er) - 3 tours
        # Blueprint: 3er allowed only if transitions ok and span ok
        # Limit N^3 complexity: use valid pairs to extend
        # If (t1, t2) is valid, try adding t3
        # But we didn't store pairs explicitly above as objects, just appended.
        # Let's iterate intelligently.
        
        # Build adjacency graph? No, simple nested loop is fine for N=200.
        # Complexity: 200^3 = 8M loop iterations, might be slow in Python if not careful.
        # With sorting and pruning, effective N is smaller.
        # Average valid successors: maybe 5-10?
        # 200 * 10 * 10 = 20k valid triples. Very fast.
        
        for i, t1 in enumerate(day_tours):
            start_idx_2 = i + 1
            for j in range(start_idx_2, len(day_tours)):
                t2 = day_tours[j]
                
                # Fast adjacency check
                if not self.validator.can_chain_intraday(t1, t2):
                    continue
                    
                start_idx_3 = j + 1
                for k in range(start_idx_3, len(day_tours)):
                    t3 = day_tours[k]
                    
                    if self.validator.can_chain_intraday(t2, t3):
                        duty = self._create_duty([t1, t2, t3])
                        is_valid, _ = self.validator.validate_duty(duty)
                        if is_valid:
                            duties.append(duty)
                            
        # Prune / Deduplicate
        unique_duties = prune_dominated_duties(duties)
        
        return unique_duties

    def _create_duty(self, tours: list[TourV2]) -> DutyV2:
        """Helper to instantiate Duty."""
        # Duty ID is not persistent, just needs to be unique for the run
        # Use signature-based ID or counter?
        # Signature is good for dedupe, but ID simpler for readability: "D_{day}_{first_tour}_{count}"
        
        first = tours[0]
        tid = f"d_{first.day}_{first.tour_id}_{len(tours)}"
        # Note: Collisions possible if multiple duties start with same tour?
        # Yes: (t1), (t1, t2), (t1, t3).
        # Need unique ID.
        # Actually DutyV2 is immutable value object.
        # We can use the signature as ID or generate UUID.
        # Let's use signature for ID to be stable.
        
        d = DutyV2.from_tours(duty_id="temp", tours=tours)
        # Patch ID with signature (stable)
        object.__setattr__(d, 'duty_id', f"D_{d.signature[:12]}")
        return d
