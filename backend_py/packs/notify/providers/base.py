"""
SOLVEREIGN V4.1 - Base Provider Interface
==========================================

Abstract base class for notification providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class ProviderResult:
    """Result from provider send attempt."""
    success: bool
    provider_message_id: Optional[str] = None
    provider_status: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_retryable: bool = True
    duration_ms: Optional[int] = None

    @classmethod
    def ok(
        cls,
        message_id: str,
        status: str = "sent",
        response: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> "ProviderResult":
        """Create successful result."""
        return cls(
            success=True,
            provider_message_id=message_id,
            provider_status=status,
            provider_response=response,
            duration_ms=duration_ms,
        )

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        is_retryable: bool = True,
        response: Optional[Dict[str, Any]] = None,
    ) -> "ProviderResult":
        """Create error result."""
        return cls(
            success=False,
            error_code=code,
            error_message=message,
            is_retryable=is_retryable,
            provider_response=response,
        )


class NotificationProvider(ABC):
    """Abstract base class for notification providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (e.g., 'WHATSAPP_CLOUD', 'SENDGRID')."""
        pass

    @abstractmethod
    async def send(
        self,
        recipient: str,
        template_name: str,
        template_params: Dict[str, Any],
        **kwargs,
    ) -> ProviderResult:
        """
        Send a notification.

        Args:
            recipient: Phone number (WhatsApp/SMS) or email address
            template_name: Template identifier
            template_params: Template variable values
            **kwargs: Provider-specific options

        Returns:
            ProviderResult with success/failure details
        """
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """Check if provider is healthy and reachable."""
        pass

    def validate_recipient(self, recipient: str) -> bool:
        """
        Validate recipient format.

        Override in subclasses for specific validation.
        """
        return bool(recipient and len(recipient) > 0)


class MockProvider(NotificationProvider):
    """Mock provider for testing."""

    def __init__(self, should_fail: bool = False, delay_ms: int = 0):
        self._should_fail = should_fail
        self._delay_ms = delay_ms
        self._sent_messages: list = []

    @property
    def provider_name(self) -> str:
        return "MOCK"

    async def send(
        self,
        recipient: str,
        template_name: str,
        template_params: Dict[str, Any],
        **kwargs,
    ) -> ProviderResult:
        """Mock send - stores message for verification."""
        import asyncio
        import uuid

        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)

        if self._should_fail:
            return ProviderResult.error(
                code="MOCK_FAILURE",
                message="Mock provider configured to fail",
                is_retryable=True,
            )

        message_id = str(uuid.uuid4())
        self._sent_messages.append({
            "message_id": message_id,
            "recipient": recipient,
            "template_name": template_name,
            "template_params": template_params,
            "sent_at": datetime.utcnow().isoformat(),
        })

        return ProviderResult.ok(
            message_id=message_id,
            status="sent",
            duration_ms=self._delay_ms,
        )

    async def check_health(self) -> bool:
        return not self._should_fail

    def get_sent_messages(self) -> list:
        """Get all sent messages (for testing)."""
        return self._sent_messages

    def clear_messages(self) -> None:
        """Clear sent messages (for testing)."""
        self._sent_messages.clear()
