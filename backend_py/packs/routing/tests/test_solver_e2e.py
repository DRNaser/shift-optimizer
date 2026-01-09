# =============================================================================
# SOLVEREIGN Routing Pack - End-to-End Solver Test
# =============================================================================
# Full integration test of the VRPTW solver with realistic scenario.
#
# Run with: python packs/routing/tests/test_solver_e2e.py
# =============================================================================

import sys
from datetime import datetime, timedelta
from typing import List
import time

# Add parent path for imports
sys.path.insert(0, ".")

from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, Priority, SolverConfig
)
from packs.routing.services.travel_time.provider import TravelTimeProvider, TravelTimeResult, MatrixResult
from packs.routing.services.solver.vrptw_solver import VRPTWSolver, SolverResult
from packs.routing.policies.job_templates import get_template_for_service_code


# =============================================================================
# MOCK TRAVEL TIME PROVIDER (Haversine-based)
# =============================================================================

class HaversineTravelTimeProvider(TravelTimeProvider):
    """Travel time provider using Haversine distance."""

    def __init__(self, average_speed_kmh: float = 30.0):
        self.average_speed_kmh = average_speed_kmh

    @property
    def provider_name(self) -> str:
        return "haversine"

    def health_check(self) -> bool:
        return True

    def get_travel_time(self, origin, destination) -> TravelTimeResult:
        import math

        lat1, lng1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lng2 = math.radians(destination[0]), math.radians(destination[1])

        dlat = lat2 - lat1
        dlng = lng2 - lng1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        R = 6371.0  # Earth radius in km

        distance_km = R * c
        distance_m = int(distance_km * 1000)

        # Time = Distance / Speed
        hours = distance_km / self.average_speed_kmh
        duration_seconds = int(hours * 3600)

        return TravelTimeResult(
            origin=origin,
            destination=destination,
            duration_seconds=duration_seconds,
            distance_meters=distance_m
        )

    def get_matrix(self, locations) -> MatrixResult:
        n = len(locations)
        time_matrix = [[0] * n for _ in range(n)]
        distance_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i != j:
                    result = self.get_travel_time(locations[i], locations[j])
                    time_matrix[i][j] = result.duration_seconds
                    distance_matrix[i][j] = result.distance_meters

        return MatrixResult(
            locations=locations,
            time_matrix=time_matrix,
            distance_matrix=distance_matrix
        )


# =============================================================================
# TEST SCENARIO: Berlin MediaMarkt Delivery
# =============================================================================

