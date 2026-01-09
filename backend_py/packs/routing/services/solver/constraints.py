# =============================================================================
# SOLVEREIGN Routing Pack - Solver Constraints
# =============================================================================
# Constraint callbacks and dimension management for OR-Tools.
#
# Constraints:
# - Time Windows (hard/soft)
# - Capacity (volume, weight)
# - Skills
# - 2-Mann Teams
# - Vehicle Eligibility
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Callable, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from ortools.constraint_solver import pywrapcp
    from .data_model import SolverDataModel

logger = logging.getLogger(__name__)


@dataclass
class ConstraintConfig:
    """Configuration for constraint handling."""
    # Time constraints
    time_horizon_minutes: int = 24 * 60      # Default: 24 hours
    allow_waiting: bool = True                # Allow waiting at stops
    max_waiting_minutes: int = 60            # Max waiting time

    # Capacity constraints
    enable_volume_constraint: bool = True
    enable_weight_constraint: bool = True

    # Skill constraints
    enable_skill_constraint: bool = True
    enable_two_person_constraint: bool = True

    # P0: Precedence constraints
    enable_precedence_constraint: bool = True

    # Soft constraint penalties
    time_window_penalty: int = 100_000       # Per minute late
    overtime_penalty: int = 10_000           # Per minute overtime
    precedence_violation_penalty: int = 100_000  # For soft precedence


