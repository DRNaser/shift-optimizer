"""
Solvereign V2 - Roster Builder (SPPRC Pricer)

Generates columns with negative reduced cost using Label Setting algorithm.
Graph: DAG (Day 0 -> Day 1 -> ... -> Day N).
Nodes: Duties (generated lazily per iteration).

Migrated from:
- src/core_v2/pricing/spprc.py
- src/core_v2/pricing/label.py  
- src/core_v2/model/column.py
"""

import logging
import time
import bisect
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Any

from .types import TourV2, DutyV2, WeekCategory
from .validator import ValidatorV2
from .duty_builder import DutyBuilderTopK, DutyBuilderCaps

logger = logging.getLogger("RosterBuilder")


# =============================================================================
# COLUMN MODEL (Weekly Roster)
# =============================================================================

@dataclass(frozen=True)
class ColumnV2:
    """
    Weekly roster for one driver.
    Contains duties and utilization stats.
    """
    col_id: str
    duties: tuple[DutyV2, ...]
    covered_tour_ids: frozenset[str]
    
    total_work_min: int
    days_worked: int
    max_day_span_min: int
    
    origin: str
    hours: float
    is_under_30h: bool
    is_under_20h: bool
    is_singleton: bool
    
    @property
    def signature(self) -> str:
        """Canonical hash for pool deduplication."""
        tours_str = '|'.join(sorted(self.covered_tour_ids))
        return hashlib.sha256(tours_str.encode()).hexdigest()[:24]

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "col_id": self.col_id,
            "duty_ids": [d.duty_id for d in self.duties],
            "covered_tour_ids": sorted(list(self.covered_tour_ids)),
            "total_work_min": self.total_work_min,
            "days_worked": self.days_worked,
            "max_day_span_min": self.max_day_span_min,
            "origin": self.origin,
            "hours": self.hours,
            "signature": self.signature,
        }

    @classmethod
    def from_duties(
        cls,
        col_id: str,
        duties: list[DutyV2],
        origin: str,
    ) -> "ColumnV2":
        """Create a Column from a list of duties."""
        sorted_duties = sorted(duties, key=lambda d: d.day)
        
        all_tours = set()
        total_work = 0
        max_span = 0
        
        for d in sorted_duties:
            all_tours.update(d.tour_ids)
            total_work += d.work_min
            max_span = max(max_span, d.span_min)
        
        hours = total_work / 60.0
        
        return cls(
            col_id=col_id,
            duties=tuple(sorted_duties),
            covered_tour_ids=frozenset(all_tours),
            total_work_min=total_work,
            days_worked=len(sorted_duties),
            max_day_span_min=max_span,
            origin=origin,
            hours=hours,
            is_under_30h=(hours < 30.0),
            is_under_20h=(hours < 20.0),
            is_singleton=(len(sorted_duties) == 1),
        )

    def cost_stage1(self, week_category: WeekCategory) -> float:
        """Stage 1 Cost (CG / LP Relaxation). Always 1.0."""
        if self.origin and self.origin.startswith("artificial"):
            return 1_000_000.0
        return 1.0

    def cost_utilization(self, week_category: WeekCategory) -> float:
        """Stage 2 Cost (MIP / Penalties)."""
        cost = 1.0
        
        if self.is_singleton:
            cost += 0.2
        
        if week_category == WeekCategory.COMPRESSED:
            if self.hours < 30.0:
                cost += 0.5
            if self.hours < 20.0:
                cost += 1.0
            underutil = max(0.0, 33.0 - self.hours)
            cost += underutil * 0.1
        else:
            if self.hours < 35.0:
                cost += 0.5
            underutil = max(0.0, 38.0 - self.hours)
            cost += underutil * 0.1
        
        return cost


# =============================================================================
# LABEL (SPPRC State)
# =============================================================================

@dataclass(frozen=True)
class Label:
    """SPPRC Label state."""
    path: tuple[str, ...]
    last_duty: DutyV2
    total_work_min: int
    days_worked: int
    reduced_cost: float
    
    def dominates(self, other: "Label") -> bool:
        """Check if this label dominates other."""
        if self.last_duty is not other.last_duty:
            return False
        if self.reduced_cost > other.reduced_cost:
            return False
        if self.total_work_min < other.total_work_min:
            return False
        return True


