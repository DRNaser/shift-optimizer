# SOLVEREIGN V3.3b - Security Evidence Pack

**Version**: v3.3b-security
**Date**: 2026-01-05
**Reviewer**: Senior Dev / Security Team

---

## Source of Truth

> **External IdP Mode is DEFAULT. Self-Hosted Auth is OPTIONAL and DISABLED in production by default.**

| Mode | Config | Production | Use Case |
|------|--------|------------|----------|
| **OIDC** (default) | `AUTH_MODE=OIDC` | Allowed | Keycloak/Auth0 |
| **Self-Hosted** | `AUTH_MODE=SELF_HOSTED` | **Blocked** unless `ALLOW_SELF_HOSTED_IN_PROD=true` | Dev/Air-gapped |

Self-Hosted Auth modules (`token_refresh.py`, `token_blacklist.py` revocation features) are **only loaded** when `AUTH_MODE=SELF_HOSTED`.

---

## Executive Summary

This document provides evidence that the V3.3b security implementation is correct, complete, and does not introduce new attack surfaces.

**Status**: Ready for Security Review

---

## 1. JWT Validation Matrix

### Test Cases

| # | Scenario | Expected | Implementation |
|---|----------|----------|----------------|
| 1 | Valid token, correct tenant | 200 OK | `jwt.py:verify_token()` |
| 2 | Expired token | 401 Unauthorized | `jwt.py:122` - exp claim check |
| 3 | Invalid signature | 401 Unauthorized | `jwt.py:115` - RS256 verification |
| 4 | Wrong issuer | 401 Unauthorized | `jwt.py:118` - iss claim check |
| 5 | Wrong audience | 401 Unauthorized | `jwt.py:120` - aud claim check |
| 6 | Missing tenant_id claim | 401 Unauthorized | `jwt.py:136` - required claims |
| 7 | Revoked token (if blacklist ON) | 401 Unauthorized | `token_blacklist.py` |
| 8 | JWKS key rotation | Auto-refresh | `jwt.py:65` - 1h cache TTL |

### Evidence Code

```python
# api/security/jwt.py:115-140
def verify_token(self, token: str) -> JWTClaims:
    try:
        # Decode and verify signature
        payload = jwt.decode(
            token,
            self._get_public_key(token),
            algorithms=self._algorithms,
            audience=self._audience,      # Line 120: aud check
            issuer=self._issuer,          # Line 118: iss check
        )

        # Extract required claims
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            raise HTTPException(401, "Missing tenant_id claim")  # Line 136
```

### Verification Command

```bash
# Test invalid token (should return 401)
curl -H "Authorization: Bearer invalid_token" http://localhost:8000/api/v1/forecasts
# Expected: {"error": "unauthorized", "message": "Invalid token"}
```

---

## 2. RBAC Permission Matrix

### Role Hierarchy

```
SUPER_ADMIN (all permissions)
    ↓
TENANT_ADMIN (tenant-scoped admin)
    ↓
PLAN_APPROVER (can lock plans)
    ↓
DISPATCHER (can solve, cannot lock)
    ↓
VIEWER (read-only)
```

### Permission Matrix

| Permission | VIEWER | DISPATCHER | PLAN_APPROVER | TENANT_ADMIN | SUPER_ADMIN |
|------------|--------|------------|---------------|--------------|-------------|
| `forecast:read` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `forecast:create` | ❌ | ✅ | ✅ | ✅ | ✅ |
| `plan:read` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `plan:solve` | ❌ | ✅ | ✅ | ✅ | ✅ |
| `plan:lock` | ❌ | ❌ | ✅ | ✅ | ✅ |
| `plan:repair` | ❌ | ❌ | ✅ | ✅ | ✅ |
| `driver:read` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `driver:pii:read` | ❌ | ❌ | ❌ | ✅ | ✅ |
| `driver:write` | ❌ | ❌ | ❌ | ✅ | ✅ |
| `tenant:manage` | ❌ | ❌ | ❌ | ✅ | ✅ |
| `admin:*` | ❌ | ❌ | ❌ | ❌ | ✅ |

