"""
Clawdbot Webhook HMAC Signature Verification

Validates incoming webhook requests from Clawdbot Gateway using HMAC-SHA256.
"""

import hmac
import hashlib
import time
import logging
from typing import Optional
from fastapi import HTTPException, status, Request

from ..config import get_config

logger = logging.getLogger(__name__)


class SignatureVerificationError(HTTPException):
    """Raised when webhook signature verification fails."""

    def __init__(self, detail: str, error_code: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )
        self.error_code = error_code


async def verify_clawdbot_signature(
    request: Request,
    signature: str,
    timestamp: str,
    body: bytes,
    secret: Optional[str] = None,
) -> bool:
    """
    Verify HMAC-SHA256 signature from Clawdbot Gateway.

    Signature format: HMAC-SHA256(secret, timestamp|body)

    Args:
        request: FastAPI request for logging context
        signature: X-Clawdbot-Signature header value
        timestamp: X-Clawdbot-Timestamp header value (Unix seconds)
        body: Raw request body bytes
        secret: HMAC secret (defaults to config)

    Returns:
        True if signature is valid

    Raises:
        SignatureVerificationError: If verification fails
    """
    config = get_config()
    secret = secret or config.clawdbot_webhook_secret

    if not secret:
        logger.error("clawdbot_webhook_secret_not_configured")
        raise SignatureVerificationError(
            detail="Webhook secret not configured",
            error_code="SECRET_NOT_CONFIGURED",
        )

    # Validate timestamp freshness
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        logger.warning(
            "clawdbot_invalid_timestamp",
            extra={"timestamp": timestamp},
        )
        raise SignatureVerificationError(
            detail="Invalid timestamp format",
            error_code="INVALID_TIMESTAMP",
        )

    current_time = int(time.time())
    tolerance = config.clawdbot_timestamp_tolerance

    if abs(current_time - ts) > tolerance:
        logger.warning(
            "clawdbot_timestamp_expired",
            extra={
                "request_timestamp": ts,
                "current_time": current_time,
                "tolerance": tolerance,
                "drift": abs(current_time - ts),
            },
        )
        raise SignatureVerificationError(
            detail=f"Timestamp expired (drift: {abs(current_time - ts)}s, max: {tolerance}s)",
            error_code="TIMESTAMP_EXPIRED",
        )

    # Compute expected signature
    # Format: timestamp|body
    message = f"{timestamp}|".encode() + body
    expected = hmac.new(
        secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature.lower(), expected.lower()):
        logger.warning(
            "clawdbot_signature_mismatch",
            extra={
                "received_prefix": signature[:8] if signature else "empty",
                "body_length": len(body),
            },
        )
        raise SignatureVerificationError(
            detail="Invalid signature",
            error_code="INVALID_SIGNATURE",
        )

    logger.debug(
        "clawdbot_signature_valid",
        extra={"timestamp": ts},
    )
    return True


def compute_signature(
    timestamp: str,
    body: bytes,
    secret: str,
) -> str:
    """
    Compute HMAC-SHA256 signature for testing/debugging.

    Args:
        timestamp: Unix timestamp string
        body: Request body bytes
        secret: HMAC secret

    Returns:
        Hex-encoded signature
    """
    message = f"{timestamp}|".encode() + body
    return hmac.new(
        secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def hash_phone_number(phone: str) -> str:
    """
    Hash phone number for privacy-preserving storage.

    Args:
        phone: Phone number in E.164 format

    Returns:
        SHA-256 hex digest
    """
    # Normalize: remove spaces, ensure starts with +
    normalized = phone.strip().replace(" ", "")
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"

    return hashlib.sha256(normalized.encode()).hexdigest()
