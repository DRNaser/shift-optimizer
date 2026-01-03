"""
Solvereign V2 - Clean Optimizer Package

The new, refactored solver architecture.
"""

__version__ = "2.0.0"

from .types import Weekday, WeekCategory, TourV2, DutyV2, day_name, DAY_NAMES
from .validator import ValidatorV2, RULES
from .config import BusinessRules, SolverConfig, BUSINESS_RULES, DEFAULT_SOLVER_CONFIG
from .fleet_counter import calculate_fleet_peak, calculate_fleet_peak_from_tours
from .duty_builder import DutyBuilderTopK, DutyBuilderCaps
from .roster_builder import RosterBuilder, ColumnV2, Label
from .master_solver import MasterLP, MasterMIP
from .optimizer import Optimizer, OptimizationResult, OptimizationProof, ColumnPool, GreedySeeder

__all__ = [
    # Types
    "Weekday",
    "WeekCategory",
    "TourV2",
    "DutyV2",
    "ColumnV2",
    "Label",
    "day_name",
    "DAY_NAMES",
    # Validation
    "ValidatorV2",
    "RULES",
    # Config
    "BusinessRules",
    "SolverConfig",
    "BUSINESS_RULES",
    "DEFAULT_SOLVER_CONFIG",
    # Components
    "DutyBuilderTopK",
    "DutyBuilderCaps",
    "RosterBuilder",
    "MasterLP",
    "MasterMIP",
    # Optimizer
    "Optimizer",
    "OptimizationResult",
    "OptimizationProof",
    "ColumnPool",
    "GreedySeeder",
    # Fleet
    "calculate_fleet_peak",
    "calculate_fleet_peak_from_tours",
]
