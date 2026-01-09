# Contract Freeze Policy

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Burn-In Period
**Effective Date**: 2026-02-03
**Last Updated**: 2026-01-08

---

## Purpose

This policy defines the contract freeze and change control requirements during the Wien Pilot burn-in period. The goal is to prevent silent regressions while maintaining the ability to fix critical issues.

---

## Frozen Contracts

### Import Contract Schema (v1)

**File**: `docs/IMPORT_CONTRACT_ROSTER.md`
**Schema**: `contracts/roster_import.schema.json`
**Version**: 1.0.0

**Frozen Elements**:
- Required fields (driver_id, external_id, name, etc.)
- Hard gates (HG-001 through HG-008)
- Soft gates (SG-001 through SG-005)
- JSON/CSV format specifications
- Austria bounding box coordinates

**Any change requires**:
1. Version bump (v1.0.0 → v1.1.0 for backward-compatible, v2.0.0 for breaking)
2. GA readiness mini-review
3. Documented migration path
4. Updated test fixtures

### KPI Threshold Config (v1)

**File**: `config/pilot_kpi_thresholds.json`
**Version**: 1.0.0

**Frozen Elements**:
- Baseline values (headcount: 145, coverage: 100%, etc.)
- WARN/BLOCK threshold percentages
- Drift detection method (z_score_and_percent)
- Alert channels

**Any change requires**:
1. Version bump
2. Documented justification
3. Impact analysis on existing alerts

### Publish Gate Config (v1)

**File**: `config/enable_publish_lock_wien.json`
**Version**: 1.0.0

**Frozen Elements**:
- Site enablement flags
- Approval requirements
- Pre-publish checks
- Audit requirements

**Exceptions**: Kill switch can be toggled without version bump (emergency only)

---

## Change Control Process

### During Burn-In (Days 1-30)

```
                    ┌─────────────────┐
                    │  Change Request │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Is it a fix for │
                    │ operational     │
                    │ blocker?        │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
             Yes                           No
              │                             │
              ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │ Expedited Review│           │ Defer to Post-  │
    │ (same day)      │           │ Burn-In Backlog │
    └────────┬────────┘           └─────────────────┘
             │
    ┌────────▼────────┐
    │ Approvers:      │
    │ - Platform Lead │
    │ - Ops Lead      │
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ If APPROVED:    │
    │ - Version bump  │
    │ - CI gates      │
    │ - Evidence pack │
    └─────────────────┘
```

### Change Request Template

```markdown
## Change Request

**Request ID**: CHG-YYYY-NNN
**Date**: YYYY-MM-DD
**Requester**: [Name]

### Summary
[One-line description]

### Justification
[ ] Operational blocker - production is impacted
[ ] Security fix - vulnerability needs immediate remediation
[ ] Data integrity - risk of data corruption/loss
[ ] Other (explain):

### Affected Components
- [ ] Import contract schema
- [ ] KPI threshold config
- [ ] Publish gate config
- [ ] API endpoints
- [ ] Database schema
- [ ] Other: [specify]

### Impact Analysis
- Backward compatible: Yes / No
- Requires migration: Yes / No
- Affects existing data: Yes / No
- Customer-visible: Yes / No

### Version Bump
- Current: v[X.Y.Z]
- Proposed: v[X.Y.Z]
- Bump type: PATCH / MINOR / MAJOR

### Testing Plan
[How will this be tested before deployment?]

### Rollback Plan
[How to rollback if issues arise?]

### Approvals
- [ ] Platform Lead: _____________ Date: _____
- [ ] Ops Lead: _____________ Date: _____
- [ ] Security (if applicable): _____________ Date: _____
```

---

## Version Bump Rules

### Semantic Versioning

```
MAJOR.MINOR.PATCH

MAJOR: Breaking changes (e.g., removing required field)
MINOR: Backward-compatible additions (e.g., new optional field)
PATCH: Bug fixes (e.g., validation fix)
```

### Examples

