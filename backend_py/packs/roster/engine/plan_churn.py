"""
SOLVEREIGN V3 - Plan Churn KPI Calculator
==========================================

Measures plan stability between versions by computing:
- Changed assignments
- Affected drivers
- Stability score (% unchanged)
- Churn rate

Usage:
    from packs.roster.engine.plan_churn import compute_plan_churn

    churn = compute_plan_churn(old_plan_id=1, new_plan_id=2)
    print(f"Stability: {churn['stability_percent']:.1f}%")
    print(f"Affected drivers: {churn['affected_drivers']}")
"""

from typing import Optional
from collections import defaultdict


def compute_plan_churn(
    old_assignments: list[dict],
    new_assignments: list[dict]
) -> dict:
    """
    Compute churn metrics between two sets of assignments.

    Args:
        old_assignments: Previous plan assignments
        new_assignments: New plan assignments

    Returns:
        dict with churn metrics:
            - total_old: Total assignments in old plan
            - total_new: Total assignments in new plan
            - unchanged: Assignments that stayed the same
            - added: New assignments (tour_instance not in old)
            - removed: Removed assignments (tour_instance not in new)
            - changed: Same tour_instance, different driver
            - affected_drivers: Set of drivers with any change
            - affected_tours: Set of tour instances with any change
            - stability_percent: % unchanged (0-100)
            - churn_rate: % changed (0-100)
    """
    # Build lookup by tour_instance_id
    old_by_tour = {a["tour_instance_id"]: a for a in old_assignments}
    new_by_tour = {a["tour_instance_id"]: a for a in new_assignments}

    old_tour_ids = set(old_by_tour.keys())
    new_tour_ids = set(new_by_tour.keys())

    # Categorize changes
    added_ids = new_tour_ids - old_tour_ids
    removed_ids = old_tour_ids - new_tour_ids
    common_ids = old_tour_ids & new_tour_ids

    unchanged = 0
    changed = 0
    changed_details = []
    affected_drivers = set()

    for tour_id in common_ids:
        old_a = old_by_tour[tour_id]
        new_a = new_by_tour[tour_id]

        if old_a["driver_id"] == new_a["driver_id"]:
            unchanged += 1
        else:
            changed += 1
            changed_details.append({
                "tour_instance_id": tour_id,
                "old_driver": old_a["driver_id"],
                "new_driver": new_a["driver_id"],
                "day": new_a.get("day")
            })
            affected_drivers.add(old_a["driver_id"])
            affected_drivers.add(new_a["driver_id"])

    # Drivers affected by added/removed tours
    for tour_id in added_ids:
        affected_drivers.add(new_by_tour[tour_id]["driver_id"])
    for tour_id in removed_ids:
        affected_drivers.add(old_by_tour[tour_id]["driver_id"])

    # Calculate metrics
    total_old = len(old_assignments)
    total_new = len(new_assignments)
    total_common = len(common_ids)

    if total_common > 0:
        stability_percent = 100.0 * unchanged / total_common
        churn_rate = 100.0 * changed / total_common
    else:
        stability_percent = 0.0 if total_new > 0 else 100.0
        churn_rate = 100.0 if total_new > 0 else 0.0

    # Affected tours
    affected_tours = added_ids | removed_ids | {d["tour_instance_id"] for d in changed_details}

    return {
        "total_old": total_old,
        "total_new": total_new,
        "total_common": total_common,
        "unchanged": unchanged,
        "added": len(added_ids),
        "removed": len(removed_ids),
        "changed": changed,
        "changed_details": changed_details,
        "affected_drivers": list(affected_drivers),
        "affected_drivers_count": len(affected_drivers),
        "affected_tours": list(affected_tours),
        "affected_tours_count": len(affected_tours),
        "stability_percent": round(stability_percent, 2),
        "churn_rate": round(churn_rate, 2),
    }


def compute_plan_churn_from_db(
    old_plan_id: int,
    new_plan_id: int
) -> dict:
    """
    Compute churn between two plan versions from database.

    Args:
        old_plan_id: Previous plan version ID
        new_plan_id: New plan version ID

    Returns:
        Churn metrics dict
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from packs.roster.engine.db_instances import get_assignments_with_instances

    old_assignments = get_assignments_with_instances(old_plan_id)
    new_assignments = get_assignments_with_instances(new_plan_id)

    churn = compute_plan_churn(old_assignments, new_assignments)
    churn["old_plan_id"] = old_plan_id
    churn["new_plan_id"] = new_plan_id

    return churn


def get_driver_change_summary(churn: dict) -> list[dict]:
    """
    Get per-driver change summary from churn data.

    Args:
        churn: Churn metrics dict

    Returns:
        List of driver change records
    """
    driver_changes = defaultdict(lambda: {"gained": 0, "lost": 0, "reassigned_to": 0, "reassigned_from": 0})

    for detail in churn.get("changed_details", []):
        old_driver = detail["old_driver"]
        new_driver = detail["new_driver"]
        driver_changes[old_driver]["reassigned_from"] += 1
        driver_changes[new_driver]["reassigned_to"] += 1

    return [
        {
            "driver_id": driver_id,
            **changes
        }
        for driver_id, changes in sorted(driver_changes.items())
    ]


# Test
if __name__ == "__main__":
    print("Plan Churn Calculator - Test")
    print("=" * 50)

    # Test data
    old = [
        {"tour_instance_id": 1, "driver_id": "D001", "day": 1},
        {"tour_instance_id": 2, "driver_id": "D001", "day": 1},
        {"tour_instance_id": 3, "driver_id": "D002", "day": 2},
        {"tour_instance_id": 4, "driver_id": "D002", "day": 2},
        {"tour_instance_id": 5, "driver_id": "D003", "day": 3},  # Will be removed
    ]

    new = [
        {"tour_instance_id": 1, "driver_id": "D001", "day": 1},  # Unchanged
        {"tour_instance_id": 2, "driver_id": "D004", "day": 1},  # Changed driver
        {"tour_instance_id": 3, "driver_id": "D002", "day": 2},  # Unchanged
        {"tour_instance_id": 4, "driver_id": "D001", "day": 2},  # Changed driver
        {"tour_instance_id": 6, "driver_id": "D003", "day": 3},  # New tour
    ]

    churn = compute_plan_churn(old, new)

    print(f"Total Old: {churn['total_old']}")
    print(f"Total New: {churn['total_new']}")
    print(f"Unchanged: {churn['unchanged']}")
    print(f"Changed: {churn['changed']}")
    print(f"Added: {churn['added']}")
    print(f"Removed: {churn['removed']}")
    print(f"Stability: {churn['stability_percent']:.1f}%")
    print(f"Churn Rate: {churn['churn_rate']:.1f}%")
    print(f"Affected Drivers: {churn['affected_drivers']}")
    print()
    print("Test PASSED")
