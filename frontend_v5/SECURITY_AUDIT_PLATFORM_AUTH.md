# SOLVEREIGN Platform Auth - Security Audit Evidence

---

## Audit Metadata

| Field | Value |
|-------|-------|
| **Repository** | `shift-optimizer` |
| **Branch** | `main` |
| **Commit SHA** | `e88374d448ed6a3c9cff7d04b19075373f35c064` |
| **Audit Date** | 2026-01-07 |
| **Prepared By** | Claude Code Security Review |
| **Scope** | Platform Auth BFF Layer (frontend_v5) |

---

## Timeline Definitions

| Milestone | Definition | Target |
|-----------|------------|--------|
| **Before deploy** | Before production deployment to Azure/staging | Infrastructure ready |
| **Before pilot** | Before Wien 46-vehicle routing pilot with MediaMarkt | Pilot week start |
| **Next minor** | Next planned feature release | v3.4 or equivalent |
| **Next CI update** | Next CI/CD pipeline modification | As scheduled |

---

## Verdict

> **GO ✅** (Production-hardened, E2E verified 5/5)
>
> **IMPORTANT:** GO applies to **Platform Auth BFF layer only**; backend verification (idempotency deduplication, HMAC signature verification, RLS enforcement) is a **separate audit**.

---

## 1. Environment Assumptions

| Assumption | Required Configuration |
|------------|------------------------|
| **HTTPS Termination** | TLS terminates at load balancer or ingress; `__Host-` cookies require `Secure` flag |
| **Trusted Proxy List** | `TRUSTED_PROXIES` must include real Ingress/LB IPs for X-Forwarded-For to work correctly |
| **NODE_ENV Semantics** | `production` = dev-login returns 404; `development` = dev-login accessible from allowlist |
| **Secret Management** | `SOLVEREIGN_SESSION_SECRET` must be set via secure secret store (not in code/repo) |
| **Cookie Domain** | `__Host-` prefix enforces no Domain attribute; cookies bound to exact origin |

---

## 2. Hard Requirements (Definition of Done)

| # | Gate | Status |
|---|------|--------|
| 1 | Signed token verify (HMAC-SHA256) + expiry check + timing-safe compare | ✅ |
| 2 | `__Host-` cookies for session + CSRF (Secure, Path=/, no Domain) | ✅ |
| 3 | CSRF required on all write operations (POST/PUT/PATCH/DELETE) | ✅ |
| 4 | Idempotency key required + forwarded to backend (all write methods) | ✅ |
| 5 | dev-login prod-block (404) + proxy-safe IP allowlist | ✅ |
| 6 | E2E security tests 5/5 pass | ✅ |

---

## 3. E2E Security Test Evidence

```
Running 5 tests using 5 workers
  5 passed (896ms)
```

### Negative Test Evidence

| Test | What It Proves | Expected Failure Mode |
|------|----------------|----------------------|
| **dev-login validates input** | Domain allowlist enforced; IP restrictions work | `401 UNAUTHORIZED` for `hacker@evil.com`; `404` in production mode |
| **write ops require CSRF + idempotency** | Missing headers blocked before processing | `400 CSRF_VALIDATION_FAILED` without X-CSRF-Token; `400 MISSING_IDEMPOTENCY_KEY` without X-Idempotency-Key |
| **invalid session token rejected** | Signature verification catches tampering | `401` for malformed token, wrong signature, or expired timestamp |
| **viewer cannot admin ops** | Role-based access control works | `403 FORBIDDEN` when viewer tries POST to admin endpoint |
| **cookies have security attrs** | Browser enforces cookie security | Session cookie: `Secure; HttpOnly; SameSite=Strict`; CSRF: `Secure; SameSite=Strict` (not HttpOnly) |

---

## 4. Security Controls Summary

### 4.1 Session Token Architecture

| Property | Implementation |
|----------|----------------|
| Format | `{base64(userId:role:expiry)}.{HMAC-SHA256}` |
| Signing | HMAC-SHA256 with `SOLVEREIGN_SESSION_SECRET` |
| TTL | 4 hours (max 8 hours) |
| Clock Skew | 30 seconds tolerance |
| Rotation | Supports `SOLVEREIGN_SESSION_SECRET_PREV` during rotation |
| Comparison | Timing-safe (`crypto.timingSafeEqual`) |

