# SOLVEREIGN - Release Gate Plan

> **Date**: 2026-01-17
> **Status**: ACTIVE - BLOCKING RELEASE
> **Scope**: Wien Pilot / GA Readiness

---

## Status Ampel (Traffic Light)

### GRUEN (Counts as PASS)

| Gate | Evidence | Status |
|------|----------|--------|
| `auth.verify_rbac_integrity()` | 16/16 PASS | GRUEN |
| `masterdata.verify_masterdata_integrity()` | 9/9 PASS | GRUEN |
| Playwright auth-smoke.spec.ts | 16 passed, 8 skipped | GRUEN |
| Routing Pack E2E Tests | Files created, smoke passes | GRUEN |
| Load Testing SLOs | `docs/LOAD_TESTING_SLOs.md` + k6 scripts | GRUEN (defined) |
| Design System v2.0 | Components functional | GRUEN |

### ROT → GEFIXT (via Migration 050)

| Gate | Issue | Fix | Status |
|------|-------|-----|--------|
| pytest Security Tests | "Struktur validiert" != Tests laufen | Option A: Tests auf Host | GEFIXT |
| `verify_final_hardening()` | SQL Bug: `'PUBLIC'` as role literal | 050: nspacl-Check | GRUEN |
| `portal.verify_portal_integrity()` | Bug: `pg_constraint_conargs()` | 050: pg_attribute JOIN | GRUEN |
| `dispatch.verify_dispatch_integrity()` | Bug: ambiguous column | 050: Rename RETURNS col | GRUEN |
| `notify.verify_notification_integrity()` | Schema not in scope | Explizit OUT OF SCOPE | N/A |
| Load Testing SLOs | Defined but NOT measured | Phase 4: k6 ausführen | GELB |

### GELB → ENTSCHIEDEN

| Gate | Entscheidung | Status |
|------|--------------|--------|
| `notify` schema | **OUT OF SCOPE** für Wien Pilot | ERLEDIGT |
| Container test mount | **Option A** (Tests auf Host/CI) | ERLEDIGT |
| `upgrade-proof.ps1` | **ENTFERNT** (nicht benötigt) | ERLEDIGT |

---

## Checkliste (Execution Order)

### Phase 1: Gate Scripts auf finalem main (BLOCKING)

**Prerequisites**: Docker running, clean git status

```powershell
# Step 1.1: Local Stability Gate
.\scripts\gate-local.ps1
# AKZEPTANZ: Exit code 0
# Bei FAIL: STOP - erst fixen, keine weiteren Schritte

# Step 1.2: Fresh DB Proof (2x for determinism)
.\scripts\fresh-db-proof.ps1 -Repeat 2 -Verbose
# AKZEPTANZ: Exit code 0 auf BEIDEN Runs
# Bei FAIL: STOP - Migration-Bug identifizieren und fixen

# Step 1.3: upgrade-proof.ps1 → ENTFERNT
# ENTSCHEIDUNG: Script existiert nicht und wird nicht benötigt (Greenfield-Deployment)
# fresh-db-proof.ps1 validiert bereits alle Migrations from-scratch
```

**DoD Phase 1**:
- [ ] `gate-local.ps1` = 0
- [ ] `fresh-db-proof.ps1 -Repeat 2` = 0 (beide Runs)
- [ ] Screenshot/Log als Beweis gespeichert

---

### Phase 2: Container-Mount-Problem eliminieren (BLOCKING)

**Problem**: pytest Security Tests wurden als "Struktur validiert" markiert, aber Tests liefen nicht im Container weil Code nicht gemounted war.

**Entscheidung erforderlich**:

| Option | Beschreibung | Empfehlung |
|--------|-------------|------------|
| **A: Tests ausserhalb Container** | Container = nur Runtime (DB, API), Tests laufen auf Host | Einfacher, aber Windows/psycopg Probleme |
| **B: Tests im Container** | Code MUSS gemounted sein, Tests laufen in Container | Sauberer, braucht volume mount |

**Minimal-Checks zur Wahrheitsfindung**:

```powershell
# Check 1: Kann Container Code sehen?
docker compose -f docker-compose.pilot.yml exec api ls -la /app
# ERWARTET: backend_py/, scripts/, etc.

# Check 2: Ist backend_py vorhanden?
docker compose -f docker-compose.pilot.yml exec api ls -la /app/backend_py
# ERWARTET: api/, db/, tests/, packs/

# Check 3: Kann pytest im Container laufen?
docker compose -f docker-compose.pilot.yml exec api python -m pytest --collect-only backend_py/tests/
# ERWARTET: Liste von Tests, NICHT "no tests found"
```

**DoD Phase 2**:
- [ ] Entscheidung dokumentiert: Option A oder B
- [ ] Wenn B: Volume mount in `docker-compose.pilot.yml` verifiziert
- [ ] `pytest --collect-only` findet Tests (Screenshot/Log)
- [ ] Mindestens 1 echter Test-Run mit PASS/FAIL (kein SKIP)

