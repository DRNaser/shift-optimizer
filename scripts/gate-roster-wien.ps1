# =============================================================================
# SOLVEREIGN - Roster Wien Pilot Gate (V2.0 - Hardened)
# =============================================================================
# Validates the Roster Pack is ready for Wien Pilot deployment.
# Focused scope: Kernel + Roster Pack + minimal Notify/Ops integration.
#
# V2.0 HARDENING:
# - Skip Enforcement: FAIL if unapproved skips or expired allowlist entries
# - Artifact Completeness: Full evidence bundle with hashes
# - Scope Conformance: Verify IN_SCOPE features not skipped
#
# Phases:
# - Phase 1: Import Sanity (no side-effect imports)
# - Phase 2: Skip Enforcement (allowlist validation)
# - Phase 3: Roster Unit Tests (core logic)
# - Phase 4: API Router Validation (all routers importable)
# - Phase 5: TypeScript Build (frontend compiles)
# - Phase 6: Scope Conformance (IN_SCOPE not skipped)
# - Phase 7: Evidence Generation (full artifact bundle)
#
# Usage: .\scripts\gate-roster-wien.ps1
#
# EXIT CODES:
#   0 = GO (all phases PASS, pilot-ready)
#   1 = FAIL (one or more phases FAIL)
#   2 = INCOMPLETE (one or more phases SKIP)
#
# SKIP FLAGS:
#   $env:SV_SKIP_TSC = "1"  - Skip TypeScript check (faster iteration)
#   $env:SV_ALLOW_HIGH_SEVERITY = "1" - Allow HIGH severity skips without sign-off
#
# ARTIFACTS:
#   artifacts/gates/roster_wien/<timestamp>/
#     - gate_report.json (main report)
#     - skip_audit.json (skip enforcement details)
#     - route_manifest.json (API route inventory)
#     - evidence_bundle.sha256 (integrity hash)
# =============================================================================

$ErrorActionPreference = "Stop"
$script:exitCode = 0
$script:hasSkips = $false
$script:startTime = Get-Date
$script:phaseResults = @{}
$script:phaseDetails = @{}
$script:skipAudit = @{
    allowed = @()
    violations = @()
    expired = @()
    high_severity_unsigned = @()
}

# Config
$skipTsc = if ($env:SV_SKIP_TSC -eq "1") { $true } else { $false }
$allowHighSeverity = if ($env:SV_ALLOW_HIGH_SEVERITY -eq "1") { $true } else { $false }
$repoRoot = Split-Path -Parent $PSScriptRoot

# Ensure we're at repo root
Set-Location $repoRoot

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Header {
    param([string]$message)
    Write-Host ""
    Write-Host "=" * 70 -ForegroundColor Cyan
    Write-Host " $message" -ForegroundColor Cyan
    Write-Host "=" * 70 -ForegroundColor Cyan
}

function Write-Pass {
    param([string]$message, [string]$phase = "", [string]$detail = "")
    Write-Host "[PASS] $message" -ForegroundColor Green
    if ($phase) {
        $script:phaseResults[$phase] = "PASS"
        if ($detail) { $script:phaseDetails[$phase] = $detail }
    }
}

function Write-Fail {
    param([string]$message, [string]$phase = "", [string]$detail = "")
    Write-Host "[FAIL] $message" -ForegroundColor Red
    $script:exitCode = 1
    if ($phase) {
        $script:phaseResults[$phase] = "FAIL"
        if ($detail) { $script:phaseDetails[$phase] = $detail }
    }
}

function Write-Skip {
    param([string]$message, [string]$phase = "")
    Write-Host "[SKIP] $message" -ForegroundColor Yellow
    $script:hasSkips = $true
    if ($phase) { $script:phaseResults[$phase] = "SKIP" }
}

function Write-Info {
    param([string]$message)
    Write-Host "[INFO] $message" -ForegroundColor Gray
}

function Write-Warn {
    param([string]$message)
    Write-Host "[WARN] $message" -ForegroundColor Yellow
}

function Get-GitCommitHash {
    try {
        $hash = git rev-parse --short HEAD 2>$null
        return $hash
    } catch {
        return "unknown"
    }
}

function Get-GitCommitHashFull {
    try {
        $hash = git rev-parse HEAD 2>$null
        return $hash
    } catch {
        return "unknown"
    }
}

