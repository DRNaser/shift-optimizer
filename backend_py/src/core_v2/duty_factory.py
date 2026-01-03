"""
Core v2 - Duty Factory (Lazy Top-K Generation)

Replaces the naive O(n²)/O(n³) DutyBuilder with O(n log n) time-windowed
successor search + dual-guided Top-K selection.

Design:
1. Singletons: ALWAYS all 1-tour duties (no cap) for guaranteed coverage
2. Multi-duties: Top-K 2er/3er by dual gain, using time-windowed search
3. Hard fail if caps exceeded
"""

import logging
import bisect
from typing import Optional
from dataclasses import dataclass, field

from .model.tour import TourV2
from .model.duty import DutyV2
from .validator.rules import ValidatorV2

logger = logging.getLogger("DutyFactory")


@dataclass
class DutyFactoryCaps:
    """Caps for lazy duty generation. Hard limits - exceed = FAIL."""
    max_multi_duties_per_day: int = 50_000
    top_m_start_tours: int = 200
    max_succ_per_tour: int = 20
    max_triples_per_tour: int = 20  # MANUAL REPLICATION: 5→20 (Manual: 22% of all duties!)
    min_gap_minutes: int = 120      # MANUAL REPLICATION: 0→120min (2h min)
    max_gap_minutes: int = 480      # MANUAL REPLICATION: 180→480min (8h max, Manual avg: 6h!)


@dataclass
class DutyFactoryTelemetry:
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
            "top_dual_tours": self.top_dual_tours[:5],  # Top 5 only
        }


