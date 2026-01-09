# SOLVEREIGN Routing Pack - KPI Baseline

> **Version**: 1.0 (Gate 6 Pilot)
> **Last Updated**: 2026-01-06
> **Status**: BASELINE ESTABLISHED

---

## 1. Executive Summary

This document establishes KPI baselines for comparing **Manual Planning** vs **SOLVEREIGN Routing Pack** performance. These metrics will be tracked during the pilot phase to validate optimization improvements.

---

## 2. KPI Categories

### 2.1 Operational Efficiency

| KPI | Definition | Manual Baseline | SOLVEREIGN Target | Measurement |
|-----|------------|-----------------|-------------------|-------------|
| **Planning Time** | Time to create daily plan | 60-90 min | < 5 min | Stopwatch: FLS export → Plan locked |
| **Stops per Vehicle** | Average deliveries per vehicle | 12-15 | 15-20 | Total stops / Vehicles used |
| **Vehicle Utilization** | % of vehicle capacity used | 65-75% | 80-90% | Used capacity / Max capacity |
| **Empty Miles** | Distance without cargo | 15-20% | < 10% | Deadhead km / Total km |

### 2.2 Service Quality

| KPI | Definition | Manual Baseline | SOLVEREIGN Target | Measurement |
|-----|------------|-----------------|-------------------|-------------|
| **On-Time Delivery %** | Arrivals within time window | 85-90% | > 95% | On-time stops / Total stops |
| **First-Attempt Success** | Deliveries without reschedule | 88-92% | > 95% | Successful / Attempted |
| **Customer Complaints** | Delivery-related complaints | 5-10/week | < 3/week | Support tickets |

### 2.3 Resource Optimization

| KPI | Definition | Manual Baseline | SOLVEREIGN Target | Measurement |
|-----|------------|-----------------|-------------------|-------------|
| **Total Distance (km)** | Daily fleet kilometers | Baseline TBD | -10% | Sum of all routes |
| **Total Duration (h)** | Driver hours on road | Baseline TBD | -10% | Sum of route times |
| **Overtime Hours** | Hours beyond shift | 5-10h/week | < 2h/week | Actual - Scheduled |
| **Fuel Cost** | Daily fuel consumption | Baseline TBD | -10% | Fleet fuel receipts |

### 2.4 System Reliability

| KPI | Definition | Manual Baseline | SOLVEREIGN Target | Measurement |
|-----|------------|-----------------|-------------------|-------------|
| **Solver Success Rate** | Plans without solver failure | N/A | > 99% | Successful / Attempted |
| **Audit Pass Rate** | Plans passing all audits | N/A | > 95% | Passed / Total |
| **System Uptime** | Service availability | N/A | > 99.5% | Monitoring |

---

## 3. Baseline Data Collection

### 3.1 Manual Planning Baseline (Week 0)

**Collection Period**: One week before pilot start

```
┌────────────────────────────────────────────────────────────────┐
│  DATA TO COLLECT (per day)                                     │
├────────────────────────────────────────────────────────────────┤
│  1. Planning start time (FLS export)                           │
│  2. Planning end time (routes finalized)                       │
│  3. Number of stops scheduled                                  │
│  4. Number of vehicles used                                    │
│  5. Total planned distance (km)                                │
│  6. Actual delivery times (from driver app)                    │
│  7. No-shows and rescheduled                                   │
│  8. Customer complaints received                               │
│  9. Overtime hours (actual vs scheduled)                       │
│  10. Fuel consumption (liters)                                 │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 Collection Template

| Date | Stops | Vehicles | Distance (km) | Duration (h) | On-Time % | No-Shows | Overtime (h) |
|------|-------|----------|---------------|--------------|-----------|----------|--------------|
| Mon  |       |          |               |              |           |          |              |
| Tue  |       |          |               |              |           |          |              |
| Wed  |       |          |               |              |           |          |              |
| Thu  |       |          |               |              |           |          |              |
| Fri  |       |          |               |              |           |          |              |
| **Avg** |    |          |               |              |           |          |              |

---

## 4. SOLVEREIGN KPI Extraction

### 4.1 Automatic KPI Calculation

SOLVEREIGN automatically calculates KPIs from plan data:

```python
# From evidence_pack.py - KPIEvidence
@dataclass
class KPIEvidence:
    total_stops: int
    assigned_stops: int
    unassigned_stops: int
    coverage_percentage: float
    total_vehicles_used: int
    total_vehicles_available: int
    vehicle_utilization_percentage: float
    total_distance_km: float
    total_duration_min: int
    avg_stops_per_vehicle: float
    on_time_percentage: float
    hard_tw_violations: int
    soft_tw_violations: int
