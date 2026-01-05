# SOLVEREIGN - Microsoft Entra ID Setup for LTS

**Version**: 1.0
**Date**: 2026-01-05
**Audience**: IT Administrators, DevOps

---

## Overview

This document describes how to configure Microsoft Entra ID (Azure AD) authentication for LTS Transport & Logistik GmbH as a production tenant on SOLVEREIGN.

### Architecture

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│   User / Browser    │      │   Microsoft Entra   │      │   SOLVEREIGN API    │
│                     │      │   (Azure AD)        │      │                     │
│  1. Login Request   │─────►│                     │      │                     │
│                     │      │  2. Authenticate    │      │                     │
│                     │◄─────│  3. ID Token        │      │                     │
│                     │      │     (JWT RS256)     │      │                     │
│  4. API Request     │──────┼──────────────────────────►│                     │
│     + Bearer Token  │      │                     │      │  5. Validate JWT    │
│                     │      │                     │      │  6. Map tid → tenant│
│                     │      │                     │      │  7. Check roles     │
│                     │◄─────┼────────────────────────────│  8. Response        │
└─────────────────────┘      └─────────────────────┘      └─────────────────────┘
```

---

## Step 1: Azure AD App Registration

### 1.1 Create API Application

1. Go to Azure Portal > Microsoft Entra ID > App registrations
2. Click "New registration"
3. Configure:
   - **Name**: `SOLVEREIGN API`
   - **Supported account types**: "Accounts in this organizational directory only"
   - **Redirect URI**: Leave empty (API, not interactive)
4. Click "Register"
5. Note the **Application (client) ID**: `{api_client_id}`
6. Note the **Directory (tenant) ID**: `{entra_tenant_id}`

### 1.2 Configure API Expose

1. Go to "Expose an API"
2. Set Application ID URI: `api://solvereign-api` or `https://solvereign.lts-transport.de`
3. Add scopes (optional for M2M):
   - `api://solvereign-api/.default`

### 1.3 Create App Roles

Go to "App roles" > "Create app role" for each role:

| Display Name | Value | Allowed member types | Description |
|--------------|-------|---------------------|-------------|
| Tenant Administrator | `TENANT_ADMIN` | Users/Groups | Full tenant access, user management |
| Planner | `PLANNER` | Users/Groups, Applications | Solve forecasts, view plans |
| Approver | `APPROVER` | Users/Groups | Lock plans for production (human only) |
| Viewer | `VIEWER` | Users/Groups, Applications | Read-only access |

**IMPORTANT**: `APPROVER` role should NOT allow Applications (M2M). This ensures only humans can lock plans.

### 1.4 Configure Token Claims

Go to "Token configuration" > "Add optional claim":

1. Token type: **Access token**
2. Add claims:
   - `email` (or `preferred_username`)
   - `family_name`
   - `given_name`

The following claims are automatic:
- `sub` - User Object ID
- `tid` - Tenant ID (Azure AD Tenant)
- `aud` - Audience
- `iss` - Issuer
- `roles` - App Roles assigned to user

---

## Step 2: Create Automation Client (Optional)

For system-to-system calls (e.g., CI/CD, integrations):

### 2.1 Create Client Application

1. App registrations > "New registration"
2. Configure:
   - **Name**: `SOLVEREIGN Automation`
   - **Supported account types**: "Accounts in this organizational directory only"
3. Click "Register"
4. Note the **Application (client) ID**: `{automation_client_id}`

### 2.2 Create Client Secret

1. Go to "Certificates & secrets"
2. Click "New client secret"
3. Set expiry (recommend 90 days)
4. **Save the secret value immediately** (shown only once)

### 2.3 Assign API Permissions

1. Go to "API permissions"
2. Click "Add a permission"
3. Select "My APIs" > "SOLVEREIGN API"
4. Select "Application permissions"
5. Select roles:
   - `PLANNER` (for solve/repair)
   - `VIEWER` (for read operations)
   - **NOT** `APPROVER` (M2M cannot lock plans)
6. Click "Grant admin consent"

---

## Step 3: Assign Roles to Users

### 3.1 Via Azure Portal

1. Go to Enterprise applications > "SOLVEREIGN API"
2. Go to "Users and groups"
3. Click "Add user/group"
4. Select user and role
5. Click "Assign"

### 3.2 Recommended Role Assignment

