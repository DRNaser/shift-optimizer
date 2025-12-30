"""
Core v2 - SPPRC Pricing Engine

Generates columns with negative reduced cost using Label Setting algorithm.
Graph: DAG (Day 0 -> Day 1 -> ... -> Day N).
Nodes: Duties (generated lazily per iteration).
"""

import logging
import time
from typing import Optional, Any

from ..model.duty import DutyV2
from ..model.column import ColumnV2
from ..model.weektype import WeekCategory
from ..validator.rules import ValidatorV2
from ..duty_factory import DutyFactoryTopK, DutyFactoryCaps
from .label import Label

logger = logging.getLogger("SPPRC")


class SPPRCPricer:
    """
    Shortest Path Resource Constrained algorithm.
    Finds valid schedules (paths) with negative reduced cost.
    
    Uses DutyFactoryTopK for lazy, dual-guided duty generation.
    """
    
    def __init__(
        self, 
        duty_factory: DutyFactoryTopK,
        week_category: WeekCategory = WeekCategory.NORMAL,
        duty_caps: Optional[DutyFactoryCaps] = None
    ):
        self.duty_factory = duty_factory
        self.sorted_days = duty_factory.sorted_days
        self.week_category = week_category
        self.duty_caps = duty_caps or DutyFactoryCaps()
        
        # Hyperparams
        self.max_labels_per_node = 20   # Keep top K labels per duty per step (reduced for speed)
        self.pruning_active = True
        self.pricing_time_limit = 3.0   # Seconds per pricing call
        self.debug = True  # Debug mode
        
        # Telemetry
        self.last_duty_counts: dict[int, int] = {}

    def price(
        self, 
        duals: dict[str, float],
        max_new_cols: int = 1500
    ) -> list[ColumnV2]:
        """
        Generate negative reduced cost columns.
        
        Args:
            duals: Map tour_id -> float (shadow price)
            max_new_cols: Limit specific number of columns to return
        """
        start_time = time.time()
        
        if self.debug:
            logger.info(f"PRICE_START: duals_count={len(duals)}, time_limit={self.pricing_time_limit}s")
        
        # 1. Generate duties lazily using current duals
        duties_by_day: dict[int, list[DutyV2]] = {}
        self.last_duty_counts = {}
        
        self.duty_factory.reset_telemetry()
        
        for day in self.sorted_days:
            try:
                t0 = time.time()
                duties = self.duty_factory.get_day_duties(day, duals, self.duty_caps)
                duties_by_day[day] = duties
                self.last_duty_counts[day] = len(duties)
                if self.debug:
                    logger.info(f"DUTY_GEN: day={day}, count={len(duties)}, time={time.time()-t0:.2f}s")
            except RuntimeError as e:
                # Cap exceeded - propagate failure
                logger.error(f"Duty generation failed: {e}")
                raise
        
        total_duties = sum(len(d) for d in duties_by_day.values())
        if self.debug:
            logger.info(f"DUTY_GEN_DONE: total={total_duties}, elapsed={time.time()-start_time:.2f}s")
        
        # 2. Run label-setting SPPRC
        # Labels bucketed by Day -> DutyID -> List[Label]
        labels_by_day: dict[int, dict[str, list[Label]]] = {
            d: {} for d in self.sorted_days
        }
        
        # Build duty lookup map
        duty_map: dict[str, DutyV2] = {}
        for dlist in duties_by_day.values():
            for d in dlist:
                duty_map[d.duty_id] = d
        
        # 2a. Generate "Start" labels (duties acting as start of roster)
        if self.debug:
            logger.info(f"LABEL_INIT_START: days={len(self.sorted_days)}")
        
        label_count = 0
        for day in self.sorted_days:
            for duty in duties_by_day.get(day, []):
                rc = self._calc_reduced_cost_duty(duty, duals)
                
                lab = Label(
                    path=(duty.duty_id,),
                    last_duty=duty,
                    total_work_min=duty.work_min,
                    days_worked=1,
                    reduced_cost=rc
                )
                if duty.duty_id not in labels_by_day[day]:
                    labels_by_day[day][duty.duty_id] = []
                labels_by_day[day][duty.duty_id].append(lab)
                label_count += 1
        
        if self.debug:
            logger.info(f"LABEL_INIT_DONE: labels={label_count}, elapsed={time.time()-start_time:.2f}s")

        # 2b. Propagate Forward (Dynamic Programming)
        if self.debug:
            logger.info(f"LABEL_PROPAGATE_START: days={len(self.sorted_days)}")
        
        extensions_done = 0
        for i, current_day in enumerate(self.sorted_days):
            day_start = time.time()
            
            # Time check at day level
            elapsed = time.time() - start_time
            if elapsed > self.pricing_time_limit:
                if self.debug:
                    logger.info(f"PRICE_TIMEOUT: at day {current_day}, elapsed={elapsed:.2f}s")
                break
            
            if current_day not in labels_by_day: 
                continue
            
            day_extensions = 0
            for duty_id, current_labels in labels_by_day[current_day].items():
                if not current_labels:
                    continue
                
                # Limit labels to process per duty (avoid explosion)
                labels_to_extend = current_labels[:self.max_labels_per_node]
                
                # Try to extend to future days
                for next_day_idx in range(i + 1, len(self.sorted_days)):
                    next_day = self.sorted_days[next_day_idx]
                    next_duties = duties_by_day.get(next_day, [])
                    
                    # Limit next duties to check (avoid O(N²) explosion)
                    for next_duty in next_duties[:100]:
                        # Check connectivity
                        prev_duty = labels_to_extend[0].last_duty
                        
                        if ValidatorV2.can_chain_days(prev_duty, next_duty):
                            # Extension valid. Extend labels.
                            duty_rc_delta = self._calc_reduced_cost_duty(next_duty, duals)
                            
                            for lab in labels_to_extend[:10]:  # Further limit
                                new_rc = lab.reduced_cost + duty_rc_delta
                                new_work = lab.total_work_min + next_duty.work_min
                                new_days = lab.days_worked + 1
                                
                                new_lab = Label(
                                    path=lab.path + (next_duty.duty_id,),
                                    last_duty=next_duty,
                                    total_work_min=new_work,
                                    days_worked=new_days,
                                    reduced_cost=new_rc
                                )
                                
                                if next_duty.duty_id not in labels_by_day[next_day]:
                                    labels_by_day[next_day][next_duty.duty_id] = []
                                
                                # Add and Prune immediately to keep list small
                                self._add_with_dominance(
                                    labels_by_day[next_day][next_duty.duty_id],
                                    new_lab
                                )

        # 3. Collect Final Columns
        candidates = []
        for day in self.sorted_days:
            for d_id, labs in labels_by_day[day].items():
                for lab in labs:
                    # Finalize Cost (Apply Global Penalties)
                    final_rc = self._finalize_rc(lab)
                    
                    if final_rc < -1e-5:  # Negative Reduced Cost
                        candidates.append((final_rc, lab))
        
        # 4. Sort and Select Top-K
        candidates.sort(key=lambda x: x[0])  # Lowest RC first
        selected_candidates = candidates[:max_new_cols]
        
        # Convert to Columns
        result_cols = []
        for rc, lab in selected_candidates:
            duties = [duty_map[did] for did in lab.path if did in duty_map]
            if not duties:
                continue
            col = ColumnV2.from_duties(
                col_id=f"prc_{lab.path[0]}_{lab.path[-1]}",
                duties=duties,
                origin="pricing"
            )
            result_cols.append(col)
        
        pricing_time = time.time() - start_time
        logger.debug(f"Pricing completed in {pricing_time:.2f}s: {len(result_cols)} columns")
            
        return result_cols

    def _calc_reduced_cost_duty(self, duty: DutyV2, duals: dict) -> float:
        """
        RC contribution of a single duty.
        Delta = BaseCost(Duty) - Sum(Duals)
        """
        dual_sum = sum(duals.get(tid, 0.0) for tid in duty.tour_ids)
        return -dual_sum

    def _finalize_rc(self, lab: Label) -> float:
        """
        Apply global costs (Base + Penalties) to get final RC.
        STRICT STAGE 1: c(col) = 1.0.
        RC = 1.0 - Sum(Duals)
        """
        # 1. Base Driver Cost = 1.0 (Strict "Minimize Drivers")
        cost = 1.0
        
        # 2. NO Utilization Penalties in Stage 1 Pricing!
        # Penalties belong in Stage 2 (MIP) only.
            
        # 3. Accumulated RC from duties (which was just -Duals)
        return cost + lab.reduced_cost

    def _add_with_dominance(self, existing: list[Label], new_lab: Label):
        """Add new_lab to existing list, keeping it Pareto-optimal."""
        # Check if dominated by any existing
        for ex in existing:
            if ex.dominates(new_lab):
                return  # Reject
        
        # Remove any existing dominated by new
        existing[:] = [ex for ex in existing if not new_lab.dominates(ex)]
        
        existing.append(new_lab)
        
        # Safety Cap
        if len(existing) > self.max_labels_per_node:
            existing.sort(key=lambda l: l.reduced_cost)
            del existing[self.max_labels_per_node:]
    
    def get_duty_telemetry(self) -> dict:
        """Get duty generation telemetry from last price() call."""
        return {
            "duty_counts_by_day": self.last_duty_counts,
            "factory_telemetry": self.duty_factory.get_telemetry_summary(),
        }

