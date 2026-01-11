"""
SOLVEREIGN V4.8.1 - Roster Repair API (Hardened)
=================================================

Repair endpoints for handling disruptions (absences/sick calls).

Routes:
- POST /api/v1/roster/repair/preview  - Preview repair changes (deterministic)
- POST /api/v1/roster/repair/commit   - Commit repair as new plan version

HARDENING (V4.8.1):
- DB-backed idempotency (core.idempotency_keys)
- Overlap validation at repair layer
- Violations list in response
- Clear verdict semantics (freeze=BLOCK, overlap=BLOCK, rest=WARN)

NON-NEGOTIABLES:
- Tenant isolation via user context (NEVER from headers)
- CSRF check on commits
- Idempotency key required on commits (DB source of truth)
- Deterministic: same inputs => same outputs (seeded)
- Evidence + audit on both preview and commit

GUARDRAIL: NO SOLVER MODIFICATIONS - only orchestration layer.
"""

import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_csrf_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster/repair", tags=["roster-repair"])


# =============================================================================
# SCHEMAS
# =============================================================================

class AbsenceEntry(BaseModel):
    """Single absence record."""
    driver_id: int = Field(..., description="Driver ID that is absent")
    from_ts: str = Field(..., alias="from", description="Absence start ISO timestamp")
    to_ts: str = Field(..., alias="to", description="Absence end ISO timestamp")
    reason: str = Field("SICK", description="Absence reason: SICK, VACATION, UNAVAILABLE")

    class Config:
        populate_by_name = True


class RepairPreviewRequest(BaseModel):
    """Request to preview a repair."""
    base_plan_version_id: int = Field(..., description="Plan version to repair from")
    absences: List[AbsenceEntry] = Field(..., min_length=1, description="List of absences")
    objective: str = Field("min_churn", description="Repair objective: min_churn, balanced")
    seed: int = Field(94, description="Random seed for deterministic tie-breaking")


class AssignmentDiff(BaseModel):
    """A single assignment change."""
    tour_instance_id: int
    driver_id: Optional[int]
    new_driver_id: Optional[int]
    day: int
    block_id: str
    shift_start: Optional[str]
    shift_end: Optional[str]
    reason: str


class ViolationEntry(BaseModel):
    """A single violation record."""
    type: str = Field(..., description="overlap, rest, freeze")
    driver_id: Optional[int]
    tour_instance_id: Optional[int]
    conflicting_tour_id: Optional[int]
    message: str
    severity: str = Field("BLOCK", description="BLOCK or WARN")


class ViolationsList(BaseModel):
    """All violations found during repair."""
    overlap: List[ViolationEntry] = Field(default_factory=list)
    rest: List[ViolationEntry] = Field(default_factory=list)
    freeze: List[ViolationEntry] = Field(default_factory=list)


class RepairSummary(BaseModel):
    """Repair summary statistics."""
    uncovered_before: int
    uncovered_after: int
    churn_driver_count: int
    churn_assignment_count: int
    freeze_violations: int
    overlap_violations: int
    rest_violations: int
    absent_drivers_count: int


class IdempotencyInfo(BaseModel):
    """Idempotency tracking (no secrets)."""
    key: str
    request_hash: str


class RepairPreviewResponse(BaseModel):
    """Response from repair preview."""
    success: bool = True
    verdict: str = Field(..., description="OK, WARN, or BLOCK")
    verdict_reasons: List[str] = Field(default_factory=list)
    summary: RepairSummary
    violations: ViolationsList
    diff: Dict[str, List[AssignmentDiff]]
    evidence_id: str
    policy_hash: str
    seed: int
    base_plan_version_id: int
    preview_computed_at: str


class RepairCommitRequest(BaseModel):
    """Request to commit a repair."""
    base_plan_version_id: int = Field(..., description="Plan version to repair from")
    absences: List[AbsenceEntry] = Field(..., min_length=1, description="List of absences")
    objective: str = Field("min_churn", description="Repair objective")
    seed: int = Field(94, description="Seed for determinism")
    commit_reason: Optional[str] = Field(None, description="Reason for repair commit")


class RepairCommitResponse(BaseModel):
    """Response from repair commit."""
    success: bool = True
    new_plan_version_id: int
    parent_plan_version_id: int
    verdict: str
    summary: RepairSummary
    violations: ViolationsList
    idempotency: IdempotencyInfo
    evidence_id: str
    evidence_ref: str
    committed_by: str
    committed_at: str
    message: str


# =============================================================================
# IDEMPOTENCY (DB-BACKED)
# =============================================================================

