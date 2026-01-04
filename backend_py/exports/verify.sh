#!/bin/bash
# SOLVEREIGN Proof Pack Verification Script (Bash)
# Validates manifest.json checksums against exported artifacts
#
# Usage: ./verify.sh [path_to_exports_folder]
# Default: Current directory

set -e

EXPORT_PATH="${1:-.}"

echo "======================================================================"
echo "SOLVEREIGN Proof Pack Verification"
echo "======================================================================"
echo ""

# Check manifest exists
MANIFEST_PATH="$EXPORT_PATH/manifest.json"
if [ ! -f "$MANIFEST_PATH" ]; then
    echo "ERROR: manifest.json not found in $EXPORT_PATH"
    exit 1
fi

# Load manifest metadata
echo "Loaded manifest.json"
PLAN_ID=$(jq -r '.plan_version_id' "$MANIFEST_PATH")
GENERATED=$(jq -r '.generated_at' "$MANIFEST_PATH")
echo "  Plan Version ID: $PLAN_ID"
echo "  Generated: $GENERATED"
echo ""

# Verify each file
PASSED=0
FAILED=0

# Get file names and hashes from manifest
FILES=$(jq -r '.files | to_entries[] | "\(.key)|\(.value)"' "$MANIFEST_PATH")

while IFS='|' read -r FILE_NAME EXPECTED_HASH; do
    FILE_PATH="$EXPORT_PATH/$FILE_NAME"

    if [ ! -f "$FILE_PATH" ]; then
        echo -e "\033[31mFAIL: $FILE_NAME - File not found\033[0m"
        ((FAILED++))
        continue
    fi

    # Compute SHA256
    ACTUAL_HASH=$(sha256sum "$FILE_PATH" | awk '{print $1}')

    if [ "${ACTUAL_HASH,,}" = "${EXPECTED_HASH,,}" ]; then
        echo -e "\033[32mPASS: $FILE_NAME\033[0m"
        ((PASSED++))
    else
        echo -e "\033[31mFAIL: $FILE_NAME\033[0m"
        echo "       Expected: $EXPECTED_HASH"
        echo "       Actual:   $ACTUAL_HASH"
        ((FAILED++))
    fi
done <<< "$FILES"

echo ""
echo "======================================================================"
echo "RESULTS: $PASSED PASSED, $FAILED FAILED"
echo "======================================================================"

if [ $FAILED -gt 0 ]; then
    echo ""
    echo -e "\033[31mVERIFICATION FAILED - Proof pack may be corrupted or tampered\033[0m"
    exit 1
else
    echo ""
    echo -e "\033[32mVERIFICATION PASSED - All checksums match\033[0m"
    exit 0
fi