function Get-GitBranch {
    try {
        $branch = git rev-parse --abbrev-ref HEAD 2>$null
        return $branch
    } catch {
        return "unknown"
    }
}

function Get-FileHash256 {
    param([string]$filePath)
    try {
        $hash = Get-FileHash -Path $filePath -Algorithm SHA256
        return $hash.Hash.ToLower()
    } catch {
        return "error"
    }
}

function Get-MigrationsList {
    try {
        $migrations = Get-ChildItem -Path "$repoRoot/backend_py/db/migrations" -Filter "*.sql" |
            Sort-Object Name |
            Select-Object -ExpandProperty Name
        return $migrations
    } catch {
        return @()
    }
}

# =============================================================================
# GATE HEADER
# =============================================================================

Write-Header "SOLVEREIGN ROSTER WIEN PILOT GATE V2.0"
$commitHash = Get-GitCommitHash
$commitHashFull = Get-GitCommitHashFull
$branch = Get-GitBranch
Write-Host " Commit: $commitHash" -ForegroundColor White
Write-Host " Branch: $branch" -ForegroundColor White
Write-Host " Started: $($script:startTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor White

if ($skipTsc -or $allowHighSeverity) {
    Write-Host ""
    Write-Warn "SKIP FLAGS DETECTED"
    if ($skipTsc) { Write-Warn "  - SV_SKIP_TSC=1 (TypeScript check skipped)" }
    if ($allowHighSeverity) { Write-Warn "  - SV_ALLOW_HIGH_SEVERITY=1 (HIGH severity sign-off bypassed)" }
}
Write-Host ""

# =============================================================================
# PHASE 1: Import Sanity Check
# =============================================================================
Write-Header "PHASE 1: Import Sanity Check"
Write-Info "Verifying no side-effect imports in Roster Pack..."

$phase1Failed = $false
$importErrors = @()

# Test critical imports
$imports = @(
    "from backend_py.api.main import app",
    "from backend_py.packs.roster.api.routers import lifecycle",
    "from backend_py.api.security.internal_rbac import InternalUserContext",
    "from backend_py.api.routers.driver_contacts import router"
)

foreach ($import in $imports) {
    $moduleName = ($import -split "import ")[-1]
    try {
        $result = python -c "$import; print('OK')" 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -match "OK") {
            Write-Info "  [OK] $moduleName"
        } else {
            Write-Warn "  [ERR] $moduleName"
            $importErrors += "$moduleName : $result"
            $phase1Failed = $true
        }
    } catch {
        Write-Warn "  [ERR] $moduleName : $_"
        $importErrors += "$moduleName : $_"
        $phase1Failed = $true
    }
}

if ($phase1Failed) {
    Write-Fail "Import sanity check failed" -phase "import_sanity" -detail ($importErrors -join "; ")
} else {
    Write-Pass "All critical imports OK" -phase "import_sanity" -detail "$($imports.Count) modules verified"
}

# =============================================================================
# PHASE 2: Skip Enforcement (Allowlist Validation)
# =============================================================================
Write-Header "PHASE 2: Skip Enforcement"
Write-Info "Validating skipped tests against allowlist..."

$phase2Failed = $false
$allowlistPath = Join-Path $repoRoot "scripts/gate/allow_skips.json"

