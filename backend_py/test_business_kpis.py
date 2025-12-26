"""
Business KPI Validator - Extract and validate all critical metrics
"""

import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.domain.models import Weekday
from src.services.forecast_solver_v4 import ConfigV4
from test_forecast_csv import parse_forecast_csv

def compute_business_kpis(result):
    """Extract all business-critical KPIs from solver result."""
    
    assignments = result.assignments
    fte_assignments = [a for a in assignments if a.driver_type == "FTE" and a.blocks]
    pt_assignments = [a for a in assignments if a.driver_type == "PT" and a.blocks]
    
    # FTE metrics
    fte_hours = [a.total_hours for a in fte_assignments]
    fte_hours_min = min(fte_hours) if fte_hours else 0
    fte_hours_max = max(fte_hours) if fte_hours else 0
    fte_hours_avg = sum(fte_hours) / len(fte_hours) if fte_hours else 0
    
    # Compliance counts
    fte_under40 = [a for a in fte_assignments if a.total_hours < 40.0]
    fte_over55 = [a for a in fte_assignments if a.total_hours > 55.0]
    
    # PT metrics
    pt_hours_total = sum(a.total_hours for a in pt_assignments)
    total_hours = sum(a.total_hours for a in assignments)
    pt_share_hours = pt_hours_total / total_hours if total_hours > 0 else 0
    
    return {
        "drivers_fte": len(fte_assignments),
        "drivers_pt": len(pt_assignments),
        "drivers_total": len(fte_assignments) + len(pt_assignments),
        
        "fte_hours_min": round(fte_hours_min, 2),
        "fte_hours_avg": round(fte_hours_avg, 2),
        "fte_hours_max": round(fte_hours_max, 2),
        
        "fte_under40_count": len(fte_under40),
        "fte_under40_pct": round(len(fte_under40) / len(fte_assignments) * 100, 1) if fte_assignments else 0,
        
        "fte_over55_count": len(fte_over55),
        "fte_over55_pct": round(len(fte_over55) / len(fte_assignments) * 100, 1) if fte_assignments else 0,
        
        "pt_hours_total": round(pt_hours_total, 1),
        "pt_share_hours": round(pt_share_hours, 4),
        "pt_share_hours_pct": round(pt_share_hours * 100, 1),
        
        "total_hours": round(total_hours, 1),
    }


def validate_11h_rest(result):
    """Validate 11h rest between consecutive workdays for all drivers."""
    
    violations = []
    checks_performed = 0
    
    weekday_order = {
        Weekday.MONDAY: 0,
        Weekday.TUESDAY: 1,
        Weekday.WEDNESDAY: 2,
        Weekday.THURSDAY: 3,
        Weekday.FRIDAY: 4,
        Weekday.SATURDAY: 5,
    }
    
    MIN_REST_MINUTES = 11 * 60  # 660 minutes
    
    for assignment in result.assignments:
        if not assignment.blocks:
            continue
        
        # Group blocks by day
        blocks_by_day = {}
        for block in assignment.blocks:
            day_idx = weekday_order.get(block.day, -1)
            if day_idx == -1:
                continue
            if day_idx not in blocks_by_day:
                blocks_by_day[day_idx] = []
            blocks_by_day[day_idx].append(block)
        
        # Sort days
        sorted_days = sorted(blocks_by_day.keys())
        
        # Check consecutive days
        for i in range(len(sorted_days) - 1):
            day1_idx = sorted_days[i]
            day2_idx = sorted_days[i + 1]
            
            # Only check if actually consecutive
            if day2_idx != day1_idx + 1:
                continue
            
            # Get last block of day1
            day1_blocks = blocks_by_day[day1_idx]
            last_block_day1 = max(day1_blocks, key=lambda b: b.last_end)
            end_day1 = last_block_day1.last_end.hour * 60 + last_block_day1.last_end.minute
            
            # Get first block of day2
            day2_blocks = blocks_by_day[day2_idx]
            first_block_day2 = min(day2_blocks, key=lambda b: b.first_start)
            start_day2 = first_block_day2.first_start.hour * 60 + first_block_day2.first_start.minute
            
            # Calculate rest (assuming day boundary at midnight)
            # Rest = (1440 - end_day1) + start_day2
            rest_minutes = (1440 - end_day1) + start_day2
            
            checks_performed += 1
            
            if rest_minutes < MIN_REST_MINUTES:
                violations.append({
                    "driver_id": assignment.driver_id,
                    "day1": list(weekday_order.keys())[day1_idx].value,
                    "day2": list(weekday_order.keys())[day2_idx].value,
                    "end_day1": f"{last_block_day1.last_end.hour:02d}:{last_block_day1.last_end.minute:02d}",
                    "start_day2": f"{first_block_day2.first_start.hour:02d}:{first_block_day2.first_start.minute:02d}",
                    "rest_minutes": rest_minutes,
                    "rest_hours": round(rest_minutes / 60, 2),
                    "violation_minutes": MIN_REST_MINUTES - rest_minutes,
                })
    
    return {
        "checks_performed": checks_performed,
        "violations_count": len(violations),
        "violations": violations,
        "compliant": len(violations) == 0,
    }


