# SOLVEREIGN V3.3b Security Architecture

**Version**: Draft 1.0
**Author**: Security Review
**Date**: 2026-01-05
**Baseline**: v3.3a-full-approval

---

## Executive Summary

Dieses Dokument definiert die Security-Architektur für V3.3b mit Fokus auf:
- Zero-Trust Authentication
- Defense-in-Depth für Tenant Isolation
- GDPR-konforme Driver Data Protection
- Audit Trail für Compliance

---

## 1. Authentication Layer

### 1.1 Current State (V3.3a)
```
Client → API-Key Header → API → tenant_id lookup → DB
```
**Schwächen**:
- API-Key = Shared Secret (kein Rotation ohne Downtime)
- Kein User-Level Audit (nur tenant-level)
- Kein MFA möglich

### 1.2 Target State (V3.3b)
```
┌─────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION FLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Client  │───▶│   IdP    │───▶│   API    │───▶│    DB    │  │
│  │          │◀───│ (Keycloak│◀───│ Gateway  │◀───│          │  │
│  │          │    │  /Auth0) │    │          │    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                 │
│  1. Client → IdP: Login (username/password + MFA)              │
│  2. IdP → Client: JWT Access Token + Refresh Token             │
│  3. Client → API: Request + Bearer Token                       │
│  4. API → IdP: Token Introspection (optional, cached)          │
│  5. API → DB: Query with tenant_id from JWT claims             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 JWT Claims Structure
```json
{
  "sub": "user-uuid-12345",
  "iss": "https://idp.solvereign.io",
  "aud": "solvereign-api",
  "exp": 1735920000,
  "iat": 1735916400,
  "tenant_id": "tenant-uuid-67890",
  "roles": ["dispatcher", "plan_approver"],
  "permissions": ["forecast:read", "forecast:write", "plan:read", "plan:approve"],
  "mfa_verified": true
}
```

### 1.4 Token Security

| Aspect | Implementation |
|--------|----------------|
| **Access Token TTL** | 15 minutes (short-lived) |
| **Refresh Token TTL** | 8 hours (work shift) |
| **Token Storage** | HttpOnly Cookie (not localStorage!) |
| **Refresh Endpoint** | `/auth/refresh` with Refresh Token Rotation |
| **Revocation** | Token blacklist in Redis (TTL = Access Token TTL) |
| **Signature** | RS256 (asymmetric, public key validation) |

### 1.5 BLINDSPOT: Token Leakage Mitigation

```python
# middleware/security.py

