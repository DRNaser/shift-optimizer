"""
Solvereign V2 - Duty Builder

Lazy duty generation with Top-K dual-guided selection.
Migrated from src/core_v2/duty_factory.py with cleaned imports.
"""

import logging
import bisect
from typing import Optional
from dataclasses import dataclass, field

from .types import TourV2, DutyV2
from .validator import ValidatorV2

logger = logging.getLogger("DutyBuilder")


@dataclass
class DutyBuilderCaps:
    """Caps for lazy duty generation. Hard limits - exceed = FAIL.
    
    PERFORMANCE-TUNED: These values are optimized to prevent
    duty explosion on large instances (1000+ tours).
    """
    max_multi_duties_per_day: int = 3_000   # Was 50k - causes 35k duties!
    top_m_start_tours: int = 30              # Was 200 - too many combinations
    max_succ_per_tour: int = 10              # Was 20 - reduce fan-out
    max_triples_per_tour: int = 3            # Was 5 - triples are expensive
    min_gap_minutes: int = 0
    max_gap_minutes: int = 180


@dataclass
class DutyBuilderTelemetry:
    """Telemetry for one get_day_duties call."""
    day: int
    tours_count: int
    singletons_count: int
    pairs_count: int
    triples_count: int
    multi_total: int
    cap_hit: bool = False
    top_dual_tours: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "tours": self.tours_count,
            "singletons": self.singletons_count,
            "pairs": self.pairs_count,
            "triples": self.triples_count,
            "multi_total": self.multi_total,
            "cap_hit": self.cap_hit,
            "top_dual_tours": self.top_dual_tours[:5],
        }