# =============================================================================
# PRICING PROFILE (Stall-Aware Exploration)
# =============================================================================

@dataclass
class PricingProfile:
    """
    Configuration for pricing behavior.
    NORMAL: Standard search parameters
    STALL: Widened search when no progress
    NUCLEAR: Maximum exploration
    """
    name: str
    top_m_per_bucket: int           # Candidates retained per 30min bucket
    bucket_minutes: int             # Bucket size for diversification
    connector_window_minutes: int   # Connector window for consecutive days
    max_out_arcs: int               # Arc budget per duty
    dominance_mode: str             # "STRICT", "SOFT", "MINIMAL"


# Pre-defined profiles
PROFILE_NORMAL = PricingProfile(
    name="NORMAL",
    top_m_per_bucket=5,
    bucket_minutes=30,
    connector_window_minutes=480,
    max_out_arcs=50,
    dominance_mode="STRICT",
)

PROFILE_STALL = PricingProfile(
    name="STALL",
    top_m_per_bucket=20,           # 4× NORMAL
    bucket_minutes=30,
    connector_window_minutes=960,   # ±8h
    max_out_arcs=150,
    dominance_mode="SOFT",
)

PROFILE_NUCLEAR = PricingProfile(
    name="NUCLEAR",
    top_m_per_bucket=40,           # 2× STALL
    bucket_minutes=30,
    connector_window_minutes=1440,  # ±12h
    max_out_arcs=300,
    dominance_mode="MINIMAL",
)


@dataclass
class RCTelemetry:
    """Best reduced cost found with components."""
    best_rc_total: float = float('inf')
    best_rc_dual_sum: float = 0.0
    best_rc_base_cost: float = 1.0
    best_rc_penalties: float = 0.0
    best_rc_days: int = 0
    candidates_considered: int = 0
    arcs_generated: int = 0
    labels_expanded: int = 0
    new_cols_2d: int = 0
    new_cols_3d_plus: int = 0
    num_buckets: int = 0
    candidates_before_diversify: int = 0
    candidates_after_diversify: int = 0


# =============================================================================
# DAILY DUTY INDEX
# =============================================================================

class DailyDutyIndex:
    """Time-based index for efficient duty lookup by start time."""
    def __init__(self, duties: list[DutyV2]):
        self.duties_sorted = sorted(duties, key=lambda d: d.start_min)
        self.start_times = [d.start_min for d in self.duties_sorted]
    
    def get_candidates(self, min_start: int, max_start: int) -> list[DutyV2]:
        """Get duties with start_min in [min_start, max_start]."""
        left = bisect.bisect_left(self.start_times, min_start)
        right = bisect.bisect_right(self.start_times, max_start)
        return self.duties_sorted[left:right]


# =============================================================================
# SPPRC PRICER (ROSTER BUILDER)
# =============================================================================