| User | Role | Permissions |
|------|------|-------------|
| IT Admin | `TENANT_ADMIN` | Full access |
| Operations Manager | `APPROVER` | Lock plans |
| Dispatchers | `PLANNER` | Solve, repair, view |
| Management | `VIEWER` | Read-only |

---

## Step 4: Register Tenant Mapping in SOLVEREIGN

### 4.1 Run Migration

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME \
  -f backend_py/db/migrations/012_tenant_identities.sql
```

### 4.2 Create Tenant Identity Mapping

```sql
-- First, ensure LTS tenant exists
INSERT INTO tenants (name, api_key_hash, is_active, metadata)
VALUES (
    'lts-transport-001',
    'not_used_with_oidc',
    TRUE,
    '{"tier": "production", "company": "LTS Transport & Logistik GmbH"}'::jsonb
)
ON CONFLICT (name) DO NOTHING;

-- Get the tenant ID
SELECT id FROM tenants WHERE name = 'lts-transport-001';
-- Let's say it returns: 2

-- Register Entra ID mapping
SELECT register_tenant_identity(
    2,                                                              -- tenant_id
    'https://login.microsoftonline.com/{entra_tenant_id}/v2.0',     -- issuer
    '{entra_tenant_id}',                                            -- external_tid
    'entra_id',                                                     -- provider_type
    'LTS Entra ID'                                                  -- display_name
);
```

Replace `{entra_tenant_id}` with your actual Azure AD Tenant ID (UUID format).

### 4.3 Configure Environment Variables

```bash
# OIDC Configuration
SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{entra_tenant_id}/v2.0
SOLVEREIGN_OIDC_AUDIENCE=api://solvereign-api
SOLVEREIGN_OIDC_CLOCK_SKEW_SECONDS=60

# Or for multi-tenant support
SOLVEREIGN_OIDC_ALLOWED_ISSUERS=https://login.microsoftonline.com/*/v2.0

# Entra-specific
SOLVEREIGN_ENTRA_TENANT_ID={entra_tenant_id}

# Auth mode
SOLVEREIGN_AUTH_MODE=OIDC
SOLVEREIGN_ALLOW_HEADER_TENANT_OVERRIDE=false  # MUST be false in production
```

---

## Step 5: Test Authentication

### 5.1 Get Access Token (Interactive)

Use Azure CLI:

```bash
# Login interactively
az login --tenant {entra_tenant_id}

# Get access token for API
az account get-access-token \
  --resource api://solvereign-api \
  --query accessToken \
  --output tsv
```

### 5.2 Get Access Token (M2M)

```bash
curl -X POST \
  https://login.microsoftonline.com/{entra_tenant_id}/oauth2/v2.0/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id={automation_client_id}" \
  -d "client_secret={client_secret}" \
  -d "scope=api://solvereign-api/.default" \
  -d "grant_type=client_credentials"
```

### 5.3 Call SOLVEREIGN API

```bash
# Get plans (requires VIEWER or higher)
curl -X GET https://api.solvereign.io/api/v1/plans \
  -H "Authorization: Bearer {access_token}"

