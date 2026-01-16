# Dispatch Workbench Smoke Test Runbook

> **Version**: V4.9.3-HOTFIX - Slot State Machine Invariants
> **Last Updated**: 2026-01-15

---

## Prerequisites

### Option A: Canonical Migration Runner (Recommended for Production)

```powershell
# Run all pending migrations via canonical runner
.\scripts\run-migrations.ps1

# Or with explicit connection string
.\scripts\run-migrations.ps1 -ConnectionString $env:DATABASE_URL
```

The canonical runner:
- Tracks applied migrations in `schema_migrations` table
- Applies migrations in lexicographic order (025, 025a, 026, ...)
- Is idempotent (re-running skips already-applied migrations)
- Logs all operations with timestamps

### Option B: Direct psql (Development/Debugging Only)

```bash
# Apply migrations manually (in order!)
psql $DATABASE_URL < backend_py/db/migrations/061_abort_freeze_weekly_sim.sql
psql $DATABASE_URL < backend_py/db/migrations/062_roster_rbac_permissions.sql
```

⚠️ **Warning**: Direct psql bypasses the migration tracker. Use only for debugging.

### Verify Migration State

```bash
# Check schema_migrations ordering
psql $DATABASE_URL -c "SELECT version, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 10;"
# Expected: 062 and 061 should be present

# Verify dispatch migration
psql $DATABASE_URL -c "SELECT * FROM dispatch.verify_abort_freeze_integrity();"
# Expected: 12 checks, all PASS

# Verify RBAC permissions
psql $DATABASE_URL -c "SELECT * FROM auth.verify_roster_permissions();"
# Expected: 8 checks, all PASS
```

### Rollback Guidance

**IMPORTANT**: Migrations are designed to be forward-only. Rollback is NOT recommended.

If a migration fails mid-execution:

1. **DO NOT** re-run the migration immediately
2. Check partial state: `SELECT * FROM schema_migrations WHERE version = '061';`
3. If version exists but tables missing, investigate specific failure
4. Contact platform team for rollback assistance

For **critical production rollback** (requires platform_admin):

```sql
-- DANGER: Only use if explicitly approved by platform team
-- This does NOT undo schema changes, only resets tracker
DELETE FROM schema_migrations WHERE version = '062';
-- Manual cleanup of added objects required
```

Rollback of dispatch schema changes requires manual intervention:
- `dispatch.simulation_runs` - DROP if created
- `dispatch.daily_slots.abort_*` columns - ALTER TABLE to remove
- Functions: DROP FUNCTION dispatch.freeze_day, etc.

**Best Practice**: Fix forward, don't roll back. Create a new migration (063) that corrects issues.

---

## Smoke Test Sequence

### Test 1: Day Lifecycle (OPEN → Abort → Freeze)

**Goal**: Verify abort works on OPEN day, freeze captures stats, frozen day blocks mutations.

```bash
# Step 1.1: Create test day (via API or seed)
# Pick a past date (e.g., yesterday) that is OPEN

# Step 1.2: Abort 2 slots with different reasons
POST /api/v1/roster/workbench/slots/{slot_id_1}/abort
Body: {"reason": "LOW_DEMAND", "note": "Test abort 1"}

POST /api/v1/roster/workbench/slots/{slot_id_2}/abort
Body: {"reason": "WEATHER", "note": "Test abort 2"}

# Expected: Both return success=true, new_status="ABORTED"

# Step 1.3: Check daily summary (aborts visible)
GET /api/v1/roster/management/daily-summary?site_id={site_id}&date_str={date}

# Expected:
# - stats.aborted = 2
# - abort_breakdown.LOW_DEMAND = 1
# - abort_breakdown.WEATHER = 1
# - is_frozen = false
# - is_live = true
```

### Test 2: Freeze Day

```bash
# Step 2.1: Freeze the day
POST /api/v1/roster/workbench/daily/freeze
Body: {"date": "YYYY-MM-DD", "site_id": {site_id}}

# Expected:
# - success = true
# - was_already_frozen = false
# - final_stats contains current counts
# - evidence_id is present

# Step 2.2: Verify idempotency (freeze again)
POST /api/v1/roster/workbench/daily/freeze
Body: {"date": "YYYY-MM-DD", "site_id": {site_id}}

# Expected:
# - success = true
# - was_already_frozen = true
# - Same final_stats as before (no drift)
```

### Test 3: Frozen Day Blocks Mutations

```bash
# Step 3.1: Try to abort a slot on frozen day
POST /api/v1/roster/workbench/slots/{slot_id_on_frozen_day}/abort
Body: {"reason": "OPS_DECISION"}

# Expected: 409 Conflict
# Response: {"error_code": "DAY_FROZEN", "message": "..."}

# Step 3.2: Try to assign driver (if using workbench)
# Expected: 409 DAY_FROZEN

# Step 3.3: Try to move assignment
# Expected: 409 DAY_FROZEN
```

### Test 4: Weekly Summary (Mixed Frozen/Live Days)

