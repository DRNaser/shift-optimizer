# SOLVEREIGN V4 - Agent Context

> **Status**: V4.5.0 | SaaS Admin Core | Production Ready
> **Last Updated**: 2026-01-09

---

## What is SOLVEREIGN?

Enterprise multi-tenant shift scheduling platform for logistics companies.

```
IMPORT → SOLVE → PUBLISH
├─ FLS/CSV import          ├─ OR-Tools VRPTW          ├─ Audit Gates
├─ Multi-tenant RLS        ├─ 145 drivers/100% cover  ├─ Evidence Pack
└─ Site Partitioning       └─ 7/7 audits PASS         └─ Lock + Export
```

**Current Tenant**: LTS Transport (pilot: Wien)

---

## Security Stack (CRITICAL)

### Role Hierarchy

| Role | Purpose | Can Access Tenants? |
|------|---------|---------------------|
| `solvereign_admin` | Migrations only | Yes (NO runtime use) |
| `solvereign_platform` | Admin operations | Yes |
| `solvereign_api` | Tenant operations | NO |
| `solvereign_definer` | Function owner | NO BYPASSRLS |

### Critical Pattern - SECURITY DEFINER Functions

```sql
-- ALWAYS use session_user, NOT current_user
IF NOT pg_has_role(session_user, 'solvereign_platform', 'MEMBER') THEN
    RAISE EXCEPTION 'Permission denied';
END IF;
```

### Verification (Source of Truth)

```bash
# Security (17 tests must PASS)
psql $DATABASE_URL -c "SELECT * FROM verify_final_hardening();"

# RBAC integrity (13 checks)
psql $DATABASE_URL -c "SELECT * FROM auth.verify_rbac_integrity();"

# Portal integrity
psql $DATABASE_URL -c "SELECT * FROM portal.verify_portal_integrity();"

# Notification integrity
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"
```

---

## V4.5.0: SaaS Admin Core (Current)

### Overview

Complete SaaS administration platform with role-based platform admin scoping:
- **Argon2id** password hashing
- **HttpOnly cookies** (`admin_session`)
- **Permission-based RBAC** per role
- **Tenant isolation** via user bindings
- **Platform admin** identified by role_name="platform_admin" (NOT tenant_id)

### Platform Admin Scoping (Role-Based)

**IMPORTANT**: Platform admins are identified by role, not tenant_id:

| Role | tenant_id | Access Level |
|------|-----------|--------------|
| `platform_admin` | NULL | All tenants (platform-wide access) |
| `tenant_admin` | 1+ | Single tenant full access |
| Others | 1+ | Single tenant, limited access |

- **platform_admin** identified by `role_name = "platform_admin"` ONLY
- Platform admin bindings have `tenant_id = NULL` (no tenant restriction)
- Sessions track `is_platform_scope` flag for SQL function access
- Audit log tracks `target_tenant_id` for cross-tenant operations
- Regular users are strictly bound to their tenant(s)
- **NO FAKE tenant_id=0**: Removed broken pattern from previous version

### Auth Schema (`auth.*`)

| Table | Purpose |
|-------|---------|
| `auth.users` | Email, password_hash, display_name |
| `auth.roles` | platform_admin, **tenant_admin**, operator_admin, dispatcher, ops_readonly |
| `auth.permissions` | portal.*, **platform.*, tenant.*** |
| `auth.role_permissions` | Role → Permission mappings |
| `auth.user_bindings` | User → Tenant/Site/Role (NULL tenant for platform_admin) |
| `auth.sessions` | Session tokens (hashed), is_platform_scope flag |
| `auth.audit_log` | Immutable audit trail, target_tenant_id for cross-tenant ops |

### Role Hierarchy

| Role | Purpose | tenant_id |
|------|---------|-----------|
| `platform_admin` | Full platform access | NULL (platform-wide) |
| `tenant_admin` | Full tenant access | 1+ (specific tenant) |
| `operator_admin` | Operations management | 1+ |
| `dispatcher` | Day-to-day operations | 1+ |
| `ops_readonly` | Read-only access | 1+ |

### Permission Categories

| Category | Examples | Who |
|----------|----------|-----|
| `platform.*` | tenants.write, users.write | platform_admin |
| `tenant.*` | sites.write, drivers.write | tenant_admin+ |
| `portal.*` | summary.read, resend.write | dispatcher+ |

### RBAC Bypass Rules

- **platform_admin bypasses all permission checks** - superuser access
- Regular users require specific permissions for each endpoint
- Permission bypass is role-based, not tenant-based