class RosterBuilder:
    """
    SPPRC Pricing Engine.
    Generates valid schedules (paths) with negative reduced cost.
    
    Supports stall-aware exploration via PricingProfile.
    """
    
    def __init__(
        self, 
        duty_builder: DutyBuilderTopK,
        week_category: WeekCategory = WeekCategory.NORMAL,
        duty_caps: Optional[DutyBuilderCaps] = None
    ):
        self.duty_builder = duty_builder
        self.sorted_days = duty_builder.sorted_days
        self.week_category = week_category
        self.duty_caps = duty_caps or DutyBuilderCaps()
        
        # Base hyperparams
        self.max_labels_per_node = 10
        self.pruning_active = True
        self.pricing_time_limit = 15.0
        self.debug = True
        
        # Min rest (fixed, not profile-dependent)
        self.min_rest_minutes = 660
        
        # Active profile (can be switched)
        self.profile = PROFILE_NORMAL
        
        # Telemetry
        self.last_duty_counts: dict[int, int] = {}
        self.last_linker_metrics: dict[str, Any] = {}
        self.best_duties_by_day: dict[int, list[DutyV2]] = {}
        self.rc_telemetry = RCTelemetry()
    
    def set_profile(self, profile: PricingProfile) -> None:
        """Switch pricing profile for stall-aware exploration."""
        if profile.name != self.profile.name:
            logger.info(f"PROFILE_SWITCH: {self.profile.name} -> {profile.name}")
        self.profile = profile
    
    def _diversify_by_bucket(
        self, 
        duties: list[DutyV2], 
        duals: dict[str, float]
    ) -> list[DutyV2]:
        """
        Diversify candidates by 30min buckets.
        Prevents over-representation of any start-time region.
        """
        if not duties:
            return []
        
        bucket_min = self.profile.bucket_minutes
        top_m = self.profile.top_m_per_bucket
        
        # Assign scores and buckets
        buckets: dict[int, list[tuple[float, DutyV2]]] = {}
        for d in duties:
            if hasattr(d, '_dual_score'):
                score = d._dual_score
            else:
                score = sum(duals.get(tid, 0.0) for tid in d.tour_ids)
            
            bucket_id = d.start_min // bucket_min
            if bucket_id not in buckets:
                buckets[bucket_id] = []
            buckets[bucket_id].append((score, d))
        
        # Pick top_m from each bucket
        result = []
        for bucket_id in sorted(buckets.keys()):
            bucket_duties = buckets[bucket_id]
            bucket_duties.sort(key=lambda x: -x[0])  # Best score first
            result.extend([d for _, d in bucket_duties[:top_m]])
        
        # Safety Net: Strict cap on total candidates
        # Even if diversified, we cannot exceed out-arc budget without risking OOM/Hang
        if len(result) > self.profile.max_out_arcs:
            # Sort by dual score to keep best globally
            result.sort(key=lambda d: -getattr(d, '_dual_score', 0.0))
            result = result[:self.profile.max_out_arcs]
        
        # Telemetry
        self.rc_telemetry.num_buckets = len(buckets)
        self.rc_telemetry.candidates_before_diversify = len(duties)
        self.rc_telemetry.candidates_after_diversify = len(result)
        
        return result

    def price(
        self, 
        duals: dict[str, float],
        max_new_cols: int = 1500
    ) -> list[ColumnV2]:
        """Generate negative reduced cost columns using active profile."""
        start_time = time.time()
        
        # Reset RC telemetry
        self.rc_telemetry = RCTelemetry()
        
        if self.debug:
            logger.info(f"PRICE_START: profile={self.profile.name}, duals={len(duals)}, window={self.profile.connector_window_minutes}")
        
        # 1. Generate duties lazily
        duties_by_day: dict[int, list[DutyV2]] = {}
        self.last_duty_counts = {}
        self.duty_builder.reset_telemetry()
        
        for day in self.sorted_days:
            try:
                t0 = time.time()
                duties = self.duty_builder.get_day_duties(day, duals, self.duty_caps)
                duties_by_day[day] = duties
                self.last_duty_counts[day] = len(duties)
                if self.debug:
                    logger.info(f"DUTY_GEN: day={day}, count={len(duties)}, time={time.time()-t0:.2f}s")
            except RuntimeError as e:
                logger.error(f"Duty generation failed: {e}")
                raise
        
        total_duties = sum(len(d) for d in duties_by_day.values())
        if self.debug:
            logger.info(f"DUTY_GEN_DONE: total={total_duties}, elapsed={time.time()-start_time:.2f}s")
        
        # Pre-calculate duals and apply bucket diversification for Gap Days
        self.best_duties_by_day = {}
        
        # Optimization: Pre-calculate _dual_score for ALL duties once
        # This replaces millions of redundant sums in _diversify_by_bucket
        for day, day_list in duties_by_day.items():
            for d in day_list:
                object.__setattr__(d, '_dual_score', sum(duals.get(tid, 0.0) for tid in d.tour_ids))
            
            # Apply bucket diversification (profile-driven)
            diversified = self._diversify_by_bucket(day_list, duals)
            self.best_duties_by_day[day] = diversified
        
        # 2. Run label-setting SPPRC
        labels_by_day: dict[int, dict[str, list[Label]]] = {d: {} for d in self.sorted_days}
        
        duty_map: dict[str, DutyV2] = {}
        for dlist in duties_by_day.values():
            for d in dlist:
                duty_map[d.duty_id] = d
        
        # 2a. Generate "Start" labels
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

        # 2b. Propagate Forward
        day_indices: dict[int, DailyDutyIndex] = {}
        for day in self.sorted_days:
            if duties_by_day.get(day):
                day_indices[day] = DailyDutyIndex(duties_by_day[day])
        
        # Telemetry
        cross_day_arcs_total = 0
        multi_day_labels_created = 0
        linker_comparisons = 0
        candidates_per_duty = []
        
        for i, current_day in enumerate(self.sorted_days):
            elapsed = time.time() - start_time
            if elapsed > self.pricing_time_limit:
                if self.debug:
                    logger.info(f"PRICE_TIMEOUT: at day {current_day}, elapsed={elapsed:.2f}s")
                break
            
            if current_day not in labels_by_day:
                continue
            
            for duty_id, current_labels in labels_by_day[current_day].items():
                if not current_labels:
                    continue
                
                labels_to_extend = current_labels[:self.max_labels_per_node]
                
                # Optimization: All labels in labels_to_extend share the same last_duty
                if not labels_to_extend:
                    continue
                
                # Pre-calculate candidates ONCE per duty node
                prev_duty = labels_to_extend[0].last_duty
                
                for next_day_idx in range(i + 1, len(self.sorted_days)):
                    next_day = self.sorted_days[next_day_idx]
                    
                    if next_day not in day_indices:
                        continue
                    
                    days_diff = next_day - current_day
                    
                    if days_diff > 1:
                        # Gap Day - use pre-calculated Top-K
                        next_duty_candidates = self.best_duties_by_day.get(next_day, [])
                    else:
                        # Consecutive Day - use profile connector_window
                        min_start_rel = prev_duty.end_min + self.min_rest_minutes - 1440
                        search_start = max(0, min_start_rel)
                        search_end = search_start + self.profile.connector_window_minutes
                        next_duty_candidates = day_indices[next_day].get_candidates(search_start, search_end)
                        
                        # Apply bucket diversification + arc budget (uses pre-calculated _dual_score)
                        next_duty_candidates = self._diversify_by_bucket(next_duty_candidates, duals)
                        
                        # Strict budget cap (if diversify yielded too many)
                        if len(next_duty_candidates) > self.profile.max_out_arcs:
                            next_duty_candidates = next_duty_candidates[:self.profile.max_out_arcs]
                    
                    candidates_per_duty.append(len(next_duty_candidates))
                    
                    for lab in labels_to_extend[:20]:
                        # prev_duty is already known (lab.last_duty == prev_duty)
                        
                        candidates_per_duty.append(len(next_duty_candidates))
                        
                        for next_duty in next_duty_candidates:
                            linker_comparisons += 1
                            
                            if ValidatorV2.can_chain_days(prev_duty, next_duty):
                                cross_day_arcs_total += 1
                                
                                duty_rc_delta = self._calc_reduced_cost_duty(next_duty, duals)
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
                                
                                self._add_with_dominance(
                                    labels_by_day[next_day][next_duty.duty_id],
                                    new_lab
                                )
                                
                                if new_days >= 2:
                                    multi_day_labels_created += 1
        
        avg_candidates = sum(candidates_per_duty) / max(1, len(candidates_per_duty))
        
        self.last_linker_metrics = {
            "avg_candidates_per_duty": avg_candidates,
            "comparisons_total": linker_comparisons,
            "cross_day_arcs": cross_day_arcs_total,
            "multi_day_labels": multi_day_labels_created,
        }
        
        if self.debug:
            logger.info(f"CROSS_DAY_ARCS: total={cross_day_arcs_total}, multi_day_labels={multi_day_labels_created}")
        
        # 3. Collect Final Columns
        candidates = []
        for day in self.sorted_days:
            for d_id, labs in labels_by_day[day].items():
                for lab in labs:
                    final_rc = self._finalize_rc(lab, duty_map)
                    if final_rc < -1e-5:
                        candidates.append((final_rc, lab))
        
        # 4. Sort and Select Top-K
        candidates.sort(key=lambda x: x[0])
        selected_candidates = candidates[:max_new_cols]
        
        result_cols = []
        days_worked_hist = {}
        
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
            
            dw = col.days_worked
            days_worked_hist[dw] = days_worked_hist.get(dw, 0) + 1
        
        pricing_time = time.time() - start_time
        
        if self.debug and result_cols:
            multi_day_count = sum(c for dw, c in days_worked_hist.items() if dw >= 2)
            logger.info(f"PRICING_RESULT: total={len(result_cols)}, multi_day={multi_day_count}, days_hist={days_worked_hist}")
        
        logger.debug(f"Pricing completed in {pricing_time:.2f}s: {len(result_cols)} columns")
        
        return result_cols

    def _calc_reduced_cost_duty(self, duty: DutyV2, duals: dict) -> float:
        """RC contribution of a single duty."""
        dual_sum = sum(duals.get(tid, 0.0) for tid in duty.tour_ids)
        return -dual_sum

    def _finalize_rc(self, lab: Label, duty_map: dict) -> float:
        """Apply global costs to get final RC. Track best RC for telemetry."""
        EPS_FRAG = 0.05
        EPS_GAP = 0.02
        EPS_SPAN = 0.02
        
        penalty = 0.0
        duties = [duty_map[did] for did in lab.path]
        num_tours = sum(len(d.tour_ids) for d in duties)
        
        if lab.days_worked == 1:
            if num_tours == 1:
                penalty = 1.0  # 1er (High penalty)
            elif num_tours >= 3:
                penalty = 0.0  # 3er (Good)
            else:
                penalty = 0.1  # 2er
        else:
            # Multi-day: check for split shift
            has_split = False
            for d in duties:
                gap = getattr(d, 'max_gap_min', 0)
                if gap > 240:
                    has_split = True
                    break
                elif d.span_min > d.work_min + 240:
                    has_split = True
                    break
            
            penalty = 0.3 if has_split else 0.0
        
        # Gap & Span Penalties
        pen_gap_total = 0.0
        pen_span_total = 0.0
        
        for d in duties:
            gap = getattr(d, 'max_gap_min', 0)
            gap_excess = max(0, gap - 180)
            pen_gap_total += gap_excess / 60.0
            
            span_excess = max(0, d.span_min - 720)
            pen_span_total += span_excess / 60.0
        
        base_cost = 1.0
        penalties = (EPS_FRAG * penalty) + (EPS_GAP * pen_gap_total) + (EPS_SPAN * pen_span_total)
        real_cost = base_cost + penalties
        
        final_rc = real_cost + lab.reduced_cost
        
        # Track best RC (even if positive)
        if final_rc < self.rc_telemetry.best_rc_total:
            self.rc_telemetry.best_rc_total = final_rc
            self.rc_telemetry.best_rc_base_cost = base_cost
            self.rc_telemetry.best_rc_penalties = penalties
            self.rc_telemetry.best_rc_dual_sum = -lab.reduced_cost  # dual contribution
            self.rc_telemetry.best_rc_days = lab.days_worked
        
        return final_rc

    def _add_with_dominance(self, existing: list[Label], new_lab: Label):
        """Add new_lab keeping Pareto-optimal."""
        for ex in existing:
            if ex.dominates(new_lab):
                return
        
        existing[:] = [ex for ex in existing if not new_lab.dominates(ex)]
        existing.append(new_lab)
        
        if len(existing) > self.max_labels_per_node:
            existing.sort(key=lambda l: l.reduced_cost)
            del existing[self.max_labels_per_node:]

    def get_duty_telemetry(self) -> dict:
        """Get duty generation telemetry from last price() call."""
        return {
            "duty_counts_by_day": self.last_duty_counts,
            "factory_telemetry": self.duty_builder.get_telemetry_summary(),
            "linker_metrics": self.last_linker_metrics,
        }