class TokenSecurityMiddleware:
    """
    Prevents token leakage via:
    - Referrer-Policy: no-referrer
    - Cache-Control: no-store
    - X-Content-Type-Options: nosniff
    """

    async def __call__(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent token in URL from leaking via Referrer
        response.headers["Referrer-Policy"] = "no-referrer"

        # Prevent caching of authenticated responses
        if "Authorization" in request.headers:
            response.headers["Cache-Control"] = "no-store, max-age=0"

        # Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        return response
```

---

## 2. Authorization Layer (RBAC)

### 2.1 Role Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                        ROLE HIERARCHY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SUPER_ADMIN (Solvereign Ops)                                   │
│       │                                                         │
│       ▼                                                         │
│  TENANT_ADMIN (Customer IT)                                     │
│       │                                                         │
│       ├──────────────────┬──────────────────┐                   │
│       ▼                  ▼                  ▼                   │
│  DISPATCHER          PLAN_APPROVER      VIEWER                  │
│  (Schichtplaner)     (Betriebsleiter)   (Read-only)            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Permission Matrix

| Permission | VIEWER | DISPATCHER | PLAN_APPROVER | TENANT_ADMIN | SUPER_ADMIN |
|------------|--------|------------|---------------|--------------|-------------|
| `forecast:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `forecast:write` | - | ✓ | ✓ | ✓ | ✓ |
| `plan:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `plan:solve` | - | ✓ | ✓ | ✓ | ✓ |
| `plan:approve` | - | - | ✓ | ✓ | ✓ |
| `plan:lock` | - | - | ✓ | ✓ | ✓ |
| `driver:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `driver:write` | - | - | - | ✓ | ✓ |
| `user:manage` | - | - | - | ✓ | ✓ |
| `tenant:configure` | - | - | - | ✓ | ✓ |
| `system:admin` | - | - | - | - | ✓ |

### 2.3 BLINDSPOT: Permission Escalation Prevention

```python
# api/dependencies/auth.py

class PermissionChecker:
    def __init__(self, required_permissions: List[str]):
        self.required = set(required_permissions)

    async def __call__(self, token: TokenData = Depends(get_current_user)):
        user_permissions = set(token.permissions)

        # Check all required permissions
        if not self.required.issubset(user_permissions):
            missing = self.required - user_permissions

            # AUDIT: Log permission denial
            await audit_log(
                event="PERMISSION_DENIED",
                user_id=token.sub,
                tenant_id=token.tenant_id,
                requested=list(self.required),
                missing=list(missing),
                ip=get_client_ip()
            )

            raise HTTPException(
                status_code=403,
                detail={"error": "FORBIDDEN", "missing_permissions": list(missing)}
            )

        # BLINDSPOT: Prevent cross-tenant access even with valid permissions
        if token.tenant_id != request.state.target_tenant_id:
            await audit_log(
                event="CROSS_TENANT_ATTEMPT",
                user_id=token.sub,
                source_tenant=token.tenant_id,
                target_tenant=request.state.target_tenant_id,
                severity="CRITICAL"
            )
            raise HTTPException(status_code=403, detail="Cross-tenant access denied")

        return token

# Usage
@router.post("/plans/{plan_id}/lock")
async def lock_plan(
    plan_id: int,
    auth: TokenData = Depends(PermissionChecker(["plan:lock"]))
):
    ...
```

---

## 3. Data Protection Layer

### 3.1 Row-Level Security (RLS)

```sql
-- Enable RLS on all tables
ALTER TABLE forecast_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Create policy: Users can only see their tenant's data
CREATE POLICY tenant_isolation ON forecast_versions
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation ON plan_versions
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation ON drivers
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- BLINDSPOT: Audit log readable by tenant, but IMMUTABLE
CREATE POLICY audit_tenant_read ON audit_log
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- Prevent any modification of audit_log (append-only)
CREATE POLICY audit_no_update ON audit_log
    FOR UPDATE
    USING (false);

CREATE POLICY audit_no_delete ON audit_log
    FOR DELETE
    USING (false);
```

### 3.2 BLINDSPOT: RLS Bypass Prevention

```python
# db/connection.py

class SecureConnection:
    """
    Connection wrapper that ALWAYS sets tenant context.
    Prevents accidental RLS bypass.
    """

    async def execute(self, query: str, params: tuple, tenant_id: str):
        async with self.pool.acquire() as conn:
            # CRITICAL: Set tenant context BEFORE every query
            await conn.execute(
                "SET app.current_tenant_id = $1",
                tenant_id
            )

            # BLINDSPOT: Prevent SET ROLE or other privilege escalation
            if self._contains_dangerous_sql(query):
                raise SecurityError("Dangerous SQL pattern detected")

            return await conn.execute(query, *params)

    def _contains_dangerous_sql(self, query: str) -> bool:
        """Detect SQL injection attempts to bypass RLS."""
        dangerous_patterns = [
            r"SET\s+ROLE",
            r"SET\s+SESSION\s+AUTHORIZATION",
            r"RESET\s+ROLE",
            r"current_setting\s*\(",  # Prevent reading other tenant IDs
            r"pg_catalog\.",           # Prevent system catalog access
            r"information_schema\.",   # Prevent schema enumeration
        ]
        query_upper = query.upper()
        return any(re.search(p, query_upper, re.IGNORECASE) for p in dangerous_patterns)
```

### 3.3 Driver Data Protection (GDPR)

```sql
-- Encryption at rest for PII
CREATE TABLE drivers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),

    -- PII: Encrypted at application level
    name_encrypted BYTEA NOT NULL,           -- AES-256-GCM
    email_encrypted BYTEA,                   -- AES-256-GCM
    phone_encrypted BYTEA,                   -- AES-256-GCM

    -- Non-PII: Plaintext for queries
    employee_id VARCHAR(50),                 -- Internal ID only
    max_weekly_hours FLOAT DEFAULT 55,
    qualifications VARCHAR[] DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'ACTIVE',

    -- GDPR: Consent and retention
    consent_given_at TIMESTAMPTZ,
    consent_version VARCHAR(20),
    data_retention_until DATE,               -- Auto-delete after this

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,

    -- RLS
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- GDPR: Auto-delete expired driver data
CREATE OR REPLACE FUNCTION cleanup_expired_driver_data()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM drivers
    WHERE data_retention_until < CURRENT_DATE
    RETURNING COUNT(*) INTO deleted_count;

    -- Audit the deletion
    INSERT INTO audit_log (check_name, status, details_json, tenant_id)
    SELECT
        'GDPR_AUTO_DELETE',
        'COMPLETED',
        jsonb_build_object('deleted_count', deleted_count),
        tenant_id
    FROM (SELECT DISTINCT tenant_id FROM drivers WHERE data_retention_until < CURRENT_DATE) t;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
```

### 3.4 BLINDSPOT: Encryption Key Management

```python
# security/encryption.py

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os

class DriverDataEncryption:
    """
    AES-256-GCM encryption for driver PII.

    BLINDSPOTS ADDRESSED:
    - Key rotation without downtime
    - Key derivation from master secret
    - Nonce uniqueness guarantee
    - AAD for context binding
    """

    def __init__(self, master_key: bytes, key_version: int = 1):
        self.key_version = key_version
        self.key = self._derive_key(master_key, key_version)
        self.aesgcm = AESGCM(self.key)

    def _derive_key(self, master: bytes, version: int) -> bytes:
        """Derive versioned key from master secret."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=f"solvereign-driver-v{version}".encode(),
            iterations=100_000,
        )
        return kdf.derive(master)

    def encrypt(self, plaintext: str, tenant_id: str, driver_id: str) -> bytes:
        """
        Encrypt with AAD (Additional Authenticated Data).
        AAD binds ciphertext to specific tenant+driver.
        """
        nonce = os.urandom(12)  # 96-bit nonce, unique per encryption
        aad = f"{tenant_id}:{driver_id}".encode()

        ciphertext = self.aesgcm.encrypt(
            nonce,
            plaintext.encode(),
            aad
        )

        # Format: version (1 byte) + nonce (12 bytes) + ciphertext
        return bytes([self.key_version]) + nonce + ciphertext

    def decrypt(self, encrypted: bytes, tenant_id: str, driver_id: str) -> str:
        """
        Decrypt with AAD verification.
        BLINDSPOT: Prevents ciphertext from being copied to different tenant/driver.
        """
        version = encrypted[0]
        nonce = encrypted[1:13]
        ciphertext = encrypted[13:]
        aad = f"{tenant_id}:{driver_id}".encode()

        # Use correct key version for decryption
        if version != self.key_version:
            old_key = self._derive_key(self.master_key, version)
            aesgcm = AESGCM(old_key)
        else:
            aesgcm = self.aesgcm

        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
        return plaintext.decode()
```

---

## 4. Audit & Monitoring

### 4.1 Security Event Categories

| Category | Events | Severity |
|----------|--------|----------|
| **AUTH** | login, logout, token_refresh, mfa_challenge | INFO |
| **AUTH_FAIL** | invalid_credentials, token_expired, mfa_failed | WARNING |
| **AUTHZ** | permission_denied, cross_tenant_attempt | WARNING |
| **AUTHZ_CRITICAL** | privilege_escalation_attempt, rls_bypass_attempt | CRITICAL |
| **DATA** | driver_pii_access, export_initiated | INFO |
| **DATA_CRITICAL** | bulk_export, gdpr_request | CRITICAL |
| **SYSTEM** | config_change, key_rotation, user_created | INFO |

### 4.2 BLINDSPOT: Audit Log Integrity

```sql
-- Append-only audit log with hash chain for tamper detection
CREATE TABLE security_audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    tenant_id UUID NOT NULL,
    user_id UUID,
    event_category VARCHAR(50) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    ip_address INET,
    user_agent TEXT,
    details_json JSONB,

    -- Hash chain for integrity
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,

    -- Constraints
    CONSTRAINT valid_severity CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL'))
);

-- BLINDSPOT: Prevent any modification
ALTER TABLE security_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_insert_only ON security_audit_log
    FOR INSERT
    WITH CHECK (true);

CREATE POLICY audit_select_own_tenant ON security_audit_log
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- No UPDATE or DELETE policies = immutable

-- Hash chain computation trigger
CREATE OR REPLACE FUNCTION compute_audit_hash()
RETURNS TRIGGER AS $$
BEGIN
    -- Get previous hash
    SELECT current_hash INTO NEW.previous_hash
    FROM security_audit_log
    ORDER BY id DESC
    LIMIT 1;

    -- Compute current hash (includes previous for chain)
    NEW.current_hash = encode(
        sha256(
            (COALESCE(NEW.previous_hash, 'GENESIS') ||
             NEW.timestamp::TEXT ||
             NEW.tenant_id::TEXT ||
             NEW.event_type ||
             COALESCE(NEW.details_json::TEXT, ''))::BYTEA
        ),
        'hex'
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_hash_trigger
    BEFORE INSERT ON security_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION compute_audit_hash();
```

---

## 5. Network & Infrastructure Security

### 5.1 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     NETWORK ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INTERNET                                                       │
│      │                                                          │
│      ▼                                                          │
│  ┌──────────┐                                                   │
│  │ WAF/CDN  │  ← Rate limiting, DDoS protection                │
│  │(Cloudflare)│                                                  │
│  └────┬─────┘                                                   │
│       │ HTTPS only (TLS 1.3)                                    │
│       ▼                                                          │
│  ┌──────────┐                                                   │
│  │  Nginx   │  ← TLS termination, request filtering            │
│  │ Ingress  │                                                   │
│  └────┬─────┘                                                   │
│       │ Internal HTTPS                                          │
│       ▼                                                          │
│  ┌──────────────────────────────────────┐                       │
│  │           PRIVATE NETWORK            │                       │
│  │  ┌──────────┐    ┌──────────┐        │                       │
│  │  │   API    │───▶│   IdP    │        │                       │
│  │  │ (FastAPI)│    │(Keycloak)│        │                       │
│  │  └────┬─────┘    └──────────┘        │                       │
│  │       │                              │                       │
│  │       ▼                              │                       │
│  │  ┌──────────┐    ┌──────────┐        │                       │
│  │  │ Postgres │    │  Redis   │        │                       │
│  │  │  (RLS)   │    │ (Cache)  │        │                       │
│  │  └──────────┘    └──────────┘        │                       │
│  └──────────────────────────────────────┘                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Rate Limiting

```python
# middleware/rate_limit.py

from fastapi import Request
import redis.asyncio as redis

class RateLimiter:
    """
    Multi-level rate limiting.

    BLINDSPOTS ADDRESSED:
    - Per-tenant limits (prevent one tenant from DoS'ing others)
    - Per-user limits (prevent abuse within tenant)
    - Per-IP limits (prevent brute force)
    - Endpoint-specific limits (expensive operations)
    """

    LIMITS = {
        # Default: 1000 req/min per tenant
        "default": {"requests": 1000, "window": 60},

        # Auth endpoints: 10 req/min per IP (brute force protection)
        "/auth/login": {"requests": 10, "window": 60, "by": "ip"},
        "/auth/refresh": {"requests": 30, "window": 60, "by": "user"},

        # Expensive operations: 10 req/min per tenant
        "/api/v1/plans/*/solve": {"requests": 10, "window": 60},
        "/api/v1/forecasts/ingest": {"requests": 20, "window": 60},

        # Export: 5 req/hour (data exfiltration prevention)
        "/api/v1/export/*": {"requests": 5, "window": 3600},
    }

    async def check(self, request: Request, tenant_id: str, user_id: str) -> bool:
        path = request.url.path
        limit = self._get_limit(path)

        key = self._build_key(path, tenant_id, user_id, request.client.host, limit)

        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, limit["window"])

        if current > limit["requests"]:
            # AUDIT: Log rate limit hit
            await audit_log(
                event="RATE_LIMIT_EXCEEDED",
                tenant_id=tenant_id,
                user_id=user_id,
                path=path,
                ip=request.client.host,
                current_count=current,
                limit=limit["requests"]
            )
            return False

        return True
```

---

## 6. Secrets Management

### 6.1 Secret Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                     SECRETS HIERARCHY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐                                           │
│  │   VAULT / KMS    │  ← Master secrets (AWS KMS, HashiCorp)   │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │  Derived Keys    │  ← Per-purpose keys (PII, API signing)   │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │ Runtime Secrets  │  ← Environment variables (rotated)       │
│  └──────────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 BLINDSPOT: Secret Rotation

```python
# config/secrets.py

class SecretManager:
    """
    Secrets with automatic rotation support.

    BLINDSPOTS ADDRESSED:
    - Dual-key overlap during rotation
    - Graceful degradation if KMS unavailable
    - No secrets in logs/errors
    """

    def __init__(self):
        self._secrets_cache = {}
        self._rotation_lock = asyncio.Lock()

    async def get_db_password(self) -> str:
        """Get DB password, never log it."""
        return await self._get_secret("DB_PASSWORD")

    async def get_jwt_signing_keys(self) -> Tuple[str, str]:
        """
        Return (current_key, previous_key) for rotation overlap.
        During rotation, both keys are valid for verification.
        """
        current = await self._get_secret("JWT_SIGNING_KEY")
        previous = await self._get_secret("JWT_SIGNING_KEY_PREVIOUS", default=None)
        return current, previous

    async def rotate_key(self, key_name: str, new_value: str):
        """
        Rotate key with overlap period.
        1. Move current to previous
        2. Set new as current
        3. After TTL, delete previous
        """
        async with self._rotation_lock:
            current = await self._get_secret(key_name)
            await self._set_secret(f"{key_name}_PREVIOUS", current)
            await self._set_secret(key_name, new_value)

            # Schedule previous key deletion after overlap period
            await self._schedule_deletion(f"{key_name}_PREVIOUS", delay_hours=24)

    def __repr__(self):
        """NEVER expose secrets in repr/str."""
        return "SecretManager(***)"
```

---

## 7. Input Validation & Sanitization

### 7.1 BLINDSPOT: Deep Input Validation

```python
# api/validators.py

from pydantic import BaseModel, Field, validator
import re

class ForecastIngestRequest(BaseModel):
    """
    Strict input validation for forecast ingestion.

    BLINDSPOTS ADDRESSED:
    - SQL injection in raw_text
    - XSS in notes field
    - Path traversal in source
    - Unicode normalization attacks
    """

    raw_text: str = Field(..., min_length=1, max_length=100_000)
    source: str = Field(..., regex=r"^[a-zA-Z0-9_-]+$", max_length=50)
    notes: Optional[str] = Field(None, max_length=1000)

    @validator("raw_text")
    def sanitize_raw_text(cls, v):
        # Normalize Unicode (prevent homograph attacks)
        import unicodedata
        v = unicodedata.normalize("NFKC", v)

        # Remove null bytes (prevent truncation attacks)
        v = v.replace("\x00", "")

        # Check for suspicious patterns
        suspicious = [
            r"<script",      # XSS
            r"javascript:",  # XSS
            r"--",           # SQL comment
            r";.*DROP",      # SQL injection
            r"UNION\s+SELECT", # SQL injection
        ]
        for pattern in suspicious:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError(f"Suspicious pattern detected: {pattern}")

        return v

    @validator("notes")
    def sanitize_notes(cls, v):
        if v is None:
            return v

        # HTML escape
        import html
        v = html.escape(v)

        # Remove control characters (except newlines)
        v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v)

        return v
```

---

## 8. Implementation Checklist

### Phase 1: Authentication (Week 1-2)
- [ ] Keycloak/Auth0 integration
- [ ] JWT validation middleware
- [ ] Token refresh endpoint
- [ ] Token blacklist (Redis)
- [ ] Security headers middleware
- [ ] Rate limiting middleware

### Phase 2: Authorization (Week 2-3)
- [ ] Role definitions in IdP
- [ ] Permission checker dependency
- [ ] Cross-tenant prevention
- [ ] Endpoint protection decorators
- [ ] Admin override audit

### Phase 3: Data Protection (Week 3-4)
- [ ] RLS policies on all tables
- [ ] RLS bypass prevention
- [ ] PII encryption module
- [ ] Key rotation procedure
- [ ] GDPR auto-deletion job

### Phase 4: Audit & Monitoring (Week 4)
- [ ] Security audit log table
- [ ] Hash chain integrity
- [ ] Alerting rules (CRITICAL events)
- [ ] Grafana security dashboard
- [ ] Penetration test scheduling

---

## 9. Threat Model Summary

| Threat | Likelihood | Impact | Mitigation | Status |
|--------|------------|--------|------------|--------|
| Credential theft | Medium | High | MFA, short-lived tokens | PLANNED |
| Cross-tenant data access | Low | Critical | RLS + API-layer checks | PLANNED |
| SQL injection | Low | Critical | Parameterized queries, input validation | EXISTING |
| Token replay | Low | Medium | Short TTL, blacklist | PLANNED |
| PII leakage | Medium | High | Encryption, access logging | PLANNED |
| Privilege escalation | Low | Critical | RBAC, audit logging | PLANNED |
| DoS | Medium | Medium | Rate limiting, WAF | PLANNED |
| Insider threat | Low | High | Audit trail, least privilege | PLANNED |

---

## 10. Compliance Mapping

| Requirement | GDPR | SOC2 | Implementation |
|-------------|------|------|----------------|
| Data encryption at rest | Art. 32 | CC6.1 | AES-256-GCM |
| Access control | Art. 25 | CC6.3 | RBAC + RLS |
| Audit logging | Art. 30 | CC7.2 | Immutable audit log |
| Data retention | Art. 17 | CC6.5 | Auto-deletion job |
| Breach notification | Art. 33 | CC7.3 | Alerting on CRITICAL |
| Right to erasure | Art. 17 | - | Driver deletion API |

---

*Document Status: DRAFT*
*Review Required: Security Team, DPO*
*Next Review: Before V3.3b implementation start*