def compute_request_hash(
    base_plan_version_id: int,
    absences: List[AbsenceEntry],
    objective: str,
    seed: int,
) -> str:
    """Compute stable SHA-256 hash of normalized request payload."""
    sorted_absences = sorted(
        [{"driver_id": a.driver_id, "from": a.from_ts, "to": a.to_ts, "reason": a.reason}
         for a in absences],
        key=lambda x: x["driver_id"]
    )
    payload = json.dumps({
        "base_plan_version_id": base_plan_version_id,
        "absences": sorted_absences,
        "objective": objective,
        "seed": seed,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_db_idempotency(
    conn,
    tenant_id: int,
    action: str,
    idempotency_key: str,
    request_hash: str,
) -> Dict[str, Any]:
    """
    Check idempotency using DB function.

    Returns:
        {status: NOT_FOUND|FOUND_MATCH|FOUND_CONFLICT, ...}
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT core.check_idempotency_key(%s, %s, %s, %s) AS result",
            (tenant_id, action, idempotency_key, request_hash)
        )
        row = cur.fetchone()
        return row[0] if row else {"status": "NOT_FOUND", "can_proceed": True}


def store_db_idempotency(
    conn,
    tenant_id: int,
    action: str,
    idempotency_key: str,
    request_hash: str,
    response_json: Dict,
) -> None:
    """Store idempotency key in DB after successful operation."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT core.store_idempotency_key(%s, %s, %s, %s, %s)",
            (tenant_id, action, idempotency_key, request_hash, json.dumps(response_json, default=str))
        )


def require_repair_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
) -> str:
    """Require idempotency key on commit."""
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "x-idempotency-key header is required for repair commit",
            },
        )
    try:
        UUID(x_idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_IDEMPOTENCY_KEY",
                "message": "x-idempotency-key must be a valid UUID",
            },
        )
    return x_idempotency_key


# =============================================================================
# EVIDENCE + AUDIT HELPERS
# =============================================================================

def generate_repair_evidence_id() -> str:
    """Generate unique evidence ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"repair_{ts}"


def generate_repair_evidence_ref(
    tenant_id: int,
    site_id: Optional[int],
    action: str,
    entity_id: int,
) -> str:
    """Generate evidence reference path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"evidence/roster_{action}_{tenant_id}_{site_id or 0}_{entity_id}_{ts}.json"


def write_repair_evidence(evidence_ref: str, data: dict) -> None:
    """Write evidence JSON to file system."""
    import os
    evidence_dir = "evidence"
    os.makedirs(evidence_dir, exist_ok=True)
    filepath = os.path.join(evidence_dir, os.path.basename(evidence_ref))
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Repair evidence written: {filepath}")


