# SOLVEREIGN Routing-Pack V1 — Wien Pilot GO/NO-GO

> **Version**: 1.0
> **Datum**: 2026-01-06
> **Scope**: Wien Pilot (≈46 Fahrzeuge/Teams)
> **Status**: READY FOR DECISION

---

## Kontext

**SOLVEREIGN Routing-Pack V1** ist für den Wien-Pilot vorbereitet (≈46 Fahrzeuge/Teams, Orders aus FLS). Ziel ist ein **lockbarer Plan mit Evidence Pack** und ein **Repair-Prozess**, der unter Freeze stabil bleibt (churn-aware).

---

## Was im Pilot geliefert wird (Outcome, nicht Code)

| Capability | Status |
|------------|--------|
| **E2E Ablauf funktioniert** | ✅ Import (FLS) → Scenario → Solve → Audit → Lock/Freeze → Evidence Pack → Repair (NO_SHOW/VEHICLE_DOWN/DELAY) |
| **Deterministische Beweisführung** | ✅ Matrix-Snapshot + SHA256 Hash im Evidence Pack, Replay möglich |
| **Governance erzwingbar** | ✅ Audit FAIL blockt Lock (409), Freeze wird DB-seitig enforced (nicht nur UI) |
| **Multi-Tenant & Site Isolation** | ✅ RLS + Parallel-Leak Tests bestanden |
| **Betrieb ist runbook-fähig** | ✅ Dispatcher Runbook (happy + failure paths), klarer Eskalationsweg |

---

## Entscheidungsvorlage

### Empfehlung: ✅ GO

**GO für Wien Pilot unter folgenden Bedingungen:**

1. FLS Export Contract v1.0 wird exakt eingehalten (Pflichtfelder, TZ, TWs, Geo-Regeln)
2. Provider-Strategie bleibt **Hybrid**: StaticMatrix als Fallback/Start, OSRM sobald Geo-Qualität passt
3. Pilot startet mit **kontrolliertem Umfang** (definierter Tag/Zeitraum, definierte Site, kein Site-Mix)

---

## Erfolgskriterien (Pilot-KPIs)

### Minimum (Go-Live erfolgreich)

| Kriterium | Target | Messung |
|-----------|--------|---------|
| Import-valid | **100%** | Keine fehlenden Pflichtfelder, keine TW-Inversions, keine Site-Mixes |
| Solve completed | **< X min** | Innerhalb definierter Runtime (Pilot-SLO festlegen) |
| Audit PASS | **100%** | Für Lock-relevante Gates |
| Evidence Pack | **OK** | Erzeugt & verifizierbar (Hash-Verify OK) |
| Repair Drill | **1+ Events** | Mind. 1 NO_SHOW/VEHICLE_DOWN erfolgreich ohne Freeze-Violations |

### Business (ROI Proof)

| Kriterium | Target | Messung |
|-----------|--------|---------|
| Dispo-Zeit | **>5× schneller** | Als manuell |
| Churn im Repair | **<10% Stop-Moves** | Bei lokalen Repairs (je nach Freeze-Scope) |
| Unassigned Reasons | **0** | Sonst klarer Root Cause dokumentiert |

---

## Harte Risiken (ohne Schönreden)

| Risiko | Impact | Likelihood |
|--------|--------|------------|
| **Geo-Qualität** (lat/lng fehlt, falsch, swapped) | OSRM liefert Mist oder keine Zeiten | MEDIUM |
| **Time Windows** schlecht (zu eng/inkonsistent) | Solver kann zwar "lösen", aber operativ failt es | MEDIUM |
| **Provider-Availability** (OSRM down/slow) | Laufzeit/Planqualität schwankt | LOW |
| **Daten-Drift nach Snapshot** (TeamsDaily/Depots geändert) | Erwartungskonflikte bei Ops | LOW |

---

## Mitigation (bereits vorbereitet)

| Risiko | Mitigation |
|--------|------------|
| Geo-Qualität | Contract + Validator blockt Import-Müll |
| Provider-Availability | Hybrid Provider (StaticMatrix → OSRM) |
| Replay-Bedarf | MatrixSnapshot + Hash schützt Evidence/Replay |
| Freeze-Violations | Freeze/Repair ist DB-enforced + getestet |

---

## Rollback-Plan (wenn Pilot kippt)

```
┌─────────────────────────────────────────────────────────────┐
│  AUTOMATISCH                                                │
├─────────────────────────────────────────────────────────────┤
│  • Kein Lock bei Audit FAIL → automatisch safe              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  FALLBACK OPTIONS                                           │
├─────────────────────────────────────────────────────────────┤
│  • StaticMatrix nutzen (wenn OSRM Probleme)                 │
│  • Last-Known-Good Plan wiederherstellen                    │
│  • Manual override nur über dokumentierten Approver-Flow    │
└─────────────────────────────────────────────────────────────┘
```

---

## Nächste Aktion (Go-Live Ablauf, 30–60 Minuten)

| Step | Aktion | Prüfung |
|------|--------|---------|
| 1 | FLS Export ziehen (Pilot-Datei) | Datei vorhanden |
| 2 | Import + Validation Report prüfen | Keine roten Fehler |
| 3 | Scenario erstellen | Snapshot Hash sichtbar |
| 4 | Solve starten | Ergebnis prüfen, Unassigned = 0 |
| 5 | Audit → Lock/Freeze | PASS, dann Lock |
| 6 | Evidence Verify | Hash OK |
| 7 | Repair Drill | 1× NO_SHOW oder VEHICLE_DOWN → Churn prüfen |

---

## Approval

| Rolle | Name | Entscheidung | Datum | Unterschrift |
|-------|------|--------------|-------|--------------|
| Operations Manager | _______________ | GO / NO-GO | ________ | ________ |
| IT Lead | _______________ | GO / NO-GO | ________ | ________ |
| Dispatcher Lead | _______________ | GO / NO-GO | ________ | ________ |

---

**Dokument-Version**: 1.0 | **Erstellt**: 2026-01-06
