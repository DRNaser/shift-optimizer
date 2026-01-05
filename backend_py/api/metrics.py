"""
SOLVEREIGN V3.3a API - Prometheus Metrics
==========================================

Core metrics required for production monitoring:
- solve_duration_seconds (Histogram)
- solve_failures_total (Counter)
- audit_failures_total (Counter)
- http_requests_total (Counter)
- http_request_duration_seconds (Histogram)

Usage:
    from api.metrics import (
        SOLVE_DURATION,
        SOLVE_FAILURES,
        AUDIT_FAILURES,
        record_solve,
        record_audit_failure,
    )
"""

import logging
from prometheus_client import Counter, Histogram, Info, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)


# =============================================================================
# SAFE METRIC REGISTRATION (handles reload/reimport)
# =============================================================================

def _safe_counter(name: str, description: str, labelnames: list = None):
    """Create Counter, return existing if already registered."""
    try:
        return Counter(name, description, labelnames or [])
    except ValueError:
        # Already registered
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise


def _safe_histogram(name: str, description: str, labelnames: list = None, buckets: tuple = None):
    """Create Histogram, return existing if already registered."""
    try:
        kwargs = {}
        if labelnames:
            kwargs['labelnames'] = labelnames
        if buckets:
            kwargs['buckets'] = buckets
        return Histogram(name, description, **kwargs)
    except ValueError:
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise


def _safe_info(name: str, description: str):
    """Create Info metric, return existing if already registered."""
    try:
        return Info(name, description)
    except ValueError:
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise


# =============================================================================
# CORE METRICS (Required by Senior Dev)
# =============================================================================

# Solve duration histogram
SOLVE_DURATION = _safe_histogram(
    'solve_duration_seconds',
    'Duration of solver execution in seconds',
    labelnames=['status'],  # success, failure, timeout
    buckets=(1, 5, 10, 30, 60, 120, 300, 600)
)

# Solve failures counter
SOLVE_FAILURES = _safe_counter(
    'solve_failures_total',
    'Total number of solver failures',
    labelnames=['reason']  # infeasible, timeout, error
)

# Audit failures counter
AUDIT_FAILURES = _safe_counter(
    'audit_failures_total',
    'Total number of audit check failures',
    labelnames=['check_name']  # coverage, overlap, rest, span, fatigue, reproducibility
)

# HTTP metrics
HTTP_REQUESTS = _safe_counter(
    'http_requests_total',
    'Total HTTP requests',
    labelnames=['method', 'endpoint', 'status']
)

HTTP_REQUEST_DURATION = _safe_histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    labelnames=['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# Build info
BUILD_INFO = _safe_info(
    'solvereign_build_info',
    'SOLVEREIGN build information'
)

# Initialize build info
try:
    import subprocess
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--short', 'HEAD'],
        stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    commit = "unknown"

BUILD_INFO.info({
    'version': '3.3.0',
    'commit': commit,
    'component': 'api'
})


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def record_solve(duration_seconds: float, status: str = 'success'):
    """
    Record a solver execution.

    Args:
        duration_seconds: How long the solve took
        status: 'success', 'failure', or 'timeout'
    """
    SOLVE_DURATION.labels(status=status).observe(duration_seconds)
    if status in ('failure', 'timeout'):
        SOLVE_FAILURES.labels(reason=status).inc()


def record_audit_failure(check_name: str):
    """
    Record an audit check failure.

    Args:
        check_name: Name of the failed check (e.g., 'coverage', 'overlap')
    """
    AUDIT_FAILURES.labels(check_name=check_name).inc()


def record_http_request(method: str, endpoint: str, status_code: int, duration_seconds: float):
    """
    Record an HTTP request.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Request path
        status_code: Response status code
        duration_seconds: Request duration
    """
    # Normalize endpoint to avoid cardinality explosion
    # e.g., /api/v1/forecasts/123 -> /api/v1/forecasts/{id}
    normalized = endpoint
    if '/forecasts/' in endpoint:
        parts = endpoint.split('/forecasts/')
        if len(parts) > 1 and parts[1].isdigit():
            normalized = parts[0] + '/forecasts/{id}'
    elif '/plans/' in endpoint:
        parts = endpoint.split('/plans/')
        if len(parts) > 1 and parts[1].split('/')[0].isdigit():
            normalized = parts[0] + '/plans/{id}'

    HTTP_REQUESTS.labels(method=method, endpoint=normalized, status=str(status_code)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, endpoint=normalized).observe(duration_seconds)


def get_metrics_response():
    """Generate Prometheus metrics response."""
    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
