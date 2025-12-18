"""
Log Stream Service
==================
Thread-safe log streaming for SSE (Server-Sent Events).

Usage:
    from src.services.log_stream import emit_log, get_log_generator, clear_logs
    
    emit_log("Starting solver...", "INFO")
    emit_log("Found 100 blocks", "INFO")
"""

import queue
import time
import threading
import logging
import json
from dataclasses import dataclass
from typing import Generator
from enum import Enum


class LogLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


class SSELogHandler(logging.Handler):
    """
    Custom logging handler that emits logs to the SSE stream.
    
    Attach this handler to any logger to have it feed the SSE stream.
    """
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            level = record.levelname
            emit_log(msg, level)
        except Exception:
            pass  # Never break logging


def attach_sse_handler(logger_name: str):
    """Attach SSE handler to a logger by name."""
    log = logging.getLogger(logger_name)
    handler = SSELogHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.setLevel(logging.DEBUG)  # Capture all log levels
    # Avoid duplicates
    for h in log.handlers[:]:
        if isinstance(h, SSELogHandler):
            log.removeHandler(h)
    log.addHandler(handler)
    # Ensure logger level is low enough to capture logs
    if log.level == logging.NOTSET or log.level > logging.DEBUG:
        log.setLevel(logging.DEBUG)


@dataclass
class LogEntry:
    timestamp: float
    level: str
    message: str


# Global log queue - thread-safe
_log_queue: queue.Queue[LogEntry] = queue.Queue(maxsize=1000)
_lock = threading.Lock()


def emit_log(message: str, level: str = "INFO"):
    """
    Emit a log message to the stream.
    
    Thread-safe and non-blocking, drops oldest if queue is full.
    """
    entry = LogEntry(
        timestamp=time.time(),
        level=level,
        message=message,
    )
    
    try:
        _log_queue.put_nowait(entry)
    except queue.Full:
        # Drop oldest and add new
        try:
            _log_queue.get_nowait()
            _log_queue.put_nowait(entry)
        except queue.Empty:
            pass


def clear_logs():
    """Clear all pending logs. Called at start of new solve."""
    with _lock:
        while not _log_queue.empty():
            try:
                _log_queue.get_nowait()
            except queue.Empty:
                break


def get_log_generator() -> Generator[str, None, None]:
    """
    Generator that yields SSE-formatted log entries.
    
    Use with FastAPI's StreamingResponse.
    """
    while True:
        try:
            # Block for up to 1 second waiting for log
            entry = _log_queue.get(timeout=1.0)
            
            # Format as SSE event - use json.dumps for proper escaping
            data = json.dumps({"level": entry.level, "message": entry.message, "ts": entry.timestamp})
            yield f"data: {data}\n\n"
            
        except queue.Empty:
            # Send keepalive ping every second
            yield f": keepalive {time.time()}\n\n"


# Convenience functions for different log levels
def log_info(message: str):
    emit_log(message, LogLevel.INFO)


def log_warn(message: str):
    emit_log(message, LogLevel.WARN)


def log_error(message: str):
    emit_log(message, LogLevel.ERROR)


def log_success(message: str):
    emit_log(message, LogLevel.SUCCESS)
