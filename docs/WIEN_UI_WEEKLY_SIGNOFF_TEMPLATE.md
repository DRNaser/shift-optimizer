# Wien UI Weekly Sign-Off

> **Site**: Wien
> **Week**: 2026-W__
> **Date**: _______________
> **Phase**: Gate 3 - Wien Dispatchers Live

---

## Weekly Summary

| Metric | Value |
|--------|-------|
| Runs processed via UI | |
| Runs published via UI | |
| Runs locked via UI | |
| Repair requests submitted | |
| CLI fallback used | [ ] Yes [ ] No |
| Incidents | |
| Gate bypasses | 0 (required) |
| Missing artifacts | 0 (required) |

---

## Dispatcher Feedback

### Usability
| Question | Rating (1-5) | Comments |
|----------|--------------|----------|
| UI is easy to navigate | | |
| Actions are clearly labeled | | |
| Status is easy to understand | | |
| Errors are helpful | | |
| Overall satisfaction | | |

### Time Comparison
| Action | CLI (avg) | UI (avg) | Time Saved |
|--------|-----------|----------|------------|
| List runs | | | |
| Review run detail | | | |
| Publish | | | |
| Lock | | | |
| Submit repair | | | |

### Issues Reported
| Issue | Frequency | Impact | Resolution |
|-------|-----------|--------|------------|
| | | | |

---

## Weekly Flow Execution

### Monday: Forecast Ingestion
| Check | Result | Notes |
|-------|--------|-------|
| Forecast uploaded | [ ] Via API [ ] Via UI | |
| Status visible in UI | [ ] Pass [ ] Fail | |

### Tuesday: Solver Run + Review
| Check | Result | Notes |
|-------|--------|-------|
| Run visible in list | [ ] Pass [ ] Fail | |
| Audits displayed | [ ] Pass [ ] Fail | |
| KPIs accurate | [ ] Pass [ ] Fail | |

### Tuesday: Publish
| Run ID | Approver | Time | Status |
|--------|----------|------|--------|
| | | | [ ] Success [ ] Fail |

### Tuesday: Lock
| Run ID | Approver | Time | Status |
|--------|----------|------|--------|
| | | | [ ] Success [ ] Fail |

### Wednesday-Sunday: Operational Period
| Day | Repairs Submitted | Issues |
|-----|-------------------|--------|
| Wed | | |
| Thu | | |
| Fri | | |
| Sat | | |
| Sun | | |

---

## Gate Enforcement Verification

### Kill Switch
| Test | Result |
|------|--------|
| Kill switch OFF during week | [ ] Verified |
| If ON, actions blocked correctly | [ ] N/A [ ] Verified |

### Site Gate
| Test | Result |
|------|--------|
| Only Wien enabled | [ ] Verified |
| Non-Wien attempts blocked | [ ] N/A [ ] Verified |

### Approval Gate
| Test | Result |
|------|--------|
| All publishes have reason >= 10 chars | [ ] Verified |
| All locks have reason >= 10 chars | [ ] Verified |
| Approver ID logged correctly | [ ] Verified |

---

## Artifact Verification

### Evidence Packs
| Run ID | Evidence Hash | Downloaded | Verified |
|--------|---------------|------------|----------|
| | | [ ] | [ ] |

### Audit Trail
| Run ID | Publish Logged | Lock Logged | Repairs Logged |
|--------|----------------|-------------|----------------|
| | [ ] | [ ] | [ ] |

---

## Monitoring Metrics

| Metric | This Week | Last Week | Trend |
|--------|-----------|-----------|-------|
| UI page loads | | | |
| UI publish attempts | | | |
| UI lock attempts | | | |
| 401 errors | | | |
| 403 errors (gates) | | | |
| 5xx errors | | | |

---

## Incidents

| ID | Time | Description | Impact | Resolution |
|----|------|-------------|--------|------------|
| | | | | |

**Total incidents**: _____
**Incidents requiring CLI fallback**: _____

---

## Dispatcher Attestation

I confirm that:
- [ ] All weekly operations were completed successfully
- [ ] No gate bypasses occurred
- [ ] All artifacts are present and verified
- [ ] No unauthorized actions were attempted

**Dispatcher**: _______________
**Date**: _______________
**Signature**: _______________

---

## Platform Team Review

| Check | Result | Reviewer |
|-------|--------|----------|
| Audit events match UI actions | [ ] | |
| Evidence hashes consistent | [ ] | |
| No security anomalies | [ ] | |
| Monitoring healthy | [ ] | |

**Platform Reviewer**: _______________
**Date**: _______________

---

## Sign-Off

### Weekly Approval
| Role | Name | Date | Result |
|------|------|------|--------|
| Dispatcher | | | [ ] Approved |
| Ops Lead | | | [ ] Approved |
| Platform Lead | | | [ ] Approved |

---

## Action Items for Next Week

| Item | Owner | Due |
|------|-------|-----|
| | | |

---

## Cumulative Metrics (Since UI Rollout)

| Metric | Total |
|--------|-------|
| Weeks on UI | |
| Total runs via UI | |
| Total CLI fallbacks | |
| Total incidents | |
| Gate bypass attempts | 0 (required) |

---

**Document Created**: _______________
**Last Updated**: _______________
