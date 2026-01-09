#!/usr/bin/env bash
# ==============================================================================
# SOLVEREIGN V3.7 - Wien W02 Staging Soak Test
# ==============================================================================
# Runs N iterations of staging dry run + ops drills to verify stability.
#
# Requirements:
# - 24h soak recommended before RC tag
# - All iterations must produce identical hashes (determinism)
# - Memory/runtime metrics recorded
#
# Exit Codes:
#   0 = All iterations PASS, hashes stable
#   1 = Some iterations WARN (flaky but recoverable)
#   2 = FAIL (hash mismatch, critical failure)
#
# Usage:
#   ./scripts/w02_staging_soak.sh --iterations 5 --interval 300
#   ./scripts/w02_staging_soak.sh --iterations 10 --with-drills
# ==============================================================================

set -euo pipefail

# ==============================================================================
# CONFIGURATION
# ==============================================================================

ITERATIONS=${ITERATIONS:-5}
INTERVAL_SECONDS=${INTERVAL_SECONDS:-300}  # 5 minutes between runs
WITH_DRILLS=${WITH_DRILLS:-false}
ARTIFACTS_DIR="artifacts/soak_$(date +%Y%m%d_%H%M%S)"
SEED=94
TENANT="wien_pilot"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --interval)
            INTERVAL_SECONDS="$2"
            shift 2
            ;;
        --with-drills)
            WITH_DRILLS=true
            shift
            ;;
        --artifacts-dir)
            ARTIFACTS_DIR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --iterations N     Number of soak iterations (default: 5)"
            echo "  --interval SEC     Seconds between iterations (default: 300)"
            echo "  --with-drills      Run ops drills once during soak"
            echo "  --artifacts-dir    Output directory for artifacts"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ==============================================================================
# SETUP
# ==============================================================================

mkdir -p "$ARTIFACTS_DIR"

echo "=============================================================================="
echo "SOLVEREIGN STAGING SOAK TEST (Wien W02)"
echo "=============================================================================="
echo "Timestamp:   $(date -Iseconds)"
echo "Iterations:  $ITERATIONS"
echo "Interval:    ${INTERVAL_SECONDS}s"
echo "With Drills: $WITH_DRILLS"
echo "Artifacts:   $ARTIFACTS_DIR"
echo "Seed:        $SEED"
echo "Tenant:      $TENANT"
echo "=============================================================================="
echo ""

# Initialize metrics
declare -a HASHES=()
declare -a RUNTIMES=()
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

# ==============================================================================
# SOAK ITERATIONS
# ==============================================================================

