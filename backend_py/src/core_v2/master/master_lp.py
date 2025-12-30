"""
Core v2 - Master LP (Set Partitioning Relaxation)

Solves the Linear Programming relaxation of the Set-Partitioning problem.
Provides dual prices (π) for the pricing engine.

Solver: HiGHS (via highspy)
Constraint: Σ x_c = 1 for each tour t
Objective: Min Σ cost_c * x_c
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


class MasterLP:
    """
    Solves LP relaxation of Set-Partitioning.
    Wrapper around HiGHS.
    """
    
    def __init__(self, columns: list[ColumnV2], all_tour_ids: list[str]):
        if not HAS_HIGHS:
            # Strict mode: If we are here, caller expects v2 to work.
            # No silent failure allowed per User Request.
            raise ImportError(
                "highspy not installed. Core v2 requires HiGHS solver. "
                "Please run: pip install highspy"
            )
            
        self.columns = columns
        self.all_tour_ids = sorted(list(set(all_tour_ids)))
        self.tour_map = {t: i for i, t in enumerate(self.all_tour_ids)}
        
        self.highs: Optional[Any] = None
        self._built = False
        
    def build(self, week_category: WeekCategory = WeekCategory.NORMAL):
        """Build the LP model with artificial variables for feasibility."""
        self.highs = highspy.Highs()
        self.highs.setOptionValue("log_to_console", False)
        # self.highs.setOptionValue("presolve", "on") 
        
        num_cols = len(self.columns)
        num_rows = len(self.all_tour_ids)
        num_artificial = num_rows # One artificial var per tour (slack)
        
        # Arrays for CSC Matrix
        start_indices = [0]
        row_indices = []
        values = []
        
        valid_cost_list = []
        valid_lb = []
        valid_ub = []
        
        # 1. Real Columns
        curr_nz = 0
        for col in self.columns:
            valid_cost_list.append(self._compute_cost(col, week_category))
            valid_lb.append(0.0)
            valid_ub.append(highspy.kHighsInf) # Relaxation x >= 0 (implicitly x<=1 due to constraint)
            
            for tour_id in col.covered_tour_ids:
                if tour_id in self.tour_map:
                    row_indices.append(self.tour_map[tour_id])
                    values.append(1.0)
                    curr_nz += 1
            start_indices.append(curr_nz)
            
        # 2. Artificial Columns (Big-M)
        # One col per tour t: covers ONLY tour t, Cost = 1,000,000
        BIG_M = 1_000_000.0
        
        for i in range(num_artificial):
            valid_cost_list.append(BIG_M)
            valid_lb.append(0.0)
            valid_ub.append(highspy.kHighsInf)
            
            # Covers exactly row i
            row_indices.append(i)
            values.append(1.0)
            curr_nz += 1
            start_indices.append(curr_nz)
            
        total_cols = num_cols + num_artificial
            
        # 3. Add Empty Rows (Tours)
        # Sum x = 1 (Exact cover)
        row_lb = [1.0] * num_rows
        row_ub = [1.0] * num_rows
        self.highs.addRows(num_rows, row_lb, row_ub, 0, [], [], [])
        
        # 4. Add All Columns (Real + Artificial)
        self.highs.addCols(total_cols, valid_cost_list, valid_lb, valid_ub, 
                           curr_nz, start_indices, row_indices, values)
                           
        self._built = True

    def solve(self, time_limit: float = 30.0) -> dict:
        """Solve and return status + duals."""
        if not self._built:
            raise RuntimeError("Model not built. Call build() first.")
            
        self.highs.setOptionValue("time_limit", time_limit)
        
        t0 = time.time()
        self.highs.run()
        runtime = time.time() - t0
        
        status_enum = self.highs.getModelStatus()
        status_str = self.highs.modelStatusToString(status_enum)
        
        if status_str != "Optimal":
            return {
                "status": status_str,
                "objective": None,
                "duals": {},
                "runtime": runtime
            }
            
        # Extract solution
        info = self.highs.getInfo()
        solution = self.highs.getSolution()
        
        # Map Duals (row_dual) to tour_ids
        # solution.row_dual is a list of float
        duals_map = {
            self.all_tour_ids[i]: solution.row_dual[i] 
            for i in range(len(self.all_tour_ids))
        }
        
        # Extract primal values (to see which columns active)
        # solution.col_value
        
        return {
            "status": "OPTIMAL",
            "objective": info.objective_function_value,
            "duals": duals_map,
            "runtime": runtime,
            "primal_values": solution.col_value
        }

    def _compute_cost(self, col: ColumnV2, week_category: WeekCategory) -> float:
        """
        Compute cost for LP objective.
        
        Includes:
        - Base driver cost (1.0)
        - Utilization penalties (soft-coded hard) to guide pricing
        """
        # Base cost: 1 driver
        cost = 1.0
        
        # Utilization penalties
        # Note: These values must align with the "Price" signal we want
        # Ideally, <30h should be very expensive so Duals go up for those tours
        
        if week_category == WeekCategory.COMPRESSED:
            if col.hours < 30.0:
                cost += 0.5  # Significant penalty
            if col.hours < 20.0:
                cost += 1.0  # Huge penalty (prefer 2 drivers over 1 bad one? Maybe)
        else: # NORMAL
            if col.hours < 35.0:
                cost += 0.5
                
        if col.is_singleton:
            cost += 0.2  # Discourage singletons
            
        return cost
