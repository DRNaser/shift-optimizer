import sys
from pathlib import Path
import random
import json
import time
from collections import defaultdict
from dataclasses import dataclass, asdict

# Add backend path
sys.path.insert(0, str(Path(__file__).parent / "backend_py"))

from test_forecast_csv import parse_forecast_csv
from src.services.smart_block_builder import Block, BlockGenOverrides
from src.domain.models import Tour

@dataclass
class PartitionStat:
    seed: int
    peak_blocks: int
    total_blocks: int
    block_mix: dict
    
    def to_dict(self):
        return asdict(self)

def randomized_partition(tours: list[Tour], seed: int, overrides: BlockGenOverrides):
    random.seed(seed)
    
    tours_by_day = defaultdict(list)
    for t in tours:
        tours_by_day[t.day].append(t)
        
    final_blocks = []
    
    # Pre-define helper functions to strict specs
    def calc_gap(t1, t2):
        e = t1.end_time.hour*60 + t1.end_time.minute
        s = t2.start_time.hour*60 + t2.start_time.minute
        return s - e
    def is_reg(gap): return 30 <= gap <= 60
    def is_split(gap): return gap == 360
    
    for day, day_tours in tours_by_day.items():
        # Sort by start_time to keep structure
        day_tours.sort(key=lambda t: t.start_time)
        active_tours = set(t.id for t in day_tours)
        
        def mark_used(ts): 
            for t in ts: active_tours.remove(t.id)

        # 3er Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            
            for i in range(len(curr)):
                t1 = curr[i]
                candidates_t2 = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g) or is_split(g):
                        candidates_t2.append(t2)
                
                if not candidates_t2: continue
                random.shuffle(candidates_t2) # Randomize choice
                
                for t2 in candidates_t2:
                    # Find t3
                    candidates_t3 = []
                    for t3 in curr:
                        if t3.start_time <= t2.end_time: continue 
                        g2 = calc_gap(t2, t3)
                        if is_reg(g2) or is_split(g2):
                            span = (t3.end_time.hour*60+t3.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                            if span <= 16*60:
                                candidates_t3.append(t3)
                                
                    if candidates_t3:
                        t3 = random.choice(candidates_t3) # Randomize choice
                        blk = Block(id=f"B3-{t1.id}", day=day, tours=[t1, t2, t3])
                        final_blocks.append(blk)
                        mark_used([t1, t2, t3])
                        found = True
                        break 
                if found: break 
            if not found: break
            
        # 2er Regular Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_reg(g):
                        span = (t2.end_time.hour*60+t2.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                        if span <= 14*60:
                            cands.append(t2)
                if cands:
                    t2 = random.choice(cands)
                    blk = Block(id=f"B2R-{t1.id}", day=day, tours=[t1, t2])
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found: break
            
        # 2er Split Loop
        while True:
            found = False
            curr = [t for t in day_tours if t.id in active_tours]
            for i in range(len(curr)):
                t1 = curr[i]
                cands = []
                for j in range(i+1, len(curr)):
                    t2 = curr[j]
                    g = calc_gap(t1, t2)
                    if is_split(g):
                        span = (t2.end_time.hour*60+t2.end_time.minute) - (t1.start_time.hour*60+t1.start_time.minute)
                        if span <= 16*60:
                            cands.append(t2)
                if cands:
                    t2 = random.choice(cands)
                    blk = Block(id=f"B2S-{t1.id}", day=day, tours=[t1, t2])
                    final_blocks.append(blk)
                    mark_used([t1, t2])
                    found = True
                    break
            if not found: break

        # 1er Remaining
        curr_day_tours = [t for t in day_tours if t.id in active_tours]
        for t in curr_day_tours:
            blk = Block(id=f"B1-{t.id}", day=day, tours=[t])
            final_blocks.append(blk)
            active_tours.remove(t.id) 
            
    return final_blocks

def main():
    iterations = 200
    print(f"Running Systematized Partition Search ({iterations} iterations)...")
    
    input_file = Path(__file__).parent / "forecast_kw51.csv"
    print(f"Loading {input_file}...")
        
    tours = parse_forecast_csv(str(input_file))
    
    overrides = BlockGenOverrides(
        max_pause_regular_minutes=60,
        split_pause_min_minutes=360,
        split_pause_max_minutes=360,
        max_daily_span_hours=16.0,
        enable_split_blocks=True
    )
    
    stats = []
    
    start_time = time.time()
    for i in range(iterations):
        blks = randomized_partition(tours, i, overrides)
        
        # Analyze
        day_counts = defaultdict(int)
        mix = defaultdict(int)
        for b in blks:
            day_counts[b.day] += 1
            mix[f"{len(b.tours)}er"] += 1
            
        peak = max(day_counts.values())
        
        stat = PartitionStat(
            seed=i,
            peak_blocks=peak,
            total_blocks=len(blks),
            block_mix=dict(mix)
        )
        stats.append(stat)
        
        if (i+1) % 50 == 0:
            print(f"Processed {i+1}/{iterations}...")

    duration = time.time() - start_time
    print(f"Sweep complete in {duration:.2f}s")
    
    # Sort: Peak Asc -> 3er Count Desc -> Total Blocks Asc
    stats.sort(key=lambda s: (s.peak_blocks, -s.block_mix.get('3er', 0), s.total_blocks))
    
    print("\nTop 5 Seeds:")
    for i in range(5):
        s = stats[i]
        print(f"Rank {i+1}: Seed {s.seed} | Peak {s.peak_blocks} | 3er {s.block_mix.get('3er',0)} | Total {s.total_blocks}")
        
    # Save best
    best = stats[0]
    output_file = Path(__file__).parent / "partition_stats.json"
    with open(output_file, "w") as f:
        json.dump([s.to_dict() for s in stats[:20]], f, indent=2)
        
    print(f"Top 20 stats saved to {output_file}")
    print(f"Recommended Seed: {best.seed}")

if __name__ == "__main__":
    main()
