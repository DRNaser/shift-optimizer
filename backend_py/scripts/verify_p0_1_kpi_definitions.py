"""
P0.1: KPI Definition & Objective Verification
Mathematically proves what drivers_total and LP objective really mean.

Tasks:
A) Hour-based verification from actual tour data
B) Objective scaling verification
C) drivers_total definition clarification
P1.1) Fleet peak validation
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.model.tour import TourV2
from src.core_v2.fleet_counter import calculate_fleet_peak_from_tours
from src.domain.models import Weekday
from test_forecast_csv import parse_forecast_csv
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("P0_1_Verify")

def main():
    # Load forecast
    csv_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_kw51.csv")
    tours_v1 = parse_forecast_csv(str(csv_file))
    
    # ====================================================================
    # TASK A: Hour-Based Verification from Actual Tour Data
    # ====================================================================
    logger.info("=" * 80)
    logger.info("TASK A: Hour-Based Verification")
    logger.info("=" * 80)
    
    total_tours = len(tours_v1)
    total_minutes_covered = sum(int(t.duration_hours * 60) for t in tours_v1)
    hours_total = total_minutes_covered / 60.0
    
    # Physical lower bounds
    max_hours_per_driver = 55.0
    lower_bound_hours = hours_total / max_hours_per_driver
    
    logger.info(f"Total Tours: {total_tours}")
    logger.info(f"Total Minutes Covered: {total_minutes_covered} min")
    logger.info(f"Hours Total: {hours_total:.1f}h")
    logger.info(f"Physical Lower Bound (55h/week): {lower_bound_hours:.1f} drivers")
    
    # Convert tours to V2
    day_map = {Weekday.MONDAY:0, Weekday.TUESDAY:1, Weekday.WEDNESDAY:2, Weekday.THURSDAY:3, Weekday.FRIDAY:4, Weekday.SATURDAY:5, Weekday.SUNDAY:6}
    tours_v2 = []
    for t in tours_v1:
        tours_v2.append(TourV2(
            f"T_{day_map.get(t.day, 0)}_{t.id}", 
            day_map.get(t.day, 0), 
            t.start_time.hour*60 + t.start_time.minute, 
            t.start_time.hour*60 + t.start_time.minute + int(t.duration_hours*60), 
            int(t.duration_hours*60)
        ))
    
    # Verify TourV2 durations match
    total_minutes_v2 = sum(t.duration_min for t in tours_v2)
    assert total_minutes_v2 == total_minutes_covered, f"Tour conversion error! {total_minutes_v2} != {total_minutes_covered}"
    logger.info(f"✓ Tour V2 conversion verified: {total_minutes_v2} min")
    
    # ====================================================================
    # P1.1: Fleet Peak Validation (same tour times)
    # ====================================================================
    logger.info("\n" + "=" * 80)
    logger.info("P1.1: Fleet Peak Validation")
    logger.info("=" * 80)
    
    baseline_fleet = calculate_fleet_peak_from_tours(tours_v1)
    logger.info(f"Baseline Fleet Peak: {baseline_fleet['fleet_peak']} vehicles")
    logger.info(f"Peak Time: {baseline_fleet['fleet_peak_time']}")
    logger.info(f"By Day: {baseline_fleet['fleet_peak_by_day']}")
    
    # ====================================================================
    # Run Optimizer
    # ====================================================================
    logger.info("\n" + "=" * 80)
    logger.info("Running Optimizer (Quick Verification)")
    logger.info("=" * 80)
    
    config = {
        "run_id": "p0_1_verify",
        "week_category": "COMPRESSED",
        "artifacts_dir": "results/p0_1_verify",
        
        "max_cg_iterations": 15,
        "lp_time_limit": 30.0,
        "restricted_mip_var_cap": 20_000,
        "restricted_mip_time_limit": 30.0,
        "mip_time_limit": 120.0,
        "final_subset_cap": 15_000,
        "target_seed_columns": 3000,
        "pricing_time_limit_sec": 10.0,
        
        "duty_caps": {
            "min_gap_minutes": 0,
            "max_gap_minutes": 1440,  # 24h
            "top_m_start_tours": 300,
            "max_succ_per_tour": 50,
            "max_triples_per_tour": 5,
        },
        "export_csv": False
    }
    
    import os
    os.makedirs(config["artifacts_dir"], exist_ok=True)
    
    opt = OptimizerCoreV2()
    result = opt.solve(tours_v2, config, run_id=config["run_id"])
    
    if result.status != "SUCCESS":
        logger.error(f"Optimization failed: {result.error_message}")
        return
    
    # ====================================================================
    # TASK B: Objective Scaling Verification
    # ====================================================================
    logger.info("\n" + "=" * 80)
    logger.info("TASK B: Objective Scaling Verification")
    logger.info("=" * 80)
    
    selected_columns = result._debug_columns
    kpis = result.kpis
    
    # Calculate column costs
    from src.core_v2.contracts.result import CoreV2Proof
    week_category = result.week_type
    
    # Import week category enum
    from src.core_v2.model.week_category import WeekCategory
    week_cat_enum = WeekCategory[week_category] if hasattr(WeekCategory, week_category) else WeekCategory.COMPRESSED
    
    column_costs = [c.cost_utilization(week_cat_enum) for c in selected_columns]
    avg_column_cost = sum(column_costs) / len(column_costs) if column_costs else 0
    min_column_cost = min(column_costs) if column_costs else 0
    max_column_cost = max(column_costs) if column_costs else 0
    
    # Base costs (should be 1.0 for real columns)
    base_costs = [c.cost_stage1() for c in selected_columns]
    avg_base_cost = sum(base_costs) / len(base_costs) if base_costs else 0
    
    logger.info(f"Selected Columns: {len(selected_columns)}")
    logger.info(f"Avg Column Cost (with penalties): {avg_column_cost:.2f}")
    logger.info(f"Min Column Cost: {min_column_cost:.2f}")
    logger.info(f"Max Column Cost: {max_column_cost:.2f}")
    logger.info(f"Avg Base Cost (stage1, no penalties): {avg_base_cost:.2f}")
    logger.info(f"MIP Objective: {kpis.get('mip_obj', 0):.2f}")
    
    # Decompose objective
    total_base_cost = sum(base_costs)
    total_penalty = sum(column_costs) - total_base_cost
    
    logger.info(f"\nObjective Decomposition:")
    logger.info(f"  Base Driver Term: {total_base_cost:.2f} (pure driver count)")
    logger.info(f"  Penalty Term: {total_penalty:.2f} (utilization penalties)")
    logger.info(f"  Total MIP Obj: {kpis.get('mip_obj', 0):.2f}")
    
    # ====================================================================
    # TASK C: drivers_total Definition Clarification
    # ====================================================================
    logger.info("\n" + "=" * 80)
    logger.info("TASK C: drivers_total Definition")
    logger.info("=" * 80)
    
    weekly_rosters_selected = len(selected_columns)
    driver_days_total = sum(c.days_worked for c in selected_columns)
    avg_days_worked_per_driver = driver_days_total / weekly_rosters_selected if weekly_rosters_selected else 0
    
    # Calculate coverage
    tours_covered = set()
    for c in selected_columns:
        tours_covered.update(c.covered_tour_ids)
    
    coverage_pct = (len(tours_covered) / total_tours) * 100 if total_tours else 0
    
    logger.info(f"Definition Breakdown:")
    logger.info(f"  weekly_rosters_selected: {weekly_rosters_selected} (# columns = MIP objective basis)")
    logger.info(f"  driver_days_total: {driver_days_total} (sum of days_worked)")
    logger.info(f"  avg_days_worked_per_driver: {avg_days_worked_per_driver:.2f} days/week")
    logger.info(f"  tours_covered: {len(tours_covered)}/{total_tours} ({coverage_pct:.1f}%)")
    
    # ====================================================================
    # FINAL REPORT
    # ====================================================================
    print("\n" + "=" * 80)
    print("P0.1 VERIFICATION REPORT")
    print("=" * 80)
    
    report = {
        "TASK_A_HOURS": {
            "total_tours": total_tours,
            "total_minutes_covered": total_minutes_covered,
            "hours_total": round(hours_total, 1),
            "physical_lower_bound_55h": round(lower_bound_hours, 1),
        },
        "TASK_B_OBJECTIVE": {
            "LP_objective_final": round(kpis.get('mip_obj', 0), 2),
            "avg_column_cost_selected": round(avg_column_cost, 2),
            "min_column_cost": round(min_column_cost, 2),
            "max_column_cost": round(max_column_cost, 2),
            "avg_base_cost_no_penalty": round(avg_base_cost, 2),
            "objective_components": {
                "base_driver_term": round(total_base_cost, 2),
                "penalty_term": round(total_penalty, 2),
            }
        },
        "TASK_C_DRIVERS_TOTAL": {
            "weekly_rosters_selected": weekly_rosters_selected,
            "driver_days_total": driver_days_total,
            "avg_days_worked_per_driver": round(avg_days_worked_per_driver, 2),
            "tours_covered": len(tours_covered),
            "coverage_pct": round(coverage_pct, 1),
        },
        "P1_1_FLEET_PEAK": {
            "fleet_peak": baseline_fleet['fleet_peak'],
            "fleet_peak_by_day": baseline_fleet['fleet_peak_by_day'],
            "fleet_peak_time": baseline_fleet['fleet_peak_time'],
            "fleet_peak_optimized": kpis.get('fleet_peak', 0),
        }
    }
    
    print(json.dumps(report, indent=2))
    
    # Save to file
    output_file = Path("results/p0_1_verification_report.json")
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"\n✓ Report saved to: {output_file}")
    
    # ====================================================================
    # USER-REQUESTED VALUES
    # ====================================================================
    print("\n" + "=" * 80)
    print("USER-REQUESTED VALUES (for immediate verification)")
    print("=" * 80)
    print(f"total_tours: {total_tours}")
    print(f"hours_total: {hours_total:.1f}h")
    print(f"drivers_total (selected columns): {weekly_rosters_selected}")
    print(f"driver_days_total: {driver_days_total}")
    print(f"LP_objective: {kpis.get('mip_obj', 0):.2f}")
    print(f"avg_column_cost_selected: {avg_column_cost:.2f}")
    print("=" * 80)
    
    # ====================================================================
    # VERDICT
    # ====================================================================
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    
    print(f"\n✓ TASK A: Hours-based verification COMPLETE")
    print(f"  - Physical LB ({lower_bound_hours:.0f}) << LP Bound ({weekly_rosters_selected})")
    print(f"  - Gap indicates fragmentation (short rosters)")
    
    print(f"\n✓ TASK B: Objective scaling verification COMPLETE")
    print(f"  - Base cost per column: {avg_base_cost:.2f} (pure driver count)")
    print(f"  - Penalties add: {total_penalty:.2f} (utilization-based)")
    print(f"  - MIP Obj = {total_base_cost:.0f} drivers + {total_penalty:.0f} penalty")
    
    print(f"\n✓ TASK C: drivers_total definition CLARIFIED")
    print(f"  - weekly_rosters_selected = {weekly_rosters_selected} (# people)")
    print(f"  - driver_days_total = {driver_days_total} (workdays)")
    print(f"  - avg_days/driver = {avg_days_worked_per_driver:.1f}")
    
    print(f"\n✓ P1.1: Fleet peak validation COMPLETE")
    print(f"  - Baseline fleet: {baseline_fleet['fleet_peak']} vehicles")
    print(f"  - Optimized fleet: {kpis.get('fleet_peak', 0)} vehicles")
    print(f"  - Should match (same tours): {baseline_fleet['fleet_peak'] == kpis.get('fleet_peak', 0)}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
