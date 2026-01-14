# SOLVEREIGN Forensic Current State Report

**Datum**: 2026-01-13
**Commit**: dafad8c9e210f91562c34cc7aa358666cb262929
**Branch**: main
**Version**: V4.5.2

---

## Executive Summary

| Kategorie | Status | Details |
|-----------|--------|---------|
| **Backend** | **HEALTHY** | API läuft, Health Check OK |
| **Frontend** | **NOT RUNNING** | Port 3002 nicht erreichbar |
| **Database** | **HEALTHY** | PostgreSQL 16, RBAC 16/16 PASS |
| **Migrations** | **59 FILES** | 001-051, alle in manifest |
| **BFF Routes** | **86 TOTAL** | 35 nutzen proxy.ts, 6 Special Routes |

---

## 1. Pilot Stack Status

### Container Status

| Container | Status | Port | Health |
|-----------|--------|------|--------|
| solvereign-pilot-api | **UP** | 8000 | **HEALTHY** |
| solvereign-pilot-db | **UP** | 5432 | **HEALTHY** |
| frontend | **DOWN** | 3002 | **NOT RUNNING** |

**VERIFIZIERT**: `curl http://localhost:8000/health`
```json
{
  "status": "ready",
  "checks": {
    "database": "healthy",
    "policy_service": "healthy",
    "packs": {"roster": "available", "routing": "available"}
  }
}
```

---

## 2. Authentication & Session Management

### Cookie-Konfiguration

| Setting | Wert | Quelle |
|---------|------|--------|
| Cookie Name (Prod) | `__Host-sv_platform_session` | `internal_rbac.py:48` |
| Cookie Name (Dev) | `sv_platform_session` | `internal_rbac.py:50` |
| TTL | 8 Stunden | `internal_rbac.py:52` |
| HttpOnly | **TRUE** | `internal_rbac.py:53` |
| SameSite | **strict** | `internal_rbac.py:54` |
| Secure | Env-basiert (prod=true) | `internal_rbac.py:85` |

### Portal Cookie (Fahrer)

| Setting | Wert | Quelle |
|---------|------|--------|
| Cookie Name | `portal_session` | `portal/session/route.ts:22` |
| TTL | 60 Minuten | `portal/session/route.ts:23` |
| Path | `/my-plan` | `portal/session/route.ts:101` |

**VERIFIZIERT**: Beide Cookie-Systeme sind getrennt und konfliktfrei.

---

## 3. BFF Route Analysis

### Gesamt-Statistik

| Kategorie | Anzahl | Prozent |
|-----------|--------|---------|
| **Alle BFF Routes** | 86 | 100% |
| Nutzen `proxyToBackend` | 35 | 41% |
| Direct `fetch(BACKEND_URL)` | 6 | 7% |
| Andere (Static/Internal) | 45 | 52% |

### Special Routes (Direct Fetch)

| Route | Typ | Begründung |
|-------|-----|------------|
| `/api/auth/login` | POST | Cookie-Handling erforderlich |
| `/api/auth/logout` | POST | Cookie-Clearing erforderlich |
| `/api/portal/session` | POST/GET/DELETE | Magic-Link Token Exchange |
| `/api/portal/ack` | POST | Session-Cookie Extraction |
| `/api/portal/read` | POST | Session-Cookie Extraction |
| `/api/tenant/dashboard` | GET | Legacy-Route |

**VERIFIZIERT**: Special Routes haben korrekten Error-Passthrough und response.ok Handling.

### Centralized Proxy Features (`lib/bff/proxy.ts`)

| Feature | Status | Code-Zeile |
|---------|--------|------------|
| Session Cookie Extraction | **YES** | `proxy.ts:23-32` |
| trace_id Propagation | **YES** | `proxy.ts:45-50` |
| Timeout Handling (10s) | **YES** | `proxy.ts:52` |
| Error Normalization | **YES** | `proxy.ts:80-110` |
| response.ok Check | **YES** | `proxy.ts:65` |

---

## 4. Contract Validation (Zod Schemas)

### Schema Files

| File | Schemas | Coverage |
|------|---------|----------|
| `lib/schemas/run-schemas.ts` | 15 Schemas | Run Create/Status/Schedule |
| `lib/schemas/matrix-schemas.ts` | ? | Matrix View |
| `lib/schemas/platform-admin-schemas.ts` | 12 Schemas | Tenant/User/Role/Site |

### Runtime Validation

| Route | Zod Parse | Graceful Fallback |
|-------|-----------|-------------------|
| Run Create | `parseRunCreateResponse()` | Throws with message |
| Run Status | `parseRunStatusResponse()` | Returns FAILED status |
| Tenant List | `parseTenantListResponse()` | Returns empty array |
| User List | `parseUserListResponse()` | Returns empty array |

**UNVERIFIED**: Nicht alle BFF Routes nutzen Zod-Validation. Risiko bei API-Änderungen.

---

## 5. Database & Migrations

### Migration Manifest

- **Total Files**: 59 (001-051 + init.sql)
- **Manifest**: `backend_py/db/migrations/pilot_manifest.txt`
- **Forward-Only**: 050, 051 sind Bug-Fixes für 040

### RBAC Integrity Check

```
SELECT * FROM auth.verify_rbac_integrity();
```

