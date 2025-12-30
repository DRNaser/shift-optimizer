"""
Run Core v2 with REAL KW51 Forecast Data

Parses forecast_kw51.csv, runs OptimizerCoreV2, outputs roster_kw51.csv
"""

import sys
import os
import csv
import logging
import json
from pathlib import Path
from datetime import datetime, time
from collections import defaultdict

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend_py"))

from src.core_v2.optimizer_v2 import OptimizerCoreV2
from src.core_v2.adapter import Adapter
from src.domain.models import Tour, Weekday

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KW51_V2")


def parse_forecast_csv(filepath: str) -> list[Tour]:
    """Parse forecast_kw51.csv format into Tour objects."""
    tours = []
    
    day_map = {
        "Montag": Weekday.MONDAY,
        "Dienstag": Weekday.TUESDAY,
        "Mittwoch": Weekday.WEDNESDAY,
        "Donnerstag": Weekday.THURSDAY,
        "Freitag": Weekday.FRIDAY,
        "Samstag": Weekday.SATURDAY,
    }
    
    current_day = None
    tour_counter = 0
    
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line == ";":
                continue
            
            parts = line.split(';')
            if len(parts) < 2:
                continue
            
            first_col = parts[0].strip()
            second_col = parts[1].strip()
            
            # Check if this is a day header
            if first_col in day_map:
                current_day = day_map[first_col]
                logger.info(f"Parsing {first_col}...")
                continue
            
            # Skip holiday markers
            if first_col == "Feiertag":
                logger.info(f"  Skipping holiday")
                continue
            
            # Parse time slot: "03:30-08:00"
            if '-' in first_col and current_day is not None:
                try:
                    times = first_col.split('-')
                    start_str = times[0].strip()
                    end_str = times[1].strip()
                    
                    # Parse count
                    count = int(second_col) if second_col.isdigit() else 0
                    
                    if count == 0:
                        continue
                    
                    # Parse times
                    start_h, start_m = map(int, start_str.split(':'))
                    end_h, end_m = map(int, end_str.split(':'))
                    
                    # Handle 23:59 as end of day
                    if end_str == "23:59":
                        end_h, end_m = 23, 59
                    
                    start_time = time(start_h, start_m)
                    end_time = time(end_h, end_m)
                    
                    # Create N tours for this slot
                    for i in range(count):
                        tour_counter += 1
                        tour = Tour(
                            id=f"T_{tour_counter:04d}",
                            day=current_day,
                            start_time=start_time,
                            end_time=end_time,
                            location="KW51",
                            required_qualifications=[]
                        )
                        tours.append(tour)
                        
                except Exception as e:
                    logger.warning(f"  Failed to parse: {line} - {e}")
    
    return tours


def export_roster_csv(assignments: list, filepath: str, active_days: list[str]):
    """Export assignments to roster CSV format."""
    
    # Build header
    header = ["Driver ID", "Type", "Weekly Hours"] + active_days
    
    rows = []
    for a in assignments:
        row = {
            "Driver ID": a.driver_id,
            "Type": a.driver_type,
            "Weekly Hours": round(a.total_hours, 1),
        }
        
        # Initialize all days as empty
        for day in active_days:
            row[day] = ""
        
        # Fill in blocks per day
        for block in a.blocks:
            day_str = block.day.value if hasattr(block.day, 'value') else str(block.day)
            # Format: "HH:MM-HH:MM (Nh)"
            if hasattr(block, 'first_start') and hasattr(block, 'last_end'):
                start = block.first_start.strftime("%H:%M")
                end = block.last_end.strftime("%H:%M")
                hours = block.total_work_hours if hasattr(block, 'total_work_hours') else 0
                row[day_str] = f"{start}-{end} ({hours:.1f}h)"
            else:
                row[day_str] = f"{len(block.tours)} tours"
        
        rows.append(row)
    
    # Sort by type then ID
    rows.sort(key=lambda r: (0 if r["Type"] == "FTE" else 1, r["Driver ID"]))
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
    
    return len(rows)