# Lock plan (requires APPROVER - FAILS with M2M token)
curl -X POST https://api.solvereign.io/api/v1/plans/42/lock \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Week 2 release"}'
```

---

## Expected JWT Claims Structure

### User Token (Interactive)

```json
{
  "aud": "api://solvereign-api",
  "iss": "https://login.microsoftonline.com/{entra_tenant_id}/v2.0",
  "sub": "user-object-id-uuid",
  "tid": "{entra_tenant_id}",
  "email": "dispatcher@lts-transport.de",
  "name": "Max Mustermann",
  "roles": ["PLANNER", "APPROVER"],
  "exp": 1735689600,
  "iat": 1735686000
}
```

### App Token (M2M)

```json
{
  "aud": "api://solvereign-api",
  "iss": "https://login.microsoftonline.com/{entra_tenant_id}/v2.0",
  "sub": "service-principal-object-id",
  "tid": "{entra_tenant_id}",
  "azp": "{automation_client_id}",
  "idtyp": "app",
  "roles": ["PLANNER", "VIEWER"],
  "exp": 1735689600,
  "iat": 1735686000
}
```

---

## Security Considerations

### Non-Negotiables

1. **Tenant ID from JWT only**: `tid` claim is the source of truth, NOT client headers
2. **Roles from JWT only**: `roles` claim is the source of truth
3. **M2M cannot lock**: App tokens cannot have APPROVER role
4. **RLS enforced**: `app.current_tenant_id` set per transaction

### Best Practices

1. **Token validation**: Always validate `iss`, `aud`, `exp`, `tid`
2. **JWKS caching**: Keys cached for 1 hour, refreshed on kid mismatch
3. **Clock skew**: 60 seconds tolerance for exp/iat
4. **Audit logging**: All auth attempts logged to security_audit_log

### Error Codes

| Error | HTTP Code | Meaning |
|-------|-----------|---------|
| `MISSING_TID` | 403 | Token missing tid claim |
| `TENANT_NOT_MAPPED` | 403 | No mapping for this Entra tenant |
| `INSUFFICIENT_ROLE` | 403 | User lacks required role |
| `APP_TOKEN_NOT_ALLOWED` | 403 | M2M token tried to lock plan |
| Token expired | 401 | Refresh token needed |
| Invalid signature | 401 | Key rotation or tampering |

---

## Troubleshooting

### "TENANT_NOT_MAPPED" Error

1. Check `tid` in JWT matches registered mapping
2. Verify tenant identity is active:
   ```sql
   SELECT * FROM tenant_identities WHERE external_tid = '{tid}';
   ```
3. Verify tenant is active:
   ```sql
   SELECT * FROM tenants WHERE id = (SELECT tenant_id FROM tenant_identities WHERE external_tid = '{tid}');
   ```

### "INSUFFICIENT_ROLE" Error

1. Check user's App Role assignment in Azure Portal
2. Verify role mapping:
   ```
   Entra Role      → Internal Role
   TENANT_ADMIN    → tenant_admin
   PLANNER         → dispatcher
   APPROVER        → plan_approver
   VIEWER          → viewer
   ```

### "Token expired" Error

- Access tokens are short-lived (default 1 hour)
- Use refresh token to get new access token
- For M2M: request new token with client credentials

### JWKS Fetch Error

1. Check network connectivity to login.microsoftonline.com
2. Verify OIDC_ISSUER is correct
3. Check for proxy/firewall blocking

---

## Activation Checklist (GoLive Day)

Run these checks BEFORE enabling Entra ID authentication for production:

### Automated Checks

```bash
# Set environment variables
export SOLVEREIGN_DATABASE_URL=postgresql://...
export SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{tid}/v2.0
export SOLVEREIGN_OIDC_AUDIENCE=api://solvereign-api
export SOLVEREIGN_ENTRA_TENANT_ID={your-entra-tid}
export SOLVEREIGN_ENVIRONMENT=production

# Run activation checks
python backend_py/tests/activation_checks.py --verbose
```

### Manual Verification Steps

| # | Check | Command/Action | Expected |
|---|-------|----------------|----------|
| 1 | Migration applied | `SELECT * FROM tenant_identities;` | Table exists |
| 2 | Tenant mapping exists | `SELECT * FROM tenant_identities WHERE external_tid = '{tid}';` | 1 row |
| 3 | Issuer matches token | Decode token, check `iss` claim | Exact match |
| 4 | Audience matches token | Decode token, check `aud` claim | Exact match |
| 5 | M2M cannot lock | POST /plans/{id}/lock with app token | 403 APP_TOKEN_NOT_ALLOWED |
| 6 | PLANNER cannot lock | POST /plans/{id}/lock with PLANNER token | 403 INSUFFICIENT_ROLE |
| 7 | APPROVER can lock | POST /plans/{id}/lock with APPROVER token | 200 LOCKED |
| 8 | RLS enforced | Two requests, different tenants | No cross-tenant data |

### Critical Sequence

```
1. Apply migration 012_tenant_identities.sql
2. Register tenant identity mapping (with correct tenant_id!)
3. Set environment variables (OIDC_ISSUER, OIDC_AUDIENCE, etc.)
4. Restart API
5. Run activation_checks.py
6. Test with PLANNER token (should work for /solve)
7. Test with APPROVER token (should work for /lock)
8. Test with M2M token (should fail for /lock)
9. Enable production traffic
```

### Known Pitfalls

1. **Tenant Name Mismatch**: Check `SELECT id, name FROM tenants;` before registration
2. **Issuer v1 vs v2**: Ensure issuer includes `/v2.0` for v2.0 tokens
3. **Audience Format**: May be `api://...` or a GUID depending on Entra config
4. **RLS Connection Leak**: Always use `db.tenant_connection(tenant_id)` not `db.connection()`

---

## Token Lifetime & Refresh

### Access Token Lifetime

