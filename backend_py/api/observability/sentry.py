"""
Sentry Error Tracking Integration
=================================

Features:
- PII scrubbing (emails, tokens, passwords)
- Tenant/User context without PII
- Release/environment tagging
- Performance tracing (optional)

Usage:
    from api.observability import init_sentry, set_sentry_context, capture_exception

    # Initialize at app startup
    init_sentry(dsn="...", environment="production", release="v4.5.0")

    # Set context per request
    set_sentry_context(tenant_id=1, user_id="uuid", request_id="req-123")

    # Capture exceptions manually
    try:
        risky_operation()
    except Exception as e:
        capture_exception(e, extra={"plan_id": 42})
"""

import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Sentry SDK is optional - gracefully degrade if not installed
try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    logger.info("sentry_sdk not installed - error tracking disabled")


# =============================================================================
# PII PATTERNS FOR SCRUBBING
# =============================================================================

PII_PATTERNS = [
    # Email addresses
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[EMAIL_REDACTED]'),
    # JWT tokens (3 base64 segments separated by dots)
    (re.compile(r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'), '[JWT_REDACTED]'),
    # API keys (32+ hex chars)
    (re.compile(r'[a-fA-F0-9]{32,}'), '[API_KEY_REDACTED]'),
    # Passwords in URLs or bodies
    (re.compile(r'password["\']?\s*[:=]\s*["\']?[^"\'&\s]+', re.IGNORECASE), 'password=[REDACTED]'),
    # Bearer tokens
    (re.compile(r'Bearer\s+[a-zA-Z0-9_-]+'), 'Bearer [REDACTED]'),
    # Phone numbers (German format)
    (re.compile(r'\+?49[\d\s-]{10,}'), '[PHONE_REDACTED]'),
    # Credit card numbers (basic pattern)
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CARD_REDACTED]'),
]

# Headers to strip completely
SENSITIVE_HEADERS = {
    'authorization',
    'x-api-key',
    'x-sv-signature',
    'cookie',
    'set-cookie',
    'x-csrf-token',
}


def scrub_pii(data: Any) -> Any:
    """
    Recursively scrub PII from data structures.

    Args:
        data: String, dict, list, or nested structure

    Returns:
        Scrubbed data with PII replaced
    """
    if isinstance(data, str):
        result = data
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    elif isinstance(data, dict):
        scrubbed = {}
        for key, value in data.items():
            # Check if key itself is sensitive
            key_lower = str(key).lower()
            if any(s in key_lower for s in ['password', 'secret', 'token', 'api_key', 'apikey', 'auth']):
                scrubbed[key] = '[REDACTED]'
            elif key_lower in SENSITIVE_HEADERS:
                scrubbed[key] = '[REDACTED]'
            else:
                scrubbed[key] = scrub_pii(value)
        return scrubbed

    elif isinstance(data, list):
        return [scrub_pii(item) for item in data]

    elif isinstance(data, tuple):
        return tuple(scrub_pii(item) for item in data)

    else:
        return data


def before_send(event: dict, hint: dict) -> Optional[dict]:
    """
    Sentry before_send hook for PII scrubbing.

    Called before every event is sent to Sentry.
    Returns None to drop the event, or modified event to send.
    """
    # Scrub exception values
    if 'exception' in event:
        for exc in event['exception'].get('values', []):
            if 'value' in exc:
                exc['value'] = scrub_pii(exc['value'])
            # Scrub stacktrace local variables
            if 'stacktrace' in exc:
                for frame in exc['stacktrace'].get('frames', []):
                    if 'vars' in frame:
                        frame['vars'] = scrub_pii(frame['vars'])

    # Scrub request data
    if 'request' in event:
        req = event['request']
        # Scrub headers
        if 'headers' in req:
            req['headers'] = scrub_pii(req['headers'])
        # Scrub cookies
        if 'cookies' in req:
            req['cookies'] = '[REDACTED]'
        # Scrub query string
        if 'query_string' in req:
            req['query_string'] = scrub_pii(req['query_string'])
        # Scrub body data
        if 'data' in req:
            req['data'] = scrub_pii(req['data'])

    # Scrub breadcrumbs
    if 'breadcrumbs' in event:
        for crumb in event['breadcrumbs'].get('values', []):
            if 'message' in crumb:
                crumb['message'] = scrub_pii(crumb['message'])
            if 'data' in crumb:
                crumb['data'] = scrub_pii(crumb['data'])

    # Scrub extra context
    if 'extra' in event:
        event['extra'] = scrub_pii(event['extra'])

    # Scrub tags (but keep safe ones)
    if 'tags' in event:
        event['tags'] = scrub_pii(event['tags'])

    return event


def before_send_transaction(event: dict, hint: dict) -> Optional[dict]:
    """
    Sentry hook for transaction events (performance tracing).

    Apply same PII scrubbing as regular events.
    """
    return before_send(event, hint)


# =============================================================================
# PUBLIC API
# =============================================================================

def init_sentry(
    dsn: Optional[str],
    environment: str = "development",
    release: Optional[str] = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
) -> bool:
    """
    Initialize Sentry error tracking.

    Args:
        dsn: Sentry DSN (None to disable)
        environment: Environment name (development/staging/production)
        release: Release version (e.g., "v4.5.0")
        traces_sample_rate: Performance tracing sample rate (0.0-1.0)
        profiles_sample_rate: Profiling sample rate (0.0-1.0)

    Returns:
        True if Sentry was initialized, False if disabled/unavailable
    """
    if not SENTRY_AVAILABLE:
        logger.warning("sentry_sdk not installed - skipping initialization")
        return False

    if not dsn:
        logger.info("Sentry DSN not configured - error tracking disabled")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,

            # Integrations
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
                LoggingIntegration(
                    level=logging.WARNING,  # Capture WARNING+ as breadcrumbs
                    event_level=logging.ERROR,  # Send ERROR+ as events
                ),
                AsyncPGIntegration(),  # PostgreSQL query spans
            ],

            # Performance
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,

            # PII Protection
            before_send=before_send,
            before_send_transaction=before_send_transaction,
            send_default_pii=False,  # Never send default PII

            # Additional options
            attach_stacktrace=True,
            max_breadcrumbs=50,

            # Don't send in debug mode by default
            debug=environment == "development",
        )

        logger.info(
            "sentry_initialized",
            extra={
                "environment": environment,
                "release": release,
                "traces_sample_rate": traces_sample_rate,
            }
        )
        return True

    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}")
        return False


