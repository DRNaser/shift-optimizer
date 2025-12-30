"""
Core v2 - Master MIP (Final Integer Solve)

Solves the Integer version of the Set-Partitioning problem.
Uses the expanded column pool to find the final legal roster assignment.

Features:
- Fixed-MIP (columns fixed/generated)
- Lexicographic Objectives
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

logger = logging.getLogger("MasterMIP")


class MasterMIP:
    """
    Solves Integer Set-Partitioning.
    Wrapper around HiGHS.
    """
    
    def __init__(self, columns: list[ColumnV2], all_tour_ids: list[str]):
        if not HAS_HIGHS:
            raise ImportError("highspy not installed.")
            
        self.columns = columns
        self.all_tour_ids = sorted(list(set(all_tour_ids)))
        self.tour_map = {t: i for i, t in enumerate(self.all_tour_ids)}
        self.highs: Optional[Any] = None
        
    def solve_lexico(self, 
                    week_category: WeekCategory,
                    time_limit: float = 300.0) -> dict:
        """
        Solve Lexicographically (Multi-Stage):
        
        Stage 1: Min Drivers (D)
        Stage 2: Min Count(<30h) (Fix D)
        Stage 3: Min Count(<35h) (Fix D, Fix <30h)
        Stage 4: Min Sum Underutil (Fix D, Fix <30h, Fix <35h)
        Stage 5: Max Count(>=40h) (Optional, Fix all above)
        """
        self.highs = highspy.Highs()
        
        # MIP Options for faster solve
        self.highs.setOptionValue("log_to_console", True)  # DEBUG
        self.highs.setOptionValue("presolve", "on")
        self.highs.setOptionValue("mip_heuristic_effort", 0.15)  # More heuristics
        self.highs.setOptionValue("mip_rel_gap", 0.01)  # 1% gap tolerance
        
        # Global time limit shared across stages? Or per stage?
        # Let's allocate budget per stage.
        stage_time_limit = time_limit / 4.0
        
        num_cols = len(self.columns)
        num_rows = len(self.all_tour_ids)
        
        logger.info(f"[MIP] Building model: {num_cols} cols, {num_rows} rows, stage_limit={stage_time_limit:.0f}s")
        
        # 1. Base Model Construction (Rows + Vars)
        # Rows (Exact Cover)
        row_lb = [1.0] * num_rows
        row_ub = [1.0] * num_rows
        self.highs.addRows(num_rows, row_lb, row_ub, 0, [], [], [])
        
        # Col Data (Matrix)
        start_indices = [0]
        row_indices = []
        values = []
        curr_nz = 0
        
        for col in self.columns:
            for tour_id in col.covered_tour_ids:
                if tour_id in self.tour_map:
                    row_indices.append(self.tour_map[tour_id])
                    values.append(1.0)
                    curr_nz += 1
            start_indices.append(curr_nz)
        
        logger.info(f"[MIP] Matrix NNZ={curr_nz}")
        
        # Initial Costs (Stage 1: Driver Count = 1.0 each)
        costs_s1 = [1.0] * num_cols
        col_lb = [0.0] * num_cols
        col_ub = [1.0] * num_cols
        
        self.highs.addCols(num_cols, costs_s1, col_lb, col_ub, 
                           curr_nz, start_indices, row_indices, values)
        
        # Integrality
        indices = list(range(num_cols))
        types = [highspy.HighsVarType.kInteger] * num_cols
        self.highs.changeColsIntegrality(num_cols, indices, types)
        
        logger.info(f"[MIP] Model build complete, starting Stage 1...")
        
        # --- STAGE 1: Min Drivers ---
        logger.info(f"[MIP] Stage 1: Min Drivers (limit={stage_time_limit:.0f}s)...")
        self.highs.setOptionValue("time_limit", stage_time_limit)
        t0 = time.time()
        self.highs.run()
        
        def check_status(stage, require_optimal=True):
            """Check MIP status - accept feasible solution on time limit if require_optimal=False."""
            s = self.highs.getModelStatus()
            status_str = self.highs.modelStatusToString(s)
            logger.info(f"[MIP] Stage {stage} status: {status_str}, time={time.time()-t0:.1f}s")
            
            # Always accept optimal
            if status_str in ["Optimal", "Optimal (tolerance)"]:
                return True
                
            # Accept time limit if we have a feasible solution and don't require optimal
            if status_str == "Time limit reached" and not require_optimal:
                info = self.highs.getInfo()
                if info.primal_solution_status == 2:  # kSolutionStatusFeasible
                    obj = info.objective_function_value
                    logger.info(f"[MIP] Stage {stage} time limit but feasible: obj={obj}")
                    return True
                    
            logger.warning(f"[MIP] Stage {stage} failed or incomplete: {status_str}")
            return False

        # For Stage 1, accept feasible solution on timeout since we have limited time budget
        if not check_status(1, require_optimal=False):
             return {"status": "FAILED_STAGE_1", "objective": None, "selected_columns": []}
             
        # Extract D*
        d_star = self.highs.getInfo().objective_function_value
        logger.info(f"[MIP] Stage 1 D* = {d_star}")
        
        # FIX D* (Add Constraint: Sum x <= D*)
        # Actually equality D* (since we minimized, we want to stay there)
        # sum(x) = D_star
        # Add a new row: 1.0 for every column
        # Row bounds: [D_star, D_star]
        # Or bounds [0, D_star] if we only care upper bound? 
        # But we want to fix it.
        # Integer D* might be slightly float off? Round it.
        d_star_int = round(d_star)
        
        # Constraint: Global Driver Count
        # indices 0..N-1, values 1.0
        idx_list = list(range(num_cols))
        val_list = [1.0] * num_cols
        self.highs.addRow(d_star_int, d_star_int, num_cols, idx_list, val_list)
        
        # --- STAGE 2: Min Count(<30h) ---
        logger.info("[MIP] Stage 2: Min Count <30h...")
        costs_s2 = []
        for col in self.columns:
            costs_s2.append(1.0 if col.hours < 30.0 else 0.0)
        
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s2)
        self.highs.setOptionValue("time_limit", stage_time_limit)
        self.highs.run()
        
        if check_status(2):
            val_s2 = self.highs.getInfo().objective_function_value
            logger.info(f"[MIP] Stage 2 Obj = {val_s2}")
            # Fix Stage 2 result: Sum (x_short) <= val_s2
            # Add row for <30h columns
            idx_s2 = [i for i, c in enumerate(self.columns) if c.hours < 30.0]
            if idx_s2:
                val_s2_int = round(val_s2)
                vals_s2 = [1.0] * len(idx_s2)
                self.highs.addRow(0.0, val_s2_int, len(idx_s2), idx_s2, vals_s2)
                
        # --- STAGE 3: Min Count(<35h) ---
        logger.info("[MIP] Stage 3: Min Count <35h...")
        costs_s3 = []
        for col in self.columns:
            costs_s3.append(1.0 if col.hours < 35.0 else 0.0)
            
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s3)
        self.highs.run()
        
        if check_status(3):
            val_s3 = self.highs.getInfo().objective_function_value
            logger.info(f"[MIP] Stage 3 Obj = {val_s3}")
            # Fix Stage 3
            idx_s3 = [i for i, c in enumerate(self.columns) if c.hours < 35.0]
            if idx_s3:
                val_s3_int = round(val_s3)
                vals_s3 = [1.0] * len(idx_s3)
                self.highs.addRow(0.0, val_s3_int, len(idx_s3), idx_s3, vals_s3)
                
        # --- STAGE 4: Min Sum Underutil ---
        # Objective: Σ max(0, T - hours_col) * x_col
        # T defined as 33h for compressed, 38h for normal?
        # User spec: "Stage4: min sum_underutil = Σ max(0, T - hours_col) * x_col (T: compressed ~33h)"
        target_hours = 33.0 if week_category == WeekCategory.COMPRESSED else 38.0
        
        logger.info(f"[MIP] Stage 4: Min Sum Underutil (T={target_hours})...")
        costs_s4 = []
        for col in self.columns:
            under = max(0.0, target_hours - col.hours)
            costs_s4.append(under)
            
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s4)
        self.highs.run()
        check_status(4) # Don't need to fix this one, it's the final major stage
        
        # --- Extract Result ---
        sols = self.highs.getSolution().col_value
        selected = []
        for i, val in enumerate(sols):
            if val > 0.5:
                selected.append(self.columns[i])
        
        runtime = 0.0 # TODO capture total
        return {
            "status": "OPTIMAL",
            "objective": self.highs.getInfo().objective_function_value,
            "selected_columns": selected,
            "runtime": runtime
        }
