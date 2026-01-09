# Wien Pilot Go/No-Go Decision Document

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Live Publish Authorization
**Decision Date**: ________________ (TBD)
**Last Updated**: 2026-01-08

---

## Executive Summary

This document defines the criteria, evidence requirements, and decision process for authorizing live publish capability for the Wien Pilot deployment.

**Decision Options**:
- **GO**: Enable publish/lock path for Wien site
- **NO-GO**: Block publish, list blockers with owners and remediation timeline

---

## Decision Criteria

### Mandatory Gates (ALL must PASS)

| # | Gate | Criteria | Evidence Required |
|---|------|----------|-------------------|
| G1 | **Parallel Run Success** | 2+ weeks parallel runs completed with PASS verdict | `parallel_run_W03_evidence.zip`, `parallel_run_W04_evidence.zip` |
| G2 | **Zero Security Incidents** | No S0/S1 security incidents during parallel period | Security incident log (empty or resolved-only) |
| G3 | **SLO Compliance** | All SLO targets met during parallel period | `slo_report_W03.json`, `slo_report_W04.json` |
| G4 | **Audit Pass Rate** | 100% audit pass on both parallel weeks | Audit logs from parallel runs |
| G5 | **Ops Sign-Off** | Operations team confirms readiness | Signed checklist from Ops Lead |
| G6 | **Determinism Verified** | Same input → same output (reproducibility) | Hash comparison logs |
| G7 | **No BLOCK KPI Drift** | KPI drift within WARN thresholds | `kpi_drift_W03.json`, `kpi_drift_W04.json` |

### Advisory Gates (Noted but not blocking)

| # | Gate | Criteria | Notes |
|---|------|----------|-------|
| A1 | **Waiver Count** | All waivers tracked with owners | Per WAIVER_CLOSURE_TRACKER.md |
| A2 | **Runbook Completeness** | All runbooks reviewed by Ops | Sign-off captured |
| A3 | **Training Completion** | Dispatchers trained on publish workflow | Training log |

---

## Evidence Checklist

### Required Artifacts for GO Decision

```
artifacts/go_decision/
├── parallel_runs/
│   ├── W03/
│   │   ├── parallel_run_evidence.zip
│   │   ├── audit_results.json
│   │   ├── kpi_summary.json
│   │   └── slo_metrics.json
│   └── W04/
│       ├── parallel_run_evidence.zip
│       ├── audit_results.json
│       ├── kpi_summary.json
│       └── slo_metrics.json
├── security/
│   ├── incident_log.json          # Should be empty or resolved-only
│   ├── rls_verification.json      # RLS boundary verification
│   └── auth_audit.json            # Authentication audit
├── operations/
│   ├── ops_readiness_checklist.pdf
│   ├── dispatcher_training_log.pdf
│   └── runbook_review_signoff.pdf
└── decision/
    ├── go_no_go_evaluation.json
    └── approval_signatures.pdf
```

---

## Gate Evaluation Details

### G1: Parallel Run Success

**Criteria**: Minimum 2 consecutive weeks of parallel runs with PASS verdict

**Evaluation**:
```markdown
Week 1 (2026-W03):
- [ ] Parallel run executed: scripts/run_parallel_week.py --week 2026-W03
- [ ] Exit code: 0 (PASS) or 1 (WARN acceptable)
- [ ] Coverage: 100%
- [ ] Evidence ZIP generated

Week 2 (2026-W04):
- [ ] Parallel run executed: scripts/run_parallel_week.py --week 2026-W04
- [ ] Exit code: 0 (PASS) or 1 (WARN acceptable)
- [ ] Coverage: 100%
- [ ] Evidence ZIP generated
```

**PASS Condition**: Both weeks exit 0 or 1, coverage 100%
**FAIL Condition**: Any week exits 2, or coverage < 100%

### G2: Zero Security Incidents

**Criteria**: No S0 or S1 security incidents during parallel run period

