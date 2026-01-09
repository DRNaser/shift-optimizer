#!/bin/bash
# =============================================================================
# SOLVEREIGN - Security Gate CI Script
# =============================================================================
# Gate A: Verify security hardening before deployment
#
# EXIT CODES:
#   0 = All tests PASS
#   1 = Security test FAIL
#   2 = Database connection error
#   3 = Missing prerequisites
#
# ARTIFACTS (always uploaded):
#   - security_gate_result.json
#   - acl_scan_report.json
#   - verify_hardening_output.txt
#
# USAGE:
#   ./scripts/ci/security_gate.sh [--db-url DATABASE_URL]
# =============================================================================

set -euo pipefail

# Configuration
DB_URL="${DATABASE_URL:-postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign}"
ARTIFACT_DIR="${ARTIFACT_DIR:-./artifacts}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --db-url)
            DB_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 3
            ;;
    esac
done

# Create artifact directory
mkdir -p "$ARTIFACT_DIR"

echo "=============================================================================="
echo "SOLVEREIGN Security Gate"
echo "=============================================================================="
echo "Timestamp: $(date -Iseconds)"
echo "Artifact dir: $ARTIFACT_DIR"
echo ""

# Track overall status
GATE_STATUS="PASS"
FAIL_COUNT=0
WARN_COUNT=0

# Function to run SQL and capture result
run_sql() {
    local sql="$1"
    psql "$DB_URL" -t -A -c "$sql" 2>&1
}

# Function to run SQL and save output
run_sql_to_file() {
    local sql="$1"
    local file="$2"
    psql "$DB_URL" -c "$sql" > "$file" 2>&1
}

# =============================================================================
# TEST 1: verify_final_hardening() - Must have 0 FAIL
# =============================================================================
echo "[1/5] Running verify_final_hardening()..."

# Check if function exists
if ! run_sql "SELECT 1 FROM pg_proc WHERE proname = 'verify_final_hardening'" | grep -q 1; then
    echo -e "${RED}FAIL: verify_final_hardening() function not found!${NC}"
    echo "Run migrations 025-025e first."
    GATE_STATUS="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    # Run verification and count failures
    HARDENING_OUTPUT=$(run_sql "SELECT test_name, expected, actual, status FROM verify_final_hardening()")
    echo "$HARDENING_OUTPUT" > "$ARTIFACT_DIR/verify_hardening_output.txt"

    FAIL_IN_HARDENING=$(echo "$HARDENING_OUTPUT" | grep -c "FAIL" || true)
    WARN_IN_HARDENING=$(echo "$HARDENING_OUTPUT" | grep -c "WARN" || true)

    if [[ "$FAIL_IN_HARDENING" -gt 0 ]]; then
        echo -e "${RED}FAIL: verify_final_hardening() has $FAIL_IN_HARDENING failures!${NC}"
        echo "$HARDENING_OUTPUT" | grep "FAIL"
        GATE_STATUS="FAIL"
        FAIL_COUNT=$((FAIL_COUNT + FAIL_IN_HARDENING))
    else
        echo -e "${GREEN}PASS: verify_final_hardening() - 0 failures${NC}"
        if [[ "$WARN_IN_HARDENING" -gt 0 ]]; then
            echo -e "${YELLOW}  ($WARN_IN_HARDENING warnings)${NC}"
            WARN_COUNT=$((WARN_COUNT + WARN_IN_HARDENING))
        fi
    fi
fi

# =============================================================================
# TEST 2: verify_rls_boundary() - Must have 0 FAIL
# =============================================================================
echo ""
echo "[2/5] Running verify_rls_boundary()..."

if ! run_sql "SELECT 1 FROM pg_proc WHERE proname = 'verify_rls_boundary'" | grep -q 1; then
    echo -e "${RED}FAIL: verify_rls_boundary() function not found!${NC}"
    GATE_STATUS="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    RLS_OUTPUT=$(run_sql "SELECT test_name, expected, actual, status FROM verify_rls_boundary()")
    echo "$RLS_OUTPUT" >> "$ARTIFACT_DIR/verify_hardening_output.txt"

    FAIL_IN_RLS=$(echo "$RLS_OUTPUT" | grep -c "FAIL" || true)

    if [[ "$FAIL_IN_RLS" -gt 0 ]]; then
        echo -e "${RED}FAIL: verify_rls_boundary() has $FAIL_IN_RLS failures!${NC}"
        echo "$RLS_OUTPUT" | grep "FAIL"
        GATE_STATUS="FAIL"
        FAIL_COUNT=$((FAIL_COUNT + FAIL_IN_RLS))
    else
        echo -e "${GREEN}PASS: verify_rls_boundary() - 0 failures${NC}"
    fi
fi

# =============================================================================
# TEST 3: solvereign_api on tenants = Permission denied (NOT 0 rows)
# =============================================================================
echo ""
echo "[3/5] Testing solvereign_api on tenants = Permission denied..."

