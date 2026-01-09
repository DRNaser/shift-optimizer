# RUNBOOK - Wien Pilot (46 Vehicles)

**System**: SOLVEREIGN (Import → Solve → Audit → Freeze/Lock → Evidence → Repair)

**Goal**: Jeden Tag/Wochenlauf reproduzierbar planen + rechtssicher freigeben + bei Störungen schnell reparieren (ohne Chaos).

---

## 0) Rollen & Zuständigkeiten

| Role | Responsibility |
|------|----------------|
| **Dispatcher (Ops)** | Führt Planläufe aus, überwacht KPIs, stößt Repair an, kommuniziert an Team |
| **Approver (Lead/Management)** | Gibt Plan frei (Go/No-Go), verantwortet Freeze-Entscheidungen |
| **Ops On-Call** | Nimmt Alerts an, entscheidet Stop/Continue, koordiniert Rollback |
| **Platform Eng** | BFF/Frontend, Auth, UI, Feature Flags, "Disable writes" |
| **Backend Eng** | Idempotency, RLS, Replay Protection, DB/Constraints, Performance |
| **Data Owner (FLS/Order Source)** | Exportqualität, Service Codes, TW, Lat/Lng Contract |

---

## 1) Erfolgs-Kriterien (Pilot)

| Criterion | Target |
|-----------|--------|
| Auth-Bypass / Tenant-Leaks / Duplicate Side Effects | **0** (Stop Conditions greifen) |
| Coverage | **100%** (oder klar dokumentierte Ausnahmen mit Approver-Signoff) |
| Reparaturzeit (Standard-Fälle) | **< 15 Minuten** bis "neuer freigegebener Plan" |
| Audit-Trail | **Vollständig** (Evidence Bundle pro Run) |

---

## 2) Daily Ops Timeline (empfohlen)

| Day | Activity |
|-----|----------|
| **D-1 (Planung)** | Import + Solve + Audit + Approve + Freeze/Lock |
| **D (Execution)** | Monitoring + Repairs bei Events (Sick-call, Vehicle, Order spikes) |
| **D+0 (Close)** | Evidence sichern, KPI Snapshot, Postmortem falls Stop/Incident |

---

## 3) Pre-Flight Checks (vor jedem Pilot-Run)

### Dispatcher Checklist (5 Minuten)

- [ ] `/health` und `/health/ready` ✅ (nur Status, keine sensiblen Daten)
- [ ] Alerts-Kanal aktiv ✅ (Azure Log Analytics → Slack/PagerDuty; Owner assigned)
- [ ] Keine aktiven STOP-Alerts ✅
- [ ] Import-Input vorhanden ✅ (FLS Export Datei/Job)
- [ ] "Writes enabled" ✅ (kein globaler Write-Disable aktiv)

### Approver Pre-Flight (1 Minute)

- [ ] Approver verfügbar im geplanten Freigabe-Zeitfenster ✅
- [ ] Freeze-Policy/Window bekannt ✅ (ab wann Änderungen nur über Repair)

---

## 4) Standard-Prozess: Import → Solve → Audit → Approve → Freeze/Lock → Publish

### 4.1 Import (Order Source → SOLVEREIGN)

**Dispatcher Steps**:

1. Import starten (Job/Endpoint/CLI)
2. Sofort prüfen:
   - Anzahl Orders/Stops plausibel (vs. Erwartung)
   - `lat/lng` vorhanden (wenn nicht: Routing-Matrix/OSRM Entscheidung greifen)
   - Time Windows (TW) korrekt (nicht leer / nicht invertiert)
   - `service_code` mapping vollständig (keine "unknown")

**Go/No-Go Import**:

| Decision | Condition |
|----------|-----------|
| **NO-GO** | lat/lng fehlen + keine Matrix-Strategie, TW kaputt, massenhaft unknown service_code, Datenvolumen offensichtlich falsch |
| **GO** | Input konsistent + Validierungen grün |

**Evidence** (immer speichern):
- Import-Log (Run-ID)
- Input checksum/hash
- "Import summary" (Counts, unknowns)

---

### 4.2 Solve (Plan erzeugen)

**Dispatcher Steps**:

1. Solver starten (konfigurierter Policy/Profile für Wien Pilot)
2. Monitor:
   - Laufzeit (Budget)
   - Coverage %
   - Constraint Violations (legal/freeze/tenant)
3. Ergebnis als PlanVersion speichern

**Go/No-Go Solve**:

| Decision | Condition |
|----------|-----------|
| **NO-GO** | Infeasible, Coverage < 100% ohne genehmigten Grund, harte Compliance verletzt |
| **GO** | Coverage = 100% (oder genehmigte Ausnahme), keine harten Violations |

**Evidence**:
- PlanVersion ID
- Solver KPIs (Headcount, overtime/violations, runtime)
- Determinism hash / config_hash (falls vorhanden)

---

### 4.3 Audit (Proof + Risiko)

**Dispatcher Steps**:

1. Audit Report generieren
2. Prüfen:
   - Hard Gates: legal/compliance
   - Freeze violations (falls Freeze bereits gesetzt)
   - Risiko-Score / Impact Preview (wenn aktiviert)

**Approver Steps**:

Audit Report lesen - nur 3 Fragen:
1. Ist es legal/compliant?
2. Ist es operativ ausführbar?
3. Gibt es Risk Flags, die Pilot gefährden?

**Go/No-Go Audit**:

| Decision | Condition |
|----------|-----------|
| **NO-GO** | Harte Violations, Tenant mismatch, unerklärte massive Churn, fehlende Evidence |
| **GO** | Alle Hard Gates grün, Risiko akzeptabel, Evidence komplett |

**Evidence**:
- Audit Report PDF/JSON
- Exceptions Liste (falls genehmigt) + Approver Notiz

---

### 4.3b Post-Solve Finalize Stage (OSRM Validation)

**Purpose**: Validate solved routes against live OSRM travel times before approval.

**Dispatcher Steps**:

1. Run OSRM finalize stage on solved plan
2. Review drift report and verdict:
   - **OK**: All metrics within thresholds, proceed to approval
   - **WARN**: Acceptable drift but review recommended, document reasons
   - **BLOCK**: Unacceptable drift, repair or re-solve required

3. Check finalize metrics:
   - P95 drift ratio (target: < 1.15 = 15% variance)
   - TW violations (target: 0)
   - Timeout rate (target: < 2%)
   - Fallback rate (target: < 5%)

**Verdict Interpretation**:

| Verdict | Action | Next Step |
|---------|--------|-----------|
| **OK** | Auto-proceed | Continue to 4.4 Approve |
| **WARN** | Review required | Dispatcher reviews drift report, documents acceptance |
| **BLOCK** | Cannot proceed | Investigate cause, repair matrix or routes |

**Troubleshooting High Drift**:

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| P95 > 1.30 | Stale matrix | Regenerate matrix from OSRM |
| Many MATRIX_MISS | New stops not in matrix | Add stops to matrix generation |
| High timeout rate | OSRM overloaded/slow | Check OSRM health, increase timeout |
| TW violations | Schedule too tight | Review TW constraints with Data Owner |

**Troubleshooting High Timeouts**:

1. Check OSRM status: `curl http://localhost:5000/status`
2. Check OSRM memory/CPU: `docker stats solvereign-osrm`
3. If OSRM down: restart with `docker restart solvereign-osrm`
4. If persistent: increase `finalize_timeout_seconds` in config

**Evidence**:
- Drift report JSON (`drift_report.json`)
- Fallback report JSON (`fallback_report.json`)
- Finalize verdict in routing evidence block

**Structured Logging** (for alerts):
```json
{
  "event_name": "routing_finalize_verdict",
  "tenant_id": "...",
  "site_id": "...",
  "plan_id": "...",
  "verdict": "WARN",
  "p95_ratio": 1.22,
  "tw_violations": 2,
  "timeout_rate": 0.03
}
```

---

### 4.4 Approve + Freeze/Lock

**Approver Decision**:

| Action | Effect |
|--------|--------|
| **Approve** | Plan wird "locked" + Freeze aktiviert (nach Policy) |
| **Reject** | Zurück zu Solve mit angepasster Policy (oder Repair-Flow, wenn bereits D-Day) |

**Dispatcher Steps**:

1. Plan lock/freeze ausführen
2. Evidence Bundle erstellen und ablegen (ArtifactStore)

**Evidence Bundle (Minimum)**:
- Input hash + Import summary
- PlanVersion + config_hash
- Audit report
- Approval record (wer, wann, warum)
- Export/publish summary

---

### 4.5 Publish (an Ops/Dispatch)

**Dispatcher Steps**:

1. Plan exportieren (Dispatch Tool / Driver App / CSV/PDF)
2. Stichprobe: 5 Fahrzeuge / 5 Routen plausibel

---

## 5) Repair Runbook (Intraday / Störungen)

