# Security Branch - Router Checklist

> **Purpose**: Authentication, authorization, RLS, and vulnerability management
> **Severity Default**: S2 (HIGH) - Block writes until verified

---

## ENTRY CHECKLIST

Before proceeding, answer these questions:

1. **Is this a data leak?**
   - YES → STOP. Read `known-vulns.md`. Escalate to S1.
   - NO → Continue

2. **Is RLS bypassed or misconfigured?**
   - YES → Read `rls-enforcement.md`
   - NO → Continue

3. **Is authentication/token handling involved?**
   - YES → Read `auth-flows.md`
   - NO → Continue

4. **Is this a replay attack or signature issue?**
   - YES → Read `auth-flows.md` (HMAC section)
   - NO → Use general security guidance below

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `rls-enforcement.md` | Row-Level Security rules and verification | RLS issues, cross-tenant leaks |
| `auth-flows.md` | Entra ID, HMAC, API Key authentication | Auth failures, token issues |
| `known-vulns.md` | Tracked vulnerabilities and mitigations | Security audits, incident response |

---

## QUICK ACTIONS

### Verify RLS is Active
```sql
-- Check current tenant context
SELECT current_setting('app.current_tenant_id', true);

-- Verify RLS policies exist
SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public';
```

### Check Auth Headers
```bash
# Required headers for internal requests
X-SV-Signature: <HMAC signature>
X-SV-Timestamp: <ISO timestamp>
X-SV-Nonce: <UUID>
```

### Security Smoke Test
```bash
python -m backend_py.tests.test_security_proofs
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Cross-tenant data visible | S1 | STOP-THE-LINE. Notify immediately. |
| RLS policy missing | S2 | Block writes. Fix before deploy. |
| Auth bypass possible | S1 | STOP-THE-LINE. Revoke tokens. |
| Weak signature validation | S2 | Block writes. Harden validation. |
| Known CVE unpatched | S3 | Schedule fix. Document risk. |

---

## RELATED BRANCHES

- Incident occurred? → `stability/incident-triage.md`
- Performance impact? → `performance/timeout-playbook.md`
- Migration needed? → `architecture/migration-rules.md`
