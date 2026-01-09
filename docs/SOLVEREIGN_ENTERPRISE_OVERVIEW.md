# SOLVEREIGN Enterprise Overview

> **Version**: 3.4.0
> **Last Updated**: 2026-01-07
> **Document Type**: External Stakeholder Brief
> **Audience**: COO, CFO, Legal/Compliance, Partner IT

---

## 1. Executive Overview

**SOLVEREIGN** is an enterprise shift scheduling and route optimization platform designed for last-mile logistics and transportation companies. It automates weekly driver roster planning while maintaining strict compliance with German labor law (ArbZG - Arbeitszeitgesetz).

**Who it's for**: Operations leaders managing 50-500+ drivers across multiple sites, dispatchers handling weekly tour assignments, and compliance officers requiring audit-ready evidence of labor law adherence.

**The core promise**: Compliance-first, reproducible planning with full audit trails. Every decision is traceable, every plan is verifiable, and every change is logged.

**Three key outcomes**:
1. **Stability**: Deterministic solver produces identical results from identical inputs - no surprises, no "it worked yesterday" problems
2. **Speed**: 4-6 hours of manual planning reduced to 30 seconds of automated optimization
3. **Verifiable decisions**: Complete audit trail with SHA256 hash chains proves exactly what was decided, when, and why

**Current performance**: 142 drivers optimized, 1,385 tours covered (100%), all 7 compliance audits passing, 54h maximum weekly hours (under 55h legal cap).

---

## 2. The Business Problem

### Why dispatch/roster planning is hard

Weekly shift scheduling for logistics operations involves balancing multiple competing constraints:

- **Fixed time windows**: Customer deliveries must happen within specific slots
- **Labor law compliance**: German ArbZG mandates rest periods, maximum weekly hours, and span limits
- **Driver availability**: Vacation, sick leave, preferences, and qualifications
- **Last-minute changes**: Sick calls, vehicle breakdowns, demand spikes
- **Multi-site complexity**: Different depots, different requirements, different teams

### Why manual planning fails

| Problem | Impact |
|---------|--------|
| **Time cost** | 4-6 hours per week per planner |
| **Inconsistent decisions** | Different planners make different choices for identical scenarios |
| **No proof trail** | "Why did driver X get this tour?" has no documented answer |
| **Compliance risk** | Labor law violations discovered only after the fact |
| **Change chaos** | Sick call at 6 AM triggers frantic manual replanning |

### What "operational chaos" looks like

- Monday morning: Forecast arrives via Slack, planner opens Excel
- Tuesday: Planner manually assigns 200+ tours to 50+ drivers
- Wednesday: Realization that 3 drivers exceed 55h cap - start over
- Thursday: Sick call from driver - manually redistribute tours
- Friday: Audit request arrives - nobody can explain past decisions

**SOLVEREIGN standardizes this**: Forecast in, validated plan out, every decision logged, every audit passed.

---

## 3. What SOLVEREIGN Delivers

### 3.1 Complete Run Lifecycle

```
IMPORT → VALIDATE → SOLVE → AUDIT/GATES → FREEZE/LOCK → EVIDENCE → EXPORT → REPAIR
```

| Stage | What Happens | Status |
|-------|--------------|--------|
| **Import** | Tours from Slack/CSV parsed into canonical format | Production |
| **Validate** | Schema + business rules checked (PASS/WARN/FAIL) | Production |
| **Solve** | OR-Tools optimizer assigns drivers to tours | Production |
| **Audit** | 7 compliance checks run automatically | Production |
| **Gates** | FAIL status blocks plan lock (HTTP 409) | Production |
| **Freeze** | 12h before tour start, assignments become immutable | Production |
| **Lock** | Human approval required - plan becomes permanent | Production |
| **Evidence** | ZIP package with hashes, audit results, assignments | Production |
| **Export** | CSV/JSON/XLSX for downstream systems | Production |
| **Repair** | Controlled modification for sick calls/emergencies | Production |

### 3.2 Capability Map

| Capability | For Operations | For Compliance/Legal | For IT |
|------------|----------------|---------------------|--------|
| **Deterministic Solver** | Same input = same output, every time | Reproducibility proof for auditors | No debugging "random" results |
| **7 Compliance Audits** | Automatic labor law checking | Pre-built ArbZG compliance | No custom audit code needed |
| **Immutable Audit Trail** | Know who changed what, when | Hash-chain tamper detection | Database triggers enforce |
| **Freeze Windows** | Stability before execution | Changes require logged override | Time-based + flag-based |
| **Multi-Tenant Isolation** | Site/depot separation | Data never crosses tenant boundaries | Row-Level Security in PostgreSQL |
| **Evidence Packs** | One-click proof of compliance | GDPR/SOC2/ISO27001 mapping | SHA256 integrity verification |

