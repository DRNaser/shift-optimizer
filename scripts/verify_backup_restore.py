#!/usr/bin/env python3
"""
SOLVEREIGN Backup Restore Verification Script
==============================================

Tests that a backup can be successfully restored and the app can connect.

Usage:
    # Test latest backup from S3
    python scripts/verify_backup_restore.py --bucket solvereign-backups-prod

    # Test specific backup file
    python scripts/verify_backup_restore.py --file ./backup.dump

    # Dry run (don't actually restore)
    python scripts/verify_backup_restore.py --bucket solvereign-backups-prod --dry-run

Requirements:
    - PostgreSQL client tools (pg_restore, createdb, dropdb)
    - boto3 (for S3 access)
    - psycopg (for verification queries)

SAFETY:
    This script creates and drops databases. Production safety checks are enforced:
    - Requires SOLVEREIGN_ENV=staging|development|test|local
    - OR explicit --i-know-what-im-doing flag (with 5-second warning)
    - Blocks execution if DATABASE_URL points to production hosts
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urlparse


# =============================================================================
# PRODUCTION SAFETY GUARD
# =============================================================================

# Allowed environment values (case-insensitive)
SAFE_ENVIRONMENTS = {"staging", "development", "test", "local", "dev"}

# Keywords in URL hostname that indicate production
PROD_HOSTNAME_KEYWORDS = {"prod", "production", "live", "primary", "master"}

# Cloud provider patterns that need extra scrutiny
CLOUD_PROVIDERS = {
    "rds.amazonaws.com": "AWS RDS",
    "database.azure.com": "Azure Database",
    "cloudsql": "Google Cloud SQL",
    "neon.tech": "Neon",
    "supabase.co": "Supabase",
}


def parse_database_host(db_url: str) -> str:
    """Extract hostname from DATABASE_URL."""
    if not db_url:
        return ""
    try:
        parsed = urlparse(db_url)
        return parsed.hostname or ""
    except Exception:
        return ""


def is_production_host(hostname: str) -> tuple[bool, str]:
    """
    Check if hostname appears to be a production database.

    Returns (is_prod, reason).
    """
    if not hostname:
        return False, ""

    hostname_lower = hostname.lower()

    # Check for production keywords in hostname
    for keyword in PROD_HOSTNAME_KEYWORDS:
        if keyword in hostname_lower:
            # But allow if "staging" is also present
            if "staging" in hostname_lower or "dev" in hostname_lower:
                continue
            return True, f"hostname contains '{keyword}'"

    # Check for cloud providers without staging/dev indicators
    for pattern, provider in CLOUD_PROVIDERS.items():
        if pattern in hostname_lower:
            if "staging" not in hostname_lower and "dev" not in hostname_lower and "test" not in hostname_lower:
                return True, f"{provider} host without staging/dev indicator"

    return False, ""


def check_environment_safety() -> tuple[bool, str]:
    """
    Verify we're not running against production.

    Returns (is_safe, reason).

    Safety is confirmed if:
    1. SOLVEREIGN_ENV is in SAFE_ENVIRONMENTS, OR
    2. DATABASE_URL hostname is clearly local/staging

    Safety is denied if:
    1. SOLVEREIGN_ENV is "production", OR
    2. DATABASE_URL points to production-like host
    """
    env = os.getenv("SOLVEREIGN_ENV", "").lower().strip()
    db_url = os.getenv("DATABASE_URL", "")
    hostname = parse_database_host(db_url)

    # Explicit environment check
    if env in SAFE_ENVIRONMENTS:
        return True, f"SOLVEREIGN_ENV={env}"

    if env == "production":
        return False, "SOLVEREIGN_ENV=production"

    # Check DATABASE_URL hostname
    is_prod, prod_reason = is_production_host(hostname)
    if is_prod:
        return False, f"DATABASE_URL {prod_reason}"

    # Local hosts are safe
    if hostname in ("localhost", "127.0.0.1", "::1", ""):
        return True, "localhost database"

    # If we can't determine, be cautious but allow with warning
    if not env:
        return True, "SOLVEREIGN_ENV not set (assuming non-production)"

    return False, f"unknown environment: {env}"

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


def log(msg: str, level: str = "INFO"):
    """Print timestamped log message."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def get_latest_backup(bucket: str, prefix: str = "postgresql/") -> str:
    """Get the most recent backup file from S3."""
    if not BOTO3_AVAILABLE:
        raise ImportError("boto3 not installed")

    s3 = boto3.client("s3")
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

    if "Contents" not in response:
        raise ValueError(f"No backups found in s3://{bucket}/{prefix}")

    # Sort by LastModified descending
    objects = sorted(response["Contents"], key=lambda x: x["LastModified"], reverse=True)
    latest = objects[0]["Key"]

    log(f"Latest backup: s3://{bucket}/{latest}")
    return latest