class ConstraintManager:
    """
    Manages all constraints for the VRPTW solver.

    Responsibilities:
    - Register transit callbacks
    - Add dimensions (Time, Capacity)
    - Configure constraint penalties
    - Handle vehicle eligibility (skills, 2-Mann)
    """

    def __init__(
        self,
        routing: "pywrapcp.RoutingModel",
        manager: "pywrapcp.RoutingIndexManager",
        data: "SolverDataModel",
        config: ConstraintConfig = None
    ):
        self.routing = routing
        self.manager = manager
        self.data = data
        self.config = config or ConstraintConfig()

        # Callback indices (for reference)
        self._time_callback_index: Optional[int] = None
        self._distance_callback_index: Optional[int] = None
        self._volume_callback_index: Optional[int] = None
        self._weight_callback_index: Optional[int] = None

        # IMPORTANT: Store callbacks as instance attributes to prevent garbage collection
        # OR-Tools callbacks must stay alive during solve
        self._callbacks: List[Callable] = []

    def add_all_constraints(self):
        """Add all constraints to the routing model."""
        logger.info("Adding constraints to routing model...")

        # 1. Time constraints (required for VRPTW)
        self.add_time_constraints()

        # 2. Distance (for objective)
        self.add_distance_callback()

        # 3. Capacity constraints
        if self.config.enable_volume_constraint or self.config.enable_weight_constraint:
            self.add_capacity_constraints()

        # 4. Vehicle eligibility (skills, 2-Mann)
        if self.config.enable_skill_constraint:
            self.add_skill_constraints()

        if self.config.enable_two_person_constraint:
            self.add_two_person_constraints()

        # 5. P0: Precedence constraints (Pickup -> Delivery)
        if self.config.enable_precedence_constraint:
            self.add_precedence_constraints()

        logger.info("All constraints added")

    # =========================================================================
    # Time Constraints
    # =========================================================================

    def add_time_constraints(self):
        """
        Add time window constraints.

        Creates:
        - Transit callback (travel time + service time)
        - Time dimension with windows
        """
        logger.debug("Adding time constraints...")

        def time_callback(from_index: int, to_index: int) -> int:
            """
            Calculate transit time from one node to another.

            Transit = travel_time + service_time_at_destination

            P1.1: Uses location mapping for clone nodes - clones share the same
            location in the travel matrix, preventing NxN matrix explosion.
            """
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)

            # P1.1: Map clone nodes to base location for matrix lookup
            from_loc = self.data.get_location_index(from_node)
            to_loc = self.data.get_location_index(to_node)

            # Travel time (in minutes)
            travel_seconds = self.data.time_matrix[from_loc][to_loc]
            travel_minutes = travel_seconds // 60

            # Service time at destination (in minutes)
            service_minutes = self.data.get_service_time(to_node)

            return travel_minutes + service_minutes

        # CRITICAL: Store callback to prevent garbage collection during solve
        self._callbacks.append(time_callback)

        # Register callback
        self._time_callback_index = self.routing.RegisterTransitCallback(time_callback)

        # Add Time dimension
        self.routing.AddDimension(
            self._time_callback_index,
            self.config.max_waiting_minutes,     # Allow waiting (slack)
            self.config.time_horizon_minutes,    # Max time per vehicle
            False,                                # Don't force start at zero
            "Time"
        )

        time_dimension = self.routing.GetDimensionOrDie("Time")

        # Set time windows for each stop node
        # P1.1: Iterates over all nodes (including clones) to set correct TW per clone
        for node in range(self.data.num_depot_nodes, self.data.num_nodes):
            stop = self.data.get_stop_for_node(node)
            if stop is None:
                continue

            index = self.manager.NodeToIndex(node)
            tw_start, tw_end = self.data.get_time_window(node)

            # P1.1: Determine if this TW is hard based on clone or stop setting
            if self.data.is_clone_node(node):
                tw_idx = self.data.get_selected_window_index(node)
                windows = stop.get_time_windows()
                is_hard = windows[tw_idx].is_hard if tw_idx is not None else stop.tw_is_hard
            else:
                is_hard = stop.tw_is_hard

            if is_hard:
                # Hard time window: must arrive within window
                time_dimension.CumulVar(index).SetRange(tw_start, tw_end)
            else:
                # Soft time window: penalty for violation
                time_dimension.SetCumulVarSoftUpperBound(
                    index,
                    tw_end,
                    self.config.time_window_penalty
                )

        # Set vehicle shift constraints
        for v_idx, vehicle in enumerate(self.data.vehicles):
            start_index = self.routing.Start(v_idx)
            end_index = self.routing.End(v_idx)

            # Shift start time
            shift_start = self.data._datetime_to_minutes(vehicle.shift_start_at)
            shift_end = self.data._datetime_to_minutes(vehicle.shift_end_at)

            # Vehicle must start within shift
            time_dimension.CumulVar(start_index).SetRange(shift_start, shift_end)

            # Vehicle must end within shift (with overtime penalty if exceeded)
            time_dimension.SetCumulVarSoftUpperBound(
                end_index,
                shift_end,
                self.config.overtime_penalty
            )

        logger.debug(f"Time constraints added: horizon={self.config.time_horizon_minutes}min")

    # =========================================================================
    # Distance Callback
    # =========================================================================

    def add_distance_callback(self):
        """Add distance callback for objective function."""

        def distance_callback(from_index: int, to_index: int) -> int:
            """
            Calculate distance in meters.

            P1.1: Uses location mapping for clone nodes.
            """
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)

            # P1.1: Map clone nodes to base location for matrix lookup
            from_loc = self.data.get_location_index(from_node)
            to_loc = self.data.get_location_index(to_node)

            return self.data.distance_matrix[from_loc][to_loc]

        # CRITICAL: Store callback to prevent garbage collection during solve
        self._callbacks.append(distance_callback)

        self._distance_callback_index = self.routing.RegisterTransitCallback(distance_callback)

        # Add Distance dimension (for tracking, not as constraint)
        self.routing.AddDimension(
            self._distance_callback_index,
            0,                    # No slack
            100_000_000,          # Max distance (100,000 km)
            True,                 # Start at zero
            "Distance"
        )

        logger.debug("Distance callback added")

    # =========================================================================
    # Capacity Constraints
    # =========================================================================

    def add_capacity_constraints(self):
        """Add capacity constraints (volume, weight)."""
        logger.debug("Adding capacity constraints...")

        if self.config.enable_volume_constraint:
            self._add_volume_constraint()

        if self.config.enable_weight_constraint:
            self._add_weight_constraint()

    def _add_volume_constraint(self):
        """Add volume capacity constraint."""

        def volume_callback(index: int) -> int:
            """Get volume demand at a node (in liters for precision)."""
            node = self.manager.IndexToNode(index)
            volume, _ = self.data.get_demand(node)
            return int(volume * 1000)  # Convert m³ to liters

        # CRITICAL: Store callback to prevent garbage collection during solve
        self._callbacks.append(volume_callback)

        self._volume_callback_index = self.routing.RegisterUnaryTransitCallback(volume_callback)

        # Get vehicle capacities
        vehicle_capacities = []
        for v_idx in range(self.data.num_vehicles):
            volume, _ = self.data.get_vehicle_capacity(v_idx)
            if volume == float('inf'):
                vehicle_capacities.append(1_000_000_000)  # Very large
            else:
                vehicle_capacities.append(int(volume * 1000))  # Convert m³ to liters

        self.routing.AddDimensionWithVehicleCapacity(
            self._volume_callback_index,
            0,                    # No slack
            vehicle_capacities,   # Per-vehicle capacity
            True,                 # Start at zero
            "Volume"
        )

        logger.debug("Volume constraint added")

    def _add_weight_constraint(self):
        """Add weight capacity constraint."""

        def weight_callback(index: int) -> int:
            """Get weight demand at a node (in grams for precision)."""
            node = self.manager.IndexToNode(index)
            _, weight = self.data.get_demand(node)
            return int(weight * 1000)  # Convert kg to grams

        # CRITICAL: Store callback to prevent garbage collection during solve
        self._callbacks.append(weight_callback)

        self._weight_callback_index = self.routing.RegisterUnaryTransitCallback(weight_callback)

        # Get vehicle capacities
        vehicle_capacities = []
        for v_idx in range(self.data.num_vehicles):
            _, weight = self.data.get_vehicle_capacity(v_idx)
            if weight == float('inf'):
                vehicle_capacities.append(1_000_000_000)  # Very large
            else:
                vehicle_capacities.append(int(weight * 1000))  # Convert kg to grams

        self.routing.AddDimensionWithVehicleCapacity(
            self._weight_callback_index,
            0,
            vehicle_capacities,
            True,
            "Weight"
        )

        logger.debug("Weight constraint added")

    # =========================================================================
    # Skill Constraints
    # =========================================================================

    def add_skill_constraints(self):
        """
        Add skill-based vehicle eligibility constraints.

        Stops with required skills can only be served by vehicles with those skills.
        P1.1: Applies to all nodes including clones (clones inherit stop's skills).
        """
        logger.debug("Adding skill constraints...")

        # P1.1: Iterate over all stop nodes (including clones)
        for node in range(self.data.num_depot_nodes, self.data.num_nodes):
            stop = self.data.get_stop_for_node(node)
            if stop is None or not stop.required_skills:
                continue

            index = self.manager.NodeToIndex(node)

            # Find eligible vehicles
            eligible = []
            for v_idx in range(self.data.num_vehicles):
                if self.data.vehicle_has_skills(v_idx, stop.required_skills):
                    eligible.append(v_idx)

            if eligible:
                self.routing.SetAllowedVehiclesForIndex(eligible, index)
                logger.debug(f"Node {node} (stop {stop.id}) requires {stop.required_skills}, "
                           f"eligible vehicles: {eligible}")
            else:
                logger.warning(f"No vehicle can serve stop {stop.id} "
                             f"(requires {stop.required_skills})")

    def add_two_person_constraints(self):
        """
        Add 2-Mann team constraints.

        Stops requiring 2-person teams can only be served by 2-person vehicles.
        P1.1: Applies to all nodes including clones (clones inherit stop's 2-Mann requirement).
        """
        logger.debug("Adding 2-Mann team constraints...")

        # P1.1: Iterate over all stop nodes (including clones)
        for node in range(self.data.num_depot_nodes, self.data.num_nodes):
            stop = self.data.get_stop_for_node(node)
            if stop is None or not stop.requires_two_person:
                continue

            index = self.manager.NodeToIndex(node)

            # Find eligible vehicles (team_size >= 2)
            eligible = []
            for v_idx in range(self.data.num_vehicles):
                if self.data.vehicle_is_two_person(v_idx):
                    eligible.append(v_idx)

            if eligible:
                self.routing.SetAllowedVehiclesForIndex(eligible, index)
                logger.debug(f"Node {node} (stop {stop.id}) requires 2-Mann, "
                           f"eligible vehicles: {eligible}")
            else:
                logger.warning(f"No 2-Mann team available for stop {stop.id}")

    # =========================================================================
    # P0: Precedence Constraints (Pickup -> Delivery)
    # =========================================================================

    def add_precedence_constraints(self):
        """
        Add precedence constraints for pickup-delivery pairs.

        Uses OR-Tools:
        - AddPickupAndDelivery: Ensures both visited or both dropped
        - VehicleVar equality: Same vehicle serves both
        - Time CumulVar ordering: Pickup before delivery
        - Optional max_lag: Maximum time between pickup and delivery

        CRITICAL DISTINCTIONS:
        - "Exchange at same customer" (Altgeräte) is NOT a precedence pair!
          Exchange = service time + capacity (device out = -1, device in = +1)
        - Precedence = Pickup THEN Delivery at DIFFERENT locations

        IMPORTANT:
        - pickup_index/delivery_index are MANAGER indices (from NodeToIndex)
        - pickup_node/delivery_node are DATA MODEL node numbers
        """
        pairs = self.data.get_precedence_node_pairs()
        if not pairs:
            logger.debug("No precedence pairs to add")
            return

        logger.debug(f"Adding {len(pairs)} precedence constraints...")

        # Get time dimension for time ordering
        time_dimension = self.routing.GetDimensionOrDie("Time")
        solver = self.routing.solver()

        for pickup_node, delivery_node, pair in pairs:
            # CRITICAL: Convert NODE to MANAGER INDEX
            pickup_index = self.manager.NodeToIndex(pickup_node)
            delivery_index = self.manager.NodeToIndex(delivery_node)

            # 1. Add pickup-delivery relationship
            # This ensures: both visited OR both dropped
            self.routing.AddPickupAndDelivery(pickup_index, delivery_index)

            # 2. Same vehicle constraint (if required)
            if pair.same_vehicle:
                solver.Add(
                    self.routing.VehicleVar(pickup_index) ==
                    self.routing.VehicleVar(delivery_index)
                )

            # 3. Time ordering: pickup BEFORE delivery
            # NOTE: CumulVar already includes service time via time_callback!
            # time_callback(from, to) = travel(from, to) + service(to)
            # So CumulVar(pickup) = arrival_at_pickup + service_at_pickup
            # This constraint ensures: finish_pickup <= finish_delivery
            solver.Add(
                time_dimension.CumulVar(pickup_index) <=
                time_dimension.CumulVar(delivery_index)
            )

            # 4. Optional max_lag constraint
            if pair.max_lag_seconds is not None:
                max_lag_minutes = pair.max_lag_seconds // 60
                if pair.is_hard:
                    # Hard constraint: must deliver within max_lag
                    solver.Add(
                        time_dimension.CumulVar(delivery_index) <=
                        time_dimension.CumulVar(pickup_index) + max_lag_minutes
                    )
                else:
                    # Soft constraint: penalty for exceeding max_lag
                    # Note: Soft max_lag is harder to implement in OR-Tools
                    # For now, log warning and skip
                    logger.warning(
                        f"Soft max_lag not implemented for pair "
                        f"{pair.pickup_stop_id} -> {pair.delivery_stop_id}"
                    )

            logger.debug(
                f"Precedence added: {pair.pickup_stop_id} -> {pair.delivery_stop_id} "
                f"(same_vehicle={pair.same_vehicle}, max_lag={pair.max_lag_seconds}s)"
            )

        logger.info(f"Added {len(pairs)} precedence constraints")

    # =========================================================================
    # Accessors
    # =========================================================================

    @property
    def time_callback_index(self) -> Optional[int]:
        return self._time_callback_index

    @property
    def distance_callback_index(self) -> Optional[int]:
        return self._distance_callback_index