# Load allowlist
if (Test-Path $allowlistPath) {
    try {
        $allowlist = Get-Content $allowlistPath -Raw | ConvertFrom-Json
        Write-Info "Loaded allowlist: $($allowlist.allowed_skips.Count) entries"

        $today = Get-Date

        # Check each allowed skip
        foreach ($skip in $allowlist.allowed_skips) {
            $skipInfo = @{
                test_file = $skip.test_file
                reason = $skip.reason
                owner = $skip.owner
                expiry = $skip.expiry
                severity = $skip.severity
                pilot_blocking = $skip.pilot_blocking
            }

            # Check expiry
            $expiryDate = [DateTime]::Parse($skip.expiry)
            if ($expiryDate -lt $today) {
                Write-Warn "  [EXPIRED] $($skip.test_file) - expired $($skip.expiry)"
                $script:skipAudit.expired += $skipInfo
                $phase2Failed = $true
            } else {
                # Check HIGH severity without sign-off
                if ($skip.severity -eq "HIGH" -and -not $allowHighSeverity) {
                    if ($skip.decision_required -eq $true) {
                        Write-Warn "  [UNSIGNED] $($skip.test_file) - HIGH severity requires sign-off"
                        $script:skipAudit.high_severity_unsigned += $skipInfo
                        $phase2Failed = $true
                    } else {
                        $script:skipAudit.allowed += $skipInfo
                    }
                } else {
                    Write-Info "  [OK] $($skip.test_file) (expires $($skip.expiry))"
                    $script:skipAudit.allowed += $skipInfo
                }
            }
        }

        # Check for bugs blocking pilot
        if ($allowlist.bugs_blocking_pilot -and $allowlist.bugs_blocking_pilot.Count -gt 0) {
            Write-Warn "  [BLOCKER] $($allowlist.bugs_blocking_pilot.Count) bugs blocking pilot"
            foreach ($bug in $allowlist.bugs_blocking_pilot) {
                Write-Warn "    - $($bug.id): $($bug.title)"
            }
            $phase2Failed = $true
        }

    } catch {
        Write-Warn "Failed to parse allowlist: $_"
        $phase2Failed = $true
    }
} else {
    Write-Warn "No allowlist found at $allowlistPath"
    $phase2Failed = $true
}

# Verify ignored test files match allowlist
# NOTE: test_freeze_day.py removed from ignore list - tests now pass (BUG-003 resolved)
$ignoredFiles = @(
    "test_simulation_no_side_effects.py",
    "test_lock_recheck_violations.py",
    "test_master_orchestrator.py",
    "test_validation_engine.py",
    "test_draft_mutations.py",
    "test_slot_state_invariants.py",
    "test_weekly_summary.py"
)

$allowedFiles = $allowlist.allowed_skips | Select-Object -ExpandProperty test_file

foreach ($ignored in $ignoredFiles) {
    if ($ignored -notin $allowedFiles) {
        Write-Warn "  [VIOLATION] $ignored ignored but not in allowlist"
        $script:skipAudit.violations += @{
            test_file = $ignored
            reason = "Ignored in gate but not in allowlist"
        }
        $phase2Failed = $true
    }
}

if ($phase2Failed) {
    $detail = "expired=$($script:skipAudit.expired.Count), unsigned=$($script:skipAudit.high_severity_unsigned.Count), violations=$($script:skipAudit.violations.Count)"
    Write-Fail "Skip enforcement failed" -phase "skip_enforcement" -detail $detail
} else {
    Write-Pass "Skip enforcement passed" -phase "skip_enforcement" -detail "$($script:skipAudit.allowed.Count) skips allowed"
}

# =============================================================================
# PHASE 3: Roster Unit Tests
# =============================================================================
Write-Header "PHASE 3: Roster Unit Tests"
Write-Info "Running Roster Pack pytest suite..."

try {
    # Build ignore patterns from allowlist
    $ignorePatterns = @()
    foreach ($skip in $allowlist.allowed_skips) {
        $ignorePatterns += "--ignore=backend_py/packs/roster/tests/$($skip.test_file)"
    }

    # Run without -x to see all failures (not just first one)
    $pytestOutput = python -m pytest backend_py/packs/roster/tests $ignorePatterns -v --tb=short 2>&1 | Out-String
    $pytestExitCode = $LASTEXITCODE

    # Count passed/failed
    $passedMatch = [regex]::Match($pytestOutput, '(\d+) passed')
    $failedMatch = [regex]::Match($pytestOutput, '(\d+) failed')
    $errorMatch = [regex]::Match($pytestOutput, '(\d+) error')

    $passed = if ($passedMatch.Success) { [int]$passedMatch.Groups[1].Value } else { 0 }
    $failed = if ($failedMatch.Success) { [int]$failedMatch.Groups[1].Value } else { 0 }
    $errors = if ($errorMatch.Success) { [int]$errorMatch.Groups[1].Value } else { 0 }

    if ($pytestExitCode -eq 0) {
        Write-Pass "Roster unit tests passed ($passed tests)" -phase "roster_unit_tests" -detail "$passed passed, $failed failed"
    } else {
        Write-Fail "Roster unit tests failed ($failed failed, $errors errors)" -phase "roster_unit_tests" -detail "$passed passed, $failed failed, $errors errors"
        # Show last 30 lines of output for debugging
        $lines = $pytestOutput -split "`n"
        $lastLines = $lines | Select-Object -Last 30
        Write-Host ""
        Write-Host "Last 30 lines of pytest output:" -ForegroundColor Yellow
        $lastLines | ForEach-Object { Write-Host $_ }
    }
} catch {
    Write-Fail "Roster tests error: $_" -phase "roster_unit_tests"
}

