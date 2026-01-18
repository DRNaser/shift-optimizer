# Wien Pilot - Dry Run Execution Runbook

> **Version**: 1.0
> **Last Updated**: 2026-01-18
> **Status**: READY FOR EXECUTION

---

## Purpose

This runbook provides step-by-step instructions for executing a dry run of the Wien Pilot E2E flow:

```
IMPORT → SOLVE → AUDIT → FREEZE → EVIDENCE
```

---

## Preconditions

### 1. Infrastructure Ready

```powershell
# Verify Docker stack is running
docker compose -f docker-compose.pilot.yml ps

# Expected: postgres (healthy), api (running)
```

### 2. Migrations Applied

```powershell
# Verify all migrations applied
docker compose -f docker-compose.pilot.yml exec postgres psql -U solvereign -d solvereign -c "SELECT count(*) FROM schema_migrations;"
# Expected: 71 (or current migration count)
```

### 3. Verify Gates Pass

```powershell
docker compose -f docker-compose.pilot.yml exec postgres psql -U solvereign -d solvereign -c "SELECT * FROM verify_pass_gate();"
# Expected: All passed=true, non_pass_count=0
```

### 4. FLS Export File Ready

Place FLS export file at:
```
artifacts/input/fls_export_YYYY-MM-DD.csv
```

Validate format against [FLS_IMPORT_CONTRACT.md](./FLS_IMPORT_CONTRACT.md).

---

## Execution Steps

### Step 1: Import Orders

```powershell
# Set environment
$DATE = "2026-01-20"
$INPUT_FILE = "artifacts/input/fls_export_$DATE.csv"

# Run import
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.import_orders --input $INPUT_FILE --date $DATE

# Expected output:
# Import completed: 150 orders imported, 2 rejected, 0 warnings
```

**Pass Criteria**:
- Exit code 0
- All valid orders imported
- Rejections have valid reason codes (see contract)

**Failure Action**:
- Check `artifacts/logs/import_$DATE.log`
- Validate CSV against contract
- Fix data issues, re-import

### Step 2: Solve Roster

```powershell
# Run solver
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.solve --date $DATE --seed 94 --time-budget 120

# Expected output:
# Solve completed in 45.2s
# Total tours: 150, Assigned: 150 (100%)
# Drivers: 52, Blocks: 78
```

**Pass Criteria**:
- Exit code 0
- 100% tour coverage
- No BLOCK constraint violations
- Solve time < 120s

**Failure Action**:
- Capture `trace_id` from output
- Save logs: `docker compose logs api > artifacts/logs/solve_$DATE.log`
- Check for constraint violations in output

### Step 3: Audit Plan

```powershell
# Run audit
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.audit --date $DATE

# Expected output:
# Audit PASSED
# Violations: 0 BLOCK, 0 SOFT
# Coverage: 100%
```

**Pass Criteria**:
- Exit code 0
- 0 BLOCK violations
- SOFT violations within allowlist (if any)

**Failure Action**:
- If BLOCK violations: DO NOT proceed
- Log violation details
- Manual review required

### Step 4: Export Evidence

```powershell
# Export evidence bundle
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.export_evidence --date $DATE --output artifacts/evidence/

# Expected output:
# Evidence bundle exported to artifacts/evidence/evidence_2026-01-20.json
# Hash: SHA256:abc123...
```

**Pass Criteria**:
- Evidence file created
- Contains: assignments, drivers, tours, audit_result
- SHA256 hash matches database record

**Failure Action**:
- Check disk space
- Verify database connectivity

### Step 5: Freeze Day

```powershell
# Freeze the day (makes plan read-only)
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.freeze_day --date $DATE

# Expected output:
# Day 2026-01-20 frozen at 2026-01-20T15:30:00+01:00
# Plan version: v1
# Lock status: LOCKED
```

**Pass Criteria**:
- Exit code 0
- Day status changes to LOCKED
- No further edits allowed

**Failure Action**:
- If freeze fails: Check for pending edits
- Resolve conflicts before freeze

### Step 6: Verify Evidence Parity

```powershell
# Verify evidence matches database
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.verify_evidence --file artifacts/evidence/evidence_$DATE.json

# Expected output:
# Evidence parity: VERIFIED
# Assignments match: 78/78
# Hash verified: OK
```

**Pass Criteria**:
- All IDs match database
- Hash matches
- No drift detected

---

## Quick Reference Commands

```powershell
# Full dry run (all steps)
$DATE = "2026-01-20"

# 1. Import
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.import_orders --input artifacts/input/fls_export_$DATE.csv --date $DATE

# 2. Solve
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.solve --date $DATE --seed 94 --time-budget 120

# 3. Audit
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.audit --date $DATE

# 4. Export
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.export_evidence --date $DATE --output artifacts/evidence/

# 5. Freeze
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.freeze_day --date $DATE

# 6. Verify
docker compose -f docker-compose.pilot.yml exec api python -m packs.roster.tools.verify_evidence --file artifacts/evidence/evidence_$DATE.json
```

---

## Escalation Matrix

| Issue | Severity | Action | Contact |
|-------|----------|--------|---------|
| Import parse error | LOW | Fix CSV, retry | Ops Team |
| Solve timeout | MEDIUM | Increase budget, check constraints | Tech Lead |
| BLOCK violation | HIGH | Manual review, DO NOT freeze | Tech Lead + Ops |
| Evidence mismatch | CRITICAL | STOP, investigate drift | Tech Lead |
| Verify gate fails | CRITICAL | STOP, run diagnostics | Tech Lead |

---

## Output Artifacts

After successful dry run, the following artifacts should exist:

```
artifacts/
├── input/
│   └── fls_export_2026-01-20.csv      # Input file
├── logs/
│   ├── import_2026-01-20.log          # Import log
│   ├── solve_2026-01-20.log           # Solve log
│   └── audit_2026-01-20.log           # Audit log
├── evidence/
│   └── evidence_2026-01-20.json       # Evidence bundle
└── reports/
    └── dry_run_report_2026-01-20.md   # Summary report
```

---

## Post-Run Checklist

```
[ ] All 6 steps completed successfully
[ ] 0 BLOCK violations
[ ] Evidence bundle created and verified
[ ] Day frozen (read-only)
[ ] Artifacts saved
[ ] Report generated
```

---

*This runbook is the single source of truth for Wien Pilot dry run execution.*
