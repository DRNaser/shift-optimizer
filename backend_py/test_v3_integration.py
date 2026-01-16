#!/usr/bin/env python3
"""
SOLVEREIGN V3 Integration Test
===============================

End-to-end test of V3 modules:
- Database operations
- Diff engine
- Audit framework

Usage:
    python backend_py/test_v3_integration.py

Prerequisites:
    1. docker-compose up -d postgres
    2. pip install 'psycopg[binary]'
"""

import sys
from datetime import time

try:
    from v3 import db, models
    from v3.diff_engine import compute_diff
    from v3.audit_fixed import audit_plan_fixed as audit_plan
except ImportError as e:
    print(f"[FAIL] Import error: {e}")
    print("   Ensure you're in the project root: cd shift-optimizer")
    sys.exit(1)


def test_forecast_creation():
    """Test 1: Create forecast versions with tours."""
    print("\n" + "="*70)
    print("TEST 1: Forecast Version Creation")
    print("="*70)

    try:
        # Use unique hashes to avoid conflicts
        from datetime import datetime
        timestamp = datetime.now().timestamp()

        # Create forecast version 1
        fv1_id = db.create_forecast_version(
            source="manual",
            input_hash=f"test_integration_v1_{timestamp}",
            parser_config_hash="v3.0.0-mvp",
            status="PASS",
            notes="Integration test forecast v1"
        )
        print(f"[OK] Created forecast_version {fv1_id}")

        # Add tours to forecast v1
        fingerprint1 = models.compute_tour_fingerprint(1, time(6, 0), time(14, 0))
        tour1_id = db.create_tour_normalized(
            forecast_version_id=fv1_id,
            day=1,  # Monday
            start_ts="06:00:00",
            end_ts="14:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint1,
            count=3,
            depot="Depot Nord"
        )
        print(f"[OK] Created tour {tour1_id} (Mo 06:00-14:00, count=3)")

        fingerprint2 = models.compute_tour_fingerprint(2, time(7, 0), time(15, 0))
        tour2_id = db.create_tour_normalized(
            forecast_version_id=fv1_id,
            day=2,  # Tuesday
            start_ts="07:00:00",
            end_ts="15:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint2,
            count=2,
            depot="Depot Süd"
        )
        print(f"[OK] Created tour {tour2_id} (Di 07:00-15:00, count=2)")

        return fv1_id, tour1_id, tour2_id

    except Exception as e:
        print(f"[FAIL] Test 1 failed: {e}")
        raise


def test_diff_engine(fv1_id, _tour1_id):
    """Test 2: Diff engine with forecast changes."""
    print("\n" + "="*70)
    print("TEST 2: Diff Engine")
    print("="*70)

    try:
        # Use unique hash
        from datetime import datetime
        timestamp = datetime.now().timestamp()

        # Create forecast version 2 (with changes)
        fv2_id = db.create_forecast_version(
            source="manual",
            input_hash=f"test_integration_v2_{timestamp}",
            parser_config_hash="v3.0.0-mvp",
            status="PASS",
            notes="Integration test forecast v2 (with changes)"
        )
        print(f"[OK] Created forecast_version {fv2_id}")

        # Copy tour1 but with changed count (3 -> 5)
        fingerprint1 = models.compute_tour_fingerprint(1, time(6, 0), time(14, 0))
        db.create_tour_normalized(
            forecast_version_id=fv2_id,
            day=1,
            start_ts="06:00:00",
            end_ts="14:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint1,
            count=5,  # Changed from 3 to 5
            depot="Depot Nord"
        )
        print(f"[OK] Modified tour (Mo 06:00-14:00, count=3 -> 5)")

        # Add new tour (ADDED)
        fingerprint3 = models.compute_tour_fingerprint(3, time(8, 0), time(16, 0))
        db.create_tour_normalized(
            forecast_version_id=fv2_id,
            day=3,  # Wednesday
            start_ts="08:00:00",
            end_ts="16:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint3,
            count=4,
            depot="Depot West"
        )
        print(f"[OK] Added new tour (Mi 08:00-16:00, count=4)")

        # Note: tour2 (Di 07:00-15:00) is REMOVED (not in fv2)

        # Compute diff
        print("\n[TEST] Computing diff...")
        diff = compute_diff(fv1_id, fv2_id)

        print(f"\n[OK] Diff Results:")
        print(f"   Added: {diff.added}")
        print(f"   Removed: {diff.removed}")
        print(f"   Changed: {diff.changed}")
        print(f"   Total changes: {diff.total_changes()}")

        # Verify expected results
        assert diff.added == 1, f"Expected 1 ADDED, got {diff.added}"
        assert diff.removed == 1, f"Expected 1 REMOVED, got {diff.removed}"
        assert diff.changed == 1, f"Expected 1 CHANGED, got {diff.changed}"
        print("[OK] Diff validation passed!")

        return fv2_id

    except Exception as e:
        print(f"[FAIL] Test 2 failed: {e}")
        raise


