# KPI Drift Monitoring

> **Purpose**: Detect regressions and anomalies in solver output
> **Last Updated**: 2026-01-07

---

## PURPOSE

KPI drift monitoring detects when solver output deviates significantly from established baselines, enabling:
1. Early regression detection
2. Performance degradation alerts
3. Quality assurance before customer impact

---

## MONITORED KPIs

### Roster Pack

| KPI | Description | Baseline | Warning | Critical |
|-----|-------------|----------|---------|----------|
| `total_drivers` | Number of drivers assigned | 145 | ±5% | ±15% |
| `fte_ratio` | % of FTE (≥40h) drivers | 100% | <95% | <85% |
| `pt_ratio` | % of PT (<40h) drivers | 0% | >5% | >15% |
| `coverage_pct` | % of tours assigned | 100% | <100% | <95% |
| `max_weekly_hours` | Highest driver weekly hours | 54h | >55h | >60h |
| `avg_weekly_hours` | Average driver weekly hours | 42h | ±10% | ±20% |
| `audit_pass_rate` | % of audits passing | 100% | <100% | <90% |

### Routing Pack

| KPI | Description | Baseline | Warning | Critical |
|-----|-------------|----------|---------|----------|
| `coverage_pct` | % of stops served | 100% | <100% | <95% |
| `tw_violations` | Time window violations | 0 | >0 | >5 |
| `total_distance_km` | Total route distance | varies | +15% | +30% |
| `total_duration_h` | Total route duration | varies | +15% | +30% |
| `routes_used` | Number of routes | varies | +20% | +50% |
| `capacity_utilization` | Avg vehicle fill % | >80% | <70% | <50% |

---

## BASELINE MANAGEMENT

### Baseline File

Location: `.claude/state/drift-baselines.json`

```json
{
  "api_p95_ms": 120,
  "solver_p95_s": 45,
  "solver_peak_rss_mb": 2048,
  "last_updated": "2026-01-07T08:00:00Z",

  "roster": {
    "gurkerl": {
      "total_drivers": 145,
      "fte_ratio": 1.0,
      "coverage_pct": 1.0,
      "max_weekly_hours": 54,
      "baseline_seed": 94,
      "baseline_output_hash": "d329b1c4..."
    }
  },

  "routing": {
    "wien": {
      "coverage_pct": 1.0,
      "tw_violations": 0,
      "routes_used": 12,
      "baseline_seed": 94,
      "baseline_output_hash": "abc123..."
    }
  }
}
```

### Update Baseline

```bash
python -m backend_py.tools.kpi_drift update-baseline \
    --pack roster \
    --tenant gurkerl \
    --forecast-id 123 \
    --seed 94
```

---

## DRIFT DETECTION

### Drift Score Calculation

```python
def compute_drift_score(current_kpis: dict, baseline_kpis: dict) -> float:
    """Compute overall drift score (0-100)."""

    weights = {
        'total_drivers': 0.3,
        'coverage_pct': 0.3,
        'fte_ratio': 0.2,
        'max_weekly_hours': 0.2
    }

    drift_score = 0
    for kpi, weight in weights.items():
        if kpi in current_kpis and kpi in baseline_kpis:
            baseline = baseline_kpis[kpi]
            current = current_kpis[kpi]

            if baseline != 0:
                pct_change = abs(current - baseline) / baseline * 100
                drift_score += pct_change * weight

    return drift_score
```

### Threshold Actions

| Drift Score | Level | Action |
|-------------|-------|--------|
| 0-10% | OK | Continue normally |
| 10-25% | WARNING | Alert. Investigate before release. |
| 25-50% | ALERT | Block release. Investigate immediately. |
| >50% | INCIDENT | Create S2 incident. Investigate root cause. |

---

## MONITORING WORKFLOW

### Post-Solve Check

