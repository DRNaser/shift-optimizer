# =============================================================================
# SOLVEREIGN Routing Pack - Gate 6: Freeze Lock Enforcer
# =============================================================================
# Hard enforcement of freeze-locks from database.
#
# Gate 6 Requirements:
# - freeze scope muss wirklich Stop-Locks erzwingen (nicht nur Empfehlung)
# - Bei Repair: erst aus DB laden welche Stops locked sind
# - Dann die locked_stop_ids HARD an Solver übergeben
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class FreezeLockViolationError(Exception):
    """Raised when a freeze-locked stop is illegally modified."""

    def __init__(
        self,
        message: str,
        stop_id: str,
        lock_reason: str,
        attempted_action: str,
    ):
        super().__init__(message)
        self.stop_id = stop_id
        self.lock_reason = lock_reason
        self.attempted_action = attempted_action


class FreezeLockEnforcementError(Exception):
    """Raised when freeze-lock enforcement fails."""
    pass


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class FreezeLockRecord:
    """
    Database record for a frozen stop/assignment.

    This represents the is_locked flag on routing_assignments or
    a computed freeze based on time horizon.
    """
    stop_id: str
    vehicle_id: str                       # Current vehicle (MUST stay here)
    sequence_index: int                   # Current sequence (MUST stay here)
    lock_source: str                      # DB_FLAG | TIME_HORIZON | MANUAL
    lock_reason: str
    locked_at: datetime
    locked_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_id": self.stop_id,
            "vehicle_id": self.vehicle_id,
            "sequence_index": self.sequence_index,
            "lock_source": self.lock_source,
            "lock_reason": self.lock_reason,
            "locked_at": self.locked_at.isoformat(),
            "locked_by": self.locked_by,
        }


@dataclass
class FreezeLockState:
    """
    Complete freeze-lock state for a repair operation.

    This is loaded from DB BEFORE any repair starts.
    """
    plan_id: str
    frozen_stops: Dict[str, FreezeLockRecord]  # stop_id -> record
    frozen_vehicles: Set[str]                   # vehicle_ids that cannot receive new stops
    freeze_horizon_minutes: int = 60            # Time-based freeze window
    computed_at: datetime = field(default_factory=datetime.now)

    @property
    def frozen_stop_ids(self) -> Set[str]:
        return set(self.frozen_stops.keys())

    @property
    def stop_vehicle_map(self) -> Dict[str, str]:
        """Map of stop_id -> required vehicle_id."""
        return {
            stop_id: record.vehicle_id
            for stop_id, record in self.frozen_stops.items()
        }

    @property
    def stop_sequence_map(self) -> Dict[str, int]:
        """Map of stop_id -> required sequence_index."""
        return {
            stop_id: record.sequence_index
            for stop_id, record in self.frozen_stops.items()
        }

    def is_stop_frozen(self, stop_id: str) -> bool:
        return stop_id in self.frozen_stops

    def get_lock_record(self, stop_id: str) -> Optional[FreezeLockRecord]:
        return self.frozen_stops.get(stop_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "frozen_stops": {
                k: v.to_dict() for k, v in self.frozen_stops.items()
            },
            "frozen_vehicles": list(self.frozen_vehicles),
            "freeze_horizon_minutes": self.freeze_horizon_minutes,
            "computed_at": self.computed_at.isoformat(),
            "total_frozen_stops": len(self.frozen_stops),
        }


@dataclass
class EnforcementResult:
    """Result of freeze-lock enforcement check."""
    passed: bool
    violations: List[Dict[str, Any]]
    frozen_stops_preserved: int
    total_frozen_stops: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "frozen_stops_preserved": self.frozen_stops_preserved,
            "total_frozen_stops": self.total_frozen_stops,
        }


# =============================================================================
# FREEZE LOCK LOADER (Simulated DB)
# =============================================================================