### Context Switching (Platform Admin)

Platform admins can set an active tenant context to use tenant-scoped UIs:

```bash
# Set active tenant context
POST /api/platform/context {"tenant_id": 1, "site_id": 10}

# Get current context
GET /api/platform/context

# Clear context (return to platform-wide scope)
DELETE /api/platform/context
```

All context switches are audited with `target_tenant_id`.

### API Endpoints

**Authentication:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login` | POST | Email/password login |
| `/api/auth/logout` | POST | Revoke session |
| `/api/auth/me` | GET | Get current user |

**Platform Administration (platform_admin only):**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/platform/tenants` | GET/POST | List/create tenants |
| `/api/platform/tenants/{id}` | GET | Tenant details |
| `/api/platform/tenants/{id}/sites` | GET/POST | List/create sites |
| `/api/platform/users` | GET/POST | List/create users |
| `/api/platform/users/{id}/reset-password` | POST | Reset password |
| `/api/platform/bindings` | POST | Create binding |
| `/api/platform/roles` | GET | List roles |
| `/api/platform/permissions` | GET | List permissions |
| `/api/platform/context` | GET/POST/DELETE | Get/set/clear active tenant context |

### User Management

```bash
# Bootstrap first platform admin (one-time setup)
python scripts/create_user.py bootstrap-platform-admin

# Create user (password prompted securely - NEVER pass on command line)
python scripts/create_user.py create \
    --email <user-email> \
    --name "<Display Name>" \
    --tenant <tenant-id> --site <site-id> --role <role>

# List users
python scripts/create_user.py list

# Verify RBAC
python scripts/create_user.py verify
```

### Platform Admin UI

| Route | Purpose |
|-------|---------|
| `/platform/login` | Login page |
| `/platform-admin` | Admin dashboard |
| `/platform-admin/tenants` | Tenant list |
| `/platform-admin/tenants/new` | Create tenant wizard |
| `/platform-admin/users` | User list |
| `/platform-admin/users/new` | Create user form |

**SECURITY**: Never hardcode credentials. Use environment variables or interactive prompts.

---

## Key Subsystems

### Driver Portal (`portal.*`)

Magic link authentication for drivers to view/acknowledge plans.

| Endpoint | Purpose |
|----------|---------|
| `/my-plan?t=<jwt>` | Driver views plan |
| `/api/portal/session` | Token → cookie exchange |
| `/api/portal/read` | Record read receipt |
| `/api/portal/ack` | Accept/decline plan |

**Cookies**: `portal_session` (driver) vs `admin_session` (admin)

### Notification Pipeline (`notify.*`)

Transactional outbox for WhatsApp/Email/SMS.

- **C#/.NET Worker**: `backend_dotnet/Solvereign.Notify/`
- **Outbox pattern**: At-least-once delivery
- **Dedup key**: SHA-256 prevents duplicate sends
- **Webhook verification**: HMAC for WhatsApp, ECDSA for SendGrid

### Master Data Layer (`masterdata.*`)

Canonical entities + external ID mappings.

```bash
# Verify MDL (9 checks)
psql $DATABASE_URL -c "SELECT * FROM masterdata.verify_masterdata_integrity();"
```

### Dispatch Assist (`dispatch.*`)

Google Sheets integration for Gurkerl roster management.

```bash
# Verify dispatch (12 checks)
psql $DATABASE_URL -c "SELECT * FROM dispatch.verify_dispatch_integrity();"
```

---

## Architecture Patterns

### Template vs Instance
- **Templates** (`tours_normalized`): Store with `count=3`
- **Instances** (`tour_instances`): Expand to 3 rows for solver

### Immutability
- LOCKED plans: No UPDATE/DELETE via triggers
- `driver_ack`: Immutable (arbeitsrechtlich)

### Plan Versioning
- `plan_versions`: Working plans (modifiable)
- `plan_snapshots`: Immutable published versions

---

## Migrations (Apply in Order)

