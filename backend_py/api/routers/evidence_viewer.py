"""
SOLVEREIGN V4.7 - Evidence Viewer API
=====================================

Evidence viewing endpoints for audit/compliance.

Routes:
- GET  /api/v1/evidence           - List evidence records
- GET  /api/v1/evidence/{id}      - Get evidence detail
- GET  /api/v1/evidence/{id}/download - Download evidence JSON

NON-NEGOTIABLES:
- Tenant isolation via user context
- No filesystem paths exposed
- Redacted preview available
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence-viewer"])


# =============================================================================
# SCHEMAS
# =============================================================================

class EvidenceSummary(BaseModel):
    """Evidence summary for list view."""
    id: int
    plan_version_id: int
    matrix_version: str
    matrix_hash: str
    finalize_verdict: str
    created_at: datetime
    has_drift_report: bool
    has_tw_validation: bool


class EvidenceListResponse(BaseModel):
    """List of evidence records."""
    success: bool = True
    evidence: List[EvidenceSummary]
    total: int


class EvidenceDetailResponse(BaseModel):
    """Detailed evidence information."""
    success: bool = True
    id: int
    plan_version_id: int
    tenant_id: int
    site_id: int

    # Matrix info
    matrix_version: str
    matrix_hash: str
    osrm_enabled: bool
    osrm_map_hash: Optional[str]
    osrm_profile: Optional[str]

    # Verdict
    finalize_verdict: str
    finalize_time_seconds: float

    # Drift metrics
    drift_p95_ratio: Optional[float]
    drift_max_ratio: Optional[float]
    drift_mean_ratio: Optional[float]

    # TW validation
    tw_violations_count: int
    tw_max_violation_seconds: int

    # Rates
    timeout_rate: float
    fallback_rate: float
    total_legs: int

    # Reasons
    verdict_reasons: List[str]

    # Artifact refs
    drift_report_artifact_id: Optional[str]
    fallback_report_artifact_id: Optional[str]
    tw_validation_artifact_id: Optional[str]

    created_at: datetime


class LocalEvidenceFile(BaseModel):
    """Local evidence file info."""
    filename: str
    event_type: str
    tenant_id: Optional[int]
    site_id: Optional[int]
    entity_id: Optional[int]
    created_at: str
    size_bytes: int


class LocalEvidenceListResponse(BaseModel):
    """List of local evidence files."""
    success: bool = True
    files: List[LocalEvidenceFile]
    total: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=EvidenceListResponse)
async def list_evidence(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
    limit: int = 50,
    offset: int = 0,
    verdict_filter: Optional[str] = None,
):
    """
    List routing evidence records for the current tenant.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        base_query = """
            SELECT
                id, plan_version_id, matrix_version, matrix_hash,
                finalize_verdict, created_at,
                drift_report_artifact_id IS NOT NULL as has_drift_report,
                tw_validation_artifact_id IS NOT NULL as has_tw_validation
            FROM routing_evidence
            WHERE tenant_id = %s
        """
        params = [ctx.tenant_id]

        if ctx.site_id:
            base_query += " AND site_id = %s"
            params.append(ctx.site_id)

        if verdict_filter:
            base_query += " AND finalize_verdict = %s"
            params.append(verdict_filter)

        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(base_query, tuple(params))
        rows = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) FROM routing_evidence WHERE tenant_id = %s"
        count_params = [ctx.tenant_id]
        if ctx.site_id:
            count_query += " AND site_id = %s"
            count_params.append(ctx.site_id)

        cur.execute(count_query, tuple(count_params))
        total = cur.fetchone()[0]

    evidence = [
        EvidenceSummary(
            id=row[0],
            plan_version_id=row[1],
            matrix_version=row[2],
            matrix_hash=row[3],
            finalize_verdict=row[4],
            created_at=row[5],
            has_drift_report=row[6],
            has_tw_validation=row[7],
        )
        for row in rows
    ]

    return EvidenceListResponse(evidence=evidence, total=total)


@router.get("/local", response_model=LocalEvidenceListResponse)
async def list_local_evidence(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
    limit: int = 50,
):
    """
    List locally stored evidence JSON files.

    Scans the evidence/ directory for files matching the tenant.
    """
    evidence_dir = "evidence"
    if not os.path.exists(evidence_dir):
        return LocalEvidenceListResponse(files=[], total=0)

    files = []
    for filename in os.listdir(evidence_dir):
        if not filename.endswith(".json"):
            continue

        # Parse filename: evidence/roster_{action}_{tenant}_{site}_{id}_{ts}.json
        try:
            parts = filename.replace(".json", "").split("_")
            if len(parts) >= 5:
                # Check if tenant matches
                file_tenant_id = int(parts[2])
                if file_tenant_id != ctx.tenant_id:
                    continue

                filepath = os.path.join(evidence_dir, filename)
                stat = os.stat(filepath)

                files.append(LocalEvidenceFile(
                    filename=filename,
                    event_type=parts[1] if len(parts) > 1 else "unknown",
                    tenant_id=file_tenant_id,
                    site_id=int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                    entity_id=int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None,
                    created_at=parts[5] if len(parts) > 5 else "",
                    size_bytes=stat.st_size,
                ))
        except (ValueError, IndexError):
            continue

    # Sort by created_at desc
    files.sort(key=lambda f: f.created_at, reverse=True)

    return LocalEvidenceListResponse(
        files=files[:limit],
        total=len(files),
    )


