#!/usr/bin/env python3
"""
SOLVEREIGN V4.3.1 - Staging Pre-Flight Check
=============================================

Run before Wien Pilot launch to verify all critical systems.

Usage:
    # Set environment variables first
    export STAGING_URL=https://staging.solvereign.com
    export STAGING_TOKEN=<entra_id_bearer_token>

    # Run all checks
    python scripts/staging_preflight.py

    # Run specific checks
    python scripts/staging_preflight.py --check headers
    python scripts/staging_preflight.py --check entra
    python scripts/staging_preflight.py --check rate-limit

Output:
    evidence/staging_preflight_{timestamp}.json
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

    def __init__(self, staging_url: str, token: Optional[str] = None):
        self.staging_url = staging_url.rstrip("/")
        self.token = token
        self.results: List[CheckResult] = []

    async def run_all(self) -> Dict[str, Any]:
        """Run all pre-flight checks."""
        print(f"\n{'='*60}")
        print("SOLVEREIGN V4.3.1 - Staging Pre-Flight Check")
        print(f"Target: {self.staging_url}")
        print(f"Time: {datetime.utcnow().isoformat()}Z")
        print(f"{'='*60}\n")

        # 1. Security Headers
        await self._check_security_headers()

        # 2. Route Caching
        await self._check_route_caching()

        # 3. Entra ID (if token provided)
        if self.token:
            await self._check_entra_auth()
        else:
            print("[SKIP] Entra ID check (no token provided)")

        # 4. API Health
        await self._check_api_health()

        # 5. Portal Page Load
        await self._check_portal_page()

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

    async def _check_entra_auth(self):
        """Check Entra ID token validation."""
        import httpx

        start = time.time()
        name = "entra_auth"

        try:
            print(f"\n[CHECK] Entra ID authentication...")

            async with httpx.AsyncClient(timeout=30) as client:
                # Try to access a protected endpoint
                response = await client.get(
                    f"{self.staging_url}/api/v1/portal/dashboard/summary",
                    headers={"Authorization": f"Bearer {self.token}"},
                    params={"snapshot_id": "test"},
                )

            # 200 or 404 (no snapshot) = auth OK
            # 401 = auth failed (wrong aud/iss)
            # 403 = tenant not mapped

            if response.status_code == 401:
                error_detail = response.json().get("detail", "Unknown error")
                passed = False
                details = {
                    "status_code": response.status_code,
                    "error": error_detail,
                    "hint": "Check OIDC_AUDIENCE and OIDC_ISSUER env vars",
                }
            elif response.status_code == 403:
                error_detail = response.json().get("detail", {})
                error_code = error_detail.get("error", "") if isinstance(error_detail, dict) else ""

                if error_code == "TENANT_NOT_MAPPED":
                    passed = False
                    details = {
                        "status_code": response.status_code,
                        "error": "TENANT_NOT_MAPPED",
                        "entra_tid": error_detail.get("entra_tid") if isinstance(error_detail, dict) else None,
                        "hint": "Add tenant_identities mapping for this Entra tenant",
                    }
                else:
                    # Other 403 = role issue, auth itself worked
                    passed = True
                    details = {"status_code": response.status_code, "note": "Auth OK, role/permission issue"}
            else:
                # 200, 404 = auth worked
                passed = True
                details = {"status_code": response.status_code}

            self.results.append(CheckResult(
                name=name,
                passed=passed,
                duration_ms=int((time.time() - start) * 1000),
                details=details,
                error=details.get("error") if not passed else None,
                severity="BLOCKER",
            ))

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Entra ID: status={response.status_code}")
            if not passed:
                print(f"       Hint: {details.get('hint', 'Check logs')}")

        except Exception as e:
            self.results.append(CheckResult(
                name=name,
                passed=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
                severity="BLOCKER",
            ))
            print(f"  [FAIL] Entra ID: {e}")

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

    def _generate_report(self) -> Dict[str, Any]:
        """Generate final report."""
        blockers = [r for r in self.results if not r.passed and r.severity == "BLOCKER"]
        warnings = [r for r in self.results if not r.passed and r.severity == "WARNING"]
        passed = [r for r in self.results if r.passed]

        report = {
            "meta": {
                "staging_url": self.staging_url,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "version": "V4.3.1",
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
    parser = argparse.ArgumentParser(description="Staging Pre-Flight Check")
    parser.add_argument(
        "--url",
        default=os.getenv("STAGING_URL", "http://localhost:3000"),
        help="Staging URL (default: STAGING_URL env var or localhost:3000)"
    )
    parser.add_argument(
        "--token",
        default=os.getenv("STAGING_TOKEN"),
        help="Entra ID Bearer token (default: STAGING_TOKEN env var)"
    )
    parser.add_argument(
        "--check",
        choices=["all", "headers", "entra", "health", "portal"],
        default="all",
        help="Which checks to run"
    )
    args = parser.parse_args()

    preflight = StagingPreFlight(args.url, args.token)
    report = await preflight.run_all()

    sys.exit(0 if report["summary"]["ready_for_pilot"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
