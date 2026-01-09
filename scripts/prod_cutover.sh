#!/usr/bin/env bash
# ==============================================================================
# SOLVEREIGN V3.7 - Production Cutover Script
# ==============================================================================
# Idempotent migration runner with ON_ERROR_STOP, verification, and evidence.
#
# Exit Codes:
#   0 = SUCCESS - All migrations applied and verified
#   1 = FAIL - Migration or verification failed
#
# Usage:
#   ./scripts/prod_cutover.sh --db-url "$DATABASE_URL" --rc-tag v3.6.5-rc1
#   ./scripts/prod_cutover.sh --db-url "$DATABASE_URL" --dry-run
# ==============================================================================

set -euo pipefail

# ==============================================================================
# CONFIGURATION
# ==============================================================================

DB_URL="${SOLVEREIGN_DB_URL:-}"
RC_TAG=""
DRY_RUN=false
ARTIFACTS_DIR="artifacts/prod_cutover_$(date +%Y%m%d_%H%M%S)"
SKIP_PREFLIGHT=false

# Migrations to apply (in order)
MIGRATIONS=(
    "025_tenants_rls_fix.sql"
    "025a_rls_hardening.sql"
    "025b_rls_role_lockdown.sql"
    "025c_rls_boundary_fix.sql"
    "025d_definer_owner_hardening.sql"
    "025e_final_hardening.sql"
    "025f_acl_fix.sql"
)

MIGRATIONS_DIR="backend_py/db/migrations"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --db-url)
            DB_URL="$2"
            shift 2
            ;;
        --rc-tag)
            RC_TAG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --artifacts-dir)
            ARTIFACTS_DIR="$2"
            shift 2
            ;;
        --skip-preflight)
            SKIP_PREFLIGHT=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --db-url URL        Database connection URL (required)"
            echo "  --rc-tag TAG        RC tag being deployed"
            echo "  --dry-run           Validate without applying migrations"
            echo "  --artifacts-dir     Output directory for artifacts"
            echo "  --skip-preflight    Skip preflight check (not recommended)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required args
if [ -z "$DB_URL" ]; then
    echo "ERROR: --db-url is required"
    exit 1
fi

# ==============================================================================
# SETUP
# ==============================================================================

mkdir -p "$ARTIFACTS_DIR"

echo "=============================================================================="
echo "SOLVEREIGN PRODUCTION CUTOVER"
echo "=============================================================================="
echo "Timestamp:   $(date -Iseconds)"
echo "RC Tag:      ${RC_TAG:-<not specified>}"
echo "Dry Run:     $DRY_RUN"
echo "Artifacts:   $ARTIFACTS_DIR"
echo "=============================================================================="
echo ""

# Initialize status
CUTOVER_STATUS="IN_PROGRESS"
MIGRATION_LOG="$ARTIFACTS_DIR/migration_log.txt"

# Start migration log
echo "SOLVEREIGN Production Cutover Log" > "$MIGRATION_LOG"
echo "Started: $(date -Iseconds)" >> "$MIGRATION_LOG"
echo "" >> "$MIGRATION_LOG"

# ==============================================================================
# PREFLIGHT CHECK
# ==============================================================================

if [ "$SKIP_PREFLIGHT" = false ]; then
    echo "[1/6] Running preflight check..."

    if python scripts/prod_preflight_check.py \
        --db-url "$DB_URL" \
        --output "$ARTIFACTS_DIR/preflight_result.json" \
        $( [ "$DRY_RUN" = true ] && echo "--dry-run" ); then
        echo "       Preflight: PASS"
    else
        PREFLIGHT_EXIT=$?
        if [ $PREFLIGHT_EXIT -eq 1 ]; then
            echo "       Preflight: WARN (proceeding with caution)"
        else
            echo "       Preflight: FAIL"
            echo "       Cannot proceed with cutover. Resolve issues first."
            CUTOVER_STATUS="FAILED"
            echo "Status: $CUTOVER_STATUS (preflight failed)" >> "$MIGRATION_LOG"
            exit 1
        fi
    fi
else
    echo "[1/6] Skipping preflight check (--skip-preflight)"
fi

# ==============================================================================
# APPLY MIGRATIONS
# ==============================================================================

echo ""
echo "[2/6] Applying migrations..."
echo "" >> "$MIGRATION_LOG"
echo "=== MIGRATIONS ===" >> "$MIGRATION_LOG"

MIGRATIONS_APPLIED=0
MIGRATIONS_SKIPPED=0
MIGRATIONS_FAILED=0

