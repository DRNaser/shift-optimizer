# Audit Report Generation

> **Purpose**: Generate enterprise audit packs for customers and compliance
> **Last Updated**: 2026-01-07

---

## PURPOSE

Generate comprehensive audit evidence packs for:
- Enterprise sales (CIO/CISO requirements)
- Compliance audits (GDPR, SOC2, ISO27001)
- Customer security reviews
- Internal quality assurance

---

## AUDIT PACK CONTENTS

### Standard Audit Pack

```
ENTERPRISE_PROOF_PACK_<date>.zip
├── AUDIT_SUMMARY.md           # Executive summary
├── EVIDENCE_HASHES.json       # Tamper-proof chain
├── COMPLIANCE_MATRIX.md       # Framework mapping
├── proofs/
│   ├── rls_harness/           # Gate 1: RLS verification
│   │   ├── test_results.json
│   │   └── coverage_report.txt
│   ├── determinism/           # Gate 2: Reproducibility
│   │   ├── proof_output.json
│   │   └── hash_verification.txt
│   ├── golden_path/           # Gate 3: E2E workflow
│   │   ├── test_results.json
│   │   └── stage_timings.json
│   └── integrations/          # Gate 4: External services
│       └── connectivity_report.json
├── security/
│   ├── auth_architecture.md
│   ├── encryption_standards.md
│   └── vulnerability_scan.json
└── metadata/
    ├── git_sha.txt
    ├── generation_time.txt
    └── generator_version.txt
```

---

## GENERATING AUDIT PACK

### Full Audit Pack

```bash
python -m backend_py.tools.audit_report generate \
    --tenant gurkerl \
    --output audit_pack_$(date +%Y%m%d).zip \
    --include-all
```

### Tenant-Specific Pack

```bash
python -m backend_py.tools.audit_report generate \
    --tenant NEW_TENANT \
    --output audit_pack_new_tenant.zip
```

### Custom Selection

```bash
python -m backend_py.tools.audit_report generate \
    --tenant gurkerl \
    --include rls_harness,determinism,security \
    --output custom_pack.zip
```

---

## AUDIT SUMMARY TEMPLATE

```markdown
# SOLVEREIGN Enterprise Audit Pack

## Executive Summary

**Generated**: 2026-01-07T10:30:00Z
**Tenant**: gurkerl
**Git SHA**: abc123def
**Generator Version**: 1.0.0

### Overall Status: ✅ PASS

| Gate | Status | Evidence |
|------|--------|----------|
| RLS Harness | ✅ PASS | proofs/rls_harness/ |
| Determinism Proof | ✅ PASS | proofs/determinism/ |
| Golden Path E2E | ✅ PASS | proofs/golden_path/ |
| Integrations | ✅ PASS | proofs/integrations/ |

## Security Highlights

- **Multi-Tenancy**: Row-Level Security enforced on all tenant tables
- **Authentication**: Entra ID SSO with HMAC request signing
- **Encryption**: AES-256-GCM for PII, TLS 1.3 in transit
- **Replay Protection**: Nonce-based with 5-minute TTL
- **Audit Trail**: Immutable write-only audit log

## Compliance Mapping

See `COMPLIANCE_MATRIX.md` for detailed framework mapping.
```

---

## COMPLIANCE MATRIX

### GDPR Mapping

| Article | Requirement | SOLVEREIGN Implementation |
|---------|-------------|---------------------------|
| Art. 5 | Data minimization | Only necessary data collected |
| Art. 17 | Right to erasure | Tenant data deletion API |
| Art. 25 | Privacy by design | RLS, encryption, access control |
| Art. 32 | Security of processing | See Security section |
| Art. 33 | Breach notification | Incident response procedures |

### SOC2 Trust Criteria

| Criteria | Description | Evidence Location |
|----------|-------------|-------------------|
| CC6.1 | Logical access | security/auth_architecture.md |
| CC6.2 | Access restrictions | proofs/rls_harness/ |
| CC6.3 | Privileged access | security/rbac.md |
| CC7.1 | Change management | See git history |
| CC7.2 | System monitoring | health/monitoring.md |

