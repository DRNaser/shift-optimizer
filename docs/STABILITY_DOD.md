# SOLVEREIGN - Stability Definition of Done

> **Version**: 1.1
> **Last Updated**: 2026-01-18
> **Status**: ENFORCED
> **Proof Tag**: `pilot-verification-green-20260118`

---

## What "Stable" Means

A commit is **stable** if and only if ALL of the following are true:

| # | Gate | Command | Must Pass |
|---|------|---------|-----------|
| 1 | **Local Build + Tests** | `.\scripts\gate-local.ps1` | YES |
| 2 | **Fresh DB Proof** | `.\scripts\fresh-db-proof.ps1` | BLOCKED* |
| 3 | **CI Pipeline** | GitHub Actions | YES |

If any gate is RED, the commit is **NOT STABLE** - period.

> **\*FIXED (2026-01-18)**: Fresh DB Proof now passes. See [PILOT_VERIFICATION_PROOF_2026-01-18.md](./PILOT_VERIFICATION_PROOF_2026-01-18.md).
> Migration chain repaired, 71 migrations apply cleanly from scratch.

---

## Source of Truth Commands

### 1. Local Stability Gate

```powershell
# Full gate (recommended before merge)
.\scripts\gate-local.ps1

# Quick backend-only (for iteration)
.\scripts\gate-local.ps1 -SkipFrontend

# With verbose output
.\scripts\gate-local.ps1 -Verbose
```

**What it validates:**
- Git working directory is clean
- Backend pytest passes (critical suites)
- Frontend: `npm ci` + `tsc --noEmit` + `next build`

**Exit codes:**
- `0` = PASS (safe to merge)
- `1` = FAIL (do NOT merge)

### 2. Fresh DB Proof

```powershell
# Full proof (recommended for migration PRs)
.\scripts\fresh-db-proof.ps1

# Run 2x for determinism (destroys between runs)
.\scripts\fresh-db-proof.ps1 -Repeat 2

# Keep containers running for inspection
.\scripts\fresh-db-proof.ps1 -KeepRunning

# Rerun proof: test idempotency on EXISTING DB (no destroy)
.\scripts\fresh-db-proof.ps1 -RerunProof -KeepRunning
```

**What it validates:**
- Destroys all Docker volumes (truly fresh) - skipped with `-RerunProof`
- Starts postgres + api from scratch
- Applies ALL migrations in order
- Runs seed (optional)
- API health check passes
- Basic smoke test

**Exit codes:**
- `0` = PASS (migrations work from scratch)
- `1` = FAIL (broken migrations)

### 3. CI Pipeline

CI runs automatically on PR and push to main:
- `pytest-suite`: Backend tests (BLOCKING)
- `frontend-build`: TypeScript + Next.js build (BLOCKING)
- `quality-gate`: Solver smoke test

---

## Release Gates (Defined)

### GREENFIELD_GATE (New Environment Deployment)

**Use case**: Deploying to a completely new environment (no existing data).

**Execution sequence**:
```powershell
# Step 1: Fresh DB Proof
.\scripts\fresh-db-proof.ps1 -KeepRunning
# AKZEPTANZ: Exit 0

# Step 2: Determinism Proof (rerun on same DB = no-op)
.\scripts\fresh-db-proof.ps1 -RerunProof -KeepRunning
# AKZEPTANZ: Exit 0, migrations already applied (no changes)

# Step 3: Verify Functions (SQL integrity checks)
docker compose -f docker-compose.pilot.yml exec postgres psql -U solvereign -d solvereign -c "SELECT * FROM verify_pass_gate();"
# AKZEPTANZ: 0 non-pass rows (see Verify Gate Queries below)
```

**DoD**:
- [ ] `fresh-db-proof.ps1` = 0
- [ ] `fresh-db-proof.ps1 -RerunProof` = 0 (idempotent)
- [ ] All verify functions return 0 non-PASS rows

---

### UPGRADE_GATE (Existing Environment Upgrade)

**Use case**: Upgrading staging/production (existing data, no `down -v`).

