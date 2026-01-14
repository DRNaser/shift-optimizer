"""
SOLVEREIGN V4.6 - WhatsApp Provider Abstraction
================================================

Provider abstraction layer for WhatsApp notifications:
- NotifyProvider interface
- whatsapp_meta: Meta Cloud API (PRIMARY)
- whatsapp_clawdbot: ClawdBot (OPTIONAL secondary)

Key Principle: Template-only outbound (no free text generation).
All messages must use pre-approved templates.

Environment Variables:
- WHATSAPP_META_ACCESS_TOKEN: Meta API access token
- WHATSAPP_META_PHONE_NUMBER_ID: WhatsApp Business phone number ID
- WHATSAPP_META_WEBHOOK_VERIFY_TOKEN: Webhook verification token
- CLAWDBOT_API_KEY: ClawdBot API key (optional)
"""

import os
import hashlib
import hmac
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

WHATSAPP_META_API_VERSION = "v18.0"
WHATSAPP_META_BASE_URL = "https://graph.facebook.com"

# Rate limiting
DEFAULT_RATE_LIMIT_PER_MINUTE = 80
DEFAULT_RATE_LIMIT_PER_DAY = 1000


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DeliveryResult:
    """Result of a message delivery attempt."""
    success: bool
    delivery_ref: Optional[str] = None  # Provider message ID
    provider: str = ""
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_retryable: bool = True
    raw_response: Optional[Dict] = None


@dataclass
class TemplateMessage:
    """Template-based message to send."""
    to_phone_e164: str
    template_id: str  # Internal template key
    template_name: str  # Provider template name
    template_namespace: Optional[str] = None
    language: str = "de"
    variables: Dict[str, str] = None  # Template variables
    correlation_id: Optional[UUID] = None

    def __post_init__(self):
        if self.variables is None:
            self.variables = {}
        if self.correlation_id is None:
            self.correlation_id = uuid4()


@dataclass
class WebhookEvent:
    """Parsed webhook event from provider."""
    event_type: str  # sent, delivered, read, failed
    provider_message_id: str
    provider: str
    timestamp: datetime
    status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_payload: Optional[Dict] = None


# =============================================================================
# PROVIDER INTERFACE
# =============================================================================