# =============================================================================
# PHASE 4: API Router Validation
# =============================================================================
Write-Header "PHASE 4: API Router Validation"
Write-Info "Verifying all API routers can be loaded..."

$phase4Failed = $false
$routeManifest = @{
    total = 0
    roster = 0
    routes = @()
}

try {
    # Suppress logs by setting log level and redirecting stderr
    $result = python -c "
import json
import logging
import sys
import os

# Suppress all logging during import
logging.disable(logging.CRITICAL)
os.environ['LOG_LEVEL'] = 'CRITICAL'

# Redirect stderr to suppress any remaining output
old_stderr = sys.stderr
sys.stderr = open(os.devnull, 'w')

try:
    from backend_py.api.main import app
    routes = [r for r in app.routes if hasattr(r, 'path')]
    roster_routes = [r for r in routes if '/roster' in r.path]
    route_list = [{'path': r.path, 'methods': list(r.methods) if hasattr(r, 'methods') else []} for r in routes[:50]]
    # Output only valid JSON to stdout
    print(json.dumps({'total': len(routes), 'roster': len(roster_routes), 'routes': route_list}))
finally:
    sys.stderr = old_stderr
    logging.disable(logging.NOTSET)
" 2>$null

    if ($LASTEXITCODE -eq 0) {
        $routeData = $result | ConvertFrom-Json
        $routeManifest.total = $routeData.total
        $routeManifest.roster = $routeData.roster
        $routeManifest.routes = $routeData.routes

        if ($routeData.total -gt 200 -and $routeData.roster -gt 0) {
            Write-Pass "API routers loaded ($($routeData.total) total, $($routeData.roster) roster)" -phase "api_routers" -detail "$($routeData.total) routes, $($routeData.roster) roster"
        } else {
            Write-Fail "Unexpected route count (total=$($routeData.total), roster=$($routeData.roster))" -phase "api_routers"
            $phase4Failed = $true
        }
    } else {
        Write-Fail "API router loading failed: $result" -phase "api_routers"
        $phase4Failed = $true
    }
} catch {
    Write-Fail "API router validation error: $_" -phase "api_routers"
}

# =============================================================================
# PHASE 5: TypeScript Build Check
# =============================================================================
Write-Header "PHASE 5: TypeScript Build Check"

if ($skipTsc) {
    Write-Skip "TypeScript check skipped (SV_SKIP_TSC=1)" -phase "typescript_build"
} else {
    Write-Info "Running tsc --noEmit..."

    try {
        Push-Location frontend_v5
        $tscOutput = npx tsc --noEmit 2>&1 | Out-String

        if ($LASTEXITCODE -eq 0) {
            Write-Pass "TypeScript compilation OK" -phase "typescript_build" -detail "No type errors"
        } else {
            # Count errors
            $errorLines = ($tscOutput -split "`n") | Where-Object { $_ -match "error TS\d+" }
            $errorCount = $errorLines.Count

            Write-Fail "TypeScript errors: $errorCount" -phase "typescript_build" -detail "$errorCount type errors"

            # Show first 10 errors
            if ($errorCount -gt 0) {
                Write-Host ""
                Write-Host "First 10 TypeScript errors:" -ForegroundColor Yellow
                $errorLines | Select-Object -First 10 | ForEach-Object { Write-Host $_ }
            }
        }
        Pop-Location
    } catch {
        Write-Fail "TypeScript check error: $_" -phase "typescript_build"
        Pop-Location
    }
}

# =============================================================================
# PHASE 6: Scope Conformance Check
# =============================================================================
Write-Header "PHASE 6: Scope Conformance Check"
Write-Info "Verifying IN_SCOPE features are not skipped..."

$phase6Failed = $false
$scopePath = Join-Path $repoRoot "docs/pilot/VIENNA_ROSTER_PILOT_SCOPE.md"

