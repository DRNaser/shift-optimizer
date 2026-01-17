"""
SOLVEREIGN V4.9.3-HOTFIX - Slot State Machine Invariant Tests
=============================================================

Tests for ghost state prevention and state machine invariants.

NON-NEGOTIABLES:
- INV-1: HOLD implies NO ASSIGNMENT (status='HOLD' → assigned_driver_id IS NULL)
- INV-2: ASSIGNED implies release_at SET (status='ASSIGNED' → release_at IS NOT NULL)
- INV-3: RELEASED implies release_at SET (existing constraint)
- INV-4: Frozen day blocks all mutations
- INV-5: Cannot HOLD from ASSIGNED (must unassign first)

Test Categories:
1. DB constraint tests (verify constraints exist and reject violations)
2. State transition tests (verify valid/invalid transitions)
3. Ghost state prevention tests (verify no invalid state combinations)
4. Idempotency tests (verify atomic operations)
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone, date, timedelta


class TestSlotStateInvariants:
    """Tests for slot state machine invariants."""

    @pytest.fixture
    def test_slot(self, conn, tenant_id, site_id):
        """Create a test slot for state transition tests."""
        async def _create(status="PLANNED", assigned_driver_id=None, release_at=None):
            day_date = date.today()
            slot_id = uuid4()

            # Create workbench day if not exists
            await conn.execute(
                """
                INSERT INTO dispatch.workbench_days (tenant_id, site_id, day_date, status)
                VALUES ($1, $2, $3, 'OPEN')
                ON CONFLICT (tenant_id, site_id, day_date) DO NOTHING
                """,
                tenant_id, site_id, day_date
            )

            # Create slot
            await conn.execute(
                """
                INSERT INTO dispatch.daily_slots (
                    slot_id, tenant_id, site_id, day_date,
                    planned_start, planned_end, status,
                    assigned_driver_id, release_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7::dispatch_slot_status,
                    $8, $9
                )
                """,
                slot_id, tenant_id, site_id, day_date,
                datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=8),
                status, assigned_driver_id, release_at
            )
            return slot_id
        return _create

    # =========================================================================
    # INV-1 TESTS: HOLD implies NO ASSIGNMENT
    # =========================================================================

    @pytest.mark.asyncio
    async def test_inv1_constraint_exists(self, conn):
        """Verify INV-1 constraint exists in database."""
        row = await conn.fetchrow(
            """
            SELECT conname FROM pg_constraint
            WHERE conname = 'inv1_hold_no_assignment'
            """
        )
        assert row is not None, "INV-1 constraint must exist"

    @pytest.mark.asyncio
    async def test_inv1_direct_insert_rejected(self, conn, tenant_id, site_id):
        """Verify direct INSERT of HOLD with assigned_driver_id is rejected."""
        day_date = date.today()
        slot_id = uuid4()

        # Ensure day exists and is open
        await conn.execute(
            """
            INSERT INTO dispatch.workbench_days (tenant_id, site_id, day_date, status)
            VALUES ($1, $2, $3, 'OPEN')
            ON CONFLICT (tenant_id, site_id, day_date) DO NOTHING
            """,
            tenant_id, site_id, day_date
        )

        # Try to create HOLD slot with driver - should fail
        with pytest.raises(Exception) as exc_info:
            await conn.execute(
                """
                INSERT INTO dispatch.daily_slots (
                    slot_id, tenant_id, site_id, day_date,
                    planned_start, planned_end,
                    status, assigned_driver_id,
                    hold_set_at, hold_reason
                ) VALUES (
                    $1, $2, $3, $4,
                    NOW(), NOW() + INTERVAL '8 hours',
                    'HOLD', 999,
                    NOW(), 'LOW_DEMAND'
                )
                """,
                slot_id, tenant_id, site_id, day_date
            )

        assert "inv1_hold_no_assignment" in str(exc_info.value).lower() or \
               "check" in str(exc_info.value).lower(), \
               "INV-1 constraint should reject HOLD+assigned"

    @pytest.mark.asyncio
    async def test_inv1_hold_from_assigned_rejected_by_function(self, conn, test_slot, test_driver):
        """Verify set_slot_hold rejects ASSIGNED → HOLD transition."""
        driver_id = await test_driver()
        slot_id = await test_slot(
            status="ASSIGNED",
            assigned_driver_id=driver_id,
            release_at=datetime.now(timezone.utc)
        )

        # Try to hold - should be rejected
        result = await conn.fetchrow(
            """
            SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test_user')
            """,
            slot_id
        )

        assert result["success"] is False, "ASSIGNED → HOLD should be rejected"
        assert "INVALID_TRANSITION" in result["message"] or "unassign" in result["message"].lower()

    # =========================================================================
    # INV-2 TESTS: ASSIGNED implies release_at SET
    # =========================================================================

    @pytest.mark.asyncio
    async def test_inv2_constraint_exists(self, conn):
        """Verify INV-2 constraint exists in database."""
        row = await conn.fetchrow(
            """
            SELECT conname FROM pg_constraint
            WHERE conname = 'inv2_assigned_has_release'
            """
        )
        assert row is not None, "INV-2 constraint must exist"

    @pytest.mark.asyncio
    async def test_inv2_direct_insert_rejected(self, conn, tenant_id, site_id):
        """Verify direct INSERT of ASSIGNED without release_at is rejected."""
        day_date = date.today()
        slot_id = uuid4()

        # Ensure day exists
        await conn.execute(
            """
            INSERT INTO dispatch.workbench_days (tenant_id, site_id, day_date, status)
            VALUES ($1, $2, $3, 'OPEN')
            ON CONFLICT (tenant_id, site_id, day_date) DO NOTHING
            """,
            tenant_id, site_id, day_date
        )

        # Try to create ASSIGNED slot without release_at - should fail
        with pytest.raises(Exception) as exc_info:
            await conn.execute(
                """
                INSERT INTO dispatch.daily_slots (
                    slot_id, tenant_id, site_id, day_date,
                    planned_start, planned_end,
                    status, assigned_driver_id, release_at
                ) VALUES (
                    $1, $2, $3, $4,
                    NOW(), NOW() + INTERVAL '8 hours',
                    'ASSIGNED', 999, NULL
                )
                """,
                slot_id, tenant_id, site_id, day_date
            )

        assert "inv2_assigned_has_release" in str(exc_info.value).lower() or \
               "check" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_inv2_set_slot_assigned_auto_sets_release_at(self, conn, test_slot, test_driver, tenant_id):
        """Verify set_slot_assigned auto-sets release_at for PLANNED slots."""
        driver_id = await test_driver()
        slot_id = await test_slot(status="PLANNED", release_at=None)

        # Assign - should auto-set release_at
        result = await conn.fetchrow(
            """
            SELECT * FROM dispatch.set_slot_assigned($1, $2, 'test_user')
            """,
            slot_id, driver_id
        )

        assert result["success"] is True, "PLANNED → ASSIGNED should succeed"

        # Verify release_at was set
        slot = await conn.fetchrow(
            "SELECT release_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id
        )
        assert slot["release_at"] is not None, "release_at should be auto-set (INV-2)"

    # =========================================================================
    # INV-5 TESTS: Cannot HOLD → ASSIGNED (must release first)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_inv5_cannot_assign_hold_slot(self, conn, test_slot, test_driver):
        """Verify cannot assign to HOLD slot directly."""
        driver_id = await test_driver()
        slot_id = await test_slot(status="PLANNED")

        # Put on hold
        await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test_user')",
            slot_id
        )

        # Try to assign - should fail
        result = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_assigned($1, $2, 'test_user')",
            slot_id, driver_id
        )

        assert result["success"] is False, "HOLD → ASSIGNED should be rejected"
        assert "HOLD" in result["message"] or "INVALID" in result["message"]

    @pytest.mark.asyncio
    async def test_inv5_correct_flow_hold_release_assign(self, conn, test_slot, test_driver):
        """Verify correct flow: PLANNED → HOLD → RELEASED → ASSIGNED."""
        driver_id = await test_driver()
        slot_id = await test_slot(status="PLANNED")

        # Step 1: PLANNED → HOLD
        result1 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test_user')",
            slot_id
        )
        assert result1["success"] is True

        # Step 2: HOLD → RELEASED
        result2 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_released($1, 'test_user')",
            slot_id
        )
        assert result2["success"] is True

        # Step 3: RELEASED → ASSIGNED
        result3 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_assigned($1, $2, 'test_user')",
            slot_id, driver_id
        )
        assert result3["success"] is True

        # Verify final state
        slot = await conn.fetchrow(
            "SELECT status, assigned_driver_id, release_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id
        )
        assert slot["status"] == "ASSIGNED"
        assert slot["assigned_driver_id"] == driver_id
        assert slot["release_at"] is not None

    # =========================================================================
    # UNASSIGN TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_unassign_transitions_to_released(self, conn, test_slot, test_driver):
        """Verify unassign transitions to RELEASED (not PLANNED)."""
        driver_id = await test_driver()
        slot_id = await test_slot(
            status="ASSIGNED",
            assigned_driver_id=driver_id,
            release_at=datetime.now(timezone.utc)
        )

        # Unassign
        result = await conn.fetchrow(
            "SELECT * FROM dispatch.unassign_slot($1, 'test_user')",
            slot_id
        )

        assert result["success"] is True
        assert result["old_driver_id"] == driver_id

        # Verify state
        slot = await conn.fetchrow(
            "SELECT status, assigned_driver_id, release_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id
        )
        assert slot["status"] == "RELEASED", "Unassign should transition to RELEASED"
        assert slot["assigned_driver_id"] is None
        assert slot["release_at"] is not None, "release_at should be preserved"

    @pytest.mark.asyncio
    async def test_unassign_allows_rehold(self, conn, test_slot, test_driver):
        """Verify after unassign, slot can be put back on HOLD."""
        driver_id = await test_driver()
        slot_id = await test_slot(
            status="ASSIGNED",
            assigned_driver_id=driver_id,
            release_at=datetime.now(timezone.utc)
        )

        # Unassign → RELEASED
        await conn.fetchrow("SELECT * FROM dispatch.unassign_slot($1, 'test_user')", slot_id)

        # Now can HOLD (RELEASED → HOLD is valid)
        result = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test_user')",
            slot_id
        )

        assert result["success"] is True
        assert result["old_status"] == "RELEASED"
        assert result["new_status"] == "HOLD"

    # =========================================================================
    # INV-4 TESTS: Frozen day blocks mutations
    # =========================================================================

    @pytest.mark.asyncio
    async def test_inv4_frozen_day_blocks_hold(self, conn, tenant_id, site_id):
        """Verify frozen day blocks HOLD mutations."""
        day_date = date.today() - timedelta(days=1)  # Yesterday
        slot_id = uuid4()

        # Create frozen day
        await conn.execute(
            """
            INSERT INTO dispatch.workbench_days (tenant_id, site_id, day_date, status, frozen_at)
            VALUES ($1, $2, $3, 'FROZEN', NOW())
            ON CONFLICT (tenant_id, site_id, day_date) DO UPDATE SET status = 'FROZEN', frozen_at = NOW()
            """,
            tenant_id, site_id, day_date
        )

        # Try to create slot in frozen day - trigger should block
        with pytest.raises(Exception) as exc_info:
            await conn.execute(
                """
                INSERT INTO dispatch.daily_slots (
                    slot_id, tenant_id, site_id, day_date,
                    planned_start, planned_end, status
                ) VALUES ($1, $2, $3, $4, NOW(), NOW() + INTERVAL '8 hours', 'PLANNED')
                """,
                slot_id, tenant_id, site_id, day_date
            )

        assert "frozen" in str(exc_info.value).lower()

    # =========================================================================
    # VERIFICATION FUNCTION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_verification_function_passes(self, conn):
        """Verify the verification function reports all checks PASS."""
        rows = await conn.fetch("SELECT * FROM dispatch.verify_slot_state_invariants()")

        for row in rows:
            assert row["status"] == "PASS", \
                f"Check '{row['check_name']}' failed: {row['details']}"

    @pytest.mark.asyncio
    async def test_no_ghost_states_in_database(self, conn):
        """Verify no ghost states exist in the database."""
        # Check for HOLD+assigned ghost states
        hold_assigned = await conn.fetchrow(
            """
            SELECT COUNT(*) as cnt FROM dispatch.daily_slots
            WHERE status = 'HOLD' AND assigned_driver_id IS NOT NULL
            """
        )
        assert hold_assigned["cnt"] == 0, "No HOLD+assigned ghost states should exist"

        # Check for ASSIGNED without release_at ghost states
        assigned_no_release = await conn.fetchrow(
            """
            SELECT COUNT(*) as cnt FROM dispatch.daily_slots
            WHERE status = 'ASSIGNED' AND release_at IS NULL
            """
        )
        assert assigned_no_release["cnt"] == 0, "No ASSIGNED without release_at should exist"

        # Check for RELEASED without release_at ghost states
        released_no_release = await conn.fetchrow(
            """
            SELECT COUNT(*) as cnt FROM dispatch.daily_slots
            WHERE status = 'RELEASED' AND release_at IS NULL
            """
        )
        assert released_no_release["cnt"] == 0, "No RELEASED without release_at should exist"


class TestGhostStatePrevention:
    """Integration tests for ghost state prevention under concurrent operations."""

    @pytest.fixture
    def test_driver(self, conn, tenant_id, site_id):
        """Create a test driver."""
        async def _create():
            result = await conn.fetchrow(
                """
                INSERT INTO drivers (tenant_id, site_id, name, is_active)
                VALUES ($1, $2, 'Test Driver', TRUE)
                RETURNING id
                """,
                tenant_id, site_id
            )
            return result["id"]
        return _create

    @pytest.mark.asyncio
    async def test_rapid_hold_release_cycle(self, conn, test_slot, tenant_id, site_id):
        """Stress test rapid HOLD/RELEASE cycling doesn't create ghost states."""
        day_date = date.today()
        slot_id = await test_slot(status="PLANNED")

        for i in range(10):
            # HOLD
            r1 = await conn.fetchrow(
                "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test')",
                slot_id
            )
            if r1["success"]:
                # RELEASE
                r2 = await conn.fetchrow(
                    "SELECT * FROM dispatch.set_slot_released($1, 'test')",
                    slot_id
                )

        # Verify no ghost state
        slot = await conn.fetchrow(
            "SELECT status, assigned_driver_id, release_at FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id
        )
        if slot["status"] == "HOLD":
            assert slot["assigned_driver_id"] is None, "INV-1 violated after cycling"
        if slot["status"] in ("RELEASED", "ASSIGNED"):
            assert slot["release_at"] is not None, "INV-2/3 violated after cycling"

    @pytest.mark.asyncio
    async def test_hold_clears_assignment_via_unassign(self, conn, test_slot, test_driver):
        """Verify holding an assigned slot requires unassign first."""
        driver_id = await test_driver()
        slot_id = await test_slot(status="PLANNED")

        # Assign
        r1 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_assigned($1, $2, 'test')",
            slot_id, driver_id
        )
        assert r1["success"]

        # Try to HOLD directly - should fail
        r2 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test')",
            slot_id
        )
        assert r2["success"] is False

        # Correct path: Unassign first
        r3 = await conn.fetchrow(
            "SELECT * FROM dispatch.unassign_slot($1, 'test')",
            slot_id
        )
        assert r3["success"]

        # Now HOLD works
        r4 = await conn.fetchrow(
            "SELECT * FROM dispatch.set_slot_hold($1, 'LOW_DEMAND'::dispatch_hold_reason, 'test')",
            slot_id
        )
        assert r4["success"]

        # Verify clean state
        slot = await conn.fetchrow(
            "SELECT status, assigned_driver_id FROM dispatch.daily_slots WHERE slot_id = $1",
            slot_id
        )
        assert slot["status"] == "HOLD"
        assert slot["assigned_driver_id"] is None


