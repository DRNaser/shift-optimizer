"""
SOLVEREIGN V3 Plan State Machine
=================================

Defines valid state transitions for plan_versions and forecast_versions.
Ensures transactional integrity and prevents invalid state changes.

Plan Version States:
    DRAFT → SOLVING → DRAFT (success) or FAILED (error)
    DRAFT → LOCKED (release)
    LOCKED → SUPERSEDED (new version released)

Forecast Version States:
    PASS → (immutable, can have plans)
    WARN → (immutable, can have plans with warning)
    FAIL → (immutable, cannot have plans)
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Callable, Any

from .schemas import PlanStatus, ForecastStatus


# ============================================================================
# STATE TRANSITION DEFINITIONS
# ============================================================================

class TransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, current_state: str, target_state: str, reason: str):
        self.current_state = current_state
        self.target_state = target_state
        self.reason = reason
        super().__init__(f"Cannot transition from {current_state} to {target_state}: {reason}")


@dataclass
class Transition:
    """A valid state transition."""
    from_state: str
    to_state: str
    requires: Optional[Callable[[dict], bool]] = None
    side_effects: Optional[List[str]] = None
    description: str = ""


# ============================================================================
# PLAN STATE MACHINE
# ============================================================================

PLAN_TRANSITIONS: List[Transition] = [
    # DRAFT → SOLVING (start solving)
    Transition(
        from_state="DRAFT",
        to_state="SOLVING",
        description="Start solver execution",
        side_effects=["log_state_change"],
    ),

    # SOLVING → DRAFT (solve succeeded)
    Transition(
        from_state="SOLVING",
        to_state="DRAFT",
        description="Solver completed successfully",
        requires=lambda ctx: ctx.get("output_hash") is not None,
        side_effects=["update_output_hash", "log_state_change"],
    ),

    # SOLVING → FAILED (solve failed)
    Transition(
        from_state="SOLVING",
        to_state="FAILED",
        description="Solver failed with error",
        side_effects=["log_error", "log_state_change"],
    ),

    # DRAFT → LOCKED (release)
    Transition(
        from_state="DRAFT",
        to_state="LOCKED",
        description="Release plan for production",
        requires=lambda ctx: (
            ctx.get("all_audits_passed", False) and
            ctx.get("locked_by") is not None
        ),
        side_effects=["set_locked_at", "set_locked_by", "supersede_previous", "log_state_change"],
    ),

    # DRAFT → SUPERSEDED (replaced by newer draft)
    Transition(
        from_state="DRAFT",
        to_state="SUPERSEDED",
        description="Replaced by newer draft",
        requires=lambda ctx: ctx.get("newer_plan_id") is not None,
        side_effects=["log_state_change"],
    ),

    # LOCKED → SUPERSEDED (new version released)
    Transition(
        from_state="LOCKED",
        to_state="SUPERSEDED",
        description="New plan version released",
        requires=lambda ctx: ctx.get("newer_locked_plan_id") is not None,
        side_effects=["log_state_change"],
    ),
]


class PlanStateMachine:
    """
    State machine for plan_versions.

    Ensures only valid transitions occur and handles side effects.
    """

    def __init__(self):
        self.transitions = {
            (t.from_state, t.to_state): t
            for t in PLAN_TRANSITIONS
        }

    def can_transition(self, current: str, target: str, context: dict = None) -> bool:
        """Check if transition is valid."""
        context = context or {}
        key = (current, target)

        if key not in self.transitions:
            return False

        transition = self.transitions[key]
        if transition.requires and not transition.requires(context):
            return False

        return True

    def get_transition(self, current: str, target: str) -> Optional[Transition]:
        """Get transition definition."""
        return self.transitions.get((current, target))

    def validate_transition(self, current: str, target: str, context: dict = None) -> None:
        """
        Validate transition or raise TransitionError.

        Args:
            current: Current state
            target: Target state
            context: Context for requirement checking

        Raises:
            TransitionError if transition is invalid
        """
        context = context or {}
        key = (current, target)

        if key not in self.transitions:
            valid_targets = [t.to_state for t in PLAN_TRANSITIONS if t.from_state == current]
            raise TransitionError(
                current, target,
                f"Invalid transition. Valid targets from {current}: {valid_targets}"
            )

        transition = self.transitions[key]
        if transition.requires and not transition.requires(context):
            raise TransitionError(
                current, target,
                f"Requirements not met for transition"
            )

    def get_valid_transitions(self, current: str) -> List[str]:
        """Get list of valid target states from current state."""
        return [t.to_state for t in PLAN_TRANSITIONS if t.from_state == current]

    def get_side_effects(self, current: str, target: str) -> List[str]:
        """Get side effects for a transition."""
        transition = self.transitions.get((current, target))
        return transition.side_effects if transition else []


# ============================================================================
# TRANSITION EXECUTOR
# ============================================================================

class TransitionExecutor:
    """
    Executes plan state transitions with side effects.

    Handles:
    - State validation
    - Side effect execution
    - Transaction management
    - Audit logging
    """

    def __init__(self, db_connection):
        self.conn = db_connection
        self.state_machine = PlanStateMachine()

    def transition(
        self,
        plan_version_id: int,
        target_state: str,
        context: dict = None
    ) -> dict:
        """
        Execute a state transition.

        Args:
            plan_version_id: Plan to transition
            target_state: Target state
            context: Additional context (locked_by, output_hash, etc.)

        Returns:
            Dict with transition result

        Raises:
            TransitionError if transition is invalid
        """
        context = context or {}

        # Get current state
        current_state = self._get_current_state(plan_version_id)

        # Validate transition
        self.state_machine.validate_transition(current_state, target_state, context)

        # Execute within transaction
        with self.conn.cursor() as cur:
            # Execute side effects
            side_effects = self.state_machine.get_side_effects(current_state, target_state)
            for effect in side_effects:
                self._execute_side_effect(cur, effect, plan_version_id, target_state, context)

            # Update state
            cur.execute("""
                UPDATE plan_versions
                SET status = %s
                WHERE id = %s
            """, (target_state, plan_version_id))

            self.conn.commit()

        return {
            "plan_version_id": plan_version_id,
            "previous_state": current_state,
            "new_state": target_state,
            "side_effects_executed": side_effects,
        }

    def _get_current_state(self, plan_version_id: int) -> str:
        """Get current plan state."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM plan_versions WHERE id = %s",
                (plan_version_id,)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Plan version {plan_version_id} not found")
            return row["status"]

    def _execute_side_effect(
        self,
        cur,
        effect: str,
        plan_version_id: int,
        target_state: str,
        context: dict
    ):
        """Execute a side effect."""
        if effect == "set_locked_at":
            cur.execute("""
                UPDATE plan_versions
                SET locked_at = NOW()
                WHERE id = %s
            """, (plan_version_id,))

        elif effect == "set_locked_by":
            cur.execute("""
                UPDATE plan_versions
                SET locked_by = %s
                WHERE id = %s
            """, (context.get("locked_by"), plan_version_id))

        elif effect == "update_output_hash":
            cur.execute("""
                UPDATE plan_versions
                SET output_hash = %s
                WHERE id = %s
            """, (context.get("output_hash"), plan_version_id))

        elif effect == "supersede_previous":
            # Mark previous LOCKED plan as SUPERSEDED
            cur.execute("""
                UPDATE plan_versions pv
                SET status = 'SUPERSEDED'
                WHERE pv.forecast_version_id = (
                    SELECT forecast_version_id FROM plan_versions WHERE id = %s
                )
                AND pv.status = 'LOCKED'
                AND pv.id != %s
            """, (plan_version_id, plan_version_id))

        elif effect == "log_state_change":
            cur.execute("""
                INSERT INTO audit_log (plan_version_id, check_name, status, count, details_json)
                VALUES (%s, 'STATE_CHANGE', 'PASS', 0, %s)
            """, (
                plan_version_id,
                {
                    "target_state": target_state,
                    "context": {k: str(v) for k, v in context.items()},
                    "timestamp": datetime.now().isoformat(),
                }
            ))

        elif effect == "log_error":
            cur.execute("""
                INSERT INTO audit_log (plan_version_id, check_name, status, count, details_json)
                VALUES (%s, 'SOLVER_ERROR', 'FAIL', 1, %s)
            """, (
                plan_version_id,
                {
                    "error": context.get("error_message", "Unknown error"),
                    "timestamp": datetime.now().isoformat(),
                }
            ))


