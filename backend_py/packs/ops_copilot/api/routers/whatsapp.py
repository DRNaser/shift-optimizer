"""
WhatsApp Webhook Router

Handles:
- POST /ingest: Webhook from Clawdbot Gateway
- POST /pairing/invites: Admin creates OTP invite
- POST /identities/revoke: Admin revokes identity
- GET /identities: List identities (admin)
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from fastapi.responses import JSONResponse

from api.security.internal_rbac import (
    InternalUserContext,
    require_session,
    require_permission,
    get_rbac_repository,
)

from ..schemas import (
    WhatsAppMessage,
    IngestResponse,
    IngestStatus,
    CreateInviteRequest,
    CreateInviteResponse,
    RevokeIdentityRequest,
    IdentityResponse,
    IdentityStatus,
    ErrorResponse,
)
from ...config import get_config
from ...security.hmac_verify import verify_clawdbot_signature, hash_phone_number
from ...security.rbac import PERMISSION_PAIRING_WRITE, PERMISSION_IDENTITY_REVOKE
from ...observability.metrics import (
    record_message,
    record_pairing,
    record_error,
    record_response_latency,
)
from ...observability.tracing import (
    create_trace_context,
    get_logger,
    timed,
    clear_trace_context,
)

router = APIRouter(prefix="/whatsapp", tags=["ops-copilot-whatsapp"])
logger = get_logger("whatsapp")


# =============================================================================
# Webhook Ingest
# =============================================================================


@router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Signature verification failed"},
        429: {"model": ErrorResponse, "description": "Rate limited"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
    summary="WhatsApp message webhook from Clawdbot",
    description="""
    Receives incoming WhatsApp messages from Clawdbot Gateway.

    **Security:**
    - HMAC signature verification required (X-Clawdbot-Signature)
    - Idempotency via message_id
    - Rate limiting per wa_user_id

    **Flow:**
    1. Verify HMAC signature
    2. Check idempotency (message_id)
    3. Resolve identity (wa_user_id -> tenant + user)
    4. If not paired, check for PAIR <OTP> command
    5. Route to LangGraph orchestrator
    6. Return response
    """,
)
async def ingest_whatsapp_message(
    request: Request,
    message: WhatsAppMessage,
    x_clawdbot_signature: str = Header(..., alias="X-Clawdbot-Signature"),
    x_clawdbot_timestamp: str = Header(..., alias="X-Clawdbot-Timestamp"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """Process incoming WhatsApp message."""
    start_time = time.time()
    trace_id = str(uuid4())

    # Create trace context
    ctx = create_trace_context(
        trace_id=trace_id,
        wa_user_id=message.wa_user_id,
    )

    try:
        # 1. Verify HMAC signature
        body = await request.body()
        await verify_clawdbot_signature(
            request=request,
            signature=x_clawdbot_signature,
            timestamp=x_clawdbot_timestamp,
            body=body,
        )

        logger.info(
            "webhook_signature_verified",
            message_id=message.message_id,
        )

        # 2. Check idempotency
        idempotency_key = x_idempotency_key or message.message_id
        if await _check_idempotency(request, idempotency_key, message.wa_user_id):
            logger.info(
                "idempotency_hit",
                message_id=message.message_id,
                idempotency_key=idempotency_key,
            )
            return IngestResponse(
                status=IngestStatus.ACCEPTED,
                trace_id=trace_id,
                reply_text=None,  # Already processed
            )

        # 3. Resolve identity
        identity = await _resolve_identity(request, message.wa_user_id)

        if identity:
            ctx.update(
                tenant_id=identity["tenant_id"],
                site_id=identity.get("site_id"),
                user_id=identity["user_id"],
                thread_id=identity.get("thread_id"),
            )
            record_message(identity["tenant_id"], "in")

        # 4. Check for PAIR command if not paired
        if identity is None:
            pairing_result = await _handle_pairing_attempt(
                request, message.wa_user_id, message.wa_phone, message.text
            )
            if pairing_result:
                return IngestResponse(
                    status=IngestStatus.ACCEPTED,
                    trace_id=trace_id,
                    reply_text=pairing_result["reply_text"],
                )

            # Not paired and no valid PAIR command
            return IngestResponse(
                status=IngestStatus.ACCEPTED,
                trace_id=trace_id,
                reply_text=(
                    "Hi! I'm the SOLVEREIGN Ops Assistant. "
                    "To get started, ask your admin for a pairing code, "
                    "then send: PAIR <your-code>"
                ),
            )

        # 5. Process message through orchestrator
        # (Orchestrator implementation in core/graph.py)
        result = await _process_message(request, identity, message)

        # Record metrics
        latency = time.time() - start_time
        record_response_latency(identity["tenant_id"], latency)

        return IngestResponse(
            status=IngestStatus.ACCEPTED,
            trace_id=trace_id,
            reply_text=result.get("reply_text"),
            draft_id=result.get("draft_id"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ingest_error", error=str(e))
        record_error(ctx.tenant_id or 0, "ingest_error")
        return IngestResponse(
            status=IngestStatus.ERROR,
            trace_id=trace_id,
            error_code="INTERNAL_ERROR",
            error_message="An internal error occurred",
        )
    finally:
        clear_trace_context()


# =============================================================================
# Pairing Management
# =============================================================================


@router.post(
    "/pairing/invites",
    response_model=CreateInviteResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
    summary="Create WhatsApp pairing invite (admin)",
    description="""
    Admin creates OTP invite for a user to pair their WhatsApp.

    **RBAC:** Requires `ops_copilot.pairing.write` permission.

    **Flow:**
    1. Generate 6-digit OTP
    2. Store OTP hash (SHA-256) with expiry
    3. Return OTP to admin (shown once)
    4. Admin communicates OTP to user out-of-band
    5. User sends "PAIR <OTP>" to WhatsApp bot
    """,
)
async def create_pairing_invite(
    request: Request,
    body: CreateInviteRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_PAIRING_WRITE)),
):
    """Create a pairing invite for a user."""
    config = get_config()

    # Validate user exists and is in the same tenant (or platform admin)
    target_user = await _get_user_by_id(request, body.user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check tenant access (platform admin can create for any tenant)
    if not user.is_platform_admin:
        if target_user.get("tenant_id") != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create invite for user in different tenant",
            )

    # Generate 6-digit OTP
    otp = "".join(secrets.choice("0123456789") for _ in range(6))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()

    # Calculate expiry
    expires_minutes = min(body.expires_minutes, config.otp_expires_minutes)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    # Insert invite
    invite_id = await _create_pairing_invite(
        request=request,
        tenant_id=target_user["tenant_id"],
        user_id=body.user_id,
        otp_hash=otp_hash,
        expires_at=expires_at,
        max_attempts=config.otp_max_attempts,
        created_by=str(user.user_id),
    )

    logger.info(
        "pairing_invite_created",
        invite_id=invite_id,
        target_user_id=body.user_id,
        expires_minutes=expires_minutes,
    )

    return CreateInviteResponse(
        invite_id=invite_id,
        otp=otp,  # Shown only once
        expires_at=expires_at,
        user_id=body.user_id,
        instructions=(
            f"Send this code to the user. They should message the bot with: PAIR {otp}\n"
            f"Code expires in {expires_minutes} minutes."
        ),
    )


@router.post(
    "/identities/revoke",
    responses={
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Identity not found"},
    },
    summary="Revoke WhatsApp identity (admin)",
    description="""
    Revokes an existing WhatsApp identity binding.
    User will need to re-pair.
    """,
)
async def revoke_identity(
    request: Request,
    body: RevokeIdentityRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_IDENTITY_REVOKE)),
):
    """Revoke a WhatsApp identity."""
    # Get identity
    identity = await _get_identity_by_id(request, body.identity_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if identity["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot revoke identity in different tenant",
            )

    # Revoke
    await _revoke_identity(request, body.identity_id, body.reason)

    logger.info(
        "identity_revoked",
        identity_id=body.identity_id,
        reason=body.reason,
        revoked_by=str(user.user_id),
    )

    return {"status": "revoked", "identity_id": body.identity_id}


@router.get(
    "/identities",
    response_model=list[IdentityResponse],
    summary="List WhatsApp identities",
    description="List all WhatsApp identities for the current tenant.",
)
async def list_identities(
    request: Request,
    status_filter: Optional[IdentityStatus] = None,
    user: InternalUserContext = Depends(require_session),
):
    """List WhatsApp identities for current tenant."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    identities = await _list_identities(request, tenant_id, status_filter)
    return identities


