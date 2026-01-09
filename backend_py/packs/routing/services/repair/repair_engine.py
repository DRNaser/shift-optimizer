# =============================================================================
# SOLVEREIGN Routing Pack - Repair Engine
# =============================================================================
# Churn-aware route repair for operational changes.
#
# Repair Events:
# - NO_SHOW: Customer not available
# - DELAY: Vehicle running late
# - VEHICLE_DOWN: Vehicle breakdown
# - STOP_ADDED: Emergency stop added
# - STOP_REMOVED: Stop cancelled
# - TIME_WINDOW_CHANGE: Customer requests TW change
#
# Churn Penalties:
# - Stop moved to different vehicle: HIGH cost
# - Stop sequence changed on same vehicle: MEDIUM cost
# - Stop removed from route: depends on reason
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class RepairEventType(str, Enum):
    """Types of repair events."""
    NO_SHOW = "NO_SHOW"                    # Customer not available
    DELAY = "DELAY"                        # Vehicle running late
    VEHICLE_DOWN = "VEHICLE_DOWN"          # Vehicle breakdown
    STOP_ADDED = "STOP_ADDED"              # Emergency stop added
    STOP_REMOVED = "STOP_REMOVED"          # Stop cancelled
    TIME_WINDOW_CHANGE = "TIME_WINDOW_CHANGE"  # TW modification


class RepairStatus(str, Enum):
    """Repair result status."""
    SUCCESS = "SUCCESS"                    # Repair successful
    PARTIAL = "PARTIAL"                    # Some stops unassigned
    FAILED = "FAILED"                      # Repair failed


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ChurnConfig:
    """Configuration for churn penalties."""
    # Penalty for moving stop to different vehicle
    vehicle_change_penalty: int = 10000

    # Penalty for changing sequence on same vehicle
    sequence_change_penalty: int = 1000

    # Penalty for stop becoming unassigned
    unassigned_penalty: int = 100000

    # Maximum allowed churn score (if exceeded, reject repair)
    max_churn_score: Optional[int] = None

    # Bonus for keeping stop on same vehicle
    same_vehicle_bonus: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_change_penalty": self.vehicle_change_penalty,
            "sequence_change_penalty": self.sequence_change_penalty,
            "unassigned_penalty": self.unassigned_penalty,
            "max_churn_score": self.max_churn_score,
            "same_vehicle_bonus": self.same_vehicle_bonus,
        }


@dataclass
class FreezeScope:
    """Defines which stops are frozen (cannot be moved)."""
    # Stop IDs that are locked (already started, confirmed, etc.)
    locked_stop_ids: Set[str] = field(default_factory=set)

    # Vehicle IDs that are locked (e.g., already dispatched)
    locked_vehicle_ids: Set[str] = field(default_factory=set)

    # Freeze horizon (minutes before stop start that freezes it)
    freeze_horizon_min: int = 60

    # Timestamp to use for freeze calculation (default: now)
    freeze_at: Optional[datetime] = None

    def is_stop_frozen(
        self,
        stop_id: str,
        arrival_at: Optional[datetime] = None
    ) -> bool:
        """Check if a stop is frozen."""
        # Explicitly locked
        if stop_id in self.locked_stop_ids:
            return True

        # Check time-based freeze
        if arrival_at and self.freeze_horizon_min > 0:
            freeze_time = self.freeze_at or datetime.now()
            freeze_cutoff = freeze_time + timedelta(minutes=self.freeze_horizon_min)
            if arrival_at <= freeze_cutoff:
                return True

        return False

    def is_vehicle_frozen(self, vehicle_id: str) -> bool:
        """Check if a vehicle is frozen (cannot accept new stops)."""
        return vehicle_id in self.locked_vehicle_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "locked_stop_ids": list(self.locked_stop_ids),
            "locked_vehicle_ids": list(self.locked_vehicle_ids),
            "freeze_horizon_min": self.freeze_horizon_min,
            "freeze_at": self.freeze_at.isoformat() if self.freeze_at else None,
        }


