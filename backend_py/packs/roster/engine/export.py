"""
SOLVEREIGN V3 Export Module
============================

Export released plans to CSV/JSON formats.
All exports include plan_version_id for traceability.

Usage:
    from packs.roster.engine.export import export_plan_to_csv, export_plan_to_json, export_release_package

    # Export single format
    export_plan_to_csv(plan_version_id=1, output_dir="exports/")
    export_plan_to_json(plan_version_id=1, output_dir="exports/")

    # Export complete release package
    export_release_package(plan_version_id=1, output_dir="exports/")
"""

import csv
import json
import os
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional
from collections import defaultdict

from . import db
from .db_instances import get_tour_instances


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime, date, time, and Decimal types."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.strftime("%H:%M:%S")
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _ensure_dir(path: str) -> None:
    """Create directory if it doesn't exist."""
    if path and not os.path.exists(path):
        os.makedirs(path)


def _get_plan_metadata(plan_version_id: int) -> dict:
    """Get plan version metadata including forecast info."""
    plan = db.get_plan_version(plan_version_id)
    if not plan:
        raise ValueError(f"Plan version {plan_version_id} not found")

    forecast = db.get_forecast_version(plan["forecast_version_id"])

    return {
        "plan_version_id": plan_version_id,
        "forecast_version_id": plan["forecast_version_id"],
        "status": plan["status"],
        "seed": plan["seed"],
        "solver_config_hash": plan["solver_config_hash"],
        "output_hash": plan["output_hash"],
        "created_at": plan["created_at"],
        "locked_at": plan.get("locked_at"),
        "locked_by": plan.get("locked_by"),
        "week_anchor_date": forecast.get("week_anchor_date") if forecast else None,
        "input_hash": forecast.get("input_hash") if forecast else None,
        "export_timestamp": datetime.now().isoformat()
    }


def _build_driver_schedules(plan_version_id: int) -> dict:
    """Build driver schedules from assignments."""
    assignments = db.get_assignments(plan_version_id)
    if not assignments:
        return {}

    # Get plan info for forecast_version_id
    plan = db.get_plan_version(plan_version_id)
    forecast_version_id = plan["forecast_version_id"]

    # Get all tour instances for this forecast
    instances = get_tour_instances(forecast_version_id)
    instance_lookup = {inst["id"]: inst for inst in instances}

    # Group assignments by driver
    driver_schedules = defaultdict(lambda: {
        "driver_id": None,
        "total_hours": 0.0,
        "total_tours": 0,
        "days_worked": set(),
        "blocks": [],
        "assignments": []
    })

    for a in assignments:
        driver_id = a["driver_id"]
        driver_schedules[driver_id]["driver_id"] = driver_id

        # Get instance details
        inst = instance_lookup.get(a["tour_instance_id"], {})

        # Build assignment record
        assignment_record = {
            "tour_instance_id": a["tour_instance_id"],
            "day": a["day"],
            "block_id": a["block_id"],
            "start_time": inst.get("start_ts"),
            "end_time": inst.get("end_ts"),
            "duration_min": inst.get("duration_min", 0),
            "work_hours": float(inst.get("work_hours", 0)),
            "crosses_midnight": inst.get("crosses_midnight", False),
            "depot": inst.get("depot"),
            "skill": inst.get("skill")
        }

        driver_schedules[driver_id]["assignments"].append(assignment_record)
        driver_schedules[driver_id]["total_hours"] += float(inst.get("work_hours", 0))
        driver_schedules[driver_id]["total_tours"] += 1
        driver_schedules[driver_id]["days_worked"].add(a["day"])

    # Convert sets to lists and compute block info
    for driver_id, schedule in driver_schedules.items():
        schedule["days_worked"] = sorted(list(schedule["days_worked"]))
        schedule["days_count"] = len(schedule["days_worked"])

        # Group by block_id
        blocks = defaultdict(list)
        for a in schedule["assignments"]:
            blocks[a["block_id"]].append(a)
        schedule["blocks"] = [
            {
                "block_id": block_id,
                "day": assignments[0]["day"],
                "tours": len(assignments),
                "total_hours": sum(a["work_hours"] for a in assignments)
            }
            for block_id, assignments in blocks.items()
        ]

    return dict(driver_schedules)


