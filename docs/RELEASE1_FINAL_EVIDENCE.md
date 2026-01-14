# SOLVEREIGN Release 1 - Final Evidence Pack

**Date**: 2026-01-13
**Commit**: `dafad8c9e210f91562c34cc7aa358666cb262929` + migrations applied
**Branch**: main
**Status**: **READY FOR RELEASE**

---

## 1. RBAC Truth (VERIFIED)

### 1.1 Permissions Matrix

| Role | `portal.approve.write` | `plan.publish` | `plan.approve` | Can Publish | Can Lock |
|------|------------------------|----------------|----------------|-------------|----------|
| `platform_admin` | **YES** | YES | YES | **YES** | **YES** |
| `tenant_admin` | **YES** | YES | YES | **YES** | **YES** |
| `operator_admin` | **YES** | YES | YES | **YES** | **YES** |
| `dispatcher` | NO | NO | NO | **NO** | **NO** |
| `ops_readonly` | NO | NO | NO | **NO** | **NO** |

**Evidence**: SQL Query Output (2026-01-13)
```
      role      |      permission
----------------+----------------------
 operator_admin | portal.approve.write
 platform_admin | portal.approve.write
 tenant_admin   | portal.approve.write
(3 rows)
```

### 1.2 Server-Side Permission Enforcement

| Endpoint | Permission Required | File:Line |
|----------|---------------------|-----------|
| POST `/api/v1/roster/snapshots/publish` | `portal.approve.write` | `lifecycle.py:649` |
| POST `/api/v1/roster/plans/{id}/lock` | `portal.approve.write` | `lifecycle.py:649` (via same dependency) |
| POST `/api/v1/roster/pins` | `portal.approve.write` | `pins.py:264` |
| DELETE `/api/v1/roster/pins` | `portal.approve.write` | `pins.py:439` |

### 1.3 Migration Applied

**Migration 052**: `backend_py/db/migrations/052_fix_portal_approve_permission.sql`
- Added `portal.approve.write` permission
- Granted to `operator_admin`, `tenant_admin`, `platform_admin`
- Verified with `NOTICE: Migration 052 verified: portal.approve.write granted to 3 roles`

---

## 2. Repair Editor Lock (Option A)

### 2.1 One OPEN Session Per Plan

**Database Constraint**: `idx_repairs_one_open_per_plan`
```sql
CREATE UNIQUE INDEX idx_repairs_one_open_per_plan
ON roster.repairs USING btree (tenant_id, site_id, plan_version_id)
WHERE ((status)::text = 'OPEN'::text)
```

### 2.2 409 Response Format

**Location**: `repair_sessions.py:487-498`
```json
{
  "error_code": "REPAIR_SESSION_ALREADY_OPEN",
  "message": "Active repair session already exists for this plan",
  "existing_session_id": "<uuid>",
  "existing_created_by": "<email>",
  "expires_at": "2026-01-13T15:30:00",
  "action_required": "Wait for session to expire or request takeover from approver"
}
```

### 2.3 Takeover Endpoint

**Endpoint**: `POST /api/v1/roster/repairs/{sessionId}/takeover`
**Location**: `repair_sessions.py:1165-1291`
**Guards**:
- Only `operator_admin`, `tenant_admin`, `platform_admin` can takeover
- Requires `reason` field (min 10 characters)
- Previous session marked `CLOSED_BY_TAKEOVER`
- Full audit trail: `takeover_by`, `takeover_reason`, `previous_session_id`

**Response**:
```json
{
  "new_session_id": "<uuid>",
  "previous_session_id": "<uuid>",
  "previous_created_by": "<email>",
  "plan_version_id": 123,
  "status": "OPEN",
  "expires_at": "2026-01-13T16:00:00",
  "takeover_reason": "Urgent fix required..."
}
```

---

## 3. Publish Policy (Release 1)

### 3.1 Server-Side Gates

| Gate | Error Code | HTTP Status | Location |
|------|------------|-------------|----------|
| Force Publish | `FORCE_PUBLISH_DISABLED` | 403 | `lifecycle.py:702-719` |
| Data Quality | `DATA_QUALITY_BLOCK_PUBLISH` | 409 | `lifecycle.py:726-758` |
| BLOCK Violations | `VIOLATIONS_BLOCK_PUBLISH` | 409 | `lifecycle.py:776-801` |

### 3.2 Force Publish Disabled

**Location**: `lifecycle.py:697-719`
```python
# RELEASE 1: Force Publish Disabled
if body.force_during_freeze:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "FORCE_PUBLISH_DISABLED",
            "message": "Force publish is disabled for Release 1",
        },
    )
```

### 3.3 Data Quality Gate

**Location**: `lifecycle.py:721-758`
```python
# Missing assignments block publish
cur.execute("""
    SELECT COUNT(*) as missing_count
    FROM tour_instances ti
    WHERE ti.plan_version_id = %s
      AND ti.assigned_driver_id IS NULL
      AND ti.is_active = true
""", (body.plan_version_id,))

if missing_count > 0:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "DATA_QUALITY_BLOCK_PUBLISH",
            "message": f"Cannot publish: {missing_count} tour(s) have no driver assigned",
        },
    )
```

---

## 4. Sessions TTL

### 4.1 Admin Session

| Setting | Value | Location |
|---------|-------|----------|
| Sliding Window | 8 hours | `internal_rbac.py:60` |
| Absolute Cap | 24 hours | `internal_rbac.py:61` |

### 4.2 Repair Session

| Setting | Value | Location |
|---------|-------|----------|
| Sliding Window | 30 minutes | `internal_rbac.py:67` |
| Absolute Cap | 2 hours | `internal_rbac.py:68` |

