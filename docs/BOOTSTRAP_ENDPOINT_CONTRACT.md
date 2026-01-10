# Bootstrap Endpoint Contract

> **Endpoint**: `POST /api/auth/staging-bootstrap`
> **Location**: `frontend_v5/app/api/auth/staging-bootstrap/route.ts`
> **Purpose**: Create platform admin session for automated testing/preflight

---

## Activation

| Env Var | Value | Effect |
|---------|-------|--------|
| `STAGING_BOOTSTRAP_ENABLED` | `true` | Endpoint active |
| `STAGING_BOOTSTRAP_ENABLED` | `false` (default) | Returns 403 |
| `STAGING_BOOTSTRAP_SECRET` | (required) | Auth secret |

---

## Request

```http
POST /api/auth/staging-bootstrap HTTP/1.1
Host: localhost:3000
x-bootstrap-secret: <secret-from-env-file>
```

---

## Response Codes

| Scenario | HTTP | Code | Message |
|----------|------|------|---------|
| Bootstrap disabled | 403 | `BOOTSTRAP_DISABLED` | Set STAGING_BOOTSTRAP_ENABLED=true |
| Secret not configured | 500 | `MISCONFIGURED` | Set STAGING_BOOTSTRAP_SECRET env var |
| Header missing | 401 | `MISSING_SECRET` | x-bootstrap-secret header is required |
| Wrong secret | 401 | `INVALID_SECRET` | Invalid bootstrap secret |
| Success | 200 | - | Session created |

---

## Success Response

```json
{
  "success": true,
  "csrf_token": "<64-char-hex>",
  "user": {
    "id": "staging-bootstrap-admin",
    "email": "staging-bootstrap@solvereign.internal",
    "name": "Staging Bootstrap",
    "role": "platform_admin"
  },
  "session": {
    "ttl_seconds": 900,
    "secure": true
  }
}
```

---

## Cookies Set

| Cookie | Prefix | HttpOnly | Secure | SameSite | Max-Age | Path |
|--------|--------|----------|--------|----------|---------|------|
| `__Host-sv_platform_session` | __Host- | Yes | Yes | strict | 900 | / |
| `__Host-sv_platform_user_id` | __Host- | Yes | Yes | strict | 900 | / |
| `__Host-sv_csrf_token` | __Host- | No | Yes | strict | 900 | / |
| `sv_platform_user_email` | - | No | Yes | strict | 900 | / |
| `sv_platform_user_name` | - | No | Yes | strict | 900 | / |
| `sv_platform_role` | - | No | Yes | strict | 900 | / |

**Note**: `__Host-` prefix requires:
- `Secure=true`
- `Path=/`
- No `Domain` attribute

---

## Session TTL

- **Duration**: 900 seconds (15 minutes)
- **Purpose**: Short-lived for security
- **Renewal**: Not supported, create new session

---

## Security Properties

| Property | Implementation |
|----------|----------------|
| Secret comparison | Timing-safe (`crypto.timingSafeEqual`) |
| CSRF token | 32 bytes, hex-encoded |
| Session token | HMAC-SHA256 signed |
| Logging | No secrets in logs |

---

## GET Endpoint (Health Check)

```http
GET /api/auth/staging-bootstrap HTTP/1.1
```

Response:
```json
{
  "endpoint": "/api/auth/staging-bootstrap",
  "enabled": false,
  "secret_configured": true,
  "session_ttl_seconds": 900,
  "usage": "Set STAGING_BOOTSTRAP_ENABLED=true to enable"
}
```

---

## Testing Checklist

- [ ] Disabled → 403 BOOTSTRAP_DISABLED
- [ ] Missing header → 401 MISSING_SECRET
- [ ] Wrong secret → 401 INVALID_SECRET
- [ ] Correct secret → 200 + cookies + csrf_token
- [ ] Cookie has `__Host-` prefix
- [ ] Cookie has `HttpOnly` (session)
- [ ] Cookie has `Secure`
- [ ] Cookie has `SameSite=strict`
- [ ] Cookie has `Max-Age=900`
- [ ] No secrets in response body
- [ ] No secrets in logs
