# LOCAL RUN BASELINE

> Established: 2026-01-13
> Purpose: Market-ready validation with GO×2 requirement

---

## Environment

| Component | Version |
|-----------|---------|
| Git HEAD | `dafad8c9e210f91562c34cc7aa358666cb262929` |
| Node.js | v24.11.1 |
| Python | 3.13.9 |
| Docker | 29.1.3 |

---

## Git Status (Start)

```
Modified (staged for test):
- Multiple backend_py test files
- Multiple frontend_v5 API routes
- playwright.config.ts (hardened)
- scripts/gate-critical.ps1 (RBAC phase added)
- scripts/seed_e2e.py (deterministic users)

New files (untracked):
- backend_py/api/tests/test_db_schema_invariants.py
- backend_py/db/migrations/049_auth_schema_drift_fix.sql
- frontend_v5/e2e/rbac-tenant-admin.spec.ts
- frontend_v5/e2e/streaming-export.spec.ts
- frontend_v5/e2e/whitelist-guard.spec.ts
- scripts/clean-install-gate.ps1
- docs/PROOF_*.md
```

---

## Target Bar

1. `scripts/clean-install-gate.ps1` → GO×2 (fresh DB)
2. `gate-critical.ps1` → All 6 phases PASS including RBAC
3. E2E specs required:
   - auth-smoke.spec.ts
   - auth-flow.spec.ts
   - rbac-tenant-admin.spec.ts
   - streaming-export.spec.ts
   - whitelist-guard.spec.ts

---

## Validation Run Log

| Run | Timestamp | Result | Notes |
|-----|-----------|--------|-------|
| 1 | (pending) | - | - |
| 2 | (pending) | - | - |
