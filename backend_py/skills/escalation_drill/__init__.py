"""
Escalation Drill Skill (Skill 105)
==================================

Validates the escalation lifecycle works correctly:
1. Create escalation
2. Verify scope is blocked
3. Resolve escalation
4. Verify scope is unblocked

This is a DRILL (template validation), NOT live incident response.

CLI:
    python -m backend_py.skills.escalation_drill --tenant test_tenant
    python -m backend_py.skills.escalation_drill --tenant test --severity S1
"""

from .drill import EscalationDrill

__all__ = ["EscalationDrill"]
