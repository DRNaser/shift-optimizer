# Break-Glass Emergency Access Procedure

**System**: SOLVEREIGN V3.7
**Purpose**: Emergency elevated access for incident response
**Classification**: INTERNAL ONLY - Handle with care

---

## 1) Overview

Break-glass access provides **time-limited elevated privileges** for emergency incident response. This procedure is audited and requires justification.

**When to Use**:
- S0/S1 incidents requiring database access
- Security events requiring immediate investigation
- Production issues not resolvable through normal channels

**When NOT to Use**:
- Routine debugging (use staging)
- Feature development
- Curiosity or "checking things"

---

## 2) Roles and Authorization

### 2.1 Who Can Request Break-Glass

| Role | Authorization Level |
|------|---------------------|
| **Ops On-Call** | Can request for active incidents |
| **Platform Eng Lead** | Can request + approve |
| **Security Lead** | Can request + approve + revoke |
| **CTO** | Full access |

### 2.2 Who Can Grant Access

| Approver | Conditions |
|----------|------------|
| **Security Lead** | Primary approver |
| **Platform Eng Lead** | If Security Lead unavailable |
| **CTO** | Escalation / override |

### 2.3 Access Tiers

| Tier | Role | Capabilities | Max Duration |
|------|------|--------------|--------------|
| **Tier 1** | `solvereign_readonly` | SELECT only | 4 hours |
| **Tier 2** | `solvereign_platform` | SELECT + platform admin | 2 hours |
| **Tier 3** | `solvereign_admin` | Full DB access | 1 hour |

---

## 3) Break-Glass Procedure

### Step 1: Document Justification

Before requesting access:

```markdown
## Break-Glass Request

**Incident ID**: [INC-YYYY-NNNN]
**Severity**: [S0/S1/S2]
**Requestor**: [Name]
**Timestamp**: [ISO timestamp]

### Justification
[Why elevated access is needed - be specific]

### Scope
- Tables/schemas needed: [list]
- Operations required: [SELECT/UPDATE/etc]
- Estimated duration: [X hours]

### Alternatives Considered
- [ ] Tried staging environment
- [ ] Checked audit logs
- [ ] Consulted team

### Risk Assessment
[What could go wrong with elevated access]
```

### Step 2: Request Approval

**Slack Channel**: #solvereign-security-requests

```
@security-lead @platform-eng-lead

BREAK-GLASS REQUEST
-------------------
Incident: INC-2026-0042
Severity: S1
Requestor: [your name]
Access Tier: [1/2/3]
Duration: [X hours]
Justification: [one sentence]

Full details: [link to incident record]
```

### Step 3: Receive Credentials

Approver will provide time-limited credentials via secure channel:

```bash
# Credentials provided via 1Password Emergency Vault or similar
# NEVER via Slack, email, or plain text

# Connection string (time-limited role)
export BREAK_GLASS_DB_URL="postgresql://break_glass_user:TEMP_PASSWORD@host/db"

# Access expires at: [ISO timestamp]
```

### Step 4: Access and Audit Trail

All break-glass sessions are logged. Execute with awareness:

```bash
# Connect with explicit session identifier
psql "$BREAK_GLASS_DB_URL" \
  -c "SET application_name = 'break_glass_INC-2026-0042';"

# All queries will be logged to:
# - PostgreSQL logs (connection + queries)
# - Azure Log Analytics (if configured)
# - security_events table
```

### Step 5: Work and Document

During access:

1. **Log all actions** in incident record
2. **Minimize scope** - only access what's needed
3. **No schema changes** without explicit approval
4. **Export evidence** before making changes

```bash
# Example: Export evidence before fix
psql "$BREAK_GLASS_DB_URL" -c "
  COPY (
    SELECT * FROM core.security_events
    WHERE created_at > NOW() - INTERVAL '24 hours'
  ) TO STDOUT WITH CSV HEADER
" > evidence/security_events_pre_fix.csv

# Example: Make minimal fix
psql "$BREAK_GLASS_DB_URL" -c "
  UPDATE tenants SET is_active = false
  WHERE id = 123
  RETURNING *;
" > evidence/fix_applied.txt
```

### Step 6: Verify and Produce Evidence

After any changes:

```bash
# Run verification
psql "$BREAK_GLASS_DB_URL" -c "SELECT * FROM verify_final_hardening();"

# Generate evidence pack
python scripts/export_evidence_pack.py export \
  --input evidence/incident_INC-2026-0042.json \
  --out evidence/break_glass_evidence_INC-2026-0042.zip
```

### Step 7: Close Access

**Immediately when done** (or at expiry):

1. Disconnect all sessions
2. Notify approver: "Break-glass access complete"
3. Credentials are auto-revoked at expiry

```bash
# Verify access revoked
psql "$BREAK_GLASS_DB_URL" -c "SELECT 1;"
# Expected: connection refused or authentication failed
```

### Step 8: Post-Incident Record

Update incident record with:

```markdown
## Break-Glass Usage Record

**Access Start**: [ISO timestamp]
**Access End**: [ISO timestamp]
**Duration**: [X hours Y minutes]

### Actions Taken
1. [action 1]
2. [action 2]

### Evidence Artifacts
- evidence/security_events_pre_fix.csv
- evidence/fix_applied.txt
- evidence/break_glass_evidence_INC-2026-0042.zip

### Verification
- verify_final_hardening(): PASS
- Health check: PASS

### Lessons Learned
[What could be improved]
```

