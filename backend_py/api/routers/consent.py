"""
SOLVEREIGN Consent Management API (P2.3)
========================================

Backend endpoint for consent persistence.
Frontend localStorage remains source of truth for blocking behavior.
This endpoint provides:
- Audit trail for compliance
- Multi-device sync for authenticated users
- Graceful degradation (anonymous users: accept but don't persist)

PRIVACY:
- No PII logged
- IP/User-Agent not stored (uses existing audit mechanism)
- Anonymous users identified only by acceptance (no fingerprinting)
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/consent", tags=["Consent"])


# =============================================================================
# MODELS
# =============================================================================


class ConsentPayload(BaseModel):
    """
    Consent payload from frontend consent banner.

    Matches localStorage format for consistency.
    """
    version: str = Field(..., description="Consent form version", example="1.0")
    timestamp: datetime = Field(..., description="When consent was given (ISO8601)")
    purposes: dict[str, bool] = Field(
        ...,
        description="Map of purpose code to granted status",
        example={"necessary": True, "analytics": False, "notifications": True}
    )


class ConsentResponse(BaseModel):
    """Response from consent storage endpoint."""
    stored: bool = Field(..., description="Whether consent was persisted to database")
    reason: Optional[str] = Field(None, description="Reason if not stored")


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post("", response_model=ConsentResponse)
async def store_consent(payload: ConsentPayload, request: Request):
    """
    Store consent choices for audit trail.

    - Authenticated users: stored in consent.user_consents via record_consent()
    - Anonymous users: accepted but not persisted (localStorage is SoT)
    - Idempotent: uses existing history mechanism (is_current flag)

    PRIVACY: No PII stored. Uses existing consent schema audit trail.
    """
    # Get user context (may be None for anonymous)
    user_id = getattr(request.state, "user_id", None)

    if not user_id:
        # Anonymous user: accept but don't persist
        # localStorage is the source of truth for these users
        logger.debug("consent_accepted_anonymous")
        return ConsentResponse(stored=False, reason="anonymous")

    # Get database connection
    db = getattr(request.state, "db", None)
    if not db:
        logger.warning("consent_no_db_connection")
        return ConsentResponse(stored=False, reason="no_db")

    try:
        # Use the existing consent.record_consent() function for each purpose
        # This handles history (is_current flag) and audit logging automatically
        for purpose_code, granted in payload.purposes.items():
            await db.execute(
                """SELECT consent.record_consent($1, $2, $3, NULL, NULL, $4)""",
                user_id,
                purpose_code,
                granted,
                payload.version,
            )

        logger.info(
            "consent_stored",
            extra={
                "user_id": user_id,
                "version": payload.version,
                "purpose_count": len(payload.purposes),
            }
        )
        return ConsentResponse(stored=True)

    except Exception as e:
        # Log error but don't expose details
        logger.warning(f"consent_storage_failed: {e}")
        return ConsentResponse(stored=False, reason="storage_error")


@router.get("", response_model=dict)
async def get_consent(request: Request):
    """
    Retrieve stored consent for current user.

    Frontend should prefer localStorage; this is for sync/audit.
    Only returns data for authenticated users.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return {"stored": False, "reason": "anonymous"}

    db = getattr(request.state, "db", None)
    if not db:
        return {"stored": False, "reason": "no_db"}

    try:
        # Use the existing consent.get_user_consents() function
        rows = await db.fetch(
            """SELECT * FROM consent.get_user_consents($1)""",
            user_id
        )

        if not rows:
            return {"stored": False, "reason": "no_consent"}

        # Build purposes dict from rows
        purposes = {}
        latest_granted_at = None

        for row in rows:
            purposes[row["purpose_code"]] = row["granted"]
            if row["granted_at"] and (not latest_granted_at or row["granted_at"] > latest_granted_at):
                latest_granted_at = row["granted_at"]

        return {
            "stored": True,
            "purposes": purposes,
            "timestamp": latest_granted_at.isoformat() if latest_granted_at else None,
        }

    except Exception as e:
        logger.warning(f"consent_retrieval_failed: {e}")
        return {"stored": False, "reason": "retrieval_error"}
