# SOLVEREIGN - Pilot Week Runbook

**Version**: 1.0
**Date**: 2026-01-05
**Pilot Start**: KW ____ 2026
**Participants**: 1 Dispatcher + 1 Approver

---

## Purpose

This runbook defines **exactly what to do** during the pilot week.
Not "test it" - but structured daily activities with measurable outcomes.

---

## Soft Launch Rules (NON-NEGOTIABLE)

### Access Granted

| Person | Role | Can Do | Cannot Do |
|--------|------|--------|-----------|
| Dispatcher | PLANNER | Read, Solve, Export, Repair | Lock |
| Approver | APPROVER | All above + Lock | - |

### Parallel Operation

```
┌───────────────────────────────────────────────────────────────────┐
│ SOFT LAUNCH = PARALLEL OPERATION                                  │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│ SOLVEREIGN (Pilot)          │  Excel/Alt-System (Production)     │
│ ─────────────────────       │  ─────────────────────────────      │
│ Solve → Export → Review     │  ← Vergleich möglich                │
│ LOCKED Plan = Referenz      │  ← NICHT die Produktionsquelle      │
│                             │                                     │
│ Ziel: Lernen, nicht ersetzen (diese Woche)                       │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Output Directory Structure

```
golden_runs/
└── 2026-Wxx/
    ├── day_0_pre_pilot/
    │   ├── plan_001.json
    │   ├── matrix.csv
    │   └── proof_pack.zip
    ├── day_1/
    │   ├── plan_002.json
    │   ├── repair_sick_2.json    (if applicable)
    │   └── daily_log.md
    ├── day_2/
    │   └── ...
    └── pilot_summary.md
```

### Issue Tracking (NOT in your head!)

Every question, deviation, or issue → **written ticket**:

```markdown
# TICKET: [SHORT TITLE]
Date: 2026-01-XX
Reporter: [Name]
Category: [Bug | Question | Process | UI | Performance]

## What happened
[Description]

## Expected
[What should have happened]

## Actual
[What did happen]

## Screenshot/Evidence
[Link or filename]