@dataclass
class RepairEvent:
    """Describes a repair event that triggered re-optimization."""
    event_type: RepairEventType
    timestamp: datetime = field(default_factory=datetime.now)

    # Affected entities
    stop_id: Optional[str] = None          # For NO_SHOW, STOP_REMOVED, etc.
    vehicle_id: Optional[str] = None       # For VEHICLE_DOWN, DELAY
    delay_minutes: Optional[int] = None    # For DELAY events

    # New values (for changes)
    new_time_window: Optional[Tuple[datetime, datetime]] = None  # For TW_CHANGE
    new_stop_data: Optional[Dict] = None   # For STOP_ADDED

    # Notes
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "stop_id": self.stop_id,
            "vehicle_id": self.vehicle_id,
            "delay_minutes": self.delay_minutes,
            "new_time_window": [
                tw.isoformat() for tw in self.new_time_window
            ] if self.new_time_window else None,
            "reason": self.reason,
        }


@dataclass
class StopDiff:
    """Difference for a single stop between original and repaired plan."""
    stop_id: str
    original_vehicle_id: Optional[str]
    new_vehicle_id: Optional[str]
    original_sequence: Optional[int]
    new_sequence: Optional[int]
    vehicle_changed: bool
    sequence_changed: bool
    became_unassigned: bool
    became_assigned: bool
    churn_cost: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_id": self.stop_id,
            "original_vehicle_id": self.original_vehicle_id,
            "new_vehicle_id": self.new_vehicle_id,
            "original_sequence": self.original_sequence,
            "new_sequence": self.new_sequence,
            "vehicle_changed": self.vehicle_changed,
            "sequence_changed": self.sequence_changed,
            "became_unassigned": self.became_unassigned,
            "became_assigned": self.became_assigned,
            "churn_cost": self.churn_cost,
        }


@dataclass
class ChurnMetrics:
    """Metrics for repair churn."""
    total_churn_score: int = 0
    stops_vehicle_changed: int = 0
    stops_sequence_changed: int = 0
    stops_became_unassigned: int = 0
    stops_became_assigned: int = 0
    stops_unchanged: int = 0
    total_stops_affected: int = 0
    diffs: List[StopDiff] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_churn_score": self.total_churn_score,
            "stops_vehicle_changed": self.stops_vehicle_changed,
            "stops_sequence_changed": self.stops_sequence_changed,
            "stops_became_unassigned": self.stops_became_unassigned,
            "stops_became_assigned": self.stops_became_assigned,
            "stops_unchanged": self.stops_unchanged,
            "total_stops_affected": self.total_stops_affected,
            "diffs": [d.to_dict() for d in self.diffs if d.vehicle_changed or d.sequence_changed or d.became_unassigned],
        }


@dataclass
class RepairResult:
    """Result of a repair operation."""
    status: RepairStatus
    event: RepairEvent
    churn: ChurnMetrics
    new_assignments: List[Dict]           # New assignment list
    new_unassigned: List[Dict]            # New unassigned list
    frozen_stops_preserved: int           # Count of frozen stops kept unchanged
    error_message: Optional[str] = None
    repair_duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "event": self.event.to_dict(),
            "churn": self.churn.to_dict(),
            "new_assignments_count": len(self.new_assignments),
            "new_unassigned_count": len(self.new_unassigned),
            "frozen_stops_preserved": self.frozen_stops_preserved,
            "error_message": self.error_message,
            "repair_duration_ms": self.repair_duration_ms,
        }


# =============================================================================
# REPAIR ENGINE
# =============================================================================

