# Slot State Machine - V4.9.3 HOTFIX

> **Status**: HARDENING PATCH
> **Purpose**: Prevent ghost states in the Activation Gate subsystem

---

## State Diagram

```
                    ┌────────────┐
                    │  PLANNED   │  (forecast-created, no driver)
                    └─────┬──────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               │               ▼
    ┌───────────┐         │         ┌───────────┐
    │   HOLD    │◄────────┘         │ ASSIGNED  │
    │ (surplus) │                   │(has driver)│
    └─────┬─────┘                   └─────┬─────┘
          │                               │
          ▼                               │
    ┌───────────┐                         │
    │ RELEASED  │─────────────────────────┤
    │(reactivate)                         │
    └─────┬─────┘                         │
          │                               │
          ▼                               ▼
    ┌───────────┐                   ┌───────────┐
    │ ASSIGNED  │──────────────────►│ EXECUTED  │
    │(has driver)                   │(completed)│
    └─────┬─────┘                   └───────────┘
          │
          ▼
    ┌───────────┐
    │  ABORTED  │
    │(cancelled)│
    └───────────┘
```

---

## Status Enum Values

| Status | Description | assigned_driver_id | release_at |
|--------|-------------|-------------------|------------|
| `PLANNED` | Forecasted, awaiting processing | NULL | NULL |
| `HOLD` | Temporarily deactivated (surplus capacity) | **MUST BE NULL** | NULL |
| `RELEASED` | Reactivated, awaiting assignment | NULL or NOT NULL | **MUST BE SET** |
| `ASSIGNED` | Driver assigned, ready for execution | **MUST BE SET** | **MUST BE SET** |
| `EXECUTED` | Tour completed | (preserved) | (preserved) |
| `ABORTED` | Tour cancelled | (cleared) | (preserved) |

---

## Invariants (ENFORCED)

### INV-1: HOLD implies NO ASSIGNMENT
```sql
CHECK (status != 'HOLD' OR assigned_driver_id IS NULL)
```
**Rationale**: A slot on HOLD is "parked" - it cannot have an active assignment.

### INV-2: ASSIGNED implies RELEASED
```sql
CHECK (status != 'ASSIGNED' OR release_at IS NOT NULL)
```
**Rationale**: You can only assign a driver to a slot that has been released into the dispatch pool.

### INV-3: RELEASED implies release_at SET
```sql
CHECK (status != 'RELEASED' OR release_at IS NOT NULL)
```
**Rationale**: RELEASED state must track when it was released (for at_risk calculations).

### INV-4: Frozen day blocks all mutations
```sql
TRIGGER trg_enforce_day_not_frozen
```
**Rationale**: Once a day is frozen, no slot mutations are allowed (audit/legal requirement).

### INV-5: Valid transitions only
| From | Allowed To |
|------|-----------|
| PLANNED | HOLD, ASSIGNED |
| HOLD | RELEASED, ABORTED |
| RELEASED | ASSIGNED, HOLD, ABORTED |
| ASSIGNED | EXECUTED, ABORTED |
| EXECUTED | (terminal) |
| ABORTED | (terminal) |

---

## Ghost States (PREVENTED)

| Ghost State | Risk | Prevention |
|------------|------|------------|
| HOLD + driver assigned | Driver thinks they have work, dispatcher thinks it's parked | INV-1 (DB constraint) |
| ASSIGNED + no release_at | Can't calculate at_risk, audit gap | INV-2 (DB constraint) |
| RELEASED + no release_at | Invalid state per invariant | INV-3 (existing constraint) |
| Direct HOLD→ASSIGNED | Skips release tracking | INV-5 (function guard) |

---

## State Transition Functions

### `dispatch.set_slot_hold(slot_id, reason, user_id, note)`
- **Allowed from**: PLANNED, RELEASED
- **NOT allowed from**: ASSIGNED (INV-1 violation), EXECUTED, ABORTED
- **Side effects**: Clears `assigned_driver_id`, `release_at`, `at_risk`

### `dispatch.set_slot_released(slot_id, user_id, threshold_minutes)`
- **Allowed from**: HOLD
- **NOT allowed from**: any other state
- **Side effects**: Sets `release_at`, calculates `at_risk`

### `dispatch.set_slot_assigned(slot_id, driver_id, user_id)` *(NEW)*
- **Allowed from**: PLANNED, RELEASED
- **NOT allowed from**: HOLD, EXECUTED, ABORTED
- **Side effects**: Sets `assigned_driver_id`, ensures `release_at` is set

---

## API Layer Guards

All workbench endpoints must:

1. **Check slot status before mutation** - reject invalid transitions
2. **Use atomic SQL functions** - never UPDATE directly
3. **Return clear error codes** - `INVALID_TRANSITION`, `GHOST_STATE_PREVENTED`
4. **Log all rejections** - audit trail for debugging

---

## Migration Strategy

1. **Add DB constraints** (INV-1, INV-2) with deferred validation
2. **Fix existing ghost states** via migration cleanup
3. **Update SQL functions** to enforce transition rules
4. **Add API guards** as defense-in-depth
5. **Add smoke tests** to verify invariants

---

## Verification Query

```sql
-- Find any ghost states
SELECT slot_id, status, assigned_driver_id, release_at,
    CASE
        WHEN status = 'HOLD' AND assigned_driver_id IS NOT NULL THEN 'GHOST: HOLD+assigned'
        WHEN status = 'ASSIGNED' AND release_at IS NULL THEN 'GHOST: ASSIGNED-no-release'
        WHEN status = 'RELEASED' AND release_at IS NULL THEN 'GHOST: RELEASED-no-release'
        ELSE 'OK'
    END as integrity_check
FROM dispatch.daily_slots
WHERE status IN ('HOLD', 'RELEASED', 'ASSIGNED')
  AND (
      (status = 'HOLD' AND assigned_driver_id IS NOT NULL) OR
      (status = 'ASSIGNED' AND release_at IS NULL) OR
      (status = 'RELEASED' AND release_at IS NULL)
  );
```

---

*Document Version: V4.9.3-HOTFIX*
*Last Updated: 2026-01-15*