```bash
# Ensure: Mon-Wed frozen, Thu-Sun open (typical scenario)

# Step 4.1: Get weekly summary
GET /api/v1/roster/management/weekly-summary?site_id={site_id}&week_start={monday_date}

# Expected:
# - daily array has 7 entries
# - frozen_days = 3 (Mon-Wed)
# - totals aggregate all days
# - abort_by_reason aggregates correctly
# - Frozen days show stored final_stats (is_live=false, stats_source="FINAL")
# - Open days show computed stats (is_live=true, stats_source="LIVE")
# - computed_at timestamp present

# CRITICAL CHECK: Frozen day stats must NOT change between requests
# Run query twice, compare frozen day stats - must be identical

# Step 4.2: Verify stats_source field
# For each day in daily array:
# - If is_frozen=true: stats_source must be "FINAL"
# - If is_frozen=false: stats_source must be "LIVE"
```

### Test 4b: Weekly Summary Input Validation

```bash
# Step 4b.1: Try with non-Monday date
GET /api/v1/roster/management/weekly-summary?site_id={site_id}&week_start=2026-01-14
# (2026-01-14 is a Wednesday)

# Expected: 400 Bad Request
# Response: {"detail": "week_start must be a Monday. Got Wednesday"}

# Step 4b.2: Try with Monday date (should work)
GET /api/v1/roster/management/weekly-summary?site_id={site_id}&week_start=2026-01-12
# (2026-01-12 is a Monday)

# Expected: 200 OK with valid weekly summary
```

### Test 5: Simulation Zero Side-Effects

```bash
# Step 5.1: Record operational table counts BEFORE
psql $DATABASE_URL -c "SELECT COUNT(*) FROM dispatch.daily_slots WHERE tenant_id=1;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM dispatch.workbench_days WHERE tenant_id=1;"
psql $DATABASE_URL -c "SELECT MAX(updated_at) FROM dispatch.daily_slots WHERE tenant_id=1;"

# Step 5.2: Run simulation (driver absence)
POST /api/v1/roster/orchestrator/simulate
Body: {
  "site_id": {site_id},
  "week_start": "{monday_date}",
  "scenarios": [{
    "scenario_type": "DRIVER_ABSENCE",
    "remove_driver_ids": [101, 102, 103]
  }]
}

# Expected:
# - status = "DONE"
# - kpi_deltas present
# - risk_tier present (LOW/MEDIUM/HIGH/CRITICAL)
# - run_id returned

# Step 5.3: Verify counts AFTER (must be identical)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM dispatch.daily_slots WHERE tenant_id=1;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM dispatch.workbench_days WHERE tenant_id=1;"
psql $DATABASE_URL -c "SELECT MAX(updated_at) FROM dispatch.daily_slots WHERE tenant_id=1;"

# CRITICAL: All three values must be EXACTLY the same as before
# If any differ: SIMULATION LEAKED SIDE-EFFECTS - CRITICAL BUG

# Step 5.4: Fetch simulation result
GET /api/v1/roster/orchestrator/simulate/{run_id}

# Expected: Full output_summary with KPI deltas
```

### Test 6: Abort vs Coverage Gap Distinction

```bash
# Ensure there is:
# - At least 1 PLANNED slot without driver (coverage gap)
# - At least 1 ABORTED slot

GET /api/v1/roster/management/daily-summary?site_id={site_id}&date_str={date}

# Expected:
# - stats.coverage_gaps = count of PLANNED without driver
# - stats.aborted = count of ABORTED
# - These are SEPARATE counts (not overlapping)
# - Aborted slots do NOT count as coverage gaps
```

### Test 7: Batch Abort Idempotency

```bash
# Step 7.1: Batch abort (same slots, same reasons)
POST /api/v1/roster/workbench/slots/abort
Body: {
  "operations": [
    {"slot_id": "{uuid1}", "reason": "LOW_DEMAND"},
    {"slot_id": "{uuid2}", "reason": "LOW_DEMAND"}
  ]
}

# Step 7.2: Repeat exact same request
POST /api/v1/roster/workbench/slots/abort
Body: {
  "operations": [
    {"slot_id": "{uuid1}", "reason": "LOW_DEMAND"},
    {"slot_id": "{uuid2}", "reason": "LOW_DEMAND"}
  ]
}

# Expected: Both requests succeed, second is idempotent
# No duplicate audit entries, no errors

# Step 7.3: Repeat with reversed order
POST /api/v1/roster/workbench/slots/abort
Body: {
  "operations": [
    {"slot_id": "{uuid2}", "reason": "LOW_DEMAND"},
    {"slot_id": "{uuid1}", "reason": "LOW_DEMAND"}
  ]
}

# Expected: Same result (operations sorted internally)
```

---

## RLS Verification

```bash
# Step R1: Query as tenant 1
SET app.current_tenant_id = '1';
SELECT COUNT(*) FROM dispatch.daily_slots;
SELECT COUNT(*) FROM dispatch.workbench_days;
SELECT COUNT(*) FROM dispatch.simulation_runs;

# Step R2: Query as tenant 2 (should see different data)
SET app.current_tenant_id = '2';
SELECT COUNT(*) FROM dispatch.daily_slots;
# Expected: Different counts (tenant isolation)

# Step R3: Without tenant context (should fail or return 0)
RESET app.current_tenant_id;
SELECT COUNT(*) FROM dispatch.daily_slots;
# Expected: 0 rows or error (RLS blocks access)
```

---

## Trigger Safety Verification

