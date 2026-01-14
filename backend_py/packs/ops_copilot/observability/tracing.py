"""
Ops-Copilot Structured Logging and Tracing

Provides trace context propagation and structured logging helpers.
"""

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
import json

# Context variables for trace propagation
_trace_context: ContextVar[Optional["TraceContext"]] = ContextVar(
    "ops_copilot_trace_context",
    default=None,
)

logger = logging.getLogger(__name__)


@dataclass
class TraceContext:
    """Trace context for request correlation."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: Optional[str] = None
    tenant_id: Optional[int] = None
    site_id: Optional[int] = None
    wa_user_id: Optional[str] = None
    user_id: Optional[str] = None
    intent: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "wa_user_id": self.wa_user_id,
            "user_id": self.user_id,
            "intent": self.intent,
        }

    def update(self, **kwargs) -> "TraceContext":
        """Update context with new values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self


def get_trace_context() -> Optional[TraceContext]:
    """Get current trace context."""
    return _trace_context.get()


def set_trace_context(ctx: TraceContext) -> None:
    """Set trace context for current request."""
    _trace_context.set(ctx)


def clear_trace_context() -> None:
    """Clear trace context."""
    _trace_context.set(None)


def create_trace_context(
    trace_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    tenant_id: Optional[int] = None,
    site_id: Optional[int] = None,
    wa_user_id: Optional[str] = None,
) -> TraceContext:
    """
    Create and set a new trace context.

    Args:
        trace_id: Optional trace ID (generated if not provided)
        thread_id: Conversation thread ID
        tenant_id: Tenant ID
        site_id: Site ID
        wa_user_id: WhatsApp user ID

    Returns:
        New TraceContext instance
    """
    ctx = TraceContext(
        trace_id=trace_id or str(uuid.uuid4()),
        thread_id=thread_id,
        tenant_id=tenant_id,
        site_id=site_id,
        wa_user_id=wa_user_id,
    )
    set_trace_context(ctx)
    return ctx


# =============================================================================
# Structured Logging Helpers
# =============================================================================


class StructuredLogger:
    """Structured logger with automatic trace context injection."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _with_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge trace context with extra fields."""
        ctx = get_trace_context()
        result = {}
        if ctx:
            result.update(ctx.to_dict())
        if extra:
            result.update(extra)
        result["pack"] = "ops_copilot"
        return result

    def debug(self, msg: str, **kwargs) -> None:
        """Log debug message with trace context."""
        self._logger.debug(msg, extra=self._with_context(kwargs))

    def info(self, msg: str, **kwargs) -> None:
        """Log info message with trace context."""
        self._logger.info(msg, extra=self._with_context(kwargs))

    def warning(self, msg: str, **kwargs) -> None:
        """Log warning message with trace context."""
        self._logger.warning(msg, extra=self._with_context(kwargs))

    def error(self, msg: str, **kwargs) -> None:
        """Log error message with trace context."""
        self._logger.error(msg, extra=self._with_context(kwargs))

    def exception(self, msg: str, **kwargs) -> None:
        """Log exception with trace context."""
        self._logger.exception(msg, extra=self._with_context(kwargs))


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for a module."""
    return StructuredLogger(f"ops_copilot.{name}")


# =============================================================================
# Event Logging
# =============================================================================


@dataclass
class EventLog:
    """Structured event log entry."""

    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[int] = None
    stop_reason: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        ctx = get_trace_context()
        data = {
            "event_type": self.event_type,
            "payload": self.payload,
            "duration_ms": self.duration_ms,
            "stop_reason": self.stop_reason,
            "error_code": self.error_code,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if ctx:
            data.update(ctx.to_dict())
        return json.dumps(data)


def log_event(
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
    stop_reason: Optional[str] = None,
    error_code: Optional[str] = None,
) -> EventLog:
    """
    Log a structured event.

    Args:
        event_type: Type of event (MESSAGE_IN, TOOL_CALL, etc.)
        payload: Event payload data
        duration_ms: Duration in milliseconds
        stop_reason: Why processing stopped
        error_code: Error code if applicable

    Returns:
        EventLog instance
    """
    event = EventLog(
        event_type=event_type,
        payload=payload or {},
        duration_ms=duration_ms,
        stop_reason=stop_reason,
        error_code=error_code,
    )

    # Log the event
    log = get_logger("events")
    log.info(
        event_type,
        event_type=event_type,
        payload=payload,
        duration_ms=duration_ms,
        stop_reason=stop_reason,
        error_code=error_code,
    )

    return event


# =============================================================================
# Timing Context Manager
# =============================================================================


class Timer:
    """Context manager for timing operations."""

    def __init__(self, operation_name: str, log_level: str = "debug"):
        self.operation_name = operation_name
        self.log_level = log_level
        self.start_time: Optional[datetime] = None
        self.duration_ms: Optional[int] = None

    def __enter__(self) -> "Timer":
        self.start_time = datetime.utcnow()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time:
            elapsed = datetime.utcnow() - self.start_time
            self.duration_ms = int(elapsed.total_seconds() * 1000)

            log = get_logger("timing")
            log_method = getattr(log, self.log_level)
            log_method(
                f"{self.operation_name}_completed",
                operation=self.operation_name,
                duration_ms=self.duration_ms,
                error=str(exc_val) if exc_val else None,
            )


def timed(operation_name: str, log_level: str = "debug") -> Timer:
    """Create a timing context manager."""
    return Timer(operation_name, log_level)
