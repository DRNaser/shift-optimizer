"""
SOLVEREIGN V3 Solver Wrapper
=============================

M4: Integration of V2 Block Heuristic Solver with V3 Versioning.

This module wraps the existing V2 solver (run_block_heuristic.py) and integrates
it with V3's versioning, audit, and database infrastructure.

SOLVER ENGINE SELECTION (ADR-003):
----------------------------------
V3 (DEFAULT) = BlockHeuristicSolver (Min-Cost Max-Flow)
    - Greedy block partitioning (3er > 2er > 1er)
    - Min-Cost Max-Flow assignment
    - Consolidation + PT Elimination
    - PRODUCTION RESULT: 145 FTE, 0 PT, 100% coverage

V4 (EXPERIMENTAL) = FeasibilityPipeline (Lexicographic)
    - Complex Phase 1 block selection (may timeout)
    - Uses PT as overflow bucket (causes regression)
    - R&D ONLY - not for production/pilot use

IMPORTANT: V3 is ALWAYS the default. V4 must be explicitly opted-in via:
    - Policy profile: solver_engine="v4"
    - Environment: SOLVER_ENGINE=v4

MEMORY LIMIT (P2 FIX):
----------------------
On Linux, applies RLIMIT_AS before solver execution to prevent OOM kills.
Configured via SOLVER_MAX_MEM_MB environment variable (default: 6144 MB = 6GB).
Set to 0 to disable (rely on Docker memory limit only).

Flow:
    1. Load tour_instances from forecast_version
    2. Apply memory limit (Linux only)
    3. Determine solver engine (V3 default, V4 opt-in)
    4. Run selected solver
    5. Store assignments in database (via tour_instance_id)
    6. Compute output_hash for reproducibility
    7. Run audit checks
    8. Return plan_version_id with status=DRAFT

NOTE: This is an MVP wrapper. Full integration requires refactoring V2 solver
      to accept tour_instances directly instead of CSV files.
"""

import hashlib
import json
import platform
import sys
from datetime import datetime
from typing import Optional, Tuple

from .config import config
from .db import (
    create_plan_version,
    get_forecast_version,
    update_plan_status,
    create_assignments_batch,
    cleanup_stale_solving_plans,
)
from .db_instances import (
    get_tour_instances,
    create_assignment_fixed,
)
from .audit_fixed import audit_plan_fixed
from .models import PlanStatus, SolverConfig
from .solver_v2_integration import solve_with_v2_solver
from .policy_snapshot import get_policy_snapshot, apply_policy_to_solver_config


# ============================================================================
# Default Solver Configuration
# ============================================================================

DEFAULT_SOLVER_CONFIG = SolverConfig(
    seed=94,
    weekly_hours_cap=55,
    freeze_window_minutes=720,
    triple_gap_min=30,
    triple_gap_max=60,
    split_break_min=240,
    split_break_max=360,
    churn_weight=0.0,
    seed_sweep_count=1,
    rest_min_minutes=660,
    span_regular_max=840,
    span_split_max=960,
)


# ============================================================================
# Memory Limit Enforcement (P2 FIX: OOM Prevention)
# ============================================================================

_memory_limit_applied = False  # Track if limit was applied this process


def apply_memory_limit() -> Tuple[bool, int, str]:
    """
    Apply memory limit to current process (Linux only).

    Uses RLIMIT_AS (address space limit) which OR-Tools respects.
    On Windows/macOS, logs warning but continues (relies on Docker limit).

    Returns:
        Tuple of (success, limit_bytes, message)
    """
    global _memory_limit_applied

    limit_mb = config.SOLVER_MAX_MEM_MB

    # Skip if disabled
    if limit_mb <= 0:
        return (True, 0, "Memory limit disabled (SOLVER_MAX_MEM_MB=0)")

    # Skip if already applied (avoid re-applying on each solve)
    if _memory_limit_applied:
        limit_bytes = limit_mb * 1024 * 1024
        return (True, limit_bytes, "Memory limit already applied")

    limit_bytes = limit_mb * 1024 * 1024

    # Platform check
    current_platform = platform.system().lower()

    if current_platform == "linux":
        try:
            import resource

            # Set soft and hard limits for address space
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            new_limit = min(limit_bytes, hard) if hard > 0 else limit_bytes

            resource.setrlimit(resource.RLIMIT_AS, (new_limit, hard))

            _memory_limit_applied = True
            print(f"[MEMORY] Applied RLIMIT_AS: {new_limit / (1024*1024):.0f}MB")

            # Try to expose metric (optional - may not be available in worker)
            try:
                from api.metrics import set_solver_memory_limit
                set_solver_memory_limit(new_limit, component="solver")
            except ImportError:
                pass

            return (True, new_limit, f"RLIMIT_AS set to {new_limit / (1024*1024):.0f}MB")

        except (ImportError, OSError, ValueError) as e:
            print(f"[MEMORY] Failed to set RLIMIT_AS: {e}")
            return (False, limit_bytes, f"Failed to set limit: {e}")

    elif current_platform == "darwin":
        # macOS: RLIMIT_AS not reliably enforced, warn and continue
        print(f"[MEMORY] macOS detected - RLIMIT not enforced, relying on Docker limit")
        return (True, limit_bytes, "macOS: relying on Docker memory limit")

    else:
        # Windows or other: warn and continue
        print(f"[MEMORY] {current_platform} detected - no RLIMIT support, relying on Docker limit")
        return (True, limit_bytes, f"{current_platform}: relying on Docker memory limit")


