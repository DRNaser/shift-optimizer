# Wien Pilot - Dispatcher Checklist

> **Version**: 1.0 | **Date**: 2026-01-12
> **Audience**: Dispatchers operating SOLVEREIGN Roster for Wien pilot

---

## 10-Step Daily Workflow

### Phase 1: Import & Solve

| Step | Action | Where | Success Criteria |
|------|--------|-------|------------------|
| **1** | **Upload Tour CSV** | Workbench > Upload | File accepted, tour count shown |
| **2** | **Start Optimization** | Workbench > Optimize (120s Fast) | Run status: QUEUED -> RUNNING -> COMPLETED |
| **3** | **Review KPI Cards** | Workbench > Results | Assignment Rate >= 95%, 0 hard violations |

### Phase 2: Review & Repair

| Step | Action | Where | Success Criteria |
|------|--------|-------|------------------|
| **4** | **Open Matrix View** | Plans > #{ID} > Matrix | Roster grid loads, violations highlighted |
| **5** | **Check Violations** | Matrix > Fix Queue Panel | All BLOCK violations = 0 |
| **6** | **Handle Sick Calls** | Matrix > Repair Mode | Enter Driver ID + absence period |
| **7** | **Preview Repair** | Repair > Preview | Verdict = OK, uncovered_after = 0 |
| **8** | **Commit Repair** | Repair > Commit | New plan version created |

### Phase 3: Publish & Lock

| Step | Action | Where | Success Criteria |
|------|--------|-------|------------------|
| **9** | **Publish Plan** | Matrix > Publish | Plan state = PUBLISHED |
| **10** | **Lock for Audit** | Matrix > Lock | Lock badge visible, repairs disabled |

---

## Data Quality Warnings

If you see a **"Data Quality Warning"** banner:

- **DO NOT IGNORE** - some assignments have missing schedule data
- Check the list of affected Driver IDs shown in the banner
- These rows will appear as `[DATEN FEHLEN]` in CSV export
- Report to support: include Run ID from the banner

---

## Lock Status Guide

| Status | What it Means | Can Repair? | Can Export? |
|--------|---------------|-------------|-------------|
| **Unlocked** | Plan is editable | Yes | Yes |
| **Locked** | Arbeitsrechtlich frozen | No | Yes |

When a plan is **Locked**:
- Repair Mode button shows lock icon
- Preview/Commit buttons are disabled
- Lock info shows who locked it and when

---

## Troubleshooting

### "Plan is Locked" when trying to repair

The plan has been frozen for legal/audit reasons. You must:
1. Create a new optimization run
2. Or contact the administrator who locked it

### "Validation Failed" on upload

- Check CSV format: semicolon separator, UTF-8 encoding
- Verify time format: HH:MM (e.g., 08:30)
- Ensure day names match expected values

### Run shows "FAILED" status

1. Check error details in the status panel
2. Note the `trace_id` for support
3. Try with different parameters or smaller dataset

### Export CSV shows "[DATEN FEHLEN]"

- Backend returned assignment without block data
- Report Run ID to technical support
- These rows are placeholders, not actual schedules

---

## Emergency Contacts

| Role | Contact | For |
|------|---------|-----|
| Technical Support | support@solvereign.com | System errors, crashes |
| Operations Lead | ops@lts-transport.at | Business process questions |

---

## Quick Reference: Button Locations

```
Workbench
  |-- Upload (top bar)
  |-- Optimize (top bar, after upload)
  |-- Export (top bar, after results)

Matrix View
  |-- Refresh (top bar)
  |-- Diff (top bar)
  |-- Repair Mode (top bar, blue button)
  |-- Publish (top bar, green button)
  |-- Lock (top bar, amber button)

Repair Mode
  |-- Plan Selector (dropdown)
  |-- Add Absence (+)
  |-- Preview (blue button)
  |-- Commit (green button, after preview)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-12 | Initial Wien pilot checklist |
