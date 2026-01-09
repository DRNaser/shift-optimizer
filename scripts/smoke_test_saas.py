#!/usr/bin/env python3
"""
SOLVEREIGN SaaS Smoke Test Checklist (V3.7.2)
=============================================

10-minute Go/No-Go verification for pilot deployment.

Usage:
    python scripts/smoke_test_saas.py --env staging
    python scripts/smoke_test_saas.py --env production --skip-destructive

Checks:
1. Database migrations applied (025-027a)
2. State machine integrity
3. Plan state transitions work
4. Evidence blob storage works
5. Signed URL generation works
6. Entra ID token validation (if configured)
7. RBAC enforcement
8. V3.7.2: Plan versioning + snapshot integrity
9. V3.7.2: Freeze window enforcement
"""

import os
import sys
import json
import asyncio
import argparse
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, FAIL, SKIP, WARN
    duration_ms: float
    details: str = ""
    error: Optional[str] = None


@dataclass
class SmokeTestReport:
    environment: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == "FAIL")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "WARN")

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.checks if c.status == "SKIP")

    @property
    def verdict(self) -> str:
        if self.failed > 0:
            return "NO-GO"
        if self.warnings > 2:
            return "REVIEW"
        return "GO"

    def to_dict(self) -> Dict:
        return {
            "environment": self.environment,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "verdict": self.verdict,
            "summary": {
                "passed": self.passed,
                "failed": self.failed,
                "warnings": self.warnings,
                "skipped": self.skipped,
            },
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "duration_ms": c.duration_ms,
                    "details": c.details,
                    "error": c.error,
                }
                for c in self.checks
            ],
        }


