# SOLVEREIGN - Stability Definition of Done

> **Version**: 1.0
> **Last Updated**: 2026-01-17
> **Status**: ENFORCED

---

## What "Stable" Means

A commit is **stable** if and only if ALL of the following are true:

| # | Gate | Command | Must Pass |
|---|------|---------|-----------|
| 1 | **Local Build + Tests** | `.\scripts\gate-local.ps1` | YES |
| 2 | **Fresh DB Proof** | `.\scripts\fresh-db-proof.ps1` | YES |
| 3 | **CI Pipeline** | GitHub Actions | YES |

If any gate is RED, the commit is **NOT STABLE** - period.

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

# Run 2x for determinism
.\scripts\fresh-db-proof.ps1 -Repeat 2

# Keep containers running for inspection
.\scripts\fresh-db-proof.ps1 -KeepRunning
```

**What it validates:**
- Destroys all Docker volumes (truly fresh)
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

*This document is the single source of truth for stability criteria.*
