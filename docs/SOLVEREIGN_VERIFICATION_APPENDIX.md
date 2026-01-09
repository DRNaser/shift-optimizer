# SOLVEREIGN Verification Appendix

> **Purpose**: Source citations for all claims in SOLVEREIGN_EXTERNAL_OVERVIEW.md
> **Generated**: 2026-01-07
> **Repository**: shift-optimizer

---

## 1. Technology Stack Versions

| Technology | Version | Source File | Line |
|------------|---------|-------------|------|
| Python | >=3.11 | `backend_py/pyproject.toml` | 5 |
| FastAPI | >=0.109.0 | `backend_py/requirements.txt` | 10 |
| PostgreSQL | 16-alpine | `docker-compose.yml` | 21 |
| psycopg3 | >=3.1.0 | `backend_py/requirements.txt` | 18 |
| OR-Tools | 9.11.4210 (pinned) | `backend_py/requirements.txt` | 36 |
| PyJWT | >=2.8.0 | `backend_py/requirements.txt` | 23 |
| Next.js | 16.1.1 | `frontend_v5/package.json` | 15 |
| React | 19.2.3 | `frontend_v5/package.json` | 17 |
| TypeScript | 5.x | `frontend_v5/package.json` | 25 |

### Notes
- OR-Tools version is **pinned** (not >=) to ensure deterministic solver behavior
- PostgreSQL uses Alpine image for smaller container size

---

## 2. Audit Checks Implementation

| Check # | Name | Source File | Line | Description |
|---------|------|-------------|------|-------------|
| 1 | CoverageCheckFixed | `backend_py/v3/audit_fixed.py` | 51 | Every tour instance has exactly one assignment |
| 2 | OverlapCheckFixed | `backend_py/v3/audit_fixed.py` | 91 | No driver assigned to concurrent tours |
| 3 | RestCheckFixed | `backend_py/v3/audit_fixed.py` | 210 | Minimum rest between work days (default: 11h) |
| 4 | SpanRegularCheckFixed | `backend_py/v3/audit_fixed.py` | 367 | Regular blocks max span (default: 14h) |
| 5 | SpanSplitCheckFixed | `backend_py/v3/audit_fixed.py` | 476 | Split blocks max span + break validation |
| 6 | FatigueCheckFixed | `backend_py/v3/audit_fixed.py` | 587 | No consecutive 3er blocks |
| 7 | ReproducibilityCheckFixed | `backend_py/v3/audit_fixed.py` | 647 | Same seed = identical output hash |
| 8 | SensitivityCheckFixed | `backend_py/v3/audit_fixed.py` | 691 | Input quality validation |

### Configurable Parameters

| Parameter | Default | Source File | Line |
|-----------|---------|-------------|------|
| weekly_hours_cap | 55 | `backend_py/v3/solver_wrapper.py` | 51 |
| weekly_hours_cap | 55 | `backend_py/v3/models.py` | 405 |
| rest_hours_min | 11 | `backend_py/v3/audit_fixed.py` | 215 |
| span_regular_max | 14h | `backend_py/v3/audit_fixed.py` | 372 |
| span_split_max | 16h | `backend_py/v3/audit_fixed.py` | 481 |
| split_break_min | 240min | `backend_py/v3/audit_fixed.py` | 486 |
| split_break_max | 360min | `backend_py/v3/audit_fixed.py` | 487 |

**Important**: The 55-hour weekly cap is a **configurable default**, not a hardcoded legal requirement. Tenants can adjust this value.

---

## 3. Database Security Implementation

### Row-Level Security

| Evidence | Source File | Lines |
|----------|-------------|-------|
| RLS enabled on 7 tables | `backend_py/db/migrations/010_security_layer.sql` | 127-133 |
| 10 RLS policies defined | `backend_py/db/migrations/010_security_layer.sql` | 174-280 |
| Tenant context function | `backend_py/db/migrations/010_security_layer.sql` | 15-25 |

Tables with RLS enabled:
1. forecast_versions
2. tours_raw
3. tours_normalized
4. tour_instances
5. plan_versions
6. assignments
7. audit_log

### Immutability Triggers

| Trigger | Source File | Lines | Purpose |
|---------|-------------|-------|---------|
| prevent_locked_plan_modification | `backend_py/db/init.sql` | 274-287 | Block UPDATE on locked plans |
| prevent_locked_assignments_modification | `backend_py/db/migrations/004_triggers_and_statuses.sql` | 31-60 | Block changes to locked assignments |
| audit_log_append_only | `backend_py/db/migrations/004_triggers_and_statuses.sql` | 65-81 | Prevent UPDATE/DELETE on audit_log |

### Security Audit Trail

