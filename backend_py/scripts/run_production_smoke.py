#!/usr/bin/env python3
"""
PRODUCTION SMOKE TEST RUNNER
============================
Validates CP-SAT Solver v3 on real data with multiple scenarios.

Usage:
    python scripts/run_production_smoke.py --tours data/tours.csv --drivers data/drivers.csv
    python scripts/run_production_smoke.py --tours data/tours.json --drivers data/drivers.json
    
Outputs:
    artifacts/{timestamp}/run_A/  (10s time limit)
    artifacts/{timestamp}/run_B/  (120s time limit)
    artifacts/{timestamp}/run_C/  (stress test)
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.models import Tour, Driver, Weekday, BlockType
from src.services.cpsat_solver import CPSATScheduler, CPSATConfig, BlockingReason


# =============================================================================
# DATA LOADERS
# =============================================================================

def load_tours_csv(filepath: str) -> list[Tour]:
    """Load tours from CSV file."""
    import csv
    tours = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Flexible column names
            tour_id = row.get('id') or row.get('tour_id') or row.get('ID')
            day_str = row.get('day') or row.get('weekday') or row.get('Day')
            start_str = row.get('start_time') or row.get('start') or row.get('Start')
            end_str = row.get('end_time') or row.get('end') or row.get('End')
            location = row.get('location') or row.get('Location') or 'DEFAULT'
            
            # Parse day
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
            
            # Parse times
            from datetime import time
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
                end_time=parse_time(end_str),
                location=location.strip()
            ))
    
    return tours


def load_tours_json(filepath: str) -> list[Tour]:
    """Load tours from JSON file."""
    from datetime import time
    
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
            end_time=parse_time(end),
            location=item.get('location', 'DEFAULT')
        ))
    
    return tours


def load_drivers_csv(filepath: str) -> list[Driver]:
    """Load drivers from CSV file."""
    import csv
    drivers = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            driver_id = row.get('id') or row.get('driver_id') or row.get('ID')
            name = row.get('name') or row.get('Name') or driver_id
            
            # Parse qualifications
            quals_str = row.get('qualifications') or row.get('quals') or ''
            quals = [q.strip() for q in quals_str.split(',') if q.strip()]
            
            # Parse max hours
            max_hours = float(row.get('max_weekly_hours') or row.get('max_hours') or 48)
            
            # Parse available days
            avail_str = row.get('available_days') or ''
            if avail_str:
                avail = [Weekday(d.strip()) for d in avail_str.split(',') if d.strip()]
            else:
                avail = list(Weekday)
            
            drivers.append(Driver(
                id=driver_id.strip(),
                name=name.strip(),
                qualifications=quals,
                max_weekly_hours=max_hours,
                available_days=avail
            ))
    
    return drivers


def load_drivers_json(filepath: str) -> list[Driver]:
    """Load drivers from JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    drivers = []
    items = data if isinstance(data, list) else data.get('drivers', [])
    
    for item in items:
        avail = item.get('available_days', [d.value for d in Weekday])
        avail_days = [Weekday(d) for d in avail] if avail else list(Weekday)
        
        drivers.append(Driver(
            id=item.get('id', f"D{len(drivers)+1}"),
            name=item.get('name', f"Driver {len(drivers)+1}"),
            qualifications=item.get('qualifications', []),
            max_weekly_hours=float(item.get('max_weekly_hours', 48)),
            available_days=avail_days
        ))
    
    return drivers


def load_data(tours_path: str, drivers_path: str) -> tuple[list[Tour], list[Driver]]:
    """Load tours and drivers from file (CSV or JSON)."""
    # Load tours
    if tours_path.endswith('.csv'):
        tours = load_tours_csv(tours_path)
    else:
        tours = load_tours_json(tours_path)
    
    # Load drivers
    if drivers_path.endswith('.csv'):
        drivers = load_drivers_csv(drivers_path)
    else:
        drivers = load_drivers_json(drivers_path)
    
    return tours, drivers


# =============================================================================
# STATUS SEMANTICS
# =============================================================================

