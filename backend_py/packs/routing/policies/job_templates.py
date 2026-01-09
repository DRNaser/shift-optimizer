# =============================================================================
# SOLVEREIGN Routing Pack - Job Templates
# =============================================================================
# Service-time templates per service_code.
#
# P0-4: Uses service_code for deterministic template lookup.
# Each service_code maps to a JobTemplate with default durations and requirements.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class JobTemplate:
    """
    Template for a job/service type.

    Defines default service duration, variance, and requirements.
    """
    service_code: str
    base_service_min: int            # Base service time in minutes
    variance_min: int = 0            # Variance (+/-) for uncertainty
    risk_buffer_min: int = 0         # Extra buffer for high-risk stops

    # Requirements
    default_skills: List[str] = None  # Default required skills
    requires_two_person: bool = False

    # Category
    category: str = "DELIVERY"

    def __post_init__(self):
        # Handle mutable default
        if self.default_skills is None:
            object.__setattr__(self, 'default_skills', [])

    def get_service_duration(
        self,
        floor: Optional[int] = None,
        priority: str = "NORMAL",
        no_show_risk: float = 0.0
    ) -> int:
        """
        Calculate service duration with adjustments.

        Args:
            floor: Floor number (adds time for higher floors)
            priority: Stop priority (CRITICAL adds buffer)
            no_show_risk: Historical no-show risk (adds buffer if high)

        Returns:
            Adjusted service duration in minutes
        """
        duration = self.base_service_min

        # Floor adjustment (2 min per floor above ground)
        if floor and floor > 0:
            duration += floor * 2

        # Priority buffer
        if priority == "CRITICAL":
            duration += self.risk_buffer_min

        # No-show risk buffer (add up to 15 min for high-risk)
        if no_show_risk > 0.3:
            duration += int(no_show_risk * 15)

        return duration


# =============================================================================
# JOB TEMPLATES (per Vertical)
# =============================================================================

JOB_TEMPLATES: Dict[str, JobTemplate] = {
    # =========================================================================
    # MediaMarkt Verticals
    # =========================================================================

    "MM_DELIVERY": JobTemplate(
        service_code="MM_DELIVERY",
        base_service_min=10,
        variance_min=5,
        risk_buffer_min=0,
        default_skills=[],
        requires_two_person=False,
        category="DELIVERY"
    ),

    "MM_DELIVERY_LARGE": JobTemplate(
        service_code="MM_DELIVERY_LARGE",
        base_service_min=20,
        variance_min=10,
        risk_buffer_min=5,
        default_skills=["HEAVY_LIFT"],
        requires_two_person=True,
        category="DELIVERY"
    ),

    "MM_DELIVERY_MONTAGE": JobTemplate(
        service_code="MM_DELIVERY_MONTAGE",
        base_service_min=60,
        variance_min=30,
        risk_buffer_min=15,
        default_skills=["MONTAGE_BASIC"],
        requires_two_person=True,
        category="MONTAGE"
    ),

    "MM_ENTSORGUNG": JobTemplate(
        service_code="MM_ENTSORGUNG",
        base_service_min=15,
        variance_min=5,
        risk_buffer_min=0,
        default_skills=["ENTSORGUNG"],
        requires_two_person=False,
        category="ENTSORGUNG"
    ),

    "MM_PICKUP": JobTemplate(
        service_code="MM_PICKUP",
        base_service_min=10,
        variance_min=5,
        risk_buffer_min=0,
        default_skills=[],
        requires_two_person=False,
        category="PICKUP"
    ),

    # =========================================================================
    # HDL Plus Verticals (Montage-focused)
    # =========================================================================

    "HDL_MONTAGE_STANDARD": JobTemplate(
        service_code="HDL_MONTAGE_STANDARD",
        base_service_min=90,
        variance_min=45,
        risk_buffer_min=30,
        default_skills=["MONTAGE_ADVANCED"],
        requires_two_person=True,
        category="MONTAGE"
    ),

    "HDL_MONTAGE_COMPLEX": JobTemplate(
        service_code="HDL_MONTAGE_COMPLEX",
        base_service_min=150,
        variance_min=60,
        risk_buffer_min=45,
        default_skills=["MONTAGE_ADVANCED", "ELEKTRO"],
        requires_two_person=True,
        category="MONTAGE"
    ),

    "HDL_MONTAGE_KITCHEN": JobTemplate(
        service_code="HDL_MONTAGE_KITCHEN",
        base_service_min=240,
        variance_min=90,
        risk_buffer_min=60,
        default_skills=["MONTAGE_ADVANCED", "ELEKTRO", "WASSER"],
        requires_two_person=True,
        category="MONTAGE"
    ),

    "HDL_DELIVERY": JobTemplate(
        service_code="HDL_DELIVERY",
        base_service_min=15,
        variance_min=10,
        risk_buffer_min=5,
        default_skills=[],
        requires_two_person=False,
        category="DELIVERY"
    ),
}

# Default template for unknown service codes
DEFAULT_TEMPLATE = JobTemplate(
    service_code="DEFAULT",
    base_service_min=30,
    variance_min=15,
    risk_buffer_min=10,
    default_skills=[],
    requires_two_person=False,
    category="DELIVERY"
)


def get_template_for_service_code(service_code: str) -> JobTemplate:
    """
    Get job template for a service code.

    P0-4: Deterministic template lookup by service_code.

    Args:
        service_code: The service code (e.g., "MM_DELIVERY_MONTAGE")

    Returns:
        JobTemplate for the service code, or DEFAULT_TEMPLATE if not found
    """
    return JOB_TEMPLATES.get(service_code.upper(), DEFAULT_TEMPLATE)


def list_service_codes() -> List[str]:
    """List all available service codes."""
    return list(JOB_TEMPLATES.keys())


def get_templates_by_category(category: str) -> List[JobTemplate]:
    """Get all templates for a category (DELIVERY, MONTAGE, etc.)."""
    return [t for t in JOB_TEMPLATES.values() if t.category == category.upper()]


def get_templates_by_vertical(vertical: str) -> List[JobTemplate]:
    """
    Get templates for a vertical.

    Args:
        vertical: "MEDIAMARKT" or "HDL_PLUS"

    Returns:
        List of templates for the vertical
    """
    prefix = "MM_" if vertical.upper() == "MEDIAMARKT" else "HDL_"
    return [t for t in JOB_TEMPLATES.values() if t.service_code.startswith(prefix)]
