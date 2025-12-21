"""
ERROR SCHEMA - RFC 7807 Problem Details
========================================
Consistent error response format for all API endpoints.

Usage:
    from src.api.error_schema import ProblemDetails, create_problem_response
    
    raise HTTPException(
        status_code=400,
        detail=ProblemDetails(
            title="Invalid Tour Data",
            status=400,
            detail="Tour T001 has invalid time range",
            reason_code="INVALID_TIME_RANGE",
        ).model_dump()
    )
"""

from pydantic import BaseModel, Field
from typing import Optional
import uuid


class ProblemDetails(BaseModel):
    """
    RFC 7807 Problem Details for HTTP APIs.
    
    Provides consistent, machine-readable error responses with:
    - Standard fields (type, title, status, detail, instance)
    - Extension fields (correlation_id, reason_code)
    """
    
    type: str = Field(
        default="about:blank",
        description="URI reference identifying the problem type"
    )
    title: str = Field(
        ...,
        description="Short, human-readable summary of the problem"
    )
    status: int = Field(
        ...,
        description="HTTP status code"
    )
    detail: Optional[str] = Field(
        default=None,
        description="Human-readable explanation specific to this occurrence"
    )
    instance: Optional[str] = Field(
        default=None,
        description="URI reference identifying the specific occurrence"
    )
    
    # Extension fields
    correlation_id: Optional[str] = Field(
        default=None,
        description="Unique ID for tracing this request across logs"
    )
    reason_code: Optional[str] = Field(
        default=None,
        description="Machine-readable code for the error type"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "about:blank",
                "title": "Invalid Request",
                "status": 400,
                "detail": "Tour T001 has start_time after end_time",
                "correlation_id": "abc123-def456",
                "reason_code": "INVALID_TIME_RANGE"
            }
        }


def create_problem_response(
    title: str,
    status: int,
    detail: Optional[str] = None,
    reason_code: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """
    Create a ProblemDetails response dictionary.
    
    Args:
        title: Short summary of the problem
        status: HTTP status code
        detail: Detailed explanation (optional)
        reason_code: Machine-readable error code (optional)
        correlation_id: Request correlation ID (optional, generated if None)
    
    Returns:
        Dictionary suitable for HTTPException detail
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())[:8]
    
    return ProblemDetails(
        title=title,
        status=status,
        detail=detail,
        reason_code=reason_code,
        correlation_id=correlation_id,
    ).model_dump(exclude_none=True)


# Common error types
class ErrorTypes:
    """Standard error type URIs (optional, extend as needed)."""
    
    VALIDATION_ERROR = "/errors/validation"
    SOLVER_TIMEOUT = "/errors/solver-timeout"
    SOLVER_INFEASIBLE = "/errors/solver-infeasible"
    BUDGET_OVERRUN = "/errors/budget-overrun"
    NOT_FOUND = "/errors/not-found"
    INTERNAL_ERROR = "/errors/internal"
