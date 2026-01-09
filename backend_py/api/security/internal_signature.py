"""
SOLVEREIGN Internal Request Signature Verification (V2 Hardened)
================================================================

Implements HMAC-based signature verification for internal (BFF → Backend) requests.
This prevents platform admin spoofing and ensures tenant context comes from trusted sources.

V2 Security Features:
- Nonce per request (replay protection within timestamp window)
- Body SHA256 hash (payload binding for POST/PUT/PATCH)
- Timestamp window (±120s configurable)
- Query string canonicalization (sorted params)

Headers (V2):
- X-SV-Internal: "1" (marks request as internal)
- X-SV-Timestamp: Unix timestamp (seconds)
- X-SV-Nonce: Unique 32-char hex nonce
- X-SV-Body-SHA256: SHA256 hash of request body (for POST/PUT/PATCH)
- X-SV-Signature: HMAC-SHA256(secret, method|path|timestamp|nonce|tenant|site|admin|body_hash)

Canonical Format V2:
    METHOD|CANONICAL_PATH|TIMESTAMP|NONCE|TENANT_CODE|SITE_CODE|IS_PLATFORM_ADMIN|BODY_SHA256

Usage:
    from .security.internal_signature import verify_internal_request, InternalContext

    @router.get("/platform/tenants")
    async def list_tenants(internal: InternalContext = Depends(require_internal_signature)):
        if internal.is_platform_admin:
            # Trusted platform admin context
            ...
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode

from fastapi import Request, HTTPException, status

from ..config import settings
from ..logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Signature validity window (±120 seconds from server time)
TIMESTAMP_WINDOW_SECONDS = 120

# Nonce/signature expiry (keep in DB for this long)
SIGNATURE_TTL_SECONDS = 300  # 5 minutes

# Minimum nonce length
MIN_NONCE_LENGTH = 16


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class InternalContext:
    """
    Verified internal request context.

    Only populated after successful signature verification.
    """
    is_internal: bool = False
    is_platform_admin: bool = False
    tenant_code: Optional[str] = None
    site_code: Optional[str] = None
    timestamp: int = 0
    nonce: Optional[str] = None
    signature: Optional[str] = None
    source_ip: Optional[str] = None


# =============================================================================
# CANONICALIZATION HELPERS
# =============================================================================

def canonicalize_path(path: str) -> str:
    """
    Canonicalize path with sorted query string.

    Ensures consistent signature regardless of query param order.
    """
    parsed = urlparse(path)
    query_params = parse_qsl(parsed.query)

    # Sort query params by key, then by value for duplicate keys
    sorted_params = sorted(query_params, key=lambda x: (x[0], x[1]))
    sorted_query = urlencode(sorted_params)

    if sorted_query:
        return f"{parsed.path}?{sorted_query}"
    return parsed.path


def compute_body_hash(body_bytes: bytes) -> str:
    """
    Compute SHA256 hash of request body.

    Returns empty string for empty body.
    """
    if not body_bytes:
        return ""
    return hashlib.sha256(body_bytes).hexdigest()


# =============================================================================
# SIGNATURE GENERATION (for BFF use / testing)
# =============================================================================

def generate_signature_v2(
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    tenant_code: Optional[str] = None,
    site_code: Optional[str] = None,
    is_platform_admin: bool = False,
    body_hash: str = "",
    secret: Optional[str] = None
) -> str:
    """
    Generate HMAC signature for internal request (V2 format).

    Used by BFF to sign requests to backend.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path with query string
        timestamp: Unix timestamp in seconds
        nonce: Unique 32-char hex nonce
        tenant_code: Optional tenant code
        site_code: Optional site code
        is_platform_admin: Whether this is a platform admin request
        body_hash: SHA256 hash of request body (empty for GET/DELETE)
        secret: Signing secret (defaults to settings.secret_key)

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    if secret is None:
        secret = settings.secret_key

    # Canonicalize path (sorted query params)
    canonical_path = canonicalize_path(path)

    # Build canonical string (V2 format)
    # FORMAT: METHOD|PATH|TIMESTAMP|NONCE|TENANT|SITE|ADMIN|BODY_HASH
    canonical = "|".join([
        method.upper(),
        canonical_path,
        str(timestamp),
        nonce,
        tenant_code or "",
        site_code or "",
        "1" if is_platform_admin else "0",
        body_hash or ""
    ])

    # Generate HMAC-SHA256
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


