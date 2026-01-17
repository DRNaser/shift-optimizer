# ADR: src_compat Module Status

> **Status**: INTERNAL/DEPRECATED
> **Created**: 2026-01-16 (PR-4)
> **Decision**: src_compat is an INTERNAL compatibility layer, NOT new legacy

## Context

During the V4.5-V4.6 cleanup, the global `backend_py/src/` package was deleted.
However, the V3 solver depended on 6 critical modules from `src/`. These were
copied into `packs/roster/engine/src_compat/` to preserve solver functionality.

## Decision

**src_compat is NOT new legacy code**. It is:
1. An INTERNAL module within the roster engine pack
2. NOT exported or used outside the engine
3. Scheduled for gradual consolidation (not external migration)

## Module Inventory

| Module | LOC | Purpose | Consumers | Removal Plan |
|--------|-----|---------|-----------|--------------|
| `models.py` | ~200 | Tour, Block, Weekday, DriverState | solver_v2_integration, block_heuristic_solver | Consolidate into engine/models.py |
| `constraints.py` | ~50 | HARD_CONSTRAINTS dict | models.py, smart_block_builder | Inline into models.py |
| `block_heuristic_solver.py` | ~400 | MinCostFlow solver | solver_v2_integration | Keep as engine/solver.py |
| `smart_block_builder.py` | ~300 | Block generation | forecast_solver_v4 | Keep for V4 experimental |
| `assignment_constraints.py` | ~100 | can_assign_block() | block_heuristic_solver | Inline into solver.py |
| `forecast_solver_v4.py` | ~5000 | V4 experimental | solver_wrapper (opt-in) | R&D ONLY, not production |

**Total**: ~6050 LOC, all INTERNAL to roster engine

## Import Graph

```
solver_wrapper.py
    └─> solver_v2_integration.py (DEFAULT path)
            └─> src_compat/models.py
            └─> src_compat/block_heuristic_solver.py
                    └─> src_compat/models.py
                    └─> src_compat/constraints.py
    └─> src_compat/forecast_solver_v4.py (V4 opt-in, R&D only)
            └─> src_compat/models.py
            └─> src_compat/smart_block_builder.py
            └─> src_compat/assignment_constraints.py
```

## Why This Is NOT Legacy

1. **Scoped**: All modules are under `packs/roster/engine/` - not global
2. **Internal**: No external consumers - only used within engine
3. **No Re-Export**: `src_compat/__init__.py` exists for internal convenience only
4. **Clear Deprecation**: `forecast_solver_v4.py` has "R&D ONLY" in every docstring
5. **Planned Consolidation**: Will be folded into engine proper, not migrated out

## Consolidation Plan (Post-Pilot)

```
Phase 1: Stabilize (Current)
├─ src_compat modules frozen
├─ determinism_proof tests pass
└─ Production uses V3 solver only

Phase 2: Consolidate (Q2 2026)
├─ Move models.py → engine/models.py
├─ Inline constraints.py into models.py
├─ Rename block_heuristic_solver.py → engine/solver.py
├─ Delete src_compat/ directory
└─ Update imports (3 files)

Phase 3: V4 Decision (Q3 2026)
├─ If V4 adopted: migrate smart_block_builder, assignment_constraints
├─ If V4 rejected: delete forecast_solver_v4.py entirely
└─ Remove all V4 experimental code paths
```

## Evidence: External Import Scan

```bash
# Verify no production consumers
rg "from packs.roster.engine.src_compat" backend_py/ --type py | grep -v "engine/"
# Result: Only skills/determinism_proof/prover.py (internal testing tool)
```

### Note on skills/ imports

`skills/determinism_proof/prover.py` imports src_compat for testing purposes.
This is acceptable because:
1. Skills are INTERNAL testing/validation tools, not production code
2. The import is wrapped in try/except for graceful degradation
3. Skills are not deployed to production environments
4. Will be updated to use engine-level exports post-consolidation

## Conclusion

src_compat is a **temporary internal convenience layer**, not new legacy.
It exists solely to preserve V3 solver functionality after the src/ deletion.
All modules are scoped within the roster engine pack and have clear paths
to consolidation or removal.

**Recommendation**: Keep src_compat as-is for Wien pilot stability.
Consolidate in Q2 2026 after production validation.