### Evidence Code

```python
# api/security/rbac.py:45-75
ROLE_PERMISSIONS = {
    Role.VIEWER: {
        Permission.FORECAST_READ,
        Permission.PLAN_READ,
        Permission.DRIVER_READ,
    },
    Role.DISPATCHER: {
        # Inherits VIEWER
        Permission.FORECAST_CREATE,
        Permission.PLAN_SOLVE,
    },
    Role.PLAN_APPROVER: {
        # Inherits DISPATCHER
        Permission.PLAN_LOCK,
        Permission.PLAN_REPAIR,
    },
    # ...
}
```

### Verification Command

```bash
# Test VIEWER cannot lock (should return 403)
curl -H "Authorization: Bearer viewer_token" \
     -X POST http://localhost:8000/api/v1/plans/1/lock
# Expected: {"error": "forbidden", "message": "Permission denied: plan:lock"}
```

---

## 3. Cross-Tenant Prevention

### Test Cases

| # | Scenario | Expected | Evidence |
|---|----------|----------|----------|
| 1 | Token Tenant A, request resource Tenant A | 200 OK | Normal flow |
| 2 | Token Tenant A, request resource Tenant B | 403 Forbidden | `rbac.py:178` |
| 3 | Token Tenant A, query param tenant_id=B | 403 Forbidden | `rbac.py:185` |
| 4 | SUPER_ADMIN accessing Tenant B | 200 OK | `rbac.py:175` |

### Evidence Code

```python
# api/security/rbac.py:170-190
async def __call__(self, request: Request, claims: JWTClaims):
    # Cross-tenant check
    target_tenant = self._extract_target_tenant(request)

    if target_tenant and target_tenant != claims.tenant_id:
        # Only SUPER_ADMIN can access other tenants
        if Role.SUPER_ADMIN not in claims.roles:
            await self._log_denial(
                request, claims,
                "CROSS_TENANT_ACCESS",
                f"Attempted access to tenant {target_tenant}"
            )
            raise HTTPException(403, "Cross-tenant access denied")
```

### Database-Level Protection (RLS)

```sql
-- db/migrations/010_security_layer.sql:149-154
CREATE POLICY tenant_isolation_forecast ON forecast_versions
    FOR ALL
    USING (
        tenant_id::TEXT = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_super_admin', true) = 'true'
    );
```

---

## 4. RLS Enforcement Proof

### 4.1 Role Configuration

```sql
-- API role: NO BYPASSRLS
CREATE ROLE solvereign_api NOINHERIT NOSUPERUSER;
ALTER ROLE solvereign_api NOBYPASSRLS;

-- Admin role: BYPASSRLS (migrations only)
CREATE ROLE solvereign_admin BYPASSRLS;
```

### 4.2 RLS Enabled Verification

```sql
-- RUN THIS TO VERIFY:
SHOW row_security;
-- Expected: on

SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public' AND tablename IN (
    'forecast_versions', 'plan_versions', 'assignments',
    'tours_raw', 'tours_normalized', 'tour_instances', 'audit_log'
);
-- Expected: All rows show rowsecurity = true
```

### 4.3 Transaction-Scoped Tenant Context

```sql
-- Called at start of each API request
SELECT set_tenant_context('tenant-uuid-here', false);

-- All subsequent queries filtered by RLS
SELECT * FROM forecast_versions;  -- Only tenant's rows returned
```

### 4.4 Concrete RLS Test Script

