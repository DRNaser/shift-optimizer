"""
Solvereign V2 - Master Solver (LP + MIP)

Solves the Set-Partitioning problem:
- LP: Relaxation for dual prices
- MIP: Final integer selection

Migrated from:
- src/core_v2/master/master_lp.py
- src/core_v2/master/master_mip.py
"""

import logging
import time
from typing import Optional, Any

try:
    import highspy
    HAS_HIGHS = True
except ImportError:
    HAS_HIGHS = False

from .types import WeekCategory
from .roster_builder import ColumnV2

logger = logging.getLogger("MasterSolver")

DEBUG_BUILD = False
BUILD_TIMEOUT_SEC = 120.0


def check_highs_available():
    """Check if HiGHS solver is available."""
    if not HAS_HIGHS:
        raise ImportError(
            "highspy not installed. Solvereign V2 requires HiGHS solver. "
            "Install via: pip install highspy"
        )


# =============================================================================
# MASTER LP (Set Partitioning Relaxation)
# =============================================================================

class MasterLP:
    """Solves LP relaxation of Set-Partitioning."""
    
    def __init__(self, columns: list[ColumnV2], all_tour_ids: list[str]):
        check_highs_available()
        
        self.columns = columns
        self.all_tour_ids = sorted(list(set(all_tour_ids)))
        self.tour_map = {t: i for i, t in enumerate(self.all_tour_ids)}
        
        self.highs: Optional[Any] = None
        self._built = False
        self._build_stats: dict = {}
        
    def build(self, week_category: WeekCategory = WeekCategory.NORMAL, debug: bool = DEBUG_BUILD):
        """Build the LP model with artificial variables."""
        build_start = time.time()
        
        num_cols = len(self.columns)
        num_rows = len(self.all_tour_ids)
        num_artificial = num_rows
        
        if debug:
            logger.info(f"LP_BUILD_START: cols={num_cols}, rows={num_rows}")
        
        self.highs = highspy.Highs()
        self.highs.setOptionValue("log_to_console", debug)
        self.highs.setOptionValue("presolve", "on")
        self.highs.setOptionValue("threads", 1)
        
        # CSC Matrix
        start_indices = [0]
        row_indices = []
        values = []
        
        valid_cost_list = []
        valid_lb = []
        valid_ub = []
        
        row_coverage = [0] * num_rows
        
        # Real Columns
        curr_nz = 0
        for col in self.columns:
            valid_cost_list.append(col.cost_stage1(week_category))
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
        
        # Artificial Columns (Big-M)
        BIG_M = 1_000_000.0
        for i in range(num_artificial):
            valid_cost_list.append(BIG_M)
            valid_lb.append(0.0)
            valid_ub.append(highspy.kHighsInf)
            row_indices.append(i)
            values.append(1.0)
            curr_nz += 1
            start_indices.append(curr_nz)
            row_coverage[i] += 1
            
        total_cols = num_cols + num_artificial
        
        self._build_stats = {
            "num_cols": num_cols,
            "num_rows": num_rows,
            "num_artificial": num_artificial,
            "nnz": curr_nz,
        }
        
        # Rows (Exact Cover)
        row_lb = [1.0] * num_rows
        row_ub = [1.0] * num_rows
        self.highs.addRows(num_rows, row_lb, row_ub, 0, [], [], [])
        
        # Add Columns
        self.highs.addCols(total_cols, valid_cost_list, valid_lb, valid_ub,
                          curr_nz, start_indices, row_indices, values)
                           
        self._built = True
        
        if debug:
            logger.info(f"LP_BUILD_COMPLETE: time={time.time()-build_start:.2f}s")

    def solve(self, time_limit: float = 30.0, debug: bool = DEBUG_BUILD) -> dict:
        """Solve and return status + duals."""
        if not self._built:
            raise RuntimeError("Model not built. Call build() first.")
        
        self.highs.setOptionValue("time_limit", time_limit)
        
        t0 = time.time()
        self.highs.run()
        runtime = time.time() - t0
        
        status_enum = self.highs.getModelStatus()
        status_str = self.highs.modelStatusToString(status_enum)
        
        if debug:
            logger.info(f"LP_SOLVE_DONE: status={status_str}, runtime={runtime:.2f}s")
        
        if status_str not in ["Optimal", "Time limit reached"]:
            return {
                "status": status_str,
                "objective": None,
                "duals": {},
                "runtime": runtime,
            }
        
        # Extract solution
        info = self.highs.getInfo()
        solution = self.highs.getSolution()
        
        obj_val = info.objective_function_value
        
        duals_map = {
            self.all_tour_ids[i]: solution.row_dual[i] 
            for i in range(len(self.all_tour_ids))
        }
        
        num_real = len(self.columns)
        artificial_used = sum(
            1 for i in range(num_real, len(solution.col_value))
            if solution.col_value[i] > 0.5
        )
        
        return {
            "status": status_str,
            "objective": obj_val,
            "duals": duals_map,
            "runtime": runtime,
            "artificial_used": artificial_used,
            "build_stats": self._build_stats,
        }


# =============================================================================
# MASTER MIP (Final Integer Solve)
# =============================================================================