### ISO 27001 Controls

| Control | Description | Implementation |
|---------|-------------|----------------|
| A.9.1 | Access control policy | RBAC with role hierarchy |
| A.9.2 | User access management | Entra ID provisioning |
| A.10.1 | Cryptographic controls | AES-256-GCM, HMAC-SHA256 |
| A.12.4 | Logging and monitoring | Structured JSON logging |
| A.14.2 | Security in dev | Code review, security tests |

---

## EVIDENCE HASHES

```json
{
  "pack_id": "AUDIT_20260107_gurkerl",
  "generated_at": "2026-01-07T10:30:00Z",
  "generator_sha": "abc123",
  "contents": [
    {
      "file": "AUDIT_SUMMARY.md",
      "sha256": "def456...",
      "size_bytes": 2048
    },
    {
      "file": "proofs/rls_harness/test_results.json",
      "sha256": "ghi789...",
      "size_bytes": 4096
    }
  ],
  "overall_hash": "sha256:xyz...",
  "signature": "HMAC-SHA256(overall_hash)"
}
```

---

## AUTOMATION

### Weekly Generation

```yaml
# .github/workflows/weekly-audit.yml
name: Weekly Audit Report
on:
  schedule:
    - cron: '0 0 * * 0'  # Sundays at midnight

jobs:
  audit-report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Generate Audit Pack
        run: |
          python -m backend_py.tools.audit_report generate \
            --all-tenants \
            --output audit_pack_$(date +%Y%m%d).zip

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: audit-pack
          path: audit_pack_*.zip
```

### On-Demand Generation

```bash
# For sales request
python -m backend_py.tools.audit_report generate \
    --tenant prospect_tenant \
    --output prospect_audit_pack.zip \
    --include security,compliance
```

---

## VERIFICATION

### Verify Pack Integrity

```bash
python -m backend_py.tools.audit_report verify \
    --pack audit_pack_20260107.zip

# Output:
# Verifying audit pack integrity...
# ✅ overall_hash matches
# ✅ All file hashes verified (12/12)
# ✅ Signature valid
# Pack is AUTHENTIC and UNMODIFIED
```

### Verify Individual Proof

```bash
python -m backend_py.tools.audit_report verify-proof \
    --pack audit_pack_20260107.zip \
    --proof rls_harness
```

---

## CUSTOMIZATION

### Add Custom Section

```python
# In audit_report/generator.py

def add_custom_section(pack: AuditPack, tenant: Tenant):
    """Add tenant-specific custom section."""

    custom_content = f"""
## Tenant-Specific Configuration

- **Pack**: {tenant.active_pack}
- **Features**: {', '.join(tenant.features)}
- **SLA**: {tenant.sla_tier}
"""

    pack.add_file("custom/tenant_config.md", custom_content)
```

### Custom Compliance Framework

```python
# Add framework mapping
CUSTOM_FRAMEWORK = {
    "control_1": {
        "description": "Access Control",
        "evidence": ["proofs/rls_harness/", "security/rbac.md"],
        "status": "PASS"
    },
    # ...
}

pack.add_compliance_mapping("CUSTOM", CUSTOM_FRAMEWORK)
```

---

## DISTRIBUTION

### Secure Delivery

1. Generate pack with signature
2. Encrypt with customer public key (if provided)
3. Upload to secure storage
4. Send download link with expiry
5. Log access

### Access Logging

```python
# Log every pack access
audit_log.record(
    event="audit_pack_downloaded",
    pack_id=pack.id,
    accessed_by=user.email,
    ip_address=request.client.host,
    timestamp=datetime.utcnow()
)
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Proof fails during generation | S2 | Fix issue. Regenerate. |
| Signature verification fails | S2 | Investigate tampering. |
| Missing compliance mapping | S3 | Add mapping. Update template. |
| Customer requests unavailable proof | S4 | Assess and add if feasible. |
