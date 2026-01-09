"""
SOLVEREIGN Gurkerl Dispatch Assist Pack
=======================================

MVP module for open shift detection and candidate suggestions.

Google Sheets remains the source of truth for the operational plan.
SOLVEREIGN provides assist functions:
- Detect open shifts
- Suggest eligible candidates
- Rank candidates by scoring
- Write proposals back to Sheets (optional)

Components:
- models.py: Data structures (OpenShift, Candidate, Proposal)
- eligibility.py: Hard constraint filters (absence, rest, max hours)
- scoring.py: Soft ranking (fairness, minimal churn)
- sheet_adapter.py: Google Sheets read/write
- service.py: Orchestration logic
"""

from .models import OpenShift, Candidate, Proposal, ShiftAssignment, DriverState
from .eligibility import EligibilityChecker
from .scoring import CandidateScorer
from .service import DispatchAssistService

__all__ = [
    "OpenShift",
    "Candidate",
    "Proposal",
    "ShiftAssignment",
    "DriverState",
    "EligibilityChecker",
    "CandidateScorer",
    "DispatchAssistService",
]
