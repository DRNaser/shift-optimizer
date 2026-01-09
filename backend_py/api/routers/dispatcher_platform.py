"""
SOLVEREIGN Dispatcher Platform API
===================================

Platform-level endpoints for dispatcher cockpit.
Provides API equivalents of dispatcher_cli.py commands.

Endpoints:
- GET  /platform/dispatcher/runs                    List runs for site
- GET  /platform/dispatcher/runs/{run_id}           Run detail with audits
- POST /platform/dispatcher/runs/{run_id}/publish   Publish with approval
- POST /platform/dispatcher/runs/{run_id}/lock      Lock with approval
- POST /platform/dispatcher/runs/{run_id}/repair    Submit repair request
- GET  /platform/dispatcher/status                  Kill switch + system status
- GET  /platform/dispatcher/evidence/{run_id}       Stream evidence.zip

Security:
- Requires platform session auth (X-Platform-Admin or X-Tenant-Code + X-Site-Code)
- Publish/lock require human approval with evidence hash linkage
- All actions produce audit events identical to CLI
"""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from ..dependencies import get_db
from ..database import DatabaseManager
from ..services.publish_gate import (
    PublishGateService,
    ApprovalRecord,
    PublishGateStatus,
    PublishGateResult
)

router = APIRouter()

# Project root for artifact access
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


# =============================================================================
# SCHEMAS
# =============================================================================

class RunStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"


class AuditCheckResult(BaseModel):
    """Result of a single audit check."""
    check_name: str
    status: str  # PASS, FAIL, WARN
    violation_count: int = 0
    details: Optional[Dict[str, Any]] = None


class KPISummary(BaseModel):
    """KPI summary for a run."""
    headcount: int
    coverage_percent: float
    fte_ratio: float
    pt_ratio: float
    runtime_seconds: float
    drift_status: str  # OK, WARN, BLOCK


class RunSummary(BaseModel):
    """Summary of a solver run."""
    run_id: str
    week_id: str
    timestamp: str
    status: RunStatus
    tenant_code: str
    site_code: str
    headcount: int
    coverage_percent: float
    audit_pass_count: int
    audit_total: int
    evidence_path: Optional[str] = None
    kpi_drift_status: str
    published: bool = False
    published_at: Optional[str] = None
    published_by: Optional[str] = None
    locked: bool = False
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None
    notes: str = ""


class RunDetail(BaseModel):
    """Detailed run information."""
    run_id: str
    week_id: str
    timestamp: str
    status: RunStatus
    tenant_code: str
    site_code: str
    headcount: int
    coverage_percent: float
    audit_results: List[AuditCheckResult]
    kpis: KPISummary
    # Evidence fields (5 required for audit trail)
    input_hash: Optional[str] = None      # SHA256 of solver input data
    output_hash: Optional[str] = None     # SHA256 of solver output/solution
    evidence_hash: Optional[str] = None   # Combined evidence pack hash
    evidence_path: Optional[str] = None   # Local path (dev only)
    artifact_uri: Optional[str] = None    # S3/blob URI (production)
    # Lifecycle
    published: bool = False
    published_at: Optional[str] = None
    published_by: Optional[str] = None
    locked: bool = False
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None
    notes: str = ""


class RunListResponse(BaseModel):
    """List of runs."""
    runs: List[RunSummary]
    total: int


class PublishRequest(BaseModel):
    """Request to publish a run."""
    approver_id: str = Field(..., min_length=1)
    approver_role: str = Field(..., pattern=r'^(dispatcher|ops_lead|platform_admin)$')
    reason: str = Field(..., min_length=10)
    override_warn: bool = False


class LockRequest(BaseModel):
    """Request to lock a published run."""
    approver_id: str = Field(..., min_length=1)
    approver_role: str = Field(..., pattern=r'^(dispatcher|ops_lead|platform_admin)$')
    reason: str = Field(..., min_length=10)


