"""
SHIFT OPTIMIZER - Config Validator
====================================
Server-side validation, clamping, and tracking of configuration overrides.
Implements: Whitelist, Range Clamp, Locked Fields, Effective Config Snapshot.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.services.forecast_solver_v4 import ConfigV4


# =============================================================================
# LOCKED FIELDS (INVARIANTS - Cannot be overridden)
# =============================================================================

LOCKED_FIELDS = {
    "num_search_workers": {"value": 1, "reason": "Determinism invariant"},
    "use_deterministic_time": {"value": True, "reason": "Determinism invariant"},
    "enable_lp_rmp_column_generation": {"value": False, "reason": "Postponed to v2.1"},
}


# =============================================================================
# TUNABLE FIELDS (Whitelisted with ranges)
# =============================================================================

TUNABLE_FIELDS = {
    # Feature flags (bool)
    "enable_fill_to_target_greedy": {"type": "bool", "default": False},
    "enable_bad_block_mix_rerun": {"type": "bool", "default": False},
    "enable_packability_costs": {"type": "bool", "default": True},
    "enable_bounded_swaps": {"type": "bool", "default": True},
    "enable_diag_block_caps": {"type": "bool", "default": False},  # Block capping diagnostics
    
    # Penalties (float)
    "penalty_1er_with_multi": {"type": "float", "default": 2.0, "min": 0.0, "max": 100.0},
    "bonus_3er": {"type": "float", "default": -3.0, "min": -100.0, "max": 0.0},
    "bonus_2er": {"type": "float", "default": -1.0, "min": -100.0, "max": 0.0},
    
    # Block capping
    "cap_quota_2er": {"type": "float", "default": 0.30, "min": 0.0, "max": 1.0},  # 2-tour block quota
    
    # Thresholds
    "pt_ratio_threshold": {"type": "float", "default": 0.25, "min": 0.0, "max": 1.0},
    "underfull_ratio_threshold": {"type": "float", "default": 0.15, "min": 0.0, "max": 1.0},
    
    # Rerun
    "rerun_1er_penalty_multiplier": {"type": "float", "default": 2.0, "min": 1.0, "max": 10.0},
    "min_rerun_budget": {"type": "float", "default": 5.0, "min": 1.0, "max": 60.0},
    
    # Repair bounds (int)
    "repair_pt_limit": {"type": "int", "default": 20, "min": 0, "max": 100},
    "repair_fte_limit": {"type": "int", "default": 30, "min": 0, "max": 100},
    "repair_block_limit": {"type": "int", "default": 100, "min": 0, "max": 500},
    
    # Hours
    "max_hours_per_fte": {"type": "float", "default": 53.0, "min": 40.0, "max": 56.0},
    "min_hours_per_fte": {"type": "float", "default": 42.0, "min": 35.0, "max": 50.0},
    "fte_hours_target": {"type": "float", "default": 49.5, "min": 42.0, "max": 55.0},
    
    # =========================================================================
    # DIAGNOSTIC: Solver Mode Override
    # =========================================================================
    "solver_mode": {"type": "str", "default": "HEURISTIC",
                    "allowed": ["GREEDY", "CPSAT", "SETPART", "HEURISTIC"]},
    
    # =========================================================================
    # LNS ENDGAME: Low-Hour Pattern Consolidation
    # =========================================================================
    "enable_lns_low_hour_consolidation": {"type": "bool", "default": False},
    "lns_time_budget_s": {"type": "float", "default": 60.0, "min": 0.0, "max": 300.0},
    "lns_low_hour_threshold_h": {"type": "float", "default": 40.0, "min": 0.0, "max": 50.0},
    
    # =========================================================================
    # OUTPUT PROFILES: MIN_HEADCOUNT_3ER vs BEST_BALANCED
    # =========================================================================
    "output_profile": {"type": "str", "default": "BEST_BALANCED",
                       "allowed": ["MIN_HEADCOUNT_3ER", "BEST_BALANCED"]},
    
    # 3er Gap Constraints (MIN_HEADCOUNT_3ER)
    "gap_3er_min_minutes": {"type": "int", "default": 30, "min": 0, "max": 180},
    "cap_quota_3er": {"type": "float", "default": 0.25, "min": 0.0, "max": 0.50},
    "pass2_min_time_s": {"type": "float", "default": 30.0, "min": 1.0, "max": 600.0},
    "w_choice_1er": {"type": "float", "default": 1.0, "min": 0.0, "max": 32.0},
    "w_3er_bonus": {"type": "float", "default": 10.0, "min": 0.0, "max": 100.0},
    
    # BEST_BALANCED weights
    "max_extra_driver_pct": {"type": "float", "default": 0.05, "min": 0.0, "max": 0.20},
    "w_balance_underfull": {"type": "float", "default": 100.0, "min": 0.0, "max": 1000.0},
    "w_pt_penalty": {"type": "float", "default": 500.0, "min": 0.0, "max": 5000.0},
    "w_balance_variance": {"type": "float", "default": 50.0, "min": 0.0, "max": 500.0},
}


@dataclass
class ConfigValidationResult:
    """Result of config validation."""
    config_effective: ConfigV4
    config_effective_hash: str
    overrides_applied: Dict[str, Any] = field(default_factory=dict)
    overrides_rejected: Dict[str, str] = field(default_factory=dict)  # key -> reason
    overrides_clamped: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)  # key -> (original, clamped)
    reason_codes: List[str] = field(default_factory=list)


def validate_and_apply_overrides(
    base_config: ConfigV4,
    overrides: Dict[str, Any],
    seed: Optional[int] = None
) -> ConfigValidationResult:
    """
    Validate, clamp, and apply config overrides.
    
    Returns:
        ConfigValidationResult with effective config and audit trail.
    """
    applied = {}
    rejected = {}
    clamped = {}
    reason_codes = []
    
    # Start with base config
    effective_config = base_config
    
    # Get valid ConfigV4 field names
    config_fields = set(base_config._fields)
    
    # Process each override
    for key, value in overrides.items():
        # Check if locked (virtual fields that cannot be changed)
        if key in LOCKED_FIELDS:
            rejected[key] = f"LOCKED_FIELD:{LOCKED_FIELDS[key]['reason']}"
            reason_codes.append(f"LOCKED_FIELD_OVERRIDE_ATTEMPT:{key}")
            continue
            
        # Check if tunable
        if key not in TUNABLE_FIELDS:
            rejected[key] = "UNKNOWN_FIELD"
            reason_codes.append(f"UNKNOWN_OVERRIDE_KEY:{key}")
            continue
            
        # Check if it's actually a field in ConfigV4
        if key not in config_fields:
            # Tunable but not in ConfigV4 (future field or alias)
            rejected[key] = "FIELD_NOT_IN_CONFIG"
            reason_codes.append(f"FIELD_NOT_FOUND:{key}")
            continue
            
        spec = TUNABLE_FIELDS[key]
        
        # Type check
        expected_type = spec["type"]
        if expected_type == "bool" and not isinstance(value, bool):
            rejected[key] = f"TYPE_ERROR:expected_bool"
            reason_codes.append(f"TYPE_ERROR:{key}")
            continue
        elif expected_type == "float" and not isinstance(value, (int, float)):
            rejected[key] = f"TYPE_ERROR:expected_float"
            reason_codes.append(f"TYPE_ERROR:{key}")
            continue
        elif expected_type == "int" and not isinstance(value, int):
            rejected[key] = f"TYPE_ERROR:expected_int"
            reason_codes.append(f"TYPE_ERROR:{key}")
            continue
        elif expected_type == "str":
            if not isinstance(value, str):
                rejected[key] = f"TYPE_ERROR:expected_str"
                reason_codes.append(f"TYPE_ERROR:{key}")
                continue
            # Check enum values if specified
            if "allowed" in spec and value not in spec["allowed"]:
                rejected[key] = f"ENUM_ERROR:must_be_one_of_{spec['allowed']}"
                reason_codes.append(f"ENUM_ERROR:{key}")
                continue
            
        # Convert int to float if needed
        if expected_type == "float" and isinstance(value, int):
            value = float(value)
            
        # Range clamp
        original_value = value
        if "min" in spec and value < spec["min"]:
            value = spec["min"]
        if "max" in spec and value > spec["max"]:
            value = spec["max"]
            
        if value != original_value:
            clamped[key] = (original_value, value)
            reason_codes.append(f"VALUE_CLAMPED:{key}:{original_value}->{value}")
            
        # Apply using _replace
        effective_config = effective_config._replace(**{key: value})
        applied[key] = value
    
    # Apply seed if provided
    if seed is not None:
        effective_config = effective_config._replace(seed=seed)
        applied["seed"] = seed
    
    # Compute hash
    # Use canonical JSON of the effective config for hashing
    hash_input = json.dumps(effective_config._asdict(), sort_keys=True)
    config_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    return ConfigValidationResult(
        config_effective=effective_config,
        config_effective_hash=config_hash,
        overrides_applied=applied,
        overrides_rejected=rejected,
        overrides_clamped=clamped,
        reason_codes=reason_codes
    )


def config_to_canonical_dict(config: ConfigV4) -> dict:
    """Convert config to canonical dict for serialization."""
    return {k: v for k, v in sorted(config._asdict().items())}
