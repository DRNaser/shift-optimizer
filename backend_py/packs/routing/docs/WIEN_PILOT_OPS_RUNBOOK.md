# SOLVEREIGN Routing-Pack V1 — Wien Pilot Ops Runbook

> **Version**: 1.0
> **Datum**: 2026-01-06
> **Scope**: Wien Pilot (≈46 Fahrzeuge/Teams)
> **Zielgruppe**: Dispatcher, Approver, Platform/Admin

---

## Rollen

| Rolle | Verantwortung |
|-------|---------------|
| **Dispatcher (Ops)** | Import, Scenario, Solve, Ergebnischeck, Repair auslösen |
| **Approver** | Lock/Freeze Freigabe, Ausnahme-Entscheidungen |
| **Platform/Admin** | Provider/ArtifactStore/Infra, Incidents, Hotfixes |

---

## A) Pre-Flight Checklist (vor jedem Pilot-Run)

### Daten (FLS Export)

- [ ] `plan_date` korrekt, Site = **WIEN** (keine Misch-Sites)
- [ ] Time windows: `tw_end > tw_start`, TZ = Site-TZ
- [ ] lat/lng vorhanden? Quote notieren (z. B. **95%+ ideal**)
- [ ] `service_code`/`job_type` vorhanden, skill flags korrekt
- [ ] Dublettenregel klar (`order_id` + `plan_date` + `site`)

### Teams

- [ ] TeamsDaily/Vehicle-Teams für `plan_date` vorhanden (≈46)
- [ ] `shift_start`/`shift_end` plausibel
- [ ] Depot coords gesetzt
- [ ] Skills/Teamgröße korrekt (2-person jobs abgedeckt)

### System Health

- [ ] ArtifactStore write/verify OK
- [ ] Provider health: OSRM OK oder StaticMatrix verfügbar
- [ ] Queue/Celery worker healthy (Job execution möglich)

---

## B) Standard-Ablauf (Happy Path)

### Schritt für Schritt

```
┌─────────────────────────────────────────────────────────────────┐
│  1. STOPS IMPORTIEREN                                           │
├─────────────────────────────────────────────────────────────────┤
│  • Validation Report lesen: Pflichtfelder/TW/Geo/Dedupe         │
│  • Nur "Accept", wenn keine roten Fehler                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. TEAMS IMPORTIEREN / PRÜFEN                                  │
├─────────────────────────────────────────────────────────────────┤
│  • Availability/Skills Check (falls Driver Pool aktiv)          │
│  • Team count + shift windows plausibel                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. SCENARIO ERSTELLEN                                          │
├─────────────────────────────────────────────────────────────────┤
│  • Snapshot Hash sichtbar? JA MUSS                              │
│  • Hinweis: Änderungen an TeamsDaily nach Snapshot              │
│    wirken nicht mehr (absichtlich)                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. SOLVE STARTEN                                               │
├─────────────────────────────────────────────────────────────────┤
│  • Provider: Hybrid Policy (je nach Geo)                        │
│  • Laufzeit überwachen, Job Logs ansehen                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. ERGEBNIS PRÜFEN                                             │
├─────────────────────────────────────────────────────────────────┤
│  • Unassigned = 0? Wenn nein: Reasons ansehen                   │
│    (Skills/TW/Capacity/Geo)                                     │
│  • KPI Quickcheck: Distanz/Zeiten plausibel                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. AUDIT AUSFÜHREN / ANSEHEN                                   │
├─────────────────────────────────────────────────────────────────┤
│  • FAIL blockt Lock (409) → zuerst fixen, nicht "drüberbügeln"  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. LOCK/FREEZE (Approver)                                      │
├─────────────────────────────────────────────────────────────────┤
│  • Lock Reason + Kommentar                                      │
│  • Freeze Scope sichtbar                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  8. EVIDENCE PACK                                               │
├─────────────────────────────────────────────────────────────────┤
│  • Evidence öffnen, HASH VERIFY drücken → muss OK sein          │
│  • Export (ZIP/PDF) wenn benötigt                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  9. REPAIR DRILL (Pilot Pflicht)                                │
├─────────────────────────────────────────────────────────────────┤
│  • NO_SHOW oder VEHICLE_DOWN auslösen                           │
│  • Repair Preview: Diff + churn score prüfen                    │
│  • Apply → neue PlanVersion → Re-Audit → Re-Lock                │
└─────────────────────────────────────────────────────────────────┘
```

---

## C) Eskalationslogik

### Severity S1 (Pilot stoppt)

| Symptom | Aktion |
|---------|--------|
| Import blockiert (Contract violations) | → sofort Platform/Admin |
| Solve hängt | → sofort Platform/Admin |
| Evidence Store down | → sofort Platform/Admin |
| RLS/tenant leak suspicion | → sofort Platform/Admin, **kein Lock** |