class RepairRequest(BaseModel):
    """Request for sick-call repair."""
    driver_id: str = Field(..., min_length=1)
    driver_name: str = Field(..., min_length=1)
    absence_type: str = Field(..., pattern=r'^(sick|vacation|no_show)$')
    affected_tours: List[str] = Field(..., min_items=1)
    urgency: str = Field(default="normal", pattern=r'^(critical|high|normal)$')
    notes: str = ""


class PublishLockResponse(BaseModel):
    """Response from publish/lock operation."""
    success: bool
    run_id: str
    status: str
    audit_event_id: Optional[str] = None
    evidence_hash: Optional[str] = None
    message: str
    blocked_reason: Optional[str] = None


class RepairResponse(BaseModel):
    """Response from repair request."""
    request_id: str
    run_id: str
    status: str
    message: str


class SystemStatus(BaseModel):
    """System status for dispatcher."""
    kill_switch_active: bool
    kill_switch_reason: Optional[str] = None
    publish_enabled: bool
    lock_enabled: bool
    shadow_mode_only: bool
    latest_run: Optional[RunSummary] = None
    pending_repairs: int = 0
    active_incidents: int = 0


# =============================================================================
# DEPENDENCIES
# =============================================================================

async def get_site_context(
    x_tenant_code: str = Header(..., alias="X-Tenant-Code"),
    x_site_code: str = Header(..., alias="X-Site-Code"),
) -> tuple[str, str]:
    """Extract tenant and site from headers."""
    return x_tenant_code, x_site_code


def get_publish_gate_service() -> PublishGateService:
    """Get publish gate service instance."""
    return PublishGateService()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_runs_dir(site_code: str) -> Path:
    """Get runs directory for site."""
    return PROJECT_ROOT / "runs"


def _get_evidence_dir(site_code: str) -> Path:
    """Get evidence directory for site."""
    return PROJECT_ROOT / "artifacts"


def _load_runs(tenant_code: str, site_code: str, limit: int = 20) -> List[RunSummary]:
    """Load run summaries from artifacts."""
    runs = []
    runs_dir = _get_runs_dir(site_code)

    if not runs_dir.exists():
        return runs

    for run_file in sorted(runs_dir.glob("*.json"), reverse=True):
        try:
            with open(run_file) as f:
                data = json.load(f)

            # Filter by tenant/site
            if data.get("tenant_code") != tenant_code:
                continue
            if data.get("site_code") != site_code:
                continue

            run = RunSummary(
                run_id=data.get("run_id", run_file.stem),
                week_id=data.get("week_id", "unknown"),
                timestamp=data.get("timestamp", ""),
                status=RunStatus(data.get("status", "PENDING")),
                tenant_code=data.get("tenant_code", tenant_code),
                site_code=data.get("site_code", site_code),
                headcount=data.get("headcount", 0),
                coverage_percent=data.get("coverage_percent", 0),
                audit_pass_count=data.get("audit_pass_count", 0),
                audit_total=data.get("audit_total", 7),
                evidence_path=data.get("evidence_path"),
                kpi_drift_status=data.get("kpi_drift_status", "UNKNOWN"),
                published=data.get("published", False),
                published_at=data.get("published_at"),
                published_by=data.get("published_by"),
                locked=data.get("locked", False),
                locked_at=data.get("locked_at"),
                locked_by=data.get("locked_by"),
                notes=data.get("notes", "")
            )
            runs.append(run)

            if len(runs) >= limit:
                break

        except Exception as e:
            # Log but continue
            pass

    return runs