### 5.1 Repair Trigger (typisch)

- Sick-call (Fahrer fällt aus)
- Vehicle breakdown
- Order spike / TW Change
- Depot/Zone Constraint ändert sich

### 5.2 Repair Prinzipien (non-negotiable)

1. **Frozen Teil bleibt stabil** (minimaler Churn)
2. **Änderungen nur im erlaubten Fenster** / mit Approver
3. **Nach Repair: Audit erneut + neue Approval**

### 5.3 Repair Steps (Dispatcher)

1. **Incident klassifizieren**:
   - **S1**: 1 Fahrer / 1 Route betroffen
   - **S2**: 2–5 Fahrer / mehrere Stops
   - **S3**: Systemisch (import/solver/auth)

2. Repair-Job starten (mit "minimize churn" Ziel)
3. Audit laufen lassen
4. Approver: approve/reject
5. Publish delta (nur betroffene Routen)

**Repair Evidence**:
- Repair run-id
- Delta summary (was wurde geändert)
- Audit report (repair)
- Approval record

---

## 6) Stop Conditions (Pilot Safety) - SOFORTIGES Vorgehen

### STOP-1: Auth bypass (SIGNATURE_INVALID non-test IP)

**Ops On-Call**:

1. **Disable writes** (sofort):
   ```bash
   az appconfig kv set --name solvereign-config --key SOLVEREIGN_PLATFORM_WRITES_DISABLED --value true
   ```

2. Logs sichern (correlation ids, source IPs, request paths)

3. Secrets rotieren (wenn Verdacht auf leak):
   ```bash
   az keyvault secret set --vault-name solvereign-kv --name SOLVEREIGN-SESSION-SECRET --value $(openssl rand -base64 32)
   ```

4. Backend/Platform Eng informieren
5. **Pilot pausieren** bis Root Cause gefunden

---

### STOP-2: Duplicate side effect (z.B. duplicate org_code/tenant_code)

**Ops On-Call**:

1. Writes disable
2. DB prüfen: constraint violations / retries
3. Idempotency table + used_signatures export:
   ```bash
   psql $DB_URL -c "SELECT * FROM idempotency_keys WHERE created_at > NOW() - INTERVAL '1 hour'" > evidence/idempotency.csv
   psql $DB_URL -c "SELECT * FROM core.used_signatures WHERE created_at > NOW() - INTERVAL '1 hour'" > evidence/signatures.csv
   ```
4. Fix + redeploy, erst dann weiter

---

### STOP-3: Tenant data leak (RLS bypass / tenant mismatch)

**Ops On-Call**:

1. **Pilot STOP**, writes disable
2. Scope bestimmen: welche Tenant(s), welche endpoints
3. Evidence export:
   ```bash
   psql $DB_URL -c "SELECT * FROM core.security_events WHERE created_at > NOW() - INTERVAL '24 hours' AND (event_type = 'TENANT_MISMATCH' OR details->>'tenant' IS NOT NULL)" > evidence/tenant_events.csv
   ```
4. Hotfix, **Postmortem zwingend**

---

### STOP-5: Coords Quality BLOCK (Unresolvable Locations)

**Trigger**: Import returns BLOCK verdict from coords quality gate (unresolved orders > 0 in strict mode).

**Ops On-Call**:

1. Check coords quality report:
   ```bash
   cat output/coords_quality_report.json | jq '.metrics'
   # Look for: orders_unresolved, missing_latlng_rate, fallback_rate
   ```

2. Identify unresolved orders:
   ```bash
   cat output/coords_quality_report.json | jq '.details.unresolved_orders'
   ```

3. Resolution options:
   - **Manual geocoding**: Add lat/lng to source data
   - **Zone mapping**: Ensure PLZ is in zone resolver
   - **H3 mapping**: Add H3 index if available
   - **Policy override**: If acceptable, adjust `block_unresolved_max` (requires Approver)

4. Re-run import after resolution:
   ```bash
   python scripts/run_wien_pilot_dry_run.py --input fixed_export.json
   ```

**Evidence**:
- Coords quality report JSON
- List of unresolved orders
- Resolution action taken

**Escalation**: If > 5% orders unresolvable → contact Data Owner (FLS)

---

### STOP-4: Routing Matrix Stale / OSRM Unavailable (repeated BLOCK verdicts)

**Trigger**: 3+ consecutive BLOCK verdicts from drift gate OR OSRM health check fails for > 5 minutes.

**Ops On-Call**:

1. Check OSRM health:
   ```bash
   curl http://localhost:5000/status
   docker ps | grep osrm
   docker logs solvereign-osrm --tail 100
   ```

2. If OSRM down, restart:
   ```bash
   docker restart solvereign-osrm
   ```

3. If matrix stale (high MATRIX_MISS rate):
   ```bash
   # Check matrix freshness
   python -m backend_py.packs.routing.cli.generate_matrix --validate data/matrices/current.csv

   # Regenerate if needed
   python -m backend_py.packs.routing.cli.generate_matrix --tenant 1 --site 1 --version wien_$(date +%Yw%V)_v1
   ```

4. If persistent: escalate to Platform Eng

**Evidence**:
- OSRM logs
- Drift report showing BLOCK reasons
- Matrix validation output

---

## 7) Rollback Plan (3 Schritte)

| Step | Command |
|------|---------|
| **1. Disable writes** | `az appconfig kv set --name solvereign-config --key SOLVEREIGN_PLATFORM_WRITES_DISABLED --value true` |
| **2. Rotate secrets** | `az keyvault secret set --vault-name solvereign-kv --name SOLVEREIGN-SESSION-SECRET --value $(openssl rand -base64 32)` |
| **3. Revert deploy** | Azure DevOps: Release pipeline → Rollback to slot `staging-previous` |

**Wichtig**: Im Runbook steht exakt, wie "Disable writes" passiert (Feature Flag / Env Var / Ingress). Das muss 1:1 klickbar sein.

---

## 8) KPI Baseline & Daily Reporting (Pilot)

### Dispatcher Daily Snapshot

| Metric | Target |
|--------|--------|
| Coverage % | 100% |
| Headcount/vehicle utilization | Per policy |
| Violations count | **0 hard** |
| Repairs count + durchschnittliche Repair-Zeit | < 15 min |
| Churn vs last approved plan | Minimal |
| Alerts count (STOP/Warnings) | 0 |

### Approver Weekly Review

- Trend: Repairs runter? Runtime stabil? Violations 0?
- Top 3 Ursachen für Repairs (Sick-call, data, ops)

---

## 9) Kommunikations-Templates (Slack)

### Approval
```
✅ Plan APPROVED
PlanVersion: [ID]
Coverage: 100%
Violations: 0
Freeze: ON
Evidence: [ArtifactStore Link]
Approver: @[Name]
```

### Repair
```
🛠️ Repair APPROVED
Delta: [Summary]
Affected routes: [Count]
Churn: [%]
Evidence: [ArtifactStore Link]
Approver: @[Name]
```

### Stop
```
🛑 STOP-1 Auth bypass triggered
Writes: DISABLED
Owner: @[On-Call Name]
Next update: [Time]
Action: Investigating source IPs + rotating secrets
```

### Routing Drift Warning
```
⚠️ Routing WARN verdict
PlanVersion: [ID]
P95 Drift: 1.22 (threshold: 1.15)
TW Violations: 2
Timeout Rate: 3%
Action: Dispatcher review required
Evidence: [ArtifactStore Link]
```

### Routing Drift Block
```
🚫 Routing BLOCK verdict
PlanVersion: [ID]
P95 Drift: 1.45 (threshold: 1.30)
TW Violations: 5
Action: Cannot approve - investigate matrix freshness
Evidence: [ArtifactStore Link]
Owner: @[Dispatcher Name]
```

---

## 10) Reference Documents