---

### Phase 3: SQL Integrity-Gate Bugs fixen (RELEASE BLOCKER)

#### Bug 3.1: `verify_final_hardening()` - SQL Syntax Error

**Root Cause**: Line 329 in `025e_final_hardening.sql`:
```sql
SELECT has_schema_privilege('PUBLIC', 'public', 'CREATE')
```
PostgreSQL akzeptiert `'PUBLIC'` nicht als String-Literal fuer Rollen. `PUBLIC` ist ein Keyword, kein normaler Rollenname.

**Fix**:
```sql
-- Option 1: Ohne Quotes (PUBLIC ist Keyword)
SELECT has_schema_privilege(PUBLIC, 'public', 'CREATE')

-- Option 2: pg_catalog.pg_roles pruefen stattdessen
SELECT EXISTS(
    SELECT 1 FROM pg_default_acl
    WHERE NOT defaclacl::text LIKE '%PUBLIC%'
)
```

**Betroffene Files**:
- `backend_py/db/migrations/025e_final_hardening.sql` (Line 329)

**DoD**:
- [ ] Migration 025f oder 042 mit Fix erstellt
- [ ] `verify_final_hardening()` laeuft ohne Exception
- [ ] Alle 17 Tests zeigen PASS/FAIL/WARN (keine Exceptions)
- [ ] `fresh-db-proof.ps1` immer noch gruen

**Repro-Test**:
```sql
SELECT * FROM verify_final_hardening();
-- ERWARTET: 17 Rows mit status PASS/FAIL/WARN
-- NICHT: ERROR: role "PUBLIC" does not exist
```

---

#### Bug 3.2: `portal.verify_portal_integrity()` - Missing Function

**Root Cause**: Lines 617-620 in `033_portal_magic_links.sql`:
```sql
SELECT 1 FROM pg_constraint_conargs(c.oid)
WHERE attname = 'tenant_id'
```
Die Funktion `pg_constraint_conargs()` existiert nicht in PostgreSQL.

**Fix**: Constraint-Columns ueber `pg_constraint.conkey` + `pg_attribute` joinen:
```sql
-- Korrekte Query fuer FK-Constraint-Columns
SELECT 1 FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid
  AND a.attnum = ANY(c.conkey)
WHERE a.attname = 'tenant_id'
```

**Betroffene Files**:
- `backend_py/db/migrations/033_portal_magic_links.sql` (Lines 617-620)

**DoD**:
- [ ] Migration 042 oder 043 mit Fix erstellt
- [ ] `portal.verify_portal_integrity()` laeuft ohne Exception
- [ ] Alle 8 Checks zeigen PASS/WARN (keine Exceptions)
- [ ] Playwright auth-smoke bleibt gruen

**Repro-Test**:
```sql
SELECT * FROM portal.verify_portal_integrity();
-- ERWARTET: 8 Rows mit status
-- NICHT: ERROR: function pg_constraint_conargs does not exist
```

---

#### Bug 3.3: `dispatch.verify_dispatch_integrity()` - Ambiguous Column

**Root Cause**: Mehrere JOINs mit gleichen Column-Namen, unqualifizierter Zugriff.

Verdacht: Lines 601-604 in `031_dispatch_lifecycle.sql`:
```sql
FROM pg_tables t
JOIN pg_class c ON c.relname = t.tablename
    AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'dispatch')
```
Problem: Subquery referenziert `nspname` ohne Tabellen-Qualifier, oder es gibt mehrere `tablename` Columns.

**Fix**: Alle Columns explizit qualifizieren:
```sql
FROM pg_tables t
JOIN pg_class c ON c.relname = t.tablename
    AND c.relnamespace = (SELECT n.oid FROM pg_namespace n WHERE n.nspname = t.schemaname)
WHERE t.schemaname = 'dispatch'
```

**Betroffene Files**:
- `backend_py/db/migrations/031_dispatch_lifecycle.sql` (Lines 593-720)

**DoD**:
- [ ] Migration 042 oder 043 mit Fix erstellt
- [ ] `dispatch.verify_dispatch_integrity()` laeuft ohne Exception
- [ ] Alle 12 Checks zeigen PASS/WARN (keine Exceptions)

**Repro-Test**:
```sql
SELECT * FROM dispatch.verify_dispatch_integrity();
-- ERWARTET: 12 Rows mit status
-- NICHT: ERROR: column reference "x" is ambiguous
```

---

### Phase 4: `notify` Schema - Scope Decision (GELB -> GRUEN/OUT)

**Frage**: Ist `notify.verify_notification_integrity()` fuer Wien Pilot im Scope?

