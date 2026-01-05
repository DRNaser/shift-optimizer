"""
SOLVEREIGN V3.3a API
====================

Production-ready REST API for shift scheduling optimization.

Modules:
- main: FastAPI application and configuration
- auth: X-API-Key authentication middleware
- dependencies: Shared dependencies (DB, tenant context)
- routers: Endpoint implementations
- schemas: Pydantic request/response models
- repositories: Tenant-scoped data access
"""

__version__ = "3.3.0"
__author__ = "SOLVEREIGN Team"