# =============================================================================
# SMOKE TEST CASES (for manual verification)
# =============================================================================

"""
SMOKE TEST RUNBOOK - Slot State Invariants
==========================================

## Test 10: Ghost State Prevention (V4.9.3-HOTFIX)

### 10a: INV-1 - Cannot create HOLD with assignment
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

### 10b: INV-2 - Cannot create ASSIGNED without release_at
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

### 10c: INV-5 - Cannot transition HOLD → ASSIGNED
```sql
-- Create a HOLD slot
WITH slot AS (
    INSERT INTO dispatch.daily_slots (
        slot_id, tenant_id, site_id, day_date, planned_start, planned_end,
        status, hold_set_at, hold_reason
    ) VALUES (
        gen_random_uuid(), 1, 1, CURRENT_DATE, NOW(), NOW() + INTERVAL '8 hours',
        'HOLD', NOW(), 'LOW_DEMAND'
    ) RETURNING slot_id
)
SELECT * FROM dispatch.set_slot_assigned(
    (SELECT slot_id FROM slot), 999, 'test_user'
);
-- Expected: success = FALSE, message contains 'HOLD' or 'INVALID'
```

### 10d: Verification query returns all PASS
```sql
SELECT * FROM dispatch.verify_slot_state_invariants();
-- Expected: All 7 checks PASS
```

### 10e: No ghost states exist
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

## GO/NO-GO Checklist - V4.9.3-HOTFIX

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | INV-1 constraint exists | `SELECT conname FROM pg_constraint WHERE conname = 'inv1_hold_no_assignment'` | 1 row |
| 2 | INV-2 constraint exists | `SELECT conname FROM pg_constraint WHERE conname = 'inv2_assigned_has_release'` | 1 row |
| 3 | set_slot_assigned exists | `SELECT proname FROM pg_proc WHERE proname = 'set_slot_assigned'` | 1 row |
| 4 | unassign_slot exists | `SELECT proname FROM pg_proc WHERE proname = 'unassign_slot'` | 1 row |
| 5 | No ghost states | Verification query above | 0 rows |
| 6 | All invariant checks pass | `SELECT * FROM dispatch.verify_slot_state_invariants()` | 7 PASS |
| 7 | HOLD→ASSIGNED blocked | Test 10c | success = FALSE |
"""
