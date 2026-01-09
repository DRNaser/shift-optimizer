"""
SOLVEREIGN V4.1 - WhatsApp Cloud API Provider
==============================================

Integration with Meta WhatsApp Business Cloud API.

SETUP:
    1. Create Meta Business account
    2. Create WhatsApp Business App
    3. Get access token from App Dashboard
    4. Register phone number
    5. Create and submit message templates for approval

ENV VARS:
    WHATSAPP_API_VERSION: API version (default: v18.0)
    WHATSAPP_PHONE_NUMBER_ID: Your phone number ID
    WHATSAPP_ACCESS_TOKEN: Access token from App Dashboard
    WHATSAPP_BUSINESS_ACCOUNT_ID: Business account ID (for template mgmt)
"""

import os
import time
import logging
from typing import Dict, Any, Optional, List

from .base import NotificationProvider, ProviderResult

logger = logging.getLogger(__name__)


class WhatsAppCloudProvider(NotificationProvider):
    """WhatsApp Cloud API provider using Meta Business API."""

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        api_version: str = "v18.0",
    ):
        self._phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        self._access_token = access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN")
        self._api_version = api_version or os.environ.get("WHATSAPP_API_VERSION", "v18.0")
        self._base_url = f"https://graph.facebook.com/{self._api_version}"

    @property
    def provider_name(self) -> str:
        return "WHATSAPP_CLOUD"

    def validate_recipient(self, recipient: str) -> bool:
        """
        Validate phone number format.

        WhatsApp requires international format without + prefix.
        E.g., 436641234567 (Austria)
        """
        if not recipient:
            return False
        # Remove common formatting
        cleaned = recipient.replace("+", "").replace(" ", "").replace("-", "")
        # Should be all digits, 7-15 chars
        return cleaned.isdigit() and 7 <= len(cleaned) <= 15

    async def send(
        self,
        recipient: str,
        template_name: str,
        template_params: Dict[str, Any],
        **kwargs,
    ) -> ProviderResult:
        """
        Send WhatsApp message using template.

        Args:
            recipient: Phone number in international format (e.g., 436641234567)
            template_name: Pre-approved template name
            template_params: Template component parameters
            **kwargs:
                language: Template language code (default: de)
                namespace: Template namespace (optional)

        Returns:
            ProviderResult with message ID or error
        """
        import httpx

        start_time = time.perf_counter()

        if not self._phone_number_id or not self._access_token:
            return ProviderResult.error(
                code="CONFIG_ERROR",
                message="WhatsApp credentials not configured",
                is_retryable=False,
            )

        if not self.validate_recipient(recipient):
            return ProviderResult.error(
                code="INVALID_RECIPIENT",
                message=f"Invalid phone number format: {recipient}",
                is_retryable=False,
            )

        # Clean phone number
        phone = recipient.replace("+", "").replace(" ", "").replace("-", "")

        # Build template components
        language = kwargs.get("language", "de")
        components = self._build_template_components(template_params)

        # Build request payload
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }

        if components:
            payload["template"]["components"] = components

        url = f"{self._base_url}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            response_data = response.json()

            if response.status_code == 200:
                message_id = response_data.get("messages", [{}])[0].get("id")
                logger.info(
                    "whatsapp_message_sent",
                    extra={
                        "message_id": message_id,
                        "template": template_name,
                        "recipient_hash": self._hash_phone(phone),
                        "duration_ms": duration_ms,
                    }
                )
                return ProviderResult.ok(
                    message_id=message_id,
                    status="sent",
                    response=response_data,
                    duration_ms=duration_ms,
                )

            # Handle errors
            error = response_data.get("error", {})
            error_code = error.get("code", response.status_code)
            error_message = error.get("message", "Unknown error")

            # Determine if retryable
            is_retryable = self._is_retryable_error(error_code)

            logger.warning(
                "whatsapp_message_failed",
                extra={
                    "error_code": error_code,
                    "error_message": error_message,
                    "template": template_name,
                    "is_retryable": is_retryable,
                }
            )

            return ProviderResult.error(
                code=str(error_code),
                message=error_message,
                is_retryable=is_retryable,
                response=response_data,
            )

        except httpx.TimeoutException:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("whatsapp_timeout", extra={"duration_ms": duration_ms})
            return ProviderResult.error(
                code="TIMEOUT",
                message="WhatsApp API timeout",
                is_retryable=True,
            )
        except httpx.RequestError as e:
            logger.error("whatsapp_request_error", extra={"error": str(e)})
            return ProviderResult.error(
                code="REQUEST_ERROR",
                message=str(e),
                is_retryable=True,
            )
        except Exception as e:
            logger.exception("whatsapp_unexpected_error")
            return ProviderResult.error(
                code="UNEXPECTED_ERROR",
                message=str(e),
                is_retryable=False,
            )

    async def check_health(self) -> bool:
        """Check if WhatsApp API is reachable."""
        import httpx

        if not self._phone_number_id or not self._access_token:
            return False

        url = f"{self._base_url}/{self._phone_number_id}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    def _build_template_components(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build WhatsApp template components from params.

        Expects params like:
        {
            "header_params": ["Image URL"],
            "body_params": ["Driver Name", "Portal URL"],
            "button_params": [{"type": "url", "index": 0, "url": "..."}]
        }

        Or simple key-value for body-only templates:
        {"driver_name": "John", "portal_url": "https://..."}
        """
        components = []

        # Check for structured params
        if "body_params" in params:
            body_component = {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(p)}
                    for p in params["body_params"]
                ],
            }
            components.append(body_component)

        if "header_params" in params:
            header_params = params["header_params"]
            if header_params:
                # Assume header is an image or text
                header_component = {
                    "type": "header",
                    "parameters": [
                        {"type": "text", "text": str(p)}
                        for p in header_params
                    ],
                }
                components.append(header_component)

        if "button_params" in params:
            for btn in params["button_params"]:
                btn_component = {
                    "type": "button",
                    "sub_type": btn.get("type", "url"),
                    "index": btn.get("index", 0),
                    "parameters": [
                        {"type": "text", "text": btn.get("url", "")}
                    ],
                }
                components.append(btn_component)

        # Simple key-value params (body only)
        if not components and params:
            # Filter out metadata keys
            body_values = [
                str(v) for k, v in params.items()
                if k not in ("language", "namespace", "template_namespace")
            ]
            if body_values:
                components.append({
                    "type": "body",
                    "parameters": [{"type": "text", "text": v} for v in body_values],
                })

        return components

    def _is_retryable_error(self, error_code: Any) -> bool:
        """Determine if error is retryable."""
        non_retryable_codes = {
            100,   # Invalid parameter
            190,   # Invalid OAuth token
            200,   # Permission denied
            368,   # Temporarily blocked
            131047,  # Re-engagement message limit
            131048,  # Spam rate limit
            131049,  # Invalid phone number
            131051,  # Phone not registered
        }
        try:
            return int(error_code) not in non_retryable_codes
        except (ValueError, TypeError):
            return True  # Retry unknown errors

    def _hash_phone(self, phone: str) -> str:
        """Hash phone number for logging (GDPR compliance)."""
        import hashlib
        return hashlib.sha256(phone.encode()).hexdigest()[:16]


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================

def parse_whatsapp_webhook(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse WhatsApp webhook payload into normalized events.

    Returns list of events with:
        - message_id: Provider message ID
        - event_type: SENT, DELIVERED, READ, FAILED
        - timestamp: Event timestamp
        - error_code: Error code if failed
        - error_message: Error message if failed
        - raw: Original webhook data
    """
    events = []

    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                statuses = value.get("statuses", [])

                for status in statuses:
                    event = {
                        "message_id": status.get("id"),
                        "recipient": status.get("recipient_id"),
                        "timestamp": status.get("timestamp"),
                        "raw": status,
                    }

                    status_value = status.get("status", "").upper()
                    if status_value == "SENT":
                        event["event_type"] = "SENT"
                    elif status_value == "DELIVERED":
                        event["event_type"] = "DELIVERED"
                    elif status_value == "READ":
                        event["event_type"] = "READ"
                    elif status_value == "FAILED":
                        event["event_type"] = "FAILED"
                        errors = status.get("errors", [])
                        if errors:
                            event["error_code"] = errors[0].get("code")
                            event["error_message"] = errors[0].get("title")
                    else:
                        continue  # Skip unknown statuses

                    events.append(event)

    except Exception as e:
        logger.error("whatsapp_webhook_parse_error", extra={"error": str(e)})

    return events