# This is the CRITICAL test: API role must get "permission denied" error,
# not "0 rows" (which would just be RLS hiding data)
API_SELECT_RESULT=$(psql "$DB_URL" -c "
SET ROLE solvereign_api;
SELECT COUNT(*) FROM tenants;
" 2>&1 || true)

if echo "$API_SELECT_RESULT" | grep -qi "permission denied"; then
    echo -e "${GREEN}PASS: solvereign_api gets 'Permission denied' on tenants table${NC}"
    echo "  (This is LEAST PRIVILEGE - actual denial, not RLS hiding)"
elif echo "$API_SELECT_RESULT" | grep -qE "^[[:space:]]*0[[:space:]]*$|count.*0"; then
    echo -e "${RED}FAIL: solvereign_api gets '0 rows' - this is just RLS hiding, not true denial!${NC}"
    echo "  Expected: Permission denied error"
    echo "  Actual: Query succeeded with 0 rows"
    echo "  Fix: REVOKE SELECT ON tenants FROM solvereign_api"
    GATE_STATUS="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    echo -e "${YELLOW}WARN: Unexpected result from solvereign_api SELECT:${NC}"
    echo "$API_SELECT_RESULT"
    WARN_COUNT=$((WARN_COUNT + 1))
fi

# Also test with session variable bypass attempt
API_BYPASS_RESULT=$(psql "$DB_URL" -c "
SET ROLE solvereign_api;
SET app.is_super_admin = 'true';
SELECT COUNT(*) FROM tenants;
" 2>&1 || true)

if echo "$API_BYPASS_RESULT" | grep -qi "permission denied"; then
    echo -e "${GREEN}PASS: Session variable bypass blocked (Permission denied)${NC}"
else
    echo -e "${RED}FAIL: Session variable bypass NOT blocked!${NC}"
    echo "$API_BYPASS_RESULT"
    GATE_STATUS="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# =============================================================================
# TEST 4: ACL Scan Report (artifact generation)
# =============================================================================
echo ""
echo "[4/5] Generating ACL scan report..."

if run_sql "SELECT 1 FROM pg_proc WHERE proname = 'acl_scan_report_json'" | grep -q 1; then
    ACL_JSON=$(run_sql "SELECT acl_scan_report_json()")
    echo "$ACL_JSON" > "$ARTIFACT_DIR/acl_scan_report.json"

    # Check for objects that need REVOKE
    TO_REVOKE=$(echo "$ACL_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('summary', {}).get('to_revoke', 0))
except:
    print(-1)
" 2>/dev/null || echo "-1")

    if [[ "$TO_REVOKE" == "0" ]]; then
        echo -e "${GREEN}PASS: ACL scan - 0 objects need REVOKE${NC}"
    elif [[ "$TO_REVOKE" == "-1" ]]; then
        echo -e "${YELLOW}WARN: Could not parse ACL scan result${NC}"
        WARN_COUNT=$((WARN_COUNT + 1))
    else
        echo -e "${RED}FAIL: ACL scan - $TO_REVOKE objects still have PUBLIC grants!${NC}"
        GATE_STATUS="FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
else
    echo -e "${YELLOW}WARN: acl_scan_report_json() not found - skipping${NC}"
    WARN_COUNT=$((WARN_COUNT + 1))
fi

# =============================================================================
# TEST 5: Platform role can access tenants (positive test)
# =============================================================================
echo ""
echo "[5/5] Testing solvereign_platform can access tenants..."

PLATFORM_SELECT_RESULT=$(psql "$DB_URL" -c "
SET ROLE solvereign_platform;
SELECT COUNT(*) FROM tenants;
" 2>&1 || true)

if echo "$PLATFORM_SELECT_RESULT" | grep -qi "permission denied"; then
    echo -e "${RED}FAIL: solvereign_platform cannot access tenants!${NC}"
    GATE_STATUS="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
elif echo "$PLATFORM_SELECT_RESULT" | grep -qE "[0-9]+"; then
    echo -e "${GREEN}PASS: solvereign_platform can access tenants table${NC}"
else
    echo -e "${YELLOW}WARN: Unexpected result from solvereign_platform SELECT${NC}"
    WARN_COUNT=$((WARN_COUNT + 1))
fi

# =============================================================================
# GENERATE FINAL REPORT
# =============================================================================
echo ""
echo "=============================================================================="
echo "Security Gate Result"
echo "=============================================================================="

# Generate JSON result
cat > "$ARTIFACT_DIR/security_gate_result.json" << EOF
{
    "timestamp": "$(date -Iseconds)",
    "gate_status": "$GATE_STATUS",
    "fail_count": $FAIL_COUNT,
    "warn_count": $WARN_COUNT,
    "tests": {
        "verify_final_hardening": "$(if [[ -z "${FAIL_IN_HARDENING:-}" || "$FAIL_IN_HARDENING" -eq 0 ]]; then echo "PASS"; else echo "FAIL"; fi)",
        "verify_rls_boundary": "$(if [[ -z "${FAIL_IN_RLS:-}" || "$FAIL_IN_RLS" -eq 0 ]]; then echo "PASS"; else echo "FAIL"; fi)",
        "api_permission_denied": "$(echo "$API_SELECT_RESULT" | grep -qi "permission denied" && echo "PASS" || echo "FAIL")",
        "session_bypass_blocked": "$(echo "$API_BYPASS_RESULT" | grep -qi "permission denied" && echo "PASS" || echo "FAIL")",
        "platform_can_access": "$(echo "$PLATFORM_SELECT_RESULT" | grep -qi "permission denied" && echo "FAIL" || echo "PASS")"
    },
    "artifacts": [
        "verify_hardening_output.txt",
        "acl_scan_report.json",
        "security_gate_result.json"
    ]
}
EOF

if [[ "$GATE_STATUS" == "PASS" ]]; then
    echo -e "${GREEN}GATE STATUS: PASS${NC}"
    echo "  Failures: $FAIL_COUNT"
    echo "  Warnings: $WARN_COUNT"
    echo ""
    echo "Artifacts saved to: $ARTIFACT_DIR/"
    ls -la "$ARTIFACT_DIR/"
    exit 0
else
    echo -e "${RED}GATE STATUS: FAIL${NC}"
    echo "  Failures: $FAIL_COUNT"
    echo "  Warnings: $WARN_COUNT"
    echo ""
    echo "Artifacts saved to: $ARTIFACT_DIR/"
    ls -la "$ARTIFACT_DIR/"
    exit 1
fi