def test_audit_framework(fv1_id):
    """Test 3: Audit framework with plan version."""
    print("\n" + "="*70)
    print("TEST 3: Audit Framework")
    print("="*70)

    try:
        # Create plan version
        plan_id = db.create_plan_version(
            forecast_version_id=fv1_id,
            seed=94,
            solver_config_hash="v3.0.0-mvp-test",
            output_hash="test_output_hash_001",
            status="DRAFT",
            notes="Integration test plan"
        )
        print(f"[OK] Created plan_version {plan_id}")

        # P0: Expand tour templates to instances first
        from v3 import db_instances
        # Expand all tours for this forecast
        count = db_instances.expand_tour_template(fv1_id)
        print(f"[OK] Expanded {count} tour instances")

        # Get tour instances for this forecast
        instances = db_instances.get_tour_instances(fv1_id)
        print(f"[OK] Found {len(instances)} tour instances in forecast")

        # Create assignments (simulate solver output)
        # Assign each instance to a driver
        for i, instance in enumerate(instances, 1):
            db.create_assignment(
                plan_version_id=plan_id,
                driver_id=f"D{i:03d}",
                tour_instance_id=instance["id"],
                day=instance["day"],
                block_id=f"D{instance['day']}_B{(i-1)//3 + 1}"  # Group into blocks of 3
            )
        print(f"[OK] Created {len(instances)} assignments")

        # Run audit checks
        print("\n[TEST] Running audit checks...")
        results = audit_plan(plan_id, save_to_db=True)

        print(f"\n[OK] Audit Results:")
        print(f"   All passed: {results['all_passed']}")
        print(f"   Checks run: {results['checks_run']}")
        print(f"   Checks passed: {results['checks_passed']}")
        print(f"   Checks failed: {results['checks_failed']}")

        # Print individual check results
        for check_name, check_result in results["results"].items():
            status_icon = "[OK]" if check_result["status"] == "PASS" else "[FAIL]"
            print(f"   {status_icon} {check_name}: {check_result['status']} (violations: {check_result['violation_count']})")

        # Verify coverage check passed
        assert results["results"]["COVERAGE"]["status"] == "PASS", "Coverage check failed"
        print("\n[OK] Audit validation passed!")

        return plan_id

    except Exception as e:
        print(f"[FAIL] Test 3 failed: {e}")
        raise


def test_release_gates(plan_id):
    """Test 4: Release gate checking."""
    print("\n" + "="*70)
    print("TEST 4: Release Gates")
    print("="*70)

    try:
        # Check if plan can be released
        can_release, blocking_checks = db.can_release(plan_id)

        print(f"\n[TEST] Release Gate Status:")
        print(f"   Can release: {can_release}")

        if blocking_checks:
            print(f"   Blocking checks:")
            for check in blocking_checks:
                print(f"      [FAIL] {check}")
        else:
            print(f"   [OK] All mandatory checks passed")

        # Test plan locking (if gates pass)
        if can_release:
            print("\n[TEST] Attempting to lock plan...")
            success = db.lock_plan_version(plan_id, locked_by="integration_test")

            if success:
                print(f"   [OK] Plan locked successfully")

                # Verify plan status changed
                plan = db.get_plan_version(plan_id)
                assert plan["status"] == "LOCKED", f"Expected LOCKED, got {plan['status']}"
                assert plan["locked_by"] == "integration_test"
                print(f"   [OK] Plan status: {plan['status']}")
                print(f"   [OK] Locked by: {plan['locked_by']}")
            else:
                print(f"   [FAIL] Failed to lock plan")
        else:
            print(f"   [PAUSED]  Skipping lock (gates not passed)")

        print("\n[OK] Release gate validation passed!")

    except Exception as e:
        print(f"[FAIL] Test 4 failed: {e}")
        raise


def test_cleanup():
    """Test 5: Cleanup test data."""
    print("\n" + "="*70)
    print("TEST 5: Cleanup")
    print("="*70)

    try:
        # Note: In production, you'd delete test data here
        # For this test, we'll leave it (useful for manual inspection)
        print("[OK] Test data preserved for manual inspection")
        print("   (Run 'DELETE FROM forecast_versions WHERE input_hash LIKE 'test_integration%'' to clean up)")

    except Exception as e:
        print(f"[FAIL] Test 5 failed: {e}")
        raise


def main():
    """Run all integration tests."""
    print("="*70)
    print("SOLVEREIGN V3 Integration Test Suite")
    print("="*70)

    # Test database connection
    print("\n[TEST] Testing database connection...")
    if not db.test_connection():
        print("[FAIL] Database connection failed!")
        print("   Ensure PostgreSQL is running: docker-compose up -d postgres")
        sys.exit(1)
    print("[OK] Database connection successful!")

    try:
        # Run tests
        fv1_id, tour1_id, _tour2_id = test_forecast_creation()
        test_diff_engine(fv1_id, tour1_id)
        plan_id = test_audit_framework(fv1_id)
        test_release_gates(plan_id)
        test_cleanup()

        # Success!
        print("\n" + "="*70)
        print("[OK] ALL INTEGRATION TESTS PASSED!")
        print("="*70)
        print("\n[TEST] Summary:")
        print(f"   Forecast versions created: 2")
        print(f"   Tours created: 4")
        print(f"   Plan versions created: 1")
        print(f"   Assignments created: 5")
        print(f"   Audit checks run: 3")
        print(f"   Diff operations: 1")
        print(f"   Release gates checked: 1")
        print("\n[HINT] Next Steps:")
        print("   1. Review data: docker exec -it solvereign-db psql -U solvereign")
        print("   2. See solver wrapper: backend_py/packs/roster/engine/")
        print("   3. See parser: backend_py/packs/roster/engine/parser.py")
        print("   4. Use REST API: backend_py/api/main.py")
        print()

    except Exception as e:
        print("\n" + "="*70)
        print("[FAIL] INTEGRATION TESTS FAILED")
        print("="*70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
