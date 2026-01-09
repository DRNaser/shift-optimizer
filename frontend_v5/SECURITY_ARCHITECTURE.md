# SOLVEREIGN Frontend Security Architecture

> **Status**: v2 - REVIEWED & EXTENDED
> **Date**: 2026-01-06
> **Scope**: Trust boundaries, session management, authorization, defense-in-depth

---

## Trust Anchor Architecture

### Data Flow
```
                    ┌─────────────────────────────────────────────────────┐
                    │                   INTERNAL NETWORK                   │
                    │   ┌──────────┐        ┌──────────┐                  │
Browser ──HTTPS──▶  │   │   BFF    │──mTLS──▶│ Backend  │                  │
      __Host-cookie │   │ (Next.js)│        │(FastAPI) │                  │
                    │   └──────────┘        └──────────┘                  │
                    │        │                   │                         │
                    │   X-Internal-Auth     SET LOCAL                      │
                    │   X-Tenant-ID         app.current_tenant             │
                    │                            │                         │
                    │                       ┌────▼────┐                    │
                    │                       │Postgres │                    │
                    │                       │  (RLS)  │                    │
                    │                       └─────────┘                    │
                    └─────────────────────────────────────────────────────┘
```

### Key Principles

1. **Browser Never Provides Tenant/Site Context**
   - All tenant/site information comes from `__Host-sv_tenant` cookie
   - Cookie is HttpOnly, Secure, SameSite=Strict
   - Browser cannot read or manipulate session data

2. **BFF is the ONLY Public Gateway**
   - Backend has NO public ingress (internal network only)
   - BFF adds `X-Internal-Auth` header (shared secret or mTLS)
   - Backend REJECTS any request without valid internal auth

3. **Backend Validates Internal Origin**
   - `X-Tenant-ID` is ONLY trusted with valid `X-Internal-Auth`
   - Without internal auth → 401 Unauthorized (even with valid tenant ID)
   - This prevents header spoofing via proxy/forwarding attacks

---

## 1. Backend Internal Auth (CRITICAL)

### Problem: Header Spoofing
```
# ATTACK: Attacker bypasses BFF, sends direct request with spoofed header
curl -H "X-Tenant-ID: victim-tenant" https://backend.internal/api/plans
```

### Solution: Internal Auth Requirement

**Option A: Shared Secret Header**
```python
# backend_py/src/api/dependencies.py
INTERNAL_AUTH_SECRET = os.environ["INTERNAL_AUTH_SECRET"]

async def verify_internal_auth(
    x_internal_auth: str = Header(..., alias="X-Internal-Auth")
):
    if not secrets.compare_digest(x_internal_auth, INTERNAL_AUTH_SECRET):
        raise HTTPException(401, "Invalid internal auth")

# Every endpoint requires this
@router.get("/plans")
async def list_plans(
    _internal: None = Depends(verify_internal_auth),  # MUST PASS
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    ...
```

**Option B: mTLS (Preferred for Production)**
```yaml
# Backend only accepts connections with valid client cert
# BFF presents client cert signed by internal CA
# No cert = connection refused at TLS layer
```

**Option C: Network Isolation (Kubernetes)**
```yaml
# NetworkPolicy: Backend only accepts from BFF pod
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-allow-bff-only
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: bff
```

### BFF Header Injection
```typescript
// app/api/[...proxy]/route.ts
const INTERNAL_AUTH_SECRET = process.env.INTERNAL_AUTH_SECRET!;

export async function handler(request: NextRequest) {
  const session = await getSession(request);

  return fetch(`${BACKEND_INTERNAL_URL}${request.nextUrl.pathname}`, {
    headers: {
      'X-Internal-Auth': INTERNAL_AUTH_SECRET,  // Proves request from BFF
      'X-Tenant-ID': session.tenant_id,
      'X-Site-ID': session.current_site_id,
      'X-User-ID': session.user_id,
    },
  });
}
```

---

## 2. Database Tenant Context (RLS Safety)

### Problem: Connection Pool Tenant Leak
```
Request 1 (Tenant A) → Connection 1 → SET app.tenant = 'A'
Request 2 (Tenant B) → Connection 1 (reused!) → Still has tenant 'A' 💀
```

### Solution: SET LOCAL in Transaction Wrapper

```python
# backend_py/src/database.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def tenant_transaction(tenant_id: str, site_id: str | None = None):
    """
    CRITICAL: Every request MUST use this wrapper.
    SET LOCAL only affects current transaction, auto-cleared on commit/rollback.
    """
    async with db_pool.connection() as conn:
        async with conn.transaction():
            # SET LOCAL = transaction-scoped, not connection-scoped
            await conn.execute(
                "SET LOCAL app.current_tenant_id = %s",
                [tenant_id]
            )
            if site_id:
                await conn.execute(
                    "SET LOCAL app.current_site_id = %s",
                    [site_id]
                )
            yield conn
            # Transaction ends → settings automatically cleared
            # Connection returns to pool in clean state
```

