"""
SOLVEREIGN V3.7 - Tenant HMAC Auth (Pack Endpoints)
===================================================

Tenant authentication for /api/v1/{pack}/* endpoints (routing, roster, etc.).
Uses API Key + HMAC signature + nonce replay protection.

SECURITY MODEL:
- Pack endpoints ONLY accept API Key + HMAC auth
- Session cookies / CSRF tokens are REJECTED on pack endpoints
- Replay protection via nonce tracking (5-minute TTL)
- Idempotency integration for cached responses

HEADERS:
- X-API-Key: Tenant API key (identity)
- X-SV-Timestamp: Unix timestamp (±120s window)
- X-SV-Nonce: Unique per-request nonce (min 16 chars)
- X-SV-Body-SHA256: SHA256 hash of request body (for POST/PUT/PATCH)
- X-SV-Signature: HMAC-SHA256 of canonical request
- X-Idempotency-Key: (optional) For request deduplication

Canonical Format:
    METHOD|PATH|TIMESTAMP|NONCE|TENANT_CODE|BODY_SHA256

Usage:
    from .security.tenant_auth import require_tenant_hmac

    @router.post("/routing/solve")
    async def solve(
        tenant: TenantHMACContext = Depends(require_tenant_hmac())
    ):
        ...
"""

import hashlib
import hmac
import time
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import Request, Response, HTTPException, status, Depends, Header

from ..config import settings
from ..logging_config import get_logger
from ..database import DatabaseManager, get_tenant_by_api_key

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

TIMESTAMP_WINDOW_SECONDS = 120      # ±120 seconds
NONCE_TTL_SECONDS = 300            # 5 minutes
MIN_NONCE_LENGTH = 16
SESSION_COOKIE_NAME = "sv_session"  # From platform_auth.py


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TenantHMACContext:
    """
    Authenticated tenant context from HMAC verification.

    Only populated after successful signature + API key validation.
    """
    tenant_id: int
    tenant_code: str
    tenant_name: str
    is_active: bool
    timestamp: int
    nonce: str
    signature: str
    body_hash: str = ""
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    # Idempotency
    idempotency_key: Optional[str] = None
    idempotency_status: str = "NEW"  # NEW, HIT, MISMATCH
    cached_response: Optional[dict] = None
    cached_status: Optional[int] = None


# =============================================================================
# SIGNATURE HELPERS
# =============================================================================

# SECURITY: Defined empty body hash for reproducibility
# SHA256 of empty string = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
EMPTY_BODY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def compute_body_hash(body_bytes: bytes) -> str:
    """
    Compute SHA256 hash of request body.

    SECURITY: Returns defined constant for empty body (not empty string).
    This ensures reproducible signatures for GET/DELETE requests.
    """
    if not body_bytes:
        return EMPTY_BODY_HASH
    return hashlib.sha256(body_bytes).hexdigest()


def generate_nonce() -> str:
    """Generate cryptographically secure nonce."""
    return secrets.token_hex(16)  # 32 chars


def canonicalize_path(path: str) -> str:
    """
    Canonicalize request path for signature.

    SECURITY: Uses raw path without re-encoding to prevent
    signature mismatches due to encoding differences.

    - Strips trailing slashes (except root)
    - Does NOT re-encode (use raw URL-decoded path)
    """
    if path == "/":
        return path
    return path.rstrip("/")


