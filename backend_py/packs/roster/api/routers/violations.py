"""
SOLVEREIGN V4.6 - Roster Violations & Matrix API
=================================================

Matrix and violations endpoints for the Roster Pack.

Routes:
- GET /api/v1/roster/plans/{plan_id}/matrix     - Get roster matrix with cells
- GET /api/v1/roster/plans/{plan_id}/violations - Get violations list

VIOLATION TYPES:
- overlap: Driver assigned to overlapping shifts (BLOCK)
- rest: Insufficient rest time between shifts (WARN)
- hour_limit: Weekly/daily hour limits exceeded (WARN)
- unassigned: Tour without driver (BLOCK)

SECURITY:
- Tenant isolation via user context
- RLS enforced on all queries
"""

import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster", tags=["roster-violations"])


# =============================================================================
# SCHEMAS
# =============================================================================

class ViolationSeverity(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"
    OK = "OK"


class ViolationType(str, Enum):
    OVERLAP = "overlap"
    REST = "rest"
    HOUR_LIMIT = "hour_limit"
    UNASSIGNED = "unassigned"
    FREEZE = "freeze"


class ViolationEntry(BaseModel):
    """A single violation record."""
    id: str = Field(..., description="Unique violation ID")
    type: ViolationType
    severity: ViolationSeverity
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    tour_instance_id: Optional[int] = None
    day: Optional[int] = None
    cell_key: str = Field(..., description="Key for matrix cell lookup: 'driver_id:day'")
    message: str
    details: Optional[Dict[str, Any]] = None


class ShiftAssignment(BaseModel):
    """Shift assignment in a matrix cell."""
    tour_instance_id: int
    block_id: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: Optional[float] = None


class MatrixCell(BaseModel):
    """A single cell in the roster matrix."""
    driver_id: str
    day: int
    assignment: Optional[ShiftAssignment] = None
    is_pinned: bool = False
    severity: ViolationSeverity = ViolationSeverity.OK
    violation_codes: List[str] = Field(default_factory=list)


class DriverRow(BaseModel):
    """Driver row metadata."""
    driver_id: str
    driver_name: str
    total_hours: float = 0.0
    shift_count: int = 0


class MatrixSummary(BaseModel):
    """Summary statistics for the matrix."""
    total_drivers: int
    total_shifts: int
    unassigned_count: int
    block_count: int
    warn_count: int


class MatrixResponse(BaseModel):
    """Response from matrix endpoint."""
    success: bool = True
    plan_version_id: int
    drivers: List[DriverRow]
    days: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    cells: List[MatrixCell]
    summary: MatrixSummary


class ViolationsResponse(BaseModel):
    """Response from violations endpoint."""
    success: bool = True
    plan_version_id: int
    violations: List[ViolationEntry]
    counts: Dict[str, int]


# =============================================================================
# VIOLATION COMPUTATION
# =============================================================================

def compute_assignments_hash(assignments: List[Dict]) -> str:
    """Compute hash of assignments for cache invalidation."""
    sorted_assignments = sorted(assignments, key=lambda a: (a.get("driver_id", ""), a.get("day", 0)))
    payload = json.dumps(sorted_assignments, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def compute_violations(
    assignments: List[Dict],
    drivers: Dict[str, Dict],
    min_rest_hours: int = 11,
    max_weekly_hours: int = 48,
) -> List[Dict]:
    """
    Compute all violations for a plan.

    Violation Types:
    1. OVERLAP: Same driver assigned to overlapping shifts (BLOCK)
    2. REST: Insufficient rest time between shifts (WARN)
    3. HOUR_LIMIT: Weekly hour limits exceeded (WARN)
    4. UNASSIGNED: Tour without driver (BLOCK)
    """
    violations = []
    violation_id = 0

    # Group assignments by driver
    by_driver: Dict[str, List[Dict]] = {}
    for asgn in assignments:
        driver_id = asgn.get("driver_id")
        if driver_id:
            if driver_id not in by_driver:
                by_driver[driver_id] = []
            by_driver[driver_id].append(asgn)

    for driver_id, driver_assignments in by_driver.items():
        driver_name = drivers.get(driver_id, {}).get("name", driver_id)

        # Sort by day and start time
        sorted_assignments = sorted(
            driver_assignments,
            key=lambda a: (a.get("day", 0), a.get("start_ts") or "")
        )

        # Check overlaps within same day
        for i, a1 in enumerate(sorted_assignments):
            for a2 in sorted_assignments[i+1:]:
                if a1.get("day") == a2.get("day"):
                    # Check time overlap
                    s1, e1 = a1.get("start_ts"), a1.get("end_ts")
                    s2, e2 = a2.get("start_ts"), a2.get("end_ts")

                    if s1 and e1 and s2 and e2:
                        try:
                            t1s = datetime.fromisoformat(str(s1).replace('Z', '+00:00')) if isinstance(s1, str) else s1
                            t1e = datetime.fromisoformat(str(e1).replace('Z', '+00:00')) if isinstance(e1, str) else e1
                            t2s = datetime.fromisoformat(str(s2).replace('Z', '+00:00')) if isinstance(s2, str) else s2
                            t2e = datetime.fromisoformat(str(e2).replace('Z', '+00:00')) if isinstance(e2, str) else e2

                            if not (t1e <= t2s or t1s >= t2e):
                                violation_id += 1
                                violations.append({
                                    "id": f"v_{violation_id}",
                                    "type": ViolationType.OVERLAP,
                                    "severity": ViolationSeverity.BLOCK,
                                    "driver_id": driver_id,
                                    "driver_name": driver_name,
                                    "tour_instance_id": a1.get("tour_instance_id"),
                                    "day": a1.get("day"),
                                    "cell_key": f"{driver_id}:{a1.get('day')}",
                                    "message": f"Driver {driver_name} has overlapping shifts on day {a1.get('day')}",
                                    "details": {
                                        "shift_1": {"tour_id": a1.get("tour_instance_id"), "start": str(s1), "end": str(e1)},
                                        "shift_2": {"tour_id": a2.get("tour_instance_id"), "start": str(s2), "end": str(e2)},
                                    },
                                })
                        except (ValueError, TypeError):
                            pass

        # Check rest time between consecutive shifts
        timed = []
        for a in sorted_assignments:
            if a.get("start_ts") and a.get("end_ts"):
                try:
                    start = datetime.fromisoformat(str(a["start_ts"]).replace('Z', '+00:00')) if isinstance(a["start_ts"], str) else a["start_ts"]
                    end = datetime.fromisoformat(str(a["end_ts"]).replace('Z', '+00:00')) if isinstance(a["end_ts"], str) else a["end_ts"]
                    timed.append({"asgn": a, "start": start, "end": end})
                except (ValueError, TypeError):
                    pass

        timed.sort(key=lambda x: x["start"])

        for i in range(len(timed) - 1):
            curr_end = timed[i]["end"]
            next_start = timed[i + 1]["start"]
            rest_hours = (next_start - curr_end).total_seconds() / 3600

            if rest_hours < min_rest_hours:
                violation_id += 1
                violations.append({
                    "id": f"v_{violation_id}",
                    "type": ViolationType.REST,
                    "severity": ViolationSeverity.WARN,
                    "driver_id": driver_id,
                    "driver_name": driver_name,
                    "tour_instance_id": timed[i + 1]["asgn"].get("tour_instance_id"),
                    "day": timed[i + 1]["asgn"].get("day"),
                    "cell_key": f"{driver_id}:{timed[i + 1]['asgn'].get('day')}",
                    "message": f"Driver {driver_name} has only {rest_hours:.1f}h rest (min: {min_rest_hours}h)",
                    "details": {
                        "rest_hours": round(rest_hours, 1),
                        "min_required": min_rest_hours,
                        "prev_shift_end": str(curr_end),
                        "next_shift_start": str(next_start),
                    },
                })

        # Check weekly hours
        weekly_minutes = sum(
            (a.get("duration_min") or 0) for a in driver_assignments
        )
        # If duration_min not available, estimate from timestamps
        if weekly_minutes == 0:
            for a in timed:
                weekly_minutes += (a["end"] - a["start"]).total_seconds() / 60

        weekly_hours = weekly_minutes / 60
        if weekly_hours > max_weekly_hours:
            violation_id += 1
            violations.append({
                "id": f"v_{violation_id}",
                "type": ViolationType.HOUR_LIMIT,
                "severity": ViolationSeverity.WARN,
                "driver_id": driver_id,
                "driver_name": driver_name,
                "tour_instance_id": None,
                "day": None,
                "cell_key": f"{driver_id}:week",
                "message": f"Driver {driver_name} has {weekly_hours:.1f}h/week (limit: {max_weekly_hours}h)",
                "details": {
                    "weekly_hours": round(weekly_hours, 1),
                    "max_allowed": max_weekly_hours,
                },
            })

    return violations


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/plans/{plan_id}/matrix", response_model=MatrixResponse)
async def get_matrix(
    request: Request,
    plan_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get roster matrix for a plan.

    Returns a grid of driver × day cells with:
    - Assignment details (tour, times)
    - Pin status
    - Severity (BLOCK/WARN/OK)
    - Violation codes
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify plan exists and is accessible
        cur.execute(
            """
            SELECT id, tenant_id, site_id, plan_state, status
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found or access denied",
            )

        # Load all assignments
        cur.execute(
            """
            SELECT
                a.id, a.driver_id, a.tour_instance_id, a.day, a.block_id,
                ti.start_ts, ti.end_ts, ti.duration_min
            FROM assignments a
            LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
            ORDER BY a.driver_id, a.day
            """,
            (plan_id,)
        )
        assignments_raw = cur.fetchall()

        # Load drivers
        cur.execute(
            """
            SELECT DISTINCT d.id, d.name
            FROM drivers d
            JOIN assignments a ON a.driver_id = d.id::text
            WHERE a.plan_version_id = %s
            """,
            (plan_id,)
        )
        drivers_raw = cur.fetchall()
        drivers_map = {str(row[0]): {"id": str(row[0]), "name": row[1]} for row in drivers_raw}

        # Load pins
        cur.execute(
            """
            SELECT driver_id, tour_instance_id, day
            FROM roster.pins
            WHERE plan_version_id = %s AND tenant_id = %s AND is_active = TRUE
            """,
            (plan_id, ctx.tenant_id)
        )
        pins_raw = cur.fetchall()
        pinned_keys = {f"{row[0]}:{row[1]}:{row[2]}" for row in pins_raw}

    # Build assignments list
    assignments = []
    for row in assignments_raw:
        assignments.append({
            "assignment_id": row[0],
            "driver_id": row[1],
            "tour_instance_id": row[2],
            "day": row[3],
            "block_id": row[4],
            "start_ts": row[5],
            "end_ts": row[6],
            "duration_min": row[7],
        })

    # Compute violations
    violations = compute_violations(assignments, drivers_map)

    # Build violation lookup by cell_key
    violations_by_cell: Dict[str, List[Dict]] = {}
    for v in violations:
        cell_key = v["cell_key"]
        if cell_key not in violations_by_cell:
            violations_by_cell[cell_key] = []
        violations_by_cell[cell_key].append(v)

    # Build driver rows and cells
    driver_rows = []
    cells = []
    driver_stats: Dict[str, Dict] = {}

    for asgn in assignments:
        driver_id = asgn["driver_id"]
        day = asgn["day"]

        # Update driver stats
        if driver_id not in driver_stats:
            driver_stats[driver_id] = {
                "total_hours": 0,
                "shift_count": 0,
            }

        duration_hours = (asgn.get("duration_min") or 0) / 60
        if duration_hours == 0 and asgn.get("start_ts") and asgn.get("end_ts"):
            try:
                start = asgn["start_ts"]
                end = asgn["end_ts"]
                if isinstance(start, str):
                    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                if isinstance(end, str):
                    end = datetime.fromisoformat(end.replace('Z', '+00:00'))
                duration_hours = (end - start).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        driver_stats[driver_id]["total_hours"] += duration_hours
        driver_stats[driver_id]["shift_count"] += 1

        # Build cell
        cell_key = f"{driver_id}:{day}"
        pin_key = f"{driver_id}:{asgn['tour_instance_id']}:{day}"
        is_pinned = pin_key in pinned_keys

        # Determine severity
        cell_violations = violations_by_cell.get(cell_key, [])
        has_block = any(v["severity"] == ViolationSeverity.BLOCK for v in cell_violations)
        has_warn = any(v["severity"] == ViolationSeverity.WARN for v in cell_violations)

        if has_block:
            severity = ViolationSeverity.BLOCK
        elif has_warn:
            severity = ViolationSeverity.WARN
        else:
            severity = ViolationSeverity.OK

        cells.append(MatrixCell(
            driver_id=driver_id,
            day=day,
            assignment=ShiftAssignment(
                tour_instance_id=asgn["tour_instance_id"],
                block_id=asgn["block_id"],
                start_time=str(asgn["start_ts"]) if asgn["start_ts"] else None,
                end_time=str(asgn["end_ts"]) if asgn["end_ts"] else None,
                hours=round(duration_hours, 1) if duration_hours > 0 else None,
            ),
            is_pinned=is_pinned,
            severity=severity,
            violation_codes=[v["type"] for v in cell_violations],
        ))

    # Build driver rows
    for driver_id, stats in driver_stats.items():
        driver_name = drivers_map.get(driver_id, {}).get("name", driver_id)
        driver_rows.append(DriverRow(
            driver_id=driver_id,
            driver_name=driver_name,
            total_hours=round(stats["total_hours"], 1),
            shift_count=stats["shift_count"],
        ))

    # Sort driver rows by name
    driver_rows.sort(key=lambda d: d.driver_name)

    # Count violations
    block_count = sum(1 for v in violations if v["severity"] == ViolationSeverity.BLOCK)
    warn_count = sum(1 for v in violations if v["severity"] == ViolationSeverity.WARN)

    # Count unassigned tours
    assigned_tours = {asgn["tour_instance_id"] for asgn in assignments}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM tour_instances ti
            JOIN forecast_versions fv ON ti.forecast_version_id = fv.id
            JOIN plan_versions pv ON pv.forecast_version_id = fv.id
            WHERE pv.id = %s AND ti.id NOT IN %s
            """,
            (plan_id, tuple(assigned_tours) if assigned_tours else (0,))
        )
        unassigned_count = cur.fetchone()[0] or 0

    summary = MatrixSummary(
        total_drivers=len(driver_rows),
        total_shifts=len(assignments),
        unassigned_count=unassigned_count,
        block_count=block_count,
        warn_count=warn_count,
    )

    logger.info(
        "matrix_loaded",
        extra={
            "plan_id": plan_id,
            "drivers": len(driver_rows),
            "cells": len(cells),
            "blocks": block_count,
            "warns": warn_count,
            "tenant_id": ctx.tenant_id,
        }
    )

    return MatrixResponse(
        success=True,
        plan_version_id=plan_id,
        drivers=driver_rows,
        days=[1, 2, 3, 4, 5, 6, 7],
        cells=cells,
        summary=summary,
    )


@router.get("/plans/{plan_id}/violations", response_model=ViolationsResponse)
async def get_violations(
    request: Request,
    plan_id: int,
    severity: Optional[str] = Query(None, description="Filter by severity: BLOCK, WARN"),
    type_filter: Optional[str] = Query(None, alias="type", description="Filter by type: overlap, rest, hour_limit, unassigned"),
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get violations list for a plan.

    Violation types:
    - overlap: Driver assigned to overlapping shifts (BLOCK)
    - rest: Insufficient rest time between shifts (WARN)
    - hour_limit: Weekly hour limits exceeded (WARN)
    - unassigned: Tour without driver (BLOCK)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify plan exists
        cur.execute(
            """
            SELECT id, tenant_id FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found or access denied",
            )

        # Load assignments
        cur.execute(
            """
            SELECT
                a.id, a.driver_id, a.tour_instance_id, a.day, a.block_id,
                ti.start_ts, ti.end_ts, ti.duration_min
            FROM assignments a
            LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
            ORDER BY a.driver_id, a.day
            """,
            (plan_id,)
        )
        assignments_raw = cur.fetchall()

        # Load drivers
        cur.execute(
            """
            SELECT DISTINCT d.id, d.name
            FROM drivers d
            JOIN assignments a ON a.driver_id = d.id::text
            WHERE a.plan_version_id = %s
            """,
            (plan_id,)
        )
        drivers_raw = cur.fetchall()
        drivers_map = {str(row[0]): {"id": str(row[0]), "name": row[1]} for row in drivers_raw}

    # Build assignments list
    assignments = []
    for row in assignments_raw:
        assignments.append({
            "assignment_id": row[0],
            "driver_id": row[1],
            "tour_instance_id": row[2],
            "day": row[3],
            "block_id": row[4],
            "start_ts": row[5],
            "end_ts": row[6],
            "duration_min": row[7],
        })

    # Compute violations
    violations = compute_violations(assignments, drivers_map)

    # Check for unassigned tours
    assigned_tours = {asgn["tour_instance_id"] for asgn in assignments}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ti.id, ti.day, ti.block_id
            FROM tour_instances ti
            JOIN forecast_versions fv ON ti.forecast_version_id = fv.id
            JOIN plan_versions pv ON pv.forecast_version_id = fv.id
            WHERE pv.id = %s AND ti.id NOT IN %s
            """,
            (plan_id, tuple(assigned_tours) if assigned_tours else (0,))
        )
        unassigned_tours = cur.fetchall()

    # Add unassigned violations
    for tour in unassigned_tours:
        violations.append({
            "id": f"v_unassigned_{tour[0]}",
            "type": ViolationType.UNASSIGNED,
            "severity": ViolationSeverity.BLOCK,
            "driver_id": None,
            "driver_name": None,
            "tour_instance_id": tour[0],
            "day": tour[1],
            "cell_key": f"unassigned:{tour[1]}",
            "message": f"Tour {tour[0]} ({tour[2]}) has no driver assigned",
            "details": {
                "tour_id": tour[0],
                "block_id": tour[2],
            },
        })

    # Apply filters
    if severity:
        violations = [v for v in violations if v["severity"] == severity.upper()]
    if type_filter:
        violations = [v for v in violations if v["type"] == type_filter]

    # Sort: BLOCK first, then WARN, then by day
    def sort_key(v):
        severity_order = {"BLOCK": 0, "WARN": 1, "OK": 2}
        return (severity_order.get(v["severity"], 3), v.get("day") or 0, v.get("driver_id") or "")

    violations.sort(key=sort_key)

    # Count by type and severity
    counts = {
        "block": sum(1 for v in violations if v["severity"] == ViolationSeverity.BLOCK),
        "warn": sum(1 for v in violations if v["severity"] == ViolationSeverity.WARN),
        "overlap": sum(1 for v in violations if v["type"] == ViolationType.OVERLAP),
        "rest": sum(1 for v in violations if v["type"] == ViolationType.REST),
        "hour_limit": sum(1 for v in violations if v["type"] == ViolationType.HOUR_LIMIT),
        "unassigned": sum(1 for v in violations if v["type"] == ViolationType.UNASSIGNED),
        "total": len(violations),
    }

    logger.info(
        "violations_computed",
        extra={
            "plan_id": plan_id,
            "total": counts["total"],
            "blocks": counts["block"],
            "warns": counts["warn"],
            "tenant_id": ctx.tenant_id,
        }
    )

    return ViolationsResponse(
        success=True,
        plan_version_id=plan_id,
        violations=[ViolationEntry(**v) for v in violations],
        counts=counts,
    )
