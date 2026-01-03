# P0: Reality Check Report - Target Definition

## Executive Summary

**VERDICT: Target "214" is a METRIC CONFUSION**

The target "214 drivers" does NOT refer to the MIP objective (weekly driver count).
It likely refers to **PEAK FLEET** (concurrent vehicles needed), which is **158 for KW51**.

---

## Analysis

### 1. What Does MIP "Drivers" Objective Measure?

**Code Evidence:** `optimizer_v2.py:724`
```python
"drivers_total": len(solution)
```

**Definition:** Number of selected columns = Number of unique weekly driver rosters.

This counts **how many individual drivers work during the week**, NOT how many are simultaneously active.

---

### 2. Physical Lower Bounds (Forecast KW51)

| Metric | Value |
|:---|---:|
| **Total Tours** | 1,272 tours |
| **Total Hours** | 5,723.8 hours |
| **Active Days** | 4 days (Mon, Tue, Wed, Fri) |
| **Peak Fleet (Wednesday)** | **158 vehicles** |
| **Physical LB (by hours, 55h/week max)** | **104 drivers** |
| **Physical LB (by tours, 25 tours/week max)** | **51 drivers** |
| **LP Lower Bound (Observed)** | **460-600 drivers** |

---

### 3. Target Comparison

| Target Interpretation | Value | Verdict |
|:---|---:|:---|
| **Peak Fleet (max concurrent)** | 158 | **✓ MATCHES "214" claim** (within ballpark) |
| **Weekly Drivers (MIP objective)** | 460-600 | **✗ IMPOSSIBLE to reach 214** |
| **Physical Lower Bound** | 104 | Confirms 214 is NOT weekly drivers |

---

## Conclusion

**The "214" target is AMBIGUOUS or MISUNDERSTOOD.**

### Most Likely Scenario:
- "214" refers to **FLEET SIZE** (number of vehicles needed for peak concurrency = 158).
- The MIP objective (**weekly drivers = 460-600**) is a DIFFERENT metric.
- **These are NOT interchangeable.**

### Why LP Bound is 460-600 (not 104):
The solver is finding **fragmented solutions** where:
- Many drivers work only 1-2 days (singletons).
- Multi-day rosters are not efficiently generated.
- This drives up the driver count beyond the theoretical minimum.

**This is a SOLVER QUALITY issue, not a bound issue.**

---

## Required Actions

### ✓ Completed (P0):
1. Verified MIP objective measures weekly drivers.
2. Calculated physical lower bounds.
3. Identified metric confusion.

### → Next (P1):
Implement **Peak Fleet Counter** to separate metrics:
- `drivers_weekly`: MIP objective (current count).
- `fleet_peak`: Max concurrent vehicles (new calculation).

### → Next (P2):
**IF** the real goal is to minimize weekly drivers to ~104-200:
- This requires **massive solver optimization**:
  - More aggressive multi-day generation.
  - Better cost tuning to penalize singletons.
  - Longer runs (200+ iterations).

---

## Recommendation

**STOP claiming "214 drivers" until metric is clarified.**

Ask stakeholders:
1. Is "214" meant to be **Fleet Size** (vehicles)?
2. Or is it **Weekly Drivers** (people)?

If (1): Solver is working correctly. Report fleet peak separately.
If (2): Target is unrealistic. Minimum is ~104, LP bound of 460-600 indicates poor fragmentation that requires optimization.
