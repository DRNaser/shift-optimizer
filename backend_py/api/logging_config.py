"""
SOLVEREIGN V3.3a API - Structured Logging
=========================================

JSON-formatted logging for observability.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from .config import settings


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.

    Output format:
    {
        "timestamp": "2026-01-05T12:00:00.000Z",
        "level": "INFO",
        "logger": "api.main",
        "message": "request_completed",
        "request_id": "abc-123",
        "duration_ms": 45.2,
        ...
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        if hasattr(record, "__dict__"):
            extra_fields = {
                k: v for k, v in record.__dict__.items()
                if k not in (
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "exc_info", "exc_text", "thread", "threadName",
                    "message", "taskName"
                )
                and not k.startswith("_")
            }
            log_data.update(extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter for development."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base_msg = f"{timestamp} [{record.levelname:8}] {record.name}: {record.getMessage()}"

        # Add extra fields
        extra_fields = getattr(record, "extra", {})
        if extra_fields:
            extra_str = " | ".join(f"{k}={v}" for k, v in extra_fields.items())
            base_msg += f" | {extra_str}"

        return base_msg


def setup_logging() -> None:
    """
    Configure application-wide logging.

    Sets up:
    - Root logger configuration
    - JSON or text formatter based on settings
    - Console handler
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.log_level))

    # Set formatter based on configuration
    if settings.log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds tenant context to all log messages.

    Usage:
        logger = LoggerAdapter(get_logger(__name__), {"tenant_id": 1})
        logger.info("Processing request")  # Automatically includes tenant_id
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict]:
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def get_tenant_logger(name: str, tenant_id: int, request_id: str = None) -> LoggerAdapter:
    """
    Get a logger with tenant context pre-populated.

    Args:
        name: Logger name
        tenant_id: Tenant ID to include in all logs
        request_id: Optional request ID

    Returns:
        Logger adapter with tenant context
    """
    extra = {"tenant_id": tenant_id}
    if request_id:
        extra["request_id"] = request_id

    return LoggerAdapter(get_logger(name), extra)