def compute_tenant_signature(
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    api_key: str,
    body_hash: str = "",
    secret: Optional[str] = None
) -> str:
    """
    Compute HMAC-SHA256 signature for tenant request.

    SECURITY NOTES:
    - Path is used as-is (raw, URL-decoded)
    - Empty body uses EMPTY_BODY_HASH constant (not empty string)
    - Canonical format is deterministic

    Args:
        method: HTTP method
        path: Request path (raw, without query string)
        timestamp: Unix timestamp
        nonce: Unique nonce (min 16 chars)
        api_key: Tenant API key
        body_hash: SHA256 of request body (or EMPTY_BODY_HASH)
        secret: Signing secret

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    if secret is None:
        secret = settings.secret_key

    # SECURITY: Canonicalize path (strip trailing slash)
    canonical_path = canonicalize_path(path)

    # SECURITY: Use EMPTY_BODY_HASH for empty body, never empty string
    effective_body_hash = body_hash if body_hash else EMPTY_BODY_HASH

    # Canonical format: METHOD|PATH|TIMESTAMP|NONCE|API_KEY|BODY_HASH
    # Each field is non-empty and deterministic
    canonical = "|".join([
        method.upper(),
        canonical_path,
        str(timestamp),
        nonce,
        api_key,
        effective_body_hash
    ])

    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


# =============================================================================
# PRODUCTION GUARDS
# =============================================================================

def reject_platform_auth_headers(request: Request) -> None:
    """
    Reject requests with platform auth headers on pack endpoints.

    Pack endpoints MUST NOT accept:
    - Session cookies (sv_session)
    - X-CSRF-Token
    - X-Platform-Admin
    """
    rejected_reasons = []

    # Check session cookie
    if request.cookies.get(SESSION_COOKIE_NAME):
        rejected_reasons.append("session_cookie")

    # Check CSRF header (indicates platform auth flow)
    if request.headers.get("X-CSRF-Token"):
        rejected_reasons.append("csrf_header")

    # Check platform admin header
    if request.headers.get("X-Platform-Admin"):
        rejected_reasons.append("platform_admin_header")

    if rejected_reasons:
        logger.warning(
            "tenant_auth_rejected_platform_headers",
            extra={
                "path": request.url.path,
                "rejected_reasons": rejected_reasons,
                "source_ip": _get_client_ip(request)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_auth_method",
                "message": "Pack endpoints require API Key + HMAC auth, not session auth",
                "rejected_reasons": rejected_reasons
            }
        )


# =============================================================================
# NONCE REPLAY PROTECTION
# =============================================================================

async def check_and_record_nonce(
    db: DatabaseManager,
    nonce: str,
    timestamp: int
) -> bool:
    """
    Check if nonce was already used (replay) and record it.

    SECURITY: Nonces are GLOBALLY unique (not per-tenant).
    This is more secure - a nonce captured from tenant A
    cannot be replayed against tenant B either.

    Table schema (from migration 022):
    - signature: VARCHAR(64) PRIMARY KEY (the nonce)
    - timestamp: BIGINT
    - expires_at: TIMESTAMPTZ (5 minute TTL)

    Returns True if this is a replay (nonce already used).
    """
    try:
        async with db.connection() as conn:
            async with conn.cursor() as cur:
                # Try to insert nonce (globally unique via PRIMARY KEY)
                # If it exists, this is a replay attack
                await cur.execute("""
                    INSERT INTO core.used_signatures (
                        signature, timestamp, expires_at
                    )
                    VALUES (%s, %s, NOW() + INTERVAL '%s seconds')
                    ON CONFLICT (signature) DO NOTHING
                    RETURNING signature
                """, (nonce, timestamp, NONCE_TTL_SECONDS))

                result = await cur.fetchone()
                await conn.commit()

                # If we got a result, the insert succeeded (not a replay)
                # If no result, the nonce already existed (replay)
                return result is None

    except Exception as e:
        logger.warning(
            "tenant_auth_replay_check_failed",
            extra={"error": str(e), "nonce_prefix": nonce[:8]}
        )
        # Fail open to prevent cascading failures
        return False


async def record_security_event(
    db: DatabaseManager,
    event_type: str,
    severity: str,
    source_ip: str,
    request_path: str,
    request_method: str,
    details: dict
) -> None:
    """Record security event to database (non-blocking)."""
    try:
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
                    source_ip,
                    request_path,
                    request_method,
                    details
                ))
                await conn.commit()

    except Exception as e:
        logger.error(
            "security_event_record_failed",
            extra={"error": str(e), "event_type": event_type}
        )


# =============================================================================
# IDEMPOTENCY INTEGRATION
# =============================================================================

async def check_idempotency(
    db: DatabaseManager,
    tenant_id: int,
    idempotency_key: str,
    request_path: str,
    request_hash: str
) -> dict:
    """
    Check idempotency key and return cached response if exists.

    Returns:
        {
            "status": "NEW" | "HIT" | "MISMATCH",
            "cached_response": dict | None,
            "cached_status": int | None
        }
    """
    try:
        async with db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT request_hash, response_body, response_status
                    FROM idempotency_keys
                    WHERE tenant_id = %s
                      AND idempotency_key = %s
                      AND endpoint = %s
                      AND expires_at > NOW()
                """, (tenant_id, idempotency_key, request_path))

                row = await cur.fetchone()

                if not row:
                    return {"status": "NEW", "cached_response": None, "cached_status": None}

                if row["request_hash"] != request_hash:
                    return {"status": "MISMATCH", "cached_response": None, "cached_status": None}

                return {
                    "status": "HIT",
                    "cached_response": row["response_body"],
                    "cached_status": row["response_status"]
                }

    except Exception as e:
        logger.warning(
            "idempotency_check_failed",
            extra={"error": str(e)}
        )
        return {"status": "NEW", "cached_response": None, "cached_status": None}