```bash
# Try to UPDATE a slot on a frozen day directly in SQL
SET app.current_tenant_id = '1';

UPDATE dispatch.daily_slots
SET status = 'ASSIGNED'
WHERE day_date = '{frozen_date}' AND tenant_id = 1
LIMIT 1;

# Expected: ERROR with message containing "DAY_FROZEN"
# Error code: 23000
```

---

## Timezone Handling

**IMPORTANT**: All date parameters use DATE type (timezone-agnostic).

- `week_start` must be a Monday in the target timezone (Europe/Vienna for LTS)
- Dates should be converted to local date before passing to API
- The system does NOT auto-convert UTC timestamps to local dates

Example (Vienna timezone):
```javascript
// Frontend: Convert to Europe/Vienna before calling API
const viennaDate = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Vienna' });
// Use viennaDate as date_str parameter
```

---

## Test 8: Batch Candidates (Week Lookahead)

**Goal**: Verify batch candidates endpoint returns ranked candidates with churn analysis.

```bash
# Step 8.1: Get candidates for open slots
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15

# Expected:
# - success=true
# - week_window.start is Monday of the week
# - week_window.end is Sunday of the week
# - frozen_days is a list (may be empty)
# - slots array contains open/unassigned slots
# - Each slot has candidates array

# Step 8.2: Verify candidate ranking
# For each slot, candidates should be ordered:
# 1. feasible_today=true first
# 2. lookahead_ok=true first
# 3. churn_locked_count=0 first
# 4. churn_count ascending
# 5. score ascending

# Step 8.3: Verify frozen day blocking
# First freeze a day in the week:
POST /api/v1/roster/workbench/daily/freeze
Body: {"date": "2026-01-14", "site_id": {site_id}}

# Then get candidates again:
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15

# Expected:
# - frozen_days array includes "2026-01-14"
# - Candidates with churn on frozen day have churn_locked_count > 0
# - Those candidates have lookahead_ok=false

# Step 8.4: Verify churn explanation
# Each candidate should have:
# - explanation: human-readable summary
# - affected_slots: list of downstream impacts
# - churn_count: number of affected slots
```

### Test 8b: Multiday Repair Flag

```bash
# Step 8b.1: Get candidates without multiday repair
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=false

# Candidates with any churn should have lookahead_ok=false

# Step 8b.2: Get candidates with multiday repair allowed
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=true

# Candidates with churn on non-frozen days should have:
# - lookahead_ok=true (pinned days allowed)
# - churn_locked_count=0 (only frozen days locked)
# - churn_count > 0 (shows future repairs needed)
```

### Test 8c: Deterministic Ranking

```bash
# Step 8c.1: Call candidates endpoint twice
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15
# Save response as result1

GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15
# Save response as result2

# Step 8c.2: Compare rankings
# For each slot, candidate order should be IDENTICAL:
# - Same driver_id sequence
# - Same rank values
# - Same scores

# CRITICAL: Ranking must be deterministic (no randomness)
# Ranking key: (feasible_today DESC, lookahead_ok DESC, churn_locked ASC, churn_count ASC, score ASC, driver_id ASC)
```

### Test 8d: Safe Defaults - Chain Reaction Protection (V4.9.2)

**Goal**: Verify UI defaults protect dispatchers from accidental chain reactions.

```bash
# Step 8d.1: Get candidates with DEFAULT settings (no flags)
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15

# Expected:
# - Response includes candidates
# - Frontend filter should DEFAULT to showing only churn=0 candidates
# - UI toggle "Show all candidates" defaults to OFF

# Step 8d.2: Verify lookahead_range in response
# Response should include:
# - lookahead_range.start = TODAY (the date_str)
# - lookahead_range.end = Sunday of that week
# CRITICAL: lookahead_start must NOT be Monday (week_start) but TODAY

# Step 8d.3: Verify churn semantics
# For each candidate, check:
# - churn_count = count of AFFECTED SLOTS (downstream repairs needed)
# - churn_count does NOT include violations like overtime
# - overtime_risk is a SEPARATE field (NONE/LOW/MED/HIGH)
# - overtime_risk is NOT counted in churn_count
```

### Test 8e: Multiday Mode Warning Banner (V4.9.2)

**Goal**: Verify UI displays warning when multiday repair is enabled.

```bash
# Step 8e.1: Enable multiday repair mode
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=true

# Expected API response:
# - Candidates with churn_count > 0 now have lookahead_ok=true (if no frozen day impact)
# - affected_slots shows specific dates and slot_ids that will be modified

# Step 8e.2: Frontend verification (manual)
# When multiday toggle is ON:
# - Warning banner displayed: "Multiday repair enabled - X future slots may be modified"
# - affected_slots breakdown visible in candidate details
# - Total affected days count shown
```

### Test 8f: Debug Metrics (V4.9.2)

**Goal**: Verify debug metrics are available for performance monitoring.

```bash
# Step 8f.1: Request with debug metrics
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&include_debug_metrics=true

# Expected:
# - debug_metrics object present in response
# - debug_metrics.db_query_count > 0
# - debug_metrics.drivers_considered >= 0
# - debug_metrics.slots_evaluated >= 0
# - debug_metrics.elapsed_ms > 0
# - debug_metrics.lookahead_start = date_str (TODAY)
# - debug_metrics.lookahead_end = Sunday of week

# Step 8f.2: Verify no N+1 queries
# For a day with 10 open slots and 50 eligible drivers:
# - db_query_count should be O(1), NOT O(slots * drivers)
# - Typically: 2-4 queries total (slots, drivers, assignments, frozen_days)
```

### Test 8g: Churn vs Risk Separation (V4.9.2)

**Goal**: Verify churn_count only counts slot changes, not violations.

```bash
# Step 8g.1: Find a candidate approaching weekly hours limit
# Manually identify a driver with 50+ hours this week

# Step 8g.2: Get candidates for a slot
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15

# Find the driver in the candidates list
# Expected:
# - If driver would exceed 55h/week: overtime_risk_level = "HIGH"
# - churn_count should NOT increase due to overtime
# - Overtime is a RISK, not churn (no downstream slot repairs)

# Step 8g.3: Find a candidate with actual churn
# Manually identify a driver who would need rest violation repair

# Expected:
# - churn_count > 0 (slot needs to be reassigned)
# - affected_slots contains the specific slot details
# - reason is "REST_VIOLATION" or "REST_NEXTDAY_FIRST_SLOT"
```

---

## Pass Criteria

| Check | Expected | Pass? |
|-------|----------|-------|
| schema_migrations tracking | 061, 062 versions present | ☐ |
| Migration verification | 12/12 PASS (verify_abort_freeze_integrity) | ☐ |
| RBAC permissions | 8/8 PASS (auth.verify_roster_permissions) | ☐ |
| Abort on OPEN day | success=true | ☐ |
| Freeze captures stats | final_stats present | ☐ |
| Frozen day blocks abort | 409 DAY_FROZEN | ☐ |
| Weekly summary 7 days | daily.length = 7 | ☐ |
| Frozen stats no drift | identical on re-query | ☐ |
| stats_source field | "FINAL" for frozen, "LIVE" for open | ☐ |
| Simulation no side-effects | fingerprint identical (count + hash) | ☐ |
| RLS tenant isolation | different counts per tenant | ☐ |
| Trigger blocks frozen update | SQL error 23000 | ☐ |
| Batch abort idempotent | no errors on repeat | ☐ |
| week_start validation | 400 if not Monday | ☐ |
| **Candidates week_window** | **Mon-Sun boundaries correct** | ☐ |
| **Candidates frozen_days** | **List contains frozen dates** | ☐ |
| **Candidates ranking** | **Lexicographic: feasible > lookahead > churn** | ☐ |
| **Candidates deterministic** | **Same order on re-query** | ☐ |
| **Churn on frozen = locked** | **churn_locked_count > 0** | ☐ |
| **V4.9.2: Lookahead starts TODAY** | **lookahead_range.start = date_str (NOT week_start)** | ☐ |
| **V4.9.2: Churn ≠ Overtime** | **overtime_risk separate from churn_count** | ☐ |
| **V4.9.2: driver_id tiebreaker** | **Same rank, same score → sorted by driver_id** | ☐ |
| **V4.9.2: Debug metrics available** | **include_debug_metrics returns timing** | ☐ |
| **V4.9.2: Frontend churn=0 default** | **UI shows only zero-churn by default** | ☐ |
| **V4.9.2: Multiday warning** | **Banner warns when multiday enabled** | ☐ |

---

## Troubleshooting

### Simulation shows SIDE_EFFECT_VIOLATION

Check logs for:
```
SIMULATION SIDE-EFFECT DETECTED run_id=...
```

This means simulation code accidentally modified operational tables.
Review all UPDATE/INSERT statements in `simulation_engine.py`.

### Freeze returns 500

Check if `dispatch.freeze_day()` SQL function exists:
```sql
SELECT * FROM pg_proc WHERE proname = 'freeze_day';
```

### RLS returns all rows

Check if `app.current_tenant_id` is set:
```sql
SELECT current_setting('app.current_tenant_id', true);
```

If NULL, RLS policies may be using permissive fallback.

### Candidates show churn for past days (V4.9.2)

If churn includes past days in the week:
```bash
# Verify lookahead_range in response
GET /api/v1/roster/workbench/daily/candidates?site_id=1&date_str=2026-01-15

# Response.lookahead_range.start must equal date_str
# NOT Monday of week
```

If lookahead_range.start is Monday instead of TODAY:
- Check `week_lookahead/window.py` for `get_lookahead_range()`
- Should return `(day_date, week_window.week_end)`

### Overtime counted as churn (V4.9.2)

If candidates show churn_count > 0 only due to overtime:
```bash
# Check candidate fields
# - overtime_risk should be "HIGH"
# - churn_count should be 0 if no slot repairs needed
# - affected_slots should be empty (overtime doesn't displace slots)
```

Fix: Ensure `compute_minimal_churn()` only counts slot displacements, not hours cap violations.

### Non-deterministic ranking (V4.9.2)

If same request returns different candidate order:
```bash
# Verify driver_id tiebreaker
# Ranking key should be:
# (feasible_today DESC, lookahead_ok DESC, churn_locked ASC, churn_count ASC, score ASC, driver_id ASC)
```

Check `week_lookahead/scoring.py` for `make_ranking_key()` - must include `driver_id` as final element.

### Debug metrics missing (V4.9.2)

If `debug_metrics` not in response:
```bash
# Must explicitly request debug metrics AND have env flag enabled
GET /api/v1/roster/workbench/daily/candidates?...&include_debug_metrics=true

# Debug metrics are gated by env flag (OFF by default in production)
# Set ROSTER_CANDIDATES_DEBUG_METRICS=1 to enable
```

Default is `include_debug_metrics=false` AND env flag must be `1`.

### Weekly hours blocking candidate (V4.9.2)

If candidates are being blocked (feasible_today=false) due to weekly hours:
```bash
# Check ROSTER_WEEKLY_HOURS_POLICY env var
# Default: HARD_CAP (candidates exceeding cap are infeasible)
# Alternative: SOFT_RISK (overtime is risk metric only, never blocks)

# Check ROSTER_WEEKLY_HOURS_CAP env var
# Default: 55.0 (Austrian transport sector limit)
```

---

## Real Operational Smoke Scenarios (V4.9.2)

### Scenario S1: Late-Start Chain Reaction

**Goal**: Verify candidate with late-start shift correctly shows churn for next-day early slot.

**Setup**:
1. Target date = Wednesday (e.g., 2026-01-15)
2. Open slot late today: 20:00-23:00
3. Driver A has Thursday 04:45 assignment

**Steps**:
```bash
# Step S1.1: Get candidates with multiday OFF (default)
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=false

# Step S1.2: Find Driver A in candidates
# Expected with multiday OFF:
# - Driver A has churn_count >= 1
# - affected_slots includes Thu 04:45 slot
# - reason = "REST_NEXTDAY_FIRST_SLOT" or "REST_VIOLATION"
# - lookahead_ok = false (churn blocks candidate)
# - feasible_today = true (no TODAY conflict)

# Step S1.3: Get candidates with multiday ON
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=true

# Expected with multiday ON:
# - Driver A has churn_count >= 1 (same)
# - lookahead_ok = true (multiday allows churn)
# - affected_slots shows exactly which slots need repair
# - UI should show warning banner

# Step S1.4: UI verification (manual)
# In CandidateDrawer:
# - Default filter "Show only no-impact" = checked
# - Driver A is HIDDEN (has churn > 0)
# - Unchecking filter reveals Driver A with amber repair icon
# - Clicking Driver A shows affected_slots list
```

**Pass Criteria**:
| Check | Expected |
|-------|----------|
| Late-today slot shows REST conflict | reason = REST_* |
| Multiday OFF hides candidate | lookahead_ok = false |
| Multiday ON reveals candidate | lookahead_ok = true |
| affected_slots accurate | Thu 04:45 slot listed |
| UI default hides churn>0 | Filter checked by default |

### Scenario S2: Frozen Future Day Hard Block

**Goal**: Verify candidate requiring tomorrow repair is HARD BLOCKED when tomorrow is frozen.

**Setup**:
1. Target date = Wednesday (e.g., 2026-01-15)
2. Thursday (2026-01-16) is FROZEN
3. Open slot today: 20:00-23:00
4. Driver B has Thursday 04:45 assignment (on frozen day)

**Steps**:
```bash
# Step S2.1: Verify Thursday is frozen
GET /api/v1/roster/workbench/daily/status?site_id={site_id}&date_str=2026-01-16

# Expected:
# - is_frozen = true
# - status = "FROZEN"

# Step S2.2: Get candidates for Wednesday
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15

# Step S2.3: Find Driver B in candidates
# Expected (REGARDLESS of multiday flag):
# - Driver B has churn_locked_count >= 1
# - affected_slots includes Thu 04:45 slot
# - severity = "HARD"
# - reason = "FROZEN"
# - lookahead_ok = false (ALWAYS - locked churn)
# - feasible_today = true (no TODAY conflict)

# Step S2.4: Try with multiday ON
GET /api/v1/roster/workbench/daily/candidates?site_id={site_id}&date_str=2026-01-15&allow_multiday_repair=true

# Expected:
# - Driver B STILL has churn_locked_count >= 1
# - lookahead_ok = false (STILL - frozen overrides multiday)
# - This is the key difference from S1: multiday does NOT help

# Step S2.5: UI verification (manual)
# In CandidateDrawer:
# - Driver B shows red snowflake icon (frozen churn)
# - Ranked below all candidates with churn_locked_count = 0
# - Cannot be selected for assignment
```

**Pass Criteria**:
| Check | Expected |
|-------|----------|
| Frozen day detected | frozen_days includes 2026-01-16 |
| Locked churn counted | churn_locked_count >= 1 |
| Severity = HARD | affected_slot.severity = "HARD" |
| Reason = FROZEN | affected_slot.reason = "FROZEN" |
| Multiday doesn't help | lookahead_ok = false even with multiday=true |
| UI shows locked icon | Red snowflake, not amber |

---

## Test 9: Morning Demand Gap SOP (V4.9.3)

**Goal**: Verify activation gate (HOLD/RELEASED) state management and morning gap workflow.

### Test 9a: Basic Hold/Release Flow

```bash
# Step 9a.1: Create test slot in PLANNED state
# (Use seed data or direct SQL)

# Step 9a.2: Put slot on HOLD
POST /api/v1/roster/workbench/slots/{slot_id}/hold
Body: {"reason": "LOW_DEMAND"}

# Expected:
# - success = true
# - previous_status = "PLANNED"
# - new_status = "HOLD"
# - hold_reason = "LOW_DEMAND"

# Step 9a.3: Release slot (early - not at risk)
POST /api/v1/roster/workbench/slots/{slot_id}/release
Body: {"late_release_threshold_minutes": 120}

# Expected:
# - success = true
# - previous_status = "HOLD"
# - new_status = "RELEASED"
# - at_risk = false (slot start > 2 hours away)

# Step 9a.4: Try to release a PLANNED slot (should fail)
POST /api/v1/roster/workbench/slots/{planned_slot_id}/release
Body: {}

# Expected: 400 INVALID_TRANSITION
# Message: "Can only RELEASE from HOLD, current status is PLANNED"
```

### Test 9b: At-Risk Detection

```bash
# Step 9b.1: Create slot starting in 30 minutes
# Put it on HOLD first

# Step 9b.2: Release the slot
POST /api/v1/roster/workbench/slots/{slot_id}/release
Body: {"late_release_threshold_minutes": 120}

# Expected:
# - success = true
# - at_risk = true
# - message contains "AT_RISK"

# Step 9b.3: Verify at_risk flag stored
# Query DB: at_risk column should be TRUE
```

### Test 9c: Morning Gap Analysis

```bash
# Step 9c.1: Set up test data
# Create mix of morning slots:
# - 2x PLANNED (unassigned)
# - 1x HOLD (with reason LOW_DEMAND)
# - 1x RELEASED (at_risk=true)

# Step 9c.2: Get morning gap analysis
GET /api/v1/roster/workbench/daily/morning-gap?site_id={site_id}&date_str=2026-01-15&morning_cutoff_hour=10

# Expected:
# - summary.total_morning_slots = 4
# - summary.planned_slots = 2
# - summary.hold_slots = 1
# - summary.released_slots = 1
# - summary.at_risk_count = 1
# - slots_on_hold array has 1 entry
# - at_risk_slots array has 1 entry
# - hold_by_reason has LOW_DEMAND: 1
```

### Test 9d: Morning Gap Workflow - set_hold Action

```bash
# Step 9d.1: Execute set_hold workflow
POST /api/v1/roster/workbench/daily/morning-gap/workflow?site_id={site_id}&date_str=2026-01-15
Body: {"action": "set_hold", "hold_reason": "SURPLUS"}

# Expected:
# - success = true
# - action = "set_hold"
# - slots_affected = count of unassigned morning PLANNED/RELEASED slots
# - results array shows each slot's outcome

# Step 9d.2: Verify morning gap analysis updated
GET /api/v1/roster/workbench/daily/morning-gap?site_id={site_id}&date_str=2026-01-15

# Expected:
# - summary.hold_slots increased
# - summary.planned_slots decreased (unassigned moved to HOLD)
```

### Test 9e: Morning Gap Workflow - release_all Action

```bash
# Step 9e.1: Execute release_all workflow
POST /api/v1/roster/workbench/daily/morning-gap/workflow?site_id={site_id}&date_str=2026-01-15
Body: {"action": "release_all"}

# Expected:
# - success = true
# - action = "release_all"
# - slots_affected = count of HOLD morning slots
# - at_risk_count = count of late releases

# Step 9e.2: Verify all morning HOLD slots now RELEASED
GET /api/v1/roster/workbench/daily/morning-gap?site_id={site_id}&date_str=2026-01-15

# Expected:
# - summary.hold_slots = 0
# - summary.released_slots increased
```

### Test 9f: Frozen Day Blocks Hold/Release

```bash
# Step 9f.1: Freeze the target day
POST /api/v1/roster/workbench/daily/freeze
Body: {"date": "2026-01-15", "site_id": {site_id}}

# Step 9f.2: Try to hold a slot on frozen day
POST /api/v1/roster/workbench/slots/{slot_id_on_frozen_day}/hold
Body: {"reason": "LOW_DEMAND"}

# Expected: 409 Conflict
# Response: {"error_code": "DAY_FROZEN", "message": "..."}

# Step 9f.3: Try to release a slot on frozen day
POST /api/v1/roster/workbench/slots/{slot_id_on_frozen_day}/release
Body: {}

# Expected: 409 Conflict
```

### Test 9g: Daily Stats Include Activation Metrics

```bash
# Step 9g.1: Create slots with various statuses including HOLD/RELEASED

# Step 9g.2: Get daily stats
GET /api/v1/roster/management/daily-summary?site_id={site_id}&date_str=2026-01-15

# Expected stats object includes:
# - hold: count of HOLD slots
# - released: count of RELEASED slots
# - at_risk_count: count of at_risk RELEASED slots
# - hold_breakdown: {LOW_DEMAND: X, SURPLUS: Y, ...}
```

### Test 9h: Batch Hold/Release

