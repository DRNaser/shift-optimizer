# =============================================================================
# SOLVEREIGN Routing Pack - Gate 4: Site/Depot Partitioning Tests
# =============================================================================
# Gate 4 Requirements:
# - scenario.site_id FK auf routing_depots
# - Lock-Key Query muss WHERE site_id = scenario.site_id enthalten
# - All vehicles must use depots with matching site_id
# =============================================================================

import sys
import unittest
import hashlib
from typing import Dict, List

sys.path.insert(0, ".")

from packs.routing.services.site_partitioning import (
    SitePartitioningService,
    SiteMismatchError,
    MissingSiteIdError,
    AdvisoryLockKey,
    SiteContext,
    validate_all_vehicles_site_match,
    generate_lock_key_sql,
)


class TestSitePartitioningService(unittest.TestCase):
    """Gate 4: Site/Depot Partitioning Tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = SitePartitioningService(strict_mode=True)
        self.service_lenient = SitePartitioningService(strict_mode=False)

    # =========================================================================
    # ADVISORY LOCK KEY TESTS
    # =========================================================================

    def test_advisory_lock_key_generation(self):
        """Test that advisory lock keys are deterministic."""
        print("\n" + "=" * 60)
        print("GATE 4: Advisory Lock Key Generation")
        print("=" * 60)

        key1 = AdvisoryLockKey(
            tenant_id=1,
            site_id="MM_BERLIN_01",
            scenario_id="550e8400-e29b-41d4-a716-446655440000"
        )
        key2 = AdvisoryLockKey(
            tenant_id=1,
            site_id="MM_BERLIN_01",
            scenario_id="550e8400-e29b-41d4-a716-446655440000"
        )

        hash1 = key1.to_hash()
        hash2 = key2.to_hash()

        print(f"    Lock Key 1: {key1}")
        print(f"    Hash 1: {hash1}")
        print(f"    Hash 2: {hash2}")

        self.assertEqual(hash1, hash2, "Same inputs must produce same hash")
        print(f"    [PASS] Same inputs produce identical hash")

    def test_advisory_lock_key_different_sites(self):
        """Test that different sites produce different lock keys."""
        print("\n" + "=" * 60)
        print("GATE 4: Different Sites = Different Lock Keys")
        print("=" * 60)

        key_berlin = AdvisoryLockKey(
            tenant_id=1,
            site_id="MM_BERLIN_01",
            scenario_id="550e8400-e29b-41d4-a716-446655440000"
        )
        key_munich = AdvisoryLockKey(
            tenant_id=1,
            site_id="MM_MUNICH_01",
            scenario_id="550e8400-e29b-41d4-a716-446655440000"
        )

        hash_berlin = key_berlin.to_hash()
        hash_munich = key_munich.to_hash()

        print(f"    Berlin site hash: {hash_berlin}")
        print(f"    Munich site hash: {hash_munich}")

        self.assertNotEqual(hash_berlin, hash_munich, "Different sites must produce different hashes")
        print(f"    [PASS] Different sites produce different lock keys")

    def test_advisory_lock_key_fits_bigint(self):
        """Test that lock key hash fits in PostgreSQL bigint."""
        print("\n" + "=" * 60)
        print("GATE 4: Lock Key Fits PostgreSQL BIGINT")
        print("=" * 60)

        # Test with various inputs
        test_cases = [
            ("tenant_1", "site_a", "uuid_1"),
            ("tenant_999999", "site_very_long_name_here", "uuid_long"),
            ("1", "MM_BERLIN_01", "550e8400-e29b-41d4-a716-446655440000"),
        ]

        BIGINT_MIN = -(2**63)
        BIGINT_MAX = 2**63 - 1

        for tenant_id, site_id, scenario_id in test_cases:
            key = AdvisoryLockKey(
                tenant_id=int(tenant_id.replace("tenant_", "")) if tenant_id.startswith("tenant_") else 1,
                site_id=site_id,
                scenario_id=scenario_id
            )
            hash_val = key.to_hash()

            self.assertGreaterEqual(hash_val, BIGINT_MIN, f"Hash {hash_val} below BIGINT_MIN")
            self.assertLessEqual(hash_val, BIGINT_MAX, f"Hash {hash_val} above BIGINT_MAX")

        print(f"    [PASS] All hashes fit in BIGINT range")

    # =========================================================================
    # SITE VALIDATION TESTS
    # =========================================================================

    def test_scenario_depot_match_success(self):
        """Test successful scenario-depot site_id match."""
        print("\n" + "=" * 60)
        print("GATE 4: Scenario-Depot Match (Success)")
        print("=" * 60)

        result = self.service.validate_scenario_depot_match(
            scenario_site_id="MM_BERLIN_01",
            depot_site_id="MM_BERLIN_01"
        )

        self.assertTrue(result)
        print(f"    [PASS] Matching site_ids allowed")

    def test_scenario_depot_match_fail_strict(self):
        """Test that mismatched site_ids raise error in strict mode."""
        print("\n" + "=" * 60)
        print("GATE 4: Scenario-Depot Mismatch (Strict Mode)")
        print("=" * 60)

        with self.assertRaises(SiteMismatchError) as ctx:
            self.service.validate_scenario_depot_match(
                scenario_site_id="MM_BERLIN_01",
                depot_site_id="MM_MUNICH_01"
            )

        print(f"    Error raised: {ctx.exception}")
        self.assertEqual(ctx.exception.scenario_site_id, "MM_BERLIN_01")
        self.assertEqual(ctx.exception.depot_site_id, "MM_MUNICH_01")
        print(f"    [PASS] Mismatched site_ids raise SiteMismatchError")

    def test_scenario_depot_match_fail_lenient(self):
        """Test that mismatched site_ids return False in lenient mode."""
        print("\n" + "=" * 60)
        print("GATE 4: Scenario-Depot Mismatch (Lenient Mode)")
        print("=" * 60)

        result = self.service_lenient.validate_scenario_depot_match(
            scenario_site_id="MM_BERLIN_01",
            depot_site_id="MM_MUNICH_01"
        )

        self.assertFalse(result)
        print(f"    [PASS] Mismatched site_ids return False (no exception)")

    def test_legacy_scenario_no_site_id(self):
        """Test that legacy scenarios (no site_id) allow any depot."""
        print("\n" + "=" * 60)
        print("GATE 4: Legacy Scenario (No site_id)")
        print("=" * 60)

        result = self.service.validate_scenario_depot_match(
            scenario_site_id=None,  # Legacy
            depot_site_id="MM_BERLIN_01"
        )

        self.assertTrue(result)
        print(f"    [PASS] Legacy scenarios (None site_id) allow any depot")

    # =========================================================================
    # VEHICLE VALIDATION TESTS
    # =========================================================================

    def test_vehicle_depots_match_success(self):
        """Test successful vehicle depot validation."""
        print("\n" + "=" * 60)
        print("GATE 4: Vehicle Depots Match")
        print("=" * 60)

        result = self.service.validate_vehicle_depots(
            scenario_site_id="MM_BERLIN_01",
            start_depot_site_id="MM_BERLIN_01",
            end_depot_site_id="MM_BERLIN_01"
        )

        self.assertTrue(result)
        print(f"    [PASS] Vehicle with matching depots allowed")

    def test_vehicle_depots_mismatch_start(self):
        """Test that vehicle with wrong start depot is rejected."""
        print("\n" + "=" * 60)
        print("GATE 4: Vehicle Start Depot Mismatch")
        print("=" * 60)

        with self.assertRaises(SiteMismatchError) as ctx:
            self.service.validate_vehicle_depots(
                scenario_site_id="MM_BERLIN_01",
                start_depot_site_id="MM_MUNICH_01",  # Wrong!
                end_depot_site_id="MM_BERLIN_01"
            )

        print(f"    Error: {ctx.exception}")
        print(f"    [PASS] Vehicle with wrong start depot rejected")

    def test_vehicle_depots_mismatch_end(self):
        """Test that vehicle with wrong end depot is rejected."""
        print("\n" + "=" * 60)
        print("GATE 4: Vehicle End Depot Mismatch")
        print("=" * 60)

        with self.assertRaises(SiteMismatchError) as ctx:
            self.service.validate_vehicle_depots(
                scenario_site_id="MM_BERLIN_01",
                start_depot_site_id="MM_BERLIN_01",
                end_depot_site_id="MM_MUNICH_01"  # Wrong!
            )

        print(f"    Error: {ctx.exception}")
        print(f"    [PASS] Vehicle with wrong end depot rejected")

    # =========================================================================
    # BULK VEHICLE VALIDATION TESTS
    # =========================================================================

    def test_validate_all_vehicles_success(self):
        """Test bulk validation of vehicles with correct depots."""
        print("\n" + "=" * 60)
        print("GATE 4: Bulk Vehicle Validation (Success)")
        print("=" * 60)

        depots = {
            "depot_1": {"id": "depot_1", "site_id": "MM_BERLIN_01"},
            "depot_2": {"id": "depot_2", "site_id": "MM_BERLIN_01"},
        }

        vehicles = [
            {"id": "v1", "start_depot_id": "depot_1", "end_depot_id": "depot_2"},
            {"id": "v2", "start_depot_id": "depot_1", "end_depot_id": "depot_1"},
            {"id": "v3", "start_depot_id": "depot_2", "end_depot_id": "depot_1"},
        ]

        errors = validate_all_vehicles_site_match(
            scenario_site_id="MM_BERLIN_01",
            vehicles=vehicles,
            depots=depots
        )

        print(f"    Vehicles validated: {len(vehicles)}")
        print(f"    Errors: {len(errors)}")

        self.assertEqual(len(errors), 0)
        print(f"    [PASS] All vehicles valid")

    def test_validate_all_vehicles_with_errors(self):
        """Test bulk validation with mixed valid/invalid vehicles."""
        print("\n" + "=" * 60)
        print("GATE 4: Bulk Vehicle Validation (With Errors)")
        print("=" * 60)

        depots = {
            "depot_berlin": {"id": "depot_berlin", "site_id": "MM_BERLIN_01"},
            "depot_munich": {"id": "depot_munich", "site_id": "MM_MUNICH_01"},
        }

        vehicles = [
            {"id": "v1", "start_depot_id": "depot_berlin", "end_depot_id": "depot_berlin"},  # OK
            {"id": "v2", "start_depot_id": "depot_munich", "end_depot_id": "depot_munich"},  # Wrong site!
            {"id": "v3", "start_depot_id": "depot_berlin", "end_depot_id": "depot_munich"},  # End wrong!
        ]

        errors = validate_all_vehicles_site_match(
            scenario_site_id="MM_BERLIN_01",
            vehicles=vehicles,
            depots=depots
        )

        print(f"    Vehicles validated: {len(vehicles)}")
        print(f"    Errors found: {len(errors)}")
        for err in errors:
            print(f"      - {err}")

        # v2 has 2 errors (start + end), v3 has 1 error (end)
        self.assertEqual(len(errors), 3)
        print(f"    [PASS] Detected all site_id violations")

    # =========================================================================
    # SITE CONTEXT TESTS
    # =========================================================================

    def test_site_context_creation(self):
        """Test SiteContext creation and partition key."""
        print("\n" + "=" * 60)
        print("GATE 4: Site Context Creation")
        print("=" * 60)

        context = self.service.create_site_context(
            tenant_id=1,
            site_id="MM_BERLIN_01",
            depot_ids=["depot_1", "depot_2", "depot_3"]
        )

        print(f"    Partition key: {context.partition_key}")
        print(f"    Depot count: {len(context.depot_ids)}")

        self.assertEqual(context.tenant_id, 1)
        self.assertEqual(context.site_id, "MM_BERLIN_01")
        self.assertEqual(len(context.depot_ids), 3)
        self.assertEqual(context.partition_key, "tenant:1:site:MM_BERLIN_01")
        print(f"    [PASS] SiteContext created correctly")

    def test_filter_depots_by_site(self):
        """Test filtering depots by site_id."""
        print("\n" + "=" * 60)
        print("GATE 4: Filter Depots by Site")
        print("=" * 60)

        depots = [
            {"id": "d1", "site_id": "MM_BERLIN_01", "name": "Berlin West"},
            {"id": "d2", "site_id": "MM_BERLIN_01", "name": "Berlin East"},
            {"id": "d3", "site_id": "MM_MUNICH_01", "name": "Munich Central"},
            {"id": "d4", "site_id": "MM_HAMBURG_01", "name": "Hamburg Port"},
        ]

        berlin_depots = self.service.filter_depots_by_site(depots, "MM_BERLIN_01")
        munich_depots = self.service.filter_depots_by_site(depots, "MM_MUNICH_01")

        print(f"    Total depots: {len(depots)}")
        print(f"    Berlin depots: {len(berlin_depots)}")
        print(f"    Munich depots: {len(munich_depots)}")

        self.assertEqual(len(berlin_depots), 2)
        self.assertEqual(len(munich_depots), 1)
        print(f"    [PASS] Depots filtered correctly by site")

    # =========================================================================
    # REQUIRED SITE_ID TESTS
    # =========================================================================

    def test_new_scenario_requires_site_id(self):
        """Test that new scenarios require site_id in strict mode."""
        print("\n" + "=" * 60)
        print("GATE 4: New Scenario Requires site_id")
        print("=" * 60)

        with self.assertRaises(MissingSiteIdError):
            self.service.validate_scenario_site_required(None)

        print(f"    [PASS] Missing site_id raises MissingSiteIdError")

    def test_new_scenario_with_site_id(self):
        """Test that scenarios with site_id pass validation."""
        print("\n" + "=" * 60)
        print("GATE 4: Scenario with site_id Passes")
        print("=" * 60)

        # Should not raise
        self.service.validate_scenario_site_required("MM_BERLIN_01")

        print(f"    [PASS] Scenario with site_id accepted")

    # =========================================================================
    # SQL HELPER TESTS
    # =========================================================================

    def test_generate_lock_key_sql(self):
        """Test SQL lock key generation helper."""
        print("\n" + "=" * 60)
        print("GATE 4: SQL Lock Key Generation")
        print("=" * 60)

        lock_key_sql = generate_lock_key_sql(
            tenant_id=1,
            site_id="MM_BERLIN_01",
            scenario_id="550e8400-e29b-41d4-a716-446655440000"
        )

        print(f"    Generated SQL key: {lock_key_sql}")

        # Should be a valid integer string
        int_val = int(lock_key_sql)
        print(f"    Integer value: {int_val}")

        # Verify it matches AdvisoryLockKey
        key = AdvisoryLockKey(1, "MM_BERLIN_01", "550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(int_val, key.to_hash())
        print(f"    [PASS] SQL helper matches AdvisoryLockKey")


class TestGate4Integration(unittest.TestCase):
    """Gate 4: Integration tests simulating real scenarios."""

    def test_multi_depot_scenario_site_enforcement(self):
        """
        Integration test: Create scenario with multiple depots.
        All depots must match scenario's site_id.
        """
        print("\n" + "=" * 70)
        print("GATE 4 INTEGRATION: Multi-Depot Scenario Site Enforcement")
        print("=" * 70)

        service = SitePartitioningService(strict_mode=True)

        # Scenario for Berlin site
        scenario = {
            "id": "scenario_001",
            "tenant_id": 1,
            "site_id": "MM_BERLIN_01",
            "plan_date": "2026-01-07",
        }

        # Depots - some Berlin, some Munich
        depots = {
            "depot_berlin_west": {"id": "depot_berlin_west", "site_id": "MM_BERLIN_01"},
            "depot_berlin_east": {"id": "depot_berlin_east", "site_id": "MM_BERLIN_01"},
            "depot_munich": {"id": "depot_munich", "site_id": "MM_MUNICH_01"},
        }

        # Vehicles - all should use Berlin depots
        vehicles = [
            {"id": "v1", "start_depot_id": "depot_berlin_west", "end_depot_id": "depot_berlin_east"},
            {"id": "v2", "start_depot_id": "depot_berlin_east", "end_depot_id": "depot_berlin_west"},
        ]

        # 1. Validate scenario has site_id
        service.validate_scenario_site_required(scenario["site_id"])
        print(f"    [1] Scenario has required site_id: {scenario['site_id']}")

        # 2. Filter depots to site
        site_depots = service.filter_depots_by_site(list(depots.values()), scenario["site_id"])
        print(f"    [2] Filtered depots: {len(site_depots)} of {len(depots)}")

        # 3. Validate all vehicles use correct depots
        errors = validate_all_vehicles_site_match(
            scenario_site_id=scenario["site_id"],
            vehicles=vehicles,
            depots=depots
        )
        print(f"    [3] Vehicle validation errors: {len(errors)}")
        self.assertEqual(len(errors), 0)

        # 4. Generate advisory lock key
        lock_key = service.get_advisory_lock_key(
            tenant_id=scenario["tenant_id"],
            site_id=scenario["site_id"],
            scenario_id=scenario["id"]
        )
        print(f"    [4] Advisory lock key: {lock_key.to_hash()}")

        print("\n" + "=" * 70)
        print("GATE 4 PASSED: Multi-depot scenario correctly enforces site_id")
        print("=" * 70)

    def test_cross_site_vehicle_rejected(self):
        """
        Integration test: Vehicle using depot from different site is rejected.
        """
        print("\n" + "=" * 70)
        print("GATE 4 INTEGRATION: Cross-Site Vehicle Rejection")
        print("=" * 70)

        service = SitePartitioningService(strict_mode=True)

        # Scenario for Berlin
        scenario_site_id = "MM_BERLIN_01"

        # Depots
        depots = {
            "depot_berlin": {"id": "depot_berlin", "site_id": "MM_BERLIN_01"},
            "depot_munich": {"id": "depot_munich", "site_id": "MM_MUNICH_01"},
        }

        # Vehicle tries to use Munich depot in Berlin scenario
        vehicles = [
            {"id": "v_bad", "start_depot_id": "depot_munich", "end_depot_id": "depot_berlin"},
        ]

        errors = validate_all_vehicles_site_match(
            scenario_site_id=scenario_site_id,
            vehicles=vehicles,
            depots=depots
        )

        print(f"    Errors detected: {len(errors)}")
        for err in errors:
            print(f"      - {err}")

        self.assertGreater(len(errors), 0, "Cross-site vehicle should be rejected")

        print("\n" + "=" * 70)
        print("GATE 4 PASSED: Cross-site vehicle correctly rejected")
        print("=" * 70)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Gate 4: Site/Depot Partitioning Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