async def save_idempotency_response(
    db: DatabaseManager,
    tenant_id: int,
    idempotency_key: str,
    request_path: str,
    request_hash: str,
    response_body: dict,
    response_status: int,
    ttl_hours: int = 24
) -> None:
    """Save response for idempotency key."""
    try:
        async with db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO idempotency_keys (
                        tenant_id, idempotency_key, endpoint,
                        request_hash, response_body, response_status,
                        expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW() + INTERVAL '%s hours')
                    ON CONFLICT (tenant_id, idempotency_key, endpoint) DO UPDATE SET
                        request_hash = EXCLUDED.request_hash,
                        response_body = EXCLUDED.response_body,
                        response_status = EXCLUDED.response_status,
                        expires_at = EXCLUDED.expires_at
                """, (
                    tenant_id, idempotency_key, request_path,
                    request_hash, response_body, response_status,
                    ttl_hours
                ))
                await conn.commit()

    except Exception as e:
        logger.warning(
            "idempotency_save_failed",
            extra={"error": str(e)}
        )


# =============================================================================
# DEPENDENCY FACTORY
# =============================================================================

def require_tenant_hmac(
    check_replay: bool = True,
    check_idempotency_key: bool = True
):
    """
    FastAPI dependency that requires valid tenant HMAC auth.

    Args:
        check_replay: Whether to check for replay attacks
        check_idempotency_key: Whether to check idempotency key

    Usage:
        @router.post("/routing/solve")
        async def solve(
            tenant: TenantHMACContext = Depends(require_tenant_hmac())
        ):
            if tenant.idempotency_status == "HIT":
                return JSONResponse(
                    content=tenant.cached_response,
                    status_code=tenant.cached_status
                )
            # Process request...
    """
    async def dependency(
        request: Request,
        x_api_key: str = Header(..., alias="X-API-Key"),
        x_sv_timestamp: str = Header(..., alias="X-SV-Timestamp"),
        x_sv_nonce: str = Header(..., alias="X-SV-Nonce"),
        x_sv_signature: str = Header(..., alias="X-SV-Signature"),
        x_sv_body_hash: str = Header("", alias="X-SV-Body-SHA256"),
        x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    ) -> TenantHMACContext:
        # SECURITY: Reject platform auth headers
        reject_platform_auth_headers(request)

        source_ip = _get_client_ip(request)
        db: DatabaseManager = request.app.state.db

        # 1. Validate timestamp format
        try:
            timestamp = int(x_sv_timestamp)
        except ValueError:
            logger.warning(
                "tenant_auth_invalid_timestamp",
                extra={"timestamp": x_sv_timestamp, "path": request.url.path}
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_timestamp", "message": "Invalid timestamp format"}
            )

        # 2. Verify timestamp within window (±120s)
        current_time = int(time.time())
        time_diff = current_time - timestamp

        if abs(time_diff) > TIMESTAMP_WINDOW_SECONDS:
            logger.warning(
                "tenant_auth_timestamp_skew",
                extra={
                    "timestamp": timestamp,
                    "current_time": current_time,
                    "diff_seconds": time_diff,
                    "path": request.url.path,
                    "source_ip": source_ip
                }
            )

            await record_security_event(
                db, "TENANT_TIMESTAMP_SKEW", "S1", source_ip,
                request.url.path, request.method,
                {"timestamp": timestamp, "skew_seconds": time_diff}
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "timestamp_expired",
                    "message": f"Request timestamp outside valid window (±{TIMESTAMP_WINDOW_SECONDS}s)"
                }
            )

        # 3. Validate nonce
        if not x_sv_nonce or len(x_sv_nonce) < MIN_NONCE_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_nonce", "message": "Invalid or missing nonce"}
            )

        # 4. Verify body hash for methods with body
        methods_with_body = ["POST", "PUT", "PATCH"]
        body_bytes = b""
        if request.method.upper() in methods_with_body:
            body_bytes = await request.body()
            expected_body_hash = compute_body_hash(body_bytes)

            if x_sv_body_hash != expected_body_hash:
                logger.warning(
                    "tenant_auth_body_hash_mismatch",
                    extra={
                        "expected": expected_body_hash[:16] + "...",
                        "received": x_sv_body_hash[:16] + "..." if x_sv_body_hash else "empty",
                        "path": request.url.path
                    }
                )

                await record_security_event(
                    db, "TENANT_BODY_MISMATCH", "S0", source_ip,
                    request.url.path, request.method,
                    {"reason": "Body hash mismatch"}
                )

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "body_hash_mismatch", "message": "Request body hash mismatch"}
                )

        # 5. Validate API key and get tenant
        if not x_api_key or len(x_api_key) < settings.api_key_min_length:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_api_key", "message": "Invalid API key format"}
            )

        tenant = await get_tenant_by_api_key(db, x_api_key)
        if not tenant:
            logger.warning(
                "tenant_auth_invalid_api_key",
                extra={"api_key_prefix": x_api_key[:8], "path": request.url.path}
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_api_key", "message": "Invalid API key"}
            )

        if not tenant["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "tenant_inactive", "message": "Tenant is inactive"}
            )

        # 6. Verify HMAC signature
        expected_signature = compute_tenant_signature(
            method=request.method,
            path=request.url.path,
            timestamp=timestamp,
            nonce=x_sv_nonce,
            api_key=x_api_key,
            body_hash=x_sv_body_hash
        )

        if not hmac.compare_digest(x_sv_signature.lower(), expected_signature.lower()):
            logger.error(
                "tenant_auth_signature_invalid",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "source_ip": source_ip,
                    "tenant_id": tenant["id"],
                    "nonce_prefix": x_sv_nonce[:8]
                }
            )

            await record_security_event(
                db, "TENANT_SIGNATURE_INVALID", "S0", source_ip,
                request.url.path, request.method,
                {"tenant_id": tenant["id"], "reason": "HMAC mismatch"}
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "signature_invalid", "message": "Invalid request signature"}
            )

        # 7. Check replay attack
        if check_replay:
            is_replay = await check_and_record_nonce(
                db, x_sv_nonce, timestamp
            )
            if is_replay:
                logger.error(
                    "tenant_auth_replay_detected",
                    extra={
                        "path": request.url.path,
                        "source_ip": source_ip,
                        "tenant_id": tenant["id"],
                        "nonce_prefix": x_sv_nonce[:8]
                    }
                )

                await record_security_event(
                    db, "TENANT_REPLAY_ATTACK", "S0", source_ip,
                    request.url.path, request.method,
                    {"tenant_id": tenant["id"], "nonce_prefix": x_sv_nonce[:8]}
                )

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "replay_attack", "message": "Replay attack detected"}
                )

        # 8. Check idempotency
        idempotency_status = "NEW"
        cached_response = None
        cached_status = None

        if check_idempotency_key and x_idempotency_key:
            request_hash = compute_body_hash(body_bytes)
            idem_result = await check_idempotency(
                db, tenant["id"], x_idempotency_key,
                request.url.path, request_hash
            )

            idempotency_status = idem_result["status"]
            cached_response = idem_result["cached_response"]
            cached_status = idem_result["cached_status"]

            if idempotency_status == "MISMATCH":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "idempotency_mismatch",
                        "message": "Idempotency key used with different request body"
                    }
                )

        logger.debug(
            "tenant_auth_success",
            extra={
                "tenant_id": tenant["id"],
                "path": request.url.path,
                "nonce_prefix": x_sv_nonce[:8]
            }
        )

        return TenantHMACContext(
            tenant_id=tenant["id"],
            tenant_code=tenant.get("tenant_code", tenant["name"]),
            tenant_name=tenant["name"],
            is_active=tenant["is_active"],
            timestamp=timestamp,
            nonce=x_sv_nonce,
            signature=x_sv_signature,
            body_hash=x_sv_body_hash,
            source_ip=source_ip,
            user_agent=request.headers.get("User-Agent"),
            idempotency_key=x_idempotency_key,
            idempotency_status=idempotency_status,
            cached_response=cached_response,
            cached_status=cached_status
        )

    return dependency


async def get_optional_tenant_hmac(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[TenantHMACContext]:
    """
    Get tenant context if HMAC auth present, without requiring it.

    Useful for endpoints that work with or without auth.
    """
    if not x_api_key:
        return None

    # If API key present, require full HMAC auth
    dependency = require_tenant_hmac()
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


# =============================================================================
# UTILITY: GENERATE CLIENT AUTH HEADERS
# =============================================================================

def generate_client_headers(
    method: str,
    path: str,
    api_key: str,
    body: bytes = b"",
    idempotency_key: Optional[str] = None,
    secret: Optional[str] = None
) -> dict:
    """
    Generate auth headers for client requests.

    Utility function for clients calling pack endpoints.

    Args:
        method: HTTP method
        path: Request path
        api_key: Tenant API key
        body: Request body bytes
        idempotency_key: Optional idempotency key
        secret: Signing secret

    Returns:
        Dict of headers to include in request
    """
    timestamp = int(time.time())
    nonce = generate_nonce()
    body_hash = compute_body_hash(body)

    signature = compute_tenant_signature(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        api_key=api_key,
        body_hash=body_hash,
        secret=secret
    )

    headers = {
        "X-API-Key": api_key,
        "X-SV-Timestamp": str(timestamp),
        "X-SV-Nonce": nonce,
        "X-SV-Signature": signature,
    }

    if body_hash:
        headers["X-SV-Body-SHA256"] = body_hash

    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    return headers