# =============================================================================
# Helper Functions (Database Operations)
# =============================================================================


async def _check_idempotency(
    request: Request,
    idempotency_key: str,
    wa_user_id: str,
    tenant_id: Optional[int] = None,
) -> bool:
    """
    Atomically check and record idempotency.

    Uses DB function with UNIQUE constraint to prevent race conditions.

    Returns:
        True if already processed (duplicate), False if new
    """
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            # Atomic check + record using DB function
            cur.execute(
                "SELECT ops.check_and_record_idempotency(%s, %s, %s)",
                (idempotency_key, wa_user_id, tenant_id),
            )
            result = cur.fetchone()
            conn.commit()
            return result[0] if result else False
    except Exception as e:
        logger.warning("idempotency_check_failed", error=str(e))
        conn.rollback()
        # On error, allow processing (fail open for availability)
        # The actual processing will create events that can be deduplicated
        return False


async def _resolve_identity(
    request: Request,
    wa_user_id: str,
) -> Optional[dict]:
    """Resolve WhatsApp user ID to internal identity."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    i.id, i.tenant_id, i.user_id, i.site_id, i.status,
                    t.thread_id
                FROM ops.whatsapp_identities i
                LEFT JOIN ops.threads t ON t.identity_id = i.id
                WHERE i.wa_user_id = %s
                  AND i.status = 'ACTIVE'
                LIMIT 1
                """,
                (wa_user_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "tenant_id": row[1],
                    "user_id": str(row[2]),
                    "site_id": row[3],
                    "status": row[4],
                    "thread_id": row[5],
                }
            return None
    except Exception as e:
        logger.warning("identity_resolution_failed", error=str(e))
        return None


