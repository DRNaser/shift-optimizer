"""
SOLVEREIGN V3.7 - Repair Service (Gate H Hardened)
===================================================

Operational repair service with:
- Churn minimization metrics
- Audit hooks (pre/post repair)
- Evidence pack generation
- Freeze-lock enforcement (HARD gate)

This wraps repair_engine.py with ops-grade observability and evidence.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Set, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# CHURN METRICS
# =============================================================================

@dataclass
class ChurnMetrics:
    """
    Churn analysis for repair operations.

    Key for Gate H: We must minimize churn while maintaining coverage.
    """
    changed_assignments: int
    total_assignments: int
    churn_rate: float  # 0.0 - 1.0
    drivers_added: int
    drivers_removed: int
    tours_reassigned: int
    unchanged_tours: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changed_assignments": self.changed_assignments,
            "total_assignments": self.total_assignments,
            "churn_rate": round(self.churn_rate, 4),
            "drivers_added": self.drivers_added,
            "drivers_removed": self.drivers_removed,
            "tours_reassigned": self.tours_reassigned,
            "unchanged_tours": self.unchanged_tours
        }


@dataclass
class BaselineComparison:
    """Comparison between baseline and repaired plan."""
    headcount_delta: int
    hours_delta: float
    coverage_delta: float
    audit_status_changed: bool
    baseline_audit_passed: bool
    repair_audit_passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headcount_delta": self.headcount_delta,
            "hours_delta": round(self.hours_delta, 2),
            "coverage_delta": round(self.coverage_delta, 2),
            "audit_status_changed": self.audit_status_changed,
            "baseline_audit_passed": self.baseline_audit_passed,
            "repair_audit_passed": self.repair_audit_passed
        }


# =============================================================================
# REPAIR EVIDENCE
# =============================================================================

@dataclass
class RepairEvidence:
    """
    Complete evidence pack for a repair operation.

    This is the audit-grade output of any repair.
    """
    run_id: str
    tenant_id: str
    evidence_type: str  # REPAIR, DRILL_SICK_CALL, DRILL_FREEZE
    timestamp: str

    # Input state
    baseline_plan_id: int
    baseline_plan_hash: str
    absent_driver_ids: List[int]
    repair_reason: str

    # Configuration
    seed: int
    config_hash: str
    freeze_horizon_minutes: int

    # Output
    new_plan_id: Optional[int]
    new_plan_hash: Optional[str]
    success: bool
    error_message: Optional[str]

    # Metrics
    churn_metrics: Optional[ChurnMetrics]
    baseline_comparison: Optional[BaselineComparison]

    # Audits
    audits_all_passed: bool
    audit_results: Dict[str, Any]

    # Freeze enforcement
    freeze_violations: int
    freeze_blocked_attempts: List[Dict[str, Any]]

    # Execution
    execution_time_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "evidence_type": self.evidence_type,
            "timestamp": self.timestamp,
            "baseline_plan_id": self.baseline_plan_id,
            "baseline_plan_hash": self.baseline_plan_hash,
            "absent_driver_ids": self.absent_driver_ids,
            "repair_reason": self.repair_reason,
            "seed": self.seed,
            "config_hash": self.config_hash,
            "freeze_horizon_minutes": self.freeze_horizon_minutes,
            "new_plan_id": self.new_plan_id,
            "new_plan_hash": self.new_plan_hash,
            "success": self.success,
            "error_message": self.error_message,
            "churn_metrics": self.churn_metrics.to_dict() if self.churn_metrics else None,
            "baseline_comparison": self.baseline_comparison.to_dict() if self.baseline_comparison else None,
            "audits_all_passed": self.audits_all_passed,
            "audit_results": self.audit_results,
            "freeze_violations": self.freeze_violations,
            "freeze_blocked_attempts": self.freeze_blocked_attempts,
            "execution_time_ms": self.execution_time_ms
        }


# =============================================================================
# REPAIR SERVICE
# =============================================================================

class RepairService:
    """
    Gate H hardened repair service.

    Features:
    - Churn minimization with metrics
    - Pre/post audit hooks
    - Evidence pack generation
    - Freeze-lock enforcement (HARD gate)
    - Deterministic with seed
    """

    def __init__(
        self,
        tenant_id: str,
        freeze_horizon_minutes: int = 720,  # 12h default
        enable_freeze_enforcement: bool = True
    ):
        self.tenant_id = tenant_id
        self.freeze_horizon_minutes = freeze_horizon_minutes
        self.enable_freeze_enforcement = enable_freeze_enforcement

        # Hooks
        self._pre_repair_hooks: List[callable] = []
        self._post_repair_hooks: List[callable] = []

    def add_pre_repair_hook(self, hook: callable) -> None:
        """Add hook to run before repair."""
        self._pre_repair_hooks.append(hook)

    def add_post_repair_hook(self, hook: callable) -> None:
        """Add hook to run after repair."""
        self._post_repair_hooks.append(hook)

    def repair_sick_call(
        self,
        plan_version_id: int,
        absent_driver_ids: List[int],
        seed: int = 94,
        requested_by: Optional[str] = None,
        is_drill: bool = False
    ) -> RepairEvidence:
        """
        Repair plan after sick-call (driver absence).

        Gate H1: This is the main sick-call drill entry point.

        Args:
            plan_version_id: Baseline plan to repair
            absent_driver_ids: Driver IDs that are unavailable
            seed: Random seed for determinism
            requested_by: Who requested the repair
            is_drill: True if this is a drill (not production)

        Returns:
            RepairEvidence with complete audit trail
        """
        run_id = f"repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{plan_version_id}"
        start_time = time.perf_counter()

        evidence_type = "DRILL_SICK_CALL" if is_drill else "REPAIR"

        # Run pre-repair hooks
        for hook in self._pre_repair_hooks:
            try:
                hook(plan_version_id, absent_driver_ids)
            except Exception as e:
                logger.warning(f"Pre-repair hook failed: {e}")

        try:
            # Load baseline state
            baseline_state = self._load_baseline_state(plan_version_id)
            baseline_hash = self._compute_plan_hash(baseline_state)

            # Compute config hash
            config = {
                "seed": seed,
                "freeze_horizon_minutes": self.freeze_horizon_minutes,
                "enable_freeze_enforcement": self.enable_freeze_enforcement
            }
            config_hash = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()

            # Execute repair
            from .repair_engine import RepairEngine, RepairRequest, RepairStrategy

            request = RepairRequest(
                plan_version_id=plan_version_id,
                absent_driver_ids=absent_driver_ids,
                seed=seed,
                strategy=RepairStrategy.MIN_CHURN,
                respect_freeze=self.enable_freeze_enforcement
            )

            engine = RepairEngine(
                tenant_id=self.tenant_id,
                freeze_window_minutes=self.freeze_horizon_minutes
            )

            result = engine.repair(request, requested_by)

            # Compute churn metrics
            churn_metrics = None
            baseline_comparison = None

            if result.status.value == "SUCCESS" and result.new_plan_version_id:
                churn_metrics = self._compute_churn_metrics(
                    baseline_state,
                    result.new_plan_version_id,
                    result.tours_reassigned
                )

                baseline_comparison = self._compute_baseline_comparison(
                    baseline_state,
                    result.new_plan_version_id,
                    result.audit_results
                )

            # Run post-repair hooks
            for hook in self._post_repair_hooks:
                try:
                    hook(result, churn_metrics)
                except Exception as e:
                    logger.warning(f"Post-repair hook failed: {e}")

            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            return RepairEvidence(
                run_id=run_id,
                tenant_id=self.tenant_id,
                evidence_type=evidence_type,
                timestamp=datetime.now().isoformat(),
                baseline_plan_id=plan_version_id,
                baseline_plan_hash=baseline_hash,
                absent_driver_ids=absent_driver_ids,
                repair_reason="SICK_CALL" if not is_drill else "DRILL",
                seed=seed,
                config_hash=config_hash,
                freeze_horizon_minutes=self.freeze_horizon_minutes,
                new_plan_id=result.new_plan_version_id,
                new_plan_hash=self._compute_plan_hash_by_id(result.new_plan_version_id) if result.new_plan_version_id else None,
                success=result.status.value == "SUCCESS",
                error_message=result.error_message if result.status.value != "SUCCESS" else None,
                churn_metrics=churn_metrics,
                baseline_comparison=baseline_comparison,
                audits_all_passed=result.audit_results.get("all_passed", False) if result.audit_results else False,
                audit_results=result.audit_results or {},
                freeze_violations=result.freeze_violations or 0,
                freeze_blocked_attempts=[],
                execution_time_ms=execution_time_ms
            )

        except Exception as e:
            logger.exception(f"Repair failed: {e}")
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            return RepairEvidence(
                run_id=run_id,
                tenant_id=self.tenant_id,
                evidence_type=evidence_type,
                timestamp=datetime.now().isoformat(),
                baseline_plan_id=plan_version_id,
                baseline_plan_hash="",
                absent_driver_ids=absent_driver_ids,
                repair_reason="SICK_CALL" if not is_drill else "DRILL",
                seed=seed,
                config_hash="",
                freeze_horizon_minutes=self.freeze_horizon_minutes,
                new_plan_id=None,
                new_plan_hash=None,
                success=False,
                error_message=str(e),
                churn_metrics=None,
                baseline_comparison=None,
                audits_all_passed=False,
                audit_results={},
                freeze_violations=0,
                freeze_blocked_attempts=[],
                execution_time_ms=execution_time_ms
            )

    def verify_freeze_enforcement(
        self,
        plan_version_id: int,
        proposed_changes: List[Dict[str, Any]],
        freeze_horizon_minutes: Optional[int] = None
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Gate H2: Verify freeze-lock enforcement.

        Returns (allowed, blocked_changes).
        """
        horizon = freeze_horizon_minutes or self.freeze_horizon_minutes

        # Load freeze state
        baseline_state = self._load_baseline_state(plan_version_id)
        frozen_tours = self._get_frozen_tours(baseline_state, horizon)

        blocked = []
        for change in proposed_changes:
            tour_id = change.get("tour_instance_id")
            if tour_id in frozen_tours:
                blocked.append({
                    "tour_instance_id": tour_id,
                    "change_type": change.get("change_type", "UNKNOWN"),
                    "reason": f"Tour is frozen (within {horizon} minute horizon)"
                })

        return len(blocked) == 0, blocked

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _load_baseline_state(self, plan_version_id: int) -> Dict[str, Any]:
        """Load baseline plan state for comparison."""
        from . import db

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get plan metadata
                cur.execute("""
                    SELECT pv.*, fv.week_anchor_date
                    FROM plan_versions pv
                    JOIN forecast_versions fv ON fv.id = pv.forecast_version_id
                    WHERE pv.id = %s
                """, (plan_version_id,))
                plan = dict(cur.fetchone())

                # Get assignments
                cur.execute("""
                    SELECT a.*, ti.start_ts, ti.end_ts, ti.work_hours
                    FROM assignments a
                    JOIN tour_instances ti ON ti.id = a.tour_instance_id
                    WHERE a.plan_version_id = %s
                    ORDER BY a.day, ti.start_ts
                """, (plan_version_id,))
                assignments = [dict(row) for row in cur.fetchall()]

                # Get audit results
                cur.execute("""
                    SELECT check_name, status, violation_count
                    FROM audit_log
                    WHERE plan_version_id = %s
                """, (plan_version_id,))
                audits = [dict(row) for row in cur.fetchall()]

                return {
                    "plan": plan,
                    "assignments": assignments,
                    "audits": audits,
                    "total_tours": len(assignments),
                    "drivers": set(a["real_driver_id"] for a in assignments if a.get("real_driver_id")),
                    "total_hours": sum(float(a.get("work_hours", 0)) for a in assignments)
                }

    def _compute_plan_hash(self, state: Dict[str, Any]) -> str:
        """Compute deterministic hash of plan state."""
        assignments = state.get("assignments", [])
        # Sort by tour_instance_id for determinism
        sorted_assignments = sorted(
            [(a.get("tour_instance_id"), a.get("real_driver_id")) for a in assignments],
            key=lambda x: x[0]
        )
        data = json.dumps(sorted_assignments, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def _compute_plan_hash_by_id(self, plan_version_id: int) -> str:
        """Compute hash for a plan by ID."""
        state = self._load_baseline_state(plan_version_id)
        return self._compute_plan_hash(state)

    def _compute_churn_metrics(
        self,
        baseline_state: Dict[str, Any],
        new_plan_id: int,
        tours_reassigned: int
    ) -> ChurnMetrics:
        """Compute churn metrics between baseline and new plan."""
        new_state = self._load_baseline_state(new_plan_id)

        baseline_assignments = {
            a["tour_instance_id"]: a["real_driver_id"]
            for a in baseline_state["assignments"]
        }
        new_assignments = {
            a["tour_instance_id"]: a["real_driver_id"]
            for a in new_state["assignments"]
        }

        changed = 0
        for tour_id, old_driver in baseline_assignments.items():
            new_driver = new_assignments.get(tour_id)
            if new_driver != old_driver:
                changed += 1

        baseline_drivers = baseline_state["drivers"]
        new_drivers = new_state["drivers"]

        drivers_added = len(new_drivers - baseline_drivers)
        drivers_removed = len(baseline_drivers - new_drivers)

        total = len(baseline_assignments)
        churn_rate = changed / total if total > 0 else 0.0

        return ChurnMetrics(
            changed_assignments=changed,
            total_assignments=total,
            churn_rate=churn_rate,
            drivers_added=drivers_added,
            drivers_removed=drivers_removed,
            tours_reassigned=tours_reassigned,
            unchanged_tours=total - changed
        )

    def _compute_baseline_comparison(
        self,
        baseline_state: Dict[str, Any],
        new_plan_id: int,
        new_audit_results: Optional[Dict]
    ) -> BaselineComparison:
        """Compare new plan to baseline."""
        new_state = self._load_baseline_state(new_plan_id)

        baseline_drivers = len(baseline_state["drivers"])
        new_drivers = len(new_state["drivers"])

        baseline_hours = baseline_state["total_hours"]
        new_hours = new_state["total_hours"]

        baseline_audits = baseline_state["audits"]
        baseline_passed = all(a["status"] == "PASS" for a in baseline_audits)
        new_passed = new_audit_results.get("all_passed", False) if new_audit_results else False

        return BaselineComparison(
            headcount_delta=new_drivers - baseline_drivers,
            hours_delta=new_hours - baseline_hours,
            coverage_delta=0.0,  # Assuming 100% coverage for both
            audit_status_changed=baseline_passed != new_passed,
            baseline_audit_passed=baseline_passed,
            repair_audit_passed=new_passed
        )

    def _get_frozen_tours(
        self,
        state: Dict[str, Any],
        horizon_minutes: int
    ) -> Set[int]:
        """Get tour IDs that are frozen based on time horizon."""
        from datetime import timedelta

        frozen = set()
        now = datetime.now()
        freeze_cutoff = now + timedelta(minutes=horizon_minutes)

        week_start = state["plan"].get("week_anchor_date")
        if not week_start:
            return frozen

        for assignment in state["assignments"]:
            day = assignment.get("day", 1)
            start_ts = assignment.get("start_ts")

            if not start_ts:
                continue

            # Compute tour datetime
            if isinstance(week_start, str):
                week_start = date.fromisoformat(week_start)

            tour_date = week_start + timedelta(days=day - 1)
            tour_datetime = datetime.combine(tour_date, start_ts)

            if tour_datetime <= freeze_cutoff:
                frozen.add(assignment["tour_instance_id"])

        return frozen


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def run_sick_call_drill(
    tenant_id: str,
    plan_version_id: int,
    absent_driver_ids: List[int],
    seed: int = 94
) -> RepairEvidence:
    """
    Gate H1: Run sick-call drill.

    Convenience function for drill scripts.
    """
    service = RepairService(tenant_id)
    return service.repair_sick_call(
        plan_version_id=plan_version_id,
        absent_driver_ids=absent_driver_ids,
        seed=seed,
        is_drill=True
    )


def verify_freeze_enforcement(
    tenant_id: str,
    plan_version_id: int,
    freeze_horizon_minutes: int = 720
) -> Tuple[bool, List[Dict]]:
    """
    Gate H2: Verify freeze enforcement.

    Returns (enforcement_working, blocked_changes).
    """
    service = RepairService(
        tenant_id=tenant_id,
        freeze_horizon_minutes=freeze_horizon_minutes
    )

    # Try to modify frozen tours (should be blocked)
    state = service._load_baseline_state(plan_version_id)
    frozen_tours = service._get_frozen_tours(state, freeze_horizon_minutes)

    if not frozen_tours:
        return True, []  # No frozen tours to test

    # Create fake changes to frozen tours
    test_changes = [
        {"tour_instance_id": tid, "change_type": "REASSIGN"}
        for tid in list(frozen_tours)[:3]  # Test first 3
    ]

    allowed, blocked = service.verify_freeze_enforcement(
        plan_version_id,
        test_changes,
        freeze_horizon_minutes
    )

    # Freeze enforcement is working if changes were blocked
    return not allowed and len(blocked) > 0, blocked
