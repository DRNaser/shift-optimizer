# =============================================================================
# SOLVEREIGN Routing Pack - VRPTW Solver
# =============================================================================
# OR-Tools based Vehicle Routing Problem with Time Windows solver.
#
# Key Features:
# - Multi-Depot Support (P0-1): Uses starts[]/ends[] for each vehicle
# - Time Windows: Hard and soft constraints
# - Capacity: Volume and weight
# - Skills: Vehicle-stop eligibility
# - 2-Mann Teams: Team size requirements
#
# Usage:
#     solver = VRPTWSolver(stops, vehicles, depots, travel_provider, config)
#     result = solver.solve()
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
import logging
import hashlib

logger = logging.getLogger(__name__)

# Try to import OR-Tools (may not be installed in all environments)
try:
    from ortools.constraint_solver import routing_enums_pb2
    from ortools.constraint_solver import pywrapcp
    HAS_ORTOOLS = True
except ImportError:
    HAS_ORTOOLS = False
    logger.warning("OR-Tools not installed. Solver will not function.")

from ...domain.models import (
    Stop, Vehicle, Depot, Route, RouteStop, RoutePlan, PlanStatus,
    SolverConfig, PrecedencePair, MultiStartConfig
)
from ...policies.objectives import ObjectiveProfile, get_profile_for_vertical
from ..travel_time.provider import TravelTimeProvider
from .data_model import SolverDataModel
from .constraints import ConstraintManager, ConstraintConfig


@dataclass
class SolverResult:
    """Result from the VRPTW solver."""
    success: bool
    status: str                              # 'OPTIMAL', 'FEASIBLE', 'NO_SOLUTION', 'ERROR'
    solver_status: Optional[int] = None      # OR-Tools status code

    # Solution
    routes: Dict[str, Route] = field(default_factory=dict)  # vehicle_id -> Route
    unassigned_stop_ids: List[str] = field(default_factory=list)
    unassigned_reasons: Dict[str, str] = field(default_factory=dict)  # stop_id -> reason

    # Metrics
    total_distance_m: int = 0
    total_duration_min: int = 0
    total_vehicles_used: int = 0
    objective_value: int = 0

    # Hashes for reproducibility
    output_hash: Optional[str] = None

    # Timing
    solve_time_seconds: float = 0.0

    # P0: Multi-Start metadata
    seed_used: Optional[int] = None          # Seed that produced this result
    multi_start_scores: Optional[Dict[int, float]] = None  # seed -> score
    kpi_score: Optional[float] = None        # Lexicographic KPI score

    # Error info
    error_message: Optional[str] = None


