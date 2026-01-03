
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

# Try imports, handle missing dependencies gracefully
try:
    from src.core_v2.validator.rules import ValidatorV2
except ImportError:
    ValidatorV2 = None

try:
    from fleet_counter import compute_fleet_peaks
    FLEET_AVAILABLE = True
except ImportError:
    FLEET_AVAILABLE = False

from src.domain.models import Weekday

def _get_active_days(tours: list) -> list[str]:
    """Extract sorted active days from tours."""
    if not tours:
        return []
    unique_days = {t.day for t in tours if hasattr(t, 'day')}
    # Sort by standard week order
    day_order = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY, Weekday.SUNDAY]
    
    sorted_days = []
    for d in day_order:
        if d in unique_days:
            sorted_days.append(d.value)
    return sorted_days

def emit_best_output(
    solution: Any, 
    context: Dict[str, Any], 
    console_out: bool = True, 
    write_manifest: bool = True
) -> Dict[str, Any]:
    """
    Central One-Stop-Shop for Reporting.
    
    Args:
        solution: SetPartitionResult object (or similar structure).
        context: Dict with keys:
            - 'tours': List of Tour objects (REQUIRED for accurate active_days/fleet).
            - 'args': Parsed arguments (optional, for seed/budget).
            - 'output_dir': Path to write manifest (optional).
            - 'config': Solver config (optional).
            
    Returns:
        The constructed manifest dictionary.
    """
    tours = context.get('tours', [])
    assignments = getattr(solution, 'selected_rosters', getattr(solution, 'assignments', []))
    status = getattr(solution, 'status', 'UNKNOWN')
    kpis = getattr(solution, 'kpi', {})
    
    # 1. Active Day Analysis
    active_days = _get_active_days(tours)
    active_days_count = len(active_days)
    fte_target_hours = max(0.0, active_days_count * 8.0)
    
    # Update KPI dictionary with ground truth
    kpis['active_days'] = active_days
    kpis['active_days_count'] = active_days_count
    kpis['fte_target_hours_dynamic'] = fte_target_hours
    
    # 2. Fleet Peak (Computed from Source)
    fleet_data = {}
    if FLEET_AVAILABLE and tours:
        try:
            fs = compute_fleet_peaks(tours, turnaround_minutes=5)
            fleet_data = {
                "fleet_peak_global": fs.global_peak_count,
                "fleet_peak_day": fs.global_peak_day.value,
                "fleet_peak_time": fs.global_peak_time.strftime("%H:%M"),
                "fleet_peak_computed_from": "tour_interval_concurrency",
                "fleet_peak_by_day": {
                    d.value: {"peak": p.peak_count, "at": p.peak_time.strftime("%H:%M")}
                    for d, p in fs.day_peaks.items()
                }
            }
            kpis.update(fleet_data)
        except Exception as e:
            print(f"[WARN] Fleet calculation failed: {e}")
            
    # 3. Dynamic Utilization Analysis
    # Use dynamic threshold for stats
    drivers = assignments
    drivers_total = len(drivers)
    
    # Re-classify based on contract logic if passed, else just count
    # Caller should have handled identification, but we compute stats here
    fte_drivers = [d for d in drivers if getattr(d, 'driver_type', 'UNK') == 'FTE' or (getattr(d, 'driver_type', 'UNK') == 'UNK' and d.total_hours >= fte_target_hours)]
    pt_drivers = [d for d in drivers if d not in fte_drivers]
    
    drivers_count_fte = len(fte_drivers)
    drivers_count_pt = len(pt_drivers)
    
    # Hours Stats (FTE relevant)
    fte_hours = [d.total_hours for d in fte_drivers]
    if fte_hours:
        fte_min = min(fte_hours)
        fte_max = max(fte_hours)
        fte_avg = sum(fte_hours) / len(fte_hours)
    else:
        fte_min = fte_max = fte_avg = 0.0
        
    kpis['drivers_total'] = drivers_total
    kpis['drivers_fte'] = drivers_count_fte
    kpis['drivers_pt'] = drivers_count_pt
    kpis['fte_hours_min'] = fte_min
    kpis['fte_hours_max'] = fte_max
    kpis['fte_hours_avg'] = fte_avg
    
    # Underutilization (Dynamic Gate)
    # Count drivers < target (with small tolerance e.g. 0.1h floating point)
    underutil_threshold = fte_target_hours - 0.1
    underutil_count = sum(1 for d in drivers if d.total_hours < underutil_threshold)
    underutil_share = (underutil_count / drivers_total) if drivers_total > 0 else 0.0
    
    kpis['underutil_threshold_dynamic'] = fte_target_hours
    kpis['underutil_count_dynamic'] = underutil_count
    kpis['underutil_share_dynamic'] = underutil_share
    
    # 4. Coverage Audit (Centralized)
    audit = {}
    if ValidatorV2 and drivers and tours:
        tour_ids = {t.id for t in tours}
        audit = ValidatorV2.compute_tour_coverage_audit_full(drivers, tour_ids)
        # Flatten into KPI
        kpis['tours_total'] = audit.get('tours_total', 0)
        kpis['tours_uncovered'] = audit.get('tours_uncovered', 0)
        kpis['tours_overcovered'] = audit.get('tours_overcovered', 0)
        kpis['coverage_hash'] = audit.get('coverage_hash', 'N/A')
    
    # 5. Block Mix
    block_mix = {"1er": 0, "2er": 0, "3er": 0, "split": 0, "template": 0}
    total_blocks = 0
    for d in drivers:
        for b in d.blocks:
            total_blocks += 1
            # Infer type if not explicit
            btype = getattr(b, 'block_type', None)
            val = btype.value if hasattr(btype, 'value') else str(btype)
            
            if "1er" in val: block_mix["1er"] += 1
            elif "2er" in val: block_mix["2er"] += 1
            elif "3er" in val: block_mix["3er"] += 1
            
            if getattr(b, 'is_split', False):
                block_mix["split"] += 1
                
    kpis['block_mix_counts'] = block_mix
    
    # 6. Lexiko Telemetry (Extraction)
    # Assuming result might have lexiko info attached
    lexiko_meta = getattr(solution, 'lexiko_meta', {})
    if lexiko_meta:
        kpis['lexiko_meta'] = lexiko_meta
        
    # =========================================================================
    # CONSOLE OUTPUT (Unified Block)
    # =========================================================================
    if console_out:
        print("\n" + "="*60)
        print(f"UNIFIED RESULT REPORT (Status: {status})")
        print("="*60)
        print(f"Active Days: {active_days_count} ({', '.join(active_days)})")
        print(f"Dynamic FTE Target: {fte_target_hours:.1f}h")
        print("-" * 60)
        
        print(f"Drivers: {drivers_count_fte} FTE + {drivers_count_pt} PT = {drivers_total} Total")
        if fte_drivers:
            print(f"FTE Hours: Min={fte_min:.1f}, Max={fte_max:.1f}, Avg={fte_avg:.1f}")
            
        print(f"Utilization Gate (<{fte_target_hours:.1f}h): {underutil_count} drivers ({underutil_share:.1%})")
        
        print("-" * 60)
        if fleet_data:
            print(f"Fleet Peak: {fleet_data.get('fleet_peak_global', 0)} vehicles @ {fleet_data.get('fleet_peak_day')} {fleet_data.get('fleet_peak_time')}")
            
        if audit:
            print(f"Coverage Audit: Uncovered={audit.get('tours_uncovered')}, Overcovered={audit.get('tours_overcovered')}")
            print(f"Coverage Hash: {audit.get('coverage_hash')}")
        
        print("-" * 60)
        print(f"Blocks: 1er={block_mix['1er']}, 2er={block_mix['2er']}, 3er={block_mix['3er']} (Split: {block_mix['split']})")
        print("="*60 + "\n")

    # =========================================================================
    # MANIFEST GENERATION
    # =========================================================================
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "seed": context.get('args', {}).get('seed', 42) if isinstance(context.get('args'), dict) else getattr(context.get('args'), 'seed', 42),
        "time_budget": context.get('args', {}).get('time_budget', 0) if isinstance(context.get('args'), dict) else getattr(context.get('args'), 'time_budget', 0),
        "active_days_context": {
            "days": active_days,
            "count": active_days_count,
            "fte_target": fte_target_hours
        },
        "coverage": {
            "tours_total": kpis.get('tours_total', 0),
            "uncovered": kpis.get('tours_uncovered', 0),
            "overcovered": kpis.get('tours_overcovered', 0),
            "hash": kpis.get('coverage_hash', 'N/A')
        },
        "kpis": kpis
    }
    
    if write_manifest and context.get('output_dir'):
        out_path = Path(context['output_dir']) / "run_manifest.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            if console_out:
                print(f"[SUCCESS] Manifest written to: {out_path}")
        except Exception as e:
            print(f"[ERROR] Failed to write manifest: {e}")
            
    return manifest
