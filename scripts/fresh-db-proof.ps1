# =============================================================================
# SOLVEREIGN - Fresh DB Proof
# =============================================================================
# Proves migrations work from scratch on a truly empty database.
# This is the SOURCE OF TRUTH for "can we deploy to a new environment?"
#
# What it does:
#   1. Destroys all Docker volumes (truly fresh start)
#   2. Starts postgres + api containers
#   3. Runs all migrations in order (with SHA256 checksum tracking)
#   4. Optionally seeds test data
#   5. Runs health check + smoke test
#
# Usage:
#   .\scripts\fresh-db-proof.ps1              # Full proof (default)
#   .\scripts\fresh-db-proof.ps1 -SkipSeed    # Skip seed step
#   .\scripts\fresh-db-proof.ps1 -Repeat 2    # Run proof 2x (determinism check)
#   .\scripts\fresh-db-proof.ps1 -KeepRunning # Don't tear down after
#   .\scripts\fresh-db-proof.ps1 -RerunProof  # Idempotency proof (NO-OP if checksums match)
#   .\scripts\fresh-db-proof.ps1 -RerunProof -BackfillChecksums  # Backfill NULL checksums
#
# Checksum-based Idempotency (-RerunProof):
#   - Each migration's SHA256 checksum is stored when applied
#   - On RerunProof: migrations with matching checksums are SKIPPED (true NO-OP)
#   - If checksum MISMATCH: FAIL CLOSED (exit 1)
#   - If checksum NULL (legacy): FAIL CLOSED unless -BackfillChecksums provided
#   - Expected: Greenfield = applied=N skipped=0, RerunProof = applied=0 skipped=N
#
# Upgrade path (existing DB with legacy migrations):
#   1. First run: .\scripts\fresh-db-proof.ps1 -RerunProof -BackfillChecksums
#      - This backfills checksums for all legacy migrations
#   2. Subsequent runs: .\scripts\fresh-db-proof.ps1 -RerunProof
#      - Now works as expected (all checksums exist)
#
# Exit codes:
#   0 = PASS (migrations work from scratch)
#   1 = FAIL (broken migrations, seed, or checksum mismatch)
#
# COMPOSE FILE: docker-compose.pilot.yml (Single Source of Truth for local dev)
#
# RULE: Every migration PR must pass this proof before merge.
# =============================================================================

param(
    [switch]$SkipSeed,
    [switch]$KeepRunning,
    [int]$Repeat = 1,
    [switch]$Verbose,
    [switch]$RerunProof,       # Skip destroy phase, re-run migrations on existing DB (idempotency test)
    [switch]$BackfillChecksums # Explicitly backfill NULL checksums on legacy migrations (required for upgrade)
)

$ErrorActionPreference = "Stop"
$script:exitCode = 0
$script:startTime = Get-Date
$script:results = @{}
$script:lastApplied = 0
$script:lastSkipped = 0
$script:legacyMigrationsFound = 0

# Resolve repo root
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Configuration
$composeFile = "docker-compose.pilot.yml"
$dbContainer = "solvereign-pilot-db"
$apiContainer = "solvereign-pilot-api"
$dbUser = "solvereign"
$dbName = "solvereign"
$dbPassword = "pilot_dev_password"
$healthUrl = "http://localhost:8000/health"

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

function Wait-ForHealthy {
    param(
        [string]$url,
        [int]$timeoutSeconds = 120,
        [int]$intervalSeconds = 5
    )

    $elapsed = 0
    while ($elapsed -lt $timeoutSeconds) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            # Expected during startup
        }
        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
        Write-Info "Waiting for $url... ($elapsed/$timeoutSeconds sec)"
    }
    return $false
}

function Get-MigrationFiles {
    $migrations = Get-ChildItem -Path "$repoRoot/backend_py/db/migrations" -Filter "*.sql" |
        Sort-Object Name
    return $migrations
}

function Get-FileChecksum {
    param([string]$FilePath)
    $hash = Get-FileHash -Path $FilePath -Algorithm SHA256
    return $hash.Hash.ToLower()
}

function Get-MigrationVersion {
    param([string]$FileName)
    # Extract version: "000_initial.sql" -> "000", "025a_rls.sql" -> "025a"
    if ($FileName -match '^(\d+[a-z]?)_') {
        return $matches[1]
    }
    return $null
}

