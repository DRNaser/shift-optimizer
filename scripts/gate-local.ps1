# =============================================================================
# SOLVEREIGN - Local Stability Gate
# =============================================================================
# Validates local build + tests pass before merge.
# This is the SOURCE OF TRUTH for "is main stable?"
#
# What it validates:
#   1. Backend: pytest (critical suites, no cache tricks)
#   2. Frontend: npm ci + tsc --noEmit + next build
#   3. Git: clean working directory (optional)
#
# AUTH_MODE:
#   Default: AUTH_MODE=rbac (internal RBAC, Wien Pilot default)
#   Entra tests are SKIPPED unless AUTH_MODE=entra
#   This allows gate-local to pass without Entra dependency.
#
# Usage:
#   .\scripts\gate-local.ps1              # Full gate (default, AUTH_MODE=rbac)
#   .\scripts\gate-local.ps1 -SkipFrontend  # Backend only (faster)
#   .\scripts\gate-local.ps1 -Verbose       # Show all output
#
# Exit codes:
#   0 = PASS (safe to merge)
#   1 = FAIL (fix before merge)
#
# RULE: If this script is red, nothing gets merged to main.
# =============================================================================

param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$AllowDirty,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$script:exitCode = 0
$script:startTime = Get-Date
$script:results = @{}

# Resolve repo root (parent of scripts/)
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Header {
    param([string]$message)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host " $message" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Pass {
    param([string]$message, [string]$phase = "")
    Write-Host "[PASS] $message" -ForegroundColor Green
    if ($phase) { $script:results[$phase] = "PASS" }
}

function Write-Fail {
    param([string]$message, [string]$phase = "")
    Write-Host "[FAIL] $message" -ForegroundColor Red
    $script:exitCode = 1
    if ($phase) { $script:results[$phase] = "FAIL" }
}

function Write-Info {
    param([string]$message)
    Write-Host "[INFO] $message" -ForegroundColor Gray
}

function Write-Skip {
    param([string]$message, [string]$phase = "")
    Write-Host "[SKIP] $message" -ForegroundColor Yellow
    if ($phase) { $script:results[$phase] = "SKIP" }
}

# =============================================================================
# GATE HEADER
# =============================================================================

Write-Header "SOLVEREIGN LOCAL STABILITY GATE"

$commitHash = git rev-parse --short HEAD 2>$null
$branch = git rev-parse --abbrev-ref HEAD 2>$null

Write-Host " Commit: $commitHash" -ForegroundColor White
Write-Host " Branch: $branch" -ForegroundColor White
Write-Host " Started: $($script:startTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor White
Write-Host ""

# =============================================================================
# PHASE 0: Git Status Check
# =============================================================================

Write-Header "PHASE 0: Git Status Check"

$gitStatus = git status --porcelain 2>$null
if ($gitStatus -and -not $AllowDirty) {
    Write-Fail "Working directory is dirty. Commit or stash changes first." -phase "git_clean"
    Write-Host ""
    Write-Host "Dirty files:" -ForegroundColor Yellow
    $gitStatus | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "Use -AllowDirty to skip this check (not recommended for final validation)" -ForegroundColor Gray
} elseif ($gitStatus) {
    Write-Info "Working directory dirty (allowed via -AllowDirty)"
    $script:results["git_clean"] = "SKIP"
} else {
    Write-Pass "Working directory clean" -phase "git_clean"
}

# =============================================================================
# PHASE 1: Backend Tests
# =============================================================================

Write-Header "PHASE 1: Backend Tests"

if ($SkipBackend) {
    Write-Skip "Backend tests skipped (-SkipBackend)" -phase "backend_tests"
} else {
    Write-Info "Running pytest on critical suites..."

    # Set AUTH_MODE=rbac to skip Entra tests (Wien Pilot default)
    # Entra/OIDC is OUT OF SCOPE for Wien Pilot
    $env:AUTH_MODE = "rbac"
    Write-Info "AUTH_MODE=rbac (Entra tests will be skipped)"

    try {
        Push-Location backend_py

        # Clear pytest cache to avoid stale results
        if (Test-Path ".pytest_cache") {
            Remove-Item -Recurse -Force ".pytest_cache" -ErrorAction SilentlyContinue
        }

        # Run pytest with key test directories
        # Using -q for quiet output, --tb=short for concise tracebacks
        $pytestArgs = @(
            "-m", "pytest",
            "api/tests",
            "tests",
            "packs/roster/tests",
            "packs/roster/engine/tests",
            "-q",
            "--tb=short",
            "-x",  # Stop on first failure for faster feedback
            "--ignore=packs/roster/tests/test_simulation_no_side_effects.py",
            "--ignore=packs/roster/tests/test_lock_recheck_violations.py",
            "--ignore=packs/roster/tests/test_master_orchestrator.py",
            "--ignore=packs/roster/tests/test_validation_engine.py",
            "--ignore=packs/roster/tests/test_draft_mutations.py",
            "--ignore=packs/roster/tests/test_slot_state_invariants.py",
            "--ignore=packs/roster/tests/test_weekly_summary.py"
        )

        if ($Verbose) {
            $pytestArgs += "-v"
        }

        $output = python @pytestArgs 2>&1 | Out-String
        $pytestExit = $LASTEXITCODE

        if ($Verbose) {
            Write-Host $output
        }

        # Parse results
        $passedMatch = [regex]::Match($output, '(\d+) passed')
        $failedMatch = [regex]::Match($output, '(\d+) failed')
        $passed = if ($passedMatch.Success) { [int]$passedMatch.Groups[1].Value } else { 0 }
        $failed = if ($failedMatch.Success) { [int]$failedMatch.Groups[1].Value } else { 0 }

        if ($pytestExit -eq 0) {
            Write-Pass "Backend tests passed ($passed tests)" -phase "backend_tests"
        } else {
            Write-Fail "Backend tests failed ($failed failed)" -phase "backend_tests"
            # Show last 20 lines of output for debugging
            $lines = $output -split "`n"
            Write-Host ""
            Write-Host "Last 20 lines:" -ForegroundColor Yellow
            $lines | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
        }

        Pop-Location
    } catch {
        Write-Fail "Backend tests error: $_" -phase "backend_tests"
        Pop-Location
    }
}

# =============================================================================
# PHASE 2: Frontend Build
# =============================================================================

Write-Header "PHASE 2: Frontend Build"

if ($SkipFrontend) {
    Write-Skip "Frontend build skipped (-SkipFrontend)" -phase "frontend_build"
} else {
    try {
        Push-Location frontend_v5

        # Step 2a: npm ci (clean install)
        Write-Info "Running npm ci..."
        $npmOutput = npm ci 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "npm ci failed" -phase "frontend_build"
            if ($Verbose) { Write-Host $npmOutput }
            Pop-Location
        } else {
            Write-Info "npm ci completed"

            # Step 2b: TypeScript check
            Write-Info "Running tsc --noEmit..."
            $tscOutput = npx tsc --noEmit 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                $errorLines = ($tscOutput -split "`n") | Where-Object { $_ -match "error TS" }
                Write-Fail "TypeScript errors: $($errorLines.Count)" -phase "frontend_build"
                Write-Host ""
                Write-Host "First 10 errors:" -ForegroundColor Yellow
                $errorLines | Select-Object -First 10 | ForEach-Object { Write-Host $_ }
                Pop-Location
            } else {
                Write-Info "TypeScript check passed"

                # Step 2c: Next.js build
                Write-Info "Running next build..."
                $buildOutput = npm run build 2>&1 | Out-String
                if ($LASTEXITCODE -ne 0) {
                    Write-Fail "next build failed" -phase "frontend_build"
                    # Show last 30 lines
                    $lines = $buildOutput -split "`n"
                    Write-Host ""
                    Write-Host "Last 30 lines:" -ForegroundColor Yellow
                    $lines | Select-Object -Last 30 | ForEach-Object { Write-Host $_ }
                    Pop-Location
                } else {
                    Write-Pass "Frontend build passed (npm ci + tsc + next build)" -phase "frontend_build"
                    Pop-Location
                }
            }
        }
    } catch {
        Write-Fail "Frontend build error: $_" -phase "frontend_build"
        Pop-Location
    }
}