def create_berlin_scenario():
    """
    Create a realistic test scenario: Berlin MediaMarkt Delivery.

    - 1 Depot (Berlin Mitte)
    - 10 Stops across Berlin
    - 3 Vehicles with different capabilities
    - Mix of delivery and montage stops
    """
    # Reference time: today 8:00
    today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    # ==========================================================================
    # DEPOT
    # ==========================================================================
    depot = Depot(
        id="DEPOT_BERLIN",
        tenant_id=1,
        site_id="MM_BERLIN_MITTE",
        name="MediaMarkt Berlin Mitte",
        geocode=Geocode(lat=52.5200, lng=13.4050),  # Berlin Mitte
        loading_time_min=15
    )

    # ==========================================================================
    # STOPS (10 deliveries across Berlin)
    # ==========================================================================
    stops = []

    # Berlin locations (approximate coordinates)
    berlin_locations = [
        ("Charlottenburg", 52.5167, 13.3000, "MM_DELIVERY", False, []),
        ("Kreuzberg", 52.4970, 13.4030, "MM_DELIVERY", False, []),
        ("Prenzlauer Berg", 52.5389, 13.4244, "MM_DELIVERY_MONTAGE", True, ["MONTAGE_BASIC"]),
        ("Friedrichshain", 52.5150, 13.4540, "MM_DELIVERY", False, []),
        ("Neukölln", 52.4810, 13.4350, "MM_DELIVERY_LARGE", True, ["HEAVY_LIFT"]),
        ("Tempelhof", 52.4700, 13.3850, "MM_DELIVERY", False, []),
        ("Schöneberg", 52.4850, 13.3500, "MM_DELIVERY_MONTAGE", True, ["MONTAGE_BASIC"]),
        ("Wedding", 52.5500, 13.3600, "MM_DELIVERY", False, []),
        ("Spandau", 52.5350, 13.2000, "MM_DELIVERY", False, []),
        ("Pankow", 52.5700, 13.4000, "MM_DELIVERY", False, []),
    ]

    for i, (name, lat, lng, service_code, two_person, skills) in enumerate(berlin_locations):
        template = get_template_for_service_code(service_code)

        # Time windows: staggered 2-hour windows starting from 9:00
        tw_start = today + timedelta(hours=1 + (i % 5))  # 9:00 - 13:00
        tw_end = tw_start + timedelta(hours=2)

        stop = Stop(
            id=f"STOP_{i+1:02d}",
            order_id=f"ORDER_{i+1:03d}",
            tenant_id=1,
            scenario_id="TEST_SCENARIO",
            address=Address(
                street=f"{name} Strasse",
                house_number=str(10 + i),
                postal_code=f"1{i+1:04d}",
                city="Berlin"
            ),
            geocode=Geocode(lat=lat, lng=lng),
            geocode_quality=None,
            tw_start=tw_start,
            tw_end=tw_end,
            service_code=service_code,
            category=StopCategory.MONTAGE if "MONTAGE" in service_code else StopCategory.DELIVERY,
            service_duration_min=template.base_service_min,
            tw_is_hard=True,
            requires_two_person=two_person,
            required_skills=skills,
            volume_m3=0.5,
            weight_kg=25.0
        )
        stops.append(stop)

    # ==========================================================================
    # VEHICLES (3 with different capabilities)
    # ==========================================================================
    vehicles = []

    # Vehicle 1: Standard delivery van (1 person)
    vehicles.append(Vehicle(
        id="VAN_01",
        tenant_id=1,
        scenario_id="TEST_SCENARIO",
        external_id="B-MM-101",
        team_id="TEAM_A",
        team_size=1,
        skills=[],
        shift_start_at=today,
        shift_end_at=today + timedelta(hours=8),
        start_depot_id="DEPOT_BERLIN",
        end_depot_id="DEPOT_BERLIN",
        capacity_volume_m3=10.0,
        capacity_weight_kg=800.0
    ))

    # Vehicle 2: 2-person team with montage skills
    vehicles.append(Vehicle(
        id="VAN_02",
        tenant_id=1,
        scenario_id="TEST_SCENARIO",
        external_id="B-MM-102",
        team_id="TEAM_B",
        team_size=2,
        skills=["MONTAGE_BASIC", "HEAVY_LIFT"],
        shift_start_at=today,
        shift_end_at=today + timedelta(hours=8),
        start_depot_id="DEPOT_BERLIN",
        end_depot_id="DEPOT_BERLIN",
        capacity_volume_m3=15.0,
        capacity_weight_kg=1200.0
    ))

    # Vehicle 3: Standard delivery van (1 person)
    vehicles.append(Vehicle(
        id="VAN_03",
        tenant_id=1,
        scenario_id="TEST_SCENARIO",
        external_id="B-MM-103",
        team_id="TEAM_C",
        team_size=1,
        skills=[],
        shift_start_at=today,
        shift_end_at=today + timedelta(hours=8),
        start_depot_id="DEPOT_BERLIN",
        end_depot_id="DEPOT_BERLIN",
        capacity_volume_m3=10.0,
        capacity_weight_kg=800.0
    ))

    return depot, stops, vehicles


# =============================================================================
# RUN SOLVER TEST
# =============================================================================

