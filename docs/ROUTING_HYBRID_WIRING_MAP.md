# Hybrid Routing System - Wiring Map

> **Purpose**: Document code integration points for Matrix-First + OSRM-Finalize architecture.
> **Created**: 2026-01-07

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HYBRID ROUTING ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SOLVE PHASE                              FINALIZE PHASE                    │
│  (Deterministic)                          (Validation)                      │
│                                                                             │
│  ┌─────────────────┐                      ┌─────────────────────────────┐  │
│  │ StaticMatrix    │                      │ OSRMFinalizeStage           │  │
│  │ Provider        │──────┐               │ (NEW)                       │  │
│  │ (version_id)    │      │               │                             │  │
│  └────────┬────────┘      │               │ 1. Query OSRM per route     │  │
│           │               │               │ 2. Compute drift metrics    │  │
│           ▼               │               │ 3. TW forward simulation    │  │
│  ┌─────────────────┐      │               │ 4. Apply DriftGate policy   │  │
│  │ SolverDataModel │      │               └────────────┬────────────────┘  │
│  │ _build_matrices │      │                            │                   │
│  └────────┬────────┘      │                            ▼                   │
│           │               │               ┌─────────────────────────────┐  │
│           ▼               │               │ Verdict: OK / WARN / BLOCK  │  │
│  ┌─────────────────┐      │               └────────────┬────────────────┘  │
│  │ Callbacks       │      │                            │                   │
│  │ time_callback   │      │                            ▼                   │
│  │ distance_cb     │      │               ┌─────────────────────────────┐  │
│  └────────┬────────┘      │               │ Evidence Artifacts          │  │
│           │               │               │ - drift_report.json         │  │
│           ▼               │               │ - fallback_report.json      │  │
│  ┌─────────────────┐      │               │ - routing manifest block    │  │
│  │ VRPTWSolver     │──────┼──────────────▶└─────────────────────────────┘  │
│  │ (OR-Tools)      │      │                                                │
│  └────────┬────────┘      │                                                │
│           │               │                                                │
│           ▼               │                                                │
│  ┌─────────────────┐      │                                                │
│  │ SolverResult    │◀─────┘                                                │
│  └─────────────────┘                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Wiring Points

### 1. Travel Time Provider Interface

**File**: `backend_py/packs/routing/services/travel_time/provider.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 19-34 | `TravelTimeResult` | Single point-to-point result |
| 36-55 | `MatrixResult` | NxN matrix result |
| 57-135 | `TravelTimeProvider` | Abstract interface |
| 137-153 | `TravelTimeError` | Error handling |
| 155-176 | `TravelTimeProviderFactory` | Dynamic provider creation |

**Extension Points**:
- Add `TTMeta` to `TravelTimeResult` (Phase 1)
- Add `matrix_version` property to `MatrixResult` (Phase 1)

---

### 2. Static Matrix Provider

**File**: `backend_py/packs/routing/services/travel_time/static_matrix.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 67-116 | `StaticMatrixConfig` | CSV path, fallback settings |
| 118-180 | `load_from_csv()` | Matrix loading |
| 232-249 | Coordinate matching | Key lookup with precision |
| 251-269 | `_haversine_fallback()` | Fallback on missing pairs |

**Extension Points**:
- Add `StaticMatrixVersion` dataclass (Phase 1)
- Add `matrix_version` property (Phase 1)
- Track fallback level in metadata (Phase 1)

---

### 3. OSRM Provider

**File**: `backend_py/packs/routing/services/travel_time/osrm_provider.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 49-73 | `OSRMConfig` | URL, timeouts, caching |
| 108-116 | HTTP client setup | Session, headers |
| 169-177 | Cache lookup | Redis before API |
| 243-345 | `get_matrix()` | OSRM table API |
| 397-406 | Circuit breaker | Failure handling |
| 421-437 | Haversine fallback | API failure recovery |

**Extension Points**:
- Add `OSRMStatus` dataclass (Phase 2)
- Add `get_osrm_status()` method (Phase 2)
- Add `finalize_mode` config flag (Phase 2)
- Add `get_consecutive_times()` for per-leg timing (Phase 2)

---

### 4. Solver Data Model

**File**: `backend_py/packs/routing/services/solver/data_model.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 62-75 | `SolverDataModel.__init__` | Provider injection |
| 124-146 | `_build_matrices()` | Matrix construction |
| 177-185 | `time_matrix` property | Seconds matrix access |
| 187-195 | `distance_matrix` property | Meters matrix access |

