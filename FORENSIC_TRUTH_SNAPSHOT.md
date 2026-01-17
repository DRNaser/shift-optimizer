# FORENSIC TRUTH SNAPSHOT
## PR #15: cleanup/pr4-deterministic-solver → main
**Generated**: 2026-01-17T07:31:00+01:00  
**SHA at Verification**: `22abfc294801713d8198fb49ffcb52daa13ec862`

---

## 1. Identity & Git State

### 1.1 Remote Configuration
```
origin  https://github.com/DRNaser/shift-optimizer.git (fetch)
origin  https://github.com/DRNaser/shift-optimizer.git (push)
```
**VERDICT**: ✅ PASS - Correct repository

### 1.2 Branch State
| Property | Value |
|----------|-------|
| Current Branch | `cleanup/pr4-deterministic-solver` |
| Local HEAD | `22abfc294801713d8198fb49ffcb52daa13ec862` |
| origin/main | `17690dec0338cef4ef7671bd9353993342f1e73c` |
| origin/cleanup/pr4-deterministic-solver | `22abfc294801713d8198fb49ffcb52daa13ec862` |
| Working Tree | **CLEAN** (after reset) |

**VERDICT**: ✅ PASS - Local matches remote, no uncommitted changes

### 1.3 Commit History (HEAD~10)
```
22abfc2 fix(ci): correct roster_matrix.csv path in quality gate
19f15b4 fix(ci): convert forecast_ci_test.csv to parser-compatible format
c215940 gate: make CleanCut pass (remove legacy imports in tests)
e999f36 ci(migration): add tenant_id to forecast_compositions and tour_removals
c5aea7f ci(deps): add asyncpg for schema invariant tests
b870fe4 fix(solver): use instance_number not DB ID for canonical tie-break (A3)
11ab463 feat(solver): add PR-4 addendum - cross-process proof + canonical fingerprint
d3f519f feat(solver): add PR-4 addendum - cross-process proof + canonical fingerprint
9ecf8d9 feat(solver): replace randomized greedy with deterministic engine (PR-4)
63ed3f9 cleanup(pr3): move v3 to packs/roster/engine, eliminate global v3 imports
```

---

## 2. Cleanup Truth

### 2.1 Legacy File Removal
| File/Directory | Expected | Actual | Status |
|----------------|----------|--------|--------|
| `backend_py/streamlit_app.py` | NOT EXIST | NOT FOUND | ✅ PASS |
| `backend_py/cli.py` | NOT EXIST | NOT FOUND | ✅ PASS |
| `requirements.txt` (root) | NOT EXIST | NOT FOUND | ✅ PASS |
| `backend_py/src/` | NOT EXIST | NOT FOUND | ✅ PASS |
| `backend_py/v3/` | NOT EXIST | NOT FOUND | ✅ PASS |

### 2.2 SOLVEREIGN Structure Exists
| Directory | Status |
|-----------|--------|
| `backend_py/packs/roster/engine/` | ✅ EXISTS (solver relocated here) |
| `backend_py/packs/roster/tools/` | ✅ EXISTS |
| `scripts/gate/gate-clean-cut.ps1` | ✅ EXISTS |

### 2.3 Import Scan Results
| Import Pattern | Production Code Hits | Status |
|----------------|---------------------|--------|
| `from v3.` / `import v3.` | 0 (only in docs/markdown) | ✅ PASS |
| `from backend_py.v3` / `import backend_py.v3` | 0 (only in README.md) | ✅ PASS |
| `from src.` / `import src.` | 4 (in src_compat legacy + docs) | ⚠️ ACCEPTABLE |
| `streamlit` | 0 production, ~30 docs/deprecation notes | ✅ PASS |

> **Note**: `src_compat/` files contain legacy V2 solver code with internal `src.` imports - these are **inert** (not imported by production code).

### 2.4 Packaging Truth
**pyproject.toml packages**:
```toml
packages = ["api", "packs", "db"]
```
- ✅ No `src/` or `v3/` packages exported

**Dockerfile COPYs**:
```dockerfile
COPY api/ ./api/
COPY packs/ ./packs/
COPY db/ ./db/
```
- ✅ No legacy directories copied

**VERDICT**: ✅ PASS - Cleanup complete, SOLVEREIGN-only structure

---

## 3. Determinism Truth

### 3.1 Random Usage Scan
| File | Random Usage | Context | Risk |
|------|--------------|---------|------|
| `solver_v2_integration.py` | **NONE** | Main solver - deterministic | ✅ SAFE |
| `solver_wrapper.py:759` | `random.shuffle` | In `_create_dummy_assignments()` fallback only | ⚠️ LOW (seeded) |
| `test_duplicate_instance_tiebreak.py` | `random.shuffle` | Test file only | ✅ N/A |
| `src_compat/block_heuristic_solver.py` | `import random` | Legacy V2 code | ⚠️ LOW |

### 3.2 Determinism Test Execution
```
======================================================================
 SOLVEREIGN Solver Determinism Proof Test
======================================================================

[Setup] Created 38 tour instances across 7 days

[Run 1/3] Running solver...
[Partitioning] DETERMINISTIC mode, 38 tours...
[Run 1/3] Hash: 73fb8941ad950be6... | Assignments: 38 | Drivers: 4

[Run 2/3] Running solver...
[Run 2/3] Hash: 73fb8941ad950be6... | Assignments: 38 | Drivers: 4

[Run 3/3] Running solver...
[Run 3/3] Hash: 73fb8941ad950be6... | Assignments: 38 | Drivers: 4

======================================================================
 [PASS] DETERMINISM PROOF: All runs produced identical output
======================================================================
```

**VERDICT**: ✅ PASS - 3 runs, identical hash `73fb8941ad950be6...`

---

## 4. Migration Order Safety

### 4.1 Migration Files
```
001_initial_schema.sql
002_compose_scenarios.sql
003_audit_checks.sql
004_status_enum.sql
005_wk02_schema.sql
006_multi_tenant.sql
```

### 4.2 Tenant ID FK Analysis

**002_compose_scenarios.sql** (lines 139-165):
```sql
CREATE TABLE IF NOT EXISTS forecast_compositions (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL DEFAULT 1,  -- FK added in 006_multi_tenant.sql
    ...
);

CREATE TABLE IF NOT EXISTS tour_removals (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL DEFAULT 1,  -- FK added in 006_multi_tenant.sql
    ...
);
```
- ✅ `tenant_id` column present with DEFAULT 1
- ✅ NO FK constraint (comment explicitly states "FK added in 006")

**006_multi_tenant.sql** (lines 17-57):
```sql
CREATE TABLE IF NOT EXISTS tenants (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    ...
);

-- Default tenant for migration
INSERT INTO tenants (id, name, api_key_hash, is_active, ...)
VALUES (1, '_migration_data_owner', ...);
```
- ✅ `tenants` table created FIRST
- ✅ Default tenant ID=1 inserted before FK constraints
- ✅ All FK constraints added AFTER tenants table exists

**VERDICT**: ✅ PASS - Migration order is SAFE

---

## 5. Summary

| Category | Status | Evidence |
|----------|--------|----------|
| Git Identity | ✅ PASS | HEAD=22abfc29, clean tree |
| Legacy Cleanup | ✅ PASS | No streamlit/cli/src/v3 files |
| Import Hygiene | ✅ PASS | No production v3/src imports |
| Determinism | ✅ PASS | 3 runs identical hash |
| Migration Safety | ✅ PASS | tenant_id before FK |

**LOCAL VERIFICATION**: ✅ ALL PASS