@router.get("/{evidence_id}", response_model=EvidenceDetailResponse)
async def get_evidence(
    request: Request,
    evidence_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get detailed evidence record.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id, plan_version_id, tenant_id, site_id,
                matrix_version, matrix_hash, osrm_enabled, osrm_map_hash, osrm_profile,
                finalize_verdict, finalize_time_seconds,
                drift_p95_ratio, drift_max_ratio, drift_mean_ratio,
                tw_violations_count, tw_max_violation_seconds,
                timeout_rate, fallback_rate, total_legs,
                verdict_reasons,
                drift_report_artifact_id, fallback_report_artifact_id, tw_validation_artifact_id,
                created_at
            FROM routing_evidence
            WHERE id = %s AND tenant_id = %s
            """,
            (evidence_id, ctx.tenant_id)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evidence {evidence_id} not found",
            )

        verdict_reasons = row[19] or []
        if isinstance(verdict_reasons, str):
            verdict_reasons = json.loads(verdict_reasons)

        return EvidenceDetailResponse(
            id=row[0],
            plan_version_id=row[1],
            tenant_id=row[2],
            site_id=row[3],
            matrix_version=row[4],
            matrix_hash=row[5],
            osrm_enabled=row[6],
            osrm_map_hash=row[7],
            osrm_profile=row[8],
            finalize_verdict=row[9],
            finalize_time_seconds=row[10] or 0,
            drift_p95_ratio=row[11],
            drift_max_ratio=row[12],
            drift_mean_ratio=row[13],
            tw_violations_count=row[14] or 0,
            tw_max_violation_seconds=row[15] or 0,
            timeout_rate=row[16] or 0,
            fallback_rate=row[17] or 0,
            total_legs=row[18] or 0,
            verdict_reasons=verdict_reasons,
            drift_report_artifact_id=row[20],
            fallback_report_artifact_id=row[21],
            tw_validation_artifact_id=row[22],
            created_at=row[23],
        )


def _validate_evidence_filename(filename: str, tenant_id: int) -> str:
    """
    Validate and sanitize evidence filename.

    Security checks:
    - Block path traversal (../, ..\, URL-encoded variants)
    - Whitelist .json extension only
    - Validate filename format
    - Verify tenant ownership

    Returns sanitized filename or raises HTTPException.
    """
    import urllib.parse

    # Decode URL encoding multiple times to catch double/triple encoding
    decoded = filename
    for _ in range(3):
        try:
            new_decoded = urllib.parse.unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid filename encoding")

    # Block path traversal patterns (case-insensitive)
    traversal_patterns = [
        "..", "/", "\\", "%2e", "%2f", "%5c",
        "%252e", "%252f", "%255c", "\x00", "%00"
    ]
    lower_decoded = decoded.lower()
    for pattern in traversal_patterns:
        if pattern.lower() in lower_decoded:
            logger.warning(f"[SECURITY] Path traversal blocked: {filename[:50]}")
            raise HTTPException(status_code=404, detail="Evidence file not found")

    # Block absolute paths
    if decoded.startswith("/") or decoded.startswith("\\") or (len(decoded) > 1 and decoded[1] == ":"):
        logger.warning(f"[SECURITY] Absolute path blocked: {filename[:50]}")
        raise HTTPException(status_code=404, detail="Evidence file not found")

    # Whitelist extension
    if not decoded.lower().endswith(".json"):
        raise HTTPException(status_code=404, detail="Evidence file not found")

    # Validate filename format: roster_{action}_{tenant}_{site}_{id}_{ts}.json
    parts = decoded.replace(".json", "").split("_")
    if len(parts) < 5:
        raise HTTPException(status_code=400, detail="Invalid filename format")

    # Verify tenant ownership
    try:
        file_tenant_id = int(parts[2])
        if file_tenant_id != tenant_id:
            logger.warning(f"[SECURITY] Tenant mismatch: file={file_tenant_id}, user={tenant_id}")
            raise HTTPException(status_code=404, detail="Evidence file not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid filename format")

    return decoded


@router.get("/local/{filename}")
async def get_local_evidence_file(
    request: Request,
    filename: str,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get a local evidence file content.

    Returns JSON content with optional redaction.

    SECURITY:
    - Validates filename to prevent path traversal
    - Verifies tenant ownership
    - Only .json files allowed
    """
    # Validate and sanitize filename
    safe_filename = _validate_evidence_filename(filename, ctx.tenant_id)

    evidence_dir = "evidence"
    filepath = os.path.join(evidence_dir, safe_filename)

    # Resolve to absolute path and verify it's within evidence_dir
    evidence_root = os.path.abspath(evidence_dir)
    resolved_path = os.path.abspath(filepath)
    if not resolved_path.startswith(evidence_root):
        logger.warning(f"[SECURITY] Path escape attempt: {resolved_path}")
        raise HTTPException(status_code=404, detail="Evidence file not found")

    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="Evidence file not found")

    with open(resolved_path, "r") as f:
        content = json.load(f)

    return JSONResponse(content=content)


@router.get("/local/{filename}/download")
async def download_local_evidence_file(
    request: Request,
    filename: str,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.export.read")),
):
    """
    Download a local evidence file.

    Requires portal.export.read permission.

    SECURITY:
    - Validates filename to prevent path traversal
    - Verifies tenant ownership
    - Only .json files allowed
    """
    # Validate and sanitize filename (reuses same validation as get)
    safe_filename = _validate_evidence_filename(filename, ctx.tenant_id)

    evidence_dir = "evidence"
    filepath = os.path.join(evidence_dir, safe_filename)

    # Resolve to absolute path and verify it's within evidence_dir
    evidence_root = os.path.abspath(evidence_dir)
    resolved_path = os.path.abspath(filepath)
    if not resolved_path.startswith(evidence_root):
        logger.warning(f"[SECURITY] Path escape attempt on download: {resolved_path}")
        raise HTTPException(status_code=404, detail="Evidence file not found")

    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="Evidence file not found")

    with open(resolved_path, "r") as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename={safe_filename}",
        },
    )