## Resolution
[Pending | Fixed | Won't Fix | Documented]
```

---

## Day 0: Pre-Pilot Dry Run

### Morning (Before Pilot Week Officially Starts)

| Time | Activity | Owner | Done |
|------|----------|-------|------|
| 09:00 | Verify API access with Entra token | IT | [ ] |
| 09:15 | Ingest current week's forecast | Dispatcher | [ ] |
| 09:30 | Solve (seed 94) + Review KPIs | Dispatcher | [ ] |
| 10:00 | Run audit, verify 7/7 PASS | Dispatcher | [ ] |
| 10:30 | Export proof pack | Dispatcher | [ ] |
| 11:00 | APPROVER reviews + LOCKs | Approver | [ ] |
| 11:30 | Export final matrix.csv | Dispatcher | [ ] |
| 12:00 | Compare with Excel plan | Both | [ ] |

### Afternoon: Repair Drills

| Scenario | Procedure | Target | Actual | Status |
|----------|-----------|--------|--------|--------|
| **2 drivers sick** | Mark unavailable, repair solve | Coverage 100%, Freeze 0 | | [ ] |
| **6 drivers sick** | Mark unavailable, repair solve | Coverage 100% OR clear fail message | | [ ] |

### Day 0 Sign-Off

- [ ] Solve works
- [ ] Lock works (APPROVER only)
- [ ] Export works
- [ ] Repair drill passed
- [ ] Output matches expectation (rough)

**Day 0 Owner Sign-Off**: __________________ Date: __________

---

## Daily Routine (Day 1-5)

### Morning Check (5 minutes)

```
07:30 - Start

1. [ ] Open SOLVEREIGN
2. [ ] Check: Any sick calls since yesterday?
   - If YES: Note names, proceed to Repair Flow
   - If NO: Log "No changes"
3. [ ] Check system health (API responding)

Time spent: ___ minutes
```

### Sick Call → Repair Flow

```
Fahrer krank gemeldet:
├── Name(n): _______________________
├── Anzahl betroffene Touren: _______
│
├── REPAIR SOLVE ausführen
│   ├── Seed: 94 (oder gewählt)
│   ├── Repair erfolgreich?
│   │   ├── JA: [ ] Coverage 100%, Freeze violations 0
│   │   └── NEIN: [ ] Dokumentieren warum (Standby-Fahrer fehlen?)
│   │
│   ├── Churn Rate: ______%
│   └── Neue Fahrer benötigt: ______
│
└── Plan NICHT locken (Pilot = parallel)
    Nur dokumentieren.
```

### Daily Log Template

Save as `golden_runs/2026-Wxx/day_N/daily_log.md`:

```markdown
# Day N - 2026-01-XX

## Status
- [ ] System operational
- [ ] Forecast unchanged / Änderungen: ___

## Sick Calls
| Driver | Tours Affected | Repair OK? | Churn % |
|--------|----------------|------------|---------|
| - | - | - | - |

## Freeze Violations
Count: 0 (must stay 0!)

## Issues/Questions
- [Link to ticket if any]

## Time Spent
- Morning check: __ min
- Repair (if any): __ min
- Total: __ min

## Notes
[Free text]
```

---

## End of Week: Summary & Sign-Off

### Collect Metrics

| Metric | Day 0 | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Avg |
|--------|-------|-------|-------|-------|-------|-------|-----|
| Headcount | | | | | | | |
| Coverage % | | | | | | | |
| Repair count | | | | | | | |
| Churn rate (max) | | | | | | | |
| Freeze violations | | | | | | | |
| Audit pass rate | | | | | | | |
| Peak fleet | | | | | | | |

### Management KPIs (Week Summary)

```
SOLVEREIGN Pilot Week Summary - KW ____

Headcount (avg):     _____ Fahrer
FTE Rate:            _____% (target: 100%)
Coverage (all days): _____% (target: 100%)

Repairs performed:   _____
Repair success rate: _____%
Avg churn per repair: _____%

Freeze violations:   _____ (target: 0)
Audit pass rate:     _____% (target: 100%)

Peak fleet (max):    _____ concurrent tours

Issues logged:       _____
Issues resolved:     _____

OVERALL: [ ] PASS  [ ] FAIL (with reasons)
```

### Acceptance Checklist Sign-Off

See [PILOT_WEEK_ACCEPTANCE.md](PILOT_WEEK_ACCEPTANCE.md)

---

## Cutover Decision

### NOT a gradual slide - a clear decision!

```
┌───────────────────────────────────────────────────────────────────┐
│ CUTOVER DECISION (End of Pilot Week)                              │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│ [ ] PILOT BESTANDEN (Acceptance signed)                          │
│                                                                   │
│ THEN:                                                             │
│                                                                   │
│   Ab Woche X:                                                     │
│   ┌─────────────────────────────────────────────────────────────┐ │
│   │ SOLVEREIGN = Single Source of Truth                         │ │
│   │                                                             │ │
│   │ • LOCKED Plan ist die Wahrheit                              │ │
│   │ • Excel/WhatsApp = nur Kommunikation, NICHT Planung         │ │
│   │ • Jede Änderung → neuer Plan (supersede)                    │ │
│   │ • KEIN manuelles Patchen im Excel                           │ │
│   └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ [ ] PILOT NICHT BESTANDEN                                        │
│                                                                   │
│ THEN:                                                             │
│   • Dokumentiere Blocker                                         │
│   • Fix issues                                                   │
│   • Schedule Pilot Week 2                                        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Cutover Communication Template

```
Betreff: SOLVEREIGN Go-Live ab KW ____

Team,

Nach erfolgreicher Pilot-Woche wechseln wir ab KW ____ auf SOLVEREIGN
als verbindliche Planungsquelle.

Was das bedeutet:

1. Der LOCKED Plan in SOLVEREIGN ist die offizielle Schicht-Zuweisung
2. Änderungen nur über neuen Solve + Lock (kein Excel-Patching)
3. Bei Fragen: [Kontakt]

Bitte bestätigt mit kurzer Antwort, dass ihr diese Mail gelesen habt.

Danke,
[Name]
```

---

## Quick Reference: Commands

```bash
# Daily check - API health
curl -s http://localhost:8000/health | jq .status

# Get current plan status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/plans?status=LOCKED

# Repair solve (after marking drivers unavailable)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"forecast_version_id": 42, "seed": 94, "run_audit": true}' \
  http://localhost:8000/api/v1/plans/solve

# Export proof pack
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/plans/123/export/proof \
  -o proof_pack.zip
```

---

## Escalation Path

| Issue | First Contact | Escalate To |
|-------|---------------|-------------|
| Can't login | IT Admin | Security Team |
| Solve timeout | IT Admin | Dev Team |
| Wrong results | Dispatcher Lead | Project Lead |
| Freeze violation | Ops Manager | Project Lead |
| RLS leak suspected | IT Admin | Security Team (CRITICAL) |

---

## Appendix: Example Daily Log

```markdown
# Day 2 - 2026-01-14

## Status
- [x] System operational
- [x] Forecast unchanged

## Sick Calls
| Driver | Tours Affected | Repair OK? | Churn % |
|--------|----------------|------------|---------|
| Müller, Hans | 4 | Yes | 3.2% |

## Freeze Violations
Count: 0 ✓

## Issues/Questions
- TICKET-007: UI zeigt falsches Datum im Header (cosmetic)

## Time Spent
- Morning check: 3 min
- Repair (1x): 8 min
- Total: 11 min

## Notes
Repair war schnell und hat funktioniert. Müller Touren auf Schmidt und Weber verteilt.
Churn akzeptabel.
```

---

*Document Owner: SOLVEREIGN Operations Team*
*Created: 2026-01-05*
