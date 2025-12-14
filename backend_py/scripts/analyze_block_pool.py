#!/usr/bin/env python3
"""
BLOCK POOL ANALYZER
===================
Analyze the block builder output to identify coverage bottlenecks.

Usage:
    python scripts/analyze_block_pool.py --tours data/tours.csv
    python scripts/analyze_block_pool.py --tours data/tours.json --output block_pool_report.json
    
Outputs:
    block_pool_report.json - Detailed analysis of block generation
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.models import Tour, Weekday
from src.domain.constraints import HARD_CONSTRAINTS
from src.services.block_builder import (
    BlockBuilder,
    build_all_possible_blocks,
    build_blocks_greedy,
    tours_can_combine
)


def load_tours(filepath: str) -> list[Tour]:
    """Load tours from CSV or JSON."""
    if filepath.endswith('.csv'):
        import csv
        tours = []
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tour_id = row.get('id') or row.get('tour_id') or row.get('ID')
                day_str = row.get('day') or row.get('weekday') or row.get('Day')
                start_str = row.get('start_time') or row.get('start') or row.get('Start')
                end_str = row.get('end_time') or row.get('end') or row.get('End')
                
                day_map = {
                    'mon': Weekday.MONDAY, 'monday': Weekday.MONDAY,
                    'tue': Weekday.TUESDAY, 'tuesday': Weekday.TUESDAY,
                    'wed': Weekday.WEDNESDAY, 'wednesday': Weekday.WEDNESDAY,
                    'thu': Weekday.THURSDAY, 'thursday': Weekday.THURSDAY,
                    'fri': Weekday.FRIDAY, 'friday': Weekday.FRIDAY,
                    'sat': Weekday.SATURDAY, 'saturday': Weekday.SATURDAY,
                    'sun': Weekday.SUNDAY, 'sunday': Weekday.SUNDAY,
                }
                day = day_map.get(day_str.lower().strip(), Weekday.MONDAY)
                
                def parse_time(s):
                    s = s.strip()
                    if ':' in s:
                        parts = s.split(':')
                        return time(int(parts[0]), int(parts[1]))
                    return time(int(s), 0)
                
                tours.append(Tour(
                    id=tour_id.strip(),
                    day=day,
                    start_time=parse_time(start_str),
                    end_time=parse_time(end_str)
                ))
        return tours
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        tours = []
        items = data if isinstance(data, list) else data.get('tours', [])
        
        for item in items:
            day_str = item.get('day', 'Mon')
            day_map = {v.value: v for v in Weekday}
            day = day_map.get(day_str, Weekday.MONDAY)
            
            start = item.get('start_time', '08:00')
            end = item.get('end_time', '12:00')
            
            def parse_time(s):
                if isinstance(s, str) and ':' in s:
                    parts = s.split(':')
                    return time(int(parts[0]), int(parts[1]))
                return time(8, 0)
            
            tours.append(Tour(
                id=item.get('id', f"T{len(tours)+1}"),
                day=day,
                start_time=parse_time(start),
                end_time=parse_time(end)
            ))
        
        return tours


def analyze_combination_potential(tours: list[Tour]) -> dict:
    """Analyze why tours can/cannot combine."""
    tours_by_day = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    total_pairs = 0
    combinable_pairs = 0
    rejection_reasons = defaultdict(int)
    near_misses = []
    
    for day, day_tours in tours_by_day.items():
        day_tours.sort(key=lambda t: t.start_time)
        
        for i, t1 in enumerate(day_tours):
            for t2 in day_tours[i + 1:]:
                total_pairs += 1
                
                # Calculate gap
                t1_end = t1.end_time.hour * 60 + t1.end_time.minute
                t2_start = t2.start_time.hour * 60 + t2.start_time.minute
                gap_minutes = t2_start - t1_end
                
                if tours_can_combine(t1, t2):
                    combinable_pairs += 1
                else:
                    # Determine reason
                    if gap_minutes < 0:
                        rejection_reasons["overlap"] += 1
                    elif gap_minutes < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
                        rejection_reasons["gap_too_small"] += 1
                        if gap_minutes >= HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS - 10:
                            near_misses.append({
                                "tour1": t1.id, "tour2": t2.id,
                                "gap": gap_minutes,
                                "needed": HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS,
                                "reason": "gap_too_small"
                            })
                    elif gap_minutes > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS:
                        rejection_reasons["gap_too_large"] += 1
                        if gap_minutes <= HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS + 30:
                            near_misses.append({
                                "tour1": t1.id, "tour2": t2.id,
                                "gap": gap_minutes,
                                "max": HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS,
                                "reason": "gap_too_large"
                            })
    
    return {
        "total_pairs": total_pairs,
        "combinable_pairs": combinable_pairs,
        "combination_rate": round(combinable_pairs / total_pairs, 4) if total_pairs else 0,
        "rejection_reasons": dict(rejection_reasons),
        "near_misses_sample": near_misses[:20]
    }


def analyze_block_pool(tours: list[Tour]) -> dict:
    """Full analysis of block generation."""
    print(f"\nAnalyzing {len(tours)} tours...")
    
    # Build all possible blocks
    all_blocks = build_all_possible_blocks(tours)
    greedy_blocks = build_blocks_greedy(tours, prefer_larger=True)
    
    # Count by type
    blocks_by_type = {
        "1er": sum(1 for b in all_blocks if len(b.tours) == 1),
        "2er": sum(1 for b in all_blocks if len(b.tours) == 2),
        "3er": sum(1 for b in all_blocks if len(b.tours) == 3),
    }
    
    greedy_by_type = {
        "1er": sum(1 for b in greedy_blocks if len(b.tours) == 1),
        "2er": sum(1 for b in greedy_blocks if len(b.tours) == 2),
        "3er": sum(1 for b in greedy_blocks if len(b.tours) == 3),
    }
    
    # Per-tour coverage
    tour_block_count: dict[str, int] = {t.id: 0 for t in tours}
    for block in all_blocks:
        for tour in block.tours:
            tour_block_count[tour.id] += 1
    
    # Find tours with 0 blocks (should be none if singles are generated)
    zero_block_tours = [tid for tid, cnt in tour_block_count.items() if cnt == 0]
    
    # Find tours with limited options
    low_option_tours = [
        {"tour_id": tid, "block_count": cnt}
        for tid, cnt in sorted(tour_block_count.items(), key=lambda x: x[1])
        if cnt <= 3  # Very limited options
    ][:20]
    
    # Distribution by day
    tours_per_day = defaultdict(int)
    blocks_per_day = defaultdict(int)
    for tour in tours:
        tours_per_day[tour.day.value] += 1
    for block in all_blocks:
        blocks_per_day[block.day.value] += 1
    
    # Combination analysis
    combination_analysis = analyze_combination_potential(tours)
    
    # Build report
    report = {
        "summary": {
            "total_tours": len(tours),
            "total_blocks_possible": len(all_blocks),
            "blocks_by_type": blocks_by_type,
            "greedy_solution_blocks": len(greedy_blocks),
            "greedy_by_type": greedy_by_type,
            "tours_with_zero_blocks": len(zero_block_tours),
            "avg_blocks_per_tour": round(sum(tour_block_count.values()) / len(tours), 2) if tours else 0
        },
        "distribution_by_day": {
            "tours": dict(tours_per_day),
            "blocks": dict(blocks_per_day)
        },
        "coverage_issues": {
            "zero_block_tours": zero_block_tours,
            "low_option_tours": low_option_tours
        },
        "combination_analysis": combination_analysis,
        "constraints_used": {
            "MIN_PAUSE_BETWEEN_TOURS": HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS,
            "MAX_PAUSE_BETWEEN_TOURS": HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS,
            "MAX_DAILY_SPAN_HOURS": HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
            "MAX_TOURS_PER_DAY": HARD_CONSTRAINTS.MAX_TOURS_PER_DAY
        }
    }
    
    return report


def main():
    parser = argparse.ArgumentParser(description="Block Pool Analyzer")
    parser.add_argument("--tours", required=True, help="Path to tours file (CSV or JSON)")
    parser.add_argument("--output", default="block_pool_report.json", help="Output file path")
    args = parser.parse_args()
    
    # Load tours
    tours = load_tours(args.tours)
    print(f"Loaded {len(tours)} tours from {args.tours}")
    
    # Analyze
    report = analyze_block_pool(tours)
    
    # Write report
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'='*50}")
    print("BLOCK POOL ANALYSIS SUMMARY")
    print(f"{'='*50}")
    print(f"Tours: {report['summary']['total_tours']}")
    print(f"Blocks Possible: {report['summary']['total_blocks_possible']}")
    print(f"  3er: {report['summary']['blocks_by_type']['3er']}")
    print(f"  2er: {report['summary']['blocks_by_type']['2er']}")
    print(f"  1er: {report['summary']['blocks_by_type']['1er']}")
    print(f"\nGreedy Solution:")
    print(f"  Total Blocks: {report['summary']['greedy_solution_blocks']}")
    print(f"  3er: {report['summary']['greedy_by_type']['3er']}")
    print(f"  2er: {report['summary']['greedy_by_type']['2er']}")
    print(f"  1er: {report['summary']['greedy_by_type']['1er']}")
    print(f"\nCoverage Issues:")
    print(f"  Tours with 0 blocks: {len(report['coverage_issues']['zero_block_tours'])}")
    print(f"  Tours with <=3 options: {len(report['coverage_issues']['low_option_tours'])}")
    print(f"\nCombination Analysis:")
    print(f"  Total pairs: {report['combination_analysis']['total_pairs']}")
    print(f"  Combinable: {report['combination_analysis']['combinable_pairs']} ({report['combination_analysis']['combination_rate']*100:.1f}%)")
    if report['combination_analysis']['rejection_reasons']:
        print(f"  Rejections: {report['combination_analysis']['rejection_reasons']}")
    print(f"\n[OK] Full report written to: {args.output}")


if __name__ == "__main__":
    main()