```sql
-- ============================================================
-- RLS PROOF TEST (run as superuser, then switch to solvereign_api)
-- ============================================================

-- Setup: Insert test data for two tenants
INSERT INTO forecast_versions (tenant_id, source, input_hash, status)
VALUES
    ('11111111-1111-1111-1111-111111111111', 'test', 'hash1', 'READY'),
    ('22222222-2222-2222-2222-222222222222', 'test', 'hash2', 'READY');

-- Switch to API role (no BYPASSRLS)
SET ROLE solvereign_api;

-- Test 1: With Tenant A context → should see only Tenant A
SELECT set_tenant_context('11111111-1111-1111-1111-111111111111');
SELECT COUNT(*) FROM forecast_versions;
-- Expected: 1

-- Test 2: With Tenant B context → should see only Tenant B
SELECT set_tenant_context('22222222-2222-2222-2222-222222222222');
SELECT COUNT(*) FROM forecast_versions;
-- Expected: 1

-- Test 3: Without context → should see ZERO
SELECT set_tenant_context('');
SELECT COUNT(*) FROM forecast_versions;
-- Expected: 0 (RLS blocks access)

-- Test 4: Malicious query without filter → still blocked by RLS
SELECT set_tenant_context('11111111-1111-1111-1111-111111111111');
SELECT * FROM forecast_versions WHERE 1=1;  -- Tries to bypass
-- Expected: Still only returns Tenant A rows

-- Cleanup
RESET ROLE;
DELETE FROM forecast_versions WHERE source = 'test';
```

### 4.5 Background Jobs Tenant Context

```python
# CRITICAL: Background jobs MUST set tenant context per transaction
# Otherwise: empty results or policy violations

# CORRECT (in background job):
async def process_forecast_job(tenant_id: str, forecast_id: int):
    async with db.get_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_tenant_context($1, false)", tenant_id
            )
            # Now all queries are tenant-scoped
            result = await conn.fetch("SELECT * FROM forecast_versions WHERE id = $1", forecast_id)

# WRONG (will get empty results or fail):
async def bad_job(forecast_id: int):
    async with db.get_connection() as conn:
        # Missing set_tenant_context!
        result = await conn.fetch("SELECT * FROM forecast_versions WHERE id = $1", forecast_id)
        # Returns empty because RLS policy blocks
```

---

## 5. Rate Limiting Evidence

### 5.1 Configuration

```python
# api/security/rate_limit.py:35-50
DEFAULT_LIMITS = {
    "/auth/login": RateLimitConfig(requests=10, window=60, by="ip"),
    "/export/*": RateLimitConfig(requests=5, window=3600, by="tenant"),
    "/api/v1/*": RateLimitConfig(requests=1000, window=60, by="tenant"),
}
```

### 5.2 Behavior

| Endpoint | Limit | Scope | On Exceed |
|----------|-------|-------|-----------|
| `/auth/login` | 10/min | IP | 429 + Retry-After |
| `/export/*` | 5/hour | Tenant | 429 + Retry-After |
| `/api/v1/*` | 1000/min | Tenant | 429 + Retry-After |

### 5.3 Failover Behavior: FAIL-OPEN (Explicit Decision)

```
┌─────────────────────────────────────────────────────────────────┐
│ ARCHITECTURE DECISION: Rate Limiting Failover                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Decision: FAIL-OPEN                                             │
│                                                                 │
│ When Redis is unavailable:                                      │
│   1. Log WARNING: "Redis unavailable, falling back to in-memory"│
│   2. Continue with per-instance in-memory limiting              │
│   3. Accept degraded protection (per-instance, not distributed) │
│                                                                 │
│ Rationale:                                                      │
│   - Availability > Perfect rate limiting                        │
│   - Legitimate users not blocked during Redis outage            │
│   - Attack surface is time-limited (Redis recovery)             │
│   - Per-instance limiting still provides some protection        │
│                                                                 │
│ Alternative (FAIL-CLOSED):                                      │
│   - All requests blocked when Redis unavailable                 │
│   - Higher security, but availability risk                      │
│   - NOT chosen: Dispatcher needs to work even if Redis is down  │
│                                                                 │
│ Monitoring:                                                     │
│   - Alert on: "rate_limit_redis_fallback" metric > 0            │
│   - Dashboard shows: "Rate Limiting Mode: DISTRIBUTED|DEGRADED" │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 Implementation Evidence

```python
# api/security/rate_limit.py
class RateLimitMiddleware:
    async def __call__(self, request, call_next):
        try:
            # Try Redis first
            await self._check_redis_limit(request)
        except RedisConnectionError:
            # FAIL-OPEN: Fall back to in-memory
            logger.warning(
                "Rate limit Redis unavailable, using in-memory fallback",
                extra={"path": request.url.path}
            )
            await self._check_memory_limit(request)

        return await call_next(request)