### FastAPI Dependency
```python
# backend_py/src/api/dependencies.py
async def get_tenant_db(
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    site_id: str = Header(None, alias="X-Site-ID"),
):
    async with tenant_transaction(tenant_id, site_id) as conn:
        yield conn

# Usage
@router.get("/plans")
async def list_plans(db = Depends(get_tenant_db)):
    # RLS uses current_setting('app.current_tenant_id')
    return await db.fetch_all("SELECT * FROM plans")
```

### Required Test: Pool Reuse Safety
```python
# tests/test_tenant_isolation.py
async def test_connection_pool_no_tenant_leak():
    """Verify tenant context doesn't leak between requests."""

    # Request 1: Tenant A
    async with tenant_transaction("tenant-a") as conn:
        await conn.execute("INSERT INTO plans (name) VALUES ('Plan A')")

    # Request 2: Tenant B on potentially same connection
    async with tenant_transaction("tenant-b") as conn:
        plans = await conn.fetch_all("SELECT * FROM plans")
        # MUST NOT see Tenant A's plan
        assert all(p['tenant_id'] == 'tenant-b' for p in plans)

    # Request 3: No tenant context (should fail or return empty)
    async with db_pool.connection() as conn:
        # Without SET LOCAL, RLS should block everything
        plans = await conn.fetch_all("SELECT * FROM plans")
        assert len(plans) == 0  # RLS blocks
```

---

## 3. Session Architecture (Minimal Cookie)

### Problem: Large Cookie Payload
```typescript
// ❌ BAD: Too much data, stale on permission change, hits 4KB limit
interface TenantSession {
  tenant_id: string;
  user_id: string;
  role: UserRole;
  permissions: Permission[];  // Can be 20+ items
  site_ids: string[];         // Can be 10+ sites
  current_site_id: string;
  issued_at: number;
  expires_at: number;
}
```

### Solution: Minimal Cookie + Server-Side Session

**Cookie Contains Only:**
```typescript
// ✅ GOOD: Minimal, under 500 bytes encrypted
interface CookiePayload {
  sid: string;              // Session ID (UUID)
  tid: string;              // Tenant ID
  uid: string;              // User ID
  v: number;                // Session version (for invalidation)
  exp: number;              // Expiry timestamp
}
```

**Full Session in Redis:**
```typescript
// Stored in Redis: sessions:{sid}
interface ServerSession {
  tenant_id: string;
  user_id: string;
  role: UserRole;
  permissions: Permission[];
  site_ids: string[];
  current_site_id: string;
  created_at: number;
  last_activity: number;
  // Metadata for invalidation
  session_version: number;
  ip_address: string;
  user_agent: string;
}
```

### Session Lookup Flow
```typescript
// lib/session.ts
export async function getSession(request: NextRequest): Promise<ServerSession> {
  const cookie = request.cookies.get('__Host-sv_tenant');
  if (!cookie) throw new AuthError('No session cookie');

  const payload = decrypt<CookiePayload>(cookie.value);

  // Check expiry
  if (payload.exp < Date.now() / 1000) {
    throw new AuthError('Session expired');
  }

  // Fetch full session from Redis
  const session = await redis.get(`sessions:${payload.sid}`);
  if (!session) throw new AuthError('Session not found');

  // Check version (for forced invalidation)
  if (session.session_version !== payload.v) {
    throw new AuthError('Session invalidated');
  }

  return session;
}
```

---

## 4. CSRF Protection (Defense in Depth)

### SameSite=Strict is NOT Enough
- May need to relax for SSO/OAuth flows
- Defense in depth is required

### Origin/Referer Validation
```typescript
// middleware.ts
const ALLOWED_ORIGINS = [
  'https://platform.solvereign.io',
  'https://*.solvereign.io',  // Tenant subdomains
];

export function middleware(request: NextRequest) {
  // Only check state-changing methods
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
    const origin = request.headers.get('Origin');
    const referer = request.headers.get('Referer');

    const checkOrigin = origin || (referer ? new URL(referer).origin : null);

    if (!checkOrigin || !isAllowedOrigin(checkOrigin, ALLOWED_ORIGINS)) {
      return NextResponse.json(
        { error: 'Invalid origin' },
        { status: 403 }
      );
    }
  }

  return NextResponse.next();
}

function isAllowedOrigin(origin: string, allowed: string[]): boolean {
  return allowed.some(pattern => {
    if (pattern.includes('*')) {
      const regex = new RegExp('^' + pattern.replace('*', '[^.]+') + '$');
      return regex.test(origin);
    }
    return origin === pattern;
  });
}
```

