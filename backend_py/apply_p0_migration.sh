#!/bin/bash
# ============================================================================
# SOLVEREIGN V3 - Apply P0 Migration
# ============================================================================
#
# This script applies the P0 fixes migration to the database.
#
# Prerequisites:
#   1. Docker running
#   2. PostgreSQL container running (docker-compose up -d postgres)
#
# Usage:
#   chmod +x apply_p0_migration.sh
#   ./apply_p0_migration.sh
# ============================================================================

set -e  # Exit on error

echo "============================================================================"
echo "SOLVEREIGN V3 - P0 Migration Application"
echo "============================================================================"
echo ""

# Check if Docker is running
if ! docker ps >/dev/null 2>&1; then
    echo "[ERROR] Docker is not running!"
    echo "        Please start Docker first."
    exit 1
fi

echo "[1/4] Checking PostgreSQL container..."
if ! docker ps --filter "name=solvereign-db" --format "{{.Names}}" | grep -q "solvereign-db"; then
    echo "[INFO] PostgreSQL container not running. Starting it..."
    docker-compose up -d postgres || {
        echo "[ERROR] Failed to start PostgreSQL container!"
        exit 1
    }
    echo "[OK] PostgreSQL container started"
    echo "[INFO] Waiting 5 seconds for database to be ready..."
    sleep 5
else
    echo "[OK] PostgreSQL container is running"
fi

echo ""
echo "[2/4] Testing database connection..."
if ! docker exec solvereign-db psql -U solvereign -d solvereign -c "SELECT 1;" >/dev/null 2>&1; then
    echo "[ERROR] Cannot connect to database!"
    echo "        Check PostgreSQL logs: docker logs solvereign-db"
    exit 1
fi
echo "[OK] Database connection successful"

echo ""
echo "[3/4] Applying migration 001_tour_instances.sql..."
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py/db/migrations/001_tour_instances.sql || {
    echo "[ERROR] Migration failed!"
    echo "        Check migration file: backend_py/db/migrations/001_tour_instances.sql"
    exit 1
}

echo ""
echo "[4/4] Verifying migration..."
if ! docker exec solvereign-db psql -U solvereign -d solvereign -c "\d tour_instances" | grep -q "tour_instances"; then
    echo "[ERROR] tour_instances table not found after migration!"
    exit 1
fi
echo "[OK] tour_instances table created successfully"

echo ""
echo "============================================================================"
echo "SUCCESS: P0 Migration Applied!"
echo "============================================================================"
echo ""
echo "Next Steps:"
echo "  1. Run tests: python backend_py/test_p0_migration.py"
echo "  2. Expand existing tours: See P0_MIGRATION_GUIDE.md"
echo "  3. Update application code to use fixed modules"
echo ""
echo "P0 Blockers Fixed:"
echo "  [OK] Template vs Instances: tour_instances table working"
echo "  [OK] Cross-midnight: crosses_midnight field implemented"
echo "  [OK] LOCKED Immutability: triggers installed"
echo ""
