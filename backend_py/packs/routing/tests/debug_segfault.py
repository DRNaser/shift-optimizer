# =============================================================================
# Debug Segmentation Fault - Step-by-Step Isolation
# =============================================================================

import sys
import gc
sys.path.insert(0, ".")

from datetime import datetime, timedelta
from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, Priority, SolverConfig
)
from packs.routing.services.travel_time.provider import TravelTimeProvider, TravelTimeResult, MatrixResult
from packs.routing.services.solver.data_model import SolverDataModel
from packs.routing.services.solver.constraints import ConstraintManager, ConstraintConfig
from packs.routing.policies.objectives import get_profile_for_vertical
import math

# OR-Tools imports
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp


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
        R = 6371.0  # Earth radius in km

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


def test_step_by_step():
    """Test step by step to isolate segfault."""

    print("=" * 70)
    print("DEBUG: Step-by-Step Segfault Isolation")
    print("=" * 70)

    depot, stops, vehicles = create_test_data()
    travel_provider = HaversineTravelTimeProvider()
    objectives = get_profile_for_vertical("MEDIAMARKT")

    print("\n[1] Building data model...")
    data = SolverDataModel(
        stops=stops,
        vehicles=vehicles,
        depots=[depot],
        travel_time_provider=travel_provider,
        reference_time=datetime.now()
    ).build()
    print(f"    Nodes: {data.num_nodes}, Vehicles: {data.num_vehicles}")
    print(f"    Vehicle starts: {data.vehicle_starts}")
    print(f"    Vehicle ends: {data.vehicle_ends}")

    print("\n[2] Creating RoutingIndexManager...")
    manager = pywrapcp.RoutingIndexManager(
        data.num_nodes,
        data.num_vehicles,
        data.vehicle_starts,
        data.vehicle_ends
    )
    print("    RoutingIndexManager created")

    print("\n[3] Creating RoutingModel...")
    routing = pywrapcp.RoutingModel(manager)
    print("    RoutingModel created")

    print("\n[4] Creating ConstraintManager...")
    constraint_config = ConstraintConfig(
        time_window_penalty=objectives.time_window_penalty,
        overtime_penalty=objectives.overtime_penalty
    )
    constraint_manager = ConstraintManager(
        routing=routing,
        manager=manager,
        data=data,
        config=constraint_config
    )
    print("    ConstraintManager created")

    print("\n[5] Adding all constraints...")
    constraint_manager.add_all_constraints()
    print("    All constraints added")
    print(f"    Stored callbacks: {len(constraint_manager._callbacks)}")

    print("\n[6] Setting arc cost evaluator...")
    print(f"    Time callback index: {constraint_manager.time_callback_index}")
    routing.SetArcCostEvaluatorOfAllVehicles(constraint_manager.time_callback_index)
    print("    Arc cost set")

    print("\n[7] Setting span cost coefficient...")
    distance_dimension = routing.GetDimensionOrDie("Distance")
    distance_dimension.SetGlobalSpanCostCoefficient(objectives.distance_cost_per_km // 1000)
    print("    Span cost set")

    print("\n[8] Adding disjunctions...")
    for stop in stops:
        node = data.get_node_for_stop(stop.id)
        if node is not None:
            index = manager.NodeToIndex(node)
            routing.AddDisjunction([index], objectives.unassigned_penalty)
    print(f"    {len(stops)} disjunctions added")

    print("\n[9] Forcing garbage collection...")
    gc.collect()
    print("    GC complete")

    print("\n[10] Creating search parameters...")
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.FromSeconds(10)
    print("    Search parameters created")

    print("\n[11] About to solve...")
    print("    (If segfault happens here, the issue is in SolveWithParameters)")
    sys.stdout.flush()

    solution = routing.SolveWithParameters(search_params)

    print("\n[12] Solve complete!")
    if solution:
        print(f"    Solution found! Objective: {solution.ObjectiveValue()}")
    else:
        print(f"    No solution. Status: {routing.status()}")

    return True


if __name__ == "__main__":
    try:
        success = test_step_by_step()
        if success:
            print("\n✅ DEBUG COMPLETE - NO SEGFAULT")
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