**Integration Point**:
- `travel_time_provider` is injected at construction
- `get_matrix(locations)` called during `build()`
- Matrices stored as `List[List[int]]` (deterministic)

---

### 5. Constraint Callbacks

**File**: `backend_py/packs/routing/services/solver/constraints.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 118-134 | `time_callback()` | Transit time lookup |
| 201-205 | `distance_callback()` | Distance lookup |

**Data Flow**:
```python
# time_callback uses matrix from data model
travel_seconds = self.data.time_matrix[from_node][to_node]
travel_minutes = travel_seconds // 60
```

---

### 6. VRPTW Solver

**File**: `backend_py/packs/routing/services/solver/vrptw_solver.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 120-128 | Data model creation | Provider injection |
| 211-224 | `_set_objective()` | Cost function setup |

**Integration Point**:
```python
self._data = SolverDataModel(
    stops=self.stops,
    vehicles=self.vehicles,
    depots=self.depots,
    travel_time_provider=self.travel_time_provider,  # <-- INJECTED
    reference_time=datetime.now()
).build()
```

---

### 7. Plan Service (Audit Gate)

**File**: `backend_py/packs/routing/services/plan_service.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 49-60 | `AuditGateError` | Exception for blocked ops |
| 112-178 | `AuditGate` | Audit check enforcement |
| 132-158 | `check_lock_allowed()` | PASS/WARN/FAIL logic |
| 204-280 | `lock_plan()` | Lock with audit gating |

**Extension Points**:
- Add `DriftGate` class (Phase 4)
- Add `lock_plan_with_drift_check()` method (Phase 4)
- Integrate `DriftGateError` exception (Phase 4)

---

### 8. Evidence Pack

**File**: `backend_py/packs/routing/services/evidence/evidence_pack.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 38-54 | `InputEvidence` | Input metadata |
| 57-95 | `RouteEvidence` | Route details |
| 113-131 | `KPIEvidence` | KPI summary |
| 134-158 | `AuditEvidence` | Audit results |
| 161-176 | `PlanEvidence` | Plan metadata |
| 179-213 | `EvidencePack` | Complete bundle |
| 591-641 | `write_zip()` | ZIP export |

**Extension Points**:
- Add `RoutingEvidence` dataclass (Phase 5)
- Add `routing` field to `EvidencePack` (Phase 5)
- Include drift/fallback report artifacts (Phase 5)

---

### 9. Artifact Store

**File**: `backend_py/packs/routing/services/evidence/artifact_store.py`

| Line | Component | Purpose |
|------|-----------|---------|
| 33-58 | `ArtifactMetadata` | Artifact metadata |
| 62-71 | `UploadResult` | Upload response |
| 74-82 | `DownloadResult` | Download response |
| 84-92 | `IntegrityCheckResult` | Hash verification |
| 98+ | `ArtifactStore(ABC)` | Abstract interface |

**Usage for Routing**:
- Upload `drift_report.json` after finalize
- Upload `fallback_report.json` after finalize
- Reference artifact IDs in `RoutingEvidence`

---

## New Components to Create

### Phase 1: TTMeta Module

**New File**: `backend_py/packs/routing/services/travel_time/tt_meta.py`

```python
@dataclass(frozen=True)
class TTMeta:
    provider: Literal["static_matrix", "osrm", "haversine"]
    version: str
    profile: Optional[str] = None
    timed_out: bool = False
    fallback_level: Optional[Literal["H3", "ZONE", "GEOHASH", "PLZ"]] = None

@dataclass
class StaticMatrixVersion:
    version_id: str
    content_hash: str
    loaded_at: datetime
    row_count: int
```

---

