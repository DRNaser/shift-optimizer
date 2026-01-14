"""
Identity Resolution Module

Resolves WhatsApp user IDs to internal user bindings and permissions.
"""

import hashlib
from typing import Optional, Dict, Any
from dataclasses import dataclass

from ..observability.tracing import get_logger

logger = get_logger("identity")


def generate_thread_id(tenant_id: int, site_id: Optional[int], wa_user_id: str) -> str:
    """
    Generate deterministic thread ID.

    Format: SHA-256(sv:{tenant_id}:{site_id|0}:whatsapp:{wa_user_id})
    """
    raw = f"sv:{tenant_id}:{site_id or 0}:whatsapp:{wa_user_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_phone_number(phone: str) -> str:
    """
    Hash phone number for privacy-preserving storage.

    Normalizes to E.164 format before hashing.
    """
    normalized = phone.strip().replace(" ", "").replace("-", "")
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"
    return hashlib.sha256(normalized.encode()).hexdigest()


async def resolve_identity(
    conn,
    wa_user_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Resolve WhatsApp user ID to internal identity.

    Args:
        conn: Database connection
        wa_user_id: WhatsApp user ID from Clawdbot

    Returns:
        Identity dict with user info and permissions, or None if not paired
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    i.id as identity_id,
                    i.tenant_id,
                    i.site_id,
                    i.user_id,
                    i.status,
                    u.email,
                    u.display_name,
                    r.role_name,
                    t.thread_id
                FROM ops.whatsapp_identities i
                JOIN auth.users u ON u.id = i.user_id
                JOIN auth.user_bindings ub ON ub.user_id = i.user_id AND ub.tenant_id = i.tenant_id
                JOIN auth.roles r ON r.id = ub.role_id
                LEFT JOIN ops.threads t ON t.identity_id = i.id
                WHERE i.wa_user_id = %s
                  AND i.status = 'ACTIVE'
                LIMIT 1
                """,
                (wa_user_id,),
            )
            row = cur.fetchone()

            if not row:
                logger.debug("identity_not_found", wa_user_id=wa_user_id)
                return None

            identity_id = str(row[0])
            tenant_id = row[1]
            site_id = row[2]
            user_id = str(row[3])
            status = row[4]
            email = row[5]
            display_name = row[6]
            role_name = row[7]
            existing_thread_id = row[8]

            # Get permissions for the role
            cur.execute(
                """
                SELECT p.permission_key
                FROM auth.role_permissions rp
                JOIN auth.permissions p ON p.id = rp.permission_id
                JOIN auth.roles r ON r.id = rp.role_id
                WHERE r.role_name = %s
                """,
                (role_name,),
            )
            permissions = [row[0] for row in cur.fetchall()]

            # Generate thread_id if not exists
            thread_id = existing_thread_id or generate_thread_id(
                tenant_id, site_id, wa_user_id
            )

            # Update last activity
            cur.execute(
                """
                UPDATE ops.whatsapp_identities
                SET last_activity_at = NOW(), updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            conn.commit()

            logger.debug(
                "identity_resolved",
                identity_id=identity_id,
                tenant_id=tenant_id,
                role=role_name,
            )

            return {
                "identity_id": identity_id,
                "tenant_id": tenant_id,
                "site_id": site_id,
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "role_name": role_name,
                "permissions": permissions,
                "thread_id": thread_id,
                "is_platform_admin": role_name == "platform_admin",
            }

    except Exception as e:
        logger.exception("identity_resolution_error", error=str(e))
        return None


async def get_or_create_thread(
    conn,
    identity_id: str,
    tenant_id: int,
    site_id: Optional[int],
    wa_user_id: str,
) -> str:
    """
    Get existing thread or create new one.

    Args:
        conn: Database connection
        identity_id: WhatsApp identity UUID
        tenant_id: Tenant ID
        site_id: Optional site ID
        wa_user_id: WhatsApp user ID

    Returns:
        Thread ID (UUID)
    """
    thread_id = generate_thread_id(tenant_id, site_id, wa_user_id)

    try:
        with conn.cursor() as cur:
            # Try to get existing thread
            cur.execute(
                """
                SELECT id FROM ops.threads
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            row = cur.fetchone()

            if row:
                # Update last activity
                cur.execute(
                    """
                    UPDATE ops.threads
                    SET last_message_at = NOW(),
                        message_count = message_count + 1,
                        updated_at = NOW()
                    WHERE thread_id = %s
                    RETURNING id
                    """,
                    (thread_id,),
                )
                conn.commit()
                return str(cur.fetchone()[0])

            # Create new thread
            cur.execute(
                """
                INSERT INTO ops.threads (
                    thread_id, tenant_id, site_id, identity_id,
                    message_count, last_message_at
                ) VALUES (%s, %s, %s, %s::uuid, 1, NOW())
                RETURNING id
                """,
                (thread_id, tenant_id, site_id, identity_id),
            )
            result = cur.fetchone()
            conn.commit()

            logger.info(
                "thread_created",
                thread_id=thread_id,
                tenant_id=tenant_id,
            )

            return str(result[0])

    except Exception as e:
        logger.exception("thread_creation_error", error=str(e))
        conn.rollback()
        raise


async def update_identity_activity(
    conn,
    identity_id: str,
) -> None:
    """Update identity last activity timestamp."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.whatsapp_identities
                SET last_activity_at = NOW(), updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            conn.commit()
    except Exception as e:
        logger.warning("update_activity_failed", error=str(e))


async def check_identity_status(
    conn,
    identity_id: str,
) -> Optional[str]:
    """
    Check if identity is still active.

    Returns status string or None if not found.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM ops.whatsapp_identities
                WHERE id = %s::uuid
                """,
                (identity_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.warning("status_check_failed", error=str(e))
        return None
