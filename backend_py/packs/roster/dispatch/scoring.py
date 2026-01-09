"""
SOLVEREIGN Gurkerl Dispatch Assist - Candidate Scoring
=======================================================

Soft ranking criteria for candidate prioritization.

Scoring Dimensions (weights configurable):
1. Fairness: Gap to target hours (under-target drivers preferred)
2. Minimal Churn: Prefer drivers already working that day (avoid new callouts)
3. Zone Affinity: Prefer drivers in the shift's zone
4. Part-Time Balance: Consider PT vs FT preferences
5. Recency: Avoid over-using same drivers

Lower score = better candidate (golf scoring).
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from .models import OpenShift, Candidate, DriverState

logger = logging.getLogger(__name__)


# =============================================================================
# SCORING WEIGHTS (Default Configuration)
# =============================================================================

@dataclass
class ScoringWeights:
    """
    Weights for scoring dimensions.

    Each weight multiplies the raw score for that dimension.
    Higher weight = more important factor.
    """
    fairness: float = 10.0          # Under-target hours is good
    churn: float = 5.0              # Prefer already-working drivers
    zone_affinity: float = 3.0      # Prefer same-zone drivers
    part_time_balance: float = 2.0  # Balance PT usage
    recency: float = 1.0            # Avoid over-use
    skill_match: float = 2.0        # Extra points for skill match


# =============================================================================
# CANDIDATE SCORER
# =============================================================================

class CandidateScorer:
    """
    Scores and ranks eligible candidates for an open shift.

    Scoring uses golf-style (lower = better) with weighted dimensions.
    """

    def __init__(self, weights: Optional[ScoringWeights] = None):
        """
        Initialize with scoring weights.

        Args:
            weights: Scoring weights (uses defaults if None)
        """
        self.weights = weights or ScoringWeights()

    def score_candidates(
        self,
        candidates: List[Candidate],
        shift: OpenShift,
        all_drivers: Optional[Dict[str, DriverState]] = None,
    ) -> List[Candidate]:
        """
        Score and rank all candidates for a shift.

        Args:
            candidates: List of candidates (eligible and ineligible)
            shift: The open shift
            all_drivers: Optional dict of driver_id -> DriverState for context

        Returns:
            List of candidates sorted by score (best first)
        """
        all_drivers = all_drivers or {}

        for candidate in candidates:
            if not candidate.is_eligible:
                # Ineligible candidates get max score
                candidate.score = float('inf')
                candidate.score_breakdown = {"ineligible": float('inf')}
                continue

            driver = all_drivers.get(candidate.driver_id)
            self._score_candidate(candidate, shift, driver)

        # Sort by score (lower = better)
        sorted_candidates = sorted(candidates, key=lambda c: c.score)

        # Assign ranks
        for i, candidate in enumerate(sorted_candidates):
            candidate.rank = i + 1
            if candidate.is_eligible:
                candidate.reasons = self._build_reasons(candidate, shift)

        eligible_count = sum(1 for c in sorted_candidates if c.is_eligible)
        if eligible_count > 0:
            best = sorted_candidates[0]
            logger.info(
                f"Scored {eligible_count} eligible candidates for shift {shift.id}. "
                f"Best: {best.driver_name} (score={best.score:.2f})"
            )

        return sorted_candidates

    def _score_candidate(
        self,
        candidate: Candidate,
        shift: OpenShift,
        driver: Optional[DriverState],
    ) -> None:
        """
        Calculate score for a single candidate.

        Lower score = better candidate.
        """
        breakdown: Dict[str, float] = {}
        total_score = 0.0

        # 1. Fairness Score: Prefer under-target drivers
        # Positive gap (under target) = good = lower score
        # Negative gap (over target) = bad = higher score
        fairness_raw = -candidate.fairness_score  # Negate: under-target is negative gap
        breakdown["fairness"] = fairness_raw * self.weights.fairness
        total_score += breakdown["fairness"]

        # 2. Churn Score: Prefer already-working drivers
        # If driver has shifts today, they're already "in the system"
        if driver and len(driver.shifts_today) > 0:
            breakdown["churn"] = 0  # No penalty - already working
        else:
            breakdown["churn"] = 10 * self.weights.churn  # Penalty for new callout
        total_score += breakdown["churn"]

        # 3. Zone Affinity: Prefer drivers in the shift's zone
        if shift.zone and driver:
            if shift.zone in driver.home_zones:
                breakdown["zone"] = 0  # No penalty
            elif not driver.home_zones:
                breakdown["zone"] = 5 * self.weights.zone_affinity  # No zone preference
            else:
                breakdown["zone"] = 15 * self.weights.zone_affinity  # Wrong zone
        else:
            breakdown["zone"] = 0
        total_score += breakdown["zone"]

        # 4. Part-Time Balance: Slight preference for FT over PT for regular shifts
        if driver and driver.is_part_time:
            breakdown["pt_balance"] = 5 * self.weights.part_time_balance
        else:
            breakdown["pt_balance"] = 0
        total_score += breakdown["pt_balance"]

        # 5. Skill Match Bonus: Lower score if skills match well
        if shift.required_skills and driver:
            matching_skills = len([s for s in shift.required_skills if s in driver.skills])
            total_skills = len(shift.required_skills)
            if matching_skills == total_skills:
                breakdown["skills"] = -10 * self.weights.skill_match  # Bonus (negative = good)
            else:
                breakdown["skills"] = 0
        else:
            breakdown["skills"] = 0
        total_score += breakdown["skills"]

        # 6. Hours Optimization: Prefer filling closer to target
        # Penalize if assignment would significantly exceed target
        hours_after = candidate.hours_after_assignment
        target = driver.target_weekly_hours if driver else 40.0
        if hours_after > target:
            overage = hours_after - target
            breakdown["hours_opt"] = overage * self.weights.recency
        else:
            breakdown["hours_opt"] = 0
        total_score += breakdown["hours_opt"]

        candidate.score = max(0, total_score)  # No negative scores
        candidate.score_breakdown = breakdown

    def _build_reasons(
        self,
        candidate: Candidate,
        shift: OpenShift,
    ) -> List[str]:
        """Build human-readable reasons for ranking."""
        reasons = []
        breakdown = candidate.score_breakdown

        # Best aspects (negative or zero contributions)
        if breakdown.get("fairness", 0) < 0:
            hours_gap = abs(candidate.fairness_score)
            reasons.append(f"Under target by {hours_gap:.1f}h (fair share)")

        if breakdown.get("churn", 0) == 0:
            reasons.append("Already working today (minimal disruption)")

        if breakdown.get("zone", 0) == 0 and shift.zone:
            reasons.append(f"Works in zone {shift.zone}")

        if breakdown.get("skills", 0) < 0:
            reasons.append("Has all required skills")

        # Concerns (positive contributions)
        if breakdown.get("fairness", 0) > 0:
            reasons.append(f"Already at {candidate.current_weekly_hours:.1f}h this week")

        if breakdown.get("churn", 0) > 0:
            reasons.append("Would require new callout")

        if breakdown.get("hours_opt", 0) > 0:
            reasons.append(f"Would exceed target hours ({candidate.hours_after_assignment:.1f}h after)")

        # Default reason if empty
        if not reasons:
            reasons.append(f"Score: {candidate.score:.2f}")

        return reasons

    def get_top_candidates(
        self,
        candidates: List[Candidate],
        n: int = 3,
        eligible_only: bool = True,
    ) -> List[Candidate]:
        """
        Get top N candidates.

        Args:
            candidates: Scored and sorted candidates
            n: Number of candidates to return
            eligible_only: Only return eligible candidates

        Returns:
            Top N candidates
        """
        if eligible_only:
            pool = [c for c in candidates if c.is_eligible]
        else:
            pool = candidates

        return pool[:n]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def score_and_rank(
    candidates: List[Candidate],
    shift: OpenShift,
    drivers: Optional[Dict[str, DriverState]] = None,
    weights: Optional[ScoringWeights] = None,
) -> List[Candidate]:
    """
    Convenience function to score and rank candidates.

    Args:
        candidates: List of candidates
        shift: The open shift
        drivers: Optional driver state lookup
        weights: Optional custom weights

    Returns:
        Sorted list of candidates (best first)
    """
    scorer = CandidateScorer(weights)
    return scorer.score_candidates(candidates, shift, drivers)


def explain_ranking(candidate: Candidate) -> str:
    """
    Generate human-readable explanation of candidate ranking.

    Args:
        candidate: The candidate

    Returns:
        Explanation string
    """
    if not candidate.is_eligible:
        disqs = [d.details for d in candidate.disqualifications]
        return f"NOT ELIGIBLE: {'; '.join(disqs)}"

    lines = [
        f"Rank #{candidate.rank}: {candidate.driver_name}",
        f"  Score: {candidate.score:.2f}",
        f"  Current hours: {candidate.current_weekly_hours:.1f}h",
        f"  After assignment: {candidate.hours_after_assignment:.1f}h",
        "  Reasons:",
    ]
    for reason in candidate.reasons:
        lines.append(f"    - {reason}")

    return "\n".join(lines)