def record_repair_audit_event(
    conn,
    event_type: str,
    user: InternalUserContext,
    details: dict,
) -> None:
    """Record repair audit event."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.audit_log (
                event_type, user_id, user_email, tenant_id, site_id,
                details, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                event_type,
                user.user_id,
                user.email,
                user.tenant_id or user.active_tenant_id,
                user.site_id or user.active_site_id,
                json.dumps(details, default=str),
            )
        )


def compute_policy_hash(absences: List[AbsenceEntry], objective: str, seed: int) -> str:
    """Compute deterministic policy hash for inputs (shorter for display)."""
    sorted_absences = sorted(
        [{"driver_id": a.driver_id, "from": a.from_ts, "to": a.to_ts, "reason": a.reason}
         for a in absences],
        key=lambda x: x["driver_id"]
    )
    payload = json.dumps({
        "absences": sorted_absences,
        "objective": objective,
        "seed": seed,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# =============================================================================
# OVERLAP VALIDATION (REPAIR LAYER - NOT SOLVER)
# =============================================================================

def validate_no_overlaps(
    added_assignments: List[Dict],
    existing_assignments: Dict[int, List[Dict]],  # driver_id -> [assignments]
) -> List[Dict]:
    """
    Validate that new assignments don't overlap with existing ones per driver.

    This is repair-layer validation - NOT solver logic modification.

    Returns list of overlap violations.
    """
    violations = []

    # Group added assignments by driver
    added_by_driver: Dict[int, List[Dict]] = {}
    for asgn in added_assignments:
        driver_id = asgn.get("new_driver_id")
        if driver_id:
            if driver_id not in added_by_driver:
                added_by_driver[driver_id] = []
            added_by_driver[driver_id].append(asgn)

    for driver_id, new_assignments in added_by_driver.items():
        # Get existing assignments for this driver
        driver_existing = existing_assignments.get(driver_id, [])

        # Check each new assignment against existing
        for new_asgn in new_assignments:
            new_start = new_asgn.get("shift_start")
            new_end = new_asgn.get("shift_end")
            new_day = new_asgn.get("day")

            for existing in driver_existing:
                # Same day check
                if existing.get("day") != new_day:
                    continue

                ex_start = existing.get("shift_start")
                ex_end = existing.get("shift_end")

                # If times available, check overlap
                if new_start and new_end and ex_start and ex_end:
                    # Parse as datetime for comparison
                    try:
                        ns = datetime.fromisoformat(str(new_start).replace('Z', '+00:00'))
                        ne = datetime.fromisoformat(str(new_end).replace('Z', '+00:00'))
                        es = datetime.fromisoformat(str(ex_start).replace('Z', '+00:00'))
                        ee = datetime.fromisoformat(str(ex_end).replace('Z', '+00:00'))

                        # Check overlap
                        if not (ne <= es or ns >= ee):
                            violations.append({
                                "type": "overlap",
                                "driver_id": driver_id,
                                "tour_instance_id": new_asgn.get("tour_instance_id"),
                                "conflicting_tour_id": existing.get("tour_instance_id"),
                                "message": f"Driver {driver_id} has overlapping shifts on day {new_day}",
                                "severity": "BLOCK",
                            })
                    except (ValueError, TypeError):
                        pass
                else:
                    # No time info - same day = potential overlap (conservative)
                    violations.append({
                        "type": "overlap",
                        "driver_id": driver_id,
                        "tour_instance_id": new_asgn.get("tour_instance_id"),
                        "conflicting_tour_id": existing.get("tour_instance_id"),
                        "message": f"Driver {driver_id} may have overlapping shifts on day {new_day} (no time info)",
                        "severity": "WARN",
                    })

        # Also check new assignments against each other
        for i, a1 in enumerate(new_assignments):
            for a2 in new_assignments[i+1:]:
                if a1.get("day") == a2.get("day"):
                    # Same day - check time overlap
                    s1, e1 = a1.get("shift_start"), a1.get("shift_end")
                    s2, e2 = a2.get("shift_start"), a2.get("shift_end")

                    if s1 and e1 and s2 and e2:
                        try:
                            t1s = datetime.fromisoformat(str(s1).replace('Z', '+00:00'))
                            t1e = datetime.fromisoformat(str(e1).replace('Z', '+00:00'))
                            t2s = datetime.fromisoformat(str(s2).replace('Z', '+00:00'))
                            t2e = datetime.fromisoformat(str(e2).replace('Z', '+00:00'))

                            if not (t1e <= t2s or t1s >= t2e):
                                violations.append({
                                    "type": "overlap",
                                    "driver_id": driver_id,
                                    "tour_instance_id": a1.get("tour_instance_id"),
                                    "conflicting_tour_id": a2.get("tour_instance_id"),
                                    "message": f"Repair creates overlapping shifts for driver {driver_id}",
                                    "severity": "BLOCK",
                                })
                        except (ValueError, TypeError):
                            pass

    return violations


def validate_rest_time(
    added_assignments: List[Dict],
    existing_assignments: Dict[int, List[Dict]],
    min_rest_hours: int = 11,
) -> List[Dict]:
    """
    Check minimum rest time between shifts.

    This is advisory validation - returns WARN violations.
    Solver handles actual constraints; this is honest disclosure.
    """
    violations = []

    # Group by driver
    added_by_driver: Dict[int, List[Dict]] = {}
    for asgn in added_assignments:
        driver_id = asgn.get("new_driver_id")
        if driver_id:
            if driver_id not in added_by_driver:
                added_by_driver[driver_id] = []
            added_by_driver[driver_id].append(asgn)

    for driver_id, new_assignments in added_by_driver.items():
        all_assignments = list(existing_assignments.get(driver_id, [])) + new_assignments

        # Sort by start time
        timed = []
        for a in all_assignments:
            if a.get("shift_start") and a.get("shift_end"):
                try:
                    start = datetime.fromisoformat(str(a["shift_start"]).replace('Z', '+00:00'))
                    end = datetime.fromisoformat(str(a["shift_end"]).replace('Z', '+00:00'))
                    timed.append({"asgn": a, "start": start, "end": end})
                except (ValueError, TypeError):
                    pass

        timed.sort(key=lambda x: x["start"])

        # Check rest between consecutive shifts
        for i in range(len(timed) - 1):
            curr_end = timed[i]["end"]
            next_start = timed[i + 1]["start"]
            rest_hours = (next_start - curr_end).total_seconds() / 3600

            if rest_hours < min_rest_hours:
                violations.append({
                    "type": "rest",
                    "driver_id": driver_id,
                    "tour_instance_id": timed[i + 1]["asgn"].get("tour_instance_id"),
                    "conflicting_tour_id": timed[i]["asgn"].get("tour_instance_id"),
                    "message": f"Driver {driver_id} has only {rest_hours:.1f}h rest (min: {min_rest_hours}h)",
                    "severity": "WARN",  # Honest: we're not enforcing, just warning
                })

    return violations


# =============================================================================
# GREEDY DETERMINISTIC REPAIR ALGORITHM
# (Orchestration only - no solver modification)
# =============================================================================

def run_greedy_repair(
    conn,
    tenant_id: int,
    site_id: Optional[int],
    base_plan_version_id: int,
    absences: List[AbsenceEntry],
    objective: str,
    seed: int,
) -> Dict[str, Any]:
    """
    Greedy deterministic repair algorithm.

    GUARDRAIL: This is orchestration/post-processing, NOT solver modification.
    We filter candidates and validate results without touching solver logic.
    """
    import random
    random.seed(seed)

    with conn.cursor() as cur:
        # Step 1: Load base plan and verify tenant
        cur.execute(
            """
            SELECT id, tenant_id, site_id, plan_state, freeze_until, status
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (base_plan_version_id, tenant_id)
        )
        base_plan = cur.fetchone()
        if not base_plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {base_plan_version_id} not found or access denied",
            )

        plan_freeze_until = base_plan[4]

        # Step 2: Load all assignments from base plan
        cur.execute(
            """
            SELECT
                a.id, a.tour_instance_id, a.driver_id, a.day, a.block_id,
                ti.start_ts, ti.end_ts
            FROM assignments a
            LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
            ORDER BY a.day, a.tour_instance_id
            """,
            (base_plan_version_id,)
        )
        base_assignments = cur.fetchall()

        # Build lookup: tour_instance_id -> assignment
        assignment_map: Dict[int, Dict] = {}
        for row in base_assignments:
            assignment_map[row[1]] = {
                "assignment_id": row[0],
                "tour_instance_id": row[1],
                "driver_id": int(row[2]) if row[2] else None,
                "day": row[3],
                "block_id": row[4],
                "start_ts": row[5],
                "end_ts": row[6],
                "shift_start": str(row[5]) if row[5] else None,
                "shift_end": str(row[6]) if row[6] else None,
            }

        # Step 3: Parse absences
        absent_driver_ids = set()
        absence_windows: Dict[int, List[tuple]] = {}

        for absence in absences:
            driver_id = absence.driver_id
            absent_driver_ids.add(driver_id)
            from_dt = datetime.fromisoformat(absence.from_ts.replace('Z', '+00:00'))
            to_dt = datetime.fromisoformat(absence.to_ts.replace('Z', '+00:00'))
            if driver_id not in absence_windows:
                absence_windows[driver_id] = []
            absence_windows[driver_id].append((from_dt, to_dt))

        # Identify affected assignments
        removed_assignments: List[Dict] = []
        affected_tour_instances: set = set()

        for tour_id, asgn in assignment_map.items():
            if asgn["driver_id"] in absent_driver_ids:
                shift_start = asgn["start_ts"]
                shift_end = asgn["end_ts"]

                is_affected = True
                if shift_start and shift_end:
                    for (abs_from, abs_to) in absence_windows.get(asgn["driver_id"], []):
                        if not (shift_end <= abs_from or shift_start >= abs_to):
                            is_affected = True
                            break
                    else:
                        is_affected = False

                if is_affected:
                    removed_assignments.append({
                        "tour_instance_id": tour_id,
                        "driver_id": asgn["driver_id"],
                        "new_driver_id": None,
                        "day": asgn["day"],
                        "block_id": asgn["block_id"],
                        "shift_start": asgn["shift_start"],
                        "shift_end": asgn["shift_end"],
                        "reason": "absent_driver",
                    })
                    affected_tour_instances.add(tour_id)

        # Step 4: Load available drivers
        cur.execute(
            """
            SELECT DISTINCT d.id, d.name
            FROM drivers d
            WHERE d.tenant_id = %s
            AND d.id NOT IN %s
            AND d.active = true
            """,
            (tenant_id, tuple(absent_driver_ids) if absent_driver_ids else (0,))
        )
        available_drivers = {row[0]: row[1] for row in cur.fetchall()}

        # Step 5: Build driver existing assignments (for overlap check)
        driver_assignments: Dict[int, List[Dict]] = {}
        for tour_id, asgn in assignment_map.items():
            if asgn["driver_id"] and asgn["driver_id"] not in absent_driver_ids:
                if asgn["driver_id"] not in driver_assignments:
                    driver_assignments[asgn["driver_id"]] = []
                driver_assignments[asgn["driver_id"]].append(asgn)

        # Step 6: Greedy assignment
        added_assignments: List[Dict] = []
        uncovered_after = 0
        churn_drivers = set()
        decisions_log: List[Dict] = []

        sorted_affected = sorted(affected_tour_instances)

        for tour_id in sorted_affected:
            asgn = assignment_map[tour_id]

            candidates = []
            for driver_id in available_drivers:
                has_overlap = False

                # Check against existing assignments
                if driver_id in driver_assignments:
                    for existing in driver_assignments[driver_id]:
                        if existing["day"] == asgn["day"]:
                            ex_start, ex_end = existing.get("start_ts"), existing.get("end_ts")
                            asgn_start, asgn_end = asgn.get("start_ts"), asgn.get("end_ts")

                            if ex_start and ex_end and asgn_start and asgn_end:
                                try:
                                    es = datetime.fromisoformat(str(ex_start).replace('Z', '+00:00')) if isinstance(ex_start, str) else ex_start
                                    ee = datetime.fromisoformat(str(ex_end).replace('Z', '+00:00')) if isinstance(ex_end, str) else ex_end
                                    ns = datetime.fromisoformat(str(asgn_start).replace('Z', '+00:00')) if isinstance(asgn_start, str) else asgn_start
                                    ne = datetime.fromisoformat(str(asgn_end).replace('Z', '+00:00')) if isinstance(asgn_end, str) else asgn_end

                                    if not (ee <= ns or es >= ne):
                                        has_overlap = True
                                        break
                                except (ValueError, TypeError):
                                    has_overlap = True
                                    break
                            else:
                                has_overlap = True
                                break

                if not has_overlap:
                    existing_count = len(driver_assignments.get(driver_id, []))
                    score = existing_count if objective == "min_churn" else -existing_count
                    candidates.append({
                        "driver_id": driver_id,
                        "score": score,
                        "existing_count": existing_count,
                    })

            candidates.sort(key=lambda c: (c["score"], c["driver_id"]))

            decision = {
                "tour_instance_id": tour_id,
                "candidates_count": len(candidates),
                "top_3_candidates": [c["driver_id"] for c in candidates[:3]],
                "chosen": None,
                "reason": None,
            }

            if candidates:
                chosen = candidates[0]
                decision["chosen"] = chosen["driver_id"]
                decision["reason"] = f"score={chosen['score']}, existing={chosen['existing_count']}"

                added_assignments.append({
                    "tour_instance_id": tour_id,
                    "driver_id": None,
                    "new_driver_id": chosen["driver_id"],
                    "day": asgn["day"],
                    "block_id": asgn["block_id"],
                    "shift_start": asgn["shift_start"],
                    "shift_end": asgn["shift_end"],
                    "reason": "repair_assigned",
                })

                churn_drivers.add(chosen["driver_id"])

                if chosen["driver_id"] not in driver_assignments:
                    driver_assignments[chosen["driver_id"]] = []
                driver_assignments[chosen["driver_id"]].append({
                    "tour_instance_id": tour_id,
                    "day": asgn["day"],
                    "start_ts": asgn["start_ts"],
                    "end_ts": asgn["end_ts"],
                    "shift_start": asgn["shift_start"],
                    "shift_end": asgn["shift_end"],
                })
            else:
                uncovered_after += 1
                decision["reason"] = "no_candidates_available"

            decisions_log.append(decision)

        # Step 7: Validate results (repair layer)
        overlap_violations = validate_no_overlaps(added_assignments, driver_assignments)
        rest_violations = validate_rest_time(added_assignments, driver_assignments)

        # Step 8: Check freeze violations
        freeze_violations_list = []
        now = datetime.now(timezone.utc)
        if plan_freeze_until and plan_freeze_until > now:
            for tour_id in affected_tour_instances:
                freeze_violations_list.append({
                    "type": "freeze",
                    "driver_id": None,
                    "tour_instance_id": tour_id,
                    "conflicting_tour_id": None,
                    "message": f"Tour {tour_id} change blocked by freeze window until {plan_freeze_until}",
                    "severity": "BLOCK",
                })

        # Step 9: Determine verdict
        verdict_reasons = []
        has_blocking = False

        if freeze_violations_list:
            verdict_reasons.append(f"{len(freeze_violations_list)} changes within freeze window (BLOCK)")
            has_blocking = True

        # Filter BLOCK-severity overlap violations
        blocking_overlaps = [v for v in overlap_violations if v["severity"] == "BLOCK"]
        if blocking_overlaps:
            verdict_reasons.append(f"{len(blocking_overlaps)} overlap violations (BLOCK)")
            has_blocking = True

        if uncovered_after > 0:
            verdict_reasons.append(f"{uncovered_after} shifts remain uncovered (WARN)")

        if rest_violations:
            verdict_reasons.append(f"{len(rest_violations)} rest time violations (WARN - not enforced)")

        if has_blocking:
            verdict = "BLOCK"
        elif uncovered_after > 0 or rest_violations:
            verdict = "WARN"
        else:
            verdict = "OK"

        # Build violations object
        violations = {
            "overlap": overlap_violations,
            "rest": rest_violations,
            "freeze": freeze_violations_list,
        }

        # Build summary
        summary = {
            "uncovered_before": len(removed_assignments),
            "uncovered_after": uncovered_after,
            "churn_driver_count": len(churn_drivers),
            "churn_assignment_count": len(added_assignments),
            "freeze_violations": len(freeze_violations_list),
            "overlap_violations": len(overlap_violations),
            "rest_violations": len(rest_violations),
            "absent_drivers_count": len(absent_driver_ids),
        }

        diff = {
            "removed_assignments": removed_assignments,
            "added_assignments": added_assignments,
            "modified_assignments": [],
        }

        return {
            "verdict": verdict,
            "verdict_reasons": verdict_reasons,
            "summary": summary,
            "violations": violations,
            "diff": diff,
            "decisions": decisions_log,
        }


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/preview", response_model=RepairPreviewResponse)
async def repair_preview(
    request: Request,
    body: RepairPreviewRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Preview repair changes without committing.

    Returns verdict with explicit violations list:
    - overlap: Driver assigned to overlapping shifts
    - rest: Insufficient rest time (WARN only - honest disclosure)
    - freeze: Changes blocked by freeze window
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    policy_hash = compute_policy_hash(body.absences, body.objective, body.seed)

    result = run_greedy_repair(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id,
        base_plan_version_id=body.base_plan_version_id,
        absences=body.absences,
        objective=body.objective,
        seed=body.seed,
    )

    evidence_id = generate_repair_evidence_id()
    evidence_ref = generate_repair_evidence_ref(
        ctx.tenant_id, ctx.site_id, "repair_preview", body.base_plan_version_id
    )

    now = datetime.now(timezone.utc)

    evidence_data = {
        "event": "repair_preview",
        "evidence_id": evidence_id,
        "tenant_id": ctx.tenant_id,
        "site_id": ctx.site_id,
        "base_plan_version_id": body.base_plan_version_id,
        "absences": [
            {"driver_id": a.driver_id, "from": a.from_ts, "to": a.to_ts, "reason": a.reason}
            for a in body.absences
        ],
        "objective": body.objective,
        "seed": body.seed,
        "policy_hash": policy_hash,
        "verdict": result["verdict"],
        "verdict_reasons": result["verdict_reasons"],
        "summary": result["summary"],
        "violations": result["violations"],
        "diff_summary": {
            "removed": len(result["diff"]["removed_assignments"]),
            "added": len(result["diff"]["added_assignments"]),
        },
        "decisions": result["decisions"],
        "computed_by": ctx.user.email,
        "computed_at": now.isoformat(),
    }
    write_repair_evidence(evidence_ref, evidence_data)

    record_repair_audit_event(
        conn,
        event_type="roster.repair.preview",
        user=ctx.user,
        details={
            "base_plan_version_id": body.base_plan_version_id,
            "absent_count": len(body.absences),
            "verdict": result["verdict"],
            "violations_count": {
                "overlap": len(result["violations"]["overlap"]),
                "rest": len(result["violations"]["rest"]),
                "freeze": len(result["violations"]["freeze"]),
            },
            "evidence_id": evidence_id,
        },
    )
    conn.commit()

    logger.info(
        "repair_preview_computed",
        extra={
            "plan_id": body.base_plan_version_id,
            "verdict": result["verdict"],
            "tenant_id": ctx.tenant_id,
        }
    )

    return RepairPreviewResponse(
        success=True,
        verdict=result["verdict"],
        verdict_reasons=result["verdict_reasons"],
        summary=RepairSummary(**result["summary"]),
        violations=ViolationsList(
            overlap=[ViolationEntry(**v) for v in result["violations"]["overlap"]],
            rest=[ViolationEntry(**v) for v in result["violations"]["rest"]],
            freeze=[ViolationEntry(**v) for v in result["violations"]["freeze"]],
        ),
        diff={
            "removed_assignments": [AssignmentDiff(**a) for a in result["diff"]["removed_assignments"]],
            "added_assignments": [AssignmentDiff(**a) for a in result["diff"]["added_assignments"]],
            "modified_assignments": [],
        },
        evidence_id=evidence_id,
        policy_hash=policy_hash,
        seed=body.seed,
        base_plan_version_id=body.base_plan_version_id,
        preview_computed_at=now.isoformat(),
    )


@router.post(
    "/commit",
    response_model=RepairCommitResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def repair_commit(
    request: Request,
    body: RepairCommitRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_repair_idempotency_key),
):
    """
    Commit repair as a new plan version.

    IDEMPOTENCY (DB-BACKED):
    - Same key + same payload = return cached response
    - Same key + different payload = 409 CONFLICT

    BLOCKS ON:
    - Freeze window violations
    - Overlap violations (BLOCK severity)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Compute request hash for idempotency
    request_hash = compute_request_hash(
        body.base_plan_version_id, body.absences, body.objective, body.seed
    )
    policy_hash = compute_policy_hash(body.absences, body.objective, body.seed)

    # Check DB idempotency
    idem_result = check_db_idempotency(
        conn, ctx.tenant_id, "roster.repair.commit", idempotency_key, request_hash
    )

    if idem_result["status"] == "FOUND_CONFLICT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REUSE_CONFLICT",
                "message": "Idempotency key already used with different request payload",
            },
        )

    if idem_result["status"] == "FOUND_MATCH":
        cached = idem_result.get("cached_response", {})
        logger.info(f"Idempotent return for repair commit key {idempotency_key}")
        return RepairCommitResponse(**cached)

    # Run repair algorithm
    result = run_greedy_repair(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id,
        base_plan_version_id=body.base_plan_version_id,
        absences=body.absences,
        objective=body.objective,
        seed=body.seed,
    )

    # Block if verdict is BLOCK
    if result["verdict"] == "BLOCK":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "REPAIR_BLOCKED",
                "message": f"Repair blocked: {', '.join(result['verdict_reasons'])}",
                "verdict": result["verdict"],
                "verdict_reasons": result["verdict_reasons"],
                "violations": result["violations"],
            },
        )

    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT forecast_version_id, site_id, seed, solver_config_hash
            FROM plan_versions WHERE id = %s AND tenant_id = %s
            """,
            (body.base_plan_version_id, ctx.tenant_id)
        )
        base_plan = cur.fetchone()
        if not base_plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Base plan {body.base_plan_version_id} not found",
            )

        cur.execute(
            """
            INSERT INTO plan_versions (
                tenant_id, site_id, forecast_version_id, seed,
                status, plan_state, baseline_plan_version_id,
                churn_count, churn_drivers_affected,
                notes, created_at
            ) VALUES (
                %s, %s, %s, %s,
                'DRAFT', 'DRAFT', %s,
                %s, %s,
                %s, NOW()
            )
            RETURNING id, created_at
            """,
            (
                ctx.tenant_id,
                ctx.site_id or base_plan[1],
                base_plan[0],
                body.seed,
                body.base_plan_version_id,
                result["summary"]["churn_assignment_count"],
                result["summary"]["churn_driver_count"],
                f"Repair from plan {body.base_plan_version_id}: {body.commit_reason or 'sick call handling'}",
            )
        )
        new_plan_row = cur.fetchone()
        new_plan_version_id = new_plan_row[0]
        created_at = new_plan_row[1]

        cur.execute(
            """
            INSERT INTO assignments (
                plan_version_id, tenant_id, driver_id,
                tour_instance_id, day, block_id, role, metadata
            )
            SELECT
                %s, tenant_id, driver_id,
                tour_instance_id, day, block_id, role, metadata
            FROM assignments
            WHERE plan_version_id = %s
            """,
            (new_plan_version_id, body.base_plan_version_id)
        )

        absent_driver_ids = [a.driver_id for a in body.absences]
        if absent_driver_ids:
            cur.execute(
                """
                DELETE FROM assignments
                WHERE plan_version_id = %s
                AND driver_id::integer = ANY(%s)
                """,
                (new_plan_version_id, absent_driver_ids)
            )

        for added in result["diff"]["added_assignments"]:
            cur.execute(
                """
                INSERT INTO assignments (
                    plan_version_id, tenant_id, driver_id,
                    tour_instance_id, day, block_id, role
                ) VALUES (%s, %s, %s, %s, %s, %s, 'PRIMARY')
                ON CONFLICT (plan_version_id, tour_instance_id)
                DO UPDATE SET driver_id = EXCLUDED.driver_id
                """,
                (
                    new_plan_version_id,
                    ctx.tenant_id,
                    str(added["new_driver_id"]),
                    added["tour_instance_id"],
                    added["day"],
                    added["block_id"],
                )
            )

        evidence_id = generate_repair_evidence_id()
        evidence_ref = generate_repair_evidence_ref(
            ctx.tenant_id, ctx.site_id, "repair_commit", new_plan_version_id
        )

        cur.execute(
            """
            INSERT INTO plan_approvals (
                plan_version_id, tenant_id, action, performed_by,
                from_state, to_state, reason, created_at
            ) VALUES (%s, %s, 'REPAIR_CREATE', %s, NULL, 'DRAFT', %s, NOW())
            """,
            (
                new_plan_version_id,
                ctx.tenant_id,
                performed_by,
                body.commit_reason or f"Repaired from plan {body.base_plan_version_id}",
            )
        )

        record_repair_audit_event(
            conn,
            event_type="roster.repair.commit",
            user=ctx.user,
            details={
                "base_plan_version_id": body.base_plan_version_id,
                "new_plan_version_id": new_plan_version_id,
                "absent_drivers": absent_driver_ids,
                "verdict": result["verdict"],
                "violations_count": {
                    "overlap": len(result["violations"]["overlap"]),
                    "rest": len(result["violations"]["rest"]),
                    "freeze": len(result["violations"]["freeze"]),
                },
                "churn_count": result["summary"]["churn_assignment_count"],
                "evidence_id": evidence_id,
                "evidence_ref": evidence_ref,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "policy_hash": policy_hash,
            },
        )

        evidence_data = {
            "event": "repair_commit",
            "evidence_id": evidence_id,
            "tenant_id": ctx.tenant_id,
            "site_id": ctx.site_id,
            "base_plan_version_id": body.base_plan_version_id,
            "new_plan_version_id": new_plan_version_id,
            "absences": [
                {"driver_id": a.driver_id, "from": a.from_ts, "to": a.to_ts, "reason": a.reason}
                for a in body.absences
            ],
            "objective": body.objective,
            "seed": body.seed,
            "policy_hash": policy_hash,
            "verdict": result["verdict"],
            "violations": result["violations"],
            "summary": result["summary"],
            "diff": {
                "removed_count": len(result["diff"]["removed_assignments"]),
                "added_count": len(result["diff"]["added_assignments"]),
                "removed": result["diff"]["removed_assignments"],
                "added": result["diff"]["added_assignments"],
            },
            "committed_by": performed_by,
            "committed_at": now.isoformat(),
            "idempotency": {
                "key": idempotency_key,
                "request_hash": request_hash,
            },
        }
        write_repair_evidence(evidence_ref, evidence_data)

        # Build response for DB storage
        response_data = {
            "success": True,
            "new_plan_version_id": new_plan_version_id,
            "parent_plan_version_id": body.base_plan_version_id,
            "verdict": result["verdict"],
            "summary": result["summary"],
            "violations": result["violations"],
            "idempotency": {
                "key": idempotency_key,
                "request_hash": request_hash,
            },
            "evidence_id": evidence_id,
            "evidence_ref": evidence_ref,
            "committed_by": performed_by,
            "committed_at": now.isoformat(),
            "message": f"Repair committed as plan {new_plan_version_id}",
        }

        # Store idempotency in DB
        store_db_idempotency(
            conn,
            ctx.tenant_id,
            "roster.repair.commit",
            idempotency_key,
            request_hash,
            response_data,
        )

        conn.commit()

    logger.info(
        "repair_committed",
        extra={
            "base_plan_id": body.base_plan_version_id,
            "new_plan_id": new_plan_version_id,
            "verdict": result["verdict"],
            "tenant_id": ctx.tenant_id,
        }
    )

    return RepairCommitResponse(
        success=True,
        new_plan_version_id=new_plan_version_id,
        parent_plan_version_id=body.base_plan_version_id,
        verdict=result["verdict"],
        summary=RepairSummary(**result["summary"]),
        violations=ViolationsList(
            overlap=[ViolationEntry(**v) for v in result["violations"]["overlap"]],
            rest=[ViolationEntry(**v) for v in result["violations"]["rest"]],
            freeze=[ViolationEntry(**v) for v in result["violations"]["freeze"]],
        ),
        idempotency=IdempotencyInfo(key=idempotency_key, request_hash=request_hash),
        evidence_id=evidence_id,
        evidence_ref=evidence_ref,
        committed_by=performed_by,
        committed_at=now.isoformat(),
        message=f"Repair committed as plan {new_plan_version_id}",
    )