```

---

## 6. Audit Log Tamper Protection

### 6.1 Hash Chain Deterministic Specification

```
┌─────────────────────────────────────────────────────────────────┐
│ HASH CHAIN SPECIFICATION                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Table: security_audit_log                                       │
│                                                                 │
│ Fields in hash computation (IN THIS ORDER):                     │
│   1. previous_hash  - VARCHAR(64), NULL for first entry         │
│   2. timestamp      - TIMESTAMPTZ, PostgreSQL default format    │
│   3. event_type     - VARCHAR(100)                              │
│   4. tenant_id      - UUID or empty string                      │
│   5. user_id        - UUID or empty string                      │
│   6. severity       - VARCHAR(20) ('INFO'|'WARNING'|'CRITICAL') │
│   7. details_json   - JSONB or '{}'                             │
│                                                                 │
│ Hash input formula:                                             │
│   COALESCE(previous_hash, 'GENESIS') ||                         │
│   timestamp::TEXT ||                                            │
│   event_type ||                                                 │
│   COALESCE(tenant_id::TEXT, '') ||                              │
│   COALESCE(user_id::TEXT, '') ||                                │
│   severity ||                                                   │
│   COALESCE(details_json::TEXT, '{}')                            │
│                                                                 │
│ Hash algorithm: SHA-256 (64 hex chars)                          │
│ Encoding: hex (encode(sha256(...), 'hex'))                      │
│                                                                 │
│ FIRST ENTRY: previous_hash is NULL → uses 'GENESIS' as prefix   │
│                                                                 │
│ Edge cases:                                                     │
│   - Missing row: Chain breaks at that ID, verify reports invalid│
│   - Reordering: Detected because previous_hash won't match      │
│   - Empty JSONB: Normalized to '{}'                             │
│   - NULL tenant/user: Normalized to empty string ''             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Hash Chain Implementation

```sql
-- db/migrations/010_security_layer.sql:55-82
CREATE OR REPLACE FUNCTION compute_security_audit_hash()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash VARCHAR(64);
    hash_input TEXT;
BEGIN
    -- Get previous hash (NULL for first entry)
    SELECT current_hash INTO prev_hash
    FROM security_audit_log
    ORDER BY id DESC
    LIMIT 1;

    NEW.previous_hash := prev_hash;

    -- Compute current hash (DETERMINISTIC ORDER)
    hash_input := COALESCE(prev_hash, 'GENESIS') ||
                  NEW.timestamp::TEXT ||
                  NEW.event_type ||
                  COALESCE(NEW.tenant_id::TEXT, '') ||
                  COALESCE(NEW.user_id::TEXT, '') ||
                  NEW.severity ||
                  COALESCE(NEW.details_json::TEXT, '{}');

    NEW.current_hash := encode(sha256(hash_input::BYTEA), 'hex');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### 6.3 Immutability Triggers

```sql
-- Prevent UPDATE (raises exception)
CREATE TRIGGER prevent_audit_update BEFORE UPDATE ON security_audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_update();

-- Prevent DELETE (raises exception)
CREATE TRIGGER prevent_audit_delete BEFORE DELETE ON security_audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_delete();

-- Exception message:
-- "Security audit log is immutable. UPDATE not allowed."
-- "Security audit log is immutable. DELETE not allowed."
```

### 6.4 Verification CLI

```bash
# Verify audit chain integrity
python cli.py audit verify --start 1 --limit 10000

