# Go-Live Execution Checklist - Wien Pilot

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Day-0 Go-Live
**Version**: 1.0.0

---

## Pre-Execution Requirements

Before starting the go-live checklist:

- [ ] Go/No-Go decision documented and approved (WIEN_GO_NO_GO.md)
- [ ] All mandatory gates G1-G7 PASS
- [ ] Open waivers acknowledged by approvers
- [ ] On-call rotation confirmed
- [ ] Communication channels verified

---

## Phase 1: Preflight (T-30min)

### 1.1 System Status Check

```bash
# Check overall system status
python scripts/dispatcher_cli.py status
```

**Expected output**:
- Kill Switch: ✅ Inactive
- Publish Enabled: ✅ Yes
- Lock Enabled: ✅ Yes
- Shadow Mode: ✅ Disabled

**Record**:
- [ ] Status check timestamp: ______________
- [ ] Kill switch status: ______________
- [ ] Publish enabled: ______________

### 1.2 Production Preflight

```bash
# Run preflight checks
python scripts/prod_preflight_check.py --tenant lts --site wien
```

**Expected output**:
- All checks PASS
- Database connectivity OK
- API health OK
- RLS verification OK

**Record**:
- [ ] Preflight timestamp: ______________
- [ ] All checks passed: Yes / No
- [ ] If No, list failures: ______________

### 1.3 Contract Version Verification

```bash
# Verify frozen contract versions
cat config/contract_versions.json | python -c "import sys,json; d=json.load(sys.stdin); print('Import Contract:', d['contracts']['import_contract_roster']['version']); print('KPI Thresholds:', d['contracts']['kpi_thresholds']['version'])"
```

**Expected**:
- Import Contract: 1.0.0
- KPI Thresholds: 1.0.0

**Record**:
- [ ] Import contract version: ______________
- [ ] KPI thresholds version: ______________

---

## Phase 2: Ingest + Solve (T-0)

### 2.1 Input Validation

```bash
# Validate input roster
python scripts/validate_import_contract.py --input <roster_file.json>
```

**Expected**:
- Exit code 0 (PASS) or 1 (WARN acceptable)
- All hard gates pass
- Soft gate warnings documented

**Record**:
- [ ] Input file: ______________
- [ ] Validation exit code: ______________
- [ ] Hard gates passed: ______________/8
- [ ] Soft gate warnings: ______________

### 2.2 Solver Execution

```bash
# Run parallel week (produces run artifacts)
python scripts/run_parallel_week.py --input <roster_file.json> --week 2026-W03 --tenant lts --site wien
```

**Expected**:
- Exit code 0 (PASS) or 1 (WARN)
- Run ID generated
- Evidence pack created

**Record**:
- [ ] Run start timestamp: ______________
- [ ] Run ID: ______________
- [ ] Exit code: ______________
- [ ] Evidence path: ______________

---

## Phase 3: Review (T+15min)

### 3.1 Run Details Review

```bash
# Show run details
python scripts/dispatcher_cli.py show-run <run_id>
```

**Verify**:
- [ ] Status: PASS (or WARN with documented reason)
- [ ] Coverage: 100%
- [ ] Audits: 7/7 PASS
- [ ] KPI Drift: OK or WARN (not BLOCK)

**Record**:
| KPI | Value | Expected | Status |
|-----|-------|----------|--------|
| Headcount | _____ | ~145 | ✅/⚠️/❌ |
| Coverage | _____% | 100% | ✅/⚠️/❌ |
| FTE Ratio | _____% | 100% | ✅/⚠️/❌ |
| PT Ratio | _____% | 0% | ✅/⚠️/❌ |
| Runtime | _____s | <30s | ✅/⚠️/❌ |

### 3.2 Audit Summary Verification

All 7 audits must PASS:

- [ ] Coverage: 100% tours assigned
- [ ] Overlap: No concurrent tours
- [ ] Rest: >=11h between days
- [ ] Span Regular: <=14h
- [ ] Span Split: <=16h, 240-360min break
- [ ] Fatigue: No 3er→3er
- [ ] Reproducibility: Deterministic

**If any FAIL**: STOP. Do not proceed to publish.

---

## Phase 4: Approval (T+20min)

### 4.1 Collect Approval

**Approver Information**:
- Approver ID: ______________
- Approver Role: [ ] dispatcher [ ] ops_lead [ ] platform_admin
- Approval Reason (min 10 chars):
  ```
  _______________________________________________________________
  _______________________________________________________________
  ```

### 4.2 Approval Verification

Verify approval meets requirements:
- [ ] Approver ID provided
- [ ] Approver role is allowed (dispatcher, ops_lead, or platform_admin)
- [ ] Reason is at least 10 characters
- [ ] Reason documents review completion

---

## Phase 5: Publish (T+25min)

### 5.1 Execute Publish

```bash
# Publish with approval
python scripts/dispatcher_cli.py publish <run_id> \
  --approver <approver_id> \
  --role <approver_role> \
  --reason "<approval_reason>"
```