def get_memory_limit_status() -> dict:
    """Get current memory limit status for diagnostics."""
    limit_mb = config.SOLVER_MAX_MEM_MB

    result = {
        "configured_mb": limit_mb,
        "platform": platform.system(),
        "applied": _memory_limit_applied,
    }

    if platform.system().lower() == "linux":
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            result["rlimit_soft_bytes"] = soft if soft != resource.RLIM_INFINITY else -1
            result["rlimit_hard_bytes"] = hard if hard != resource.RLIM_INFINITY else -1
        except Exception as e:
            result["rlimit_error"] = str(e)

    return result


def run_crash_recovery(max_age_minutes: int = 60) -> int:
    """
    Clean up any stale SOLVING plans from previous crashes.

    Call this on application startup or before solving.

    Args:
        max_age_minutes: Plans SOLVING longer than this are marked FAILED

    Returns:
        Number of plans cleaned up
    """
    try:
        cleaned = cleanup_stale_solving_plans(max_age_minutes=max_age_minutes)
        if cleaned > 0:
            print(f"[CRASH RECOVERY] Cleaned {cleaned} stale SOLVING plans")
        return cleaned
    except Exception as e:
        # Don't fail if DB not available
        print(f"[CRASH RECOVERY] Skipped (DB unavailable): {e}")
        return 0


