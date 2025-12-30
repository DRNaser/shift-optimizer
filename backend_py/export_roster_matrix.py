import csv
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.services.portfolio_controller import run_portfolio
from test_forecast_csv import parse_forecast_csv
from src.domain.models import Weekday

# Fleet Counter integration
try:
    from fleet_counter import compute_fleet_peaks, export_peak_summary_csv, FleetPeakSummary
    FLEET_COUNTER_AVAILABLE = True
except ImportError:
    FLEET_COUNTER_AVAILABLE = False

def format_time(t):
    return f"{t.hour:02d}:{t.minute:02d}"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Roster Matrix")
    parser.add_argument("--time-budget", type=float, default=60.0, help="Solver time budget in seconds")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    # Contract-based FTE/PT classification (v7.3.0)
    parser.add_argument("--fte-pool-size", type=int, default=176, help="Contract FTE pool size (drivers labeled FTE)")
    parser.add_argument("--pt-pool-size", type=int, default=9999, help="Contract PT pool size (warning threshold)")
    args = parser.parse_args()

    print("=" * 70)
    print("ROSTER MATRIX EXPORTER (v7.3.0 + Holiday Week Support)")
    print("=" * 70)
    print(f"  FTE Pool Size: {args.fte_pool_size}")
    
    # Input
    input_file = Path(__file__).parent.parent / "forecast input.csv"
    if not input_file.exists():
        print(f"Error: Input file not found at {input_file}")
        return
        
    print(f"Reading forecast from: {input_file}")
    tours = parse_forecast_csv(str(input_file))
    print(f"Loaded {len(tours)} tours")

    # ==========================================================================
    # FLEET COUNTER (pre-solve analysis)
    # ==========================================================================
    fleet_summary = None
    if FLEET_COUNTER_AVAILABLE:
        print("\n" + "=" * 70)
        print("FLEET COUNTER - Peak Vehicle Demand Analysis")
        print("=" * 70)
        try:
            fleet_summary = compute_fleet_peaks(tours, turnaround_minutes=5)
            print(f"Total Tours: {fleet_summary.total_tours}")
            print(f"Global Peak: {fleet_summary.global_peak_count} vehicles @ {fleet_summary.global_peak_day.value} {fleet_summary.global_peak_time.strftime('%H:%M')}")
            print("\nPer-Day Peaks:")
            for day, peak in fleet_summary.day_peaks.items():
                marker = " <- PEAK" if day == fleet_summary.global_peak_day else ""
                print(f"  {day.value}: {peak.peak_count} vehicles @ {peak.peak_time.strftime('%H:%M')}{marker}")
        except Exception as fleet_err:
            print(f"Fleet counter error: {fleet_err}")
    else:
        print("\n[WARN] Fleet counter not available")

    # Solve
    print("\n" + "=" * 70)
    print(f"Running solver (Set-Partitioning V7.3.0, Quality Mode, Budget={args.time_budget}s)...")
    print("=" * 70)
    result = run_portfolio(tours, time_budget=args.time_budget, seed=args.seed)
    
    solution = result.solution
    valid_statuses = ["OPTIMAL", "FEASIBLE", "COMPLETED", "OK", "OK_SEEDED"]
    if solution.status not in valid_statuses:
        print(f"Solver failed with status: {solution.status}")
        return

    assignments = solution.assignments
    kpi = solution.kpi
    
    print(f"\nSolved! Status: {solution.status}")
    print(f"Assignments: {len(assignments)} drivers")
    
    # ==========================================================================
    # CONTRACT-BASED FTE/PT CLASSIFICATION (v7.3.0)
    # ==========================================================================
    # FTE/PT is determined by contract pool size, NOT by hours worked
    # This is critical for holiday weeks where max hours < 40
    fte_pool_size = args.fte_pool_size
    drivers_total = len(assignments)
    fte_used = min(drivers_total, fte_pool_size)
    pt_used = max(0, drivers_total - fte_pool_size)
    
    # Sort by hours (descending) for deterministic labeling
    # Top `fte_used` drivers get FTE label, rest get PT
    assignments.sort(key=lambda a: (-a.total_hours, getattr(a, 'driver_id', '')))
    
    for idx, a in enumerate(assignments):
        if idx < fte_used:
            a.driver_type = "FTE"
            a.driver_id = f"FTE{idx + 1:03d}"
        else:
            a.driver_type = "PT"
            a.driver_id = f"PT{idx - fte_used + 1:03d}"
    
    # Update KPI with contract-based metrics
    kpi["fte_pool_size"] = fte_pool_size
    kpi["fte_used"] = fte_used
    kpi["pt_used"] = pt_used
    kpi["drivers_fte"] = fte_used
    kpi["drivers_pt"] = pt_used
    
    print(f"\n[CONTRACT-BASED] FTE Pool: {fte_pool_size}")
    print(f"  FTE Used: {fte_used}, PT Used: {pt_used}")

    # ==========================================================================
    # ROSTER MATRIX CSV
    # ==========================================================================
    rows = []
    
    # Sort by Driver Type (FTE first), then Hours (desc), then ID
    assignments.sort(key=lambda a: (0 if a.driver_type == "FTE" else 1, -a.total_hours, a.driver_id))

    headers = ["Driver ID", "Type", "Weekly Hours", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    # Map Weekday enum to header columns
    day_map = {
        Weekday.MONDAY: "Mon",
        Weekday.TUESDAY: "Tue",
        Weekday.WEDNESDAY: "Wed",
        Weekday.THURSDAY: "Thu",
        Weekday.FRIDAY: "Fri",
        Weekday.SATURDAY: "Sat"
    }

    for assignment in assignments:
        if assignment.total_hours <= 0.01:
            continue
            
        row = {
            "Driver ID": assignment.driver_id,
            "Type": assignment.driver_type,
            "Weekly Hours": f"{assignment.total_hours:.2f}".replace('.', ','), # German decimal format
            "Mon": "", "Tue": "", "Wed": "", "Thu": "", "Fri": "", "Sat": ""
        }
        
        for block in assignment.blocks:
            day_str = day_map.get(block.day)
            if day_str:
                start = format_time(block.first_start)
                end = format_time(block.last_end)
                try:
                    b_type = block.block_type.value # e.g. "3er"
                except:
                    b_type = "Block"
                    
                # Check for split
                split_flag = " (Split)" if getattr(block, 'is_split', False) else ""
                
                # Format: "08:00-17:00 (3er)"
                cell_content = f"{start}-{end} ({b_type}{split_flag})"
                row[day_str] = cell_content
        
        rows.append(row)

    # Write Roster CSV
    output_dir = Path(__file__).parent
    roster_file = output_dir / "roster_matrix.csv"
    
    # Use utf-8-sig for Excel compatibility (BOM)
    # Use semicolon delimiter for German Excel
    with open(roster_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=";", extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[SUCCESS] Roster Matrix exported to: {roster_file}")
    print(f"Total Rows: {len(rows)}")

    # ==========================================================================
    # KPI CSV (Enhanced with Fleet Metrics)
    # ==========================================================================
    kpi_file = output_dir / "roster_matrix_kpis.csv"
    
    # Flatten KPIs for CSV
    kpi_rows = []
    
    # Core metrics
    kpi_rows.append({"Metric": "Total Drivers", "Value": len(assignments)})
    kpi_rows.append({"Metric": "FTE Drivers", "Value": kpi.get("drivers_fte", 0)})
    kpi_rows.append({"Metric": "PT Drivers", "Value": kpi.get("drivers_pt", 0)})
    kpi_rows.append({"Metric": "Total Hours", "Value": kpi.get("total_hours", 0)})
    kpi_rows.append({"Metric": "FTE Hours Avg", "Value": kpi.get("fte_hours_avg", 0)})
    kpi_rows.append({"Metric": "FTE Hours Min", "Value": kpi.get("fte_hours_min", 0)})
    kpi_rows.append({"Metric": "FTE Hours Max", "Value": kpi.get("fte_hours_max", 0)})
    
    # Block stats
    kpi_rows.append({"Metric": "Blocks Selected", "Value": kpi.get("blocks_selected", 0)})
    kpi_rows.append({"Metric": "Blocks 3er", "Value": kpi.get("blocks_3er", 0)})
    kpi_rows.append({"Metric": "Blocks 2er", "Value": kpi.get("blocks_2er", 0)})
    kpi_rows.append({"Metric": "Blocks 1er", "Value": kpi.get("blocks_1er", 0)})
    
    # Fleet metrics (from KPI or direct computation)
    fleet_peak = kpi.get("fleet_peak_count", 0)
    fleet_day = kpi.get("fleet_peak_day", "N/A")
    fleet_time = kpi.get("fleet_peak_time", "N/A")
    
    kpi_rows.append({"Metric": "Fleet Peak Vehicles", "Value": fleet_peak})
    kpi_rows.append({"Metric": "Fleet Peak Day", "Value": fleet_day})
    kpi_rows.append({"Metric": "Fleet Peak Time", "Value": fleet_time})
    
    with open(kpi_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Metric", "Value"], delimiter=";")
        writer.writeheader()
        writer.writerows(kpi_rows)
    
    print(f"[SUCCESS] KPI Summary exported to: {kpi_file}")

    # ==========================================================================
    # FLEET SUMMARY CSV
    # ==========================================================================
    if fleet_summary and FLEET_COUNTER_AVAILABLE:
        fleet_file = output_dir / "fleet_summary.csv"
        export_peak_summary_csv(fleet_summary, fleet_file)
        print(f"[SUCCESS] Fleet Summary exported to: {fleet_file}")

    # ==========================================================================
    # CONSOLE SUMMARY
    # ==========================================================================
    print("\n" + "=" * 70)
    print("EXPORT SUMMARY")
    print("=" * 70)
    print(f"  Drivers: {kpi.get('drivers_fte', 0)} FTE + {kpi.get('drivers_pt', 0)} PT = {len(assignments)} Total")
    print(f"  Hours:   {kpi.get('total_hours', 0):.1f}h total, {kpi.get('fte_hours_avg', 0):.1f}h avg FTE")
    if fleet_peak > 0:
        print(f"  Fleet:   {fleet_peak} vehicles peak @ {fleet_day} {fleet_time}")
    print()
    print("Files Generated:")
    print(f"  1. {roster_file.name} (Driver schedules)")
    print(f"  2. {kpi_file.name} (KPI metrics)")
    if fleet_summary:
        print(f"  3. fleet_summary.csv (Fleet peak analysis)")
    print("=" * 70)
    
    # Preview
    print("\nPreview (Top 3 FTE):")
    for r in rows[:3]:
        print(f"  {r['Driver ID']} ({r['Type']}, {r['Weekly Hours']}h)")

if __name__ == "__main__":
    main()

