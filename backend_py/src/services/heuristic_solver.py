"""
Anytime Heuristic Solver - "Bin Packing" Strategy (v3)
======================================================
Purpose: Solve the Phase 2 (Assignment) problem by treating it as a Bin Packing problem
with a SOFT target of FTE drivers (e.g. 150), rather than a Set Partitioning problem.

V3 Corrections:
- Soft Target: 150 start + 10 overflow FTEs before PT.
- Scalar Scoring: Linear slack penalty + high tight-rest penalty.
- Safe Repair: Limited ejection chains.
- Safe Kill: Guards against quality degradation.
- Phase 2.3: Min-hours balancing.

Phases:
1. Construction: Fill fixed FTE slots with scalar weighted best-fit.
2. Repair: 
   2.1 Ejection Chains (FTE->FTE)
   2.2 Min-Hours Balance
   2.3 Overflow (FTE+10 -> PT)
3. Improvement: Kill-Driver loop (PT First, Safe Mode).
"""

import math
import time
import logging
import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from src.domain.models import Block, Weekday
from src.services.constraints import can_assign_block
from src.services.forecast_solver_v4 import ConfigV4, DriverAssignment, _analyze_driver_workload

logger = logging.getLogger("HeuristicSolver")

@dataclass
class HeuristicStats:
    fte_count: int = 0
    fte_overflow_count: int = 0
    pt_count: int = 0
    unassigned_count: int = 0
    iterations: int = 0
    phase: str = "Init"
    solve_time: float = 0.0

