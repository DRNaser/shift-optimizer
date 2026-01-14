# SOLVEREIGN Market-Ready Checklist

> **Date**: 2026-01-12
> **Version**: V4.6-market
> **Status**: All P0s RESOLVED

---

## Pass Criteria Summary

| Check | Status | Evidence |
|-------|--------|----------|
| Backend repair sessions canonical | **PASS** | `roster.repairs` table + `repair_sessions.py` |
| Session expiry enforcement (410) | **PASS** | `validate_session_active()` returns HTTP 410 |
| Idempotency on all mutations | **PASS** | create/apply/undo all idempotent |
| BFF thin proxy (no local state) | **PASS** | All repair routes use `lib/bff/proxy.ts` |
| Gate includes backend tests | **PASS** | `gate-critical.ps1` Phase 1: pytest |
| Authenticated E2E test | **PASS** | `e2e/auth-flow.spec.ts` |
| TypeScript compiles | **PASS** | `npx tsc --noEmit` exit 0 |
| E2E credentials required | **PASS** | Gate fails if `SV_E2E_USER/PASS` missing |
| Business invariants E2E | **PASS** | `e2e/roster-business-invariants.spec.ts` |
| baseURL consistency | **PASS** | All tests use `SV_E2E_BASE_URL` with port 3002 |

---

## GO×2 Market-Ready Ritual (3 Commands)

**This is the ONLY way to prove market-readiness from a fresh checkout.**

### Prerequisites

- Docker Desktop installed and running
- Node.js 18+ and Python 3.11+
- PostgreSQL client tools (psql) - for migrations

### The 3-Command Ritual

```powershell
# Command 1: Start pilot stack (DB + migrations + seed + backend + frontend)
.\scripts\pilot-up.ps1

# Command 2: Run gate (first time)
.\scripts\gate-critical.ps1

# Command 3: Run gate again (proves non-flakiness)
.\scripts\gate-critical.ps1
```

**Both gate runs MUST exit with code 0 (GO).**

### What pilot-up.ps1 Does

1. **Starts PostgreSQL** via Docker (`docker-compose.pilot.yml`)
2. **Runs migrations** - applies all SQL files from `backend_py/db/migrations/`
3. **Seeds E2E data** - creates test tenant, site, and platform_admin user
4. **Starts backend** - uvicorn on port 8000
5. **Starts frontend** - next start on port 3002
6. **Creates .env.e2e.local** - with test credentials (auto-loaded by gate)

### Alternative: Manual Setup

If you prefer to manage services yourself:

```powershell
# Terminal 1: Database
docker-compose -f docker-compose.pilot.yml up -d postgres

# Run migrations + seed (same terminal, wait for DB)
.\scripts\run-migrations.ps1
.\scripts\seed-e2e.ps1

# Terminal 2: Backend
cd backend_py
$env:DATABASE_URL = "postgresql://solvereign:pilot_dev_password@localhost:5432/solvereign"
uvicorn api.main:app --port 8000

# Terminal 3: Frontend
cd frontend_v5
npm run build && npm run start -- -p 3002

# Terminal 4: Gate (credentials auto-load from .env.e2e.local)
.\scripts\gate-critical.ps1
.\scripts\gate-critical.ps1
```

### Stopping the Pilot Stack

```powershell
.\scripts\pilot-down.ps1
# Or: Ctrl+C in the pilot-up.ps1 terminal
```

### Verify Reports

```powershell
# Check latest JSON report
Get-ChildItem reports\gate-critical-*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content | ConvertFrom-Json

# Check latest human-readable log
Get-ChildItem reports\gate-critical-*.txt | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content | Select-Object -Last 30
```

**Both runs MUST show:**
- `backend_health: PASS`
- `backend_pytest: PASS`
- `typescript: PASS`
- `frontend_build: PASS`
- `e2e_tests: PASS`

---

## Troubleshooting

### Common Failures and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Docker not found` | Docker Desktop not installed | Install Docker Desktop |
| `psql not found` | PostgreSQL client not installed | `winget install PostgreSQL.PostgreSQL` |
| `Database not ready` | PostgreSQL not started | Check Docker is running, then `docker-compose -f docker-compose.pilot.yml up -d` |
| `E2E credentials missing` | .env.e2e.local not created | Run `.\scripts\seed-e2e.ps1` |
| `Backend NOT ready` | Backend crashed or not started | Check backend logs, ensure DATABASE_URL is correct |
| `Frontend failed to start` | Build error or port in use | Run `npx next build` manually to see errors |
| `E2E tests failed` | Auth or navigation issue | Check `frontend_v5/playwright-report/index.html` for details |
| `TypeScript errors` | Type check failed | Run `cd frontend_v5 && npx tsc --noEmit` for details |

### Diagnostic Commands

```powershell
# Check if PostgreSQL is running
docker ps --filter "name=solvereign-pilot-db"

# Check PostgreSQL health
docker inspect --format='{{.State.Health.Status}}' solvereign-pilot-db

# Test database connection
psql "postgresql://solvereign:pilot_dev_password@localhost:5432/solvereign" -c "SELECT 1"

# Check backend health
Invoke-WebRequest -Uri "http://localhost:8000/health/ready" -UseBasicParsing | Select-Object -ExpandProperty Content

# Check frontend is running
Invoke-WebRequest -Uri "http://localhost:3002" -UseBasicParsing -TimeoutSec 2

# View E2E credentials
Get-Content .env.e2e.local
```

### Clean Restart

If things are in a bad state:

```powershell
# Stop everything and remove data
.\scripts\pilot-down.ps1

# Remove Docker volume (full reset)
docker volume rm solvereign-pilot-db-data

# Start fresh
.\scripts\pilot-up.ps1
```

---

## Gate Command Details

**Exit Codes:**
| Code | Verdict | Meaning |
|------|---------|---------|
| `0` | **GO** | All phases PASS - safe to deploy |
| `1` | **FAST** | One or more phases FAIL - fix failures first |
| `2` | **NO-GO (INCOMPLETE)** | One or more phases SKIP - NOT valid for market-ready |

**Reports Generated:**
- `reports/gate-critical-YYYYMMDD-HHMMSS.json` - Machine-readable phase results
- `reports/gate-critical-YYYYMMDD-HHMMSS.txt` - Human-readable log

### Mandatory Requirements

- **Backend must be running** at `http://localhost:8000/health/ready`
- **Frontend must be running** at `http://localhost:3002` (or gate auto-starts it)
- **E2E credentials must be set**: `SV_E2E_USER` and `SV_E2E_PASS` env vars

### Development Mode (NOT for market-ready)

```powershell
# Skip flags for local dev only - verdict will be NO-GO (INCOMPLETE)
$env:SV_SKIP_BACKEND_HEALTH = "1"
$env:SV_SKIP_E2E = "1"
.\scripts\gate-critical.ps1
```

---

## What This Gate Runs

| Phase | Check | Must Pass |
|-------|-------|-----------|
| 1 | **Backend Health** - `/health/ready` (DB + packs) | YES |
| 2 | **Backend Pytest** - `backend_py/packs/roster/tests` | YES |
| 3 | **TypeScript Check** - `npx tsc --noEmit` | YES |
| 4 | **Frontend Build** - `npx next build` | YES |
| 5 | **Critical E2E** - auth, platform, roster workflows | YES |

---

## Repair Session Lifecycle (Backend Canonical)

```
POST /api/v1/roster/repairs/sessions
  → Creates session in roster.repairs (advisory lock)
  → Returns session_id + expires_at

POST /api/v1/roster/repairs/{sessionId}/preview
  → Validates session OPEN + not expired
  → Computes pin conflicts + violation deltas
  → Extends session expiry

POST /api/v1/roster/repairs/{sessionId}/apply
  → Validates session OPEN + not expired (HTTP 410 if expired)
  → Checks plan not locked (HTTP 409 if locked)
  → Checks no pin conflicts (HTTP 409 if conflicts)
  → Applies actions with idempotency key
  → Invalidates violations cache

POST /api/v1/roster/repairs/{sessionId}/undo
  → Validates session + not published since start
  → Idempotent via x-idempotency-key header
  → Marks action as undone (audit trail preserved)
  → Extends session expiry

POST /api/v1/roster/repairs/{sessionId}/abort
  → Marks session ABORTED
  → Discards unapplied actions
```

---

## Security Guarantees

| Guarantee | Enforcement |
|-----------|-------------|
| Tenant isolation | RLS + belt+suspenders validation in `repair_sessions.py` |
| Session ownership | tenant_id + site_id from user context, never headers |
| Expiry enforcement | Server-side check with HTTP 410 response |
| Idempotency | DB-backed via `core.idempotency_keys` |
| Audit trail | `roster.audit_notes` (immutable) |

---

## Files Changed (This Release)

### BFF Routes (Now Thin Proxy)
- `app/api/roster/repairs/sessions/route.ts` - Create session
- `app/api/roster/repairs/[sessionId]/route.ts` - Get session status
- `app/api/roster/repairs/[sessionId]/apply/route.ts` - Apply actions
- `app/api/roster/repairs/[sessionId]/preview/route.ts` - Preview action
- `app/api/roster/repairs/[sessionId]/undo/route.ts` - Undo action
- `app/api/roster/repair/preview/route.ts` - Legacy preview (uses proxy)

### Infrastructure
- `lib/bff/proxy.ts` - Centralized BFF proxy helper
- `scripts/gate-critical.ps1` - Market-ready gate with backend tests
- `e2e/auth-flow.spec.ts` - Authenticated E2E test

### Documentation
- `docs/BLINDSPOT_ANALYSIS_2026-01-12.md` - Updated with RESOLVED status
- `docs/MARKET_READY_CHECKLIST.md` - This file

---

## Running Authenticated E2E

```bash
# Set credentials
export SV_E2E_USER=your-test-user@example.com
export SV_E2E_PASS=your-test-password

# Run authenticated flow
cd frontend_v5
npx playwright test e2e/auth-flow.spec.ts
```

---

## Verification Commands

```bash
# Backend tests
cd backend_py && python -m pytest packs/roster/tests -v

# Frontend type check
cd frontend_v5 && npx tsc --noEmit

# Frontend build
cd frontend_v5 && npx next build

# Critical E2E (requires frontend running)
cd frontend_v5 && npm run e2e:critical

# Full gate (recommended)
.\scripts\gate-critical.ps1
```

---

## Known Remaining Items (P1/P2)

| Item | Severity | Notes |
|------|----------|-------|
| State transition trigger | P1 | No DB trigger prevents invalid plan_version transitions |
| Snapshot immutability test | P2 | Relies on SQL function, needs explicit test |
| Constraint validation tests | P2 | Max tours/day, rest time, weekly hours need verification |

These are tracked in `docs/BLINDSPOT_ANALYSIS_2026-01-12.md` and do not block market deployment.

---

*Generated: 2026-01-12*