for i in $(seq 1 "$ITERATIONS"); do
    echo "[Iteration $i/$ITERATIONS] Starting at $(date +%H:%M:%S)..."

    ITER_DIR="$ARTIFACTS_DIR/iter_$i"
    mkdir -p "$ITER_DIR"

    START_TIME=$(date +%s.%N)

    # Run roster dry run
    if python scripts/ci/wien_roster_gate.sh --skip-routing \
        --artifacts-dir "$ITER_DIR" \
        --seed "$SEED" \
        --tenant "$TENANT" > "$ITER_DIR/roster.log" 2>&1; then

        END_TIME=$(date +%s.%N)
        RUNTIME=$(echo "$END_TIME - $START_TIME" | bc)
        RUNTIMES+=("$RUNTIME")

        # Extract output hash
        if [ -f "$ITER_DIR/wien_roster_gate_result.json" ]; then
            HASH=$(jq -r '.output_hash // "MISSING"' "$ITER_DIR/wien_roster_gate_result.json")
        else
            # Fallback: compute hash from log
            HASH=$(sha256sum "$ITER_DIR/roster.log" | cut -d' ' -f1)
        fi
        HASHES+=("$HASH")

        echo "         Runtime: ${RUNTIME}s"
        echo "         Hash:    ${HASH:0:16}..."

        # Check determinism
        if [ ${#HASHES[@]} -gt 1 ]; then
            PREV_HASH=${HASHES[$((${#HASHES[@]} - 2))]}
            if [ "$HASH" != "$PREV_HASH" ]; then
                echo "         WARN: Hash mismatch with previous iteration!"
                WARN_COUNT=$((WARN_COUNT + 1))
            fi
        fi

        ((PASS_COUNT++))

    else
        echo "         FAIL: Roster gate failed"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        HASHES+=("FAILED")
        RUNTIMES+=("0")
    fi

    # Record memory usage (if available)
    if command -v free &> /dev/null; then
        free -m > "$ITER_DIR/memory.txt"
    fi

    # Wait before next iteration (except last)
    if [ "$i" -lt "$ITERATIONS" ]; then
        echo "         Waiting ${INTERVAL_SECONDS}s before next iteration..."
        sleep "$INTERVAL_SECONDS"
    fi
done

# ==============================================================================
# OPS DRILLS (if requested)
# ==============================================================================

if [ "$WITH_DRILLS" = true ]; then
    echo ""
    echo "[Ops Drills] Running once..."

    DRILLS_DIR="$ARTIFACTS_DIR/drills"
    mkdir -p "$DRILLS_DIR"

    # H1: Sick-Call Drill
    echo "  [H1] Sick-Call Drill..."
    if python scripts/run_sick_call_drill.py --dry-run --seed "$SEED" \
        --absent-drivers DRV001,DRV002,DRV003,DRV004,DRV005 \
        --tenant "$TENANT" > "$DRILLS_DIR/h1_sick_call.log" 2>&1; then
        echo "       PASS"
    else
        echo "       WARN: Exit code $?"
        WARN_COUNT=$((WARN_COUNT + 1))
    fi

    # H2: Freeze-Window Drill
    echo "  [H2] Freeze-Window Drill..."
    if python scripts/run_freeze_window_drill.py --dry-run --seed "$SEED" \
        --freeze-horizon 720 \
        --tenant "$TENANT" > "$DRILLS_DIR/h2_freeze.log" 2>&1; then
        echo "       PASS"
    else
        echo "       FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    # H3: Partial-Forecast Drill
    echo "  [H3] Partial-Forecast Drill..."
    if python scripts/run_partial_forecast_drill.py --dry-run --seed "$SEED" \
        --tenant "$TENANT" > "$DRILLS_DIR/h3_partial.log" 2>&1; then
        echo "       PASS"
    else
        echo "       WARN"
        WARN_COUNT=$((WARN_COUNT + 1))
    fi
fi

# ==============================================================================
# DETERMINISM CHECK
# ==============================================================================

echo ""
echo "[Determinism Check]"

UNIQUE_HASHES=$(printf '%s\n' "${HASHES[@]}" | grep -v "FAILED" | sort -u | wc -l)
TOTAL_HASHES=$(printf '%s\n' "${HASHES[@]}" | grep -v "FAILED" | wc -l)

if [ "$UNIQUE_HASHES" -eq 1 ] && [ "$TOTAL_HASHES" -gt 0 ]; then
    echo "  PASS: All $TOTAL_HASHES iterations produced same hash"
    DETERMINISM="PASS"
elif [ "$UNIQUE_HASHES" -eq 0 ]; then
    echo "  FAIL: No successful iterations"
    DETERMINISM="FAIL"
else
    echo "  FAIL: $UNIQUE_HASHES unique hashes across $TOTAL_HASHES iterations"
    DETERMINISM="FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ==============================================================================
# METRICS SUMMARY
# ==============================================================================

echo ""
echo "[Metrics Summary]"

# Runtime statistics
if [ ${#RUNTIMES[@]} -gt 0 ]; then
    TOTAL_RUNTIME=0
    MIN_RUNTIME=999999
    MAX_RUNTIME=0

    for rt in "${RUNTIMES[@]}"; do
        if [ "$rt" != "0" ]; then
            TOTAL_RUNTIME=$(echo "$TOTAL_RUNTIME + $rt" | bc)
            if (( $(echo "$rt < $MIN_RUNTIME" | bc -l) )); then
                MIN_RUNTIME=$rt
            fi
            if (( $(echo "$rt > $MAX_RUNTIME" | bc -l) )); then
                MAX_RUNTIME=$rt
            fi
        fi
    done

    AVG_RUNTIME=$(echo "scale=2; $TOTAL_RUNTIME / $PASS_COUNT" | bc)

    echo "  Runtime (avg): ${AVG_RUNTIME}s"
    echo "  Runtime (min): ${MIN_RUNTIME}s"
    echo "  Runtime (max): ${MAX_RUNTIME}s"
fi

# ==============================================================================
# GENERATE SOAK REPORT
# ==============================================================================

SOAK_REPORT="$ARTIFACTS_DIR/soak_report.json"

cat > "$SOAK_REPORT" << EOF
{
  "timestamp": "$(date -Iseconds)",
  "iterations": $ITERATIONS,
  "interval_seconds": $INTERVAL_SECONDS,
  "with_drills": $WITH_DRILLS,
  "seed": $SEED,
  "tenant": "$TENANT",
  "results": {
    "pass_count": $PASS_COUNT,
    "warn_count": $WARN_COUNT,
    "fail_count": $FAIL_COUNT,
    "determinism": "$DETERMINISM",
    "unique_hashes": $UNIQUE_HASHES
  },
  "hashes": $(printf '%s\n' "${HASHES[@]}" | jq -R . | jq -s .),
  "runtimes": [$(IFS=,; echo "${RUNTIMES[*]}")],
  "artifacts_dir": "$ARTIFACTS_DIR"
}
EOF

echo ""
echo "[Report] $SOAK_REPORT"

# ==============================================================================
# FINAL VERDICT
# ==============================================================================

echo ""
echo "=============================================================================="
echo "SOAK TEST SUMMARY"
echo "=============================================================================="
echo "Iterations:   $ITERATIONS"
echo "Pass:         $PASS_COUNT"
echo "Warn:         $WARN_COUNT"
echo "Fail:         $FAIL_COUNT"
echo "Determinism:  $DETERMINISM"
echo ""

if [ "$FAIL_COUNT" -gt 0 ] || [ "$DETERMINISM" = "FAIL" ]; then
    echo "VERDICT: FAIL"
    echo "Cannot cut RC tag - resolve failures first"
    echo "=============================================================================="
    exit 2
elif [ "$WARN_COUNT" -gt 0 ]; then
    echo "VERDICT: WARN"
    echo "Soak passed with warnings - review before RC tag"
    echo "=============================================================================="
    exit 1
else
    echo "VERDICT: PASS"
    echo "Ready to cut RC tag (e.g., v3.6.5-rc1)"
    echo "=============================================================================="
    exit 0
fi
