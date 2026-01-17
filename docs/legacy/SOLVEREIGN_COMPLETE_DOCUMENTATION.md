# ⚠️ DEPRECATED - LEGACY DOCUMENT

> **This document is DEPRECATED as of V4.5 (January 2026).**
> The Streamlit UI, CLI, and `src/` package referenced here have been removed.
> Current runtime: FastAPI kernel (`backend_py/api/main.py`) + Next.js SaaS Admin (`frontend_v5/`).
> See `CLAUDE.md` for current architecture.

---

# SOLVEREIGN V3.2 - Complete Documentation

> **Enterprise Dispatch Optimization Platform**
> Version 3.2 | Status: **DEPRECATED** | Stand: Januar 2026
> LTS Transport & Logistik GmbH

---

## Inhaltsverzeichnis

1. [Executive Summary](#1-executive-summary)
2. [Architektur-Überblick](#2-architektur-überblick)
3. [Core Module](#3-core-module)
4. [Solver-Algorithmus](#4-solver-algorithmus)
5. [Audit Framework](#5-audit-framework)
6. [Simulation Framework](#6-simulation-framework)
7. [Benutzeroberflächen](#7-benutzeroberflächen)
8. [Datenbank-Schema](#8-datenbank-schema)
9. [API & Integration](#9-api--integration)
10. [Compliance & Sicherheit](#10-compliance--sicherheit)

---

## 1. Executive Summary

### Was ist SOLVEREIGN?

SOLVEREIGN ist eine **Enterprise-Lösung für die automatisierte Schichtplanung** im Transportwesen. Die Plattform optimiert Fahrerzuweisungen unter strikter Einhaltung des deutschen Arbeitszeitgesetzes (ArbZG) und minimiert gleichzeitig die Personalkosten.

### Kernmetriken (Produktiv-Ergebnisse)

| Metrik | Wert | Bedeutung |
|--------|------|-----------|
| **Fahrer optimiert** | 142-145 | Minimale Headcount für 1.385 Touren/Woche |
| **FTE-Quote** | 100% | Keine Teilzeitkräfte erforderlich |
| **Max. Wochenstunden** | 54h | Unter 55h-Grenze (ArbZG-konform) |
| **Coverage** | 100% | Alle Touren werden abgedeckt |
| **Audit-Pass-Rate** | 8/8 | Alle Compliance-Checks bestanden |
| **Optimierungszeit** | <30s | Für komplette Wochenplanung |

### Kernfunktionen

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SOLVEREIGN V3.2                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  PARSE          OPTIMIZE         AUDIT           SIMULATE          │
│  ┌─────┐        ┌─────┐         ┌─────┐         ┌─────┐           │
│  │Slack│───────▶│Block│────────▶│ArbZG│────────▶│What │           │
│  │ CSV │        │Heur.│         │Check│         │ If? │           │
│  └─────┘        └─────┘         └─────┘         └─────┘           │
│                                                                     │
│  • Whitelist    • 4-Stage       • 8 Checks      • 13 Szenarien    │
│  • Validation   • Lexiko-       • Coverage      • Monte Carlo     │
│  • Fingerprint    graphic       • Overlap       • ROI Optimizer   │
│                                 • Rest/Span     • Risk Scoring    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architektur-Überblick

### 2.1 System-Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │   Streamlit UI  │  │      CLI        │  │   REST API      │     │
│  │   (5 Tabs)      │  │   (6 Commands)  │  │   (geplant)     │     │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘     │
│           │                    │                    │               │
└───────────┼────────────────────┼────────────────────┼───────────────┘
            │                    │                    │
┌───────────┼────────────────────┼────────────────────┼───────────────┐
│           ▼                    ▼                    ▼               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    V3 CORE MODULES                           │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │  parser.py     │ solver_wrapper.py │ audit_fixed.py         │   │
│  │  diff_engine.py│ seed_sweep.py     │ simulation_engine.py   │   │
│  │  plan_churn.py │ near_violations.py│ freeze_windows.py      │   │
│  │  peak_fleet.py │ proof_pack.py     │ compose.py             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    DATABASE LAYER                            │   │
│  │              PostgreSQL 16 + Event Sourcing                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│                         BACKEND LAYER                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Event-Sourcing-Architektur

SOLVEREIGN verwendet **Event Sourcing** für vollständige Nachvollziehbarkeit:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ forecast_versions│────▶│  plan_versions   │────▶│    audit_log     │
│   (Immutable)    │     │   (Immutable)    │     │  (Append-Only)   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
    Input Hash              Output Hash              Check Results
    (SHA-256)               (SHA-256)              (JSON Details)
```

**Vorteile:**
- **Reproduzierbarkeit**: Gleicher Input + Seed = Identischer Output
- **Audit Trail**: Vollständige Historie aller Planänderungen
- **Rollback**: Rückkehr zu jedem vorherigen Zustand möglich
- **Compliance**: Nachweis für Betriebsrat und Arbeitsrechtsprüfungen

### 2.3 Technologie-Stack

| Komponente | Technologie | Version |
|------------|-------------|---------|
| Backend | Python | 3.11+ |
| Database | PostgreSQL | 16 Alpine |
| Solver | Google OR-Tools | Latest |
| UI | Streamlit | 1.x |
| Container | Docker Compose | V2 |
| Hashing | SHA-256 | - |

---

## 3. Core Module

### 3.1 Parser (`parser.py`) - 576 Zeilen

Der Parser verarbeitet Forecast-Daten aus verschiedenen Quellen.

#### Unterstützte Formate

```
┌─────────────────────────────────────────────────────────────────┐
│ EINGABE-FORMATE                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 1. TEXT (Slack/Manual):                                         │
│    Mo 06:00-14:00 3 Fahrer Depot Nord                           │
│    Di 08:00-16:00 2 Fahrer                                      │
│    Mi 14:00-22:00                                               │
│    Do 22:00-06:00  (Cross-Midnight)                             │
│    Fr 06:00-10:00 + 15:00-19:00  (Split-Schicht)                │
│                                                                 │
│ 2. CSV:                                                         │
│    day,start,end,count,depot,skill                              │
│    1,06:00,14:00,3,Nord,                                        │
│    2,08:00,16:00,2,,                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Whitelist-basierte Validierung

| Status | Bedeutung | Aktion |
|--------|-----------|--------|
| **PASS** | Alle Zeilen valide | Forecast wird gespeichert |
| **WARN** | Nicht-kritische Probleme | Hinweis, weiter möglich |
| **FAIL** | Kritische Fehler | **Solver blockiert** |

#### Tag-Mapping (Deutsch)

```python
DAY_MAPPING = {
    "Mo": 1, "Montag": 1,
    "Di": 2, "Dienstag": 2,
    "Mi": 3, "Mittwoch": 3,
    "Do": 4, "Donnerstag": 4,
    "Fr": 5, "Freitag": 5,
    "Sa": 6, "Samstag": 6,
    "So": 7, "Sonntag": 7,
}
```

#### Fingerprint-Generierung

Jede Tour erhält einen eindeutigen SHA-256 Fingerprint:

```python
fingerprint = SHA256(f"{day}|{start}|{end}|{depot}|{skill}")
# Beispiel: "1|06:00|14:00|Nord|" → "a3f2c8..."
```

---

### 3.2 Diff Engine (`diff_engine.py`) - 280 Zeilen

Vergleicht zwei Forecast-Versionen und klassifiziert Änderungen.

#### Änderungstypen

```
┌─────────────────────────────────────────────────────────────────┐
│ DIFF KLASSIFIKATION                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ADDED     │ Neue Tour in neuem Forecast                         │
│           │ → Fingerprint existiert nur in NEW                  │
│                                                                 │
│ REMOVED   │ Tour wurde entfernt                                 │
│           │ → Fingerprint existiert nur in OLD                  │
│                                                                 │
│ CHANGED   │ Count oder Attribute geändert                       │
│           │ → Gleicher Fingerprint, andere Werte                │
│                                                                 │
│ UNCHANGED │ Identisch                                           │
│           │ → Wird nicht gelistet                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Anwendungsfälle

1. **Partial → Complete Forecast**: Erkennt neue Touren für Mi-So
2. **Stornierungen**: Zeigt entfernte Touren
3. **Änderungen**: Identifiziert geänderte Fahrer-Counts

---

### 3.3 Solver Wrapper (`solver_wrapper.py`) - 330 Zeilen

Integriert den V2 Block-Heuristic-Solver mit dem V3 Versioning-System.

#### Hauptfunktionen

```python
# Lösen und Auditieren in einem Schritt
result = solve_and_audit(forecast_version_id=1, seed=94)

# Nur Lösen
plan_id = solve_forecast(forecast_version_id=1, seed=94)

# KPIs berechnen
kpis = compute_plan_kpis(plan_version_id=1)
```

#### Output-Struktur

```python
{
    "plan_version_id": 42,
    "seed": 94,
    "kpis": {
        "total_drivers": 145,
        "fte_drivers": 145,
        "pt_drivers": 0,
        "total_hours": 7850.5,
        "avg_hours": 54.1,
        "max_hours": 54.0,
        "block_1er": 120,
        "block_2er_reg": 85,
        "block_2er_split": 42,
        "block_3er": 222,
    },
    "audit_results": {
        "all_passed": True,
        "checks_run": 8,
        "checks_passed": 8,
    },
    "output_hash": "d329b1c4..."
}
```

---

### 3.4 Seed Sweep (`seed_sweep.py`) - 520 Zeilen

Automatische Optimierung durch parallele Seed-Suche.

#### Funktionsweise

```
┌─────────────────────────────────────────────────────────────────┐
│ AUTO-SEED-SWEEP                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Input: 15 Seeds [94, 42, 17, 23, 31, 47, 53, 67, ...]           │
│                                                                 │
│ Parallel Execution (4 Workers):                                 │
│ ┌────┐ ┌────┐ ┌────┐ ┌────┐                                     │
│ │ 94 │ │ 42 │ │ 17 │ │ 23 │  ... → 15 Results                  │
│ └────┘ └────┘ └────┘ └────┘                                     │
│                                                                 │
│ Lexikographische Sortierung:                                    │
│ 1. Min Drivers   (Primär)                                       │
│ 2. Min PT Ratio  (Sekundär)                                     │
│ 3. Max 3er Blocks (Tertiär)                                     │
│ 4. Min 1er Blocks (Quartär)                                     │
│                                                                 │
│ Output: Best Seed + Top 3 + Comparison Table                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Ergebnis-Beispiel

```
+--------+----------+--------+--------+--------+--------+----------+
| Seed   | Fahrer   | FTE    | PT%    | 3er    | 1er    | Status   |
+--------+----------+--------+--------+--------+--------+----------+
| 94     | 145      | 145    | 0.0    | 222    | 120    | OK       |
| 42     | 147      | 145    | 1.4    | 218    | 125    | OK       |
| 17     | 148      | 144    | 2.7    | 215    | 130    | OK       |
+--------+----------+--------+--------+--------+--------+----------+

Empfehlung: Seed 94 mit 145 Fahrern empfohlen.
```

---

### 3.5 Plan Churn (`plan_churn.py`) - 212 Zeilen

Misst Stabilität zwischen zwei Plänen.

#### Metriken

| Metrik | Beschreibung | Formel |
|--------|--------------|--------|
| **Tours Changed** | Anzahl geänderter Zuweisungen | Count |
| **Churn Rate** | Prozent geänderter Touren | Changed / Total |
| **Driver Stability** | Fahrer mit gleichem Schedule | Unchanged / Total |

#### Schwellwerte

| Churn Rate | Bewertung |
|------------|-----------|
| < 5% | Stabil |
| 5-10% | Akzeptabel |
| 10-20% | Hoch |
| > 20% | Kritisch |

---

### 3.6 Freeze Windows (`freeze_windows.py`) - 482 Zeilen

Verhindert Last-Minute-Änderungen innerhalb definierter Zeitfenster.

#### Standard-Konfiguration

```python
DEFAULT_FREEZE_WINDOW = 720  # 12 Stunden vor Tour-Start

def is_frozen(tour_instance, freeze_minutes=720):
    """
    Prüft, ob eine Tour innerhalb des Freeze-Fensters liegt.

    Beispiel: Tour startet Mo 06:00
    - Freeze ab: So 18:00 (12h vorher)
    - Aktuell: So 20:00
    → Tour ist FROZEN (keine Änderungen erlaubt)
    """
```

#### Freeze-Status

| Status | Bedeutung | Aktion |
|--------|-----------|--------|
| **OPEN** | Außerhalb Freeze-Fenster | Änderungen erlaubt |
| **FROZEN** | Im Freeze-Fenster | Nur mit Override |
| **LOCKED** | Plan freigegeben | Keine Änderungen |

---

### 3.7 Near Violations (`near_violations.py`) - 302 Zeilen

Identifiziert "Yellow Zone" Warnungen - Grenzfälle, die bald Violations werden könnten.

#### Warn-Schwellen

| Check | PASS | WARN (Yellow) | FAIL (Red) |
|-------|------|---------------|------------|
| Rest | ≥11h | 11-11.5h | <11h |
| Span Regular | ≤14h | 13.5-14h | >14h |
| Span Split | ≤16h | 15.5-16h | >16h |
| Weekly Hours | ≤55h | 53-55h | >55h |

#### Ausgabe

```python
{
    "total_warnings": 12,
    "by_type": {
        "rest_near_violation": 3,
        "span_near_violation": 5,
        "hours_near_violation": 4,
    },
    "drivers_at_risk": [101, 105, 112, 118],
    "recommendations": [
        "Fahrer 101: 10.8h Rest am Di→Mi - prüfen",
        "Fahrer 105: 54.5h/Woche - nahe am Limit",
    ]
}
```

---

### 3.8 Peak Fleet (`peak_fleet.py`) - 229 Zeilen

Analysiert die maximale gleichzeitige Fahrzeugauslastung.

#### Visualisierung

```
Peak Fleet Analysis - Montag
════════════════════════════════════════════════════════════════

Zeit     │ Aktive Touren │ Visualisierung
─────────┼───────────────┼────────────────────────────────────
05:00    │      3        │ ███
06:00    │     28        │ ████████████████████████████
07:00    │     45        │ █████████████████████████████████████████████
08:00    │     52        │ ████████████████████████████████████████████████████ ← PEAK
09:00    │     48        │ ████████████████████████████████████████████████
...

Peak: 52 gleichzeitige Touren um 08:00
Empfehlung: 55+ Fahrzeuge bereithalten für Buffer
```

---

### 3.9 Proof Pack (`proof_pack.py`) - ~200 Zeilen

Generiert kryptografisch signierte Audit-Pakete.

#### Inhalt des ZIP-Archivs

```
proof_pack_plan_42_2026-01-05.zip
├── metadata.json          # Hashes, Timestamps, Version
├── forecast_input.txt     # Original Forecast
├── plan_output.json       # Solver-Output
├── assignments.csv        # Alle Zuweisungen
├── roster_matrix.csv      # Fahrer-Wochenplan
├── audit_results.json     # Alle 8 Checks
├── kpis.json              # KPI-Summary
└── checksums.sha256       # Integritätsprüfung
```

#### Hash-Chain

```
Input Hash ────────────────────────────────────┐
                                               ├──▶ Proof Pack Hash
Output Hash ───────────────────────────────────┤
                                               │
Audit Hash ────────────────────────────────────┘
```

---

## 4. Solver-Algorithmus

### 4.1 Block-Heuristic-Solver (V2)

Der Solver verwendet einen **4-stufigen Algorithmus** mit lexikographischer Optimierung.

#### Stage 0: Greedy Partitioning

```
┌─────────────────────────────────────────────────────────────────┐
│ GREEDY BLOCK FORMATION                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Priorität: 3er > 2er > 1er                                      │
│                                                                 │
│ Tag 1 (Montag):                                                 │
│ ┌────────┐ ┌────────┐ ┌────────┐                                │
│ │06:00-10│→│10:45-14│→│14:45-18│  = 3er-Block (12h Span)        │
│ └────────┘ └────────┘ └────────┘                                │
│                                                                 │
│ ┌────────┐ ┌────────┐                                           │
│ │06:00-14│→│15:00-23│  = 2er-Split (17h Span, 1h Break)         │
│ └────────┘ └────────┘                                           │
│                                                                 │
│ ┌────────┐                                                      │
│ │06:00-14│  = 1er-Block (8h)                                    │
│ └────────┘                                                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Stage 1: Min-Cost Max-Flow

```python
# Google OR-Tools Integration
from ortools.graph.python import min_cost_flow

# Netzwerk-Aufbau:
# Source → Blocks → Drivers → Sink
# Kosten: Lexikographisch gewichtet
```

#### Stage 2: Consolidation

```
Vor Consolidation:
  Driver 1: Mo [3er], Di [1er], Mi [2er]
  Driver 2: Mo [1er], Di [-], Mi [1er]

Nach Consolidation:
  Driver 1: Mo [3er], Di [1er, übernommen], Mi [2er]
  Driver 2: ENTFERNT (Aufgaben umverteilt)
```

#### Stage 3: PT Elimination

```
Ziel: 0% Teilzeit-Fahrer

Methode:
1. Identifiziere PT-Fahrer (<40h/Woche)
2. Versuche deren Blöcke auf FTE zu verteilen
3. Nur wenn FTE ≤55h bleibt
```

### 4.2 Lexikographische Kostenfunktion

```python
cost = (
    1_000_000_000 * num_drivers       # Primär: Min Fahrer
  + 1_000_000     * num_pt_drivers    # Sekundär: Min Teilzeit
  + 1_000         * num_splits        # Tertiär: Min Splits
  + 100           * num_singletons    # Quartär: Min 1er
)
```

### 4.3 Block-Typen

| Typ | Beschreibung | Max Span | Pause |
|-----|--------------|----------|-------|
| **1er** | Einzelne Tour | 8-10h | - |
| **2er-reg** | 2 Touren, kurze Pause | ≤14h | 30-60min |
| **2er-split** | 2 Touren, lange Pause | ≤16h | 4-6h |
| **3er-chain** | 3 Touren, verbunden | ≤16h | 30-60min je |

### 4.4 Constraints

| Constraint | Wert | Rechtsgrundlage |
|------------|------|-----------------|
| Max Daily Span | 14h (1er/2er-reg), 16h (3er/split) | Betriebsvereinbarung |
| Max Daily Arbeitszeit | ~15.5h (inkl. Pausen in 3er) | EU VO 561/2006 + Tarifvertrag |
| Max Weekly Hours | 55h | Betriebsvereinbarung (LTS Policy) |
| Min Rest | 11h | §5 ArbZG |
| Fatigue Rule | Kein 3er→3er | Betriebsvereinbarung |

> **Wichtiger Hinweis zur Arbeitszeit**:
> - §3 ArbZG (8h, max 10h/Tag) gilt für **normale Arbeitnehmer**
> - **Transport-Sektor**: EU VO 561/2006 und Tarifverträge erlauben längere Schichten
> - **3er-Blöcke**: Bei 16h Span mit Pausen (30-60min je Gap) ergibt sich ~15.5h Anwesenheit
> - Die 55h-Wochengrenze ist eine **konservative LTS Policy**, keine ArbZG-Grenze
> - ArbZG-Ausgleichspflicht: Ø48h im Halbjahr (erlaubt Spitzenwochen mit 55h+)

---

## 5. Audit Framework

### 5.1 Übersicht der 8 Audit-Checks

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUDIT FRAMEWORK (8 CHECKS)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ COVERAGE        OVERLAP         REST            SPAN-REG        │
│ ┌─────┐         ┌─────┐         ┌─────┐         ┌─────┐        │
│ │ ✓   │         │ ✓   │         │ ✓   │         │ ✓   │        │
│ │1:1  │         │ No  │         │≥11h │         │≤14h │        │
│ └─────┘         └─────┘         └─────┘         └─────┘        │
│                                                                 │
│ SPAN-SPLIT      FATIGUE         REPRO           SENSITIVITY     │
│ ┌─────┐         ┌─────┐         ┌─────┐         ┌─────┐        │
│ │ ✓   │         │ ✓   │         │ ✓   │         │ ✓   │        │
│ │≤16h │         │No   │         │Same │         │<10% │        │
│ │4-6h │         │3→3  │         │Hash │         │Churn│        │
│ └─────┘         └─────┘         └─────┘         └─────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Check-Details

#### Check 1: Coverage

```python
class CoverageCheckFixed:
    """
    Prüft: Jede Tour-Instanz genau 1x zugewiesen.

    PASS: instances == assignments (1:1 Mapping)
    FAIL: Duplikate oder fehlende Zuweisungen
    """
```

#### Check 2: Overlap

```python
class OverlapCheckFixed:
    """
    Prüft: Kein Fahrer arbeitet gleichzeitig an zwei Touren.

    PASS: Keine zeitlichen Überschneidungen
    FAIL: Fahrer X hat Tour A und B gleichzeitig
    """
```

#### Check 3: Rest

```python
class RestCheckFixed:
    """
    Prüft: ≥11h Ruhezeit zwischen Arbeitstagen.

    PASS: Alle Ruhezeiten ≥ 660 Minuten
    FAIL: Fahrer X hat nur 10h Pause zwischen Di und Mi
    """
```

#### Check 4: Span Regular

```python
class SpanRegularCheckFixed:
    """
    Prüft: 1er/2er-reg Blöcke ≤14h Span.

    Span = Ende letzte Tour - Start erste Tour
    PASS: Alle regular blocks ≤ 840 Minuten
    FAIL: Block mit 15h Span gefunden
    """
```

#### Check 5: Span Split

```python
class SpanSplitCheckFixed:
    """
    Prüft: Split/3er Blöcke ≤16h Span + 4-6h Pause.

    PASS: Span ≤960min UND Pause 240-360min
    FAIL: Split mit nur 3h Pause
    """
```

#### Check 6: Fatigue

```python
class FatigueCheckFixed:
    """
    Prüft: Kein 3er-Block an zwei aufeinanderfolgenden Tagen.

    PASS: Kein Fahrer hat 3er am Mo UND 3er am Di
    FAIL: Fahrer X hat 3er→3er (Erschöpfungsrisiko)
    """
```

#### Check 7: Reproducibility

```python
class ReproducibilityCheckFixed:
    """
    Prüft: Gleicher Input + Seed = Gleicher Output Hash.

    PASS: output_hash ist konsistent
    FAIL: Non-determinismus erkannt
    """
```

#### Check 8: Sensitivity (V3.1)

```python
class SensitivityCheckFixed:
    """
    Prüft: Plan-Stabilität bei kleinen Config-Änderungen.

    Perturbationen:
    - Max Hours: 55h → 58h/52h
    - Rest: 11h → 10h
    - Fatigue: 3er→3er erlauben

    PASS: Churn < 10% bei allen Perturbationen
    FAIL: Plan ist fragil (hohe Sensitivität)
    """
```

### 5.3 Audit-Ergebnis-Struktur

```python
{
    "all_passed": True,
    "checks_run": 8,
    "checks_passed": 8,
    "results": {
        "COVERAGE": {"status": "PASS", "violations": 0},
        "OVERLAP": {"status": "PASS", "violations": 0},
        "REST": {"status": "PASS", "violations": 0},
        "SPAN_REGULAR": {"status": "PASS", "violations": 0},
        "SPAN_SPLIT": {"status": "PASS", "violations": 0},
        "FATIGUE": {"status": "PASS", "violations": 0},
        "REPRODUCIBILITY": {"status": "PASS", "violations": 0},
        "SENSITIVITY": {"status": "PASS", "violations": 0, "stability_class": "STABLE"},
    }
}
```

---

## 6. Simulation Framework

### 6.1 Übersicht der 13 Szenarien

```
┌─────────────────────────────────────────────────────────────────┐
│                 SIMULATION FRAMEWORK (13 Szenarien)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ECONOMIC (3)           COMPLIANCE (2)        OPERATIONAL (3)    │
│ ├─ Cost Curve          ├─ Max-Hours Policy   ├─ Patch-Chaos     │
│ ├─ Freeze Tradeoff     └─ Driver-Friendly    ├─ Sick-Call Drill │
│ └─ Headcount Budget                          └─ Tour-Cancel     │
│                                                                 │
│ STRATEGIC (2)          ADVANCED V3.2 (3)                        │
│ ├─ Auto-Seed-Sweep     ├─ Multi-Failure Cascade                 │
│ └─ Multi-Scenario      ├─ Probabilistic Churn                   │
│    Comparison          └─ Policy ROI Optimizer                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 ECONOMIC Szenarien

#### A. Cost Curve

**Frage**: "Was kostet jede Qualitätsregel in Fahrern?"

```
┌─────────────────────────────────────────────────────────────────┐
│ COST CURVE ANALYSE                                              │
├─────────────────────────────────────────────────────────────────┤
│ Baseline: 145 Fahrer (alle Regeln aktiv)                        │
│                                                                 │
│ Regel deaktiviert        │ Δ Fahrer │ Ersparnis/Jahr           │
│ ─────────────────────────┼──────────┼─────────────────────────  │
│ 3er→3er erlauben         │ -4       │ ~€200.000                 │
│ Rest 11h → 10h           │ -3       │ ~€150.000                 │
│ Max 55h → 58h            │ -2       │ ~€100.000                 │
│ Split 240min → 180min    │ -2       │ ~€100.000                 │
│ Span 14h → 15h           │ -1       │ ~€50.000                  │
│                                                                 │
│ Total potenzielle Ersparnis: -12 Fahrer = ~€600.000/Jahr        │
│ Risk Score: MEDIUM                                              │
└─────────────────────────────────────────────────────────────────┘
```

#### B. Freeze Window Tradeoff

**Frage**: "12h vs 18h vs 24h Freeze - Kosten vs. Stabilität?"

```
┌─────────────────────────────────────────────────────────────────┐
│ FREEZE WINDOW TRADE-OFF                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Freeze    │ Fahrer │ Stabilität │ Bewertung                     │
│ ──────────┼────────┼────────────┼─────────────────────────────  │
│ 12h       │ 145    │ 78%        │ Flexibel, chaotisch           │
│ 18h       │ 147    │ 89%        │ ← SWEET SPOT                  │
│ 24h       │ 150    │ 95%        │ Stabil, teuer                 │
│ 48h       │ 155    │ 98%        │ Sehr stabil, teuer            │
│                                                                 │
│ Trade-off: +1 Fahrer → +5.5% Stabilität                         │
│ Risk Score: LOW                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### C. Headcount Budget

**Frage**: "Wir müssen unter 140 Fahrer - welche Regeln lockern?"

```
┌─────────────────────────────────────────────────────────────────┐
│ HEADCOUNT-BUDGET ANALYSE                                        │
├─────────────────────────────────────────────────────────────────┤
│ Ziel: ≤140 Fahrer (aktuell: 145, Gap: -5)                       │
│                                                                 │
│ EMPFOHLENE LOCKERUNGEN:                                         │
│ ┌───────────────────┬──────────┬────────┬───────────────────┐   │
│ │ Option            │ Δ Fahrer │ Risiko │ ArbZG             │   │
│ ├───────────────────┼──────────┼────────┼───────────────────┤   │
│ │ Max 55h → 58h     │ -2       │ LOW    │ Grenzwertig       │   │
│ │ 3er→3er erlauben  │ -4       │ MEDIUM │ Legal             │   │
│ │ Split 240→180     │ -2       │ HIGH   │ Grenzwertig       │   │
│ └───────────────────┴──────────┴────────┴───────────────────┘   │
│                                                                 │
│ Kombinationen:                                                  │
│ • Option 1 only: 143 Fahrer (LOW Risk)                          │
│ • Option 1+2: 140 Fahrer (MEDIUM Risk) ← Ziel erreicht          │
│ • Option 1+2+3: 138 Fahrer (HIGH Risk)                          │
│                                                                 │
│ Risk Score: MEDIUM                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 COMPLIANCE Szenarien

#### D. Max-Hours Policy

**Frage**: "Was passiert bei 55h → 52h → 50h → 48h Cap?"

```
┌─────────────────────────────────────────────────────────────────┐
│ MAX-HOURS POLICY ANALYSE                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Cap   │ Fahrer │ FTE  │ PT%  │ Coverage │ Bewertung             │
│ ──────┼────────┼──────┼──────┼──────────┼─────────────────────  │
│ 55h   │ 145    │ 145  │ 0%   │ 100%     │ Baseline              │
│ 52h   │ 148    │ 145  │ 2%   │ 100%     │ Konservativ (+3)      │
│ 50h   │ 152    │ 144  │ 5%   │ 100%     │ Fahrer-freundlich     │
│ 48h   │ 158    │ 140  │ 8%   │ 100%     │ ArbZG-sicher          │
│ 45h   │ 165    │ 135  │ 12%  │ 99.5%    │ ⚠️ Coverage-Risiko    │
│                                                                 │
│ Formel: (55h - X) / 3 × 5 = zusätzliche Fahrer                  │
│ Beispiel: 55h → 48h = 7h / 3 × 5 ≈ 12 Fahrer mehr               │
│                                                                 │
│ Risk Score: LOW (bei 48h+)                                      │
└─────────────────────────────────────────────────────────────────┘
```

#### E. Driver-Friendly Policy

**Frage**: "Was kostet es, wenn 3er nur mit 30-60min Gaps erlaubt sind?"

```
┌─────────────────────────────────────────────────────────────────┐
│ DRIVER-FRIENDLY POLICY                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Aktuell (3er mit Split-Gaps erlaubt):                           │
│   145 Fahrer, 222 3er-Blocks                                    │
│                                                                 │
│ Nur 30-60min Gaps in 3er-Chains:                                │
│   152 Fahrer (+7), 180 3er-Blocks (-42)                         │
│                                                                 │
│ KOSTEN-NUTZEN:                                                  │
│ ├─ Mehrkosten: +7 Fahrer/Woche = ~€350.000/Jahr                 │
│ ├─ Benefits:                                                    │
│ │   • Höhere Fahrer-Zufriedenheit                               │
│ │   • Weniger Beschwerden über "16h-Tage"                       │
│ │   • Potenzielle Fluktuation ↓                                 │
│ └─ Break-Even: Fluktuation um 5% senken                         │
│                                                                 │
│ Risk Score: LOW                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.4 OPERATIONAL Szenarien

#### F. Patch-Chaos

**Frage**: "Mo/Di fix, Mi-So kommt später - wie viel Churn?"

```
┌─────────────────────────────────────────────────────────────────┐
│ PATCH-CHAOS SIMULATION                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Partial (LOCKED): Mo/Di (554 Touren)                            │
│ Patch (NEW): Mi-So (831 Touren)                                 │
│                                                                 │
│ ERGEBNIS:                                                       │
│ ├─ Baseline (Full Week): 145 Fahrer                             │
│ ├─ Nach Patch-Integration: 148 Fahrer (+3)                      │
│ ├─ Churn Mo/Di: 12 Tours (8.7%)                                 │
│ ├─ Freeze Violations: 4 Tours                                   │
│ └─ Override Required: 4 Tours                                   │
│                                                                 │
│ Empfehlung: "Mo früher locken kostet 3 Fahrer extra"            │
│ Risk Score: MEDIUM                                              │
└─────────────────────────────────────────────────────────────────┘
```

#### G. Sick-Call Drill

**Frage**: "5 Fahrer fallen morgen früh aus - wie schnell Repair?"

```
┌─────────────────────────────────────────────────────────────────┐
│ SICK-CALL DRILL                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Ausfall: 5 Fahrer am Montag                                     │
│                                                                 │
│ ERGEBNIS:                                                       │
│ ├─ Betroffene Touren: 18                                        │
│ ├─ Repair-Zeit: 2.3 Sekunden                                    │
│ ├─ Repair-Churn: 18 Tours umverteilt                            │
│ ├─ Neue Fahrer benötigt: 2                                      │
│ └─ Compliance: ALL PASS                                         │
│                                                                 │
│ Empfehlung: "System kann Ausfälle schnell kompensieren"         │
│ Risk Score: LOW                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### H. Tour-Cancel

**Frage**: "20 Touren werden kurzfristig storniert - Churn?"

```
┌─────────────────────────────────────────────────────────────────┐
│ TOUR-STORNIERUNG                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Storniert: 20 Touren                                            │
│                                                                 │
│ ERGEBNIS:                                                       │
│ ├─ Fahrer befreit: 8                                            │
│ ├─ Reassignment Churn: 35 Tours                                 │
│ ├─ Churn Rate: 2.5%                                             │
│ └─ Einsparung: ~8 Fahrer-Stunden                                │
│                                                                 │
│ Empfehlung: "Minimal replan, nur betroffene Blöcke"             │
│ Risk Score: LOW                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.5 STRATEGIC Szenarien

#### I. Auto-Seed-Sweep

**Frage**: "Welcher Seed ist optimal?"

```
┌─────────────────────────────────────────────────────────────────┐
│ AUTO-SEED-SWEEP                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Seeds getestet: 15 (parallel, 4 Workers)                        │
│ Execution Time: 45.2 Sekunden                                   │
│                                                                 │
│ TOP 3:                                                          │
│ ┌──────┬────────┬─────┬──────┬──────┬──────┐                    │
│ │ Rank │ Seed   │ FTE │ PT   │ 1er  │ 3er  │                    │
│ ├──────┼────────┼─────┼──────┼──────┼──────┤                    │
│ │ 1    │ 94     │ 145 │ 0    │ 120  │ 222  │                    │
│ │ 2    │ 42     │ 145 │ 2    │ 125  │ 218  │                    │
│ │ 3    │ 17     │ 144 │ 4    │ 130  │ 215  │                    │
│ └──────┴────────┴─────┴──────┴──────┴──────┘                    │
│                                                                 │
│ Empfehlung: Seed 94 mit 145 Fahrern                             │
│ Varianz: 145-148 (gering - stabile Lösung)                      │
└─────────────────────────────────────────────────────────────────┘
```

#### J. Multi-Scenario Comparison

**Frage**: "Aggressiv vs. Balanced vs. Safe - side-by-side?"

```
┌─────────────────────────────────────────────────────────────────┐
│ MULTI-SZENARIO-VERGLEICH                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─────────────────┬─────────────────┬─────────────────┐         │
│ │ AGGRESSIV       │ BALANCED        │ SAFE            │         │
│ │ (Seed 42)       │ (Seed 94)       │ (Seed 17)       │         │
│ ├─────────────────┼─────────────────┼─────────────────┤         │
│ │ 140 Fahrer      │ 145 Fahrer      │ 150 Fahrer      │         │
│ │ 0% PT           │ 0% PT           │ 3% PT           │         │
│ │ 56h Max [!]     │ 54h Max         │ 50h Max         │         │
│ │ Churn: 25%      │ Churn: 15%      │ Churn: 8%       │         │
│ ├─────────────────┼─────────────────┼─────────────────┤         │
│ │ ✓ 6/8 Audits    │ ✓ 8/8 Audits    │ ✓ 8/8 Audits    │         │
│ │ [!] Near-Viol   │ [OK]            │ [OK]            │         │
│ └─────────────────┴─────────────────┴─────────────────┘         │
│                                                                 │
│ Empfehlung: BALANCED (best trade-off)                           │
└─────────────────────────────────────────────────────────────────┘
```

### 6.6 ADVANCED V3.2 Szenarien

#### K. Multi-Failure Cascade

**Frage**: "5 Fahrer krank + 10 Touren storniert + Cascade-Effekte?"

```
┌─────────────────────────────────────────────────────────────────┐
│ MULTI-FAILURE CASCADE SIMULATION                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Initial: 5 Fahrer krank + 10 Touren storniert                   │
│ Cascade-Wahrscheinlichkeit: 15%                                 │
│                                                                 │
│ ERGEBNIS:                                                       │
│ ├─ Cascade Events: 3 Runden                                     │
│ │   • Runde 1: +2 krank, +3 storniert                           │
│ │   • Runde 2: +1 krank, +2 storniert                           │
│ │   • Runde 3: +0 krank, +1 storniert                           │
│ ├─ Total Fahrer Out: 8 (von 5 initial)                          │
│ ├─ Total Tours Cancelled: 16 (von 10 initial)                   │
│ ├─ Total Affected Tours: 36                                     │
│ ├─ Churn Rate: 2.6%                                             │
│ ├─ Neue Fahrer benötigt: 2                                      │
│ ├─ Repair-Zeit: 4.2s                                            │
│ ├─ Cascade-Wahrscheinlichkeit: 90%                              │
│ ├─ Best Case: 143 Fahrer                                        │
│ └─ Worst Case: 150 Fahrer                                       │
│                                                                 │
│ Empfehlung: Backup-Pool um 20% erhöhen für Resilience           │
│ Risk Score: MEDIUM                                              │
└─────────────────────────────────────────────────────────────────┘
```

#### L. Probabilistic Churn (Monte Carlo)

**Frage**: "Wie wahrscheinlich ist Churn > 10% unter Stress?"

```
┌─────────────────────────────────────────────────────────────────┐
│ PROBABILISTIC CHURN FORECAST (Monte Carlo)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Simulationen: 100                                               │
│ Basis-Ausfallwahrscheinlichkeit: 5%                             │
│                                                                 │
│ ERGEBNIS:                                                       │
│ ├─ Mittlere Churn-Rate: 3.49% ± 0.56%                           │
│ ├─ P(Churn > 10%): 0.0%                                         │
│ ├─ 95%-Konfidenzintervall: [2.4%, 4.5%]                         │
│ └─ Perzentile:                                                  │
│     • 5%:  2.1%                                                 │
│     • 50%: 3.4%                                                 │
│     • 95%: 4.5%                                                 │
│                                                                 │
│ HISTOGRAM:                                                      │
│ 0-5%   ██████████████████████████████████████████ 92%           │
│ 5-10%  ████████ 8%                                              │
│ 10-15% 0%                                                       │
│ 15%+   0%                                                       │
│                                                                 │
│ Empfehlung: System zeigt gute Stabilität unter Stress           │
│ Risk Score: LOW                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### M. Policy ROI Optimizer

**Frage**: "Optimale Regel-Kombination für beste Kosten-Nutzen?"

```
┌─────────────────────────────────────────────────────────────────┐
│ POLICY ROI OPTIMIZER                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Optimierungsziel: BALANCED                                      │
│ Budget: ±5 Fahrer                                               │
│ Constraint: Nur ArbZG-konforme Optionen                         │
│                                                                 │
│ OPTIMALE KOMBINATION:                                           │
│ ├─ Policies: max_hours_58 + allow_3er_3er + span_15h            │
│ ├─ Fahrer-Delta: -7                                             │
│ ├─ Ersparnis: €350.000/Jahr                                     │
│ ├─ Stabilitäts-Impact: -30%                                     │
│ ├─ ROI Score: 25.0                                              │
│ └─ Risiko: MEDIUM                                               │
│                                                                 │
│ TOP 5 KOMBINATIONEN:                                            │
│ ┌────────────────────────────────┬────────┬──────────┬────────┐ │
│ │ Policies                       │Δ Fahrer│ Ersparnis│ Risiko │ │
│ ├────────────────────────────────┼────────┼──────────┼────────┤ │
│ │ max_hours_58 + 3er→3er + span  │ -7     │ €350k    │ MEDIUM │ │
│ │ max_hours_58 + 3er→3er         │ -6     │ €300k    │ MEDIUM │ │
│ │ 3er→3er + span_15h             │ -5     │ €250k    │ MEDIUM │ │
│ │ max_hours_58 + span_15h        │ -3     │ €150k    │ LOW    │ │
│ │ max_hours_58                   │ -2     │ €100k    │ LOW    │ │
│ └────────────────────────────────┴────────┴──────────┴────────┘ │
│                                                                 │
│ Pareto-Frontier: 7 nicht-dominierte Optionen                    │
│ Kombinationen analysiert: 16                                    │
│ Risk Score: MEDIUM                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 6.7 Risk Score Berechnung

```python
def compute_risk_score(headcount_delta, churn_rate, freeze_violations=0, audit_failures=0):
    score = 0

    # Headcount
    if headcount_delta > 10: score += 3
    elif headcount_delta > 5: score += 2
    elif headcount_delta > 0: score += 1

    # Churn
    if churn_rate > 0.20: score += 3
    elif churn_rate > 0.10: score += 2
    elif churn_rate > 0.05: score += 1

    # Freeze Violations
    if freeze_violations > 10: score += 3
    elif freeze_violations > 5: score += 2
    elif freeze_violations > 0: score += 1

    # Audit Failures
    if audit_failures > 0: score += 5  # Critical!

    # Map to level
    if score >= 8: return "CRITICAL"
    elif score >= 5: return "HIGH"
    elif score >= 3: return "MEDIUM"
    else: return "LOW"
```

---

## 7. Benutzeroberflächen

### 7.1 Streamlit UI (5 Tabs)

```
┌─────────────────────────────────────────────────────────────────┐
│ SOLVEREIGN                                         V3 | Enterprise │
├─────────────────────────────────────────────────────────────────┤
│ [ Forecast ] [ Vergleich ] [ Planung ] [ Release ] [ Simulation ]│
└─────────────────────────────────────────────────────────────────┘
```

#### Tab 1: Forecast

- **Gespeicherte Forecasts laden**
- **Neuer Forecast erstellen** (Text/CSV)
- **Parse-Status** (PASS/WARN/FAIL)
- **Optimieren** mit Seed-Auswahl

#### Tab 2: Vergleich

- **Zwei Forecasts auswählen**
- **Diff-Ansicht**: ADDED/REMOVED/CHANGED
- **Plan-Churn Analyse**

#### Tab 3: Planung

- **Roster-Matrix** (Fahrer × Tage)
- **KPI-Dashboard** (Fahrer, FTE, PT, Hours)
- **Near-Violations** (Yellow Zone)
- **Peak Fleet Analyse**

#### Tab 4: Release

- **Lock-Workflow**
- **Release-Gates prüfen**
- **Proof Pack Export**

#### Tab 5: Simulation

- **Kategorie-Auswahl**: Economic, Compliance, Operational, Strategic, Advanced
- **13 Szenarien** mit interaktiven Parametern
- **Ergebnis-Visualisierung** mit Risk Score

### 7.2 CLI (6 Commands)

```bash
# Forecast einlesen
solvereign ingest forecast_kw51.csv

# Plan optimieren
solvereign solve 1 --seed 94

# Plan sperren
solvereign lock 1

# Proof Pack exportieren
solvereign export 1 --output ./exports

# System-Status
solvereign status

# Simulationen (9 Szenarien)
solvereign simulate cost-curve --forecast 1
solvereign simulate max-hours --forecast 1 --caps 55,52,50,48
solvereign simulate auto-sweep --forecast 1 --seeds 15
solvereign simulate headcount --forecast 1 --target 140
solvereign simulate tour-cancel --forecast 1 --count 20
solvereign simulate sick-call --forecast 1 --count 5 --day 1
solvereign simulate multi-failure --forecast 1 --count 5 --tours 10 --cascade 0.15
solvereign simulate prob-churn --forecast 1 --sims 100 --threshold 0.10
solvereign simulate policy-roi --forecast 1 --budget 5 --optimize balanced
```

---

## 8. Datenbank-Schema

### 8.1 Haupt-Tabellen (10)

```sql
-- 1. Forecast Versions (Input)
CREATE TABLE forecast_versions (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(50),           -- 'slack', 'csv', 'manual'
    input_hash VARCHAR(64),       -- SHA-256 of canonical text
    parser_config_hash VARCHAR(64),
    status VARCHAR(10),           -- 'PASS', 'WARN', 'FAIL'
    week_anchor_date DATE,        -- Monday of planning week
    notes TEXT
);

-- 2. Tours Raw (Unparsed)
CREATE TABLE tours_raw (
    id SERIAL PRIMARY KEY,
    forecast_version_id INT REFERENCES forecast_versions,
    line_no INT,
    raw_text TEXT,
    parse_status VARCHAR(10),
    parse_errors JSONB,
    parse_warnings JSONB,
    canonical_text TEXT
);

-- 3. Tours Normalized (Templates)
CREATE TABLE tours_normalized (
    id SERIAL PRIMARY KEY,
    forecast_version_id INT REFERENCES forecast_versions,
    day INT,                      -- 1=Mo, 2=Di, ...
    start_ts TIME,
    end_ts TIME,
    duration_min INT,
    work_hours NUMERIC(5,2),
    span_group_key VARCHAR(50),
    tour_fingerprint VARCHAR(64),
    count INT DEFAULT 1,          -- Template expansion
    depot VARCHAR(50),
    skill VARCHAR(50)
);

-- 4. Tour Instances (Expanded)
CREATE TABLE tour_instances (
    id SERIAL PRIMARY KEY,
    forecast_version_id INT REFERENCES forecast_versions,
    tour_template_id INT REFERENCES tours_normalized,
    instance_no INT,
    day INT,
    start_ts TIME,
    end_ts TIME,
    crosses_midnight BOOLEAN,     -- Explicit flag
    duration_min INT,
    work_hours NUMERIC(5,2),
    span_group_key VARCHAR(50),
    depot VARCHAR(50),
    skill VARCHAR(50),
    UNIQUE(tour_template_id, instance_no)
);

-- 5. Plan Versions (Output)
CREATE TABLE plan_versions (
    id SERIAL PRIMARY KEY,
    forecast_version_id INT REFERENCES forecast_versions,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    seed INT,
    solver_config_hash VARCHAR(64),
    output_hash VARCHAR(64),      -- SHA-256 of assignments
    status VARCHAR(10) DEFAULT 'DRAFT',  -- 'DRAFT', 'LOCKED'
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(100)
);

-- 6. Assignments
CREATE TABLE assignments (
    id SERIAL PRIMARY KEY,
    plan_version_id INT REFERENCES plan_versions,
    driver_id INT,
    tour_instance_id INT REFERENCES tour_instances,
    day INT,
    block_id INT,
    role VARCHAR(20),             -- 'primary', 'backup'
    metadata JSONB
);

-- 7. Audit Log (Append-Only)
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    plan_version_id INT REFERENCES plan_versions,
    check_name VARCHAR(50),
    status VARCHAR(10),           -- 'PASS', 'FAIL'
    violation_count INT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. Freeze Windows
CREATE TABLE freeze_windows (
    id SERIAL PRIMARY KEY,
    forecast_version_id INT REFERENCES forecast_versions,
    freeze_start TIMESTAMPTZ,
    freeze_end TIMESTAMPTZ,
    status VARCHAR(20)
);

-- 9. Diff Results (Cache)
CREATE TABLE diff_results (
    id SERIAL PRIMARY KEY,
    forecast_old_id INT REFERENCES forecast_versions,
    forecast_new_id INT REFERENCES forecast_versions,
    added INT,
    removed INT,
    changed INT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. Schema Migrations
CREATE TABLE schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 8.2 Immutability Triggers

```sql
-- Prevent LOCKED plan modifications
CREATE FUNCTION prevent_locked_modification() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'LOCKED' THEN
        RAISE EXCEPTION 'Cannot modify LOCKED plan';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_locked_plan_modification
BEFORE UPDATE ON plan_versions
FOR EACH ROW EXECUTE FUNCTION prevent_locked_modification();

CREATE TRIGGER prevent_locked_assignments_modification
BEFORE UPDATE OR DELETE ON assignments
FOR EACH ROW
WHEN (EXISTS (
    SELECT 1 FROM plan_versions
    WHERE id = OLD.plan_version_id AND status = 'LOCKED'
))
EXECUTE FUNCTION prevent_locked_modification();
```

---

## 9. API & Integration

### 9.1 Python API

```python
# Import
from v3.parser import parse_forecast_text
from v3.solver_wrapper import solve_and_audit
from v3.db_instances import get_tour_instances, expand_tour_template
from v3.simulation_engine import (
    run_cost_curve, run_max_hours_policy, run_probabilistic_churn
)

# Parse Forecast
result = parse_forecast_text(
    raw_text="Mo 06:00-14:00 3 Fahrer",
    source="manual",
    save_to_db=True
)

# Expand Templates
expand_tour_template(forecast_version_id=1)

# Solve & Audit
plan = solve_and_audit(forecast_version_id=1, seed=94)

# Run Simulation
sim = run_probabilistic_churn(
    num_simulations=100,
    churn_threshold=0.10
)
```

### 9.2 REST API (geplant)

```
POST   /api/v3/forecasts              # Create forecast
GET    /api/v3/forecasts              # List forecasts
GET    /api/v3/forecasts/{id}         # Get forecast
POST   /api/v3/forecasts/{id}/solve   # Solve forecast
GET    /api/v3/plans/{id}             # Get plan
POST   /api/v3/plans/{id}/lock        # Lock plan
GET    /api/v3/plans/{id}/export      # Export proof pack
POST   /api/v3/simulate/{scenario}    # Run simulation
```

---

## 10. Compliance & Sicherheit

### 10.1 Arbeitszeit-Compliance

| Regel | Rechtsgrundlage | SOLVEREIGN Umsetzung |
|-------|-----------------|----------------------|
| Max. Tages-Span | Betriebsvereinbarung | ≤16h (3er/split), ≤14h (1er/2er) |
| Max. Wochenarbeitszeit | LTS Policy | ≤55h/Woche |
| Ruhepausen | §4 ArbZG | 30-60min Gaps in Blöcken |
| Ruhezeit | §5 ArbZG | ≥11h zwischen Schichten |
| Nachtarbeit | §6 ArbZG | Besondere Berücksichtigung |
| Fahrer-Lenk-/Ruhezeit | EU VO 561/2006 | Separate Prüfung erforderlich |

> **Rechtlicher Hinweis**:
> - **ArbZG §3** (8h, max 10h/Tag) gilt primär für Büroarbeiter
> - **Transport-Sektor**: EU VO 561/2006 regelt Lenk- und Ruhezeiten separat
> - **LTS-spezifisch**: 3er-Blöcke mit 16h Span sind durch Tarifvertrag/Betriebsvereinbarung gedeckt
> - Die 55h-Wochengrenze ist **LTS Policy**, nicht gesetzlich vorgeschrieben
> - Bei Ausgleich im Halbjahresschnitt auf Ø48h sind Spitzenwochen zulässig

### 10.2 Datenschutz (DSGVO)

- **Pseudonymisierung**: Fahrer-IDs statt Namen
- **Zweckbindung**: Nur für Schichtplanung
- **Speicherbegrenzung**: Automatische Löschung nach 12 Monaten
- **Audit Trail**: Für Betriebsrat einsehbar

### 10.3 Kryptografische Sicherheit

- **SHA-256 Hashing** für Input/Output
- **Immutable Event Log** für Audit Trail
- **Trigger-basierte Integrität** in PostgreSQL

---

## Anhang

### A. Code-Statistiken

```
backend_py/v3/
├── parser.py               576 Zeilen
├── diff_engine.py          280 Zeilen
├── solver_wrapper.py       330 Zeilen
├── solver_v2_integration.py 250 Zeilen
├── audit_fixed.py          830 Zeilen
├── seed_sweep.py           520 Zeilen
├── simulation_engine.py  2,500 Zeilen
├── plan_churn.py           212 Zeilen
├── near_violations.py      302 Zeilen
├── freeze_windows.py       482 Zeilen
├── peak_fleet.py           229 Zeilen
├── proof_pack.py           200 Zeilen
├── compose.py              300 Zeilen
├── db.py                   450 Zeilen
├── db_instances.py         194 Zeilen
├── models.py               430 Zeilen
├── config.py               160 Zeilen
───────────────────────────────────
Total V3 Modules:         ~7.500 Zeilen

backend_py/
├── streamlit_app.py      2,850 Zeilen
├── cli.py                  770 Zeilen
───────────────────────────────────
Total Application:       ~11.000 Zeilen
```

### B. Deployment

```bash
# Start PostgreSQL
docker compose up -d postgres

# Apply Migrations
python backend_py/apply_p0_migration.py

# Run Tests
python backend_py/test_v3_without_db.py

# Start UI
streamlit run backend_py/streamlit_app.py
```

### C. Kontakt

- **Entwicklung**: SOLVEREIGN Engineering Team
- **Support**: support@solvereign.de
- **Repository**: github.com/lts-transport/solvereign

---

*SOLVEREIGN V3.2 - Dokumentation Stand Januar 2026*
*© LTS Transport & Logistik GmbH*