def set_sentry_context(
    tenant_id: Optional[int] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    site_id: Optional[int] = None,
    **extra_tags: Any,
) -> None:
    """
    Set Sentry context for the current scope.

    Call this per-request to tag errors with tenant/user context.
    Note: Only IDs are stored, never PII like emails or names.

    Args:
        tenant_id: Tenant ID (integer, not name)
        user_id: User UUID (not email)
        request_id: Request correlation ID
        site_id: Site ID within tenant
        **extra_tags: Additional tags
    """
    if not SENTRY_AVAILABLE:
        return

    with sentry_sdk.configure_scope() as scope:
        # Set user context (ID only, no PII)
        if user_id:
            scope.set_user({"id": str(user_id)})

        # Set tags for filtering
        if tenant_id is not None:
            scope.set_tag("tenant_id", str(tenant_id))
        if site_id is not None:
            scope.set_tag("site_id", str(site_id))
        if request_id:
            scope.set_tag("request_id", request_id)

        # Extra tags
        for key, value in extra_tags.items():
            # Scrub any PII that might have snuck in
            safe_value = scrub_pii(str(value)) if value else None
            if safe_value:
                scope.set_tag(key, safe_value)


def capture_exception(
    exception: BaseException,
    extra: Optional[dict] = None,
    tags: Optional[dict] = None,
    level: str = "error",
) -> Optional[str]:
    """
    Manually capture an exception to Sentry.

    Args:
        exception: The exception to capture
        extra: Extra context data (will be scrubbed)
        tags: Tags to add to the event
        level: Severity level (error, warning, info)

    Returns:
        Sentry event ID if sent, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None

    with sentry_sdk.push_scope() as scope:
        scope.set_level(level)

        if extra:
            # Scrub PII from extra data
            safe_extra = scrub_pii(extra)
            for key, value in safe_extra.items():
                scope.set_extra(key, value)

        if tags:
            safe_tags = scrub_pii(tags)
            for key, value in safe_tags.items():
                scope.set_tag(key, str(value))

        event_id = sentry_sdk.capture_exception(exception)

    return event_id


def capture_message(
    message: str,
    level: str = "info",
    extra: Optional[dict] = None,
) -> Optional[str]:
    """
    Capture a message to Sentry (not an exception).

    Args:
        message: Message to send
        level: Severity level (info, warning, error)
        extra: Extra context data

    Returns:
        Sentry event ID if sent, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None

    # Scrub PII from message
    safe_message = scrub_pii(message)

    with sentry_sdk.push_scope() as scope:
        scope.set_level(level)

        if extra:
            safe_extra = scrub_pii(extra)
            for key, value in safe_extra.items():
                scope.set_extra(key, value)

        event_id = sentry_sdk.capture_message(safe_message)

    return event_id