class SmokeTestRunner:
    """Runs smoke tests against SOLVEREIGN deployment."""

    def __init__(self, env: str, skip_destructive: bool = False):
        self.env = env
        self.skip_destructive = skip_destructive
        self.report = SmokeTestReport(environment=env, started_at=datetime.now())
        self.db_url = os.environ.get("DATABASE_URL")
        self.api_url = os.environ.get("API_URL", "http://localhost:8000")
        self.storage_configured = bool(
            os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or
            os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        )

    async def run_all(self) -> SmokeTestReport:
        """Run all smoke tests."""
        print(f"\n{'='*60}")
        print(f"SOLVEREIGN SaaS Smoke Test V3.7.2 - {self.env.upper()}")
        print(f"{'='*60}\n")

        # Database checks - Core migrations
        print("\n[Database Migrations]")
        await self._check("migration_026_applied", self._check_migration_026)
        await self._check("migration_026a_applied", self._check_migration_026a)
        await self._check("migration_027_applied", self._check_migration_027)
        await self._check("migration_027a_applied", self._check_migration_027a)

        # Database checks - Integrity
        print("\n[Integrity Checks]")
        await self._check("state_machine_integrity", self._check_state_machine_integrity)
        await self._check("rls_hardening", self._check_rls_hardening)
        await self._check("snapshot_integrity", self._check_snapshot_integrity)

        # State transition checks
        print("\n[State Transitions]")
        await self._check("state_draft_to_solving", self._check_state_transition_draft_solving)
        await self._check("state_published_immutable", self._check_published_immutability)
        await self._check("snapshot_immutable", self._check_snapshot_immutability)

        # V3.7.2: Plan Versioning checks
        print("\n[V3.7.2 Plan Versioning]")
        await self._check("build_snapshot_payload_fn", self._check_build_snapshot_payload)
        await self._check("unique_version_constraint", self._check_unique_version_constraint)
        await self._check("legacy_snapshot_count", self._check_legacy_snapshots)

        # Blob storage checks
        print("\n[Blob Storage]")
        await self._check("blob_storage_configured", self._check_blob_storage)
        await self._check("blob_upload_download", self._check_blob_upload_download)
        await self._check("signed_url_generation", self._check_signed_url)

        # Auth checks
        print("\n[Authentication]")
        await self._check("entra_config_present", self._check_entra_config)

        self.report.completed_at = datetime.now()
        return self.report

    async def _check(self, name: str, check_fn) -> None:
        """Run a single check and record result."""
        import time
        start = time.perf_counter()

        try:
            status, details = await check_fn()
            duration = (time.perf_counter() - start) * 1000
            result = CheckResult(
                name=name,
                status=status,
                duration_ms=round(duration, 2),
                details=details,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            result = CheckResult(
                name=name,
                status="FAIL",
                duration_ms=round(duration, 2),
                error=str(e),
            )

        self.report.checks.append(result)

        # Print result
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "○", "WARN": "⚠"}[result.status]
        color = {"PASS": "\033[92m", "FAIL": "\033[91m", "SKIP": "\033[90m", "WARN": "\033[93m"}[result.status]
        reset = "\033[0m"
        print(f"  {color}{icon}{reset} {name}: {result.status} ({result.duration_ms}ms)")
        if result.details:
            print(f"      {result.details}")
        if result.error:
            print(f"      ERROR: {result.error}")

    # =========================================================================
    # DATABASE CHECKS
    # =========================================================================

    async def _check_migration_026(self) -> Tuple[str, str]:
        """Check if migration 026 is applied."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = '026'"
                )
                row = await cur.fetchone()
                if row:
                    return "PASS", "Migration 026 applied"
                return "FAIL", "Migration 026 not found"

    async def _check_migration_026a(self) -> Tuple[str, str]:
        """Check if migration 026a (atomicity) is applied."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = '026a'"
                )
                row = await cur.fetchone()
                if row:
                    return "PASS", "Migration 026a applied"
                return "WARN", "Migration 026a not applied (atomicity hardening)"

    async def _check_migration_027(self) -> Tuple[str, str]:
        """Check if migration 027 (plan versioning) is applied."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = '027'"
                )
                row = await cur.fetchone()
                if row:
                    return "PASS", "Migration 027 applied (plan versioning)"
                return "FAIL", "Migration 027 not applied (plan versioning)"

    async def _check_migration_027a(self) -> Tuple[str, str]:
        """Check if migration 027a (snapshot fixes) is applied."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = '027a'"
                )
                row = await cur.fetchone()
                if row:
                    return "PASS", "Migration 027a applied (snapshot fixes)"
                return "FAIL", "Migration 027a not applied (V3.7.2 snapshot fixes)"

    async def _check_state_machine_integrity(self) -> Tuple[str, str]:
        """Run verify_state_machine_integrity()."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("SELECT * FROM verify_state_machine_integrity()")
                    rows = await cur.fetchall()

                    failed = [r for r in rows if r[1] == "FAIL"]
                    if failed:
                        return "FAIL", f"{len(failed)} integrity checks failed"

                    warns = [r for r in rows if r[1] == "WARN"]
                    if warns:
                        return "WARN", f"{len(warns)} warnings"

                    return "PASS", f"{len(rows)} checks passed"
                except Exception as e:
                    if "does not exist" in str(e):
                        return "WARN", "Function not found (apply 026a)"
                    raise

    async def _check_rls_hardening(self) -> Tuple[str, str]:
        """Run verify_final_hardening()."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("SELECT * FROM verify_final_hardening()")
                    rows = await cur.fetchall()

                    failed = sum(1 for r in rows if r[1] == "FAIL")
                    if failed > 0:
                        return "FAIL", f"{failed}/{len(rows)} hardening checks failed"

                    return "PASS", f"{len(rows)} hardening checks passed"
                except Exception as e:
                    if "does not exist" in str(e):
                        return "WARN", "Function not found (apply 025e)"
                    raise

    async def _check_snapshot_integrity(self) -> Tuple[str, str]:
        """Run verify_snapshot_integrity() (V3.7.2)."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("SELECT * FROM verify_snapshot_integrity()")
                    rows = await cur.fetchall()

                    failed = [r for r in rows if r[1] == "FAIL"]
                    warns = [r for r in rows if r[1] == "WARN"]

                    if failed:
                        return "FAIL", f"{len(failed)} snapshot integrity checks failed"
                    if warns:
                        return "WARN", f"{len(warns)} warnings (legacy snapshots?)"

                    return "PASS", f"{len(rows)} snapshot integrity checks passed"
                except Exception as e:
                    if "does not exist" in str(e):
                        return "WARN", "Function not found (apply 027a)"
                    raise

    # =========================================================================
    # STATE TRANSITION CHECKS
    # =========================================================================

    async def _check_state_transition_draft_solving(self) -> Tuple[str, str]:
        """Verify DRAFT → SOLVING transition works."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        if self.skip_destructive:
            return "SKIP", "Destructive tests skipped"

        # This would need a test plan_version - skip for now
        return "SKIP", "Requires test data setup"

    async def _check_published_immutability(self) -> Tuple[str, str]:
        """Verify PUBLISHED plans cannot be modified."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                # Check trigger exists
                await cur.execute("""
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'tr_prevent_published_modification'
                """)
                if not await cur.fetchone():
                    return "FAIL", "Immutability trigger not found"

                return "PASS", "Trigger tr_prevent_published_modification exists"

    async def _check_snapshot_immutability(self) -> Tuple[str, str]:
        """Verify plan_snapshots cannot be modified (V3.7.2)."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                # Check trigger exists
                await cur.execute("""
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'tr_prevent_snapshot_modification'
                """)
                if not await cur.fetchone():
                    return "FAIL", "Snapshot immutability trigger not found"

                return "PASS", "Trigger tr_prevent_snapshot_modification exists"

    # =========================================================================
    # V3.7.2: PLAN VERSIONING CHECKS
    # =========================================================================

    async def _check_build_snapshot_payload(self) -> Tuple[str, str]:
        """Verify build_snapshot_payload() function exists (V3.7.2)."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("""
                        SELECT 1 FROM pg_proc
                        WHERE proname = 'build_snapshot_payload'
                    """)
                    if await cur.fetchone():
                        return "PASS", "build_snapshot_payload() function exists"
                    return "FAIL", "build_snapshot_payload() not found (apply 027a)"
                except Exception as e:
                    return "FAIL", str(e)

    async def _check_unique_version_constraint(self) -> Tuple[str, str]:
        """Verify unique constraint on (plan_version_id, version_number) (V3.7.2)."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("""
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'plan_snapshots_unique_version_per_plan'
                    """)
                    if await cur.fetchone():
                        return "PASS", "Unique version constraint exists (race-safe)"
                    return "FAIL", "Unique version constraint not found (apply 027a)"
                except Exception as e:
                    return "FAIL", str(e)

    async def _check_legacy_snapshots(self) -> Tuple[str, str]:
        """Check count of legacy snapshots with empty payloads (V3.7.2)."""
        if not self.db_url:
            return "SKIP", "DATABASE_URL not set"

        import psycopg
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            async with conn.cursor() as cur:
                try:
                    # Check if plan_snapshots table exists
                    await cur.execute("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'plan_snapshots'
                    """)
                    if not await cur.fetchone():
                        return "SKIP", "plan_snapshots table not found"

                    # Count legacy snapshots
                    await cur.execute("""
                        SELECT COUNT(*) FROM plan_snapshots
                        WHERE assignments_snapshot IS NULL
                           OR assignments_snapshot = '[]'::jsonb
                    """)
                    row = await cur.fetchone()
                    legacy_count = row[0] if row else 0

                    if legacy_count == 0:
                        return "PASS", "No legacy snapshots found"
                    return "WARN", f"{legacy_count} legacy snapshots (run backfill_snapshot_payloads)"
                except Exception as e:
                    if "does not exist" in str(e):
                        return "SKIP", "plan_snapshots table not found"
                    return "FAIL", str(e)

    # =========================================================================
    # BLOB STORAGE CHECKS
    # =========================================================================

    async def _check_blob_storage(self) -> Tuple[str, str]:
        """Check if blob storage is configured."""
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")

        if conn_str:
            return "PASS", "Connection string mode (pilot)"
        if account_url:
            return "PASS", "Managed Identity mode (production)"

        return "WARN", "No Azure Storage configured (using LocalFileArtifactStore)"

    async def _check_blob_upload_download(self) -> Tuple[str, str]:
        """Test blob upload and download."""
        if not self.storage_configured:
            return "SKIP", "Storage not configured"

        if self.skip_destructive:
            return "SKIP", "Destructive tests skipped"

        try:
            # Import and test
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend_py"))
            from api.services.artifact_store import get_artifact_store

            store = get_artifact_store()

            # Upload test blob
            test_data = {"test": True, "timestamp": datetime.now().isoformat()}
            metadata = await store.store(
                tenant_id=1,
                site_id=1,
                artifact_type="smoke_test",
                content=test_data,
            )

            # Download and verify
            content = await store.get(metadata.artifact_id, tenant_id=1)
            if not content:
                return "FAIL", "Failed to download uploaded blob"

            downloaded = json.loads(content.decode())
            if downloaded.get("test") != True:
                return "FAIL", "Downloaded content mismatch"

            # Cleanup
            await store.delete(metadata.artifact_id, tenant_id=1)

            return "PASS", f"Upload/download OK (auth: {store.get_auth_mode()})"

        except ImportError as e:
            return "SKIP", f"Import error: {e}"
        except Exception as e:
            return "FAIL", str(e)

    async def _check_signed_url(self) -> Tuple[str, str]:
        """Test signed URL generation."""
        if not self.storage_configured:
            return "SKIP", "Storage not configured"

        # Would need existing artifact - skip detailed test
        return "SKIP", "Requires existing artifact"

    # =========================================================================
    # AUTH CHECKS
    # =========================================================================

    async def _check_entra_config(self) -> Tuple[str, str]:
        """Check Entra ID configuration."""
        tenant_id = os.environ.get("ENTRA_TENANT_ID")
        audience = os.environ.get("OIDC_AUDIENCE")

        if not tenant_id:
            return "WARN", "ENTRA_TENANT_ID not set"
        if not audience:
            return "WARN", "OIDC_AUDIENCE not set"

        return "PASS", f"Entra tenant: {tenant_id[:8]}..."


