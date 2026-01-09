# Release Process

**System**: SOLVEREIGN V3.7
**Audience**: Platform Engineering, Release Managers
**Last Updated**: 2026-01-08

---

## 1) Release Types

| Type | Cadence | Approval | Rollback Window |
|------|---------|----------|-----------------|
| **Major** (vX.0.0) | Quarterly | CTO + Product | 24 hours |
| **Minor** (vX.Y.0) | Bi-weekly | Platform Lead | 12 hours |
| **Patch** (vX.Y.Z) | As needed | On-call | 4 hours |
| **Hotfix** | Emergency | Security Lead | 1 hour |

---

## 2) Release Checklist

### 2.1 Pre-Release (D-3 to D-1)

```markdown
## Pre-Release Checklist

Release: vX.Y.Z
Target Date: YYYY-MM-DD
Release Manager: [Name]

### Code Readiness
- [ ] All PRs merged to main
- [ ] No open blockers in milestone
- [ ] CHANGELOG.md updated
- [ ] Version bumped in package files

### Testing
- [ ] All CI gates pass (pr-guardian.yml)
- [ ] Staging soak test PASS (>=5 iterations)
- [ ] Ops drills PASS (H1, H2, H3)
- [ ] Security gate PASS (verify_final_hardening)

### Documentation
- [ ] CHANGELOG.md complete
- [ ] Migration notes documented
- [ ] Breaking changes documented
- [ ] Runbook updated if needed

### Dependencies
- [ ] Python dependencies frozen (requirements.txt)
- [ ] Docker images tagged
- [ ] OSRM version noted (or PARKED)

### Approvals
- [ ] Product Owner sign-off
- [ ] Platform Lead sign-off
- [ ] Security Lead sign-off (if security changes)
```

### 2.2 Release Day (D-0)

```markdown
## Release Day Checklist

### Pre-Deployment
- [ ] Maintenance window communicated
- [ ] On-call engineer assigned
- [ ] Rollback plan reviewed
- [ ] Backup verified

### Deployment
- [ ] Writes disabled (if schema changes)
- [ ] Preflight check PASS
- [ ] Migrations applied (ON_ERROR_STOP)
- [ ] Hardening verified
- [ ] Smoke tests PASS

### Post-Deployment
- [ ] Writes re-enabled
- [ ] Health check OK
- [ ] SLO metrics baseline captured
- [ ] Release tag pushed
- [ ] Changelog published

### Monitoring (First Hour)
- [ ] Error rate <1%
- [ ] Latency P95 within SLO
- [ ] No security alerts
- [ ] No customer reports
```

### 2.3 Post-Release (D+1)

```markdown
## Post-Release Checklist

- [ ] Release notes published
- [ ] Stakeholders notified
- [ ] Monitoring alerts tuned
- [ ] Retrospective scheduled (if major)
- [ ] Next milestone planned
```

---

## 3) Version Tagging

### 3.1 Tag Format

```
v<major>.<minor>.<patch>[-rc<n>]

Examples:
  v3.7.0        # GA release
  v3.7.1        # Patch release
  v3.7.0-rc1    # Release candidate 1
  v3.7.0-rc2    # Release candidate 2
```

### 3.2 Tagging Process

```bash
# 1. Ensure on main branch, up to date
git checkout main
git pull origin main

# 2. Verify all CI passes
gh run list --workflow=pr-guardian.yml --branch=main

# 3. Create annotated tag
git tag -a v3.7.0 -m "Release v3.7.0 - Wien Pilot GA

Highlights:
- P0 RLS Security Hardening
- Wien Pilot Import Pipeline
- Pack Entitlements Enforcement
- Production Cutover Automation

See CHANGELOG.md for full details."

# 4. Push tag
git push origin v3.7.0

# 5. Create GitHub release (optional)
gh release create v3.7.0 \
  --title "SOLVEREIGN v3.7.0 - Wien Pilot GA" \
  --notes-file CHANGELOG.md \
  --prerelease=false
```

### 3.3 Release Candidate Tags

```bash
# RC tags for staging validation
git tag -a v3.7.0-rc1 -m "Wien Pilot RC1 - soak verified"
git push origin v3.7.0-rc1

# If issues found, fix and create RC2
git tag -a v3.7.0-rc2 -m "Wien Pilot RC2 - fixed issue #123"
git push origin v3.7.0-rc2

# Promote RC to GA (same commit)
git tag -a v3.7.0 -m "Wien Pilot GA - promoted from rc2"
git push origin v3.7.0
```

