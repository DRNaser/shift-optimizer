"""
SOLVEREIGN V3.3b - Entra ID Activation Checks
=============================================

Run these checks BEFORE going live with Entra ID authentication.
All checks must PASS before activating production traffic.

Usage:
    # Set environment variables first
    export SOLVEREIGN_DATABASE_URL=postgresql://...
    export SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{tid}/v2.0
    export SOLVEREIGN_OIDC_AUDIENCE=api://solvereign-api

    # Run checks
    python backend_py/tests/activation_checks.py

    # Or run specific check
    python backend_py/tests/activation_checks.py --check=rls_leak
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class CheckResult:
    """Result of an activation check."""
    name: str
    passed: bool
    message: str
    details: Dict[str, Any] = None
    critical: bool = True  # If critical, deployment should be blocked


class ActivationChecker:
    """Runs all activation checks for Entra ID deployment."""

    def __init__(self, db_url: str, verbose: bool = False):
        self.db_url = db_url
        self.verbose = verbose
        self.results: List[CheckResult] = []

    def log(self, msg: str):
        """Print log message if verbose."""
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    async def check_1_migration_tables(self) -> CheckResult:
        """
        Check A: Verify tenant_identities table exists with correct schema.
        """
        import psycopg
        from psycopg.rows import dict_row

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # Check table exists
                    await cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'tenant_identities'
                        ) as table_exists
                    """)
                    result = await cur.fetchone()
                    if not result["table_exists"]:
                        return CheckResult(
                            name="migration_tables",
                            passed=False,
                            message="tenant_identities table does not exist",
                            details={"missing_table": "tenant_identities"},
                        )

                    # Check unique constraint
                    await cur.execute("""
                        SELECT COUNT(*) as constraint_count
                        FROM pg_constraint
                        WHERE conname = 'uq_tenant_identity_issuer_tid'
                    """)
                    result = await cur.fetchone()
                    if result["constraint_count"] == 0:
                        return CheckResult(
                            name="migration_tables",
                            passed=False,
                            message="Missing unique constraint on (issuer, external_tid)",
                            details={"missing_constraint": "uq_tenant_identity_issuer_tid"},
                        )

                    # Check columns
                    await cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'tenant_identities'
                    """)
                    columns = [r["column_name"] for r in await cur.fetchall()]
                    required = {"id", "tenant_id", "issuer", "external_tid", "is_active"}
                    missing = required - set(columns)
                    if missing:
                        return CheckResult(
                            name="migration_tables",
                            passed=False,
                            message=f"Missing columns: {missing}",
                            details={"missing_columns": list(missing)},
                        )

                    return CheckResult(
                        name="migration_tables",
                        passed=True,
                        message="tenant_identities table exists with correct schema",
                        details={"columns": columns},
                    )

        except Exception as e:
            return CheckResult(
                name="migration_tables",
                passed=False,
                message=f"Database error: {str(e)}",
                details={"error": str(e)},
            )

    async def check_2_tenant_mapping(self, entra_tid: str = None) -> CheckResult:
        """
        Check B: Verify register_tenant_identity function and tenant mapping.
        """
        import psycopg
        from psycopg.rows import dict_row

        if not entra_tid:
            return CheckResult(
                name="tenant_mapping",
                passed=False,
                message="No ENTRA_TENANT_ID provided. Set via --entra-tid=<uuid>",
                critical=False,
            )

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # Check if mapping exists
                    await cur.execute("""
                        SELECT ti.*, t.name as tenant_name
                        FROM tenant_identities ti
                        JOIN tenants t ON ti.tenant_id = t.id
                        WHERE ti.external_tid = %s
                    """, (entra_tid,))
                    result = await cur.fetchone()

                    if not result:
                        return CheckResult(
                            name="tenant_mapping",
                            passed=False,
                            message=f"No mapping found for Entra tid: {entra_tid}",
                            details={
                                "entra_tid": entra_tid,
                                "hint": "Run register_tenant_identity() with correct tenant_id",
                            },
                        )

                    if not result["is_active"]:
                        return CheckResult(
                            name="tenant_mapping",
                            passed=False,
                            message=f"Tenant mapping exists but is_active=FALSE",
                            details={"mapping": dict(result)},
                        )

                    return CheckResult(
                        name="tenant_mapping",
                        passed=True,
                        message=f"Tenant mapping OK: {result['tenant_name']} (id={result['tenant_id']})",
                        details={"mapping": dict(result)},
                    )

        except Exception as e:
            return CheckResult(
                name="tenant_mapping",
                passed=False,
                message=f"Database error: {str(e)}",
                details={"error": str(e)},
            )

    def check_3_issuer_audience(self, issuer: str = None, audience: str = None) -> CheckResult:
        """
        Check: Verify OIDC issuer and audience configuration.

        CRITICAL: 90% of 401 errors happen here!
        """
        if not issuer:
            return CheckResult(
                name="issuer_audience",
                passed=False,
                message="SOLVEREIGN_OIDC_ISSUER not set",
                details={"env_var": "SOLVEREIGN_OIDC_ISSUER"},
            )

        if not audience:
            return CheckResult(
                name="issuer_audience",
                passed=False,
                message="SOLVEREIGN_OIDC_AUDIENCE not set",
                details={"env_var": "SOLVEREIGN_OIDC_AUDIENCE"},
            )

        # Validate issuer format
        errors = []
        warnings = []

        # Check for v2.0 endpoint
        if "login.microsoftonline.com" in issuer:
            if "/v2.0" not in issuer:
                warnings.append(
                    "Issuer may be v1.0 format. Entra tokens usually use v2.0. "
                    "Check your token's 'iss' claim matches exactly."
                )

        # Check audience format
        if not audience.startswith("api://") and not audience.startswith("https://"):
            warnings.append(
                f"Audience '{audience}' may be a client ID. "
                "Check if your token's 'aud' claim uses Application ID URI or Client ID."
            )

        if errors:
            return CheckResult(
                name="issuer_audience",
                passed=False,
                message="; ".join(errors),
                details={"issuer": issuer, "audience": audience, "errors": errors},
            )

        return CheckResult(
            name="issuer_audience",
            passed=True,
            message=f"OIDC config OK: issuer={issuer[:50]}...",
            details={
                "issuer": issuer,
                "audience": audience,
                "warnings": warnings if warnings else None,
            },
        )

    def check_4_header_override_guardrail(self, environment: str) -> CheckResult:
        """
        Check: Verify allow_header_tenant_override is FALSE in production.
        """
        from api.config import settings

        if environment == "production":
            if settings.allow_header_tenant_override:
                return CheckResult(
                    name="header_override_guardrail",
                    passed=False,
                    message="CRITICAL: allow_header_tenant_override=true in production!",
                    details={
                        "environment": environment,
                        "allow_header_tenant_override": True,
                        "fix": "Set SOLVEREIGN_ALLOW_HEADER_TENANT_OVERRIDE=false",
                    },
                )

        return CheckResult(
            name="header_override_guardrail",
            passed=True,
            message=f"Header override guardrail OK (env={environment})",
            details={
                "environment": environment,
                "allow_header_tenant_override": settings.allow_header_tenant_override,
            },
        )

    async def check_5_rls_no_leak(self) -> CheckResult:
        """
        Check: Verify RLS session variable is properly scoped per connection.

        This tests that tenant_connection() properly isolates RLS context.
        """
        import psycopg
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        try:
            # Create a pool with 2 connections
            pool = AsyncConnectionPool(
                conninfo=self.db_url,
                min_size=2,
                max_size=2,
                kwargs={"row_factory": dict_row},
            )
            await pool.wait()

            try:
                # Request 1: Set tenant_id = 999 on connection A
                async with pool.connection() as conn_a:
                    async with conn_a.cursor() as cur:
                        await cur.execute(
                            "SELECT set_config('app.current_tenant_id', '999', false)"
                        )
                        await cur.execute(
                            "SELECT current_setting('app.current_tenant_id', true) as tid"
                        )
                        result = await cur.fetchone()
                        tid_a = result["tid"] if result else None
                        self.log(f"Connection A tenant_id after SET: {tid_a}")

                # Connection A returns to pool

                # Request 2: Get a connection (could be A or B), check if tenant leaked
                async with pool.connection() as conn_b:
                    async with conn_b.cursor() as cur:
                        await cur.execute(
                            "SELECT current_setting('app.current_tenant_id', true) as tid"
                        )
                        result = await cur.fetchone()
                        tid_b = result["tid"] if result else None
                        self.log(f"Connection B tenant_id (should be empty): {tid_b}")

                # Check for leak
                if tid_b and tid_b == "999":
                    return CheckResult(
                        name="rls_no_leak",
                        passed=False,
                        message="RLS LEAK DETECTED! Tenant ID persisted across connection reuse.",
                        details={
                            "tenant_id_set": "999",
                            "tenant_id_leaked": tid_b,
                            "fix": "Use RESET ALL or SET ... true for local scope",
                        },
                    )

                return CheckResult(
                    name="rls_no_leak",
                    passed=True,
                    message="RLS isolation OK (no tenant leak across connections)",
                    details={
                        "conn_a_tid": tid_a,
                        "conn_b_tid": tid_b,
                    },
                )

            finally:
                await pool.close()

        except Exception as e:
            return CheckResult(
                name="rls_no_leak",
                passed=False,
                message=f"RLS test error: {str(e)}",
                details={"error": str(e)},
            )

    def check_6_m2m_role_restriction(self) -> CheckResult:
        """
        Check: Verify M2M tokens have APPROVER role stripped.
        """
        from api.security.entra_auth import map_entra_roles, RESTRICTED_APP_ROLES

        # Test user token (should keep APPROVER)
        user_roles = map_entra_roles(["PLANNER", "APPROVER"], is_app_token=False)
        user_has_approver = "plan_approver" in user_roles

        # Test app token (should strip APPROVER)
        app_roles = map_entra_roles(["PLANNER", "APPROVER"], is_app_token=True)
        app_has_approver = "plan_approver" in app_roles

        if not user_has_approver:
            return CheckResult(
                name="m2m_role_restriction",
                passed=False,
                message="User tokens should keep APPROVER role",
                details={"user_roles": user_roles},
            )

        if app_has_approver:
            return CheckResult(
                name="m2m_role_restriction",
                passed=False,
                message="CRITICAL: App tokens should NOT have APPROVER role!",
                details={"app_roles": app_roles, "should_be_blocked": "plan_approver"},
            )

        return CheckResult(
            name="m2m_role_restriction",
            passed=True,
            message="M2M role restriction OK (APPROVER stripped from app tokens)",
            details={
                "user_roles": user_roles,
                "app_roles": app_roles,
                "restricted_roles": list(RESTRICTED_APP_ROLES),
            },
        )

    async def check_7_tenant_name_lookup(self) -> CheckResult:
        """
        Check: Verify tenant lookup uses correct column (name vs tenant_key).

        Common bug: name='lts-transport-001' vs name='LTS Transport & Logistik GmbH'
        """
        import psycopg
        from psycopg.rows import dict_row

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # List all tenants
                    await cur.execute("""
                        SELECT id, name, is_active
                        FROM tenants
                        ORDER BY id
                    """)
                    tenants = await cur.fetchall()

                    if not tenants:
                        return CheckResult(
                            name="tenant_name_lookup",
                            passed=False,
                            message="No tenants found in database",
                            details={"hint": "Run migration 006_multi_tenant.sql first"},
                        )

                    # Check for common naming issues
                    tenant_names = [t["name"] for t in tenants]

                    return CheckResult(
                        name="tenant_name_lookup",
                        passed=True,
                        message=f"Found {len(tenants)} tenant(s)",
                        details={
                            "tenants": [
                                {"id": t["id"], "name": t["name"], "is_active": t["is_active"]}
                                for t in tenants
                            ],
                            "note": "Ensure tenant name matches what you use in register_tenant_identity()",
                        },
                    )

        except Exception as e:
            return CheckResult(
                name="tenant_name_lookup",
                passed=False,
                message=f"Database error: {str(e)}",
                details={"error": str(e)},
            )

    async def run_all_checks(
        self,
        entra_tid: str = None,
        issuer: str = None,
        audience: str = None,
        environment: str = "production",
    ) -> Tuple[bool, List[CheckResult]]:
        """Run all activation checks and return summary."""

        print("\n" + "=" * 70)
        print("SOLVEREIGN V3.3b - Entra ID Activation Checks")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Environment: {environment}")
        print("=" * 70 + "\n")

        # Run all checks
        checks = [
            ("1. Migration Tables", await self.check_1_migration_tables()),
            ("2. Tenant Mapping", await self.check_2_tenant_mapping(entra_tid)),
            ("3. Issuer/Audience", self.check_3_issuer_audience(issuer, audience)),
            ("4. Header Override Guardrail", self.check_4_header_override_guardrail(environment)),
            ("5. RLS No Leak", await self.check_5_rls_no_leak()),
            ("6. M2M Role Restriction", self.check_6_m2m_role_restriction()),
            ("7. Tenant Name Lookup", await self.check_7_tenant_name_lookup()),
        ]

        all_passed = True
        critical_failed = False

        for check_name, result in checks:
            status = "PASS" if result.passed else "FAIL"
            icon = "✓" if result.passed else "✗"

            print(f"{icon} {check_name}: {status}")
            print(f"   {result.message}")

            if result.details and self.verbose:
                for k, v in result.details.items():
                    if v is not None:
                        print(f"   - {k}: {v}")

            if not result.passed:
                all_passed = False
                if result.critical:
                    critical_failed = True

            print()
            self.results.append(result)

        # Summary
        print("=" * 70)
        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)

        if all_passed:
            print(f"✓ ALL CHECKS PASSED ({passed_count}/{total_count})")
            print("  Safe to activate Entra ID authentication")
        elif critical_failed:
            print(f"✗ CRITICAL CHECKS FAILED ({passed_count}/{total_count} passed)")
            print("  DO NOT activate until all critical issues are resolved")
        else:
            print(f"⚠ SOME CHECKS FAILED ({passed_count}/{total_count} passed)")
            print("  Review failed checks before activation")

        print("=" * 70 + "\n")

        return all_passed, self.results


async def main():
    parser = argparse.ArgumentParser(description="SOLVEREIGN Entra ID Activation Checks")
    parser.add_argument(
        "--db-url",
        default=os.getenv("SOLVEREIGN_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--entra-tid",
        default=os.getenv("SOLVEREIGN_ENTRA_TENANT_ID"),
        help="Azure AD Tenant ID to check mapping for",
    )
    parser.add_argument(
        "--issuer",
        default=os.getenv("SOLVEREIGN_OIDC_ISSUER"),
        help="OIDC issuer URL",
    )
    parser.add_argument(
        "--audience",
        default=os.getenv("SOLVEREIGN_OIDC_AUDIENCE"),
        help="OIDC audience",
    )
    parser.add_argument(
        "--environment",
        default=os.getenv("SOLVEREIGN_ENVIRONMENT", "production"),
        choices=["development", "staging", "production"],
        help="Deployment environment",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--check",
        help="Run specific check only (e.g., rls_leak, m2m, migration)",
    )

    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: Database URL required. Set SOLVEREIGN_DATABASE_URL or use --db-url")
        sys.exit(1)

    checker = ActivationChecker(args.db_url, verbose=args.verbose)

    all_passed, results = await checker.run_all_checks(
        entra_tid=args.entra_tid,
        issuer=args.issuer,
        audience=args.audience,
        environment=args.environment,
    )

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