### 4.2 Cookie Security Matrix

| Cookie | Prefix | HttpOnly | Secure | SameSite | Trust Level |
|--------|--------|----------|--------|----------|-------------|
| `__Host-sv_platform_session` | ✅ | ✅ | ✅ | Strict | **AUTH** |
| `__Host-sv_platform_user_id` | ✅ | ✅ | ✅ | Strict | **AUTH** |
| `__Host-sv_csrf_token` | ✅ | ❌ | ✅ | Strict | **CSRF** |
| `sv_platform_user_email` | ❌ | ❌ | ⚡ | Strict | Display only |
| `sv_platform_user_name` | ❌ | ❌ | ⚡ | Strict | Display only |
| `sv_platform_role` | ❌ | ❌ | ⚡ | Strict | Display only |

### 4.3 IP Allowlist (Proxy-Safe)

```typescript
const TRUSTED_PROXIES = [
  '127.0.0.1', '::1',
  '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
];
// Algorithm: Walk X-Forwarded-For backwards, return first non-proxy IP
```

### 4.4 Write Operation Guards

| Guard | Header | Applies To | Failure Code |
|-------|--------|------------|--------------|
| CSRF | `X-CSRF-Token` | POST, PUT, PATCH, DELETE | `400 CSRF_VALIDATION_FAILED` |
| Idempotency | `X-Idempotency-Key` | POST, PUT, PATCH, DELETE | `400 MISSING_IDEMPOTENCY_KEY` |

---

## 5. Threat Model

| Threat | Mitigation | Verified |
|--------|------------|----------|
| Cookie spoofing | HMAC signature verification | ✅ |
| Role escalation | Role cookie display-only; auth uses signed token | ✅ |
| CSRF attacks | Double-submit pattern with `__Host-` cookie | ✅ |
| XSS token theft | HttpOnly on session cookie | ✅ |
| Subdomain attacks | `__Host-` prefix prevents Domain attribute | ✅ |
| Timing attacks | `crypto.timingSafeEqual` for signature | ✅ |
| Replay attacks | Nonce + timestamp in HMAC signature | ⚠️ Backend |
| XFF spoofing | Only trust X-Forwarded-For from trusted proxies | ✅ |
| Legacy dev-session | Requires `ALLOW_LEGACY_DEV_SESSION=true` + non-prod | ✅ |

---

## 6. Residual Risk / Accepted Risk

| Risk ID | Risk Statement | Severity | Mitigation | Status | Owner | Deadline |
|---------|----------------|----------|------------|--------|-------|----------|
| **R1** | Write replay may create duplicate side effects unless backend deduplicates by idempotency key. BFF forwards key but does not enforce dedupe. | Medium | Backend audit + dedupe table with unique index on `idempotency_key` | **ACCEPTED** | Backend Eng | Before pilot |
| **R2** | Backend must verify platform session token / HMAC independently. BFF-only verification is insufficient if backend is accessed directly (e.g., internal network). | Medium | Backend audit of `internal_signature.py` to confirm HMAC verification | **ACCEPTED** | Backend Eng | Before pilot |
| **R3** | If tokens are stolen, replay is possible until expiry (4h). Mitigation is short TTL + secret rotation. Backend should enforce additional controls (nonce tracking in `core.used_signatures`) if high-value operations are involved. | Medium | Verify `core.used_signatures` table usage; consider shorter TTL for sensitive ops | **ACCEPTED** | Backend Eng | Before pilot |
| **R4** | `TRUSTED_PROXIES` contains only private CIDRs. Production deployment may have different LB/Ingress IPs that must be added. | Low | Update with real Ingress/LB IPs before deploy; add logging for ignored XFF | **ACCEPTED** | Platform Eng | Before deploy |

---

## 7. P2 Follow-ups (Non-Blocking Hygiene)

### P2-1: TRUSTED_PROXIES Deployment-Real

| Field | Value |
|-------|-------|
| **Owner** | Platform Eng |
| **Target** | Before deploy |
| **Evidence** | `TRUSTED_PROXIES` contains real Ingress/LB IPs; logging shows XFF correctly parsed |

**Action:**
1. Add real Ingress/LB IPs or ranges for production
2. Add logging when X-Forwarded-For ignored (untrusted peer)
3. Document expected proxy chain per environment

