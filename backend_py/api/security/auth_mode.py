"""
SOLVEREIGN V3.3b - Auth Mode Configuration

=============================================================================
SOURCE OF TRUTH
=============================================================================

External IdP Mode (OIDC) is DEFAULT.
Self-Hosted Auth is OPTIONAL and DISABLED in production by default.

| Mode        | AUTH_MODE      | Production                                |
|-------------|----------------|-------------------------------------------|
| OIDC        | OIDC (default) | Allowed                                   |
| Self-Hosted | SELF_HOSTED    | Blocked unless ALLOW_SELF_HOSTED_IN_PROD  |

=============================================================================
"""

import os
import sys
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class AuthMode(Enum):
    """Authentication mode."""
    OIDC = "OIDC"              # External IdP (Keycloak, Auth0) - DEFAULT
    SELF_HOSTED = "SELF_HOSTED"  # Self-hosted auth (dev/air-gapped only)


@dataclass
class AuthConfig:
    """Authentication configuration."""
    mode: AuthMode
    oidc_issuer: Optional[str] = None
    oidc_audience: Optional[str] = None
    oidc_jwks_url: Optional[str] = None

    # Self-hosted only
    jwt_secret_key: Optional[str] = None
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7


def get_auth_mode() -> AuthMode:
    """
    Get the configured authentication mode.

    Returns:
        AuthMode enum value

    Environment Variables:
        AUTH_MODE: "OIDC" (default) or "SELF_HOSTED"
    """
    mode_str = os.environ.get("AUTH_MODE", "OIDC").upper()

    if mode_str == "SELF_HOSTED":
        return AuthMode.SELF_HOSTED
    else:
        return AuthMode.OIDC


def validate_auth_mode_for_environment() -> None:
    """
    Validate that the auth mode is allowed for the current environment.

    PRODUCTION GUARDRAIL:
    - Self-Hosted Auth is BLOCKED in production unless explicitly allowed.
    - This prevents accidental deployment of self-hosted auth in prod.

    Raises:
        SystemExit: If self-hosted auth is used in production without explicit allow.
    """
    mode = get_auth_mode()
    environment = os.environ.get("ENVIRONMENT", "development").lower()

    if mode == AuthMode.SELF_HOSTED and environment == "production":
        allow_self_hosted = os.environ.get("ALLOW_SELF_HOSTED_IN_PROD", "").lower() == "true"

        if not allow_self_hosted:
            logger.critical(
                "SECURITY VIOLATION: Self-Hosted Auth Mode is not allowed in production! "
                "Set AUTH_MODE=OIDC or set ALLOW_SELF_HOSTED_IN_PROD=true if you really need it."
            )
            print(
                "\n"
                "=" * 70 + "\n"
                "SECURITY ERROR: Self-Hosted Auth Mode blocked in production!\n"
                "=" * 70 + "\n"
                "\n"
                "Self-Hosted Auth (token_refresh, token_blacklist) is designed for:\n"
                "  - Development/testing without IdP\n"
                "  - Air-gapped environments\n"
                "\n"
                "In production, use External IdP (Keycloak/Auth0):\n"
                "  AUTH_MODE=OIDC\n"
                "\n"
                "If you REALLY need Self-Hosted Auth in production:\n"
                "  ALLOW_SELF_HOSTED_IN_PROD=true\n"
                "\n"
                "=" * 70 + "\n",
                file=sys.stderr
            )
            sys.exit(1)

    # Log the auth mode being used
    if mode == AuthMode.OIDC:
        logger.info(f"Auth mode: OIDC (External IdP)")
    else:
        if environment == "production":
            logger.warning(
                "Auth mode: SELF_HOSTED in PRODUCTION (explicitly allowed). "
                "Ensure this is intentional."
            )
        else:
            logger.info(f"Auth mode: SELF_HOSTED (development/testing)")


def get_auth_config() -> AuthConfig:
    """
    Get the full authentication configuration.

    Returns:
        AuthConfig with mode-appropriate settings
    """
    mode = get_auth_mode()

    if mode == AuthMode.OIDC:
        return AuthConfig(
            mode=mode,
            oidc_issuer=os.environ.get("OIDC_ISSUER"),
            oidc_audience=os.environ.get("OIDC_AUDIENCE"),
            oidc_jwks_url=os.environ.get("OIDC_JWKS_URL"),
        )
    else:
        return AuthConfig(
            mode=mode,
            jwt_secret_key=os.environ.get("JWT_SECRET_KEY"),
            access_token_ttl_minutes=int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "15")),
            refresh_token_ttl_days=int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "7")),
        )


def is_self_hosted_auth_enabled() -> bool:
    """Check if self-hosted auth modules should be loaded."""
    return get_auth_mode() == AuthMode.SELF_HOSTED


# =============================================================================
# MODULE LOADING GUARD
# =============================================================================

def require_self_hosted_auth():
    """
    Decorator/guard to ensure self-hosted auth modules are only used
    when AUTH_MODE=SELF_HOSTED.

    Usage:
        @require_self_hosted_auth()
        def create_refresh_token(...):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not is_self_hosted_auth_enabled():
                raise RuntimeError(
                    f"Function {func.__name__} requires AUTH_MODE=SELF_HOSTED. "
                    f"Current mode: {get_auth_mode().value}"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator
