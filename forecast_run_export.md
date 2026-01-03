# Forecast Optimization Run Export
**Run ID:** test_forecast_pt_min
**Timestamp:** 2026-01-01 21:56
**Configuration:**
- PT Weight: 10.0
- Hard Driver Limit: 145 (Mode A)
- Active Days (Dynamic FTE): Enabled

## Progress Summary
| Iter | Pool Size | LP Objective | Incumbent | Wall Time (s) | Notes |
|------|-----------|--------------|-----------|---------------|-------|
| 1    | 3,000     | 12,633.15    | 9999      | 7.2           | Initial Seed (High PT use) |
| 5    | 9,000     | 11,008.75    | 9999      | 126.5         | Obj decreased by ~13% |
| 10   | 16,500    | 9,864.85     | 9999      | 313.4         | Obj decreased by ~22% |
| 15   | 24,000    | 8,551.20     | 9999      | 423.0         | Obj decreased by ~32% |
| 18   | 28,500    | 7,678.41     | 9999      | 453.6         | Significant drop |
| 19   | 30,000    | 7,526.16     | 9999      | 463.6         | Lowest Objective |
| 20   | 21,500    | 7,900.81     | 9999      | 472.4         | Pool Pruning Occurred |

## Detailed Analysis

**Objective Interpretation:**
With `Cost = Driver + 10 * IsPT`, the starting objective of ~12,633 implies substantial PT usage (approx 1000-1100 PT drivers used to cover 1385 tours).
By Iteration 19, the objective dropped to **7,526**.
This represents a massive shift from PT to FTE rosters.
Approximate improvement: (12633 - 7526) / 10 = **~510 fewer PT drivers** (replaced by efficient FTEs).

**Incumbent Status (9999):**
The Restricted MIP reports "Infeasible" (Incumbent 9999) because the hard constraint `Total Drivers <= 145` cannot yet be met by the current pool columns. 
The system requires a highly optimized pool where almost all tours are covered by 145 FTE drivers (approx 9.5 tours/driver) to become valid. The LP trend shows we are moving in the right direction. 
Recommend running for 100+ iterations or relaxing the hard constraint to a soft penalty for intermediate tracking.