| Document | Purpose |
|----------|---------|
| [docs/WIEN_PILOT_KPI_BASELINE.md](docs/WIEN_PILOT_KPI_BASELINE.md) | **KPI definitions, baselines, thresholds, and detailed runbook appendix** |
| [SECURITY_AUDIT_PILOT_CHAIN.md](SECURITY_AUDIT_PILOT_CHAIN.md) | Security gate + stop conditions |
| [frontend_v5/SECURITY_AUDIT_PLATFORM_AUTH.md](frontend_v5/SECURITY_AUDIT_PLATFORM_AUTH.md) | BFF auth audit |
| [backend_py/SECURITY_AUDIT_BACKEND.md](backend_py/SECURITY_AUDIT_BACKEND.md) | Backend security audit |
| [scripts/audit_backend_checklist.js](scripts/audit_backend_checklist.js) | Audit checklist script |
| [docs/ROUTING_HYBRID_WIRING_MAP.md](docs/ROUTING_HYBRID_WIRING_MAP.md) | Routing system architecture |
| [backend_py/packs/routing/contracts/fls_import_contract.schema.json](backend_py/packs/routing/contracts/fls_import_contract.schema.json) | FLS import contract schema |
| [backend_py/packs/routing/policies/profiles/wien_pilot_routing.json](backend_py/packs/routing/policies/profiles/wien_pilot_routing.json) | Wien pilot policy profile |
| [backend_py/schemas/drift_report.schema.json](backend_py/schemas/drift_report.schema.json) | Drift report JSON schema |
| [backend_py/schemas/fallback_report.schema.json](backend_py/schemas/fallback_report.schema.json) | Fallback report JSON schema |
| [backend_py/schemas/routing_evidence.schema.json](backend_py/schemas/routing_evidence.schema.json) | Routing evidence JSON schema |
| [backend_py/schemas/evidence_pack.schema.json](backend_py/schemas/evidence_pack.schema.json) | **Evidence pack JSON schema (Gate I)** |
| [golden_datasets/routing/wien_pilot_46_vehicles/](golden_datasets/routing/wien_pilot_46_vehicles/) | Golden dataset for regression testing |
| [.claude/state/wien_baseline.json](.claude/state/wien_baseline.json) | **Wien pilot KPI baseline for drift detection** |
| [scripts/run_sick_call_drill.py](scripts/run_sick_call_drill.py) | Gate H1: Sick-call drill script |
| [scripts/run_freeze_window_drill.py](scripts/run_freeze_window_drill.py) | Gate H2: Freeze-window drill script |
| [scripts/run_partial_forecast_drill.py](scripts/run_partial_forecast_drill.py) | Gate H3: Partial-forecast drill script |
| [scripts/export_evidence_pack.py](scripts/export_evidence_pack.py) | Evidence pack exporter (ZIP + checksums) |
| [backend_py/v3/repair_service.py](backend_py/v3/repair_service.py) | Hardened repair service with churn metrics |

---

## 11) Wien W02 Dry Run (WITHOUT Routing Pack)

> **Status**: Routing pack PARKED until real input test data available
> **Scope**: Security gates + Roster E2E only

### 11.1 W02 Gate Overview

| Gate | Script | Exit Code | Artifacts |
|------|--------|-----------|-----------|
| **A: Security** | `scripts/ci/security_gate.sh` | 0=PASS, 1=FAIL | `security_gate_result.json`, `acl_scan_report.json` |
| **B: Roster** | `scripts/ci/wien_roster_gate.sh` | 0=PASS, 1=FAIL | `wien_roster_gate_result.json` |
| **C: Routing** | PARKED | - | - |

### 11.2 Pre-Flight W02

**Requirements**:
```bash
# 1. PostgreSQL with migrations 025-025f applied
docker compose up -d postgres
psql $DATABASE_URL < backend_py/db/migrations/025_tenants_rls_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025a_rls_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025b_rls_role_lockdown.sql
psql $DATABASE_URL < backend_py/db/migrations/025c_rls_boundary_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025d_definer_owner_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025e_final_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025f_acl_fix.sql

# 2. Python dependencies
pip install psycopg[binary] python-dotenv
```

### 11.3 Gate A: Security Gate (DB Hardening)

**Purpose**: Verify RLS + ACL hardening before any production deployment.

**Run**:
```bash
./scripts/ci/security_gate.sh --db-url "$DATABASE_URL"
```

**Expected Output (PASS)**:
```
==============================================================================
SOLVEREIGN Security Gate
==============================================================================
[1/5] Running verify_final_hardening()...
PASS: verify_final_hardening() - 0 failures

[2/5] Running verify_rls_boundary()...
PASS: verify_rls_boundary() - 0 failures

[3/5] Testing solvereign_api on tenants = Permission denied...
PASS: solvereign_api gets 'Permission denied' on tenants table
PASS: Session variable bypass blocked (Permission denied)

[4/5] Generating ACL scan report...
PASS: ACL scan - 0 objects need REVOKE

[5/5] Testing solvereign_platform can access tenants...
PASS: solvereign_platform can access tenants table

==============================================================================
Security Gate Result
==============================================================================
GATE STATUS: PASS
  Failures: 0
  Warnings: 0
```

**Critical Test**: solvereign_api must get **"Permission denied"** (not "0 rows"):
```sql
-- This MUST return "permission denied", NOT "0 rows"
SET ROLE solvereign_api;
SELECT COUNT(*) FROM tenants;

-- Session variable bypass MUST also fail
SET ROLE solvereign_api;
SET app.is_super_admin = 'true';
SELECT COUNT(*) FROM tenants;
-- Expected: "permission denied" (not "0 rows")
```