### 3.3 Domain Packs (Pluggable)

| Pack | Purpose | Status |
|------|---------|--------|
| **Roster Pack** | Weekly shift scheduling (block heuristic) | Production |
| **Routing Pack** | Vehicle routing with time windows (OR-Tools VRPTW) | Pilot Ready |

---

## 4. Trust & Governance

### 4.1 Audit Trail - What Gets Recorded

Every plan version captures:

| Item | Example | Purpose |
|------|---------|---------|
| **Input hash** | `d1fc3cc7b2d8...` (SHA256) | Proves exact input used |
| **Solver config hash** | `0793d620da60...` | Proves solver settings |
| **Output hash** | `d329b1c40b8f...` | Proves exact result |
| **Seed** | `94` | Enables reproduction |
| **Timestamp** | `2026-01-07T10:30:00Z` | When solved |
| **User** | `dispatcher@lts.de` | Who approved |
| **Audit results** | `7/7 PASS` | Compliance status |

**Where verified**: `backend_py/v3/audit_fixed.py`, `backend_py/db/init.sql`

### 4.2 Immutability - How Plans Are Protected

Once a plan is **LOCKED**:

- Database triggers prevent any UPDATE or DELETE
- Assignments table is frozen
- Audit log accepts only new entries (append-only)
- Hash chain detects any tampering attempt

**Exception**: Override with logged reason, TTL, and approval (planned feature)

**Where verified**: `backend_py/db/migrations/004_triggers_and_statuses.sql`

### 4.3 Freeze Windows - Reducing Churn

**Default**: 12 hours before tour start, assignments are frozen

| Type | Mechanism | Override |
|------|-----------|----------|
| **Time-based** | Automatic based on tour start time | Requires APPROVER role |
| **Flag-based** | Manual `is_locked` on specific stops | Requires APPROVER role |

**Why it matters**: Prevents last-minute chaos, gives drivers stable schedules, reduces "morning of" surprises.

**Where verified**: `backend_py/v3/freeze_windows.py`, `backend_py/packs/routing/services/repair/freeze_lock_enforcer.py`

### 4.4 Go/No-Go Gates

| Gate | Blocks Lock If | HTTP Status |
|------|----------------|-------------|
| **Coverage** | Any tour unassigned | 409 Conflict |
| **Overlap** | Driver has concurrent tours | 409 Conflict |
| **Rest** | <11h between blocks | 409 Conflict |
| **Span Regular** | Block exceeds 14h | 409 Conflict |
| **Span Split** | Split block exceeds 16h or wrong break | 409 Conflict |
| **Fatigue** | 3er-chain on consecutive days | 409 Conflict |
| **Weekly Max** | Driver exceeds 55h | 409 Conflict |

**Where verified**: `backend_py/v3/audit_fixed.py` (691 lines, 7 audit classes)

### 4.5 Role-Based Access Control

| Role | Can Solve | Can Lock | Can Override Freeze |
|------|-----------|----------|---------------------|
| VIEWER | No | No | No |
| PLANNER/DISPATCHER | Yes | No | No |
| APPROVER | Yes | Yes | Yes |
| TENANT_ADMIN | Yes | Yes | Yes |

**Critical**: Machine-to-machine tokens CANNOT lock plans. Human approval required.

**Where verified**: `backend_py/api/dependencies.py`, `frontend_v5/lib/tenant-rbac.ts`

---

## 5. Typical Workflow

### Example: Weekly Roster Planning

**Scenario**: 46 vehicles, 1 site (Wien), 1,385 tours/week, goal: minimize drivers while maximizing FTE

#### Step-by-Step

| Step | Action | System Response |
|------|--------|-----------------|
| 1 | Planner uploads forecast CSV | Parser validates format (PASS/WARN/FAIL) |
| 2 | System expands tour templates | 1,385 tour instances created |
| 3 | Planner clicks "Solve" | Solver runs (~30 seconds) |
| 4 | System runs 7 audits | All checks PASS |
| 5 | Planner reviews KPIs | 142 drivers, 100% FTE, max 54h |
| 6 | Planner submits for approval | Plan enters DRAFT state |
| 7 | Approver reviews and locks | Plan enters LOCKED state |
| 8 | System generates evidence pack | ZIP with hashes, audit results |
| 9 | 12h before first tour | Freeze window activates |
| 10 | Driver calls in sick | Repair workflow triggered |
| 11 | Dispatcher reassigns tours | Override logged with reason |
| 12 | Export to payroll/TMS | CSV/JSON delivered |

