# DB Schema Truth-Probe

**Date**: 2026-01-13
**Container**: solvereign-pilot-db

## 1. auth.sessions Table

| Column | Data Type | Max Length | Nullable |
|--------|-----------|------------|----------|
| id | uuid | - | NO |
| user_id | uuid | - | NO |
| tenant_id | integer | - | YES |
| site_id | integer | - | YES |
| role_id | integer | - | NO |
| session_hash | character | 64 | NO |
| created_at | timestamp with time zone | - | NO |
| expires_at | timestamp with time zone | - | NO |
| last_activity_at | timestamp with time zone | - | NO |
| revoked_at | timestamp with time zone | - | YES |
| revoked_reason | text | - | YES |
| rotated_from | uuid | - | YES |
| ip_hash | character | 64 | YES |
| user_agent_hash | character | 64 | YES |
| active_tenant_id | integer | - | YES |
| active_site_id | integer | - | YES |
| is_platform_scope | boolean | - | NO |

**Verdict**: Schema MATCHES code expectations in `internal_rbac.py:474-487`

## 2. auth.validate_session Functions

Two overloaded functions exist:

### Function 1 (TEXT parameter - CURRENT)
```
Arguments: p_session_hash text
Returns: TABLE(
  session_id uuid,
  user_id uuid,
  user_email character varying,
  user_display_name character varying,
  tenant_id integer,
  site_id integer,
  role_id integer,
  role_name character varying,
  expires_at timestamp with time zone,
  is_platform_scope boolean,
  active_tenant_id integer,
  active_site_id integer
)
```

### Function 2 (CHARACTER parameter - LEGACY)
```
Arguments: p_session_hash character
Returns: TABLE(
  session_id uuid,
  user_id uuid,
  user_email character varying,
  user_display_name character varying,
  tenant_id integer,
  site_id integer,
  role_id integer,
  role_name character varying,
  expires_at timestamp with time zone
)
```

**Code expectation** (`internal_rbac.py:474-487`):
- Expects 12 columns: session_id, user_id, user_email, user_display_name, tenant_id, site_id, role_id, role_name, expires_at, is_platform_scope, active_tenant_id, active_site_id
- Uses `len(row) > 9` guard for backwards compatibility

**Verdict**: Function 1 (TEXT) MATCHES. Function 2 (CHARACTER) is legacy but harmless (Postgres will pick TEXT version for text input).

## 3. auth.users Table

| Column | Data Type | Max Length |
|--------|-----------|------------|
| id | uuid | - |
| email | character varying | 255 |
| display_name | character varying | 255 |
| password_hash | text | - |
| is_active | boolean | - |
| is_locked | boolean | - |
| ... | ... | ... |

**Verdict**: MATCHES `validate_session` return types (VARCHAR(255) for email/display_name)

## 4. E2E Test User

```
ID: 667fec1d-0e58-495e-8ee3-a5b82de366d2
Email: e2e-test@example.com
Display Name: E2E Test User
is_active: true
is_locked: false
```

### Binding:
```
tenant_id: 1
site_id: 1
role_name: platform_admin
```

**Issue Found**: User has `tenant_id=1` binding but role is `platform_admin`. Per CLAUDE.md, platform_admin should have `tenant_id=NULL` for platform-wide access.

## 5. Active Sessions

5 active sessions found for e2e user (none revoked), all with:
- `is_platform_scope: false`
- `tenant_id: NULL`

**Issue Found**: `is_platform_scope` is FALSE even though user is platform_admin. This may cause context-related failures.

## Summary

| Check | Status | Notes |
|-------|--------|-------|
| sessions columns | PASS | All 17 columns present |
| validate_session signature | PASS | 12-column return matches code |
| users table types | PASS | VARCHAR(255) matches function |
| e2e user exists | PASS | Active, not locked |
| e2e user binding | WARN | platform_admin has tenant_id=1 instead of NULL |
| session is_platform_scope | WARN | FALSE instead of TRUE for platform_admin |

## Recommendations

1. Fix e2e user binding: `UPDATE auth.user_bindings SET tenant_id = NULL WHERE user_id = '667fec1d-0e58-495e-8ee3-a5b82de366d2'`
2. Verify session creation sets `is_platform_scope = TRUE` for platform_admin role
