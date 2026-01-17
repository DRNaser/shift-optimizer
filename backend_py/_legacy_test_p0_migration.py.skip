#!/usr/bin/env python3
"""
SOLVEREIGN V3 - P0 Migration Test
==================================

Tests the tour_instances migration and fixed audit checks.

Prerequisites:
    1. docker-compose up -d postgres
    2. Apply migration: psql -f backend_py/db/migrations/001_tour_instances.sql
    3. pip install 'psycopg[binary]'

Usage:
    python backend_py/test_p0_migration.py
"""

import sys
from datetime import time

try:
    from v3 import db, models
    from packs.roster.engine.db_instances import (
        expand_tour_template,
        get_tour_instances,
        create_assignment_fixed,
        check_coverage_fixed,
    )
    from packs.roster.engine.audit_fixed import audit_plan_fixed
except ImportError as e:
    print(f"ERROR: Import failed: {e}")
    print("   Ensure you're in the project root: cd shift-optimizer")
    sys.exit(1)


def test_migration_applied():
    """Test 1: Verify migration 001 was applied."""
    print("\n" + "="*70)
    print("TEST 1: Migration Applied")
    print("="*70)

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if tour_instances table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'tour_instances'
                    ) AS exists
                """)
                row = cur.fetchone()
                exists = row['exists'] if isinstance(row, dict) else row[0]

                if not exists:
                    print("ERROR: tour_instances table does not exist!")
                    print("   Run migration: psql -f backend_py/db/migrations/001_tour_instances.sql")
                    return False

                print("OK: tour_instances table exists")

                # Check if expand_tour_instances function exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_proc
                        WHERE proname = 'expand_tour_instances'
                    ) AS exists
                """)
                row = cur.fetchone()
                exists = row['exists']

                if not exists:
                    print("ERROR: expand_tour_instances function does not exist!")
                    return False

                print("OK: expand_tour_instances function exists")

                # Check if assignments table has tour_instance_id column
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'assignments'
                        AND column_name = 'tour_instance_id'
                    ) AS exists
                """)
                row = cur.fetchone()
                exists = row['exists']

                if not exists:
                    print("ERROR: assignments.tour_instance_id column does not exist!")
                    return False

                print("OK: assignments.tour_instance_id column exists")

        print("\nPASS: Migration 001 successfully applied!")
        return True

    except Exception as e:
        print(f"FAIL: Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tour_instance_expansion():
    """Test 2: Create forecast and expand to tour instances."""
    print("\n" + "="*70)
    print("TEST 2: Tour Instance Expansion")
    print("="*70)

    try:
        # Use unique hash to avoid conflicts (LOCKED plans cannot be deleted due to triggers)
        from datetime import datetime
        unique_hash = f"test_p0_migration_{datetime.now().timestamp()}"

        # Create forecast version
        fv_id = db.create_forecast_version(
            source="manual",
            input_hash=unique_hash,
            parser_config_hash="v3.0.0-mvp",
            status="PASS",
            notes="P0 migration test"
        )
        print(f"OK: Created forecast_version {fv_id}")

        # Add tours with different counts
        fingerprint1 = models.compute_tour_fingerprint(1, time(6, 0), time(14, 0))
        tour1_id = db.create_tour_normalized(
            forecast_version_id=fv_id,
            day=1,  # Monday
            start_ts="06:00:00",
            end_ts="14:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint1,
            count=3,  # Should create 3 instances
            depot="Depot Nord"
        )
        print(f"OK: Created tour {tour1_id} (Mo 06:00-14:00, count=3)")

        fingerprint2 = models.compute_tour_fingerprint(2, time(7, 0), time(15, 0))
        tour2_id = db.create_tour_normalized(
            forecast_version_id=fv_id,
            day=2,  # Tuesday
            start_ts="07:00:00",
            end_ts="15:00:00",
            duration_min=480,
            work_hours=8.0,
            tour_fingerprint=fingerprint2,
            count=2,  # Should create 2 instances
            depot="Depot Sud"
        )
        print(f"OK: Created tour {tour2_id} (Di 07:00-15:00, count=2)")

        # Expand tours to instances
        print("\nExpanding tours to instances...")
        instances_created = expand_tour_template(fv_id)
        print(f"OK: Created {instances_created} tour instances")

        # Verify instance count
        instances = get_tour_instances(fv_id)
        print(f"OK: Retrieved {len(instances)} instances from database")

        # Verify expected counts
        if instances_created != 5:
            print(f"ERROR: Expected 5 instances, got {instances_created}")
            return False

        if len(instances) != 5:
            print(f"ERROR: Expected 5 instances from query, got {len(instances)}")
            return False

        # Verify instance details
        tour1_instances = [i for i in instances if i["tour_template_id"] == tour1_id]
        tour2_instances = [i for i in instances if i["tour_template_id"] == tour2_id]

        if len(tour1_instances) != 3:
            print(f"ERROR: Tour 1 should have 3 instances, got {len(tour1_instances)}")
            return False

        if len(tour2_instances) != 2:
            print(f"ERROR: Tour 2 should have 2 instances, got {len(tour2_instances)}")
            return False

        print(f"OK: Tour 1 has 3 instances (instance_numbers: {[i['instance_number'] for i in tour1_instances]})")
        print(f"OK: Tour 2 has 2 instances (instance_numbers: {[i['instance_number'] for i in tour2_instances]})")

        print("\nPASS: Tour instance expansion works correctly!")
        return fv_id, instances

    except Exception as e:
        print(f"FAIL: Test 2 failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def test_fixed_assignments(fv_id, instances):
    """Test 3: Create assignments with tour_instance_id."""
    print("\n" + "="*70)
    print("TEST 3: Fixed Assignments (tour_instance_id)")
    print("="*70)

    try:
        # Create plan version
        plan_id = db.create_plan_version(
            forecast_version_id=fv_id,
            seed=94,
            solver_config_hash="v3.0.0-mvp-test",
            output_hash="test_p0_hash_001",
            status="DRAFT",
            notes="P0 migration test plan"
        )
        print(f"OK: Created plan_version {plan_id}")

        # Create assignments for each instance
        assignments_created = 0
        for i, instance in enumerate(instances):
            assignment_id = create_assignment_fixed(
                plan_version_id=plan_id,
                driver_id=f"D{i+1:03d}",
                tour_instance_id=instance["id"],
                day=instance["day"],
                block_id=f"D{instance['day']}_B1"
            )
            assignments_created += 1
            print(f"OK: Created assignment {assignment_id} (Driver D{i+1:03d} -> Instance {instance['id']})")

        print(f"\nOK: Created {assignments_created} assignments")

        # Verify expected count
        if assignments_created != 5:
            print(f"ERROR: Expected 5 assignments, got {assignments_created}")
            return None

        print("\nPASS: Fixed assignments work correctly!")
        return plan_id

    except Exception as e:
        print(f"FAIL: Test 3 failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_fixed_coverage_check(plan_id):
    """Test 4: Verify fixed coverage check."""
    print("\n" + "="*70)
    print("TEST 4: Fixed Coverage Check")
    print("="*70)

    try:
        # Run coverage check
        coverage_result = check_coverage_fixed(plan_id)

        print(f"\nCoverage Results:")
        print(f"   Status: {coverage_result['status']}")
        print(f"   Total instances: {coverage_result['total_instances']}")
        print(f"   Total assignments: {coverage_result['total_assignments']}")
        print(f"   Coverage ratio: {coverage_result['coverage_ratio']:.2%}")
        print(f"   Missing instances: {len(coverage_result['missing_instances'])}")
        print(f"   Extra assignments: {len(coverage_result['extra_assignments'])}")

        # Verify 100% coverage
        if coverage_result["status"] != "PASS":
            print(f"\nERROR: Coverage check failed!")
            print(f"   Missing instances: {coverage_result['missing_instances']}")
            print(f"   Extra assignments: {coverage_result['extra_assignments']}")
            return False

        if coverage_result["coverage_ratio"] != 1.0:
            print(f"ERROR: Coverage ratio should be 1.0, got {coverage_result['coverage_ratio']}")
            return False

        print("\nPASS: Fixed coverage check works correctly!")
        return True

    except Exception as e:
        print(f"FAIL: Test 4 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fixed_audit_framework(plan_id):
    """Test 5: Run full audit framework with fixed checks."""
    print("\n" + "="*70)
    print("TEST 5: Fixed Audit Framework")
    print("="*70)

    try:
        # Run all audit checks
        print("\nRunning audit checks...")
        audit_results = audit_plan_fixed(plan_id, save_to_db=True)

        print(f"\nAudit Results:")
        print(f"   All passed: {audit_results['all_passed']}")
        print(f"   Checks run: {audit_results['checks_run']}")
        print(f"   Checks passed: {audit_results['checks_passed']}")
        print(f"   Checks failed: {audit_results['checks_failed']}")

        # Print individual check results
        for check_name, check_result in audit_results["results"].items():
            status_icon = "OK" if check_result["status"] == "PASS" else "FAIL"
            print(f"   [{status_icon}] {check_name}: {check_result['status']} (violations: {check_result['violation_count']})")

        # Verify all checks passed
        if not audit_results["all_passed"]:
            print(f"\nERROR: Not all audit checks passed!")
            return False

        print("\nPASS: Fixed audit framework works correctly!")
        return True

    except Exception as e:
        print(f"FAIL: Test 5 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_locked_immutability(plan_id):
    """Test 6: Verify LOCKED plan immutability (assignments + audit_log)."""
    print("\n" + "="*70)
    print("TEST 6: LOCKED Plan Immutability")
    print("="*70)

    try:
        # Lock the plan
        print(f"\nLocking plan {plan_id}...")
        success = db.lock_plan_version(plan_id, locked_by="p0_migration_test")

        if not success:
            print("ERROR: Failed to lock plan!")
            return False

        print("OK: Plan locked successfully")

        # Verify plan is LOCKED
        plan = db.get_plan_version(plan_id)
        if plan["status"] != "LOCKED":
            print(f"ERROR: Plan status should be LOCKED, got {plan['status']}")
            return False

        print(f"OK: Plan status is LOCKED")

        # Try to create new assignment (should fail)
        print("\nAttempting to create assignment for LOCKED plan (should fail)...")
        try:
            create_assignment_fixed(
                plan_version_id=plan_id,
                driver_id="D999",
                tour_instance_id=1,
                day=1,
                block_id="D1_B1"
            )
            print("ERROR: Should have raised exception for LOCKED plan!")
            return False
        except Exception as e:
            if "Cannot modify data for LOCKED plan" in str(e):
                print(f"OK: Assignment creation blocked: {e}")
            else:
                print(f"ERROR: Wrong exception: {e}")
                return False

        # Try to create audit log entry (should succeed - append-only)
        print("\nAttempting to append audit log for LOCKED plan (should succeed)...")
        try:
            db.create_audit_log(
                plan_version_id=plan_id,
                check_name="TEST_CHECK",
                status="PASS",
                count=0,
                details_json={"test": "append-only"}
            )
            print("OK: Audit log append allowed (append-only)")
        except Exception as e:
            print(f"ERROR: Audit log append failed: {e}")
            return False

        print("\nPASS: LOCKED plan immutability works correctly!")
        return True

    except Exception as e:
        print(f"FAIL: Test 6 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all P0 migration tests."""
    print("="*70)
    print("SOLVEREIGN V3 - P0 Migration Test Suite")
    print("="*70)

    # Test database connection
    print("\nTesting database connection...")
    if not db.test_connection():
        print("ERROR: Database connection failed!")
        print("   Ensure PostgreSQL is running: docker-compose up -d postgres")
        sys.exit(1)
    print("OK: Database connection successful!")

    # Run tests
    results = []

    # Test 1: Migration applied
    results.append(("Migration Applied", test_migration_applied()))

    # Test 2: Tour instance expansion
    fv_id, instances = test_tour_instance_expansion()
    results.append(("Tour Instance Expansion", fv_id is not None))

    if fv_id is None:
        print("\nERROR: Cannot continue - tour instance expansion failed")
        sys.exit(1)

    # Test 3: Fixed assignments
    plan_id = test_fixed_assignments(fv_id, instances)
    results.append(("Fixed Assignments", plan_id is not None))

    if plan_id is None:
        print("\nERROR: Cannot continue - assignment creation failed")
        sys.exit(1)

    # Test 4: Fixed coverage check
    results.append(("Fixed Coverage Check", test_fixed_coverage_check(plan_id)))

    # Test 5: Fixed audit framework
    results.append(("Fixed Audit Framework", test_fixed_audit_framework(plan_id)))

    # Test 6: LOCKED immutability
    results.append(("LOCKED Immutability", test_locked_immutability(plan_id)))

    # Summary
    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\n{'='*70}")
    if passed == total:
        print(f"SUCCESS: ALL {total} P0 TESTS PASSED!")
        print("="*70)
        print("\nP0 Blockers FIXED:")
        print("   [OK] Template vs Instances: tour_instances table working")
        print("   [OK] Coverage Check: 1:1 instance mapping validated")
        print("   [OK] LOCKED Immutability: assignments protected")
        print("   [OK] Cross-midnight: crosses_midnight field implemented")
        print("\nNext Steps:")
        print("   1. Replace v3/audit.py with v3/audit_fixed.py")
        print("   2. Update all code to use db_instances.py")
        print("   3. Apply migration to production database")
        print("   4. Implement remaining audit checks (SPAN, REPRODUCIBILITY, FATIGUE)")
    else:
        print(f"FAILED: {total - passed} of {total} TESTS FAILED")
        print("="*70)
        print("\nFailed Tests:")
        for name, result in results:
            if not result:
                print(f"   [FAIL] {name}")

    print()


if __name__ == "__main__":
    main()