def run_solver_test():
    """Run the end-to-end solver test."""

    print("=" * 70)
    print("SOLVEREIGN Routing Pack - End-to-End Solver Test")
    print("=" * 70)
    print()

    # Create scenario
    print("[1] Creating test scenario: Berlin MediaMarkt Delivery")
    depot, stops, vehicles = create_berlin_scenario()

    print(f"    - Depot: {depot.name}")
    print(f"    - Stops: {len(stops)}")
    print(f"    - Vehicles: {len(vehicles)}")

    # Show stop details
    print()
    print("    Stops:")
    for s in stops:
        skills_str = f" [{', '.join(s.required_skills)}]" if s.required_skills else ""
        two_person_str = " (2-Mann)" if s.requires_two_person else ""
        print(f"      - {s.id}: {s.service_code}{two_person_str}{skills_str}")

    print()
    print("    Vehicles:")
    for v in vehicles:
        skills_str = f" [{', '.join(v.skills)}]" if v.skills else ""
        print(f"      - {v.id}: Team={v.team_size}{skills_str}")

    # Create travel time provider
    print()
    print("[2] Creating travel time provider (Haversine)")
    travel_provider = HaversineTravelTimeProvider(average_speed_kmh=30.0)

    # Create solver config
    print()
    print("[3] Creating solver with config:")
    config = SolverConfig(
        time_limit_seconds=30,
        seed=42,
        first_solution_strategy="PATH_CHEAPEST_ARC",
        local_search_metaheuristic="GUIDED_LOCAL_SEARCH",
        allow_unassigned=True
    )
    print(f"    - Time limit: {config.time_limit_seconds}s")
    print(f"    - Seed: {config.seed}")
    print(f"    - Strategy: {config.first_solution_strategy}")
    print(f"    - Metaheuristic: {config.local_search_metaheuristic}")

    # Create solver
    print()
    print("[4] Creating VRPTW Solver...")
    solver = VRPTWSolver(
        stops=stops,
        vehicles=vehicles,
        depots=[depot],
        travel_time_provider=travel_provider,
        config=config,
        vertical="MEDIAMARKT"
    )

    # Run solver
    print()
    print("[5] Running solver...")
    start_time = time.time()

    try:
        result: SolverResult = solver.solve()
    except ImportError as e:
        print(f"    ERROR: OR-Tools not installed: {e}")
        print("    Install with: pip install ortools")
        return False

    solve_time = time.time() - start_time

    # Print results
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    print(f"Status: {result.status}")
    print(f"Success: {result.success}")
    print(f"Solve time: {solve_time:.2f}s")
    print()

    if result.success:
        print(f"Vehicles used: {result.total_vehicles_used}")
        print(f"Total distance: {result.total_distance_m / 1000:.2f} km")
        print(f"Total duration: {result.total_duration_min} min")
        print(f"Unassigned stops: {len(result.unassigned_stop_ids)}")
        print(f"Objective value: {result.objective_value}")
        print(f"Output hash: {result.output_hash[:16]}...")
        print()

        # Print routes
        print("ROUTES:")
        print("-" * 50)
        for vehicle_id, route in result.routes.items():
            if route.stops:
                print(f"\n  Vehicle {vehicle_id}:")
                print(f"    Distance: {route.total_distance_km:.2f} km")
                print(f"    Stops ({len(route.stops)}):")
                for rs in route.stops:
                    # Find stop details
                    stop = next((s for s in stops if s.id == rs.stop_id), None)
                    if stop:
                        print(f"      {rs.sequence_index+1}. {rs.stop_id} ({stop.service_code})")
                    else:
                        print(f"      {rs.sequence_index+1}. {rs.stop_id}")

        # Print unassigned
        if result.unassigned_stop_ids:
            print()
            print("UNASSIGNED STOPS:")
            print("-" * 50)
            for stop_id in result.unassigned_stop_ids:
                reason = result.unassigned_reasons.get(stop_id, "UNKNOWN")
                stop = next((s for s in stops if s.id == stop_id), None)
                if stop:
                    print(f"  - {stop_id} ({stop.service_code}): {reason}")
                else:
                    print(f"  - {stop_id}: {reason}")

        # Validate results
        print()
        print("VALIDATION:")
        print("-" * 50)

        # Check all assigned stops are valid
        assigned_stops = set()
        for route in result.routes.values():
            for rs in route.stops:
                assigned_stops.add(rs.stop_id)

        all_stops = set(s.id for s in stops)
        unassigned_set = set(result.unassigned_stop_ids)

        # Coverage check
        coverage = len(assigned_stops) + len(unassigned_set)
        if coverage == len(stops):
            print(f"  [PASS] Coverage: {len(assigned_stops)}/{len(stops)} assigned")
        else:
            print(f"  [FAIL] Coverage mismatch: {coverage} != {len(stops)}")

        # No duplicate assignments
        if len(assigned_stops) == sum(len(r.stops) for r in result.routes.values()):
            print(f"  [PASS] No duplicate assignments")
        else:
            print(f"  [FAIL] Duplicate assignments detected")

        # Skill constraint check
        skill_violations = 0
        for vehicle_id, route in result.routes.items():
            vehicle = next(v for v in vehicles if v.id == vehicle_id)
            for rs in route.stops:
                stop = next((s for s in stops if s.id == rs.stop_id), None)
                if stop and stop.required_skills:
                    if not vehicle.has_all_skills(stop.required_skills):
                        skill_violations += 1
                        print(f"  [FAIL] Skill violation: {stop.id} requires {stop.required_skills}, "
                              f"vehicle {vehicle_id} has {vehicle.skills}")

        if skill_violations == 0:
            print(f"  [PASS] All skill constraints satisfied")

        # 2-Mann constraint check
        two_person_violations = 0
        for vehicle_id, route in result.routes.items():
            vehicle = next(v for v in vehicles if v.id == vehicle_id)
            for rs in route.stops:
                stop = next((s for s in stops if s.id == rs.stop_id), None)
                if stop and stop.requires_two_person:
                    if vehicle.team_size < 2:
                        two_person_violations += 1
                        print(f"  [FAIL] 2-Mann violation: {stop.id} requires 2-Mann, "
                              f"vehicle {vehicle_id} has team_size={vehicle.team_size}")

        if two_person_violations == 0:
            print(f"  [PASS] All 2-Mann constraints satisfied")

        print()
        return True

    else:
        print(f"Error: {result.error_message}")
        return False


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    success = run_solver_test()
    print()
    if success:
        print("TEST PASSED")
        sys.exit(0)
    else:
        print("TEST FAILED")
        sys.exit(1)