def assess_launch_readiness(kpis, rest_check):
    """Determine if solution is launch-ready."""
    
    gates = {
        "fte_over55_zero": {
            "passed": kpis["fte_over55_count"] == 0,
            "critical": True,
            "value": kpis["fte_over55_count"],
            "target": 0,
        },
        "pt_share_low": {
            "passed": kpis["pt_share_hours"] <= 0.15,
            "critical": True,
            "value": kpis["pt_share_hours_pct"],
            "target": "≤15%",
        },
        "rest_11h_compliant": {
            "passed": rest_check["compliant"],
            "critical": True,
            "value": rest_check["violations_count"],
            "target": 0,
        },
    }
    
    all_critical_passed = all(g["passed"] for g in gates.values() if g["critical"])
    
    recommendations = []
    
    if not gates["fte_over55_zero"]["passed"]:
        recommendations.append(f"❌ CRITICAL: {kpis['fte_over55_count']} FTE über 55h - COMPLIANCE VIOLATION")
    
    if not gates["pt_share_low"]["passed"]:
        recommendations.append(f"⚠️  PT share {kpis['pt_share_hours_pct']:.1f}% > 15% - needs reduction")
    
    if not gates["rest_11h_compliant"]["passed"]:
        recommendations.append(f"❌ CRITICAL: {rest_check['violations_count']} 11h rest violations - ILLEGAL")
    
    # Soft warnings
    if kpis["fte_under40_count"] > kpis["drivers_fte"] * 0.3:
        recommendations.append(f"ℹ️  {kpis['fte_under40_pct']:.1f}% FTE unter 40h - optimize underfull")
    
    if kpis["fte_hours_avg"] < 42.0:
        recommendations.append(f"ℹ️  FTE avg {kpis['fte_hours_avg']:.1f}h < 42h - pool-cap + underfull-repair needed")
    
    return {
        "launch_ready": all_critical_passed,
        "gates": gates,
        "recommendations": recommendations,
    }


def main():
    print("=" * 70)
    print("BUSINESS KPI VALIDATION")
    print("=" * 70)
    print()
    
    # Parse input
    input_file = Path(__file__).parent.parent / "forecast input.csv"
    tours = parse_forecast_csv(str(input_file))
    print(f"Loaded {len(tours)} tours")
    print()
    
    # Run solver
    from src.services.forecast_solver_v4 import solve_forecast_v4
    
    config = ConfigV4(
        seed=42,
        num_workers=1,
        time_limit_phase1=20.0,
        time_limit_phase2=40.0,
    )
    
    print("Running solver (seed=42)...")
    result = solve_forecast_v4(tours, config)
    print(f"Status: {result.status}")
    print()
    
    # Extract KPIs
    print("=" * 70)
    print("1. BUSINESS KPIs")
    print("=" * 70)
    kpis = compute_business_kpis(result)
    
    print(f"Drivers: {kpis['drivers_fte']} FTE + {kpis['drivers_pt']} PT = {kpis['drivers_total']} total")
    print()
    print(f"FTE Hours:")
    print(f"  Min: {kpis['fte_hours_min']}h")
    print(f"  Avg: {kpis['fte_hours_avg']}h")
    print(f"  Max: {kpis['fte_hours_max']}h")
    print()
    print(f"FTE Under 40h: {kpis['fte_under40_count']} ({kpis['fte_under40_pct']}%)")
    print(f"FTE Over 55h: {kpis['fte_over55_count']} ({kpis['fte_over55_pct']}%)")
    print()
    print(f"PT Hours Total: {kpis['pt_hours_total']}h")
    print(f"PT Share: {kpis['pt_share_hours_pct']}% of total {kpis['total_hours']}h")
    print()
    
    # Validate 11h rest
    print("=" * 70)
    print("2. 11H REST COMPLIANCE")
    print("=" * 70)
    rest_check = validate_11h_rest(result)
    
    print(f"Checks performed: {rest_check['checks_performed']}")
    print(f"Violations: {rest_check['violations_count']}")
    
    if rest_check['violations']:
        print()
        print("VIOLATIONS FOUND:")
        for v in rest_check['violations'][:10]:  # Show first 10
            print(f"  {v['driver_id']}: {v['day1']}→{v['day2']}")
            print(f"    End {v['end_day1']} → Start {v['start_day2']}")
            print(f"    Rest: {v['rest_hours']}h (missing {v['violation_minutes']} min)")
    else:
        print("✅ ALL CHECKS PASSED - 11h rest compliant!")
    print()
    
    # Assess launch readiness
    print("=" * 70)
    print("3. LAUNCH READINESS")
    print("=" * 70)
    assessment = assess_launch_readiness(kpis, rest_check)
    
    print(f"Launch Ready: {'✅ YES' if assessment['launch_ready'] else '❌ NO'}")
    print()
    
    for gate_name, gate in assessment['gates'].items():
        status = "✅" if gate['passed'] else "❌"
        critical = "[CRITICAL]" if gate['critical'] else "[SOFT]"
        print(f"{status} {critical} {gate_name}: {gate['value']} (target: {gate['target']})")
    
    print()
    if assessment['recommendations']:
        print("Recommendations:")
        for rec in assessment['recommendations']:
            print(f"  {rec}")
    
    # Save results
    output = {
        "kpis": kpis,
        "rest_check": {
            "checks_performed": rest_check["checks_performed"],
            "violations_count": rest_check["violations_count"],
            "compliant": rest_check["compliant"],
        },
        "assessment": {
            "launch_ready": assessment["launch_ready"],
            "gates": assessment["gates"],
        }
    }
    
    output_file = Path(__file__).parent / "business_kpi_validation.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"Results saved to: {output_file}")
    print()
    
    return 0 if assessment["launch_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