**Incident Severity Reference**:
- **S0**: Data breach, cross-tenant access, authentication bypass
- **S1**: Failed audit, potential data exposure, RLS violation
- **S2**: Security warning, non-critical vulnerability
- **S3**: Minor security improvement needed

**Evaluation**:
```markdown
- [ ] Security incident log reviewed
- [ ] No S0 incidents recorded: TRUE / FALSE
- [ ] No S1 incidents recorded: TRUE / FALSE
- [ ] All S2/S3 incidents have remediation plan: TRUE / FALSE
```

**PASS Condition**: Zero S0 and S1 incidents
**FAIL Condition**: Any S0 or S1 incident (even if resolved)

### G3: SLO Compliance

**Criteria**: All SLO targets met per docs/SLO_WIEN_PILOT.md

**SLO Targets**:
| Metric | Target | Week 1 Actual | Week 2 Actual |
|--------|--------|---------------|---------------|
| API Uptime | >= 99.5% | ___% | ___% |
| API P95 Latency | < 2s | ___s | ___s |
| Solver P95 Latency | < 30s | ___s | ___s |
| Audit Pass Rate | 100% | ___% | ___% |
| Assignment Churn | < 10% | ___% | ___% |

**PASS Condition**: All targets met both weeks
**FAIL Condition**: Any target missed either week

### G4: Audit Pass Rate

**Criteria**: 100% audit pass on all 7 mandatory checks

**Audit Checks**:
- [ ] Coverage: 100% tours assigned
- [ ] Overlap: No driver works concurrent tours
- [ ] Rest: >= 11h between consecutive days
- [ ] Span Regular: <= 14h for regular blocks
- [ ] Span Split: <= 16h for split/3er, 240-360min break
- [ ] Fatigue: No consecutive 3er → 3er
- [ ] Reproducibility: Same input → same output hash

**PASS Condition**: All 7 checks PASS both weeks
**FAIL Condition**: Any check FAIL either week

### G5: Operations Sign-Off

**Criteria**: Operations team confirms readiness for live publish

**Checklist** (Ops Lead to complete):
```markdown
- [ ] Runbooks reviewed and understood
- [ ] Escalation paths tested
- [ ] Rollback procedure practiced
- [ ] Monitoring dashboards configured
- [ ] On-call rotation established
- [ ] Communication channels confirmed
- [ ] Manual override procedures documented
```

**Sign-Off**:
- Ops Lead Name: _______________
- Date: _______________
- Signature: _______________

### G6: Determinism Verified

**Criteria**: Same input with same seed produces identical output hash

**Verification**:
```bash
# Run 1
python scripts/run_parallel_week.py --week 2026-W03 --seed 94
# Record output_hash_1

# Run 2 (same input, same seed)
python scripts/run_parallel_week.py --week 2026-W03 --seed 94
# Record output_hash_2

# Verify
output_hash_1 == output_hash_2
```

**PASS Condition**: Hashes match for both weeks
**FAIL Condition**: Hash mismatch indicates non-determinism

### G7: KPI Drift Within Thresholds

**Criteria**: No BLOCK-level KPI drift per config/pilot_kpi_thresholds.json

**KPI Thresholds**:
| KPI | WARN Threshold | BLOCK Threshold | Week 1 | Week 2 |
|-----|----------------|-----------------|--------|--------|
| Headcount | +/- 5% | +/- 10% | ___% | ___% |
| Coverage | < 99.5% | < 99% | ___% | ___% |
| FTE Ratio | < 95% | < 90% | ___% | ___% |
| Churn | > 10% | > 20% | ___% | ___% |
| Runtime | > 30s | > 60s | ___s | ___s |

**PASS Condition**: All KPIs within WARN threshold or better
**FAIL Condition**: Any KPI in BLOCK range

---

## Decision Matrix

### Automated Evaluation