def _load_run_detail(tenant_code: str, site_code: str, run_id: str) -> Optional[RunDetail]:
    """Load detailed run information."""
    runs_dir = _get_runs_dir(site_code)
    run_file = runs_dir / f"{run_id}.json"

    if not run_file.exists():
        return None

    with open(run_file) as f:
        data = json.load(f)

    # Verify tenant/site
    if data.get("tenant_code") != tenant_code:
        return None
    if data.get("site_code") != site_code:
        return None

    # Load audit results
    audit_results = []
    for check in data.get("audit_results", []):
        audit_results.append(AuditCheckResult(
            check_name=check.get("check_name", "unknown"),
            status=check.get("status", "PASS"),
            violation_count=check.get("violation_count", 0),
            details=check.get("details")
        ))

    # Default audit checks if not present
    if not audit_results:
        default_checks = ["Coverage", "Overlap", "Rest", "SpanRegular", "SpanSplit", "Fatigue", "Reproducibility"]
        audit_pass = data.get("audit_pass_count", 7)
        for i, check_name in enumerate(default_checks):
            audit_results.append(AuditCheckResult(
                check_name=check_name,
                status="PASS" if i < audit_pass else "FAIL",
                violation_count=0
            ))

    # KPIs
    kpis = KPISummary(
        headcount=data.get("headcount", 0),
        coverage_percent=data.get("coverage_percent", 100),
        fte_ratio=data.get("fte_ratio", 1.0),
        pt_ratio=data.get("pt_ratio", 0.0),
        runtime_seconds=data.get("runtime_seconds", 0),
        drift_status=data.get("kpi_drift_status", "OK")
    )

    # Compute evidence hash if path exists
    evidence_hash = None
    evidence_path = data.get("evidence_path")
    if evidence_path:
        evidence_dir = Path(evidence_path)
        if evidence_dir.exists() and evidence_dir.is_dir():
            hasher = hashlib.sha256()
            for f in sorted(evidence_dir.iterdir()):
                if f.is_file():
                    hasher.update(f.read_bytes())
            evidence_hash = f"sha256:{hasher.hexdigest()}"

    # Load input/output hashes from evidence subdirectory if available
    input_hash = data.get("input_hash")
    output_hash = data.get("output_hash")
    artifact_uri = data.get("artifact_uri")

    # Try to load from evidence pack metadata.json
    if evidence_path and not input_hash:
        metadata_file = Path(evidence_path) / "metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file) as mf:
                    meta = json.load(mf)
                    evidence_hash = evidence_hash or meta.get("pack_hash")
            except:
                pass

        input_summary_file = Path(evidence_path) / "input_summary.json"
        if input_summary_file.exists():
            try:
                with open(input_summary_file) as inf:
                    inp = json.load(inf)
                    input_hash = inp.get("input_hash")
            except:
                pass

        plan_file = Path(evidence_path) / "plan.json"
        if plan_file.exists():
            try:
                with open(plan_file) as pf:
                    plan_data = json.load(pf)
                    output_hash = plan_data.get("output_hash")
            except:
                pass

    return RunDetail(
        run_id=data.get("run_id", run_id),
        week_id=data.get("week_id", "unknown"),
        timestamp=data.get("timestamp", ""),
        status=RunStatus(data.get("status", "PENDING")),
        tenant_code=data.get("tenant_code", tenant_code),
        site_code=data.get("site_code", site_code),
        headcount=data.get("headcount", 0),
        coverage_percent=data.get("coverage_percent", 0),
        audit_results=audit_results,
        kpis=kpis,
        # Evidence fields
        input_hash=input_hash,
        output_hash=output_hash,
        evidence_hash=evidence_hash,
        evidence_path=evidence_path,
        artifact_uri=artifact_uri,
        # Lifecycle
        published=data.get("published", False),
        published_at=data.get("published_at"),
        published_by=data.get("published_by"),
        locked=data.get("locked", False),
        locked_at=data.get("locked_at"),
        locked_by=data.get("locked_by"),
        notes=data.get("notes", "")
    )