### Optional: CSRF Token (Double Submit)
```typescript
// For forms that can't use fetch with credentials
// Generate token in cookie + require in header/body

// Set token cookie (readable by JS, NOT HttpOnly)
Set-Cookie: sv_csrf=<random>; Secure; SameSite=Strict; Path=/

// Client reads cookie, sends in header
fetch('/api/action', {
  headers: { 'X-CSRF-Token': getCookie('sv_csrf') }
});

// Server validates cookie value === header value
```

### CORS Configuration
```typescript
// next.config.ts
const nextConfig = {
  async headers() {
    return [
      {
        source: '/api/:path*',
        headers: [
          {
            key: 'Access-Control-Allow-Origin',
            value: 'https://platform.solvereign.io',  // NO wildcards
          },
          {
            key: 'Access-Control-Allow-Credentials',
            value: 'true',
          },
          {
            key: 'Access-Control-Allow-Methods',
            value: 'GET, POST, PUT, DELETE, OPTIONS',
          },
        ],
      },
    ];
  },
};
```

---

## 5. Session Lifecycle & Invalidation

### Session Events

| Event | Action |
|-------|--------|
| Login | Create session, set cookie |
| Logout | Delete Redis session, clear cookie |
| Role change | Increment `session_version`, force re-auth |
| Permission change | Increment `session_version`, force re-auth |
| Pack entitlement change | Increment `session_version`, force re-auth |
| Security incident | Bulk invalidate all sessions for tenant |
| Password change | Invalidate all other sessions for user |

### Implementation
```python
# backend_py/src/services/session.py

async def invalidate_user_sessions(user_id: str, except_sid: str | None = None):
    """Invalidate all sessions for user (e.g., password change)."""
    pattern = f"sessions:*"
    async for key in redis.scan_iter(pattern):
        session = await redis.get(key)
        if session and session['user_id'] == user_id:
            if except_sid and key.endswith(except_sid):
                continue
            await redis.delete(key)

async def invalidate_tenant_sessions(tenant_id: str):
    """Invalidate all sessions for tenant (e.g., security incident)."""
    pattern = f"sessions:*"
    async for key in redis.scan_iter(pattern):
        session = await redis.get(key)
        if session and session['tenant_id'] == tenant_id:
            await redis.delete(key)

async def bump_session_version(user_id: str):
    """Force re-auth on next request (e.g., role change)."""
    user = await db.fetch_one("SELECT session_version FROM users WHERE id = $1", [user_id])
    new_version = (user['session_version'] or 0) + 1
    await db.execute(
        "UPDATE users SET session_version = $1 WHERE id = $2",
        [new_version, user_id]
    )
    # Existing sessions will fail version check → force re-auth
```

### Session TTL Strategy
```
Access Token (Cookie): 15 minutes
Refresh Window: 7 days (sliding)
Absolute Max: 30 days

On each request:
  - If token expires in < 5 min → issue new token
  - If refresh window expired → force re-auth
  - If absolute max reached → force re-auth
```

---

## 6. Audit Logging (Required Events)

### Security-Critical Events
```python
# backend_py/src/services/audit.py

class AuditEvent(str, Enum):
    # Auth
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILED = "auth.login.failed"
    LOGOUT = "auth.logout"
    SESSION_INVALIDATED = "auth.session.invalidated"

    # Tenant Context
    SITE_SWITCH = "tenant.site.switch"

    # Plan Lifecycle (Critical)
    PLAN_LOCKED = "plan.locked"
    PLAN_FROZEN = "plan.frozen"
    PLAN_REPAIR_STARTED = "plan.repair.started"
    PLAN_REPAIR_COMPLETED = "plan.repair.completed"

    # Evidence
    EVIDENCE_GENERATED = "evidence.generated"
    EVIDENCE_DOWNLOADED = "evidence.downloaded"

    # Admin
    USER_ROLE_CHANGED = "admin.user.role_changed"
    USER_PERMISSIONS_CHANGED = "admin.user.permissions_changed"
    PACK_ENABLED = "admin.pack.enabled"
    PACK_DISABLED = "admin.pack.disabled"

async def audit_log(
    event: AuditEvent,
    tenant_id: str,
    user_id: str,
    site_id: str | None,
    details: dict,
    ip_address: str,
):
    await db.execute("""
        INSERT INTO audit_log (event, tenant_id, user_id, site_id, details, ip_address, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
    """, [event.value, tenant_id, user_id, site_id, json.dumps(details), ip_address])
```

---

## 7. Content Security Policy (Full)