class RepairEngine:
    """
    Churn-aware route repair engine.

    Handles operational changes (no-shows, delays, breakdowns) while
    minimizing disruption to existing routes.

    The engine:
    1. Identifies frozen stops that cannot be moved
    2. Applies the repair event (remove stop, add delay, etc.)
    3. Re-optimizes unfrozen stops with churn penalties
    4. Computes churn diff between original and repaired plan

    Usage:
        engine = RepairEngine(churn_config=ChurnConfig())

        result = engine.repair(
            event=RepairEvent(
                event_type=RepairEventType.NO_SHOW,
                stop_id="STOP_123",
                reason="Customer not home"
            ),
            original_assignments=assignments,
            original_unassigned=unassigned,
            stops=stops,
            vehicles=vehicles,
            freeze_scope=FreezeScope(freeze_horizon_min=60)
        )

        if result.status == RepairStatus.SUCCESS:
            print(f"Repair successful, churn score: {result.churn.total_churn_score}")
    """

    def __init__(self, churn_config: Optional[ChurnConfig] = None):
        """
        Initialize repair engine.

        Args:
            churn_config: Configuration for churn penalties
        """
        self.config = churn_config or ChurnConfig()

    def repair(
        self,
        event: RepairEvent,
        original_assignments: List[Dict],
        original_unassigned: List[Dict],
        stops: List[Dict],
        vehicles: List[Dict],
        freeze_scope: Optional[FreezeScope] = None,
    ) -> RepairResult:
        """
        Perform churn-aware repair.

        Args:
            event: The repair event that triggered this
            original_assignments: Current assignments (before repair)
            original_unassigned: Current unassigned stops (before repair)
            stops: All stops (for context)
            vehicles: All vehicles (for context)
            freeze_scope: Which stops/vehicles are frozen

        Returns:
            RepairResult with new assignments and churn metrics
        """
        import time
        start_time = time.time()

        freeze_scope = freeze_scope or FreezeScope()

        try:
            # Step 1: Apply the event to get modified state
            modified_assignments, modified_unassigned, affected_stops = self._apply_event(
                event=event,
                assignments=original_assignments.copy(),
                unassigned=original_unassigned.copy(),
                stops=stops,
                vehicles=vehicles,
            )

            # Step 2: Identify frozen stops
            frozen_stop_ids = self._identify_frozen_stops(
                assignments=modified_assignments,
                freeze_scope=freeze_scope,
            )

            # Step 3: Partition into frozen and movable
            frozen_assignments = [
                a for a in modified_assignments
                if a["stop_id"] in frozen_stop_ids
            ]
            movable_assignments = [
                a for a in modified_assignments
                if a["stop_id"] not in frozen_stop_ids
            ]

            # Step 4: Simple re-optimization (V1: just resequence)
            # In V2, this would call the full solver with churn penalties
            new_assignments = self._simple_reoptimize(
                frozen_assignments=frozen_assignments,
                movable_assignments=movable_assignments,
                modified_unassigned=modified_unassigned,
                stops=stops,
                vehicles=vehicles,
                freeze_scope=freeze_scope,
            )

            # Step 5: Compute churn
            churn = self._compute_churn(
                original_assignments=original_assignments,
                new_assignments=new_assignments,
                original_unassigned=original_unassigned,
                new_unassigned=modified_unassigned,
            )

            # Step 6: Check max churn limit
            if (
                self.config.max_churn_score is not None
                and churn.total_churn_score > self.config.max_churn_score
            ):
                return RepairResult(
                    status=RepairStatus.FAILED,
                    event=event,
                    churn=churn,
                    new_assignments=original_assignments,  # Keep original
                    new_unassigned=original_unassigned,
                    frozen_stops_preserved=len(frozen_stop_ids),
                    error_message=f"Churn score {churn.total_churn_score} exceeds max {self.config.max_churn_score}",
                    repair_duration_ms=int((time.time() - start_time) * 1000),
                )

            # Determine status
            if modified_unassigned:
                status = RepairStatus.PARTIAL
            else:
                status = RepairStatus.SUCCESS

            return RepairResult(
                status=status,
                event=event,
                churn=churn,
                new_assignments=new_assignments,
                new_unassigned=modified_unassigned,
                frozen_stops_preserved=len(frozen_stop_ids),
                repair_duration_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.error(f"Repair failed: {e}", exc_info=True)
            return RepairResult(
                status=RepairStatus.FAILED,
                event=event,
                churn=ChurnMetrics(),
                new_assignments=original_assignments,
                new_unassigned=original_unassigned,
                frozen_stops_preserved=0,
                error_message=str(e),
                repair_duration_ms=int((time.time() - start_time) * 1000),
            )

    def _apply_event(
        self,
        event: RepairEvent,
        assignments: List[Dict],
        unassigned: List[Dict],
        stops: List[Dict],
        vehicles: List[Dict],
    ) -> Tuple[List[Dict], List[Dict], Set[str]]:
        """
        Apply repair event to current state.

        Returns:
            (modified_assignments, modified_unassigned, affected_stop_ids)
        """
        affected_stops: Set[str] = set()

        if event.event_type == RepairEventType.NO_SHOW:
            # Remove stop from assignments, add to unassigned
            if event.stop_id:
                affected_stops.add(event.stop_id)
                assignments = [a for a in assignments if a["stop_id"] != event.stop_id]
                unassigned.append({
                    "stop_id": event.stop_id,
                    "reason_code": "NO_SHOW",
                    "reason_details": event.reason,
                })

        elif event.event_type == RepairEventType.STOP_REMOVED:
            # Remove stop from assignments
            if event.stop_id:
                affected_stops.add(event.stop_id)
                assignments = [a for a in assignments if a["stop_id"] != event.stop_id]
                unassigned.append({
                    "stop_id": event.stop_id,
                    "reason_code": "STOP_CANCELLED",
                    "reason_details": event.reason,
                })

        elif event.event_type == RepairEventType.VEHICLE_DOWN:
            # Mark all stops on this vehicle as needing reassignment
            if event.vehicle_id:
                vehicle_stops = [
                    a["stop_id"] for a in assignments
                    if a["vehicle_id"] == event.vehicle_id
                ]
                affected_stops.update(vehicle_stops)

                # Remove from assignments (they'll be re-assigned)
                removed = [a for a in assignments if a["vehicle_id"] == event.vehicle_id]
                assignments = [a for a in assignments if a["vehicle_id"] != event.vehicle_id]

                # Add to unassigned temporarily
                for a in removed:
                    unassigned.append({
                        "stop_id": a["stop_id"],
                        "reason_code": "VEHICLE_DOWN_PENDING",
                        "reason_details": f"Vehicle {event.vehicle_id} down",
                    })

        elif event.event_type == RepairEventType.DELAY:
            # Mark vehicle's remaining stops as potentially affected
            if event.vehicle_id:
                vehicle_stops = [
                    a["stop_id"] for a in assignments
                    if a["vehicle_id"] == event.vehicle_id
                ]
                affected_stops.update(vehicle_stops)
                # Note: actual time adjustment happens in re-optimization

        elif event.event_type == RepairEventType.STOP_ADDED:
            # Add new stop to unassigned (will be assigned during re-optimization)
            if event.new_stop_data and event.stop_id:
                affected_stops.add(event.stop_id)
                unassigned.append({
                    "stop_id": event.stop_id,
                    "reason_code": "PENDING_ASSIGNMENT",
                    "reason_details": "Emergency stop added",
                })

        elif event.event_type == RepairEventType.TIME_WINDOW_CHANGE:
            # Mark stop as affected (may need reassignment)
            if event.stop_id:
                affected_stops.add(event.stop_id)
                # Note: TW change applied in stop data, re-optimization handles feasibility

        return assignments, unassigned, affected_stops

    def _identify_frozen_stops(
        self,
        assignments: List[Dict],
        freeze_scope: FreezeScope,
    ) -> Set[str]:
        """Identify stops that are frozen and cannot be moved."""
        frozen: Set[str] = set()

        for a in assignments:
            stop_id = a["stop_id"]
            arrival_at = a.get("arrival_at")

            # Parse arrival if string
            if isinstance(arrival_at, str):
                try:
                    arrival_at = datetime.fromisoformat(arrival_at)
                except (ValueError, TypeError):
                    arrival_at = None

            if freeze_scope.is_stop_frozen(stop_id, arrival_at):
                frozen.add(stop_id)

        return frozen

    def _simple_reoptimize(
        self,
        frozen_assignments: List[Dict],
        movable_assignments: List[Dict],
        modified_unassigned: List[Dict],
        stops: List[Dict],
        vehicles: List[Dict],
        freeze_scope: FreezeScope,
    ) -> List[Dict]:
        """
        Simple re-optimization (V1).

        In V1, we just:
        1. Keep frozen assignments unchanged
        2. Resequence movable assignments on their current vehicles
        3. Try to assign PENDING stops to vehicles with capacity

        In V2, this would call the full OR-Tools solver with:
        - Locked vehicle constraints for frozen stops
        - Churn penalty callbacks for reassignments
        """
        # Start with frozen assignments (unchanged)
        result = list(frozen_assignments)

        # Group movable by vehicle
        by_vehicle: Dict[str, List[Dict]] = {}
        for a in movable_assignments:
            vid = a["vehicle_id"]
            if vid not in by_vehicle:
                by_vehicle[vid] = []
            by_vehicle[vid].append(a)

        # Resequence each vehicle's movable stops
        for vid, vehicle_stops in by_vehicle.items():
            # Sort by arrival time
            vehicle_stops.sort(key=lambda x: x.get("arrival_at", ""))

            # Update sequence indices
            # Find max frozen sequence for this vehicle
            frozen_on_vehicle = [
                a for a in frozen_assignments
                if a["vehicle_id"] == vid
            ]
            max_frozen_seq = max(
                (a.get("sequence_index", 0) for a in frozen_on_vehicle),
                default=0
            )

            for i, a in enumerate(vehicle_stops):
                a["sequence_index"] = max_frozen_seq + i + 1

            result.extend(vehicle_stops)

        # Try to assign pending stops from unassigned
        pending = [
            u for u in modified_unassigned
            if u.get("reason_code") in ("PENDING_ASSIGNMENT", "VEHICLE_DOWN_PENDING")
        ]

        # Simple greedy assignment for pending stops
        for p in pending:
            stop_id = p["stop_id"]

            # Find first non-frozen vehicle with capacity
            for v in vehicles:
                vid = v["id"]
                if freeze_scope.is_vehicle_frozen(vid):
                    continue

                # Check if vehicle has room (simple: < 20 stops)
                current_count = sum(1 for a in result if a["vehicle_id"] == vid)
                if current_count < 20:
                    # Assign to this vehicle
                    new_seq = max(
                        (a.get("sequence_index", 0) for a in result if a["vehicle_id"] == vid),
                        default=0
                    ) + 1

                    result.append({
                        "stop_id": stop_id,
                        "vehicle_id": vid,
                        "sequence_index": new_seq,
                        "arrival_at": None,  # Would be computed by solver
                        "departure_at": None,
                    })

                    # Remove from unassigned
                    modified_unassigned[:] = [
                        u for u in modified_unassigned
                        if u["stop_id"] != stop_id
                    ]
                    break

        return result

    def _compute_churn(
        self,
        original_assignments: List[Dict],
        new_assignments: List[Dict],
        original_unassigned: List[Dict],
        new_unassigned: List[Dict],
    ) -> ChurnMetrics:
        """Compute churn metrics between original and new assignments."""
        # Build lookup maps
        original_by_stop: Dict[str, Dict] = {
            a["stop_id"]: a for a in original_assignments
        }
        new_by_stop: Dict[str, Dict] = {
            a["stop_id"]: a for a in new_assignments
        }
        original_unassigned_ids = {u["stop_id"] for u in original_unassigned}
        new_unassigned_ids = {u["stop_id"] for u in new_unassigned}

        # All stop IDs
        all_stops = (
            set(original_by_stop.keys())
            | set(new_by_stop.keys())
            | original_unassigned_ids
            | new_unassigned_ids
        )

        # Compute diffs
        diffs: List[StopDiff] = []
        total_churn = 0
        stops_vehicle_changed = 0
        stops_sequence_changed = 0
        stops_became_unassigned = 0
        stops_became_assigned = 0
        stops_unchanged = 0

        for stop_id in all_stops:
            orig = original_by_stop.get(stop_id)
            new = new_by_stop.get(stop_id)
            was_unassigned = stop_id in original_unassigned_ids
            is_unassigned = stop_id in new_unassigned_ids

            orig_vehicle = orig["vehicle_id"] if orig else None
            new_vehicle = new["vehicle_id"] if new else None
            orig_seq = orig.get("sequence_index") if orig else None
            new_seq = new.get("sequence_index") if new else None

            vehicle_changed = False
            sequence_changed = False
            became_unassigned = False
            became_assigned = False
            churn_cost = 0

            if orig and new:
                # Stop was and is assigned
                if orig_vehicle != new_vehicle:
                    vehicle_changed = True
                    churn_cost += self.config.vehicle_change_penalty
                    stops_vehicle_changed += 1
                elif orig_seq != new_seq:
                    sequence_changed = True
                    churn_cost += self.config.sequence_change_penalty
                    stops_sequence_changed += 1
                else:
                    # Apply bonus for keeping same
                    churn_cost -= self.config.same_vehicle_bonus
                    stops_unchanged += 1

            elif orig and not new:
                # Stop became unassigned
                became_unassigned = True
                churn_cost += self.config.unassigned_penalty
                stops_became_unassigned += 1

            elif not orig and new:
                # Stop became assigned (was unassigned)
                became_assigned = True
                # This is good - no penalty, maybe bonus
                churn_cost -= self.config.same_vehicle_bonus
                stops_became_assigned += 1

            # else: was and is unassigned - no change

            total_churn += max(0, churn_cost)  # Don't let bonuses go negative

            diff = StopDiff(
                stop_id=stop_id,
                original_vehicle_id=orig_vehicle,
                new_vehicle_id=new_vehicle,
                original_sequence=orig_seq,
                new_sequence=new_seq,
                vehicle_changed=vehicle_changed,
                sequence_changed=sequence_changed,
                became_unassigned=became_unassigned,
                became_assigned=became_assigned,
                churn_cost=churn_cost,
            )
            diffs.append(diff)

        return ChurnMetrics(
            total_churn_score=total_churn,
            stops_vehicle_changed=stops_vehicle_changed,
            stops_sequence_changed=stops_sequence_changed,
            stops_became_unassigned=stops_became_unassigned,
            stops_became_assigned=stops_became_assigned,
            stops_unchanged=stops_unchanged,
            total_stops_affected=len(all_stops),
            diffs=diffs,
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def repair_no_show(
    stop_id: str,
    original_assignments: List[Dict],
    original_unassigned: List[Dict],
    stops: List[Dict],
    vehicles: List[Dict],
    reason: str = "Customer not available",
    churn_config: Optional[ChurnConfig] = None,
    freeze_scope: Optional[FreezeScope] = None,
) -> RepairResult:
    """
    Convenience function for handling no-show events.

    Args:
        stop_id: The stop that was a no-show
        original_assignments: Current assignments
        original_unassigned: Current unassigned stops
        stops: All stops
        vehicles: All vehicles
        reason: Reason for no-show
        churn_config: Churn configuration
        freeze_scope: Freeze scope

    Returns:
        RepairResult
    """
    engine = RepairEngine(churn_config=churn_config)
    event = RepairEvent(
        event_type=RepairEventType.NO_SHOW,
        stop_id=stop_id,
        reason=reason,
    )
    return engine.repair(
        event=event,
        original_assignments=original_assignments,
        original_unassigned=original_unassigned,
        stops=stops,
        vehicles=vehicles,
        freeze_scope=freeze_scope,
    )


def repair_vehicle_down(
    vehicle_id: str,
    original_assignments: List[Dict],
    original_unassigned: List[Dict],
    stops: List[Dict],
    vehicles: List[Dict],
    reason: str = "Vehicle breakdown",
    churn_config: Optional[ChurnConfig] = None,
    freeze_scope: Optional[FreezeScope] = None,
) -> RepairResult:
    """
    Convenience function for handling vehicle breakdown events.

    Args:
        vehicle_id: The vehicle that broke down
        original_assignments: Current assignments
        original_unassigned: Current unassigned stops
        stops: All stops
        vehicles: All available vehicles (excluding broken one)
        reason: Reason for breakdown
        churn_config: Churn configuration
        freeze_scope: Freeze scope

    Returns:
        RepairResult
    """
    engine = RepairEngine(churn_config=churn_config)
    event = RepairEvent(
        event_type=RepairEventType.VEHICLE_DOWN,
        vehicle_id=vehicle_id,
        reason=reason,
    )

    # Add broken vehicle to frozen list
    freeze_scope = freeze_scope or FreezeScope()
    freeze_scope.locked_vehicle_ids.add(vehicle_id)

    return engine.repair(
        event=event,
        original_assignments=original_assignments,
        original_unassigned=original_unassigned,
        stops=stops,
        vehicles=vehicles,
        freeze_scope=freeze_scope,
    )