def _compute_kpis(plan_version_id: int, driver_schedules: dict) -> dict:
    """Compute KPIs from driver schedules."""
    if not driver_schedules:
        return {
            "total_drivers": 0,
            "fte_drivers": 0,
            "pt_drivers": 0,
            "pt_ratio": 0.0,
            "total_tours": 0,
            "total_hours": 0.0,
            "avg_hours_per_driver": 0.0,
            "block_mix": {"3er": 0, "2er_reg": 0, "2er_split": 0, "1er": 0}
        }

    total_drivers = len(driver_schedules)
    total_hours = sum(s["total_hours"] for s in driver_schedules.values())
    total_tours = sum(s["total_tours"] for s in driver_schedules.values())

    # FTE = 40+ hours, PT = <40 hours
    fte_drivers = sum(1 for s in driver_schedules.values() if s["total_hours"] >= 40)
    pt_drivers = total_drivers - fte_drivers

    # Block mix (from block sizes)
    block_mix = {"3er": 0, "2er_reg": 0, "2er_split": 0, "1er": 0}
    for schedule in driver_schedules.values():
        for block in schedule["blocks"]:
            if block["tours"] >= 3:
                block_mix["3er"] += 1
            elif block["tours"] == 2:
                # Determine if split based on break duration
                block_mix["2er_reg"] += 1  # Default to regular
            else:
                block_mix["1er"] += 1

    return {
        "total_drivers": total_drivers,
        "fte_drivers": fte_drivers,
        "pt_drivers": pt_drivers,
        "pt_ratio": round(pt_drivers / total_drivers * 100, 2) if total_drivers > 0 else 0.0,
        "total_tours": total_tours,
        "total_hours": round(total_hours, 2),
        "avg_hours_per_driver": round(total_hours / total_drivers, 2) if total_drivers > 0 else 0.0,
        "block_mix": block_mix
    }


def export_matrix_csv(plan_version_id: int, output_dir: str = "") -> str:
    """
    Export roster matrix to CSV (driver x day grid).

    Returns:
        Path to exported file
    """
    _ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"matrix_pv{plan_version_id}.csv")

    assignments = db.get_assignments(plan_version_id)
    if not assignments:
        raise ValueError(f"No assignments found for plan_version {plan_version_id}")

    # Get plan info for forecast_version_id
    plan = db.get_plan_version(plan_version_id)
    instances = get_tour_instances(plan["forecast_version_id"])
    instance_lookup = {inst["id"]: inst for inst in instances}

    # Build driver x day matrix
    drivers = sorted(set(a["driver_id"] for a in assignments))
    days = [1, 2, 3, 4, 5, 6, 7]  # Mo-So
    day_names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    # Group assignments by driver and day
    matrix = defaultdict(lambda: defaultdict(list))
    for a in assignments:
        inst = instance_lookup.get(a["tour_instance_id"], {})
        start = inst.get("start_ts")
        end = inst.get("end_ts")
        if start and end:
            time_str = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        else:
            time_str = a["block_id"]
        matrix[a["driver_id"]][a["day"]].append(time_str)

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header with metadata
        writer.writerow([f"# plan_version_id: {plan_version_id}"])
        writer.writerow([f"# exported_at: {datetime.now().isoformat()}"])
        writer.writerow([])

        # Column headers
        writer.writerow(["Driver"] + day_names + ["Total Hours"])

        # Data rows
        for driver_id in drivers:
            row = [driver_id]
            total_hours = 0
            for day in days:
                tours = matrix[driver_id].get(day, [])
                if tours:
                    row.append(" | ".join(tours))
                    # Estimate hours from tour count (simplified)
                    total_hours += len(tours) * 4.5  # Approximate
                else:
                    row.append("")
            row.append(f"{total_hours:.1f}")
            writer.writerow(row)

    return output_path


def export_rosters_csv(plan_version_id: int, output_dir: str = "") -> str:
    """
    Export per-driver rosters to CSV (detailed view).

    Returns:
        Path to exported file
    """
    _ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"rosters_pv{plan_version_id}.csv")

    driver_schedules = _build_driver_schedules(plan_version_id)
    if not driver_schedules:
        raise ValueError(f"No assignments found for plan_version {plan_version_id}")

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header with metadata
        writer.writerow([f"# plan_version_id: {plan_version_id}"])
        writer.writerow([f"# exported_at: {datetime.now().isoformat()}"])
        writer.writerow([])

        # Column headers
        writer.writerow([
            "Driver", "Day", "Block", "Start", "End",
            "Duration (min)", "Work Hours", "Depot", "Cross-Midnight"
        ])

        # Data rows
        for driver_id in sorted(driver_schedules.keys()):
            schedule = driver_schedules[driver_id]
            for a in sorted(schedule["assignments"], key=lambda x: (x["day"], str(x["start_time"] or ""))):
                writer.writerow([
                    driver_id,
                    a["day"],
                    a["block_id"],
                    a["start_time"].strftime("%H:%M") if a["start_time"] else "",
                    a["end_time"].strftime("%H:%M") if a["end_time"] else "",
                    a["duration_min"],
                    a["work_hours"],
                    a["depot"] or "",
                    "Yes" if a["crosses_midnight"] else "No"
                ])

    return output_path


