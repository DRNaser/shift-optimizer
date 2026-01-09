# =============================================================================
# SOLVEREIGN Routing Pack - Solver Data Model
# =============================================================================
# Prepares input data for OR-Tools solver.
#
# Responsibilities:
# - Convert domain objects to solver indices
# - Build time/distance matrices
# - Prepare time windows, capacities, demands
# - Handle Multi-Depot node mapping (P0-1)
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import logging

from ...domain.models import Stop, Vehicle, Depot, PrecedencePair
from ..travel_time.provider import TravelTimeProvider, MatrixResult

logger = logging.getLogger(__name__)


@dataclass
class SolverDataModel:
    """
    Data model for OR-Tools VRPTW solver.

    Converts domain objects to solver-compatible format:
    - Nodes: [depot_0, depot_1, ..., stop_0, stop_1, ...]
    - Indices are used by OR-Tools, IDs are used by domain
    """

    # Input data
    stops: List[Stop]
    vehicles: List[Vehicle]
    depots: List[Depot]
    travel_time_provider: TravelTimeProvider

    # P0: Precedence constraints (pickup -> delivery pairs)
    precedence_pairs: List[PrecedencePair] = field(default_factory=list)

    # Reference time (for converting datetime to minutes)
    reference_time: datetime = field(default_factory=datetime.now)

    # Computed mappings (populated by build())
    _node_to_stop: Dict[int, Stop] = field(default_factory=dict)
    _node_to_depot: Dict[int, Depot] = field(default_factory=dict)
    _stop_id_to_node: Dict[str, int] = field(default_factory=dict)
    _depot_id_to_node: Dict[str, int] = field(default_factory=dict)
    _vehicle_id_to_index: Dict[str, int] = field(default_factory=dict)

    # P1.1: Multi-TW clone tracking
    _clone_to_base_stop: Dict[int, str] = field(default_factory=dict)      # clone_node -> base_stop_id
    _clone_to_window_idx: Dict[int, int] = field(default_factory=dict)     # clone_node -> window index
    _base_stop_clones: Dict[str, List[int]] = field(default_factory=dict)  # stop_id -> [clone_nodes]
    _node_to_location_idx: Dict[int, int] = field(default_factory=dict)    # node -> matrix location index

    # Matrices (populated by build())
    _time_matrix: List[List[int]] = field(default_factory=list)
    _distance_matrix: List[List[int]] = field(default_factory=list)

    # Vehicle start/end nodes for Multi-Depot (P0-1)
    _vehicle_starts: List[int] = field(default_factory=list)
    _vehicle_ends: List[int] = field(default_factory=list)

    _is_built: bool = False

    def build(self) -> "SolverDataModel":
        """
        Build the data model.

        Creates node mappings and computes travel matrices.
        Must be called before using the model with solver.
        """
        if self._is_built:
            logger.warning("Data model already built, rebuilding...")

        logger.info(f"Building data model: {len(self.depots)} depots, "
                   f"{len(self.stops)} stops, {len(self.vehicles)} vehicles")

        # P1.1: Validate no multi-TW stops in precedence pairs
        self._validate_no_multi_tw_in_precedence()

        # 1. Create node indices
        # Nodes: [depot_0, depot_1, ..., stop_0, stop_1, ...]
        node_index = 0

        # Add depots first
        for depot in self.depots:
            self._node_to_depot[node_index] = depot
            self._depot_id_to_node[depot.id] = node_index
            self._node_to_location_idx[node_index] = node_index  # Depots: location = node
            node_index += 1

        self._num_depot_nodes = node_index

        # Add stops (with P1.1 clone expansion for multi-TW)
        location_idx = len(self.depots)  # Matrix locations: depots then stops

        for stop in self.stops:
            windows = stop.get_time_windows()

            if len(windows) == 1:
                # Single TW: standard mapping (backwards compatible)
                self._node_to_stop[node_index] = stop
                self._stop_id_to_node[stop.id] = node_index
                self._node_to_location_idx[node_index] = location_idx
                node_index += 1
            else:
                # P1.1: Multi-TW - create clone nodes (one per time window)
                clone_nodes = []
                for tw_idx in range(len(windows)):
                    self._node_to_stop[node_index] = stop  # All clones point to same stop
                    self._clone_to_base_stop[node_index] = stop.id
                    self._clone_to_window_idx[node_index] = tw_idx
                    self._node_to_location_idx[node_index] = location_idx  # All clones share location
                    clone_nodes.append(node_index)
                    node_index += 1

                self._base_stop_clones[stop.id] = clone_nodes
                self._stop_id_to_node[stop.id] = clone_nodes[0]  # First clone for lookup
                logger.debug(f"P1.1: Created {len(clone_nodes)} clone nodes for stop {stop.id}")

            location_idx += 1  # One location per stop (clones share)

        self._total_nodes = node_index
        self._num_locations = location_idx  # Track actual matrix size

        # 2. Create vehicle index mapping
        for idx, vehicle in enumerate(self.vehicles):
            self._vehicle_id_to_index[vehicle.id] = idx

        # 3. Build vehicle start/end nodes (P0-1: Multi-Depot)
        self._vehicle_starts = []
        self._vehicle_ends = []

        for vehicle in self.vehicles:
            start_node = self._depot_id_to_node.get(vehicle.start_depot_id)
            end_node = self._depot_id_to_node.get(vehicle.end_depot_id)

            if start_node is None:
                raise ValueError(f"Vehicle {vehicle.id} references unknown start_depot_id: {vehicle.start_depot_id}")
            if end_node is None:
                raise ValueError(f"Vehicle {vehicle.id} references unknown end_depot_id: {vehicle.end_depot_id}")

            self._vehicle_starts.append(start_node)
            self._vehicle_ends.append(end_node)

        # 4. Build travel matrices
        self._build_matrices()

        self._is_built = True
        clone_count = sum(len(c) for c in self._base_stop_clones.values())
        logger.info(f"Data model built: {self._total_nodes} nodes ({clone_count} clones), "
                   f"{len(self._time_matrix)}x{len(self._time_matrix)} matrix")

        return self

    def _validate_no_multi_tw_in_precedence(self):
        """
        P1.1: Reject multi-TW stops in precedence pairs.

        Multi-time-windows for precedence stops require complex pairwise clone
        selection logic (P2/P3 scope). For P1, we reject this combination with
        a clear error message.
        """
        multi_tw_stops = {s.id for s in self.stops if s.has_multiple_time_windows()}

        if not multi_tw_stops:
            return  # No multi-TW stops, nothing to validate

        for pair in self.precedence_pairs:
            if pair.pickup_stop_id in multi_tw_stops:
                raise ValueError(
                    f"P1.1 BLOCKED: Precedence pickup '{pair.pickup_stop_id}' has multiple time windows. "
                    f"Multi-TW is not supported for pickup-delivery pairs. "
                    f"Provide a single time window or split into separate stops."
                )
            if pair.delivery_stop_id in multi_tw_stops:
                raise ValueError(
                    f"P1.1 BLOCKED: Precedence delivery '{pair.delivery_stop_id}' has multiple time windows. "
                    f"Multi-TW is not supported for pickup-delivery pairs. "
                    f"Provide a single time window or split into separate stops."
                )

    def _build_matrices(self):
        """Build time and distance matrices using travel time provider."""
        # Collect all locations (depots + stops)
        locations: List[Tuple[float, float]] = []

        # Add depot locations
        for depot in self.depots:
            locations.append(depot.geocode.to_tuple())

        # Add stop locations (use (0,0) for non-geocoded stops)
        for stop in self.stops:
            if stop.geocode:
                locations.append(stop.geocode.to_tuple())
            else:
                # Non-geocoded stop - will use fallback distance
                logger.warning(f"Stop {stop.id} not geocoded, using (0,0)")
                locations.append((0.0, 0.0))

        # Get matrix from provider
        matrix_result: MatrixResult = self.travel_time_provider.get_matrix(locations)

        self._time_matrix = matrix_result.time_matrix
        self._distance_matrix = matrix_result.distance_matrix

    # =========================================================================
    # Node Accessors
    # =========================================================================

    @property
    def num_nodes(self) -> int:
        """Total number of nodes (depots + stops)."""
        return self._total_nodes

    @property
    def num_depot_nodes(self) -> int:
        """Number of depot nodes."""
        return self._num_depot_nodes

    @property
    def num_vehicles(self) -> int:
        """Number of vehicles."""
        return len(self.vehicles)

    @property
    def vehicle_starts(self) -> List[int]:
        """Start node for each vehicle (P0-1: Multi-Depot)."""
        return self._vehicle_starts

    @property
    def vehicle_ends(self) -> List[int]:
        """End node for each vehicle (P0-1: Multi-Depot)."""
        return self._vehicle_ends

    @property
    def time_matrix(self) -> List[List[int]]:
        """Time matrix in seconds."""
        return self._time_matrix

    @property
    def distance_matrix(self) -> List[List[int]]:
        """Distance matrix in meters."""
        return self._distance_matrix

    def is_depot_node(self, node: int) -> bool:
        """Check if node is a depot."""
        return node in self._node_to_depot

    def is_stop_node(self, node: int) -> bool:
        """Check if node is a stop."""
        return node in self._node_to_stop

    def get_stop_for_node(self, node: int) -> Optional[Stop]:
        """Get stop for a node index."""
        return self._node_to_stop.get(node)

    def get_depot_for_node(self, node: int) -> Optional[Depot]:
        """Get depot for a node index."""
        return self._node_to_depot.get(node)

    def get_node_for_stop(self, stop_id: str) -> Optional[int]:
        """Get node index for a stop ID."""
        return self._stop_id_to_node.get(stop_id)

    def get_node_for_depot(self, depot_id: str) -> Optional[int]:
        """Get node index for a depot ID."""
        return self._depot_id_to_node.get(depot_id)

    def get_vehicle_index(self, vehicle_id: str) -> Optional[int]:
        """Get vehicle index for a vehicle ID."""
        return self._vehicle_id_to_index.get(vehicle_id)

    # =========================================================================
    # P1.1: Multi-TW Clone Accessors
    # =========================================================================

    def is_clone_node(self, node: int) -> bool:
        """P1.1: Check if node is a multi-TW clone."""
        return node in self._clone_to_base_stop

    def get_clone_nodes_for_stop(self, stop_id: str) -> Optional[List[int]]:
        """P1.1: Get all clone nodes for a multi-TW stop (None if single-TW)."""
        return self._base_stop_clones.get(stop_id)

    def get_base_stop_id(self, node: int) -> str:
        """
        P1.1: Get original stop ID for any node (clone or regular).

        For clone nodes, returns the base stop ID.
        For regular stop nodes, returns the stop's ID.
        For depot nodes, returns empty string.
        """
        if node in self._clone_to_base_stop:
            return self._clone_to_base_stop[node]
        stop = self._node_to_stop.get(node)
        return stop.id if stop else ""

    def get_selected_window_index(self, node: int) -> Optional[int]:
        """P1.1: Get which time window index this clone represents (None if not a clone)."""
        return self._clone_to_window_idx.get(node)

    def get_location_index(self, node: int) -> int:
        """
        P1.1: Get matrix location index for a node.

        Clone nodes share the same location index as their base stop,
        preventing matrix explosion. Regular nodes map directly.
        """
        return self._node_to_location_idx.get(node, node)

    @property
    def num_locations(self) -> int:
        """Number of unique locations (matrix size). May differ from num_nodes due to clones."""
        return getattr(self, '_num_locations', self._total_nodes)

    # =========================================================================
    # Time Window Helpers
    # =========================================================================

    def get_time_window(self, node: int) -> Tuple[int, int]:
        """
        Get time window for a node in minutes from reference time.

        Depots have infinite time windows (0, horizon).
        Stops have their tw_start/tw_end converted to minutes.

        P1.1: For clone nodes, returns the specific time window for that clone.
        """
        if self.is_depot_node(node):
            # Depot: open all day (use large horizon)
            return (0, 24 * 60)  # 0 to 1440 minutes

        stop = self._node_to_stop.get(node)
        if not stop:
            return (0, 24 * 60)

        # P1.1: Check if this is a clone node with specific window
        if node in self._clone_to_window_idx:
            tw_idx = self._clone_to_window_idx[node]
            tw = stop.get_time_windows()[tw_idx]
            return (max(0, self._datetime_to_minutes(tw.start)),
                    self._datetime_to_minutes(tw.end))

        # Legacy single TW (or first window for non-clone access)
        tw_start_min = self._datetime_to_minutes(stop.tw_start)
        tw_end_min = self._datetime_to_minutes(stop.tw_end)

        return (max(0, tw_start_min), tw_end_min)

    def get_service_time(self, node: int) -> int:
        """Get service time for a node in minutes."""
        if self.is_depot_node(node):
            depot = self._node_to_depot.get(node)
            return depot.loading_time_min if depot else 0

        stop = self._node_to_stop.get(node)
        return stop.service_duration_min if stop else 0

    def _datetime_to_minutes(self, dt: datetime) -> int:
        """Convert datetime to minutes from reference time."""
        delta = dt - self.reference_time
        return int(delta.total_seconds() / 60)

    # =========================================================================
    # Capacity Helpers
    # =========================================================================

    def get_demand(self, node: int) -> Tuple[float, float]:
        """
        Get demand (volume, weight) for a node.

        Returns (volume_m3, weight_kg) - can be NEGATIVE for deliveries!
        Depots have zero demand.

        CRITICAL for Pickup-Delivery:
        - Pickup (load_delta=+1): POSITIVE demand (adds to vehicle)
        - Delivery (load_delta=-1): NEGATIVE demand (removes from vehicle)

        This enables proper capacity tracking for precedence pairs.
        """
        if self.is_depot_node(node):
            return (0.0, 0.0)

        stop = self._node_to_stop.get(node)
        if not stop:
            return (0.0, 0.0)

        # load_delta: -1 = delivery (decreases vehicle load), +1 = pickup (increases)
        # CRITICAL: Do NOT use abs() here! Deliveries need negative demand.
        return (
            stop.volume_m3 * stop.load_delta,
            stop.weight_kg * stop.load_delta
        )

    def get_vehicle_capacity(self, vehicle_index: int) -> Tuple[float, float]:
        """Get vehicle capacity (volume, weight)."""
        if vehicle_index >= len(self.vehicles):
            return (0.0, 0.0)

        vehicle = self.vehicles[vehicle_index]
        return (
            vehicle.capacity_volume_m3 or float('inf'),
            vehicle.capacity_weight_kg or float('inf')
        )

    # =========================================================================
    # Skill Helpers
    # =========================================================================

    def get_required_skills(self, node: int) -> List[str]:
        """Get required skills for a node."""
        if self.is_depot_node(node):
            return []

        stop = self._node_to_stop.get(node)
        return stop.required_skills if stop else []

    def requires_two_person(self, node: int) -> bool:
        """Check if node requires 2-person team."""
        if self.is_depot_node(node):
            return False

        stop = self._node_to_stop.get(node)
        return stop.requires_two_person if stop else False

    def vehicle_has_skills(self, vehicle_index: int, skills: List[str]) -> bool:
        """Check if vehicle has all required skills."""
        if vehicle_index >= len(self.vehicles):
            return False

        vehicle = self.vehicles[vehicle_index]
        return all(skill in vehicle.skills for skill in skills)

    def vehicle_is_two_person(self, vehicle_index: int) -> bool:
        """Check if vehicle is 2-person team."""
        if vehicle_index >= len(self.vehicles):
            return False

        return self.vehicles[vehicle_index].team_size >= 2

    # =========================================================================
    # Validation
    # =========================================================================

    def validate(self) -> List[str]:
        """
        Validate the data model.

        Returns list of validation errors (empty if valid).
        """
        errors = []

        if not self._is_built:
            errors.append("Data model not built. Call build() first.")
            return errors

        # Check for non-geocoded stops
        non_geocoded = [s.id for s in self.stops if not s.geocode]
        if non_geocoded:
            errors.append(f"{len(non_geocoded)} stops not geocoded: {non_geocoded[:5]}...")

        # Check vehicle depot references
        for vehicle in self.vehicles:
            if vehicle.start_depot_id not in self._depot_id_to_node:
                errors.append(f"Vehicle {vehicle.id} has invalid start_depot_id: {vehicle.start_depot_id}")
            if vehicle.end_depot_id not in self._depot_id_to_node:
                errors.append(f"Vehicle {vehicle.id} has invalid end_depot_id: {vehicle.end_depot_id}")

        # Check matrix dimensions
        if len(self._time_matrix) != self._total_nodes:
            errors.append(f"Time matrix size mismatch: {len(self._time_matrix)} vs {self._total_nodes} nodes")

        # Validate precedence pairs
        for pair in self.precedence_pairs:
            # Check pickup exists as a STOP (not depot!)
            if pair.pickup_stop_id not in self._stop_id_to_node:
                # Check if it's accidentally a depot ID
                if pair.pickup_stop_id in self._depot_id_to_node:
                    errors.append(
                        f"Precedence pickup '{pair.pickup_stop_id}' is a DEPOT, not a stop! "
                        f"PrecedencePairs must reference stops only. For depot returns, "
                        f"create an explicit depot-stop node."
                    )
                else:
                    errors.append(f"Precedence pickup stop not found: {pair.pickup_stop_id}")

            # Check delivery exists as a STOP (not depot!)
            if pair.delivery_stop_id not in self._stop_id_to_node:
                if pair.delivery_stop_id in self._depot_id_to_node:
                    errors.append(
                        f"Precedence delivery '{pair.delivery_stop_id}' is a DEPOT, not a stop! "
                        f"PrecedencePairs must reference stops only. For depot returns, "
                        f"create an explicit depot-stop node."
                    )
                else:
                    errors.append(f"Precedence delivery stop not found: {pair.delivery_stop_id}")

        return errors

    # =========================================================================
    # P0: Precedence Helpers
    # =========================================================================

    def get_precedence_node_pairs(self) -> List[Tuple[int, int, PrecedencePair]]:
        """
        Get precedence pairs as (pickup_node, delivery_node, pair).

        CRITICAL: Returns NODE indices (not manager indices!).
        Caller must convert to manager indices via NodeToIndex().

        Returns:
            List of (pickup_node, delivery_node, original_pair)
        """
        result = []
        for pair in self.precedence_pairs:
            pickup_node = self._stop_id_to_node.get(pair.pickup_stop_id)
            delivery_node = self._stop_id_to_node.get(pair.delivery_stop_id)

            if pickup_node is None or delivery_node is None:
                logger.warning(f"Skipping invalid precedence pair: {pair.pickup_stop_id} -> {pair.delivery_stop_id}")
                continue

            result.append((pickup_node, delivery_node, pair))

        return result
