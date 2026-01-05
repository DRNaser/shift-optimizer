"""
SOLVEREIGN V3.3b - Security Headers Middleware
===============================================

Defense-in-depth HTTP headers:
- Prevent XSS, clickjacking, MIME sniffing
- Control referrer leakage
- Prevent caching of sensitive data
- Content Security Policy (CSP)

OWASP Secure Headers Reference:
https://owasp.org/www-project-secure-headers/
"""

import logging
from typing import Optional, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses.

    Headers applied:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Referrer-Policy: strict-origin-when-cross-origin
    - Cache-Control: no-store (for authenticated requests)
    - Strict-Transport-Security (HSTS)
    - Content-Security-Policy (CSP)
    - Permissions-Policy

    Configuration:
    - is_production: Enable HSTS and strict CSP
    - frame_ancestors: Allowed frame ancestors (default: none)
    """

    def __init__(
        self,
        app,
        is_production: bool = False,
        hsts_max_age: int = 31536000,  # 1 year
        frame_ancestors: Optional[str] = None,
        csp_report_uri: Optional[str] = None,
    ):
        super().__init__(app)
        self.is_production = is_production
        self.hsts_max_age = hsts_max_age
        self.frame_ancestors = frame_ancestors or "'none'"
        self.csp_report_uri = csp_report_uri

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request and add security headers to response."""
        response: Response = await call_next(request)

        # =================================================================
        # CORE SECURITY HEADERS
        # =================================================================

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS Protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Control referrer information
        # - strict-origin-when-cross-origin: Send origin only for cross-origin
        # - no-referrer for authenticated responses (prevent token leakage)
        if "Authorization" in request.headers or "X-API-Key" in request.headers:
            response.headers["Referrer-Policy"] = "no-referrer"
        else:
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # =================================================================
        # CACHE CONTROL
        # =================================================================

        # Prevent caching of authenticated responses
        if "Authorization" in request.headers or "X-API-Key" in request.headers:
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # =================================================================
        # HSTS (HTTPS enforcement)
        # =================================================================

        if self.is_production:
            # Strict-Transport-Security
            # - max-age: How long browsers should remember HTTPS-only
            # - includeSubDomains: Apply to all subdomains
            # - preload: Allow inclusion in browser preload lists
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )

        # =================================================================
        # CONTENT SECURITY POLICY (CSP)
        # =================================================================

        csp_directives = [
            # Default: only same-origin
            "default-src 'self'",

            # Scripts: only same-origin, no inline
            "script-src 'self'",

            # Styles: same-origin + inline (for Swagger UI)
            "style-src 'self' 'unsafe-inline'",

            # Images: same-origin + data URIs
            "img-src 'self' data:",

            # Fonts: same-origin
            "font-src 'self'",

            # Connect: same-origin (API calls)
            "connect-src 'self'",

            # Frame ancestors: prevent embedding
            f"frame-ancestors {self.frame_ancestors}",

            # Base URI: prevent base tag hijacking
            "base-uri 'self'",

            # Form actions: only same-origin
            "form-action 'self'",

            # Block mixed content
            "block-all-mixed-content",

            # Upgrade insecure requests (production only)
            *(['upgrade-insecure-requests'] if self.is_production else []),
        ]

        # Add report URI if configured
        if self.csp_report_uri:
            csp_directives.append(f"report-uri {self.csp_report_uri}")

        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # =================================================================
        # PERMISSIONS POLICY (Feature Policy successor)
        # =================================================================

        permissions = [
            # Disable geolocation
            "geolocation=()",

            # Disable camera
            "camera=()",

            # Disable microphone
            "microphone=()",

            # Disable payment
            "payment=()",

            # Disable USB
            "usb=()",

            # Disable accelerometer
            "accelerometer=()",

            # Disable gyroscope
            "gyroscope=()",

            # Disable magnetometer
            "magnetometer=()",
        ]

        response.headers["Permissions-Policy"] = ", ".join(permissions)

        # =================================================================
        # CROSS-ORIGIN POLICIES
        # =================================================================

        # Prevent cross-origin resource sharing attacks
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"

        return response


# =============================================================================
# CONVENIENCE CONFIGURATIONS
# =============================================================================

def create_security_headers_middleware(app, is_production: bool = False):
    """
    Factory for security headers middleware with default configuration.

    Usage:
        app = FastAPI()
        app.add_middleware(create_security_headers_middleware(app, is_production=True))
    """
    return SecurityHeadersMiddleware(
        app,
        is_production=is_production,
        hsts_max_age=31536000,  # 1 year
        frame_ancestors="'none'",
    )


# Development configuration (relaxed for Swagger UI)
class DevelopmentSecurityHeaders(SecurityHeadersMiddleware):
    """
    Relaxed security headers for development.

    Differences from production:
    - No HSTS
    - Relaxed CSP for Swagger UI
    """

    def __init__(self, app):
        super().__init__(
            app,
            is_production=False,
            frame_ancestors="'self'",  # Allow Swagger UI iframes
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await super().dispatch(request, call_next)

        # Override CSP for Swagger UI paths
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            # Relaxed CSP for documentation
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'self'"
            )

        return response