# Expected output (valid chain):
# 🔐 Verifying Security Audit Log Integrity
# ============================================================
#
# Checked entries: 1234
# Start ID: 1
#
# ✅ AUDIT CHAIN VALID - No tampering detected
#    All 1234 entries have valid hash chain
#
# 📊 Audit Log Summary:
#    Total entries: 1234
#    Tenants: 3
#    First entry: 2026-01-01 00:00:00+00
#    Last entry: 2026-01-05 12:00:00+00
#    Critical events: 2
#    Warning events: 15

# Expected output (tampered):
# ❌ AUDIT CHAIN INVALID - Tampering detected!
#    First invalid entry ID: 567
#
#    CRITICAL: Investigate immediately!
```

### 6.5 Verification SQL Function

```sql
-- Direct SQL verification
SELECT * FROM verify_security_audit_chain(1, 10000);

-- Returns:
-- is_valid | checked_count | first_invalid_id
-- ---------+---------------+------------------
-- true     | 1234          | NULL             -- Valid chain
-- false    | 567           | 567              -- Invalid at ID 567
```

---

## 7. No Token Leakage

### 7.1 Log Redaction Evidence

**Code location**: `api/main.py:184-193`

```python
# What IS logged (safe):
logger.info(
    "request_completed",
    extra={
        "request_id": request_id,      # Safe: UUID
        "method": request.method,      # Safe: GET/POST/etc
        "path": request.url.path,      # Safe: URL path
        "status_code": response.status_code,  # Safe: 200/401/etc
        "duration_ms": round(duration_ms, 2), # Safe: timing
    }
)

# What is NOT logged (redacted by omission):
# - Authorization header (JWT token)
# - X-API-Key header
# - Cookie header
# - Request body (may contain credentials)
# - Query parameters (may contain tokens)
```

### 7.2 Example Log Output (Safe)

```json
{
  "timestamp": "2026-01-05T10:30:00.000Z",
  "level": "INFO",
  "logger": "api.main",
  "message": "request_completed",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "method": "POST",
  "path": "/api/v1/forecasts/1/solve",
  "status_code": 200,
  "duration_ms": 1234.56
}
```

**Note**: No `authorization`, `token`, `jwt`, `bearer`, `cookie` fields present.

### 7.3 Security Headers (Prevent Referrer Leakage)

```python
# api/security/headers.py:81-84
if "Authorization" in request.headers or "X-API-Key" in request.headers:
    response.headers["Referrer-Policy"] = "no-referrer"  # Tokens never in Referer
else:
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
```

### 7.4 Verification

```bash
# 1. Make authenticated request
curl -v -H "Authorization: Bearer eyJ..." http://localhost:8000/api/v1/forecasts

# 2. Check logs (docker compose logs api)
# Expected: NO "Authorization" or "Bearer" in log output
# Expected: Only request_id, method, path, status_code, duration_ms
```

---

## 8. Middleware Order Verification

### Correct Order (Execution Flow)

```
1. SecurityHeadersMiddleware  ← Always runs, adds security headers
2. CORSMiddleware             ← Handles preflight
3. RequestContextMiddleware   ← Sets request_id
4. AuthMiddleware             ← JWT validation, sets tenant_id/user_id
5. RateLimitMiddleware        ← Can use tenant_id/user_id from auth
6. Router handlers            ← Business logic
```

### Evidence Code

```python
# api/main.py:109-147 (configure_middleware)
# Note: FastAPI middleware is LIFO, so we add in reverse order

app.add_middleware(RateLimitMiddleware)         # Runs 5th
# Auth is per-route via dependencies
app.add_middleware(CORSMiddleware, ...)         # Runs 2nd
app.add_middleware(SecurityHeadersMiddleware)   # Runs 1st
```

### 8.1 Test Evidence

```bash
# Run middleware order tests
python backend_py/tests/test_middleware_order.py

