# Multi-Site Onboarding Plan

**System**: SOLVEREIGN V3.7
**Scope**: LTS Second Site Expansion
**Status**: Planning
**Last Updated**: 2026-03-05

---

## Overview

This document outlines the plan to onboard a second LTS site using the proven Wien Pilot gates. The goal is to demonstrate multi-site capability under the same tenant with minimal risk.

---

## Candidate Sites

| Site | Location | Fleet Size | Complexity | Risk Level |
|------|----------|------------|------------|------------|
| **Graz** | Styria | ~80 drivers | Medium | Low |
| **Linz** | Upper Austria | ~120 drivers | High | Medium |
| **Salzburg** | Salzburg | ~60 drivers | Low | Low |

**Recommended**: Graz (medium fleet, low risk, good geographic diversity)

---

## Onboarding Approach

### Phase 1: Site Assessment (Week 1)

| Task | Owner | Deliverable |
|------|-------|-------------|
| Obtain site roster sample | Product Owner | graz_roster_sample.json |
| Validate against import contract | Platform Eng | validation_report_graz.json |
| Identify site-specific rules | Ops Lead | graz_site_config.json |
| Estimate KPI baselines | Platform Eng | graz_kpi_baseline.json |

### Phase 2: Shadow Mode (Weeks 2-3)

| Task | Owner | Deliverable |
|------|-------|-------------|
| Enable site in shadow mode | Platform Eng | config update |
| Run parallel week 1 | Ops Lead | graz_parallel_W09.zip |
| Run parallel week 2 | Ops Lead | graz_parallel_W10.zip |
| Compare with manual process | Product Owner | comparison_report.md |

### Phase 3: Go/No-Go (Week 4)

| Task | Owner | Deliverable |
|------|-------|-------------|
| Review parallel results | All | review_meeting_notes.md |
| Assess KPI alignment | Platform Eng | kpi_alignment_report.json |
| Gate approval (mini GA review) | Platform Lead | GRAZ_GO_NO_GO.md |

### Phase 4: Live Enable (Week 5)

| Task | Owner | Deliverable |
|------|-------|-------------|
| Enable publish/lock for Graz | Platform Eng | config update |
| First live week | Ops Lead | graz_live_W11.zip |
| Monitor drift | Platform Eng | drift_report.json |

---

## Gate Reuse Matrix

| Wien Gate | Graz Equivalent | Status |
|-----------|-----------------|--------|
| Gate AE (Go-Live Checklist) | Reuse as-is | Ready |
| Gate AF (Burn-In Reporting) | Reuse with site param | Ready |
| Gate AG (Fire Drill) | Reuse as-is | Ready |
| Gate AH-AK (Multi-Week) | Abbreviated (2 weeks) | Modified |

---

## Configuration Requirements

### Site Enablement Config

Add to `config/enable_publish_lock_wien.json`:

```json
{
  "site_overrides": {
    "wien_pilot": { ... },
    "graz_pilot": {
      "tenant_code": "lts",
      "site_code": "graz",
      "pack": "roster",
      "publish_enabled": false,
      "lock_enabled": false,
      "shadow_mode_only": true,
      "require_human_approval": true,
      "approval_config": {
        "min_approvers": 1,
        "allowed_approver_roles": ["dispatcher", "ops_lead", "platform_admin"],
        "require_reason": true,
        "min_reason_length": 10
      },
      "effective_date": "2026-03-10",
      "notes": "Graz pilot - shadow mode initially"
    }
  }
}
```

### KPI Thresholds (Graz-Specific)

Create `config/graz_kpi_thresholds.json`:

```json
{
  "tenant_code": "graz_pilot",
  "baselines": {
    "headcount": 80,
    "avg_hours_per_driver": 42,
    "fte_ratio": 0.95,
    "pt_ratio": 0.05
  },
  "thresholds": {
    "headcount": { "warn_percent": 5, "block_percent": 10 },
    "coverage": { "warn_threshold": 99.5, "block_threshold": 99.0 }
  }
}
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Different labor rules | Verify with legal before go-live |
| Different depot structure | Map in master data before shadow |
| Different shift patterns | Validate import contract covers patterns |
| Resource contention | Use separate advisory lock keys per site |

---

## Success Criteria

### Shadow Mode Exit Criteria

- [ ] 2 weeks parallel runs with PASS verdict
- [ ] KPI drift within thresholds
- [ ] No site-specific blockers identified
- [ ] Ops team trained on Graz workflow

### Live Enable Criteria

- [ ] Shadow criteria met
- [ ] Mini GA review PASS
- [ ] Platform Lead approval
- [ ] Kill switch tested for Graz

---

## Timeline

| Week | Phase | Milestone |
|------|-------|-----------|
| W09 | Assessment | Site config complete |
| W10 | Shadow | Parallel week 1 |
| W11 | Shadow | Parallel week 2 |
| W12 | Review | Go/No-Go decision |
| W13 | Live | First live week (if GO) |

---

## Deliverables

### Assessment Phase
- `config/graz_site_config.json`
- `config/graz_kpi_thresholds.json`
- `docs/GRAZ_SITE_ASSESSMENT.md`

### Shadow Phase
- `artifacts/graz_parallel_W10/`
- `artifacts/graz_parallel_W11/`
- `docs/GRAZ_PARALLEL_COMPARISON.md`

### Live Phase
- `artifacts/live_graz_week_W13/`
- `docs/GRAZ_WEEKLY_SIGNOFF_W13.md`

---

## Commands Reference

```bash
# Validate Graz roster
python scripts/validate_import_contract.py --input graz_roster.json

# Run Graz parallel week
python scripts/run_parallel_week.py --input graz_roster.json --week 2026-W10 --tenant lts --site graz

# Dispatcher CLI for Graz
python scripts/dispatcher_cli.py --site graz list-runs
python scripts/dispatcher_cli.py --site graz status
```

---

## Sign-Off

| Role | Name | Date |
|------|------|------|
| Product Owner | ____________ | ______ |
| Platform Lead | ____________ | ______ |
| Ops Lead | ____________ | ______ |

---

**Document Version**: 1.0

**Last Updated**: 2026-03-05

**Next Review**: After site assessment (W09)