class VRPTWSolver:
    """
    VRPTW Solver using OR-Tools.

    P0-1: Multi-Depot support via starts[]/ends[] arrays.
    """

    def __init__(
        self,
        stops: List[Stop],
        vehicles: List[Vehicle],
        depots: List[Depot],
        travel_time_provider: TravelTimeProvider,
        config: SolverConfig = None,
        objective_profile: ObjectiveProfile = None,
        vertical: str = "BALANCED",
        precedence_pairs: List[PrecedencePair] = None,  # P0: Precedence constraints
        multi_start_config: MultiStartConfig = None     # P0: Multi-start config
    ):
        if not HAS_ORTOOLS:
            raise ImportError("OR-Tools is required for VRPTWSolver. Install with: pip install ortools")

        self.stops = stops
        self.vehicles = vehicles
        self.depots = depots
        self.travel_time_provider = travel_time_provider
        self.config = config or SolverConfig()
        self.precedence_pairs = precedence_pairs or []
        self.multi_start_config = multi_start_config

        # Get objective profile (from vertical or provided)
        if objective_profile:
            self.objectives = objective_profile
        else:
            self.objectives = get_profile_for_vertical(vertical)

        # Will be set during solve()
        self._data: Optional[SolverDataModel] = None
        self._manager: Optional["pywrapcp.RoutingIndexManager"] = None
        self._routing: Optional["pywrapcp.RoutingModel"] = None

    def solve(self) -> SolverResult:
        """
        Run the VRPTW optimization.

        Returns:
            SolverResult with routes and metrics
        """
        import time
        start_time = time.time()

        try:
            # 1. Build data model
            logger.info("Building data model...")
            self._data = SolverDataModel(
                stops=self.stops,
                vehicles=self.vehicles,
                depots=self.depots,
                travel_time_provider=self.travel_time_provider,
                precedence_pairs=self.precedence_pairs,  # P0: Pass precedence
                reference_time=datetime.now()
            ).build()

            # Validate data
            errors = self._data.validate()
            if errors:
                logger.error(f"Data validation errors: {errors}")
                return SolverResult(
                    success=False,
                    status="ERROR",
                    error_message=f"Data validation failed: {errors}"
                )

            # 2. Create routing index manager (P0-1: MULTI-DEPOT)
            logger.info("Creating routing index manager with Multi-Depot...")
            self._manager = pywrapcp.RoutingIndexManager(
                self._data.num_nodes,
                self._data.num_vehicles,
                self._data.vehicle_starts,    # P0-1: Start nodes per vehicle
                self._data.vehicle_ends       # P0-1: End nodes per vehicle
            )

            # 3. Create routing model
            self._routing = pywrapcp.RoutingModel(self._manager)

            # 4. Add constraints
            logger.info("Adding constraints...")
            constraint_config = ConstraintConfig(
                time_window_penalty=self.objectives.time_window_penalty,
                overtime_penalty=self.objectives.overtime_penalty
            )
            # IMPORTANT: Store as instance variable to prevent garbage collection
            # during solve. Callbacks reference self.data which must stay alive.
            self._constraint_manager = ConstraintManager(
                routing=self._routing,
                manager=self._manager,
                data=self._data,
                config=constraint_config
            )
            self._constraint_manager.add_all_constraints()

            # 5. Set objective (minimize cost)
            self._set_objective(self._constraint_manager)

            # 6. Allow dropping stops (if configured)
            if self.config.allow_unassigned:
                self._allow_dropping_stops()

            # 7. Configure search parameters
            search_params = self._create_search_params()

            # 8. Solve
            logger.info(f"Solving with time limit {self.config.time_limit_seconds}s...")
            solution = self._routing.SolveWithParameters(search_params)

            solve_time = time.time() - start_time

            # 9. Extract solution
            if solution:
                result = self._extract_solution(solution)
                result.solve_time_seconds = solve_time
                logger.info(f"Solution found in {solve_time:.2f}s: "
                           f"{result.total_vehicles_used} vehicles, "
                           f"{len(result.unassigned_stop_ids)} unassigned")
                return result
            else:
                logger.warning("No solution found")
                return SolverResult(
                    success=False,
                    status="NO_SOLUTION",
                    solver_status=self._routing.status(),
                    solve_time_seconds=solve_time,
                    error_message="No feasible solution found"
                )

        except Exception as e:
            logger.exception("Solver error")
            return SolverResult(
                success=False,
                status="ERROR",
                error_message=str(e),
                solve_time_seconds=time.time() - start_time
            )

    def _set_objective(self, constraint_manager: ConstraintManager):
        """Set the optimization objective."""
        # Primary: Minimize total travel time (arc cost)
        self._routing.SetArcCostEvaluatorOfAllVehicles(
            constraint_manager.time_callback_index
        )

        # Secondary: Minimize distance (via dimension cost)
        distance_dimension = self._routing.GetDimensionOrDie("Distance")
        distance_dimension.SetGlobalSpanCostCoefficient(
            self.objectives.distance_cost_per_km // 1000  # Per meter
        )

        logger.debug(f"Objective set: time + distance (coef={self.objectives.distance_cost_per_km})")

    def _allow_dropping_stops(self):
        """
        Allow dropping stops with penalty (for infeasible cases).

        P1.1: For multi-TW stops, creates disjunction over ALL clone nodes.
        This ensures exactly one clone is visited (or all dropped together).
        """
        penalty = self.objectives.unassigned_penalty
        handled_stops: set = set()

        for stop in self.stops:
            if stop.id in handled_stops:
                continue

            clone_nodes = self._data.get_clone_nodes_for_stop(stop.id)

            if clone_nodes:
                # P1.1: Multi-TW stop - create disjunction over all clones
                clone_indices = [self._manager.NodeToIndex(n) for n in clone_nodes]
                self._routing.AddDisjunction(clone_indices, penalty)
                logger.debug(f"P1.1: Multi-TW disjunction for {stop.id} with {len(clone_indices)} clones")
            else:
                # Single TW: standard disjunction
                node = self._data.get_node_for_stop(stop.id)
                if node is not None:
                    index = self._manager.NodeToIndex(node)
                    self._routing.AddDisjunction([index], penalty)

            handled_stops.add(stop.id)

        logger.debug(f"Disjunctions added for {len(handled_stops)} stops (penalty={penalty})")

    def _create_search_params(self, seed: Optional[int] = None, time_limit: Optional[int] = None) -> Any:
        """
        Create search parameters for the solver.

        P0: Determinism Hardening:
        - random_seed: Set for reproducibility
        - number_of_workers=1: Prevents non-deterministic parallel search

        Args:
            seed: Random seed for reproducibility (None = use default)
            time_limit: Override time limit (for multi-start runs)
        """
        search_params = pywrapcp.DefaultRoutingSearchParameters()

        # First solution strategy
        strategy_map = {
            "PATH_CHEAPEST_ARC": routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
            "PATH_MOST_CONSTRAINED_ARC": routing_enums_pb2.FirstSolutionStrategy.PATH_MOST_CONSTRAINED_ARC,
            "SAVINGS": routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
            "PARALLEL_CHEAPEST_INSERTION": routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
        }
        search_params.first_solution_strategy = strategy_map.get(
            self.config.first_solution_strategy,
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )

        # Local search metaheuristic
        metaheuristic_map = {
            "GUIDED_LOCAL_SEARCH": routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH,
            "SIMULATED_ANNEALING": routing_enums_pb2.LocalSearchMetaheuristic.SIMULATED_ANNEALING,
            "TABU_SEARCH": routing_enums_pb2.LocalSearchMetaheuristic.TABU_SEARCH,
            "AUTOMATIC": routing_enums_pb2.LocalSearchMetaheuristic.AUTOMATIC,
        }
        search_params.local_search_metaheuristic = metaheuristic_map.get(
            self.config.local_search_metaheuristic,
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )

        # Time limit (use override if provided)
        effective_limit = time_limit if time_limit is not None else self.config.time_limit_seconds
        search_params.time_limit.FromSeconds(effective_limit)

        # Solution limit (if set)
        if self.config.solution_limit > 0:
            search_params.solution_limit = self.config.solution_limit

        # P0: Determinism hardening
        if seed is not None:
            # Note: OR-Tools uses 'random_seed' for some strategies
            # Some metaheuristics may not respect this, but we set it for best effort
            search_params.random_seed = seed
            logger.debug(f"Search params: seed={seed}")

        # CRITICAL: Single worker for determinism
        # Multi-threaded search can produce different results across runs
        if self.multi_start_config and self.multi_start_config.force_single_worker:
            search_params.number_of_workers = 1
            logger.debug("Search params: single worker (determinism mode)")

        # Logging
        search_params.log_search = False  # Set to True for debug

        return search_params

    def _extract_solution(self, solution: Any) -> SolverResult:
        """Extract solution from OR-Tools into domain objects."""
        logger.info("Extracting solution...")
        routes: Dict[str, Route] = {}
        total_distance = 0
        total_duration = 0
        vehicles_used = 0

        logger.debug("Getting dimensions...")
        time_dimension = self._routing.GetDimensionOrDie("Time")
        logger.debug("Dimensions retrieved")

        # Extract each vehicle's route
        for v_idx in range(self._data.num_vehicles):
            vehicle = self.vehicles[v_idx]
            route_stops: List[RouteStop] = []

            index = self._routing.Start(v_idx)
            route_distance = 0
            sequence = 0

            while not self._routing.IsEnd(index):
                node = self._manager.IndexToNode(index)
                next_index = solution.Value(self._routing.NextVar(index))
                next_node = self._manager.IndexToNode(next_index)

                # Skip depot nodes for route stops
                if self._data.is_stop_node(node):
                    stop = self._data.get_stop_for_node(node)

                    # P1.1: Get base stop ID and selected window for clones
                    base_stop_id = self._data.get_base_stop_id(node)
                    selected_window_idx = self._data.get_selected_window_index(node)

                    # Get timing from solution
                    # TODO: Compute proper arrival/departure times from CumulVar
                    # NOTE: SlackVar access removed due to OR-Tools segfault issue
                    slack = 0

                    route_stops.append(RouteStop(
                        stop_id=base_stop_id,  # P1.1: Use base stop ID, not clone
                        sequence_index=sequence,
                        arrival_time=self._data.reference_time,  # TODO: Add minutes
                        departure_time=self._data.reference_time,
                        slack_minutes=slack,
                        is_locked=False,
                        assignment_reason="SOLVER",
                        selected_window_index=selected_window_idx  # P1.1: Track selected window
                    ))
                    sequence += 1

                # Accumulate distance
                # P1.1: Use location indices for matrix lookup
                from_loc = self._data.get_location_index(node)
                to_loc = self._data.get_location_index(next_node)
                route_distance += self._data.distance_matrix[from_loc][to_loc]

                index = next_index

            # Only count vehicles with actual stops
            if route_stops:
                vehicles_used += 1

                # Get route end time
                end_time_var = time_dimension.CumulVar(index)
                route_duration = solution.Min(end_time_var)

                routes[vehicle.id] = Route(
                    id=f"route_{vehicle.id}",
                    plan_id="",  # Set by caller
                    vehicle_id=vehicle.id,
                    stops=route_stops,
                    total_distance_km=route_distance / 1000.0,
                    total_duration_min=route_duration,
                    total_service_min=sum(s.slack_minutes for s in route_stops),
                    total_travel_min=route_duration  # Simplified
                )

                total_distance += route_distance
                total_duration += route_duration

        logger.debug(f"Extracted {vehicles_used} vehicle routes")

        # P1.1 SAFETY CHECK: Verify no duplicate base_stop_ids in any route
        # Disjunction guarantees "at most one" clone visited, but let's verify
        for vehicle_id, route in routes.items():
            seen_base_stops = set()
            for rs in route.stops:
                if rs.stop_id in seen_base_stops:
                    logger.error(f"P1.1 BUG: Duplicate stop {rs.stop_id} in route {vehicle_id}")
                    raise RuntimeError(
                        f"P1.1 invariant violated: stop {rs.stop_id} appears multiple times "
                        f"in route {vehicle_id}. This indicates a disjunction constraint failure."
                    )
                seen_base_stops.add(rs.stop_id)

        # Find unassigned stops
        # P1.1: For multi-TW stops, check if ALL clones are dropped
        unassigned = []
        unassigned_reasons = {}

        for stop in self.stops:
            clone_nodes = self._data.get_clone_nodes_for_stop(stop.id)

            if clone_nodes:
                # P1.1: Multi-TW stop - check if ALL clones are dropped
                all_dropped = True
                for clone_node in clone_nodes:
                    clone_index = self._manager.NodeToIndex(clone_node)
                    if solution.Value(self._routing.NextVar(clone_index)) != clone_index:
                        all_dropped = False
                        break

                if all_dropped:
                    unassigned.append(stop.id)
                    unassigned_reasons[stop.id] = "DROPPED_BY_SOLVER"
            else:
                # Single TW: standard check
                node = self._data.get_node_for_stop(stop.id)
                if node is None:
                    continue

                index = self._manager.NodeToIndex(node)
                if solution.Value(self._routing.NextVar(index)) == index:
                    # Stop is dropped (points to itself)
                    unassigned.append(stop.id)
                    unassigned_reasons[stop.id] = "DROPPED_BY_SOLVER"

        logger.debug(f"Found {len(unassigned)} unassigned stops")

        # Compute output hash for reproducibility
        output_hash = self._compute_output_hash(routes, unassigned)
        logger.info("Solution extracted successfully")

        return SolverResult(
            success=True,
            status="FEASIBLE",
            solver_status=self._routing.status(),
            routes=routes,
            unassigned_stop_ids=unassigned,
            unassigned_reasons=unassigned_reasons,
            total_distance_m=total_distance,
            total_duration_min=total_duration,
            total_vehicles_used=vehicles_used,
            objective_value=solution.ObjectiveValue(),
            output_hash=output_hash
        )

    def _compute_output_hash(
        self,
        routes: Dict[str, Route],
        unassigned: List[str]
    ) -> str:
        """Compute hash of solution for reproducibility check."""
        # Create deterministic representation
        route_data = []
        for vehicle_id in sorted(routes.keys()):
            route = routes[vehicle_id]
            stops = [s.stop_id for s in sorted(route.stops, key=lambda x: x.sequence_index)]
            route_data.append(f"{vehicle_id}:{','.join(stops)}")

        unassigned_str = ",".join(sorted(unassigned))
        combined = "|".join(route_data) + "||" + unassigned_str

        return hashlib.sha256(combined.encode()).hexdigest()

    # =========================================================================
    # P0: Multi-Start Best-of Solving
    # =========================================================================

    def solve_multi_start(self) -> SolverResult:
        """
        Run multiple solves with different seeds and return the best solution.

        P0: Multi-Start Best-of Implementation:
        - Runs N solves with different random seeds
        - Scores each solution using lexicographic KPI function
        - Returns the best solution with evidence of all runs

        CRITICAL for determinism:
        - Each run uses number_of_workers=1
        - Seeds are explicitly provided or generated deterministically
        - All run scores are logged for evidence

        Returns:
            SolverResult from the best-scoring run
        """
        import time
        start_time = time.time()

        if not self.multi_start_config:
            # No multi-start config, fall back to single solve
            logger.info("No multi-start config, using single solve")
            return self.solve()

        config = self.multi_start_config

        # Determine seeds to use
        if config.seeds:
            seeds = config.seeds[:config.num_seeds]
        else:
            # Generate deterministic seeds
            seeds = list(range(1, config.num_seeds + 1))

        logger.info(f"Starting multi-start solve with {len(seeds)} seeds: {seeds}")

        # Track all runs
        all_results: Dict[int, SolverResult] = {}
        all_tuples: Dict[int, tuple] = {}  # seed -> KPI tuple for evidence
        best_result: Optional[SolverResult] = None
        best_tuple: Optional[tuple] = None
        best_seed: Optional[int] = None

        for seed in seeds:
            run_start = time.time()
            logger.info(f"Multi-start run: seed={seed}")

            # Run solve with this seed
            result = self._solve_with_seed(
                seed=seed,
                time_limit=config.per_run_time_limit_seconds
            )

            run_time = time.time() - run_start

            if self._is_solution_valid(result):
                # Compute KPI tuple for lexicographic comparison
                kpi_tuple = self._compute_kpi_tuple(result)
                all_tuples[seed] = kpi_tuple
                all_results[seed] = result
                result.seed_used = seed
                # Store tuple as score for evidence (sum of weighted components)
                result.kpi_score = -sum(kpi_tuple)  # Negate so higher = better in logs

                logger.info(
                    f"Seed {seed}: tuple={kpi_tuple}, "
                    f"unassigned={len(result.unassigned_stop_ids)}, "
                    f"vehicles={result.total_vehicles_used}, "
                    f"time={run_time:.2f}s"
                )

                # CRITICAL: Use min() for tuple comparison (lower = better)
                if best_tuple is None or kpi_tuple < best_tuple:
                    best_tuple = kpi_tuple
                    best_result = result
                    best_seed = seed
            else:
                logger.warning(f"Seed {seed} failed: {result.error_message}")
                all_tuples[seed] = (float('inf'),) * 5  # Infinity tuple = worst

            # Check overall time limit
            elapsed = time.time() - start_time
            if elapsed >= config.overall_time_limit_seconds:
                logger.warning(
                    f"Multi-start time limit reached after {len(all_tuples)} runs"
                )
                break

        total_time = time.time() - start_time

        # P1.2: Apply disqualification filters before final selection
        all_results, all_tuples = self._apply_disqualification_filters(all_results, all_tuples)

        # Re-select best from filtered candidates
        best_result = None
        best_tuple = None
        best_seed = None

        for seed, kpi_tuple in all_tuples.items():
            if seed not in all_results:
                continue
            if best_tuple is None or kpi_tuple < best_tuple:
                best_tuple = kpi_tuple
                best_result = all_results[seed]
                best_seed = seed

        if best_result is None:
            logger.error("All multi-start runs failed")
            return SolverResult(
                success=False,
                status="NO_SOLUTION",
                error_message="All multi-start runs failed",
                solve_time_seconds=total_time,
                multi_start_scores={s: -sum(t) for s, t in all_tuples.items()}
            )

        # Add multi-start metadata to best result
        # Convert tuples to scores for JSON serialization
        best_result.multi_start_scores = {s: -sum(t) for s, t in all_tuples.items()}
        best_result.solve_time_seconds = total_time

        logger.info(
            f"Multi-start complete: best_seed={best_seed}, "
            f"best_tuple={best_tuple}, "
            f"total_time={total_time:.2f}s, "
            f"runs_completed={len(all_tuples)}"
        )

        return best_result

    def _solve_with_seed(self, seed: int, time_limit: int) -> SolverResult:
        """
        Run a single solve with specific seed and time limit.

        IMPORTANT: This creates a NEW routing model for each run.
        OR-Tools models cannot be reused after solve.
        """
        import time
        start_time = time.time()

        try:
            # 1. Build data model (reuse stops/vehicles but fresh model)
            self._data = SolverDataModel(
                stops=self.stops,
                vehicles=self.vehicles,
                depots=self.depots,
                travel_time_provider=self.travel_time_provider,
                precedence_pairs=self.precedence_pairs,
                reference_time=datetime.now()
            ).build()

            # Validate data
            errors = self._data.validate()
            if errors:
                return SolverResult(
                    success=False,
                    status="ERROR",
                    error_message=f"Data validation failed: {errors}",
                    seed_used=seed
                )

            # 2. Create NEW routing model (cannot reuse!)
            self._manager = pywrapcp.RoutingIndexManager(
                self._data.num_nodes,
                self._data.num_vehicles,
                self._data.vehicle_starts,
                self._data.vehicle_ends
            )
            self._routing = pywrapcp.RoutingModel(self._manager)

            # 3. Add constraints
            constraint_config = ConstraintConfig(
                time_window_penalty=self.objectives.time_window_penalty,
                overtime_penalty=self.objectives.overtime_penalty
            )
            self._constraint_manager = ConstraintManager(
                routing=self._routing,
                manager=self._manager,
                data=self._data,
                config=constraint_config
            )
            self._constraint_manager.add_all_constraints()

            # 4. Set objective
            self._set_objective(self._constraint_manager)

            # 5. Allow dropping stops
            if self.config.allow_unassigned:
                self._allow_dropping_stops()

            # 6. Create search params with seed and time limit
            search_params = self._create_search_params(seed=seed, time_limit=time_limit)

            # 7. Solve
            solution = self._routing.SolveWithParameters(search_params)

            solve_time = time.time() - start_time

            # 8. Extract solution
            if solution:
                result = self._extract_solution(solution)
                result.solve_time_seconds = solve_time
                result.seed_used = seed
                return result
            else:
                return SolverResult(
                    success=False,
                    status="NO_SOLUTION",
                    solver_status=self._routing.status(),
                    solve_time_seconds=solve_time,
                    error_message="No feasible solution found",
                    seed_used=seed
                )

        except Exception as e:
            logger.exception(f"Solver error with seed {seed}")
            return SolverResult(
                success=False,
                status="ERROR",
                error_message=str(e),
                solve_time_seconds=time.time() - start_time,
                seed_used=seed
            )

    def _compute_kpi_tuple(self, result: SolverResult) -> tuple:
        """
        Compute lexicographic KPI tuple for solution comparison.

        P0: TRUE lexicographic ordering via tuple comparison.
        Lower values = better. Python tuple comparison is lexicographic.

        Priority order (most important first):
        1. unassigned_count - Coverage is king
        2. hard_tw_violations - Hard constraints must be satisfied
        3. overtime_minutes - Labor law compliance
        4. total_travel_minutes - Efficiency
        5. vehicles_used - Tie-breaker

        Returns:
            Tuple for comparison (lower = better)
        """
        # 1. Unassigned stops (fewer = better)
        unassigned = len(result.unassigned_stop_ids)

        # 2. Hard TW violations
        # DESIGN NOTE: Hard TWs use OR-Tools SetRange() which makes violations
        # INFEASIBLE (solver cannot produce such solutions). Therefore:
        # - hard_tw_violations is ALWAYS 0 for any valid solution
        # - This is correct behavior, not a placeholder
        # - The P1.2 disqualification filter is ready for future soft TW tracking
        # - Tests use mocked KPI tuples to verify filter logic independently
        hard_tw_violations = 0  # Hard TWs = infeasible, always 0 for valid solutions

        # 3. Overtime estimation
        # Approximate: total duration - (8h shift * vehicles)
        expected_shift_minutes = 8 * 60 * max(1, result.total_vehicles_used)
        overtime = max(0, result.total_duration_min - expected_shift_minutes)

        # 4. Total travel time
        travel = result.total_duration_min

        # 5. Vehicles used
        vehicles = result.total_vehicles_used

        return (unassigned, hard_tw_violations, overtime, travel, vehicles)

    def _is_solution_valid(self, result: SolverResult) -> bool:
        """
        Check if solution is valid for selection.

        A solution is INVALID if:
        - It failed to solve
        - It has hard constraint violations (future: track these)

        Returns:
            True if solution can be considered for best selection
        """
        if not result.success:
            return False

        # Future: Check for actual hard constraint violations
        # For now, all successful solutions are valid
        return True

    def _apply_disqualification_filters(
        self,
        all_results: Dict[int, SolverResult],
        all_tuples: Dict[int, tuple]
    ) -> tuple:
        """
        P1.2: Apply lexicographic disqualification rules.

        Rules (in order):
        1. If ANY solution has hard_tw_violations == 0, disqualify all with > 0
        2. If ANY solution has unassigned == 0, disqualify all with > 0

        This ensures we never pick a solution with violations if a clean solution exists.
        "Hard" really means "hard" - not just "penalized more".

        Args:
            all_results: Dict of seed -> SolverResult
            all_tuples: Dict of seed -> KPI tuple

        Returns:
            (filtered_results, filtered_tuples) after disqualification
        """
        if not all_tuples:
            return all_results, all_tuples

        # Tuple structure: (unassigned, hard_tw_violations, overtime, travel, vehicles)
        # Index 0 = unassigned, Index 1 = hard_tw_violations

        # Check if any solution has no hard TW violations
        has_clean_tw = any(t[1] == 0 for t in all_tuples.values())

        # Check if any solution has 100% coverage
        has_full_coverage = any(t[0] == 0 for t in all_tuples.values())

        filtered_results = {}
        filtered_tuples = {}
        disqualified_reasons: Dict[int, str] = {}

        for seed, kpi_tuple in all_tuples.items():
            unassigned = kpi_tuple[0]
            hard_tw = kpi_tuple[1]

            # Rule 1: Disqualify if has TW violations when clean exists
            if has_clean_tw and hard_tw > 0:
                disqualified_reasons[seed] = f"hard_tw_violations={hard_tw} (clean solution exists)"
                logger.info(f"P1.2: Seed {seed} disqualified: {disqualified_reasons[seed]}")
                continue

            # Rule 2: Disqualify if has unassigned when full coverage exists
            if has_full_coverage and unassigned > 0:
                disqualified_reasons[seed] = f"unassigned={unassigned} (full coverage exists)"
                logger.info(f"P1.2: Seed {seed} disqualified: {disqualified_reasons[seed]}")
                continue

            # Passed all filters
            filtered_results[seed] = all_results[seed]
            filtered_tuples[seed] = kpi_tuple

        logger.info(
            f"P1.2: Disqualification complete - {len(filtered_tuples)}/{len(all_tuples)} "
            f"candidates remain"
        )

        # If ALL were disqualified (shouldn't happen), fall back to original
        if not filtered_tuples:
            logger.warning("P1.2: All solutions disqualified, using original set")
            return all_results, all_tuples

        return filtered_results, filtered_tuples


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_solver(
    stops: List[Stop],
    vehicles: List[Vehicle],
    depots: List[Depot],
    travel_time_provider: TravelTimeProvider,
    vertical: str = "BALANCED",
    config: SolverConfig = None,
    precedence_pairs: List[PrecedencePair] = None,
    multi_start_config: MultiStartConfig = None
) -> VRPTWSolver:
    """
    Factory function to create a configured VRPTW solver.

    Args:
        stops: List of stops to route
        vehicles: List of available vehicles
        depots: List of depots (for Multi-Depot)
        travel_time_provider: Provider for travel times
        vertical: Vertical name for objective profile ("MEDIAMARKT" or "HDL_PLUS")
        config: Solver configuration
        precedence_pairs: P0 - Pickup/delivery precedence constraints
        multi_start_config: P0 - Multi-start best-of configuration

    Returns:
        Configured VRPTWSolver instance
    """
    return VRPTWSolver(
        stops=stops,
        vehicles=vehicles,
        depots=depots,
        travel_time_provider=travel_time_provider,
        config=config,
        vertical=vertical,
        precedence_pairs=precedence_pairs,
        multi_start_config=multi_start_config
    )