# Define IN_SCOPE test files that MUST pass (not be skipped)
$inScopeTests = @(
    "test_roster_pack_critical.py",      # Core lifecycle
    "test_candidate_finder.py",          # Candidate finder
    "test_week_lookahead.py",            # Week lookahead
    "test_abort_status.py",              # Abort handling
    "test_activation_gate.py"            # Activation gate
)

# Check that IN_SCOPE tests are NOT in the skip list
$skippedFiles = $allowlist.allowed_skips | Select-Object -ExpandProperty test_file

foreach ($required in $inScopeTests) {
    if ($required -in $skippedFiles) {
        Write-Warn "  [SCOPE VIOLATION] $required is IN_SCOPE but skipped"
        $phase6Failed = $true
    } else {
        Write-Info "  [OK] $required (IN_SCOPE, not skipped)"
    }
}

# Verify OUT_OF_SCOPE items are properly documented
$outOfScopeTests = @(
    "test_master_orchestrator.py",
    "test_simulation_no_side_effects.py",
    "test_draft_mutations.py"
)

foreach ($outScope in $outOfScopeTests) {
    if ($outScope -in $skippedFiles) {
        Write-Info "  [OK] $outScope (OUT_OF_SCOPE, documented skip)"
    } else {
        Write-Info "  [NOTE] $outScope - not skipped (running as bonus coverage)"
    }
}

if ($phase6Failed) {
    Write-Fail "Scope conformance failed - IN_SCOPE features skipped" -phase "scope_conformance"
} else {
    Write-Pass "Scope conformance OK" -phase "scope_conformance" -detail "$($inScopeTests.Count) IN_SCOPE tests verified"
}

# =============================================================================
# PHASE 7: Evidence Generation (Enhanced)
# =============================================================================
Write-Header "PHASE 7: Evidence Generation"

$endTime = Get-Date
$durationSeconds = [math]::Round(($endTime - $script:startTime).TotalSeconds, 2)

# Determine verdict
$verdict = "GO"
if ($script:exitCode -ne 0) {
    $verdict = "FAIL"
} elseif ($script:hasSkips) {
    $verdict = "INCOMPLETE"
    $script:exitCode = 2
}

# Create artifact directory
$timestamp = $script:startTime.ToString("yyyyMMdd-HHmmss")
$artifactDir = Join-Path $repoRoot "artifacts/gates/roster_wien/$timestamp"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

# Get migrations list
$migrations = Get-MigrationsList
$migrationsHash = ($migrations -join "|").GetHashCode().ToString("X8")

# Build comprehensive report object
$report = @{
    gate = "roster_wien_pilot"
    version = "2.0.0"
    timestamp = $script:startTime.ToString("o")
    duration_seconds = $durationSeconds
    verdict = $verdict
    exit_code = $script:exitCode

    git = @{
        commit_short = $commitHash
        commit_full = $commitHashFull
        branch = $branch
    }

    environment = @{
        hostname = $env:COMPUTERNAME
        user = $env:USERNAME
        skip_tsc = $skipTsc
        allow_high_severity = $allowHighSeverity
    }

    migrations = @{
        count = $migrations.Count
        hash = $migrationsHash
        latest = if ($migrations.Count -gt 0) { $migrations[-1] } else { "none" }
    }

    phases = $script:phaseResults
    phase_details = $script:phaseDetails

    skip_audit = $script:skipAudit

    route_manifest = @{
        total_routes = $routeManifest.total
        roster_routes = $routeManifest.roster
    }

    summary = @{
        total_phases = $script:phaseResults.Count
        passed = ($script:phaseResults.Values | Where-Object { $_ -eq "PASS" }).Count
        failed = ($script:phaseResults.Values | Where-Object { $_ -eq "FAIL" }).Count
        skipped = ($script:phaseResults.Values | Where-Object { $_ -eq "SKIP" }).Count
    }

    scope = @{
        in_scope_tests = $inScopeTests
        out_of_scope_tests = $outOfScopeTests
        skipped_tests = $skippedFiles
    }
}

# Write JSON reports
$reportPath = Join-Path $artifactDir "gate_report.json"
$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8

$skipAuditPath = Join-Path $artifactDir "skip_audit.json"
$script:skipAudit | ConvertTo-Json -Depth 10 | Set-Content -Path $skipAuditPath -Encoding UTF8

