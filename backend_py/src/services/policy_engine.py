"""
POLICY ENGINE - Deterministic Path & Parameter Selection
========================================================
Selects solver path (A/B/C) and adapts parameters based on instance features.

Rules are deterministic: same features -> same path + parameters.
No ML, no randomness.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from src.services.instance_profiler import FeatureVector

logger = logging.getLogger("PolicyEngine")


# =============================================================================
# PATH SELECTION
# =============================================================================

class PathSelection(Enum):
    """Solver path selection."""
    A = "FAST"       # Fast mode: Greedy + Light LNS
    B = "BALANCED"   # Balanced mode: Heuristic + Extended LNS
    C = "HEAVY"      # Heavy mode: Set-Partitioning + Fallback


# =============================================================================
# REASON CODES
# =============================================================================

class ReasonCode:
    """Reason codes for path selection and events."""
    # Path selection reasons
    NORMAL_INSTANCE = "NORMAL_INSTANCE"
    PEAKY_HIGH = "PEAKY_HIGH"
    PEAKY_OR_PT_PRESSURE = "PEAKY_OR_PT_PRESSURE"
    POOL_TOO_LARGE = "POOL_TOO_LARGE"
    PT_RATE_HIGH = "PT_RATE_HIGH"
    REST_RISK_HIGH = "REST_RISK_HIGH"
    
    # Early stop reasons
    GOOD_ENOUGH = "GOOD_ENOUGH"
    NEAR_DAYMIN = "NEAR_DAYMIN"
    TIME_BUDGET_EXHAUSTED = "TIME_BUDGET_EXHAUSTED"
    
    # Fallback reasons
    STAGNATION = "STAGNATION"
    PATH_A_FAILED = "PATH_A_FAILED"
    PATH_B_FAILED = "PATH_B_FAILED"
    FALLBACK_PATH_B = "FALLBACK_PATH_B"
    FALLBACK_PATH_C = "FALLBACK_PATH_C"
    
    # Success reasons
    OPTIMAL_FOUND = "OPTIMAL_FOUND"
    FEASIBLE_SOLUTION = "FEASIBLE_SOLUTION"


# =============================================================================
# PARAMETER BUNDLE
# =============================================================================

@dataclass
class ParameterBundle:
    """
    Solver parameters adapted for the selected path.
    """
    # Path info
    path: PathSelection
    reason_code: str = "OK"  # Default to avoid missing arg errors
    
    # LNS parameters
    lns_iterations: int = 100
    lns_time_limit_s: float = 30.0
    destroy_fraction: float = 0.15
    repair_time_limit_s: float = 5.0
    
    # PT handling
    pt_focused_destroy_weight: float = 0.3
    enable_pt_elimination: bool = True
    
    # Set-Partitioning parameters (Path C)
    sp_enabled: bool = False
    column_gen_quota: int = 200
    pool_cap: int = 5000
    pricing_time_limit_s: float = 15.0
    sp_max_rounds: int = 100
    
    # Phase 1 parameters
    phase1_time_limit_s: float = 60.0
    
    # Early stop parameters
    epsilon: float = 0.02           # Gap tolerance (2%)
    daymin_buffer: int = 2          # Allow drivers = daymin + buffer
    stagnation_iters: int = 20      # Iterations without improvement
    repair_failure_threshold: float = 0.3  # 30% failure rate triggers fallback
    
    # Heuristic solver parameters
    heuristic_improvement_budget_s: float = 15.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "path": self.path.value,
            "reason_code": self.reason_code,
            "lns_iterations": self.lns_iterations,
            "lns_time_limit_s": self.lns_time_limit_s,
            "destroy_fraction": self.destroy_fraction,
            "repair_time_limit_s": self.repair_time_limit_s,
            "pt_focused_destroy_weight": self.pt_focused_destroy_weight,
            "enable_pt_elimination": self.enable_pt_elimination,
            "sp_enabled": self.sp_enabled,
            "column_gen_quota": self.column_gen_quota,
            "pool_cap": self.pool_cap,
            "pricing_time_limit_s": self.pricing_time_limit_s,
            "sp_max_rounds": self.sp_max_rounds,
            "phase1_time_limit_s": self.phase1_time_limit_s,
            "epsilon": self.epsilon,
            "daymin_buffer": self.daymin_buffer,
            "stagnation_iters": self.stagnation_iters,
            "repair_failure_threshold": self.repair_failure_threshold,
            "heuristic_improvement_budget_s": self.heuristic_improvement_budget_s,
        }


# =============================================================================
# PATH SELECTION RULES
# =============================================================================

# Thresholds for path selection
PEAKINESS_THRESHOLD_B = 0.35      # >= 35% concentration -> Path B
PT_PRESSURE_THRESHOLD_B = 0.5     # >= 50% PT pressure -> Path B
POOL_PRESSURE_HIGH = "HIGH"       # Pool pressure HIGH -> Path C
REST_RISK_THRESHOLD_B = 0.15      # >= 15% rest risk -> Path B


def select_path(features: FeatureVector) -> Tuple[PathSelection, str]:
    """
    Select solver path based on instance features.
    
    Decision tree:
    1. If pool_pressure == HIGH or n_blocks very large -> Path C
    2. If peakiness >= threshold or pt_pressure >= threshold -> Path B
    3. Otherwise -> Path A
    
    Args:
        features: Computed feature vector
    
    Returns:
        Tuple of (PathSelection, reason_code)
    """
    logger.info(f"Selecting path for: peakiness={features.peakiness_index:.2f}, "
                f"pool_pressure={features.pool_pressure}, "
                f"pt_pressure={features.pt_pressure_proxy:.2f}")
    
    # Rule 1: Pool too large -> Path C (heavy mode)
    if features.pool_pressure == POOL_PRESSURE_HIGH:
        logger.info(f"Selected Path C: {ReasonCode.POOL_TOO_LARGE}")
        return PathSelection.C, ReasonCode.POOL_TOO_LARGE
    
    # Rule 2: High peakiness -> Path B
    if features.peakiness_index >= PEAKINESS_THRESHOLD_B:
        logger.info(f"Selected Path B: {ReasonCode.PEAKY_HIGH}")
        return PathSelection.B, ReasonCode.PEAKY_HIGH
    
    # Rule 3: High PT pressure -> Path B
    if features.pt_pressure_proxy >= PT_PRESSURE_THRESHOLD_B:
        logger.info(f"Selected Path B: {ReasonCode.PEAKY_OR_PT_PRESSURE}")
        return PathSelection.B, ReasonCode.PEAKY_OR_PT_PRESSURE
    
    # Rule 4: High rest risk -> Path B (needs more careful scheduling)
    if features.rest_risk_proxy >= REST_RISK_THRESHOLD_B:
        logger.info(f"Selected Path B: {ReasonCode.REST_RISK_HIGH}")
        return PathSelection.B, ReasonCode.REST_RISK_HIGH
    
    # Default: Path A (fast mode)
    logger.info(f"Selected Path A: {ReasonCode.NORMAL_INSTANCE}")
    return PathSelection.A, ReasonCode.NORMAL_INSTANCE


# =============================================================================
# PARAMETER ADAPTATION RULES
# =============================================================================

def select_parameters(
    features: FeatureVector,
    path: PathSelection,
    reason_code: str,
    time_budget: float = 30.0,
) -> ParameterBundle:
    """
    Select solver parameters based on path and features.
    
    Each path has a default parameter set, adjusted by features.
    
    Args:
        features: Computed feature vector
        path: Selected solver path
        reason_code: Why this path was selected
        time_budget: Total time budget in seconds
    
    Returns:
        ParameterBundle with adapted parameters
    """
    logger.info(f"Selecting parameters for Path {path.value}, budget={time_budget}s")
    
    # Base parameters by path
    if path == PathSelection.A:
        params = _params_path_a(features, time_budget)
    elif path == PathSelection.B:
        params = _params_path_b(features, time_budget)
    else:  # Path C
        params = _params_path_c(features, time_budget)
    
    params.path = path
    params.reason_code = reason_code
    
    # Adjust epsilon based on time budget
    if time_budget <= 15.0:
        params.epsilon = 0.05  # 5% gap tolerance for fast runs
    elif time_budget >= 120.0:
        params.epsilon = 0.01  # 1% for long runs
    
    # Adjust daymin buffer based on instance size
    if features.n_tours > 500:
        params.daymin_buffer = 3  # Larger buffer for big instances
    elif features.n_tours < 200:
        params.daymin_buffer = 1  # Tighter for small instances
    
    logger.info(f"Parameters: lns_iters={params.lns_iterations}, "
                f"destroy={params.destroy_fraction:.2f}, "
                f"sp_enabled={params.sp_enabled}")
    
    return params


def _params_path_a(features: FeatureVector, time_budget: float) -> ParameterBundle:
    """
    Path A: Fast mode parameters.
    
    - Light LNS (fewer iterations, smaller destroy fraction)
    - Quick Phase 1
    - Aggressive early stopping
    """
    # Allocate time: 20% Phase 1, 70% LNS, 10% buffer
    phase1_time = time_budget * 0.2
    lns_time = time_budget * 0.7
    
    return ParameterBundle(
        path=PathSelection.A,
        reason_code="",
        
        # LNS: light settings
        lns_iterations=100,
        lns_time_limit_s=lns_time,
        destroy_fraction=0.10,  # Small neighborhood
        repair_time_limit_s=3.0,  # Fast repairs
        
        # PT handling
        pt_focused_destroy_weight=0.2,
        enable_pt_elimination=True,
        
        # No SP in Path A
        sp_enabled=False,
        
        # Phase 1
        phase1_time_limit_s=phase1_time,
        
        # Early stop: aggressive
        epsilon=0.02,
        stagnation_iters=15,
        repair_failure_threshold=0.25,
        
        # Heuristic: minimal
        heuristic_improvement_budget_s=min(10.0, time_budget * 0.15),
    )


def _params_path_b(features: FeatureVector, time_budget: float) -> ParameterBundle:
    """
    Path B: Balanced mode parameters.
    
    - Extended LNS (more iterations, larger neighborhoods)
    - PT-focused destroy for peak handling
    - Moderate Phase 1 time
    """
    # Allocate time: 25% Phase 1, 65% LNS, 10% buffer
    phase1_time = time_budget * 0.25
    lns_time = time_budget * 0.65
    
    # Adjust LNS iterations based on features
    lns_iters = 200
    if features.peakiness_index >= 0.5:
        lns_iters = 300  # More iterations for very peaky instances
    
    return ParameterBundle(
        path=PathSelection.B,
        reason_code="",
        
        # LNS: extended settings
        lns_iterations=lns_iters,
        lns_time_limit_s=lns_time,
        destroy_fraction=0.20,  # Larger neighborhood
        repair_time_limit_s=5.0,  # Standard repairs
        
        # PT handling: aggressive
        pt_focused_destroy_weight=0.5,  # Focus on PT elimination
        enable_pt_elimination=True,
        
        # No SP in Path B (could be fallback)
        sp_enabled=False,
        
        # Phase 1
        phase1_time_limit_s=phase1_time,
        
        # Early stop: moderate
        epsilon=0.02,
        stagnation_iters=25,
        repair_failure_threshold=0.30,
        
        # Heuristic: standard
        heuristic_improvement_budget_s=min(20.0, time_budget * 0.2),
    )


def _params_path_c(features: FeatureVector, time_budget: float) -> ParameterBundle:
    """
    Path C: Heavy mode parameters.
    
    - Set-Partitioning enabled
    - Conservative LNS as repair
    - Extended Phase 1
    """
    # Allocate time: 20% Phase 1, 50% SP, 20% LNS fallback, 10% buffer
    phase1_time = time_budget * 0.2
    sp_time = time_budget * 0.5
    lns_time = time_budget * 0.2
    
    # SP parameters based on pool size
    if features.pool_pressure == "HIGH":
        pool_cap = 3000  # Smaller pool to stay manageable
        gen_quota = 150
    else:
        pool_cap = 5000
        gen_quota = 200
    
    return ParameterBundle(
        path=PathSelection.C,
        reason_code="",
        
        # LNS: conservative (fallback only)
        lns_iterations=150,
        lns_time_limit_s=lns_time,
        destroy_fraction=0.15,
        repair_time_limit_s=4.0,
        
        # PT handling
        pt_focused_destroy_weight=0.4,
        enable_pt_elimination=True,
        
        # SP enabled
        sp_enabled=True,
        column_gen_quota=gen_quota,
        pool_cap=pool_cap,
        pricing_time_limit_s=min(15.0, sp_time / 3),
        sp_max_rounds=min(100, int(sp_time / 0.5)),  # ~0.5s per round
        
        # Phase 1
        phase1_time_limit_s=phase1_time,
        
        # Early stop: conservative (SP needs time)
        epsilon=0.015,  # 1.5% gap
        stagnation_iters=30,
        repair_failure_threshold=0.35,
        
        # Heuristic: minimal (SP is primary)
        heuristic_improvement_budget_s=min(15.0, time_budget * 0.1),
    )


# =============================================================================
# FALLBACK LOGIC
# =============================================================================

def get_fallback_path(current_path: PathSelection) -> Tuple[PathSelection, str]:
    """
    Get the next fallback path when current path fails or stagnates.
    
    Fallback order: A -> B -> C
    
    Returns:
        Tuple of (next_path, reason_code) or (None, reason) if no fallback
    """
    if current_path == PathSelection.A:
        return PathSelection.B, ReasonCode.FALLBACK_PATH_B
    elif current_path == PathSelection.B:
        return PathSelection.C, ReasonCode.FALLBACK_PATH_C
    else:
        # No fallback from C - it's the last resort
        return None, ReasonCode.PATH_B_FAILED


def should_fallback(
    iterations_without_improvement: int,
    repair_failure_rate: float,
    params: ParameterBundle,
) -> Tuple[bool, str]:
    """
    Determine if we should switch to fallback path.
    
    Args:
        iterations_without_improvement: Count of iterations with no score improvement
        repair_failure_rate: Ratio of failed repairs (0-1)
        params: Current parameter bundle
    
    Returns:
        Tuple of (should_fallback: bool, reason_code: str)
    """
    # Stagnation check
    if iterations_without_improvement >= params.stagnation_iters:
        return True, ReasonCode.STAGNATION
    
    # High repair failure rate
    if repair_failure_rate >= params.repair_failure_threshold:
        return True, ReasonCode.STAGNATION
    
    return False, ""


# =============================================================================
# EARLY STOP LOGIC
# =============================================================================

def should_early_stop(
    current_score: int,  # e.g., driver count
    lower_bound: int,
    daymin_achieved: bool,
    params: ParameterBundle,
) -> Tuple[bool, str]:
    """
    Determine if we should stop early.
    
    Args:
        current_score: Current solution score (lower is better)
        lower_bound: Known lower bound
        daymin_achieved: Whether we're at or near daymin
        params: Current parameter bundle
    
    Returns:
        Tuple of (should_stop: bool, reason_code: str)
    """
    # Check if within epsilon of lower bound
    if lower_bound > 0:
        gap = (current_score - lower_bound) / lower_bound
        if gap <= params.epsilon:
            return True, ReasonCode.GOOD_ENOUGH
    
    # Check if at/near daymin
    if daymin_achieved:
        return True, ReasonCode.NEAR_DAYMIN
    
    return False, ""


# =============================================================================
# POLICY ENGINE CLASS
# =============================================================================

class PolicyEngine:
    """
    Stateful policy engine for path and parameter selection.
    """
    
    def __init__(self):
        self.current_path: PathSelection = PathSelection.A
        self.current_params: ParameterBundle = None
        self.reason_codes: list[str] = []
        self.fallback_count: int = 0
    
    def select(
        self,
        features: FeatureVector,
        time_budget: float = 30.0,
    ) -> ParameterBundle:
        """
        Select path and parameters for the given features.
        """
        path, reason = select_path(features)
        params = select_parameters(features, path, reason, time_budget)
        
        self.current_path = path
        self.current_params = params
        self.reason_codes = [reason]
        self.fallback_count = 0
        
        return params
    
    def trigger_fallback(self, reason: str) -> ParameterBundle:
        """
        Trigger fallback to next path.
        
        Returns new parameters, or None if no fallback available.
        """
        next_path, fallback_reason = get_fallback_path(self.current_path)
        
        if next_path is None:
            self.reason_codes.append(reason)
            return None
        
        self.current_path = next_path
        self.reason_codes.append(reason)
        self.reason_codes.append(fallback_reason)
        self.fallback_count += 1
        
        # Get new parameters (use cached features if available)
        # For now, create default params for the new path
        self.current_params = ParameterBundle(
            path=next_path,
            reason_code=fallback_reason,
        )
        
        logger.info(f"Fallback triggered: {self.current_path.value} ({fallback_reason})")
        return self.current_params
    
    def get_summary(self) -> dict:
        """Get summary of policy decisions."""
        return {
            "final_path": self.current_path.value if self.current_path else None,
            "reason_codes": self.reason_codes,
            "fallback_count": self.fallback_count,
            "parameters": self.current_params.to_dict() if self.current_params else None,
        }