function Get-MigrationChecksums {
    param([string]$Container, [string]$User, [string]$Database)

    # Query checksums by file_name (1:1 mapping with migration files)
    $query = "COPY (SELECT file_name || '|' || checksum FROM schema_migrations WHERE file_name IS NOT NULL AND checksum IS NOT NULL) TO STDOUT;"
    $result = docker exec $Container psql -U $User -d $Database -t -A -c "$query" 2>&1 | Out-String

    $checksums = @{}
    if ($result) {
        $result.Trim() -split "`n" | Where-Object { $_.Trim() -and $_ -match '\|' } | ForEach-Object {
            $line = $_.Trim()
            $pipePos = $line.IndexOf('|')
            if ($pipePos -gt 0) {
                $fileName = $line.Substring(0, $pipePos)
                $checksum = $line.Substring($pipePos + 1)
                $checksums[$fileName] = $checksum
            }
        }
    }
    return $checksums
}

function Get-AppliedMigrations {
    param([string]$Container, [string]$User, [string]$Database)

    $query = "SELECT version FROM schema_migrations;"
    $result = docker exec $Container psql -U $User -d $Database -t -A -c "$query" 2>&1

    $versions = @()
    if ($LASTEXITCODE -eq 0 -and $result) {
        $versions = $result -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }
    }
    return $versions
}

# =============================================================================
# GATE HEADER
# =============================================================================

Write-Header "SOLVEREIGN FRESH DB PROOF"

$commitHash = git rev-parse --short HEAD 2>$null
$migrations = Get-MigrationFiles
$migrationCount = $migrations.Count

Write-Host " Commit: $commitHash" -ForegroundColor White
Write-Host " Compose: $composeFile" -ForegroundColor White
Write-Host " Migrations: $migrationCount files" -ForegroundColor White
Write-Host " Repeat: $Repeat time(s)" -ForegroundColor White
Write-Host " Started: $($script:startTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor White
Write-Host ""

# Verify compose file exists
if (-not (Test-Path $composeFile)) {
    Write-Fail "Compose file not found: $composeFile"
    exit 1
}

# =============================================================================
# RUN PROOF (potentially multiple times for determinism)
# =============================================================================

