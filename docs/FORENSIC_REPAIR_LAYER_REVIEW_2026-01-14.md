# Forensic Review: Smart Repair / Dispatch Repair Layer v1

**Date**: 2026-01-14
**Reviewer**: Claude Code Agent
**Scope**: backend_py/packs/roster/core/candidate_finder.py, repair_orchestrator.py + API routers + BFF

---

## Executive Summary

The Smart Repair (Orchestrated Repair) implementation is **functional but has two CRITICAL gaps** that must be addressed before production use:

1. **Proposal violation claims are not validated** - Proposals claim `block_violations=0` without actually checking
2. **Coverage definition mismatch** - Smart Repair checks "impacted tour coverage" not canonical "all tours coverage"

The orchestrated endpoints are properly wired, have idempotency, and integrate with the existing plan lifecycle (DRAFT -> AUDITED -> PUBLISHED flow).

---

## Activation Map

### Backend Wiring

| Component | File | Lines | Registration |
|-----------|------|-------|--------------|
| repair_orchestrator router | `packs/roster/api/routers/repair_orchestrator.py` | 1-1029 | Registered in `__init__.py:155-156` |
| repair_orchestrator core | `packs/roster/core/repair_orchestrator.py` | 1-720 | Imported by router |
| candidate_finder core | `packs/roster/core/candidate_finder.py` | 1-570 | Imported by orchestrator |

**Endpoints exposed:**
- `POST /api/v1/roster/repairs/orchestrated/preview`
- `POST /api/v1/roster/repairs/orchestrated/prepare`
- `POST /api/v1/roster/repairs/orchestrated/confirm`
- `GET /api/v1/roster/repairs/candidates/{plan}/{driver}`

### Frontend BFF Wiring

| Route | File | Backend Target |
|-------|------|----------------|
| `POST /api/roster/repairs/orchestrated/preview` | `frontend_v5/app/api/roster/repairs/orchestrated/preview/route.ts` | simpleProxy to backend |
| `POST /api/roster/repairs/orchestrated/prepare` | `frontend_v5/app/api/roster/repairs/orchestrated/prepare/route.ts` | proxyToBackend with idempotency |
| `POST /api/roster/repairs/orchestrated/confirm` | `frontend_v5/app/api/roster/repairs/orchestrated/confirm/route.ts` | proxyToBackend with idempotency |

---

## Forensic Findings

### A) Coverage Definition

**Status: RISK - Needs Fix**

| Aspect | Finding |
|--------|---------|
| Location | `repair_orchestrator.py:189, 274, 354` |
| Issue | Proposals set `coverage_percent=100.0` as a constant, based on "all impacted_tours are assigned" |
| Canonical Logic | Publish Gate checks `tour_instances WHERE assigned_driver_id IS NULL` (lifecycle.py:726-758) |
| Gap | A proposal could have 100% "impacted tour coverage" while other tours remain UNASSIGNED |

**Evidence:**
```python
# repair_orchestrator.py:189 - No validation, just constant
return RepairProposal(
    ...
    coverage_percent=100.0,  # <- Assumed, not calculated
    block_violations=0,      # <- Assumed, not validated
    ...
)
```

**Recommendation:** After building a proposal, compute actual coverage against all tour_instances in the plan, not just impacted ones. The canonical query is:
```sql
SELECT COUNT(*) FROM tour_instances ti
LEFT JOIN assignments a ON ti.id = a.tour_instance_id AND a.plan_version_id = $1
WHERE ti.plan_version_id = $1 AND a.id IS NULL
```

---

### B) Canonical Violations Engine

**Status: RISK - Needs Fix**

| Aspect | Finding |
|--------|---------|
| Confirm uses canonical | YES - `repair_orchestrator.py:751` imports and calls `compute_violations_sync` |
| Preview/Proposal uses canonical | NO - Proposals **assume** `block_violations=0` without validation |
| Gap | A proposal could claim 0 violations but actually create violations (especially OVERLAP) |

**Evidence:**
```python
# repair_orchestrator.py:185-192 - No actual violation check
return RepairProposal(
    ...
    feasible=True,              # <- Based on candidates found, not violations checked
    coverage_percent=100.0,     # <- Constant
    block_violations=0,         # <- CLAIMED WITHOUT VALIDATION
    warn_violations=0,
    ...
)
```

