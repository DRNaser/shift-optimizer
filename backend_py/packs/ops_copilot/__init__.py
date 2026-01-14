"""
Ops-Copilot Pack - WhatsApp AI Operations Assistant

A LangGraph-powered AI assistant for operations staff accessible via WhatsApp.

Features:
- OTP-based pairing (admin invite + user activation)
- Multi-tenant isolation (RLS + app-level)
- 2-phase commit for writes (prepare -> CONFIRM -> commit)
- Episodic memory persistence
- Tenant-scoped playbooks
- Internal ticketing system
- Broadcast messaging (ops: free text, driver: templates + opt-in)

Version: 1.0.0
"""

__version__ = "1.0.0"
__pack_name__ = "ops_copilot"

from .config import OpsCopilotConfig

__all__ = ["OpsCopilotConfig", "__version__", "__pack_name__"]
