# Changelog

All notable changes to ShiftOptimizer will be documented in this file.

## [2.0.0] - 2024-12-20

### Added

#### Core Architecture
- **Deterministic solver**: Single-thread CP-SAT (`num_search_workers=1`), fixed seed, stable ordering
- **Budgeted execution**: Hard time slices per phase (50% phase1, 15% phase2, 28% lns, 5% buffer)
- **Canonical RunReport**: `to_canonical_json()` excludes timestamps for CI reproducibility

#### Phase 1: Packability
- `compute_tour_has_multi()` - O(n) precompute for multi-tour options
- 1er-with-alternative penalty (+2.0 when multi-tour block exists)
- 3er bonus (-3.0) / 2er bonus (-1.0) for packability shaping
- Metrics: `forced_1er_rate`, `missed_3er_opps_count`

#### Phase 2: Fill-to-Target
- `fill_to_target_score()` - Config-driven scoring with threshold-crossing bonus
- `compute_block_mix_ratios()` - PT ratio and underfull ratio calculation
- `should_trigger_rerun()` - BAD_BLOCK_MIX feedback loop (max 1 rerun)
- Feature flags: `enable_fill_to_target_greedy`, `enable_bad_block_mix_rerun`

#### Phase 3: Repair Upgrades
- `repair_pt_to_fte_swaps()` - Bounded PT→FTE repair with limits
  - PT_LIMIT=20, FTE_LIMIT=30, BLOCK_LIMIT=100
- Deterministic tie-break ordering throughout
- No unbounded loops (max 3 passes, stop on no progress)

#### Tests
- 79+ new tests covering S0.5-S3.4 requirements
- Budget compliance integration tests (micro CP-SAT, overrun detection)
- Canonical signature determinism tests

### Changed
- All feature flags default to OFF for canary rollout
- `_sanity_check()` returns `(ok, errors)` instead of raising ValueError

### Deprecated
- Phase 4 (LP-RMP Column Generation) postponed to v2.1

### Fixed
- 13 CP-SAT locations now use `num_search_workers=1` for determinism
- 9+ dict/set iteration sites now use `sorted()` for stable ordering
- Tightening logic uses guardrailed step instead of hardcoded -5

---

## How to Enable v2.0 Features

All new features are **disabled by default** for safe canary rollout.

```python
from src.services.forecast_solver_v4 import ConfigV4

# Enable v2.0 features
config = ConfigV4()._replace(
    enable_fill_to_target_greedy=True,
    enable_bad_block_mix_rerun=True,
)
```

## Canary Metrics to Monitor

| Metric | Expected Behavior |
|--------|-------------------|
| `pt_ratio` | Should decrease or stay stable |
| `underfull_ratio` | Should decrease with fill-to-target |
| `time_phase1`, `time_phase2`, etc. | Each ≤ allocated slice |
| `reason_codes` | No BUDGET_OVERRUN codes |
| `solution_signature` | Identical on repeated runs (same seed) |

## Dependencies

- OR-Tools: Pin to specific version for determinism (see requirements.txt)