```typescript
// middleware.ts
const CSP_DIRECTIVES = {
  'default-src': ["'self'"],
  'script-src': ["'self'", "'strict-dynamic'"],  // No unsafe-inline
  'style-src': ["'self'", "'unsafe-inline'"],    // Tailwind needs this
  'img-src': ["'self'", 'data:', 'https://*.solvereign.io'],
  'font-src': ["'self'"],
  'connect-src': [
    "'self'",
    'https://api.solvereign.io',        // Backend API
    'https://*.sentry.io',               // Error tracking
    'https://api.mapbox.com',            // Map tiles (if routing pack)
  ],
  'frame-ancestors': ["'none'"],         // Clickjacking protection
  'base-uri': ["'self'"],
  'form-action': ["'self'"],
  'upgrade-insecure-requests': [],
};

const cspHeader = Object.entries(CSP_DIRECTIVES)
  .map(([key, values]) => `${key} ${values.join(' ')}`)
  .join('; ');

// Set header
response.headers.set('Content-Security-Policy', cspHeader);
```

---

## 8. BFF Response Minimization

### Problem: Leaking Internal Data
```typescript
// ❌ BAD: Returns everything from session
return NextResponse.json({
  tenant: fullTenantObject,      // May contain billing info
  user: fullUserObject,          // May contain internal flags
  sites: allSitesWithSettings,   // May contain sensitive config
});
```

### Solution: Explicit DTO
```typescript
// ✅ GOOD: Only what UI needs
interface TenantMeDTO {
  tenant: {
    id: string;
    name: string;
    slug: string;
    logo_url: string | null;
  };
  user: {
    id: string;
    name: string;
    email: string;
    role: string;
  };
  sites: Array<{
    id: string;
    code: string;
    name: string;
  }>;
  current_site_id: string | null;
  enabled_packs: string[];
}

export async function GET(request: NextRequest) {
  const session = await getSession(request);

  // Fetch only what's needed, not full objects
  const tenant = await fetchTenantPublicInfo(session.tenant_id);
  const user = await fetchUserPublicInfo(session.user_id);
  const sites = await fetchSitesMinimal(session.tenant_id, session.site_ids);

  const dto: TenantMeDTO = {
    tenant: {
      id: tenant.id,
      name: tenant.name,
      slug: tenant.slug,
      logo_url: tenant.logo_url,
    },
    user: {
      id: user.id,
      name: user.name,
      email: user.email,
      role: user.role,
    },
    sites: sites.map(s => ({
      id: s.id,
      code: s.code,
      name: s.name,
    })),
    current_site_id: session.current_site_id,
    enabled_packs: session.enabled_packs,
  };

  return NextResponse.json(dto);
}
```

---

## Security DoD Checklist

### Backend Isolation
- [ ] Backend has no public ingress
- [ ] X-Internal-Auth header required on all endpoints
- [ ] Internal auth validated with constant-time comparison
- [ ] Network policy restricts backend access to BFF only

### Database Tenant Safety
- [ ] SET LOCAL in transaction wrapper (not SET)
- [ ] RLS policies on all tenant-scoped tables
- [ ] Connection pool reuse test passes
- [ ] No raw queries without tenant context

### Session Management
- [ ] Cookie payload < 500 bytes
- [ ] Full session in Redis (not cookie)
- [ ] Session version for forced invalidation
- [ ] TTL with sliding refresh window
- [ ] Absolute max session lifetime

### CSRF Protection
- [ ] Origin/Referer validation on state-changing requests
- [ ] CORS without wildcards
- [ ] SameSite=Strict on all cookies
- [ ] Optional: CSRF token for forms

### Audit Logging
- [ ] Login/logout events
- [ ] Site switch events
- [ ] Plan lock/freeze/repair events
- [ ] Evidence generation/download events
- [ ] Permission/role change events

### Response Security
- [ ] BFF returns minimal DTOs
- [ ] No internal IDs/flags exposed
- [ ] CSP with no unsafe-inline for scripts
- [ ] All security headers set

---

## Related Files

| File | Purpose |
|------|---------|
| [lib/hooks/use-tenant.ts](lib/hooks/use-tenant.ts) | Tenant context (UX-only guards) |
| [lib/tenant-types.ts](lib/tenant-types.ts) | Type definitions |
| [app/api/tenant/me/route.ts](app/api/tenant/me/route.ts) | BFF - tenant context |
| [app/api/tenant/switch-site/route.ts](app/api/tenant/switch-site/route.ts) | BFF - site switching |
| [middleware.ts](middleware.ts) | Origin check, CSP headers |
| backend_py/src/api/dependencies.py | Internal auth, tenant context |
| backend_py/src/database.py | Transaction wrapper with SET LOCAL |