**Artifacts**:
- `artifacts/security_gate_result.json` - Gate status and test results
- `artifacts/acl_scan_report.json` - PUBLIC grant scan
- `artifacts/verify_hardening_output.txt` - Detailed test output

### 11.4 Gate B: Roster E2E (WITHOUT Routing)

**Purpose**: Verify parser + solver + audit framework work correctly.

**Run**:
```bash
./scripts/ci/wien_roster_gate.sh
```

**Expected Output (PASS)**:
```
==============================================================================
SOLVEREIGN Wien Roster Gate (W02 Dry Run)
==============================================================================
[1/5] Testing V3 Parser...
PASS: Parser returns PASS status

[2/5] Testing Solver Wrapper...
PASS: Solver wrapper returns plan_version_id

[3/5] Testing Audit Framework (7 checks)...
PASS: All 7 audit checks pass

[4/5] Testing Determinism (seed=94)...
PASS: Same seed produces same output_hash

[5/5] Checking routing pack status...
INFO: Routing pack PARKED - using --skip-routing

==============================================================================
Wien Roster Gate Result
==============================================================================
GATE STATUS: PASS
  Final Verdict: OK
  can_publish: true
  Routing: PARKED
```

**Artifacts**:
- `artifacts/wien_roster_gate_result.json` - Gate status
- Contains: parser status, audit results, determinism hash

### 11.5 Routing Pack Status (PARKED)

**Why Parked**: Real FLS input test data not yet available.

**What Remains Working**:
- Routing unit tests (`pytest backend_py/packs/routing/tests/`)
- OSRM map hash tests (18 tests)
- Golden dataset regression tests

**What is Skipped**:
- E2E pilot gates requiring real input
- FLS import validation
- OSRM live route validation

**Re-enable When**:
1. FLS provides test export file
2. OSRM map data for Wien region available
3. Zone resolver populated with Wien PLZ

### 11.6 CI Integration

Both gates run in `.github/workflows/pr-guardian.yml`:

```yaml
wien-security-gate:
  runs-on: ubuntu-latest
  services:
    postgres: ...
  steps:
    - run: ./scripts/ci/security_gate.sh
    - uses: actions/upload-artifact@v4
      with:
        name: security-gate-artifacts

wien-roster-gate:
  runs-on: ubuntu-latest
  needs: [wien-security-gate]
  steps:
    - run: ./scripts/ci/wien_roster_gate.sh
    - uses: actions/upload-artifact@v4
      with:
        name: roster-gate-artifacts
```

### 11.7 W02 Success Criteria

| Criterion | Target |
|-----------|--------|
| Security Gate | PASS (0 failures) |
| solvereign_api on tenants | "Permission denied" error |
| Session variable bypass | BLOCKED |
| Roster Audit | 7/7 checks PASS |
| Determinism | Same hash with seed=94 |
| Auth Separation | Platform vs Pack enforced |

### 11.8 Auth Separation (V3.7)

**Platform Endpoints** (`/api/v1/platform/*`):
- Uses: Session cookies + CSRF tokens
- Rejects: X-API-Key, X-SV-Signature, X-SV-Nonce

**Pack Endpoints** (`/api/v1/routing/*`, `/api/v1/roster/*`):
- Uses: X-API-Key + HMAC signature + Nonce
- Rejects: Session cookies, X-CSRF-Token

**Kernel Endpoints** (`/api/v1/forecasts/*`, `/api/v1/plans/*`):
- Uses: X-API-Key (simple auth)

**Enforcement**: Middleware in `main.py` rejects mismatched auth at request level.

---

## 12) Operational Drills (Gate H)

> **Purpose**: Validate ops-readiness through break-it drills before pilot go-live.
> **Frequency**: Run before each pilot week + on-demand for incident preparedness.

### 12.1 Drill Overview

| Drill | Script | Purpose | Exit Codes |
|-------|--------|---------|------------|
| **H1: Sick-Call** | `scripts/run_sick_call_drill.py` | 5 drivers unavailable, repair with 100% coverage | 0=PASS, 1=WARN (churn>10%), 2=FAIL |
| **H2: Freeze-Window** | `scripts/run_freeze_window_drill.py` | 12h freeze enforcement HARD gate | 0=PASS (BLOCK+ALLOW), 2=FAIL |
| **H3: Partial-Forecast** | `scripts/run_partial_forecast_drill.py` | Mon-Wed partial → full week delta | 0=PASS (deterministic), 2=FAIL |