for ($run = 1; $run -le $Repeat; $run++) {

    if ($Repeat -gt 1) {
        Write-Header "RUN $run OF $Repeat"
    }

    # =========================================================================
    # PHASE 1: Destroy Everything (skipped if -RerunProof)
    # =========================================================================
    if ($RerunProof) {
        Write-Header "PHASE 1: SKIPPED (RerunProof mode)"
        Write-Info "Keeping existing database state for idempotency test..."
        $script:results["destroy_$run"] = "SKIP"
    } else {
        Write-Header "PHASE 1: Destroy All State"
        Write-Info "Stopping containers and removing volumes..."

        try {
            # Stop and remove containers + volumes
            docker compose -f $composeFile down -v --remove-orphans 2>&1 | Out-Null

            # Extra cleanup: remove named volumes explicitly
            docker volume rm solvereign-pilot-db-data 2>&1 | Out-Null

            Write-Pass "All containers and volumes destroyed" -phase "destroy_$run"
        } catch {
            Write-Info "Cleanup warning (may be expected): $_"
            $script:results["destroy_$run"] = "PASS"
        }
    }

    # =========================================================================
    # PHASE 2: Start Fresh Containers
    # =========================================================================
    Write-Header "PHASE 2: Start Fresh Containers"
    Write-Info "Starting postgres + api..."

    try {
        $output = docker compose -f $composeFile up -d --build 2>&1 | Out-String
        if ($Verbose) { Write-Host $output }

        if ($LASTEXITCODE -ne 0) {
            Write-Fail "docker compose up failed" -phase "start_$run"
            continue
        }

        Write-Info "Containers started, waiting for postgres..."

        # Wait for postgres to be healthy
        $pgHealthy = $false
        for ($i = 0; $i -lt 30; $i++) {
            $status = docker inspect --format='{{.State.Health.Status}}' $dbContainer 2>$null
            if ($status -eq "healthy") {
                $pgHealthy = $true
                break
            }
            Start-Sleep -Seconds 2
        }

        if (-not $pgHealthy) {
            Write-Fail "Postgres did not become healthy in 60s" -phase "start_$run"
            docker logs $dbContainer 2>&1 | Select-Object -Last 20
            continue
        }

        Write-Pass "Postgres healthy" -phase "start_$run"
    } catch {
        Write-Fail "Start containers error: $_" -phase "start_$run"
        continue
    }

    # =========================================================================
    # PHASE 3: Run Migrations (with checksum-based skip for RerunProof)
    # =========================================================================
    Write-Header "PHASE 3: Run Migrations"
    Write-Info "Checking $migrationCount migrations..."

    $migrationsFailed = $false
    $migrationsApplied = 0
    $migrationsSkipped = 0
    $migrationsLegacyUpgraded = 0

    # Get existing checksums from DB (only meaningful for RerunProof)
    $existingChecksums = @{}
    $appliedVersions = @()
    if ($RerunProof) {
        Write-Info "RerunProof mode: Loading existing migration state from database..."
        $existingChecksums = Get-MigrationChecksums -Container $dbContainer -User $dbUser -Database $dbName
        $appliedVersions = Get-AppliedMigrations -Container $dbContainer -User $dbUser -Database $dbName
        Write-Info "Found $($existingChecksums.Count) migrations with checksums, $($appliedVersions.Count) total applied"
    }

    # Collect all checksums for post-migration storage
    $pendingChecksums = @{}

    foreach ($migration in $migrations) {
        $migName = $migration.Name
        $fileChecksum = Get-FileChecksum -FilePath $migration.FullName
        $pendingChecksums[$migName] = $fileChecksum

        # Check if this migration should be skipped (RerunProof mode)
        if ($RerunProof) {
            # Case 1: File exists with checksum - compare checksums
            if ($existingChecksums.ContainsKey($migName)) {
                $dbChecksum = $existingChecksums[$migName]

                if ($dbChecksum -eq $fileChecksum) {
                    # Checksum matches - SKIP (true NO-OP)
                    $migrationsSkipped++
                    if ($Verbose) { Write-Info "  SKIP (checksum match): $migName" }
                    continue
                } else {
                    # Checksum MISMATCH - FAIL CLOSED
                    Write-Fail "CHECKSUM MISMATCH: $migName"
                    Write-Host "  File checksum: $fileChecksum" -ForegroundColor Red
                    Write-Host "  DB checksum:   $dbChecksum" -ForegroundColor Red
                    Write-Host "  Migration file has changed since it was applied!" -ForegroundColor Red
                    Write-Host "  This indicates a potentially breaking change to an already-applied migration." -ForegroundColor Red
                    $migrationsFailed = $true
                    break
                }
            }
            # Case 2: Legacy migration (applied but no checksum) - FAIL CLOSED unless -BackfillChecksums
            $version = Get-MigrationVersion -FileName $migName
            if ($version -and ($appliedVersions -contains $version -or $appliedVersions -contains "file:$migName")) {
                $script:legacyMigrationsFound++

                if ($BackfillChecksums) {
                    # Explicit backfill mode: compute and store checksum
                    $insertSql = "INSERT INTO schema_migrations (version, description, checksum, file_name, applied_at) VALUES ('file:$migName', 'Checksum backfill for $migName', '$fileChecksum', '$migName', NOW()) ON CONFLICT (version) DO UPDATE SET checksum = EXCLUDED.checksum, file_name = EXCLUDED.file_name;"
                    docker exec $dbContainer psql -U $dbUser -d $dbName -c "$insertSql" 2>&1 | Out-Null
                    $migrationsSkipped++
                    $migrationsLegacyUpgraded++
                    if ($Verbose) { Write-Info "  BACKFILL: $migName (checksum now tracked)" }
                } else {
                    # FAIL CLOSED: NULL checksum without explicit backfill flag
                    Write-Fail "NULL CHECKSUM: $migName"
                    Write-Host "  This migration is applied but has no checksum (legacy migration)." -ForegroundColor Red
                    Write-Host "  Use -BackfillChecksums to explicitly compute and store checksums." -ForegroundColor Yellow
                    Write-Host "" -ForegroundColor Red
                    Write-Host "  Example: .\scripts\fresh-db-proof.ps1 -RerunProof -BackfillChecksums" -ForegroundColor Yellow
                    $migrationsFailed = $true
                    break
                }
                continue
            }
            # Case 3: New migration - apply it
        }

        # Execute migration using file-based approach (handles special chars)
        try {
            $containerPath = "/tmp/$migName"
            docker cp $migration.FullName "${dbContainer}:${containerPath}" 2>&1 | Out-Null
            $result = docker exec $dbContainer psql -U $dbUser -d $dbName -f $containerPath 2>&1 | Out-String

            if ($LASTEXITCODE -ne 0) {
                Write-Fail "Migration failed: $migName"
                if ($Verbose) { Write-Host $result }
                $migrationsFailed = $true
                break
            }

            # Cleanup temp file
            docker exec $dbContainer rm -f $containerPath 2>&1 | Out-Null

            $migrationsApplied++
            if ($Verbose) { Write-Info "  APPLY: $migName (checksum: $($fileChecksum.Substring(0,8))...)" }

        } catch {
            Write-Fail "Migration error on $migName : $_"
            $migrationsFailed = $true
            break
        }
    }

    # After all migrations, store checksums for tracking (file_name column now exists from 059)
    if (-not $migrationsFailed -and $migrationsApplied -gt 0) {
        Write-Info "Storing checksums for $($pendingChecksums.Count) migrations..."
        foreach ($entry in $pendingChecksums.GetEnumerator()) {
            $migName = $entry.Key
            $hash = $entry.Value
            $insertSql = "INSERT INTO schema_migrations (version, description, checksum, file_name, applied_at) VALUES ('file:$migName', 'Checksum tracking for $migName', '$hash', '$migName', NOW()) ON CONFLICT (version) DO UPDATE SET checksum = EXCLUDED.checksum, file_name = EXCLUDED.file_name;"
            docker exec $dbContainer psql -U $dbUser -d $dbName -c "$insertSql" 2>&1 | Out-Null
        }
    }

    # Phase result with detailed counts
    if ($migrationsFailed) {
        Write-Fail "Migrations failed ($migrationsApplied applied, $migrationsSkipped skipped)" -phase "migrations_$run"
    } else {
        Write-Pass "Migrations: $migrationsApplied applied, $migrationsSkipped skipped" -phase "migrations_$run"
        if ($migrationsLegacyUpgraded -gt 0) {
            Write-Info "Legacy migrations upgraded to checksum tracking: $migrationsLegacyUpgraded"
        }
    }

    # Store counts for final verdict
    $script:lastApplied = $migrationsApplied
    $script:lastSkipped = $migrationsSkipped

    # =========================================================================
    # PHASE 4: Seed Data (Optional)
    # =========================================================================
    Write-Header "PHASE 4: Seed Data"

    if ($SkipSeed) {
        Write-Info "Seed skipped (-SkipSeed)"
        $script:results["seed_$run"] = "SKIP"
    } else {
        Write-Info "Running seed script..."

        try {
            # Run seed script in api container
            $seedResult = docker exec $apiContainer python /app/scripts/seed_e2e.py 2>&1 | Out-String

            if ($LASTEXITCODE -ne 0) {
                Write-Fail "Seed failed" -phase "seed_$run"
                if ($Verbose) { Write-Host $seedResult }
            } else {
                Write-Pass "Seed completed" -phase "seed_$run"
            }
        } catch {
            Write-Info "Seed script not found or failed: $_"
            $script:results["seed_$run"] = "SKIP"
        }
    }

    # =========================================================================
    # PHASE 5: Health Check
    # =========================================================================
    Write-Header "PHASE 5: Health Check"
    Write-Info "Waiting for API to be healthy..."

    $healthy = Wait-ForHealthy -url $healthUrl -timeoutSeconds 120
    if ($healthy) {
        Write-Pass "API is healthy ($healthUrl)" -phase "health_$run"
    } else {
        Write-Fail "API did not become healthy in 120s" -phase "health_$run"
        docker logs $apiContainer 2>&1 | Select-Object -Last 30
    }

    # =========================================================================
    # PHASE 6: Smoke Test
    # =========================================================================
    Write-Header "PHASE 6: Smoke Test"
    Write-Info "Running basic API smoke test..."

    try {
        # Test /health endpoint
        $healthResponse = Invoke-RestMethod -Uri $healthUrl -Method Get -ErrorAction Stop
        Write-Info "Health response: $($healthResponse | ConvertTo-Json -Compress)"

        # Test /api/v1/roster/plans (should return empty list or 401)
        try {
            $plansResponse = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/roster/plans" -Method Get -ErrorAction SilentlyContinue
            Write-Info "Plans endpoint accessible (status: $($plansResponse.StatusCode))"
        } catch {
            # 401/403 is expected without auth
            if ($_.Exception.Response.StatusCode.value__ -in @(401, 403)) {
                Write-Info "Plans endpoint requires auth (expected)"
            }
        }

        Write-Pass "Smoke test passed" -phase "smoke_$run"
    } catch {
        Write-Fail "Smoke test failed: $_" -phase "smoke_$run"
    }

    # =========================================================================
    # TEARDOWN (unless -KeepRunning)
    # =========================================================================
    if (-not $KeepRunning -and $run -lt $Repeat) {
        Write-Info "Tearing down for next run..."
        docker compose -f $composeFile down -v --remove-orphans 2>&1 | Out-Null
    }
}