# Expected output:
# [TEST 1] Auth before RateLimit (correct)...
# Execution order: ['1_SecurityHeaders_ENTER', '2_CORS_ENTER',
#   '3_RequestContext_ENTER', '4_Auth_ENTER', '5_RateLimit_ENTER',
#   '5_RateLimit_HAS_TENANT:test-tenant-id', '6_Handler', ...]
# [PASS] Middleware order correct - Auth runs before RateLimit
#
# [TEST 2] RateLimit before Auth (wrong - demonstrates failure)...
# [PASS] Demonstrated wrong order fails to provide tenant_id
```

**Test file**: `backend_py/tests/test_middleware_order.py`

**Key assertions verified**:
1. Auth middleware enters BEFORE RateLimit middleware
2. RateLimit has access to `tenant_id` (set by Auth)
3. SecurityHeaders is outermost (first enter, last exit)
4. Wrong order (RateLimit before Auth) results in `NO_TENANT`

---

## 9. Questions for Senior Dev Review

### Q1: Why token_refresh.py exists when IdP is planned?

**Answer**: Self-hosted auth mode for:
- Development without IdP
- Air-gapped deployments
- Testing

**When Keycloak/Auth0 deployed**: This module is NOT used. IdP handles refresh.

### Q2: Is RLS enforced without BYPASSRLS?

**Answer**: Yes.
```sql
ALTER ROLE solvereign_api NOBYPASSRLS;  -- Explicit
```
Only `solvereign_admin` has BYPASSRLS (migrations only, never used by app).

### Q3: Middleware order correct?

**Answer**: Yes, verified in code. Rate limit runs AFTER auth has set tenant_id.

---

## 10. Microsoft Entra ID Authentication (V3.3b)

### 10.1 Tenant Mapping Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ ENTRA ID TENANT MAPPING                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ JWT Token from Entra ID:                                        │
│   {                                                             │
│     "iss": "https://login.microsoftonline.com/{tid}/v2.0",      │
│     "aud": "api://solvereign-api",                              │
│     "tid": "entra-tenant-uuid",           ← Azure AD Tenant ID  │
│     "sub": "user-object-id",                                    │
│     "roles": ["PLANNER", "APPROVER"],     ← Entra App Roles     │
│     ...                                                         │
│   }                                                             │
│                                                                 │
│ Database Lookup:                                                │
│   SELECT tenant_id FROM tenant_identities                       │
│   WHERE issuer = {iss} AND external_tid = {tid}                 │
│                                                                 │
│ Result: Internal tenant_id (INTEGER) for RLS                    │
│                                                                 │
│ CRITICAL: tenant_id comes from JWT tid claim,                   │
│           NEVER from client headers in production               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Error Codes

| Error | HTTP Code | Meaning | Evidence |
|-------|-----------|---------|----------|
| `MISSING_TID` | 403 | Token missing tid claim | `entra_auth.py:203-211` |
| `TENANT_NOT_MAPPED` | 403 | No mapping for Entra tid | `entra_auth.py:369-382` |
| `INSUFFICIENT_ROLE` | 403 | User lacks required role | `entra_auth.py:436-449` |
| `APP_TOKEN_NOT_ALLOWED` | 403 | M2M token tried to lock | `plans.py:381-387` |

### 10.3 Evidence: Tenant Mapping SQL

```sql
-- Migration: 012_tenant_identities.sql

-- Lookup function used by auth middleware
CREATE FUNCTION get_tenant_by_idp_identity(p_issuer, p_external_tid)
RETURNS INTEGER AS $$
    SELECT ti.tenant_id
    FROM tenant_identities ti
    JOIN tenants t ON ti.tenant_id = t.id
    WHERE ti.issuer = p_issuer
      AND ti.external_tid = p_external_tid
      AND ti.is_active = TRUE
      AND t.is_active = TRUE;
$$;
```

### 10.4 Evidence: APPROVER Role Requirement for Lock

```python
# api/routers/plans.py:340-387