async def _handle_pairing_attempt(
    request: Request,
    wa_user_id: str,
    wa_phone: str,
    text: str,
) -> Optional[dict]:
    """Handle pairing attempt if message is PAIR command."""
    text_upper = text.strip().upper()
    if not text_upper.startswith("PAIR "):
        return None

    otp = text_upper[5:].strip()
    if not otp or len(otp) != 6 or not otp.isdigit():
        return {
            "reply_text": "Invalid format. Please send: PAIR <6-digit-code>",
        }

    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return {"reply_text": "Service temporarily unavailable. Please try again."}

    try:
        with conn.cursor() as cur:
            # Call the verify_pairing_otp function
            phone_hash = hash_phone_number(wa_phone)
            cur.execute(
                """
                SELECT ops.verify_pairing_otp(
                    (SELECT user_id FROM ops.pairing_invites
                     WHERE otp_hash = encode(sha256(%s::bytea), 'hex')
                       AND status = 'PENDING'
                       AND expires_at > NOW()
                     ORDER BY created_at DESC
                     LIMIT 1),
                    %s,
                    %s,
                    %s
                )
                """,
                (otp, otp, wa_user_id, phone_hash),
            )
            result = cur.fetchone()
            if result and result[0]:
                result_json = result[0]
                if result_json.get("success"):
                    record_pairing(result_json["tenant_id"], "success")
                    conn.commit()
                    return {
                        "reply_text": (
                            "Successfully paired! You can now use the Ops Assistant.\n"
                            "Try asking: 'What can you help me with?'"
                        ),
                    }
                else:
                    error = result_json.get("error", "UNKNOWN")
                    record_pairing(0, error.lower())
                    conn.rollback()

                    if error == "INVALID_OTP":
                        remaining = result_json.get("remaining_attempts", 0)
                        return {
                            "reply_text": f"Invalid code. {remaining} attempts remaining.",
                        }
                    elif error == "MAX_ATTEMPTS_EXCEEDED":
                        return {
                            "reply_text": "Too many failed attempts. Please request a new code.",
                        }
                    elif error == "NO_VALID_INVITE":
                        return {
                            "reply_text": "No valid pairing invite found. Please request a new code.",
                        }
                    elif error == "ALREADY_PAIRED":
                        return {
                            "reply_text": "This WhatsApp number is already paired.",
                        }
                    else:
                        return {
                            "reply_text": "Pairing failed. Please try again or contact support.",
                        }
            else:
                return {
                    "reply_text": "Invalid code. Please check and try again.",
                }
    except Exception as e:
        logger.exception("pairing_error", error=str(e))
        record_pairing(0, "error")
        return {"reply_text": "Pairing failed. Please try again."}