### Repair Drill (Sick Call)

**Scenario**: Driver A calls in sick at 6 AM, has 3 tours starting at 8 AM

| Step | Action | Constraint |
|------|--------|------------|
| 1 | Dispatcher opens repair UI | Sees frozen assignments |
| 2 | Selects Driver A's tours | System shows eligible replacements |
| 3 | Assigns to Driver B | System checks: rest, span, capacity |
| 4 | Override logged | Reason: "Sick call from Driver A" |
| 5 | Driver B notified | Via export/notification system |

---

## 6. Inputs & Outputs

### 6.1 Input Contracts

#### Tour/Shift Input (Roster Pack)

| Field | Example | Required |
|-------|---------|----------|
| Day | `Mo`, `Di`, `Mi`, `Do`, `Fr`, `Sa`, `So` | Yes |
| Start time | `08:00` | Yes |
| End time | `16:00` | Yes |
| Count | `3 Fahrer` (3 drivers needed) | Optional (default: 1) |
| Depot | `Depot West` | Optional |
| Skill | `Kuehl` (refrigerated) | Optional |

**Format**: German notation, e.g., `Mo 08:00-16:00 3 Fahrer Depot West`

#### Stop/Order Input (Routing Pack)

| Field | Example | Required |
|-------|---------|----------|
| Stop ID | `STOP-001` | Yes |
| Latitude | `48.2082` | Yes |
| Longitude | `16.3738` | Yes |
| Time window start | `08:00` | Yes |
| Time window end | `12:00` | Yes |
| Service duration | `15` (minutes) | Yes |
| Volume/Weight | `0.5` (m3) | Optional |
| Skills required | `2-mann` | Optional |

### 6.2 Output Artifacts

| Artifact | Format | Content |
|----------|--------|---------|
| **Plan export** | CSV/XLSX/JSON | Driver roster with tour assignments |
| **KPI summary** | JSON | Drivers, hours, FTE ratio, block mix |
| **Audit report** | JSON/MD | 7 check results with details |
| **Evidence pack** | ZIP | All above + hashes + metadata |
| **Compliance matrix** | MD | GDPR/SOC2/ISO27001 mapping |

**Where verified**: `backend_py/v3/export.py`, `backend_py/skills/audit_report/`

---

## 7. Tech Stack

### 7.1 Verified Technologies

| Layer | Technology | Version | Where Verified |
|-------|------------|---------|----------------|
| **Backend Framework** | FastAPI | >=0.109.0 | `backend_py/requirements.txt:10` |
| **Runtime** | Python | >=3.11 | `backend_py/pyproject.toml:5` |
| **Database** | PostgreSQL | 16 Alpine | `docker-compose.yml` |
| **DB Driver** | psycopg | >=3.1.0 | `backend_py/requirements.txt:18` |
| **Solver** | OR-Tools | 9.11.4210 | `backend_py/requirements.txt:36` |
| **Math Programming** | HiGHS | 1.12.0 | `backend_py/requirements.txt:37` |
| **Frontend Framework** | Next.js | 16.1.1 | `frontend_v5/package.json` |
| **UI Library** | React | 19.2.3 | `frontend_v5/package.json` |
| **Auth Provider** | Microsoft Entra ID | OIDC v2.0 | `docs/TECHNICAL_PRD.md` |
| **JWT Library** | PyJWT | >=2.8.0 | `backend_py/requirements.txt:23` |
| **Encryption** | cryptography | >=41.0.0 | `backend_py/requirements.txt:24` |
| **Logging** | structlog | >=24.1.0 | `backend_py/requirements.txt:30` |
| **Metrics** | prometheus-client | >=0.19.0 | `backend_py/requirements.txt:31` |
| **Testing** | pytest | >=7.4.0 | `backend_py/requirements.txt:48` |

### 7.2 Security & Compliance Stack

| Component | Implementation | Where Verified |
|-----------|----------------|----------------|
| **Authentication** | OIDC JWT (RS256) via Entra ID | `backend_py/api/security/entra_auth.py` |
| **Authorization** | Role-based (VIEWER/DISPATCHER/APPROVER/ADMIN) | `backend_py/api/dependencies.py` |
| **Tenant Isolation** | PostgreSQL Row-Level Security | `backend_py/db/migrations/010_security_layer.sql` |
| **PII Encryption** | AES-256-GCM | `backend_py/api/security/encryption.py` |
| **Rate Limiting** | Per-tenant, per-user, per-IP | `backend_py/api/config.py:108` |
| **Audit Logging** | Immutable with hash chain | `backend_py/db/migrations/010_security_layer.sql` |