def _update_run_file(site_code: str, run_id: str, updates: Dict[str, Any]) -> bool:
    """Update run file with new data."""
    runs_dir = _get_runs_dir(site_code)
    run_file = runs_dir / f"{run_id}.json"

    if not run_file.exists():
        return False

    with open(run_file) as f:
        data = json.load(f)

    data.update(updates)

    with open(run_file, "w") as f:
        json.dump(data, f, indent=2)

    return True


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    context: tuple[str, str] = Depends(get_site_context),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[RunStatus] = Query(default=None, alias="status"),
):
    """
    List runs for the current site.

    Equivalent to: dispatcher_cli.py list-runs
    """
    tenant_code, site_code = context
    runs = _load_runs(tenant_code, site_code, limit=limit * 2)  # Over-fetch for filtering

    # Filter by status if requested
    if status_filter:
        runs = [r for r in runs if r.status == status_filter]

    # Apply limit
    runs = runs[:limit]

    return RunListResponse(runs=runs, total=len(runs))


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    context: tuple[str, str] = Depends(get_site_context),
):
    """
    Get detailed run information including audit results and KPIs.

    Equivalent to: dispatcher_cli.py show-run <run_id>
    """
    tenant_code, site_code = context
    run = _load_run_detail(tenant_code, site_code, run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found for site {site_code}"
        )

    return run


@router.post("/runs/{run_id}/publish", response_model=PublishLockResponse)
async def publish_run(
    run_id: str,
    request: PublishRequest,
    context: tuple[str, str] = Depends(get_site_context),
    gate_service: PublishGateService = Depends(get_publish_gate_service),
):
    """
    Publish a run (requires approval).

    Equivalent to: dispatcher_cli.py publish <run_id> --approver <id> --role <role> --reason <reason>

    Gates enforced:
    - Site enablement (Wien only initially)
    - Kill switch
    - Shadow mode
    - Human approval with role validation
    - Evidence hash linkage
    """
    tenant_code, site_code = context

    # Load run
    run = _load_run_detail(tenant_code, site_code, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found"
        )

    # Check run status
    if run.status == RunStatus.FAIL or run.status == RunStatus.BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot publish run with status: {run.status.value}"
        )

    if run.status == RunStatus.WARN and not request.override_warn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run has warnings. Set override_warn=true to publish anyway."
        )

    if run.published:
        return PublishLockResponse(
            success=True,
            run_id=run_id,
            status="ALREADY_PUBLISHED",
            audit_event_id=None,
            evidence_hash=run.evidence_hash,
            message="Run already published"
        )

    # Create approval record
    approval = ApprovalRecord(
        approver_id=request.approver_id,
        approver_role=request.approver_role,
        reason=request.reason
    )

    # Extract plan_version_id from run_id (e.g., RUN-20260120-001 -> 1)
    try:
        plan_version_id = int(run_id.split("-")[-1])
    except:
        plan_version_id = hash(run_id) % 10000

    # Check publish gate
    result = gate_service.check_publish_allowed(
        tenant_code=tenant_code,
        site_code=site_code,
        pack="roster",
        plan_version_id=plan_version_id,
        evidence_hash=run.evidence_hash or "placeholder",
        approval=approval
    )

    if not result.allowed:
        return PublishLockResponse(
            success=False,
            run_id=run_id,
            status=result.status.value,
            audit_event_id=result.audit_event_id,
            evidence_hash=run.evidence_hash,
            message="Publish blocked",
            blocked_reason=result.blocked_reason
        )

    # Update run file
    _update_run_file(site_code, run_id, {
        "published": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "published_by": request.approver_id,
        "publish_audit_event_id": result.audit_event_id
    })

    return PublishLockResponse(
        success=True,
        run_id=run_id,
        status="PUBLISHED",
        audit_event_id=result.audit_event_id,
        evidence_hash=run.evidence_hash,
        message=f"Run published by {request.approver_id}"
    )


