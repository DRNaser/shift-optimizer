"""
Solvereign V2 - Configuration

Hard-coded business rules and solver configuration.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class BusinessRules:
    """Hard business constraints for driver scheduling."""
    
    # Legal constraints
    MAX_WEEKLY_HOURS: float = 55.0
    MAX_DAILY_SPAN_HOURS: float = 16.5
    MIN_REST_HOURS: float = 11.0
    
    # Operational constraints
    MAX_TOURS_PER_DAY: int = 3
    MAX_DUTIES_PER_WEEK: int = 6
    
    # Break/Pause rules
    MIN_PAUSE_MINUTES: int = 30
    MAX_PAUSE_REGULAR_MINUTES: int = 90
    SPLIT_PAUSE_MIN_MINUTES: int = 240  # 4h
    SPLIT_PAUSE_MAX_MINUTES: int = 480  # 8h


@dataclass(frozen=True)
class SolverConfig:
    """Configuration for the column generation solver."""
    
    # Column Generation
    max_cg_iterations: int = 30
    lp_time_limit: float = 60.0
    pricing_time_limit: float = 60.0
    
    # MIP Solving
    restricted_mip_var_cap: int = 20_000
    restricted_mip_time_limit: float = 15.0
    restricted_mip_time_limit: float = 15.0
    final_mip_time_limit: float = 300.0
    
    # Emergency / Convergence Config
    driver_overage_penalty: float = 500.0
    pt_weight_base: float = 50.0
    pt_weight_max: float = 200.0
    
    # Duty Generation
    top_m_start_tours: int = 50
    max_succ_per_tour: int = 30
    max_triples_per_tour: int = 5
    
    # Seeding
    target_seed_columns: int = 3000


# Global instances
BUSINESS_RULES: Final[BusinessRules] = BusinessRules()
DEFAULT_SOLVER_CONFIG: Final[SolverConfig] = SolverConfig()
