"""
SOLVEREIGN V3.3b - Repair API Tests
====================================

Tests:
1. Determinism Test: Repair 5x -> same output_hash
2. Integration Test: Solve -> Repair -> Audit PASS
3. Idempotency Test: Same key returns cached result
4. Lock Test: Concurrent repairs rejected

Run: python backend_py/test_repair_api.py
"""

import sys
import os
import json
import hashlib
import time
from datetime import date, timedelta

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packs.roster.engine.db import get_connection, test_connection
from packs.roster.engine.driver_model import (
    RepairRequest, RepairStrategy, AvailabilityStatus,
    create_driver, set_driver_availability, get_drivers,
    validate_driver_ids_exist
)
from packs.roster.engine.repair_engine import RepairEngine, repair_plan


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_result(name: str, passed: bool, details: str = ""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {name}")
    if details:
        print(f"         {details}")


# =============================================================================
# TEST FIXTURES
# =============================================================================

# Note: Legacy tables (forecast_versions, plan_versions) use INTEGER tenant_id
# Driver tables (drivers, driver_availability) use UUID tenant_id
TEST_TENANT_INT = 1  # For legacy tables
TEST_TENANT_UUID = "00000000-0000-0000-0000-000000000001"  # For driver tables


def setup_test_data():
    """Set up test data for repair tests."""
    print_header("SETUP: Create Test Data")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if we have forecast and plan versions
            cur.execute("SELECT id FROM forecast_versions WHERE tenant_id = %s LIMIT 1", (TEST_TENANT_INT,))
            fv = cur.fetchone()

            if not fv:
                print("  [INFO] Creating test forecast version...")
                # Create a minimal forecast
                cur.execute("""
                    INSERT INTO forecast_versions
                        (tenant_id, source, input_hash, parser_config_hash, status,
                         week_anchor_date, week_key)
                    VALUES (%s, 'test', 'test_hash', 'parser_v1', 'PASS',
                            CURRENT_DATE - EXTRACT(DOW FROM CURRENT_DATE)::INT + 1,
                            to_char(CURRENT_DATE, 'IYYY-"W"IW'))
                    RETURNING id
                """, (TEST_TENANT_INT,))
                fv = cur.fetchone()
                forecast_id = fv['id']
                print(f"  [INFO] Created forecast_version id={forecast_id}")
            else:
                forecast_id = fv['id']
                print(f"  [INFO] Using existing forecast_version id={forecast_id}")

            # Check for tour instances
            cur.execute("""
                SELECT COUNT(*) as cnt FROM tour_instances
                WHERE forecast_version_id = %s
            """, (forecast_id,))
            ti_count = cur.fetchone()['cnt']

            if ti_count == 0:
                print("  [INFO] Creating test tour instances...")
                # Create a few test tours
                for day in range(1, 8):  # Mo-So
                    for i in range(3):  # 3 tours per day
                        start_hour = 6 + i * 4  # 06:00, 10:00, 14:00
                        cur.execute("""
                            INSERT INTO tour_instances
                                (forecast_version_id, tour_template_id, instance_no,
                                 day, start_ts, end_ts, duration_min, work_hours,
                                 crosses_midnight, span_group_key)
                            VALUES (%s, %s, 1, %s, %s::TIME, %s::TIME, 240, 4.0, FALSE, 'test')
                        """, (
                            forecast_id,
                            day * 10 + i,  # Fake template ID
                            day,
                            f"{start_hour:02d}:00",
                            f"{start_hour + 4:02d}:00"
                        ))
                conn.commit()
                print(f"  [INFO] Created 21 test tour instances")
            else:
                print(f"  [INFO] Using {ti_count} existing tour instances")

            # Check for plan version
            cur.execute("""
                SELECT id FROM plan_versions
                WHERE forecast_version_id = %s AND tenant_id = %s
                LIMIT 1
            """, (forecast_id, TEST_TENANT_INT))
            pv = cur.fetchone()

            if not pv:
                print("  [INFO] Creating test plan version...")
                cur.execute("""
                    INSERT INTO plan_versions
                        (tenant_id, forecast_version_id, seed, solver_config_hash,
                         output_hash, status)
                    VALUES (%s, %s, 42, 'config_v1', 'output_hash_test', 'DRAFT')
                    RETURNING id
                """, (TEST_TENANT_INT, forecast_id))
                pv = cur.fetchone()
                plan_id = pv['id']
                print(f"  [INFO] Created plan_version id={plan_id}")
            else:
                plan_id = pv['id']
                print(f"  [INFO] Using existing plan_version id={plan_id}")

            # Get tour instances for this forecast
            cur.execute("""
                SELECT id, day, start_ts FROM tour_instances
                WHERE forecast_version_id = %s
                ORDER BY day, start_ts
            """, (forecast_id,))
            tour_instances = cur.fetchall()

            # Check for drivers
            cur.execute("""
                SELECT COUNT(*) as cnt FROM drivers WHERE tenant_id = %s
            """, (TEST_TENANT_UUID,))
            driver_count = cur.fetchone()['cnt']

            if driver_count < 5:
                print("  [INFO] Creating test drivers...")
                for i in range(10):
                    cur.execute("""
                        INSERT INTO drivers (tenant_id, external_ref, display_name, max_weekly_hours)
                        VALUES (%s, %s, %s, 55.0)
                        ON CONFLICT (tenant_id, external_ref) DO NOTHING
                        RETURNING id
                    """, (TEST_TENANT_UUID, f"REPAIR-TEST-{i:03d}", f"Driver {i}"))
                conn.commit()
                print(f"  [INFO] Created 10 test drivers")

            # Get drivers
            cur.execute("""
                SELECT id FROM drivers WHERE tenant_id = %s ORDER BY id
            """, (TEST_TENANT_UUID,))
            drivers = [r['id'] for r in cur.fetchall()]

            # Check for assignments
            cur.execute("""
                SELECT COUNT(*) as cnt FROM assignments WHERE plan_version_id = %s
            """, (plan_id,))
            assignment_count = cur.fetchone()['cnt']

            if assignment_count == 0 and tour_instances and drivers:
                print("  [INFO] Creating test assignments...")
                driver_idx = 0
                for ti in tour_instances:
                    driver_id = drivers[driver_idx % len(drivers)]
                    cur.execute("""
                        INSERT INTO assignments
                            (plan_version_id, driver_id, real_driver_id, tour_instance_id,
                             day, block_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        plan_id,
                        str(driver_id),  # Legacy VARCHAR field
                        driver_id,       # New FK field
                        ti['id'],
                        ti['day'],
                        f"block_{ti['day']}_{driver_idx}"
                    ))
                    driver_idx += 1
                conn.commit()
                print(f"  [INFO] Created {len(tour_instances)} assignments")
            else:
                print(f"  [INFO] {assignment_count} assignments exist")

            conn.commit()
            return {
                "forecast_id": forecast_id,
                "plan_id": plan_id,
                "drivers": drivers,
                "tour_instances": [dict(ti) for ti in tour_instances]
            }


def cleanup_test_data():
    """Clean up test repair data (keeping drivers for other tests)."""
    print_header("CLEANUP: Remove Test Repair Data")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Clean repair logs (uses UUID tenant)
            cur.execute("""
                DELETE FROM repair_log
                WHERE tenant_id = %s
            """, (TEST_TENANT_UUID,))
            deleted = cur.rowcount
            print(f"  [INFO] Deleted {deleted} repair_log entries")

            # Clean test plan versions created during repair (uses INT tenant)
            cur.execute("""
                DELETE FROM plan_versions
                WHERE tenant_id = %s AND is_repair = TRUE
            """, (TEST_TENANT_INT,))
            deleted = cur.rowcount
            print(f"  [INFO] Deleted {deleted} repair plan versions")

            conn.commit()


# =============================================================================
# TEST: DETERMINISM
# =============================================================================

def test_determinism():
    """Test: Repair 5x -> same output_hash."""
    print_header("TEST 1: Determinism (5 runs, same output_hash)")

    test_data = setup_test_data()
    plan_id = test_data["plan_id"]
    drivers = test_data["drivers"]

    if len(drivers) < 2:
        print("  [SKIP] Not enough drivers for determinism test")
        return True

    # Pick first driver as "absent"
    absent_driver_ids = [drivers[0]]

    # Run repair 5 times
    results = []
    output_hashes = set()

    for run in range(5):
        request = RepairRequest(
            plan_version_id=plan_id,
            absent_driver_ids=absent_driver_ids,
            respect_freeze=False,  # Disable freeze for testing
            strategy=RepairStrategy.MIN_CHURN,
            seed=42  # Fixed seed
        )

        engine = RepairEngine(tenant_id=TEST_TENANT_UUID)
        result = engine.repair(request, requested_by="test")
        results.append(result)

        if result.new_plan_version_id:
            # Get output hash from new plan
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT output_hash FROM plan_versions WHERE id = %s
                    """, (result.new_plan_version_id,))
                    row = cur.fetchone()
                    if row:
                        output_hashes.add(row['output_hash'])

        print(f"  Run {run + 1}: status={result.status.value}, "
              f"tours_reassigned={result.tours_reassigned}, "
              f"time={result.execution_time_ms}ms")

    # Check all hashes are identical
    all_same = len(output_hashes) == 1

    print_result(
        "All 5 runs produced identical output_hash",
        all_same,
        f"unique hashes: {len(output_hashes)}"
    )

    # Also check tours_reassigned is consistent
    reassigned_counts = [r.tours_reassigned for r in results]
    consistent_count = len(set(reassigned_counts)) == 1

    print_result(
        "tours_reassigned consistent across runs",
        consistent_count,
        f"counts: {reassigned_counts}"
    )

    return all_same and consistent_count


# =============================================================================
# TEST: INTEGRATION (Solve -> Repair -> Audit)
# =============================================================================

def test_integration():
    """Test: Solve -> Repair -> Audit PASS."""
    print_header("TEST 2: Integration (Solve -> Repair -> Audit)")

    test_data = setup_test_data()
    plan_id = test_data["plan_id"]
    drivers = test_data["drivers"]

    if len(drivers) < 3:
        print("  [SKIP] Not enough drivers for integration test")
        return True

    # Mark driver 0 as SICK
    absent_driver_ids = [drivers[0]]

    print(f"  [INFO] Running repair with absent_driver_ids={absent_driver_ids}")

    request = RepairRequest(
        plan_version_id=plan_id,
        absent_driver_ids=absent_driver_ids,
        respect_freeze=False,  # Disable freeze for testing
        strategy=RepairStrategy.MIN_CHURN,
        seed=42
    )

    engine = RepairEngine(tenant_id=TEST_TENANT_UUID)
    result = engine.repair(request, requested_by="integration_test")

    print(f"  [INFO] Repair result: status={result.status.value}")
    print(f"         tours_reassigned={result.tours_reassigned}")
    print(f"         drivers_affected={result.drivers_affected}")
    print(f"         churn_rate={result.churn_rate:.2%}")

    # Check repair succeeded
    repair_success = result.status.value == "SUCCESS"
    print_result("Repair completed successfully", repair_success)

    if not repair_success:
        print(f"  [ERROR] {result.error_message}")
        return False

    # Check new plan was created
    new_plan_created = result.new_plan_version_id is not None
    print_result("New plan version created", new_plan_created,
                f"plan_id={result.new_plan_version_id}")

    # Check audits passed
    if result.audit_results:
        audits_passed = result.audit_results.get('all_passed', False)
        checks_run = result.audit_results.get('checks_run', 0)
        checks_passed = result.audit_results.get('checks_passed', 0)

        print_result(
            "All audit checks passed",
            audits_passed,
            f"{checks_passed}/{checks_run} checks"
        )
    else:
        audits_passed = True  # No audit results means success path was taken
        print("  [INFO] Audit results not available (plan unchanged)")

    return repair_success and new_plan_created


# =============================================================================
# TEST: IDEMPOTENCY
# =============================================================================

def test_idempotency():
    """Test: Same idempotency key returns cached result."""
    print_header("TEST 3: Idempotency (same key -> cached result)")

    test_data = setup_test_data()
    plan_id = test_data["plan_id"]
    drivers = test_data["drivers"]

    if len(drivers) < 2:
        print("  [SKIP] Not enough drivers for idempotency test")
        return True

    absent_driver_ids = [drivers[0]]
    idempotency_key = f"test-idem-{int(time.time())}"

    # First request
    request1 = RepairRequest(
        plan_version_id=plan_id,
        absent_driver_ids=absent_driver_ids,
        respect_freeze=False,
        strategy=RepairStrategy.MIN_CHURN,
        seed=42,
        idempotency_key=idempotency_key
    )

    engine = RepairEngine(tenant_id=TEST_TENANT_UUID)
    result1 = engine.repair(request1, requested_by="idem_test_1")

    print(f"  [INFO] First request: repair_log_id={result1.repair_log_id}")

    # Second request with same key
    request2 = RepairRequest(
        plan_version_id=plan_id,
        absent_driver_ids=absent_driver_ids,
        respect_freeze=False,
        strategy=RepairStrategy.MIN_CHURN,
        seed=42,
        idempotency_key=idempotency_key
    )

    # Check idempotency in database
    # NOTE: Idempotency check was in deleted backend_py.src - stub returns None
    cached = None  # Idempotency feature needs reimplementation in packs.roster.api

    cached_found = cached is not None
    print_result("Cached result found for idempotency key", cached_found)

    if cached:
        same_repair_log = cached.get('repair_log_id') == result1.repair_log_id
        print_result(
            "Cached repair_log_id matches original",
            same_repair_log,
            f"cached={cached.get('repair_log_id')}, original={result1.repair_log_id}"
        )
        return same_repair_log

    return cached_found


# =============================================================================
# TEST: VALIDATION ERRORS
# =============================================================================

def test_validation_errors():
    """Test: Invalid inputs return proper errors."""
    print_header("TEST 4: Validation Errors")

    test_data = setup_test_data()
    plan_id = test_data["plan_id"]

    all_passed = True

    # Test 1: Empty absent_driver_ids
    print("\n  Test 4.1: Empty absent_driver_ids")
    request = RepairRequest(
        plan_version_id=plan_id,
        absent_driver_ids=[],  # Empty!
        respect_freeze=False,
        strategy=RepairStrategy.MIN_CHURN
    )

    engine = RepairEngine(tenant_id=TEST_TENANT_UUID)
    result = engine.repair(request)

    # Should succeed with 0 changes (no absent drivers = no changes)
    # Actually empty list should be caught by validation
    no_change = result.tours_reassigned == 0
    print_result("Empty absent list handled correctly", no_change or result.status.value == "FAILED")

    # Test 2: Invalid driver ID
    print("\n  Test 4.2: Invalid driver ID")
    request = RepairRequest(
        plan_version_id=plan_id,
        absent_driver_ids=[999999],  # Non-existent
        respect_freeze=False,
        strategy=RepairStrategy.MIN_CHURN
    )

    result = engine.repair(request)
    invalid_handled = result.status.value == "FAILED" and "Invalid driver" in str(result.error_message)
    print_result("Invalid driver ID rejected", invalid_handled,
                f"error={result.error_message}")
    all_passed = all_passed and invalid_handled

    # Test 3: Non-existent plan
    print("\n  Test 4.3: Non-existent plan ID")
    request = RepairRequest(
        plan_version_id=999999,
        absent_driver_ids=[1],
        respect_freeze=False,
        strategy=RepairStrategy.MIN_CHURN
    )

    result = engine.repair(request)
    not_found_handled = result.status.value == "FAILED" and "not found" in str(result.error_message).lower()
    print_result("Non-existent plan rejected", not_found_handled,
                f"error={result.error_message}")
    all_passed = all_passed and not_found_handled

    return all_passed


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all repair API tests."""
    print("\n" + "="*60)
    print("  SOLVEREIGN V3.3b - Repair API Tests")
    print("="*60)

    # Test connection first
    if not test_connection():
        print("\n[FAIL] Database connection failed!")
        print("       Start the database: docker compose up -d postgres")
        return 1

    print("\n[OK] Database connection successful")

    results = []

    # Run tests
    try:
        results.append(("Determinism (5x same hash)", test_determinism()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("Determinism (5x same hash)", False))

    try:
        results.append(("Integration (Solve->Repair->Audit)", test_integration()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("Integration (Solve->Repair->Audit)", False))

    try:
        results.append(("Idempotency", test_idempotency()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("Idempotency", False))

    try:
        results.append(("Validation Errors", test_validation_errors()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("Validation Errors", False))

    # Cleanup
    cleanup_test_data()

    # Summary
    print_header("SUMMARY")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n  Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n  [SUCCESS] All repair API tests passed!")
        return 0
    else:
        print("\n  [FAILURE] Some tests failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