### 7.3 CI/CD Pipeline

| Workflow | Trigger | Purpose | Where Verified |
|----------|---------|---------|----------------|
| `pr-fast.yml` | Every PR | <5 min feedback | `.github/workflows/pr-fast.yml` |
| `pr-guardian.yml` | Every PR | Schema, secrets, pack boundaries | `.github/workflows/pr-guardian.yml` |
| `pr-proof.yml` | Solver/auth changes | Determinism proof (3 runs) | `.github/workflows/pr-proof.yml` |
| `nightly-torture.yml` | Daily 2 AM | RLS harness, stress tests | `.github/workflows/nightly-torture.yml` |
| `weekly-audit.yml` | Sunday 00:00 | Enterprise audit reports | `.github/workflows/weekly-audit.yml` |

---

## 8. PRD Summary

### 8.1 Vision & Goals

**Vision**: Automated, compliant, auditable shift scheduling that eliminates manual planning while providing enterprise-grade governance.

**Goals**:
- Minimize driver count while maximizing FTE ratio
- 100% German labor law (ArbZG) compliance
- Full audit trail for every decision
- Sub-60-second solve times

### 8.2 Non-Goals / Out of Scope

- Real-time GPS tracking
- Driver mobile app (planned, not implemented)
- Payroll calculation
- HR management

### 8.3 Personas

| Persona | Needs | Primary Actions |
|---------|-------|-----------------|
| **Dispatcher** | Fast planning, change handling | Solve, repair, export |
| **Operations Manager** | KPIs, compliance, cost control | Review, approve, report |
| **Compliance Officer** | Audit evidence, labor law proof | Evidence packs, audit reports |
| **IT Administrator** | Integration, security, uptime | Configuration, monitoring |

### 8.4 Core User Journeys

**Journey 1: Weekly Planning**
```
Import forecast → Run solver → Review KPIs → Approve plan → Export roster
```

**Journey 2: Repair (Sick Call)**
```
Receive sick call → Open repair UI → Select replacement → Override logged → Notify driver
```

### 8.5 Functional Requirements

| Priority | Requirement | Status |
|----------|-------------|--------|
| **MUST** | Multi-tenant isolation | Production |
| **MUST** | 7 compliance audits | Production |
| **MUST** | Deterministic solver | Production |
| **MUST** | Immutable audit trail | Production |
| **MUST** | Evidence pack export | Production |
| **SHOULD** | Freeze window enforcement | Production |
| **SHOULD** | RBAC with Entra ID | Production |
| **COULD** | Driver mobile notifications | Planned |
| **COULD** | Real-time dashboard | Partial |

### 8.6 Non-Functional Requirements

| Category | Requirement | Current Status |
|----------|-------------|----------------|
| **Determinism** | Same seed = same hash | Verified |
| **Performance** | Solve <60s for 1,500 tours | ~30s actual |
| **Availability** | 99.9% uptime | Infrastructure dependent |
| **Security** | No cross-tenant data access | RLS + tests verified |
| **Compliance** | ArbZG, GDPR-ready | 7 audits + encryption |

### 8.7 Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Tour coverage | 100% | 100% (1,385/1,385) |
| FTE ratio | >95% | 100% (142/142) |
| Max weekly hours | <55h | 54h |
| Audit pass rate | 100% | 7/7 PASS |
| Solve time | <60s | ~30s |
| Incident rate | <1/week | 0 (pilot) |

### 8.8 Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data quality issues | Medium | High | Parser validation (PASS/WARN/FAIL) |
| Performance regression | Low | Medium | Nightly stress tests |
| Override abuse | Low | Medium | Logged with reason, TTL |
| Pack boundary drift | Low | High | CI linter enforces separation |

---

## 9. Business Use Cases

### 9.1 LTS Transport / Gurkerl (Primary)

**Type**: Roster Pack (Weekly shift scheduling)

| Aspect | Details |
|--------|---------|
| **Data in** | Weekly forecast from Slack (German notation) |
| **Data out** | Driver roster CSV, evidence pack |
| **Operational value** | 4-6h planning reduced to 30s |
| **Compliance value** | 7 ArbZG audits pre-checked |
| **ROI lever** | 5-8 fewer drivers = €250-400k/year savings |

### 9.2 MediaMarkt / HDL Plus (Pilot)

