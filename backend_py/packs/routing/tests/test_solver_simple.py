# =============================================================================
# Simple VRPTWSolver Test
# =============================================================================

import sys
sys.path.insert(0, ".")

from datetime import datetime, timedelta
from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, SolverConfig
)
from packs.routing.services.travel_time.provider import TravelTimeProvider, TravelTimeResult, MatrixResult
from packs.routing.services.solver.vrptw_solver import VRPTWSolver
import math


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
        lat1, lng1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lng2 = math.radians(destination[0]), math.radians(destination[1])

        dlat = lat2 - lat1
        dlng = lng2 - lng1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        R = 6371.0

        distance_km = R * c
        distance_m = int(distance_km * 1000)

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


def create_test_data():
    """Create minimal test scenario."""
    today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    depot = Depot(
        id="DEPOT_BERLIN",
        tenant_id=1,
        site_id="MM_BERLIN",
        name="MediaMarkt Berlin",
        geocode=Geocode(lat=52.5200, lng=13.4050),
        loading_time_min=15
    )

    stops = []
    locations = [
        ("Charlottenburg", 52.5167, 13.3000),
        ("Kreuzberg", 52.4970, 13.4030),
        ("Prenzlauer Berg", 52.5389, 13.4244),
    ]

    for i, (name, lat, lng) in enumerate(locations):
        tw_start = today + timedelta(hours=1 + i)
        tw_end = tw_start + timedelta(hours=2)

        stop = Stop(
            id=f"STOP_{i+1:02d}",
            order_id=f"ORDER_{i+1:03d}",
            tenant_id=1,
            scenario_id="TEST",
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
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=10,
        )
        stops.append(stop)

    vehicle = Vehicle(
        id="VAN_01",
        tenant_id=1,
        scenario_id="TEST",
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
    )

    return depot, stops, [vehicle]


def test_vrptw_solver():
    """Test VRPTWSolver directly."""

    print("=" * 70)
    print("TEST: VRPTWSolver Direct Test")
    print("=" * 70)

    depot, stops, vehicles = create_test_data()
    travel_provider = HaversineTravelTimeProvider()

    config = SolverConfig(
        time_limit_seconds=10,
        seed=42,
        first_solution_strategy="PATH_CHEAPEST_ARC",
        local_search_metaheuristic="GUIDED_LOCAL_SEARCH",
        allow_unassigned=True
    )

    print("\n[1] Creating VRPTWSolver...")
    solver = VRPTWSolver(
        stops=stops,
        vehicles=vehicles,
        depots=[depot],
        travel_time_provider=travel_provider,
        config=config,
        vertical="MEDIAMARKT"
    )
    print("    VRPTWSolver created")

    print("\n[2] Calling solver.solve()...")
    print("    (If segfault happens here, the issue is in VRPTWSolver.solve())")
    sys.stdout.flush()

    result = solver.solve()

    print("\n[3] Solve returned!")
    print(f"    Success: {result.success}")
    print(f"    Status: {result.status}")

    if result.success:
        print(f"    Vehicles used: {result.total_vehicles_used}")
        print(f"    Distance: {result.total_distance_m / 1000:.2f} km")
        print(f"    Objective: {result.objective_value}")
        print(f"    Unassigned: {len(result.unassigned_stop_ids)}")
    else:
        print(f"    Error: {result.error_message}")

    print("\n[4] TEST COMPLETE")
    return result.success


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')

    success = test_vrptw_solver()
    print(f"\nResult: {'PASS' if success else 'FAIL'}")
    sys.exit(0 if success else 1)
