"""
Utilization Report Generator - Mandatory Output Artifact

Generates comprehensive utilization analysis for driver solutions:
- Hour distribution (buckets, histograms, percentiles)
- Fairness metrics (StdDev, Gini)
- Structure metrics (driver-days, tours/driver, idle time)
- Low-hour roster identification

Outputs:
- utilization_rosters.csv (detailed per-driver)
- utilization_summary.json (aggregated KPIs)
"""

import json
import csv
from pathlib import Path
from collections import defaultdict
from typing import List, Dict
import statistics


def compute_gini_coefficient(values: List[float]) -> float:
    """
    Compute Gini coefficient for fairness measurement.
    0 = perfect equality, 1 = maximum inequality
    """
    if not values or len(values) < 2:
        return 0.0
    
    sorted_values = sorted(values)
    n = len(sorted_values)
    cum_values = 0
    
    for i, val in enumerate(sorted_values):
        cum_values += (2 * (i + 1) - n - 1) * val
    
    return cum_values / (n * sum(sorted_values)) if sum(sorted_values) > 0 else 0.0


def compute_idle_minutes(blocks) -> float:
    """
    Compute total idle minutes (gaps between tours) for a driver.
    """
    if not blocks or len(blocks) <= 1:
        return 0.0
    
    # Sort blocks by day and start time
    sorted_blocks = sorted(blocks, key=lambda b: (b.day.value, b.first_start))
    
    total_idle = 0.0
    for i in range(len(sorted_blocks) - 1):
        curr = sorted_blocks[i]
        next_b = sorted_blocks[i + 1]
        
        # Only count gaps within the same day
        if curr.day.value == next_b.day.value:
            # Gap = next_start - curr_end
            curr_end_min = curr.last_end.hour * 60 + curr.last_end.minute
            next_start_min = next_b.first_start.hour * 60 + next_b.first_start.minute
            gap = next_start_min - curr_end_min
            if gap > 0:
                total_idle += gap
    
    return total_idle


