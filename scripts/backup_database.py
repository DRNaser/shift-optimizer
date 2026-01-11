#!/usr/bin/env python3
"""
SOLVEREIGN Database Backup Script (P0.2)
========================================

Automated PostgreSQL backup to S3-compatible storage.

Features:
- pg_dump with gzip compression
- S3 upload with server-side encryption (SSE-S3)
- Retention cleanup (configurable days)
- Slack/webhook notification on failure
- Prometheus metrics (backup_last_success_timestamp)

Environment Variables:
    DATABASE_URL          PostgreSQL connection string
    BACKUP_S3_BUCKET      S3 bucket name
    BACKUP_S3_PREFIX      Object prefix (default: backups/)
    BACKUP_RETENTION_DAYS Days to keep backups (default: 30)
    AWS_ACCESS_KEY_ID     AWS credentials
    AWS_SECRET_ACCESS_KEY AWS credentials
    AWS_DEFAULT_REGION    AWS region (default: eu-central-1)
    BACKUP_WEBHOOK_URL    Webhook for failure notifications (optional)

Usage:
    # Run backup
    python scripts/backup_database.py

    # Dry run (no upload)
    python scripts/backup_database.py --dry-run

    # Restore from backup
    python scripts/backup_database.py --restore 20260111_020000.sql.gz
"""

import os
import sys
import gzip
import subprocess
import tempfile
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Optional boto3 import
try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not installed - S3 uploads disabled")


# =============================================================================
# CONFIGURATION
# =============================================================================

class BackupConfig:
    """Backup configuration from environment."""

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.s3_bucket = os.getenv("BACKUP_S3_BUCKET")
        self.s3_prefix = os.getenv("BACKUP_S3_PREFIX", "backups/")
        self.retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
        self.aws_region = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
        self.webhook_url = os.getenv("BACKUP_WEBHOOK_URL")
        self.environment = os.getenv("SOLVEREIGN_ENVIRONMENT", "development")

    def validate(self) -> list[str]:
        """Validate configuration. Returns list of errors."""
        errors = []
        if not self.database_url:
            errors.append("DATABASE_URL not set")
        if not self.s3_bucket and BOTO3_AVAILABLE:
            errors.append("BACKUP_S3_BUCKET not set")
        return errors


# =============================================================================
# BACKUP FUNCTIONS
# =============================================================================

def create_backup(config: BackupConfig, output_path: Path) -> bool:
    """
    Create PostgreSQL backup using pg_dump.

    Args:
        config: Backup configuration
        output_path: Path for compressed backup file

    Returns:
        True if backup successful
    """
    logger.info(f"Creating database backup...")

    try:
        # Run pg_dump and pipe to gzip
        # Note: pg_dump reads PGPASSWORD from environment or .pgpass
        cmd = [
            "pg_dump",
            "--format=custom",  # Custom format supports parallel restore
            "--compress=6",     # Medium compression
            "--no-owner",       # Don't include ownership
            "--no-acl",         # Don't include permissions
            config.database_url
        ]

        with open(output_path, "wb") as f:
            result = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=3600,  # 1 hour timeout
            )

        if result.returncode != 0:
            logger.error(f"pg_dump failed: {result.stderr.decode()}")
            return False

        # Verify file was created and has content
        if not output_path.exists() or output_path.stat().st_size < 100:
            logger.error("Backup file is empty or missing")
            return False

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Backup created: {output_path.name} ({size_mb:.2f} MB)")
        return True

    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 1 hour")
        return False
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        return False