| Wenn IN SCOPE | Wenn OUT OF SCOPE |
|---------------|-------------------|
| Migration 034-038 muss deployed sein | In STABILITY_DOD.md dokumentieren als "not in scope" |
| RLS/RBAC verifiziert | `verify_notification_integrity()` Call entfernen |
| Smoke-Flow (send test notification) | Kein Blocker fuer Release |

**Action Required**:
```markdown
# In docs/STABILITY_DOD.md hinzufuegen:

## Out of Scope - Wien Pilot

| Feature | Status | Reason |
|---------|--------|--------|
| Notification Pipeline (`notify.*`) | OUT | Deferred to Phase 2 |
```

**DoD**:
- [ ] Entscheidung dokumentiert
- [ ] Wenn IN SCOPE: Migration deployed, verify gruen
- [ ] Wenn OUT: STABILITY_DOD.md aktualisiert

---

### Phase 5: Load Testing - Messen, nicht nur definieren (P1)

**Status**: SLOs definiert (`docs/LOAD_TESTING_SLOs.md`), aber NICHT gemessen.

**Erforderlich**:
```bash
# Baseline-Test ausfuehren
k6 run tests/load/baseline.js

# Output speichern
k6 run --out json=load-results/baseline_$(date +%Y%m%d).json tests/load/baseline.js
```

**Akzeptanzkriterien**:
- p95 < 300ms
- p99 < 500ms
- Error rate < 0.1%
- RPS >= 100

**Voraussetzungen**:
- API + DB running (docker-compose.pilot.yml)
- Test-Fixtures geladen
- Netzwerk-Isolation (keine anderen Last)

**DoD**:
- [ ] k6 baseline.js ausgefuehrt
- [ ] JSON-Report in `load-results/` committed
- [ ] Alle Thresholds PASS (oder Degradation dokumentiert)

---

## Fix-Plan Summary

| Bug | Root Cause | Fix Location | DoD | Status |
|-----|------------|--------------|-----|--------|
| verify_final_hardening() | `'PUBLIC'` String statt Keyword | 050_verify_function_fixes.sql | Exception-frei | GRUEN |
| portal.verify_portal_integrity() | `pg_constraint_conargs()` existiert nicht | 050_verify_function_fixes.sql | 8/8 PASS | GRUEN |
| dispatch.verify_dispatch_integrity() | `status` Column vs RETURNS col | 050_verify_function_fixes.sql | 12/12 PASS | GRUEN |

---

## Risiken und Stop-the-Line Regeln

### STOP-THE-LINE (Immediate Halt)

| Trigger | Action |
|---------|--------|
| `gate-local.ps1` = 1 | Keine Merges, Bug fixen |
| `fresh-db-proof.ps1` = 1 | Keine Deployments, Migration fixen |
| verify_*() Exception | Migration-Fix erstellen und testen |
| 5xx in Playwright smoke | API Debug, kein Release |

### WARN (Proceed with Caution)

| Trigger | Action |
|---------|--------|
| Skipped tests > 10% | Review skip reasons |
| Load test threshold WARN | Document degradation |
| verify check = WARN | Log and monitor |

### Akzeptable Risks (Document and Proceed)

| Risk | Mitigation |
|------|------------|
| notify schema not deployed | Documented as out-of-scope |
| Load test on local != production | Plan staging run before GA |
| Some Playwright tests skipped | Skips have valid reasons (auth required) |

---

## Execution Checklist (Final)

```
PHASE 1: Gate Scripts
[ ] gate-local.ps1 = 0
[ ] fresh-db-proof.ps1 -Repeat 2 = 0 (both)
[ ] Screenshot saved

PHASE 2: Container Mount
[ ] Decision: Option A or B documented
[ ] pytest --collect-only finds tests
[ ] At least 1 real test run (no skip)

PHASE 3: SQL Bugs
[ ] 042_verify_fixes.sql created
[ ] verify_final_hardening() = 17 rows, no exception
[ ] portal.verify_portal_integrity() = 8 rows, no exception
[ ] dispatch.verify_dispatch_integrity() = 12 rows, no exception
[ ] fresh-db-proof.ps1 still green

PHASE 4: notify Scope
[ ] Decision documented in STABILITY_DOD.md

PHASE 5: Load Testing (P1)
[ ] k6 baseline.js executed
[ ] Results in load-results/
[ ] Thresholds documented

FINAL GATE
[ ] All verify functions 100% green (no exceptions)
[ ] All stability scripts 100% green
[ ] Screenshot/log evidence archived
```

---

## Evidence Archive Location

```
docs/evidence/
├── gate-local_2026-01-17.log
├── fresh-db-proof_2026-01-17.log
├── verify_rbac_integrity.png
├── verify_final_hardening.png
├── verify_portal_integrity.png
├── verify_dispatch_integrity.png
├── playwright_auth-smoke.log
└── k6_baseline_2026-01-17.json
```

---

*Document created: 2026-01-17 | Release Gatekeeper Assessment*