class SolveStatus:
    HARD_OK = "HARD_OK"
    SOFT_FALLBACK = "SOFT_FALLBACK"
    FAILED = "FAILED"


def determine_status(model, plan, expected_coverage: int) -> str:
    """Determine solve status with clear semantics."""
    if model.fallback_triggered:
        return SolveStatus.SOFT_FALLBACK
    
    if not model.using_hard_coverage:
        return SolveStatus.SOFT_FALLBACK
    
    if plan.stats.total_tours_assigned < expected_coverage:
        return SolveStatus.SOFT_FALLBACK
    
    if not plan.validation.is_valid:
        return SolveStatus.FAILED
    
    return SolveStatus.HARD_OK


# =============================================================================
# ENHANCED UNASSIGNED DIAGNOSTICS
# =============================================================================

def build_unassigned_diagnostics(model, plan) -> list[dict]:
    """Build enhanced diagnostics for each unassigned tour."""
    diagnostics = []
    
    for ut in plan.unassigned_tours:
        tour = ut.tour
        report = model.pre_solve_report.tour_reports.get(tour.id) if model.pre_solve_report else None
        
        # Count candidates
        blocks_for_tour = model.tour_to_blocks.get(tour.id, [])
        candidate_blocks = len(blocks_for_tour)
        
        # Count feasible drivers per block
        feasible_driver_count = 0
        top_blockers: dict[str, int] = {}
        
        for block in blocks_for_tour:
            for driver in model.drivers:
                ok, reason = model._check_assignment(block, driver)
                if ok:
                    feasible_driver_count += 1
                elif reason:
                    top_blockers[reason] = top_blockers.get(reason, 0) + 1
        
        # Determine flags
        has_any_blocks = candidate_blocks > 0
        has_any_feasible_driver = feasible_driver_count > 0
        is_globally_conflicting = has_any_feasible_driver and model.fallback_triggered
        
        # Determine reason
        if not has_any_blocks:
            reason_code = BlockingReason.NO_BLOCK_GENERATED
        elif not has_any_feasible_driver:
            # Use top blocker
            reason_code = max(top_blockers.keys(), key=lambda r: top_blockers[r]) if top_blockers else BlockingReason.DRIVER_UNAVAILABLE
        elif is_globally_conflicting:
            reason_code = BlockingReason.GLOBAL_INFEASIBLE
        else:
            reason_code = str(ut.reason_codes[0].value) if ut.reason_codes else "unknown"
        
        diagnostics.append({
            "tour_id": tour.id,
            "day": tour.day.value,
            "time": f"{tour.start_time.strftime('%H:%M')}-{tour.end_time.strftime('%H:%M')}",
            "reason_code": reason_code,
            "candidate_blocks_total": candidate_blocks,
            "candidate_drivers_total": feasible_driver_count,
            "top_blockers": [{"code": k, "count": v} for k, v in sorted(top_blockers.items(), key=lambda x: -x[1])[:5]],
            "has_any_blocks": has_any_blocks,
            "has_any_feasible_driver": has_any_feasible_driver,
            "is_globally_conflicting": is_globally_conflicting,
            "details": ut.details
        })
    
    return diagnostics


# =============================================================================
# RUN SCENARIO
# =============================================================================