**Recommendation:** After generating a proposal's assignments, simulate the violations by:
1. Take current assignments for plan
2. Remove assignments for impacted_tours
3. Add proposed assignments
4. Run canonical violation check on simulated state
5. Only return proposal if block_count == 0

---

### C) Lifecycle Integration

**Status: PASS with Minor Concern**

| Aspect | Finding |
|--------|---------|
| prepare creates | `plan_version` with `status='DRAFT'`, `plan_state='DRAFT'` |
| confirm transitions to | `status='AUDITED'`, `plan_state='AUDITED'` |
| Compatible with publish | YES - AUDITED plans can be published via existing flow |
| Records approvals | YES - `plan_approvals` table entries for REPAIR_PREPARE, REPAIR_CONFIRM |

**Minor Concern:** The orchestrated repair creates a NEW plan_version (child of original). This is different from `repair_sessions` which modifies the existing plan in-place. Both systems coexist but don't interact.

**Recommendation:** Document that orchestrated repair is "fork + apply" model, not "in-place edit" model. This is actually cleaner for audit trails.

---

### D) Idempotency & Race-Safety

**Status: PASS**

| Aspect | Finding |
|--------|---------|
| prepare idempotency | Required header, checked in `core.idempotency_keys` with 24h TTL |
| confirm idempotency | Required header, checked in `core.idempotency_keys` with 24h TTL |
| Status guard | confirm checks `WHERE status='DRAFT'` before updating |
| Replay safe | Returns cached response on replay |

**Evidence:**
```python
# repair_orchestrator.py:527-540
cur.execute(
    """SELECT response_body FROM core.idempotency_keys
       WHERE idempotency_key = %s AND tenant_id = %s
       AND created_at > NOW() - INTERVAL '24 hours'""",
    (idempotency_key, ctx.tenant_id)
)
cached = cur.fetchone()
if cached:
    return PrepareResponse(**json.loads(cached[0]))
```

---

### E) Change Budget Defaults

**Status: PASS**

| Parameter | Default | Assessment |
|-----------|---------|------------|
| max_changed_tours | 5 | Conservative for 1-2 tour incidents |
| max_changed_drivers | 3 | Conservative |
| max_chain_depth | 2 | Conservative |
| allow_split | True | Correct for flexibility |
| max_splits | 2 | Conservative |

**Evidence:** `ChangeBudget` class in `repair_orchestrator.py:67-72` has sensible defaults.

---

### F) Candidate Finder Hardconstraints

**Status: PARTIAL PASS**

| Constraint | Checked | Location |
|------------|---------|----------|
| Time Overlap | YES | `candidate_finder.py:73-105` |
| Rest Rules (11h) | YES | `candidate_finder.py:108-143` |
| max_tours_per_day (3) | YES | `candidate_finder.py:146-162` |
| Weekly hours cap (55h) | YES (soft) | `candidate_finder.py:346-347` |
| Skills/Vehicle | **NO** | Not implemented |
| SPAN_REGULAR (14h) | **NO** | Not implemented |
| SPAN_SPLIT (16h) | **NO** | Not implemented |

**Risk Assessment:** Missing Skills/Vehicle constraints could propose assignments that the solver would reject. Missing SPAN checks could create WARN violations.

**Recommendation:**
- Skills/Vehicle: If the roster pack has these as hard constraints, add them to candidate_finder
- SPAN checks: These are WARN-level, less critical but should be added for completeness

---

### G) Cross-tenant/RLS + Access Control

**Status: PASS**

| Aspect | Finding |
|--------|---------|
| TenantContext enforcement | All endpoints use `require_tenant_context_with_permission` |
| Plan ownership validation | Explicit check `WHERE id = %s AND tenant_id = %s` |
| Idempotency key scoping | Keys are tenant-scoped |
| CSRF protection | prepare/confirm have `require_csrf_check` dependency |

**Evidence:**
```python
# repair_orchestrator.py:315
ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read"))

# repair_orchestrator.py:369-383
cur.execute(
    """SELECT id, tenant_id, site_id FROM plan_versions
       WHERE id = %s AND tenant_id = %s""",
    (plan_version_id, ctx.tenant_id)
)
```

---

### H) UI/UX Gate Consistency

**Status: NOT VERIFIED (Frontend)**