def generate_utilization_report(
    assignments: list,
    output_dir: Path,
    scenario_name: str = "KW51"
):
    """
    Generate mandatory utilization report artifacts.
    
    Args:
        assignments: List of DriverAssignment objects
        output_dir: Directory to save output files
        scenario_name: Name of scenario (for file naming)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # =========================================================================
    # A) DISTRIBUTION ANALYSIS
    # =========================================================================
    
    # Collect hours per driver
    hours_list = [a.total_hours for a in assignments if hasattr(a, 'total_hours')]
    
    if not hours_list:
        print("[WARN] No driver hours found, skipping utilization report")
        return
    
    # Buckets
    buckets = {
        "0-10": 0,
        "10-20": 0,
        "20-30": 0,
        "30-40": 0,
        "40-55": 0,
        "55+": 0
    }
    
    for h in hours_list:
        if h < 10:
            buckets["0-10"] += 1
        elif h < 20:
            buckets["10-20"] += 1
        elif h < 30:
            buckets["20-30"] += 1
        elif h < 40:
            buckets["30-40"] += 1
        elif h < 55:
            buckets["40-55"] += 1
        else:
            buckets["55+"] += 1
    
    # Percentiles
    sorted_hours = sorted(hours_list)
    n = len(sorted_hours)
    
    def percentile(p):
        idx = int(n * p / 100)
        return sorted_hours[min(idx, n - 1)]
    
    p10 = percentile(10)
    p25 = percentile(25)
    p50 = percentile(50)  # median
    p75 = percentile(75)
    p90 = percentile(90)
    
    # Percentages
    pct_under_30 = sum(1 for h in hours_list if h < 30) / len(hours_list) * 100
    pct_under_35 = sum(1 for h in hours_list if h < 35) / len(hours_list) * 100
    pct_gte_40 = sum(1 for h in hours_list if h >= 40) / len(hours_list) * 100
    pct_gte_45 = sum(1 for h in hours_list if h >= 45) / len(hours_list) * 100
    
    # Fairness
    mean_hours = statistics.mean(hours_list)
    stddev_hours = statistics.stdev(hours_list) if len(hours_list) > 1 else 0.0
    gini = compute_gini_coefficient(hours_list)
    
    # =========================================================================
    # B) STRUCTURE ANALYSIS
    # =========================================================================
    
    # Driver-days used per day
    driver_days_per_day = defaultdict(set)
    tours_per_driver = []
    days_per_driver = []
    idle_minutes_per_driver = []
    
    for a in assignments:
        # Days worked
        days_worked = set()
        for block in a.blocks:
            day_val = block.day.value if hasattr(block.day, 'value') else str(block.day)
            days_worked.add(day_val)
            driver_days_per_day[day_val].add(a.driver_id)
        
        days_per_driver.append(len(days_worked))
        
        # Tours (sum of tours in all blocks)
        total_tours = sum(len(b.tours) for b in a.blocks)
        tours_per_driver.append(total_tours)
        
        # Idle minutes
        idle_min = compute_idle_minutes(a.blocks)
        idle_minutes_per_driver.append(idle_min)
    
    driver_days_counts = {day: len(drivers) for day, drivers in driver_days_per_day.items()}
    
    # =========================================================================
    # C) TOP-20 LOW-HOUR ROSTERS
    # =========================================================================
    
    low_hour_rosters = sorted(
        [(a.driver_id, a.total_hours, len(a.blocks), sum(len(b.tours) for b in a.blocks)) 
         for a in assignments],
        key=lambda x: x[1]  # Sort by hours ascending
    )[:20]
    
    # =========================================================================
    # OUTPUT: utilization_summary.json
    # =========================================================================
    
    summary = {
        "scenario": scenario_name,
        "drivers_total": len(assignments),
        
        "distribution": {
            "buckets": buckets,
            "mean_hours": round(mean_hours, 2),
            "median_hours": round(p50, 2),
            "stddev_hours": round(stddev_hours, 2),
            "min_hours": round(min(hours_list), 2),
            "max_hours": round(max(hours_list), 2),
            "p10": round(p10, 2),
            "p25": round(p25, 2),
            "p75": round(p75, 2),
            "p90": round(p90, 2),
        },
        
        "percentages": {
            "pct_under_30h": round(pct_under_30, 1),
            "pct_under_35h": round(pct_under_35, 1),
            "pct_gte_40h": round(pct_gte_40, 1),
            "pct_gte_45h": round(pct_gte_45, 1),
        },
        
        "fairness": {
            "gini_coefficient": round(gini, 3),
            "stddev_hours": round(stddev_hours, 2),
        },
        
        "structure": {
            "driver_days_per_day": driver_days_counts,
            "avg_tours_per_driver": round(statistics.mean(tours_per_driver), 2) if tours_per_driver else 0,
            "avg_days_per_driver": round(statistics.mean(days_per_driver), 2) if days_per_driver else 0,
            "avg_idle_minutes_per_driver": round(statistics.mean(idle_minutes_per_driver), 1) if idle_minutes_per_driver else 0,
        },
        
        "low_hour_rosters_top20": [
            {"driver_id": did, "hours": h, "blocks": b, "tours": t}
            for did, h, b, t in low_hour_rosters
        ]
    }
    
    summary_file = output_dir / f"utilization_summary_{scenario_name}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n[UTILIZATION] Summary saved to: {summary_file}")
    
    # =========================================================================
    # OUTPUT: utilization_rosters.csv
    # =========================================================================
    
    roster_rows = []
    for a in assignments:
        days_worked = set(b.day.value if hasattr(b.day, 'value') else str(b.day) for b in a.blocks)
        total_tours = sum(len(b.tours) for b in a.blocks)
        idle_min = compute_idle_minutes(a.blocks)
        
        roster_rows.append({
            "driver_id": a.driver_id,
            "driver_type": a.driver_type if hasattr(a, 'driver_type') else "UNKNOWN",
            "total_hours": round(a.total_hours, 2),
            "num_blocks": len(a.blocks),
            "num_tours": total_tours,
            "num_days": len(days_worked),
            "days_worked": ",".join(sorted(days_worked)),
            "idle_minutes": round(idle_min, 1),
        })
    
    csv_file = output_dir / f"utilization_rosters_{scenario_name}.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "driver_id", "driver_type", "total_hours", "num_blocks", 
            "num_tours", "num_days", "days_worked", "idle_minutes"
        ])
        writer.writeheader()
        writer.writerows(roster_rows)
    
    print(f"[UTILIZATION] Roster details saved to: {csv_file}")
    
    # =========================================================================
    # CONSOLE OUTPUT (Quick Summary)
    # =========================================================================
    
    print(f"\n{'='*70}")
    print(f"UTILIZATION REPORT: {scenario_name}")
    print(f"{'='*70}")
    print(f"Drivers: {len(assignments)}")
    print(f"Average Hours: {mean_hours:.1f}h (StdDev: {stddev_hours:.1f}h)")
    print(f"Median Hours: {p50:.1f}h")
    print(f"Range: {min(hours_list):.1f}h - {max(hours_list):.1f}h")
    print(f"\nDistribution:")
    for bucket, count in buckets.items():
        pct = count / len(assignments) * 100
        print(f"  {bucket}h: {count:3d} drivers ({pct:5.1f}%)")
    print(f"\nQuality Gates:")
    print(f"  <30h: {pct_under_30:5.1f}% ⚠️" if pct_under_30 > 20 else f"  <30h: {pct_under_30:5.1f}% ✓")
    print(f"  ≥40h: {pct_gte_40:5.1f}% ⚠️" if pct_gte_40 < 50 else f"  ≥40h: {pct_gte_40:5.1f}% ✓")
    print(f"\nFairness:")
    print(f"  Gini: {gini:.3f} ({'HIGH' if gini > 0.3 else 'OK'})")
    print(f"  StdDev: {stddev_hours:.1f}h")
    print(f"\nTop-5 Low-Hour Rosters:")
    for did, h, b, t in low_hour_rosters[:5]:
        print(f"  {did}: {h:.1f}h ({t} tours, {b} blocks)")
    print(f"{'='*70}\n")
    
    return summary_file, csv_file
