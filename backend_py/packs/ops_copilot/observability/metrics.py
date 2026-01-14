"""
Ops-Copilot Prometheus Metrics

Counters and histograms for monitoring Ops-Copilot operations.
"""

from prometheus_client import Counter, Histogram, Gauge
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Counters
# =============================================================================

# Message counters
OPS_COPILOT_MESSAGES_TOTAL = Counter(
    "ops_copilot_messages_total",
    "Total WhatsApp messages processed",
    ["tenant_id", "direction"],  # direction: in, out
)

# Tool call counters
OPS_COPILOT_TOOL_CALLS_TOTAL = Counter(
    "ops_copilot_tool_calls_total",
    "Total tool invocations",
    ["tenant_id", "tool_name", "status"],  # status: success, error
)

# Write action counters
OPS_COPILOT_WRITE_ACTIONS_TOTAL = Counter(
    "ops_copilot_write_actions_total",
    "Total write actions",
    ["tenant_id", "action_type", "status"],  # status: prepared, confirmed, committed, cancelled, expired
)

# Pairing counters
OPS_COPILOT_PAIRING_TOTAL = Counter(
    "ops_copilot_pairing_total",
    "Pairing attempts",
    ["tenant_id", "status"],  # status: success, invalid_otp, expired, max_attempts
)

# Error counters
OPS_COPILOT_ERRORS_TOTAL = Counter(
    "ops_copilot_errors_total",
    "Total errors",
    ["tenant_id", "error_type"],  # error_type: hmac_invalid, rate_limited, timeout, etc.
)

# Broadcast counters
OPS_COPILOT_BROADCASTS_TOTAL = Counter(
    "ops_copilot_broadcasts_total",
    "Total broadcast messages",
    ["tenant_id", "audience", "status"],  # audience: ops, driver; status: enqueued, rejected
)

# =============================================================================
# Histograms
# =============================================================================

# Response latency
OPS_COPILOT_RESPONSE_LATENCY = Histogram(
    "ops_copilot_response_latency_seconds",
    "End-to-end response latency",
    ["tenant_id"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0],
)

# Graph steps per request
OPS_COPILOT_GRAPH_STEPS = Histogram(
    "ops_copilot_graph_steps",
    "Number of LangGraph steps per request",
    ["tenant_id"],
    buckets=[1, 2, 3, 4, 5, 6, 7, 8],
)

# Tool calls per request
OPS_COPILOT_TOOL_CALLS_PER_REQUEST = Histogram(
    "ops_copilot_tool_calls_per_request",
    "Number of tool calls per request",
    ["tenant_id"],
    buckets=[0, 1, 2, 3, 4, 5],
)

# Memory retrieval latency
OPS_COPILOT_MEMORY_LATENCY = Histogram(
    "ops_copilot_memory_latency_seconds",
    "Memory retrieval latency",
    ["tenant_id", "memory_type"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# =============================================================================
# Gauges
# =============================================================================

# Active threads
OPS_COPILOT_ACTIVE_THREADS = Gauge(
    "ops_copilot_active_threads",
    "Number of active conversation threads",
    ["tenant_id"],
)

# Pending drafts
OPS_COPILOT_PENDING_DRAFTS = Gauge(
    "ops_copilot_pending_drafts",
    "Number of pending drafts awaiting confirmation",
    ["tenant_id"],
)


# =============================================================================
# Helper Functions
# =============================================================================


def record_message(tenant_id: int, direction: str) -> None:
    """Record a message event."""
    OPS_COPILOT_MESSAGES_TOTAL.labels(
        tenant_id=str(tenant_id),
        direction=direction,
    ).inc()


def record_tool_call(tenant_id: int, tool_name: str, success: bool) -> None:
    """Record a tool call event."""
    OPS_COPILOT_TOOL_CALLS_TOTAL.labels(
        tenant_id=str(tenant_id),
        tool_name=tool_name,
        status="success" if success else "error",
    ).inc()


def record_write_action(tenant_id: int, action_type: str, status: str) -> None:
    """Record a write action event."""
    OPS_COPILOT_WRITE_ACTIONS_TOTAL.labels(
        tenant_id=str(tenant_id),
        action_type=action_type,
        status=status,
    ).inc()


def record_pairing(tenant_id: int, status: str) -> None:
    """Record a pairing event."""
    OPS_COPILOT_PAIRING_TOTAL.labels(
        tenant_id=str(tenant_id),
        status=status,
    ).inc()


def record_error(tenant_id: int, error_type: str) -> None:
    """Record an error event."""
    OPS_COPILOT_ERRORS_TOTAL.labels(
        tenant_id=str(tenant_id),
        error_type=error_type,
    ).inc()


def record_broadcast(tenant_id: int, audience: str, status: str) -> None:
    """Record a broadcast event."""
    OPS_COPILOT_BROADCASTS_TOTAL.labels(
        tenant_id=str(tenant_id),
        audience=audience,
        status=status,
    ).inc()


def record_response_latency(tenant_id: int, latency_seconds: float) -> None:
    """Record response latency."""
    OPS_COPILOT_RESPONSE_LATENCY.labels(
        tenant_id=str(tenant_id),
    ).observe(latency_seconds)


def record_graph_steps(tenant_id: int, steps: int) -> None:
    """Record graph steps per request."""
    OPS_COPILOT_GRAPH_STEPS.labels(
        tenant_id=str(tenant_id),
    ).observe(steps)


def record_tool_calls_per_request(tenant_id: int, count: int) -> None:
    """Record tool calls per request."""
    OPS_COPILOT_TOOL_CALLS_PER_REQUEST.labels(
        tenant_id=str(tenant_id),
    ).observe(count)


def record_memory_latency(
    tenant_id: int,
    memory_type: str,
    latency_seconds: float,
) -> None:
    """Record memory retrieval latency."""
    OPS_COPILOT_MEMORY_LATENCY.labels(
        tenant_id=str(tenant_id),
        memory_type=memory_type,
    ).observe(latency_seconds)


def set_active_threads(tenant_id: int, count: int) -> None:
    """Set active thread count."""
    OPS_COPILOT_ACTIVE_THREADS.labels(
        tenant_id=str(tenant_id),
    ).set(count)


def set_pending_drafts(tenant_id: int, count: int) -> None:
    """Set pending draft count."""
    OPS_COPILOT_PENDING_DRAFTS.labels(
        tenant_id=str(tenant_id),
    ).set(count)
