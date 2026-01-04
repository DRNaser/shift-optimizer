# SOLVEREIGN Proof Pack Verification Script (PowerShell)
# Validates manifest.json checksums against exported artifacts
#
# Usage: .\verify.ps1 [path_to_exports_folder]
# Default: Current directory

param(
    [string]$ExportPath = "."
)

Write-Host "=" * 70
Write-Host "SOLVEREIGN Proof Pack Verification"
Write-Host "=" * 70
Write-Host ""

# Check manifest exists
$manifestPath = Join-Path $ExportPath "manifest.json"
if (-not (Test-Path $manifestPath)) {
    Write-Host "ERROR: manifest.json not found in $ExportPath" -ForegroundColor Red
    exit 1
}

# Load manifest
try {
    $manifest = Get-Content $manifestPath | ConvertFrom-Json
    Write-Host "Loaded manifest.json"
    Write-Host "  Plan Version ID: $($manifest.plan_version_id)"
    Write-Host "  Generated: $($manifest.generated_at)"
    Write-Host ""
} catch {
    Write-Host "ERROR: Failed to parse manifest.json" -ForegroundColor Red
    exit 1
}

# Verify each file
$passed = 0
$failed = 0

foreach ($file in $manifest.files.PSObject.Properties) {
    $fileName = $file.Name
    $expectedHash = $file.Value
    $filePath = Join-Path $ExportPath $fileName

    if (-not (Test-Path $filePath)) {
        Write-Host "FAIL: $fileName - File not found" -ForegroundColor Red
        $failed++
        continue
    }

    # Compute SHA256
    $actualHash = (Get-FileHash -Path $filePath -Algorithm SHA256).Hash.ToLower()

    if ($actualHash -eq $expectedHash.ToLower()) {
        Write-Host "PASS: $fileName" -ForegroundColor Green
        $passed++
    } else {
        Write-Host "FAIL: $fileName" -ForegroundColor Red
        Write-Host "       Expected: $expectedHash"
        Write-Host "       Actual:   $actualHash"
        $failed++
    }
}

Write-Host ""
Write-Host "=" * 70
Write-Host "RESULTS: $passed PASSED, $failed FAILED"
Write-Host "=" * 70

if ($failed -gt 0) {
    Write-Host ""
    Write-Host "VERIFICATION FAILED - Proof pack may be corrupted or tampered" -ForegroundColor Red
    exit 1
} else {
    Write-Host ""
    Write-Host "VERIFICATION PASSED - All checksums match" -ForegroundColor Green
    exit 0
}