async def _process_message(
    request: Request,
    identity: dict,
    message: WhatsAppMessage,
) -> dict:
    """Process message through orchestrator."""
    # TODO: Implement full LangGraph orchestrator
    # For now, return a placeholder response
    return {
        "reply_text": (
            "Message received! The AI assistant is being configured. "
            "Full functionality coming soon."
        ),
    }


async def _get_user_by_id(request: Request, user_id: str) -> Optional[dict]:
    """Get user by ID."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.display_name, ub.tenant_id
                FROM auth.users u
                LEFT JOIN auth.user_bindings ub ON ub.user_id = u.id
                WHERE u.id = %s::uuid
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "email": row[1],
                    "display_name": row[2],
                    "tenant_id": row[3],
                }
            return None
    except Exception as e:
        logger.warning("user_lookup_failed", error=str(e))
        return None


async def _create_pairing_invite(
    request: Request,
    tenant_id: int,
    user_id: str,
    otp_hash: str,
    expires_at: datetime,
    max_attempts: int,
    created_by: str,
) -> str:
    """Create a pairing invite in the database."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.pairing_invites
                    (tenant_id, user_id, otp_hash, expires_at, max_attempts, created_by)
                VALUES (%s, %s::uuid, %s, %s, %s, %s::uuid)
                RETURNING id
                """,
                (tenant_id, user_id, otp_hash, expires_at, max_attempts, created_by),
            )
            result = cur.fetchone()
            conn.commit()
            return str(result[0])
    except Exception as e:
        logger.exception("create_invite_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create invite",
        )


async def _get_identity_by_id(request: Request, identity_id: str) -> Optional[dict]:
    """Get identity by ID."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, wa_user_id, tenant_id, user_id, site_id, status,
                       paired_at, paired_via, last_activity_at
                FROM ops.whatsapp_identities
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "wa_user_id": row[1],
                    "tenant_id": row[2],
                    "user_id": str(row[3]),
                    "site_id": row[4],
                    "status": row[5],
                    "paired_at": row[6],
                    "paired_via": row[7],
                    "last_activity_at": row[8],
                }
            return None
    except Exception as e:
        logger.warning("identity_lookup_failed", error=str(e))
        return None


async def _revoke_identity(
    request: Request,
    identity_id: str,
    reason: str,
) -> None:
    """Revoke an identity."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.whatsapp_identities
                SET status = 'REVOKED', updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            conn.commit()
    except Exception as e:
        logger.exception("revoke_identity_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke identity",
        )


async def _list_identities(
    request: Request,
    tenant_id: int,
    status_filter: Optional[IdentityStatus],
) -> list[dict]:
    """List identities for a tenant."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, wa_user_id, tenant_id, user_id, site_id, status,
                       paired_at, paired_via, last_activity_at
                FROM ops.whatsapp_identities
                WHERE tenant_id = %s
            """
            params = [tenant_id]

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter.value)

            query += " ORDER BY paired_at DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                IdentityResponse(
                    id=str(row[0]),
                    wa_user_id=row[1],
                    tenant_id=row[2],
                    user_id=str(row[3]),
                    site_id=row[4],
                    status=IdentityStatus(row[5]),
                    paired_at=row[6],
                    paired_via=row[7],
                    last_activity_at=row[8],
                )
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_identities_failed", error=str(e))
        return []
