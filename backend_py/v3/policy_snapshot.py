"""
Policy Snapshot Helper (V3 Integration)

Provides policy profile snapshot functionality for the V3 solver.
Integrates with the kernel PolicyService for ADR-002 compliance.

Usage:
    from .policy_snapshot import get_policy_snapshot, apply_policy_to_solver_config

    # Get active policy for tenant
    snapshot = get_policy_snapshot(tenant_id="uuid", pack_id="roster")

    # Apply policy overrides to solver config
    solver_config = apply_policy_to_solver_config(snapshot, default_config)
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class PolicySnapshot:
    """
    Snapshot of policy configuration at solve time.

    This is stored with each plan_version for reproducibility.
    """
    profile_id: Optional[str]  # UUID of the policy profile (None = using defaults)
    config: Dict[str, Any]  # Configuration dictionary
    config_hash: str  # SHA256 hash for determinism verification
    schema_version: str  # Schema version
    using_defaults: bool  # True if no custom policy configured


# =============================================================================
# DEFAULT CONFIGURATIONS (Fallbacks when no policy configured)
# =============================================================================

DEFAULT_ROSTER_CONFIG = {
    # Driver constraints (German labor law compliant defaults)
    "max_weekly_hours": 55,
    "min_rest_hours": 11,
    "max_span_regular_hours": 14,
    "max_span_split_hours": 16,

    # Split break constraints
    "min_split_break_minutes": 240,
    "max_split_break_minutes": 360,

    # Block construction
    "min_gap_between_tours_minutes": 30,
    "max_gap_between_tours_minutes": 60,

    # Optimization preferences
    "optimization_goal": "minimize_drivers",
    "prefer_fte_over_pt": True,
    "minimize_splits": True,
    "allow_3er_consecutive": False,

    # Solver settings
    "solver_time_limit_seconds": 300,
    "seed": 94,
    "refinement_passes": 3,

    # Audit settings
    "fail_on_audit_warning": False,
    "required_coverage_percent": 100.0,
}

DEFAULT_ROUTING_CONFIG = {
    # Vehicle constraints
    "max_route_duration_hours": 10,
    "max_stops_per_route": 50,
    "default_service_time_minutes": 15,

    # Time window handling
    "time_window_slack_minutes": 15,
    "allow_waiting": True,
    "max_waiting_minutes": 30,

    # Solver settings
    "solver_time_limit_seconds": 300,
    "metaheuristic": "GUIDED_LOCAL_SEARCH",
    "solution_limit": 100,

    # Freeze/lock settings
    "freeze_horizon_minutes": 60,
    "auto_lock_on_dispatch": True,

    # Evidence settings
    "require_evidence_hash": True,
    "artifact_retention_days": 90,
}


def compute_config_hash(config: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash of configuration for determinism verification.

    Args:
        config: Configuration dictionary

    Returns:
        Hex-encoded SHA256 hash
    """
    canonical = json.dumps(config, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_policy_snapshot(
    tenant_id: str,
    pack_id: str,
    policy_service=None,
) -> PolicySnapshot:
    """
    Get policy snapshot for a tenant/pack.

    Args:
        tenant_id: UUID of the tenant
        pack_id: Pack identifier ("roster" or "routing")
        policy_service: Optional PolicyService instance (for async context)

    Returns:
        PolicySnapshot with config and hash

    Note:
        If policy_service is not provided, returns defaults.
        This supports both sync (V3 solver) and async (API) contexts.
    """
    # Determine default config based on pack
    if pack_id == "roster":
        default_config = DEFAULT_ROSTER_CONFIG
    elif pack_id == "routing":
        default_config = DEFAULT_ROUTING_CONFIG
    else:
        default_config = {}

    # If no service provided, return defaults
    if policy_service is None:
        return PolicySnapshot(
            profile_id=None,
            config=default_config,
            config_hash=compute_config_hash(default_config),
            schema_version="1.0",
            using_defaults=True,
        )

    # Try to get from database (sync fallback for V3)
    try:
        result = _get_policy_sync(tenant_id, pack_id)
        if result:
            return PolicySnapshot(
                profile_id=result["profile_id"],
                config=result["config"],
                config_hash=result["config_hash"],
                schema_version=result["schema_version"],
                using_defaults=False,
            )
    except Exception as e:
        print(f"[WARN] Could not fetch policy for {tenant_id}/{pack_id}: {e}")

    # Fallback to defaults
    return PolicySnapshot(
        profile_id=None,
        config=default_config,
        config_hash=compute_config_hash(default_config),
        schema_version="1.0",
        using_defaults=True,
    )


def _get_policy_sync(tenant_id: str, pack_id: str) -> Optional[Dict[str, Any]]:
    """
    Synchronous database lookup for active policy.

    Used by V3 solver wrapper (sync context).
    """
    from .db import get_connection

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Try the core.get_active_policy function if available
                try:
                    cur.execute("""
                        SELECT
                            profile_id,
                            config_json as config,
                            config_hash,
                            schema_version,
                            use_defaults
                        FROM core.get_active_policy(%s, %s)
                    """, (tenant_id, pack_id))
                    row = cur.fetchone()

                    if row and not row.get("use_defaults") and row.get("profile_id"):
                        return {
                            "profile_id": str(row["profile_id"]),
                            "config": row["config"],
                            "config_hash": row["config_hash"],
                            "schema_version": row["schema_version"],
                        }
                except Exception:
                    # Function might not exist yet, try direct query
                    pass

                # Direct query fallback
                cur.execute("""
                    SELECT
                        pp.id as profile_id,
                        pp.config_json as config,
                        pp.config_hash,
                        pp.schema_version
                    FROM core.tenant_pack_settings tps
                    JOIN core.policy_profiles pp ON pp.id = tps.active_profile_id
                    WHERE tps.tenant_id = %s::uuid
                      AND tps.pack_id = %s
                      AND tps.use_pack_defaults = false
                      AND pp.status = 'active'
                """, (tenant_id, pack_id))
                row = cur.fetchone()

                if row:
                    return {
                        "profile_id": str(row["profile_id"]),
                        "config": row["config"],
                        "config_hash": row["config_hash"],
                        "schema_version": row["schema_version"],
                    }

    except Exception as e:
        # Schema might not exist yet
        print(f"[DEBUG] Policy lookup failed (schema may not exist): {e}")

    return None


def apply_policy_to_solver_config(
    snapshot: PolicySnapshot,
    base_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply policy overrides to solver configuration.

    Args:
        snapshot: Policy snapshot
        base_config: Base solver config dict

    Returns:
        Merged config with policy overrides applied
    """
    if snapshot.using_defaults or not snapshot.config:
        return base_config

    merged = base_config.copy()

    # Map policy fields to solver config fields (roster pack)
    roster_mappings = {
        "max_weekly_hours": "weekly_hours_cap",
        "min_rest_hours": lambda v: ("rest_min_minutes", v * 60),
        "max_span_regular_hours": lambda v: ("span_regular_max", v * 60),
        "max_span_split_hours": lambda v: ("span_split_max", v * 60),
        "min_split_break_minutes": "split_break_min",
        "max_split_break_minutes": "split_break_max",
        "min_gap_between_tours_minutes": "triple_gap_min",
        "max_gap_between_tours_minutes": "triple_gap_max",
        "solver_time_limit_seconds": "time_limit_seconds",
        "seed": "seed",
        "refinement_passes": "refinement_passes",
    }

    for policy_key, value in snapshot.config.items():
        if policy_key in roster_mappings:
            mapping = roster_mappings[policy_key]
            if callable(mapping):
                target_key, transformed_value = mapping(value)
                merged[target_key] = transformed_value
            else:
                merged[mapping] = value

    return merged


# =============================================================================
# ASYNC HELPERS (for API context)
# =============================================================================

async def get_policy_snapshot_async(
    tenant_id: str,
    pack_id: str,
    policy_service,
) -> PolicySnapshot:
    """
    Async version of get_policy_snapshot.

    Used by API routers with PolicyService dependency.
    """
    from api.services.policy_service import ActivePolicy, PolicyNotFound

    # Determine default config based on pack
    if pack_id == "roster":
        default_config = DEFAULT_ROSTER_CONFIG
    elif pack_id == "routing":
        default_config = DEFAULT_ROUTING_CONFIG
    else:
        default_config = {}

    try:
        result = await policy_service.get_active_policy(tenant_id, pack_id)

        if isinstance(result, PolicyNotFound):
            return PolicySnapshot(
                profile_id=None,
                config=default_config,
                config_hash=compute_config_hash(default_config),
                schema_version="1.0",
                using_defaults=True,
            )

        return PolicySnapshot(
            profile_id=result.profile_id,
            config=result.config,
            config_hash=result.config_hash,
            schema_version=result.schema_version,
            using_defaults=False,
        )

    except Exception as e:
        print(f"[WARN] Async policy lookup failed: {e}")
        return PolicySnapshot(
            profile_id=None,
            config=default_config,
            config_hash=compute_config_hash(default_config),
            schema_version="1.0",
            using_defaults=True,
        )