$routeManifestPath = Join-Path $artifactDir "route_manifest.json"
$routeManifest | ConvertTo-Json -Depth 10 | Set-Content -Path $routeManifestPath -Encoding UTF8

# Generate evidence bundle hash
$reportHash = Get-FileHash256 $reportPath
$skipAuditHash = Get-FileHash256 $skipAuditPath
$routeManifestHash = Get-FileHash256 $routeManifestPath

$bundleHashContent = @"
# SOLVEREIGN Gate Evidence Bundle
# Generated: $($script:startTime.ToString("o"))
# Commit: $commitHashFull

gate_report.json: $reportHash
skip_audit.json: $skipAuditHash
route_manifest.json: $routeManifestHash
"@

$bundleHashPath = Join-Path $artifactDir "evidence_bundle.sha256"
$bundleHashContent | Set-Content -Path $bundleHashPath -Encoding UTF8

Write-Info "Evidence written to: $artifactDir"
Write-Info "  - gate_report.json ($reportHash)"
Write-Info "  - skip_audit.json ($skipAuditHash)"
Write-Info "  - route_manifest.json ($routeManifestHash)"
Write-Info "  - evidence_bundle.sha256"
Write-Pass "Evidence generation complete" -phase "evidence"

# =============================================================================
# FINAL VERDICT
# =============================================================================
Write-Host ""
Write-Header "FINAL VERDICT"
Write-Host ""

$summaryPassed = ($script:phaseResults.Values | Where-Object { $_ -eq "PASS" }).Count
$summaryFailed = ($script:phaseResults.Values | Where-Object { $_ -eq "FAIL" }).Count
$summarySkipped = ($script:phaseResults.Values | Where-Object { $_ -eq "SKIP" }).Count

Write-Host " Phases: $summaryPassed PASS, $summaryFailed FAIL, $summarySkipped SKIP" -ForegroundColor White
Write-Host " Duration: $durationSeconds seconds" -ForegroundColor White
Write-Host " Commit: $commitHash" -ForegroundColor White
Write-Host " Migrations: $($migrations.Count) (hash: $migrationsHash)" -ForegroundColor White
Write-Host ""

switch ($verdict) {
    "GO" {
        Write-Host " VERDICT: GO - Roster Wien Pilot Ready" -ForegroundColor Green
        Write-Host ""
        Write-Host " All phases passed. Safe to deploy to Wien Pilot." -ForegroundColor Green
    }
    "FAIL" {
        Write-Host " VERDICT: FAIL - Not Ready" -ForegroundColor Red
        Write-Host ""
        Write-Host " One or more phases failed. Fix issues before deployment." -ForegroundColor Red

        # List failed phases
        $failedPhases = $script:phaseResults.GetEnumerator() | Where-Object { $_.Value -eq "FAIL" }
        foreach ($phase in $failedPhases) {
            $detail = $script:phaseDetails[$phase.Key]
            Write-Host "   - $($phase.Key): $detail" -ForegroundColor Red
        }

        # Show specific blockers
        if ($script:skipAudit.expired.Count -gt 0) {
            Write-Host ""
            Write-Host " Expired skips (update allowlist):" -ForegroundColor Yellow
            foreach ($exp in $script:skipAudit.expired) {
                Write-Host "   - $($exp.test_file): expired $($exp.expiry)" -ForegroundColor Yellow
            }
        }

        if ($script:skipAudit.high_severity_unsigned.Count -gt 0) {
            Write-Host ""
            Write-Host " HIGH severity skips require sign-off:" -ForegroundColor Yellow
            foreach ($hs in $script:skipAudit.high_severity_unsigned) {
                Write-Host "   - $($hs.test_file): $($hs.reason)" -ForegroundColor Yellow
            }
            Write-Host "   Use SV_ALLOW_HIGH_SEVERITY=1 to bypass (requires justification)" -ForegroundColor Gray
        }
    }
    "INCOMPLETE" {
        Write-Host " VERDICT: INCOMPLETE - Skipped Phases" -ForegroundColor Yellow
        Write-Host ""
        Write-Host " Some phases were skipped. Run without skip flags for full validation." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host " Artifact: $artifactDir" -ForegroundColor Gray
Write-Host ""

exit $script:exitCode