def solve_forecast(
    forecast_version_id: int,
    seed: Optional[int] = None,
    save_to_db: bool = True,
    run_audit: bool = True,
    solver_config: Optional[SolverConfig] = None,
    baseline_plan_id: Optional[int] = None,
    scenario_label: Optional[str] = None,
    tenant_id: int = 1,  # Default tenant for backward compatibility
    tenant_uuid: Optional[str] = None,  # UUID for policy lookup (ADR-002)
    pack_id: str = "roster",  # Pack identifier for policy lookup
    solver_engine: Optional[str] = None,  # ADR-003: Solver engine override ("v3" or "v4")
) -> dict:
    """
    Solve a forecast using V2 block heuristic solver.

    Args:
        forecast_version_id: ID of forecast to solve
        seed: Random seed for deterministic solver (default: config.SOLVER_SEED)
        save_to_db: Whether to save results to database
        run_audit: Whether to run audit checks after solving
        solver_config: Full solver configuration (overrides seed if provided)
        baseline_plan_id: Baseline plan for churn calculation
        scenario_label: Optional scenario name for tracking

    Returns:
        dict with:
            - plan_version_id: ID of created plan
            - assignments_count: Number of assignments created
            - drivers_count: Number of unique drivers
            - output_hash: SHA256 of assignments for reproducibility
            - audit_results: Audit check results (if run_audit=True)
            - status: "DRAFT"
            - churn_count: Changes vs baseline (if baseline provided)
            - drivers_total, fte_count, pt_count, etc.

    Raises:
        ValueError: If forecast_version not found or has no instances
    """
    # P2 FIX: Apply memory limit before solver execution
    mem_success, mem_limit, mem_msg = apply_memory_limit()
    if mem_limit > 0:
        print(f"[SOLVER] Memory limit: {mem_msg}")

    # ADR-002: Fetch policy snapshot for this tenant/pack
    policy_snapshot = None
    if tenant_uuid:
        policy_snapshot = get_policy_snapshot(tenant_uuid, pack_id)
        if not policy_snapshot.using_defaults:
            print(f"[POLICY] Using profile {policy_snapshot.profile_id} (hash: {policy_snapshot.config_hash[:16]}...)")
        else:
            print(f"[POLICY] Using pack defaults for {pack_id}")
    else:
        # No tenant UUID provided, use defaults
        policy_snapshot = get_policy_snapshot("", pack_id)
        print(f"[POLICY] No tenant_uuid provided, using defaults for {pack_id}")

    # Build solver config
    if solver_config is None:
        solver_config = SolverConfig(
            seed=seed if seed is not None else config.SOLVER_SEED,
            weekly_hours_cap=DEFAULT_SOLVER_CONFIG.weekly_hours_cap,
            freeze_window_minutes=DEFAULT_SOLVER_CONFIG.freeze_window_minutes,
            triple_gap_min=DEFAULT_SOLVER_CONFIG.triple_gap_min,
            triple_gap_max=DEFAULT_SOLVER_CONFIG.triple_gap_max,
            split_break_min=DEFAULT_SOLVER_CONFIG.split_break_min,
            split_break_max=DEFAULT_SOLVER_CONFIG.split_break_max,
            churn_weight=DEFAULT_SOLVER_CONFIG.churn_weight,
            seed_sweep_count=DEFAULT_SOLVER_CONFIG.seed_sweep_count,
            rest_min_minutes=DEFAULT_SOLVER_CONFIG.rest_min_minutes,
            span_regular_max=DEFAULT_SOLVER_CONFIG.span_regular_max,
            span_split_max=DEFAULT_SOLVER_CONFIG.span_split_max,
        )

        # Apply policy overrides to solver config
        if policy_snapshot and not policy_snapshot.using_defaults:
            config_dict = solver_config.to_dict()
            merged_config = apply_policy_to_solver_config(policy_snapshot, config_dict)
            solver_config = SolverConfig(
                seed=merged_config.get("seed", solver_config.seed),
                weekly_hours_cap=merged_config.get("weekly_hours_cap", solver_config.weekly_hours_cap),
                freeze_window_minutes=merged_config.get("freeze_window_minutes", solver_config.freeze_window_minutes),
                triple_gap_min=merged_config.get("triple_gap_min", solver_config.triple_gap_min),
                triple_gap_max=merged_config.get("triple_gap_max", solver_config.triple_gap_max),
                split_break_min=merged_config.get("split_break_min", solver_config.split_break_min),
                split_break_max=merged_config.get("split_break_max", solver_config.split_break_max),
                churn_weight=merged_config.get("churn_weight", solver_config.churn_weight),
                seed_sweep_count=merged_config.get("seed_sweep_count", solver_config.seed_sweep_count),
                rest_min_minutes=merged_config.get("rest_min_minutes", solver_config.rest_min_minutes),
                span_regular_max=merged_config.get("span_regular_max", solver_config.span_regular_max),
                span_split_max=merged_config.get("span_split_max", solver_config.span_split_max),
            )
            print(f"[POLICY] Applied policy overrides to solver config")

    # Use seed from config if not explicitly provided
    if seed is None:
        seed = solver_config.seed

    # Validate forecast exists
    forecast = get_forecast_version(forecast_version_id)
    if not forecast:
        raise ValueError(f"Forecast version {forecast_version_id} not found")

    # Check forecast status - must be PASS to solve
    if forecast.get('status') == 'FAIL':
        raise ValueError(
            f"Cannot solve FAIL forecast (forecast_version_id={forecast_version_id}). "
            "Fix parse errors before solving."
        )

    # Load tour instances
    instances = get_tour_instances(forecast_version_id)
    if not instances:
        raise ValueError(
            f"No tour instances found for forecast {forecast_version_id}. "
            "Run expand_tour_template() first."
        )

    print(f"Loaded {len(instances)} tour instances for forecast {forecast_version_id}")

    # SPEC 8.1: Freeze Window Enforcement
    # Get frozen instances and their baseline assignments
    frozen_assignments = {}
    if baseline_plan_id and solver_config.freeze_window_minutes > 0:
        frozen_ids = get_frozen_instances(
            forecast_version_id,
            baseline_plan_id,
            freeze_minutes=solver_config.freeze_window_minutes
        )
        if frozen_ids:
            print(f"[FREEZE] {len(frozen_ids)} instances frozen (within {solver_config.freeze_window_minutes}min of start)")
            # Get baseline assignments for frozen instances
            from .db_instances import get_assignments_with_instances
            baseline_assignments = get_assignments_with_instances(baseline_plan_id)
            for ba in baseline_assignments:
                if ba['tour_instance_id'] in frozen_ids:
                    frozen_assignments[ba['tour_instance_id']] = ba['driver_id']
            print(f"[FREEZE] Preserving {len(frozen_assignments)} baseline assignments")

    # =========================================================================
    # ADR-003: Solver Engine Selection
    # =========================================================================
    # Determine which solver engine to use (V3 = default, V4 = opt-in only)
    # Returns tuple: (engine, reason) for audit trail
    effective_engine, engine_reason = _determine_solver_engine(solver_engine, policy_snapshot)
    print(f"[SOLVER] solver_engine_selected={effective_engine} reason={engine_reason}")

    # Call selected solver
    solver_degraded = False
    solver_error_message = None
    try:
        if effective_engine == "v3":
            # V3: Original BlockHeuristicSolver (Min-Cost Max-Flow) - PRODUCTION DEFAULT
            # This produces 145 FTE, 0 PT for Wien pilot
            assignments = solve_with_v2_solver(instances, seed=seed)
        elif effective_engine == "v4":
            # V4: Experimental FeasibilityPipeline - R&D ONLY
            # WARNING: May timeout or produce PT overflow (regression risk)
            print(f"[SOLVER] WARNING: V4 is EXPERIMENTAL - not for production use!")
            assignments = _solve_with_v4_engine(instances, seed=seed, solver_config=solver_config)
        else:
            # Unknown engine - fall back to V3
            print(f"[SOLVER] Unknown engine '{effective_engine}', falling back to V3")
            assignments = solve_with_v2_solver(instances, seed=seed)
            effective_engine = "v3"
    except Exception as e:
        solver_degraded = True
        solver_error_message = str(e)
        print(f"[ERROR] {effective_engine.upper()} solver failed: {e}")
        print(f"[WARN] Falling back to dummy assignments - PLAN QUALITY DEGRADED")
        assignments = _create_dummy_assignments(instances, seed)

    # SPEC 8.1: Override solver assignments for frozen instances
    if frozen_assignments:
        for i, assignment in enumerate(assignments):
            instance_id = assignment['tour_instance_id']
            if instance_id in frozen_assignments:
                baseline_driver = frozen_assignments[instance_id]
                if assignment['driver_id'] != baseline_driver:
                    print(f"[FREEZE] Overriding instance {instance_id}: {assignment['driver_id']} -> {baseline_driver}")
                    assignments[i]['driver_id'] = baseline_driver
                    assignments[i]['metadata'] = assignments[i].get('metadata', {})
                    assignments[i]['metadata']['freeze_enforced'] = True
                    assignments[i]['metadata']['original_driver'] = assignment['driver_id']

    print(f"Solver created {len(assignments)} assignments using {len(set(a['driver_id'] for a in assignments))} drivers")

    # Compute solver config hash (for reproducibility)
    solver_config_dict = solver_config.to_dict()
    solver_config_dict["version"] = "v2_block_heuristic" if effective_engine == "v3" else "v4_feasibility"
    solver_config_dict["solver_engine"] = effective_engine  # ADR-003: Track engine used
    solver_config_dict["fatigue_rule"] = "no_consecutive_triples"
    solver_config_hash = hashlib.sha256(
        json.dumps(solver_config_dict, sort_keys=True).encode()
    ).hexdigest()

    # Compute output hash (for reproducibility)
    # SPEC 11: output_hash must include solver_config_hash for complete reproducibility
    output_data = {
        "solver_config_hash": solver_config_hash,
        "assignments": sorted(
            [
                {
                    "driver_id": a["driver_id"],
                    "tour_instance_id": a["tour_instance_id"],
                    "day": a["day"],
                }
                for a in assignments
            ],
            key=lambda x: (x["driver_id"], x["day"], x["tour_instance_id"])
        )
    }
    output_hash = hashlib.sha256(
        json.dumps(output_data, sort_keys=True).encode()
    ).hexdigest()

    # Create plan version with SOLVING status (crash recovery marker)
    if save_to_db:
        plan_version_id = create_plan_version(
            forecast_version_id=forecast_version_id,
            seed=seed,
            solver_config_hash=solver_config_hash,
            output_hash="",  # Placeholder, updated after batch insert
            status=PlanStatus.SOLVING.value,
            scenario_label=scenario_label,
            baseline_plan_version_id=baseline_plan_id,
            solver_config_json=solver_config_dict,
            tenant_id=tenant_id,
            # ADR-002: Policy snapshot for reproducibility
            policy_profile_id=policy_snapshot.profile_id if policy_snapshot else None,
            policy_config_hash=policy_snapshot.config_hash if policy_snapshot else None,
        )
        print(f"Created plan_version {plan_version_id} (status=SOLVING)")
        if policy_snapshot and policy_snapshot.profile_id:
            print(f"  Policy: {policy_snapshot.profile_id} (hash: {policy_snapshot.config_hash[:16]}...)")

        try:
            # TRANSACTION SAFETY: Insert ALL assignments in single transaction
            # If crash occurs here, plan stays in SOLVING state for cleanup
            count = create_assignments_batch(plan_version_id, assignments, tenant_id=tenant_id)
            print(f"Stored {count} assignments in database (batch transaction)")

            # State transition: SOLVING -> SOLVED (assignments complete)
            update_plan_status(plan_version_id, PlanStatus.SOLVED.value, output_hash)
            print(f"Plan {plan_version_id} status: SOLVING -> SOLVED")

        except Exception as e:
            # Mark plan as FAILED on any error
            update_plan_status(plan_version_id, PlanStatus.FAILED.value)
            print(f"[ERROR] Solver failed, plan {plan_version_id} marked FAILED: {e}")
            raise

        # Run audit checks
        audit_results = None
        if run_audit:
            print("Running audit checks...")
            audit_results = audit_plan_fixed(plan_version_id, save_to_db=True, tenant_id=tenant_id)
            print(f"Audit: {audit_results['checks_passed']}/{audit_results['checks_run']} checks passed")

            # State transition: SOLVED -> AUDITED (audit complete)
            update_plan_status(plan_version_id, PlanStatus.AUDITED.value)
            print(f"Plan {plan_version_id} status: SOLVED -> AUDITED")

            # State transition: AUDITED -> DRAFT (ready for review)
            update_plan_status(plan_version_id, PlanStatus.DRAFT.value)
            print(f"Plan {plan_version_id} status: AUDITED -> DRAFT")

            if not audit_results['all_passed']:
                print("WARNING: Some audit checks failed!")
                for check_name, result in audit_results['results'].items():
                    if result['status'] == 'FAIL':
                        print(f"  FAIL: {check_name} ({result['violation_count']} violations)")

        # Calculate churn vs baseline if provided
        # SPEC 8.2: If no baseline, churn must be marked N/A explicitly (never "0")
        churn_count = None  # N/A when no baseline
        churn_drivers_affected = None
        churn_percent = None
        churn_available = False

        if baseline_plan_id:
            churn = _calculate_churn(baseline_plan_id, assignments)
            churn_count = churn['churn_count']
            churn_drivers_affected = churn['drivers_affected']
            churn_percent = churn['churn_percent']
            churn_available = True

            # Store churn metrics in plan_versions
            _update_plan_churn(plan_version_id, churn_count, churn_drivers_affected)

        # Calculate driver metrics
        kpis = compute_plan_kpis(plan_version_id)

        result = {
            "plan_version_id": plan_version_id,
            "assignments_count": len(assignments),
            "drivers_count": len(set(a["driver_id"] for a in assignments)),
            "drivers_total": kpis.get('total_drivers', 0),
            "fte_count": kpis.get('total_drivers', 0) - kpis.get('pt_drivers', 0),
            "pt_count": kpis.get('pt_drivers', 0),
            "avg_weekly_hours": kpis.get('avg_work_hours', 0.0),
            "max_weekly_hours": _get_max_weekly_hours(assignments),
            "output_hash": output_hash,
            "solver_config_hash": solver_config_hash,
            "seed": seed,
            "status": PlanStatus.DRAFT.value,
            "audit_results": audit_results,
            "audits_passed": audit_results['checks_passed'] if audit_results else 0,
            "audits_total": audit_results['checks_run'] if audit_results else 0,
            "churn_count": churn_count,
            "churn_drivers_affected": churn_drivers_affected,
            "churn_percent": churn_percent,
            "churn_available": churn_available,  # False = N/A (no baseline)
            "assignments": assignments,  # Include for scenario runner
            # V2 Solver degradation flag (P0 critical: detect fallback)
            "solver_degraded": solver_degraded,
            "solver_error_message": solver_error_message,
            # ADR-002: Policy snapshot info
            "policy_profile_id": policy_snapshot.profile_id if policy_snapshot else None,
            "policy_config_hash": policy_snapshot.config_hash if policy_snapshot else None,
            "policy_using_defaults": policy_snapshot.using_defaults if policy_snapshot else True,
            # ADR-003: Solver engine tracking
            "solver_engine": effective_engine,
            "solver_engine_reason": engine_reason,
            "solver_engine_publishable": effective_engine == "v3" or config.ALLOW_V4_PUBLISH,
        }

    else:
        # Dry run (no DB save)
        result = {
            "plan_version_id": None,
            "assignments_count": len(assignments),
            "drivers_count": len(set(a["driver_id"] for a in assignments)),
            "drivers_total": len(set(a["driver_id"] for a in assignments)),
            "fte_count": 0,
            "pt_count": 0,
            "avg_weekly_hours": 0.0,
            "max_weekly_hours": 0.0,
            "output_hash": output_hash,
            "solver_config_hash": solver_config_hash,
            "seed": seed,
            "status": "DRY_RUN",
            "audit_results": None,
            "audits_passed": 0,
            "audits_total": 0,
            "churn_count": None,  # N/A in dry run
            "churn_drivers_affected": None,
            "churn_percent": None,
            "churn_available": False,  # N/A
            "assignments": assignments,
            # V2 Solver degradation flag (P0 critical: detect fallback)
            "solver_degraded": solver_degraded,
            "solver_error_message": solver_error_message,
            # ADR-002: Policy snapshot info
            "policy_profile_id": policy_snapshot.profile_id if policy_snapshot else None,
            "policy_config_hash": policy_snapshot.config_hash if policy_snapshot else None,
            "policy_using_defaults": policy_snapshot.using_defaults if policy_snapshot else True,
            # ADR-003: Solver engine tracking
            "solver_engine": effective_engine,
            "solver_engine_reason": engine_reason,
            "solver_engine_publishable": effective_engine == "v3" or config.ALLOW_V4_PUBLISH,
        }

    return result


