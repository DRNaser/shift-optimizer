"""
STRUCTURED LOGGING MODULE
==========================
Centralized logging configuration for production observability.

Features:
- JSON-formatted logs for log aggregation (ELK, CloudWatch, etc.)
- Consistent context fields (run_id, phase, duration)
- Console fallback for development
"""

import json
import logging
import sys
import os
from datetime import datetime
from typing import Optional, Any


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def __init__(self, service_name: str = "shift-optimizer"):
        super().__init__()
        self.service_name = service_name
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add custom context fields if present
        for field in ["run_id", "phase", "duration_s", "drivers", "tours", "status"]:
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)
        
        return json.dumps(log_entry, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for development."""
    
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = record.levelname[0]  # First letter: I, W, E, D
        
        # Add context if present
        context = ""
        if hasattr(record, "run_id"):
            context = f"[{record.run_id}] "
        if hasattr(record, "phase"):
            context += f"[{record.phase}] "
        
        return f"{timestamp} {level} {context}{record.getMessage()}"


def get_logger(name: str, run_id: Optional[str] = None) -> logging.Logger:
    """Get a logger with optional run context."""
    logger = logging.getLogger(name)
    
    # Return existing if already configured
    if logger.handlers:
        return logger
    
    # Determine format based on environment
    use_json = os.getenv("LOG_FORMAT", "console").lower() == "json"
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    handler = logging.StreamHandler(sys.stdout)
    
    if use_json:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.propagate = False
    
    return logger


class LogContext:
    """Context manager for adding structured context to logs."""
    
    def __init__(self, logger: logging.Logger, **kwargs):
        self.logger = logger
        self.context = kwargs
        self._old_factory = None
    
    def __enter__(self):
        self._old_factory = logging.getLogRecordFactory()
        context = self.context
        
        def record_factory(*args, **kwargs):
            record = self._old_factory(*args, **kwargs)
            for key, value in context.items():
                setattr(record, key, value)
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
    
    def __exit__(self, *args):
        logging.setLogRecordFactory(self._old_factory)


def log_phase_start(logger: logging.Logger, phase: str, run_id: str = None, **extra):
    """Log the start of a phase."""
    logger.info(f"Phase started: {phase}", extra={"phase": phase, "run_id": run_id, **extra})


def log_phase_end(logger: logging.Logger, phase: str, duration_s: float, status: str = "OK", run_id: str = None, **extra):
    """Log the end of a phase with duration."""
    logger.info(
        f"Phase completed: {phase} in {duration_s:.2f}s ({status})",
        extra={"phase": phase, "duration_s": duration_s, "status": status, "run_id": run_id, **extra}
    )


def log_kpi(logger: logging.Logger, run_id: str, **kpis):
    """Log KPI metrics."""
    kpi_str = ", ".join(f"{k}={v}" for k, v in kpis.items())
    logger.info(f"KPIs: {kpi_str}", extra={"run_id": run_id, **kpis})
