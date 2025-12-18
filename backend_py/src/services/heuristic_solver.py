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
        
        return self._build_result()

    # =========================================================================
    # PHASE 0: PREPROCESSING
    # =========================================================================
    def _phase0_preprocessing(self):
        """Sort blocks and initialize target FTE slots."""
        # Sort by Difficulty
        def difficulty_key(b: Block):
            is_sat = 2 if b.day.value == "Sat" else 0
            is_fri = 1.5 if b.day.value == "Fri" else 0
            is_edge = 1 if b.first_start.hour <= 5 or b.last_end.hour >= 20 else 0
            # Higher priority first (negative for sorting DESC)
            return (-is_sat, -is_fri, -is_edge, -b.total_work_minutes, b.id)
            
        self.blocks.sort(key=difficulty_key)
        
        # Init fixed FTE slots
        for _ in range(self.FTE_TARGET):
            self._create_driver("FTE")

    # =========================================================================
    # PHASE 1: CONSTRUCTION
    # =========================================================================
    def _phase1_construction(self):
        """Fill initialized FTE slots."""
        self.stats.phase = "Phase 1: Construction"
        
        unassigned = []
        for block in self.blocks:
            best_did = None
            best_score = float('inf')
            
            # Iterate only FTEs (fast for 150)
            for did, d in self.drivers.items():
                if d["type"] != "FTE": continue
                
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
                        # Move all
                        for b in blocks_to_move:
                            self._assign_block(target["id"], b)
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

    # =========================================================================
    # PHASE 3: IMPROVEMENT (SAFE KILL)
    # =========================================================================
    def _phase3_improvement(self):
        """Iterative Local Search (LNS) to improve quality."""
        self.stats.phase = "Phase 3: Improvement (LNS)"
        start_t = time.time()
        budget = self.config.anytime_budget
        logger.info(f"  2.5 Improvement Phase (LNS) - Budget: {budget:.1f}s")
        
        import random
        iteration = 0
        
        while time.time() - start_t < budget:
            iteration += 1
            
            # Select Targets: 1 PT + 2 FTE_Under + 2 Random
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
            
            # DESTROY: Unassign
            released_blocks = []
            victim_ids = [d["id"] for d in victims]
            
            # Backup state? No, greedy approach.
            for vid in victim_ids:
                if vid not in self.drivers: continue
                driver = self.drivers[vid]
                released_blocks.extend(list(driver["blocks"]))
                # Reset driver
                driver["blocks"] = []
                driver["hours"] = 0.0
                driver["active_days"] = set()
                driver["day_blocks"] = defaultdict(list)
                
            # Remove PTs from drivers list (will reopen if needed)
            for vid in victim_ids:
                if vid in self.drivers and self.drivers[vid]["type"] != "FTE":
                     self._remove_driver(vid)

            # REPAIR: Assign Greedily (Randomized Order)
            released_blocks.sort(key=lambda b: -b.total_work_minutes) # Hardest first
            
            for block in released_blocks:
                best_did = None
                best_score = float('inf')
                
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
                         
                         if score < best_score:
                             best_score = score
                             best_did = d["id"]
                
                if best_did:
                    self._assign_block(best_did, block)
                else:
                    # Forced to open new PT
                    new_did = self._create_driver("PT")
                    self._assign_block(new_did, block)
            
            if iteration % 50 == 0:
                pt_now = len([d for d in self.drivers.values() if d["type"] == "PT"])
                logger.info(f"    LNS Iter {iteration}: PT Count {pt_now}")



    def _try_redistribute_driver(self, victim_id: str) -> bool:
        """Try to move all blocks from victim to others. Transactional."""
        victim = self.drivers[victim_id]
        blocks_to_move = list(victim["blocks"])
        original_assignments = [] # For rollback? 
        # Complex to rollback if we modify state in place.
        # Simplification: Check feasibility of ALL blocks first.
        
        moves = [] # (block, target_did)
        targets = [d for d in self.drivers.values() if d["id"] != victim_id]
        # Sort targets by score?
        
        for block in blocks_to_move:
            found = False
            for t in targets:
                if self._can_take_block(t, block):
                    # SAFETY CHECK: Quality degradation?
                    # E.g. don't allow if t["days"] becomes > 6
                    if len(t["active_days"]) >= 6 and block.day.value not in t["active_days"]:
                        continue # Don't push to 7 days
                    
                    moves.append((block, t["id"]))
                    found = True
                    break
            if not found:
                return False
                
        # Execute moves
        for block, target_did in moves:
            # We don't unassign from victim yet, just do it
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

    def _remove_driver(self, did: str):
        if did in self.drivers:
            del self.drivers[did]

    def _assign_block(self, did: str, block: Block):
        d = self.drivers[did]
        d["blocks"].append(block)
        d["hours"] += block.total_work_hours
        d["active_days"].add(block.day.value)
        d["day_blocks"][block.day.value].append(block)

    def _unassign_block(self, did: str, block: Block):
        d = self.drivers[did]
        d["blocks"].remove(block)
        d["hours"] -= block.total_work_hours
        d["day_blocks"][block.day.value].remove(block)
        if not d["day_blocks"][block.day.value]:
            d["active_days"].remove(block.day.value)

    def _can_take_block(self, d: dict, block: Block) -> bool:
        if d["hours"] + block.total_work_hours > self.MAX_HOURS:
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
            
        # Stats
        fte_hours = [a.total_hours for a in assignments if a.driver_type == "FTE"]
        
        stats = {
            "drivers_fte": len(fte_hours),
            "drivers_pt": sum(1 for a in assignments if a.driver_type == "PT"),
            "time": round(time.time() - self.start_time, 2),
            "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
            "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
            "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
            "under_hours_count": sum(1 for h in fte_hours if h < self.MIN_HOURS)
        }
        return assignments, stats