# ============================================================================
# ADR-003: Solver Engine Selection Helpers
# ============================================================================

def _determine_solver_engine(
    explicit_override: Optional[str],
    policy_snapshot: Optional[object]
) -> tuple:
    """
    Determine which solver engine to use.

    Priority (highest to lowest):
    1. Explicit override parameter (solver_engine="v4")
    2. Policy profile setting (solver_engine in config)
    3. Environment variable (SOLVER_ENGINE)
    4. Default: "v3" (ALWAYS)

    See: docs/SOLVER_ENGINE_PRECEDENCE.md

    Args:
        explicit_override: Explicit engine override from caller
        policy_snapshot: Policy snapshot with config

    Returns:
        Tuple of (engine, reason) where:
        - engine: "v3" or "v4" (defaults to "v3" if unknown)
        - reason: "explicit_override" | "policy" | "env" | "default"
    """
    # 1. Explicit override takes precedence
    if explicit_override and explicit_override.lower() in ("v3", "v4"):
        return (explicit_override.lower(), "explicit_override")

    # 2. Policy profile setting
    if policy_snapshot and hasattr(policy_snapshot, 'config'):
        policy_config = policy_snapshot.config
        if isinstance(policy_config, dict) and 'solver_engine' in policy_config:
            engine = policy_config['solver_engine']
            if engine in ("v3", "v4"):
                return (engine, "policy")

    # 3. Environment variable
    env_engine = config.SOLVER_ENGINE
    if env_engine in ("v3", "v4"):
        return (env_engine, "env")

    # 4. Default: V3 (ALWAYS - this is non-negotiable for production)
    return ("v3", "default")


def _solve_with_v4_engine(
    instances: list[dict],
    seed: int,
    solver_config: Optional[SolverConfig] = None
) -> list[dict]:
    """
    Solve using V4 experimental FeasibilityPipeline.

    WARNING: This is EXPERIMENTAL and may:
    - Timeout on complex inputs
    - Produce PT overflow (regression from 145 FTE / 0 PT)
    - Have non-deterministic behavior

    Args:
        instances: Tour instances to solve
        seed: Random seed
        solver_config: Solver configuration

    Returns:
        List of assignment dicts

    Raises:
        ImportError: If V4 solver not available
        Exception: If solver fails
    """
    try:
        # Attempt to import V4 solver
        from v3.src_compat.forecast_solver_v4 import solve_forecast_fte_only, ConfigV4
        from v3.src_compat.models import Tour, Weekday

        # Convert instances to Tour objects
        V3_DAY_TO_WEEKDAY = {
            1: Weekday.MONDAY,
            2: Weekday.TUESDAY,
            3: Weekday.WEDNESDAY,
            4: Weekday.THURSDAY,
            5: Weekday.FRIDAY,
            6: Weekday.SATURDAY,
            7: Weekday.SUNDAY,
        }

        tours = []
        for inst in instances:
            day = inst.get('day', 1)
            weekday = V3_DAY_TO_WEEKDAY.get(day, Weekday.MONDAY)
            tour = Tour(
                id=f"T{inst['id']}",
                day=weekday,
                start_time=inst['start_ts'],
                end_time=inst['end_ts'],
            )
            tours.append(tour)

        # Run V4 solver
        time_limit = solver_config.solver_time_limit_seconds if solver_config else 300.0
        result = solve_forecast_fte_only(tours, time_limit=float(time_limit), seed=seed)

        # Convert V4 result to assignment format
        assignments = []
        for driver_assignment in result.assignments:
            driver_id = driver_assignment.driver_id
            for block in driver_assignment.blocks:
                for tour in block.tours:
                    # Extract tour instance ID from tour.id (format: "T{id}")
                    tour_instance_id = int(tour.id[1:]) if tour.id.startswith("T") else 0
                    assignments.append({
                        "driver_id": driver_id,
                        "tour_instance_id": tour_instance_id,
                        "day": list(V3_DAY_TO_WEEKDAY.keys())[
                            list(V3_DAY_TO_WEEKDAY.values()).index(block.day)
                        ] if block.day in V3_DAY_TO_WEEKDAY.values() else 1,
                        "block_id": block.id,
                        "role": "PRIMARY",
                        "metadata": {
                            "solver_engine": "v4",
                            "block_type": f"{len(block.tours)}er",
                            "driver_type": driver_assignment.driver_type,
                        }
                    })

        return assignments

    except ImportError as e:
        raise ImportError(f"V4 solver not available: {e}. Use V3 instead.")
    except Exception as e:
        raise Exception(f"V4 solver failed: {e}")


def _create_dummy_assignments(instances: list[dict], seed: int) -> list[dict]:
    """
    Create dummy assignments for MVP demonstration.

    TODO (FULL M4): Replace with actual V2 solver call.

    This function creates a simple greedy assignment:
    - Assign each instance to a unique driver
    - Driver IDs: D001, D002, D003, ...
    - One instance per driver per day (1er blocks)
    """
    import random
    random.seed(seed)

    assignments = []

    # Group instances by day
    from collections import defaultdict
    instances_by_day = defaultdict(list)
    for instance in instances:
        instances_by_day[instance['day']].append(instance)

    # Simple greedy: one driver per instance per day
    driver_counter = 1

    for day in sorted(instances_by_day.keys()):
        day_instances = sorted(instances_by_day[day], key=lambda x: x['start_ts'])

        for instance in day_instances:
            driver_id = f"D{driver_counter:03d}"
            block_id = f"D{day}_B1"  # Day X, Block 1 (1er)

            assignments.append({
                "driver_id": driver_id,
                "tour_instance_id": instance['id'],
                "day": day,
                "block_id": block_id,
                "role": "PRIMARY",
                "metadata": {
                    "solver_note": "MVP dummy assignment (1 driver per instance)",
                    "seed": seed
                }
            })

            driver_counter += 1

    # Shuffle to make it deterministic but realistic
    random.shuffle(assignments)

    return assignments