---

## 4) CHANGELOG Format

```markdown
# Changelog

All notable changes to SOLVEREIGN are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature descriptions

### Changed
- Modification descriptions

### Deprecated
- Soon-to-be removed features

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security fixes

## [3.7.0] - 2026-01-08

### Added
- P0 RLS Security Hardening (migrations 025-025f)
- Wien Pilot Import Pipeline with coords quality gate
- Pack entitlements enforcement with 403 responses
- Production cutover automation scripts
- Enterprise skills (113-116): audit, impact, golden datasets, KPI drift

### Changed
- OSRM map hash now path-neutral for audit consistency
- SECURITY DEFINER functions use session_user for caller check
- Health endpoint includes entitlement cache status

### Security
- [CVE-XXXX] Fixed RLS bypass via session variable (025c)
- Added HMAC V2 signature verification
- Added replay protection via nonce tracking

### Migration Notes
- Apply migrations 025-025f in order
- Run verify_final_hardening() after migration
- ACL scan should show no PUBLIC grants

## [3.6.0] - 2026-01-01

### Added
- Multi-tenant API with X-API-Key auth
- Idempotency keys with 24h TTL
- Tour instances with crosses_midnight flag
...
```

---

## 5) Migration Notes

### 5.1 Migration Documentation

Each migration must document:

```markdown
## Migration: 025c_rls_boundary_fix.sql

### Purpose
Fix RLS bypass via session variables by switching to role-based checks.

### Changes
- Drop policy: tenants_isolation_policy
- Create policy: tenants_platform_role_only (uses pg_has_role)
- Modify function: list_all_tenants() to use session_user

### Prerequisites
- Migrations 025, 025a, 025b applied
- Database backup taken
- Writes disabled

### Rollback
- Restore from backup (schema changes not easily reversible)

### Verification
SELECT * FROM verify_rls_boundary();
-- All rows should show status='PASS'

### Risk Level
HIGH - Security-critical change
```

### 5.2 Breaking Changes

```markdown
## Breaking Changes in v3.7.0

### API Changes
- None

### Database Changes
- RLS policies now use pg_has_role() instead of session variables
- set_super_admin_context() is DEPRECATED and has no effect

### Configuration Changes
- SOLVEREIGN_PLATFORM_WRITES_DISABLED now respected

### Behavior Changes
- 403 returned for disabled packs (previously 200 with empty data)
- API key auth blocked on platform endpoints

### Migration Required
- Yes, migrations 025-025f must be applied in order
```

---

## 6) Rollback Procedure

### 6.1 Rollback Triggers

| Trigger | Severity | Action |
|---------|----------|--------|
| 5xx error rate >5% for 5min | S1 | Immediate rollback |
| Data corruption detected | S0 | Immediate rollback |
| Security vulnerability | S0 | Immediate rollback |
| SLO violation sustained | S2 | Rollback within 1h |

### 6.2 Rollback Steps

```bash
# 1. Disable writes
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value true

# 2. Get rollback target
ROLLBACK_TAG=$(jq -r '.rollback_sha' .claude/state/last-known-good.json)

# 3. Deploy previous version
git checkout $ROLLBACK_TAG
./scripts/deploy.sh --env production

# 4. Restore database (if schema changed)
pg_restore \
  --dbname $SOLVEREIGN_DB_URL \
  --clean --if-exists \
  backups/pre_release_backup.dump

# 5. Verify
curl -s https://api.solvereign.com/health/ready | jq '.ready'

# 6. Re-enable writes
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value false

# 7. Create incident record
```

### 6.3 Post-Rollback Actions

- [ ] Create incident record
- [ ] Notify stakeholders
- [ ] Capture evidence (logs, metrics)
- [ ] Schedule postmortem
- [ ] Block re-release until fix verified

---

## 7) Dependency Management

### 7.1 Python Dependencies

```bash
# Freeze dependencies before release
pip freeze > requirements.lock.txt

# Verify no unpinned dependencies
grep -v "==" requirements.txt && echo "ERROR: Unpinned deps found"

# Update requirements.txt with exact versions
pip-compile requirements.in --generate-hashes
```

### 7.2 Docker Images

```bash
# Tag release images
docker tag solvereign-api:latest solvereign-api:v3.7.0
docker push solvereign-api:v3.7.0

# Use specific tags in production
# docker-compose.prod.yml
services:
  api:
    image: solvereign-api:v3.7.0  # Not :latest
```