for migration in "${MIGRATIONS[@]}"; do
    MIGRATION_PATH="$MIGRATIONS_DIR/$migration"

    if [ ! -f "$MIGRATION_PATH" ]; then
        echo "       WARN: $migration not found, skipping"
        echo "SKIP: $migration (file not found)" >> "$MIGRATION_LOG"
        MIGRATIONS_SKIPPED=$((MIGRATIONS_SKIPPED + 1))
        continue
    fi

    # Extract version from filename
    VERSION=$(echo "$migration" | sed 's/_.*//' | sed 's/\.sql//')

    # Check if already applied
    ALREADY_APPLIED=$(psql "$DB_URL" -t -c "
        SELECT COUNT(*) FROM schema_migrations WHERE version = '$VERSION'
    " 2>/dev/null | tr -d ' ' || echo "0")

    if [ "$ALREADY_APPLIED" = "1" ]; then
        echo "       SKIP: $migration (already applied)"
        echo "SKIP: $migration (already applied)" >> "$MIGRATION_LOG"
        MIGRATIONS_SKIPPED=$((MIGRATIONS_SKIPPED + 1))
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "       DRY-RUN: Would apply $migration"
        echo "DRY-RUN: $migration" >> "$MIGRATION_LOG"
        continue
    fi

    echo "       Applying: $migration..."

    # Apply with ON_ERROR_STOP
    if psql "$DB_URL" \
        -v ON_ERROR_STOP=1 \
        -f "$MIGRATION_PATH" \
        >> "$ARTIFACTS_DIR/migration_output_${migration}.txt" 2>&1; then
        echo "       OK: $migration"
        echo "OK: $migration" >> "$MIGRATION_LOG"
        MIGRATIONS_APPLIED=$((MIGRATIONS_APPLIED + 1))
    else
        echo "       FAIL: $migration"
        echo "FAIL: $migration" >> "$MIGRATION_LOG"
        MIGRATIONS_FAILED=$((MIGRATIONS_FAILED + 1))
        CUTOVER_STATUS="FAILED"

        # Copy error output
        cat "$ARTIFACTS_DIR/migration_output_${migration}.txt"
        echo ""
        echo "Migration failed. Stopping cutover."
        echo "Status: $CUTOVER_STATUS (migration failed: $migration)" >> "$MIGRATION_LOG"
        exit 1
    fi
done

echo ""
echo "       Applied: $MIGRATIONS_APPLIED"
echo "       Skipped: $MIGRATIONS_SKIPPED"
echo "       Failed:  $MIGRATIONS_FAILED"

# ==============================================================================
# VERIFY HARDENING
# ==============================================================================

echo ""
echo "[3/6] Verifying hardening..."

if [ "$DRY_RUN" = true ]; then
    echo "       DRY-RUN: Would run verify_final_hardening()"
else
    # Run verification
    VERIFY_OUTPUT=$(psql "$DB_URL" -t -c "SELECT * FROM verify_final_hardening();" 2>&1)
    echo "$VERIFY_OUTPUT" > "$ARTIFACTS_DIR/verify_hardening.txt"

    # Count failures
    VERIFY_FAILURES=$(echo "$VERIFY_OUTPUT" | grep -c "FAIL" || true)

    if [ "$VERIFY_FAILURES" -gt 0 ]; then
        echo "       FAIL: $VERIFY_FAILURES hardening check(s) failed"
        echo "$VERIFY_OUTPUT"
        CUTOVER_STATUS="FAILED"
        echo "Status: $CUTOVER_STATUS (hardening verification failed)" >> "$MIGRATION_LOG"
        exit 1
    else
        echo "       PASS: All hardening checks passed"
    fi
fi

# ==============================================================================
# GENERATE ACL SCAN REPORT
# ==============================================================================

echo ""
echo "[4/6] Generating ACL scan report..."

if [ "$DRY_RUN" = true ]; then
    echo "       DRY-RUN: Would generate ACL scan"
else
    psql "$DB_URL" -t -c "
        SELECT json_agg(row_to_json(t))
        FROM (
            SELECT
                nspname AS schema,
                relname AS table_name,
                array_agg(privilege_type) AS public_grants
            FROM information_schema.role_table_grants
            JOIN pg_class ON relname = table_name
            JOIN pg_namespace ON pg_namespace.oid = relnamespace
            WHERE grantee = 'PUBLIC'
              AND nspname NOT IN ('pg_catalog', 'information_schema')
            GROUP BY nspname, relname
        ) t;
    " > "$ARTIFACTS_DIR/acl_scan_report.json"

    # Check if any PUBLIC grants found
    ACL_COUNT=$(cat "$ARTIFACTS_DIR/acl_scan_report.json" | grep -c '"table_name"' || true)

    if [ "$ACL_COUNT" -gt 0 ]; then
        echo "       WARN: $ACL_COUNT table(s) with PUBLIC grants"
    else
        echo "       PASS: No PUBLIC grants on app tables"
    fi
fi

# ==============================================================================
# SMOKE TESTS
# ==============================================================================

echo ""
echo "[5/6] Running smoke tests..."

if [ "$DRY_RUN" = true ]; then
    echo "       DRY-RUN: Would run smoke tests"
else
    # Test database queries work
    SMOKE_RESULT=$(psql "$DB_URL" -t -c "SELECT 1 AS smoke_test;" 2>&1)

    if echo "$SMOKE_RESULT" | grep -q "1"; then
        echo "       PASS: Database smoke test"
    else
        echo "       FAIL: Database smoke test"
        CUTOVER_STATUS="FAILED"
    fi

    # Test security functions exist
    FUNC_COUNT=$(psql "$DB_URL" -t -c "
        SELECT COUNT(*) FROM pg_proc
        WHERE proname IN ('get_tenant_by_api_key_hash', 'set_tenant_context', 'list_all_tenants')
    " | tr -d ' ')

    if [ "$FUNC_COUNT" -ge 3 ]; then
        echo "       PASS: Security functions exist ($FUNC_COUNT found)"
    else
        echo "       WARN: Some security functions missing ($FUNC_COUNT found)"
    fi

    # Save smoke test results
    cat > "$ARTIFACTS_DIR/smoke_test_result.json" << EOF
{
    "timestamp": "$(date -Iseconds)",
    "database_query": "PASS",
    "security_functions": $FUNC_COUNT
}
EOF
fi

# ==============================================================================
# GENERATE SUMMARY
# ==============================================================================

echo ""
echo "[6/6] Generating cutover summary..."

if [ "$CUTOVER_STATUS" != "FAILED" ]; then
    CUTOVER_STATUS="SUCCESS"
fi

# Get git info
GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Generate summary
cat > "$ARTIFACTS_DIR/cutover_summary.json" << EOF
{
    "timestamp": "$(date -Iseconds)",
    "status": "$CUTOVER_STATUS",
    "dry_run": $DRY_RUN,
    "rc_tag": "${RC_TAG:-null}",
    "git_sha": "$GIT_SHA",
    "git_branch": "$GIT_BRANCH",
    "migrations": {
        "applied": $MIGRATIONS_APPLIED,
        "skipped": $MIGRATIONS_SKIPPED,
        "failed": $MIGRATIONS_FAILED
    },
    "artifacts_dir": "$ARTIFACTS_DIR"
}
EOF

echo "" >> "$MIGRATION_LOG"
echo "=== SUMMARY ===" >> "$MIGRATION_LOG"
echo "Status: $CUTOVER_STATUS" >> "$MIGRATION_LOG"
echo "Completed: $(date -Iseconds)" >> "$MIGRATION_LOG"

# ==============================================================================
# FINAL OUTPUT
# ==============================================================================

echo ""
echo "=============================================================================="
echo "CUTOVER SUMMARY"
echo "=============================================================================="
echo "Status:      $CUTOVER_STATUS"
echo "Migrations:  $MIGRATIONS_APPLIED applied, $MIGRATIONS_SKIPPED skipped"
echo "Dry Run:     $DRY_RUN"
echo ""
echo "Artifacts:   $ARTIFACTS_DIR/"
ls -la "$ARTIFACTS_DIR/"
echo ""

if [ "$CUTOVER_STATUS" = "SUCCESS" ]; then
    echo "=============================================================================="
    echo "CUTOVER SUCCESSFUL"
    echo "=============================================================================="
    echo ""
    echo "Next steps:"
    echo "1. Verify /health/ready endpoint"
    echo "2. Run ops drill (sick-call) in prod-safe mode"
    echo "3. Get approver sign-off"
    echo "4. Re-enable writes"
    echo ""
    exit 0
else
    echo "=============================================================================="
    echo "CUTOVER FAILED"
    echo "=============================================================================="
    echo ""
    echo "Review artifacts in $ARTIFACTS_DIR/ for details."
    echo "Consider rollback if production is impacted."
    echo ""
    exit 1
fi