class DutyBuilderTopK:
    """
    Lazy duty factory with dual-guided Top-K selection.
    
    Uses O(n log n) time-windowed successor search instead of O(n²) scans.
    """
    
    def __init__(self, tours_by_day: dict[int, list[TourV2]], validator=ValidatorV2):
        """
        Args:
            tours_by_day: Dict[day_index, list[TourV2]]
            validator: Validator class
        """
        self.tours_by_day = tours_by_day
        self.validator = validator
        self.sorted_days = sorted(tours_by_day.keys())
        
        # Pre-sort tours by start_min for each day
        self._sorted_tours: dict[int, list[TourV2]] = {}
        self._start_times: dict[int, list[int]] = {}
        
        for day, tours in tours_by_day.items():
            sorted_tours = sorted(tours, key=lambda t: (t.start_min, t.tour_id))
            self._sorted_tours[day] = sorted_tours
            self._start_times[day] = [t.start_min for t in sorted_tours]
        
        self.telemetry: list[DutyBuilderTelemetry] = []
    
    def get_day_duties(
        self, 
        day: int, 
        duals: dict[str, float],
        caps: Optional[DutyBuilderCaps] = None
    ) -> list[DutyV2]:
        """Generate duties for a day, guided by dual prices."""
        if caps is None:
            caps = DutyBuilderCaps()
            
        if day not in self._sorted_tours:
            return []
            
        day_tours = self._sorted_tours[day]
        start_times = self._start_times[day]
        
        # 1. ALWAYS: All singletons (no cap)
        singletons = self._generate_singletons(day_tours)
        
        # 2. TOP-K: Multi-duties by dual gain
        pairs, triples = self._generate_multi_duties(
            day, day_tours, start_times, duals, caps
        )
        
        multi_total = len(pairs) + len(triples)
        
        # Record telemetry
        top_duals = sorted(
            [(t.tour_id, duals.get(t.tour_id, 0.0)) for t in day_tours],
            key=lambda x: -x[1]
        )[:5]
        
        telem = DutyBuilderTelemetry(
            day=day,
            tours_count=len(day_tours),
            singletons_count=len(singletons),
            pairs_count=len(pairs),
            triples_count=len(triples),
            multi_total=multi_total,
            cap_hit=multi_total >= caps.max_multi_duties_per_day,
            top_dual_tours=[tid for tid, _ in top_duals],
        )
        self.telemetry.append(telem)
        
        # 3. Smart pruning if cap exceeded
        if multi_total > caps.max_multi_duties_per_day:
            logger.warning(
                f"DUTY_CAP_HIT: Day {day} produced {multi_total} multi-duties "
                f"(cap={caps.max_multi_duties_per_day}). Applying smart pruning..."
            )
            
            all_multi = pairs + triples
            
            # Priority 1: Bottleneck Coverage
            dual_values = sorted([duals.get(tid, 0.0) for tid in duals.keys()], reverse=True)
            bottleneck_threshold = dual_values[max(0, int(len(dual_values) * 0.1))] if dual_values else 0.0
            bottleneck_tour_ids = set(tid for tid, val in duals.items() if val >= bottleneck_threshold)
            
            kept_bottleneck = [
                d for d in all_multi
                if any(tid in bottleneck_tour_ids for tid in d.tour_ids)
            ]
            
            logger.info(f"DUTY_PRUNE: Kept {len(kept_bottleneck)} bottleneck-covering duties")
            
            #Priority 2: Connectivity Score
            remaining = [d for d in all_multi if d not in kept_bottleneck]
            
            next_day_idx = min(self.sorted_days.index(day) + 1, len(self.sorted_days) - 1) if day in self.sorted_days else None
            if next_day_idx is not None and next_day_idx < len(self.sorted_days):
                next_day_candidates = self.sorted_days[next_day_idx]
                if next_day_candidates in self.tours_by_day:
                    next_day_tours = self.tours_by_day[next_day_candidates]
                    next_day_starts_sorted = sorted([t.start_min for t in next_day_tours])
                    
                    for d in remaining:
                        days_gap = next_day_candidates - day
                        min_start = d.end_min + 660 - (days_gap * 1440)
                        search_start = max(0, min_start)
                        search_end = search_start + 720
                        conn_score = self._count_window(next_day_starts_sorted, search_start, search_end)
                        d._conn_score = conn_score
            else:
                for d in remaining:
                    d._conn_score = 1440 - d.end_min
            
            remaining.sort(key=lambda d: -getattr(d, '_conn_score', 0))
            kept_connectivity = remaining[:max(1, int(len(remaining) * 0.3))]
            
            logger.info(f"DUTY_PRUNE: Kept {len(kept_connectivity)} high-connectivity duties")
            
            # Priority 3: Fill remainder by dual gain
            remaining = [d for d in all_multi if d not in kept_bottleneck and d not in kept_connectivity]
            remaining.sort(key=lambda d: -sum(duals.get(tid, 0.0) for tid in d.tour_ids))
           
            budget = caps.max_multi_duties_per_day - len(kept_bottleneck) - len(kept_connectivity)
            kept_dual = remaining[:max(0, budget)]
            
            logger.info(f"DUTY_PRUNE: Kept {len(kept_dual)} high-dual duties")
            
            pairs_triples_final = kept_bottleneck + kept_connectivity + kept_dual
            pairs = [d for d in pairs_triples_final if len(d.tour_ids) == 2]
            triples = [d for d in pairs_triples_final if len(d.tour_ids) == 3]
        
        # 4. Combine and sort deterministically
        all_duties = singletons + pairs + triples
        
        def duty_sort_key(d: DutyV2) -> tuple:
            gain = sum(duals.get(tid, 0.0) for tid in d.tour_ids)
            return (-gain, d.signature)
        
        all_duties.sort(key=duty_sort_key)
        
        logger.debug(
            f"Day {day}: {len(singletons)} singletons + "
            f"{len(pairs)} pairs + {len(triples)} triples = {len(all_duties)} duties"
        )
        
        return all_duties
    
    def _generate_singletons(self, day_tours: list[TourV2]) -> list[DutyV2]:
        """Generate ALL 1-tour duties (no cap)."""
        duties = []
        for t in day_tours:
            d = DutyV2.from_tours(duty_id="temp", tours=[t])
            object.__setattr__(d, 'duty_id', f"S_{d.signature[:12]}")
            duties.append(d)
        return duties
    
    def _generate_multi_duties(
        self,
        day: int,
        day_tours: list[TourV2],
        start_times: list[int],
        duals: dict[str, float],
        caps: DutyBuilderCaps
    ) -> tuple[list[DutyV2], list[DutyV2]]:
        """Generate Top-K 2er/3er duties."""
        pairs: list[DutyV2] = []
        triples: list[DutyV2] = []
        
        n = len(day_tours)
        if n < 2:
            return pairs, triples
        
        # Score tours for start selection
        tour_scores = [
            (i, t, duals.get(t.tour_id, 0.0)) 
            for i, t in enumerate(day_tours)
        ]
        tour_scores.sort(key=lambda x: (-x[2], x[1].start_min, x[1].tour_id))
        
        start_candidates = tour_scores[:caps.top_m_start_tours]
        
        seen_pairs: set[str] = set()
        seen_triples: set[str] = set()
        
        for idx1, t1, dual1 in start_candidates:
            window_start = t1.end_min + caps.min_gap_minutes
            window_end = t1.end_min + caps.max_gap_minutes
            
            left = bisect.bisect_left(start_times, window_start)
            right = bisect.bisect_right(start_times, window_end)
            
            successor_candidates = []
            for j in range(left, min(right, n)):
                t2 = day_tours[j]
                if t2.tour_id == t1.tour_id:
                    continue
                if not self.validator.can_chain_intraday(t1, t2):
                    continue
                dual2 = duals.get(t2.tour_id, 0.0)
                successor_candidates.append((j, t2, dual2))
            
            successor_candidates.sort(key=lambda x: (-x[2], x[1].start_min, x[1].tour_id))
            top_successors = successor_candidates[:caps.max_succ_per_tour]
            
            for idx2, t2, dual2 in top_successors:
                pair_duty = self._try_create_duty([t1, t2])
                if pair_duty and pair_duty.signature not in seen_pairs:
                    seen_pairs.add(pair_duty.signature)
                    pairs.append(pair_duty)
                    
                    if len(pairs) + len(triples) >= caps.max_multi_duties_per_day:
                        return pairs, triples
                    
                    # Try triples
                    triple_count = 0
                    window_start_3 = t2.end_min + caps.min_gap_minutes
                    window_end_3 = t2.end_min + caps.max_gap_minutes
                    
                    left_3 = bisect.bisect_left(start_times, window_start_3)
                    right_3 = bisect.bisect_right(start_times, window_end_3)
                    
                    t3_candidates = []
                    for k in range(left_3, min(right_3, n)):
                        t3 = day_tours[k]
                        if t3.tour_id in (t1.tour_id, t2.tour_id):
                            continue
                        if not self.validator.can_chain_intraday(t2, t3):
                            continue
                        dual3 = duals.get(t3.tour_id, 0.0)
                        t3_candidates.append((k, t3, dual3))
                    
                    t3_candidates.sort(key=lambda x: (-x[2], x[1].start_min, x[1].tour_id))
                    
                    for _, t3, _ in t3_candidates[:caps.max_triples_per_tour]:
                        if triple_count >= caps.max_triples_per_tour:
                            break
                        
                        triple_duty = self._try_create_duty([t1, t2, t3])
                        if triple_duty and triple_duty.signature not in seen_triples:
                            seen_triples.add(triple_duty.signature)
                            triples.append(triple_duty)
                            triple_count += 1
                            
                            if len(pairs) + len(triples) >= caps.max_multi_duties_per_day:
                                return pairs, triples
        
        return pairs, triples
    
    def _try_create_duty(self, tours: list[TourV2]) -> Optional[DutyV2]:
        """Create and validate a duty."""
        try:
            duty = DutyV2.from_tours(duty_id="temp", tours=tours)
            is_valid, _ = self.validator.validate_duty(duty)
            if not is_valid:
                return None
            prefix = "P" if len(tours) == 2 else "T"
            object.__setattr__(duty, 'duty_id', f"{prefix}_{duty.signature[:12]}")
            return duty
        except Exception:
            return None
    
    def _count_window(self, sorted_start_times: list[int], min_start: int, max_start: int) -> int:
        """Count elements in window using bisect."""
        left = bisect.bisect_left(sorted_start_times, min_start)
        right = bisect.bisect_right(sorted_start_times, max_start)
        return right - left
    
    def get_telemetry_summary(self) -> dict:
        """Get aggregated telemetry."""
        if not self.telemetry:
            return {}
        
        by_day = {t.day: t.to_dict() for t in self.telemetry}
        total_singletons = sum(t.singletons_count for t in self.telemetry)
        total_multi = sum(t.multi_total for t in self.telemetry)
        
        return {
            "by_day": by_day,
            "total_singletons": total_singletons,
            "total_multi": total_multi,
            "total_duties": total_singletons + total_multi,
            "any_cap_hit": any(t.cap_hit for t in self.telemetry),
        }
    
    def reset_telemetry(self):
        """Clear telemetry for new iteration."""
        self.telemetry.clear()
