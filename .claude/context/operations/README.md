# Operations Branch - Router Checklist

> **Purpose**: Deployment, rollback, tenant onboarding, and release management
> **Severity Default**: S3 - Follow procedures carefully

---

## ENTRY CHECKLIST

Before proceeding, answer these questions:

1. **Is this an emergency rollback?**
   - YES → Read `rollback-procedures.md` IMMEDIATELY
   - NO → Continue

2. **Are you deploying to production?**
   - YES → Read `deployment-checklist.md`
   - NO → Continue

3. **Are you onboarding a new tenant?**
   - YES → Read `tenant-onboarding.md`
   - NO → Continue

4. **Do you need to generate audit reports?**
   - YES → Read `audit-report-gen.md`
   - NO → Use general operations guidance below

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `deployment-checklist.md` | Production deployment procedures | Any deploy |
| `rollback-procedures.md` | Emergency rollback steps | Deployment failure |
| `tenant-onboarding.md` | New tenant setup gates | Onboarding |
| `audit-report-gen.md` | Enterprise audit pack generation | Customer audits |

---

## DEPLOYMENT CHECKLIST (QUICK VERSION)

### Pre-Deploy
- [ ] All tests pass (`python -m pytest backend_py/`)
- [ ] Migrations tested on staging
- [ ] Health probes verified
- [ ] Rollback plan documented
- [ ] Stakeholders notified

### Deploy
- [ ] Apply migrations in order
- [ ] Deploy new pods
- [ ] Verify health probes pass
- [ ] Run smoke tests

### Post-Deploy
- [ ] Update `last-known-good.json`
- [ ] Verify KPI baselines
- [ ] Monitor for 30min
- [ ] Announce completion

---

## TENANT ONBOARDING GATES

| Gate | Description | Required |
|------|-------------|----------|
| 1 | RLS Harness Pass | YES |
| 2 | Determinism Proof | YES |
| 3 | Golden Path E2E | YES |
| 4 | Integrations Contract | YES |

**Rule**: ALL 4 gates must PASS before tenant goes live.

```bash
# Run onboarding validation
python -m backend_py.tools.onboarding_contract validate --tenant <code>
```

---

## ROLLBACK QUICK REFERENCE

### Emergency Rollback (< 5min)

```bash
# 1. Revert to previous deployment
kubectl rollout undo deployment/solvereign-api

# 2. Verify health
curl http://localhost:8000/health/ready

# 3. If DB migration was applied, check rollback script
psql solvereign < backend_py/db/migrations/NNN_rollback.sql
```

### Planned Rollback

1. Read `rollback-procedures.md` fully
2. Notify stakeholders
3. Create incident record
4. Execute rollback
5. Verify health
6. Document lessons learned

---

## LAST KNOWN GOOD STATE

Location: `.claude/state/last-known-good.json`

```json
{
  "git_sha": "a8005c2",
  "migrations_version": "023_policy_profiles",
  "config_hash": "sha256:abc123...",
  "timestamp": "2026-01-07T10:30:00Z",
  "all_tests_pass": true,
  "health_status": "healthy"
}
```

**Rule**: Update this after EVERY successful production deploy.

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Deploy failed, rollback needed | S2 | Execute rollback. Create incident. |
| Health probes failing post-deploy | S2 | Rollback. Investigate. |
| Tenant onboarding gate failed | S3 | Block go-live. Fix issues first. |
| Missing rollback script | S3 | Create before deploying. |
| LKG state outdated | S4 | Update after next successful deploy. |

---

## RELATED BRANCHES

- Incident during deploy? → `stability/incident-triage.md`
- Security review needed? → `security/rls-enforcement.md`
- Performance concerns? → `performance/capacity-planning.md`