class NotifyProvider(ABC):
    """
    Abstract interface for notification providers.

    All providers must implement template-based sending only.
    Free text generation is NOT supported.
    """

    @property
    @abstractmethod
    def provider_key(self) -> str:
        """Unique provider identifier."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Check if provider is properly configured."""
        pass

    @abstractmethod
    async def send_template(
        self,
        to_phone_e164: str,
        template_name: str,
        variables: Dict[str, Any],
        correlation_id: UUID,
        template_namespace: Optional[str] = None,
        language: str = "de"
    ) -> DeliveryResult:
        """
        Send a template-based message.

        Args:
            to_phone_e164: Recipient phone in E.164 format
            template_name: Pre-approved template name
            variables: Template variable mapping
            correlation_id: Correlation ID for tracking
            template_namespace: Optional template namespace
            language: Template language code

        Returns:
            DeliveryResult with success status and delivery reference
        """
        pass

    @abstractmethod
    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Verify webhook signature from provider.

        Args:
            payload: Raw webhook payload
            signature: Signature from provider header

        Returns:
            True if signature is valid
        """
        pass

    @abstractmethod
    def parse_webhook_event(self, payload: Dict) -> Optional[WebhookEvent]:
        """
        Parse webhook payload into WebhookEvent.

        Args:
            payload: Raw webhook JSON payload

        Returns:
            Parsed WebhookEvent or None if not applicable
        """
        pass


# =============================================================================
# WHATSAPP META PROVIDER (PRIMARY)
# =============================================================================

class WhatsAppMetaProvider(NotifyProvider):
    """
    WhatsApp Cloud API provider (Meta).

    Uses Meta's official WhatsApp Business Cloud API.
    Requires pre-approved message templates.
    """

    def __init__(self):
        self._access_token = os.environ.get("WHATSAPP_META_ACCESS_TOKEN")
        self._phone_number_id = os.environ.get("WHATSAPP_META_PHONE_NUMBER_ID")
        self._webhook_verify_token = os.environ.get("WHATSAPP_META_WEBHOOK_VERIFY_TOKEN")
        self._app_secret = os.environ.get("WHATSAPP_META_APP_SECRET")

    @property
    def provider_key(self) -> str:
        return "whatsapp_meta"

    @property
    def is_configured(self) -> bool:
        return bool(self._access_token and self._phone_number_id)

    async def send_template(
        self,
        to_phone_e164: str,
        template_name: str,
        variables: Dict[str, Any],
        correlation_id: UUID,
        template_namespace: Optional[str] = None,
        language: str = "de"
    ) -> DeliveryResult:
        """Send template message via Meta Cloud API."""

        if not self.is_configured:
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="NOT_CONFIGURED",
                error_message="WhatsApp Meta provider not configured",
                is_retryable=False
            )

        # Build template components
        components = self._build_template_components(variables)

        # API payload
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164.lstrip('+'),  # Meta API expects no + prefix
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components
            }
        }

        url = f"{WHATSAPP_META_BASE_URL}/{WHATSAPP_META_API_VERSION}/{self._phone_number_id}/messages"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json"
                    }
                )

                response_data = response.json()

                if response.status_code == 200:
                    # Success
                    message_id = response_data.get("messages", [{}])[0].get("id")
                    logger.info(
                        f"WhatsApp Meta: Sent template '{template_name}' to {to_phone_e164[:8]}***, "
                        f"message_id={message_id}, correlation={correlation_id}"
                    )
                    return DeliveryResult(
                        success=True,
                        delivery_ref=message_id,
                        provider=self.provider_key,
                        raw_response=response_data
                    )
                else:
                    # API error
                    error = response_data.get("error", {})
                    error_code = str(error.get("code", response.status_code))
                    error_message = error.get("message", "Unknown error")

                    # Determine if retryable
                    is_retryable = self._is_retryable_error(error_code)

                    logger.warning(
                        f"WhatsApp Meta: Failed to send to {to_phone_e164[:8]}***, "
                        f"error={error_code}: {error_message}"
                    )

                    return DeliveryResult(
                        success=False,
                        provider=self.provider_key,
                        error_code=error_code,
                        error_message=error_message,
                        is_retryable=is_retryable,
                        raw_response=response_data
                    )

        except httpx.TimeoutException:
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="TIMEOUT",
                error_message="Request timed out",
                is_retryable=True
            )
        except Exception as e:
            logger.exception(f"WhatsApp Meta: Unexpected error: {e}")
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="INTERNAL_ERROR",
                error_message=str(e),
                is_retryable=True
            )

    def _build_template_components(self, variables: Dict[str, Any]) -> List[Dict]:
        """Build template components from variable mapping."""
        components = []

        # Body parameters (most common)
        body_params = []
        for key, value in sorted(variables.items()):
            # Assume sequential body parameters by default
            body_params.append({
                "type": "text",
                "text": str(value)
            })

        if body_params:
            components.append({
                "type": "body",
                "parameters": body_params
            })

        return components

    def _is_retryable_error(self, error_code: str) -> bool:
        """Determine if error is retryable."""
        # Non-retryable error codes
        non_retryable = {
            "131026",  # Message undeliverable
            "131047",  # Re-engagement message
            "131051",  # Unsupported message type
            "132000",  # Template not found
            "132001",  # Template missing
            "132007",  # Template not approved
        }
        return error_code not in non_retryable

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Meta webhook signature using HMAC-SHA256."""
        if not self._app_secret:
            logger.warning("WhatsApp Meta: App secret not configured for webhook verification")
            return False

        expected_signature = hmac.new(
            self._app_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Meta sends signature as "sha256=<signature>"
        if signature.startswith("sha256="):
            signature = signature[7:]

        return hmac.compare_digest(expected_signature, signature)

    def parse_webhook_event(self, payload: Dict) -> Optional[WebhookEvent]:
        """Parse Meta webhook payload."""
        try:
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})

            # Message status update
            statuses = value.get("statuses", [])
            if statuses:
                status = statuses[0]
                status_type = status.get("status")  # sent, delivered, read, failed

                event_type = {
                    "sent": "SENT",
                    "delivered": "DELIVERED",
                    "read": "READ",
                    "failed": "FAILED"
                }.get(status_type, status_type.upper())

                return WebhookEvent(
                    event_type=event_type,
                    provider_message_id=status.get("id"),
                    provider=self.provider_key,
                    timestamp=datetime.fromtimestamp(int(status.get("timestamp", 0))),
                    status=status_type,
                    error_code=status.get("errors", [{}])[0].get("code"),
                    error_message=status.get("errors", [{}])[0].get("message"),
                    raw_payload=payload
                )

            return None

        except Exception as e:
            logger.exception(f"WhatsApp Meta: Failed to parse webhook: {e}")
            return None

    def get_webhook_verify_response(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Handle webhook verification request from Meta.

        Returns challenge if valid, None otherwise.
        """
        if mode == "subscribe" and token == self._webhook_verify_token:
            return challenge
        return None


# =============================================================================
# CLAWDBOT PROVIDER (OPTIONAL SECONDARY)
# =============================================================================

class ClawdBotProvider(NotifyProvider):
    """
    ClawdBot WhatsApp provider (optional secondary).

    Supports both individual messages and group broadcasts.
    NOT required for core flows - use as backup only.
    """

    def __init__(self):
        self._api_key = os.environ.get("CLAWDBOT_API_KEY")
        self._api_url = os.environ.get("CLAWDBOT_API_URL", "https://api.clawdbot.com/v1")

    @property
    def provider_key(self) -> str:
        return "whatsapp_clawdbot"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def send_template(
        self,
        to_phone_e164: str,
        template_name: str,
        variables: Dict[str, Any],
        correlation_id: UUID,
        template_namespace: Optional[str] = None,
        language: str = "de"
    ) -> DeliveryResult:
        """Send template message via ClawdBot API."""

        if not self.is_configured:
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="NOT_CONFIGURED",
                error_message="ClawdBot provider not configured",
                is_retryable=False
            )

        # ClawdBot payload format (simplified)
        payload = {
            "to": to_phone_e164,
            "template": template_name,
            "language": language,
            "parameters": variables,
            "correlation_id": str(correlation_id)
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._api_url}/messages/template",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json"
                    }
                )

                response_data = response.json()

                if response.status_code in (200, 201):
                    message_id = response_data.get("message_id")
                    logger.info(
                        f"ClawdBot: Sent template '{template_name}' to {to_phone_e164[:8]}***, "
                        f"message_id={message_id}"
                    )
                    return DeliveryResult(
                        success=True,
                        delivery_ref=message_id,
                        provider=self.provider_key,
                        raw_response=response_data
                    )
                else:
                    error_code = response_data.get("error_code", str(response.status_code))
                    error_message = response_data.get("error", "Unknown error")

                    return DeliveryResult(
                        success=False,
                        provider=self.provider_key,
                        error_code=error_code,
                        error_message=error_message,
                        is_retryable=response.status_code >= 500,
                        raw_response=response_data
                    )

        except httpx.TimeoutException:
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="TIMEOUT",
                error_message="Request timed out",
                is_retryable=True
            )
        except Exception as e:
            logger.exception(f"ClawdBot: Unexpected error: {e}")
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="INTERNAL_ERROR",
                error_message=str(e),
                is_retryable=True
            )

    async def send_to_group(
        self,
        group_id: str,
        template_name: str,
        variables: Dict[str, Any],
        correlation_id: UUID
    ) -> DeliveryResult:
        """Send template message to a ClawdBot group."""

        if not self.is_configured:
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="NOT_CONFIGURED",
                error_message="ClawdBot provider not configured",
                is_retryable=False
            )

        payload = {
            "group_id": group_id,
            "template": template_name,
            "parameters": variables,
            "correlation_id": str(correlation_id)
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._api_url}/groups/{group_id}/broadcast",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json"
                    }
                )

                response_data = response.json()

                if response.status_code in (200, 201):
                    return DeliveryResult(
                        success=True,
                        delivery_ref=response_data.get("broadcast_id"),
                        provider=self.provider_key,
                        raw_response=response_data
                    )
                else:
                    return DeliveryResult(
                        success=False,
                        provider=self.provider_key,
                        error_code=response_data.get("error_code"),
                        error_message=response_data.get("error"),
                        is_retryable=response.status_code >= 500,
                        raw_response=response_data
                    )

        except Exception as e:
            logger.exception(f"ClawdBot group broadcast error: {e}")
            return DeliveryResult(
                success=False,
                provider=self.provider_key,
                error_code="INTERNAL_ERROR",
                error_message=str(e),
                is_retryable=True
            )

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """ClawdBot webhook verification (if supported)."""
        # Implement based on ClawdBot's webhook signature scheme
        # For now, return True as ClawdBot is optional
        return True

    def parse_webhook_event(self, payload: Dict) -> Optional[WebhookEvent]:
        """Parse ClawdBot webhook payload."""
        try:
            event_type = payload.get("event_type", "").upper()
            if event_type not in ("SENT", "DELIVERED", "READ", "FAILED"):
                return None

            return WebhookEvent(
                event_type=event_type,
                provider_message_id=payload.get("message_id"),
                provider=self.provider_key,
                timestamp=datetime.fromisoformat(payload.get("timestamp", "")),
                status=payload.get("status"),
                error_code=payload.get("error_code"),
                error_message=payload.get("error_message"),
                raw_payload=payload
            )
        except Exception as e:
            logger.exception(f"ClawdBot: Failed to parse webhook: {e}")
            return None


# =============================================================================
# PROVIDER MANAGER
# =============================================================================

class ProviderManager:
    """
    Manages notification providers with fallback support.

    Handles provider selection, failover, and health tracking.
    """

    def __init__(self):
        self._providers: Dict[str, NotifyProvider] = {}
        self._primary_provider: Optional[str] = None

        # Register default providers
        self.register_provider(WhatsAppMetaProvider(), is_primary=True)
        self.register_provider(ClawdBotProvider())

    def register_provider(self, provider: NotifyProvider, is_primary: bool = False):
        """Register a provider."""
        self._providers[provider.provider_key] = provider
        if is_primary and provider.is_configured:
            self._primary_provider = provider.provider_key

    def get_provider(self, provider_key: Optional[str] = None) -> Optional[NotifyProvider]:
        """Get a specific provider or the primary provider."""
        if provider_key:
            return self._providers.get(provider_key)

        # Return primary if configured
        if self._primary_provider:
            return self._providers.get(self._primary_provider)

        # Find first configured provider
        for provider in self._providers.values():
            if provider.is_configured:
                return provider

        return None

    def get_available_providers(self) -> List[str]:
        """Get list of configured provider keys."""
        return [
            key for key, provider in self._providers.items()
            if provider.is_configured
        ]

    async def send_with_fallback(
        self,
        message: TemplateMessage,
        preferred_provider: Optional[str] = None
    ) -> DeliveryResult:
        """
        Send message with automatic fallback to secondary provider.

        Args:
            message: Template message to send
            preferred_provider: Preferred provider key (optional)

        Returns:
            DeliveryResult from successful provider or last failure
        """
        providers_to_try = []

        # Add preferred provider first
        if preferred_provider and preferred_provider in self._providers:
            providers_to_try.append(preferred_provider)

        # Add primary provider
        if self._primary_provider and self._primary_provider not in providers_to_try:
            providers_to_try.append(self._primary_provider)

        # Add remaining configured providers
        for key, provider in self._providers.items():
            if provider.is_configured and key not in providers_to_try:
                providers_to_try.append(key)

        last_result = None

        for provider_key in providers_to_try:
            provider = self._providers.get(provider_key)
            if not provider or not provider.is_configured:
                continue

            result = await provider.send_template(
                to_phone_e164=message.to_phone_e164,
                template_name=message.template_name,
                variables=message.variables,
                correlation_id=message.correlation_id,
                template_namespace=message.template_namespace,
                language=message.language
            )

            if result.success:
                return result

            last_result = result

            # Don't retry if error is not retryable
            if not result.is_retryable:
                break

            logger.warning(
                f"Provider {provider_key} failed, trying next. "
                f"Error: {result.error_code} - {result.error_message}"
            )

        return last_result or DeliveryResult(
            success=False,
            error_code="NO_PROVIDERS",
            error_message="No configured providers available",
            is_retryable=False
        )


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_provider_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Get the singleton provider manager instance."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager
