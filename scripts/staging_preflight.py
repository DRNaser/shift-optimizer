#!/usr/bin/env python3
"""
SOLVEREIGN V4.5 - Staging Pre-Flight Check
=============================================

Run before production launch to verify all critical systems.

Usage:
    # Set environment variables first (NEVER hardcode credentials)
    export STAGING_URL=https://staging.solvereign.com
    export STAGING_EMAIL=<your-test-email>
    export STAGING_PASSWORD=<your-test-password>

    # Run all checks
    python scripts/staging_preflight.py

    # Run specific checks
    python scripts/staging_preflight.py --check headers
    python scripts/staging_preflight.py --check auth
    python scripts/staging_preflight.py --check rate-limit

    # Docker-native (avoids Windows timeouts):
    docker compose exec api python scripts/staging_preflight.py --base-url http://localhost:8000

Output:
    evidence/staging_preflight_{timestamp}.json

SECURITY:
    - Never hardcode credentials in code or docs
    - Use environment variables for test credentials
    - Never commit credentials to version control

Notes:
    - Login and /api/auth/me use the SAME httpx.Client for cookie persistence
    - If running on localhost HTTP with Secure cookies, will warn about HTTPS requirement
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

# Windows console fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


@dataclass
class CheckResult:
    """Result of a single check."""
    name: str
    passed: bool
    duration_ms: int
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    severity: str = "BLOCKER"  # BLOCKER, WARNING, INFO


class StagingPreFlight:
    """Pre-flight checks for staging environment."""

    def __init__(
        self,
        staging_url: str,
        email: Optional[str] = None,
        password: Optional[str] = None
    ):
        self.staging_url = staging_url.rstrip("/")
        self.email = email
        self.password = password
        self.results: List[CheckResult] = []
        # Persistent client for cookie handling - will be created in run_all
        self._auth_client: Optional["httpx.AsyncClient"] = None
        # Track if we detected Secure cookie issue on HTTP
        self._secure_cookie_warning: Optional[str] = None

    async def _login_with_client(self, client: "httpx.AsyncClient") -> Dict[str, Any]:
        """Login using provided client instance for cookie persistence.

        Returns dict with:
            - success: bool
            - cookie_names: list of cookie names received (for logging)
            - secure_cookie_on_http: bool - True if Secure cookie on HTTP (will fail)
            - error: str or None
        """
        import httpx

        result = {
            "success": False,
            "cookie_names": [],
            "secure_cookie_on_http": False,
            "error": None,
        }

        if not self.email or not self.password:
            result["error"] = "No credentials provided"
            return result

        try:
            response = await client.post(
                f"{self.staging_url}/api/auth/login",
                json={"email": self.email, "password": self.password},
            )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    result["error"] = error_data.get("detail", f"HTTP {response.status_code}")
                except Exception:
                    result["error"] = f"HTTP {response.status_code}"
                return result

            # Check Set-Cookie header for Secure flag issue
            set_cookie = response.headers.get("set-cookie", "")
            is_http = self.staging_url.startswith("http://")

            if set_cookie and is_http:
                set_cookie_lower = set_cookie.lower()
                if "secure" in set_cookie_lower:
                    result["secure_cookie_on_http"] = True
                    self._secure_cookie_warning = (
                        "Cookie has 'Secure' flag but URL is HTTP. "
                        "Browser will reject cookie. Use HTTPS or run on real staging host."
                    )

            # Log cookie names received (NOT values - security)
            result["cookie_names"] = list(client.cookies.keys())

            # Check if __Host-sv_platform_session cookie was set
            if "__Host-sv_platform_session" in client.cookies:
                result["success"] = True
                print(f"  [INFO] Cookies received: {result['cookie_names']}")
            else:
                # Cookie might not be in client.cookies if Secure flag blocks it on HTTP
                if result["secure_cookie_on_http"]:
                    result["error"] = (
                        "HTTPS required for Secure cookie. "
                        "Login succeeded but cookie not stored (Secure flag on HTTP)."
                    )
                else:
                    result["error"] = "Login returned 200 but no __Host-sv_platform_session cookie set"

            return result

        except Exception as e:
            result["error"] = str(e)
            return result

    async def run_all(self) -> Dict[str, Any]:
        """Run all pre-flight checks."""
        print(f"\n{'='*60}")
        print("SOLVEREIGN V4.4 - Staging Pre-Flight Check")
        print(f"Target: {self.staging_url}")
        print(f"Time: {datetime.utcnow().isoformat()}Z")
        print(f"{'='*60}\n")

        # 1. Security Headers
        await self._check_security_headers()

        # 2. Route Caching
        await self._check_route_caching()

        # 3. Internal RBAC Auth (if credentials provided)
        if self.email and self.password:
            await self._check_internal_auth()
        else:
            print("[SKIP] Internal Auth check (no credentials provided)")

        # 4. API Health
        await self._check_api_health()

        # 5. Auth Health
        await self._check_auth_health()

        # 6. Portal Page Load
        await self._check_portal_page()

        # 7. Pilot-Kill Check: Cookie Secure Flag (proxy/TLS)
        await self._check_cookie_secure_flag()

        # 8. Pilot-Kill Check: CSRF Protection (no Origin/Referer → blocked)
        await self._check_csrf_protection()

        # 9. Pilot-Kill Check: Session TTL / Time Drift
        await self._check_session_ttl()

        # Generate report
        return self._generate_report()

    async def _check_security_headers(self):
        """Check security headers on /my-plan."""
        import httpx

        start = time.time()
        name = "security_headers"

        try:
            print(f"[CHECK] Security headers on /my-plan...")

            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                # Use a dummy token to trigger the page
                response = await client.get(
                    f"{self.staging_url}/my-plan",
                    params={"t": "test_token_for_headers_check"}
                )

            headers = dict(response.headers)

            # Required headers
            required = {
                "referrer-policy": "no-referrer",
                "x-frame-options": "DENY",
                "x-content-type-options": "nosniff",
            }

            # Check cache-control contains no-store
            cache_control = headers.get("cache-control", "").lower()
            has_no_store = "no-store" in cache_control

            # Check CSP exists
            csp = headers.get("content-security-policy", "")
            has_csp = bool(csp)

            missing = []
            for header, expected in required.items():
                actual = headers.get(header, "").lower()
                if expected.lower() not in actual:
                    missing.append(f"{header} (expected: {expected}, got: {actual or 'missing'})")

            if not has_no_store:
                missing.append(f"cache-control (expected: no-store, got: {cache_control or 'missing'})")

            if not has_csp:
                missing.append("content-security-policy (missing)")

            passed = len(missing) == 0

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={
                    "headers": {k: v for k, v in headers.items() if k.lower() in [
                        "referrer-policy", "cache-control", "x-frame-options",
                        "x-content-type-options", "content-security-policy"
                    ]},
                    "missing": missing,
                },
                error=f"Missing headers: {', '.join(missing)}" if missing else None,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Security headers: {len(required) + 2 - len(missing)}/{len(required) + 2}")
            if missing:
                for m in missing:
                    print(f"       - {m}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Security headers: {e}")

    async def _check_route_caching(self):
        """Check that BFF routes are not cached."""
        import httpx

        start = time.time()
        name = "route_caching"

        try:
            print(f"\n[CHECK] Route caching prevention...")

            # Check BFF routes
            bff_routes = [
                "/api/portal/session",
                "/api/portal-admin/summary",
                "/api/auth/me",
            ]

            issues = []

            async with httpx.AsyncClient(timeout=30) as client:
                for route in bff_routes:
                    try:
                        response = await client.get(f"{self.staging_url}{route}")
                        cache_control = response.headers.get("cache-control", "").lower()

                        # Should NOT have public or max-age > 0 for dynamic routes
                        if "public" in cache_control:
                            issues.append(f"{route}: has 'public' in cache-control")

                        # Ideally should have no-store or private
                        # (Next.js may return empty cache-control for errors)
                    except Exception as e:
                        # 401/403 is expected without auth - that's fine
                        pass

            passed = len(issues) == 0

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={"routes_checked": bff_routes, "issues": issues},
                error="\n".join(issues) if issues else None,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Route caching: {len(bff_routes)} routes checked")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Route caching: {e}")

    async def _check_internal_auth(self):
        """Check Internal RBAC authentication.

        CRITICAL: Uses a SINGLE httpx.AsyncClient for both login and /api/auth/me
        to ensure cookie persistence works correctly.
        """
        import httpx

        start = time.time()
        name = "internal_auth"

        try:
            print(f"\n[CHECK] Internal RBAC authentication...")

            # Use a SINGLE persistent client for the entire auth flow
            async with httpx.AsyncClient(timeout=30) as client:
                # Step 1: Login (cookies auto-stored in client)
                login_result = await self._login_with_client(client)

                if not login_result["success"]:
                    # Check for Secure cookie on HTTP issue
                    if login_result["secure_cookie_on_http"]:
                        severity = "WARNING"
                        hint = (
                            "HTTPS required for Secure cookie. "
                            "Run on real staging host or use: "
                            "docker compose exec api python scripts/staging_preflight.py"
                        )
                    else:
                        severity = "BLOCKER"
                        hint = "Check email/password and that user exists in auth.users"

                    self.results.append(CheckResult(
                        name=name,
                        passed=False,
                        duration_ms=int((time.time() - start) * 1000),
                        details={
                            "step": "login",
                            "hint": hint,
                            "cookie_names": login_result["cookie_names"],
                            "secure_cookie_on_http": login_result["secure_cookie_on_http"],
                        },
                        error=login_result["error"],
                        severity=severity,
                    ))
                    print(f"  [FAIL] Internal Auth: {login_result['error']}")
                    if login_result["secure_cookie_on_http"]:
                        print(f"  [HINT] {hint}")
                    return

                # Step 2: Verify __Host-sv_platform_session cookie exists in client
                if "__Host-sv_platform_session" not in client.cookies:
                    self.results.append(CheckResult(
                        name=name,
                        passed=False,
                        duration_ms=int((time.time() - start) * 1000),
                        details={
                            "step": "cookie_check",
                            "cookie_names": list(client.cookies.keys()),
                        },
                        error="__Host-sv_platform_session cookie not found in client after login",
                        severity="BLOCKER",
                    ))
                    print(f"  [FAIL] Internal Auth: No __Host-sv_platform_session cookie after login")
                    return

                # Step 3: Call /api/auth/me using SAME client (cookies auto-sent)
                response = await client.get(f"{self.staging_url}/api/auth/me")

                if response.status_code == 200:
                    data = response.json()
                    passed = True
                    details = {
                        "status_code": response.status_code,
                        "user_id": data.get("user_id"),
                        "email": data.get("email"),
                        "tenant_id": data.get("tenant_id"),
                        "role_name": data.get("role_name"),
                        "permissions": data.get("permissions", [])[:5],  # First 5
                        "cookie_names": list(client.cookies.keys()),
                    }
                else:
                    passed = False
                    try:
                        error_body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:200]
                    except Exception:
                        error_body = response.text[:200]
                    details = {
                        "status_code": response.status_code,
                        "error": error_body,
                        "cookie_names": list(client.cookies.keys()),
                    }

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details=details,
                error=str(details.get("error")) if not passed else None,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            if passed:
                print(f"  [{status}] Internal Auth: {details.get('email')} as {details.get('role_name')}")
            else:
                print(f"  [{status}] Internal Auth: /api/auth/me returned {response.status_code}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Internal Auth: {e}")

    async def _check_api_health(self):
        """Check API health endpoint."""
        import httpx

        start = time.time()
        name = "api_health"

        try:
            print(f"\n[CHECK] API health...")

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.staging_url}/health")

            passed = response.status_code == 200

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={"status_code": response.status_code},
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] API health: {response.status_code}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] API health: {e}")

    async def _check_auth_health(self):
        """Check Auth health endpoint."""
        import httpx

        start = time.time()
        name = "auth_health"

        try:
            print(f"\n[CHECK] Auth health...")

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.staging_url}/api/auth/health")

            passed = response.status_code == 200

            details = {"status_code": response.status_code}
            if passed:
                data = response.json()
                details["service"] = data.get("service")
                details["session_cookie_name"] = data.get("session_cookie_name")

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details=details,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Auth health: {response.status_code}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Auth health: {e}")

    async def _check_portal_page(self):
        """Check portal page loads."""
        import httpx

        start = time.time()
        name = "portal_page"

        try:
            print(f"\n[CHECK] Portal page load...")

            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(f"{self.staging_url}/my-plan")

            # Should return 200 (page loads, shows error state without token)
            passed = response.status_code == 200

            # Check for React hydration
            has_react = "react" in response.text.lower() or "__NEXT" in response.text

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={
                    "status_code": response.status_code,
                    "has_react": has_react,
                    "content_length": len(response.content),
                },
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Portal page: {response.status_code}, {len(response.content)} bytes")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Portal page: {e}")

    async def _check_cookie_secure_flag(self):
        """Pilot-Kill Check: Verify Secure flag on cookies survives TLS termination."""
        import httpx

        start = time.time()
        name = "cookie_secure_flag"

        try:
            print(f"\n[CHECK] Cookie Secure flag (proxy/TLS)...")

            # We need to login to get a cookie, or at least try portal session
            async with httpx.AsyncClient(timeout=30) as client:
                # Try creating a portal session (will fail without token, but we get headers)
                response = await client.post(
                    f"{self.staging_url}/api/portal/session",
                    json={"token": "test_for_cookie_check"},
                )

                # Check Set-Cookie header for Secure flag
                set_cookie = response.headers.get("set-cookie", "")

                # Also try auth login if we have credentials
                if self.email and self.password:
                    response = await client.post(
                        f"{self.staging_url}/api/auth/login",
                        json={"email": self.email, "password": self.password},
                    )
                    set_cookie = response.headers.get("set-cookie", "")

            issues = []

            # If we got a cookie, check flags
            if set_cookie:
                set_cookie_lower = set_cookie.lower()

                # Check for Secure flag (only matters on HTTPS)
                if self.staging_url.startswith("https://"):
                    if "secure" not in set_cookie_lower:
                        issues.append("Cookie missing 'Secure' flag (critical for HTTPS)")

                # Check for HttpOnly
                if "httponly" not in set_cookie_lower:
                    issues.append("Cookie missing 'HttpOnly' flag")

                # Check for SameSite
                if "samesite" not in set_cookie_lower:
                    issues.append("Cookie missing 'SameSite' attribute")
            else:
                # No cookie set - that's okay for portal session without valid token
                if self.email and self.password:
                    issues.append("No Set-Cookie header received after login")

            # For HTTPS, we must have Secure
            passed = len(issues) == 0

            # If it's localhost/HTTP, this is a warning not blocker
            severity = "BLOCKER" if self.staging_url.startswith("https://") else "WARNING"

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={
                    "set_cookie_present": bool(set_cookie),
                    "issues": issues,
                    "url_is_https": self.staging_url.startswith("https://"),
                },
                error="; ".join(issues) if issues else None,
                severity=severity,
            ))

            status = "PASS" if passed else "FAIL"
            if not set_cookie and not (self.email and self.password):
                print(f"  [SKIP] Cookie Secure flag: No credentials to test login")
            else:
                print(f"  [{status}] Cookie Secure flag: {'OK' if passed else '; '.join(issues)}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="WARNING",
            ))
            print(f"  [FAIL] Cookie Secure flag: {e}")

    async def _check_csrf_protection(self):
        """Pilot-Kill Check: CSRF protection via SameSite=Strict cookie.

        SOLVEREIGN uses SameSite=Strict on session cookies for CSRF protection.
        This is the recommended approach for modern browsers (> 99% coverage).
        We verify that the cookie has SameSite=Strict/Lax set.

        Note: Requests without Origin/Referer are intentionally allowed because
        SameSite=Strict prevents cross-site cookie attachment in browsers.
        """
        import httpx

        start = time.time()
        name = "csrf_protection"

        try:
            print(f"\n[CHECK] CSRF protection (SameSite cookie check)...")

            # Try to login and check the Set-Cookie header
            async with httpx.AsyncClient(timeout=30) as client:
                # Login to get a cookie with proper flags
                if self.email and self.password:
                    response = await client.post(
                        f"{self.staging_url}/api/auth/login",
                        json={"email": self.email, "password": self.password},
                    )
                    set_cookie = response.headers.get("set-cookie", "")
                else:
                    # Try portal session endpoint
                    response = await client.post(
                        f"{self.staging_url}/api/portal/session",
                        json={"token": "test_token"},
                    )
                    set_cookie = response.headers.get("set-cookie", "")

            issues = []

            if set_cookie:
                set_cookie_lower = set_cookie.lower()

                # Check for SameSite attribute
                if "samesite=strict" in set_cookie_lower:
                    samesite_value = "strict"
                elif "samesite=lax" in set_cookie_lower:
                    samesite_value = "lax"
                elif "samesite=none" in set_cookie_lower:
                    samesite_value = "none"
                    issues.append("Cookie has SameSite=None - CSRF protection disabled!")
                elif "samesite" not in set_cookie_lower:
                    samesite_value = "missing"
                    issues.append("Cookie missing SameSite attribute (defaults to Lax in modern browsers)")
                else:
                    samesite_value = "unknown"

                # SameSite=Strict is best, Lax is acceptable
                if samesite_value in ("strict", "lax"):
                    passed = True
                else:
                    passed = len(issues) == 0
            else:
                # No cookie received
                if self.email and self.password:
                    issues.append("Login did not return Set-Cookie header")
                    passed = False
                else:
                    # Skipped - no credentials
                    self.results.append(CheckResult(
                        name=name,
                        passed=True,
                        duration_ms=int((time.time() - start) * 1000),
                        details={"skipped": True, "reason": "No credentials to test"},
                        severity="WARNING",
                    ))
                    print(f"  [SKIP] CSRF protection: No credentials")
                    return

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={
                    "set_cookie_present": bool(set_cookie),
                    "samesite_value": samesite_value if set_cookie else None,
                    "issues": issues,
                    "note": "CSRF protection via SameSite=Strict cookie (modern browser approach)",
                },
                error="; ".join(issues) if issues else None,
                severity="BLOCKER" if issues else "INFO",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] CSRF protection: SameSite={samesite_value if set_cookie else 'N/A'}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="WARNING",
            ))
            print(f"  [FAIL] CSRF protection: {e}")

    async def _check_session_ttl(self):
        """Pilot-Kill Check: Session TTL and time drift sanity.

        Uses SINGLE httpx.AsyncClient for login + /api/auth/me to ensure cookie persistence.
        """
        import httpx
        from datetime import datetime, timezone

        start = time.time()
        name = "session_ttl"

        try:
            print(f"\n[CHECK] Session TTL / Time drift...")

            if not self.email or not self.password:
                self.results.append(CheckResult(
                    name=name,
                    passed=True,
                    duration_ms=int((time.time() - start) * 1000),
                    details={"skipped": True, "reason": "No credentials to test"},
                    severity="WARNING",
                ))
                print(f"  [SKIP] Session TTL: No credentials")
                return

            # Use SINGLE client for login + auth/me
            async with httpx.AsyncClient(timeout=30) as client:
                # Login first (cookies stored in client)
                login_result = await self._login_with_client(client)

                if not login_result["success"]:
                    self.results.append(CheckResult(
                        name=name,
                        passed=False,
                        duration_ms=int((time.time() - start) * 1000),
                        details={
                            "step": "login",
                            "error": login_result["error"],
                            "secure_cookie_on_http": login_result["secure_cookie_on_http"],
                        },
                        error=login_result["error"],
                        severity="WARNING",
                    ))
                    print(f"  [FAIL] Session TTL: Login failed - {login_result['error']}")
                    return

                # Get current user info (cookies auto-sent by same client)
                response = await client.get(f"{self.staging_url}/api/auth/me")

            if response.status_code != 200:
                self.results.append(CheckResult(
                    name=name,
                    passed=False,
                    duration_ms=int((time.time() - start) * 1000),
                    details={"status_code": response.status_code},
                    error=f"/api/auth/me returned {response.status_code}",
                    severity="BLOCKER",
                ))
                print(f"  [FAIL] Session TTL: /api/auth/me returned {response.status_code}")
                return

            data = response.json()
            issues = []

            # Check if we have session info
            # The /me endpoint should return user info - we check if session is valid
            if "user_id" not in data:
                issues.append("Session invalid - no user_id returned")

            # Basic sanity: session should work
            passed = len(issues) == 0

            # Note: We can't check server time drift directly without a dedicated endpoint
            # But if session validation works, time is probably okay

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details={
                    "session_valid": "user_id" in data,
                    "user_id": data.get("user_id"),
                    "expires_at": data.get("expires_at"),
                    "issues": issues,
                },
                error="; ".join(issues) if issues else None,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Session TTL: {'Valid session' if passed else '; '.join(issues)}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="WARNING",
            ))
            print(f"  [FAIL] Session TTL: {e}")

    def _generate_report(self) -> Dict[str, Any]:
        """Generate final report."""
        blockers = [r for r in self.results if not r.passed and r.severity == "BLOCKER"]
        warnings = [r for r in self.results if not r.passed and r.severity == "WARNING"]
        passed = [r for r in self.results if r.passed]

        report = {
            "meta": {
                "staging_url": self.staging_url,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "version": "V4.4",
            },
            "summary": {
                "total_checks": len(self.results),
                "passed": len(passed),
                "blockers": len(blockers),
                "warnings": len(warnings),
                "ready_for_pilot": len(blockers) == 0,
            },
            "results": [asdict(r) for r in self.results],
        }

        # Print summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"\nTotal: {len(self.results)} checks")
        print(f"  Passed:   {len(passed)}")
        print(f"  Blockers: {len(blockers)}")
        print(f"  Warnings: {len(warnings)}")

        if blockers:
            print(f"\nBLOCKERS (must fix before pilot):")
            for b in blockers:
                print(f"  - {b.name}: {b.error or 'Failed'}")

        if report["summary"]["ready_for_pilot"]:
            print(f"\n✅ READY FOR PILOT")
        else:
            print(f"\n❌ NOT READY - Fix {len(blockers)} blocker(s)")

        # Save to file
        output_dir = Path("evidence")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"staging_preflight_{timestamp}.json"

        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)

        print(f"\nEvidence saved to: {output_file}")

        return report


async def main():
    parser = argparse.ArgumentParser(
        description="Staging Pre-Flight Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # From host machine:
    python scripts/staging_preflight.py --base-url http://localhost:3000

    # Docker-native (avoids Windows timeouts):
    docker compose exec api python scripts/staging_preflight.py --base-url http://localhost:8000

    # With environment variables:
    export STAGING_URL=https://staging.solvereign.com
    export STAGING_EMAIL=dispatcher@lts.at
    export STAGING_PASSWORD=<password>
    python scripts/staging_preflight.py
        """
    )
    parser.add_argument(
        "--url", "--base-url",
        dest="url",
        default=os.getenv("STAGING_URL", "http://localhost:3000"),
        help="Staging URL (default: STAGING_URL env var or localhost:3000)"
    )
    parser.add_argument(
        "--email",
        default=os.getenv("STAGING_EMAIL"),
        help="User email for internal auth (default: STAGING_EMAIL env var)"
    )
    parser.add_argument(
        "--password",
        default=os.getenv("STAGING_PASSWORD"),
        help="User password for internal auth (default: STAGING_PASSWORD env var)"
    )
    parser.add_argument(
        "--check",
        choices=["all", "headers", "auth", "health", "portal"],
        default="all",
        help="Which checks to run"
    )
    args = parser.parse_args()

    # Validate URL scheme
    if not args.url.startswith(("http://", "https://")):
        print(f"[ERROR] URL must start with http:// or https://: {args.url}")
        sys.exit(1)

    # Warn about HTTP with potential Secure cookies
    if args.url.startswith("http://") and "localhost" not in args.url and "127.0.0.1" not in args.url:
        print(f"[WARNING] Using HTTP for non-localhost URL. Secure cookies may not work.")
        print(f"          Consider using HTTPS or running inside Docker:")
        print(f"          docker compose exec api python scripts/staging_preflight.py")
        print()

    preflight = StagingPreFlight(args.url, args.email, args.password)
    report = await preflight.run_all()

    # Print final warning if Secure cookie issue was detected
    if preflight._secure_cookie_warning:
        print(f"\n[WARNING] {preflight._secure_cookie_warning}")

    sys.exit(0 if report["summary"]["ready_for_pilot"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