class FreezeLockLoader:
    """
    Loads freeze-lock state from database.

    Gate 6: MUST load from DB before any repair operation.

    In production, this queries:
    1. routing_assignments WHERE is_locked = TRUE
    2. routing_assignments WHERE arrival_at < NOW() + freeze_horizon
    3. Any explicit freeze_windows entries
    """

    def __init__(self, freeze_horizon_minutes: int = 60):
        """
        Initialize freeze lock loader.

        Args:
            freeze_horizon_minutes: Default freeze horizon (minutes before arrival)
        """
        self.freeze_horizon_minutes = freeze_horizon_minutes

    def load_from_assignments(
        self,
        plan_id: str,
        assignments: List[Dict],
        reference_time: Optional[datetime] = None,
    ) -> FreezeLockState:
        """
        Load freeze-lock state from assignment data.

        This is the Gate 6 implementation:
        1. Load ALL assignments with is_locked=TRUE from DB
        2. Compute time-based freezes (within freeze_horizon)
        3. Return complete FreezeLockState

        Args:
            plan_id: The plan being repaired
            assignments: Current assignments from DB
            reference_time: Time to use for freeze calculation (default: now)

        Returns:
            FreezeLockState with all frozen stops
        """
        reference_time = reference_time or datetime.now()
        freeze_cutoff = reference_time + timedelta(minutes=self.freeze_horizon_minutes)

        frozen_stops: Dict[str, FreezeLockRecord] = {}
        frozen_vehicles: Set[str] = set()

        for assignment in assignments:
            stop_id = assignment.get("stop_id")
            vehicle_id = assignment.get("vehicle_id")
            sequence_index = assignment.get("sequence_index", 0)
            is_locked = assignment.get("is_locked", False)
            arrival_at = assignment.get("arrival_at")

            if not stop_id or not vehicle_id:
                continue

            # Parse arrival_at if string
            if isinstance(arrival_at, str):
                try:
                    arrival_at = datetime.fromisoformat(arrival_at.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    arrival_at = None

            # Check if frozen
            lock_source = None
            lock_reason = None

            if is_locked:
                # Explicit DB lock
                lock_source = "DB_FLAG"
                lock_reason = "Assignment marked as locked in database"
            elif arrival_at and arrival_at <= freeze_cutoff:
                # Time-based freeze
                lock_source = "TIME_HORIZON"
                minutes_until = int((arrival_at - reference_time).total_seconds() / 60)
                lock_reason = f"Arrival in {minutes_until} minutes (within {self.freeze_horizon_minutes}min freeze horizon)"

            if lock_source:
                frozen_stops[stop_id] = FreezeLockRecord(
                    stop_id=stop_id,
                    vehicle_id=vehicle_id,
                    sequence_index=sequence_index,
                    lock_source=lock_source,
                    lock_reason=lock_reason,
                    locked_at=reference_time,
                )

        return FreezeLockState(
            plan_id=plan_id,
            frozen_stops=frozen_stops,
            frozen_vehicles=frozen_vehicles,
            freeze_horizon_minutes=self.freeze_horizon_minutes,
            computed_at=reference_time,
        )

    def add_manual_locks(
        self,
        state: FreezeLockState,
        stop_ids: Set[str],
        vehicle_map: Dict[str, str],
        sequence_map: Dict[str, int],
        locked_by: str = "manual",
    ) -> FreezeLockState:
        """
        Add manual freeze-locks to existing state.

        Args:
            state: Existing freeze-lock state
            stop_ids: Stop IDs to lock
            vehicle_map: stop_id -> vehicle_id mapping
            sequence_map: stop_id -> sequence_index mapping
            locked_by: Who is adding the lock

        Returns:
            Updated FreezeLockState
        """
        now = datetime.now()

        for stop_id in stop_ids:
            if stop_id not in state.frozen_stops:
                vehicle_id = vehicle_map.get(stop_id, "")
                sequence_index = sequence_map.get(stop_id, 0)

                state.frozen_stops[stop_id] = FreezeLockRecord(
                    stop_id=stop_id,
                    vehicle_id=vehicle_id,
                    sequence_index=sequence_index,
                    lock_source="MANUAL",
                    lock_reason=f"Manually locked by {locked_by}",
                    locked_at=now,
                    locked_by=locked_by,
                )

        return state


# =============================================================================
# FREEZE LOCK ENFORCER
# =============================================================================

class FreezeLockEnforcer:
    """
    Hard enforcement of freeze-locks.

    Gate 6: This is NOT a recommendation - it's a HARD GATE.

    Any repair that violates freeze-locks MUST be rejected.

    Usage:
        loader = FreezeLockLoader(freeze_horizon_minutes=60)
        enforcer = FreezeLockEnforcer()

        # 1. Load freeze state from DB BEFORE repair
        freeze_state = loader.load_from_assignments(
            plan_id="plan_001",
            assignments=current_assignments,
        )

        # 2. After repair, enforce freeze-locks
        result = enforcer.enforce(
            freeze_state=freeze_state,
            new_assignments=repaired_assignments,
        )

        if not result.passed:
            raise FreezeLockEnforcementError(f"Violations: {result.violations}")
    """

    def enforce(
        self,
        freeze_state: FreezeLockState,
        new_assignments: List[Dict],
        raise_on_violation: bool = True,
    ) -> EnforcementResult:
        """
        Enforce freeze-locks on repair result.

        This is the HARD GATE:
        - Frozen stops MUST remain on same vehicle
        - Frozen stops MUST remain at same sequence
        - Any violation = REJECT repair

        Args:
            freeze_state: Freeze-lock state loaded from DB
            new_assignments: New assignments from repair
            raise_on_violation: If True, raise exception on violation

        Returns:
            EnforcementResult

        Raises:
            FreezeLockViolationError: If raise_on_violation and any violation found
        """
        violations: List[Dict[str, Any]] = []
        preserved_count = 0

        # Build lookup for new assignments
        new_by_stop: Dict[str, Dict] = {
            a["stop_id"]: a for a in new_assignments
        }

        for stop_id, lock_record in freeze_state.frozen_stops.items():
            new_assignment = new_by_stop.get(stop_id)

            if not new_assignment:
                # Frozen stop is missing from new assignments!
                violation = {
                    "stop_id": stop_id,
                    "violation_type": "FROZEN_STOP_REMOVED",
                    "expected_vehicle": lock_record.vehicle_id,
                    "expected_sequence": lock_record.sequence_index,
                    "actual_vehicle": None,
                    "actual_sequence": None,
                    "lock_source": lock_record.lock_source,
                    "lock_reason": lock_record.lock_reason,
                }
                violations.append(violation)

                if raise_on_violation:
                    raise FreezeLockViolationError(
                        message=f"Gate 6 HARD VIOLATION: Frozen stop {stop_id} was removed from assignments",
                        stop_id=stop_id,
                        lock_reason=lock_record.lock_reason,
                        attempted_action="REMOVE",
                    )
                continue

            new_vehicle = new_assignment.get("vehicle_id")
            new_sequence = new_assignment.get("sequence_index")

            # Check vehicle unchanged
            if new_vehicle != lock_record.vehicle_id:
                violation = {
                    "stop_id": stop_id,
                    "violation_type": "VEHICLE_CHANGED",
                    "expected_vehicle": lock_record.vehicle_id,
                    "expected_sequence": lock_record.sequence_index,
                    "actual_vehicle": new_vehicle,
                    "actual_sequence": new_sequence,
                    "lock_source": lock_record.lock_source,
                    "lock_reason": lock_record.lock_reason,
                }
                violations.append(violation)

                if raise_on_violation:
                    raise FreezeLockViolationError(
                        message=(
                            f"Gate 6 HARD VIOLATION: Frozen stop {stop_id} moved from "
                            f"vehicle {lock_record.vehicle_id} to {new_vehicle}"
                        ),
                        stop_id=stop_id,
                        lock_reason=lock_record.lock_reason,
                        attempted_action=f"MOVE_VEHICLE:{lock_record.vehicle_id}->{new_vehicle}",
                    )
                continue

            # Check sequence unchanged
            if new_sequence != lock_record.sequence_index:
                violation = {
                    "stop_id": stop_id,
                    "violation_type": "SEQUENCE_CHANGED",
                    "expected_vehicle": lock_record.vehicle_id,
                    "expected_sequence": lock_record.sequence_index,
                    "actual_vehicle": new_vehicle,
                    "actual_sequence": new_sequence,
                    "lock_source": lock_record.lock_source,
                    "lock_reason": lock_record.lock_reason,
                }
                violations.append(violation)

                if raise_on_violation:
                    raise FreezeLockViolationError(
                        message=(
                            f"Gate 6 HARD VIOLATION: Frozen stop {stop_id} sequence changed from "
                            f"{lock_record.sequence_index} to {new_sequence}"
                        ),
                        stop_id=stop_id,
                        lock_reason=lock_record.lock_reason,
                        attempted_action=f"RESEQUENCE:{lock_record.sequence_index}->{new_sequence}",
                    )
                continue

            # Stop is correctly preserved
            preserved_count += 1

        passed = len(violations) == 0

        logger.info(
            f"Freeze-lock enforcement: {'PASSED' if passed else 'FAILED'} "
            f"({preserved_count}/{len(freeze_state.frozen_stops)} preserved)"
        )

        return EnforcementResult(
            passed=passed,
            violations=violations,
            frozen_stops_preserved=preserved_count,
            total_frozen_stops=len(freeze_state.frozen_stops),
        )

    def get_solver_constraints(
        self,
        freeze_state: FreezeLockState,
        stop_to_node: Dict[str, int],
        vehicle_to_idx: Dict[str, int],
    ) -> List[Tuple[int, List[int]]]:
        """
        Generate OR-Tools constraints for frozen stops.

        Gate 6: These constraints MUST be passed to solver.

        Returns list of (node_index, [allowed_vehicle_idx]) tuples
        for use with SetAllowedVehiclesForIndex.

        Args:
            freeze_state: Freeze-lock state
            stop_to_node: Mapping from stop_id to OR-Tools node index
            vehicle_to_idx: Mapping from vehicle_id to OR-Tools vehicle index

        Returns:
            List of (node_idx, [vehicle_idx]) constraints
        """
        constraints = []

        for stop_id, lock_record in freeze_state.frozen_stops.items():
            if stop_id not in stop_to_node:
                continue
            if lock_record.vehicle_id not in vehicle_to_idx:
                continue

            node_idx = stop_to_node[stop_id]
            vehicle_idx = vehicle_to_idx[lock_record.vehicle_id]

            # Frozen stop can ONLY be assigned to its current vehicle
            constraints.append((node_idx, [vehicle_idx]))

        return constraints


# =============================================================================
# INTEGRATION WITH REPAIR ENGINE
# =============================================================================

def load_and_enforce_freeze_locks(
    plan_id: str,
    original_assignments: List[Dict],
    new_assignments: List[Dict],
    freeze_horizon_minutes: int = 60,
    reference_time: Optional[datetime] = None,
) -> Tuple[FreezeLockState, EnforcementResult]:
    """
    Complete Gate 6 workflow: Load from DB + Enforce.

    This is the main entry point for Gate 6 integration.

    Args:
        plan_id: Plan being repaired
        original_assignments: Assignments BEFORE repair
        new_assignments: Assignments AFTER repair
        freeze_horizon_minutes: Freeze horizon
        reference_time: Reference time for freeze calculation

    Returns:
        (FreezeLockState, EnforcementResult)

    Raises:
        FreezeLockViolationError: If any violation found
    """
    # 1. Load freeze state from original assignments (simulating DB)
    loader = FreezeLockLoader(freeze_horizon_minutes=freeze_horizon_minutes)
    freeze_state = loader.load_from_assignments(
        plan_id=plan_id,
        assignments=original_assignments,
        reference_time=reference_time,
    )

    logger.info(
        f"Gate 6: Loaded {len(freeze_state.frozen_stops)} frozen stops "
        f"from plan {plan_id}"
    )

    # 2. Enforce on new assignments
    enforcer = FreezeLockEnforcer()
    result = enforcer.enforce(
        freeze_state=freeze_state,
        new_assignments=new_assignments,
        raise_on_violation=True,  # HARD enforcement
    )

    return freeze_state, result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_repair_respects_freeze(
    plan_id: str,
    original_assignments: List[Dict],
    repaired_assignments: List[Dict],
    freeze_horizon_minutes: int = 60,
) -> bool:
    """
    Validate that a repair operation respects all freeze-locks.

    Returns True if valid, raises FreezeLockViolationError if not.

    This is the Gate 6 validation function to call after EVERY repair.
    """
    try:
        load_and_enforce_freeze_locks(
            plan_id=plan_id,
            original_assignments=original_assignments,
            new_assignments=repaired_assignments,
            freeze_horizon_minutes=freeze_horizon_minutes,
        )
        return True
    except FreezeLockViolationError:
        raise