def compute_plan_kpis(plan_version_id: int) -> dict:
    """
    Compute KPIs for a plan version.

    Returns:
        dict with KPIs:
            - total_drivers: Total number of drivers
            - avg_work_hours: Average work hours per driver
            - pt_drivers: Number of part-time drivers (<40h)
            - block_mix: Distribution of 1er/2er/3er blocks
            - peak_concurrent: Max concurrent active tours
    """
    from .db_instances import get_assignments_with_instances
    from collections import defaultdict

    assignments = get_assignments_with_instances(plan_version_id)

    # Group by driver
    driver_hours = defaultdict(float)
    driver_blocks = defaultdict(list)

    for a in assignments:
        driver_id = a['driver_id']
        work_hours = float(a.get('work_hours', 0))
        driver_hours[driver_id] += work_hours
        driver_blocks[driver_id].append(a)

    total_drivers = len(driver_hours)
    avg_work_hours = sum(driver_hours.values()) / total_drivers if total_drivers > 0 else 0
    pt_drivers = sum(1 for hours in driver_hours.values() if hours < 40)

    # Block mix (count tours per driver per day)
    block_counts = defaultdict(int)
    for driver_id, driver_assignments in driver_blocks.items():
        tours_per_day = defaultdict(int)
        for a in driver_assignments:
            tours_per_day[a['day']] += 1

        for day, tour_count in tours_per_day.items():
            if tour_count == 1:
                block_counts['1er'] += 1
            elif tour_count == 2:
                block_counts['2er'] += 1
            elif tour_count >= 3:
                block_counts['3er'] += 1

    total_blocks = sum(block_counts.values())
    block_mix = {
        k: {
            "count": v,
            "percentage": round(100 * v / total_blocks, 1) if total_blocks > 0 else 0
        }
        for k, v in block_counts.items()
    }

    kpis = {
        "total_drivers": total_drivers,
        "avg_work_hours": round(avg_work_hours, 2),
        "pt_drivers": pt_drivers,
        "pt_ratio": round(100 * pt_drivers / total_drivers, 1) if total_drivers > 0 else 0,
        "block_mix": block_mix,
        "total_blocks": total_blocks
    }

    return kpis


# Convenience function (matches old API)
def solve_and_audit(forecast_version_id: int, seed: Optional[int] = None) -> dict:
    """
    Solve forecast and run audits (one-step convenience function).

    This is the primary entry point for creating a new plan from a forecast.

    Returns:
        Complete result dict with plan_version_id, KPIs, and audit results.
    """
    result = solve_forecast(
        forecast_version_id=forecast_version_id,
        seed=seed,
        save_to_db=True,
        run_audit=True
    )

    # Add KPIs
    if result['plan_version_id']:
        kpis = compute_plan_kpis(result['plan_version_id'])
        result['kpis'] = kpis

    return result


# ============================================================================
# Churn Calculation Helpers
# ============================================================================

def _calculate_churn(baseline_plan_id: int, new_assignments: list[dict]) -> dict:
    """
    Calculate churn between baseline and new assignments.

    Churn = number of instance-level changes (added/removed/changed driver).

    Args:
        baseline_plan_id: Baseline plan ID
        new_assignments: New assignments list

    Returns:
        dict with churn metrics
    """
    from .db_instances import get_assignments_with_instances

    try:
        baseline_assignments = get_assignments_with_instances(baseline_plan_id)
    except Exception:
        return {'churn_count': 0, 'drivers_affected': 0, 'churn_percent': 0.0}

    # Build baseline map: tour_instance_id -> (driver_id, block_id)
    baseline_map = {
        a['tour_instance_id']: (a['driver_id'], a.get('block_id', ''))
        for a in baseline_assignments
    }

    # Build new map
    new_map = {
        a['tour_instance_id']: (a['driver_id'], a.get('block_id', ''))
        for a in new_assignments
    }

    # Calculate differences
    all_instances = set(baseline_map.keys()) | set(new_map.keys())
    churn_count = 0
    affected_drivers = set()

    for instance_id in all_instances:
        baseline_val = baseline_map.get(instance_id)
        new_val = new_map.get(instance_id)

        if baseline_val != new_val:
            churn_count += 1

            if baseline_val:
                affected_drivers.add(baseline_val[0])
            if new_val:
                affected_drivers.add(new_val[0])

    total_instances = len(all_instances)
    churn_percent = (churn_count / total_instances * 100) if total_instances > 0 else 0.0

    return {
        'churn_count': churn_count,
        'drivers_affected': len(affected_drivers),
        'churn_percent': round(churn_percent, 2),
    }


