"""
RLS Leak Harness Skill (Skill 101)
==================================

Validates Row-Level Security isolation by running parallel multi-tenant
operations and verifying no cross-tenant data leakage occurs.

CLI:
    python -m backend_py.skills.rls_leak_harness --tenants 2 --operations 100
    python -m backend_py.skills.rls_leak_harness --tenants 10 --operations 1000 --workers 50
"""

from .harness import RLSLeakHarness

__all__ = ["RLSLeakHarness"]