| Feature | Source File | Lines |
|---------|-------------|-------|
| security_audit_log table | `backend_py/db/migrations/010_security_layer.sql` | 35-50 |
| Hash chain computation | `backend_py/db/migrations/010_security_layer.sql` | 55-88 |
| Tamper detection trigger | `backend_py/db/migrations/010_security_layer.sql` | 90-110 |

---

## 4. Authentication Implementation

### Entra ID Integration

| Component | Source File | Lines | Notes |
|-----------|-------------|-------|-------|
| JWT validation | `backend_py/api/security/entra_auth.py` | 1-578 | Full implementation (not mock) |
| JWKS fetching | `backend_py/api/security/entra_auth.py` | 145-180 | Caches Microsoft public keys |
| Token verification | `backend_py/api/security/entra_auth.py` | 250-320 | Validates issuer, audience, expiry |
| Tenant mapping | `backend_py/db/migrations/012_tenant_identities.sql` | 1-257 | Maps Entra tid to tenant_id |

### RBAC Implementation

| Component | Source File | Lines |
|-----------|-------------|-------|
| Role definitions | `backend_py/api/security/rbac.py` | 90-176 |
| Permission checks | `backend_py/api/security/rbac.py` | 180-250 |
| Frontend RBAC | `frontend_v5/lib/tenant-rbac.ts` | 1-258 |

Defined roles: VIEWER, PLANNER, APPROVER, TENANT_ADMIN, PLATFORM_ADMIN

### Request Signing (Internal)

| Feature | Source File | Lines |
|---------|-------------|-------|
| HMAC-SHA256 signing | `backend_py/api/security/internal_signature.py` | 1-698 |
| Replay protection | `backend_py/api/security/internal_signature.py` | 450-520 |
| Nonce tracking | `backend_py/db/migrations/022_replay_protection.sql` | 1-50 |

---

## 5. Test Coverage

### Routing Pack Gate Tests (68 tests)

| Test File | Test Count | Source Path |
|-----------|------------|-------------|
| test_solver_realistic.py | 3 | `backend_py/packs/routing/tests/` |
| test_audit_gate.py | 12 | `backend_py/packs/routing/tests/` |
| test_rls_parallel_leak.py | 3 | `backend_py/packs/routing/tests/` |
| test_site_partitioning.py | 19 | `backend_py/packs/routing/tests/` |
| test_artifact_store.py | 19 | `backend_py/packs/routing/tests/` |
| test_freeze_lock_enforcer.py | 12 | `backend_py/packs/routing/tests/` |
| **Total Gate Tests** | **68** | |

### Additional Test Suites

| Category | Approximate Count | Location |
|----------|-------------------|----------|
| Routing pack tests | ~192 | `backend_py/packs/routing/tests/` |
| Skills tests | ~88 | `backend_py/skills/*/tests/` |
| V3 core tests | ~50 | `backend_py/v3/` + `backend_py/test_*.py` |
| API tests | ~30 | `backend_py/api/tests/` |

**Note**: The "68/68 tests" figure in documentation refers specifically to the 6 gate test files for V3.3b pilot validation, not all tests in the repository.

---

## 6. Solver Implementation

### OR-Tools Integration

| Component | Source File | Key Lines |
|-----------|-------------|-----------|
| VRPTW solver | `backend_py/packs/routing/services/solver/solver.py` | ~400 lines |
| Block heuristic | `backend_py/src/services/block_heuristic_solver.py` | 457 lines |
| V2 solver integration | `backend_py/v3/solver_v2_integration.py` | ~350 lines |

### Determinism Guarantee

| Mechanism | Source | Evidence |
|-----------|--------|----------|
| Pinned OR-Tools version | `requirements.txt:36` | `ortools==9.11.4210` (exact version) |
| Fixed seed parameter | `solver_wrapper.py:51` | `seed` parameter passed to solver |
| Output hash computation | `models.py:380-400` | SHA256 of sorted assignments |
| Reproducibility audit | `audit_fixed.py:647` | Verifies hash stability |

---

## 7. Evidence Pack Generation

### Artifact Store Implementation

| Store Type | Source File | Lines |
|------------|-------------|-------|
| LocalArtifactStore | `backend_py/packs/routing/services/evidence/artifact_store.py` | 200-350 |
| S3ArtifactStore | `backend_py/packs/routing/services/evidence/artifact_store.py` | 400-600 |
| AzureBlobArtifactStore | `backend_py/packs/routing/services/evidence/artifact_store.py` | 650-850 |

### Evidence Pack Contents