```

### 4.2 API Endpoint for KPIs

```bash
# Get plan KPIs
curl "$API_URL/api/v1/routing/plans/{plan_id}/kpis" \
  -H "X-API-Key: $API_KEY"

# Response
{
  "plan_id": "plan-123",
  "generated_at": "2026-01-06T07:30:00+01:00",
  "kpis": {
    "total_stops": 150,
    "assigned_stops": 148,
    "unassigned_stops": 2,
    "coverage_percentage": 98.67,
    "total_vehicles_used": 10,
    "total_vehicles_available": 12,
    "vehicle_utilization_percentage": 83.33,
    "total_distance_km": 423.5,
    "total_duration_min": 540,
    "avg_stops_per_vehicle": 14.8,
    "on_time_percentage": 96.5,
    "hard_tw_violations": 0,
    "soft_tw_violations": 3
  }
}
```

### 4.3 Weekly KPI Report

```bash
# Get weekly aggregated KPIs
curl "$API_URL/api/v1/routing/kpis/weekly?week=2026-W02" \
  -H "X-API-Key: $API_KEY"

# Response
{
  "week": "2026-W02",
  "days_covered": 5,
  "aggregated_kpis": {
    "total_stops": 750,
    "avg_stops_per_day": 150,
    "avg_coverage_percentage": 98.5,
    "avg_on_time_percentage": 96.2,
    "total_distance_km": 2150.5,
    "avg_stops_per_vehicle": 15.2,
    "total_unassigned": 8,
    "total_repairs": 3
  }
}
```

---

## 5. Comparison Framework

### 5.1 Daily Comparison

| Metric | Manual | SOLVEREIGN | Delta | % Change |
|--------|--------|------------|-------|----------|
| Planning Time | 75 min | 4 min | -71 min | -94.7% |
| Stops per Vehicle | 13 | 16 | +3 | +23.1% |
| On-Time % | 87% | 97% | +10% | +11.5% |
| Total Distance | 450 km | 410 km | -40 km | -8.9% |

### 5.2 Statistical Significance

For pilot validation, track at minimum:
- **5 days** of SOLVEREIGN data
- **5 days** of manual baseline

Use paired t-test for significance:
- p < 0.05 = statistically significant improvement
- p < 0.01 = highly significant improvement

---

## 6. Churn Metrics (Repair Operations)

### 6.1 Churn Baseline

| Metric | Definition | Target |
|--------|------------|--------|
| **Avg Churn Score** | Average repair churn | < 5,000 |
| **Repairs per Day** | Number of repair events | < 5 |
| **Stops Moved** | Stops reassigned per repair | < 3 |
| **Driver Notifications** | Route change alerts | < 10/day |

### 6.2 Churn by Event Type

| Event Type | Expected Frequency | Expected Churn |
|------------|-------------------|----------------|
| NO_SHOW | 3-5/day | 1,000 per event |
| DELAY | 1-2/day | 500 per event |
| VEHICLE_DOWN | 0.5/week | 15,000 per event |
| STOP_ADDED | 1-2/day | 2,000 per event |

---

## 7. Pilot Success Criteria

### 7.1 Minimum Requirements (MUST PASS)

| Requirement | Threshold | Measurement |
|-------------|-----------|-------------|
| Coverage | ≥ 98% | Assigned stops / Total |
| On-Time | ≥ 95% | On-time / Attempted |
| No Overlap | 100% | Audit check |
| Solver Success | ≥ 99% | Successful solves |

### 7.2 Target Improvements (SHOULD MEET)

| Metric | Improvement vs Manual | Confidence |
|--------|----------------------|------------|
| Planning Time | ≥ 90% reduction | High |
| Total Distance | ≥ 5% reduction | Medium |
| Stops per Vehicle | ≥ 15% increase | Medium |
| Overtime | ≥ 50% reduction | Low |

### 7.3 Go/No-Go Thresholds

| Status | Criteria |
|--------|----------|
| **GO** | All MUST PASS met + 2/4 SHOULD MEET |
| **CONDITIONAL GO** | All MUST PASS met + 1/4 SHOULD MEET |
| **NO-GO** | Any MUST PASS failed |

---

## 8. Reporting Schedule

### 8.1 Daily Report (Automated)

Generated at 19:00 daily:
- Today's KPIs vs baseline
- Repair events summary
- Issues requiring attention

### 8.2 Weekly Report (Manual Review)

Generated Friday 17:00:
- Week-over-week comparison
- Trend analysis
- Pilot progress vs targets
- Action items for next week

### 8.3 Pilot Summary (End of Pilot)

Comprehensive analysis:
- Statistical comparison
- ROI calculation
- Lessons learned
- Production readiness assessment

---

## 9. KPI Dashboard Specification

### 9.1 Primary Metrics (Always Visible)

```
┌─────────────────────────────────────────────────────────────────┐
│  TODAY'S PERFORMANCE                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Coverage: 98.5%  │  On-Time: 96.2%  │  Vehicles: 10/12       │
│   [██████████░]    │  [██████████░]   │  [████████░░]          │
│                                                                 │
│   Stops: 148/150   │  Distance: 423km │  Duration: 9h          │
│                                                                 │
│   Repairs: 2       │  Churn: 3,500    │  Unassigned: 2         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 Trend Chart (7-Day Rolling)

