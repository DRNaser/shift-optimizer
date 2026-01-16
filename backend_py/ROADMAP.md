# SOLVEREIGN Roadmap

> **Last Update**: 2026-01-08 (Wien W02 + Auth Separation)
> **Version**: 9.3.0 (V3.7 Auth Separation)
> **Status**: **V3.7 AUTH SEPARATION** ✅ | **ROUTING PARKED** ⏸️ | **WIEN W02 GATES** ✅
> **Tag**: [`v9.3.0-wien-w02`](https://github.com/DRNaser/shift-optimizer/tree/main)

---

## ⏸️ BLOCKER: Routing Pack PARKED (Wien W02)

> **Reason**: Real FLS input test data not yet available
> **Unblocks When**: FLS provides test export file for Wien pilot

### What's Parked

| Component | Status | Reason |
|-----------|--------|--------|
| FLS Import E2E | ⏸️ PARKED | No test data |
| OSRM Live Validation | ⏸️ PARKED | No OSRM map for Wien |
| Coords Quality Gate E2E | ⏸️ PARKED | Needs real addresses |
| `scripts/run_wien_pilot_dry_run.py` | ⏸️ PARKED | Requires input file |

### What Still Runs

| Component | Status | Tests |
|-----------|--------|-------|
| Routing Unit Tests | ✅ ACTIVE | `pytest backend_py/packs/routing/tests/` |
| OSRM Map Hash Tests | ✅ ACTIVE | 18 tests (path-neutral hashing) |
| Golden Dataset Regression | ✅ ACTIVE | Schema validation only |
| Security Gate | ✅ ACTIVE | `scripts/ci/security_gate.sh` |
| Roster E2E Gate | ✅ ACTIVE | `scripts/ci/wien_roster_gate.sh` |

### Unblock Checklist

- [ ] FLS test export file received (JSON with 10+ orders)
- [ ] OSRM map data for Wien region available
- [ ] Zone resolver populated with Wien PLZ codes
- [ ] Test tenant configured with Wien site

---

## 🔐 V3.7 Auth Separation (Jan 8, 2026) ✅ NEW

### Overview

V3.7 enforces strict separation between Platform and Pack authentication:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AUTH SEPARATION (V3.7)                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  PLATFORM AUTH               PACK AUTH                              │
│  (/api/v1/platform/*)        (/api/v1/routing/*, /api/v1/roster/*) │
│  ├─ Session cookies          ├─ X-API-Key                          │
│  ├─ CSRF tokens              ├─ HMAC signature                     │
│  ├─ RBAC roles               ├─ Nonce replay protection            │
│  └─ dev-login BLOCKED prod   └─ Idempotency integration            │
│                                                                     │
│  REJECTS: API Key, HMAC      REJECTS: Session, CSRF                │
│                                                                     │
│                 NO ENDPOINT ACCEPTS BOTH!                           │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files (V3.7)

| File | Purpose |
|------|---------|
| `api/security/platform_auth.py` | Session + CSRF + RBAC for platform |
| `api/security/tenant_auth.py` | API Key + HMAC + Nonce for packs |
| `scripts/ci/security_gate.sh` | DB hardening verification |
| `scripts/ci/wien_roster_gate.sh` | Roster E2E dry run |

### Key Features

1. **Platform Auth** (`platform_auth.py`):
   - `require_platform_session(roles=[...])` dependency
   - Session cookies with HMAC signing
   - CSRF token validation for POST/PUT/PATCH/DELETE
   - `reject_tenant_auth_headers()` blocks API Key on platform
   - `dev_login()` HARD BLOCKED in production

2. **Tenant HMAC Auth** (`tenant_auth.py`):
   - `require_tenant_hmac()` dependency
   - HMAC-SHA256 signature verification
   - Nonce replay protection (5-minute TTL)
   - Idempotency key integration
   - `reject_platform_auth_headers()` blocks sessions on packs

3. **Middleware Enforcement** (`main.py`):
   - Auth separation middleware rejects mismatched auth at request level
   - Runs BEFORE route handlers
   - Logs violations for security monitoring

### Wien W02 Gates

| Gate | Script | Expected Output |
|------|--------|-----------------|
| **Security** | `security_gate.sh` | solvereign_api → "Permission denied" on tenants |
| **Roster** | `wien_roster_gate.sh` | 7/7 audit checks PASS, determinism verified |

---

## 🏢 V3.4 Enterprise Extensions (Jan 7, 2026) ✅

### Overview

V3.4 adds 4 **Enterprise Extensions** (Skills 113-116) for production-grade monitoring, testing, and audit compliance:

```
┌─────────────────────────────────────────────────────────────────────┐
│              ENTERPRISE EXTENSIONS (4 SKILLS, 88 TESTS)             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ SKILL 116: KPI Drift    SKILL 115: Golden      SKILL 114: Impact   │
│ ├─ Anomaly detection    ├─ Versioned fixtures  ├─ Risk assessment  │
│ ├─ Baseline protection  ├─ Hash validation     ├─ Rollback plans   │
│ └─ 26 tests ✅          └─ 12 tests ✅         └─ 24 tests ✅      │
│                                                                     │
│ SKILL 113: Audit Report                                             │
│ ├─ Evidence collection (101+103+104+106+112)                        │
│ ├─ Compliance matrix (GDPR/SOC2/ISO27001)                           │
│ ├─ Customer-safe redaction                                          │
│ └─ 26 tests ✅                                                      │
│                                                                     │
│                     TOTAL: 88/88 TESTS PASS                         │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files (V3.4)

| Skill | Directory | Purpose |
|-------|-----------|---------|
| 116 | `backend_py/skills/kpi_drift/` | KPI Drift Detector |
| 115 | `backend_py/skills/golden_datasets/` | Golden Dataset Manager |
| 114 | `backend_py/skills/impact_preview/` | Change Impact Analyzer |
| 113 | `backend_py/skills/audit_report/` | Enterprise Audit Report Generator |

### Skill Details

#### Skill 116: KPI Drift Detector
- **Purpose**: Proactive anomaly detection for solver KPIs
- **Thresholds**: OK (<10%), WARNING (10-25%), ALERT (25-50%), INCIDENT (>50%)
- **Features**: Z-score + percent-change drift calculation, weighted metrics
- **Baseline Protection**: APPROVER role required (automation cannot write)
- **CLI**: `python -m backend_py.skills.kpi_drift check --tenant X --pack Y`
- **Exit Codes**: 0=OK, 1=WARNING, 2=ALERT, 3=INCIDENT

#### Skill 115: Golden Dataset Manager
- **Purpose**: Versioned test fixtures for regression testing
- **Datasets**: `golden_datasets/routing/wien_small/`, `golden_datasets/roster/gurkerl_small/`
- **Features**: SHA256 input/output hashes, manifest versioning
- **CLI**: `python -m backend_py.skills.golden_datasets list|validate|regression`
- **Exit Codes**: 0=PASS, 1=FAIL

#### Skill 114: Impact Preview
- **Purpose**: "Was bricht wenn...?" for every change
- **Change Types**: CONFIG, PACK, MIGRATION, CODE
- **Risk Levels**: SAFE (0), CAUTION (1), RISKY (2), BLOCKED (3)
- **Features**: Affected tenant analysis, rollback plan generation
- **CLI**: `python -m backend_py.skills.impact_preview analyze --change-type X --target Y`

#### Skill 113: Audit Report Generator
- **Purpose**: One-click proof pack for CIO/CISO audits
- **Orchestrates**: Skills 101+103+104+106+112
- **Compliance**: GDPR, SOC2, ISO27001 matrix
- **Output Modes**: INTERNAL (full), CUSTOMER_SAFE (redacted)
- **Features**: Evidence ZIP, hash chain, redaction verification
- **CLI**: `python -m backend_py.skills.audit_report generate|platform|compliance`

### CI Integration

All skills integrated in `.github/workflows/pr-guardian.yml`:

```yaml
jobs:
  kpi-drift-tests:         # Skill 116 - 26 tests
  golden-dataset-tests:    # Skill 115 - 12 tests
  impact-preview-tests:    # Skill 114 - 24 tests
  audit-report-tests:      # Skill 113 - 26 tests
```

---

## 🚀 V3.3b Routing-Pack Pilot Gates (Jan 6, 2026) ✅

### Overview

V3.3b implements 6 critical **Go/No-Go Gates** for production-ready Routing-Pack deployment:

```
┌─────────────────────────────────────────────────────────────────────┐
│                 ROUTING-PACK PILOT GATES (6/6 PASS)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ GATE 1: Realistic Solver   GATE 2: Audit-Gating    GATE 3: RLS Test│
│ ├─ OR-Tools VRPTW          ├─ FAIL blocks lock     ├─ Thread-local │
│ ├─ GUIDED_LOCAL_SEARCH     ├─ HTTP 409 Conflict   ├─ 2 tenants    │
│ └─ 3 tests ✅              └─ 12 tests ✅          └─ 3 tests ✅   │
│                                                                     │
│ GATE 4: Site Partition     GATE 5: Artifact Store  GATE 6: Freeze  │
│ ├─ Advisory locks          ├─ S3/Azure/Local       ├─ Hard gate    │
│ ├─ FK enforcement          ├─ SHA256 integrity     ├─ DB is_locked │
│ └─ 19 tests ✅             └─ 19 tests ✅          └─ 12 tests ✅  │
│                                                                     │
│                        TOTAL: 68/68 TESTS PASS                      │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files (V3.3b)

| File | Purpose |
|------|---------|
| `packs/routing/tests/test_solver_realistic.py` | Gate 1: OR-Tools actual solve proof |
| `packs/routing/services/plan_service.py` | Gate 2: AuditGate + PlanService |
| `packs/routing/tests/test_audit_gate.py` | Gate 2: 12 audit gate tests |
| `packs/routing/tests/test_rls_parallel_leak.py` | Gate 3: RLS isolation tests |
| `db/migrations/021_scenario_site_partitioning.sql` | Gate 4: Site FK + advisory locks |
| `packs/routing/services/site_partitioning.py` | Gate 4: Site partitioning service |
| `packs/routing/tests/test_site_partitioning.py` | Gate 4: 19 partitioning tests |
| `packs/routing/services/evidence/artifact_store.py` | Gate 5: Abstract store interface |
| `packs/routing/tests/test_artifact_store.py` | Gate 5: 19 artifact tests |
| `packs/routing/services/repair/freeze_lock_enforcer.py` | Gate 6: Hard freeze enforcement |
| `packs/routing/tests/test_freeze_lock_enforcer.py` | Gate 6: 12 freeze tests |

### Gate Details

#### Gate 1: OR-Tools Realistic Solver Test
- **Problem**: 21ms E2E test only tested pipeline, not actual solver
- **Solution**: Verify `status=ROUTING_SUCCESS`, `objective>0`, `search_time>1ms`
- **Metaheuristic**: `GUIDED_LOCAL_SEARCH` with 5s time limit

#### Gate 2: Audit-Gating at Lock Endpoint
- **Problem**: FAIL audit should block plan lock (not just warn)
- **Solution**: `AuditGate.check_lock_allowed()` → FAIL = HTTP 409
- **Required Checks**: Coverage, Time Window, Shift Feasibility, Skills, Overlap

#### Gate 3: Two-Tenant Parallel RLS Leak Test
- **Problem**: Verify tenant isolation under parallel Celery execution
- **Solution**: `threading.local()` tenant context, 0 cross-tenant leaks

#### Gate 4: Site/Depot Partitioning Enforcement
- **Problem**: Advisory locks must scope per tenant+site
- **Solution**: `routing_advisory_lock_key(tenant_id, site_id, scenario_id)` + FK

#### Gate 5: Evidence Pack via Artifact Store + Hash
- **Problem**: Evidence needs cloud storage with integrity verification
- **Solution**: Abstract `ArtifactStore` (Local/S3/Azure) + SHA256 hash

#### Gate 6: Repair Freeze-Locks Hard Enforce from DB
- **Problem**: Freeze-locks were recommendations, not hard gates
- **Solution**: `FreezeLockEnforcer` raises `FreezeLockViolationError`

### Plan State Machine (Updated)

```
QUEUED → SOLVING → SOLVED → AUDITED → DRAFT → LOCKED
                     ↓         ↓
                  [FAIL]    [FAIL blocks LOCK via Gate 2]
```

### Vision: Pilot Deployment

**Target Verticals**: MediaMarkt, HDL Plus

**Deployment Steps**:
1. Apply migrations (`021_scenario_site_partitioning.sql`)
2. Configure artifact store (S3/Azure Blob)
3. Deploy to pilot tenant
4. Monitor Celery RLS isolation
5. Validate freeze-lock enforcement

---

## 🚀 V3.2 Simulation Framework (Jan 5, 2026) ✅ NEW

### Overview

V3.2 adds a comprehensive **What-If Simulation Framework** with 13 business scenarios across 5 categories:

```
┌─────────────────────────────────────────────────────────────────────┐
│                 SIMULATION FRAMEWORK (13 Szenarien)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ ECONOMIC (3)           COMPLIANCE (2)        OPERATIONAL (3)        │
│ ├─ Cost Curve          ├─ Max-Hours Policy   ├─ Patch-Chaos         │
│ ├─ Freeze Tradeoff     └─ Driver-Friendly    ├─ Sick-Call Drill     │
│ └─ Headcount Budget                          └─ Tour-Cancel         │
│                                                                     │
│ STRATEGIC (2)          ADVANCED V3.2 (3)                            │
│ ├─ Auto-Seed-Sweep     ├─ Multi-Failure Cascade                     │
│ └─ Multi-Scenario      ├─ Probabilistic Churn (Monte Carlo)         │
│    Comparison          └─ Policy ROI Optimizer (Pareto)             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files (V3.2)

| File | Lines | Purpose |
|------|-------|---------|
| `v3/simulation_engine.py` | ~2,500 | Unified simulation framework |
| `v3/seed_sweep.py` | ~520 | Auto-seed optimization with parallel execution |
| `v3/plan_churn.py` | ~212 | Plan stability metrics |
| `v3/near_violations.py` | ~302 | Yellow Zone warnings |
| `v3/peak_fleet.py` | ~229 | Concurrent tour analysis |
| `v3/audit_fixed.py` (updated) | +150 | 8th audit check: Sensitivity |
| ~~`cli.py`~~ | ~~+350~~ | ~~9 simulation CLI commands~~ **DEPRECATED: Removed in V4.5** |
| ~~`streamlit_app.py`~~ | ~~+500~~ | ~~Simulation Tab with all 13 scenarios~~ **DEPRECATED: Removed in V4.5** |
| `tests/test_simulation.py` | ~680 | Comprehensive test suite |

### 8 Audit Checks (Updated from 6)

| # | Check | Criteria | Status |
|---|-------|----------|--------|
| 1 | **COVERAGE** | Every tour assigned exactly once | ✅ |
| 2 | **OVERLAP** | No driver works overlapping tours | ✅ |
| 3 | **REST** | ≥11h rest between consecutive blocks | ✅ |
| 4 | **SPAN_REGULAR** | Regular blocks ≤14h span | ✅ |
| 5 | **SPAN_SPLIT** | Split blocks ≤16h span + 240-360min break | ✅ |
| 6 | **FATIGUE** | No consecutive 3er→3er days | ✅ |
| 7 | **REPRODUCIBILITY** | Same inputs → same outputs | ✅ |
| 8 | **SENSITIVITY** | Churn <10% under perturbations | ✅ NEW |

### CLI Commands (V3.2)

```bash
# Basic Scenarios
solvereign simulate cost-curve --forecast 1
solvereign simulate max-hours --forecast 1 --caps 55,52,50,48
solvereign simulate auto-sweep --forecast 1 --seeds 15
solvereign simulate headcount --forecast 1 --target 140
solvereign simulate tour-cancel --forecast 1 --count 20
solvereign simulate sick-call --forecast 1 --count 5 --day 1

# V3.2 Advanced Scenarios
solvereign simulate multi-failure --forecast 1 --count 5 --tours 10 --cascade 0.15
solvereign simulate prob-churn --forecast 1 --sims 100 --threshold 0.10
solvereign simulate policy-roi --forecast 1 --budget 5 --optimize balanced
```

### Usage Examples

```python
# Cost Curve Analysis
from v3.simulation_engine import run_cost_curve
result = run_cost_curve(tour_instances, baseline_seed=94)
# → Shows cost of each rule in drivers

# Monte Carlo Churn Forecast
from v3.simulation_engine import run_probabilistic_churn
result = run_probabilistic_churn(
    num_simulations=100,
    churn_threshold=0.10,
    failure_probability=0.05
)
# → P(Churn > 10%) with confidence intervals

# Policy ROI Optimizer (Pareto Frontier)
from v3.simulation_engine import run_policy_roi_optimizer
result = run_policy_roi_optimizer(
    budget_drivers=5,
    optimize_for="balanced",  # "cost" | "stability" | "balanced"
    constraints=["arbzg_compliant"]
)
# → Optimal policy combination with ROI score

# Auto-Seed-Sweep (Parallel)
from v3.seed_sweep import auto_seed_sweep
result = auto_seed_sweep(tour_instances, num_seeds=15, parallel=True)
# → Best seed with lexicographic optimization
```

---

## 🚀 V3.1 Enterprise Features (Jan 2026)

### Overview

V3.1 adds enterprise-grade features for incremental forecasts, scenario comparison, and operational stability:

1. ✅ **Compose Engine** - LWW merge for partial Slack forecasts
2. ✅ **Partial Release Gating** - Completeness check with admin override
3. ✅ **Scenario Runner** - Parameterized solver comparison
4. ✅ **Churn Minimization** - Stability penalty vs baseline
5. ✅ **Freeze Windows** - Baseline-tied assignment locks

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `v3/compose.py` | ~400 | LWW Compose Engine |
| `v3/scenario_runner.py` | ~350 | Scenario comparison framework |
| `v3/models.py` (updated) | +150 | New models (SolverConfig, ScenarioResult, etc.) |
| `db/migrations/002_compose_scenarios.sql` | ~150 | Schema extensions |

### Schema Changes (Migration 002)

**forecast_versions** extensions:
- `week_key VARCHAR(20)` - Week identifier (e.g., "2026-W01")
- `completeness_status` - UNKNOWN | PARTIAL | COMPLETE
- `expected_days INTEGER` - Expected days per week (default 6)
- `days_present INTEGER` - Actual days with tours
- `provenance_json JSONB` - Patch chain tracking
- `parent_version_id` - Patch chain parent

**plan_versions** extensions:
- `scenario_label VARCHAR(100)` - Named scenarios
- `baseline_plan_version_id` - Churn calculation reference
- `solver_config_json JSONB` - Full config storage
- `churn_count INTEGER` - Instance changes
- `churn_drivers_affected INTEGER` - Affected drivers

**New tables**:
- `forecast_compositions` - Patch provenance
- `tour_removals` - Explicit tombstones

### Usage Examples

```python
# Compose Engine
from v3.compose import compose_week_forecast, check_release_gate

result = compose_week_forecast("2026-W01", conn, expected_days=6)
gate = check_release_gate(result.composed_version_id, conn)

# Scenario Runner
from v3.scenario_runner import ScenarioRunner
from v3.models import SolverConfig

runner = ScenarioRunner(conn)
comparison = runner.run_scenarios(
    forecast_version_id=1,
    scenarios=[
        SolverConfig(seed=42, churn_weight=0.0),
        SolverConfig(seed=42, churn_weight=0.5),
    ],
    week_key="2026-W01"
)
best = comparison.best_by_drivers()

# Freeze Windows
from v3.solver_wrapper import check_freeze_violations

violations = check_freeze_violations(forecast_id, baseline_plan_id, 720)
```

---

## 🔧 P0 Fixes Complete (Jan 2026)

### Critical Blockers Fixed

**All P0 blockers in V3 architecture have been resolved:**

1. ✅ **Template vs Instances** (Data Model Fix)
   - Problem: `tours_normalized.count=3` but only 1 assignment possible → Coverage check broken
   - Solution: Created `tour_instances` table (1:1 mapping with assignments)
   - Files: [001_tour_instances.sql](db/migrations/001_tour_instances.sql), [db_instances.py](v3/db_instances.py)

2. ✅ **Cross-Midnight Time Model** (Explicit Semantics)
   - Problem: `start_ts="22:00"` `end_ts="06:00"` unclear if cross-midnight
   - Solution: Added `crosses_midnight BOOLEAN` field to tour_instances
   - Impact: Reliable Rest/Overlap/Span checks

3. ✅ **LOCKED Immutability** (Complete Protection)
   - Problem: LOCKED plans only protected `plan_versions`, not `assignments`/`tour_instances`/`audit_log`
   - Solution: Added database triggers to prevent modifications
   - Behavior:
     - ❌ LOCKED: No UPDATE/DELETE on `assignments`, `tour_instances` (plan-relevant tables)
     - ✅ ALLOWED: INSERT into `audit_log` (append-only audit trail, even after LOCK)
     - ⚠️ STATUS CHANGE: `plan_versions.status` transitions via controlled procedure only

### Implementation Summary

- **Files Created**: 5 new files (1,618+ lines)
- **Migration**: [001_tour_instances.sql](db/migrations/001_tour_instances.sql) (154 lines)
- **Fixed DB Ops**: [db_instances.py](v3/db_instances.py) (194 lines)
- **Fixed Audit**: [audit_fixed.py](v3/audit_fixed.py) (420 lines)
- **Test Suite**: [test_p0_migration.py](test_p0_migration.py) (450 lines)
- **Documentation**: [P0_MIGRATION_GUIDE.md](P0_MIGRATION_GUIDE.md) (400+ lines)

**See**: [P0_FIXES_SUMMARY.md](P0_FIXES_SUMMARY.md) for complete details.

---

## 🔒 Proof Hardening Complete (Jan 4, 2026)

### Critical Audit Fixes (Production Hardening)

**All 8 critical proof issues have been systematically fixed:**

#### 1. ✅ **Canonical Input Hash** (Proof #2A)
   - **Problem**: Used raw CSV bytes → broke on whitespace changes
   - **Solution**: Sorted canonical lines (`"Mo 08:00-16:00 Depot West"`)
   - **Impact**: Deterministic input hashing, immune to format changes

#### 2. ✅ **crosses_midnight Computation** (Proof #2B)
   - **Problem**: Hardcoded `False` for ALL tours → overnight audits invalid
   - **Solution**: `crosses_midnight = (tour.end_time < tour.start_time)`
   - **Impact**: Correct identification of 22:00-06:00 tours

#### 3. ✅ **Comprehensive output_hash** (Proof #2C)
   - **Problem**: Only hashed `(driver_id, day, tour_instance_id)` → collision risk
   - **Solution**: Includes `block_type`, `start_min`, `end_min`, `crosses_midnight`, `solver_config_hash`
   - **Impact**: Robust reproducibility verification

#### 4. ✅ **O(n) Duplicate Detection** (Proof #4)
   - **Problem**: O(n²) list comprehension with `.count()`
   - **Solution**: `Counter(assigned_ids)` for O(n) performance
   - **Impact**: Scalable coverage validation

#### 5. ✅ **Datetime-Based Overlap/Rest** (Proof #5)
   - **Problem**: TIME-only arithmetic → missed cross-midnight overlaps, incorrect Sun→Mon rest
   - **Solution**: `week_anchor_date` with absolute `start_dt`/`end_dt` computation
   - **Impact**: 100% coverage of all overlap/rest violations

#### 6. ✅ **Exact 360min Split Break** (Proof #6)
   - **Problem**: `>120min` heuristic → not auditfähig
   - **Solution**: `if break_minutes != 360` → EXACT check, no tolerance
   - **Impact**: Audit-compliant split shift validation

#### 7. ✅ **V2 Tour Model Cross-Midnight** (Red Flag Resolved)
   - **Problem**: `end_ts = time(23, 59)` hack → audit invalid
   - **Solution**: Extended `Tour` model with native `crosses_midnight` field
   - **Impact**: No more 23:59 hack, real end times preserved

#### 8. ✅ **Freeze Window Implementation** (Proof #9)
   - **Problem**: Missing → not production-ready
   - **Solution**: Deterministic freeze logic with simulated `now` timestamp
   - **Impact**: Operational stability requirement satisfied

### Files Modified

1. **[generate_golden_run.py](generate_golden_run.py)** (~120 lines) - Canonical input, crosses_midnight, strong output_hash
2. **[test_audit_proofs.py](test_audit_proofs.py)** (~300 lines) - Datetime-based Proofs #4-9
3. **[src/domain/models.py](../src/domain/models.py)** (~50 lines) - Tour model with crosses_midnight field
4. **[v3/solver_v2_integration.py](v3/solver_v2_integration.py)** (~10 lines) - Pass real times (no hack)

**Total**: ~480 lines modified/added

### Evidence Artifacts

- **[PROOF_FIXES_SUMMARY.md](../PROOF_FIXES_SUMMARY.md)** - Complete technical details
- **[SKILL.md](../SKILL.md)** - Operating manual for future work

### Verification Status

| Proof | Status | Key Fix |
|-------|--------|---------|
| **#2 (A)** | ✅ FIXED | Canonical input hash with sorted lines |
| **#2 (B)** | ✅ FIXED | Correct crosses_midnight computation |
| **#2 (C)** | ✅ FIXED | Comprehensive output_hash |
| **#4** | ✅ PASS | O(n) duplicate detection, 100% coverage |
| **#5** | ✅ PASS | Rest check between BLOCKS (days), not tours |
| **#6** | ✅ PASS | 16h span for 3er/split, 14h for regular, 240-360min split breaks |
| **#7** | ✅ PASS | V2 Tour model with crosses_midnight |
| **#8** | ✅ PASS | No consecutive 3er→3er (fatigue rule in can_assign) |
| **#9** | ✅ PASS | Freeze window with datetime logic |

**Result**: **ALL 8 AUDITS PASS** - water-tight and production-ready.

---

## 📊 Final Status (V3.2 Complete)

```
═══════════════════════════════════════════════════════════════════
                    SOLVEREIGN V3.2 - PRODUCTION METRICS
═══════════════════════════════════════════════════════════════════

SOLVER PERFORMANCE:
  Drivers:     142-145 (FTE, varies by seed)
  PT Drivers:  0 (100% FTE)
  Coverage:    1385/1385 tours (100%)
  Violations:  0 (Rest/Overlap/Span/Fatigue)
  All Audits:  8/8 PASS

BLOCK MIX (Seed 94):
  3er-chain:  193 blocks (connected triples, 30-60min gaps)
  2er-split:  157 blocks (240-360min break)
  2er-reg:    189 blocks (30-60min gap)
  1er:        114 blocks (single tours)
  Total:      653 blocks

SIMULATION FRAMEWORK:
  Scenarios:       13 (Economic, Compliance, Operational, Strategic, Advanced)
  Monte Carlo:     Up to 1000 simulations
  Parallel Seeds:  4 workers (ThreadPoolExecutor)
  Risk Scoring:    LOW | MEDIUM | HIGH | CRITICAL

CODE STATISTICS:
  V3 Core Modules:     ~7,500 lines
  Simulation Engine:   ~2,500 lines
  ~~Streamlit UI:        ~2,850 lines~~ (DEPRECATED: Removed in V4.5)
  ~~CLI:                 ~770 lines~~ (DEPRECATED: Removed in V4.5)
  Tests:               ~1,500 lines
  ─────────────────────────────────
  Total Codebase:      ~11,000+ lines (excl. deprecated UI/CLI)
```

### Block Type Rules (Final)

| Block Type | Gap Between Tours | Span Limit | Description |
|------------|-------------------|------------|-------------|
| **3er-chain** | 30-60min | ≤16h | Connected triple, max 120min idle/day |
| **2er-split** | 240-360min | ≤16h | Split shift with 4-6h break |
| **2er-reg** | 30-60min | ≤14h | Regular double shift |
| **1er** | N/A | N/A | Single tour |

### Key Achievements (Jan 2026)
1.  **Baseline Re-Established**: Moved from ~250 (Legacy) -> **142 Drivers**.
2.  **Fatigue Safety**: Implemented "No Consecutive Triple Days" rule (3er → 3er forbidden) in `can_assign()`.
3.  **3er-Chain Quality**: 3er blocks now require 30-60min gaps only (no 4-6h split gaps).
4.  **Split Break Range**: 2er-split allows 240-360min breaks (4-6h) instead of exactly 360min.
5.  **Visualization**: Deployed `final_schedule_matrix.html` - Dispatcher Cockpit.
6.  **Clean Codebase**: Removed 20+ legacy files, stabilizing on V2 Architecture.

---

## 🛑 Operational Rules

### 1. Legal Compliance (Hard)
*   **11h Rest**: Strictly enforced between blocks.
*   **Max Span**: 14h (Regular) / 16h (Split).
*   **Split Break**: Exactly 360m (6h) for Split shifts.

### 2. Fatigue Management (Soft/Hard)
*   **Triple Limit**: A driver performing a Triple Tour (3er) **cannot** do a Triple Tour the next day.
*   **Gap Quality**: Gaps < 45 min are flagged as "Risk" in the dashboard.

---

## 📘 Operational Runbook

### 1. Standard Run
*   **Command**: `python backend_py/run_block_heuristic.py`
*   **Input**: `forecast input.csv` (Standard) or `forecast_kw51.csv` (Compressed).
*   **Output**:
    *   `final_schedule_matrix.csv` (Data)
    *   `final_schedule_matrix.html` (Visual Dashboard)

### 2. Tuning
*   **Seed Optimization**: Run `python find_best_partition.py` to find the best seed for new data.
    *   Current Best (Normal): **Seed 94** (Peak 145).
    *   Current Best (KW51): **Seed 18** (Peak 187).

### 3. Verification
*   **Regression Test**: `python test_golden_run.py`
    *   Checks Coverage, Rest, Overlap, and KPI adherence.

---

## ✅ Completed Milestones (History)

### v8.0.0 Final Delivery (Jan 3, 2026)
**Context**: User required a production-ready roster with visual confirmation of safety rules.
**Deliverables**:
*   [x] **Solver V2**: Block Heuristic + Min-Cost Max-Flow.
*   [x] **Fatigue Rule**: Forbid 3er->3er transitions.
*   [x] **Dispatcher Heatmap**: Interactive HTML export.
*   [x] **Cleanup**: Repo sanitized.

### v7.0.0 Legacy V1 Freeze (Dec 2025)
**Context**: Old MIP solver (deprecated).
**Result**: 156 Drivers. Superseded by V2 (145 Drivers).

---

## 🏗️ V3 Architecture: Deterministic Pipeline (MVP)

> **Status**: DESIGN COMPLETE → IMPLEMENTATION READY
> **Goal**: Transform V2 solver into production-ready operational platform
> **Philosophy**: Event Sourcing + Immutable Infrastructure + Audit Trail

### State Machine Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  Ingest (Slack/CSV) → Parse → Validate → Normalize → Version       │
│       ↓                                                             │
│  Diff → Solve (DRAFT) → Audit → Release (LOCK) → Export           │
└─────────────────────────────────────────────────────────────────────┘
```

**Stage Details:**

1. **Ingest**: Accept Slack text or CSV input
2. **Parse** (Whitelist): `tours_raw` + parse_result
3. **Validate Gate**: PASS/WARN/FAIL per line + global status
4. **Normalize**: `tours_normalized` (canonical IDs, times, cross-midnight handling)
5. **Version**: `forecast_version++` + `input_hash`
6. **Diff**: Compare against previous forecast → ADDED/REMOVED/CHANGED
7. **Solve (DRAFT)**: Generate `plan_version` (status=DRAFT)
8. **Audit**: Coverage/Rest/Overlap/Span checks → KPI JSON
9. **Release (LOCK)**: Manual approval → `plan_version` (status=LOCKED) + Freeze Policy
10. **Export**: `matrix.csv`, `rosters.csv`, `kpis.json`, `audit_summary.json`

**Critical Rules:**
- ✅ Solve runs automatically
- ⛔ Release requires manual approval (button)
- 📨 Messaging only from LOCKED plans (future feature)

### Data Model (Postgres) – Minimal but Complete

**Core Tables (MVP):**

#### 1. `forecast_versions`
```sql
id                  SERIAL PRIMARY KEY
created_at          TIMESTAMP NOT NULL DEFAULT NOW()
source              VARCHAR(50) NOT NULL  -- 'slack' | 'manual' | 'csv'
input_hash          VARCHAR(64) NOT NULL  -- SHA256 of canonical input
parser_config_hash  VARCHAR(64) NOT NULL  -- Version control for parser rules
status              VARCHAR(10) NOT NULL  -- 'PASS' | 'WARN' | 'FAIL'
week_anchor_date    DATE NOT NULL         -- Anchor date (e.g., Monday) for deterministic datetime computation
notes               TEXT
```

#### 2. `tours_raw`
```sql
id                  SERIAL PRIMARY KEY
forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id)
line_no             INTEGER NOT NULL
raw_text            TEXT NOT NULL
parse_status        VARCHAR(10) NOT NULL  -- 'PASS' | 'WARN' | 'FAIL'
parse_errors        JSONB                 -- [{code, message, severity}, ...]
parse_warnings      JSONB
canonical_text      TEXT                  -- Standardized format for hashing
```

#### 3. `tours_normalized` (Template Table)
```sql
id                  SERIAL PRIMARY KEY     -- Stable template ID
forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id)
day                 INTEGER NOT NULL       -- 1-7 (Mo-So)
start_ts            TIME NOT NULL
end_ts              TIME NOT NULL
duration_min        INTEGER NOT NULL
work_hours          DECIMAL(5,2) NOT NULL
span_group_key      VARCHAR(50)            -- For split shift grouping
tour_fingerprint    VARCHAR(64) NOT NULL   -- For diff matching (fingerprint on Templates, NOT instances)
count               INTEGER DEFAULT 1      -- Number of instances to expand
depot               VARCHAR(50)
skill               VARCHAR(50)
```

#### 3b. `tour_instances` (Expanded Instance Table)
```sql
id                  SERIAL PRIMARY KEY     -- Instance ID (for 1:1 assignment mapping)
forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id)
tour_template_id    INTEGER NOT NULL REFERENCES tours_normalized(id)
instance_no         INTEGER NOT NULL       -- 1, 2, 3 for count=3
day                 INTEGER NOT NULL       -- 1-7 (Mo-So)
start_ts            TIME NOT NULL
end_ts              TIME NOT NULL
crosses_midnight    BOOLEAN NOT NULL       -- TRUE if end_ts < start_ts
duration_min        INTEGER NOT NULL
work_hours          DECIMAL(5,2) NOT NULL
span_group_key      VARCHAR(50)
depot               VARCHAR(50)
skill               VARCHAR(50)
UNIQUE(tour_template_id, instance_no)
```

#### 4. `plan_versions`
```sql
id                  SERIAL PRIMARY KEY
forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id)
created_at          TIMESTAMP NOT NULL DEFAULT NOW()
seed                INTEGER NOT NULL       -- Deterministic solver seed
solver_config_hash  VARCHAR(64) NOT NULL   -- Solver parameter version
output_hash         VARCHAR(64) NOT NULL   -- SHA256(assignments + kpis)
status              VARCHAR(20) NOT NULL   -- 'DRAFT' | 'LOCKED' | 'SUPERSEDED'
locked_at           TIMESTAMP
locked_by           VARCHAR(100)
```

#### 5. `assignments`
```sql
id                  SERIAL PRIMARY KEY
plan_version_id     INTEGER NOT NULL REFERENCES plan_versions(id)
driver_id           VARCHAR(50) NOT NULL   -- roster_id or driver identifier
tour_instance_id    INTEGER NOT NULL REFERENCES tour_instances(id)  -- 1:1 assignment mapping
day                 INTEGER NOT NULL
block_id            VARCHAR(50) NOT NULL   -- e.g., "D1_B3" (Day 1, Block 3)
role                VARCHAR(50)            -- Optional: 'PRIMARY' | 'BACKUP'
```

#### 6. `audit_log`
```sql
id                  SERIAL PRIMARY KEY
plan_version_id     INTEGER NOT NULL REFERENCES plan_versions(id)
check_name          VARCHAR(100) NOT NULL  -- 'COVERAGE' | 'REST' | 'OVERLAP' | 'SPAN'
status              VARCHAR(10) NOT NULL   -- 'PASS' | 'FAIL'
count               INTEGER                -- Violation count (0 for PASS)
details_json        JSONB                  -- Full check details
created_at          TIMESTAMP NOT NULL DEFAULT NOW()
```

#### 7. `freeze_windows` (Optional MVP)
```sql
id                  SERIAL PRIMARY KEY
rule_name           VARCHAR(100) NOT NULL  -- 'PRE_SHIFT_12H' | 'SAME_DAY'
minutes_before_start INTEGER NOT NULL      -- Freeze threshold
behavior            VARCHAR(50) NOT NULL   -- 'FROZEN' | 'OVERRIDE_REQUIRED'
enabled             BOOLEAN DEFAULT TRUE
```

**Future Tables (V4+):**
- `drivers`: Driver master data
- `driver_states_weekly`: Availability, preferences, constraints
- `messages`: Notifications sent to drivers
- `acks`: Driver confirmations
- `overrides`: Manual freeze window bypasses

**Non-Negotiable Rule:**
> Every output must reference `plan_version_id`. No "latest plan" without explicit version.

### 4. Parser: Deterministic, Strict, Auditable

**Core Principle:** Whitelist-only parsing. No "best effort" fallbacks.

**Parser Output (Per Line):**
```python
@dataclass
class ParseResult:
    parse_status: Literal["PASS", "WARN", "FAIL"]
    normalized_fields: dict  # {day, start, end, count, depot?, zone?}
    canonical_text: str      # Standardized format for hashing
    issues: list[Issue]      # [{code, message, severity}, ...]

@dataclass
class Issue:
    code: str           # e.g., "INVALID_TIME_FORMAT", "MISSING_DAY"
    message: str        # Human-readable error
    severity: str       # "ERROR" | "WARNING"
```

**Validation Gate Logic:**
- ✅ `forecast_versions.status = PASS`: All lines parsed successfully → Proceed to Solve
- ⚠️ `forecast_versions.status = WARN`: Warnings present but no failures → Proceed with caution
- ❌ `forecast_versions.status = FAIL`: Any line failed → **Block Solve/Release**

**Example Whitelist Patterns:**
```
✅ PASS: "Mo 06:00-14:00 3 Fahrer Depot Nord"
✅ PASS: "Di 06:00-14:00 + 15:00-19:00" (split shift)
✅ PASS: "Mi 06:00-14:00"
⚠️ WARN: "Do 06:00-14:00 2 Fahrer" (count mismatch vs. historical avg)
❌ FAIL: "Fr early shift" (ambiguous time)
❌ FAIL: "Sa 25:00-14:00" (invalid time)
```

### 5. Diff Engine: Changes Are Objects, Not Feelings

**Matching Rule (Stable Tour Identity):**
```python
tour_fingerprint = hash(day, start_minute, end_minute, depot?, skill?)
```

**Diff Classification:**
```python
class DiffType(Enum):
    ADDED = "ADDED"        # New fingerprint in forecast_version N
    REMOVED = "REMOVED"    # Fingerprint present in N-1, absent in N
    CHANGED = "CHANGED"    # Same fingerprint, different attributes (count, depot, etc.)

@dataclass
class TourDiff:
    diff_type: DiffType
    fingerprint: str
    old_values: dict | None  # For REMOVED/CHANGED
    new_values: dict | None  # For ADDED/CHANGED
    changed_fields: list[str]  # For CHANGED only
```

**Output Format:**
```json
{
  "forecast_version_old": 47,
  "forecast_version_new": 48,
  "summary": {
    "added": 5,
    "removed": 2,
    "changed": 3
  },
  "details": [
    {
      "diff_type": "ADDED",
      "fingerprint": "Mo_0600_1400_DepotNord",
      "new_values": {"day": 1, "start": "06:00", "end": "14:00", "count": 3}
    },
    {
      "diff_type": "CHANGED",
      "fingerprint": "Di_0700_1500_DepotSued",
      "old_values": {"count": 2},
      "new_values": {"count": 4},
      "changed_fields": ["count"]
    }
  ]
}
```

**Template Expansion Strategy:**
- **Storage (Template)**: 1 row in `tours_normalized` with `count=3`
- **Storage (Instances)**: 3 rows in `tour_instances` (instance_no=1,2,3)
- **Solver**: Operates on `tour_instances` (1:1 mapping with assignments)
- **Diff**: Changing template count from 3→4 = CHANGED → regenerate instances → mark as CHANGED
- **Audit**: Coverage/Overlap/Rest/Span checks run on `tour_instances` (NOT templates)

### 6. Freeze Windows: No More Ping-Pong

**MVP Policy (Simple & Strict):**
```python
def is_frozen(tour_instance: TourInstance, freeze_minutes: int = 720) -> bool:
    """Tour instance is FROZEN if start time is within freeze window."""
    # Compute deterministic start_datetime from week_anchor_date + day + start_ts + crosses_midnight
    forecast_version = get_forecast_version(tour_instance.forecast_version_id)
    start_datetime = compute_tour_start_datetime(
        forecast_version.week_anchor_date,
        tour_instance.day,
        tour_instance.start_ts,
        tour_instance.crosses_midnight
    )
    return datetime.now() >= start_datetime - timedelta(minutes=freeze_minutes)
```

**Default Freeze Window:** 12 hours (720 minutes) before tour start

**Critical Dependency:** `week_anchor_date` (stored in `forecast_versions`) enables deterministic datetime computation from (day, start_ts, crosses_midnight)

**Frozen Tour Behavior:**
1. **Diff Engine**: Still shows FROZEN tours in change reports
2. **Solver**: Cannot reassign FROZEN tours unless `override=True`
3. **Audit Log**: All overrides logged with user + reason

**Plan Version Immutability:**
```
❌ FORBIDDEN: Edit plan_version in-place
✅ REQUIRED:  Create new plan_version + mark old as SUPERSEDED
✅ REQUIRED:  Override flag if modifying FROZEN tours
```

**Philosophy:**
> *"Operational stability beats daily optimization. Better a suboptimal plan that doesn't escalate than 'always optimal' with daily chaos."*

**Trade-off:** Accept slight sub-optimality near freeze deadline in exchange for operational sanity.

### 7. Solver: Determinism + Headcount Pressure + PT Minimization

**Current V2 Approach:** Partition (seed sweep) → Min-Cost Max-Flow

**V3 Enhancement:** Formalize two-stage architecture with lexicographic objectives

#### **Stage A: Block Generation (Daily Partitioning)**

**Input:** Tours per day from `tours_normalized`

**Process:**
1. Generate all legal daily blocks (1er/2er/3er) based on WorkHours
2. Apply cost function (not heuristic intuition):
   ```python
   block_cost = {
       "3er": 100,    # Lowest cost (preferred)
       "2er": 200,
       "split_2er": 300,
       "1er": 400     # Highest cost (avoid)
   }
   ```
3. Select optimal block mix per day

**Output:** Set of legal blocks per day

**Constraints:**
- Each tour covered exactly once
- Block span ≤ 14h (regular) or 16h (split)
- Split blocks have exactly 360min break

#### **Stage B: Weekly Assignment (Path Cover)**

**Input:** Daily blocks + compatibility edges

**Compatibility Edge:** Block A (day d) → Block B (day d+1) if:
- Rest gap ≥ 11h between A.end and B.start
- No overlap
- Fatigue rule: 3er → 3er forbidden

**Objective (Lexicographic):**
```python
# Priority 1: Minimize driver headcount
cost = 1_000_000_000 * num_drivers

# Priority 2: Minimize part-time drivers (WorkHours < 40)
cost += 1_000_000 * num_pt_drivers

# Priority 3: Minimize splits/singletons
cost += 1_000 * num_splits
cost += 100 * num_singletons
```

**Implementation Options:**
1. **Min-Cost Max-Flow** with large weight differences (current V2)
2. **Small MIP** on block-level graph (V3 alternative)

**Determinism Requirements:**
```python
# CRITICAL for reproducibility
random.seed(FIXED_SEED)
blocks.sort(key=lambda b: (b.day, b.start, b.id))  # Stable ordering
num_workers = 1  # No parallelism
```

**V2 Reality Check (Seed Sweep Heuristic):**
- Current best: Seed 94 → 145 drivers, 0 PT
- Seed sweep is heuristic → acceptable IF:
  1. **Deterministic**: Fixed seed → reproducible output
  2. **Audited**: Store seed_candidates, selection_reason, peak_blocks_by_seed in audit_log JSON
  3. **Documented**: Migration path from "seed sweep" to "deterministic selection rule" (e.g., min peak blocks, tie-breakers)
- V3 formalizes what V2 discovered empirically
- **Future**: Replace seed sweep with fixed seed selection rule (e.g., "seed with min peak blocks, tie-break by min driver ID lexicographic")

### 8. Audits & Release Gates: Automated PASS/FAIL Only

**Mandatory Checks (Blocking, stored in `audit_log`):**

| Check Name | Criteria | FAIL Condition |
|------------|----------|----------------|
| **COVERAGE** | Every tour assigned exactly once | Any tour unassigned or multi-assigned |
| **OVERLAP** | No driver works overlapping tours | Any driver with overlapping blocks |
| **REST** | ≥11h rest between consecutive blocks | Any rest gap < 11h |
| **SPAN_REGULAR** | ≤14h span for regular blocks | Any regular block > 14h |
| **SPAN_SPLIT** | ≤16h span + 360min break for splits | Any split violating constraints |
| **REPRODUCIBILITY** | Same inputs → same outputs | `output_hash` mismatch on re-run |

**Reproducibility Formula:**
```python
input_signature = (input_hash, seed, solver_config_hash)
output_hash = sha256(assignments + kpis + metadata)

# Test: Re-run solver with same inputs
assert compute_output_hash() == stored_output_hash
```

**Soft KPIs (Non-blocking, visible in dashboard):**

| KPI | Calculation | Target |
|-----|-------------|--------|
| **FTE Avg WorkHours** | `sum(weekly_hours) / num_drivers` | ≥ 40h |
| **Part-Time Ratio** | `count(drivers with <40h) / total` | 0% |
| **Block Mix** | Distribution of 1er/2er/3er | Maximize 3er |
| **Peak Fleet** | Max concurrent active tours | Minimize |
| **Split Ratio** | `count(split_blocks) / total_blocks` | Minimize |

**Release Gate Logic:**
```python
def can_release(plan_version_id: int) -> bool:
    audits = get_audits(plan_version_id)
    mandatory_checks = [
        "COVERAGE", "OVERLAP", "REST",
        "SPAN_REGULAR", "SPAN_SPLIT", "REPRODUCIBILITY"
    ]
    return all(
        audit.status == "PASS"
        for audit in audits
        if audit.check_name in mandatory_checks
    )
```

### 9. ~~Streamlit Cockpit: Dispatch-Focused UI (MVP)~~ **DEPRECATED: Removed in V4.5**

> **Note**: The Streamlit UI was replaced by the Next.js SaaS Admin frontend (`frontend_v5/`).
> Runtime is now FastAPI kernel (`backend_py/api/main.py`) + domain packs only.

**Design Principle:** Show only what dispatchers need to make decisions.

#### **Tab 1: Ingest & Parser**
```
┌─────────────────────────────────────────────────────────┐
│ 📥 Input Source: [Slack] [CSV] [Manual]                │
│                                                         │
│ Line │ Status │ Canonical Text         │ Issues        │
│──────┼────────┼────────────────────────┼──────────────│
│  1   │ ✅ PASS│ Mo 06:00-14:00 (3)     │               │
│  2   │ ⚠️ WARN│ Di 06:00-14:00 (2)     │ Count mismatch│
│  3   │ ❌ FAIL│ Fr early shift         │ Ambiguous time│
│                                                         │
│ Global Status: FAIL (1 error, 1 warning)                │
│ [Fix Errors] [Proceed Anyway (Admin Only)]              │
└─────────────────────────────────────────────────────────┘
```

#### **Tab 2: Diff View**
```
┌─────────────────────────────────────────────────────────┐
│ 📊 Changes: forecast_v47 → forecast_v48                 │
│                                                         │
│ Filter: [All] [Added] [Removed] [Changed]              │
│                                                         │
│ Type    │ Day │ Time          │ Change                 │
│─────────┼─────┼───────────────┼────────────────────────│
│ ➕ ADDED│ Mo  │ 06:00-14:00   │ +3 drivers Depot Nord  │
│ ➖ REM  │ Di  │ 15:00-19:00   │ Tour cancelled         │
│ 🔄 CHG │ Mi  │ 07:00-15:00   │ 2 → 4 drivers          │
│                                                         │
│ Summary: 5 added, 2 removed, 3 changed                  │
└─────────────────────────────────────────────────────────┘
```

#### **Tab 3: Plan Preview**
```
┌─────────────────────────────────────────────────────────┐
│ 🗓️ Roster Matrix (plan_version_48 DRAFT)                │
│                                                         │
│ [Reuse existing final_schedule_matrix.html]            │
│                                                         │
│ 📈 KPIs:                                                │
│ • Drivers: 145 FTE (0 PT)                               │
│ • Avg Hours: 41.2h/week                                 │
│ • Block Mix: 65% 3er, 25% 2er, 10% 1er                  │
│                                                         │
│ ✅ Audit Status: ALL CHECKS PASSED                      │
│ • Coverage: ✅ 100%                                     │
│ • Rest: ✅ 0 violations                                 │
│ • Overlap: ✅ 0 violations                              │
│ • Reproducibility: ✅ hash match                        │
└─────────────────────────────────────────────────────────┘
```

#### **Tab 4: Release**
```
┌─────────────────────────────────────────────────────────┐
│ 🚀 Release Control                                      │
│                                                         │
│ Plan Version: 48 (DRAFT)                                │
│ Created: 2026-01-04 14:23:15                            │
│ Seed: 94                                                │
│                                                         │
│ Release Checklist:                                      │
│ ✅ All mandatory audits passed                          │
│ ✅ No FROZEN tours modified without override            │
│ ⚠️ 3 tours start within 12h (frozen soon)               │
│                                                         │
│ [🔒 LOCK & RELEASE] ← Only active if gates PASS         │
│                                                         │
│ After release:                                          │
│ • Plan status → LOCKED                                  │
│ • Exports generated (CSV, JSON)                         │
│ • No further modifications allowed                      │
└─────────────────────────────────────────────────────────┘
```

### 10. Definition of Done (Per Milestone)

**Clear exit criteria to prevent scope creep:**

#### **M1: Parser + Validation Gate**
✅ **DONE when:**
- [ ] 20+ parser test cases (covering PASS/WARN/FAIL scenarios)
- [ ] `input_hash` stable (whitespace/format irrelevant after canonicalization)
- [ ] FAIL status blocks solver execution
- [ ] Parser config versioned (`parser_config_hash`)

**Deliverable:** Parser module + test suite

---

#### **M2: Postgres Core Schema**
✅ **DONE when:**
- [ ] `docker-compose up` launches DB successfully
- [ ] Migrations create all MVP tables (including `tour_instances`, `week_anchor_date` in `forecast_versions`)
- [ ] Roundtrip test: CSV → `forecast_version` → `tours_raw` → `tours_normalized` → `tour_instances` (expansion) → export CSV
- [ ] Foreign key constraints enforced
- [ ] Migration file `001_tour_instances.sql` integrated into setup runbook

**Deliverable:** Database schema + docker setup + migration scripts + `db_instances.py` (instance expansion module)

---

#### **M3: Diff Engine**
✅ **DONE when:**
- [ ] Input: 2 forecast versions → Output: deterministic `diff.json`
- [ ] Snapshot tests pass (fixed inputs → fixed diff output)
- [ ] Handles ADDED/REMOVED/CHANGED correctly
- [ ] Tour fingerprint matching works across versions

**Deliverable:** Diff module + snapshot test suite

---

#### **M4: Solver Integration (DRAFT Plans)**
✅ **DONE when:**
- [ ] `plan_version` created with status=DRAFT
- [ ] `audit_log` populated with all mandatory checks
- [ ] Reproducibility test passes (same inputs → same `output_hash`)
- [ ] V2 solver wrapped with versioning layer

**Deliverable:** Solver wrapper + audit framework

---

#### **M5: Release Mechanism**
✅ **DONE when:**
- [ ] LOCKED plans immutable (no in-place edits)
- [ ] Export files include `plan_version_id` in metadata
- [ ] Manual release button functional (via REST API)
- [ ] Superseded plans marked correctly

**Deliverable:** Release workflow + export module

---

## 🚀 Next Steps (Priority Ordered)

### Immediate Actions (Verification & Validation)

#### 1. ✅ **Run Updated Golden Run** (IMMEDIATE)
**Status**: Ready to execute
**Command**: `python backend_py/generate_golden_run.py`

**Expected Results**:
- New `input_hash` (canonical, sorted)
- New `output_hash` (comprehensive with timestamps + block_type)
- Cross-midnight tour count displayed
- Golden run artifacts in `golden_run/`:
  - `matrix.csv` (145 drivers)
  - `rosters.csv` (per-driver schedules)
  - `kpis.json` (KPI summary)
  - `metadata.json` (all hashes)

**Success Criteria**:
- ✅ Generates without errors
- ✅ New hashes different from old (due to canonical + comprehensive changes)
- ✅ KPIs match: 145 FTE, 0 PT, 100% coverage

---

#### 2. ✅ **Run Updated Audit Proofs** (IMMEDIATE)
**Status**: Ready to execute
**Command**: `python backend_py/test_audit_proofs.py`

**Expected Results**:
- All proofs (#4-9) PASS with datetime-based validation
- Proof #5: Overlap/rest checks with week_anchor_date
- Proof #6: Exact 360min split break validation
- Proof #9: Freeze window classification

**Success Criteria**:
- ✅ `Overall: ALL PROOFS PASSED`
- ✅ No overlap/rest/span violations
- ✅ Freeze logic deterministic (all tours classified)

---

### Phase 1: Production Integration (HIGH PRIORITY)

#### 3. **Database Integration** (Week 1)
**Goal**: Connect V3 modules to PostgreSQL

**Tasks**:
1. Start PostgreSQL: `docker compose up -d postgres`
2. Verify connection: `python backend_py/test_db_connection.py`
3. Run P0 migration: `python backend_py/apply_p0_migration.py`
4. Test P0 migration: `python backend_py/test_p0_migration.py`
5. Integrate golden run with database:
   - Parse forecast → save to `forecast_versions`
   - Expand instances → save to `tour_instances`
   - Run solver → save to `plan_versions` + `assignments`
   - Run audits → save to `audit_log`

**Deliverables**:
- [ ] Database initialized with migration
- [ ] Golden run saved to database (plan_version_id=1)
- [ ] Audit results in `audit_log` table
- [ ] Reproducibility test passes (re-run → same output_hash)

**Success Criteria**:
- ✅ All data persisted correctly
- ✅ Foreign keys enforced
- ✅ LOCKED triggers prevent modifications

---

#### 4. **End-to-End Workflow Test** (Week 1-2)
**Goal**: Full pipeline test with real data

**Workflow**:
```bash
# 1. Parse forecast
python -c "
from backend_py.v3.parser import parse_forecast_text
result = parse_forecast_text(raw_text='...', source='manual', save_to_db=True)
print(f'Forecast ID: {result[\"forecast_version_id\"]}')
"

# 2. Expand instances
python -c "
from backend_py.v3.db_instances import expand_tour_templates
expand_tour_templates(forecast_version_id=1)
"

# 3. Solve and audit
python -c "
from backend_py.v3.solver_wrapper import solve_and_audit
result = solve_and_audit(forecast_version_id=1, seed=94)
print(f'Plan ID: {result[\"plan_version_id\"]}')
print(f'Audit: {result[\"audit_results\"][\"checks_passed\"]}/{result[\"audit_results\"][\"checks_run\"]}')
"

# 4. Lock plan
python -c "
from backend_py.v3.db import lock_plan_version
lock_plan_version(plan_version_id=1, locked_by='admin@lts.de')
"
```

**Deliverables**:
- [ ] Complete workflow script
- [ ] Documentation: `V3_E2E_WORKFLOW.md`
- [ ] Verified LOCKED immutability

---

### Phase 2: Operational UI ✅ COMPLETE

#### 5. ~~**Streamlit Dispatcher Cockpit**~~ ✅ DONE → **DEPRECATED in V4.5**

> **DEPRECATED**: Streamlit UI removed in V4.5. UI now lives in `frontend_v5/` (Next.js SaaS Admin).

**Goal**: 4-tab UI for dispatchers

~~**Files**: [streamlit_app.py](streamlit_app.py) (~400 lines)~~

**Tab Design**:
1. **Tab 1: Parser Status** ✅
   - Input: Paste Slack text or upload CSV
   - Display: Line-by-line PASS/WARN/FAIL status
   - Gate: Block solve if any FAIL

2. **Tab 2: Diff View** ✅
   - Compare forecast versions
   - Show ADDED/REMOVED/CHANGED tours
   - Color-coded diff table

3. **Tab 3: Plan Preview** ✅
   - Display roster matrix
   - Display KPIs (drivers, PT%, block mix)
   - Show audit results (green/red badges)

4. **Tab 4: Release Control** ✅
   - Show DRAFT plan details
   - Release checklist (audits, freeze status)
   - **[🔒 LOCK & RELEASE]** button (only active if gates PASS)
   - Export release package (CSV/JSON)

**Deliverables** (historical - now via REST API):
- ~~[x] Working Streamlit app~~ **DEPRECATED**
- [x] Connected to PostgreSQL (via FastAPI)
- [x] Manual release workflow functional (via REST API)
- [x] Export integration (via REST API)

~~**Run Command**: `streamlit run backend_py/streamlit_app.py`~~ **DEPRECATED**

---

### Phase 3: Freeze Window Enforcement ✅ COMPLETE

#### 6. **Freeze Window in Solver** ✅ DONE
**Goal**: Enforce 12h freeze rule in solver

**Files**: [v3/freeze_windows.py](v3/freeze_windows.py) (~350 lines)

**Implemented Functions**:
- `is_frozen(tour_instance_id, now)` - Check single instance freeze status
- `classify_instances(forecast_version_id, now)` - Classify all as FROZEN/MODIFIABLE
- `get_frozen_instances(forecast_version_id, now)` - Get frozen tour instances
- `get_previous_assignments(frozen_ids, forecast_version_id)` - Get previous assignments for frozen tours
- `log_freeze_override(plan_version_id, user, reason, affected_ids)` - Log override to audit_log
- `solve_with_freeze(forecast_version_id, seed, override, override_user, override_reason)` - Solve respecting freeze

**Deliverables**:
- [x] `freeze_windows.py` module
- [x] Integration with solver_wrapper (via `solve_with_freeze`)
- [x] Override logging to audit_log
- [x] CLI entry point for freeze operations

**CLI Commands**:
```bash
python -m v3.freeze_windows classify <forecast_version_id>   # Show frozen vs modifiable
python -m v3.freeze_windows solve <fv_id> [seed]             # Solve respecting freeze
python -m v3.freeze_windows override <fv_id> [seed]          # Solve with override
```

---

### Phase 4: Integration Testing ✅ COMPLETE

#### 7. **Snapshot Tests** ✅ DONE
**Goal**: Regression prevention

**Test Files**:
- [x] [test_diff_snapshots.py](test_diff_snapshots.py) - Fixed inputs → fixed diff outputs (8/8 passing)
- [x] [test_reproducibility.py](test_reproducibility.py) - Same inputs → same output_hash
- [x] [test_audit_proofs.py](test_audit_proofs.py) - Proofs #4-9 with datetime-based validation
- [x] [test_p0_migration.py](test_p0_migration.py) - P0 migration tests (6/6 passing)
- [x] [test_v3_integration.py](test_v3_integration.py) - End-to-end workflow (5/5 passing)

**Snapshot Test Coverage**:
- `test_diff_no_changes` - Identical forecasts → 0 diffs
- `test_diff_added_tour` - New tour classified as ADDED
- `test_diff_removed_tour` - Missing tour classified as REMOVED
- `test_diff_changed_count` - Changed count classified as CHANGED
- `test_diff_changed_depot` - Depot change creates new fingerprint
- `test_diff_complex_scenario` - Multiple change types
- `test_diff_fingerprint_determinism` - Same data → same fingerprint
- `test_diff_empty_forecasts` - Empty forecasts handled correctly

**Deliverables**:
- [x] Snapshot test suite
- [ ] CI/CD integration (GitHub Actions) - Future enhancement

---

### Phase 5: Export Module ✅ COMPLETE

#### 8. **CSV/JSON Export** ✅ DONE
**Goal**: Export released plans for external systems

**Files**: [v3/export.py](v3/export.py) (~400 lines)

**Implemented Functions**:
- `export_matrix_csv(plan_version_id, output_dir)` - Driver x Day roster grid
- `export_rosters_csv(plan_version_id, output_dir)` - Per-driver detailed schedules
- `export_kpis_json(plan_version_id, output_dir)` - KPI summary (drivers, PT%, block mix)
- `export_metadata_json(plan_version_id, output_dir)` - All hashes and version info
- `export_audit_json(plan_version_id, output_dir)` - Audit results
- `export_release_package(plan_version_id, output_dir)` - Complete release bundle

**Export Package Structure**:
```
exports/release_pv{id}/
├── matrix_pv{id}.csv       # Driver x Day grid
├── rosters_pv{id}.csv      # Per-driver schedules
├── kpis_pv{id}.json        # KPI summary
├── metadata_pv{id}.json    # Hashes and version info
├── audit_pv{id}.json       # Audit results
└── manifest.json           # Package manifest
```

**CLI Command**:
```bash
python -m v3.export <plan_version_id> [output_dir]
```

---

### Phase 6: Future Enhancements (V4+)

**Not MVP, but important for full production:**

1. **Driver Master Data** (`drivers` table)
2. **Availability/Preferences** (`driver_states_weekly`)
3. **Messaging System** (SMS/WhatsApp integration)
4. **Mobile App** (driver confirmations)
5. **CI/CD Integration** (GitHub Actions)

---

## 📝 Current Status Summary

### V3.2 Complete ✅ (Jan 5, 2026)

#### Core Platform
- ✅ V2 Solver (142-145 drivers, 0 PT, seed 94)
- ✅ V3 Architecture (P0 + M1-M5)
- ✅ Proof Hardening (canonical hashing, datetime audits)
- ✅ V2 Integration (crosses_midnight support)
- ✅ Freeze Window Logic (Proof #9)
- ✅ Database Integration (PostgreSQL, all tests passing)
- ✅ E2E Workflow Testing (golden run, audits, P0 migration)

#### User Interface
- ~~✅ **Streamlit UI** (5-tab dispatcher cockpit: Forecast, Vergleich, Planung, Release, Simulation)~~ **DEPRECATED V4.5**
- ~~✅ **CLI** (6 commands: ingest, solve, lock, export, status, simulate)~~ **DEPRECATED V4.5**
- ✅ **Next.js SaaS Admin** (`frontend_v5/`) - Platform Admin, Roster Management, Driver Portal

#### Audit Framework
- ✅ **8 Audit Checks** (Coverage, Overlap, Rest, Span-Regular, Span-Split, Fatigue, Reproducibility, Sensitivity)
- ✅ **Snapshot Tests** ([test_diff_snapshots.py](test_diff_snapshots.py) - 8/8 passing)
- ✅ **CSV/JSON Export** ([export.py](v3/export.py) - matrix, rosters, KPIs, metadata, audit)

#### V3.2 Simulation Framework ✅ NEW
- ✅ **13 Simulation Scenarios** across 5 categories
- ✅ **Economic**: Cost Curve, Freeze Tradeoff, Headcount Budget
- ✅ **Compliance**: Max-Hours Policy, Driver-Friendly Policy
- ✅ **Operational**: Patch-Chaos, Sick-Call Drill, Tour-Cancel
- ✅ **Strategic**: Auto-Seed-Sweep (parallel), Multi-Scenario Comparison
- ✅ **Advanced V3.2**: Multi-Failure Cascade, Probabilistic Churn (Monte Carlo), Policy ROI Optimizer (Pareto)
- ✅ **Risk Scoring**: Unified LOW/MEDIUM/HIGH/CRITICAL classification
- ✅ **Test Suite**: [test_simulation.py](tests/test_simulation.py) - 25+ test cases

### Pending ⏳ (V4+)
- ⏳ Driver Master Data (`drivers` table)
- ⏳ Messaging System (SMS/WhatsApp integration)
- ⏳ Mobile App (driver confirmations)
- ⏳ CI/CD Integration (GitHub Actions)
- ⏳ Multi-Tenant SaaS Architecture
- ⏳ REST API (FastAPI endpoints)

### Blocked ⛔
- None

---

### 📋 Agent Handoff Context

**SOLVEREIGN V3.2 – COMPLETE IMPLEMENTATION BRIEF**

**System Overview:**
```
┌─────────────────────────────────────────────────────────────────────┐
│  Ingest (Slack/CSV) → Parse → Validate → Normalize → Version        │
│       ↓                                                              │
│  Diff → Solve (DRAFT) → Audit (8 Checks) → Release (LOCK) → Export  │
│       ↓                                                              │
│  Simulate (13 Scenarios) → Risk Score → Recommendations             │
└─────────────────────────────────────────────────────────────────────┘
```

**Non-Negotiables:**
- ❌ No LLM in core pipeline
- ✅ Postgres in Docker = Single Source of Truth
- ✅ Full version control (`forecast_version_id` + `plan_version_id`)
- ✅ Immutable audit trail (8 checks)
- ✅ Freeze windows prevent last-minute chaos
- ✅ Reproducibility: `(input_hash, seed, config_hash) → output_hash`
- ✅ What-If Simulations for decision support

**Business Constraints:**
- **Hard Gates:** Coverage 100%, Rest ≥11h, Overlap 0, Span limits, Sensitivity <10%
- **Soft Targets:** 0 PT drivers (<40h minimized), Headcount ≤145 (comparable demand)

**Technical Reality:**
- V2 solver (142-145 drivers, 0 PT, seed 94) is **production-ready**
- V3 adds **operational tooling** (versioning, diff, UI, freeze windows)
- V3.2 adds **simulation framework** (13 scenarios, Monte Carlo, Pareto optimization)
- 8 audit checks including Sensitivity (plan stability under perturbations)
- Auto-Seed-Sweep with parallel execution (4 workers)

**V3 Modules (Key Files):**
```
v3/
├── parser.py            (576 lines)  - Whitelist parser
├── diff_engine.py       (280 lines)  - Fingerprint-based diff
├── solver_wrapper.py    (330 lines)  - V2 integration
├── audit_fixed.py       (830 lines)  - 8 audit checks
├── simulation_engine.py (2500 lines) - 13 scenarios
├── seed_sweep.py        (520 lines)  - Auto-seed optimization
├── freeze_windows.py    (482 lines)  - 12h freeze enforcement
├── plan_churn.py        (212 lines)  - Stability metrics
├── near_violations.py   (302 lines)  - Yellow zone warnings
├── peak_fleet.py        (229 lines)  - Concurrent tours
└── proof_pack.py        (200 lines)  - Cryptographic proofs
```

**MVP Tables:**
`forecast_versions`, `tours_raw`, `tours_normalized`, `tour_instances`, `plan_versions`, `assignments`, `audit_log`, `freeze_windows`, `diff_results`, `schema_migrations`

**Critical Relationships:**
- `tours_normalized` (1) → `tour_instances` (N) via `count` expansion
- `tour_instances` (1) ⇔ `assignments` (1) via `tour_instance_id` (1:1 mapping)
- Audits run on `tour_instances`, NOT templates
- Diff runs on templates (`tour_fingerprint`), triggers instance regeneration on CHANGED

**Critical Rules:**
- ✅ Solve runs automatically on DRAFT
- ⛔ Release requires manual approval
- 📨 Messaging only from LOCKED plans (future)
- 🔬 Simulations are read-only (no DB writes)

**V3.2 Simulation Scenarios:**
| Category | Scenarios |
|----------|-----------|
| Economic | Cost Curve, Freeze Tradeoff, Headcount Budget |
| Compliance | Max-Hours Policy, Driver-Friendly Policy |
| Operational | Patch-Chaos, Sick-Call Drill, Tour-Cancel |
| Strategic | Auto-Seed-Sweep, Multi-Scenario Comparison |
| Advanced | Multi-Failure Cascade, Probabilistic Churn, Policy ROI Optimizer |

**Risk Score Calculation:**
```python
score = headcount_delta_score + churn_score + freeze_violation_score + audit_failure_score
if score >= 8: return CRITICAL
elif score >= 5: return HIGH
elif score >= 3: return MEDIUM
else: return LOW
```
