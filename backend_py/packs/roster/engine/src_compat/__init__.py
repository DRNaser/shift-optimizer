"""
V3 Source Compatibility Layer
=============================

This module contains legacy src/ code inlined into v3 for compatibility.
These modules were migrated from backend_py/src/ when that package was deleted.

DEPRECATED: This compatibility layer will be removed when v3 is migrated to
            packs/roster/engine/ in PR-3.

Modules:
    - constraints: Hard constraint definitions (HARD_CONSTRAINTS dataclass)
    - models: Domain models (Tour, Block, Weekday)
    - assignment_constraints: Block assignment constraint checking
    - smart_block_builder: Tour → Block partitioning algorithm
    - block_heuristic_solver: Min-Cost Max-Flow block solver
    - forecast_solver_v4: Experimental V4 solver (R&D only)
"""

from packs.roster.engine.src_compat.constraints import HARD_CONSTRAINTS
from packs.roster.engine.src_compat.models import Tour, Block, Weekday, BlockType, PauseZone
from packs.roster.engine.src_compat.assignment_constraints import can_assign_block
from packs.roster.engine.src_compat.smart_block_builder import (
    build_weekly_blocks_smart,
    BlockGenOverrides,
)
from packs.roster.engine.src_compat.block_heuristic_solver import BlockHeuristicSolver

__all__ = [
    "HARD_CONSTRAINTS",
    "Tour",
    "Block",
    "Weekday",
    "BlockType",
    "PauseZone",
    "can_assign_block",
    "build_weekly_blocks_smart",
    "BlockGenOverrides",
    "BlockHeuristicSolver",
]