```
On-Time Delivery %
100% ┤                          ●
 95% ┤      ●     ●     ●  ●
 90% ┤  ●
 85% ┤●
     └────┬────┬────┬────┬────┬────┬────
         Mon  Tue  Wed  Thu  Fri  Sat  Sun

     ── Manual Baseline (85-90%)
     ●● SOLVEREIGN Actual
```

---

## 10. Data Export Format

### 10.1 CSV Export for Analysis

```csv
date,plan_id,stops_total,stops_assigned,vehicles_used,distance_km,duration_min,on_time_pct,repairs,churn_total
2026-01-06,plan-123,150,148,10,423.5,540,96.5,2,3500
2026-01-07,plan-124,145,145,10,401.2,510,97.2,1,1200
...
```

### 10.2 JSON Export for Integration

```json
{
  "export_date": "2026-01-06T19:00:00+01:00",
  "period": "daily",
  "plans": [
    {
      "plan_id": "plan-123",
      "date": "2026-01-06",
      "kpis": { ... },
      "repairs": [ ... ],
      "audit_results": { ... }
    }
  ]
}
```

---

## Appendix: Calculation Formulas

### Coverage %
```
coverage_pct = (assigned_stops / total_stops) × 100
```

### On-Time %
```
on_time_pct = (stops_within_tw / total_attempted) × 100
```

### Vehicle Utilization %
```
utilization_pct = (vehicles_used / vehicles_available) × 100
```

### Churn Score
```
churn_score = (vehicle_changes × 10000) + (sequence_changes × 1000) + (unassigned × 100000)
```

### Planning Time Reduction %
```
reduction_pct = ((manual_time - solvereign_time) / manual_time) × 100
```

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-06 | SOLVEREIGN | Initial baseline document |