```python
# Pseudo-code for automated evaluation
def evaluate_go_decision(evidence_path: str) -> GoDecision:
    gates = {
        "G1_parallel_runs": check_parallel_runs(evidence_path),
        "G2_security": check_security_incidents(evidence_path),
        "G3_slo": check_slo_compliance(evidence_path),
        "G4_audit": check_audit_pass_rate(evidence_path),
        "G5_ops_signoff": check_ops_signoff(evidence_path),
        "G6_determinism": check_determinism(evidence_path),
        "G7_kpi_drift": check_kpi_drift(evidence_path),
    }

    all_pass = all(g["status"] == "PASS" for g in gates.values())

    if all_pass:
        return GoDecision(
            verdict="GO",
            action="Enable publish/lock path for Wien site",
            gates=gates
        )
    else:
        failed = [k for k, v in gates.items() if v["status"] == "FAIL"]
        return GoDecision(
            verdict="NO-GO",
            action="Block publish, remediate blockers",
            blockers=failed,
            gates=gates
        )
```

### Decision Outcomes

#### GO Decision

**Verdict**: GO
**Action**: Enable publish/lock path for Wien site

**What happens**:
1. Wien site (`wien_pilot`) is marked as `publish_enabled = TRUE`
2. Dispatchers can use the Lock endpoint to finalize plans
3. Evidence pack is archived for compliance
4. 30-day burn-in period begins with heightened monitoring

**Post-GO Monitoring**:
- Daily KPI review for first 2 weeks
- Weekly review thereafter
- Immediate escalation on any S0/S1 incident

#### NO-GO Decision

**Verdict**: NO-GO
**Action**: Block publish, list blockers with owners

**Blocker Template**:
| # | Gate | Blocker Description | Owner | Target Date |
|---|------|---------------------|-------|-------------|
| 1 | ___ | ___________________ | _____ | __________ |
| 2 | ___ | ___________________ | _____ | __________ |

**Re-Evaluation**:
- Schedule follow-up review after blockers resolved
- Minimum 1 additional week parallel run required
- All gates must re-pass

---

## Approval Process

### Step 1: Evidence Collection

```bash
# Collect all evidence
python scripts/collect_go_evidence.py --output artifacts/go_decision/
```

### Step 2: Automated Evaluation

```bash
# Run automated checks
python scripts/evaluate_go_decision.py --evidence artifacts/go_decision/
```

### Step 3: Human Review

**Review Meeting Participants**:
- Product Owner
- Platform Engineering Lead
- Operations Lead
- Security Representative (if applicable)

**Agenda**:
1. Review automated evaluation results (10 min)
2. Walk through evidence artifacts (20 min)
3. Discuss any WARN conditions (10 min)
4. Address open waivers (10 min)
5. Make GO/NO-GO decision (10 min)

### Step 4: Sign-Off

**For GO Decision**:

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | ____________ | ______ | __________ |
| Platform Lead | ____________ | ______ | __________ |
| Operations Lead | ____________ | ______ | __________ |

**For NO-GO Decision**:

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | ____________ | ______ | __________ |
| Re-Evaluation Date: ______ | | | |

---

## Current Status

### Gate Status (Pre-Evaluation)

| Gate | Status | Notes |
|------|--------|-------|
| G1 | PENDING | Awaiting parallel runs (2026-W03, 2026-W04) |
| G2 | PENDING | Awaiting parallel period completion |
| G3 | PENDING | Awaiting SLO data |
| G4 | PENDING | Awaiting audit results |
| G5 | PENDING | Awaiting Ops review |
| G6 | PENDING | Awaiting determinism verification |
| G7 | PENDING | Awaiting KPI data |

### Open Waivers

| Waiver ID | Description | Owner | Expiry |
|-----------|-------------|-------|--------|
| WAV-2026-001 | OSRM Routing Parked | Platform Lead | 2026-03-31 |
| WAV-2026-002 | No Real Customer Data | Product Owner | 2026-02-15 |

**Note**: Open waivers do not block GO decision if:
1. Waiver is explicitly acknowledged by all approvers
2. Waiver has defined closure path with owner
3. Waiver expiry is tracked in WAIVER_CLOSURE_TRACKER.md

---

## Timeline

### Planned Schedule

