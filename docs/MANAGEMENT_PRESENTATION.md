# SOLVEREIGN V3.3b
## Management Präsentation

**Datum**: Januar 2026
**Version**: 3.3b (Production Ready)
**Zielgruppe**: Geschäftsführung, Operations Management

---

## Executive Summary

### Was ist SOLVEREIGN?

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   VORHER (Excel/WhatsApp)          NACHHER (SOLVEREIGN)            │
│   ─────────────────────            ────────────────────             │
│                                                                     │
│   • 4-6 Stunden manuelle           • 30 Sekunden automatisch       │
│     Planung pro Woche                                               │
│                                                                     │
│   • Keine Compliance-Prüfung       • 7 ArbZG-Checks automatisch    │
│                                                                     │
│   • Änderungen = Chaos             • Repair-Solve in < 1 Minute    │
│                                                                     │
│   • Kein Audit Trail               • Vollständige Nachvollziehbarkeit│
│                                                                     │
│   • 150+ Fahrer nötig              • 142-145 Fahrer (5-8 weniger)  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Geschäftlicher Nutzen

### Kostenersparnis (konservativ geschätzt)

| Kategorie | Einsparung/Jahr | Berechnung |
|-----------|-----------------|------------|
| **Fahrer-Reduktion** | €250.000 - €400.000 | 5-8 Fahrer × €50k Vollkosten |
| **Dispatcher-Zeit** | €15.000 - €25.000 | 4h/Woche × 52 Wochen × €75/h |
| **Compliance-Risiko** | Unkalkulierbar | Vermeidung ArbZG-Verstöße |
| **Reaktionszeit** | Operativ | Krankmeldung → Plan in 60s |

**Konservative Jahresersparnis: €265.000 - €425.000**

### ROI-Berechnung

```
Investition (einmalig):
  • Entwicklung:     bereits abgeschlossen (intern)
  • Pilot Week:      ~€5.000 (Personalaufwand)
  • Go-Live:         ~€3.000 (IT-Aufwand)
  ─────────────────────────────────────────
  Gesamt:            ~€8.000

Jährlicher Nutzen:   €265.000 - €425.000

ROI:                 3.300% - 5.300% im ersten Jahr
Amortisation:        < 2 Wochen
```

---

## Aktuelle Leistungskennzahlen

### Solver-Ergebnis (Produktionsdaten KW01/2026)

| KPI | Wert | Bedeutung |
|-----|------|-----------|
| **Fahrer gesamt** | 142 | Minimum bei voller Compliance |
| **FTE-Quote** | 100% | Alle Fahrer ≥40h (keine Teilzeit) |
| **Max. Wochenstunden** | 54h | Unter 55h ArbZG-Grenze |
| **Touren abgedeckt** | 1.385/1.385 | 100% Coverage |
| **Audit-Checks** | 7/7 PASS | Vollständig compliant |

### Vergleich mit manueller Planung

```
                    Manuell        SOLVEREIGN      Δ
                    ───────        ──────────      ─
Fahrer:             ~150           142             -8
Planungszeit:       4-6 Std        30 Sek          -99%
Compliance-Check:   Manuell        Automatisch     ∞
Änderungsreaktion:  30-60 Min      < 60 Sek        -98%
Dokumentation:      Fragmentiert   Vollständig     ✓
```

---

## Compliance & Rechtssicherheit

### 7 Automatische ArbZG-Prüfungen

| # | Prüfung | Regel | Status |
|---|---------|-------|--------|
| 1 | Coverage | Jede Tour genau 1x zugewiesen | ✓ PASS |
| 2 | Overlap | Keine gleichzeitigen Touren | ✓ PASS |
| 3 | Ruhezeit | ≥11h zwischen Schichten | ✓ PASS |
| 4 | Tagesspanne (Regular) | ≤14h für normale Schichten | ✓ PASS |
| 5 | Tagesspanne (Split) | ≤16h mit 4-6h Pause | ✓ PASS |
| 6 | Ermüdung | Keine 3er→3er an Folgetagen | ✓ PASS |
| 7 | Wochenstunden | ≤55h pro Woche | ✓ PASS |

### Audit Trail

```
Jede Entscheidung ist nachvollziehbar:

  Wer?     → Benutzer-ID aus Microsoft Entra
  Was?     → Exakte Änderung dokumentiert
  Wann?    → Zeitstempel (unveränderlich)
  Warum?   → Notizen bei Lock-Freigabe
  Ergebnis → Kryptografischer Hash (fälschungssicher)
```

---

## Sicherheit & Datenschutz

### Zugriffskontrolle

| Rolle | Kann | Kann nicht |
|-------|------|------------|
| **Dispatcher (PLANNER)** | Lesen, Lösen, Exportieren, Reparieren | Plan freigeben |
| **Freigeber (APPROVER)** | Alles oben + **Plan freigeben** | - |
| **System (M2M)** | API-Zugriff, Automatisierung | Plan freigeben |

**Wichtig**: Nur Menschen können Pläne freigeben (kein automatisches System).

### Mandantentrennung