**Execution sequence** (no script needed - manual process):
```powershell
# Step 1: Deploy new code (staging)
# git pull && docker compose up -d --build

# Step 2: Migrations run automatically via entrypoint
# OR manually: docker compose exec api python -m alembic upgrade head

# Step 3: Smoke test (Auth + UI)
curl -s http://localhost:8000/health | jq
# AKZEPTANZ: {"status": "healthy"}

# Step 4: Verify Functions
docker compose exec postgres psql -U solvereign -d solvereign -c "SELECT * FROM verify_pass_gate();"
# AKZEPTANZ: 0 non-pass rows
```

**DoD**:
- [ ] Migrations applied without error
- [ ] `/health` returns 200
- [ ] Auth login works (manual smoke)
- [ ] All verify functions return 0 non-PASS rows

**Note**: No `upgrade-proof.ps1` script exists. This gate is defined as a **process** for staging deployments.

---

## What is FORBIDDEN

To prevent instability, the following are **FORBIDDEN**:

### Branch Policy
- **NO worktrees** (except for explicit, temporary use)
- **NO branch farms** (max 1 feature branch at a time)
- **NO `codex/*` branches** pushed to remote
- **NO parallel migrations** without coordination

### Merge Policy
- **NO merge without green CI**
- **NO merge without `gate-local.ps1` pass**
- **NO migration PR without `fresh-db-proof.ps1` pass**
- **NO skipping tests without allowlist entry**

### Remote Policy
- `main` is the ONLY permanent branch
- Feature branches are deleted after merge
- Tags are preserved (safety-*, stable-*)

---

## Skip Allowlist

Some tests may be temporarily skipped. These MUST be documented in:
```
scripts/gate/allow_skips.json
```

Each skip requires:
- `test_file`: Name of skipped test
- `reason`: Why it's skipped
- `owner`: Who is responsible
- `expiry`: When the skip expires
- `severity`: LOW/MEDIUM/HIGH
- `pilot_blocking`: true/false

**Rule**: Expired skips cause gate FAILURE.

---

## Migration Rules

1. **One migration PR at a time**
   - No parallel migration branches
   - Coordinate with team before creating

2. **Fresh DB proof required**
   - Every migration PR must include `fresh-db-proof.ps1` screenshot
   - Or CI equivalent (Fresh DB Nightly job)

3. **No migration edits after merge**
   - Once merged, migrations are immutable
   - Fixes require NEW migrations

---

## Recovery Points

Safety tags exist for rollback:

| Tag | Purpose |
|-----|---------|
| `safety-main-YYYYMMDD` | Pre-operation backup of main |
| `stable-post-*` | Known stable state |

To rollback:
```bash
# View tags
git tag -l "safety-*"
git tag -l "stable-*"

# Restore from tag (creates new branch for review)
git checkout -b recovery/from-tag safety-main-20260117
```

---

## Checklist for PRs

Before creating a PR, verify:

```
[ ] git status shows clean working directory
[ ] .\scripts\gate-local.ps1 returns 0
[ ] If migration: .\scripts\fresh-db-proof.ps1 returns 0
[ ] No new codex/* branches created
[ ] No worktrees left behind
```

Before merging a PR, verify:

```
[ ] All CI checks are green
[ ] No "continue-on-error" hacks in CI
[ ] Reviewer approved
[ ] Branch will be deleted after merge
```

---

## Definition of Done: Summary

| Condition | Required |
|-----------|----------|
| `gate-local.ps1` = 0 | YES |
| `fresh-db-proof.ps1` = 0 (if migrations) | YES |
| CI green | YES |
| No worktrees | YES |
| No branch farms | YES |
| Reviewer approved | YES |

**If ALL conditions are met, the commit is STABLE.**

---

## Database Integrity Gates (Added 2026-01-17)

In addition to build/test gates, the following SQL verify functions MUST pass:

### Migration Count Definition