class DutyFactoryTopK:
    """
    Lazy duty factory with dual-guided Top-K selection.
    
    Uses O(n log n) time-windowed successor search instead of O(n²) scans.
    """
    
    def __init__(self, tours_by_day: dict[int, list[TourV2]], validator=ValidatorV2):
        """
        Args:
            tours_by_day: Dict[day_index, list[TourV2]]
            validator: Validator class with can_chain_intraday()
        """
        self.tours_by_day = tours_by_day
        self.validator = validator
        self.sorted_days = sorted(tours_by_day.keys())
        
        # Pre-sort tours by start_min for each day (O(n log n) once)
        self._sorted_tours: dict[int, list[TourV2]] = {}
        self._start_times: dict[int, list[int]] = {}  # For bisect lookup
        
        for day, tours in tours_by_day.items():
            sorted_tours = sorted(tours, key=lambda t: (t.start_min, t.tour_id))
            self._sorted_tours[day] = sorted_tours
            self._start_times[day] = [t.start_min for t in sorted_tours]
        
        # Telemetry accumulator
        self.telemetry: list[DutyFactoryTelemetry] = []
    
    def get_day_duties(
        self, 
        day: int, 
        duals: dict[str, float],
        caps: Optional[DutyFactoryCaps] = None
    ) -> list[DutyV2]:
        """
        Generate duties for a day, guided by dual prices.
        
        Args:
            day: Day index (0-6)
            duals: tour_id -> dual price (π)
            caps: Generation caps (uses defaults if None)
            
        Returns:
            Deterministically sorted list of DutyV2
            
        Raises:
            RuntimeError: If caps exceeded (FAIL_FAST_DUTY_CAP)
        """
        if caps is None:
            caps = DutyFactoryCaps()
            
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
        
        telem = DutyFactoryTelemetry(
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
        
        # 3. Hard fail if cap exceeded
        if multi_total > caps.max_multi_duties_per_day:
            logger.error(
                f"FAIL_FAST_DUTY_CAP: Day {day} produced {multi_total} multi-duties "
                f"(cap={caps.max_multi_duties_per_day})"
            )
            raise RuntimeError(
                f"FAIL_FAST_DUTY_CAP: Day {day} exceeded multi-duty cap "
                f"({multi_total} > {caps.max_multi_duties_per_day})"
            )
        
        # 4. Combine and sort deterministically
        all_duties = singletons + pairs + triples
        
        # Sort by (-dual_gain, signature) for determinism
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
        """Generate ALL 1-tour duties (no cap). O(n)."""
        duties = []
        for t in day_tours:
            d = DutyV2.from_tours(duty_id="temp", tours=[t])
            # Stable ID from signature
            object.__setattr__(d, 'duty_id', f"S_{d.signature[:12]}")
            duties.append(d)
        return duties
    
    def _generate_multi_duties(
        self,
        day: int,
        day_tours: list[TourV2],
        start_times: list[int],
        duals: dict[str, float],
        caps: DutyFactoryCaps
    ) -> tuple[list[DutyV2], list[DutyV2]]:
        """
        Generate Top-K 2er/3er duties using time-windowed successor search.
        
        O(n log n) complexity via bisect for window lookup.
        """
        pairs: list[DutyV2] = []
        triples: list[DutyV2] = []
        
        n = len(day_tours)
        if n < 2:
            return pairs, triples
        
        # Score tours by dual value for start selection
        tour_scores = [
            (i, t, duals.get(t.tour_id, 0.0)) 
            for i, t in enumerate(day_tours)
        ]
        # Sort by -dual, then by (start_min, tour_id) for tie-break
        tour_scores.sort(key=lambda x: (-x[2], x[1].start_min, x[1].tour_id))
        
        # Take TOP_M_START_TOURS as candidate starts
        start_candidates = tour_scores[:caps.top_m_start_tours]
        
        seen_pairs: set[str] = set()  # Dedupe by signature
        seen_triples: set[str] = set()
        
        for idx1, t1, dual1 in start_candidates:
            # Find successor window: tours starting in [t1.end_min + min_gap, t1.end_min + max_gap]
            window_start = t1.end_min + caps.min_gap_minutes
            window_end = t1.end_min + caps.max_gap_minutes
            
            # Binary search for window bounds (O(log n))
            left = bisect.bisect_left(start_times, window_start)
            right = bisect.bisect_right(start_times, window_end)
            
            # Candidate successors in window
            successor_candidates = []
            for j in range(left, min(right, n)):
                t2 = day_tours[j]
                if t2.tour_id == t1.tour_id:
                    continue
                if not self.validator.can_chain_intraday(t1, t2):
                    continue
                dual2 = duals.get(t2.tour_id, 0.0)
                successor_candidates.append((j, t2, dual2))
            
            # Sort successors by dual value, take top MAX_SUCC_PER_TOUR
            successor_candidates.sort(key=lambda x: (-x[2], x[1].start_min, x[1].tour_id))
            top_successors = successor_candidates[:caps.max_succ_per_tour]
            
            # Generate pairs
            for idx2, t2, dual2 in top_successors:
                pair_duty = self._try_create_duty([t1, t2])
                if pair_duty and pair_duty.signature not in seen_pairs:
                    seen_pairs.add(pair_duty.signature)
                    pairs.append(pair_duty)
                    
                    # Early exit if cap reached
                    if len(pairs) + len(triples) >= caps.max_multi_duties_per_day:
                        return pairs, triples
                    
                    # Try to extend to triples
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
        """Create and validate a duty. Returns None if invalid."""
        try:
            duty = DutyV2.from_tours(duty_id="temp", tours=tours)
            is_valid, _ = self.validator.validate_duty(duty)
            if not is_valid:
                return None
            # Stable ID from signature
            prefix = "P" if len(tours) == 2 else "T"
            object.__setattr__(duty, 'duty_id', f"{prefix}_{duty.signature[:12]}")
            return duty
        except Exception:
            return None
    
    def get_telemetry_summary(self) -> dict:
        """Get aggregated telemetry across all calls."""
        if not self.telemetry:
            return {}
        
        by_day = {}
        for t in self.telemetry:
            by_day[t.day] = t.to_dict()
        
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
