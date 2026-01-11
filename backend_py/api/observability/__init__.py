"""
SOLVEREIGN Observability Module
===============================

Centralized error tracking, APM, and monitoring integrations.
"""

from .sentry import init_sentry, set_sentry_context, capture_exception

__all__ = ["init_sentry", "set_sentry_context", "capture_exception"]
