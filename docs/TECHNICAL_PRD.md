# SOLVEREIGN V3.3b
## Technical Product Requirements Document (PRD)

**Version**: 3.3b
**Status**: Production Ready
**Last Updated**: 2026-01-05
**Author**: Engineering Team
**Reviewers**: Security, DevOps, Operations

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Authentication & Authorization](#3-authentication--authorization)
4. [Database Schema](#4-database-schema)
5. [API Specification](#5-api-specification)
6. [Core Algorithms](#6-core-algorithms)
7. [Compliance Engine](#7-compliance-engine)
8. [Security Requirements](#8-security-requirements)
9. [Operational Requirements](#9-operational-requirements)
10. [Testing Requirements](#10-testing-requirements)
11. [Deployment](#11-deployment)
12. [Appendices](#appendices)

---

## 1. Overview

### 1.1 Product Description

SOLVEREIGN is an automated shift scheduling platform that optimizes driver assignments for weekly tour schedules while maintaining strict compliance with German labor laws (ArbZG).

### 1.2 Technical Goals

| Goal | Requirement | Current Status |
|------|-------------|----------------|
| Optimization | Minimize drivers while maximizing FTE | 142 drivers, 100% FTE |
| Compliance | Pass all 7 ArbZG audit checks | 7/7 PASS |
| Performance | Solve time < 60 seconds | ~30 seconds |
| Reliability | 99.9% uptime target | Pending (new system) |
| Security | Multi-tenant isolation, OIDC auth | Implemented |

### 1.3 System Boundaries

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SOLVEREIGN SYSTEM                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  Streamlit  │    │   FastAPI   │    │  PostgreSQL │                 │
│  │     UI      │───▶│     API     │───▶│     DB      │                 │
│  │  (Port 8501)│    │ (Port 8000) │    │ (Port 5432) │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         │                  │                  │                         │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Users     │    │ Entra ID    │    │   Backups   │                 │
│  │ (Browsers)  │    │   (OIDC)    │    │  (Storage)  │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

External Interfaces:
  • Microsoft Entra ID (authentication)
  • Slack (optional: forecast input)
  • WhatsApp/SMS (optional: driver notifications)
```

### 1.4 Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Frontend | Streamlit | 1.29+ |
| API | FastAPI | 0.104+ |
| Database | PostgreSQL | 16 |
| Solver | Google OR-Tools | 9.7+ |
| Auth | Microsoft Entra ID | OIDC v2.0 |
| Runtime | Python | 3.11+ |
| Container | Docker | 24+ |

---

## 2. System Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              COMPONENTS                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         PRESENTATION LAYER                        │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  Forecast   │  │  Planning   │  │  Release    │               │  │
│  │  │    Tab      │  │    Tab      │  │    Tab      │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                           API LAYER                               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  /forecasts │  │   /plans    │  │ /simulations│               │  │
│  │  │   Router    │  │   Router    │  │   Router    │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                    SECURITY MIDDLEWARE                       │ │  │
│  │  │  [Rate Limit] → [Auth] → [RLS Context] → [Audit Log]        │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         BUSINESS LAYER                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │   Parser    │  │   Solver    │  │   Audit     │               │  │
│  │  │  (v3/parser)│  │  (v3/solver)│  │  (v3/audit) │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │                                                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │    Diff     │  │  Simulation │  │   Repair    │               │  │
│  │  │   Engine    │  │   Engine    │  │   Engine    │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                          DATA LAYER                               │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                  PostgreSQL + RLS                            │ │  │
│  │  │  [tenants] [forecasts] [plans] [assignments] [audit_log]    │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          MAIN WORKFLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. INGEST           2. PARSE             3. EXPAND                     │
│  ┌─────────┐        ┌─────────┐          ┌─────────┐                   │
│  │  Slack/ │  ───▶  │ Parser  │  ───▶    │ Instance│                   │
│  │   CSV   │        │(validate)│          │Expansion│                   │
│  └─────────┘        └─────────┘          └─────────┘                   │
│                                                │                        │
│                                                ▼                        │
│  6. LOCK             5. AUDIT             4. SOLVE                      │
│  ┌─────────┐        ┌─────────┐          ┌─────────┐                   │
│  │ APPROVER│  ◀───  │ 7 Checks│  ◀───    │ OR-Tools│                   │
│  │ Sign-off│        │  Pass?  │          │ Min-Cost│                   │
│  └─────────┘        └─────────┘          └─────────┘                   │
│       │                                                                 │
│       ▼                                                                 │
│  7. EXPORT                                                              │
│  ┌─────────┐                                                           │
│  │  Proof  │  → Matrix CSV + Rosters + Proof Pack ZIP                  │
│  │  Pack   │                                                           │
│  └─────────┘                                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 State Machine

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      PLAN VERSION STATE MACHINE                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐    parse     ┌──────────┐    expand    ┌──────────┐      │
│  │ INGESTED │ ──────────▶  │  PARSED  │ ──────────▶  │ EXPANDED │      │
│  └──────────┘              └──────────┘              └──────────┘      │
│                                                            │            │
│                                                      solve │            │
│                                                            ▼            │
│  ┌──────────┐    lock      ┌──────────┐    audit    ┌──────────┐      │
│  │  LOCKED  │ ◀──────────  │  DRAFT   │ ◀──────────  │  SOLVED  │      │
│  └──────────┘  (APPROVER)  └──────────┘   (auto)    └──────────┘      │
│       │                                                                 │
│       │ (immutable)                                                     │
│       │                                                                 │
│       ▼                                                                 │
│  ┌──────────┐                                                          │
│  │SUPERSEDED│  ◀── (new version replaces old)                          │
│  └──────────┘                                                          │
│                                                                         │
│  INVARIANTS:                                                            │
│    • LOCKED plans are immutable (enforced by DB triggers)               │
│    • Only APPROVER role can transition DRAFT → LOCKED                   │
│    • M2M tokens cannot lock (human approval required)                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Authentication & Authorization

### 3.1 Identity Provider

| Attribute | Value |
|-----------|-------|
| Provider | Microsoft Entra ID |
| Protocol | OIDC v2.0 |
| Token Type | JWT (RS256) |
| Issuer | `https://login.microsoftonline.com/{tenant_id}/v2.0` |
| Audience | `api://solvereign-api` |

### 3.2 JWT Claims Used

```json
{
  "iss": "https://login.microsoftonline.com/{tid}/v2.0",
  "aud": "api://solvereign-api",
  "tid": "entra-tenant-uuid",         // ← Mapped to internal tenant_id
  "sub": "user-object-id",
  "oid": "user-object-id",
  "name": "User Display Name",
  "preferred_username": "user@domain.com",
  "roles": ["PLANNER", "APPROVER"],   // ← Mapped to internal roles
  "azp": "client-app-id",
  "azpacr": "1"                       // ← 0=public, 1=secret, 2=cert
}
```

### 3.3 Tenant Mapping

```sql
-- Lookup: Entra tid → Internal tenant_id
SELECT tenant_id FROM tenant_identities
WHERE issuer = {iss_claim}
  AND external_tid = {tid_claim}
  AND is_active = TRUE;

-- If no mapping found → 403 TENANT_NOT_MAPPED
```

### 3.4 Role Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ROLE HIERARCHY                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  TENANT_ADMIN                                                           │
│       │                                                                 │
│       ▼                                                                 │
│  APPROVER (plan_approver)                                               │
│       │                                                                 │
│       ▼                                                                 │
│  DISPATCHER (dispatcher)                                                │
│       │                                                                 │
│       ▼                                                                 │
│  VIEWER (viewer)                                                        │
│                                                                         │
│  PERMISSIONS BY ROLE:                                                   │
│  ┌──────────────┬────────┬────────┬────────┬────────┬────────┐         │
│  │ Action       │ Viewer │Dispatch│Approver│ Admin  │ M2M    │         │
│  ├──────────────┼────────┼────────┼────────┼────────┼────────┤         │
│  │ Read plans   │   ✓    │   ✓    │   ✓    │   ✓    │   ✓    │         │
│  │ Solve        │   ✗    │   ✓    │   ✓    │   ✓    │   ✓    │         │
│  │ Export       │   ✗    │   ✓    │   ✓    │   ✓    │   ✓    │         │
│  │ Repair       │   ✗    │   ✓    │   ✓    │   ✓    │   ✓    │         │
│  │ LOCK         │   ✗    │   ✗    │   ✓    │   ✓    │   ✗    │         │
│  │ Manage users │   ✗    │   ✗    │   ✗    │   ✓    │   ✗    │         │
│  └──────────────┴────────┴────────┴────────┴────────┴────────┘         │
│                                                                         │
│  CRITICAL: M2M tokens cannot LOCK (human approval required)             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.5 Entra Role Mapping

| Entra App Role | Internal Role | Notes |
|----------------|---------------|-------|
| `PLANNER` | `dispatcher` | Standard dispatcher access |
| `APPROVER` | `plan_approver` | Can lock plans |
| `ADMIN` | `tenant_admin` | Tenant management |
| `VIEWER` | `viewer` | Read-only access |

### 3.6 M2M Token Restrictions

```python
# App tokens (azpacr != "0") have restricted roles stripped
RESTRICTED_APP_ROLES = {"plan_approver", "tenant_admin"}

# Even if app registration has APPROVER role, it's removed at runtime
if is_app_token and role in RESTRICTED_APP_ROLES:
    role = None  # Stripped
```

---

## 4. Database Schema

### 4.1 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              ERD (CORE)                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐       ┌─────────────────────┐                         │
│  │   tenants   │───1:N─│  tenant_identities  │                         │
│  │─────────────│       │─────────────────────│                         │
│  │ id (PK)     │       │ id (PK)             │                         │
│  │ name        │       │ tenant_id (FK)      │                         │
│  │ is_active   │       │ issuer              │                         │
│  │ metadata    │       │ external_tid        │                         │
│  └─────────────┘       └─────────────────────┘                         │
│         │                                                               │
│         │ 1:N                                                           │
│         ▼                                                               │
│  ┌───────────────────┐         ┌─────────────────────┐                 │
│  │ forecast_versions │───1:N───│   tours_normalized  │                 │
│  │───────────────────│         │─────────────────────│                 │
│  │ id (PK)           │         │ id (PK)             │                 │
│  │ tenant_id (FK)    │         │ forecast_version_id │                 │
│  │ input_hash        │         │ day, start_ts, end_ts│                │
│  │ week_anchor_date  │         │ count, depot, skill │                 │
│  │ status            │         │ tour_fingerprint    │                 │
│  └───────────────────┘         └─────────────────────┘                 │
│         │                               │                               │
│         │ 1:N                           │ 1:N (expand)                  │
│         ▼                               ▼                               │
│  ┌───────────────────┐         ┌─────────────────────┐                 │
│  │   plan_versions   │         │   tour_instances    │                 │
│  │───────────────────│         │─────────────────────│                 │
│  │ id (PK)           │         │ id (PK)             │                 │
│  │ forecast_version_id│        │ tour_template_id    │                 │
│  │ seed              │         │ instance_no         │                 │
│  │ output_hash       │         │ crosses_midnight    │                 │
│  │ status            │         │ day, start_ts, end_ts│                │
│  │ locked_at         │         └─────────────────────┘                 │
│  │ locked_by         │                  │                               │
│  └───────────────────┘                  │                               │
│         │                               │                               │
│         │ 1:N                           │ 1:1                           │
│         ▼                               ▼                               │
│  ┌───────────────────┐         ┌─────────────────────┐                 │
│  │   assignments     │─────────│   (tour_instance)   │                 │
│  │───────────────────│         └─────────────────────┘                 │
│  │ id (PK)           │                                                 │
│  │ plan_version_id   │                                                 │
│  │ driver_id         │                                                 │
│  │ tour_instance_id  │◀── 1:1 mapping (critical!)                      │
│  │ day, block_id     │                                                 │
│  └───────────────────┘                                                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Row-Level Security (RLS)

```sql
-- All tenant-scoped tables have RLS enabled
ALTER TABLE forecast_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
-- ... etc

-- Policy: Users can only see their tenant's data
CREATE POLICY tenant_isolation ON forecast_versions
FOR ALL USING (
    tenant_id = current_setting('app.current_tenant_id')::INTEGER
);

-- Connection setup (MUST use tenant_connection pattern)
SELECT set_config('app.current_tenant_id', '42', false);
-- All subsequent queries filtered to tenant_id = 42
```

### 4.3 Immutability Triggers

```sql
-- Prevent modification of LOCKED plans
CREATE TRIGGER prevent_locked_plan_modification
BEFORE UPDATE ON plan_versions
FOR EACH ROW
WHEN (OLD.status = 'LOCKED')
EXECUTE FUNCTION raise_locked_error();

-- Prevent modification of LOCKED plan assignments
CREATE TRIGGER prevent_locked_assignments_modification
BEFORE UPDATE OR DELETE ON assignments
FOR EACH ROW
EXECUTE FUNCTION check_plan_not_locked();
```

### 4.4 Key Migrations

| Migration | Description |
|-----------|-------------|
| `006_multi_tenant.sql` | tenant_id on all tables |
| `007_idempotency_keys.sql` | Request deduplication |
| `008_tour_segments.sql` | TIMESTAMPTZ for anchor-aware scheduling |
| `009_plan_versions_extended.sql` | State machine + advisory locks |
| `010_security_layer.sql` | Audit tables + encryption prep |
| `011_driver_model.sql` | Driver master data + availability |
| `012_tenant_identities.sql` | Entra ID tenant mapping |

---

## 5. API Specification

### 5.1 Endpoints Overview

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | None | Health check |
| GET | `/health/ready` | None | Readiness probe |
| GET | `/health/live` | None | Liveness probe |
| GET | `/api/v1/tenants/me` | Bearer | Current tenant info |
| POST | `/api/v1/forecasts` | Bearer | Create forecast |
| GET | `/api/v1/forecasts` | Bearer | List forecasts |
| GET | `/api/v1/forecasts/{id}` | Bearer | Get forecast |
| POST | `/api/v1/plans/solve` | Bearer | Solve forecast |
| GET | `/api/v1/plans/{id}` | Bearer | Get plan |
| POST | `/api/v1/plans/{id}/lock` | Bearer+APPROVER | Lock plan |
| GET | `/api/v1/plans/{id}/export/matrix` | Bearer | Export matrix CSV |
| GET | `/api/v1/plans/{id}/export/proof` | Bearer | Export proof pack |
| POST | `/api/v1/simulations/run` | Bearer | Run simulation |

### 5.2 Request/Response Examples

#### POST /api/v1/forecasts

**Request:**
```http
POST /api/v1/forecasts HTTP/1.1
Authorization: Bearer {jwt}
X-Idempotency-Key: abc123
Content-Type: application/json

{
  "raw_text": "Mo 08:00-16:00 2 Fahrer\nDi 06:00-14:00 3 Fahrer",
  "source": "slack",
  "week_anchor_date": "2026-01-06"
}
```

**Response (201 Created):**
```json
{
  "id": 42,
  "status": "PARSED",
  "tours_count": 5,
  "input_hash": "d1fc3cc7b2d8...",
  "created_at": "2026-01-05T10:00:00Z"
}
```

#### POST /api/v1/plans/solve

**Request:**
```http
POST /api/v1/plans/solve HTTP/1.1
Authorization: Bearer {jwt}
Content-Type: application/json

{
  "forecast_version_id": 42,
  "seed": 94,
  "run_audit": true
}
```

**Response (201 Created):**
```json
{
  "id": 123,
  "forecast_version_id": 42,
  "status": "DRAFT",
  "seed": 94,
  "output_hash": "d329b1c40b8f...",
  "kpis": {
    "total_drivers": 142,
    "total_hours": 6840.5,
    "avg_hours": 48.2,
    "fte_count": 142,
    "pt_count": 0,
    "block_1er": 45,
    "block_2er_reg": 120,
    "block_2er_split": 35,
    "block_3er": 222
  },
  "audit_results": {
    "all_passed": true,
    "checks_passed": 7,
    "checks_run": 7
  }
}
```

#### POST /api/v1/plans/{id}/lock

**Request:**
```http
POST /api/v1/plans/123/lock HTTP/1.1
Authorization: Bearer {approver_jwt}
Content-Type: application/json

{
  "notes": "Approved for KW02"
}
```

**Response (200 OK):**
```json
{
  "id": 123,
  "status": "LOCKED",
  "locked_at": "2026-01-05T14:30:00Z",
  "locked_by": "approver@lts.de"
}
```

**Error Response (403 - PLANNER trying to lock):**
```json
{
  "error": "INSUFFICIENT_ROLE",
  "message": "Requires plan_approver or tenant_admin role",
  "required_roles": ["plan_approver", "tenant_admin"],
  "user_roles": ["dispatcher"]
}
```

### 5.3 Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `MISSING_TID` | 403 | JWT missing tid claim |
| `TENANT_NOT_MAPPED` | 403 | Entra tid not registered |
| `INSUFFICIENT_ROLE` | 403 | User lacks required role |
| `APP_TOKEN_NOT_ALLOWED` | 403 | M2M token tried restricted action |
| `PLAN_LOCKED` | 409 | Cannot modify locked plan |
| `PLAN_NOT_FOUND` | 404 | Plan ID not found |
| `AUDIT_FAILED` | 422 | Plan failed compliance checks |
| `SOLVE_IN_PROGRESS` | 409 | Another solve running (advisory lock) |

### 5.4 Idempotency

```http
X-Idempotency-Key: {unique-key}

# First request → processes and returns result
# Subsequent requests with same key → returns cached result
# TTL: 24 hours
```

---

## 6. Core Algorithms

### 6.1 Solver Algorithm (Block Heuristic)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SOLVER STAGES                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  STAGE 0: GREEDY PARTITIONING                                          │
│  ─────────────────────────────                                          │
│  Priority: 3er chains > 2er blocks > 1er singletons                    │
│                                                                         │
│  For each day:                                                          │
│    1. Find all compatible 3-tour chains (30-60min gaps)                │
│    2. Remaining tours → find compatible 2-tour blocks                  │
│    3. Remaining tours → mark as singletons                             │
│                                                                         │
│  STAGE 1: MIN-COST MAX-FLOW (OR-Tools)                                 │
│  ──────────────────────────────────────                                 │
│  Model:                                                                 │
│    • Source → Driver nodes → Block nodes → Sink                        │
│    • Capacity constraints: 1 block per driver per day                  │
│    • Weekly hour constraints: ≤55h per driver                          │
│                                                                         │
│  Cost function (lexicographic):                                         │
│    cost = 1_000_000_000 × num_drivers    # Primary                     │
│    cost += 1_000_000 × num_pt_drivers    # Secondary                   │
│    cost += 1_000 × num_splits            # Tertiary                    │
│    cost += 100 × num_singletons          # Quaternary                  │
│                                                                         │
│  STAGE 2: CONSOLIDATION                                                 │
│  ───────────────────────                                                │
│  Attempt to merge singletons into existing drivers                     │
│  Goal: Reduce total driver count                                        │
│                                                                         │
│  STAGE 3: PT ELIMINATION                                               │
│  ───────────────────────                                                │
│  Redistribute PT driver blocks to FTE drivers                          │
│  Goal: Maximize FTE rate (target: 100%)                                 │
│                                                                         │
│  OUTPUT: 142 drivers, 100% FTE, 0 PT, Max 54h                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Block Classification

| Block Type | Tours | Gap | Max Span | Split Break |
|------------|-------|-----|----------|-------------|
| 1er | 1 | N/A | 14h | N/A |
| 2er-reg | 2 | 30-60min | 14h | N/A |
| 2er-split | 2 | 240-360min | 16h | 4-6h |
| 3er-chain | 3 | 30-60min each | 16h | N/A |

### 6.3 Parser Algorithm

```python
def parse_tour_line(raw_text: str) -> ParseResult:
    """
    Whitelist-based German tour parsing.

    Patterns recognized:
    - "Mo 08:00-16:00"                    # Basic
    - "Mo 08:00-16:00 2 Fahrer"           # With count
    - "Mo 08:00-16:00 Depot Nord"         # With depot
    - "Mo 22:00-06:00"                    # Cross-midnight
    - "Mo 08:00-12:00 + 16:00-20:00"      # Split shift

    Day mapping: Mo=1, Di=2, Mi=3, Do=4, Fr=5, Sa=6, So=7
    """
    # Step 1: Extract day
    # Step 2: Extract time ranges (supports cross-midnight)
    # Step 3: Extract optional count (default: 1)
    # Step 4: Extract optional depot
    # Step 5: Validate and return
```

### 6.4 Fingerprint Computation

```python
def compute_tour_fingerprint(day, start_ts, end_ts, depot, skill):
    """
    SHA256 hash for tour identity.
    Used by diff engine for change detection.
    """
    canonical = f"{day}|{start_ts}|{end_ts}|{depot or ''}|{skill or ''}"
    return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## 7. Compliance Engine

### 7.1 Audit Checks

| # | Check | Rule | Implementation |
|---|-------|------|----------------|
| 1 | Coverage | Every tour_instance assigned exactly once | Count assignments = count instances |
| 2 | Overlap | No driver works concurrent tours | Check time intersections per driver |
| 3 | Rest | ≥11h between consecutive blocks | Compare block end to next block start |
| 4 | Span Regular | 1er/2er-reg ≤14h span | Max(end_ts) - Min(start_ts) ≤ 14h |
| 5 | Span Split | 2er-split/3er ≤16h + 240-360min break | Span check + break validation |
| 6 | Fatigue | No 3er→3er on consecutive days | Check block_type sequence per driver |
| 7 | Weekly Max | ≤55h per driver per week | Sum(work_hours) by driver |

### 7.2 Audit Result Structure

```json
{
  "all_passed": true,
  "checks_run": 7,
  "checks_passed": 7,
  "results": {
    "coverage": {
      "status": "PASS",
      "violation_count": 0,
      "details": {
        "expected_assignments": 1385,
        "actual_assignments": 1385
      }
    },
    "overlap": {
      "status": "PASS",
      "violation_count": 0,
      "details": {}
    },
    // ... other checks
  }
}
```

### 7.3 Near-Violations (Yellow Zone)

```python
# Warnings for borderline cases (not failures)
YELLOW_ZONE_THRESHOLDS = {
    "rest_hours": 11.5,      # Warning if < 11.5h (legal min: 11h)
    "weekly_hours": 52.0,    # Warning if > 52h (legal max: 55h)
    "span_regular": 13.5,    # Warning if > 13.5h (legal max: 14h)
}
```

---

## 8. Security Requirements

### 8.1 Authentication Requirements

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| OIDC JWT validation | ✅ | `entra_auth.py` |
| Issuer validation | ✅ | Match against configured issuer |
| Audience validation | ✅ | `api://solvereign-api` |
| Token expiry check | ✅ | JWT `exp` claim |
| Clock skew tolerance | ✅ | 60 seconds |

### 8.2 Authorization Requirements

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| Role-based access | ✅ | `rbac.py` |
| APPROVER-only lock | ✅ | `RequireApprover` dependency |
| M2M restrictions | ✅ | Restricted roles stripped |
| Tenant isolation | ✅ | RLS on all tables |

### 8.3 Data Protection Requirements

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| RLS isolation | ✅ | PostgreSQL policies |
| tenant_connection pattern | ✅ | `database.py` |
| Parallel leak testing | ✅ | `test_rls_parallel_leak.py` |
| Audit logging | ✅ | All mutations logged |
| Immutability | ✅ | DB triggers on LOCKED |

### 8.4 Security Headers

```python
# Required headers set by middleware
{
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'"
}
```

---

## 9. Operational Requirements

### 9.1 Monitoring

| Metric | Threshold | Alert |
|--------|-----------|-------|
| API latency P99 | < 5s | Warning at 3s |
| Error rate | < 1% | Critical at 5% |
| Solve time | < 60s | Warning at 45s |
| DB connections | < 80% pool | Warning at 60% |

### 9.2 Logging

```json
{
  "timestamp": "2026-01-05T10:00:00.000Z",
  "level": "INFO",
  "message": "plan_locked",
  "tenant_id": 42,
  "plan_id": 123,
  "user_id": "user-oid",
  "trace_id": "abc123",
  "duration_ms": 45
}
```

### 9.3 Backup & Recovery

| Item | Frequency | Retention |
|------|-----------|-----------|
| Full DB backup | Daily | 30 days |
| Transaction logs | Continuous | 7 days |
| Proof packs | Per plan | Permanent |

### 9.4 Health Checks

```
GET /health         → System status
GET /health/ready   → Ready for traffic (DB connected)
GET /health/live    → Process alive (Kubernetes liveness)
```

---

## 10. Testing Requirements

### 10.1 Test Categories

| Category | Coverage Target | Current |
|----------|-----------------|---------|
| Unit tests | 80% | Implemented |
| Integration tests | Critical paths | Implemented |
| Security tests | All auth scenarios | Implemented |
| Load tests | 50 concurrent | Implemented |

### 10.2 Critical Test Files

| File | Purpose |
|------|---------|
| `test_entra_tenant_mapping.py` | Entra tid → tenant_id mapping |
| `test_rbac_lock_approver.py` | APPROVER-only lock enforcement |
| `test_rls_parallel_leak.py` | Multi-tenant isolation under load |
| `activation_checks.py` | Pre-production validation |
| `gate2_db_schema.py` | Schema verification |
| `gate6_determinism.py` | Reproducibility testing |

### 10.3 Pre-Production Gates

```bash
# Run all activation checks
python backend_py/tests/activation_checks.py

# Run parallel leak test
python backend_py/tests/test_rls_parallel_leak.py --parallel=50 --rounds=10

# Verify determinism
python backend_py/tests/gate6_determinism.py
```

---

## 11. Deployment

### 11.1 Environment Variables

```bash
# Database
SOLVEREIGN_DATABASE_URL=postgresql://user:pass@host:5432/db

# OIDC
SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{tid}/v2.0
SOLVEREIGN_OIDC_AUDIENCE=api://solvereign-api
SOLVEREIGN_OIDC_CLOCK_SKEW_SECONDS=60

# Security
SOLVEREIGN_ENVIRONMENT=production
SOLVEREIGN_ALLOW_HEADER_TENANT_OVERRIDE=false  # MUST be false in prod

# Solver
SOLVEREIGN_SOLVER_TIMEOUT_SECONDS=120
SOLVEREIGN_DEFAULT_SEED=94
```

### 11.2 Docker Compose

```yaml
version: '3.8'
services:
  api:
    build: ./backend_py
    ports:
      - "8000:8000"
    environment:
      - SOLVEREIGN_DATABASE_URL=${DATABASE_URL}
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=solvereign
    healthcheck:
      test: ["CMD-SHELL", "pg_isready"]
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend_py/db/init.sql:/docker-entrypoint-initdb.d/01-init.sql

  streamlit:
    build: ./backend_py
    command: streamlit run streamlit_app.py
    ports:
      - "8501:8501"
```

### 11.3 Migration Sequence

```bash
# 1. Backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# 2. Apply migrations in order
for f in backend_py/db/migrations/*.sql; do
  psql $DATABASE_URL < $f
done

# 3. Register tenant identity
psql $DATABASE_URL < backend_py/db/migrations/012_tenant_identities.sql

# 4. Verify
python backend_py/tests/activation_checks.py
```

---

## Appendices

### A. Glossary

| Term | Definition |
|------|------------|
| Block | Set of tours assigned to one driver on one day |
| 1er | Single tour block |
| 2er-reg | 2 tours with 30-60min gap |
| 2er-split | 2 tours with 4-6h break |
| 3er-chain | 3 tours with 30-60min gaps |
| FTE | Full-time equivalent (≥40h/week) |
| PT | Part-time (<40h/week) |
| RLS | Row-Level Security |
| LOCKED | Immutable plan state |
| Fingerprint | SHA256 tour identity hash |

### B. File Index

```
backend_py/
├── api/                    # FastAPI application
│   ├── main.py             # App factory
│   ├── config.py           # Settings
│   ├── database.py         # Connection pool + RLS
│   ├── security/           # Auth, RBAC, encryption
│   └── routers/            # API endpoints
├── v3/                     # Core business logic
│   ├── parser.py           # Tour parsing
│   ├── solver_wrapper.py   # OR-Tools integration
│   ├── audit_fixed.py      # Compliance checks
│   ├── simulation_engine.py # What-If scenarios
│   └── proof_pack.py       # Export generation
├── db/
│   ├── init.sql            # Base schema
│   └── migrations/         # Schema changes
└── tests/                  # Test suite
```

### C. References

1. [ROADMAP.md](../backend_py/ROADMAP.md) - Architecture specification
2. [SECURITY_EVIDENCE_PACK.md](../SECURITY_EVIDENCE_PACK.md) - Security documentation
3. [PILOT_WEEK_RUNBOOK.md](./PILOT_WEEK_RUNBOOK.md) - Operational guide
4. [ENTRA_SETUP_LTS.md](./ENTRA_SETUP_LTS.md) - Entra ID setup

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-05 | Engineering | Initial PRD |

---

*SOLVEREIGN V3.3b Technical PRD*
*Confidential - LTS Transport & Logistik GmbH*
