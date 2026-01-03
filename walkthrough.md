# Walkthrough — Core V2 Stabilization & Final Optimization (10× Speedup)

**Status:** Production-ready ✅  
**Last updated (UTC):** 2025-12-31 16:14  
**Core:** V2 (12h Relative Window + Bounded Gap Logic + MIP-friendly 12k Subset)

---

## 1) Executive Summary

This walkthrough documents the final stabilized configuration and the performance/quality outcomes after restoring cross‑day linking and optimizing runtime.

### Final Outcomes
- **Cross-day linking restored** (coordinate mismatch fixed + gap-day handling)
- **Massive multi-day connectivity preserved** (~**5,000,000 edges/iteration**)
- **Iteration runtime reduced ~10×** (from ~150s to **~12–15s** per iteration)
- **MIP stability maintained** (Final MIP within budget; restricted MIP improved)

---

## 2) Root Cause & Fixes (What Changed)

### 2.1 Critical Bug Root Cause (Fixed)
**Symptom:** `avg_candidates_per_duty = 0.0` despite widening the connector window.  
**Cause:** The linker queried **absolute times** (e.g., 1860 minutes) against a **day-relative index** (0–1440), producing systematic miss matches.

### 2.2 Fix: Relative Coordinate Search (Implemented)
The search window is computed in the same coordinate system as the day-relative duty index:

- `search_start = prev_end + rest_min - (days_diff * 1440)`

This allows the successor lookup to correctly match duties on the next day (or beyond) even when absolute offsets exceed 1440 minutes.

### 2.3 Fix: Bounded Gap-Day Handling (Implemented)
For missing-day gaps (e.g., Fri→Mon), candidate generation uses **bounded gap logic** (not full-day scans), ensuring feasibility while controlling edge explosion.

---

## 3) Locked Production Configuration (Final)

These parameters are **locked** for deployment (Core V2.1 equivalent):

| Parameter | Final Value | Notes |
|---|---:|---|
| `connector_window` | **12h** (720 min) | **Relative** window after rest, in day-relative coordinates |
| `max_candidates_per_duty` | **50** | Down from 250; main speed lever |
| `restricted_mip_time_limit` | **45s** | Up from 30s to reduce feasibility friction |
| `final_mip_time_limit` | **300s** | Stability guardrail |
| `subset_size_cap` | **12,000** | MIP-friendly subset with bottleneck/density prioritization |

---

## 4) KPI / Observability (Permanent Metrics)

The following metrics are **persistently logged** each iteration (manifest KPI set):

- `avg_candidates_per_duty`
- `edges_created`
- `comparisons_total`
- `label_propagate_time`
- `linkable_duties`

Recommended additional (optional) derived checks:
- `hit_rate = duties_with_candidates / linkable_duties`
- `truncation_count = duties_hitting_cap`
- `edges_per_second` (for perf drift detection)

---

## 5) Verified Results

### 5.1 Speed & Scalability (Before → After)
| Metric | Previous (cap 250) | Optimized (cap 50) | Improvement |
|---|---:|---:|---:|
| Linker time / iteration | ~40–160s | **~12–15s** | **~10× faster** |
| Edges created / iteration | ~20,000,000 | **~5,000,000** | Still massive |
| Truncation | 0 | **~100k duties truncated** | Expected trade-off |

### 5.2 Quality Signal (From Production Run)
- Cross-day linking unlocks efficient multi-day pairings.
- LP lower bound reached ~**370.5** (strong signal that driver target is attainable).
- Projected driver count in target range **~420–460** (depends on integrality/feasibility behavior).

---

## 6) How to Run (Operational Steps)

### 6.1 Standard Production Run
1. Ensure Core V2 parameters match the table in **Section 3**.
2. Run the iterative restricted MIP loop (45s per iteration).
3. Run Final MIP (300s budget) as the convergence backstop.
4. Persist:
   - per-iteration KPI metrics
   - final roster counts / objective values
   - seed/config snapshot for reproducibility

### 6.2 Acceptance Criteria (DoD)
A run is acceptable when:
- `avg_candidates_per_duty > 0` and stable
- `edges_created > 0` and consistent (no sudden collapse)
- no Final MIP timeouts under 300s
- no recurring infeasible flaps beyond tolerance
- runtime remains near the expected **12–15s/iter** band

---

## 7) Guardrails & Auto-Pause Triggers

Immediately pause and investigate if any of the following occur:
- `avg_candidates_per_duty == 0` (regression of cross-day linking)
- `edges_created == 0` (graph collapse)
- linker time jumps >3× baseline without configuration change
- Final MIP hits timeout or repeatedly approaches budget
- infeasible flaps become frequent

---

## 8) Troubleshooting Cheatsheet

### Problem: avg_candidates collapses to 0
- Confirm coordinate system alignment (absolute vs day-relative)
- Confirm `search_start` subtracts `days_diff * 1440`
- Validate duty index keys are day-relative (0–1440)

### Problem: runtime spikes again
- Check whether `max_candidates_per_duty` was changed or ignored
- Inspect edge counts per iter (if edges jump, a filter/guard is bypassed)
- Verify bounded gap logic is active (not full-day scan)

### Problem: restricted MIP struggles
- Keep Final MIP as stability backstop
- Consider small increases to restricted time limit (only if needed)
- Ensure subset preserves bottlenecks/dense columns

---

## 9) Deployment Notes

This configuration is suitable for deployment because it satisfies:
- **Reliability:** ✅ (12h relative window + bounded gap fix)
- **Performance:** ✅ (O(N log N) indexing + candidate cap)
- **Quality:** ✅ (massive multi-day connectivity + MIP-friendly subsetting)
- **Observability:** ✅ (permanent KPIs in manifest)

---

## 10) Changelog (Condensed)

- **Fixed:** cross-day linker coordinate mismatch (absolute vs day-relative)
- **Added:** bounded gap-day logic for missing days (Fri→Mon etc.)
- **Optimized:** candidate cap 250 → 50
- **Tuned:** restricted MIP time limit 30s → 45s
- **Kept:** final MIP budget 300s and 12k subset strategy