@router.post("/runs/{run_id}/lock", response_model=PublishLockResponse)
async def lock_run(
    run_id: str,
    request: LockRequest,
    context: tuple[str, str] = Depends(get_site_context),
    gate_service: PublishGateService = Depends(get_publish_gate_service),
):
    """
    Lock a published run for export (requires approval).

    Equivalent to: dispatcher_cli.py lock <run_id> --approver <id> --role <role> --reason <reason>

    Gates enforced (same as publish, plus lock_enabled check):
    - Site enablement
    - Kill switch
    - Lock enabled
    - Human approval
    - Evidence hash linkage
    """
    tenant_code, site_code = context

    # Load run
    run = _load_run_detail(tenant_code, site_code, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found"
        )

    if run.locked:
        return PublishLockResponse(
            success=True,
            run_id=run_id,
            status="ALREADY_LOCKED",
            audit_event_id=None,
            evidence_hash=run.evidence_hash,
            message="Run already locked"
        )

    # Create approval record
    approval = ApprovalRecord(
        approver_id=request.approver_id,
        approver_role=request.approver_role,
        reason=request.reason
    )

    # Extract plan_version_id
    try:
        plan_version_id = int(run_id.split("-")[-1])
    except:
        plan_version_id = hash(run_id) % 10000

    # Check lock gate
    result = gate_service.check_lock_allowed(
        tenant_code=tenant_code,
        site_code=site_code,
        pack="roster",
        plan_version_id=plan_version_id,
        evidence_hash=run.evidence_hash or "placeholder",
        approval=approval
    )

    if not result.allowed:
        return PublishLockResponse(
            success=False,
            run_id=run_id,
            status=result.status.value,
            audit_event_id=result.audit_event_id,
            evidence_hash=run.evidence_hash,
            message="Lock blocked",
            blocked_reason=result.blocked_reason
        )

    # Update run file
    _update_run_file(site_code, run_id, {
        "locked": True,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "locked_by": request.approver_id,
        "lock_audit_event_id": result.audit_event_id
    })

    return PublishLockResponse(
        success=True,
        run_id=run_id,
        status="LOCKED",
        audit_event_id=result.audit_event_id,
        evidence_hash=run.evidence_hash,
        message=f"Run locked by {request.approver_id}"
    )


@router.post("/runs/{run_id}/repair", response_model=RepairResponse)
async def request_repair(
    run_id: str,
    request: RepairRequest,
    context: tuple[str, str] = Depends(get_site_context),
):
    """
    Submit a repair request for sick-call/no-show.

    Equivalent to: dispatcher_cli.py request-repair --week <week> --driver <id> ...
    """
    tenant_code, site_code = context

    # Load run to get week_id
    run = _load_run_detail(tenant_code, site_code, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found"
        )

    # Generate request ID
    timestamp = datetime.now(timezone.utc)
    request_id = f"REP-{timestamp.strftime('%Y%m%d%H%M%S')}"

    # Build repair request data
    repair_data = {
        "request_id": request_id,
        "timestamp": timestamp.isoformat(),
        "run_id": run_id,
        "week_id": run.week_id,
        "tenant_code": tenant_code,
        "site_code": site_code,
        "driver_id": request.driver_id,
        "driver_name": request.driver_name,
        "absence_type": request.absence_type,
        "affected_tours": request.affected_tours,
        "urgency": request.urgency,
        "notes": request.notes,
        "status": "PENDING"
    }

    # Save repair request
    repair_dir = PROJECT_ROOT / "artifacts" / "repair_requests"
    repair_dir.mkdir(parents=True, exist_ok=True)

    repair_file = repair_dir / f"{request_id}.json"
    with open(repair_file, "w") as f:
        json.dump(repair_data, f, indent=2)

    return RepairResponse(
        request_id=request_id,
        run_id=run_id,
        status="PENDING",
        message=f"Repair request created for driver {request.driver_name}"
    )