```bash
# Step 9h.1: Batch hold multiple slots
POST /api/v1/roster/workbench/slots/hold
Body: {
  "operations": [
    {"slot_id": "{uuid1}", "reason": "LOW_DEMAND"},
    {"slot_id": "{uuid2}", "reason": "LOW_DEMAND"}
  ]
}

# Expected:
# - total = 2
# - applied = 2
# - rejected = 0

# Step 9h.2: Batch release
POST /api/v1/roster/workbench/slots/release
Body: {
  "slot_ids": ["{uuid1}", "{uuid2}"],
  "late_release_threshold_minutes": 120
}

# Expected:
# - total = 2
# - applied = 2
# - at_risk_count = 0 or higher depending on timing
```

---

## Morning Gap SOP - Dispatcher Workflow (V4.9.3)

### Standard Morning Procedure

**When**: Every morning before 06:00

1. **Check Morning Gap Analysis**
   ```
   GET /api/v1/roster/workbench/daily/morning-gap?site_id={site_id}&date_str={today}
   ```
   - Review `summary.planned_slots` (unassigned morning slots)
   - Check if demand forecast matches reality

2. **If surplus morning slots (demand lower than planned)**:
   - Set unassigned slots to HOLD:
     ```
     POST /api/v1/roster/workbench/daily/morning-gap/workflow
     Body: {"action": "set_hold", "hold_reason": "LOW_DEMAND"}
     ```

3. **If demand increases later**:
   - Release slots individually or all:
     ```
     POST /api/v1/roster/workbench/daily/morning-gap/workflow
     Body: {"action": "release_all"}
     ```
   - Check `at_risk_count` - if > 0, prioritize these for assignment

4. **At end of day**:
   - Review `at_risk_slots` in freeze stats
   - Document reasons for late releases

### Emergency Scenario: Mass Late Release

If demand spikes and many HOLD slots need release:

1. Use `release_all` workflow
2. Check `at_risk_count` in response
3. Prioritize at-risk slots for immediate candidate search
4. Use Week Lookahead candidates API for repair

### Key Points for Dispatchers

- **HOLD** = Slot hidden from drivers, not counted in coverage
- **RELEASED** = Slot reactivated (was on HOLD)
- **AT_RISK** = Released late (< 2 hours before start)
- HOLD is **reversible** - unlike ABORTED
- HOLD preserves the planned slot for later use
- ABORTED = permanent removal from coverage

---

## GO/NO-GO Checklist Summary (V4.9.3)

| Category | Check | Status |
|----------|-------|--------|
| **Pinned semantics** | roster.pins table exists | ☐ |
| **Pinned semantics** | Pins queried in batch.py | ☐ |
| **Pinned semantics** | Safe default (empty if no pins) | ☐ |
| **Weekly hours** | HARD_CAP policy default | ☐ |
| **Weekly hours** | Exceeding cap = infeasible | ☐ |
| **Weekly hours** | Risk tier in ranking | ☐ |
| **Debug metrics** | Gated by env flag | ☐ |
| **Debug metrics** | No tenant IDs in output | ☐ |
| **Frontend parity** | BFF preserves order | ☐ |
| **Frontend parity** | No .sort() in drawer | ☐ |
| **S1: Late-start** | Churn detected | ☐ |
| **S1: Late-start** | Multiday toggle works | ☐ |
| **S2: Frozen block** | Locked churn counted | ☐ |
| **S2: Frozen block** | Multiday doesn't help | ☐ |
| **V4.9.3: Activation Gate** | HOLD status enum added | ☐ |
| **V4.9.3: Activation Gate** | RELEASED status enum added | ☐ |
| **V4.9.3: Activation Gate** | release_at column exists | ☐ |
| **V4.9.3: Activation Gate** | at_risk column exists | ☐ |
| **V4.9.3: Hold/Release** | PLANNED → HOLD works | ☐ |
| **V4.9.3: Hold/Release** | HOLD → RELEASED works | ☐ |
| **V4.9.3: Hold/Release** | PLANNED → RELEASED fails | ☐ |
| **V4.9.3: At-Risk** | Late release flagged | ☐ |
| **V4.9.3: At-Risk** | at_risk stored in DB | ☐ |
| **V4.9.3: Morning Gap** | Analysis endpoint works | ☐ |
| **V4.9.3: Morning Gap** | set_hold workflow works | ☐ |
| **V4.9.3: Morning Gap** | release_all workflow works | ☐ |
| **V4.9.3: Freeze blocks** | HOLD on frozen day fails | ☐ |
| **V4.9.3: Daily stats** | hold count included | ☐ |
| **V4.9.3: Daily stats** | hold_breakdown included | ☐ |
| **V4.9.3: Batch ops** | Batch hold works | ☐ |
| **V4.9.3: Batch ops** | Batch release works | ☐ |
| **V4.9.3-HOTFIX: INV-1** | Constraint exists | ☐ |
| **V4.9.3-HOTFIX: INV-2** | Constraint exists | ☐ |
| **V4.9.3-HOTFIX: INV-1** | HOLD+assigned blocked | ☐ |
| **V4.9.3-HOTFIX: INV-2** | ASSIGNED needs release_at | ☐ |
| **V4.9.3-HOTFIX: INV-5** | HOLD→ASSIGNED blocked | ☐ |
| **V4.9.3-HOTFIX** | set_slot_assigned exists | ☐ |
| **V4.9.3-HOTFIX** | unassign_slot exists | ☐ |
| **V4.9.3-HOTFIX** | No ghost states in DB | ☐ |
| **V4.9.3-HOTFIX** | verify_slot_state_invariants 7 PASS | ☐ |

