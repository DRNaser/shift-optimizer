---
name: Release Checklist
about: Production deployment checklist for SOLVEREIGN releases
title: 'Release: vX.Y.Z'
labels: 'release'
assignees: ''
---

## Release Information

- **Version**: vX.Y.Z
- **Date**: YYYY-MM-DD
- **Release Manager**: @username
- **Runbook**: [docs/DEPLOYMENT_RUNBOOK.md](/docs/DEPLOYMENT_RUNBOOK.md)

## Runbook Cross-Reference

| Checklist Section | Runbook Section |
|-------------------|-----------------|
| Migrations | Section A: Database Migrations |
| Staging Verification | Section C: Deploy Backend, Section D: Common Pitfalls |
| Environment Configuration | Section B: Environment Variables |
| Go/No-Go Decision | Go/No-Go Checklist (10 Points) |
| Deployment Steps | Sections C, D, E |
| Post-Deployment | Observability "Done" Criteria |
| Rollback Plan | Quick Rollback Plan |

## Pre-Deployment Checklist

### Migrations

- [ ] All migrations applied to staging
- [ ] `SELECT * FROM auth.verify_legal_acceptance_integrity()` - All PASS
- [ ] `SELECT * FROM billing.verify_billing_schema()` - All PASS
- [ ] `SELECT * FROM consent.verify_consent_schema()` - All PASS
- [ ] `SELECT * FROM verify_final_hardening()` - All 17 checks PASS

### Staging Verification

- [ ] App boots clean (`kubectl logs deployment/api` - no errors)
- [ ] Sentry test error visible in dashboard
- [ ] Stripe webhook test passed (`stripe trigger invoice.paid`)
- [ ] Webhook idempotency verified (send 3x, 1 DB record)
- [ ] Billing gating test passed (tenant status → 402 response)
- [ ] Backup job ran successfully
- [ ] **Backup restore verified** (weekly CronJob or manual test)
- [ ] Grafana dashboard shows live data
- [ ] Legal pages accessible (`/legal/terms`, `/legal/privacy`, `/legal/imprint`)

### Environment Configuration

- [ ] All secrets configured in production:
  - [ ] `SOLVEREIGN_SENTRY_DSN`
  - [ ] `SOLVEREIGN_STRIPE_API_KEY`
  - [ ] `SOLVEREIGN_STRIPE_WEBHOOK_SECRET`
  - [ ] `BACKUP_S3_BUCKET`
  - [ ] AWS credentials for backups
- [ ] `stripe` Python package installed (webhooks return 503 if missing)
- [ ] Stripe webhook URL configured in Stripe Dashboard
- [ ] `SOLVEREIGN_BILLING_ENFORCEMENT=on` (not off!)

## Go/No-Go Decision

> Matches [DEPLOYMENT_RUNBOOK.md - Go/No-Go Checklist](/docs/DEPLOYMENT_RUNBOOK.md#gono-go-checklist-10-points)

| # | Check | Command/Action | Expected | Status |
|---|-------|----------------|----------|--------|
| 1 | Migrations applied | `SELECT * FROM billing.verify_billing_schema()` | All PASS | ⬜ |
| 2 | App boots clean | `kubectl logs deployment/api` | No errors | ⬜ |
| 3 | Stripe webhook verified | `stripe trigger invoice.paid` | 200 OK, DB updated | ⬜ |
| 4 | Webhook idempotent | Send same event 3x | Only 1 DB record | ⬜ |
| 5 | Billing gating works | Set tenant to `past_due`, call API | 402 response | ⬜ |
| 6 | Sentry sees errors | Trigger test error | Issue in Sentry | ⬜ |
| 7 | Backup runs | Manual trigger | S3 file created | ⬜ |
| 8 | **Restore works** | Restore to test DB | App starts | ⬜ |
| 9 | Grafana shows data | Open dashboard | All panels populated | ⬜ |
| 10 | Legal pages accessible | Visit `/legal/terms` | Page loads | ⬜ |

**All 10 must pass before production deployment.**

## Deployment Steps

1. [ ] Create release tag: `git tag vX.Y.Z && git push --tags`
2. [ ] Deploy migrations to production
3. [ ] Deploy backend: `kubectl set image deployment/api api=ghcr.io/solvereign/api:vX.Y.Z`
4. [ ] Verify backend logs
5. [ ] Deploy frontend (Vercel auto-deploy or manual)
6. [ ] Verify frontend routes
7. [ ] Deploy backup CronJob (if updated)
8. [ ] Smoke test production endpoints

## Post-Deployment Verification

- [ ] Health check returns 200
- [ ] Login flow works
- [ ] One API request completes successfully
- [ ] No new errors in Sentry (first 15 minutes)
- [ ] Grafana metrics flowing

## Rollback Plan

If issues detected:

1. Backend: `kubectl rollout undo deployment/api`
2. Frontend: `vercel rollback`
3. If billing issues: `SOLVEREIGN_BILLING_ENFORCEMENT=off` (temporary!)
4. Notify team in #releases channel

## Sign-Off

- [ ] Release Manager: @username
- [ ] QA: @username (optional)
- [ ] Product: @username (optional)

---

**Release Notes**: (Link to changelog or release notes)

**Related PRs**: #PR1, #PR2

**Post-Release Tasks**:
- [ ] Update CLAUDE.md version
- [ ] Close related issues
- [ ] Announce in #releases
