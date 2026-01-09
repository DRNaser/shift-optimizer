"""
SOLVEREIGN V4.1 - Public Portal API
=====================================

Public endpoints for driver portal access via magic links.
NO Entra ID authentication - uses JWT magic link tokens.

ENDPOINTS:
    GET  /my-plan              - View driver's published plan
    POST /api/portal/read      - Record read receipt (idempotent)
    POST /api/portal/ack       - Accept/Decline plan (single-use)
    GET  /api/portal/status    - Get current ack status

Security:
    - Token validation via JWT
    - Rate limiting per jti_hash
    - NEVER log raw tokens
    - Single-use ACK tokens
"""

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, HTTPException, Query, status, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ...packs.portal.models import (
    TokenScope,
    TokenStatus,
    AckStatus,
    AckReasonCode,
    AckSource,
    PortalAction,
    validate_free_text,
    hash_ip,
)
from ...packs.portal.token_service import (
    PortalTokenService,
    PortalAuthService,
    TokenConfig,
    create_mock_auth_service,
)
from ...packs.portal.repository import MockPortalRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Portal (Public)"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class ReadRequest(BaseModel):
    """Request to record a read receipt."""
    token: Optional[str] = Field(None, description="Bearer token (alternative to header)")


class ReadResponse(BaseModel):
    """Response from read receipt."""
    success: bool = True
    snapshot_id: str
    driver_id: str
    first_read_at: str
    last_read_at: str
    read_count: int
    is_first_read: bool


class AckRequest(BaseModel):
    """Request to acknowledge (accept/decline) a plan."""
    token: Optional[str] = Field(None, description="Bearer token (alternative to header)")
    status: str = Field(..., description="ACCEPTED or DECLINED")
    reason_code: Optional[str] = Field(None, description="Reason code for decline")
    free_text: Optional[str] = Field(None, max_length=200, description="Optional free text (max 200 chars)")


class AckResponse(BaseModel):
    """Response from acknowledgment."""
    success: bool = True
    snapshot_id: str
    driver_id: str
    status: str
    ack_at: str
    is_new: bool  # True if this was a new ack, False if returning existing
    token_revoked: bool  # True if token was revoked after ACK


class StatusResponse(BaseModel):
    """Response with current ack status."""
    snapshot_id: str
    driver_id: str
    is_read: bool
    read_count: int
    is_acked: bool
    ack_status: Optional[str] = None
    ack_at: Optional[str] = None
    is_superseded: bool = False
    new_snapshot_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""
    success: bool = False
    error_code: str
    error_message: str


# =============================================================================
# DEPENDENCY: Get Auth Service
# =============================================================================

# Global auth service (initialized lazily)
_auth_service: Optional[PortalAuthService] = None
_repository: Optional[MockPortalRepository] = None


def get_auth_service() -> PortalAuthService:
    """Get or create the portal auth service."""
    global _auth_service, _repository

    if _auth_service is None:
        # Use mock for now - replace with PostgresPortalRepository in production
        _auth_service, _repository = create_mock_auth_service()

    return _auth_service


def get_repository() -> MockPortalRepository:
    """Get the portal repository."""
    global _repository
    if _repository is None:
        get_auth_service()  # Initialize both
    return _repository


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_token_from_request(
    request: Request,
    t: Optional[str] = Query(None, description="Token query parameter"),
    body_token: Optional[str] = None,
) -> str:
    """
    Extract token from request (query param, body, or header).

    Priority: query param > body > Authorization header
    """
    # 1. Query parameter
    if t:
        return t

    # 2. Body (passed from endpoint)
    if body_token:
        return body_token

    # 3. Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": "MISSING_TOKEN", "error_message": "Token required"},
    )


# =============================================================================
# PUBLIC ENDPOINTS
# =============================================================================