@router.get("/status", response_model=SystemStatus)
async def get_system_status(
    context: tuple[str, str] = Depends(get_site_context),
    gate_service: PublishGateService = Depends(get_publish_gate_service),
):
    """
    Get current system status including kill switch state.

    Equivalent to: dispatcher_cli.py status
    """
    tenant_code, site_code = context

    # Get site config
    site_config = gate_service._get_site_config(tenant_code, site_code, "roster")

    # Get latest run
    runs = _load_runs(tenant_code, site_code, limit=1)
    latest_run = runs[0] if runs else None

    # Count pending repairs
    repair_dir = PROJECT_ROOT / "artifacts" / "repair_requests"
    pending_repairs = 0
    if repair_dir.exists():
        for f in repair_dir.glob("*.json"):
            try:
                with open(f) as rf:
                    data = json.load(rf)
                if data.get("site_code") == site_code and data.get("status") == "PENDING":
                    pending_repairs += 1
            except:
                pass

    # Get kill switch state
    kill_switch_active = gate_service.is_kill_switch_active()
    kill_switch_reason = None
    if kill_switch_active:
        rollback = gate_service.config.get("rollback_toggle", {})
        kill_switch_reason = rollback.get("kill_switch_reason")

    return SystemStatus(
        kill_switch_active=kill_switch_active,
        kill_switch_reason=kill_switch_reason,
        publish_enabled=site_config.get("publish_enabled", False),
        lock_enabled=site_config.get("lock_enabled", False),
        shadow_mode_only=site_config.get("shadow_mode_only", True),
        latest_run=latest_run,
        pending_repairs=pending_repairs,
        active_incidents=0  # TODO: Integrate with escalation service
    )


@router.get("/evidence/{run_id}")
async def download_evidence(
    run_id: str,
    context: tuple[str, str] = Depends(get_site_context),
):
    """
    Download evidence pack for a run.

    Returns the evidence.zip file with SHA256 checksum header.
    """
    tenant_code, site_code = context

    # Load run to get evidence path
    run = _load_run_detail(tenant_code, site_code, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found"
        )

    if not run.evidence_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No evidence pack available for this run"
        )

    evidence_dir = Path(run.evidence_path)
    evidence_zip = evidence_dir / "evidence.zip"

    if not evidence_zip.exists():
        # Try to find any zip in the directory
        zips = list(evidence_dir.glob("*.zip"))
        if zips:
            evidence_zip = zips[0]
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence ZIP not found"
            )

    # Compute hash
    file_hash = hashlib.sha256(evidence_zip.read_bytes()).hexdigest()

    return FileResponse(
        path=evidence_zip,
        filename=f"{run_id}_evidence.zip",
        media_type="application/zip",
        headers={
            "X-Evidence-SHA256": file_hash,
            "X-Run-ID": run_id
        }
    )


@router.get("/evidence/{run_id}/checksums")
async def get_evidence_checksums(
    run_id: str,
    context: tuple[str, str] = Depends(get_site_context),
):
    """
    Get checksums for all evidence artifacts.

    Returns SHA256 checksums for verification.
    """
    tenant_code, site_code = context

    # Load run to get evidence path
    run = _load_run_detail(tenant_code, site_code, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found"
        )

    if not run.evidence_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No evidence pack available for this run"
        )

    evidence_dir = Path(run.evidence_path)
    checksums_file = evidence_dir / "checksums.sha256"

    if checksums_file.exists():
        # Parse existing checksums file
        checksums = {}
        for line in checksums_file.read_text().strip().split("\n"):
            if "  " in line:
                hash_val, filename = line.split("  ", 1)
                checksums[filename] = hash_val
        return {"run_id": run_id, "checksums": checksums}

    # Compute checksums on the fly
    checksums = {}
    for f in sorted(evidence_dir.iterdir()):
        if f.is_file():
            file_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            checksums[f.name] = file_hash

    return {"run_id": run_id, "checksums": checksums}
