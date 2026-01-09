#!/usr/bin/env python3
"""
SOLVEREIGN V3.7 - Production Preflight Check
=============================================

Pre-cutover validation for production deployment.
Checks database, environment, migrations, and security state.

Exit Codes:
    0 = PASS - All checks passed, safe to proceed
    1 = WARN - Non-critical issues, proceed with caution
    2 = FAIL - Critical issues, do NOT proceed

Usage:
    python scripts/prod_preflight_check.py --db-url "$DATABASE_URL" --env production
    python scripts/prod_preflight_check.py --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# CHECK DEFINITIONS
# =============================================================================

class CheckResult:
    """Result of a single preflight check."""

    def __init__(self, name: str, status: str, message: str, details: Dict = None):
        self.name = name
        self.status = status  # PASS, WARN, FAIL
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details
        }


class PreflightChecker:
    """Runs all preflight checks."""

    def __init__(self, db_url: str = None, env: str = "production", dry_run: bool = False):
        self.db_url = db_url
        self.env = env
        self.dry_run = dry_run
        self.results: List[CheckResult] = []

    def run_all_checks(self) -> Tuple[str, List[CheckResult]]:
        """Run all preflight checks and return overall verdict."""
        print("=" * 70)
        print("SOLVEREIGN PRODUCTION PREFLIGHT CHECK")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Environment: {self.env}")
        print(f"Dry Run: {self.dry_run}")
        print()

        # Run checks
        self._check_environment_vars()
        self._check_database_connection()
        self._check_migrations_applied()
        self._check_rls_enabled()
        self._check_security_roles()
        self._check_writes_disabled()
        self._check_backup_exists()
        self._check_rc_tag()
        self._check_state_files()
        self._check_no_active_incidents()

        # Calculate verdict
        fail_count = sum(1 for r in self.results if r.status == "FAIL")
        warn_count = sum(1 for r in self.results if r.status == "WARN")
        pass_count = sum(1 for r in self.results if r.status == "PASS")

        if fail_count > 0:
            verdict = "FAIL"
        elif warn_count > 0:
            verdict = "WARN"
        else:
            verdict = "PASS"

        return verdict, self.results

    def _add_result(self, name: str, status: str, message: str, details: Dict = None):
        """Add a check result."""
        result = CheckResult(name, status, message, details)
        self.results.append(result)

        # Print result
        icon = {"PASS": "[OK]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
        print(f"  {icon} {name}: {message}")

    # =========================================================================
    # INDIVIDUAL CHECKS
    # =========================================================================

    def _check_environment_vars(self):
        """Check required environment variables are set."""
        print("\n[1/10] Checking environment variables...")

        required_vars = [
            "SOLVEREIGN_DB_URL",
            "SOLVEREIGN_SESSION_SECRET",
            "SOLVEREIGN_ENV"
        ]

        optional_vars = [
            "SOLVEREIGN_HMAC_SECRET",
            "SOLVEREIGN_LOG_LEVEL"
        ]

        missing_required = []
        missing_optional = []

        for var in required_vars:
            if not os.environ.get(var) and not self.db_url:
                missing_required.append(var)

        for var in optional_vars:
            if not os.environ.get(var):
                missing_optional.append(var)

        if missing_required and not self.dry_run:
            self._add_result(
                "env_vars_required",
                "FAIL",
                f"Missing required vars: {missing_required}",
                {"missing": missing_required}
            )
        elif missing_optional:
            self._add_result(
                "env_vars_optional",
                "WARN",
                f"Missing optional vars: {missing_optional}",
                {"missing": missing_optional}
            )
        else:
            self._add_result(
                "env_vars",
                "PASS",
                "All required environment variables set"
            )

    def _check_database_connection(self):
        """Check database is accessible."""
        print("\n[2/10] Checking database connection...")

        if self.dry_run:
            self._add_result("db_connection", "PASS", "Dry run - skipped")
            return

        if not self.db_url:
            self._add_result("db_connection", "FAIL", "No database URL provided")
            return

        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    version = cur.fetchone()[0]

            self._add_result(
                "db_connection",
                "PASS",
                "Database accessible",
                {"version": version[:50]}
            )

        except Exception as e:
            self._add_result(
                "db_connection",
                "FAIL",
                f"Database connection failed: {str(e)[:100]}"
            )

    def _check_migrations_applied(self):
        """Check required migrations are applied."""
        print("\n[3/10] Checking migrations...")

        if self.dry_run:
            self._add_result("migrations", "PASS", "Dry run - skipped")
            return

        if not self.db_url:
            self._add_result("migrations", "WARN", "No database URL - skipped")
            return

        required_migrations = ["025", "025a", "025b", "025c", "025d", "025e", "025f"]

        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT version FROM schema_migrations
                        WHERE version = ANY(%s)
                    """, (required_migrations,))
                    applied = [row[0] for row in cur.fetchall()]

            missing = set(required_migrations) - set(applied)

            if missing:
                self._add_result(
                    "migrations",
                    "FAIL",
                    f"Missing migrations: {sorted(missing)}",
                    {"missing": list(missing), "applied": applied}
                )
            else:
                self._add_result(
                    "migrations",
                    "PASS",
                    f"All {len(required_migrations)} security migrations applied"
                )

        except Exception as e:
            self._add_result(
                "migrations",
                "FAIL",
                f"Migration check failed: {str(e)[:100]}"
            )

    def _check_rls_enabled(self):
        """Check RLS is enabled on critical tables."""
        print("\n[4/10] Checking RLS enabled...")

        if self.dry_run:
            self._add_result("rls_enabled", "PASS", "Dry run - skipped")
            return

        if not self.db_url:
            self._add_result("rls_enabled", "WARN", "No database URL - skipped")
            return

        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT relname, relrowsecurity, relforcerowsecurity
                        FROM pg_class
                        WHERE relname IN ('tenants', 'idempotency_keys')
                          AND relkind = 'r'
                    """)
                    tables = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

            issues = []
            for table in ["tenants", "idempotency_keys"]:
                if table not in tables:
                    issues.append(f"{table}: not found")
                elif not tables[table][0]:
                    issues.append(f"{table}: RLS not enabled")
                elif not tables[table][1]:
                    issues.append(f"{table}: FORCE RLS not set")

            if issues:
                self._add_result(
                    "rls_enabled",
                    "FAIL",
                    f"RLS issues: {issues}",
                    {"issues": issues}
                )
            else:
                self._add_result(
                    "rls_enabled",
                    "PASS",
                    "RLS enabled and forced on all critical tables"
                )

        except Exception as e:
            self._add_result(
                "rls_enabled",
                "FAIL",
                f"RLS check failed: {str(e)[:100]}"
            )

    def _check_security_roles(self):
        """Check security roles exist and have correct privileges."""
        print("\n[5/10] Checking security roles...")

        if self.dry_run:
            self._add_result("security_roles", "PASS", "Dry run - skipped")
            return

        if not self.db_url:
            self._add_result("security_roles", "WARN", "No database URL - skipped")
            return

        required_roles = ["solvereign_api", "solvereign_platform", "solvereign_definer"]

        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT rolname FROM pg_roles
                        WHERE rolname = ANY(%s)
                    """, (required_roles,))
                    existing = [row[0] for row in cur.fetchall()]

            missing = set(required_roles) - set(existing)

            if missing:
                self._add_result(
                    "security_roles",
                    "FAIL",
                    f"Missing roles: {sorted(missing)}",
                    {"missing": list(missing)}
                )
            else:
                self._add_result(
                    "security_roles",
                    "PASS",
                    f"All {len(required_roles)} security roles exist"
                )

        except Exception as e:
            self._add_result(
                "security_roles",
                "FAIL",
                f"Role check failed: {str(e)[:100]}"
            )

    def _check_writes_disabled(self):
        """Check writes are disabled during cutover."""
        print("\n[6/10] Checking writes disabled...")

        if self.dry_run:
            self._add_result("writes_disabled", "PASS", "Dry run - skipped")
            return

        # Check environment variable
        writes_disabled = os.environ.get("SOLVEREIGN_PLATFORM_WRITES_DISABLED", "").lower()

        if writes_disabled == "true":
            self._add_result(
                "writes_disabled",
                "PASS",
                "Writes are disabled (safe for migration)"
            )
        else:
            self._add_result(
                "writes_disabled",
                "WARN",
                "Writes NOT disabled - recommend disabling during cutover"
            )

    def _check_backup_exists(self):
        """Check recent backup exists."""
        print("\n[7/10] Checking backup exists...")

        backup_dir = PROJECT_ROOT / "backups"

        if not backup_dir.exists():
            self._add_result(
                "backup_exists",
                "WARN",
                "No backups directory found"
            )
            return

        # Find most recent backup
        backups = list(backup_dir.glob("solvereign_pre_cutover_*.dump"))

        if not backups:
            self._add_result(
                "backup_exists",
                "WARN",
                "No pre-cutover backup found - recommend creating one"
            )
        else:
            latest = max(backups, key=lambda p: p.stat().st_mtime)
            age_hours = (datetime.now().timestamp() - latest.stat().st_mtime) / 3600

            if age_hours > 24:
                self._add_result(
                    "backup_exists",
                    "WARN",
                    f"Backup is {age_hours:.1f}h old - recommend fresh backup",
                    {"backup": str(latest.name)}
                )
            else:
                self._add_result(
                    "backup_exists",
                    "PASS",
                    f"Recent backup exists ({age_hours:.1f}h old)",
                    {"backup": str(latest.name)}
                )

    def _check_rc_tag(self):
        """Check RC tag exists and matches HEAD."""
        print("\n[8/10] Checking RC tag...")

        import subprocess

        try:
            # Get current HEAD
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                text=True
            ).strip()

            # Get tags pointing to HEAD
            tags = subprocess.check_output(
                ["git", "tag", "--points-at", "HEAD"],
                cwd=PROJECT_ROOT,
                text=True
            ).strip().split("\n")

            rc_tags = [t for t in tags if "-rc" in t.lower()]

            if rc_tags:
                self._add_result(
                    "rc_tag",
                    "PASS",
                    f"RC tag(s) found: {rc_tags}",
                    {"tags": rc_tags, "head": head[:8]}
                )
            else:
                self._add_result(
                    "rc_tag",
                    "WARN",
                    "No RC tag at HEAD - recommend tagging before cutover",
                    {"head": head[:8]}
                )

        except Exception as e:
            self._add_result(
                "rc_tag",
                "WARN",
                f"Could not check git tags: {str(e)[:50]}"
            )

    def _check_state_files(self):
        """Check required state files exist."""
        print("\n[9/10] Checking state files...")

        required_files = [
            ".claude/state/last-known-good.json",
            ".claude/state/wien_baseline.json"
        ]

        missing = []
        for file_path in required_files:
            full_path = PROJECT_ROOT / file_path
            if not full_path.exists():
                missing.append(file_path)

        if missing:
            self._add_result(
                "state_files",
                "WARN",
                f"Missing state files: {missing}",
                {"missing": missing}
            )
        else:
            self._add_result(
                "state_files",
                "PASS",
                f"All {len(required_files)} required state files exist"
            )

    def _check_no_active_incidents(self):
        """Check no active S0/S1 incidents."""
        print("\n[10/10] Checking for active incidents...")

        incidents_file = PROJECT_ROOT / ".claude/state/active-incidents.json"

        if not incidents_file.exists():
            self._add_result(
                "no_active_incidents",
                "PASS",
                "No active incidents file (OK)"
            )
            return

        try:
            with open(incidents_file) as f:
                incidents = json.load(f)

            active = [
                inc for inc in incidents.get("incidents", [])
                if inc.get("status") in ["new", "active", "investigating"]
                and inc.get("severity") in ["S0", "S1"]
            ]

            if active:
                self._add_result(
                    "no_active_incidents",
                    "FAIL",
                    f"{len(active)} active S0/S1 incident(s) - resolve before cutover",
                    {"incidents": [inc.get("id") for inc in active]}
                )
            else:
                self._add_result(
                    "no_active_incidents",
                    "PASS",
                    "No active S0/S1 incidents"
                )

        except Exception as e:
            self._add_result(
                "no_active_incidents",
                "WARN",
                f"Could not check incidents: {str(e)[:50]}"
            )


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Production Preflight Check"
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get("SOLVEREIGN_DB_URL"),
        help="Database connection URL"
    )
    parser.add_argument(
        "--env",
        type=str,
        default="production",
        choices=["staging", "production"],
        help="Target environment"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without database checks"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file path"
    )

    args = parser.parse_args()

    # Run checks
    checker = PreflightChecker(
        db_url=args.db_url,
        env=args.env,
        dry_run=args.dry_run
    )

    verdict, results = checker.run_all_checks()

    # Print summary
    print()
    print("=" * 70)
    print("PREFLIGHT SUMMARY")
    print("=" * 70)

    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    print(f"Total Checks: {len(results)}")
    print(f"  PASS: {pass_count}")
    print(f"  WARN: {warn_count}")
    print(f"  FAIL: {fail_count}")
    print()
    print(f"VERDICT: {verdict}")

    if verdict == "PASS":
        print("Safe to proceed with production cutover.")
    elif verdict == "WARN":
        print("Proceed with caution - review warnings before cutover.")
    else:
        print("DO NOT proceed - resolve failures before cutover.")

    print("=" * 70)

    # Write output file if requested
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "environment": args.env,
            "dry_run": args.dry_run,
            "verdict": verdict,
            "summary": {
                "total": len(results),
                "pass": pass_count,
                "warn": warn_count,
                "fail": fail_count
            },
            "checks": [r.to_dict() for r in results]
        }

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2)

        print(f"\nOutput written to: {args.output}")

    # Exit with appropriate code
    if verdict == "FAIL":
        sys.exit(2)
    elif verdict == "WARN":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
