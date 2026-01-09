# =============================================================================
# SOLVEREIGN Routing Pack - Realistic Solver Test
# =============================================================================
# This test PROVES that OR-Tools solver actually executes with real constraints.
#
# Gate 1 Requirements:
# - solver actually executed (status flag, objective value present)
# - search_params.time_limit_seconds > 0
# - metaheuristic active (GUIDED_LOCAL_SEARCH)
# - matrix build not mocked
# - non-empty assignments returned
# =============================================================================

import sys
import time
import unittest
import random
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

sys.path.insert(0, ".")

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory
)


class TestSolverActualExecution(unittest.TestCase):
    """
    Tests that PROVE OR-Tools solver actually runs.

    These are NOT mocked - they call real OR-Tools with real constraints.
    """

    def setUp(self):
        """Set up test with small but realistic scenario."""
        random.seed(42)
        self.today = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)

    def _build_distance_matrix(self, locations: List[Tuple[float, float]]) -> List[List[int]]:
        """Build real Euclidean distance matrix (not mocked)."""
        n = len(locations)
        matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i != j:
                    lat1, lng1 = locations[i]
                    lat2, lng2 = locations[j]
                    # Haversine approximation in meters
                    dlat = abs(lat2 - lat1) * 111000  # ~111km per degree
                    dlng = abs(lng2 - lng1) * 111000 * 0.65  # adjusted for latitude
                    dist = int((dlat**2 + dlng**2)**0.5)
                    matrix[i][j] = dist

        return matrix

    def _build_time_matrix(self, distance_matrix: List[List[int]], speed_mps: int = 10) -> List[List[int]]:
        """Build time matrix from distance (in seconds)."""
        n = len(distance_matrix)
        return [
            [distance_matrix[i][j] // speed_mps for j in range(n)]
            for i in range(n)
        ]

    def test_ortools_actually_solves_10_stops(self):
        """
        PROOF: OR-Tools solver runs with 10 stops, 2 vehicles.

        Validates:
        - Solver status is success (0, 1, or 2)
        - Objective value is computed
        - Assignments are non-empty
        - Search time > 0
        """
        print("\n" + "=" * 60)
        print("PROOF TEST: OR-Tools Solver Actually Executes")
        print("=" * 60)

        # Setup: 1 depot + 10 stops = 11 nodes
        num_stops = 10
        num_vehicles = 2
        depot_location = (52.52, 13.405)  # Berlin center

        # Generate stop locations
        stop_locations = [
            (52.52 + random.uniform(-0.05, 0.05), 13.405 + random.uniform(-0.05, 0.05))
            for _ in range(num_stops)
        ]

        all_locations = [depot_location] + stop_locations

        # Build REAL matrices (not mocked)
        print(f"\n[1] Building distance matrix for {len(all_locations)} locations...")
        start = time.time()
        distance_matrix = self._build_distance_matrix(all_locations)
        time_matrix = self._build_time_matrix(distance_matrix)
        matrix_time = (time.time() - start) * 1000
        print(f"    Matrix build: {matrix_time:.1f}ms")

        # Verify matrix is not trivial
        max_dist = max(max(row) for row in distance_matrix)
        self.assertGreater(max_dist, 0, "Distance matrix must have non-zero values")
        print(f"    Max distance: {max_dist}m")

        # Create OR-Tools manager
        print(f"\n[2] Creating RoutingIndexManager...")
        manager = pywrapcp.RoutingIndexManager(
            len(all_locations),  # num nodes
            num_vehicles,        # num vehicles
            0                    # depot index
        )

        # Create routing model
        print(f"[3] Creating RoutingModel...")
        routing = pywrapcp.RoutingModel(manager)

        # Distance callback
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return distance_matrix[from_node][to_node]

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # Add distance dimension
        routing.AddDimension(
            transit_callback_index,
            0,           # slack
            100000,      # max distance per vehicle (100km)
            True,        # start at zero
            "Distance"
        )

        # Time callback
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return time_matrix[from_node][to_node]

        time_callback_index = routing.RegisterTransitCallback(time_callback)

        # Add time dimension with time windows
        routing.AddDimension(
            time_callback_index,
            3600,        # 1 hour slack
            36000,       # 10 hour max
            False,       # don't force start at zero
            "Time"
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        # Add time windows (realistic: 2-hour windows)
        for stop_idx in range(1, num_stops + 1):
            index = manager.NodeToIndex(stop_idx)
            tw_start = random.randint(0, 18000)  # 0-5 hours
            tw_end = tw_start + 7200  # 2-hour window
            time_dimension.CumulVar(index).SetRange(tw_start, tw_end)

        # Configure search parameters - MUST use real search
        print(f"\n[4] Configuring search parameters...")
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_params.time_limit.FromSeconds(5)  # 5 second limit

        print(f"    Strategy: PATH_CHEAPEST_ARC")
        print(f"    Metaheuristic: GUIDED_LOCAL_SEARCH")
        print(f"    Time limit: 5 seconds")

        # SOLVE
        print(f"\n[5] Solving...")
        solve_start = time.time()
        solution = routing.SolveWithParameters(search_params)
        solve_time = (time.time() - solve_start) * 1000

        # Get solver status
        solver_status = routing.status()
        status_names = {
            0: "ROUTING_NOT_SOLVED",
            1: "ROUTING_SUCCESS",
            2: "ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED",
            3: "ROUTING_FAIL",
            4: "ROUTING_FAIL_TIMEOUT",
            5: "ROUTING_INVALID"
        }

        print(f"\n[6] Results:")
        print(f"    Solver status: {solver_status} ({status_names.get(solver_status, 'UNKNOWN')})")
        print(f"    Solve time: {solve_time:.1f}ms")

        # PROOF ASSERTIONS
        print(f"\n[7] Proof Assertions:")

        # Assertion 1: Solver ran (not INVALID or NOT_SOLVED without solution)
        self.assertIsNotNone(solution, "Solution must exist")
        print(f"    [PASS] Solution exists")

        # Assertion 2: Objective value computed
        objective = solution.ObjectiveValue()
        self.assertGreater(objective, 0, "Objective value must be positive")
        print(f"    [PASS] Objective value: {objective}")

        # Assertion 3: Extract routes - must have assignments
        total_assigned = 0
        for vehicle_id in range(num_vehicles):
            index = routing.Start(vehicle_id)
            route_stops = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:  # Not depot
                    route_stops.append(node)
                index = solution.Value(routing.NextVar(index))
            total_assigned += len(route_stops)
            if route_stops:
                print(f"    Vehicle {vehicle_id}: {len(route_stops)} stops")

        self.assertGreater(total_assigned, 0, "Must have at least 1 assigned stop")
        print(f"    [PASS] Total assigned: {total_assigned}/{num_stops}")

        # Assertion 4: Solve time reasonable (not instant = actually searched)
        # With GLS metaheuristic, even small problems take measurable time
        self.assertGreater(solve_time, 1, "Solve time must be > 1ms (not instant)")
        print(f"    [PASS] Solve time > 1ms (actually searched)")

        print("\n" + "=" * 60)
        print("PROOF COMPLETE: OR-Tools solver actually executed")
        print("=" * 60)

    def test_ortools_solves_50_stops_with_constraints(self):
        """
        PROOF: OR-Tools handles 50 stops with real constraints.

        This is closer to realistic MediaMarkt scenario size.
        """
        print("\n" + "=" * 60)
        print("PROOF TEST: 50 Stops with Time Windows + Capacity")
        print("=" * 60)

        num_stops = 50
        num_vehicles = 5
        depot_location = (52.52, 13.405)

        # Generate stops
        stop_locations = [
            (52.52 + random.uniform(-0.1, 0.1), 13.405 + random.uniform(-0.1, 0.1))
            for _ in range(num_stops)
        ]

        all_locations = [depot_location] + stop_locations

        # Build matrices
        print(f"\n[1] Building matrices for {len(all_locations)} locations...")
        start = time.time()
        distance_matrix = self._build_distance_matrix(all_locations)
        time_matrix = self._build_time_matrix(distance_matrix)
        print(f"    Matrix build: {(time.time() - start)*1000:.1f}ms")

        # Demands (random 1-3 units per stop)
        demands = [0] + [random.randint(1, 3) for _ in range(num_stops)]
        vehicle_capacities = [20] * num_vehicles  # 20 units per vehicle

        # Create model
        manager = pywrapcp.RoutingIndexManager(len(all_locations), num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        # Distance
        def distance_callback(from_index, to_index):
            return distance_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

        transit_idx = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

        # Capacity constraint
        def demand_callback(from_index):
            return demands[manager.IndexToNode(from_index)]

        demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx,
            0,                    # slack
            vehicle_capacities,   # capacity per vehicle
            True,                 # start at zero
            "Capacity"
        )

        # Time windows
        def time_callback(from_index, to_index):
            return time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

        time_idx = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(time_idx, 3600, 36000, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")

        for stop_idx in range(1, num_stops + 1):
            index = manager.NodeToIndex(stop_idx)
            tw_start = random.randint(0, 14400)
            tw_end = tw_start + 7200
            time_dim.CumulVar(index).SetRange(tw_start, tw_end)

        # Search params
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        search_params.time_limit.FromSeconds(10)

        print(f"\n[2] Solving with:")
        print(f"    Stops: {num_stops}")
        print(f"    Vehicles: {num_vehicles}")
        print(f"    Capacity per vehicle: 20 units")
        print(f"    Time limit: 10 seconds")

        # Solve
        solve_start = time.time()
        solution = routing.SolveWithParameters(search_params)
        solve_time = (time.time() - solve_start) * 1000

        print(f"\n[3] Results:")
        print(f"    Solver status: {routing.status()}")
        print(f"    Solve time: {solve_time:.1f}ms")

        # Assertions
        self.assertIsNotNone(solution)

        objective = solution.ObjectiveValue()
        print(f"    Objective: {objective}")
        self.assertGreater(objective, 0)

        # Count assignments
        total_assigned = 0
        total_load = 0
        for v in range(num_vehicles):
            index = routing.Start(v)
            route_load = 0
            route_stops = 0
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    route_stops += 1
                    route_load += demands[node]
                index = solution.Value(routing.NextVar(index))
            total_assigned += route_stops
            total_load += route_load
            if route_stops > 0:
                print(f"    Vehicle {v}: {route_stops} stops, load={route_load}")

        print(f"\n    Total assigned: {total_assigned}/{num_stops}")
        print(f"    Total load: {total_load}")

        self.assertGreater(total_assigned, 0)

        print("\n" + "=" * 60)
        print("PROOF COMPLETE: 50-stop scenario solved")
        print("=" * 60)

    def test_ortools_respects_time_limit(self):
        """
        PROOF: Solver respects time_limit parameter.

        Set 2-second limit, verify solve doesn't exceed it significantly.
        """
        print("\n" + "=" * 60)
        print("PROOF TEST: Time Limit Respected")
        print("=" * 60)

        num_stops = 30
        num_vehicles = 3

        locations = [(52.52 + random.uniform(-0.05, 0.05), 13.405 + random.uniform(-0.05, 0.05))
                     for _ in range(num_stops + 1)]

        distance_matrix = self._build_distance_matrix(locations)

        manager = pywrapcp.RoutingIndexManager(len(locations), num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        def callback(i, j):
            return distance_matrix[manager.IndexToNode(i)][manager.IndexToNode(j)]

        idx = routing.RegisterTransitCallback(callback)
        routing.SetArcCostEvaluatorOfAllVehicles(idx)

        # Set 2-second time limit
        TIME_LIMIT_SECONDS = 2
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        search_params.time_limit.FromSeconds(TIME_LIMIT_SECONDS)

        print(f"    Time limit set: {TIME_LIMIT_SECONDS}s")

        solve_start = time.time()
        solution = routing.SolveWithParameters(search_params)
        solve_time = time.time() - solve_start

        print(f"    Actual solve time: {solve_time:.2f}s")

        # Allow 20% tolerance for overhead
        max_allowed = TIME_LIMIT_SECONDS * 1.2
        self.assertLess(solve_time, max_allowed,
            f"Solve time {solve_time:.2f}s exceeded limit {TIME_LIMIT_SECONDS}s by too much")

        print(f"    [PASS] Solve time within tolerance")

        print("\n" + "=" * 60)
        print("PROOF COMPLETE: Time limit respected")
        print("=" * 60)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Solver Proof Tests")
    print("These tests PROVE OR-Tools actually executes")
    print("=" * 70)
    unittest.main(verbosity=2)