# Legacy V1 signature (for backwards compatibility during migration)
def generate_signature(
    method: str,
    path: str,
    timestamp: int,
    tenant_code: Optional[str] = None,
    site_code: Optional[str] = None,
    is_platform_admin: bool = False,
    secret: Optional[str] = None
) -> str:
    """
    Generate HMAC signature (V1 legacy format).

    DEPRECATED: Use generate_signature_v2 for new code.
    """
    if secret is None:
        secret = settings.secret_key

    canonical = "|".join([
        method.upper(),
        path,
        str(timestamp),
        tenant_code or "",
        site_code or "",
        "1" if is_platform_admin else "0"
    ])

    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


# =============================================================================
# SIGNATURE VERIFICATION
# =============================================================================

async def verify_internal_request(
    request: Request,
    check_replay: bool = True
) -> InternalContext:
    """
    Verify internal request signature (V2 hardened).

    Validates:
    1. Required headers present
    2. Timestamp within ±120s window
    3. Nonce is valid (not empty, min length)
    4. Body hash matches (for POST/PUT/PATCH)
    5. Signature is valid
    6. No replay (nonce not used before)

    Args:
        request: FastAPI request
        check_replay: Whether to check for replay attacks (requires DB)

    Returns:
        InternalContext with verified values

    Raises:
        HTTPException(401) if signature is missing or invalid
        HTTPException(403) if timestamp is stale or replay detected
    """
    # Check if this is an internal request
    x_sv_internal = request.headers.get("X-SV-Internal")
    if x_sv_internal != "1":
        return InternalContext(is_internal=False)

    # Get required headers
    x_sv_timestamp = request.headers.get("X-SV-Timestamp")
    x_sv_signature = request.headers.get("X-SV-Signature")
    x_sv_nonce = request.headers.get("X-SV-Nonce")
    x_sv_body_hash = request.headers.get("X-SV-Body-SHA256", "")

    # Validate required headers
    if not x_sv_timestamp or not x_sv_signature:
        logger.warning(
            "internal_signature_missing",
            extra={
                "has_timestamp": bool(x_sv_timestamp),
                "has_signature": bool(x_sv_signature),
                "has_nonce": bool(x_sv_nonce),
                "path": request.url.path,
                "source_ip": _get_client_ip(request)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing internal request headers"
        )

    # V2 requires nonce
    if not x_sv_nonce or len(x_sv_nonce) < MIN_NONCE_LENGTH:
        logger.warning(
            "internal_signature_invalid_nonce",
            extra={
                "nonce_length": len(x_sv_nonce) if x_sv_nonce else 0,
                "path": request.url.path,
                "source_ip": _get_client_ip(request)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing nonce"
        )

    # Parse timestamp
    try:
        timestamp = int(x_sv_timestamp)
    except ValueError:
        logger.warning(
            "internal_signature_invalid_timestamp",
            extra={"timestamp": x_sv_timestamp, "path": request.url.path}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid timestamp format"
        )

    # Verify timestamp within window (±120s)
    current_time = int(time.time())
    time_diff = current_time - timestamp

    if abs(time_diff) > TIMESTAMP_WINDOW_SECONDS:
        logger.warning(
            "internal_signature_timestamp_skew",
            extra={
                "timestamp": timestamp,
                "current_time": current_time,
                "diff_seconds": time_diff,
                "window_seconds": TIMESTAMP_WINDOW_SECONDS,
                "path": request.url.path,
                "source_ip": _get_client_ip(request)
            }
        )

        await _record_security_event(
            request,
            event_type="SIG_TIMESTAMP_SKEW",
            severity="S1",
            details={
                "timestamp": timestamp,
                "server_time": current_time,
                "skew_seconds": time_diff
            }
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Request timestamp outside valid window (±{TIMESTAMP_WINDOW_SECONDS}s)"
        )

    # Verify body hash for methods with body
    methods_with_body = ["POST", "PUT", "PATCH"]
    if request.method.upper() in methods_with_body:
        # Read body bytes for hash verification
        body_bytes = await request.body()
        expected_body_hash = compute_body_hash(body_bytes)

        if x_sv_body_hash != expected_body_hash:
            logger.warning(
                "internal_signature_body_hash_mismatch",
                extra={
                    "expected_hash": expected_body_hash[:16] + "...",
                    "received_hash": x_sv_body_hash[:16] + "..." if x_sv_body_hash else "empty",
                    "path": request.url.path,
                    "method": request.method
                }
            )

            await _record_security_event(
                request,
                event_type="SIG_BODY_MISMATCH",
                severity="S0",
                details={"reason": "Body hash does not match"}
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request body hash mismatch"
            )
    else:
        # No body for GET/DELETE - body hash should be empty
        if x_sv_body_hash and x_sv_body_hash != "":
            x_sv_body_hash = ""

    # Get context headers (these are what we're verifying)
    tenant_code = request.headers.get("X-Tenant-Code")
    site_code = request.headers.get("X-Site-Code")
    x_platform_admin = request.headers.get("X-Platform-Admin")
    is_platform_admin = x_platform_admin == "true"

    # Get full path with query string for signature
    full_path = str(request.url.path)
    if request.url.query:
        full_path = f"{full_path}?{request.url.query}"

    # Generate expected signature (V2)
    expected_signature = generate_signature_v2(
        method=request.method,
        path=full_path,
        timestamp=timestamp,
        nonce=x_sv_nonce,
        tenant_code=tenant_code,
        site_code=site_code,
        is_platform_admin=is_platform_admin,
        body_hash=x_sv_body_hash
    )

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(x_sv_signature.lower(), expected_signature.lower()):
        source_ip = _get_client_ip(request)
        logger.error(
            "internal_signature_invalid",
            extra={
                "path": request.url.path,
                "method": request.method,
                "source_ip": source_ip,
                "tenant_code": tenant_code,
                "is_platform_admin": is_platform_admin,
                "nonce_prefix": x_sv_nonce[:8]
            }
        )

        await _record_security_event(
            request,
            event_type="SIGNATURE_INVALID",
            severity="S0",
            details={"reason": "HMAC mismatch"}
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid request signature"
        )

    # Check for replay attacks using nonce
    if check_replay:
        is_replay = await _check_and_record_nonce(
            request, x_sv_nonce, timestamp
        )
        if is_replay:
            logger.error(
                "internal_signature_replay",
                extra={
                    "path": request.url.path,
                    "source_ip": _get_client_ip(request),
                    "nonce_prefix": x_sv_nonce[:8]
                }
            )

            await _record_security_event(
                request,
                event_type="REPLAY_ATTACK",
                severity="S0",
                details={"nonce_prefix": x_sv_nonce[:8]}
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "REPLAY_ATTACK", "message": "Replay attack detected"}
            )

    logger.debug(
        "internal_signature_verified",
        extra={
            "path": request.url.path,
            "tenant_code": tenant_code,
            "is_platform_admin": is_platform_admin,
            "nonce_prefix": x_sv_nonce[:8]
        }
    )

    return InternalContext(
        is_internal=True,
        is_platform_admin=is_platform_admin,
        tenant_code=tenant_code,
        site_code=site_code,
        timestamp=timestamp,
        nonce=x_sv_nonce,
        signature=x_sv_signature,
        source_ip=_get_client_ip(request)
    )


# =============================================================================
# DEPENDENCY FACTORIES
# =============================================================================

def require_internal_signature(
    require_platform_admin: bool = False,
    check_replay: bool = True
):
    """
    FastAPI dependency that requires valid internal signature.

    Args:
        require_platform_admin: If True, also require platform admin flag
        check_replay: Whether to check for replay attacks

    Usage:
        @router.get("/platform/admin-only")
        async def admin_endpoint(
            internal: InternalContext = Depends(require_internal_signature(require_platform_admin=True))
        ):
            ...
    """
    async def dependency(request: Request) -> InternalContext:
        # In development, allow bypass if configured
        if settings.is_development and settings.allow_header_tenant_override:
            # Dev mode: trust headers without signature
            # WARNING: This is NEVER allowed in production (enforced by config validator)
            return InternalContext(
                is_internal=True,
                is_platform_admin=request.headers.get("X-Platform-Admin") == "true",
                tenant_code=request.headers.get("X-Tenant-Code"),
                site_code=request.headers.get("X-Site-Code"),
                timestamp=int(time.time()),
                source_ip=_get_client_ip(request)
            )

        # Verify signature
        context = await verify_internal_request(request, check_replay=check_replay)

        if not context.is_internal:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Internal request required"
            )

        if require_platform_admin and not context.is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin access required"
            )

        return context

    return dependency