# ============================================================================
# FORECAST STATE MACHINE (Simpler)
# ============================================================================

class ForecastStateMachine:
    """
    State machine for forecast_versions.

    Forecasts are immutable after creation, so this mainly
    validates that operations are allowed based on status.
    """

    @staticmethod
    def can_solve(status: str) -> bool:
        """Check if forecast can be solved."""
        return status in ("PASS", "WARN")

    @staticmethod
    def can_create_plan(status: str) -> bool:
        """Check if forecast can have plans created."""
        return status in ("PASS", "WARN")

    @staticmethod
    def validate_for_solve(status: str) -> None:
        """
        Validate forecast status for solving.

        Raises:
            ValueError if status is FAIL
        """
        if status == "FAIL":
            raise ValueError(
                "Cannot solve FAIL forecast. Fix parse errors first."
            )


# ============================================================================
# IDEMPOTENCY HELPERS
# ============================================================================

def check_forecast_exists(conn, input_hash: str) -> Optional[int]:
    """
    Check if forecast with same input_hash exists.

    Returns:
        forecast_version_id if exists, None otherwise
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM forecast_versions WHERE input_hash = %s",
            (input_hash,)
        )
        row = cur.fetchone()
        return row["id"] if row else None


def check_plan_exists(conn, forecast_version_id: int, seed: int, solver_config_hash: str) -> Optional[int]:
    """
    Check if plan with same (forecast, seed, config) exists.

    Returns:
        plan_version_id if exists, None otherwise
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM plan_versions
            WHERE forecast_version_id = %s
            AND seed = %s
            AND solver_config_hash = %s
            AND status NOT IN ('FAILED', 'SUPERSEDED')
        """, (forecast_version_id, seed, solver_config_hash))
        row = cur.fetchone()
        return row["id"] if row else None


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def release_plan(
    conn,
    plan_version_id: int,
    locked_by: str,
    all_audits_passed: bool = True
) -> dict:
    """
    Release a plan (DRAFT → LOCKED).

    Args:
        conn: Database connection
        plan_version_id: Plan to release
        locked_by: User/system releasing
        all_audits_passed: Whether audits passed

    Returns:
        Transition result
    """
    executor = TransitionExecutor(conn)
    return executor.transition(
        plan_version_id=plan_version_id,
        target_state="LOCKED",
        context={
            "locked_by": locked_by,
            "all_audits_passed": all_audits_passed,
        }
    )


def mark_solve_started(conn, plan_version_id: int) -> dict:
    """Mark plan as SOLVING."""
    executor = TransitionExecutor(conn)
    return executor.transition(
        plan_version_id=plan_version_id,
        target_state="SOLVING",
        context={}
    )


def mark_solve_completed(conn, plan_version_id: int, output_hash: str) -> dict:
    """Mark plan as completed (SOLVING → DRAFT)."""
    executor = TransitionExecutor(conn)
    return executor.transition(
        plan_version_id=plan_version_id,
        target_state="DRAFT",
        context={"output_hash": output_hash}
    )


def mark_solve_failed(conn, plan_version_id: int, error_message: str) -> dict:
    """Mark plan as failed (SOLVING → FAILED)."""
    executor = TransitionExecutor(conn)
    return executor.transition(
        plan_version_id=plan_version_id,
        target_state="FAILED",
        context={"error_message": error_message}
    )