```
┌─────────────────────────────────────────────────────────────────┐
│ Multi-Tenant Architektur                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   LTS Daten    │    Andere Kunden (Zukunft)                     │
│   ───────────  │    ─────────────────────────                   │
│   ████████████ │    ░░░░░░░░░░░░░░░░░░░░░░░░                     │
│   ████████████ │    ░░░░░░░░░░░░░░░░░░░░░░░░                     │
│                                                                 │
│   Vollständig isoliert durch Row-Level Security (RLS)           │
│   Kein Kunde sieht Daten anderer Kunden                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Microsoft Entra ID Integration

- Single Sign-On mit bestehenden LTS-Konten
- Keine zusätzlichen Passwörter
- Zentrale Benutzerverwaltung durch IT
- Automatische Deaktivierung bei Offboarding

---

## Implementierungsplan

### Phase 1: Pilot Week (1 Woche)

```
Tag 0 (Vorbereitung):
  ├── IT: API-Zugang einrichten
  ├── Dispatcher: System-Einführung (1h)
  └── Dry Run: Testplanung durchführen

Tag 1-5 (Parallelbetrieb):
  ├── SOLVEREIGN läuft parallel zu Excel
  ├── Täglich 5 Minuten Morning Check
  ├── Krankmeldungen als Repair-Drill
  └── Dokumentation aller Abweichungen

Ende Woche:
  ├── Go/No-Go Entscheidung
  └── Unterschriften auf Acceptance-Dokument
```

### Phase 2: Production (nach Pilot)

```
Cutover-Tag:
  ├── SOLVEREIGN = Single Source of Truth
  ├── Excel nur noch zur Kommunikation
  └── Jede Änderung → neuer Plan (kein Patching)

Laufend:
  ├── Wöchentliche Planung: < 5 Minuten
  ├── Krankmeldung-Reaktion: < 1 Minute
  └── Compliance: automatisch gewährleistet
```

---

## Risikobewertung

### Identifizierte Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|--------|-------------------|--------|------------|
| System-Ausfall | Niedrig | Hoch | Fallback: letzter LOCKED Plan gültig |
| Falsche Ergebnisse | Sehr niedrig | Mittel | 7 Audit-Checks, menschliche Freigabe |
| Benutzer-Fehler | Mittel | Niedrig | Schulung, einfache UI |
| Datenverlust | Sehr niedrig | Hoch | PostgreSQL, Backup-Strategie |

### Fallback-Strategie

```
Bei System-Problemen:

  1. Letzter LOCKED Plan bleibt gültig (unveränderlich gespeichert)
  2. Export als CSV jederzeit möglich
  3. Manuelle Planung als temporärer Fallback
  4. 24h Support-Reaktionszeit
```

---

## Nächste Schritte

### Sofort (diese Woche)

| # | Aktion | Verantwortlich | Deadline |
|---|--------|----------------|----------|
| 1 | Management-Freigabe für Pilot | Geschäftsführung | - |
| 2 | IT: Entra ID Konfiguration | IT Admin | 2 Tage |
| 3 | Dispatcher-Schulung planen | Operations | 1 Tag |

### Pilot Week (KW __)

| # | Aktion | Verantwortlich | Dauer |
|---|--------|----------------|-------|
| 4 | Day 0: Dry Run | Dispatcher + IT | 1 Tag |
| 5 | Tag 1-5: Parallelbetrieb | Dispatcher | 5 Tage |
| 6 | End of Week: Go/No-Go | Alle Stakeholder | - |

### Production (KW __ + 1)

| # | Aktion | Verantwortlich | Status |
|---|--------|----------------|--------|
| 7 | Cutover-Kommunikation | Operations Lead | - |
| 8 | Vollbetrieb | Dispatcher | Laufend |

---

## Anhang: Screenshots

### Hauptansicht (Streamlit UI)

```
┌─────────────────────────────────────────────────────────────────┐
│ SOLVEREIGN                                    [Dispatcher: MZ]  │
├─────────────────────────────────────────────────────────────────┤
│ [Forecast] [Vergleich] [Planung] [Release] [Simulation]         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Plan KW02/2026                                              │ │
│ │ Status: DRAFT                                               │ │
│ │                                                             │ │
│ │ Fahrer:     142                                             │ │
│ │ FTE-Quote:  100%                                            │ │
│ │ Coverage:   1385/1385 (100%)                                │ │
│ │ Max Std:    54h                                             │ │
│ │                                                             │ │
│ │ Audits:     ✓ 7/7 PASS                                      │ │
│ │                                                             │ │
│ │ [Solve] [Export Matrix] [Export Proof Pack]                 │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Roster-Matrix (Fahrer-Wochenplan)

```
┌────────────────────────────────────────────────────────────────────┐
│ Fahrer  │ Mo          │ Di          │ Mi          │ Do    │ Fr    │
├─────────┼─────────────┼─────────────┼─────────────┼───────┼───────┤
│ D001    │ 06:00-14:00 │ 06:00-14:00 │ 06:00-14:00 │ Frei  │ Frei  │
│         │ 14:30-18:00 │ 14:30-18:00 │             │       │       │
├─────────┼─────────────┼─────────────┼─────────────┼───────┼───────┤
│ D002    │ 08:00-16:00 │ 08:00-16:00 │ 08:00-16:00 │ 08:00 │ 08:00 │
│         │             │             │             │ 16:00 │ 12:00 │
├─────────┼─────────────┼─────────────┼─────────────┼───────┼───────┤
│ ...     │ ...         │ ...         │ ...         │ ...   │ ...   │
└────────────────────────────────────────────────────────────────────┘
```

---

## Kontakt

| Rolle | Name | Kontakt |
|-------|------|---------|
| Projekt-Lead | [Name] | [Email] |
| IT Admin | [Name] | [Email] |
| Operations Lead | [Name] | [Email] |

---

**SOLVEREIGN V3.3b** - Production Ready
*Automatisierte Schichtplanung mit vollständiger ArbZG-Compliance*

---

*Dokument erstellt: 2026-01-05*
*Nächste Aktualisierung: Nach Pilot Week*