async def get_trusted_context(request: Request) -> InternalContext:
    """
    Get trusted context from request (verifies signature if internal).

    Use this for endpoints that work with both internal and external requests.
    External requests get empty context (is_internal=False).
    Internal requests get verified context.
    """
    x_sv_internal = request.headers.get("X-SV-Internal")

    if x_sv_internal == "1":
        return await verify_internal_request(request)
    else:
        return InternalContext(is_internal=False)


# =============================================================================
# PLATFORM ADMIN DEPENDENCY
# =============================================================================

async def require_platform_admin(request: Request) -> InternalContext:
    """
    Require platform admin access.

    This is the main dependency for platform admin endpoints.
    Enforces signature verification in production.
    """
    dependency = require_internal_signature(require_platform_admin=True)
    return await dependency(request)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_client_ip(request: Request) -> str:
    """Get client IP from request, handling proxies."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "unknown"


async def _check_and_record_nonce(
    request: Request,
    nonce: str,
    timestamp: int
) -> bool:
    """
    Check if nonce was already used (replay) and record it.

    Returns True if this is a replay (nonce already used).
    """
    try:
        db = request.app.state.db

        async with db.connection() as conn:
            async with conn.cursor() as cur:
                # Try to insert nonce (using signature column for storage)
                # If it exists, this is a replay
                await cur.execute("""
                    INSERT INTO core.used_signatures (signature, timestamp, expires_at)
                    VALUES (%s, %s, NOW() + INTERVAL '%s seconds')
                    ON CONFLICT (signature) DO NOTHING
                    RETURNING signature
                """, (nonce, timestamp, SIGNATURE_TTL_SECONDS))

                result = await cur.fetchone()
                await conn.commit()

                # If we got a result, the insert succeeded (not a replay)
                # If no result, the nonce already existed (replay)
                return result is None

    except Exception as e:
        logger.warning(
            "replay_check_failed",
            extra={"error": str(e), "path": request.url.path}
        )
        return False


async def _record_security_event(
    request: Request,
    event_type: str,
    severity: str,
    details: dict
) -> None:
    """Record security event to database (non-blocking)."""
    try:
        db = request.app.state.db

        async with db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO core.security_events (
                        event_type, severity, source_ip,
                        request_path, request_method, details
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    event_type,
                    severity,
                    _get_client_ip(request),
                    request.url.path,
                    request.method,
                    details
                ))
                await conn.commit()

    except Exception as e:
        logger.error(
            "security_event_record_failed",
            extra={"error": str(e), "event_type": event_type}
        )


# =============================================================================
# MIDDLEWARE FOR AUTOMATIC PROTECTION
# =============================================================================

class InternalSignatureMiddleware:
    """
    Middleware that enforces signature verification on platform endpoints.

    Automatically protects /api/v1/platform/* endpoints.
    """

    PROTECTED_PREFIXES = [
        "/api/v1/platform/",
    ]

    def __init__(self, app, enforce_in_production: bool = True):
        self.app = app
        self.enforce_in_production = enforce_in_production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        needs_protection = any(
            path.startswith(prefix) for prefix in self.PROTECTED_PREFIXES
        )

        if not needs_protection:
            await self.app(scope, receive, send)
            return

        if self.enforce_in_production and settings.is_production:
            headers = dict(scope.get("headers", []))
            x_sv_internal = headers.get(b"x-sv-internal", b"").decode()

            if x_sv_internal != "1":
                response = {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                    ],
                }
                await send(response)
                body = b'{"error": "unauthorized", "message": "Platform endpoints require internal authentication"}'
                await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)