def upload_to_s3(config: BackupConfig, local_path: Path, s3_key: str) -> bool:
    """
    Upload backup file to S3 with server-side encryption.

    Args:
        config: Backup configuration
        local_path: Local backup file path
        s3_key: S3 object key

    Returns:
        True if upload successful
    """
    if not BOTO3_AVAILABLE:
        logger.warning("boto3 not available - skipping S3 upload")
        return False

    logger.info(f"Uploading to s3://{config.s3_bucket}/{s3_key}")

    try:
        s3 = boto3.client("s3", region_name=config.aws_region)

        # Upload with SSE-S3 encryption
        s3.upload_file(
            str(local_path),
            config.s3_bucket,
            s3_key,
            ExtraArgs={
                "ServerSideEncryption": "AES256",
                "StorageClass": "STANDARD_IA",  # Infrequent access for cost savings
                "Metadata": {
                    "backup-type": "postgresql",
                    "environment": config.environment,
                    "created-at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )

        logger.info(f"Upload complete: s3://{config.s3_bucket}/{s3_key}")
        return True

    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return False


def cleanup_old_backups(config: BackupConfig) -> int:
    """
    Delete backups older than retention period.

    Args:
        config: Backup configuration

    Returns:
        Number of objects deleted
    """
    if not BOTO3_AVAILABLE:
        return 0

    logger.info(f"Cleaning up backups older than {config.retention_days} days...")

    try:
        s3 = boto3.client("s3", region_name=config.aws_region)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=config.retention_days)

        # List objects with prefix
        paginator = s3.get_paginator("list_objects_v2")
        deleted_count = 0

        for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=config.s3_prefix):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < cutoff_date:
                    s3.delete_object(Bucket=config.s3_bucket, Key=obj["Key"])
                    logger.info(f"Deleted old backup: {obj['Key']}")
                    deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backups")
        return deleted_count

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return 0


def send_notification(config: BackupConfig, success: bool, details: str) -> None:
    """
    Send webhook notification on backup completion/failure.

    Args:
        config: Backup configuration
        success: True if backup succeeded
        details: Additional details message
    """
    if not config.webhook_url:
        return

    try:
        payload = {
            "event": "backup_completed" if success else "backup_failed",
            "environment": config.environment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details,
            "status": "success" if success else "failure",
        }

        # Slack-compatible format
        if "slack" in config.webhook_url.lower():
            emoji = ":white_check_mark:" if success else ":x:"
            payload = {
                "text": f"{emoji} *SOLVEREIGN Backup* ({config.environment}): {'Success' if success else 'FAILED'}",
                "attachments": [{
                    "color": "good" if success else "danger",
                    "fields": [
                        {"title": "Details", "value": details, "short": False},
                        {"title": "Timestamp", "value": datetime.now(timezone.utc).isoformat(), "short": True},
                    ]
                }]
            }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            config.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Notification sent")

    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


def write_prometheus_metrics(success: bool, duration_seconds: float) -> None:
    """
    Write Prometheus metrics for backup monitoring.

    Creates a file that can be read by node_exporter textfile collector.
    """
    metrics_path = Path("/var/lib/prometheus/node-exporter/backup.prom")

    try:
        metrics_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        metrics = [
            f"# HELP solvereign_backup_last_run_timestamp Last backup run timestamp",
            f"# TYPE solvereign_backup_last_run_timestamp gauge",
            f"solvereign_backup_last_run_timestamp {timestamp}",
            f"# HELP solvereign_backup_last_success Success status of last backup (1=success, 0=failure)",
            f"# TYPE solvereign_backup_last_success gauge",
            f"solvereign_backup_last_success {1 if success else 0}",
            f"# HELP solvereign_backup_duration_seconds Duration of last backup in seconds",
            f"# TYPE solvereign_backup_duration_seconds gauge",
            f"solvereign_backup_duration_seconds {duration_seconds:.2f}",
        ]

        if success:
            metrics.extend([
                f"# HELP solvereign_backup_last_success_timestamp Timestamp of last successful backup",
                f"# TYPE solvereign_backup_last_success_timestamp gauge",
                f"solvereign_backup_last_success_timestamp {timestamp}",
            ])

        metrics_path.write_text("\n".join(metrics) + "\n")
        logger.info(f"Prometheus metrics written to {metrics_path}")

    except Exception as e:
        logger.warning(f"Failed to write Prometheus metrics: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main(dry_run: bool = False, restore_file: Optional[str] = None) -> int:
    """
    Main backup entry point.

    Args:
        dry_run: If True, create backup but don't upload
        restore_file: If set, restore from this S3 key instead of backing up

    Returns:
        Exit code (0=success, 1=failure)
    """
    start_time = datetime.now(timezone.utc)
    config = BackupConfig()

    # Validate configuration
    errors = config.validate()
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        return 1

    if restore_file:
        logger.info(f"Restore not implemented yet. Use: pg_restore -d $DATABASE_URL {restore_file}")
        return 1

    # Generate backup filename
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"solvereign_{config.environment}_{timestamp}.dump"
    s3_key = f"{config.s3_prefix}{backup_filename}"

    success = False
    details = ""

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / backup_filename

            # Create backup
            if not create_backup(config, local_path):
                details = "pg_dump failed"
                return 1

            size_mb = local_path.stat().st_size / (1024 * 1024)
            details = f"Backup size: {size_mb:.2f} MB"

            if dry_run:
                logger.info(f"Dry run - skipping S3 upload. File: {local_path}")
                success = True
            else:
                # Upload to S3
                if not upload_to_s3(config, local_path, s3_key):
                    details += " | S3 upload failed"
                    return 1

                details += f" | Uploaded to s3://{config.s3_bucket}/{s3_key}"

                # Cleanup old backups
                deleted = cleanup_old_backups(config)
                if deleted > 0:
                    details += f" | Cleaned up {deleted} old backups"

                success = True

    except Exception as e:
        logger.exception(f"Backup failed: {e}")
        details = f"Exception: {str(e)}"
        success = False

    finally:
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        # Write metrics
        write_prometheus_metrics(success, duration)

        # Send notification
        send_notification(config, success, details)

        logger.info(f"Backup {'completed' if success else 'failed'} in {duration:.1f}s")

    return 0 if success else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SOLVEREIGN Database Backup")
    parser.add_argument("--dry-run", action="store_true", help="Create backup but don't upload")
    parser.add_argument("--restore", type=str, help="Restore from S3 backup file")
    args = parser.parse_args()

    sys.exit(main(dry_run=args.dry_run, restore_file=args.restore))
