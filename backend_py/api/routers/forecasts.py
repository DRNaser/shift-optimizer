"""
SOLVEREIGN V3.3a API - Forecasts Router
=======================================

Forecast ingest and status endpoints.
"""

import hashlib
import json
from datetime import date, datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager, check_idempotency, record_idempotency
from ..exceptions import ForecastNotFoundError, ForecastValidationError


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class ForecastIngestRequest(BaseModel):
    """Request to ingest a new forecast."""
    raw_text: str = Field(..., min_length=1, description="Raw forecast text (tour lines)")
    source: str = Field(default="api", description="Source of forecast (api, slack, csv)")
    week_anchor_date: Optional[date] = Field(None, description="Monday of the forecast week")
    notes: Optional[str] = Field(None, description="Optional notes")


class ParsedTour(BaseModel):
    """Parsed tour information."""
    line_no: int
    day: int
    start_ts: str
    end_ts: str
    duration_min: int
    count: int
    depot: Optional[str] = None
    skill: Optional[str] = None
    parse_status: str
    warnings: List[str] = []
    errors: List[str] = []


class ForecastIngestResponse(BaseModel):
    """Response after ingesting a forecast."""
    forecast_version_id: int
    status: str  # PASS, WARN, FAIL
    input_hash: str
    tours_count: int
    instances_count: int
    parse_errors_count: int
    parse_warnings_count: int
    created_at: datetime
    message: str


class ForecastStatusResponse(BaseModel):
    """Detailed forecast status."""
    id: int
    status: str
    source: str
    input_hash: str
    week_anchor_date: Optional[date]
    tours_count: int
    instances_count: int
    plans_count: int
    latest_plan_status: Optional[str]
    created_at: datetime
    notes: Optional[str]


class ForecastListItem(BaseModel):
    """Forecast list item."""
    id: int
    status: str
    source: str
    tours_count: int
    created_at: datetime
    has_locked_plan: bool


