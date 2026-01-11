"""
SOLVEREIGN V3.3a API Configuration
==================================

Pydantic Settings for type-safe environment configuration.
"""

from functools import lru_cache
from typing import Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class APISettings(BaseSettings):
    """API Configuration with environment variable support."""

    # ==========================================================================
    # Application
    # ==========================================================================
    app_name: str = Field(default="SOLVEREIGN API", description="Application name")
    app_version: str = Field(default="3.3.0", description="API version")
    debug: bool = Field(default=False, description="Enable debug mode")
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment"
    )

    # ==========================================================================
    # Server
    # ==========================================================================
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=1, description="Uvicorn workers (1 for determinism)")
    reload: bool = Field(default=False, description="Enable auto-reload")

    # ==========================================================================
    # Database
    # ==========================================================================
    database_url: str = Field(
        default="postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign",
        description="PostgreSQL connection URL"
    )
    database_pool_size: int = Field(default=5, description="Connection pool size")
    database_max_overflow: int = Field(default=10, description="Max pool overflow")
    database_pool_timeout: int = Field(default=30, description="Pool connection timeout")

    # ==========================================================================
    # Authentication
    # ==========================================================================
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    api_key_min_length: int = Field(default=32, description="Minimum API key length")

    # ==========================================================================
    # OIDC/Entra ID Configuration
    # ==========================================================================
    oidc_issuer: Optional[str] = Field(
        default=None,
        description="OIDC issuer URL (e.g., https://login.microsoftonline.com/{tid}/v2.0)"
    )
    oidc_audience: Optional[str] = Field(
        default=None,
        description="OIDC audience (API Application ID or URI)"
    )
    oidc_jwks_url: Optional[str] = Field(
        default=None,
        description="JWKS endpoint URL (auto-discovered from issuer if not set)"
    )
    oidc_clock_skew_seconds: int = Field(
        default=60,
        description="Clock skew tolerance for JWT exp/iat validation"
    )
    oidc_allowed_issuers: list[str] = Field(
        default=[],
        description="List of allowed issuers (for multi-tenant Entra)"
    )

    # Entra ID specific
    entra_tenant_id: Optional[str] = Field(
        default=None,
        description="Azure AD Tenant ID for single-tenant apps"
    )

    # Auth mode guardrails
    auth_mode: str = Field(
        default="OIDC",
        description="Auth mode: OIDC (default) or SELF_HOSTED"
    )
    allow_header_tenant_override: bool = Field(
        default=False,
        description="Allow X-Tenant-ID header to override JWT tenant (DEV ONLY, NEVER in prod)"
    )

    # ==========================================================================
    # Solver
    # ==========================================================================
    solver_timeout_seconds: int = Field(default=300, description="Solver timeout (5min)")
    solver_default_seed: int = Field(default=94, description="Default solver seed")

    # ==========================================================================
    # Idempotency
    # ==========================================================================
    idempotency_ttl_hours: int = Field(default=24, description="Idempotency key TTL")
    idempotency_header: str = Field(default="X-Idempotency-Key", description="Idempotency header")

    # ==========================================================================
    # Rate Limiting (future)
    # ==========================================================================
    rate_limit_enabled: bool = Field(default=False, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, description="Requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window")

    # ==========================================================================
    # Observability
    # ==========================================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: Literal["json", "text"] = Field(
        default="json",
        description="Log output format"
    )
    metrics_enabled: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_path: str = Field(default="/metrics", description="Metrics endpoint path")

    # Sentry Error Tracking
    sentry_dsn: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking (leave empty to disable)"
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1,
        description="Sentry performance traces sample rate (0.0-1.0)"
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.1,
        description="Sentry profiling sample rate (0.0-1.0)"
    )

    # ==========================================================================
    # Stripe Billing (P1)
    # ==========================================================================
    stripe_api_key: Optional[str] = Field(
        default=None,
        description="Stripe secret API key (sk_live_... or sk_test_...)"
    )
    stripe_webhook_secret: Optional[str] = Field(
        default=None,
        description="Stripe webhook signing secret (whsec_...)"
    )
    stripe_default_currency: str = Field(
        default="eur",
        description="Default currency for billing (eur for DACH market)"
    )

    # ==========================================================================
    # CORS
    # ==========================================================================
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8501"],
        description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")
    cors_allow_methods: list[str] = Field(default=["*"], description="Allowed methods")
    cors_allow_headers: list[str] = Field(default=["*"], description="Allowed headers")

    # ==========================================================================
    # Security
    # ==========================================================================
    secret_key: str = Field(
        default="change_me_in_production_to_a_random_64_char_string_abc123",
        description="Application secret key"
    )

    # ==========================================================================
    # Validators
    # ==========================================================================
    @field_validator("workers")
    @classmethod
    def validate_workers(cls, v: int) -> int:
        if v != 1:
            import warnings
            warnings.warn(
                f"workers={v} may break solver determinism. Use 1 for reproducible results.",
                UserWarning
            )
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str, info) -> str:
        if info.data.get("environment") == "production" and "change_me" in v:
            raise ValueError("SECRET_KEY must be changed in production")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("oidc_allowed_issuers", mode="before")
    @classmethod
    def parse_oidc_allowed_issuers(cls, v):
        if isinstance(v, str):
            return [iss.strip() for iss in v.split(",") if iss.strip()]
        return v

    @field_validator("allow_header_tenant_override")
    @classmethod
    def validate_header_override(cls, v: bool, info) -> bool:
        if v and info.data.get("environment") == "production":
            raise ValueError(
                "allow_header_tenant_override MUST be False in production. "
                "Tenant ID must come from JWT token, never from client headers."
            )
        return v

    # ==========================================================================
    # Properties
    # ==========================================================================
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def effective_jwks_url(self) -> Optional[str]:
        """Get JWKS URL, auto-discovering from issuer if not explicitly set."""
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        if self.oidc_issuer:
            # Standard OIDC discovery: issuer + /.well-known/openid-configuration
            # For Entra v2.0: https://login.microsoftonline.com/{tid}/v2.0/.well-known/openid-configuration
            return f"{self.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        return None

    @property
    def is_oidc_configured(self) -> bool:
        """Check if OIDC is properly configured."""
        return bool(self.oidc_issuer and self.oidc_audience)

    @property
    def is_stripe_configured(self) -> bool:
        """Check if Stripe billing is properly configured."""
        return bool(self.stripe_api_key and self.stripe_webhook_secret)

    class Config:
        env_prefix = "SOLVEREIGN_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> APISettings:
    """
    Get cached settings instance.

    Settings are loaded once and cached for performance.
    Use dependency injection in FastAPI for testability.
    """
    return APISettings()


# Singleton for direct import
settings = get_settings()
