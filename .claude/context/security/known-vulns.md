# Known Vulnerabilities Tracker

> **Purpose**: Track and mitigate known security vulnerabilities
> **Last Updated**: 2026-01-07

---

## ACTIVE VULNERABILITIES

| ID | Severity | Component | Description | Status | ETA |
|----|----------|-----------|-------------|--------|-----|
| (none currently) | - | - | - | - | - |

---

## RESOLVED VULNERABILITIES

| ID | Severity | Component | Description | Resolution | Date |
|----|----------|-----------|-------------|------------|------|
| SOLV-001 | S2 | RLS | Missing RLS on tour_instances | Added policy | 2026-01-05 |
| SOLV-002 | S2 | Auth | HMAC V1 weak signature | Upgraded to V2 | 2026-01-06 |
| SOLV-003 | S3 | API | Missing rate limiting | Added 3-tier rate limit | 2026-01-06 |

---

## VULNERABILITY ASSESSMENT CHECKLIST

### Weekly Review

- [ ] Check for new CVEs in dependencies
- [ ] Run `pip-audit` on requirements
- [ ] Run `npm audit` on frontend
- [ ] Review recent security logs
- [ ] Check for failed auth attempts (spike detection)

### Pre-Release Review

- [ ] RLS verification on all tenant tables
- [ ] Auth flow testing (all 3 methods)
- [ ] Replay protection verification
- [ ] Rate limiting verification
- [ ] Input validation review

---

## DEPENDENCY SCANNING

### Python Dependencies

```bash
# Install pip-audit
pip install pip-audit

# Scan for vulnerabilities
pip-audit -r requirements.txt

# Auto-fix if possible
pip-audit -r requirements.txt --fix
```

### Node.js Dependencies

```bash
# Scan for vulnerabilities
npm audit

# Auto-fix if possible
npm audit fix
```

---

## OWASP TOP 10 COVERAGE

| # | Risk | SOLVEREIGN Mitigation |
|---|------|----------------------|
| A01 | Broken Access Control | RLS + RBAC + audit-gating |
| A02 | Cryptographic Failures | AES-256-GCM for PII, HMAC-SHA256 |
| A03 | Injection | Parameterized queries, input validation |
| A04 | Insecure Design | Threat modeling, security reviews |
| A05 | Security Misconfiguration | Hardened defaults, no debug in prod |
| A06 | Vulnerable Components | pip-audit, npm audit, regular updates |
| A07 | Auth Failures | Entra ID SSO, HMAC signing, replay protection |
| A08 | Software/Data Integrity | SHA256 hashing, artifact verification |
| A09 | Logging Failures | Structured JSON logging, audit trail |
| A10 | SSRF | URL allowlisting, no user-controlled URLs |

---

## INCIDENT RESPONSE FOR SECURITY ISSUES

### S1 - Critical Security Incident

1. **Immediate** (0-15min):
   - Block all external traffic if needed
   - Revoke compromised credentials
   - Capture evidence (logs, artifacts)
   - Notify security lead

2. **Short-term** (15min-1h):
   - Identify scope of breach
   - Notify affected tenants
   - Prepare customer communication
   - Begin forensic analysis

3. **Resolution**:
   - Apply fix and verify
   - Full security audit
   - Update this document
   - Conduct post-mortem

### S2 - High Security Issue

1. Block writes if data integrity at risk
2. Apply fix within 24h
3. Notify affected tenants
4. Document in this tracker

---

## REPORTING A VULNERABILITY

**Internal Discovery**:
1. Document in this file immediately
2. Assign severity level
3. Create incident if S1/S2
4. Track to resolution

**External Report**:
1. Acknowledge within 24h
2. Triage and assign severity
3. Keep reporter updated
4. Credit in resolution notes

---

## SECURITY CONTACTS

| Role | Contact | When to Notify |
|------|---------|----------------|
| Security Lead | (internal) | All S1/S2 |
| Platform Admin | (internal) | All S1/S2/S3 |
| Legal | (internal) | Data breach, S1 |

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Active exploitation | S1 | STOP-THE-LINE. Incident response. |
| Unpatched CVE (critical) | S1 | Patch within 24h or block affected code. |
| Unpatched CVE (high) | S2 | Patch within 7 days. |
| Unpatched CVE (medium) | S3 | Patch in next release. |
| Unpatched CVE (low) | S4 | Track and schedule. |
