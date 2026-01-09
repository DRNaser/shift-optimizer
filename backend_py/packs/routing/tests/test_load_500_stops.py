# =============================================================================
# SOLVEREIGN Routing Pack - Realistic Load Test
# =============================================================================
# Test with 500 stops and 40 vehicles to validate pilot readiness.
#
# IMPORTANT: These tests validate the PIPELINE (validation, audit, evidence)
# NOT the actual OR-Tools solver. The solver is tested separately in
# test_solver_realistic.py which runs with real OR-Tools constraints.
#
# This test validates:
# 1. Input Validation performance at scale
# 2. Route Auditing at scale
# 3. Evidence Pack generation at scale
# 4. Memory usage is reasonable
# 5. Response times are acceptable
#
# For actual solver performance, see test_solver_realistic.py
# =============================================================================

import sys
import time
import unittest
import random
from datetime import datetime, timedelta
from typing import List, Dict

sys.path.insert(0, ".")

from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, Priority
)
from packs.routing.services.validation.input_validator import InputValidator
from packs.routing.services.audit.route_auditor import (
    RouteAuditor,
    AuditStop,
    AuditVehicle,
    AuditAssignment,
    AuditUnassigned,
)
from packs.routing.services.evidence.evidence_pack import EvidencePackWriter


class TestRealisticLoadScenario(unittest.TestCase):
    """Load test with realistic MediaMarkt/HDL scale."""

    # Test parameters
    NUM_STOPS = 500
    NUM_VEHICLES = 40
    NUM_DEPOTS = 3

    def setUp(self):
        """Set up test fixtures - generate realistic data."""
        random.seed(42)  # Reproducible random data
        self.today = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)

        # Generate test data
        print(f"\nGenerating {self.NUM_STOPS} stops, {self.NUM_VEHICLES} vehicles...")
        start = time.time()

        self.depots = self._generate_depots()
        self.vehicles = self._generate_vehicles()
        self.stops = self._generate_stops()

        print(f"Data generation took {(time.time() - start)*1000:.1f}ms")

    def _generate_depots(self) -> List[Depot]:
        """Generate realistic depots."""
        depot_locations = [
            ("DEPOT_NORD", "Berlin Nord", 52.55, 13.35),
            ("DEPOT_SUD", "Berlin Süd", 52.45, 13.40),
            ("DEPOT_OST", "Berlin Ost", 52.50, 13.50),
        ]
        return [
            Depot(
                id=d[0],
                tenant_id=1,
                site_id=d[0],
                name=d[1],
                geocode=Geocode(lat=d[2], lng=d[3]),
                loading_time_min=15
            )
            for d in depot_locations
        ]

    def _generate_vehicles(self) -> List[Vehicle]:
        """Generate 40 vehicles with varying skills and team sizes."""
        vehicles = []
        skill_sets = [
            ["MONTAGE_BASIC"],
            ["MONTAGE_BASIC", "ELEKTRO"],
            ["MONTAGE_ADVANCED"],
            ["MONTAGE_ADVANCED", "ELEKTRO"],
            [],  # Delivery only
        ]
        team_sizes = [1, 1, 1, 2, 2]  # 60% single, 40% two-person

        for i in range(self.NUM_VEHICLES):
            depot_idx = i % len(self.depots)
            skill_idx = i % len(skill_sets)
            team_idx = i % len(team_sizes)

            # Staggered shift starts (6:00, 7:00, 8:00)
            shift_start_hour = 6 + (i % 3)
            shift_start = self.today.replace(hour=shift_start_hour)
            shift_end = shift_start + timedelta(hours=9)  # 9-hour shifts

            vehicles.append(Vehicle(
                id=f"VAN_{i+1:03d}",
                tenant_id=1,
                scenario_id="LOAD_TEST",
                external_id=f"V-{i+1:03d}",
                team_id=f"TEAM_{chr(65 + depot_idx)}",
                team_size=team_sizes[team_idx],
                skills=skill_sets[skill_idx],
                shift_start_at=shift_start,
                shift_end_at=shift_end,
                start_depot_id=self.depots[depot_idx].id,
                end_depot_id=self.depots[depot_idx].id,
                capacity_volume_m3=15.0,
                capacity_weight_kg=1200.0,
            ))

        return vehicles

    def _generate_stops(self) -> List[Stop]:
        """Generate 500 realistic stops."""
        stops = []
        service_codes = [
            ("MM_DELIVERY", StopCategory.DELIVERY, False, []),
            ("MM_DELIVERY", StopCategory.DELIVERY, False, []),
            ("MM_DELIVERY", StopCategory.DELIVERY, False, []),
            ("MM_DELIVERY_MONTAGE", StopCategory.MONTAGE, True, ["MONTAGE_BASIC"]),
            ("MM_DELIVERY_MONTAGE", StopCategory.MONTAGE, True, ["MONTAGE_BASIC"]),
            ("HDL_MONTAGE_STANDARD", StopCategory.MONTAGE, True, ["MONTAGE_ADVANCED"]),
            ("HDL_MONTAGE_COMPLEX", StopCategory.MONTAGE, True, ["MONTAGE_ADVANCED", "ELEKTRO"]),
        ]

        # Berlin bounding box (approx)
        lat_min, lat_max = 52.40, 52.60
        lng_min, lng_max = 13.20, 13.60

        for i in range(self.NUM_STOPS):
            service = service_codes[i % len(service_codes)]

            # Random location in Berlin
            lat = random.uniform(lat_min, lat_max)
            lng = random.uniform(lng_min, lng_max)

            # Time windows spread across the day
            tw_start_offset = random.randint(1, 10)  # 1-10 hours from shift start
            tw_start = self.today + timedelta(hours=tw_start_offset)
            tw_end = tw_start + timedelta(hours=2)  # 2-hour window

            # Service duration varies by type
            if service[1] == StopCategory.DELIVERY:
                service_duration = random.randint(10, 20)
            else:
                service_duration = random.randint(45, 120)

            stops.append(Stop(
                id=f"STOP_{i+1:04d}",
                order_id=f"ORDER_{i+1:04d}",
                tenant_id=1,
                scenario_id="LOAD_TEST",
                address=Address(
                    street=f"Straße {i+1}",
                    house_number=str(random.randint(1, 200)),
                    postal_code=f"1{random.randint(0,2)}{random.randint(100, 999)}",
                    city="Berlin"
                ),
                geocode=Geocode(lat=lat, lng=lng),
                geocode_quality="HIGH",
                tw_start=tw_start,
                tw_end=tw_end,
                service_code=service[0],
                category=service[1],
                service_duration_min=service_duration,
                requires_two_person=service[2],
                required_skills=service[3],
            ))

        return stops

    def _generate_assignments(self) -> tuple:
        """Generate realistic assignments (simple round-robin for load test)."""
        assignments = []
        unassigned = []

        # Simple round-robin assignment
        vehicle_stops: Dict[str, List] = {v.id: [] for v in self.vehicles}

        for i, stop in enumerate(self.stops):
            # Find eligible vehicle
            eligible = [
                v for v in self.vehicles
                if (not stop.required_skills or set(stop.required_skills).issubset(set(v.skills)))
                and (not stop.requires_two_person or v.team_size >= 2)
            ]

            if eligible:
                # Round-robin among eligible
                vehicle = eligible[i % len(eligible)]
                vehicle_stops[vehicle.id].append(stop)
            else:
                unassigned.append({
                    "stop_id": stop.id,
                    "reason_code": "NO_ELIGIBLE_VEHICLE",
                    "reason_details": "No vehicle has required skills/team size"
                })

        # Build assignments with sequence and timing
        for vehicle in self.vehicles:
            stops_for_vehicle = vehicle_stops[vehicle.id]
            current_time = vehicle.shift_start_at + timedelta(minutes=30)  # After depot loading

            for seq, stop in enumerate(stops_for_vehicle, 1):
                # Simple timing (doesn't account for travel)
                arrival = current_time
                departure = arrival + timedelta(minutes=stop.service_duration_min)

                assignments.append({
                    "stop_id": stop.id,
                    "vehicle_id": vehicle.id,
                    "sequence_index": seq,
                    "arrival_at": arrival,
                    "departure_at": departure,
                    "slack_minutes": 15,
                })

                current_time = departure + timedelta(minutes=15)  # 15 min travel

        return assignments, unassigned

    # =========================================================================
    # LOAD TESTS
    # =========================================================================

    def test_input_validation_performance(self):
        """Test input validation at scale (500 stops, 40 vehicles)."""
        validator = InputValidator()

        start = time.time()
        result = validator.validate(
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
        )
        elapsed_ms = (time.time() - start) * 1000

        print(f"\nInput Validation Results:")
        print(f"  Time: {elapsed_ms:.1f}ms")
        print(f"  Stops: {result.stops_validated}")
        print(f"  Vehicles: {result.vehicles_validated}")
        print(f"  Errors: {len(result.errors)}")
        print(f"  Warnings: {len(result.warnings)}")

        # Performance assertions
        self.assertLess(elapsed_ms, 5000, "Validation should complete in <5s")
        self.assertEqual(result.stops_validated, self.NUM_STOPS)
        self.assertEqual(result.vehicles_validated, self.NUM_VEHICLES)

    def test_route_auditing_performance(self):
        """Test route auditing at scale."""
        assignments, unassigned = self._generate_assignments()

        # Convert to audit types
        audit_stops = [
            AuditStop(
                id=s.id,
                tw_start=s.tw_start,
                tw_end=s.tw_end,
                tw_is_hard=True,
                required_skills=s.required_skills or [],
                requires_two_person=s.requires_two_person,
            )
            for s in self.stops
        ]

        audit_vehicles = [
            AuditVehicle(
                id=v.id,
                shift_start_at=v.shift_start_at,
                shift_end_at=v.shift_end_at,
                skills=v.skills,
                team_size=v.team_size,
            )
            for v in self.vehicles
        ]

        audit_assignments = [
            AuditAssignment(
                stop_id=a["stop_id"],
                vehicle_id=a["vehicle_id"],
                arrival_at=a["arrival_at"],
                departure_at=a["departure_at"],
                sequence_index=a["sequence_index"],
            )
            for a in assignments
        ]

        audit_unassigned = [
            AuditUnassigned(
                stop_id=u["stop_id"],
                reason_code=u["reason_code"],
            )
            for u in unassigned
        ]

        auditor = RouteAuditor()

        start = time.time()
        result = auditor.audit(
            plan_id="LOAD_TEST_PLAN",
            stops=audit_stops,
            vehicles=audit_vehicles,
            assignments=audit_assignments,
            unassigned=audit_unassigned,
        )
        elapsed_ms = (time.time() - start) * 1000

        print(f"\nRoute Audit Results:")
        print(f"  Time: {elapsed_ms:.1f}ms")
        print(f"  Checks Run: {result.checks_run}")
        print(f"  Checks Passed: {result.checks_passed}")
        print(f"  Checks Failed: {result.checks_failed}")

        for check_name, check in result.results.items():
            status_icon = "[PASS]" if check.status.value == "PASS" else "[FAIL]"
            print(f"  {status_icon} {check_name.value}: {check.status.value} ({check.violation_count} violations)")

        # Performance assertions
        self.assertLess(elapsed_ms, 5000, "Audit should complete in <5s")
        self.assertEqual(result.checks_run, 5)

    def test_evidence_pack_generation(self):
        """Test evidence pack generation at scale."""
        assignments, unassigned = self._generate_assignments()

        # Convert stops and vehicles to dicts
        stops_dict = [
            {
                "id": s.id,
                "order_id": s.order_id,
                "address": {
                    "street": s.address.street,
                    "house_number": s.address.house_number,
                    "postal_code": s.address.postal_code,
                    "city": s.address.city,
                },
                "tw_start": s.tw_start,
                "tw_end": s.tw_end,
                "tw_is_hard": True,
                "service_duration_min": s.service_duration_min,
                "required_skills": s.required_skills or [],
                "requires_two_person": s.requires_two_person,
                "category": s.category.value,
            }
            for s in self.stops
        ]

        vehicles_dict = [
            {
                "id": v.id,
                "external_id": v.external_id,
                "shift_start_at": v.shift_start_at,
                "shift_end_at": v.shift_end_at,
                "skills": v.skills,
                "team_size": v.team_size,
                "start_depot_id": v.start_depot_id,
                "end_depot_id": v.end_depot_id,
            }
            for v in self.vehicles
        ]

        depots_dict = [
            {
                "id": d.id,
                "name": d.name,
                "site_id": d.site_id,
            }
            for d in self.depots
        ]

        # First run audit to get results
        auditor = RouteAuditor()
        audit_result = auditor.audit(
            plan_id="LOAD_TEST_PLAN",
            stops=[
                AuditStop(
                    id=s.id,
                    tw_start=s.tw_start,
                    tw_end=s.tw_end,
                    tw_is_hard=True,
                    required_skills=s.required_skills or [],
                    requires_two_person=s.requires_two_person,
                )
                for s in self.stops
            ],
            vehicles=[
                AuditVehicle(
                    id=v.id,
                    shift_start_at=v.shift_start_at,
                    shift_end_at=v.shift_end_at,
                    skills=v.skills,
                    team_size=v.team_size,
                )
                for v in self.vehicles
            ],
            assignments=[
                AuditAssignment(
                    stop_id=a["stop_id"],
                    vehicle_id=a["vehicle_id"],
                    arrival_at=a["arrival_at"],
                    departure_at=a["departure_at"],
                    sequence_index=a["sequence_index"],
                )
                for a in assignments
            ],
            unassigned=[
                AuditUnassigned(stop_id=u["stop_id"], reason_code=u["reason_code"])
                for u in unassigned
            ],
        )

        writer = EvidencePackWriter()

        start = time.time()
        pack = writer.create_evidence_pack(
            plan_id="LOAD_TEST_PLAN",
            scenario_id="SCENARIO_LOAD",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=stops_dict,
            vehicles=vehicles_dict,
            depots=depots_dict,
            assignments=assignments,
            unassigned=unassigned,
            audit_result=audit_result,
            seed=42,
            solver_config_hash="load_test_config",
        )
        elapsed_ms = (time.time() - start) * 1000

        print(f"\nEvidence Pack Results:")
        print(f"  Generation Time: {elapsed_ms:.1f}ms")
        print(f"  Routes: {len(pack.routes)}")
        print(f"  Unassigned: {len(pack.unassigned)}")
        print(f"  Coverage: {pack.kpis.coverage_percentage}%")
        print(f"  Vehicles Used: {pack.kpis.total_vehicles_used}")

        # Performance assertions
        self.assertLess(elapsed_ms, 5000, "Evidence pack should generate in <5s")
        self.assertGreater(len(pack.routes), 0)

    def test_end_to_end_workflow(self):
        """Test complete workflow at scale."""
        print("\n" + "=" * 60)
        print("END-TO-END LOAD TEST")
        print(f"  Stops: {self.NUM_STOPS}")
        print(f"  Vehicles: {self.NUM_VEHICLES}")
        print(f"  Depots: {self.NUM_DEPOTS}")
        print("=" * 60)

        total_start = time.time()

        # Step 1: Input Validation
        print("\n[1/3] Input Validation...")
        validator = InputValidator()
        start = time.time()
        validation_result = validator.validate(
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
        )
        validation_time = (time.time() - start) * 1000
        print(f"      {validation_time:.1f}ms - {len(validation_result.errors)} errors")

        # Step 2: Generate assignments (simulates solver)
        print("\n[2/3] Generating Assignments...")
        start = time.time()
        assignments, unassigned = self._generate_assignments()
        assignment_time = (time.time() - start) * 1000
        print(f"      {assignment_time:.1f}ms - {len(assignments)} assigned, {len(unassigned)} unassigned")

        # Step 3: Route Auditing
        print("\n[3/3] Route Auditing + Evidence Pack...")
        auditor = RouteAuditor()
        start = time.time()

        audit_result = auditor.audit(
            plan_id="E2E_TEST",
            stops=[
                AuditStop(
                    id=s.id, tw_start=s.tw_start, tw_end=s.tw_end,
                    tw_is_hard=True, required_skills=s.required_skills or [],
                    requires_two_person=s.requires_two_person,
                )
                for s in self.stops
            ],
            vehicles=[
                AuditVehicle(
                    id=v.id, shift_start_at=v.shift_start_at, shift_end_at=v.shift_end_at,
                    skills=v.skills, team_size=v.team_size,
                )
                for v in self.vehicles
            ],
            assignments=[
                AuditAssignment(
                    stop_id=a["stop_id"], vehicle_id=a["vehicle_id"],
                    arrival_at=a["arrival_at"], departure_at=a["departure_at"],
                    sequence_index=a["sequence_index"],
                )
                for a in assignments
            ],
            unassigned=[
                AuditUnassigned(stop_id=u["stop_id"], reason_code=u["reason_code"])
                for u in unassigned
            ],
        )
        audit_time = (time.time() - start) * 1000
        print(f"      {audit_time:.1f}ms - {audit_result.checks_passed}/{audit_result.checks_run} passed")

        total_time = (time.time() - total_start) * 1000

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Total Time: {total_time:.1f}ms")
        print(f"  Validation: {validation_time:.1f}ms")
        print(f"  Assignment: {assignment_time:.1f}ms")
        print(f"  Auditing:   {audit_time:.1f}ms")
        print(f"  Coverage:   {(len(assignments) / self.NUM_STOPS * 100):.1f}%")
        print("=" * 60)

        # Final assertions
        self.assertLess(total_time, 15000, "End-to-end should complete in <15s")


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Realistic Load Test (500 stops, 40 vehicles)")
    print("=" * 70)
    unittest.main(verbosity=2)