def main():
    logger.info("=" * 70)
    logger.info("CORE V2 - KW51 REAL DATA RUN (LAZY DUTY GENERATION)")
    logger.info("=" * 70)
    
    # Paths
    base_dir = Path(__file__).parent.parent
    forecast_path = base_dir / "forecast_kw51.csv"
    roster_path = base_dir / "backend_py" / "roster_kw51.csv"
    
    # 1. Parse Forecast
    logger.info(f"Loading forecast from: {forecast_path}")
    tours_v1 = parse_forecast_csv(str(forecast_path))
    logger.info(f"Parsed {len(tours_v1)} tours")
    
    # Count by day
    by_day = defaultdict(int)
    for t in tours_v1:
        by_day[t.day.value] += 1
    for day, count in sorted(by_day.items()):
        logger.info(f"  {day}: {count} tours")
    
    # 2. Convert to v2
    logger.info("Converting to v2 format...")
    adapter = Adapter(tours_v1)
    tours_v2 = adapter.convert_to_v2()
    
    # 3. Configure with lazy duty generation caps
    run_id = f"kw51_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    artifacts_dir = str(base_dir / "backend_py" / "artifacts" / "v2_shadow" / run_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    
    config = {
        # CG Loop
        "max_cg_iterations": 50,         # Increased to allow convergence
        "lp_time_limit": 60.0,           # 60s per LP solve (was 10s)
        "pricing_time_limit_sec": 20.0,  # 20s to allow full propagation (was 5s, timed out at Day 1)
        "max_new_cols_per_iter": 1500,
        "target_seed_columns": 5000,
        
        # MIP
        "mip_time_limit": 1200.0,         # 20 min for final MIP
        
        # Lazy Duty Generation Caps
        "duty_caps": {
            "max_multi_duties_per_day": 50_000,
            "top_m_start_tours": 200,
            "max_succ_per_tour": 20,
            "max_triples_per_tour": 5,
        },
        
        # Infrastructure
        "backend": "highspy",
        "artifacts_dir": artifacts_dir,
    }
    
    logger.info("-" * 40)
    logger.info("CONFIG:")
    logger.info(f"  CG iterations: {config['max_cg_iterations']}")
    logger.info(f"  LP time limit: {config['lp_time_limit']}s")
    logger.info(f"  Pricing time limit: {config['pricing_time_limit_sec']}s")
    logger.info(f"  Max new cols/iter: {config['max_new_cols_per_iter']}")
    logger.info(f"  Duty caps: max_multi={config['duty_caps']['max_multi_duties_per_day']}")
    logger.info("-" * 40)

    # 4. Run Optimizer
    logger.info("=" * 70)
    logger.info("STARTING CORE V2 OPTIMIZATION...")
    logger.info("=" * 70)
    
    optimizer = OptimizerCoreV2()
    
    try:
        result = optimizer.solve(tours_v2, config, run_id=run_id)
    except Exception as e:
        logger.error(f"Optimizer Crashed: {e}", exc_info=True)
        return
    
    # 5. Report Results
    logger.info("=" * 70)
    logger.info(f"STATUS: {result.status}")
    if result.error_code:
        logger.error(f"ERROR: {result.error_code} - {result.error_message}")
    logger.info("=" * 70)
    
    # Always output telemetry
    logger.info("-" * 40)
    logger.info("TELEMETRY:")
    logger.info(f"  tours_total: {len(tours_v1)}")
    duty_counts = result.kpis.get("duty_counts_by_day", {})
    total_duties = sum(duty_counts.values()) if duty_counts else 0
    logger.info(f"  total_duties_generated: {total_duties}")
    for day, cnt in sorted(duty_counts.items()):
        logger.info(f"    Day {day}: {cnt} duties")
    logger.info(f"  cg_iterations: {result.kpis.get('cg_iterations', 'N/A')}")
    logger.info(f"  new_cols_added_total: {result.kpis.get('new_cols_added_total', 'N/A')}")
    logger.info(f"  pool_final_size: {result.kpis.get('pool_final_size', 'N/A')}")
    
    if result.status == "SUCCESS":
        logger.info("-" * 40)
        logger.info("SOLUTION FOUND!")
        logger.info(f"  Drivers: {result.num_drivers}")
        logger.info(f"  Runtime: {result.kpis.get('total_time', 0):.2f}s")
        logger.info(f"  MIP Obj: {result.kpis.get('mip_obj', 0):.2f}")
        
        # KPIs
        logger.info("-" * 40)
        logger.info("KPIs:")
        logger.info(f"  FTE: {result.kpis.get('drivers_fte', 0)}")
        logger.info(f"  PT: {result.kpis.get('drivers_pt', 0)}")
        logger.info(f"  PT Share: {result.kpis.get('pt_share_pct', 0):.1f}%")
        logger.info(f"  FTE Hours: min={result.kpis.get('fte_hours_min', 0):.1f}h, max={result.kpis.get('fte_hours_max', 0):.1f}h, avg={result.kpis.get('fte_hours_avg', 0):.1f}h")
        
        # Utilization Gates
        logger.info("-" * 40)
        logger.info("UTILIZATION GATES:")
        pct_under_30 = result.kpis.get('pct_under_30', 0)
        pct_under_20 = result.kpis.get('pct_under_20', 0)
        avg_hours = result.kpis.get('avg_hours', 0)
        
        gate_30_pass = pct_under_30 <= 10.0
        gate_20_pass = pct_under_20 <= 3.0
        
        logger.info(f"  [{'PASS' if gate_30_pass else 'FAIL'}] pct_under_30: {pct_under_30:.1f}% (gate: ≤10%)")
        logger.info(f"  [{'PASS' if gate_20_pass else 'FAIL'}] pct_under_20: {pct_under_20:.1f}% (gate: ≤3%)")
        logger.info(f"  avg_hours: {avg_hours:.1f}h (target: ≥30h)")
        
        # Verification Checks
        logger.info("-" * 40)
        logger.info("VERIFICATION CHECKS:")
        
        coverage_ok = result.proof.coverage_pct == 100.0
        logger.info(f"  [{'PASS' if coverage_ok else 'FAIL'}] Coverage: {result.proof.coverage_pct:.1f}%")
        
        artificial_ok = result.proof.artificial_used_final == 0
        logger.info(f"  [{'PASS' if artificial_ok else 'FAIL'}] Artificial Final: {result.proof.artificial_used_final} (LP: {result.proof.artificial_used_lp})")
        
        # 6. Export Roster CSV
        active_days = list(by_day.keys())
        export_count = export_roster_csv(result.solution, str(roster_path), active_days)
        logger.info("-" * 40)
        logger.info(f"Exported {export_count} drivers to: {roster_path}")
        
        # 7. Save full manifest
        manifest = result.to_dict()
        manifest["input"] = {
            "total_tours": len(tours_v1),
            "by_day": dict(by_day),
        }
        manifest_path = os.path.join(artifacts_dir, "run_manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, default=str)
        logger.info(f"Full manifest saved: {manifest_path}")
        
    else:
        logger.error(f"Solve Failed: {result.status}")
        logger.error(f"Reason: {result.error_code} - {result.error_message}")
        
        # Save failure manifest
        manifest = result.to_dict()
        manifest["input"] = {
            "total_tours": len(tours_v1),
            "by_day": dict(by_day),
        }
        manifest_path = os.path.join(artifacts_dir, "run_manifest_FAIL.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, default=str)
        logger.info(f"Failure manifest saved: {manifest_path}")
    
    logger.info("=" * 70)
    logger.info("DONE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