---

### P2-2: Base64URL Instead of Base64

| Field | Value |
|-------|-------|
| **Owner** | Platform Eng |
| **Target** | Next minor |
| **Evidence** | Token payload uses Base64URL encoding (no `+`, `/`, `=`) |

**Action:**
1. Switch to Base64URL encoding (RFC 4648)
2. Remove or control padding

---

### P2-3: Delimiter Security

| Field | Value |
|-------|-------|
| **Owner** | Platform Eng |
| **Target** | Next minor |
| **Evidence** | userId/role validation rejects `:` character OR JSON payload used |

**Action (Minimal):**
- Validate: `userId` and `role` must not contain `:`

**Action (Better):**
- Switch to JSON: `base64url(JSON.stringify({userId, role, exp}))`

---

### P2-4: Secret Strength in CI

| Field | Value |
|-------|-------|
| **Owner** | DevOps |
| **Target** | Next CI update |
| **Evidence** | CI fails if secret < 32 chars; warns if `_PREV` set > 1 week |

**Action:**
```bash
# CI check
[ -z "$SOLVEREIGN_SESSION_SECRET" ] && exit 1
[ ${#SOLVEREIGN_SESSION_SECRET} -lt 32 ] && exit 1
[ -n "$SOLVEREIGN_SESSION_SECRET_PREV" ] && echo "WARNING: Rotation in progress"
```

---

### P2-5: Session Revocation Runbook

| Field | Value |
|-------|-------|
| **Owner** | Operations |
| **Target** | Before pilot |
| **Evidence** | Runbook exists in ops docs; tested in staging |

**Runbook:**
```markdown
## Emergency Session Revocation

1. Generate new secret: `openssl rand -base64 32`
2. Set as `SOLVEREIGN_SESSION_SECRET`
3. Move old to `SOLVEREIGN_SESSION_SECRET_PREV` (graceful) OR delete (immediate)
4. Deploy - all sessions invalidated within TTL (4h max)
5. After grace period, remove `_PREV`
```

---

## 8. Files Modified

| File | Changes |
|------|---------|
| `lib/platform-rbac.ts` | HMAC signing, timing-safe compare, secret rotation, session validation |
| `app/api/platform/auth/dev-login/route.ts` | Proxy-safe IP, `__Host-` cookies, DELETE protection |
| `lib/platform-api.ts` | Idempotency forwarding for all write methods |
| `e2e/platform-security.spec.ts` | 5 security E2E tests |

---

## 9. Approval Matrix

| Role | Status | Date | Notes |
|------|--------|------|-------|
| Security Review | **GO ✅** | 2026-01-07 | BFF layer only |
| E2E Tests | **5/5 PASS** | 2026-01-07 | All negative tests verified |
| P2 Follow-ups | Documented | 2026-01-07 | Owners + deadlines assigned |
| Residual Risks | **ACCEPTED** | 2026-01-07 | Backend audit required before pilot |

---

## 10. Sign-off

> **GO ✅ applies to Platform Auth BFF layer only.**
>
> Backend verification (idempotency deduplication, HMAC signature verification, RLS enforcement, replay protection) requires **separate backend audit** before pilot.

---

| Role | Name / Entity | Date |
|------|---------------|------|
| **Prepared by** | Claude Code Security Review | 2026-01-07 |
| **Reviewed by** | _(Pending: Tech Lead / Security Owner)_ | _(Pending)_ |
| **Approved by** | _(Pending: Platform Engineering Lead)_ | _(Pending)_ |

---

**Effective for:** Commit `e88374d448ed6a3c9cff7d04b19075373f35c064`

**Document Version:** 1.2

---

## Appendix: Backend Audit Checklist

The backend audit (required before pilot) should use the checklist at:

```
scripts/audit_backend_checklist.js
```

Run with: `node scripts/audit_backend_checklist.js`

This covers:
- B0: Metadata capture
- B1: Direct-backend auth (no BFF bypass)
- B2: Session/token verification
- B3: RBAC server-side
- B4: Idempotency dedupe (DB constraint)
- B5: Idempotency scope (all write methods)
- B6: Tenant isolation
- B7: Audit trail
- B8: Rate limiting
- B9: Evidence bundle

Output should be saved to `SECURITY_AUDIT_BACKEND.md`.
