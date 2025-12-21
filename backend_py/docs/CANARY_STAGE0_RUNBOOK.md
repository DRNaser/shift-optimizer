# Canary Stage 0 Runbook (Flags OFF)

## 0) Start-Setup

### Server starten (prod-nah, deterministisch)

```bash
cd backend_py
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> [!IMPORTANT]
> **--workers 1** ist wichtig für:
> - Deterministisches Verhalten bleibt stabil
> - Signature-LRU bleibt konsistent (kein "pro Worker eigener Cache")

### Smoke Checks

```bash
curl -fsS http://localhost:8000/api/v1/healthz
curl -fsS http://localhost:8000/api/v1/readyz
curl -fsS http://localhost:8000/api/v1/metrics | head
```

### Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: "shift-optimizer"
    metrics_path: "/api/v1/metrics"  # WICHTIG: nicht /metrics!
    static_configs:
      - targets: ["<HOST>:8000"]
```

> [!TIP]
> **Für echte Production Readiness:** Stage 0 im Docker-Image laufen lassen (gleicher Runtime-Stack wie Prod):
> ```bash
> docker build -t shift-optimizer:2.0.0 .
> docker run --rm -p 8000:8000 shift-optimizer:2.0.0
> ```

---

## 1) Stage-0 Monitoring (Rules)

### A) WARN (Monitor - nicht stoppen)

Kleine Überschreitungen (1-5s) sind normal.

* **Irgendein Overrun (30m)**

```promql
increase(solver_budget_overrun_total{phase="total"}[30m]) > 0
```

### B) STOP (Rollback / Hotfix)

Echtes Risiko oder Regression.

1. **Overrun-Rate zu hoch (> 2% in 60m)**

```promql
(
  increase(solver_budget_overrun_total{phase="total"}[60m])
  /
  clamp_min(increase(solver_signature_runs_total[60m]), 1)
) > 0.02
```

2. **P95 Laufzeit zu hoch (> 126s in 60m)** *(bei 120s Budget)*

```promql
histogram_quantile(0.95,
  sum by (le) (rate(solver_phase_duration_seconds_bucket{phase="total"}[10m]))
) > 126
```

3. **Safety Stop (bei wenig Traffic)**

```promql
increase(solver_budget_overrun_total{phase="total"}[60m]) >= 3
```

### C) Guardrails (dürfen nicht regressieren)

| Metrik | PromQL | Interpretation |
|--------|--------|----------------|
| **Infeasible Rate** | `increase(solver_infeasible_total[10m]) / clamp_min(increase(solver_signature_runs_total[10m]), 1)` | Nicht höher als Baseline |
| **Signature Uniqueness** | `increase(solver_signature_unique_total[10m]) / clamp_min(increase(solver_signature_runs_total[10m]), 1)` | Keine komischen Drops/Spikes |
| **SetPartitioning Fallback** | `increase(solver_set_partitioning_total{status=~"timeout|fallback"}[10m])` | Plötzlich häufig -> Untersuchen |

---

## 2) Determinismus nachweisen

### Synthetischer Canary-Run (empfohlen)

Alle 10-15 Minuten dieselbe Instanz mit `seed=42` lösen:

```bash
# Beispiel: Cron-Job oder manuell
curl -X POST http://localhost:8000/api/v1/schedule \
  -H "Content-Type: application/json" \
  -d '{"tours": [...], "seed": 42, "time_limit_seconds": 30}'
```

**Erwartung:** `solution_signature` bleibt bei identischem Input/Seed immer gleich.

---

## 3) Exit Criteria Stage 0

### ✅ GO zu Stage 1

- [ ] Budget Overrun-Rate **< 2%**
- [ ] P95 Laufzeit **< 126s**
- [ ] Infeasible Rate **nicht regressiv**
- [ ] Keine erhöhte Error-Rate
- [ ] Determinismus-Runs: Signature **stabil**

### ❌ NO-GO

- Overrun-Rate > 2%
- P95 Laufzeit > 126s
- >= 3 Absolute Overruns in 1h
- Sustained API Errors
- Deutlich höhere Infeasible Rate vs Baseline

---

## 4) Quick Alerts Summary

| Alert | Trigger |
|-------|---------|
| **WARN** Overrun | `increase(...[30m]) > 0` |
| **STOP** Overrun Rate | `Rate > 2%` |
| **STOP** P95 Latency | `P95 > 126s` |
| **STOP** Abs Overruns | `Count >= 3` |
| API Errors | `rate > 0` |

---

## 5) LRU-Implementierung (verifiziert ✅)

```python
# prometheus_metrics.py - Zeilen 193-200
signature_runs_total.inc()  # IMMER

if 'solution_signature' in run_report:
    sig = run_report['solution_signature']
    if _signature_lru.is_new(sig):     # NUR wenn neu im 5k-Fenster
        signature_unique_total.inc()
```

**Korrekt implementiert:** ✅

---

## Nächster Schritt

Nach erfolgreichem Stage 0 (24-48h, alle Exit Criteria erfüllt):

→ **Stage 1 starten** mit Feature Flags ON:
```python
enable_fill_to_target_greedy = True
enable_bad_block_mix_rerun = True
```
