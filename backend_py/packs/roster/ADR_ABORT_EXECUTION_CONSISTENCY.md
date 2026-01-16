# ADR-005: Abort vs Execution Consistency Rule

> **Status**: ACCEPTED
> **Date**: 2026-01-15
> **Authors**: Claude Code, Ops Team
> **Scope**: Dispatch Workbench V4.9

---

## Context

Today, slot status transitions are manual/ops-driven:
- `PLANNED → ASSIGNED → EXECUTED` (happy path)
- `PLANNED → ABORTED` (cancelled due to low demand, weather, etc.)

**Future Integration**: mTrack or other telemetry systems may send execution confirmations automatically. This creates a potential conflict:

```
Timeline:
10:00 - Slot is PLANNED (driver assigned)
14:00 - Day is FROZEN (slot still shows PLANNED)
15:00 - mTrack sends: "Driver X completed trip Y" → wants to set EXECUTED
```

**Question**: Should telemetry override frozen state?

---

## Decision

**VARIANTE A: STRICT FROZEN TRUTH**

Once a day is frozen, no status changes are allowed - including from external telemetry.

### Rule

| Source | Day State | Action |
|--------|-----------|--------|
| Manual | OPEN | ✅ Allowed |
| Manual | FROZEN | ❌ Rejected (409 DAY_FROZEN) |
| Telemetry | OPEN | ✅ Allowed |
| Telemetry | FROZEN | ❌ Rejected → logged as "late telemetry anomaly" |

### Rationale

1. **Single Source of Truth**: Frozen stats are THE truth for that day. Allowing post-freeze mutations creates "which number is real?" confusion.

2. **Predictable Management Reports**: If frozen day shows 8 EXECUTED, it stays 8 EXECUTED forever. Management doesn't see reports changing retroactively.

3. **Simpler Implementation**: No need for versioned stats, before/after reconciliation, or "telemetry override" flags.

4. **Audit Integrity**: Evidence bundles captured at freeze time remain valid. No need to re-sign or amend evidence.

5. **Late Telemetry is Rare**: Proper freeze timing (e.g., 06:00 next day) should capture 99%+ of execution data.

---

## Alternative Considered (REJECTED for Pilot)

### Variante B: Telemetry Override Before Freeze

Allow `ABORTED → EXECUTED` transition from telemetry, but only if day is still OPEN.

```python
# Variante B (NOT implemented)
if day_status == "OPEN" and source == "TELEMETRY":
    if current_status == "ABORTED" and new_status == "EXECUTED":
        # Allowed: telemetry proves it actually ran
        apply_transition()
```

**Why Rejected**:
- Adds state machine complexity
- Need to track `last_modified_source` (manual vs telemetry)
- Creates "who wins?" disputes in reports
- Not needed for pilot scope

---

## Implementation

### Current Behavior (Correct)

1. All mutations check `check_day_frozen()` before applying
2. If frozen: return 409 DAY_FROZEN
3. No special handling for telemetry source

### Future Telemetry Integration

When mTrack integration is added:

```python
async def process_mtrack_execution(event: MTrackEvent):
    is_frozen = await check_day_frozen(conn, tenant_id, site_id, event.date)

    if is_frozen:
        # Log anomaly but DO NOT modify slot
        logger.warning(
            "late_telemetry_anomaly",
            extra={
                "slot_id": event.slot_id,
                "event_type": "EXECUTION",
                "day_date": event.date,
                "reason": "DAY_ALREADY_FROZEN",
            }
        )
        # Store in anomaly table for ops review
        await store_late_telemetry_anomaly(conn, event)
        return  # No state change

    # Day is OPEN - apply execution
    await set_slot_status(...)
```

### Late Telemetry Anomaly Handling

If late telemetry arrives for frozen day:

1. **Log as Warning**: `late_telemetry_anomaly` event
2. **Store for Review**: `dispatch.late_telemetry_anomalies` table (future)
3. **Ops Dashboard Alert**: "3 late execution reports for frozen days this week"
4. **Resolution**: Ops decides if freeze timing needs adjustment

---

## Consequences

### Acceptable Trade-offs

1. **Occasional "PLANNED" in Reports**: A slot that was actually executed but reported late shows as PLANNED in frozen reports.
   - **Frequency**: Rare if freeze timing is correct
   - **Mitigation**: Adjust freeze time to wait for telemetry lag

2. **Anomaly Log Growth**: Late telemetry creates log entries.
   - **Mitigation**: Aggregate anomalies, alert on threshold

### Unacceptable Outcomes (Prevented)

1. **Changing Frozen Stats**: NEVER happens
2. **Report Drift**: NEVER happens
3. **Evidence Invalidation**: NEVER happens

---

## Related

- ADR-004: Freeze Immutability (No Unfreeze)
- Migration: `061_abort_freeze_weekly_sim.sql`
- Function: `dispatch.check_day_frozen()`
- Trigger: `trg_block_frozen_slot_changes`
