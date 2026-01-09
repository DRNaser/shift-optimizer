"""
SOLVEREIGN V4.1 - Email Provider (SendGrid)
=============================================

Integration with SendGrid for email delivery.

SETUP:
    1. Create SendGrid account
    2. Create API key with Mail Send permissions
    3. Verify sender domain/address

ENV VARS:
    SENDGRID_API_KEY: SendGrid API key
    SENDGRID_FROM_EMAIL: Verified sender email
    SENDGRID_FROM_NAME: Sender display name
"""

import os
import re
import time
import logging
from typing import Dict, Any, Optional

from .base import NotificationProvider, ProviderResult

logger = logging.getLogger(__name__)

# Email regex pattern (simplified, covers most cases)
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class SendGridProvider(NotificationProvider):
    """SendGrid email provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ):
        self._api_key = api_key or os.environ.get("SENDGRID_API_KEY")
        self._from_email = from_email or os.environ.get("SENDGRID_FROM_EMAIL")
        self._from_name = from_name or os.environ.get("SENDGRID_FROM_NAME", "SOLVEREIGN")
        self._api_url = "https://api.sendgrid.com/v3/mail/send"

    @property
    def provider_name(self) -> str:
        return "SENDGRID"

    def validate_recipient(self, recipient: str) -> bool:
        """Validate email address format."""
        if not recipient:
            return False
        return bool(EMAIL_PATTERN.match(recipient))

    async def send(
        self,
        recipient: str,
        template_name: str,
        template_params: Dict[str, Any],
        **kwargs,
    ) -> ProviderResult:
        """
        Send email via SendGrid.

        Args:
            recipient: Email address
            template_name: Template identifier (used for tracking)
            template_params: Template variables including:
                - subject: Email subject
                - body: Plain text body
                - body_html: HTML body (optional)
                - driver_name, portal_url, etc.
            **kwargs:
                reply_to: Reply-to email address
                categories: List of tracking categories

        Returns:
            ProviderResult with message ID or error
        """
        import httpx

        start_time = time.perf_counter()

        if not self._api_key or not self._from_email:
            return ProviderResult.error(
                code="CONFIG_ERROR",
                message="SendGrid credentials not configured",
                is_retryable=False,
            )

        if not self.validate_recipient(recipient):
            return ProviderResult.error(
                code="INVALID_RECIPIENT",
                message=f"Invalid email address: {recipient}",
                is_retryable=False,
            )

        # Build email content
        subject = template_params.get("subject", f"SOLVEREIGN - {template_name}")
        body_text = template_params.get("body", "")
        body_html = template_params.get("body_html")

        # Render template variables in body
        for key, value in template_params.items():
            if key not in ("subject", "body", "body_html"):
                body_text = body_text.replace(f"{{{{{key}}}}}", str(value))
                if body_html:
                    body_html = body_html.replace(f"{{{{{key}}}}}", str(value))

        # Build SendGrid payload
        payload = {
            "personalizations": [
                {
                    "to": [{"email": recipient}],
                    "subject": subject,
                }
            ],
            "from": {
                "email": self._from_email,
                "name": self._from_name,
            },
            "content": [],
            "tracking_settings": {
                "click_tracking": {"enable": True},
                "open_tracking": {"enable": True},
            },
            "custom_args": {
                "template_name": template_name,
            },
        }

        # Add content (plain text required, HTML optional)
        if body_text:
            payload["content"].append({
                "type": "text/plain",
                "value": body_text,
            })

        if body_html:
            payload["content"].append({
                "type": "text/html",
                "value": body_html,
            })

        # Add reply-to if specified
        reply_to = kwargs.get("reply_to")
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        # Add categories for tracking
        categories = kwargs.get("categories", [])
        if categories:
            payload["categories"] = categories[:10]  # SendGrid limit

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url,
                    json=payload,
                    headers=headers,
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            if response.status_code in (200, 202):
                # SendGrid returns message ID in X-Message-Id header
                message_id = response.headers.get("X-Message-Id", "")
                logger.info(
                    "email_sent",
                    extra={
                        "message_id": message_id,
                        "template": template_name,
                        "recipient_hash": self._hash_email(recipient),
                        "duration_ms": duration_ms,
                    }
                )
                return ProviderResult.ok(
                    message_id=message_id,
                    status="accepted",
                    response={"status_code": response.status_code},
                    duration_ms=duration_ms,
                )

            # Handle errors
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                error_message = errors[0].get("message") if errors else "Unknown error"
                error_code = str(response.status_code)
            except Exception:
                error_message = response.text or "Unknown error"
                error_code = str(response.status_code)

            is_retryable = self._is_retryable_error(response.status_code)

            logger.warning(
                "email_failed",
                extra={
                    "error_code": error_code,
                    "error_message": error_message,
                    "template": template_name,
                    "is_retryable": is_retryable,
                }
            )

            return ProviderResult.error(
                code=error_code,
                message=error_message,
                is_retryable=is_retryable,
                response={"status_code": response.status_code},
            )

        except httpx.TimeoutException:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("email_timeout", extra={"duration_ms": duration_ms})
            return ProviderResult.error(
                code="TIMEOUT",
                message="SendGrid API timeout",
                is_retryable=True,
            )
        except httpx.RequestError as e:
            logger.error("email_request_error", extra={"error": str(e)})
            return ProviderResult.error(
                code="REQUEST_ERROR",
                message=str(e),
                is_retryable=True,
            )
        except Exception as e:
            logger.exception("email_unexpected_error")
            return ProviderResult.error(
                code="UNEXPECTED_ERROR",
                message=str(e),
                is_retryable=False,
            )

    async def check_health(self) -> bool:
        """Check if SendGrid API is reachable."""
        import httpx

        if not self._api_key:
            return False

        # Use the scopes endpoint for health check
        url = "https://api.sendgrid.com/v3/scopes"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    def _is_retryable_error(self, status_code: int) -> bool:
        """Determine if HTTP error is retryable."""
        # 4xx errors are generally not retryable (except 429)
        # 5xx errors are retryable
        return status_code == 429 or status_code >= 500

    def _hash_email(self, email: str) -> str:
        """Hash email for logging (GDPR compliance)."""
        import hashlib
        return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================

def parse_sendgrid_webhook(events: list) -> list:
    """
    Parse SendGrid Event Webhook payload into normalized events.

    SendGrid sends array of events, each with:
        - sg_message_id: Message ID
        - event: Event type (processed, delivered, open, click, bounce, etc.)
        - timestamp: Unix timestamp

    Returns list of events with:
        - message_id: Provider message ID
        - event_type: SENT, DELIVERED, READ, FAILED
        - timestamp: Event timestamp
        - error_code: Error code if failed
        - error_message: Error message if failed
        - raw: Original event data
    """
    normalized = []

    for event in events:
        try:
            sg_event = event.get("event", "").lower()
            message_id = event.get("sg_message_id", "").split(".")[0]  # Remove .filter suffix

            normalized_event = {
                "message_id": message_id,
                "recipient": event.get("email"),
                "timestamp": event.get("timestamp"),
                "raw": event,
            }

            # Map SendGrid events to normalized types
            if sg_event in ("processed", "deferred"):
                normalized_event["event_type"] = "SENT"
            elif sg_event == "delivered":
                normalized_event["event_type"] = "DELIVERED"
            elif sg_event in ("open", "click"):
                normalized_event["event_type"] = "READ"
            elif sg_event in ("bounce", "blocked", "dropped", "spamreport"):
                normalized_event["event_type"] = "FAILED"
                normalized_event["error_code"] = sg_event.upper()
                normalized_event["error_message"] = event.get("reason", sg_event)
            else:
                continue  # Skip unknown events

            normalized.append(normalized_event)

        except Exception as e:
            logger.error("sendgrid_webhook_parse_error", extra={"error": str(e)})

    return normalized