def _update_plan_churn(plan_version_id: int, churn_count: int, churn_drivers: int) -> None:
    """
    Update churn metrics in plan_versions table.

    Args:
        plan_version_id: Plan to update
        churn_count: Number of instance changes
        churn_drivers: Number of affected drivers
    """
    from .db import get_connection

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE plan_versions
                    SET churn_count = %s, churn_drivers_affected = %s
                    WHERE id = %s
                """, (churn_count, churn_drivers, plan_version_id))
            conn.commit()
    except Exception as e:
        print(f"[WARN] Could not update churn metrics: {e}")


def _get_max_weekly_hours(assignments: list[dict]) -> float:
    """
    Get max weekly hours across all drivers.

    Args:
        assignments: List of assignment dicts

    Returns:
        Max weekly hours
    """
    from collections import defaultdict

    driver_hours = defaultdict(float)
    for a in assignments:
        driver_id = a['driver_id']
        work_hours = float(a.get('work_hours', 0))
        driver_hours[driver_id] += work_hours

    if not driver_hours:
        return 0.0

    return max(driver_hours.values())


# ============================================================================
# Freeze Window Helpers
# ============================================================================

def check_freeze_violations(
    forecast_version_id: int,
    baseline_plan_id: Optional[int],
    freeze_minutes: int = 720
) -> list[dict]:
    """
    Check for freeze window violations.

    A freeze violation occurs when:
    1. A tour instance is within freeze_minutes of starting
    2. The assignment differs from the baseline

    Args:
        forecast_version_id: Forecast to check
        baseline_plan_id: Baseline plan (last LOCKED)
        freeze_minutes: Freeze window in minutes (default 12h)

    Returns:
        List of violation dicts with instance details
    """
    from datetime import timedelta
    from .db import get_forecast_version
    from .db_instances import get_tour_instances, get_assignments_with_instances

    if not baseline_plan_id:
        return []  # No baseline = no freeze violations

    forecast = get_forecast_version(forecast_version_id)
    if not forecast:
        return []

    week_anchor = forecast.get('week_anchor_date')
    if not week_anchor:
        return []  # Cannot compute without anchor

    now = datetime.now()
    freeze_threshold = now + timedelta(minutes=freeze_minutes)

    instances = get_tour_instances(forecast_version_id)
    baseline_assignments = get_assignments_with_instances(baseline_plan_id)

    # Build baseline map
    baseline_map = {
        a['tour_instance_id']: a['driver_id']
        for a in baseline_assignments
    }

    violations = []
    for instance in instances:
        # Compute instance start datetime
        day_offset = instance['day'] - 1  # Day 1 = Monday = offset 0
        start_ts = instance['start_ts']

        instance_start = datetime.combine(
            week_anchor + timedelta(days=day_offset),
            start_ts
        )

        # Handle cross-midnight
        if instance.get('crosses_midnight'):
            # Start is on the previous day's evening
            pass  # Still uses same logic

        # Check if within freeze window
        if instance_start <= freeze_threshold:
            instance_id = instance['id']
            baseline_driver = baseline_map.get(instance_id)

            if baseline_driver:
                violations.append({
                    'instance_id': instance_id,
                    'day': instance['day'],
                    'start_ts': str(start_ts),
                    'instance_start': instance_start.isoformat(),
                    'frozen_driver': baseline_driver,
                    'minutes_until_start': int((instance_start - now).total_seconds() / 60),
                })

    return violations


def get_frozen_instances(
    forecast_version_id: int,
    baseline_plan_id: int,
    freeze_minutes: int = 720
) -> set[int]:
    """
    Get set of frozen tour instance IDs.

    Frozen = within freeze window AND has baseline assignment.

    Args:
        forecast_version_id: Forecast to check
        baseline_plan_id: Baseline plan
        freeze_minutes: Freeze window

    Returns:
        Set of frozen instance IDs
    """
    violations = check_freeze_violations(
        forecast_version_id, baseline_plan_id, freeze_minutes
    )
    return {v['instance_id'] for v in violations}