```python
async def check_kpi_drift_after_solve(
    plan_version_id: int,
    tenant_id: str,
    pack_id: str
) -> DriftCheckResult:
    """Run after every solve to detect drift."""

    # Get current KPIs
    current_kpis = await compute_plan_kpis(plan_version_id)

    # Get baseline
    baselines = load_baselines()
    baseline_kpis = baselines.get(pack_id, {}).get(tenant_id, {})

    if not baseline_kpis:
        return DriftCheckResult(status="SKIP", reason="No baseline")

    # Compute drift
    drift_score = compute_drift_score(current_kpis, baseline_kpis)

    # Take action based on drift
    if drift_score > 50:
        await create_incident(
            severity="S2",
            summary=f"KPI drift {drift_score:.1f}% detected for {tenant_id}/{pack_id}"
        )
        return DriftCheckResult(status="INCIDENT", drift_score=drift_score)

    elif drift_score > 25:
        await send_alert(f"KPI ALERT: {drift_score:.1f}% drift for {tenant_id}/{pack_id}")
        return DriftCheckResult(status="ALERT", drift_score=drift_score)

    elif drift_score > 10:
        await log_warning(f"KPI WARNING: {drift_score:.1f}% drift for {tenant_id}/{pack_id}")
        return DriftCheckResult(status="WARNING", drift_score=drift_score)

    return DriftCheckResult(status="OK", drift_score=drift_score)
```

### Nightly Trend Analysis

```python
def analyze_trends(tenant_id: str, pack_id: str, days: int = 30):
    """Analyze KPI trends over time."""

    history = load_kpi_history(tenant_id, pack_id, days)

    trends = {}
    for kpi in ['total_drivers', 'coverage_pct', 'max_weekly_hours']:
        values = [h[kpi] for h in history if kpi in h]

        if len(values) >= 7:
            # Simple linear regression for trend
            slope = compute_slope(values)
            trends[kpi] = {
                'slope': slope,
                'trend': 'increasing' if slope > 0 else 'decreasing',
                'significance': abs(slope) > 0.01
            }

    return trends
```

---

## CLI COMMANDS

### Check Drift

```bash
python -m backend_py.tools.kpi_drift check \
    --tenant gurkerl \
    --pack roster \
    --plan-version-id 123

# Output:
# Baseline: total_drivers=145, fte_ratio=100%, coverage=100%
# Current:  total_drivers=148, fte_ratio=98%, coverage=100%
# Drift Score: 4.2% (OK)
```

### Generate Report

```bash
python -m backend_py.tools.kpi_drift report \
    --tenant gurkerl \
    --pack roster \
    --days 30 \
    --output kpi_report.md
```

### Analyze Trends

```bash
python -m backend_py.tools.kpi_drift trends \
    --tenant gurkerl \
    --pack roster \
    --days 30

# Output:
# total_drivers: stable (slope: +0.02/day)
# fte_ratio: decreasing (slope: -0.1%/day) ⚠️
# coverage_pct: stable (100%)
```

---

## ALERTING INTEGRATION

### Slack Notification

```python
async def send_drift_alert(result: DriftCheckResult):
    if result.status == "WARNING":
        emoji = "⚠️"
    elif result.status == "ALERT":
        emoji = "🚨"
    elif result.status == "INCIDENT":
        emoji = "🔥"
    else:
        return

    message = f"""
{emoji} KPI Drift Detected

Tenant: {result.tenant_id}
Pack: {result.pack_id}
Drift Score: {result.drift_score:.1f}%
Status: {result.status}

Details:
{format_kpi_comparison(result.current, result.baseline)}
"""

    await slack.post_message("#alerts", message)
```

### Incident Auto-Creation

```python
if drift_result.status == "INCIDENT":
    await create_incident(
        id=generate_incident_id(),
        severity="S2",
        status="new",
        summary=f"KPI drift {drift_result.drift_score:.1f}% for {tenant}/{pack}",
        evidence=[{
            "type": "kpi_comparison",
            "current": drift_result.current,
            "baseline": drift_result.baseline
        }]
    )
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Drift > 50% | S2 | Create incident. Block release. Investigate. |
| Drift 25-50% | S2 | Block release. Investigate before continuing. |
| Drift 10-25% | S3 | Warn. Review before release. |
| Consistent downward trend | S3 | Schedule investigation. Review algorithm. |
| Baseline outdated (>30 days) | S4 | Update baseline. Document changes. |
