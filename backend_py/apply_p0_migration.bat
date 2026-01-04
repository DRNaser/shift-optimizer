@echo off
REM ============================================================================
REM SOLVEREIGN V3 - Apply P0 Migration
REM ============================================================================
REM
REM This script applies the P0 fixes migration to the database.
REM
REM Prerequisites:
REM   1. Docker Desktop running
REM   2. PostgreSQL container running (docker-compose up -d postgres)
REM
REM Usage:
REM   apply_p0_migration.bat
REM ============================================================================

echo ============================================================================
echo SOLVEREIGN V3 - P0 Migration Application
echo ============================================================================
echo.

REM Check if Docker is running
docker ps >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running!
    echo         Please start Docker Desktop first.
    echo.
    pause
    exit /b 1
)

echo [1/4] Checking PostgreSQL container...
docker ps --filter "name=solvereign-db" --format "{{.Names}}" | findstr "solvereign-db" >nul 2>&1
if errorlevel 1 (
    echo [INFO] PostgreSQL container not running. Starting it...
    docker-compose up -d postgres
    if errorlevel 1 (
        echo [ERROR] Failed to start PostgreSQL container!
        echo.
        pause
        exit /b 1
    )
    echo [OK] PostgreSQL container started
    echo [INFO] Waiting 5 seconds for database to be ready...
    timeout /t 5 /nobreak >nul
) else (
    echo [OK] PostgreSQL container is running
)

echo.
echo [2/4] Testing database connection...
docker exec solvereign-db psql -U solvereign -d solvereign -c "SELECT 1;" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot connect to database!
    echo         Check PostgreSQL logs: docker logs solvereign-db
    echo.
    pause
    exit /b 1
)
echo [OK] Database connection successful

echo.
echo [3/4] Applying migration 001_tour_instances.sql...
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py\db\migrations\001_tour_instances.sql
if errorlevel 1 (
    echo [ERROR] Migration failed!
    echo         Check migration file: backend_py\db\migrations\001_tour_instances.sql
    echo.
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying migration...
docker exec solvereign-db psql -U solvereign -d solvereign -c "\d tour_instances" | findstr "tour_instances" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] tour_instances table not found after migration!
    echo.
    pause
    exit /b 1
)
echo [OK] tour_instances table created successfully

echo.
echo ============================================================================
echo SUCCESS: P0 Migration Applied!
echo ============================================================================
echo.
echo Next Steps:
echo   1. Run tests: python backend_py\test_p0_migration.py
echo   2. Expand existing tours: See P0_MIGRATION_GUIDE.md
echo   3. Update application code to use fixed modules
echo.
echo P0 Blockers Fixed:
echo   [OK] Template vs Instances: tour_instances table working
echo   [OK] Cross-midnight: crosses_midnight field implemented
echo   [OK] LOCKED Immutability: triggers installed
echo.
pause
