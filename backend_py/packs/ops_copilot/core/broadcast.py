"""
Broadcast Validation and Execution Module

Validates and executes broadcast messages for ops and driver audiences.
"""

import re
from typing import Optional, List, Dict, Any, Set
from uuid import uuid4

from ..observability.tracing import get_logger
from ..observability.metrics import record_broadcast

logger = get_logger("broadcast")


class BroadcastValidationError(Exception):
    """Raised when broadcast validation fails."""

    def __init__(self, message: str, error_code: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


async def validate_ops_broadcast(
    conn,
    tenant_id: int,
    message: str,
    recipient_ids: List[str],
) -> Dict[str, Any]:
    """
    Validate an ops broadcast request.

    Ops broadcasts allow free text to ops staff identities.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        message: Broadcast message text
        recipient_ids: List of identity IDs to send to

    Returns:
        Validation result with filtered recipients

    Raises:
        BroadcastValidationError: If validation fails
    """
    if not message or len(message.strip()) == 0:
        raise BroadcastValidationError(
            "Message cannot be empty",
            "EMPTY_MESSAGE",
        )

    if len(message) > 4096:
        raise BroadcastValidationError(
            "Message exceeds maximum length (4096 characters)",
            "MESSAGE_TOO_LONG",
            {"max_length": 4096, "actual_length": len(message)},
        )

    # Validate recipients exist and belong to tenant
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, wa_user_id, user_id
                FROM ops.whatsapp_identities
                WHERE tenant_id = %s
                  AND status = 'ACTIVE'
                  AND id = ANY(%s::uuid[])
                """,
                (tenant_id, recipient_ids),
            )
            valid_recipients = [
                {
                    "identity_id": str(row[0]),
                    "wa_user_id": row[1],
                    "user_id": str(row[2]),
                }
                for row in cur.fetchall()
            ]

            if not valid_recipients:
                raise BroadcastValidationError(
                    "No valid recipients found",
                    "NO_VALID_RECIPIENTS",
                )

            invalid_count = len(recipient_ids) - len(valid_recipients)

            return {
                "valid": True,
                "recipients": valid_recipients,
                "recipient_count": len(valid_recipients),
                "invalid_count": invalid_count,
            }

    except BroadcastValidationError:
        raise
    except Exception as e:
        logger.exception("ops_broadcast_validation_failed", error=str(e))
        raise BroadcastValidationError(
            "Validation failed",
            "VALIDATION_ERROR",
            {"error": str(e)},
        )


async def validate_driver_broadcast(
    conn,
    tenant_id: int,
    template_key: str,
    params: Dict[str, str],
    driver_ids: List[str],
) -> Dict[str, Any]:
    """
    Validate a driver broadcast request.

    Driver broadcasts require:
    1. Pre-approved WhatsApp template
    2. Valid placeholders
    3. All target drivers must be opted-in

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        template_key: Broadcast template key
        params: Template placeholder values
        driver_ids: List of driver IDs to send to

    Returns:
        Validation result with template info and filtered recipients

    Raises:
        BroadcastValidationError: If validation fails
    """
    try:
        with conn.cursor() as cur:
            # Get and validate template
            cur.execute(
                """
                SELECT id, body_template, expected_params, allowed_placeholders,
                       wa_template_name, is_approved, audience
                FROM ops.broadcast_templates
                WHERE template_key = %s
                  AND (tenant_id = %s OR tenant_id IS NULL)
                  AND is_active = TRUE
                  AND is_deprecated = FALSE
                ORDER BY tenant_id NULLS LAST
                LIMIT 1
                """,
                (template_key, tenant_id),
            )
            template = cur.fetchone()

            if not template:
                raise BroadcastValidationError(
                    f"Template '{template_key}' not found",
                    "TEMPLATE_NOT_FOUND",
                )

            template_id = str(template[0])
            body_template = template[1]
            expected_params = template[2] or []
            allowed_placeholders = template[3] or []
            wa_template_name = template[4]
            is_approved = template[5]
            audience = template[6]

            # Validate audience is DRIVER
            if audience != "DRIVER":
                raise BroadcastValidationError(
                    "Template is not configured for driver audience",
                    "WRONG_AUDIENCE",
                    {"template_audience": audience, "required": "DRIVER"},
                )

            # Validate template is approved
            if not is_approved:
                raise BroadcastValidationError(
                    "Template is not approved by Meta",
                    "TEMPLATE_NOT_APPROVED",
                )

            # Validate WA template exists
            if not wa_template_name:
                raise BroadcastValidationError(
                    "Template missing WhatsApp template name",
                    "MISSING_WA_TEMPLATE",
                )

            # Validate all expected params are provided
            missing_params = set(expected_params) - set(params.keys())
            if missing_params:
                raise BroadcastValidationError(
                    f"Missing required parameters: {', '.join(missing_params)}",
                    "MISSING_PARAMS",
                    {"missing": list(missing_params)},
                )

            # Validate no extra params (if allowed_placeholders is set)
            if allowed_placeholders:
                extra_params = set(params.keys()) - set(allowed_placeholders)
                if extra_params:
                    raise BroadcastValidationError(
                        f"Invalid parameters: {', '.join(extra_params)}",
                        "INVALID_PARAMS",
                        {"invalid": list(extra_params), "allowed": allowed_placeholders},
                    )

            # Check driver opt-in status
            cur.execute(
                """
                SELECT driver_id, wa_user_id, is_subscribed
                FROM ops.broadcast_subscriptions
                WHERE tenant_id = %s
                  AND driver_id = ANY(%s)
                """,
                (tenant_id, driver_ids),
            )
            subscription_rows = cur.fetchall()
            subscriptions = {
                row[0]: {"wa_user_id": row[1], "is_subscribed": row[2]}
                for row in subscription_rows
            }

            # Filter to only opted-in drivers
            valid_drivers = []
            opted_out = []
            not_found = []

            for driver_id in driver_ids:
                if driver_id not in subscriptions:
                    not_found.append(driver_id)
                elif not subscriptions[driver_id]["is_subscribed"]:
                    opted_out.append(driver_id)
                else:
                    valid_drivers.append({
                        "driver_id": driver_id,
                        "wa_user_id": subscriptions[driver_id]["wa_user_id"],
                    })

            if not valid_drivers:
                raise BroadcastValidationError(
                    "No opted-in drivers found",
                    "NO_OPTED_IN_DRIVERS",
                    {"opted_out_count": len(opted_out), "not_found_count": len(not_found)},
                )

            return {
                "valid": True,
                "template_id": template_id,
                "template_key": template_key,
                "wa_template_name": wa_template_name,
                "recipients": valid_drivers,
                "recipient_count": len(valid_drivers),
                "opted_out_count": len(opted_out),
                "not_found_count": len(not_found),
            }

    except BroadcastValidationError:
        raise
    except Exception as e:
        logger.exception("driver_broadcast_validation_failed", error=str(e))
        raise BroadcastValidationError(
            "Validation failed",
            "VALIDATION_ERROR",
            {"error": str(e)},
        )


async def enqueue_broadcast(
    conn,
    tenant_id: int,
    thread_id: str,
    audience: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enqueue a broadcast for sending (MVP stub).

    In the MVP, this just records the intent in ops.events.
    Actual WhatsApp sending is not implemented.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Source thread ID
        audience: "OPS" or "DRIVER"
        payload: Broadcast payload

    Returns:
        Enqueue result with event ID
    """
    try:
        with conn.cursor() as cur:
            event_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO ops.events (
                    event_id, tenant_id, thread_id, event_type, payload
                ) VALUES (%s::uuid, %s, %s, 'BROADCAST_ENQUEUED', %s)
                """,
                (event_id, tenant_id, thread_id, {
                    "audience": audience,
                    **payload,
                }),
            )
            conn.commit()

            record_broadcast(tenant_id, audience.lower(), "enqueued")

            logger.info(
                "broadcast_enqueued",
                event_id=event_id,
                audience=audience,
                recipient_count=payload.get("recipient_count", 0),
            )

            return {
                "enqueued": True,
                "event_id": event_id,
                "note": "Actual WhatsApp sending not implemented in MVP",
            }

    except Exception as e:
        logger.exception("enqueue_broadcast_failed", error=str(e))
        record_broadcast(tenant_id, audience.lower(), "rejected")
        raise


def render_template(template: str, params: Dict[str, str]) -> str:
    """
    Render a template with placeholder values.

    Replaces {{variable}} with values from params.

    Args:
        template: Template string with {{variable}} placeholders
        params: Dictionary of placeholder values

    Returns:
        Rendered string
    """
    result = template
    for key, value in params.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def extract_placeholders(template: str) -> List[str]:
    """
    Extract placeholder names from a template.

    Args:
        template: Template string with {{variable}} placeholders

    Returns:
        List of placeholder names
    """
    pattern = r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}"
    return re.findall(pattern, template)


def validate_placeholders(
    template: str,
    params: Dict[str, str],
    allowed: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Validate template placeholders against provided params.

    Args:
        template: Template string
        params: Provided parameters
        allowed: Optional list of allowed placeholder names

    Returns:
        Validation result with missing/extra/invalid placeholders
    """
    expected = set(extract_placeholders(template))
    provided = set(params.keys())

    missing = expected - provided
    extra = provided - expected

    invalid = []
    if allowed:
        allowed_set = set(allowed)
        invalid = list(provided - allowed_set)

    return {
        "valid": len(missing) == 0 and len(invalid) == 0,
        "missing": list(missing),
        "extra": list(extra),
        "invalid": invalid,
    }