---

## Test 10: Ghost State Prevention (V4.9.3-HOTFIX)

**Goal**: Verify slot state machine invariants prevent invalid state combinations.

### Test 10a: INV-1 - Cannot create HOLD with assignment

```sql
-- Should fail with constraint violation
INSERT INTO dispatch.daily_slots (
    slot_id, tenant_id, site_id, day_date,
    planned_start, planned_end,
    status, assigned_driver_id, hold_set_at, hold_reason
) VALUES (
    gen_random_uuid(), 1, 1, CURRENT_DATE,
    NOW(), NOW() + INTERVAL '8 hours',
    'HOLD', 999, NOW(), 'LOW_DEMAND'
);
-- Expected: ERROR: inv1_hold_no_assignment check constraint violation
```

### Test 10b: INV-2 - Cannot create ASSIGNED without release_at

```sql
-- Should fail with constraint violation
INSERT INTO dispatch.daily_slots (
    slot_id, tenant_id, site_id, day_date,
    planned_start, planned_end,
    status, assigned_driver_id, release_at
) VALUES (
    gen_random_uuid(), 1, 1, CURRENT_DATE,
    NOW(), NOW() + INTERVAL '8 hours',
    'ASSIGNED', 999, NULL
);
-- Expected: ERROR: inv2_assigned_has_release check constraint violation
```

### Test 10c: INV-5 - Cannot transition HOLD → ASSIGNED directly

```bash
# Step 10c.1: Create a PLANNED slot and put it on HOLD
POST /api/v1/roster/workbench/slots/{slot_id}/hold
Body: {"reason": "LOW_DEMAND"}

# Step 10c.2: Try to assign directly (should fail)
POST /api/v1/roster/workbench/slots/{slot_id}/assign
Body: {"driver_id": 123}

# Expected: 400 SLOT_ON_HOLD
# Message: "Cannot assign to HOLD slot. Must release first (INV-5)."
```

### Test 10d: Correct Flow - HOLD → RELEASED → ASSIGNED

```bash
# Step 10d.1: Create slot and HOLD
POST /api/v1/roster/workbench/slots/{slot_id}/hold
Body: {"reason": "LOW_DEMAND"}

# Step 10d.2: RELEASE
POST /api/v1/roster/workbench/slots/{slot_id}/release
Body: {}
# Expected: success = true

# Step 10d.3: ASSIGN (now works)
POST /api/v1/roster/workbench/slots/{slot_id}/assign
Body: {"driver_id": 123}
# Expected: success = true, driver_id = 123

# Verify DB state:
SELECT status, assigned_driver_id, release_at
FROM dispatch.daily_slots WHERE slot_id = '{slot_id}';
# Expected: ASSIGNED, 123, NOT NULL
```

### Test 10e: INV-1 - Cannot HOLD from ASSIGNED

```bash
# Step 10e.1: Assign a driver to a slot
POST /api/v1/roster/workbench/slots/{slot_id}/assign
Body: {"driver_id": 123}
# Expected: success = true

# Step 10e.2: Try to HOLD directly (should fail)
POST /api/v1/roster/workbench/slots/{slot_id}/hold
Body: {"reason": "LOW_DEMAND"}
# Expected: 400 INVALID_TRANSITION
# Message: "Cannot HOLD from ASSIGNED. Must unassign first."
```

### Test 10f: Correct Flow - ASSIGNED → RELEASED → HOLD

```bash
# Step 10f.1: Start with ASSIGNED slot

# Step 10f.2: UNASSIGN (goes to RELEASED)
POST /api/v1/roster/workbench/slots/{slot_id}/unassign
# Expected: success = true, new_status = "RELEASED"

# Step 10f.3: HOLD (now works)
POST /api/v1/roster/workbench/slots/{slot_id}/hold
Body: {"reason": "LOW_DEMAND"}
# Expected: success = true

# Verify no ghost state:
SELECT status, assigned_driver_id FROM dispatch.daily_slots WHERE slot_id = '{slot_id}';
# Expected: HOLD, NULL (INV-1 satisfied)
```

### Test 10g: Verification Function All PASS

```sql
SELECT * FROM dispatch.verify_slot_state_invariants();
-- Expected: 7 rows, all with status = 'PASS'
```

### Test 10h: No Ghost States Query

```sql
-- Should return 0 rows
SELECT slot_id, status, assigned_driver_id, release_at,
    CASE
        WHEN status = 'HOLD' AND assigned_driver_id IS NOT NULL THEN 'GHOST: HOLD+assigned'
        WHEN status = 'ASSIGNED' AND release_at IS NULL THEN 'GHOST: ASSIGNED-no-release'
        WHEN status = 'RELEASED' AND release_at IS NULL THEN 'GHOST: RELEASED-no-release'
    END as ghost_type
FROM dispatch.daily_slots
WHERE (status = 'HOLD' AND assigned_driver_id IS NOT NULL)
   OR (status = 'ASSIGNED' AND release_at IS NULL)
   OR (status = 'RELEASED' AND release_at IS NULL);
-- Expected: 0 rows
```

---

*Generated by Claude Code for SOLVEREIGN V4.9.3-HOTFIX*