### Severity S2 (Pilot läuft, Qualität riskant)

| Symptom | Aktion |
|---------|--------|
| Geo-Quote zu niedrig | → Provider auf StaticMatrix |
| Viele Unassigned | → Datenqualität fixen |
| OSRM langsam | → Provider auf StaticMatrix |
| | → ggf. Plan nicht locken |

### Severity S3 (UI/Komfort)

| Symptom | Aktion |
|---------|--------|
| Anzeige/Filter/UX-Probleme | → Ticket, später fixen |
| Plan/Lock/Evidence ok | → Weiterarbeiten |

---

## D) "Was tun wenn…" (Playbooks)

### 1) OSRM down/timeout

**Symptom:** Solve läuft extrem lang / Provider errors

**Aktion:**
```
1. Provider auf StaticMatrix umstellen (Fallback)
2. Run erneut starten
3. Incident loggen (Zeit, Endpoint, error)
```

---

### 2) Import Validator schlägt fehl (Pflichtfelder/TW/Geo)

**Symptom:** Import blockiert (rot)

**Aktion:**
```
1. NICHT umgehen
2. Export korrigieren (FLS Contract)
3. Häufigster Fix:
   - TZ falsch
   - tw_end < tw_start
   - lat/lng leer oder swapped
```

---

### 3) Audit FAIL (Lock blockiert mit 409)

**Symptom:** Lock nicht möglich

**Aktion:**
```
1. Audit-Details öffnen → konkrete Verletzung lesen
2. Fix durch:
   - Input korrigieren
   - Config anpassen
   - Repair statt "neu lösen"
3. Erst nach PASS locken
```

---

### 4) Evidence Pack Verify FAIL

**Symptom:** Hash verify nicht ok / Artifact fehlt

**Aktion:**
```
1. NICHT locken bzw. Lock zurückhalten
2. ArtifactStore health check
3. Permissions, bucket/container prüfen
4. Evidence regeneration (falls supported) → verify erneut
```

---

### 5) Repair erzeugt zu viel Churn

**Symptom:** Repair Preview zeigt massive Stop-Moves

**Aktion:**
```
1. Repair Scope enger setzen (lokal)
2. Freeze Scope prüfen (was ist gesperrt)
3. Falls immer noch hoch:
   → Approver entscheidet (Trade-off dokumentieren)
```

---

### 6) "Unassigned > 0"

**Symptom:** Stops bleiben offen

**Aktion:**
```
Reasons ansehen:

• Skill mismatch    → Teams/Skills korrigieren
• TW zu eng         → Daten/Policy prüfen
• Capacity fehlt    → Team count/shift windows prüfen
• Geo fehlt         → Provider/Geocoding/StaticMatrix

⚠️ Kein Lock, solange Unassigned nicht verstanden/akzeptiert ist
```

---

## E) Minimaler Pilot-Tagesplan

| Phase | Dauer | Aktivitäten |
|-------|-------|-------------|
| **T-0** | 30–60 min | Pre-flight → Import → Solve → Audit → Lock → Evidence Verify |
| **T+1** | 15–30 min | Mindestens 1 Repair Drill realistisch fahren |
| **T+Ende** | 15 min | KPI Snapshot (Baseline vs SOLVEREIGN) + Lessons Learned loggen |

---

## F) Quick Reference Card

### Unassigned Reason Codes

| Code | Bedeutung | Fix |
|------|-----------|-----|
| `NO_SKILL_MATCH` | Kein Team hat benötigte Skills | Team/Skill Daten prüfen |
| `NO_CAPACITY` | Alle Teams voll | Mehr Teams / kleinere Touren |
| `TW_INFEASIBLE` | Zeitfenster nicht erreichbar | TW erweitern oder Split |
| `GEO_MISSING` | Keine Koordinaten | FLS Geocoding fixen |
| `VEHICLE_DOWN_PENDING` | Fahrzeug ausgefallen | Repair abwarten |

### Churn Score Interpretation

| Score | Bedeutung | Aktion |
|-------|-----------|--------|
| 0 – 5.000 | LOW | Auto-OK |
| 5.001 – 20.000 | MEDIUM | Dispatcher Review |
| 20.001 – 50.000 | HIGH | Approver Freigabe |
| > 50.000 | CRITICAL | Ops Manager |

### Kontakte

| Rolle | Kontakt |
|-------|---------|
| IT Support | support@lts.de |
| Tech Support | routing@solvereign.de |
| Operations Manager | ops@lts.de |

---

**Dokument-Version**: 1.0 | **Erstellt**: 2026-01-06