@router.get(
    "/my-plan",
    response_class=HTMLResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def view_my_plan(
    request: Request,
    t: str = Query(..., description="Magic link token"),
    auth_service: PortalAuthService = Depends(get_auth_service),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    View driver's published plan.

    This is the main entry point for drivers via magic link.
    Returns minimal mobile-friendly HTML.
    """
    client_ip = get_client_ip(request)

    # Validate token
    result = await auth_service.validate_and_authorize(
        t,
        required_scope=TokenScope.READ,
        ip_address=client_ip,
    )

    if not result.is_valid:
        if result.rate_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error_code": "RATE_LIMITED",
                    "error_message": f"Too many requests. Retry after {result.retry_after_seconds}s",
                },
                headers={"Retry-After": str(result.retry_after_seconds)},
            )

        status_code = (
            status.HTTP_401_UNAUTHORIZED
            if result.status in (TokenStatus.EXPIRED, TokenStatus.INVALID)
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=status_code,
            detail={"error_code": result.error_code, "error_message": result.error_message},
        )

    token = result.token

    # Record read receipt
    read_receipt = await repository.record_read(
        tenant_id=token.tenant_id,
        site_id=token.site_id,
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
    )

    # Check if superseded
    supersede = await repository.get_supersede(token.tenant_id, token.snapshot_id)
    is_superseded = supersede is not None
    new_snapshot_id = supersede.new_snapshot_id if supersede else None

    # Get existing ack if any
    ack = await repository.get_ack(token.tenant_id, token.snapshot_id, token.driver_id)

    # Generate HTML (minimal mobile-friendly view)
    html_content = _generate_plan_html(
        token=token,
        read_receipt=read_receipt,
        ack=ack,
        is_superseded=is_superseded,
        new_snapshot_id=new_snapshot_id,
        can_ack=token.can_ack and ack is None,
        raw_token=t,
    )

    return HTMLResponse(content=html_content)


@router.post(
    "/api/portal/read",
    response_model=ReadResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def record_read(
    request: Request,
    body: Optional[ReadRequest] = None,
    t: Optional[str] = Query(None),
    auth_service: PortalAuthService = Depends(get_auth_service),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Record read receipt (idempotent).

    Call this when driver views their plan.
    Multiple calls update last_read_at and increment read_count.
    """
    # Get token
    body_token = body.token if body else None
    raw_token = await get_token_from_request(request, t, body_token)
    client_ip = get_client_ip(request)

    # Validate
    result = await auth_service.validate_and_authorize(
        raw_token,
        required_scope=TokenScope.READ,
        ip_address=client_ip,
    )

    if not result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED if result.status == TokenStatus.INVALID else status.HTTP_403_FORBIDDEN,
            detail={"error_code": result.error_code, "error_message": result.error_message},
        )

    token = result.token

    # Record read (idempotent)
    receipt = await repository.record_read(
        tenant_id=token.tenant_id,
        site_id=token.site_id,
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
    )

    return ReadResponse(
        success=True,
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
        first_read_at=receipt.first_read_at.isoformat(),
        last_read_at=receipt.last_read_at.isoformat(),
        read_count=receipt.read_count,
        is_first_read=receipt.is_first_read,
    )


@router.post(
    "/api/portal/ack",
    response_model=AckResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def acknowledge_plan(
    request: Request,
    body: AckRequest,
    t: Optional[str] = Query(None),
    auth_service: PortalAuthService = Depends(get_auth_service),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Accept or decline the plan.

    IDEMPOTENT: Returns existing ack if already acknowledged.
    SINGLE-USE: Token is revoked after first successful new ACK.

    Note: This is arbeitsrechtlich relevant - acks are immutable.
    """
    # Get token
    raw_token = await get_token_from_request(request, t, body.token)
    client_ip = get_client_ip(request)

    # Validate with ACK scope
    result = await auth_service.validate_and_authorize(
        raw_token,
        required_scope=TokenScope.ACK,
        ip_address=client_ip,
    )

    if not result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED if result.status == TokenStatus.INVALID else status.HTTP_403_FORBIDDEN,
            detail={"error_code": result.error_code, "error_message": result.error_message},
        )

    token = result.token

    # Validate status
    try:
        ack_status = AckStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_STATUS", "error_message": "Status must be ACCEPTED or DECLINED"},
        )

    # Validate reason code
    reason_code = None
    if body.reason_code:
        try:
            reason_code = AckReasonCode(body.reason_code)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_REASON_CODE",
                    "error_message": f"Invalid reason code: {body.reason_code}",
                },
            )

    # Validate and sanitize free text
    free_text = validate_free_text(body.free_text)

    # Check for existing ack (idempotent return)
    existing_ack = await repository.get_ack(
        token.tenant_id,
        token.snapshot_id,
        token.driver_id,
    )

    if existing_ack:
        # Return existing (immutable)
        return AckResponse(
            success=True,
            snapshot_id=token.snapshot_id,
            driver_id=token.driver_id,
            status=existing_ack.status.value,
            ack_at=existing_ack.ack_at.isoformat(),
            is_new=False,
            token_revoked=False,
        )

    # Record new ack
    ack = await repository.record_ack(
        tenant_id=token.tenant_id,
        site_id=token.site_id,
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
        status=ack_status,
        reason_code=reason_code,
        free_text=free_text,
        source=AckSource.PORTAL,
    )

    # Revoke token (single-use ACK)
    token_revoked = await auth_service.revoke_token_after_ack(token.jti_hash)

    logger.info(
        f"Plan acknowledged: snapshot={token.snapshot_id[:8]}..., "
        f"driver={token.driver_id}, status={ack_status.value}"
    )

    return AckResponse(
        success=True,
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
        status=ack.status.value,
        ack_at=ack.ack_at.isoformat(),
        is_new=True,
        token_revoked=token_revoked,
    )


@router.get(
    "/api/portal/status",
    response_model=StatusResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def get_status(
    request: Request,
    t: str = Query(..., description="Magic link token"),
    auth_service: PortalAuthService = Depends(get_auth_service),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Get current status (read/ack) for the driver.

    Useful for checking if already acknowledged.
    """
    client_ip = get_client_ip(request)

    result = await auth_service.validate_and_authorize(
        t,
        required_scope=None,  # Any scope allowed
        ip_address=client_ip,
    )

    if not result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": result.error_code, "error_message": result.error_message},
        )

    token = result.token

    # Get read receipt
    read_receipt = await repository.get_read_receipt(
        token.tenant_id,
        token.snapshot_id,
        token.driver_id,
    )

    # Get ack
    ack = await repository.get_ack(
        token.tenant_id,
        token.snapshot_id,
        token.driver_id,
    )

    # Check supersede
    supersede = await repository.get_supersede(token.tenant_id, token.snapshot_id)

    return StatusResponse(
        snapshot_id=token.snapshot_id,
        driver_id=token.driver_id,
        is_read=read_receipt is not None,
        read_count=read_receipt.read_count if read_receipt else 0,
        is_acked=ack is not None,
        ack_status=ack.status.value if ack else None,
        ack_at=ack.ack_at.isoformat() if ack else None,
        is_superseded=supersede is not None,
        new_snapshot_id=supersede.new_snapshot_id if supersede else None,
    )


# =============================================================================
# HTML RENDERING
# =============================================================================

def _generate_plan_html(
    token,
    read_receipt,
    ack,
    is_superseded: bool,
    new_snapshot_id: Optional[str],
    can_ack: bool,
    raw_token: str,
) -> str:
    """
    Generate minimal mobile-friendly HTML for plan view.

    In production, this should be replaced with:
    - Pre-rendered driver views from portal.driver_views
    - Or a proper frontend application
    """
    # Status badge
    if ack:
        badge_color = "#10b981" if ack.status == AckStatus.ACCEPTED else "#ef4444"
        badge_text = "Akzeptiert" if ack.status == AckStatus.ACCEPTED else "Abgelehnt"
    elif read_receipt:
        badge_color = "#3b82f6"
        badge_text = "Gelesen"
    else:
        badge_color = "#6b7280"
        badge_text = "Ungelesen"

    # Superseded banner
    superseded_html = ""
    if is_superseded:
        superseded_html = f"""
        <div style="background: #fef3c7; border: 1px solid #f59e0b; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
            <strong>Hinweis:</strong> Es gibt eine neuere Version dieses Plans.
            <br>Neue Snapshot-ID: {new_snapshot_id[:8] if new_snapshot_id else 'N/A'}...
        </div>
        """

    # ACK form
    ack_form = ""
    if can_ack and not is_superseded:
        ack_form = f"""
        <div style="margin-top: 24px; padding: 16px; background: #f3f4f6; border-radius: 8px;">
            <h3 style="margin: 0 0 16px 0;">Plan bestätigen</h3>
            <form id="ackForm" style="display: flex; flex-direction: column; gap: 12px;">
                <button type="button" onclick="submitAck('ACCEPTED')"
                    style="padding: 16px; font-size: 18px; background: #10b981; color: white; border: none; border-radius: 8px; cursor: pointer;">
                    ✓ Akzeptieren
                </button>
                <button type="button" onclick="showDeclineForm()"
                    style="padding: 16px; font-size: 18px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer;">
                    ✗ Ablehnen
                </button>
            </form>

            <div id="declineForm" style="display: none; margin-top: 16px;">
                <select id="reasonCode" style="width: 100%; padding: 12px; margin-bottom: 12px; border-radius: 8px; border: 1px solid #d1d5db;">
                    <option value="">Grund auswählen (optional)</option>
                    <option value="SCHEDULING_CONFLICT">Terminkonflikt</option>
                    <option value="PERSONAL_REASONS">Persönliche Gründe</option>
                    <option value="HEALTH_ISSUE">Gesundheitliche Gründe</option>
                    <option value="VACATION_CONFLICT">Urlaubskonflikt</option>
                    <option value="OTHER">Sonstiges</option>
                </select>
                <textarea id="freeText" placeholder="Kommentar (max 200 Zeichen)" maxlength="200"
                    style="width: 100%; padding: 12px; margin-bottom: 12px; border-radius: 8px; border: 1px solid #d1d5db; min-height: 80px;"></textarea>
                <button type="button" onclick="submitAck('DECLINED')"
                    style="padding: 16px; font-size: 18px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer; width: 100%;">
                    Ablehnung senden
                </button>
            </div>
        </div>

        <script>
            function showDeclineForm() {{
                document.getElementById('declineForm').style.display = 'block';
            }}

            async function submitAck(status) {{
                const body = {{
                    status: status,
                    reason_code: document.getElementById('reasonCode')?.value || null,
                    free_text: document.getElementById('freeText')?.value || null,
                }};

                try {{
                    const response = await fetch('/api/portal/ack?t={raw_token}', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(body),
                    }});

                    const data = await response.json();

                    if (response.ok) {{
                        alert(status === 'ACCEPTED' ? 'Plan akzeptiert!' : 'Plan abgelehnt.');
                        window.location.reload();
                    }} else {{
                        alert('Fehler: ' + (data.error_message || 'Unbekannter Fehler'));
                    }}
                }} catch (error) {{
                    alert('Netzwerkfehler. Bitte versuchen Sie es erneut.');
                }}
            }}
        </script>
        """

    # Ack status display
    ack_status_html = ""
    if ack:
        status_text = "Akzeptiert" if ack.status == AckStatus.ACCEPTED else "Abgelehnt"
        ack_status_html = f"""
        <div style="margin-top: 24px; padding: 16px; background: {'#d1fae5' if ack.status == AckStatus.ACCEPTED else '#fee2e2'}; border-radius: 8px;">
            <strong>Status:</strong> {status_text}
            <br><small>am {ack.ack_at.strftime('%d.%m.%Y %H:%M') if ack.ack_at else 'N/A'}</small>
            {f'<br><small>Grund: {ack.reason_code.value if ack.reason_code else "N/A"}</small>' if ack.reason_code else ''}
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mein Dienstplan - SOLVEREIGN</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #f9fafb;
                padding: 16px;
                max-width: 600px;
                margin: 0 auto;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
            }}
            .badge {{
                padding: 6px 12px;
                border-radius: 9999px;
                font-size: 14px;
                font-weight: 500;
                color: white;
            }}
            .card {{
                background: white;
                border-radius: 12px;
                padding: 20px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="font-size: 24px;">Mein Dienstplan</h1>
            <span class="badge" style="background: {badge_color};">{badge_text}</span>
        </div>

        {superseded_html}

        <div class="card">
            <p><strong>Fahrer-ID:</strong> {token.driver_id}</p>
            <p><strong>Snapshot:</strong> {token.snapshot_id[:8]}...</p>
            <p><strong>Gelesen:</strong> {read_receipt.read_count if read_receipt else 0}x</p>

            <hr style="margin: 16px 0; border: none; border-top: 1px solid #e5e7eb;">

            <p style="color: #6b7280; font-size: 14px;">
                Der vollständige Wochenplan wird aus der Datenbank geladen.
                <br>In der Produktionsversion werden hier die Schichten angezeigt.
            </p>

            {ack_status_html}
        </div>

        {ack_form}

        <footer style="margin-top: 32px; text-align: center; color: #9ca3af; font-size: 12px;">
            SOLVEREIGN Driver Portal v4.1
        </footer>
    </body>
    </html>
    """