| Change | Bump Type | Example |
|--------|-----------|---------|
| Fix validation regex bug | PATCH | 1.0.0 → 1.0.1 |
| Add optional field | MINOR | 1.0.1 → 1.1.0 |
| Remove required field | MAJOR | 1.1.0 → 2.0.0 |
| Change field type | MAJOR | 1.1.0 → 2.0.0 |
| Add new hard gate | MINOR | 1.0.0 → 1.1.0 |
| Remove hard gate | MAJOR | 1.1.0 → 2.0.0 |

---

## Dependency Pinning

### Python Dependencies

**File**: `backend_py/requirements.txt`

During burn-in, all dependencies must be pinned to exact versions:
```
psycopg[binary]==3.1.12
fastapi==0.109.0
pydantic==2.5.3
ortools==9.8.3296
```

**Updates require**:
1. Security advisory justification
2. Local testing with pinned version
3. CI pipeline pass
4. Change request approval

### System Dependencies

**File**: `docker-compose.yml`

Pinned:
- PostgreSQL: `16-alpine`
- Python: `3.11-slim`

---

## CI Gates During Burn-In

All changes during burn-in must pass:

1. **Unit Tests**: 100% pass rate
2. **Integration Tests**: All scenarios pass
3. **RLS Security Tests**: 35+ tests pass
4. **Audit Gate Tests**: 12 tests pass
5. **Golden Dataset Regression**: No drift
6. **Schema Validation**: All schemas valid

### CI Configuration

```yaml
# .github/workflows/pr-guardian.yml (relevant section)

burn_in_gates:
  runs-on: ubuntu-latest
  steps:
    - name: Check change request approved
      run: |
        # Verify change request exists and is approved
        # Fail if no change request for config/contract changes

    - name: Verify version bump
      run: |
        # Check that version was bumped appropriately

    - name: Run full test suite
      run: |
        pytest backend_py/tests/ -v
        pytest backend_py/api/tests/ -v

    - name: Generate evidence pack
      run: |
        python scripts/generate_change_evidence.py
```

---

## Evidence Requirements

Every change during burn-in must produce:

1. **Change Request Document**: `artifacts/changes/CHG-YYYY-NNN.md`
2. **Test Results**: `artifacts/changes/CHG-YYYY-NNN_tests.json`
3. **Before/After Comparison**: Schema diff if applicable
4. **Approval Signatures**: Digital or documented sign-off

### Evidence Pack Structure

```
artifacts/changes/CHG-2026-001/
├── change_request.md
├── test_results.json
├── schema_diff.patch (if applicable)
├── approvals.json
└── deployment_log.txt
```

---

## Exceptions

### Kill Switch

The kill switch can be activated/deactivated without a change request:
- This is an emergency control
- Activation creates an incident automatically
- Deactivation requires documented resolution

### Security Hotfix

S0/S1 security issues can bypass normal change control:
- Must still pass CI gates
- Change request created post-hoc (within 24h)
- Requires security lead sign-off

---

## Post-Burn-In Transition

After successful 30-day burn-in:

1. **Contract Review**: Evaluate frozen contracts for updates
2. **Backlog Triage**: Process deferred changes
3. **Policy Update**: Relax freeze policy to normal change control
4. **Version Planning**: Plan v1.1.0 or v2.0.0 releases

---

## Contacts

| Role | Responsibility |
|------|----------------|
| Platform Lead | Change request approval, version decisions |
| Ops Lead | Operational impact assessment |
| Security Lead | Security hotfix approval |
| Product Owner | Feature prioritization (post-burn-in) |

---

## References

| Document | Purpose |
|----------|---------|
| [VERSIONING.md](../VERSIONING.md) | Version policy |
| [RELEASE.md](../RELEASE.md) | Release process |
| [IMPORT_CONTRACT_ROSTER.md](IMPORT_CONTRACT_ROSTER.md) | Import contract |
| [pilot_kpi_thresholds.json](../config/pilot_kpi_thresholds.json) | KPI config |

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Next Review**: End of burn-in (2026-03-05)
