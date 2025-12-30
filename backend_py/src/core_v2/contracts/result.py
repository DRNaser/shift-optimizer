"""
Core v2 Result Contract

Strict typed result for OptimizerCoreV2. No dict returns allowed.
"""

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class CoreV2Proof:
    """Proof of correctness for optimization run."""
    coverage_pct: float = 0.0           # % of tours covered (must be 100.0)
    artificial_used_lp: int = 0         # Artificial columns in LP relaxation
    artificial_used_final: int = 0      # Artificial columns in final MIP (must be 0)
    mip_gap: float = 0.0                # MIP optimality gap
    total_tours: int = 0
    covered_tours: int = 0


@dataclass
class CoreV2Result:
    """
    Strict result contract for Core v2 Optimizer.
    
    Status: SUCCESS | FAIL | UNKNOWN
    Error codes: ARTIFICIAL_USED, INFEASIBLE, TIMEOUT, etc.
    """
    status: str                                     # SUCCESS | FAIL | UNKNOWN
    run_id: str = ""
    error_code: str = ""                            # Empty on success
    error_message: str = ""                         # Human-readable error
    
    week_type: str = ""                             # NORMAL | COMPRESSED | SHORT
    active_days: int = 0
    
    solution: list = field(default_factory=list)    # list[DriverAssignment] (v1-compatible)
    kpis: dict = field(default_factory=dict)        # Standard KPIs
    proof: CoreV2Proof = field(default_factory=CoreV2Proof)
    
    artifacts_dir: str = ""                         # Path to run artifacts
    logs: list = field(default_factory=list)        # Execution logs
    
    # Debug-only: raw ColumnV2 objects (not for production use)
    _debug_columns: Optional[list] = None
    
    @property
    def num_drivers(self) -> int:
        """Number of drivers in solution."""
        return len(self.solution)
    
    @property
    def is_valid(self) -> bool:
        """Check if result passes all validation checks."""
        return (
            self.status == "SUCCESS" and
            self.proof.coverage_pct == 100.0 and
            self.proof.artificial_used_final == 0
        )
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON export."""
        return {
            "status": self.status,
            "run_id": self.run_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "week_type": self.week_type,
            "active_days": self.active_days,
            "num_drivers": self.num_drivers,
            "kpis": self.kpis,
            "proof": {
                "coverage_pct": self.proof.coverage_pct,
                "artificial_used_lp": self.proof.artificial_used_lp,
                "artificial_used_final": self.proof.artificial_used_final,
                "mip_gap": self.proof.mip_gap,
                "total_tours": self.proof.total_tours,
                "covered_tours": self.proof.covered_tours,
            },
            "artifacts_dir": self.artifacts_dir,
            "is_valid": self.is_valid,
        }