The backend provides:
- `coverage_percent` (but currently always 100.0)
- `block_violations` (but currently always 0)
- `delta_summary` with changed_tours_count, changed_drivers_count

UI should display these values faithfully. Since backend values are currently constants, UI would show "green" even if actual state differs.

---

## Missing Tests

### Tests That Exist

| Test File | Coverage |
|-----------|----------|
| `test_candidate_finder.py` | Unit tests for constraint checkers, scoring |
| `test_repair_orchestrator.py` | Unit tests for proposal generation, invariants |

### Tests That Should Be Added

1. **Violation Validation Test**
   - Create proposal that would cause OVERLAP
   - Assert proposal is rejected or marked infeasible

2. **Canonical Coverage Consistency Test**
   - Create plan with some unassigned tours
   - Generate repair proposal
   - Assert coverage_percent reflects ALL tours, not just impacted

3. **Confirm Idempotency Integration Test**
   - Call confirm twice with same idempotency key
   - Assert only one plan_approval record created

4. **Cross-tenant Isolation Test**
   - Tenant A generates proposal for Tenant B's plan
   - Assert 404 (not 403 - no information leak)

5. **Baseline Regression Test**
   - Run V3 solver
   - Run Smart Repair preview
   - Assert V3 output unchanged

---

## Required Fixes

### Fix 1: Validate Violations After Proposal Generation (CRITICAL)

**File:** `backend_py/packs/roster/core/repair_orchestrator.py`

**Change:** After building proposal assignments, validate using canonical violations engine.

```python
# In _generate_no_split_proposal and _generate_split_proposal:
# After building assignments list, add:

def _validate_proposal_violations(
    cursor,
    plan_version_id: int,
    proposed_assignments: List[ProposedAssignment],
    removed_tour_ids: List[int],
) -> Tuple[int, int]:
    """
    Simulate violations for proposal without writing to DB.
    Returns (block_count, warn_count).
    """
    # This requires either:
    # 1. In-memory simulation
    # 2. Temp table approach
    # 3. Use existing violation logic with modified assignment set
    pass
```

**Minimal Fix Approach:** For MVP, validate violations in `confirm` only (which is already done) and clearly document that `preview` block_violations is a "best effort estimate."

### Fix 2: Coverage Should Check All Tours (MEDIUM)

**File:** `backend_py/packs/roster/core/repair_orchestrator.py`

**Change:** After generating proposals, verify no other UNASSIGNED violations exist.

### Fix 3: Add Missing Constraint Tests (LOW)

Add tests for:
- Skills/Vehicle (if applicable in roster pack)
- SPAN violations

---

## Verification Commands

```bash
# Run repair layer tests (ALL PASSED - 21 tests)
cd backend_py && python -m pytest packs/roster/tests/test_candidate_finder.py -v
cd backend_py && python -m pytest packs/roster/tests/test_repair_orchestrator.py -v

# Run V3 baseline regression (ensure unchanged)
cd backend_py && python -m pytest tests/test_v3_solver_regression.py -v

# Check router registration
cd backend_py && python -c "from packs.roster.api.routers import router; print('OK')"

# Frontend TypeScript check (PASSED)
cd frontend_v5 && npx tsc --noEmit
```

## Verification Results (2026-01-14)

| Test Suite | Result | Count |
|------------|--------|-------|
| test_candidate_finder.py | PASSED | 18/18 |
| test_repair_orchestrator.py | PASSED | 21/21 |
| Frontend TypeScript | PASSED | - |

All new tests added in this review are passing:
- `TestCanonicalViolationsIntegration`: 3 tests verifying confirm uses canonical violations
- `TestCrossTenantIsolation`: 3 tests verifying tenant isolation

---

## Conclusion

The Smart Repair implementation is **architecturally sound** with proper:
- Lifecycle integration (DRAFT -> AUDITED)
- Idempotency patterns
- Tenant isolation
- Conservative defaults

However, **two critical gaps** exist:
1. Proposals claim `block_violations=0` without validation
2. Coverage definition differs from canonical publish gate

**Recommendation:**
- For immediate pilot: Document that `preview` is advisory, `confirm` is authoritative (which validates canonically)
- For production: Implement proposal violation simulation

**Risk Level:** MEDIUM - The confirm step validates canonically, so no invalid plan can be published. But UI may show misleading "all green" during preview.

---

*Report generated by forensic review process. All findings backed by file:line references.*
