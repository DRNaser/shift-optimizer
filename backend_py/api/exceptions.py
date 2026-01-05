"""
SOLVEREIGN V3.3a API - Custom Exceptions
========================================

Structured exception hierarchy for consistent error handling.
"""

from typing import Any, Optional


class SolvereIgnError(Exception):
    """Base exception for all SOLVEREIGN errors."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


# =============================================================================
# Authentication Errors
# =============================================================================

class AuthenticationError(SolvereIgnError):
    """Base authentication error."""
    pass


class TenantNotFoundError(AuthenticationError):
    """Raised when API key doesn't match any active tenant."""

    def __init__(self, message: str = "Invalid or missing API key"):
        super().__init__(message)


class TenantInactiveError(AuthenticationError):
    """Raised when tenant exists but is deactivated."""

    def __init__(self, tenant_id: int):
        super().__init__(f"Tenant {tenant_id} is inactive")
        self.tenant_id = tenant_id


# =============================================================================
# Resource Not Found Errors
# =============================================================================

class NotFoundError(SolvereIgnError):
    """Base not found error."""
    pass


class ForecastNotFoundError(NotFoundError):
    """Raised when forecast version doesn't exist."""

    def __init__(self, forecast_id: int, tenant_id: Optional[int] = None):
        message = f"Forecast {forecast_id} not found"
        if tenant_id:
            message += f" for tenant {tenant_id}"
        super().__init__(message, {"forecast_id": forecast_id, "tenant_id": tenant_id})
        self.forecast_id = forecast_id
        self.tenant_id = tenant_id


class PlanNotFoundError(NotFoundError):
    """Raised when plan version doesn't exist."""

    def __init__(self, plan_id: int, tenant_id: Optional[int] = None):
        message = f"Plan {plan_id} not found"
        if tenant_id:
            message += f" for tenant {tenant_id}"
        super().__init__(message, {"plan_id": plan_id, "tenant_id": tenant_id})
        self.plan_id = plan_id
        self.tenant_id = tenant_id


# =============================================================================
# Concurrency Errors
# =============================================================================

class ConcurrencyError(SolvereIgnError):
    """Base concurrency error."""
    pass


class SolveLockError(ConcurrencyError):
    """Raised when unable to acquire solve lock (forecast already being solved)."""

    def __init__(self, tenant_id: int, forecast_id: int):
        super().__init__(
            f"Forecast {forecast_id} is currently being solved. Try again later.",
            {"tenant_id": tenant_id, "forecast_id": forecast_id}
        )
        self.tenant_id = tenant_id
        self.forecast_id = forecast_id


class PlanLockedError(ConcurrencyError):
    """Raised when trying to modify a LOCKED plan."""

    def __init__(self, plan_id: int):
        super().__init__(
            f"Plan {plan_id} is LOCKED and cannot be modified.",
            {"plan_id": plan_id}
        )
        self.plan_id = plan_id


# =============================================================================
# Idempotency Errors
# =============================================================================

class IdempotencyConflictError(SolvereIgnError):
    """Raised when idempotency key exists but request hash differs (409 Conflict)."""

    def __init__(self, idempotency_key: str, endpoint: str):
        super().__init__(
            f"Idempotency key '{idempotency_key}' already exists with different request body",
            {"idempotency_key": idempotency_key, "endpoint": endpoint}
        )
        self.idempotency_key = idempotency_key
        self.endpoint = endpoint


# =============================================================================
# Validation Errors
# =============================================================================

class ValidationError(SolvereIgnError):
    """Raised when request validation fails."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details)


class ForecastValidationError(ValidationError):
    """Raised when forecast parsing fails validation."""

    def __init__(self, parse_errors: list[dict], line_count: int):
        super().__init__(
            f"Forecast validation failed: {len(parse_errors)} errors in {line_count} lines",
            {"errors": parse_errors, "line_count": line_count}
        )
        self.parse_errors = parse_errors


# =============================================================================
# State Machine Errors
# =============================================================================

class StateTransitionError(SolvereIgnError):
    """Raised when invalid state transition is attempted."""

    def __init__(self, current_state: str, target_state: str, allowed: list[str]):
        super().__init__(
            f"Invalid state transition: {current_state} -> {target_state}. Allowed: {allowed}",
            {"current": current_state, "target": target_state, "allowed": allowed}
        )
        self.current_state = current_state
        self.target_state = target_state
        self.allowed = allowed


# =============================================================================
# Solver Errors
# =============================================================================

class SolverError(SolvereIgnError):
    """Base solver error."""
    pass


class SolverTimeoutError(SolverError):
    """Raised when solver exceeds timeout."""

    def __init__(self, timeout_seconds: int, forecast_id: int):
        super().__init__(
            f"Solver timeout after {timeout_seconds}s for forecast {forecast_id}",
            {"timeout_seconds": timeout_seconds, "forecast_id": forecast_id}
        )


class SolverInfeasibleError(SolverError):
    """Raised when solver cannot find a feasible solution."""

    def __init__(self, forecast_id: int, reason: Optional[str] = None):
        message = f"No feasible solution for forecast {forecast_id}"
        if reason:
            message += f": {reason}"
        super().__init__(message, {"forecast_id": forecast_id, "reason": reason})


# =============================================================================
# Database Errors
# =============================================================================

class DatabaseError(SolvereIgnError):
    """Base database error."""
    pass


class ConnectionError(DatabaseError):
    """Raised when database connection fails."""
    pass


class TransactionError(DatabaseError):
    """Raised when transaction fails."""
    pass