class MasterMIP:
    """Solves Integer Set-Partitioning with lexicographic objectives."""
    
    def __init__(self, columns: list[ColumnV2], all_tour_ids: list[str]):
        check_highs_available()
        
        self.columns = columns
        self.all_tour_ids = sorted(list(set(all_tour_ids)))
        self.tour_map = {t: i for i, t in enumerate(self.all_tour_ids)}
        self.highs: Optional[Any] = None
    
    def solve_lexico(self, 
                    week_category: WeekCategory,
                    time_limit: float = 300.0) -> dict:
        """
        Solve Lexicographically:
        Stage 1: Min Drivers
        Stage 2: Min Count(<30h)
        Stage 3: Min Count(<35h)
        Stage 4: Min Sum Underutil
        """
        self.highs = highspy.Highs()
        self.highs.setOptionValue("log_to_console", False)
        self.highs.setOptionValue("presolve", "on")
        self.highs.setOptionValue("mip_heuristic_effort", 0.15)
        self.highs.setOptionValue("mip_rel_gap", 0.01)
        
        stage_time_limit = time_limit / 4.0
        
        num_cols = len(self.columns)
        num_rows = len(self.all_tour_ids)
        
        logger.info(f"[MIP] Building: {num_cols} cols, {num_rows} rows")
        
        # Rows (Exact Cover)
        row_lb = [1.0] * num_rows
        row_ub = [1.0] * num_rows
        self.highs.addRows(num_rows, row_lb, row_ub, 0, [], [], [])
        
        # CSC Matrix
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
        
        # Stage 1 Costs with fragmentation penalties
        EPS_FRAG = 0.05
        EPS_GAP = 0.02
        EPS_SPAN = 0.02
        
        costs_s1 = []
        for col in self.columns:
            base_cost = 1.0
            penalty = 0.0
            
            if col.is_singleton:
                penalty = 1.0
            elif col.days_worked == 1:
                num_tours = len(col.covered_tour_ids)
                penalty = 0.0 if num_tours >= 3 else 0.1
            else:
                # Multi-day: check for split
                has_split = any(
                    getattr(d, 'max_gap_min', 0) > 240 or d.span_min > d.work_min + 240
                    for d in col.duties
                )
                penalty = 0.3 if has_split else 0.0
            
            # Gap & Span penalties
            pen_gap = sum(max(0, getattr(d, 'max_gap_min', 0) - 180) / 60.0 for d in col.duties)
            pen_span = sum(max(0, d.span_min - 720) / 60.0 for d in col.duties)
            
            costs_s1.append(base_cost + EPS_FRAG * penalty + EPS_GAP * pen_gap + EPS_SPAN * pen_span)
        
        col_lb = [0.0] * num_cols
        col_ub = [1.0] * num_cols
        
        self.highs.addCols(num_cols, costs_s1, col_lb, col_ub,
                          curr_nz, start_indices, row_indices, values)
        
        # Integrality
        indices = list(range(num_cols))
        types = [highspy.HighsVarType.kInteger] * num_cols
        self.highs.changeColsIntegrality(num_cols, indices, types)
        
        # --- STAGE 1: Min Drivers ---
        logger.info(f"[MIP] Stage 1: Min Drivers...")
        self.highs.setOptionValue("time_limit", stage_time_limit)
        t0 = time.time()
        self.highs.run()
        
        status = self.highs.getModelStatus()
        status_str = self.highs.modelStatusToString(status)
        
        if status_str not in ["Optimal", "Optimal (tolerance)", "Time limit reached"]:
            logger.warning(f"[MIP] Stage 1 failed: {status_str}")
            return {"status": "FAILED_STAGE_1", "objective": None, "selected_columns": []}
        
        d_star = self.highs.getInfo().objective_function_value
        d_star_int = round(d_star)
        logger.info(f"[MIP] Stage 1 D* = {d_star_int}")
        
        # Fix D*
        self.highs.addRow(d_star_int, d_star_int, num_cols, list(range(num_cols)), [1.0] * num_cols)
        
        # --- STAGE 2: Min Count(<30h) ---
        logger.info("[MIP] Stage 2: Min Count <30h...")
        costs_s2 = [1.0 if col.hours < 30.0 else 0.0 for col in self.columns]
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s2)
        self.highs.run()
        
        # --- STAGE 3: Min Count(<35h) ---
        logger.info("[MIP] Stage 3: Min Count <35h...")
        costs_s3 = [1.0 if col.hours < 35.0 else 0.0 for col in self.columns]
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s3)
        self.highs.run()
        
        # --- STAGE 4: Min Underutil ---
        target_hours = 33.0 if week_category == WeekCategory.COMPRESSED else 38.0
        logger.info(f"[MIP] Stage 4: Min Underutil (T={target_hours})...")
        costs_s4 = [max(0.0, target_hours - col.hours) for col in self.columns]
        self.highs.changeColsCost(num_cols, list(range(num_cols)), costs_s4)
        self.highs.run()
        
        # Extract Result
        sols = self.highs.getSolution().col_value
        selected = [self.columns[i] for i, val in enumerate(sols) if val > 0.5]
        
        return {
            "status": "OPTIMAL",
            "objective": d_star_int,
            "selected_columns": selected,
            "runtime": time.time() - t0
        }