class ForecastListResponse(BaseModel):
    """Paginated forecast list."""
    items: List[ForecastListItem]
    total: int
    page: int
    page_size: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", response_model=ForecastIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_forecast(
    request: ForecastIngestRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Ingest a new forecast.

    Parses the raw text, validates tours, and creates:
    - forecast_version record
    - tours_raw records (parse results)
    - tours_normalized records (canonical tours)
    - tour_instances records (expanded templates)

    Idempotency:
    - If X-Idempotency-Key provided with same payload: returns cached response
    - If X-Idempotency-Key provided with different payload: returns 409 Conflict

    Returns forecast ID and parse status.
    """
    # Import parser here to avoid circular imports
    from v3.parser import parse_forecast_text
    from v3.db_instances import expand_tour_template

    # ==========================================================================
    # IDEMPOTENCY CHECK (before any processing)
    # ==========================================================================
    endpoint = "/api/v1/forecasts"
    request_hash = None

    if x_idempotency_key:
        # Compute hash of request body
        body_json = json.dumps({
            "raw_text": request.raw_text,
            "source": request.source,
            "week_anchor_date": str(request.week_anchor_date) if request.week_anchor_date else None,
            "notes": request.notes,
        }, sort_keys=True)
        request_hash = hashlib.sha256(body_json.encode()).hexdigest()

        # Check idempotency in database
        async with db.connection() as conn:
            idempotency_result = await check_idempotency(
                conn,
                tenant.tenant_id,
                x_idempotency_key,
                endpoint,
                request_hash,
            )

        # Handle HIT: return cached response
        if idempotency_result["status"] == "HIT":
            cached = idempotency_result["cached_response"]
            return JSONResponse(
                status_code=idempotency_result["cached_status"] or 201,
                content=cached,
                headers={"X-Idempotency-Replayed": "true"}
            )

        # Handle MISMATCH: return 409 Conflict
        if idempotency_result["status"] == "MISMATCH":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "IDEMPOTENCY_MISMATCH",
                    "message": "Same idempotency key used with different request payload",
                    "idempotency_key": x_idempotency_key,
                    "new_request_hash": request_hash,
                }
            )

    # ==========================================================================
    # PROCESS REQUEST (idempotency status is NEW or no key provided)
    # ==========================================================================
    try:
        # Parse forecast with tenant_id
        # Convert week_anchor_date to string if provided
        week_anchor = None
        if request.week_anchor_date:
            week_anchor = request.week_anchor_date.isoformat()

        parse_result = parse_forecast_text(
            raw_text=request.raw_text,
            source=request.source,
            save_to_db=True,
            week_anchor_date=week_anchor,
            tenant_id=tenant.tenant_id,
        )

        # Expand instances if not FAIL (sync function, use run_in_executor)
        instances_count = 0
        if parse_result["status"] != "FAIL":
            import asyncio
            loop = asyncio.get_event_loop()
            instances_count = await loop.run_in_executor(
                None,
                expand_tour_template,
                parse_result["forecast_version_id"]
            )

        # Determine message
        if parse_result["status"] == "PASS":
            message = f"Forecast ingested successfully: {parse_result['tours_count']} tours"
        elif parse_result["status"] == "WARN":
            message = f"Forecast ingested with warnings: {parse_result['warnings_count']} warnings"
        else:
            message = f"Forecast validation failed: {parse_result['errors_count']} errors"

        response_data = ForecastIngestResponse(
            forecast_version_id=parse_result["forecast_version_id"],
            status=parse_result["status"],
            input_hash=parse_result["input_hash"],
            tours_count=parse_result["tours_count"],
            instances_count=instances_count,
            parse_errors_count=parse_result.get("errors_count", 0),
            parse_warnings_count=parse_result.get("warnings_count", 0),
            created_at=datetime.now(),
            message=message,
        )

        # ==========================================================================
        # RECORD IDEMPOTENCY (after successful processing)
        # ==========================================================================
        if x_idempotency_key and request_hash:
            async with db.connection() as conn:
                await record_idempotency(
                    conn,
                    tenant.tenant_id,
                    x_idempotency_key,
                    endpoint,
                    "POST",
                    request_hash,
                    201,  # status code
                    response_data.model_dump(mode="json"),
                )

        return response_data

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Forecast parsing failed: {str(e)}"
        )


@router.get("/{forecast_id}", response_model=ForecastStatusResponse)
async def get_forecast_status(
    forecast_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Get detailed forecast status.

    Returns:
    - Parse status and tour counts
    - Associated plan information
    - Instance expansion status
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Get forecast
            await cur.execute(
                """
                SELECT
                    fv.id, fv.status, fv.source, fv.input_hash,
                    fv.week_anchor_date, fv.created_at, fv.notes,
                    (SELECT COUNT(*) FROM tours_normalized WHERE forecast_version_id = fv.id) as tours_count,
                    (SELECT COUNT(*) FROM tour_instances WHERE forecast_version_id = fv.id) as instances_count,
                    (SELECT COUNT(*) FROM plan_versions WHERE forecast_version_id = fv.id) as plans_count,
                    (SELECT status FROM plan_versions WHERE forecast_version_id = fv.id ORDER BY created_at DESC LIMIT 1) as latest_plan_status
                FROM forecast_versions fv
                WHERE fv.id = %s AND fv.tenant_id = %s
                """,
                (forecast_id, tenant.tenant_id)
            )
            row = await cur.fetchone()

            if not row:
                raise ForecastNotFoundError(forecast_id, tenant.tenant_id)

            return ForecastStatusResponse(
                id=row["id"],
                status=row["status"],
                source=row["source"],
                input_hash=row["input_hash"],
                week_anchor_date=row["week_anchor_date"],
                tours_count=row["tours_count"] or 0,
                instances_count=row["instances_count"] or 0,
                plans_count=row["plans_count"] or 0,
                latest_plan_status=row["latest_plan_status"],
                created_at=row["created_at"],
                notes=row["notes"],
            )


@router.get("", response_model=ForecastListResponse)
async def list_forecasts(
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
):
    """
    List forecasts for tenant.

    Supports pagination and status filtering.
    """
    offset = (page - 1) * page_size

    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Build query
            where_clause = "WHERE fv.tenant_id = %s"
            params = [tenant.tenant_id]

            if status_filter:
                where_clause += " AND fv.status = %s"
                params.append(status_filter)

            # Get total count
            await cur.execute(
                f"SELECT COUNT(*) as total FROM forecast_versions fv {where_clause}",
                params
            )
            total = (await cur.fetchone())["total"]

            # Get paginated results
            await cur.execute(
                f"""
                SELECT
                    fv.id, fv.status, fv.source, fv.created_at,
                    (SELECT COUNT(*) FROM tours_normalized WHERE forecast_version_id = fv.id) as tours_count,
                    EXISTS(
                        SELECT 1 FROM plan_versions pv
                        WHERE pv.forecast_version_id = fv.id AND pv.status = 'LOCKED'
                    ) as has_locked_plan
                FROM forecast_versions fv
                {where_clause}
                ORDER BY fv.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset]
            )
            rows = await cur.fetchall()

            items = [
                ForecastListItem(
                    id=r["id"],
                    status=r["status"],
                    source=r["source"],
                    tours_count=r["tours_count"] or 0,
                    created_at=r["created_at"],
                    has_locked_plan=r["has_locked_plan"],
                )
                for r in rows
            ]

            return ForecastListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
            )
