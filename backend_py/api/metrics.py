"""
SOLVEREIGN V3.3a API - Prometheus Metrics
==========================================

Core metrics required for production monitoring:
- solve_duration_seconds (Histogram)
- solve_failures_total (Counter)
- audit_failures_total (Counter)
- http_requests_total (Counter)
- http_request_duration_seconds (Histogram)
- celery_queue_length (Gauge) - P2 FIX: Queue depth visibility

Usage:
    from api.metrics import (
        SOLVE_DURATION,
        SOLVE_FAILURES,
        AUDIT_FAILURES,
        record_solve,
        record_audit_failure,
        update_queue_metrics,
    )
"""

import logging
import os
import time
from prometheus_client import Counter, Histogram, Info, Gauge, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)


# =============================================================================
# SAFE METRIC REGISTRATION (handles reload/reimport)
# =============================================================================

def _safe_counter(name: str, description: str, labelnames: list = None):
    """Create Counter, return existing if already registered."""
    # Counters strip _total suffix from name, e.g. 'solve_failures_total' -> _name='solve_failures'
    # Check both the passed name and the base name (without _total)
    base_name = name.removesuffix('_total') if name.endswith('_total') else name

    # Check if already registered under the base name or the full name
    for check_name in [name, base_name]:
        if check_name in REGISTRY._names_to_collectors:
            collector = REGISTRY._names_to_collectors[check_name]
            if hasattr(collector, '_name') and collector._name == base_name:
                return collector

    try:
        return Counter(name, description, labelnames or [])
    except ValueError:
        # Already registered - find by iterating
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == base_name:
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


def _safe_gauge(name: str, description: str, labelnames: list = None):
    """Create Gauge, return existing if already registered."""
    try:
        return Gauge(name, description, labelnames or [])
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
# CELERY QUEUE METRICS (P2 FIX: Queue Depth Visibility)
# =============================================================================

# Queue depth gauge - tracks pending tasks in Celery queues
CELERY_QUEUE_LENGTH = _safe_gauge(
    'celery_queue_length',
    'Number of pending tasks in Celery queue',
    labelnames=['queue']
)

# Solver memory limit info gauge
SOLVER_MEMORY_LIMIT = _safe_gauge(
    'solver_memory_limit_bytes',
    'Configured memory limit for solver processes',
    labelnames=['component']
)

# Cache for queue metrics (avoid hammering Redis on every /metrics call)
_queue_metrics_cache = {
    'last_update': 0,
    'values': {},
    'ttl_seconds': 5,  # Refresh every 5 seconds max
}


def update_queue_metrics():
    """
    Update Celery queue depth metrics from Redis.

    Uses Redis LLEN to check queue length directly.
    Results are cached for 5 seconds to avoid Redis hammering.

    Queue format in Redis (Celery default): celery (or custom queue name)
    """
    current_time = time.time()

    # Check cache TTL
    if current_time - _queue_metrics_cache['last_update'] < _queue_metrics_cache['ttl_seconds']:
        return _queue_metrics_cache['values']

    try:
        import redis

        # Get Redis URL from environment (same as Celery uses)
        redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

        # Quick connection with short timeout (don't block /metrics)
        client = redis.from_url(redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)

        # Check known queue names used by SOLVEREIGN
        queue_names = ["routing", "celery"]  # routing is our main queue

        values = {}
        for queue_name in queue_names:
            try:
                # Celery stores tasks as Redis list with key = queue name
                length = client.llen(queue_name)
                CELERY_QUEUE_LENGTH.labels(queue=queue_name).set(length)
                values[queue_name] = length
            except Exception as e:
                logger.debug(f"Failed to get queue length for {queue_name}: {e}")
                # Set to -1 to indicate error (distinguishes from 0 = empty)
                CELERY_QUEUE_LENGTH.labels(queue=queue_name).set(-1)
                values[queue_name] = -1

        # Update cache
        _queue_metrics_cache['last_update'] = current_time
        _queue_metrics_cache['values'] = values

        client.close()
        return values

    except ImportError:
        logger.warning("redis package not installed, queue metrics unavailable")
        return {}
    except Exception as e:
        logger.warning(f"Failed to update queue metrics: {e}")
        return {}


def set_solver_memory_limit(limit_bytes: int, component: str = "solver"):
    """
    Record the configured solver memory limit.

    Called at startup when memory limits are applied.
    """
    SOLVER_MEMORY_LIMIT.labels(component=component).set(limit_bytes)


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
    # Update queue metrics before generating response (P2 FIX)
    update_queue_metrics()

    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