### 7.3 OSRM Status

```markdown
## OSRM Map Data

Status: PARKED (not included in Wien Pilot)
Reason: Awaiting real coordinate test data

When ready:
- Download Austria PBF from Geofabrik
- Process with OSRM backend
- Store hash in routing_evidence
- Re-enable coords quality gate
```

---

## 8) Release Artifacts

### 8.1 Required Artifacts

```
releases/v3.7.0/
├── CHANGELOG.md              # Release notes
├── requirements.lock.txt     # Frozen Python deps
├── migrations/               # Applied migrations
│   ├── 025_tenants_rls_fix.sql
│   ├── 025a_rls_hardening.sql
│   └── ...
├── artifacts/
│   ├── preflight_result.json
│   ├── verify_hardening.txt
│   ├── acl_scan_report.json
│   └── cutover_summary.json
├── checksums.txt             # SHA256 of all files
└── release_manifest.json     # Metadata
```

### 8.2 Release Manifest

```json
{
  "version": "3.7.0",
  "release_date": "2026-01-08",
  "git_sha": "abc123def456",
  "git_tag": "v3.7.0",
  "migrations_applied": [
    "025_tenants_rls_fix",
    "025a_rls_hardening",
    "025b_rls_role_lockdown",
    "025c_rls_boundary_fix",
    "025d_definer_owner_hardening",
    "025e_final_hardening",
    "025f_acl_fix"
  ],
  "python_version": "3.11.0",
  "postgres_version": "16.1",
  "osrm_status": "PARKED",
  "approvals": {
    "product_owner": "name@lts.com",
    "platform_lead": "name@lts.com",
    "security_lead": "name@lts.com"
  },
  "checksums": {
    "requirements.lock.txt": "sha256:...",
    "migrations.tar.gz": "sha256:..."
  }
}
```

---

## 9) Emergency Release (Hotfix)

### 9.1 Hotfix Process

```bash
# 1. Branch from release tag
git checkout -b hotfix/v3.7.1 v3.7.0

# 2. Apply minimal fix
# ... make changes ...

# 3. Fast-track review (Security Lead required for security fixes)
gh pr create --title "Hotfix: [description]" --label "hotfix"

# 4. Merge and tag
git checkout main
git merge hotfix/v3.7.1
git tag -a v3.7.1 -m "Hotfix: [description]"
git push origin main v3.7.1

# 5. Deploy immediately
./scripts/deploy.sh --env production --tag v3.7.1
```

### 9.2 Hotfix Criteria

Hotfixes are allowed for:
- Security vulnerabilities (S0/S1)
- Data corruption bugs
- Complete service outage
- Compliance violations

Hotfixes are NOT for:
- Feature additions
- Performance improvements (unless causing outage)
- Cosmetic issues

---

## 10) Release Communication

### 10.1 Internal Notification

```markdown
Subject: [RELEASE] SOLVEREIGN v3.7.0 - Wien Pilot GA

Team,

SOLVEREIGN v3.7.0 has been deployed to production.

**Highlights**:
- P0 RLS Security Hardening complete
- Wien Pilot import pipeline ready
- Pack entitlements enforcement enabled

**Action Required**:
- Monitor dashboards for next 2 hours
- Report any anomalies to #solvereign-ops

**Documentation**:
- CHANGELOG: [link]
- Runbook: [link]

Thanks,
[Release Manager]
```

### 10.2 Customer Notification (if applicable)

```markdown
Subject: SOLVEREIGN Update - Enhanced Security and Features

Dear [Customer],

We have deployed an update to SOLVEREIGN with the following improvements:

**New Features**:
- Enhanced data isolation for multi-tenant environments
- Improved audit trail and compliance reporting

**No Action Required**:
This update is backward compatible. Your existing integrations will continue to work.

**Questions?**
Contact support@solvereign.com

Best regards,
SOLVEREIGN Team
```

---

## 11) References

| Document | Purpose |
|----------|---------|
| [VERSIONING.md](VERSIONING.md) | Version numbering policy |
| [RUNBOOK_PROD_CUTOVER.md](RUNBOOK_PROD_CUTOVER.md) | Production deployment steps |
| [docs/SLO_WIEN_PILOT.md](docs/SLO_WIEN_PILOT.md) | Service level objectives |
| [docs/DATA_GOVERNANCE.md](docs/DATA_GOVERNANCE.md) | Data retention and GDPR |

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Owner**: Platform Engineering
