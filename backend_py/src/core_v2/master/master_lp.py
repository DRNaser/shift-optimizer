"""
Core v2 - Master LP (Set Partitioning Relaxation)

Solves the Linear Programming relaxation of the Set-Partitioning problem.
Provides dual prices (π) for the pricing engine.

Solver: HiGHS (via highspy)
Constraint: Σ x_c = 1 for each tour t
Objective: Min Σ cost_c * x_c

Supports sparse build from pool adjacency for O(nz) instead of O(T*C).
"""

import logging
from typing import Optional, Any
import time

try:
    import highspy
    HAS_HIGHS = True
except ImportError:
    HAS_HIGHS = False

from ..model.column import ColumnV2
from ..model.weektype import WeekCategory

logger = logging.getLogger("MasterLP")

# Debug flag - set to True for debugging hang issues
DEBUG_BUILD = True
BUILD_TIMEOUT_SEC = 120.0


class MasterLP:
    """
    Solves LP relaxation of Set-Partitioning.
    Wrapper around HiGHS.
    """
    
    def __init__(self, columns: list[ColumnV2], all_tour_ids: list[str]):
        if not HAS_HIGHS:
            raise ImportError(
                "highspy not installed. Core v2 requires HiGHS solver. "
                "Please run: pip install highspy"
            )
            
        self.columns = columns
        self.all_tour_ids = sorted(list(set(all_tour_ids)))
        self.tour_map = {t: i for i, t in enumerate(self.all_tour_ids)}
        
        self.highs: Optional[Any] = None
        self._built = False
        self._build_stats: dict = {}
        
    def build(self, week_category: WeekCategory = WeekCategory.NORMAL, debug: bool = DEBUG_BUILD):
        """Build the LP model with artificial variables for feasibility."""
        build_start = time.time()
        
        num_cols = len(self.columns)
        num_rows = len(self.all_tour_ids)
        num_artificial = num_rows
        
        if debug:
            logger.info(f"LP_BUILD_START: cols={num_cols}, rows={num_rows}, artificial={num_artificial}")
        
        self.highs = highspy.Highs()
        
        # Debug options
        if debug:
            self.highs.setOptionValue("log_to_console", True)
            self.highs.setOptionValue("output_flag", True)
        else:
            self.highs.setOptionValue("log_to_console", False)
        
        self.highs.setOptionValue("presolve", "on")
        self.highs.setOptionValue("threads", 1)
        
        # Arrays for CSC Matrix
        start_indices = [0]
        row_indices = []
        values = []
        
        valid_cost_list = []
        valid_lb = []
        valid_ub = []
        
        # Track row coverage for validation
        row_coverage = [0] * num_rows
        
        # 1. Real Columns
        curr_nz = 0
        for col_idx, col in enumerate(self.columns):
            valid_cost_list.append(self._compute_cost(col, week_category))
            valid_lb.append(0.0)
            valid_ub.append(highspy.kHighsInf)
            
            for tour_id in col.covered_tour_ids:
                if tour_id in self.tour_map:
                    row_idx = self.tour_map[tour_id]
                    row_indices.append(row_idx)
                    values.append(1.0)
                    curr_nz += 1
                    row_coverage[row_idx] += 1
            start_indices.append(curr_nz)
            
            # Timeout check during build
            if col_idx % 1000 == 0 and debug:
                elapsed = time.time() - build_start
                if elapsed > BUILD_TIMEOUT_SEC:
                    logger.error(f"LP_BUILD_TIMEOUT: {elapsed:.1f}s at col {col_idx}/{num_cols}")
                    raise TimeoutError(f"LP build timeout at column {col_idx}")
            
        # 2. Artificial Columns (Big-M)
        BIG_M = 1_000_000.0
        
        for i in range(num_artificial):
            valid_cost_list.append(BIG_M)
            valid_lb.append(0.0)
            valid_ub.append(highspy.kHighsInf)
            row_indices.append(i)
            values.append(1.0)
            curr_nz += 1
            start_indices.append(curr_nz)
            row_coverage[i] += 1  # Artificial covers this row
            
        total_cols = num_cols + num_artificial
        
        # Compute stats
        avg_degree = curr_nz / max(1, num_rows)
        max_degree = max(row_coverage) if row_coverage else 0
        min_degree = min(row_coverage) if row_coverage else 0
        zero_coverage_rows = sum(1 for c in row_coverage if c == 0)
        
        self._build_stats = {
            "num_cols": num_cols,
            "num_rows": num_rows,
            "num_artificial": num_artificial,
            "total_cols": total_cols,
            "nnz": curr_nz,
            "avg_degree": avg_degree,
            "max_degree": max_degree,
            "min_degree": min_degree,
            "zero_coverage_rows": zero_coverage_rows,
        }
        
        if debug:
            logger.info(
                f"LP_BUILD_MATRIX_DONE: NNZ={curr_nz}, avg_degree={avg_degree:.1f}, "
                f"max_degree={max_degree}, min_degree={min_degree}, zero_rows={zero_coverage_rows}"
            )
        
        # Validation: every row must have at least 1 column (artificial ensures this)
        if zero_coverage_rows > 0:
            logger.error(f"LP_BUILD_ERROR: {zero_coverage_rows} rows have zero coverage!")
            
        # 3. Add Empty Rows (Tours) - Exact cover
        row_lb = [1.0] * num_rows
        row_ub = [1.0] * num_rows
        
        if debug:
            logger.info(f"LP_BUILD_ADDROWS_START: {num_rows} rows")
            
        t_rows = time.time()
        self.highs.addRows(num_rows, row_lb, row_ub, 0, [], [], [])
        
        if debug:
            logger.info(f"LP_BUILD_ADDROWS_DONE: {time.time() - t_rows:.2f}s")
        
        # 4. Add All Columns (Real + Artificial)
        if debug:
            logger.info(f"LP_BUILD_ADDCOLS_START: {total_cols} cols, {curr_nz} nonzeros")
            
        t_cols = time.time()
        self.highs.addCols(total_cols, valid_cost_list, valid_lb, valid_ub, 
                           curr_nz, start_indices, row_indices, values)
        
        if debug:
            logger.info(f"LP_BUILD_ADDCOLS_DONE: {time.time() - t_cols:.2f}s")
                           
        self._built = True
        
        build_time = time.time() - build_start
        if debug:
            logger.info(f"LP_BUILD_COMPLETE: total_time={build_time:.2f}s")

    def solve(self, time_limit: float = 30.0, debug: bool = DEBUG_BUILD) -> dict:
        """Solve and return status + duals."""
        if not self._built:
            raise RuntimeError("Model not built. Call build() first.")
        
        if debug:
            logger.info(f"LP_SOLVE_START: time_limit={time_limit}s, stats={self._build_stats}")
            
        self.highs.setOptionValue("time_limit", time_limit)
        
        t0 = time.time()
        self.highs.run()
        runtime = time.time() - t0
        
        status_enum = self.highs.getModelStatus()
        status_str = self.highs.modelStatusToString(status_enum)
        
        if debug:
            logger.info(f"LP_SOLVE_DONE: status={status_str}, runtime={runtime:.2f}s")
        
        hit_time_limit = status_str == "Time limit reached"
        if status_str != "Optimal":
            # If Time Limit reached but we have a solution, we can return it (marked as SUBOPTIMAL/TIMEOUT)
            is_feasible = hit_time_limit 
            
            if not is_feasible:
                # True failure
                return {
                    "status": status_str,
                    "objective": None,
                    "duals": {},
                    "runtime": runtime,
                    "build_stats": self._build_stats,
                    "hit_time_limit": hit_time_limit,
                    "duals_stale": True,
                }
            else:
                if debug:
                    logger.warning(f"LP_TIMEOUT: Using feasible solution from {status_str}")
            
        # Extract solution
        info = self.highs.getInfo()
        solution = self.highs.getSolution()
        
        obj_val = info.objective_function_value
        if debug:
            logger.info(f"LP_SOLVE_OPTIMAL: obj={obj_val:.4f}")
        
        # Map Duals (row_dual) to tour_ids
        duals_map = {
            self.all_tour_ids[i]: solution.row_dual[i] 
            for i in range(len(self.all_tour_ids))
        }
        
        # Count artificial usage (columns after real columns)
        num_real = len(self.columns)
        artificial_used = sum(
            1 for i in range(num_real, len(solution.col_value))
            if solution.col_value[i] > 0.5
        )
        
        if debug and artificial_used > 0:
            logger.warning(f"LP_ARTIFICIAL_USED: {artificial_used} artificial columns in solution")
        
        return {
            "status": status_str,
            "objective": obj_val,
            "duals": duals_map,
            "runtime": runtime,
            "primal_values": solution.col_value,
            "artificial_used": artificial_used,
            "build_stats": self._build_stats,
            "hit_time_limit": hit_time_limit,
            "duals_stale": hit_time_limit,
        }

    def _compute_cost(self, col: ColumnV2, week_category: WeekCategory) -> float:
        """Compute cost for LP objective (Strict Stage 1)."""
        return col.cost_stage1(week_category)