**Type**: Routing Pack (Vehicle routing with time windows)

| Aspect | Details |
|--------|---------|
| **Data in** | Daily stops/orders with time windows |
| **Data out** | Optimized routes per vehicle |
| **Operational value** | Reduced driving time, fewer vehicles |
| **Compliance value** | Time window adherence, capacity limits |
| **ROI lever** | Route optimization = fuel + time savings |

**Status**: 6/6 pilot gates PASS, 68/68 tests PASS

### 9.3 Future Expansion

| Tenant | Pack | Data Model | Status |
|--------|------|------------|--------|
| Amazon Logistics | Analytics only | KPI dashboards | Planned |
| Other logistics | Roster/Routing | Per-tenant config | Planned |

---

## 10. What SOLVEREIGN is NOT

### 10.1 Not a "Black Box AI Autopilot"

- Every decision is explainable via audit trail
- Solver uses deterministic algorithms (OR-Tools), not neural networks
- Same input + same seed = same output, always

### 10.2 Not Replacing Dispatchers

- Dispatchers still review, approve, and handle exceptions
- System standardizes and proves decisions, doesn't make them autonomously
- Human approval required for plan lock

### 10.3 Not Modifying Source Data

- SOLVEREIGN ingests and snapshots input
- Original forecast files remain unchanged
- Version control tracks all input versions

### 10.4 Not a Monolith

- Pluggable pack architecture (Roster, Routing, future packs)
- Kernel handles governance, packs handle domain logic
- Packs can be enabled/disabled per tenant

---

## 11. Current Status & Readiness

### 11.1 Production Ready

| Component | Status | Evidence |
|-----------|--------|----------|
| Roster Pack (V3) | Production | 142 drivers, 7/7 audits |
| Multi-tenant API | Production | RLS + 68 tests |
| Entra ID Auth | Production | OIDC v2.0 integrated |
| Evidence Packs | Production | SHA256 hash chain |
| 7 Compliance Audits | Production | All checks implemented |
| Immutable Audit Trail | Production | DB triggers enforced |

### 11.2 Pilot Ready

| Component | Status | Evidence |
|-----------|--------|----------|
| Routing Pack (V3.3b) | Pilot | 6/6 gates, 68 tests |
| Freeze-Lock Enforcement | Pilot | Hard gate tested |
| Artifact Store (S3/Azure) | Pilot | Integration complete |

### 11.3 Planned / Backlog

| Component | Status | Timeline |
|-----------|--------|----------|
| Driver mobile notifications | Planned | Q1 2026 |
| Real-time dashboard | Partial | Q1 2026 |
| Override with TTL | Planned | Q2 2026 |
| Additional compliance frameworks | Planned | On request |

---

## 12. Open Questions

| Question | Needed For | Priority |
|----------|------------|----------|
| Production OSRM/HERE API credentials | Routing Pack pilot | High |
| Azure Blob vs S3 for evidence storage | Production deployment | Medium |
| SMS/WhatsApp provider for notifications | Driver communication | Medium |
| SOC 2 Type II audit timeline | Enterprise sales | Low |

---

## Appendix A: File References

| Document | Path | Lines |
|----------|------|-------|
| Technical PRD | `docs/TECHNICAL_PRD.md` | 970 |
| Security Architecture | `SECURITY_ARCHITECTURE_V3.3b.md` | 812 |
| Management Presentation | `docs/MANAGEMENT_PRESENTATION.md` | ~400 |
| Deployment Guide | `DEPLOYMENT.md` | 290 |
| Roadmap | `backend_py/ROADMAP.md` | 800+ |
| Database Schema | `backend_py/db/init.sql` | 375 |
| Audit Engine | `backend_py/v3/audit_fixed.py` | 691 |
| Solver Wrapper | `backend_py/v3/solver_wrapper.py` | 330 |

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **ArbZG** | Arbeitszeitgesetz - German working time law |
| **Block** | Set of tours assigned to one driver on one day |
| **Determinism** | Same inputs + same seed = identical outputs |
| **Evidence Pack** | ZIP file with hashes, audit results, assignments |
| **Freeze Window** | Period before tour start when changes are restricted |
| **FTE** | Full-Time Equivalent (>=40h/week) |
| **Hash Chain** | Sequential hashes that detect tampering |
| **OR-Tools** | Google's Operations Research optimization library |
| **RLS** | Row-Level Security in PostgreSQL |
| **VRPTW** | Vehicle Routing Problem with Time Windows |

---

*Document generated from verified codebase analysis. All claims backed by file references.*