---

## 4) Credential Management

### 4.1 Creating Time-Limited Credentials

**Security Lead Only**:

```bash
# Create time-limited role (expires in 2 hours)
psql $ADMIN_DB_URL << 'EOF'
DO $$
DECLARE
    v_password TEXT := encode(gen_random_bytes(24), 'base64');
    v_expires TIMESTAMPTZ := NOW() + INTERVAL '2 hours';
BEGIN
    -- Create or update break-glass user
    EXECUTE format(
        'CREATE ROLE break_glass_user LOGIN PASSWORD %L VALID UNTIL %L',
        v_password,
        v_expires
    );

    -- Grant appropriate role
    GRANT solvereign_platform TO break_glass_user;

    -- Log the creation
    INSERT INTO core.security_events (event_type, severity, details)
    VALUES ('BREAK_GLASS_GRANTED', 'S1', jsonb_build_object(
        'user', 'break_glass_user',
        'expires', v_expires,
        'granted_by', current_user
    ));

    RAISE NOTICE 'Password: %', v_password;
    RAISE NOTICE 'Expires: %', v_expires;
END $$;
EOF
```

### 4.2 Revoking Credentials

**Immediate revocation** (before expiry if needed):

```bash
psql $ADMIN_DB_URL << 'EOF'
-- Terminate active sessions
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = 'break_glass_user';

-- Revoke role
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM break_glass_user;
REVOKE solvereign_platform FROM break_glass_user;

-- Drop user
DROP ROLE IF EXISTS break_glass_user;

-- Log revocation
INSERT INTO core.security_events (event_type, severity, details)
VALUES ('BREAK_GLASS_REVOKED', 'S2', jsonb_build_object(
    'user', 'break_glass_user',
    'revoked_by', current_user,
    'reason', 'manual_revocation'
));
EOF
```

---

## 5) Audit and Compliance

### 5.1 Logging Requirements

All break-glass access is logged:

| What | Where | Retention |
|------|-------|-----------|
| Connection events | PostgreSQL logs | 90 days |
| Queries executed | PostgreSQL logs | 90 days |
| Grant/revoke events | `core.security_events` | 1 year |
| Incident record | Incident management system | Permanent |

### 5.2 Audit Queries

```sql
-- Recent break-glass events
SELECT *
FROM core.security_events
WHERE event_type LIKE 'BREAK_GLASS%'
ORDER BY created_at DESC
LIMIT 50;

-- Active break-glass sessions
SELECT usename, application_name, client_addr, backend_start
FROM pg_stat_activity
WHERE usename = 'break_glass_user';
```

### 5.3 Compliance Review

Monthly review of break-glass usage:

1. Count of break-glass requests
2. Average access duration
3. Actions taken during access
4. Any policy violations

---

## 6) Incident Record Template

Use this template for all break-glass incidents:

```markdown
# Incident Record: INC-YYYY-NNNN

## Summary
| Field | Value |
|-------|-------|
| **ID** | INC-YYYY-NNNN |
| **Severity** | S0 / S1 / S2 |
| **Status** | Open / Investigating / Resolved / Closed |
| **Created** | [ISO timestamp] |
| **Resolved** | [ISO timestamp] |
| **Owner** | [Name] |

## Timeline
| Time | Event |
|------|-------|
| HH:MM | Incident detected via [source] |
| HH:MM | Break-glass access requested |
| HH:MM | Access granted by [approver] |
| HH:MM | Root cause identified |
| HH:MM | Fix applied |
| HH:MM | Access revoked |
| HH:MM | Incident resolved |

## Root Cause
[Detailed explanation of what caused the incident]

## Impact
- Users affected: [count]
- Data affected: [description]
- Duration: [X hours Y minutes]

## Resolution
[What was done to fix the issue]

## Break-Glass Usage
- Tier: [1/2/3]
- Duration: [X hours Y minutes]
- Actions: [summary]
- Evidence: [artifact locations]

## Prevention
[What changes will prevent recurrence]

## Action Items
- [ ] [action 1] - Owner: [name] - Due: [date]
- [ ] [action 2] - Owner: [name] - Due: [date]

## Artifacts
- `evidence/INC-YYYY-NNNN/`
  - security_events_export.csv
  - fix_applied.txt
  - break_glass_evidence.zip
```

---

## 7) Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| **Ops On-Call** | [PagerDuty] | First responder |
| **Security Lead** | [Name/Phone] | Approver |
| **Platform Eng Lead** | [Name/Phone] | Technical |
| **CTO** | [Name/Phone] | Executive |

---

## 8) Quick Reference

### Request Break-Glass
1. Document justification
2. Post to #solvereign-security-requests
3. Wait for approval
4. Receive credentials via secure channel

### During Access
1. Log everything in incident record
2. Minimize scope
3. Export evidence before changes
4. Verify after changes

### After Access
1. Disconnect immediately when done
2. Notify approver
3. Update incident record
4. Submit evidence artifacts

---

**Document Version**: 1.0

**Classification**: INTERNAL ONLY

**Last Updated**: 2026-01-08

**Review Cycle**: Quarterly