Entra ID access tokens typically expire in **1 hour** (configurable 5 min to 24 hours).

| Scenario | Impact | Solution |
|----------|--------|----------|
| API-only (M2M) | Token expires during long solve | Request new token before expiry |
| UI (PKCE) | User session ends | Implement refresh token flow |
| CLI/Scripts | Token expires mid-batch | Cache refresh token, auto-renew |

### Refresh Token Flow for UI

```javascript
// MSAL.js example for browser
const msalConfig = {
  auth: {
    clientId: "{api_client_id}",
    authority: "https://login.microsoftonline.com/{entra_tenant_id}",
    redirectUri: "http://localhost:3000",
  },
  cache: {
    cacheLocation: "sessionStorage",  // or "localStorage"
  }
};

// Silent token refresh
async function getAccessToken() {
  const accounts = msalInstance.getAllAccounts();
  if (accounts.length > 0) {
    const request = {
      scopes: ["api://solvereign-api/.default"],
      account: accounts[0],
    };
    try {
      const response = await msalInstance.acquireTokenSilent(request);
      return response.accessToken;
    } catch (error) {
      // Fallback to interactive login
      return msalInstance.acquireTokenPopup(request);
    }
  }
}
```

### API Token Renewal for Automation

```bash
#!/bin/bash
# Renew token before expiry (run every 45 minutes via cron)

TOKEN_RESPONSE=$(curl -s -X POST \
  https://login.microsoftonline.com/{entra_tenant_id}/oauth2/v2.0/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id={automation_client_id}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "scope=api://solvereign-api/.default" \
  -d "grant_type=client_credentials")

ACCESS_TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.access_token')
echo $ACCESS_TOKEN > /var/run/solvereign/access_token
```

### User Communication

Dispatchers should know:
- Session lasts ~1 hour before re-login required
- "Token expired" error means: refresh page or re-login
- Long-running operations (batch solve) should complete within token lifetime

---

## Tenant Identity Rotation

### When to Rotate

- LTS migrates to new Azure AD tenant (M&A, restructuring)
- Issuer URL changes (v1→v2 migration)
- Security incident (compromised tenant)

### Rotation Procedure

**1. Add New Identity (No Downtime)**

```sql
-- Add new Entra mapping (don't remove old yet)
SELECT register_tenant_identity(
    (SELECT id FROM tenants WHERE name = 'lts-transport-001'),
    'https://login.microsoftonline.com/{NEW_ENTRA_TID}/v2.0',
    '{NEW_ENTRA_TID}',
    'entra_id',
    'LTS Entra ID (new)'
);

-- Verify both work
SELECT * FROM tenant_identities WHERE tenant_id = (
    SELECT id FROM tenants WHERE name = 'lts-transport-001'
);
```

**2. Update Environment (If Issuer Changed)**

```bash
# Update issuer to new value
SOLVEREIGN_OIDC_ISSUER=https://login.microsoftonline.com/{NEW_ENTRA_TID}/v2.0

# Or add to allowed issuers list (multi-tenant)
SOLVEREIGN_OIDC_ALLOWED_ISSUERS=https://login.microsoftonline.com/*/v2.0
```

**3. Transition Period**

- Both old and new Entra tids work (dual-active)
- Users gradually migrate to new tenant
- Monitor: `SELECT external_tid, count(*) FROM auth_log GROUP BY 1`

**4. Deactivate Old Identity**

```sql
-- After all users migrated (check logs first!)
UPDATE tenant_identities
SET is_active = FALSE, updated_at = NOW()
WHERE external_tid = '{OLD_ENTRA_TID}';
```

**5. Remove Old Identity (Optional)**

```sql
-- After 30+ days with no old-tid activity
DELETE FROM tenant_identities
WHERE external_tid = '{OLD_ENTRA_TID}'
  AND is_active = FALSE;
```

### Emergency Revocation

If old Entra tenant is compromised:

```sql
-- Immediate deactivation
UPDATE tenant_identities
SET is_active = FALSE
WHERE external_tid = '{COMPROMISED_TID}';

-- Force all sessions to re-authenticate
-- (Entra side: Conditional Access → Require MFA, or revoke sessions)
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.2 | 2026-01-05 | Added token refresh, identity rotation docs |
| 1.1 | 2026-01-05 | Added activation checklist |
| 1.0 | 2026-01-05 | Initial release |

---

*Document Owner: SOLVEREIGN Security Team*
*Next Review: 2026-04-05*