**Expected output**:
- ✅ PUBLISH APPROVED
- Audit Event ID generated
- Evidence hash linked

**Record**:
- [ ] Publish timestamp: ______________
- [ ] Audit event ID: ______________
- [ ] Evidence hash: ______________
- [ ] Exit code: ______________

### 5.2 Verify Publish Gate

**If blocked**:
- [ ] Note blocked reason: ______________
- [ ] Escalate to platform lead if unexpected

---

## Phase 6: Lock (T+30min)

### 6.1 Execute Lock

```bash
# Lock for export
python scripts/dispatcher_cli.py lock <run_id> \
  --approver <approver_id> \
  --role <approver_role> \
  --reason "<lock_reason>"
```

**Expected output**:
- 🔒 PLAN LOCKED
- Audit Event ID generated
- Plan is immutable

**Record**:
- [ ] Lock timestamp: ______________
- [ ] Audit event ID: ______________
- [ ] Exit code: ______________

### 6.2 Verify Lock Status

```bash
# Verify plan is locked
python scripts/dispatcher_cli.py show-run <run_id>
```

- [ ] Plan shows locked=true
- [ ] locked_by matches approver_id
- [ ] locked_at timestamp recorded

---

## Phase 7: Evidence Pack (T+35min)

### 7.1 Export Evidence

```bash
# Export evidence pack
python scripts/export_evidence_pack.py --run-id <run_id> --output artifacts/live_wien_week_W03/
```

**Or manually collect**:
```bash
# Copy evidence files
cp -r runs/<run_id>/* artifacts/live_wien_week_W03/
```

### 7.2 Generate Checksums

```bash
# Generate SHA256 checksums
cd artifacts/live_wien_week_W03/
sha256sum * > checksums.sha256
```

### 7.3 Evidence Pack Contents

Verify all required files present:

- [ ] run_summary.json
- [ ] audit_results.json
- [ ] kpi_summary.json
- [ ] evidence.zip
- [ ] checksums.sha256
- [ ] approval_record.json
- [ ] lock_record.json

### 7.4 Evidence Pack Structure

```
artifacts/live_wien_week_W03/
├── run_summary.json
├── audit_results.json
├── kpi_summary.json
├── evidence.zip
├── checksums.sha256
├── approval_record.json
├── lock_record.json
└── export/
    └── [exported schedule files]
```

---

## Phase 8: Final Verification (T+40min)

### 8.1 Evidence Hash Verification

```bash
# Verify checksums
cd artifacts/live_wien_week_W03/
sha256sum -c checksums.sha256
```

- [ ] All checksums match

### 8.2 Audit Trail Verification

Verify audit events exist:
- [ ] PUBLISH_APPROVED event
- [ ] LOCK_COMPLETED event
- [ ] Evidence hash in both events

### 8.3 Kill Switch Test (Safe Mode)

**Test rollback capability** (use blocked site, not Wien):

```bash
# Test on non-Wien site (should already be blocked)
python scripts/dispatcher_cli.py --site munich publish TEST-001 \
  --approver test_user \
  --role dispatcher \
  --reason "Testing block for non-Wien site"
```

**Expected**: BLOCKED (Site is in shadow-only mode)

- [ ] Non-Wien site correctly blocked
- [ ] Kill switch not needed for this test

---

## Sign-Off

### Execution Complete

- [ ] All phases completed successfully
- [ ] Evidence pack stored in retention path
- [ ] No FAIL audits
- [ ] Publish + Lock succeeded for Wien only
- [ ] Evidence hash matches audit linkage

### Approvals

| Role | Name | Signature | Date | Time |
|------|------|-----------|------|------|
| Executor | ____________ | ____________ | ______ | ______ |
| Approver | ____________ | ____________ | ______ | ______ |
| Ops Lead | ____________ | ____________ | ______ | ______ |

### Execution Summary

| Metric | Value |
|--------|-------|
| Week ID | 2026-W03 |
| Run ID | ____________ |
| Headcount | ____________ |
| Coverage | ____________% |
| Audit Result | ____________/7 PASS |
| Publish Time | ____________ |
| Lock Time | ____________ |
| Evidence Path | ____________ |

---

## Rollback Procedure (If Needed)

If issues detected after publish but before lock:

1. **Do NOT proceed to lock**
2. Document issue
3. Create incident record
4. Notify ops lead
5. Return to manual scheduling for this week

If critical issue after lock:

1. Activate kill switch (prevents future publishes)
2. Create incident record
3. Follow INCIDENT_BREAK_GLASS.md
4. Schedule post-mortem

---

## Post-Execution

### Immediate (T+1h)

- [ ] Evidence pack verified and stored
- [ ] Weekly sign-off document created
- [ ] Burn-in report scheduled for end of week

### End of Week

- [ ] Generate burn-in report
- [ ] Review KPI drift
- [ ] Close any open incidents
- [ ] Update WIEN_WEEKLY_SIGNOFF_W03.md

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08