**N = count(backend_py/db/migrations/*.sql)**

N is computed dynamically at runtime by `fresh-db-proof.ps1`. Never hardcode migration counts.

| Gate | Pass Criterion |
|------|---------------|
| **Greenfield** | applied=N, skipped=0 |
| **RerunProof** | applied=0, skipped=N |

### Required Verify Functions

| Function | Checks | PASS Criterion |
|----------|--------|----------------|
| `auth.verify_rbac_integrity()` | ~16 | 0 non-PASS rows |
| `masterdata.verify_masterdata_integrity()` | ~9 | 0 non-PASS rows |
| `verify_final_hardening()` | 8-17 | 0 FAIL rows (WARN allowed) |
| `portal.verify_portal_integrity()` | ~8 | 0 non-PASS rows |
| `dispatch.verify_dispatch_integrity()` | ~12 | 0 non-PASS rows |

> **Note**: Check counts are approximate and may change as verify functions are enhanced. These are **integrity checks**, not migration counts.

### Pass Criteria (EXAKT)

- **PASS**: `non_pass_count = 0`
- **WARN**: Allowed for `verify_final_hardening()` only (security policy docs)
- **FAIL**: Any `non_pass_count > 0` on critical functions
- **Exception**: Any SQL exception = **IMMEDIATE RED** (gate blocked)

### Verify Gate Queries (Copy-Paste Ready)

```sql
-- ============================================================
-- VERIFY GATE: Run these queries. ALL must return 0.
-- ============================================================

-- 1. auth.verify_rbac_integrity (16 checks)
SELECT count(*) AS non_pass FROM auth.verify_rbac_integrity() WHERE status <> 'PASS';
-- AKZEPTANZ: 0

-- 2. masterdata.verify_masterdata_integrity (9 checks)
SELECT count(*) AS non_pass FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS';
-- AKZEPTANZ: 0

-- 3. verify_final_hardening (8-17 checks, WARN allowed)
SELECT count(*) AS fail_count FROM verify_final_hardening() WHERE status = 'FAIL';
-- AKZEPTANZ: 0 (WARN rows are acceptable)

-- 4. portal.verify_portal_integrity (8 checks)
SELECT count(*) AS non_pass FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS';
-- AKZEPTANZ: 0

-- 5. dispatch.verify_dispatch_integrity (12 checks)
SELECT count(*) AS non_pass FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS';
-- AKZEPTANZ: 0
```

### Combined Gate Check (Single Query)

```sql
-- Returns TRUE only if ALL gates pass
SELECT
    (SELECT count(*) FROM auth.verify_rbac_integrity() WHERE status <> 'PASS') = 0 AS auth_ok,
    (SELECT count(*) FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS') = 0 AS masterdata_ok,
    (SELECT count(*) FROM verify_final_hardening() WHERE status = 'FAIL') = 0 AS hardening_ok,
    (SELECT count(*) FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS') = 0 AS portal_ok,
    (SELECT count(*) FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS') = 0 AS dispatch_ok;
-- AKZEPTANZ: Alle Spalten = true
```

### Running All Verify Functions (Full Output)

```sql
-- Run all verify functions (after migrations) - for debugging
SELECT 'auth.verify_rbac_integrity' AS fn, * FROM auth.verify_rbac_integrity()
UNION ALL
SELECT 'masterdata.verify_masterdata_integrity', check_name, status, details FROM masterdata.verify_masterdata_integrity()
UNION ALL
SELECT 'verify_final_hardening', test_name, status, actual FROM verify_final_hardening()
UNION ALL
SELECT 'portal.verify_portal_integrity', check_name, check_status, details FROM portal.verify_portal_integrity()
UNION ALL
SELECT 'dispatch.verify_dispatch_integrity', check_name, check_status, details FROM dispatch.verify_dispatch_integrity();
```

---

## Expected Test Failures (xfail) - Wien Pilot

The following tests are marked `@pytest.mark.xfail` and are **NOT blocking** for Wien Pilot:

| Test | Reason | Backlog |
|------|--------|---------|
| `test_simulation.py::test_all_scenarios_return_correct_types` | MaxHoursPolicyResult not exported | SIM-001 |
| `test_simulation.py::test_tour_cancel_more_than_available` | Uses full dataset internally | SIM-002 |
| `test_simulation.py::test_multi_failure_cascade_no_cascade` | Cascade logic bug | SIM-003 |
| `test_simulation.py::test_probabilistic_churn_basic` | num_simulations param ignored | SIM-004 |
| `test_simulation.py::test_policy_roi_optimizer_basic` | optimize_for param ignored | SIM-005 |
| `test_simulation.py::test_policy_roi_optimizer_stability_focus` | optimize_for param ignored | SIM-005 |

**Rule**: These xfails are acceptable because:
1. Simulation engine is NOT used in Wien Pilot (Phase 2 feature)
2. Each has a backlog reference for future fix
3. Core roster/solver tests are 100% green

**Action Required**: Before Phase 2 (Simulation features), remove xfails by fixing engine incompatibilities.

---

## Out of Scope - Wien Pilot

The following features are explicitly **OUT OF SCOPE** for Wien Pilot release:

| Feature | Schema | Status | Reason |
|---------|--------|--------|--------|
| **Entra ID / OIDC** | - | DEFERRED | Internal RBAC is default (AUTH_MODE=rbac) |
| Notification Pipeline | `notify.*` | DEFERRED | Phase 2 - WhatsApp/Email integration |
| Routing Pack | `routing.*` | PLACEHOLDER | Coming Soon - VRPTW optimization |

These features may have migrations deployed but are NOT part of release criteria.

### Auth Mode: RBAC Only (Wien Pilot)

**Wien Pilot uses internal RBAC authentication only (AUTH_MODE=rbac).**

| Mode | ENV Variable | Status |
|------|--------------|--------|
| **RBAC** | `AUTH_MODE=rbac` | **DEFAULT** - Email/password via `auth.*` schema |
| Entra ID | `AUTH_MODE=entra` | DEFERRED - Microsoft SSO for Phase 2 |

**Consequences:**
- Entra-specific tests are SKIPPED in gate-local.ps1
- `test_entra_tenant_mapping.py` is conditionally skipped
- No OIDC/JWT issuer validation required
- Platform Admin login uses internal RBAC only

---

## Wien Pilot Runbook (Explicit Scope)

### What IS in scope:

| Feature | Schema | DoD |
|---------|--------|-----|
| Authentication | `auth.*` | verify_rbac_integrity() = 0 non-PASS |
| Master Data | `masterdata.*` | verify_masterdata_integrity() = 0 non-PASS |
| Driver Portal | `portal.*` | verify_portal_integrity() = 0 non-PASS |
| Dispatch Assist | `dispatch.*` | verify_dispatch_integrity() = 0 non-PASS |
| Security Hardening | `public.*` | verify_final_hardening() = 0 FAIL |

### What is NOT in scope:

| Feature | Consequence |
|---------|-------------|
| `notify.*` (WhatsApp/Email) | **Keine Fahrerbenachrichtigung** via App. Magic Links per manuellem Versand. |
| `routing.*` (VRPTW) | Routing-Optimierung deaktiviert. Nur statische Touren. |

### Hard Decision: Notify

**Wien Pilot läuft OHNE automatische Fahrerbenachrichtigung.**

- Migrations 034-038 sind deployed (Schema existiert)
- ABER: Keine RLS/RBAC-Validierung erforderlich
- ABER: Kein Smoke-Flow (WhatsApp/Email) erforderlich
- `notify.verify_notification_integrity()` wird **NICHT** als Gate geprüft

**Wenn Notify benötigt wird (Phase 2)**:
1. Migration deployed ✓ (bereits geschehen)
2. RLS/RBAC verifiziert (neues Gate hinzufügen)
3. Smoke-Flow: Test-Notification via WhatsApp/Email
4. Dann: `notify.verify_notification_integrity()` als Pflicht-Gate

---

## Migration Chain Status (2026-01-18)

### Status: REPAIRED

Migration chain was fully repaired on 2026-01-18. All 71 migrations now apply cleanly from scratch.

**Proof**: See [PILOT_VERIFICATION_PROOF_2026-01-18.md](./PILOT_VERIFICATION_PROOF_2026-01-18.md)

| Gate | Result |
|------|--------|
| Greenfield | 71 applied, exit 0 |
| Idempotency | 0 applied, 71 skipped |
| verify_pass_gate() | 5/5 PASS |

### Bootstrap Migration

`000a_bootstrap_fixes.sql` was created to fix critical ordering issues:

| Bug | Description | Fix |
|-----|-------------|-----|
| audit_log missing | 000 creates `audit_logs`, 004/010 expect `audit_log` | Creates `audit_log` table |
| Roles missing | solvereign_admin created in 010 but referenced by 039 | Creates roles early |
| Version column too small | schema_migrations.version is VARCHAR(20) | Uses VARCHAR(50) |

See [MIGRATION_CHAIN_FIX_REPORT.md](./MIGRATION_CHAIN_FIX_REPORT.md) for full historical analysis.

---

*This document is the single source of truth for stability criteria.*