### 12.2 H1: Sick-Call Drill

**Scenario**: 5 drivers call in sick. Repair service must:
- Maintain 100% coverage
- Minimize churn (target: <10%)
- All audits PASS

**Run**:
```bash
# Dry-run mode (without DB)
python scripts/run_sick_call_drill.py --dry-run --seed 94 \
  --absent-drivers DRV001,DRV002,DRV003,DRV004,DRV005 \
  --tenant wien_pilot

# Full execution (with DB)
python scripts/run_sick_call_drill.py --seed 94 \
  --absent-drivers DRV001,DRV002,DRV003,DRV004,DRV005 \
  --tenant wien_pilot --plan-version-id 123
```

**Expected Output (PASS)**:
```
======================================================================
SOLVEREIGN SICK-CALL DRILL (Gate H1)
======================================================================
Timestamp: 2026-01-08T10:00:00
Tenant: wien_pilot
Mode: DRY_RUN

[1/6] Loading baseline plan...
[2/6] Simulating sick-call (5 drivers)...
[3/6] Running repair service...
[4/6] Verifying coverage...
       Coverage: 100% (1385/1385 tours)
[5/6] Running audits...
       All 7 audits PASS
[6/6] Computing churn metrics...
       Changed assignments: 42
       Churn rate: 3.03%

======================================================================
DRILL SUMMARY
======================================================================
VERDICT: PASS
  Coverage: 100%
  Churn Rate: 3.03% (target: <10%)
  Audits: 7/7 PASS

Evidence: artifacts/drills/sick_call/drill_20260108_sick_call_wien_pilot.json
======================================================================
```

**Verdicts**:
| Exit | Verdict | Condition |
|------|---------|-----------|
| 0 | PASS | Coverage=100%, Audits PASS, Churn<10% |
| 1 | WARN | Coverage=100%, Audits PASS, Churn>=10% |
| 2 | FAIL | Coverage<100% OR any Audit FAIL |

### 12.3 H2: Freeze-Window Drill

**Scenario**: Test that freeze-lock enforcement is a HARD gate:
- Tours starting within 12h freeze window MUST be BLOCKED from modification
- Tours outside freeze window CAN be modified
- Edge case: tours exactly at boundary

**Run**:
```bash
# Dry-run mode
python scripts/run_freeze_window_drill.py --dry-run --seed 94 \
  --freeze-horizon 720 \
  --tenant wien_pilot

# Full execution
python scripts/run_freeze_window_drill.py --seed 94 \
  --freeze-horizon 720 \
  --tenant wien_pilot --plan-version-id 123
```

**Expected Output (PASS)**:
```
======================================================================
SOLVEREIGN FREEZE-WINDOW DRILL (Gate H2)
======================================================================
Timestamp: 2026-01-08T10:00:00
Tenant: wien_pilot
Mode: DRY_RUN
Freeze Horizon: 720 minutes (12 hours)

[1/5] Loading plan and freeze state...
[2/5] Testing: Modify frozen tour...
       Action: Reassign tour T-001 (starts in 4h)
       Expected: BLOCK
       Actual: BLOCK
       PASS

[3/5] Testing: Modify unfrozen tour...
       Action: Reassign tour T-099 (starts in 24h)
       Expected: ALLOW
       Actual: ALLOW
       PASS

[4/5] Testing: Boundary edge case...
       Action: Reassign tour T-050 (starts in 12h exactly)
       Expected: BLOCK (freeze is inclusive)
       Actual: BLOCK
       PASS

[5/5] Verifying enforcement mode...
       Mode: HARD (exception-based, not WARN)
       PASS

======================================================================
DRILL SUMMARY
======================================================================
VERDICT: PASS
  Frozen Tour: BLOCKED (correct)
  Unfrozen Tour: ALLOWED (correct)
  Boundary Edge: BLOCKED (correct)
  Enforcement Mode: HARD

Evidence: artifacts/drills/freeze_window/drill_20260108_freeze_wien_pilot.json
======================================================================
```

**Critical Verification**: Enforcement must be **BLOCK** (exception raised), NOT **WARN** (logged but allowed).

### 12.4 H3: Partial-Forecast Drill

**Scenario**: Simulate forecast arriving in two batches:
- V1: Mon-Wed only (partial)
- V2: Full week (complete)
- Verify deterministic delta computation