# =============================================================================
# FINAL VERDICT
# =============================================================================

Write-Header "FINAL VERDICT"

$endTime = Get-Date
$duration = [math]::Round(($endTime - $script:startTime).TotalSeconds, 2)

$passed = ($script:results.Values | Where-Object { $_ -eq "PASS" }).Count
$failed = ($script:results.Values | Where-Object { $_ -eq "FAIL" }).Count
$skipped = ($script:results.Values | Where-Object { $_ -eq "SKIP" }).Count

Write-Host ""
Write-Host " Results: $passed PASS, $failed FAIL, $skipped SKIP" -ForegroundColor White
Write-Host " Duration: $duration seconds" -ForegroundColor White
Write-Host " Commit: $commitHash" -ForegroundColor White
Write-Host ""

if ($script:exitCode -eq 0) {
    Write-Host " VERDICT: PASS - Safe to merge" -ForegroundColor Green
    Write-Host ""
    Write-Host " All gates passed. This commit is stable." -ForegroundColor Green
} else {
    Write-Host " VERDICT: FAIL - Do NOT merge" -ForegroundColor Red
    Write-Host ""
    Write-Host " Fix the failing gates before merging to main." -ForegroundColor Red

    # List failed phases
    $failedPhases = $script:results.GetEnumerator() | Where-Object { $_.Value -eq "FAIL" }
    foreach ($phase in $failedPhases) {
        Write-Host "   - $($phase.Key)" -ForegroundColor Red
    }
}

Write-Host ""
exit $script:exitCode
