"""
OTP Pairing Module

Handles pairing flow for WhatsApp identities.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

from ..observability.tracing import get_logger
from ..observability.metrics import record_pairing

logger = get_logger("pairing")


def generate_otp() -> Tuple[str, str]:
    """
    Generate a 6-digit OTP and its hash.

    Returns:
        Tuple of (plain_otp, otp_hash)
    """
    otp = "".join(secrets.choice("0123456789") for _ in range(6))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    return otp, otp_hash


def hash_otp(otp: str) -> str:
    """Hash an OTP for secure storage."""
    return hashlib.sha256(otp.encode()).hexdigest()


def parse_pair_command(text: str) -> Optional[str]:
    """
    Parse PAIR command from message text.

    Args:
        text: Message text

    Returns:
        OTP string if valid PAIR command, None otherwise
    """
    text = text.strip().upper()

    if not text.startswith("PAIR "):
        return None

    otp = text[5:].strip()

    # Validate OTP format (6 digits)
    if len(otp) != 6 or not otp.isdigit():
        return None

    return otp


async def create_pairing_invite(
    conn,
    tenant_id: int,
    user_id: str,
    created_by: str,
    expires_minutes: int = 15,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """
    Create a pairing invite for a user.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        user_id: Target user UUID
        created_by: Admin user UUID who created the invite
        expires_minutes: Expiration time in minutes
        max_attempts: Maximum OTP verification attempts

    Returns:
        Dict with invite_id, otp (plain), expires_at
    """
    otp, otp_hash = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.pairing_invites (
                    tenant_id, user_id, otp_hash, expires_at,
                    max_attempts, created_by
                ) VALUES (%s, %s::uuid, %s, %s, %s, %s::uuid)
                RETURNING id
                """,
                (tenant_id, user_id, otp_hash, expires_at, max_attempts, created_by),
            )
            invite_id = str(cur.fetchone()[0])
            conn.commit()

            logger.info(
                "pairing_invite_created",
                invite_id=invite_id,
                user_id=user_id,
                expires_minutes=expires_minutes,
            )

            return {
                "invite_id": invite_id,
                "otp": otp,  # Plain OTP (shown once to admin)
                "expires_at": expires_at,
            }

    except Exception as e:
        logger.exception("create_invite_failed", error=str(e))
        conn.rollback()
        raise


