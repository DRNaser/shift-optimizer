# Data Governance Policy

**System**: SOLVEREIGN V3.7
**Scope**: All tenant data, audit logs, evidence artifacts
**Effective**: 2026-01-08
**Review Cycle**: Quarterly

---

## 1) Overview

This document defines data governance policies for SOLVEREIGN, including retention schedules, GDPR compliance, access controls, and data lifecycle management.

**Guiding Principles**:
- Minimize data collection (collect only what's needed)
- Tenant isolation by design (RLS at database level)
- Audit trail for all data access
- Right to deletion with evidence of completion

---

## 2) Data Classification

### 2.1 Classification Levels

| Level | Description | Examples | Retention |
|-------|-------------|----------|-----------|
| **RESTRICTED** | Personal identifiable data | Driver names, emails, phone | Per GDPR |
| **CONFIDENTIAL** | Business-sensitive data | Schedules, KPIs, costs | Per contract |
| **INTERNAL** | Operational data | Logs, metrics, health checks | Per policy |
| **PUBLIC** | Non-sensitive data | API docs, schema versions | Indefinite |

### 2.2 Data Categories

| Category | Classification | Location | Owner |
|----------|---------------|----------|-------|
| Driver PII | RESTRICTED | `drivers` table | Tenant |
| Tour schedules | CONFIDENTIAL | `tour_instances`, `assignments` | Tenant |
| Plan versions | CONFIDENTIAL | `plan_versions` | Tenant |
| Audit logs | INTERNAL | `audit_log` | Platform |
| Security events | INTERNAL | `core.security_events` | Platform |
| Evidence packs | CONFIDENTIAL | Artifact storage | Platform |
| Access logs | INTERNAL | Application logs | Platform |
| Health metrics | INTERNAL | Monitoring system | Platform |

---

## 3) Retention Policy

### 3.1 Retention Schedule

| Data Type | Retention Period | Justification |
|-----------|------------------|---------------|
| **Operational Data** | | |
| Active plans | Until superseded | Current operations |
| Locked plans | 90 days | Audit reference |
| Archived plans | 2 years | Business requirements |
| Tour templates | 90 days | Diff computation |
| Tour instances | 90 days | Audit trail |
| **Audit Data** | | |
| Audit logs | 1 year | Compliance |
| Security events | 1 year | Incident investigation |
| Break-glass records | 3 years | Security compliance |
| **Evidence Artifacts** | | |
| Evidence packs | 1 year | Audit trail |
| Solve manifests | 90 days | Reproducibility |
| Drill results | 90 days | Ops validation |
| **Logs** | | |
| Application logs | 90 days | Debugging |
| Access logs | 1 year | Security |
| Health metrics | 30 days | Monitoring |

### 3.2 Retention Implementation

```sql
-- Automated cleanup job (runs daily at 03:00 UTC)

-- Delete old audit logs (>1 year)
DELETE FROM audit_log
WHERE created_at < NOW() - INTERVAL '1 year';

-- Archive locked plans (>90 days)
UPDATE plan_versions
SET status = 'ARCHIVED'
WHERE status = 'LOCKED'
  AND locked_at < NOW() - INTERVAL '90 days';

-- Delete archived plans (>2 years)
DELETE FROM plan_versions
WHERE status = 'ARCHIVED'
  AND locked_at < NOW() - INTERVAL '2 years';

-- Delete old security events (>1 year)
DELETE FROM core.security_events
WHERE created_at < NOW() - INTERVAL '1 year';
```

### 3.3 Evidence Artifact Retention

```bash
# Artifact storage structure
artifacts/
├── evidence/           # 1 year retention
│   └── <tenant_id>/
│       └── <year>/
│           └── <month>/
├── drills/             # 90 days retention
│   └── <drill_type>/
├── temp/               # 7 days retention
└── exports/            # 30 days retention
```

---

## 4) GDPR Compliance

### 4.1 Data Subject Rights

| Right | Implementation | Response Time |
|-------|---------------|---------------|
| **Access** (Art. 15) | Export tenant data | 30 days |
| **Rectification** (Art. 16) | Update driver records | 30 days |
| **Erasure** (Art. 17) | Delete tenant data | 30 days |
| **Portability** (Art. 20) | Export in JSON format | 30 days |
| **Restriction** (Art. 18) | Disable processing | 72 hours |

### 4.2 Data Export Workflow

**Purpose**: Fulfill GDPR Article 15 (Right of Access) and Article 20 (Data Portability)

```bash
# Step 1: Generate data export request
python scripts/gdpr_export.py request \
  --tenant wien_pilot \
  --requester "privacy@tenant.com" \
  --reason "GDPR Art. 15 Access Request"

# Step 2: Review and approve (Data Protection Officer)
python scripts/gdpr_export.py approve \
  --request-id REQ-2026-0001 \
  --approver "dpo@lts.com"

# Step 3: Execute export
python scripts/gdpr_export.py execute \
  --request-id REQ-2026-0001 \
  --output exports/gdpr_export_wien_pilot_20260108.zip

# Step 4: Deliver to requester (secure channel)
# Step 5: Log completion
python scripts/gdpr_export.py complete \
  --request-id REQ-2026-0001 \
  --delivery-method "encrypted_email"
```

**Export Contents**:
```
gdpr_export_<tenant>_<date>.zip
├── manifest.json           # Export metadata
├── drivers.json            # Driver PII
├── assignments.json        # Historical assignments
├── plans.json              # Plan summaries (no internal hashes)
├── audit_log.json          # Tenant-scoped audit entries
└── checksums.txt           # Integrity verification
```

### 4.3 Data Deletion Workflow

**Purpose**: Fulfill GDPR Article 17 (Right to Erasure / "Right to be Forgotten")

```bash
# Step 1: Create deletion request
python scripts/gdpr_delete.py request \
  --tenant wien_pilot \
  --scope "all" \
  --requester "privacy@tenant.com" \
  --reason "GDPR Art. 17 Erasure Request"

# Step 2: Review impact (shows what will be deleted)
python scripts/gdpr_delete.py preview \
  --request-id DEL-2026-0001

# Step 3: Dual approval required
python scripts/gdpr_delete.py approve \
  --request-id DEL-2026-0001 \
  --approver "dpo@lts.com" \
  --role "DPO"

python scripts/gdpr_delete.py approve \
  --request-id DEL-2026-0001 \
  --approver "platform-lead@lts.com" \
  --role "PLATFORM_LEAD"

# Step 4: Execute deletion (irreversible)
python scripts/gdpr_delete.py execute \
  --request-id DEL-2026-0001 \
  --confirm "DELETE_PERMANENTLY"

# Step 5: Generate deletion certificate
python scripts/gdpr_delete.py certificate \
  --request-id DEL-2026-0001 \
  --output evidence/deletion_certificate_DEL-2026-0001.pdf
```

**Deletion Scope Options**:
- `all`: Complete tenant data deletion
- `pii_only`: Driver PII only (preserves anonymized operational data)
- `specific`: Specific data categories

**Deletion Certificate**:
```markdown
## Data Deletion Certificate

Request ID: DEL-2026-0001
Tenant: wien_pilot
Scope: all
Requested: 2026-01-08T10:00:00Z
Completed: 2026-01-08T14:30:00Z

### Data Deleted
- drivers: 145 records
- assignments: 12,500 records
- plan_versions: 52 records
- tour_instances: 8,000 records
- audit_log: 1,200 entries

### Verification
- Database deletion: VERIFIED
- Backup exclusion: VERIFIED
- Artifact purge: VERIFIED
- Log redaction: VERIFIED

Signature: [Platform Lead]
Date: 2026-01-08
```

### 4.4 Data Processing Agreement (DPA) Requirements

| Requirement | Implementation |
|-------------|---------------|
| Purpose limitation | Tenant-scoped processing only |
| Data minimization | Collect only required fields |
| Storage limitation | Retention policy enforced |
| Integrity | RLS + audit logging |
| Confidentiality | Encryption at rest + transit |
| Accountability | DPO designated, audit trail |

---

## 5) Access Control

### 5.1 Role-Based Access

| Role | Data Access | Actions |
|------|-------------|---------|
| **Tenant User** | Own tenant data only | Read schedules, assignments |
| **Tenant Admin** | Own tenant data + config | Manage drivers, run solves |
| **Platform Ops** | All tenant data (read) | Monitor, troubleshoot |
| **Platform Admin** | All tenant data (read/write) | Migrations, config |
| **Security Lead** | Security events, audit logs | Incident response |
| **DPO** | GDPR requests, deletion certs | Privacy compliance |

### 5.2 Access Logging

All data access is logged:

```json
{
  "timestamp": "2026-01-08T10:00:00Z",
  "event_type": "DATA_ACCESS",
  "actor": "platform-admin@lts.com",
  "actor_role": "PLATFORM_ADMIN",
  "tenant_id": "wien_pilot",
  "resource": "plan_versions",
  "action": "SELECT",
  "row_count": 52,
  "reason": "Incident investigation INC-2026-0001",
  "session_id": "sess_abc123"
}
```

### 5.3 Monthly Access Review

```bash
# Generate monthly access report
python scripts/access_review.py generate \
  --month 2026-01 \
  --output reports/access_review_2026_01.json

# Review checklist
- [ ] No unauthorized cross-tenant access
- [ ] Break-glass usage justified
- [ ] Service accounts reviewed
- [ ] Inactive users disabled
```

---

## 6) Tenant Data Isolation

### 6.1 Database-Level Isolation

```sql
-- RLS enforces tenant isolation
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON assignments
  USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- Platform role can access all tenants via pg_has_role()
CREATE POLICY platform_access ON assignments
  FOR ALL TO solvereign_platform
  USING (pg_has_role(current_user, 'solvereign_platform', 'MEMBER'));
```

### 6.2 Application-Level Isolation

```python
# All queries are tenant-scoped
async def get_assignments(tenant_id: int, plan_version_id: int):
    # RLS automatically filters to tenant
    return await db.fetch(
        "SELECT * FROM assignments WHERE plan_version_id = $1",
        plan_version_id
    )
```

### 6.3 Storage-Level Isolation

```
# Artifact storage uses tenant prefixes
artifacts/
└── evidence/
    ├── tenant_001/    # Wien Pilot
    │   └── ...
    ├── tenant_002/    # Future tenant
    │   └── ...
```

---

## 7) Backup and Recovery

### 7.1 Backup Schedule

| Type | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| Full backup | Daily (02:00 UTC) | 30 days | Azure Blob |
| Incremental | Hourly | 7 days | Azure Blob |
| Transaction log | Continuous | 7 days | Azure Blob |
| Evidence artifacts | Daily sync | Per policy | Azure Blob |

### 7.2 Recovery Procedures

```bash
# Point-in-time recovery (PITR)
pg_restore \
  --dbname $SOLVEREIGN_DB_URL \
  --target-time "2026-01-08 10:00:00 UTC" \
  backups/solvereign_full_20260108.dump

# Verify RLS after recovery
psql $SOLVEREIGN_DB_URL -c "SELECT * FROM verify_final_hardening();"
```

### 7.3 Backup Exclusions

GDPR-deleted data is excluded from future backups:
- Deletion job runs before backup
- Backup retention respects deletion requests
- Recovery to pre-deletion state requires DPO approval

---

## 8) Data Lifecycle

### 8.1 Lifecycle Stages

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA LIFECYCLE                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CREATED     →    ACTIVE    →    LOCKED    →    ARCHIVED        │
│  (Ingested)      (Mutable)      (Immutable)    (Read-only)      │
│                                                                  │
│                                                    │             │
│                                                    ▼             │
│                                                 DELETED          │
│                                                 (Purged)         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Lifecycle Transitions

| From | To | Trigger | Reversible |
|------|-----|---------|------------|
| CREATED | ACTIVE | Validation pass | No |
| ACTIVE | LOCKED | User lock action | No |
| LOCKED | ARCHIVED | 90-day retention | No |
| ARCHIVED | DELETED | 2-year retention | No |
| Any | DELETED | GDPR request | No |

### 8.3 Archival Process

```python
# Daily archival job
async def archive_old_plans():
    # Move plans older than 90 days to archive
    await db.execute("""
        UPDATE plan_versions
        SET status = 'ARCHIVED'
        WHERE status = 'LOCKED'
          AND locked_at < NOW() - INTERVAL '90 days'
    """)

    # Move artifacts to cold storage
    await artifact_store.move_to_archive(
        source="evidence/",
        filter_older_than=timedelta(days=90),
        destination="archive/"
    )
```

---

## 9) Compliance Checklist

### 9.1 Monthly Review

```markdown
## Data Governance Monthly Review

Date: 2026-01-XX
Reviewer: [Name]

### Retention Compliance
- [ ] Automated cleanup jobs running
- [ ] No data beyond retention period
- [ ] Archive process successful

### Access Control
- [ ] Access logs reviewed
- [ ] No unauthorized access detected
- [ ] Service accounts audited

### GDPR Compliance
- [ ] All requests processed within SLA
- [ ] Deletion certificates issued
- [ ] Export requests fulfilled

### Backup Verification
- [ ] Daily backups successful
- [ ] Recovery test performed (quarterly)
- [ ] GDPR deletions excluded

### Documentation
- [ ] Policy changes documented
- [ ] New data categories classified
- [ ] Training completed (if new staff)

Signature: _______________
```

### 9.2 Quarterly Audit

```bash
# Generate compliance report
python scripts/compliance_audit.py generate \
  --quarter 2026-Q1 \
  --output reports/compliance_audit_2026_Q1.pdf

# Report includes:
# - Data inventory
# - Retention compliance
# - Access review summary
# - GDPR request statistics
# - Incident summary
# - Recommendations
```

---

## 10) Incident Response

### 10.1 Data Breach Procedure

| Step | Action | Timeline |
|------|--------|----------|
| 1 | Detect and contain | Immediate |
| 2 | Assess scope and impact | 4 hours |
| 3 | Notify Security Lead | 4 hours |
| 4 | Notify DPO | 24 hours |
| 5 | Notify supervisory authority (if required) | 72 hours |
| 6 | Notify affected data subjects (if required) | Without undue delay |
| 7 | Document and remediate | Ongoing |

### 10.2 Breach Notification Template

```markdown
## Data Breach Notification

Incident ID: [INC-YYYY-NNNN]
Date Discovered: [Date]
Date Occurred: [Date or range]

### Nature of Breach
[Description of what happened]

### Data Affected
- Categories: [e.g., driver names, schedules]
- Approximate records: [Number]
- Tenants affected: [List]

### Likely Consequences
[Assessment of risk to data subjects]

### Measures Taken
[Actions to address the breach]

### Recommendations
[Steps data subjects should take]

Contact: [DPO contact information]
```

---

## 11) Documentation References

| Document | Purpose |
|----------|---------|
| [INCIDENT_BREAK_GLASS.md](INCIDENT_BREAK_GLASS.md) | Emergency access procedure |
| [RUNBOOK_PROD_CUTOVER.md](../RUNBOOK_PROD_CUTOVER.md) | Production deployment |
| [SLO_WIEN_PILOT.md](SLO_WIEN_PILOT.md) | Service level objectives |
| Security Enforcement | `.claude/security-enforcement.json` |

---

**Document Version**: 1.0

**Classification**: INTERNAL

**Last Updated**: 2026-01-08

**Next Review**: 2026-04-08 (Quarterly)

**Approved By**: [DPO Name], [Platform Lead Name]