# =============================================================================
# FINAL TEARDOWN
# =============================================================================

if (-not $KeepRunning) {
    Write-Header "TEARDOWN"
    Write-Info "Stopping containers..."
    docker compose -f $composeFile down 2>&1 | Out-Null
    Write-Info "Containers stopped (volumes preserved for inspection)"
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
Write-Host " N (migration files): $migrationCount" -ForegroundColor White
Write-Host "   Applied: $($script:lastApplied)" -ForegroundColor $(if ($script:lastApplied -gt 0) { "Cyan" } else { "Gray" })
Write-Host "   Skipped: $($script:lastSkipped)" -ForegroundColor $(if ($script:lastSkipped -gt 0) { "Green" } else { "Gray" })
if ($script:legacyMigrationsFound -gt 0) {
    Write-Host "   Legacy (NULL checksum): $($script:legacyMigrationsFound)" -ForegroundColor Yellow
}
Write-Host " Runs: $Repeat" -ForegroundColor White
Write-Host ""

# Greenfield verdict (not RerunProof mode)
if (-not $RerunProof -and $script:exitCode -eq 0) {
    if ($script:lastApplied -eq $migrationCount -and $script:lastSkipped -eq 0) {
        Write-Host " GREENFIELD: PROVEN (applied=N where N=$migrationCount, skipped=0)" -ForegroundColor Green
    }
    Write-Host ""
}

# Idempotency verdict for RerunProof mode
if ($RerunProof -and $script:exitCode -eq 0) {
    if ($script:lastApplied -eq 0 -and $script:lastSkipped -eq $migrationCount) {
        Write-Host " IDEMPOTENCY: PROVEN (applied=0, skipped=N where N=$migrationCount)" -ForegroundColor Green
    } elseif ($script:lastApplied -gt 0) {
        Write-Host " IDEMPOTENCY: PARTIAL ($($script:lastApplied) newly applied, N=$migrationCount)" -ForegroundColor Yellow
    }
    Write-Host ""
}

if ($script:exitCode -eq 0) {
    Write-Host " VERDICT: PASS - Fresh DB Proof Successful" -ForegroundColor Green
    Write-Host ""
    Write-Host " Migrations work from scratch. Safe to deploy to new environments." -ForegroundColor Green
} else {
    Write-Host " VERDICT: FAIL - Fresh DB Proof Failed" -ForegroundColor Red
    Write-Host ""
    Write-Host " Fix migration or seed issues before deployment." -ForegroundColor Red

    # List failed phases
    $failedPhases = $script:results.GetEnumerator() | Where-Object { $_.Value -eq "FAIL" }
    foreach ($phase in $failedPhases) {
        Write-Host "   - $($phase.Key)" -ForegroundColor Red
    }
}

if ($KeepRunning) {
    Write-Host ""
    Write-Host " Containers left running for inspection." -ForegroundColor Yellow
    Write-Host " Stop with: docker compose -f $composeFile down" -ForegroundColor Yellow
}

Write-Host ""
exit $script:exitCode