### Phase 3: Finalize Stage Module

**New Directory**: `backend_py/packs/routing/services/finalize/`

```
finalize/
├── __init__.py
├── osrm_finalize.py      # Main orchestrator
├── drift_detector.py     # Drift metrics
├── tw_validator.py       # TW forward simulation
├── drift_gate.py         # Gate 7 enforcement
└── fallback_tracker.py   # Fallback tracking
```

---

### Phase 6: JSON Schemas

**New Directory**: `backend_py/schemas/`

```
schemas/
├── drift_report.schema.json
└── fallback_report.schema.json
```

---

## Data Flow: Solve to Finalize

```
1. SOLVE REQUEST
   └── VRPTWSolver.__init__(travel_time_provider=StaticMatrixProvider)

2. BUILD MATRICES
   └── SolverDataModel._build_matrices()
       └── StaticMatrixProvider.get_matrix(locations)
           └── Returns deterministic int[][] matrices

3. SOLVE
   └── VRPTWSolver.solve()
       └── OR-Tools uses time_callback, distance_callback
       └── Returns SolverResult with routes

4. FINALIZE (NEW)
   └── OSRMFinalizeStage.finalize(solver_result, matrix_provider, osrm_provider)
       ├── Query OSRM for each route's consecutive legs
       ├── DriftDetector.compute_drift(matrix_times, osrm_times)
       ├── TWValidator.validate(routes, osrm_times, time_windows)
       ├── FallbackTracker.get_report()
       └── DriftGate.evaluate(drift_report, tw_result, timeout_rate)
           └── Returns verdict: OK | WARN | BLOCK

5. LOCK (with drift check)
   └── PlanService.lock_plan_with_drift_check()
       ├── AuditGate.check_lock_allowed()
       └── DriftGate.check_lock_allowed()
           └── BLOCK raises DriftGateError

6. EVIDENCE
   └── EvidencePackWriter.create_evidence_pack(routing_evidence=...)
       └── Include drift_report_artifact_id, fallback_report_artifact_id
```

---

## Environment Variables

```env
# Matrix Generation
SOLVEREIGN_MATRIX_DIR=data/matrices

# OSRM Finalize
SOLVEREIGN_OSRM_FINALIZE_URL=http://localhost:5000
SOLVEREIGN_OSRM_FINALIZE_TIMEOUT_MS=5000
SOLVEREIGN_OSRM_FINALIZE_CONNECT_TIMEOUT_MS=2000
SOLVEREIGN_OSRM_MAX_TOTAL_TIMEOUT_MS=60000

# Drift Gate Thresholds
SOLVEREIGN_DRIFT_OK_P95_MAX=1.15
SOLVEREIGN_DRIFT_WARN_P95_MAX=1.30
SOLVEREIGN_DRIFT_TW_VIOLATIONS_OK=0
SOLVEREIGN_DRIFT_TW_VIOLATIONS_WARN=3
SOLVEREIGN_DRIFT_TIMEOUT_RATE_OK=0.02
SOLVEREIGN_DRIFT_TIMEOUT_RATE_WARN=0.10
```

---

## Test Files

| Test File | Tests | Phase |
|-----------|-------|-------|
| `test_matrix_generator.py` | 15 | 0 |
| `test_static_matrix_version.py` | 10 | 1 |
| `test_osrm_finalize_mode.py` | 12 | 2 |
| `test_osrm_finalize.py` | 25 | 3 |
| `test_drift_detector.py` | 15 | 3 |
| `test_tw_validator.py` | 15 | 3 |
| `test_fallback_tracker.py` | 10 | 3 |
| `test_drift_gate.py` | 20 | 4 |

---

## References

- Plan file: `.claude/plans/soft-whistling-sunrise.md`
- CLAUDE.md: Project context and architecture
- Gate 2 (AuditGate): `plan_service.py:112-178` - Pattern to replicate for DriftGate
- Gate 5 (ArtifactStore): `artifact_store.py` - For storing drift/fallback reports
- Gate 6 (FreezeLock): `freeze_lock_enforcer.py` - Hard gate pattern example
