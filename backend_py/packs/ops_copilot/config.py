"""
Ops-Copilot Pack Configuration

Environment-based configuration for the Ops-Copilot pack.
"""

from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional


class OpsCopilotConfig(BaseSettings):
    """Configuration for the Ops-Copilot pack."""

    # Clawdbot Gateway
    clawdbot_webhook_secret: str = Field(
        default="",
        description="HMAC secret for Clawdbot webhook signature verification",
    )
    clawdbot_timestamp_tolerance: int = Field(
        default=300,
        description="Timestamp tolerance in seconds for webhook verification",
    )

    # LangGraph Orchestrator Limits
    max_steps_per_turn: int = Field(
        default=8,
        description="Maximum graph steps per conversation turn",
    )
    max_tool_calls: int = Field(
        default=5,
        description="Maximum tool invocations per turn",
    )
    timeout_seconds: int = Field(
        default=20,
        description="Total timeout for orchestrator execution",
    )

    # OTP Pairing
    otp_expires_minutes: int = Field(
        default=15,
        description="OTP invite expiration time in minutes",
    )
    otp_max_attempts: int = Field(
        default=3,
        description="Maximum OTP verification attempts",
    )

    # Draft Expiration
    draft_expires_minutes: int = Field(
        default=5,
        description="Draft expiration time in minutes",
    )

    # Rate Limiting
    rate_limit_messages_per_minute: int = Field(
        default=20,
        description="Max messages per WA user per minute",
    )
    rate_limit_broadcasts_per_hour: int = Field(
        default=100,
        description="Max broadcast messages per tenant per hour",
    )

    # LLM Configuration
    llm_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="LLM model for the orchestrator",
    )
    llm_temperature: float = Field(
        default=0.3,
        description="LLM temperature for responses",
    )

    # Memory Configuration
    memory_ttl_days: int = Field(
        default=30,
        description="Default TTL for episodic memories in days",
    )
    max_memories_per_thread: int = Field(
        default=100,
        description="Maximum memories to retain per thread",
    )

    # Feature Flags
    enable_playbook_search: bool = Field(
        default=True,
        description="Enable semantic playbook search",
    )
    enable_memory_persistence: bool = Field(
        default=True,
        description="Enable episodic memory persistence",
    )
    enable_driver_broadcasts: bool = Field(
        default=False,
        description="Enable driver broadcast feature (requires template approval)",
    )

    model_config = {
        "env_prefix": "OPS_COPILOT_",
        "env_file": ".env",
        "extra": "ignore",
    }


# Singleton instance
_config: Optional[OpsCopilotConfig] = None


def get_config() -> OpsCopilotConfig:
    """Get or create the configuration singleton."""
    global _config
    if _config is None:
        _config = OpsCopilotConfig()
    return _config