async def verify_pairing_otp(
    conn,
    wa_user_id: str,
    wa_phone_hash: str,
    otp: str,
) -> Dict[str, Any]:
    """
    Verify OTP and create identity binding if valid.

    Args:
        conn: Database connection
        wa_user_id: WhatsApp user ID
        wa_phone_hash: SHA-256 hash of phone number
        otp: Plain OTP from user

    Returns:
        Result dict with success status and details
    """
    otp_hash = hash_otp(otp)

    try:
        with conn.cursor() as cur:
            # Find valid pending invite with matching OTP hash
            cur.execute(
                """
                SELECT id, tenant_id, user_id, max_attempts, attempt_count
                FROM ops.pairing_invites
                WHERE otp_hash = %s
                  AND status = 'PENDING'
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (otp_hash,),
            )
            invite = cur.fetchone()

            if not invite:
                # OTP not found - could be wrong OTP or expired
                # Try to find any pending invite to increment attempts
                logger.warning("pairing_otp_not_found", wa_user_id=wa_user_id)
                record_pairing(0, "invalid_otp")
                return {
                    "success": False,
                    "error": "INVALID_OTP",
                    "message": "Invalid or expired pairing code",
                }

            invite_id = str(invite[0])
            tenant_id = invite[1]
            user_id = str(invite[2])
            max_attempts = invite[3]
            attempt_count = invite[4]

            # Check if already exhausted
            if attempt_count >= max_attempts:
                cur.execute(
                    """
                    UPDATE ops.pairing_invites
                    SET status = 'EXHAUSTED'
                    WHERE id = %s::uuid
                    """,
                    (invite_id,),
                )
                conn.commit()
                record_pairing(tenant_id, "max_attempts")
                return {
                    "success": False,
                    "error": "MAX_ATTEMPTS_EXCEEDED",
                    "message": "Too many failed attempts. Request a new code.",
                }

            # Check if WA user already paired to this tenant
            cur.execute(
                """
                SELECT id FROM ops.whatsapp_identities
                WHERE wa_user_id = %s AND tenant_id = %s AND status = 'ACTIVE'
                """,
                (wa_user_id, tenant_id),
            )
            if cur.fetchone():
                record_pairing(tenant_id, "already_paired")
                return {
                    "success": False,
                    "error": "ALREADY_PAIRED",
                    "message": "This WhatsApp number is already paired",
                }

            # Create identity binding
            cur.execute(
                """
                INSERT INTO ops.whatsapp_identities (
                    wa_user_id, wa_phone_hash, tenant_id, user_id,
                    status, paired_via
                ) VALUES (%s, %s, %s, %s::uuid, 'ACTIVE', 'OTP')
                RETURNING id
                """,
                (wa_user_id, wa_phone_hash, tenant_id, user_id),
            )
            identity_id = str(cur.fetchone()[0])

            # Mark invite as used
            cur.execute(
                """
                UPDATE ops.pairing_invites
                SET status = 'USED',
                    used_at = NOW(),
                    used_wa_user_id = %s
                WHERE id = %s::uuid
                """,
                (wa_user_id, invite_id),
            )

            # Record event
            cur.execute(
                """
                INSERT INTO ops.events (
                    tenant_id, thread_id, event_type, payload
                ) VALUES (%s, '', 'PAIRING_SUCCESS', %s)
                """,
                (
                    tenant_id,
                    {
                        "identity_id": identity_id,
                        "invite_id": invite_id,
                        "user_id": user_id,
                    },
                ),
            )

            conn.commit()

            logger.info(
                "pairing_success",
                identity_id=identity_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            record_pairing(tenant_id, "success")

            return {
                "success": True,
                "identity_id": identity_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            }

    except Exception as e:
        logger.exception("pairing_verification_error", error=str(e))
        conn.rollback()
        record_pairing(0, "error")
        return {
            "success": False,
            "error": "INTERNAL_ERROR",
            "message": "Pairing failed. Please try again.",
        }


async def increment_attempt_count(
    conn,
    user_id: str,
) -> Dict[str, Any]:
    """
    Increment attempt count for a user's pending invite.

    Used when OTP is wrong but we found the user's invite.

    Args:
        conn: Database connection
        user_id: Target user UUID

    Returns:
        Result with remaining attempts
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.pairing_invites
                SET attempt_count = attempt_count + 1
                WHERE user_id = %s::uuid
                  AND status = 'PENDING'
                  AND expires_at > NOW()
                RETURNING id, max_attempts, attempt_count
                """,
                (user_id,),
            )
            row = cur.fetchone()
            conn.commit()

            if row:
                remaining = row[1] - row[2]
                if remaining <= 0:
                    cur.execute(
                        """
                        UPDATE ops.pairing_invites
                        SET status = 'EXHAUSTED'
                        WHERE id = %s::uuid
                        """,
                        (str(row[0]),),
                    )
                    conn.commit()
                    return {"exhausted": True, "remaining": 0}
                return {"exhausted": False, "remaining": remaining}

            return {"exhausted": False, "remaining": 0}

    except Exception as e:
        logger.warning("increment_attempt_failed", error=str(e))
        return {"exhausted": False, "remaining": 0}


async def revoke_identity(
    conn,
    identity_id: str,
    reason: str,
    revoked_by: str,
) -> bool:
    """
    Revoke a WhatsApp identity.

    Args:
        conn: Database connection
        identity_id: Identity UUID
        reason: Revocation reason
        revoked_by: Admin user UUID

    Returns:
        True if revoked successfully
    """
    try:
        with conn.cursor() as cur:
            # Get identity info for event logging
            cur.execute(
                """
                SELECT tenant_id, user_id FROM ops.whatsapp_identities
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            row = cur.fetchone()
            if not row:
                return False

            tenant_id = row[0]

            # Revoke identity
            cur.execute(
                """
                UPDATE ops.whatsapp_identities
                SET status = 'REVOKED', updated_at = NOW()
                WHERE id = %s::uuid AND status = 'ACTIVE'
                """,
                (identity_id,),
            )

            # Record event
            cur.execute(
                """
                INSERT INTO ops.events (
                    tenant_id, thread_id, event_type, payload
                ) VALUES (%s, '', 'IDENTITY_REVOKED', %s)
                """,
                (
                    tenant_id,
                    {
                        "identity_id": identity_id,
                        "reason": reason,
                        "revoked_by": revoked_by,
                    },
                ),
            )

            conn.commit()

            logger.info(
                "identity_revoked",
                identity_id=identity_id,
                reason=reason,
                revoked_by=revoked_by,
            )

            return True

    except Exception as e:
        logger.exception("revoke_identity_failed", error=str(e))
        conn.rollback()
        return False
