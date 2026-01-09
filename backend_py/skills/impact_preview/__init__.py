"""Impact Preview - Change Impact Analyzer for Enterprise Admin Confidence.

Answers the question "Was bricht wenn...?" for every change.
"""

from .analyzer import (
    ChangeImpactAnalyzer,
    ChangeType,
    RiskLevel,
    ImpactResult,
    AffectedTenant,
)

__all__ = [
    "ChangeImpactAnalyzer",
    "ChangeType",
    "RiskLevel",
    "ImpactResult",
    "AffectedTenant",
]