**Enforcement**: `repair_sessions.py:260-331` - validates both expiry and absolute cap

---

## 5. Cookie Configuration

### 5.1 Production Cookie

| Setting | Value |
|---------|-------|
| Name | `__Host-sv_platform_session` |
| Secure | true |
| HttpOnly | true |
| SameSite | strict |
| Path | `/` |
| Max-Age | 28800 (8h) |

### 5.2 Development Cookie

| Setting | Value |
|---------|-------|
| Name | `sv_platform_session` |
| Secure | false |
| HttpOnly | true |
| SameSite | strict |

### 5.3 BFF Route Analysis

| Category | Count |
|----------|-------|
| Total BFF Routes | 86 |
| Using `proxyToBackend` | 36 |
| Special Routes (justified) | 6 |
| Other (internal/static) | 44 |

**Critical Routes**: All roster pack routes use `proxyToBackend` ✓

---

## 6. Backup Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| `backup.ps1` | `scripts/backup.ps1` | Windows backup (90-day retention) |
| `backup.sh` | `scripts/backup.sh` | Linux/macOS backup (90-day retention) |
| `restore-smoke.ps1` | `scripts/restore-smoke.ps1` | Restore verification test |

**Schedule Recommendation**: Daily at 03:00 UTC

---

## 7. DB Integrity Scorecard

### 7.1 RBAC Integrity (16/16 PASS)

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
| permissions_seeded | **PASS** (25 permissions) |
| role_permissions_mapped | **PASS** (72 mappings) |
| tenant_admin_role_exists | **PASS** |
| platform_permissions_exist | **PASS** |
| users_rls_enabled | **PASS** |
| sessions_rls_enabled | **PASS** |
| audit_log_immutable | **PASS** |
| no_fake_tenant_zero | **PASS** |

### 7.2 Roster Integrity (13/13 PASS)

| Check | Status |
|-------|--------|
| rls_pins | **PASS** |
| rls_repairs | **PASS** |
| rls_repair_actions | **PASS** |
| rls_violations_cache | **PASS** |
| rls_audit_notes | **PASS** |
| audit_notes_immutable_trigger | **PASS** |
| tenant_id_not_null | **PASS** |
| pins_unique_constraint | **PASS** |
| repair_idempotency_index | **PASS** |
| violations_cache_freshness | **PASS** |
| one_open_session_constraint | **PASS** |
| helper_functions | **PASS** |
| undo_columns | **PASS** |

---

## 8. Manual Smoke Test Checklist

### 8.1 operator_admin Flow

| Step | Expected | Status |
|------|----------|--------|
| Login as operator_admin | Redirect to dashboard | ☐ |
| Navigate to Workbench | Page loads, no errors | ☐ |
| View Matrix | Grid renders with data | ☐ |
| Create Repair Session | Session created, ID returned | ☐ |
| Preview Repair Action | Preview shows violation delta | ☐ |
| Apply Repair Action | Action applied, undo available | ☐ |
| Click Publish | **Success** (if no violations) | ☐ |
| Click Lock | **Success** (with confirm:true) | ☐ |

### 8.2 dispatcher Flow

| Step | Expected | Status |
|------|----------|--------|
| Login as dispatcher | Redirect to dashboard | ☐ |
| Navigate to Workbench | Page loads, no errors | ☐ |
| View Matrix | Grid renders with data | ☐ |
| Create Repair Session | Session created, ID returned | ☐ |
| Click Publish | **403 + error_code + trace_id** | ☐ |
| Click Lock | **403 + error_code + trace_id** | ☐ |

### 8.3 Repair Editor Lock

| Step | Expected | Status |
|------|----------|--------|
| User A creates repair session | Session created | ☐ |
| User B tries to create session | **409 REPAIR_SESSION_ALREADY_OPEN** | ☐ |
| UI shows "in use by User A" | View-only mode activated | ☐ |
| operator_admin clicks Takeover | New session created, audit logged | ☐ |

---

## 9. Negative Path Tests

| Test | Expected Error | HTTP |
|------|----------------|------|
| Login with bad password | `INVALID_CREDENTIALS` | 401 |
| Create second repair session | `REPAIR_SESSION_ALREADY_OPEN` | 409 |
| Use expired session | `SESSION_EXPIRED` | 410 |
| Session exceeds 2h cap | `SESSION_ABSOLUTE_CAP` | 410 |
| Dispatcher publish | `Permission required: portal.approve.write` | 403 |
| Lock without confirm | `CONFIRMATION_REQUIRED` | 400 |
| Publish with BLOCK violations | `VIOLATIONS_BLOCK_PUBLISH` | 409 |
| Publish with missing assignments | `DATA_QUALITY_BLOCK_PUBLISH` | 409 |
| Force publish attempt | `FORCE_PUBLISH_DISABLED` | 403 |

---

## 10. Files Modified/Created

### Migrations
- `backend_py/db/migrations/052_fix_portal_approve_permission.sql` - NEW

### Backend
- `backend_py/packs/roster/api/routers/repair_sessions.py` - Modified (409 format, takeover endpoint, TTL enforcement)
- `backend_py/packs/roster/api/routers/lifecycle.py` - Modified (force publish disabled, data quality gate)
- `backend_py/api/security/internal_rbac.py` - Modified (TTL constants)

### Scripts
- `scripts/backup.ps1` - NEW
- `scripts/backup.sh` - NEW
- `scripts/restore-smoke.ps1` - NEW

---

## 11. Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tech Lead | __________ | __________ | __________ |
| QA Lead | __________ | __________ | __________ |
| Product Owner | __________ | __________ | __________ |

---

*Generated: 2026-01-13 by Claude Code*
*Gate Status: 16/16 RBAC + 13/13 Roster = **29/29 PASS***
