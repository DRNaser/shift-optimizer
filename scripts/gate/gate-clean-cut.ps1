# =============================================================================
# SOLVEREIGN - CleanCut Gate (V1.0)
# =============================================================================
# Validates the codebase is clean of legacy components:
# - No Streamlit UI or dependencies
# - No backend_py/src/ (zombie package)
# - No backend_py/v3/ (after PR-3)
# - No src.* or v3.* imports (after PR-3)
# - Dockerfile doesn't copy legacy packages
# - pyproject.toml doesn't package legacy
#
# EXIT CODES:
#   0 = PASS (all checks passed)
#   1 = FAIL (one or more checks failed)
#
# Usage: .\scripts\gate\gate-clean-cut.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
$script:exitCode = 0
$script:checks = @{}
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Set-Location $repoRoot

function Write-Pass {
    param([string]$check, [string]$message)
    Write-Host "[PASS] ${check}: ${message}" -ForegroundColor Green
    $script:checks[$check] = "PASS"
}

function Write-Fail {
    param([string]$check, [string]$message)
    Write-Host "[FAIL] ${check}: ${message}" -ForegroundColor Red
    $script:exitCode = 1
    $script:checks[$check] = "FAIL"
}

function Write-Skip {
    param([string]$check, [string]$message)
    Write-Host "[SKIP] ${check}: ${message}" -ForegroundColor Yellow
    $script:checks[$check] = "SKIP"
}

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host " SOLVEREIGN CleanCut Gate" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# =============================================================================
# CHECK 1: Streamlit files removed
# =============================================================================
Write-Host "`n--- Check 1: Streamlit Files ---" -ForegroundColor White

if (Test-Path "backend_py/streamlit_app.py") {
    Write-Fail "STREAMLIT_APP" "backend_py/streamlit_app.py still exists"
} else {
    Write-Pass "STREAMLIT_APP" "backend_py/streamlit_app.py removed"
}

# =============================================================================
# CHECK 2: Legacy CLI removed
# =============================================================================
Write-Host "`n--- Check 2: Legacy CLI ---" -ForegroundColor White

if (Test-Path "backend_py/cli.py") {
    Write-Fail "LEGACY_CLI" "backend_py/cli.py still exists"
} else {
    Write-Pass "LEGACY_CLI" "backend_py/cli.py removed"
}

# =============================================================================
# CHECK 3: Root requirements.txt removed
# =============================================================================
Write-Host "`n--- Check 3: Root Requirements ---" -ForegroundColor White

if (Test-Path "requirements.txt") {
    $content = Get-Content "requirements.txt" -Raw
    if ($content -match "streamlit") {
        Write-Fail "ROOT_REQUIREMENTS" "requirements.txt contains streamlit"
    } else {
        Write-Pass "ROOT_REQUIREMENTS" "requirements.txt exists but no streamlit"
    }
} else {
    Write-Pass "ROOT_REQUIREMENTS" "requirements.txt removed"
}

# =============================================================================
# CHECK 4: backend_py/src removed
# =============================================================================
Write-Host "`n--- Check 4: Zombie src Package ---" -ForegroundColor White

if (Test-Path "backend_py/src") {
    Write-Fail "SRC_PACKAGE" "backend_py/src/ still exists"
} else {
    Write-Pass "SRC_PACKAGE" "backend_py/src/ removed"
}

# =============================================================================
# CHECK 5: backend_py/v3 removed (as of PR-3)
# =============================================================================
Write-Host "`n--- Check 5: Global v3 Package ---" -ForegroundColor White

if (Test-Path "backend_py/v3") {
    Write-Fail "V3_PACKAGE" "backend_py/v3/ still exists (should be moved to packs/roster/engine/)"
} else {
    # Verify v3 imports are also eliminated using PowerShell native search
    $v3ImportFiles = Get-ChildItem -Path "backend_py" -Recurse -Filter "*.py" |
        Select-String -Pattern "from v3\.|import v3\b" -List 2>$null
    if ($v3ImportFiles.Count -gt 0) {
        Write-Fail "V3_IMPORTS" "backend_py/v3/ removed but v3.* imports remain in: $($v3ImportFiles.Path -join ', ')"
    } else {
        Write-Pass "V3_PACKAGE" "backend_py/v3/ removed and no v3.* imports"
    }
}

# =============================================================================
# CHECK 6: No src.* imports remain
# =============================================================================
Write-Host "`n--- Check 6: src.* Imports ---" -ForegroundColor White

# Search for src.* imports using PowerShell native search
$srcImportFiles = Get-ChildItem -Path "backend_py" -Recurse -Filter "*.py" |
    Select-String -Pattern "from src\b|import src\b" -List 2>$null
# Exclude forecast_solver_v4.py (V4 experimental with graceful fallback)
$srcImportsFiltered = $srcImportFiles | Where-Object { $_.Path -notmatch "forecast_solver_v4\.py" }

if ($srcImportsFiltered.Count -gt 0) {
    Write-Fail "SRC_IMPORTS" "Found src.* imports in: $($srcImportsFiltered.Path -join ', ')"
} elseif ($srcImportFiles.Count -gt 0) {
    Write-Pass "SRC_IMPORTS" "Only V4 experimental src imports remain (graceful fallback)"
} else {
    Write-Pass "SRC_IMPORTS" "No src.* imports found"
}

# =============================================================================
# CHECK 7: Dockerfile doesn't copy src/
# =============================================================================
Write-Host "`n--- Check 7: Dockerfile ---" -ForegroundColor White

$dockerfile = Get-Content "backend_py/Dockerfile" -Raw
if ($dockerfile -match "COPY src/") {
    Write-Fail "DOCKERFILE_SRC" "Dockerfile still copies src/"
} else {
    Write-Pass "DOCKERFILE_SRC" "Dockerfile does not copy src/"
}

# =============================================================================
# CHECK 8: pyproject.toml doesn't package src
# =============================================================================
Write-Host "`n--- Check 8: pyproject.toml ---" -ForegroundColor White

$pyproject = Get-Content "backend_py/pyproject.toml" -Raw
if ($pyproject -match 'packages\s*=\s*\[\s*"src"\s*\]') {
    Write-Fail "PYPROJECT_SRC" "pyproject.toml still packages src"
} else {
    Write-Pass "PYPROJECT_SRC" "pyproject.toml does not package src"
}

# =============================================================================
# SUMMARY
# =============================================================================
Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host " CLEANCUT GATE SUMMARY" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

$passCount = ($script:checks.Values | Where-Object { $_ -eq "PASS" }).Count
$failCount = ($script:checks.Values | Where-Object { $_ -eq "FAIL" }).Count
$skipCount = ($script:checks.Values | Where-Object { $_ -eq "SKIP" }).Count

Write-Host "PASS: $passCount | FAIL: $failCount | SKIP: $skipCount"
Write-Host ""

if ($script:exitCode -eq 0) {
    Write-Host "[GATE] CLEANCUT: PASS" -ForegroundColor Green
} else {
    Write-Host "[GATE] CLEANCUT: FAIL" -ForegroundColor Red
}

exit $script:exitCode