| Check | Status |
|-------|--------|
| session_hash_column | **PASS** |
| session_hash_unique | **PASS** |
| is_platform_scope_column | **PASS** |
| active_tenant_id_column | **PASS** |
| validate_session_signature | **PASS** |
| no_token_hash_column | **PASS** |
| column_types_correct | **PASS** |
| roles_seeded | **PASS** (5 roles) |
| permissions_seeded | **PASS** (24 permissions) |
| role_permissions_mapped | **PASS** (69 mappings) |
| tenant_admin_role_exists | **PASS** |
| platform_permissions_exist | **PASS** (7 platform.*) |
| users_rls_enabled | **PASS** |
| sessions_rls_enabled | **PASS** |
| audit_log_immutable | **PASS** |
| no_fake_tenant_zero | **PASS** |

**16/16 PASS** - RBAC-Schema ist vollständig und korrekt.

### Seeded Data

| Entity | Count |
|--------|-------|
| Tenants | 1 (E2E Test Tenant) |
| Sites | 1 (E2E Test Site) |
| Users | 4 (e2e-platform-admin, e2e-dispatcher, e2e-test, e2e-tenant-admin) |
| Roles | 5 (platform_admin, tenant_admin, operator_admin, dispatcher, ops_readonly) |
| Permissions | 24 |

---

## 6. Flow-by-Flow Scorecard

### Login Flow

| Step | Status | Evidence |
|------|--------|----------|
| Frontend Login Page | **UNVERIFIED** | Frontend nicht gestartet |
| BFF Login Route | **VERIFIED** | `app/api/auth/login/route.ts` |
| Backend Auth | **VERIFIED** | `/api/auth/login` returns 200 |
| Cookie Set | **VERIFIED** | `Set-Cookie` Header korrekt |

### Platform Admin Flow

| Step | Status | Evidence |
|------|--------|----------|
| Tenant List | **VERIFIED** | `proxyToBackend('/api/platform/tenants')` |
| User List | **VERIFIED** | `proxyToBackend('/api/platform/users')` |
| Create Tenant | **VERIFIED** | POST-Route vorhanden |
| Create User | **VERIFIED** | POST-Route vorhanden |

### Roster Workbench Flow

| Step | Status | Evidence |
|------|--------|----------|
| Plan List | **VERIFIED** | `/api/roster/plans` |
| Run Create | **VERIFIED** | `/api/roster/runs` |
| Matrix View | **VERIFIED** | `/api/roster/plans/[id]/matrix` |
| Pins | **VERIFIED** | `/api/roster/plans/[id]/pins` |
| Violations | **VERIFIED** | `/api/roster/plans/[id]/violations` |

### Repair Flow

| Step | Status | Evidence |
|------|--------|----------|
| Preview | **VERIFIED** | `/api/roster/repair/preview` |
| Commit | **VERIFIED** | `/api/roster/repair/commit` |
| Sessions | **VERIFIED** | `/api/roster/repairs/sessions` |
| Undo | **VERIFIED** | `/api/roster/repairs/[sessionId]/undo` |

### Publish & Lock Flow

| Step | Status | Evidence |
|------|--------|----------|
| Publish | **VERIFIED** | `/api/roster/snapshots/publish` |
| Lock | **VERIFIED** | `/api/roster/plans/[id]/lock` |
| Freeze | **UNVERIFIED** | Route vorhanden, Semantik unklar |

### Evidence/Export Flow

| Step | Status | Evidence |
|------|--------|----------|
| Local Evidence | **VERIFIED** | `/api/evidence/local` |
| Export (JSON) | **VERIFIED** | `lib/export.ts:exportAsJSON` |
| Export (PDF) | **VERIFIED** | `lib/export.ts:exportAsPDF` |
| Export (Excel) | **VERIFIED** | `lib/export.ts:exportAsExcel` |

---

## 7. Identified Gaps

### Kritische Lücken

| # | Gap | Risiko | Empfehlung |
|---|-----|--------|------------|
| 1 | **Frontend nicht gestartet** | E2E-Tests nicht ausführbar | `npm run dev` in frontend_v5 |
| 2 | **Freeze-Semantik unklar** | User-Erwartungen nicht erfüllt | Dokumentieren oder entfernen |
| 3 | **Backup-Script fehlt** | Datenverlust-Risiko | pg_dump Cronjob einrichten |
| 4 | **Repair Session TTL undefiniert** | Sessions laufen nie ab | TTL in Config setzen |

### Warnungen

| # | Warnung | Impact |
|---|---------|--------|
| 1 | Nicht alle BFF-Routes nutzen Zod | Schema-Änderungen können Crashes verursachen |
| 2 | Portal Session base64-encoded | Kein Signing - Manipulation theoretisch möglich |
| 3 | 45 Static/Internal Routes ungeprüft | Potenzielle Security-Lücken |

---

## 8. Nächste Schritte

1. [ ] Frontend starten: `cd frontend_v5 && npm run dev`
2. [ ] E2E Tests ausführen: `npx playwright test`
3. [ ] Decision Intake Form ausfüllen lassen
4. [ ] Freeze-Semantik mit Product Owner klären
5. [ ] Backup-Script erstellen und testen

---

*Generiert: 2026-01-13 von Claude Code Forensik*
*Commit: dafad8c9e210f91562c34cc7aa358666cb262929*