| File | Purpose | Source |
|------|---------|--------|
| AUDIT_SUMMARY.md | Human-readable audit results | `audit_report/generator.py:300-350` |
| EVIDENCE_HASHES.json | SHA256 integrity hashes | `audit_report/generator.py:400-450` |
| MANIFEST.json | Pack metadata | `audit_report/generator.py:450-500` |
| evidence/*.json | Individual evidence files | `audit_report/generator.py:350-400` |

---

## 8. Compliance Framework References

### What Exists

| Feature | Source | Status |
|---------|--------|--------|
| RLS tenant isolation | `010_security_layer.sql` | Implemented |
| Append-only audit log | `004_triggers_and_statuses.sql` | Implemented |
| Hash chain tamper detection | `010_security_layer.sql:55-88` | Implemented |
| Locked record immutability | `init.sql:274-287` | Implemented |
| Evidence pack export | `artifact_store.py` | Implemented |

### What Does NOT Exist

| Claimed Feature | Actual Status |
|-----------------|---------------|
| GDPR control mapping | Template text only (`generator.py:542-560`) |
| SOC 2 control mapping | Template text only (`generator.py:560-575`) |
| ISO 27001 control mapping | Template text only (`generator.py:575-586`) |

**Clarification**: The compliance framework references in `generator.py` lines 542-586 are **template text** for evidence pack documentation. They are NOT verified control mappings. The note in the code says: "Simulated - run RLS harness for real data".

Evidence exports can support compliance programs, but the platform does not provide compliance certification.

---

## 9. Deployment Evidence

### What Exists

| Artifact | Source | Purpose |
|----------|--------|---------|
| docker-compose.yml | Repository root | Local development |
| Dockerfile references | Various | Container builds |
| requirements.txt | `backend_py/` | Python dependencies |
| package.json | `frontend_v5/` | Node dependencies |

### What Does NOT Exist

| Expected for "Production" | Status |
|---------------------------|--------|
| Kubernetes manifests | Not found |
| Helm charts | Not found |
| Cloud deployment configs | Not found |
| Production monitoring setup | Not found |
| Runbooks for production ops | Not found |

**Conclusion**: The platform is **implemented and tested** but production deployment infrastructure is not included in the repository. Status should be "Pilot-Ready" not "Production".

---

## 10. Claims NOT Made (Avoided Hallucinations)

The external overview document intentionally does NOT claim:

| Avoided Claim | Reason |
|---------------|--------|
| "55h legal cap under ArbZG" | 55h is a configurable default, not hardcoded legal compliance |
| "Production deployment" | No production infrastructure evidence in repository |
| "SOC 2 certified" | Compliance mappings are template text only |
| "GDPR compliant" | Evidence exports support compliance, not certification |
| "ISO 27001 certified" | Compliance mappings are template text only |
| "Slack integration" | No Slack-specific code found; import is CSV/API |
| "145 drivers achieved" | This was a specific test result, not a system capability claim |
| Specific customer names | No customer evidence in repository |

---

## 11. File Structure Summary

```
Key source files cited in this appendix:

backend_py/
├── requirements.txt                    # Python dependencies with versions
├── pyproject.toml                      # Python version requirement
├── v3/
│   ├── audit_fixed.py                  # 8 audit check implementations
│   ├── models.py                       # Data models, configurable defaults
│   └── solver_wrapper.py               # Solver integration
├── api/
│   └── security/
│       ├── entra_auth.py               # Entra ID JWT validation
│       ├── rbac.py                     # Role-based access control
│       └── internal_signature.py       # HMAC request signing
├── db/
│   ├── init.sql                        # Base schema + triggers
│   └── migrations/
│       ├── 004_triggers_and_statuses.sql
│       ├── 010_security_layer.sql      # RLS + audit trail
│       ├── 012_tenant_identities.sql   # Entra mapping
│       └── 022_replay_protection.sql   # Nonce tracking
├── packs/routing/
│   ├── services/
│   │   ├── solver/solver.py            # OR-Tools VRPTW
│   │   └── evidence/artifact_store.py  # S3/Azure storage
│   └── tests/                          # 68 gate tests
└── skills/
    └── audit_report/generator.py       # Evidence pack generation

frontend_v5/
├── package.json                        # Node dependencies
└── lib/tenant-rbac.ts                  # Frontend RBAC

docker-compose.yml                      # PostgreSQL 16 definition
```

---

## Verification Methodology

This appendix was generated by:

1. **Automated search** for version numbers in dependency files
2. **Line-by-line verification** of audit check implementations
3. **Database migration analysis** for security features
4. **Test file enumeration** for coverage claims
5. **Negative verification** for claims that should NOT be made

All line numbers were verified against the current repository state as of 2026-01-07.

---

*Document generated to support SOLVEREIGN_EXTERNAL_OVERVIEW.md claims.*