| Phase | Date | Activity |
|-------|------|----------|
| P1 | 2026-W03 (Jan 13-19) | First parallel run week |
| P2 | 2026-W04 (Jan 20-26) | Second parallel run week |
| P3 | 2026-01-27 | Evidence collection deadline |
| P4 | 2026-01-28 | Go/No-Go review meeting |
| P5 | 2026-01-29 | Decision finalized |
| P6 | 2026-02-03 | GO: Publish enabled (if approved) |

### Re-Evaluation Schedule (if NO-GO)

| Event | Date |
|-------|------|
| Blockers remediated | TBD + 1 week |
| Additional parallel run | TBD + 2 weeks |
| Re-evaluation meeting | TBD + 2.5 weeks |

---

## Appendix A: Evidence Artifact Schemas

### go_no_go_evaluation.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["evaluation_date", "gates", "verdict", "approvers"],
  "properties": {
    "evaluation_date": {
      "type": "string",
      "format": "date-time"
    },
    "gates": {
      "type": "object",
      "properties": {
        "G1_parallel_runs": { "$ref": "#/definitions/gate_result" },
        "G2_security": { "$ref": "#/definitions/gate_result" },
        "G3_slo": { "$ref": "#/definitions/gate_result" },
        "G4_audit": { "$ref": "#/definitions/gate_result" },
        "G5_ops_signoff": { "$ref": "#/definitions/gate_result" },
        "G6_determinism": { "$ref": "#/definitions/gate_result" },
        "G7_kpi_drift": { "$ref": "#/definitions/gate_result" }
      }
    },
    "verdict": {
      "type": "string",
      "enum": ["GO", "NO-GO"]
    },
    "blockers": {
      "type": "array",
      "items": { "$ref": "#/definitions/blocker" }
    },
    "waivers_acknowledged": {
      "type": "array",
      "items": { "type": "string" }
    },
    "approvers": {
      "type": "array",
      "items": { "$ref": "#/definitions/approver" }
    }
  },
  "definitions": {
    "gate_result": {
      "type": "object",
      "required": ["status", "evidence_path"],
      "properties": {
        "status": { "enum": ["PASS", "FAIL", "PENDING"] },
        "evidence_path": { "type": "string" },
        "notes": { "type": "string" }
      }
    },
    "blocker": {
      "type": "object",
      "required": ["gate", "description", "owner", "target_date"],
      "properties": {
        "gate": { "type": "string" },
        "description": { "type": "string" },
        "owner": { "type": "string" },
        "target_date": { "type": "string", "format": "date" }
      }
    },
    "approver": {
      "type": "object",
      "required": ["role", "name", "approved", "date"],
      "properties": {
        "role": { "type": "string" },
        "name": { "type": "string" },
        "approved": { "type": "boolean" },
        "date": { "type": "string", "format": "date" }
      }
    }
  }
}
```

---

## Appendix B: Quick Reference Commands

```bash
# Run parallel week
python scripts/run_parallel_week.py --input roster.json --week 2026-W03 --tenant wien_pilot

# Collect evidence
python scripts/collect_go_evidence.py --output artifacts/go_decision/

# Evaluate decision (automated)
python scripts/evaluate_go_decision.py --evidence artifacts/go_decision/

# Generate approval document
python scripts/generate_approval_doc.py --evidence artifacts/go_decision/ --output approval.pdf
```

---

## References

| Document | Purpose |
|----------|---------|
| [GA_READINESS_REPORT.md](GA_READINESS_REPORT.md) | GA readiness assessment |
| [WAIVER_CLOSURE_TRACKER.md](WAIVER_CLOSURE_TRACKER.md) | Open waiver tracking |
| [SLO_WIEN_PILOT.md](SLO_WIEN_PILOT.md) | SLO targets and definitions |
| [RUNBOOK_OPERATIONS_CADENCE.md](../RUNBOOK_OPERATIONS_CADENCE.md) | Operations schedule |
| [DISPATCHER_CHECKLIST.md](DISPATCHER_CHECKLIST.md) | Dispatcher quick reference |

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Next Review**: After parallel runs complete (2026-01-27)