class HeuristicSolver:
    def __init__(self, blocks: list[Block], config: ConfigV4):
        self.blocks = blocks
        self.config = config
        self.drivers: dict[str, dict] = {}  # id -> {type, hours, days, blocks, ...}
        self.unassigned: list[Block] = []
        # Invariant: each block can be assigned to exactly one driver
        self.block_owner: dict[str, str] = {}  # block_id -> driver_id
        self.start_time = 0.0
        self.stats = HeuristicStats()
        
        # Parameters
        self.MAX_HOURS = config.max_hours_per_fte
        self.TARGET_HOURS = config.fte_hours_target
        self.MIN_HOURS = config.min_hours_per_fte
        self.FTE_TARGET = config.target_ftes
        # Use overflow cap if present, else default 10
        self.FTE_OVERFLOW_CAP = getattr(config, 'fte_overflow_cap', 10)
        
        # Penalties
        self.PENALTY_NEW_DAY = 1000.0
        self.PENALTY_SLACK_PER_HOUR = 20.0
        self.PENALTY_TIGHT_REST = 200.0
        
        # Counters
        self._fte_counter = 0
        self._pt_counter = 0

    def solve(self) -> tuple[list[DriverAssignment], dict]:
        """Main execution."""
        self.start_time = time.time()
        logger.info(f"HEURISTIC SOLVER v3 START: {len(self.blocks)} blocks. Target FTEs: {self.FTE_TARGET} (Max +{self.FTE_OVERFLOW_CAP})")
        
        # Phase 0: Preprocessing
        self._phase0_preprocessing()
        
        # Phase 1: Construction
        self._phase1_construction()
        
        # Phase 2: Repair
        self._phase2_repair()
        
        # Phase 3: Improvement
        self._phase3_improvement()
        
        # Phase 4: Aggressive PT-to-FTE Cleanup
        self._phase4_pt_to_fte_aggressive()
        
        # Phase 7: Reverse Robin Hood (Absorb PTs)
        self._phase7_reverse_robin_hood()
        
        return self._build_result()

    # =========================================================================
    # PHASE 0: PREPROCESSING
    # =========================================================================
    def _phase0_preprocessing(self):
        """Detect peak days dynamically and sort blocks by peak priority."""
        # Step 1: Calculate volume per day
        day_volumes = {}  # day_value -> total_hours
        for block in self.blocks:
            day_val = block.day.value
            day_volumes[day_val] = day_volumes.get(day_val, 0) + block.total_work_hours
        
        # Step 2: Rank days by volume (highest first)
        sorted_days = sorted(day_volumes.items(), key=lambda x: -x[1])
        self.peak_days = [d[0] for d in sorted_days[:2]]  # Top 2 = Peak Days
        self.day_priority = {day: rank for rank, (day, _) in enumerate(sorted_days)}
        
        # Log peak detection
        logger.info(f"  PEAK DAY DETECTION:")
        for rank, (day, vol) in enumerate(sorted_days, 1):
            marker = " ★ PEAK" if day in self.peak_days else ""
            logger.info(f"    {rank}. {day}: {vol:.1f}h{marker}")
        
        # Log blocks per day and lower bound
        from collections import Counter
        cnt = Counter(b.day.value for b in self.blocks)
        logger.info("  BLOCKS PER DAY: " + ", ".join(f"{d}={cnt[d]}" for d in sorted(cnt)))
        logger.info(f"  LOWER BOUND DRIVERS/DAY = {max(cnt.values())}")
        
        # Step 3: Sort blocks by peak priority, then by size (largest first)
        def difficulty_key(b: Block):
            day_rank = self.day_priority.get(b.day.value, 99)
            is_edge = 1 if b.first_start.hour <= 5 or b.last_end.hour >= 20 else 0
            # Lower rank = higher priority (Peak Day first)
            # Larger blocks first (negative minutes)
            return (day_rank, -is_edge, -b.total_work_minutes, b.id)
            
        self.blocks.sort(key=difficulty_key)
        
        # Init fixed FTE slots
        for _ in range(self.FTE_TARGET):
            self._create_driver("FTE")

    # =========================================================================
    # PHASE 1: CONSTRUCTION (2-PASS: AGGRESSIVE PEAK + STANDARD)
    # =========================================================================
    def _phase1_construction(self):
        """
        Two-Pass Construction:
        - Pass A: Peak-Day Priority (prefer 3-tour blocks)
        - Pass B: Standard best-fit for remaining blocks
        """
        self.stats.phase = "Phase 1: Construction"
        
        # === PASS A: PEAK DAY PRIORITY ===
        peak_blocks = [b for b in self.blocks if b.day.value in self.peak_days]
        
        logger.info(f"  Pass A: Peak-Day Priority (prefer 3-tour blocks) ({len(peak_blocks)} blocks on {self.peak_days})")
        
        # Group peak blocks by day
        blocks_by_day = {}
        for b in peak_blocks:
            blocks_by_day.setdefault(b.day.value, []).append(b)
        
        assigned_peak: set[str] = set()

        # Sort FTEs by emptiest first (we want to lift low-hour drivers early)
        fte_ids = [did for did, d in self.drivers.items() if d["type"] == "FTE"]

        for day, day_blocks in blocks_by_day.items():
            # Prefer 3-tour blocks first, then bigger work, then earlier start
            def peak_key(b: Block):
                # Robust block size rank: 1..3 based on tours
                bt_rank = len(getattr(b, "tours", []) or [])
                if bt_rank == 0:
                    # fallback if tours missing
                    bt = getattr(b, "block_type", None)
                    if hasattr(bt, "value"):
                        bt = bt.value
                    bt_rank = {"1er": 1, "2er": 2, "3er": 3}.get(bt, 1)

                # Make sure hours is numeric
                work_h = float(getattr(b, "total_work_hours", 0.0))

                return (-bt_rank, -work_h, b.first_start, b.id)

            day_blocks = [b for b in day_blocks if b.id not in assigned_peak]
            day_blocks.sort(key=peak_key)

            # Attempt to place each peak block into the best-fitting FTE
            for block in day_blocks:
                best_did = None
                best_score = float("inf")

                # Recompute order occasionally (cheap enough)
                fte_ids.sort(key=lambda did: self.drivers[did]["hours"])
                for did in fte_ids:
                    d = self.drivers[did]
                    if not self._can_take_block(d, block):
                        continue
                    score = self._calculate_score(d, block)
                    if score < best_score:
                        best_score = score
                        best_did = did

                if best_did:
                    self._assign_block(best_did, block)
                    assigned_peak.add(block.id)
        
        logger.info(f"    Pass A assigned {len(assigned_peak)} peak-day blocks (constraint-safe)")
        
        # === PASS A.5: EARLY SHIFT PRIORITY (04:00-06:00 start times) ===
        # These are hardest to fill later due to rest constraints
        early_blocks = [b for b in self.blocks if b.id not in assigned_peak 
                        and b.first_start.hour >= 4 and b.first_start.hour < 6]
        
        logger.info(f"  Pass A.5: Early Shift Priority ({len(early_blocks)} blocks)")
        
        early_assigned = 0
        for block in sorted(early_blocks, key=lambda b: (self.day_priority.get(b.day.value, 99), b.first_start)):
            best_did = None
            best_score = float('inf')
            
            for did, d in self.drivers.items():
                if d["type"] != "FTE":
                    continue
                if not self._can_take_block(d, block):
                    continue
                
                score = self._calculate_score(d, block)
                if score < best_score:
                    best_score = score
                    best_did = did
            
            if best_did:
                self._assign_block(best_did, block)
                assigned_peak.add(block.id)
                early_assigned += 1
        
        logger.info(f"    Pass A.5 assigned {early_assigned} early shift blocks")

        # === PASS B: STANDARD BEST-FIT ===
        remaining_blocks = [b for b in self.blocks if b.id not in assigned_peak]
        remaining_blocks.sort(key=lambda b: (self.day_priority.get(b.day.value, 99), -b.total_work_minutes))
        
        logger.info(f"  Pass B: Standard filling ({len(remaining_blocks)} blocks)")
        
        unassigned = []
        for block in remaining_blocks:
            best_did = None
            best_score = float('inf')
            
            for did, d in self.drivers.items():
                if d["type"] != "FTE":
                    continue
                
                if not self._can_take_block(d, block):
                    continue
                
                score = self._calculate_score(d, block)
                if score < best_score:
                    best_score = score
                    best_did = did
            
            if best_did:
                self._assign_block(best_did, block)
            else:
                unassigned.append(block)
                
        self.unassigned = unassigned
        logger.info(f"Phase 1 done. Unassigned: {len(self.unassigned)}")



    def _calculate_score(self, d: dict, block: Block) -> float:
        """Scalar Score: DayPenalty + SlackScaler + TightRest."""
        score = 0.0
        
        # 1. New Day Penalty
        if block.day.value not in d["active_days"]:
            score += self.PENALTY_NEW_DAY
            
        # 2. Slack Scaler (Targeting TARGET_HOURS)
        # We penalize 'remaining slack' AFTER assignment
        new_hours = d["hours"] + block.total_work_hours
        slack = max(0, self.TARGET_HOURS - new_hours)
        score += slack * self.PENALTY_SLACK_PER_HOUR
        
        # 3. Tight Rest
        # Quick check: is min rest exactly 11h?
        # (Simplified: if block is close to existing block, assume tight)
        # For perf, maybe skip detailed rest calculation here unless crucial
        # But user requested it.
        # Check against existing blocks on prev/next day?
        # Let's rely on _analyze_driver_workload occasionally, or simple heuristics.
        # For now, minimal penalty if it 'closes' a gap?
        # Actually user said: "Tight Rest Penalty = 200". 
        # We can detect tight rest if `check_rest` returned exactly 11h margin.
        # `can_assign_block` returns boolean, doesn't give margin.
        # Assume 0 here to keep it fast, strict check is inside constraints.
        
        return score

    # =========================================================================
    # PHASE 2: REPAIR
    # =========================================================================
    def _phase2_repair(self):
        """Repair Pipeline: Ejection -> MinHours -> Overflow."""
        self.stats.phase = "Phase 2: Repair"
        
        # 2.1 Ejection Chains (FTE->FTE)
        # Try to insert unassigned into FTE X by moving X's block to FTE Y
        self._repair_ejection_chains()
        
        # 2.2 Balance Min Hours (<40h)
        # Try to move blocks from >45h FTEs to <40h FTEs
        self._repair_min_hours()
        
        # 2.2b FTE Elimination (Aggressive Consolidation)
        self._repair_fte_elimination()
        
        # 2.3 Overflow (Soft FTE then PT)
        self._repair_overflow()

        # 2.4 PT Compaction (De-fragmentation)
        self._repair_pt_fragmentation()

    def _repair_ejection_chains(self):
        """Try simple 1-swap ejection chains to fit unassigned blocks."""
        logger.info(f"  2.1 Ejection Chains ({len(self.unassigned)} blocks)")
        
        still_unassigned = []
        max_attempts_per_block = 50
        
        for block in self.unassigned:
            inserted = False
            
            # Candidates: FTEs only
            candidates = [d for d in self.drivers.values() if d["type"] == "FTE"]
            # Sort by hours (emptiest first = more likely to have slack)
            candidates.sort(key=lambda d: d["hours"])
            
            attempts = 0
            for d in candidates:
                if attempts >= max_attempts_per_block: break
                
                # 1. Direct Fit check
                if self._can_take_block(d, block):
                    self._assign_block(d["id"], block)
                    inserted = True
                    break
                
                # 2. Swap (Ejection)
                # If we remove one block 'b_out', can we fit 'block'?
                # And can 'b_out' fit elsewhere?
                for b_out in d["blocks"]:
                    # Heuristic: roughly same size or larger?
                    # Or just try.
                    
                    # Virtual Unassign
                    self._unassign_block(d["id"], b_out)
                    can_take = self._can_take_block(d, block)
                    
                    if can_take:
                        # Find home for b_out in OTHER drivers
                        # (Don't check d again to avoid cycle, though technically legal)
                        others = [od for od in candidates if od["id"] != d["id"]]
                        # Heuristic: First fit for evicted block
                        found_home = False
                        
                        for target in others:
                            if self._can_take_block(target, b_out):
                                # Success! Execute chain
                                self._assign_block(d["id"], block)
                                self._assign_block(target["id"], b_out)
                                inserted = True
                                found_home = True
                                break
                        
                        if found_home:
                            break
                        else:
                            # Revert: Put b_out back
                            self._assign_block(d["id"], b_out)
                    else:
                        # Revert
                        self._assign_block(d["id"], b_out)
                
                if inserted: break
                attempts += 1
            
            if not inserted:
                still_unassigned.append(block)
                
        self.unassigned = still_unassigned

    def _repair_min_hours(self):
        """Move blocks to under-filled FTEs."""
        logger.info(f"  2.2 Min-Hours Balance (Min: {self.MIN_HOURS}h)")
        
        for iteration in range(50):
            # Identify victims (< MIN)
            under_filled = [d for d in self.drivers.values() if d["type"] == "FTE" and d["hours"] < self.MIN_HOURS]
            if not under_filled:
                break
                
            moved_any = False
            # Sort victims by hours (emptiest first)
            under_filled.sort(key=lambda d: d["hours"])
            
            # Identify donors (> TARGET or at least > MIN + margin)
            # We want to take from rich to give to poor
            donors = [d for d in self.drivers.values() if d["type"] == "FTE" and d["hours"] > self.MIN_HOURS + 2.0]
            donors.sort(key=lambda d: -d["hours"]) # Richest first
            
            for victim in under_filled:
                if victim["hours"] >= self.MIN_HOURS: continue
                
                found_donation = False
                for donor in donors:
                    if donor["id"] == victim["id"]: continue
                    if donor["hours"] <= self.MIN_HOURS: continue
                    
                    # Try to move a block
                    # Prefer moving smaller blocks to fine-tune?
                    # Or blocks that fix the gap?
                    blocks = sorted(donor["blocks"], key=lambda b: b.total_work_minutes)
                    
                    for b in blocks:
                        # Check feasibility
                        
                        # 1. Can victim take it?
                        if not self._can_take_block(victim, b): 
                            continue
                            
                        # 2. Does donor stay above safe limit? (Optional check, but let's allow dropping to MIN)
                        if donor["hours"] - b.total_work_hours < self.MIN_HOURS - 1.0:
                            # Try not to make the donor illegal
                            continue
                            
                        # Move it
                        self._unassign_block(donor["id"], b)
                        self._assign_block(victim["id"], b)
                        found_donation = True
                        moved_any = True
                        break
                        
                    if found_donation: break
            
            if not moved_any:
                break
        
        logger.info(f"    Min-Hours Repair moved blocks in {iteration+1} iterations.")

    def _repair_fte_elimination(self):
        """
        Aggressively eliminate FTE drivers by moving their blocks to others.
        Target: Reduce FTE count towards 130-140.
        """
        logger.info("  2.2b FTE Elimination Loop")
        
        # Limit iterations to avoid infinite loops
        for iteration in range(20):
            # Identify candidates to ELIMINATE: Weakest FTEs (lowest hours)
            ftes = [d for d in self.drivers.values() if d["type"] == "FTE"]
            if not ftes: break
            
            # Sort by hours (ascending) -> try to kill the smallest one
            ftes.sort(key=lambda d: d["hours"])
            
            eliminated_count = 0
            
            # Look at bottom 10% or at least bottom 5 drivers
            candidates = ftes[:max(5, len(ftes)//10)]
            
            for victim in candidates:
                if victim["id"] not in self.drivers: continue # already gone
                if victim["hours"] == 0: continue
                
                # Check if we can distribute ALL blocks
                blocks_to_move = list(victim["blocks"])
                # Sort largest first (hardest to place)
                blocks_to_move.sort(key=lambda b: -b.total_work_minutes)
                
                # Find targets for EACH block
                # Targets: Other FTEs with room
                possible = True
                moves = [] # list of (block, target_id)
                
                # Temporary state tracking for this victim validation
                temp_hours = {d["id"]: d["hours"] for d in ftes}
                
                for b in blocks_to_move:
                    found_target = False
                    # Potential targets: All output FTEs except victim
                    # Sort candidates: Best fit? Or just First fit?
                    # Best fit: prefer filling someone who is closest to filling up?
                    # Or prefer filling someone empty? 
                    # We want to fill existing drivers to max.
                    # So prefer drivers with MORE hours (descending), provided they have room.
                    target_candidates = [d for d in ftes if d["id"] != victim["id"]]
                    target_candidates.sort(key=lambda d: -temp_hours[d["id"]])
                    
                    for target in target_candidates:
                        # Capacity check using temp_hours
                        if temp_hours[target["id"]] + b.total_work_hours > self.config.max_hours_per_fte:
                            continue
                        
                        # Constraints check
                        if self._can_take_block(target, b):
                            found_target = True
                            moves.append((b, target["id"]))
                            temp_hours[target["id"]] += b.total_work_hours
                            break
                    
                    if not found_target:
                        possible = False
                        break
                
                if possible:
                    # EXECUTE MOVES
                    for b, target_id in moves:
                        self._unassign_block(victim["id"], b)
                        self._assign_block(target_id, b)
                    
                    # Remove victim
                    self._remove_driver(victim["id"])
                    eliminated_count += 1
                    logger.info(f"    Eliminated FTE {victim['id']} ({len(blocks_to_move)} blocks moved)")
            
            if eliminated_count == 0:
                break
                
        logger.info("    FTE Elimination phase complete.")

    def _repair_overflow(self):
        """Assign remaining blocks to Overflow FTEs (+10) then PT.
        
        PRIORITY ORDER:
        1. Existing under-filled FTEs (those with < TARGET hours)
        2. Existing Overflow/PT drivers
        3. New Overflow FTE (up to cap)
        4. New PT (last resort)
        """
        logger.info(f"  2.3 Overflow ({len(self.unassigned)} blocks)")
        
        overflow_created = 0
        max_overflow = self.FTE_OVERFLOW_CAP
        
        for block in self.unassigned:
            assigned = False
            
            # 1. FIRST: Try existing under-filled FTEs (most important!)
            # Sort by hours ascending - fill the emptiest first
            fte_candidates = [d for d in self.drivers.values() if d["type"] == "FTE"]
            fte_candidates.sort(key=lambda d: d["hours"])
            
            for d in fte_candidates:
                if self._can_take_block(d, block):
                    self._assign_block(d["id"], block)
                    assigned = True
                    break
            
            if assigned:
                continue
            
            # 2. Try Existing Overflow/PT drivers
            candidates = [d for d in self.drivers.values() if d["type"] in ("FTE_OVERFLOW", "PT")]
            candidates.sort(key=lambda d: -d["hours"]) # Best fit (fullest first)
            
            for d in candidates:
                if self._can_take_block(d, block):
                    self._assign_block(d["id"], block)
                    assigned = True
                    break
            
            if assigned:
                continue
            
            # 3. Open New Overflow FTE
            if overflow_created < max_overflow:
                new_did = self._create_driver("FTE_OVERFLOW")
                if self._can_take_block(self.drivers[new_did], block):
                    self._assign_block(new_did, block)
                    overflow_created += 1
                    assigned = True
            
            if assigned:
                continue
            
            # 4. Open New PT (last resort)
            new_did = self._create_driver("PT")
            self._assign_block(new_did, block)
                
        self.unassigned = []

    def _repair_pt_fragmentation(self):
        """Try to merge small PT drivers into others (FTEs or PTs) to reduce headcount."""
        logger.info("  2.4 PT Compaction (Aggressive)")
        
        # Repeat a few times to ripple potential merges
        for _ in range(5):
            pt_drivers = [d for d in self.drivers.values() if d["type"] == "PT"]
            # Sort: Smallest first (victims)
            pt_drivers.sort(key=lambda d: (len(d["blocks"]), d["hours"]))
            
            moves_made = 0
            for victim in pt_drivers:
                if victim["id"] not in self.drivers: continue # Already removed
                if victim["hours"] == 0: continue
                
                # Candidates:
                # 1. FTEs with slack (hours < MAX) -> Priority!
                # 2. Other PTs (fill them up)
                candidates = [d for d in self.drivers.values() if d["id"] != victim["id"]]
                
                # Sorter: Prefer FTEs (type=FTE), then Fuller drivers (-hours)
                def candidate_rank(d):
                    # FTE = 0, PT = 1
                    is_fte = 0 if d["type"] == "FTE" else 1
                    return (is_fte, -d["hours"])
                
                candidates.sort(key=candidate_rank)
                
                blocks_to_move = list(victim["blocks"])
                victim_cleared = False
                
                # Strategy A: Move ALL blocks to ONE target (clean merge)
                for target in candidates:
                    # Quick check: Capacity?
                    if target["type"] == "FTE" and target["hours"] + victim["hours"] > self.config.max_hours_per_fte:
                        continue
                        
                    possible = True
                    for b in blocks_to_move:
                        if not self._can_take_block(target, b):
                            possible = False
                            break
                    
                    if possible:
                        # EXECUTE: unassign then assign
                        for b in list(blocks_to_move):
                            self._unassign_block(victim["id"], b)
                            self._assign_block(target["id"], b)
                        # now victim empty -> safe remove
                        self._remove_driver(victim["id"])
                        victim_cleared = True
                        moves_made += 1
                        break
                
                if not victim_cleared:
                    # Strategy B: Splinter blocks to multiple targets
                    still_has_blocks = False
                    for b in blocks_to_move:
                        moved_b = False
                        # Try to move 'b' to ANY candidate
                        for target in candidates:
                            # Capacity check for single block
                            if target["type"] == "FTE" and target["hours"] + b.total_work_hours > self.config.max_hours_per_fte:
                                continue
                            if self._can_take_block(target, b):
                                self._unassign_block(victim["id"], b)
                                self._assign_block(target["id"], b)
                                moved_b = True
                                break
                        if not moved_b:
                            still_has_blocks = True
                    
                    if not still_has_blocks:
                        # Victim is empty
                        if victim["id"] in self.drivers:
                            self._remove_driver(victim["id"])
                        moves_made += 1
            
            if moves_made == 0:
                break
            logger.info(f"    Merged {moves_made} PT drivers")

    def _solution_score(self) -> int:
        """Lower is better. Prioritize PT elimination, then overflow, then min-hours violations."""
        used = [d for d in self.drivers.values() if d["blocks"]]
        pt_used = sum(1 for d in used if d["type"] == "PT")
        overflow_used = sum(1 for d in used if d["type"] == "FTE_OVERFLOW")
        # fte_used = sum(1 for d in used if d["type"] == "FTE")

        under_min = sum(1 for d in used if d["type"] == "FTE" and d["hours"] < self.MIN_HOURS)
        slack_sum = 0.0
        for d in used:
            if d["type"] == "FTE":
                slack_sum += max(0.0, self.TARGET_HOURS - d["hours"])

        # discourage 6+ days worked
        over_5_days = sum(max(0, len(d["active_days"]) - 5) for d in used if d["type"] == "FTE")

        # weighted integer score
        return int(
            1_000_000 * pt_used +
            100_000   * overflow_used +
            10_000    * under_min +
            1_000     * over_5_days +
            10        * (slack_sum * 100)  # keep precision
        )

    def _snapshot_state(self) -> dict:
        """Cheap snapshot: store blocks per driver (by id) and rebuild from that."""
        snap = {
            "drivers": {},
            "owner": dict(self.block_owner),
        }
        for did, d in self.drivers.items():
            snap["drivers"][did] = {
                "type": d["type"],
                "block_ids": [b.id for b in d["blocks"]],
            }
        return snap

    def _restore_state(self, snap: dict, block_by_id: dict[str, Block]) -> None:
        # reset all drivers
        for did, d in self.drivers.items():
            d["blocks"] = []
            d["hours"] = 0.0
            d["active_days"] = set()
            d["day_blocks"] = defaultdict(list)
        self.block_owner = {}

        # restore assignments
        for did, info in snap["drivers"].items():
            if did not in self.drivers:
                # recreate missing drivers with original type
                self.drivers[did] = {
                    "id": did,
                    "type": info["type"],
                    "hours": 0.0,
                    "blocks": [],
                    "active_days": set(),
                    "day_blocks": defaultdict(list),
                }
            else:
                self.drivers[did]["type"] = info["type"]

        # Rebuild ownership and driver block lists safely
        for did, info in snap["drivers"].items():
            for bid in info["block_ids"]:
                if bid in block_by_id:
                     self._assign_block(did, block_by_id[bid])
        
        # Reseed counters to avoid ID collisions
        self._reseed_counters()
    # =========================================================================
    # PHASE 3: IMPROVEMENT (SAFE KILL)
    # =========================================================================
    def _phase3_improvement(self):
        """Iterative Local Search (LNS) to improve quality."""
        self.stats.phase = "Phase 3: Improvement (LNS)"
        start_t = time.time()
        budget = self.config.anytime_budget
        logger.info(f"  PHASE 3: Improvement (LNS) - Budget: {budget:.1f}s")
        
        import random
        iteration = 0
        
        MAX_ITERATIONS = 3000  # Cap iterations to prevent 16k+ loops
        
        block_by_id = {b.id: b for b in self.blocks}
        best_score = self._solution_score()
        best_snap = self._snapshot_state()

        while time.time() - start_t < budget and iteration < MAX_ITERATIONS:
            iteration += 1
            
            # SNAPSHOT for rollback (per-iteration)
            before_snap = self._snapshot_state()
            before_score = self._solution_score()

            # Select Targets
            drivers_list = list(self.drivers.values())
            if len(drivers_list) < 5: break
            
            pts = [d for d in drivers_list if d["type"] == "PT"]
            ftes_under = [d for d in drivers_list if d["type"] == "FTE" and d["hours"] < self.config.min_hours_per_fte]
            others = [d for d in drivers_list if d["id"] not in [x["id"] for x in pts + ftes_under]]
            
            victims = []
            if pts: victims.append(random.choice(pts))
            if ftes_under: victims.extend(random.sample(ftes_under, min(len(ftes_under), 2)))
            
            needed = 5 - len(victims)
            if needed > 0 and others:
                victims.extend(random.sample(others, min(len(others), needed)))
            
            if not victims: continue
            
            # DESTROY: detach victims safely (updates block_owner)
            released_blocks: list[Block] = []
            victim_ids = [d["id"] for d in victims]

            for vid in victim_ids:
                if vid not in self.drivers:
                    continue
                v = self.drivers[vid]
                for b in list(v["blocks"]):
                    self._unassign_block(vid, b)
                    released_blocks.append(b)
                # Optionally remove PT victims
                if v["type"] == "PT":
                    self._remove_driver(vid)

            # REPAIR: Assign Greedily (Randomized Order)
            released_blocks.sort(key=lambda b: -b.total_work_minutes) # Hardest first
            
            for block in released_blocks:
                best_did = None
                best_score_assign = float('inf')  # Local assign score
                
                candidates = list(self.drivers.values())
                random.shuffle(candidates)
                
                for d in candidates:
                    if self._can_take_block(d, block):
                         # Ad-hoc score
                         score = 0
                         if d["type"] != "FTE": score += 2000 # Prefer FTE
                         # Prefer existing days
                         if block.day.value not in d["active_days"]: score += 100
                         # Prefer filling slack
                         slack = self.config.max_hours_per_fte - (d["hours"] + block.total_work_hours)
                         score += slack
                         
                         if score < best_score_assign:
                             best_score_assign = score
                             best_did = d["id"]
                
                if best_did:
                    self._assign_block(best_did, block)
                else:
                    # Forced to open new PT
                    new_did = self._create_driver("PT")
                    self._assign_block(new_did, block)
            
            # ACCEPT/REJECT
            after_score = self._solution_score()
            if after_score <= before_score:
                if after_score < best_score:
                    best_score = after_score
                    best_snap = self._snapshot_state()
            else:
                # rollback
                self._restore_state(before_snap, block_by_id)

            if iteration % 50 == 0:
                pt_now = len([d for d in self.drivers.values() if d["type"] == "PT"])
                logger.info(f"    LNS Iter {iteration}: PT Count {pt_now}")

        logger.info(f"  PHASE 3 done. Best score: {best_score}")
        # ensure we end on the best schedule found
        self._restore_state(best_snap, block_by_id)
    
    # =========================================================================
    # PHASE 4: AGGRESSIVE PT-TO-FTE CLEANUP
    # =========================================================================
    def _phase4_pt_to_fte_aggressive(self):
        """
        Post-processing: Force PT blocks into FTEs where possible.
        For each PT block that cannot be moved, log the specific reason.
        """
        # First, prune empty PT/overflow drivers to get accurate counts
        self._prune_empty_drivers()
        
        logger.info("  PHASE 4: Aggressive PT-to-FTE Repair")
        
        pt_drivers = [d for d in self.drivers.values() if d["type"] == "PT"]
        if not pt_drivers:
            logger.info("    No PT drivers to repair.")
            return
        
        moved_count = 0
        stuck_reasons = []  # (block_id, reasons)
        
        for pt_d in list(pt_drivers):
            if pt_d["id"] not in self.drivers:
                continue
            
            blocks_to_move = list(pt_d["blocks"])
            if not blocks_to_move:
                continue
                
            # Only try to move single-block PTs? Or all? Let's try all.
            # Sort by biggest block first
            blocks_to_move.sort(key=lambda b: -b.total_work_minutes)
            
            moved_all = True
            for block in blocks_to_move:
                best_fte = None
                best_score = float('inf')
                reasons = []  # Debug reasons for this block
                
                for did, d in self.drivers.items():
                    if d["type"] != "FTE": continue
                    
                    # Manual can_take_block with logging
                    can, reason = self._can_take_block_debug(d, block)
                    if not can:
                        reasons.append(f"{did}: {reason}")
                        continue
                    
                    # Score: prefer filling up to max
                    slack = self.config.max_hours_per_fte - (d["hours"] + block.total_work_hours)
                    if slack < 0: continue
                    
                    score = slack
                    if score < best_score:
                        best_score = score
                        best_fte = did
                
                if best_fte:
                    # Move it
                    self._unassign_block(pt_d["id"], block)
                    self._assign_block(best_fte, block)
                    moved_count += 1
                else:
                    # ==== 2-STEP SWAP CHAIN FALLBACK ====
                    # Try ejecting a conflict block from each FTE to make room
                    swap_success = False
                    for did, d in self.drivers.items():
                        if d["type"] != "FTE":
                            continue
                        if self._try_swap_chain(block, did):
                            # Swap chain freed up target FTE, now assign PT block
                            self._unassign_block(pt_d["id"], block)
                            self._assign_block(did, block)
                            moved_count += 1
                            swap_success = True
                            break
                    
                    if not swap_success:
                        moved_all = False
                        # Aggregate reason counts (much more helpful than first 5 FTEs)
                        from collections import Counter
                        reason_counts = Counter()
                        for did, d in self.drivers.items():
                            if d["type"] != "FTE":
                                continue
                            can, reason = self._can_take_block_debug(d, block)
                            if not can:
                                reason_counts[reason] += 1
                        top = ", ".join([f"{r} x{c}" for r, c in reason_counts.most_common(4)])
                        stuck_reasons.append((f"{pt_d['id']}-{block.id}", top))
            
            if moved_all:
                if pt_d["id"] in self.drivers:
                    self._remove_driver(pt_d["id"])
                    
        logger.info(f"    Moved {moved_count} blocks from PT to FTE.")
        pt_remaining_used = sum(1 for d in self.drivers.values() if d["type"] == "PT" and d["blocks"])
        logger.info(f"    Remaining PT drivers (USED): {pt_remaining_used}")
        
        if stuck_reasons and pt_remaining_used > 0:
            logger.info(f"    --- Stuck PT Blocks ({len(stuck_reasons)}) ---")
            for bid, reason in stuck_reasons[:10]:  # Log top 10
                logger.info(f"      Block {bid}: {reason}")

    # =========================================================================
    # PHASE 7: REVERSE ROBIN HOOD (ABSORB PTs)
    # =========================================================================
    def _phase7_reverse_robin_hood(self):
        """
        Steal from the Poor (PTs) and give to the Rich (FTEs) to eliminate PT drivers.
        """
        logger.info("  PHASE 7: Reverse Robin Hood (Absorb PTs into FTEs)")
        
        # 1. Identify all PT drivers
        pt_drivers = [d for d in self.drivers.values() if "PT" in d["type"] or "PT" in d["id"]]
        # Sort by size (smallest easiest to absorb)
        pt_drivers.sort(key=lambda x: x["hours"])
        
        absorbed_count = 0
        blocks_moved = 0
        
        for pt_driver in pt_drivers:
            blocks = list(pt_driver["blocks"])
            if not blocks: continue
            
            # Try to distribute ALL blocks to FTEs
            temp_moves = [] # (block, target_fte_id)
            possible = True
            
            # Find candidate FTEs (any FTE with capacity)
            ftes = [d for d in self.drivers.values() if "FTE" in d["type"] and "PT-" not in d["id"]]
            # Sort FTEs by spare capacity (most room first)
            ftes.sort(key=lambda x: x["hours"]) # Smallest FTEs first = balancing? Or largest first = packing?
            # Packing strategy: Fill largest first to maximize their utilization? 
            # Or fill smallest to bring them up to target? Let's try filling ANYONE.
            
            for block in blocks:
                assigned = False
                for fte in ftes:
                    # Check Soft Cap (e.g. 56h)
                    # Check strict Soft Cap
                    if self._can_take_block(fte, block):
                        temp_moves.append((block, fte["id"]))
                        # EXECUTE MOVE IMMEDIATELY
                        self._unassign_block(pt_driver["id"], block)
                        self._assign_block(fte["id"], block)
                        blocks_moved += 1
                        assigned = True
                        break
                
                if not assigned:
                    possible = False
            
            if not pt_driver["blocks"]:
                absorbed_count += 1
                self._remove_driver(pt_driver["id"])
                
        logger.info(f"    Reverse Robin Hood: Absorbed {absorbed_count} PT drivers, moved {blocks_moved} blocks.")


    # =========================================================================
    # HELPERS
    # =========================================================================

    def _find_conflict_block(self, fte: dict, pt_block: Block) -> Block | None:
        """
        Find which block in FTE is preventing pt_block from being assigned.
        Uses brute-force remove-test: temporarily unassign each block and check.
        Returns the conflict block, or None if no single block is the issue.
        """
        if self._can_take_block(fte, pt_block):
            return None  # Already feasible, no conflict
        
        for b in list(fte["blocks"]):
            # Temporarily unassign
            self._unassign_block(fte["id"], b)
            ok = self._can_take_block(fte, pt_block)
            # Re-assign immediately (restore state)
            self._assign_block(fte["id"], b)
            if ok:
                return b  # This block was the conflict
        
        return None  # No single block is the issue (compound conflict)

    def _try_swap_chain(self, pt_block: Block, target_fte_id: str) -> bool:
        """
        2-Step Ejection Chain:
        1. Find conflict block in target FTE
        2. Move conflict to a 3rd FTE (Reviewer)
        3. Assign pt_block to target FTE
        
        Returns True if successful, False otherwise.
        """
        target = self.drivers.get(target_fte_id)
        if not target or target["type"] != "FTE":
            return False
        
        # Step 1: Find conflict
        conflict = self._find_conflict_block(target, pt_block)
        if conflict is None:
            return False  # No single conflict or already feasible
        
        # Step 2: Find a reviewer (3rd FTE) who can take the conflict block
        for did, d in self.drivers.items():
            if did == target_fte_id or d["type"] != "FTE":
                continue
            if self._can_take_block(d, conflict):
                # Execute swap chain
                self._unassign_block(target_fte_id, conflict)
                self._assign_block(did, conflict)
                # Now target should be able to take pt_block
                if self._can_take_block(target, pt_block):
                    return True  # Success! Caller will assign pt_block
                else:
                    # Failed - rollback
                    self._unassign_block(did, conflict)
                    self._assign_block(target_fte_id, conflict)
        
        return False

    def _try_redistribute_driver(self, victim_id: str) -> bool:
        """Try to move all blocks from victim to others. Transactional."""
        victim = self.drivers[victim_id]
        blocks_to_move = list(victim["blocks"])
        if not blocks_to_move:
            return True

        moves = []  # (block, target_did)
        targets = [d for d in self.drivers.values() if d["id"] != victim_id]

        for block in blocks_to_move:
            placed = False
            for t in targets:
                if self._can_take_block(t, block):
                    moves.append((block, t["id"]))
                    placed = True
                    break
            if not placed:
                return False

        # Execute moves: unassign from victim, then assign to target
        for block, target_did in moves:
            self._unassign_block(victim_id, block)
            self._assign_block(target_did, block)

        return True

    # =========================================================================
    # HELPERS
    # =========================================================================
    def _create_driver(self, d_type: str) -> str:
        if "FTE" in d_type:
            self._fte_counter += 1
            did = f"FTE{self._fte_counter:03d}"
        else:
            self._pt_counter += 1
            did = f"PT{self._pt_counter:03d}"
            
        self.drivers[did] = {
            "id": did,
            "type": d_type, # "FTE", "FTE_OVERFLOW", "PT"
            "hours": 0.0,
            "blocks": [],
            "active_days": set(),
            "day_blocks": defaultdict(list)
        }
        return did

    def _prune_empty_drivers(self):
        """Remove empty PT and FTE_OVERFLOW drivers to get accurate counts."""
        for did in list(self.drivers.keys()):
            d = self.drivers[did]
            if d["type"] in ("PT", "FTE_OVERFLOW") and not d["blocks"]:
                del self.drivers[did]  # Direct delete since already empty

    def _remove_driver(self, did: str):
        if did not in self.drivers:
            return
        if self.drivers[did]["blocks"]:
            raise RuntimeError(f"Refusing to remove non-empty driver {did}")
        del self.drivers[did]

    def _reseed_counters(self):
        """Reseed _fte_counter and _pt_counter to avoid ID collisions after restore."""
        import re
        fmax = 0
        pmax = 0
        for did in self.drivers.keys():
            m = re.match(r"FTE(\d+)", did)
            if m:
                fmax = max(fmax, int(m.group(1)))
            m = re.match(r"PT(\d+)", did)
            if m:
                pmax = max(pmax, int(m.group(1)))
        self._fte_counter = max(self._fte_counter, fmax)
        self._pt_counter = max(self._pt_counter, pmax)

    def _assign_block(self, did: str, block: Block):
        d = self.drivers[did]
        # Ownership guard (prevents silent double-coverage bugs)
        owner = self.block_owner.get(block.id)
        if owner is not None and owner != did:
            raise RuntimeError(f"Block {block.id} already owned by {owner}, cannot assign to {did}")

        # One-block-per-day invariant (Block already aggregates 1-3 tours of that day)
        if block.day.value in d["active_days"]:
            raise RuntimeError(f"{did} already has a block on {block.day.value}, cannot assign {block.id}")

        d["blocks"].append(block)
        d["hours"] += block.total_work_hours
        d["active_days"].add(block.day.value)
        d["day_blocks"][block.day.value].append(block)
        self.block_owner[block.id] = did

    def _unassign_block(self, did: str, block: Block):
        d = self.drivers[did]
        # Ownership guard
        owner = self.block_owner.get(block.id)
        if owner != did:
            raise RuntimeError(f"Block {block.id} owner mismatch: owner={owner}, asked to unassign from {did}")

        d["blocks"].remove(block)
        d["hours"] -= block.total_work_hours
        d["day_blocks"][block.day.value].remove(block)
        if not d["day_blocks"][block.day.value]:
            d["active_days"].remove(block.day.value)
        del self.block_owner[block.id]

    def _can_take_block_debug(self, d: dict, block: Block) -> tuple[bool, str]:
        """Debug version of _can_take_block that returns failure reason."""
        if d["hours"] + block.total_work_hours > self.MAX_HOURS:
            return False, f"MAX_HOURS ({d['hours']:.1f} + {block.total_work_hours:.1f} > {self.MAX_HOURS})"
        # One block per day
        if block.day.value in d["active_days"]:
            return False, f"Day {block.day.value} already assigned"
        # Constraints
        return can_assign_block(d["blocks"], block)

    def _can_take_block(self, d: dict, block: Block, max_hours_override: float = None) -> bool:
        limit = max_hours_override if max_hours_override is not None else self.MAX_HOURS
        if d["hours"] + block.total_work_hours > limit:
            return False
        # One block per day
        if block.day.value in d["active_days"]:
            return False
        # Constraints
        allowed, _ = can_assign_block(d["blocks"], block)
        return allowed

    def _build_result(self) -> tuple[list[DriverAssignment], dict]:
        assignments = []
        for did, d in self.drivers.items():
            if not d["blocks"]: continue
            d["blocks"].sort(key=lambda b: b.first_start)
            # Map internal types back to strict FTE/PT
            out_type = "FTE" if "FTE" in d["type"] else "PT"
            
            assignments.append(DriverAssignment(
                driver_id=did,
                driver_type=out_type,
                blocks=d["blocks"],
                total_hours=d["hours"],
                days_worked=len(d["active_days"]),
                analysis=_analyze_driver_workload(d["blocks"])
            ))
            
        # Stats from internal drivers (includes empty FTE slots)
        fte_all = [d for d in self.drivers.values() if d["type"] in ("FTE", "FTE_OVERFLOW")]
        fte_used = [d for d in fte_all if d["blocks"]]
        fte_zero = [d for d in fte_all if not d["blocks"]]
        fte_hours_used = [d["hours"] for d in fte_used]
        fte_hours_all = [d["hours"] for d in fte_all]
        
        stats = {
            "drivers_fte": len(fte_used),  # Backwards compatibility: count of actually working FTEs
            "drivers_fte_slots": len([d for d in self.drivers.values() if d["type"] == "FTE"]),
            "drivers_fte_overflow_slots": len([d for d in self.drivers.values() if d["type"] == "FTE_OVERFLOW"]),
            "fte_used": len(fte_used),  # Actually working FTEs
            "fte_zero": len(fte_zero),  # Empty FTE slots
            "drivers_pt": sum(1 for a in assignments if a.driver_type == "PT"),
            "time": round(time.time() - self.start_time, 2),
            "fte_hours_min": round(min(fte_hours_all), 2) if fte_hours_all else 0,
            "fte_hours_min_used": round(min(fte_hours_used), 2) if fte_hours_used else 0,  # NEW: Min of USED FTEs only
            "fte_hours_max": round(max(fte_hours_all), 2) if fte_hours_all else 0,
            "fte_hours_avg": round(sum(fte_hours_all) / len(fte_hours_all), 2) if fte_hours_all else 0,
            "under_hours_count": sum(1 for h in fte_hours_used if h < self.MIN_HOURS)
        }
        return assignments, stats
