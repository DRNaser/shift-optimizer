"""
INSIGHTS INTERFACE - Rich Telemetry for Shift Optimizer
========================================================
Provides comprehensive insights, diagnostics, and real-time reporting
for portfolio-based optimization runs.

This is the recommended entry point for production use.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from time import perf_counter
from typing import Optional, Callable, Any

from src.domain.models import Tour, Block, Weekday
from src.services.instance_profiler import FeatureVector, compute_features
from src.services.policy_engine import PathSelection, ParameterBundle, ReasonCode
from src.services.portfolio_controller import (
    run_portfolio,
    PortfolioResult,
    generate_run_report,
    RunReport,
)

logger = logging.getLogger("Insights")


# =============================================================================
# INSIGHTS RESULT
# =============================================================================

@dataclass
class InsightsResult:
    """
    Rich result with full insights and diagnostics.
    """
    # Core result
    status: str
    total_drivers: int
    drivers_fte: int
    drivers_pt: int
    
    # Quality metrics
    lower_bound: int
    gap_to_lb_pct: float
    is_optimal: bool  # Gap <= 2%
    
    # Path info
    path_used: str
    path_reason: str
    fallback_used: bool
    
    # Early stop info
    early_stopped: bool
    early_stop_reason: str
    
    # Block mix
    blocks_total: int
    blocks_1er: int
    blocks_2er: int
    blocks_3er: int
    block_mix_score: float  # Higher = more multi-tour blocks
    
    # Driver hours distribution
    hours_min: float
    hours_max: float
    hours_avg: float
    hours_stddev: float
    under_40h_count: int
    over_53h_count: int
    
    # Timing
    runtime_s: float
    phase1_time_s: float
    phase2_time_s: float
    
    # Features (key subset)
    peakiness_index: float
    pool_pressure: str
    rest_risk: float
    
    # Full data (for detailed analysis)
    assignments: list = field(default_factory=list)
    features: Optional[FeatureVector] = None
    parameters: Optional[ParameterBundle] = None
    reason_codes: list = field(default_factory=list)
    
    def summary(self) -> str:
        """One-line summary for quick inspection."""
        return (
            f"[{self.status}] {self.total_drivers} drivers "
            f"({self.drivers_fte} FTE + {self.drivers_pt} PT) | "
            f"Gap: {self.gap_to_lb_pct:.1f}% | "
            f"Path: {self.path_used} | "
            f"Time: {self.runtime_s:.1f}s"
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "total_drivers": self.total_drivers,
            "drivers_fte": self.drivers_fte,
            "drivers_pt": self.drivers_pt,
            "lower_bound": self.lower_bound,
            "gap_to_lb_pct": round(self.gap_to_lb_pct, 2),
            "is_optimal": self.is_optimal,
            "path_used": self.path_used,
            "path_reason": self.path_reason,
            "fallback_used": self.fallback_used,
            "early_stopped": self.early_stopped,
            "early_stop_reason": self.early_stop_reason,
            "blocks_total": self.blocks_total,
            "blocks_1er": self.blocks_1er,
            "blocks_2er": self.blocks_2er,
            "blocks_3er": self.blocks_3er,
            "block_mix_score": round(self.block_mix_score, 2),
            "hours_min": round(self.hours_min, 1),
            "hours_max": round(self.hours_max, 1),
            "hours_avg": round(self.hours_avg, 1),
            "hours_stddev": round(self.hours_stddev, 1),
            "under_40h_count": self.under_40h_count,
            "over_53h_count": self.over_53h_count,
            "runtime_s": round(self.runtime_s, 2),
            "phase1_time_s": round(self.phase1_time_s, 2),
            "phase2_time_s": round(self.phase2_time_s, 2),
            "peakiness_index": round(self.peakiness_index, 3),
            "pool_pressure": self.pool_pressure,
            "rest_risk": round(self.rest_risk, 3),
            "reason_codes": self.reason_codes,
        }
    
    def print_report(self):
        """Print a formatted console report."""
        print("\n" + "=" * 70)
        print("SHIFT OPTIMIZER - INSIGHTS REPORT")
        print("=" * 70)
        print(f"\n{'Status:':<25} {self.status}")
        print(f"{'Path Used:':<25} {self.path_used} ({self.path_reason})")
        if self.fallback_used:
            print(f"{'Fallback:':<25} Yes")
        if self.early_stopped:
            print(f"{'Early Stop:':<25} {self.early_stop_reason}")
        
        print(f"\n{'-' * 70}")
        print("DRIVER SUMMARY")
        print(f"{'-' * 70}")
        print(f"{'Total Drivers:':<25} {self.total_drivers}")
        print(f"{'  FTE:':<25} {self.drivers_fte}")
        print(f"{'  PT:':<25} {self.drivers_pt}")
        print(f"{'Lower Bound:':<25} {self.lower_bound}")
        print(f"{'Gap to LB:':<25} {self.gap_to_lb_pct:.1f}% {'[OPTIMAL]' if self.is_optimal else ''}")
        
        print(f"\n{'-' * 70}")
        print("HOURS DISTRIBUTION")
        print(f"{'-' * 70}")
        print(f"{'Min / Avg / Max:':<25} {self.hours_min:.1f}h / {self.hours_avg:.1f}h / {self.hours_max:.1f}h")
        print(f"{'Std Dev:':<25} {self.hours_stddev:.1f}h")
        if self.under_40h_count > 0:
            print(f"{'Under 40h:':<25} {self.under_40h_count} ⚠️")
        if self.over_53h_count > 0:
            print(f"{'Over 53h:':<25} {self.over_53h_count} ⚠️")
        
        print(f"\n{'-' * 70}")
        print("BLOCK MIX")
        print(f"{'-' * 70}")
        print(f"{'Total Blocks:':<25} {self.blocks_total}")
        print(f"{'  1-tour:':<25} {self.blocks_1er} ({100*self.blocks_1er/max(1,self.blocks_total):.0f}%)")
        print(f"{'  2-tour:':<25} {self.blocks_2er} ({100*self.blocks_2er/max(1,self.blocks_total):.0f}%)")
        print(f"{'  3-tour:':<25} {self.blocks_3er} ({100*self.blocks_3er/max(1,self.blocks_total):.0f}%)")
        print(f"{'Mix Score:':<25} {self.block_mix_score:.2f} (higher = more multi-tour)")
        
        print(f"\n{'-' * 70}")
        print("INSTANCE FEATURES")
        print(f"{'-' * 70}")
        print(f"{'Peakiness:':<25} {self.peakiness_index:.2%}")
        print(f"{'Pool Pressure:':<25} {self.pool_pressure}")
        print(f"{'Rest Risk:':<25} {self.rest_risk:.2%}")
        
        print(f"\n{'-' * 70}")
        print("TIMING")
        print(f"{'-' * 70}")
        print(f"{'Total Runtime:':<25} {self.runtime_s:.1f}s")
        print(f"{'  Phase 1 (blocks):':<25} {self.phase1_time_s:.1f}s")
        print(f"{'  Phase 2 (assign):':<25} {self.phase2_time_s:.1f}s")
        
        print("\n" + "=" * 70 + "\n")


# =============================================================================
# MAIN INTERFACE
# =============================================================================

def solve_with_insights(
    tours: list[Tour],
    time_budget: float = 30.0,
    seed: int = 42,
    verbose: bool = True,
    report_path: Optional[str] = None,
) -> InsightsResult:
    """
    Solve forecast with full insights and diagnostics.
    
    This is the recommended entry point for production use.
    
    Args:
        tours: List of Tour objects
        time_budget: Time budget in seconds (default 30s)
        seed: Random seed for determinism
        verbose: Print progress to console
        report_path: Optional path to save JSON report
    
    Returns:
        InsightsResult with comprehensive metrics and diagnostics
    """
    def log(msg: str):
        if verbose:
            print(msg, flush=True)
    
    log("=" * 70)
    log(f"SHIFT OPTIMIZER - Portfolio Mode")
    log(f"Tours: {len(tours)} | Budget: {time_budget}s | Seed: {seed}")
    log("=" * 70)
    
    # Run portfolio optimization
    result = run_portfolio(
        tours=tours,
        time_budget=time_budget,
        seed=seed,
        log_fn=log if verbose else None,
    )
    
    # Extract assignments
    assignments = result.solution.assignments if result.solution else []
    
    # Calculate hours stats
    fte_hours = [a.total_hours for a in assignments if a.driver_type == "FTE"]
    all_hours = [a.total_hours for a in assignments]
    
    if all_hours:
        hours_avg = sum(all_hours) / len(all_hours)
        hours_stddev = (sum((h - hours_avg) ** 2 for h in all_hours) / len(all_hours)) ** 0.5
    else:
        hours_avg = 0.0
        hours_stddev = 0.0
    
    # Calculate block mix from assignments
    blocks_in_solution = []
    for a in assignments:
        blocks_in_solution.extend(a.blocks)
    
    blocks_1er = sum(1 for b in blocks_in_solution if len(b.tours) == 1)
    blocks_2er = sum(1 for b in blocks_in_solution if len(b.tours) == 2)
    blocks_3er = sum(1 for b in blocks_in_solution if len(b.tours) == 3)
    blocks_total = len(blocks_in_solution)
    
    # Block mix score: weighted average (1er=1, 2er=2, 3er=3) normalized
    if blocks_total > 0:
        block_mix_score = (blocks_1er * 1 + blocks_2er * 2 + blocks_3er * 3) / blocks_total
    else:
        block_mix_score = 0.0
    
    # Build insights result
    insights = InsightsResult(
        status=result.solution.status if result.solution else "FAILED",
        total_drivers=len(assignments),
        drivers_fte=len([a for a in assignments if a.driver_type == "FTE"]),
        drivers_pt=len([a for a in assignments if a.driver_type == "PT"]),
        
        lower_bound=result.lower_bound,
        gap_to_lb_pct=result.gap_to_lb * 100,
        is_optimal=result.gap_to_lb <= 0.02,
        
        path_used=result.final_path.value if result.final_path else "UNKNOWN",
        path_reason=result.reason_codes[0] if result.reason_codes else "",
        fallback_used=result.fallback_used,
        
        early_stopped=result.early_stopped,
        early_stop_reason=result.early_stop_reason,
        
        blocks_total=blocks_total,
        blocks_1er=blocks_1er,
        blocks_2er=blocks_2er,
        blocks_3er=blocks_3er,
        block_mix_score=block_mix_score,
        
        hours_min=min(all_hours) if all_hours else 0.0,
        hours_max=max(all_hours) if all_hours else 0.0,
        hours_avg=hours_avg,
        hours_stddev=hours_stddev,
        under_40h_count=sum(1 for h in fte_hours if h < 40.0),
        over_53h_count=sum(1 for h in fte_hours if h > 53.0),
        
        runtime_s=result.total_runtime_s,
        phase1_time_s=result.phase1_time_s,
        phase2_time_s=result.phase2_time_s,
        
        peakiness_index=result.features.peakiness_index if result.features else 0.0,
        pool_pressure=result.features.pool_pressure if result.features else "UNKNOWN",
        rest_risk=result.features.rest_risk_proxy if result.features else 0.0,
        
        assignments=assignments,
        features=result.features,
        parameters=result.parameters_used,
        reason_codes=result.reason_codes,
    )
    
    # Print report if verbose
    if verbose:
        insights.print_report()
    
    # Save JSON report if path provided
    if report_path:
        report = generate_run_report(result, tours, report_path)
        log(f"Report saved to: {report_path}")
    
    return insights


# =============================================================================
# DAY-BY-DAY ANALYSIS
# =============================================================================

def analyze_by_day(insights: InsightsResult) -> dict[str, dict]:
    """
    Analyze solution by day.
    
    Returns dict with per-day metrics:
    - tours_count
    - blocks_count
    - drivers_required (unique)
    - peak_concurrent
    """
    day_stats = {}
    
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
        day_blocks = []
        day_drivers = set()
        
        for a in insights.assignments:
            for block in a.blocks:
                if block.day.value == day:
                    day_blocks.append(block)
                    day_drivers.add(a.driver_id)
        
        day_stats[day] = {
            "blocks_count": len(day_blocks),
            "drivers_required": len(day_drivers),
            "tours_count": sum(len(b.tours) for b in day_blocks),
            "hours_total": sum(b.total_work_hours for b in day_blocks),
        }
    
    return day_stats


def print_day_analysis(insights: InsightsResult):
    """Print day-by-day analysis table."""
    stats = analyze_by_day(insights)
    
    print("\n" + "=" * 70)
    print("DAY-BY-DAY ANALYSIS")
    print("=" * 70)
    print(f"{'Day':<8} {'Tours':<8} {'Blocks':<8} {'Drivers':<10} {'Hours':<8}")
    print("-" * 70)
    
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
        s = stats[day]
        print(f"{day:<8} {s['tours_count']:<8} {s['blocks_count']:<8} {s['drivers_required']:<10} {s['hours_total']:.1f}")
    
    print("=" * 70 + "\n")


# =============================================================================
# DRIVER ANALYSIS
# =============================================================================

def analyze_drivers(insights: InsightsResult) -> list[dict]:
    """
    Analyze each driver in the solution.
    
    Returns list of driver stats sorted by hours.
    """
    driver_stats = []
    
    for a in insights.assignments:
        days_worked = len(set(b.day.value for b in a.blocks))
        blocks_count = len(a.blocks)
        tours_count = sum(len(b.tours) for b in a.blocks)
        
        driver_stats.append({
            "driver_id": a.driver_id,
            "type": a.driver_type,
            "hours": a.total_hours,
            "days_worked": days_worked,
            "blocks": blocks_count,
            "tours": tours_count,
            "hours_per_day": a.total_hours / days_worked if days_worked > 0 else 0,
        })
    
    # Sort by type (FTE first) then hours descending
    driver_stats.sort(key=lambda x: (0 if x["type"] == "FTE" else 1, -x["hours"]))
    
    return driver_stats


def print_driver_summary(insights: InsightsResult, top_n: int = 10):
    """Print top/bottom drivers summary."""
    stats = analyze_drivers(insights)
    
    print("\n" + "=" * 70)
    print("DRIVER SUMMARY (Top & Bottom)")
    print("=" * 70)
    print(f"{'ID':<12} {'Type':<6} {'Hours':<8} {'Days':<6} {'Blocks':<8} {'Tours':<6}")
    print("-" * 70)
    
    # Top N
    for s in stats[:top_n]:
        print(f"{s['driver_id']:<12} {s['type']:<6} {s['hours']:.1f}{'h':<5} {s['days_worked']:<6} {s['blocks']:<8} {s['tours']:<6}")
    
    if len(stats) > top_n * 2:
        print("...")
    
    # Bottom N
    for s in stats[-top_n:]:
        flag = "⚠️" if s["type"] == "FTE" and s["hours"] < 40 else ""
        print(f"{s['driver_id']:<12} {s['type']:<6} {s['hours']:.1f}{'h':<5} {s['days_worked']:<6} {s['blocks']:<8} {s['tours']:<6} {flag}")
    
    print("=" * 70 + "\n")


# =============================================================================
# COMPARISON HELPER
# =============================================================================

def compare_runs(run1: InsightsResult, run2: InsightsResult, labels: tuple = ("Run 1", "Run 2")):
    """Compare two optimization runs."""
    print("\n" + "=" * 70)
    print("RUN COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<25} {labels[0]:<20} {labels[1]:<20} {'Δ':<10}")
    print("-" * 70)
    
    metrics = [
        ("Total Drivers", run1.total_drivers, run2.total_drivers),
        ("FTE Drivers", run1.drivers_fte, run2.drivers_fte),
        ("PT Drivers", run1.drivers_pt, run2.drivers_pt),
        ("Gap to LB (%)", run1.gap_to_lb_pct, run2.gap_to_lb_pct),
        ("Block Mix Score", run1.block_mix_score, run2.block_mix_score),
        ("Runtime (s)", run1.runtime_s, run2.runtime_s),
    ]
    
    for name, v1, v2 in metrics:
        delta = v2 - v1
        delta_str = f"{delta:+.1f}" if isinstance(v1, float) else f"{delta:+d}"
        arrow = "↓" if delta < 0 else ("↑" if delta > 0 else "=")
        print(f"{name:<25} {str(v1):<20} {str(v2):<20} {delta_str} {arrow}")
    
    print("=" * 70 + "\n")