def download_backup(bucket: str, key: str, local_path: str) -> None:
    """Download backup from S3."""
    if not BOTO3_AVAILABLE:
        raise ImportError("boto3 not installed")

    s3 = boto3.client("s3")
    log(f"Downloading s3://{bucket}/{key} to {local_path}")
    s3.download_file(bucket, key, local_path)
    log(f"Downloaded {os.path.getsize(local_path) / 1024 / 1024:.2f} MB")


def create_test_db(db_name: str) -> bool:
    """Create a test database."""
    log(f"Creating test database: {db_name}")
    result = subprocess.run(
        ["createdb", db_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"Failed to create database: {result.stderr}", "ERROR")
        return False
    return True


def restore_backup(backup_path: str, db_name: str) -> bool:
    """
    Restore backup to test database.

    Supports both custom format (.dump) and plain SQL (.sql/.sql.gz).
    Uses --exit-on-error for pg_restore, ON_ERROR_STOP for psql.
    """
    log(f"Restoring backup to {db_name}")

    # Detect format by extension
    is_custom_format = backup_path.endswith(".dump") or backup_path.endswith(".backup")

    if is_custom_format:
        # Custom format: use pg_restore
        result = subprocess.run(
            [
                "pg_restore",
                "-d", db_name,
                "--no-owner",
                "--no-acl",
                "--exit-on-error",  # Stop on first error
                "--jobs=4",
                backup_path,
            ],
            capture_output=True,
            text=True,
        )
    else:
        # Plain SQL format: use psql with ON_ERROR_STOP
        # Handle gzipped files
        if backup_path.endswith(".gz"):
            import gzip
            with gzip.open(backup_path, "rt") as f:
                sql_content = f.read()
            result = subprocess.run(
                [
                    "psql",
                    "-d", db_name,
                    "-v", "ON_ERROR_STOP=1",
                    "--single-transaction",
                ],
                input=sql_content,
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                [
                    "psql",
                    "-d", db_name,
                    "-v", "ON_ERROR_STOP=1",
                    "--single-transaction",
                    "-f", backup_path,
                ],
                capture_output=True,
                text=True,
            )

        # For non-custom format, returncode 0 is success
        if result.returncode != 0:
            log(f"Restore failed: {result.stderr}", "ERROR")
            return False
        return True

    # pg_restore specific handling (for custom format)
    # pg_restore may return warnings (exit code 1) but still succeed
    if result.returncode > 1:
        log(f"Restore failed: {result.stderr}", "ERROR")
        return False

    if result.stderr:
        log(f"Restore warnings: {result.stderr[:500]}", "WARN")

    return True


def verify_restore(db_name: str) -> dict:
    """Run verification queries against restored database."""
    log("Running verification queries")

    results = {}
    db_url = f"postgresql://localhost/{db_name}"

    try:
        import psycopg
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Check tenant count
                cur.execute("SELECT COUNT(*) FROM tenants")
                results["tenants"] = cur.fetchone()[0]

                # Check user count
                cur.execute("SELECT COUNT(*) FROM auth.users")
                results["users"] = cur.fetchone()[0]

                # Check RLS hardening
                cur.execute("SELECT * FROM verify_final_hardening()")
                hardening = cur.fetchall()
                results["hardening_pass"] = all(row[1] == "PASS" for row in hardening)
                results["hardening_checks"] = len(hardening)

                # Check billing schema (if exists)
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'billing'
                    )
                """)
                results["billing_schema"] = cur.fetchone()[0]

                # Check latest forecast
                cur.execute("""
                    SELECT MAX(created_at) FROM forecast_versions
                """)
                latest = cur.fetchone()[0]
                results["latest_forecast"] = str(latest) if latest else "none"

    except Exception as e:
        log(f"Verification failed: {e}", "ERROR")
        results["error"] = str(e)

    return results


def drop_test_db(db_name: str) -> None:
    """Drop the test database."""
    log(f"Dropping test database: {db_name}")
    subprocess.run(
        ["dropdb", "--if-exists", db_name],
        capture_output=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Verify backup restore",
        epilog="SAFETY: Set SOLVEREIGN_ENV=staging to bypass production checks.",
    )
    parser.add_argument("--bucket", help="S3 bucket name")
    parser.add_argument("--prefix", default="postgresql/", help="S3 prefix")
    parser.add_argument("--file", help="Local backup file (instead of S3)")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually restore")
    parser.add_argument("--keep-db", action="store_true", help="Don't drop test DB after")
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Override production safety check (DANGEROUS - 5s warning)",
    )

    args = parser.parse_args()

    # ==========================================================================
    # PRODUCTION SAFETY CHECK
    # ==========================================================================
    is_safe, reason = check_environment_safety()

    if not is_safe and not args.i_know_what_im_doing:
        log("=" * 60, "ERROR")
        log("PRODUCTION SAFETY CHECK FAILED", "ERROR")
        log("=" * 60, "ERROR")
        log("This script creates/drops databases and must not run against production.", "ERROR")
        log("", "ERROR")
        log(f"Reason: {reason}", "ERROR")
        log("", "ERROR")
        log("To fix, either:", "ERROR")
        log("  1. Set SOLVEREIGN_ENV=staging (or development/test/local)", "ERROR")
        log("  2. Use --i-know-what-im-doing flag (DANGEROUS)", "ERROR")
        log("", "ERROR")
        log(f"Current SOLVEREIGN_ENV: {os.getenv('SOLVEREIGN_ENV', '<not set>')}", "ERROR")
        hostname = parse_database_host(os.getenv("DATABASE_URL", ""))
        log(f"DATABASE_URL host: {hostname or '<not set>'}", "ERROR")
        return 3

    if args.i_know_what_im_doing:
        log("=" * 60, "WARN")
        log("PRODUCTION SAFETY OVERRIDE ACTIVE", "WARN")
        log("=" * 60, "WARN")
        log(f"Environment: {os.getenv('SOLVEREIGN_ENV', '<not set>')}", "WARN")
        log(f"Database host: {parse_database_host(os.getenv('DATABASE_URL', ''))}", "WARN")
        log("", "WARN")
        log("You have 5 seconds to Ctrl+C if this is a mistake...", "WARN")
        for i in range(5, 0, -1):
            log(f"  {i}...", "WARN")
            time.sleep(1)
        log("Proceeding with override.", "WARN")
    elif not is_safe:
        # This shouldn't happen due to earlier check, but be safe
        return 3
    else:
        log(f"Safety check passed: {reason}", "INFO")

    if not args.bucket and not args.file:
        parser.error("Either --bucket or --file required")

    # Generate unique test DB name
    test_db = f"solvereign_restore_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    log("=" * 60)
    log("SOLVEREIGN BACKUP RESTORE VERIFICATION")
    log("=" * 60)

    try:
        # Get backup file
        if args.file:
            backup_path = args.file
            log(f"Using local file: {backup_path}")
        else:
            # Download from S3
            latest_key = get_latest_backup(args.bucket, args.prefix)

            if args.dry_run:
                log(f"DRY RUN: Would restore s3://{args.bucket}/{latest_key}")
                return 0

            with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as f:
                backup_path = f.name

            download_backup(args.bucket, latest_key, backup_path)

        # Verify file exists
        if not os.path.exists(backup_path):
            log(f"Backup file not found: {backup_path}", "ERROR")
            return 1

        # Create test DB
        if not create_test_db(test_db):
            return 1

        # Restore
        if not restore_backup(backup_path, test_db):
            drop_test_db(test_db)
            return 1

        # Verify
        results = verify_restore(test_db)

        log("=" * 60)
        log("VERIFICATION RESULTS")
        log("=" * 60)

        for key, value in results.items():
            log(f"  {key}: {value}")

        # Determine pass/fail
        passed = (
            results.get("tenants", 0) > 0 and
            results.get("users", 0) > 0 and
            results.get("hardening_pass", False) and
            "error" not in results
        )

        log("=" * 60)
        if passed:
            log("RESULT: PASS - Restore verification successful", "INFO")
        else:
            log("RESULT: FAIL - Restore verification failed", "ERROR")
        log("=" * 60)

        return 0 if passed else 1

    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        return 2

    finally:
        # Cleanup
        if not args.keep_db and not args.dry_run:
            drop_test_db(test_db)

        # Remove temp file
        if args.bucket and backup_path and os.path.exists(backup_path):
            os.unlink(backup_path)


if __name__ == "__main__":
    sys.exit(main())
