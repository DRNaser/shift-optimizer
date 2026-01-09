"""
KPI Drift Detector - Proactive anomaly detection for solver KPIs.

This skill monitors solver output KPIs against historical baselines
and triggers alerts when significant drift is detected.

Usage:
    python -m backend_py.skills.kpi_drift check --tenant gurkerl --pack roster
    python -m backend_py.skills.kpi_drift report --tenant gurkerl --since 7d
"""

from .detector import KPIDriftDetector, DriftLevel, DriftResult
from .baseline import BaselineComputer, KPIBaseline, MetricBaseline

__all__ = [
    "KPIDriftDetector",
    "DriftLevel",
    "DriftResult",
    "BaselineComputer",
    "KPIBaseline",
    "MetricBaseline",
]