**Run**:
```bash
# Dry-run mode
python scripts/run_partial_forecast_drill.py --dry-run --seed 94 \
  --tenant wien_pilot

# Full execution
python scripts/run_partial_forecast_drill.py --seed 94 \
  --tenant wien_pilot
```

**Expected Output (PASS)**:
```
======================================================================
SOLVEREIGN PARTIAL-FORECAST DRILL (Gate H3)
======================================================================
Timestamp: 2026-01-08T10:00:00
Tenant: wien_pilot
Mode: DRY_RUN

[1/6] Creating V1 forecast (Mon-Wed)...
       Tours: 593 (partial)
[2/6] Solving V1...
       Coverage: 100%
       Hash: abc123...
[3/6] Creating V2 forecast (full week)...
       Tours: 1385 (complete)
[4/6] Computing delta (V2 - V1)...
       Added: 792 tours (Thu-Sun)
       Changed: 0 tours
       Removed: 0 tours
[5/6] Solving V2...
       Coverage: 100%
       Hash: def456...
[6/6] Verifying determinism...
       Re-run V2 with same seed...
       Hash match: def456... == def456...
       PASS

======================================================================
DRILL SUMMARY
======================================================================
VERDICT: PASS
  V1 Tours: 593
  V2 Tours: 1385
  Delta: +792 (no removals)
  Determinism: VERIFIED

Evidence: artifacts/drills/partial_forecast/drill_20260108_partial_wien_pilot.json
======================================================================
```

### 12.5 Evidence Pack Export

After running drills, export evidence pack for audit:

```bash
# Export single drill evidence
python scripts/export_evidence_pack.py export \
  --input artifacts/drills/sick_call/drill_20260108_sick_call_wien_pilot.json \
  --out evidence_h1_sick_call.zip

# Verify evidence pack integrity
python scripts/export_evidence_pack.py verify evidence_h1_sick_call.zip
```

**Evidence Pack Contents**:
```
evidence_pack_<run_id>.zip
├── manifest.json       # Metadata + file hashes
├── checksums.txt       # SHA256 of all files
├── evidence.json       # Main evidence data
├── audit_log.json      # Audit results (if present)
├── churn_report.json   # Churn metrics (H1 only)
└── freeze_report.json  # Freeze state (H2 only)
```

### 12.6 CI Integration

Drills run automatically in CI via `.github/workflows/pr-guardian.yml`:

```yaml
ops-drills-gate:
  name: Ops Drills Gate (Gate H)
  steps:
    - name: "[H1] Run Sick-Call Drill"
      run: python scripts/run_sick_call_drill.py --dry-run ...

    - name: "[H2] Run Freeze-Window Drill"
      run: python scripts/run_freeze_window_drill.py --dry-run ...

    - name: "[H3] Run Partial-Forecast Drill"
      run: python scripts/run_partial_forecast_drill.py --dry-run ...

    - name: Upload drill artifacts
      uses: actions/upload-artifact@v4
      with:
        name: ops-drills-evidence
        retention-days: 30
```

**Artifacts uploaded**: All evidence JSONs + ZIPs are uploaded **always** (even on failure).

### 12.7 Drill Success Criteria

| Drill | Pass Condition |
|-------|----------------|
| H1 Sick-Call | Coverage=100%, All audits PASS, Churn<20% |
| H2 Freeze-Window | BLOCK on frozen tours, ALLOW on unfrozen |
| H3 Partial-Forecast | Deterministic hash on re-run |

### 12.8 When to Run Drills

| Timing | Reason |
|--------|--------|
| **Before Pilot Week** | Validate ops-readiness |
| **After Migration** | Verify system behavior unchanged |
| **After Config Change** | Confirm freeze/churn behavior |
| **Monthly** | Maintain operational confidence |

### 12.9 Troubleshooting

**H1 Sick-Call: High Churn (>20%)**
- Check if absent drivers had many assignments
- Review solver priority (minimize churn vs coverage)
- May need to adjust repair strategy

**H2 Freeze-Window: ALLOW on frozen tour**
- CRITICAL: This is a security issue
- Check freeze_horizon_minutes config
- Verify FreezeLockEnforcer is enabled
- Check tour start times are in UTC

**H3 Partial-Forecast: Hash mismatch**
- Verify seed is consistent (94)
- Check for non-deterministic operations
- Review solver config changes

---

**Document Version**: 1.2 (Gate H Update)

**Effective for**: Wien Pilot (46 Vehicles) - W02 Dry Run

**Last Updated**: 2026-01-08
