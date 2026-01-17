# ADR-004: Freeze Immutability - No Unfreeze for Pilot

> **Status**: ACCEPTED
> **Date**: 2026-01-15
> **Authors**: Claude Code, Ops Team
> **Scope**: Dispatch Workbench V4.9

---

## Context

The Dispatch Workbench allows dispatchers and operators to manage daily slot assignments. At end-of-day (or configured cutoff), days are "frozen" to capture the final operational state for:

1. Management reporting (no drift in historical data)
2. Compliance evidence (arbeitsrechtlich documentation)
3. KPI dashboards (consistent week-over-week comparisons)

The question: Should there be an "Unfreeze" capability?

---

## Decision

**NO UNFREEZE CAPABILITY FOR PILOT**

Once a day is frozen, it remains frozen permanently. There is no API endpoint, SQL function, or admin tool to unfreeze a day.

### Rationale

1. **Simplicity**: Unfreeze introduces complex edge cases:
   - What happens to evidence bundles?
   - How do we track stats_source (FINAL vs RE-OPENED)?
   - Audit trail becomes non-linear

2. **Data Integrity**: Management reports rely on frozen stats being immutable. "Yesterday had 8 aborts" must not become "Yesterday had 12 aborts" after the fact.

3. **Arbeitsrecht**: Frozen days may be used as evidence for driver acknowledgments and work time records. Reopening creates legal ambiguity.

4. **Operational Reality**: In 99% of cases, "incorrect freeze" is actually "incomplete data entry before freeze". The solution is better pre-freeze validation, not unfreeze.

---

## Consequences

### If Operator Freezes Too Early (Accidental)

1. **Slots not yet marked ABORTED**: Remain in their pre-freeze state. Reports show slightly incorrect abort count.
   - **Mitigation**: Add "validation warnings" before freeze (e.g., "3 slots still PLANNED at 23:00 - proceed?")

2. **Stats are wrong**: The frozen final_stats are the canonical truth.
   - **Mitigation**: Add `audit_note` field to evidence bundle explaining discrepancy.

3. **Compliance concern**: Contact legal/ops team for manual annotation in external system.
   - **NOT**: Unfreeze and re-freeze.

### Future Consideration (Post-Pilot)

If business requirements evolve, consider:

1. **2-Person Gate Unfreeze**: Requires platform_admin + tenant_admin approval
2. **Audit Reason Required**: Must provide compliance-level justification
3. **Evidence Versioning**: Store original and amended evidence bundles
4. **Immutable Log**: `UNFREEZE_EVENT` in audit_log with full before/after snapshot

This is NOT implemented for pilot. Decision can be revisited after pilot feedback.

---

## Alternatives Considered

### Option A: Allow Unfreeze for tenant_admin (REJECTED)
- Too easy to accidentally unfreeze
- Creates management report confusion
- Weakens evidence integrity

### Option B: Allow Unfreeze with 2-Person Gate (DEFERRED)
- Adds complexity for rare edge case
- Can be added post-pilot if needed
- Not worth pilot schedule risk

### Option C: Soft-Delete Freeze (REJECTED)
- Creates "schrodinger's day" (frozen but not frozen)
- Breaks stats_source logic
- Confuses downstream consumers

---

## Implementation Notes

1. No `unfreeze_day()` SQL function exists
2. No `/workbench/daily/unfreeze` endpoint exists
3. `dispatch.workbench_days.status` can only transition: `OPEN → FROZEN`
4. Trigger `trg_block_frozen_slot_changes` enforces immutability at DB level

---

## Related

- Migration: `061_abort_freeze_weekly_sim.sql`
- Permission: `roster.day.freeze` (operator_admin+)
- Endpoint: `POST /api/v1/roster/workbench/daily/freeze`