def run_scenario(
    tours: list[Tour],
    drivers: list[Driver],
    config: CPSATConfig,
    output_dir: Path,
    scenario_name: str
) -> dict:
    """Run a single scenario and write all artifacts."""
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario_name}")
    print(f"Config: time_limit={config.time_limit_seconds}s, seed={config.seed}, workers={config.num_workers}")
    print(f"{'='*60}")
    
    # Run scheduler
    from src.services.cpsat_solver import CPSATSchedulerModel
    from ortools.sat.python import cp_model
    
    model = CPSATSchedulerModel(tours, drivers, config)
    
    if not model.pre_solve_report or not model.pre_solve_report.is_model_feasible:
        status = SolveStatus.FAILED
        plan = None
        solve_time = 0
    else:
        cp_status, solver = model.solve()
        solve_time = solver.WallTime()
        
        if cp_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            scheduler = CPSATScheduler(tours, drivers, config)
            plan = scheduler.schedule(date.today())
            status = determine_status(model, plan, len(model.coverable_tour_ids))
        else:
            plan = None
            status = SolveStatus.FAILED
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write pre_solve_report.json
    if model.pre_solve_report:
        with open(output_dir / "pre_solve_report.json", 'w') as f:
            json.dump(model.pre_solve_report.to_dict(), f, indent=2)
    
    # Write solve_report.json
    solve_report = {
        "scenario": scenario_name,
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "config": {
            "time_limit_seconds": config.time_limit_seconds,
            "seed": config.seed,
            "num_workers": config.num_workers,
            "fallback_enabled": config.fallback_to_soft
        },
        "timing": {
            "solve_time_seconds": round(solve_time, 2),
            "time_limit_hit": solve_time >= config.time_limit_seconds * 0.95
        },
        "input": {
            "tours_total": len(tours),
            "drivers_total": len(drivers),
            "coverable_tours": len(model.coverable_tour_ids) if model.pre_solve_report else 0
        },
        "output": {},
        "fallback_triggered": model.fallback_triggered,
        "used_hard_coverage": model.using_hard_coverage
    }
    
    if plan:
        solve_report["output"] = {
            "tours_assigned": plan.stats.total_tours_assigned,
            "tours_unassigned": plan.stats.total_tours_unassigned,
            "coverage_rate": round(plan.stats.total_tours_assigned / len(tours), 4) if tours else 0,
            "drivers_used": plan.stats.total_drivers,
            "blocks_triple": plan.stats.block_counts.get(BlockType.TRIPLE, 0),
            "blocks_double": plan.stats.block_counts.get(BlockType.DOUBLE, 0),
            "blocks_single": plan.stats.block_counts.get(BlockType.SINGLE, 0),
            "validation_ok": plan.validation.is_valid
        }
        
        # Hint tracking
        hints_used = sum(1 for k in model.hints_added if k in model.assignment)
        solve_report["hints"] = {
            "provided": len(model.hints_added),
            "used": hints_used,
            "effectiveness": round(hints_used / len(model.hints_added), 2) if model.hints_added else 0
        }
    
    with open(output_dir / "solve_report.json", 'w') as f:
        json.dump(solve_report, f, indent=2)
    
    # Write assignments.json
    if plan:
        assignments_data = []
        for a in plan.assignments:
            assignments_data.append({
                "driver_id": a.driver_id,
                "day": a.day.value,
                "block_id": a.block.id,
                "block_type": f"{len(a.block.tours)}er",
                "tours": [{"id": t.id, "time": f"{t.start_time.strftime('%H:%M')}-{t.end_time.strftime('%H:%M')}"} for t in a.block.tours],
                "total_hours": round(a.block.total_work_hours, 2),
                "span_hours": round(a.block.span_hours, 2)
            })
        
        with open(output_dir / "assignments.json", 'w') as f:
            json.dump(assignments_data, f, indent=2)
    
    # Write unassigned.json with enhanced diagnostics
    if plan:
        unassigned_data = build_unassigned_diagnostics(model, plan)
        with open(output_dir / "unassigned.json", 'w') as f:
            json.dump(unassigned_data, f, indent=2)
        
        # Aggregate reasons
        reason_counts: dict[str, int] = {}
        for d in unassigned_data:
            rc = d["reason_code"]
            reason_counts[rc] = reason_counts.get(rc, 0) + 1
        solve_report["unassigned_reasons"] = reason_counts
    
    # Write summary.txt
    with open(output_dir / "summary.txt", 'w') as f:
        f.write(f"{'='*50}\n")
        f.write(f"SCENARIO: {scenario_name}\n")
        f.write(f"{'='*50}\n\n")
        f.write(f"STATUS: {status}\n\n")
        f.write(f"CONFIG:\n")
        f.write(f"  Time Limit: {config.time_limit_seconds}s\n")
        f.write(f"  Seed: {config.seed}\n")
        f.write(f"  Workers: {config.num_workers}\n\n")
        f.write(f"INPUT:\n")
        f.write(f"  Tours: {len(tours)}\n")
        f.write(f"  Drivers: {len(drivers)}\n")
        f.write(f"  Coverable Tours: {len(model.coverable_tour_ids)}\n\n")
        
        if plan:
            f.write(f"OUTPUT:\n")
            f.write(f"  Assigned: {plan.stats.total_tours_assigned}/{len(tours)} ({plan.stats.total_tours_assigned/len(tours)*100:.1f}%)\n")
            f.write(f"  Unassigned: {plan.stats.total_tours_unassigned}\n")
            f.write(f"  Drivers Used: {plan.stats.total_drivers}\n")
            f.write(f"  Blocks: {plan.stats.block_counts.get(BlockType.TRIPLE,0)}x3er, {plan.stats.block_counts.get(BlockType.DOUBLE,0)}x2er, {plan.stats.block_counts.get(BlockType.SINGLE,0)}x1er\n\n")
            
            f.write(f"TIMING:\n")
            f.write(f"  Solve Time: {solve_time:.2f}s\n")
            f.write(f"  Time Limit Hit: {'YES' if solve_time >= config.time_limit_seconds * 0.95 else 'NO'}\n\n")
            
            if model.fallback_triggered:
                f.write(f"[WARNING] FALLBACK TRIGGERED: Hard coverage was infeasible\n\n")
            
            if plan.unassigned_tours:
                f.write(f"UNASSIGNED REASONS (Top 5):\n")
                reason_counts = {}
                for ut in plan.unassigned_tours:
                    rc = str(ut.reason_codes[0].value) if ut.reason_codes else "unknown"
                    reason_counts[rc] = reason_counts.get(rc, 0) + 1
                for rc, cnt in sorted(reason_counts.items(), key=lambda x: -x[1])[:5]:
                    f.write(f"  {rc}: {cnt}\n")
        else:
            f.write(f"OUTPUT: FAILED - No plan generated\n")
        
        f.write(f"\n{'='*50}\n")
    
    print(f"\n[OK] Artifacts written to: {output_dir}")
    print(f"   Status: {status}")
    if plan:
        print(f"   Coverage: {plan.stats.total_tours_assigned}/{len(tours)}")
    
    return solve_report


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="CP-SAT Production Smoke Test")
    parser.add_argument("--tours", required=True, help="Path to tours file (CSV or JSON)")
    parser.add_argument("--drivers", required=True, help="Path to drivers file (CSV or JSON)")
    parser.add_argument("--output", default="artifacts", help="Output directory")
    parser.add_argument("--single", choices=["A", "B", "C"], help="Run single scenario only")
    args = parser.parse_args()
    
    # Load data
    print(f"\nLoading data...")
    tours, drivers = load_data(args.tours, args.drivers)
    print(f"  Tours: {len(tours)}")
    print(f"  Drivers: {len(drivers)}")
    
    # Create timestamp directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path(args.output) / timestamp
    
    # Define scenarios
    scenarios = {
        "A": CPSATConfig(time_limit_seconds=10.0, seed=42, num_workers=4, fallback_to_soft=True),
        "B": CPSATConfig(time_limit_seconds=120.0, seed=42, num_workers=4, fallback_to_soft=True),
        "C": CPSATConfig(time_limit_seconds=120.0, seed=42, num_workers=8, fallback_to_soft=True),  # Stress
    }
    
    # Run scenarios
    results = {}
    
    if args.single:
        scenarios_to_run = {args.single: scenarios[args.single]}
    else:
        scenarios_to_run = scenarios
    
    for name, config in scenarios_to_run.items():
        output_dir = base_dir / f"run_{name}"
        results[name] = run_scenario(tours, drivers, config, output_dir, f"Run {name}")
    
    # Write combined summary
    with open(base_dir / "combined_summary.json", 'w') as f:
        json.dump({
            "timestamp": timestamp,
            "input": {
                "tours_file": args.tours,
                "drivers_file": args.drivers,
                "tours_count": len(tours),
                "drivers_count": len(drivers)
            },
            "scenarios": results
        }, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"ALL SCENARIOS COMPLETE")
    print(f"Output: {base_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
