# Weekly Operations Runbook

**Version**: 1.0
**Updated**: 2026-01-05
**Audience**: Dispatchers, Operations Team

---

## Overview

This runbook covers the standard weekly workflow for shift planning at LTS using SOLVEREIGN.

---

## Monday: Preparation

### 1. Receive Forecast

**Time**: 09:00-10:00

**Steps**:
1. Receive forecast from Operations Manager (Slack/Email)
2. Copy forecast text to `templates/forecast_template.txt`
3. Verify format:
   - Day names correct (Mo, Di, Mi, Do, Fr, Sa, So)
   - Time format HH:MM
   - Count format "X Fahrer"
   - Depot names match master list

**Checklist**:
- [ ] Forecast received
- [ ] Format validated
- [ ] All 7 days present
- [ ] No unknown patterns

### 2. Update Driver Availability

**Time**: 10:00-11:00

**Steps**:
1. Check emails/calls for sick/vacation updates
2. Update `templates/availability_import.csv`
3. Import via API or UI

**API Call**:
```bash
curl -X POST /api/v1/drivers/availability/bulk \
  -H "X-Tenant-ID: lts-transport-001" \
  -F "file=@availability_import.csv" \
  -F "dry_run=true"
```

**Checklist**:
- [ ] All known absences entered
- [ ] SICK/VACATION/BLOCKED status correct
- [ ] Dates in YYYY-MM-DD format

### 3. Ingest Forecast

**Time**: 11:00-12:00

**Steps**:
1. Open SOLVEREIGN UI
2. Go to "Forecast" tab
3. Paste forecast text
4. Click "Parse & Validate"
5. Review parse status

**Expected Results**:
- Status: PASS (green)
- All lines parsed
- No warnings

**If FAIL**:
- Check error message
- Fix format issues
- Re-parse

---

## Tuesday: Solve & Review

### 4. Run Solver

**Time**: 09:00-10:00

**Steps**:
1. Go to "Planning" tab
2. Configure solver:
   - Seed: 94 (default)
   - Max Weekly Hours: 55
3. Click "Solve"
4. Wait for completion (~30 seconds)

**Alternative - Seed Sweep**:
```
Seeds to try: 42, 94, 17, 123, 7
Pick best result (lowest drivers, 0% PT)
```

### 5. Review KPIs

**Time**: 10:00-11:00

**Target KPIs**:
| KPI | Target | Your Value |
|-----|--------|------------|
| Headcount | <=145 | ______ |
| PT Ratio | 0% | ______ |
| Max Hours | <=54h | ______ |
| Coverage | 100% | ______ |

**If KPIs Not Met**:
- Try different seed
- Check availability constraints
- Escalate to Operations Lead

### 6. Review Near-Violations

**Time**: 11:00-11:30

**What to Check**:
- Yellow zone tours (close to constraint limits)
- Rest violations approaching
- Span limits close

**Action**:
- Document any concerns
- Discuss with Operations Manager

### 7. Review Peak Fleet

**Time**: 11:30-12:00

**What to Check**:
- Concurrent drivers needed per time slot
- Peak periods identified
- Compare to SLA requirements

---

## Wednesday: Lock & Export

### 8. Get Lock Approval

**Time**: 09:00-10:00

**Required Approver**: Operations Manager (APPROVER role)

**Approval Checklist**:
- [ ] All 7 audits PASS
- [ ] KPIs within targets
- [ ] Near-violations reviewed
- [ ] Peak fleet acceptable
- [ ] Operations Manager verbal/written approval

### 9. Lock Plan

**Time**: 10:00-10:30

**Steps**:
1. Go to "Release" tab
2. Click "Lock Plan"
3. Confirm dialog
4. Verify status: LOCKED

**After Lock**:
- Plan is immutable
- Changes require new plan version
- Record lock time and approver

### 10. Export Artifacts

**Time**: 10:30-12:00

**Export Proof Pack**:
1. Click "Export Proof Pack"
2. Save to `golden_runs/YYYY-WXX/proof_pack.zip`

**Export Roster Matrix**:
1. Click "Export Roster"
2. Save to `golden_runs/YYYY-WXX/roster_matrix.csv`

**Archive**:
```
golden_runs/2026-WXX/
  ├── proof_pack.zip
  ├── roster_matrix.csv
  ├── forecast_input.txt
  └── metadata.json (input_hash, output_hash, seed)
```

### 11. Distribute to Drivers

**Time**: 14:00-16:00

**Current Process** (Manual):
1. Print roster matrix
2. Post on driver board
3. Send individual schedules via email/WhatsApp

**Future**: Automated notifications

---

## Thursday-Saturday: Execution

### 12. Monitor for Changes

**Continuous**

**Watch for**:
- Sick calls
- Tour cancellations
- Emergency changes

**If Driver Sick**:
- Note driver ID
- Go to Repair Runbook

### 13. Document Overrides

**If Manual Changes Needed**:
1. Document reason
2. Record original assignment
3. Record manual override
4. Add to weekly report

---

## Sunday: Week Close

### 14. Archive Week

**Time**: End of day

**Steps**:
1. Verify all outputs in `golden_runs/YYYY-WXX/`
2. Note any incidents/repairs
3. Update weekly summary

### 15. Prepare Next Week

**Steps**:
1. Clear temporary files
2. Reset availability template
3. Await next week's forecast

---

## Quick Reference

### API Endpoints

| Action | Endpoint |
|--------|----------|
| Parse forecast | `POST /api/v1/forecasts` |
| Solve | `POST /api/v1/plans/{fv_id}/solve` |
| Lock | `POST /api/v1/plans/{pv_id}/lock` |
| Export | `GET /api/v1/plans/{pv_id}/export` |

### Key Contacts

| Role | Contact |
|------|---------|
| Operations Manager | [Name] |
| IT Support | [Name] |
| SOLVEREIGN Support | support@solvereign.io |

### Emergency Procedures

**If System Down**:
1. Contact IT Support immediately
2. Use last week's roster as backup
3. Document all manual decisions

**If No Solution Found**:
1. Check availability constraints
2. Try different seeds
3. Escalate to Operations Lead

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-05 | Initial release |
