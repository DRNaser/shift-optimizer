#!/bin/bash
# ==============================================================================
# SOLVEREIGN Database Backup Script (Linux/macOS)
# ==============================================================================
#
# Usage:
#   ./scripts/backup.sh
#   ./scripts/backup.sh /var/backups/solvereign
#   CONTAINER_NAME=solvereign-prod-db ./scripts/backup.sh
#
# Cron schedule (daily at 03:00 UTC):
#   0 3 * * * /opt/solvereign/scripts/backup.sh >> /var/log/solvereign-backup.log 2>&1
#
# Retention: 90 days (configurable via RETENTION_DAYS env var)
# ==============================================================================

set -euo pipefail

# Configuration (overridable via environment)
BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
CONTAINER_NAME="${CONTAINER_NAME:-solvereign-pilot-db}"
DATABASE_NAME="${DATABASE_NAME:-solvereign}"
DATABASE_USER="${DATABASE_USER:-solvereign}"
RETENTION_DAYS="${RETENTION_DAYS:-90}"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/solvereign_${TIMESTAMP}.dump"

echo "=============================================="
echo "SOLVEREIGN Database Backup"
echo "=============================================="
echo "Timestamp: ${TIMESTAMP}"
echo "Container: ${CONTAINER_NAME}"
echo "Database:  ${DATABASE_NAME}"
echo "Output:    ${BACKUP_FILE}"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Check if container is running
if ! docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -q true; then
    echo "ERROR: Container '${CONTAINER_NAME}' is not running!"
    exit 1
fi

# Create backup using pg_dump inside container
echo "Creating backup..."
START_TIME=$(date +%s)

if ! docker exec "${CONTAINER_NAME}" pg_dump -U "${DATABASE_USER}" -Fc "${DATABASE_NAME}" > "${BACKUP_FILE}"; then
    echo "ERROR: pg_dump failed!"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)

echo ""
echo "Backup completed successfully!"
echo "  File:     ${BACKUP_FILE}"
echo "  Size:     ${FILE_SIZE}"
echo "  Duration: ${DURATION} seconds"

# Cleanup old backups
echo ""
echo "Cleaning up backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=0

while IFS= read -r -d '' old_file; do
    echo "  Removing: $(basename "${old_file}")"
    rm -f "${old_file}"
    ((DELETED_COUNT++))
done < <(find "${BACKUP_DIR}" -name "solvereign_*.dump" -type f -mtime +"${RETENTION_DAYS}" -print0 2>/dev/null)

if [ "${DELETED_COUNT}" -gt 0 ]; then
    echo "Removed ${DELETED_COUNT} old backup(s)"
else
    echo "  No old backups to remove"
fi

# List current backups
echo ""
echo "Current backups:"
ls -lh "${BACKUP_DIR}"/solvereign_*.dump 2>/dev/null | awk '{print "  " $9 " (" $5 ") - " $6 " " $7 " " $8}' || echo "  (none)"

echo ""
echo "=============================================="
echo "Backup complete!"
echo "=============================================="
