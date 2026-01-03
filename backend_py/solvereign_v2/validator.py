"""
Solvereign V2 - Validator

Single source of truth for all legal and business constraints.
Migrated from src/core_v2/validator/rules.py
"""

from dataclasses import dataclass
from typing import Optional, Final

from .types import TourV2, DutyV2


@dataclass(frozen=True)
class ValidationRules:
    """
    Hard rules that must NEVER be violated.
    """
    # Time-based
    MAX_WEEKLY_HOURS: float = 55.0
    MAX_DAILY_SPAN_MINUTES: int = 990   # 16.5h Max Spread (Hard Limit)
    MIN_REST_MINUTES: int = 660         # 11 hours
    
    # Count-based
    MAX_TOURS_PER_DAY: int = 3
    MAX_DUTIES_PER_WEEK: int = 6  # 6 working days max (Mon-Sat)


RULES: Final[ValidationRules] = ValidationRules()


class ValidatorV2:
    """
    The Law Layer. Enforces rules on Tours, Duties, and Columns.
    """
    
    @staticmethod
    def validate_duty(duty: DutyV2) -> tuple[bool, Optional[str]]:
        """
        Validate a Duty (intraday checks).
        
        Checks:
        1. Max tours per day
        2. Max span (if constrained)
        """
        # 1. Count
        if len(duty.tour_ids) > RULES.MAX_TOURS_PER_DAY:
            return False, f"Max tours exceeded: {len(duty.tour_ids)} > {RULES.MAX_TOURS_PER_DAY}"
        
        # 2. Span
        if duty.span_min > RULES.MAX_DAILY_SPAN_MINUTES:
            return False, f"Daily span exceeded: {duty.span_min/60:.1f}h > {RULES.MAX_DAILY_SPAN_MINUTES/60:.1f}h"
            
        return True, None

    @staticmethod
    def can_chain_intraday(t1: TourV2, t2: TourV2) -> bool:
        """
        Check if two tours can be chained on the SAME day.
        
        Rules:
        1. t1 ends before t2 starts
        2. t1 and t2 on same day
        """
        if t1.day != t2.day:
            return False
        if t1.end_min > t2.start_min:  # Strict overlap
            return False
        return True

    @staticmethod
    def can_chain_days(d1: DutyV2, d2: DutyV2) -> bool:
        """
        Check if d2 can follow d1 on SUBSEQUENT day(s).
        
        Rules:
        1. d2 is after d1
        2. Rest period >= 11h (660 min)
           Rest = (Start of d2) - (End of d1) + (Days between * 1440)
        """
        if d2.day <= d1.day:
            return False
        
        abs_end_1 = d1.day * 1440 + d1.end_min
        abs_start_2 = d2.day * 1440 + d2.start_min
        
        rest_min = abs_start_2 - abs_end_1
        
        return rest_min >= RULES.MIN_REST_MINUTES