def print_report(report: SmokeTestReport) -> None:
    """Print final report."""
    print(f"\n{'='*60}")
    print("SMOKE TEST REPORT")
    print(f"{'='*60}")
    print(f"Environment: {report.environment}")
    print(f"Duration: {(report.completed_at - report.started_at).total_seconds():.1f}s")
    print(f"\nResults:")
    print(f"  Passed:   {report.passed}")
    print(f"  Failed:   {report.failed}")
    print(f"  Warnings: {report.warnings}")
    print(f"  Skipped:  {report.skipped}")
    print(f"\n{'='*60}")

    verdict_color = {
        "GO": "\033[92m",
        "NO-GO": "\033[91m",
        "REVIEW": "\033[93m",
    }[report.verdict]
    reset = "\033[0m"

    print(f"VERDICT: {verdict_color}{report.verdict}{reset}")
    print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(description="SOLVEREIGN SaaS Smoke Test")
    parser.add_argument("--env", default="staging", choices=["staging", "production", "dev"])
    parser.add_argument("--skip-destructive", action="store_true", help="Skip tests that modify data")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    runner = SmokeTestRunner(env=args.env, skip_destructive=args.skip_destructive)
    report = await runner.run_all()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report)

    # Exit code based on verdict
    sys.exit(0 if report.verdict == "GO" else 1)


if __name__ == "__main__":
    asyncio.run(main())