def export_kpis_json(plan_version_id: int, output_dir: str = "") -> str:
    """
    Export KPIs to JSON.

    Returns:
        Path to exported file
    """
    _ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"kpis_pv{plan_version_id}.json")

    driver_schedules = _build_driver_schedules(plan_version_id)
    kpis = _compute_kpis(plan_version_id, driver_schedules)

    # Add metadata
    kpis["plan_version_id"] = plan_version_id
    kpis["exported_at"] = datetime.now().isoformat()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(kpis, f, indent=2, cls=JSONEncoder)

    return output_path


def export_metadata_json(plan_version_id: int, output_dir: str = "") -> str:
    """
    Export plan metadata to JSON (all hashes and version info).

    Returns:
        Path to exported file
    """
    _ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"metadata_pv{plan_version_id}.json")

    metadata = _get_plan_metadata(plan_version_id)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, cls=JSONEncoder)

    return output_path


def export_audit_json(plan_version_id: int, output_dir: str = "") -> str:
    """
    Export audit results to JSON.

    Returns:
        Path to exported file
    """
    _ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"audit_pv{plan_version_id}.json")

    audits = db.get_audit_logs(plan_version_id)

    audit_results = {
        "plan_version_id": plan_version_id,
        "exported_at": datetime.now().isoformat(),
        "checks": []
    }

    for audit in audits:
        audit_results["checks"].append({
            "check_name": audit["check_name"],
            "status": audit["status"],
            "violation_count": audit.get("violation_count", audit.get("count", 0)),
            "details": audit.get("details_json", audit.get("details", {})),
            "created_at": audit.get("created_at")
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2, cls=JSONEncoder)

    return output_path


def export_release_package(
    plan_version_id: int,
    output_dir: str = "exports",
    include_audit: bool = True
) -> dict:
    """
    Export complete release package (all formats).

    Args:
        plan_version_id: Plan version to export
        output_dir: Output directory (default: "exports")
        include_audit: Include audit results in package (default: True)

    Returns:
        Dict with paths to all exported files
    """
    # Verify plan exists and is LOCKED
    plan = db.get_plan_version(plan_version_id)
    if not plan:
        raise ValueError(f"Plan version {plan_version_id} not found")

    if plan["status"] != "LOCKED":
        print(f"[WARN] Plan {plan_version_id} is not LOCKED (status={plan['status']}). Exporting anyway.")

    # Create output directory with plan version
    package_dir = os.path.join(output_dir, f"release_pv{plan_version_id}")
    _ensure_dir(package_dir)

    # Export all formats
    exported_files = {
        "matrix_csv": export_matrix_csv(plan_version_id, package_dir),
        "rosters_csv": export_rosters_csv(plan_version_id, package_dir),
        "kpis_json": export_kpis_json(plan_version_id, package_dir),
        "metadata_json": export_metadata_json(plan_version_id, package_dir)
    }

    if include_audit:
        exported_files["audit_json"] = export_audit_json(plan_version_id, package_dir)

    # Create manifest
    manifest = {
        "plan_version_id": plan_version_id,
        "status": plan["status"],
        "exported_at": datetime.now().isoformat(),
        "files": {
            k: os.path.basename(v) for k, v in exported_files.items()
        }
    }

    manifest_path = os.path.join(package_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    exported_files["manifest_json"] = manifest_path

    print(f"[OK] Release package exported to: {package_dir}")
    for name, path in exported_files.items():
        print(f"   - {name}: {os.path.basename(path)}")

    return exported_files


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for exporting plans."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m v3.export <plan_version_id> [output_dir]")
        print("   Example: python -m v3.export 1 exports/")
        sys.exit(1)

    plan_version_id = int(sys.argv[1])
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "exports"

    print(f"Exporting plan_version {plan_version_id}...")
    try:
        files = export_release_package(plan_version_id, output_dir)
        print(f"\n[SUCCESS] Exported {len(files)} files")
    except Exception as e:
        print(f"[ERROR] Export failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