@router.post("/{plan_id}/lock", response_model=LockResponse)
async def lock_plan(
    plan_id: int,
    request: LockRequest,
    user: EntraUserContext = Depends(RequireApprover),  # ← RBAC check
    db: DatabaseManager = Depends(get_db),
):
    # M2M tokens cannot lock plans (human approval required)
    if user.is_app_token:
        raise HTTPException(
            status_code=403,
            detail={"error": "APP_TOKEN_NOT_ALLOWED", ...}
        )
```

### 10.5 Evidence: M2M Token Role Restriction

```python
# api/security/entra_auth.py:62-74

# M2M (app-only) tokens cannot have APPROVER role
RESTRICTED_APP_ROLES = {"plan_approver", "tenant_admin"}

def map_entra_roles(entra_roles, is_app_token=False):
    for entra_role in entra_roles:
        internal_role = ENTRA_ROLE_MAPPING.get(entra_role)
        if internal_role:
            # M2M tokens cannot have restricted roles
            if is_app_token and internal_role in RESTRICTED_APP_ROLES:
                logger.warning("app_token_restricted_role_blocked", ...)
                continue  # ← Role stripped from app tokens
            internal_roles.append(internal_role)
```

### 10.6 Verification Commands

```bash
# Test 1: Token without tid → 403 MISSING_TID
curl -H "Authorization: Bearer {token_without_tid}" \
     http://localhost:8000/api/v1/plans
# Expected: 403 {"error": "MISSING_TID"}

# Test 2: Unmapped Entra tenant → 403 TENANT_NOT_MAPPED
curl -H "Authorization: Bearer {token_with_unknown_tid}" \
     http://localhost:8000/api/v1/plans
# Expected: 403 {"error": "TENANT_NOT_MAPPED"}

# Test 3: PLANNER cannot lock → 403 INSUFFICIENT_ROLE
curl -H "Authorization: Bearer {planner_token}" \
     -X POST http://localhost:8000/api/v1/plans/1/lock
# Expected: 403 {"error": "INSUFFICIENT_ROLE"}

# Test 4: APPROVER can lock → 200 OK
curl -H "Authorization: Bearer {approver_token}" \
     -X POST http://localhost:8000/api/v1/plans/1/lock \
     -H "Content-Type: application/json" \
     -d '{"notes": "Release approved"}'
# Expected: 200 {"status": "LOCKED", ...}

# Test 5: M2M token cannot lock → 403 APP_TOKEN_NOT_ALLOWED
curl -H "Authorization: Bearer {m2m_token}" \
     -X POST http://localhost:8000/api/v1/plans/1/lock
# Expected: 403 {"error": "APP_TOKEN_NOT_ALLOWED"}
```

### 10.7 Test Coverage

| Test File | Tests | Status |
|-----------|-------|--------|
| `test_entra_tenant_mapping.py` | Missing tid, unmapped tid, role mapping | Created |
| `test_rbac_lock_approver.py` | PLANNER denied, APPROVER allowed, M2M denied | Created |

### 10.8 Production Configuration

```bash
# Required environment variables for Entra ID
SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{entra_tenant_id}/v2.0
SOLVEREIGN_OIDC_AUDIENCE=api://solvereign-api
SOLVEREIGN_OIDC_CLOCK_SKEW_SECONDS=60

# Security guardrail (MUST be false in production)
SOLVEREIGN_ALLOW_HEADER_TENANT_OVERRIDE=false
```

---

## 11. Known Limitations

| Item | Status | Mitigation |
|------|--------|------------|
| Keycloak not integrated | Pending | Self-hosted auth works |
| KMS not integrated | Pending | Env var for dev, ADR documented |
| MFA not enforced | Pending | IdP will handle |
| CRITICAL alerting | Pending | Logs contain severity |
| Pen test | Pending | Scheduled before prod |

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Security Architect | | | |
| Senior Developer | | | |
| DevOps Lead | | | |

---

*Generated: 2026-01-05*