```bash
# Security stack (025-025f)
psql $DATABASE_URL < backend_py/db/migrations/025_tenants_rls_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025a_rls_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025b_rls_role_lockdown.sql
psql $DATABASE_URL < backend_py/db/migrations/025c_rls_boundary_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025d_definer_owner_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025e_final_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025f_acl_fix.sql

# Solver + Plan versioning
psql $DATABASE_URL < backend_py/db/migrations/026_solver_runs.sql
psql $DATABASE_URL < backend_py/db/migrations/026a_state_atomicity.sql
psql $DATABASE_URL < backend_py/db/migrations/027_plan_versioning.sql
psql $DATABASE_URL < backend_py/db/migrations/027a_snapshot_fixes.sql

# Master data + Dispatch
psql $DATABASE_URL < backend_py/db/migrations/028_masterdata.sql
psql $DATABASE_URL < backend_py/db/migrations/031_dispatch_lifecycle.sql

# Portal + Notifications
psql $DATABASE_URL < backend_py/db/migrations/033_portal_magic_links.sql
psql $DATABASE_URL < backend_py/db/migrations/034_notifications.sql
psql $DATABASE_URL < backend_py/db/migrations/035_notifications_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/036_notifications_retention.sql
psql $DATABASE_URL < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL < backend_py/db/migrations/037a_portal_notify_hardening.sql

# Internal RBAC
psql $DATABASE_URL < backend_py/db/migrations/039_internal_rbac.sql

# SaaS Admin Core (V4.5)
psql $DATABASE_URL < backend_py/db/migrations/040_platform_admin_model.sql
psql $DATABASE_URL < backend_py/db/migrations/041_platform_context_switching.sql
```

---

## Key Files

### Backend

| Category | File |
|----------|------|
| API Entry | `backend_py/api/main.py` |
| Auth Router | `backend_py/api/routers/auth.py` |
| Platform Admin Router | `backend_py/api/routers/platform_admin.py` |
| RBAC Logic | `backend_py/api/security/internal_rbac.py` |
| Portal Admin | `backend_py/api/routers/portal_admin.py` |
| Portal Public | `backend_py/api/routers/portal_public.py` |
| Solver | `backend_py/v3/solver_wrapper.py` |

### Frontend

| Category | File |
|----------|------|
| Login Page | `frontend_v5/app/platform/login/page.tsx` |
| Platform Admin Home | `frontend_v5/app/(platform)/platform-admin/page.tsx` |
| Tenant List | `frontend_v5/app/(platform)/platform-admin/tenants/page.tsx` |
| Tenant Wizard | `frontend_v5/app/(platform)/platform-admin/tenants/new/page.tsx` |
| User List | `frontend_v5/app/(platform)/platform-admin/users/page.tsx` |
| Driver Portal | `frontend_v5/app/my-plan/page.tsx` |
| Auth BFF | `frontend_v5/app/api/auth/*/route.ts` |
| Platform Admin BFF | `frontend_v5/app/api/platform-admin/*/route.ts` |
| Portal BFF | `frontend_v5/app/api/portal/*/route.ts` |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/create_user.py` | User management CLI |
| `scripts/staging_preflight.py` | Pre-deployment checks |

---

## Wien Pilot Checklist

### P0 Blockers

| Gate | Item | Verify |
|------|------|--------|
| A | Security headers | `curl -I https://staging/my-plan` |
| B | Auth working | `python scripts/staging_preflight.py` |
| C | Real providers | Email + WhatsApp screenshots |
| D | Prod migrations | All verify functions PASS |

### Quick Staging Test

```bash
# Set credentials via environment (NEVER hardcode)
export STAGING_URL=http://localhost:8000
export STAGING_EMAIL=<your-test-email>
export STAGING_PASSWORD=<prompt-for-password>
python scripts/staging_preflight.py

# Docker-native (recommended - avoids Windows timeouts):
docker compose exec api python scripts/staging_preflight.py \
    --base-url http://localhost:8000 \
    --email <your-test-email>
# Password will be prompted interactively
```

**Note**: If Secure cookies block local HTTP, preflight will warn:
"HTTPS required for Secure cookie" - run on real staging host or inside Docker.

---

## Completed Milestones

| Version | Milestone |
|---------|-----------|
| V3.3-V3.6 | Multi-tenant API, Routing Pack, Security Stack |
| V3.7 | Plan Versioning, Wien Pilot Infrastructure |
| V3.8-V3.9 | Master Data Layer, Dispatch Assist |
| V4.1-V4.2 | Portal + Notifications + Integration |
| V4.3 | Frontend Driver Portal |
| V4.4 | Internal RBAC |
| **V4.5** | **SaaS Admin Core (Current)** |

---

## Test Commands

```bash
# Python tests
pytest backend_py/tests/test_final_hardening.py -v
pytest backend_py/api/tests/test_internal_rbac.py -v

# C# tests
cd backend_dotnet/Solvereign.Notify.Tests && dotnet test

# Frontend
cd frontend_v5 && npx tsc --noEmit && npx next build
```

---

*For detailed version history, see `docs/` and migration files.*
