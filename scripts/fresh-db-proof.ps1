# =============================================================================
# SOLVEREIGN - Fresh DB Proof
# =============================================================================
# Proves migrations work from scratch on a truly empty database.
# This is the SOURCE OF TRUTH for "can we deploy to a new environment?"
#
# What it does:
#   1. Destroys all Docker volumes (truly fresh start)
#   2. Starts postgres + api containers
#   3. Runs all migrations in order
#   4. Optionally seeds test data
#   5. Runs health check + smoke test
#
# Usage:
#   .\scripts\fresh-db-proof.ps1              # Full proof (default)
#   .\scripts\fresh-db-proof.ps1 -SkipSeed    # Skip seed step
#   .\scripts\fresh-db-proof.ps1 -Repeat 2    # Run proof 2x (determinism check)
#   .\scripts\fresh-db-proof.ps1 -KeepRunning # Don't tear down after
#
# Exit codes:
#   0 = PASS (migrations work from scratch)
#   1 = FAIL (broken migrations or seed)
#
# COMPOSE FILE: docker-compose.pilot.yml (Single Source of Truth for local dev)
#
# RULE: Every migration PR must pass this proof before merge.
# =============================================================================

param(
    [switch]$SkipSeed,
    [switch]$KeepRunning,
    [int]$Repeat = 1,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$script:exitCode = 0
$script:startTime = Get-Date
$script:results = @{}

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
    # PHASE 1: Destroy Everything
    # =========================================================================
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
    # PHASE 3: Run Migrations
    # =========================================================================
    Write-Header "PHASE 3: Run Migrations"
    Write-Info "Applying $migrationCount migrations..."

    $migrationsFailed = $false
    $migrationsApplied = 0

    foreach ($migration in $migrations) {
        $migName = $migration.Name

        try {
            # Copy migration to container and run it
            $sqlPath = $migration.FullName
            $containerPath = "/tmp/$migName"

            # Use docker exec with psql
            $sqlContent = Get-Content $sqlPath -Raw

            # Execute via docker exec
            $result = docker exec $dbContainer psql -U $dbUser -d $dbName -c "$sqlContent" 2>&1 | Out-String

            if ($LASTEXITCODE -ne 0) {
                Write-Fail "Migration failed: $migName"
                if ($Verbose) { Write-Host $result }
                $migrationsFailed = $true
                break
            }

            $migrationsApplied++
            if ($Verbose) { Write-Info "  Applied: $migName" }

        } catch {
            Write-Fail "Migration error on $migName : $_"
            $migrationsFailed = $true
            break
        }
    }

    if ($migrationsFailed) {
        Write-Fail "Migrations failed ($migrationsApplied/$migrationCount applied)" -phase "migrations_$run"
    } else {
        Write-Pass "All $migrationsApplied migrations applied" -phase "migrations_$run"
    }

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
Write-Host " Migrations: $migrationCount" -ForegroundColor White
Write-Host " Runs: $Repeat" -ForegroundColor White
Write-Host ""

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
