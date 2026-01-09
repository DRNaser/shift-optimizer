"""
SOLVEREIGN V3.8 - Master Data Layer API Router
===============================================

Endpoints for canonical entity resolution and external ID mapping.

Key Principle: Packs never store external IDs directly. All external IDs
are resolved to canonical UUIDs via this API.

Mapping Rule:
    (tenant_id, external_system, entity_type, external_id) -> internal_uuid

ENDPOINTS:
    POST /api/v1/masterdata/resolve       - Resolve or create single mapping
    POST /api/v1/masterdata/resolve-bulk  - Batch resolve multiple IDs
    GET  /api/v1/masterdata/sites         - List tenant sites
    GET  /api/v1/masterdata/vehicles      - List tenant vehicles
    GET  /api/v1/masterdata/mappings      - List external mappings
"""

import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/masterdata", tags=["masterdata"])


# =============================================================================
# SCHEMAS
# =============================================================================

class ResolveRequest(BaseModel):
    """Request to resolve an external ID to canonical internal ID."""
    external_system: str = Field(..., min_length=1, max_length=100,
        description="Source system (e.g., 'fls', 'sap', 'google_sheets')")
    entity_type: str = Field(..., min_length=1, max_length=50,
        description="Entity type (e.g., 'driver', 'vehicle', 'tour', 'site')")
    external_id: str = Field(..., min_length=1, max_length=255,
        description="External system's identifier")
    create_payload: Optional[Dict[str, Any]] = Field(None,
        description="If provided and mapping not found, create entity with this data")

    @validator('entity_type')
    def validate_entity_type(cls, v):
        allowed = {'driver', 'vehicle', 'tour', 'site', 'location', 'customer', 'skill', 'zone'}
        if v.lower() not in allowed:
            # Allow custom types but warn
            logger.warning(f"Non-standard entity_type: {v}")
        return v.lower()


class ResolveResponse(BaseModel):
    """Response from resolve endpoint."""
    found: bool = Field(..., description="Whether mapping was found or created")
    internal_id: Optional[str] = Field(None, description="Canonical internal UUID")
    external_id: str = Field(..., description="Original external ID")
    entity_type: str = Field(..., description="Entity type")
    created: bool = Field(False, description="True if entity was created (not just found)")
    error: Optional[str] = Field(None, description="Error message if resolution failed")


class BulkResolveRequest(BaseModel):
    """Request to resolve multiple external IDs."""
    external_system: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(..., min_length=1, max_length=50)
    external_ids: List[str] = Field(..., min_items=1, max_items=1000,
        description="List of external IDs to resolve")

    @validator('entity_type')
    def validate_entity_type(cls, v):
        return v.lower()


class BulkResolveItem(BaseModel):
    """Single item in bulk resolve response."""
    external_id: str
    internal_id: Optional[str] = None
    found: bool


class BulkResolveResponse(BaseModel):
    """Response from bulk resolve endpoint."""
    total: int = Field(..., description="Total IDs requested")
    found: int = Field(..., description="Number found")
    not_found: int = Field(..., description="Number not found")
    results: List[BulkResolveItem] = Field(..., description="Resolution results")


class MappingResponse(BaseModel):
    """External mapping response."""
    id: str
    external_system: str
    entity_type: str
    external_id: str
    internal_id: str
    sync_status: str
    last_synced_at: Optional[str] = None
    created_at: str


class SiteResponse(BaseModel):
    """Site entity response."""
    id: str
    site_code: str
    name: str
    timezone: str
    is_active: bool
    created_at: str


class VehicleResponse(BaseModel):
    """Vehicle entity response."""
    id: str
    vehicle_code: str
    name: Optional[str] = None
    vehicle_type: str
    capacity_weight_kg: Optional[float] = None
    capacity_volume_m3: Optional[float] = None
    is_active: bool
    created_at: str


class UpsertMappingRequest(BaseModel):
    """Request to create/update a mapping directly."""
    external_system: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=255)
    internal_id: str = Field(..., description="UUID of internal entity")
    metadata: Optional[Dict[str, Any]] = None

    @validator('entity_type')
    def validate_entity_type(cls, v):
        return v.lower()


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/resolve", response_model=ResolveResponse)
async def resolve_external_id(
    request: ResolveRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Resolve external ID to canonical internal ID.

    **Behavior:**
    - If mapping exists: returns internal_id
    - If mapping not found AND create_payload provided: creates entity + mapping
    - If mapping not found AND no payload: returns found=false with error

    **Idempotency:** Safe to call multiple times with same inputs.

    **Example:**
    ```json
    {
        "external_system": "fls",
        "entity_type": "driver",
        "external_id": "DRV-001",
        "create_payload": {"name": "Max Mustermann", "license_class": "C"}
    }
    ```
    """
    async with db.tenant_transaction(tenant.tenant_id) as conn:
        async with conn.cursor() as cur:
            if request.create_payload:
                # Use resolve_or_create function
                import json
                payload_json = json.dumps(request.create_payload)

                await cur.execute(
                    """
                    SELECT masterdata.resolve_or_create(
                        %s, %s, %s, %s, %s::jsonb
                    ) AS result
                    """,
                    (tenant.tenant_id, request.external_system, request.entity_type,
                     request.external_id, payload_json)
                )
                row = await cur.fetchone()
                result = row["result"]

                if result.get("error"):
                    return ResolveResponse(
                        found=False,
                        external_id=request.external_id,
                        entity_type=request.entity_type,
                        error=result.get("error"),
                    )

                internal_id = result.get("internal_id")

                logger.info(
                    "masterdata_resolved",
                    extra={
                        "tenant_id": tenant.tenant_id,
                        "external_system": request.external_system,
                        "entity_type": request.entity_type,
                        "external_id": request.external_id,
                        "internal_id": str(internal_id) if internal_id else None,
                        "created": result.get("created", False),
                    }
                )

                return ResolveResponse(
                    found=True,
                    internal_id=str(internal_id) if internal_id else None,
                    external_id=request.external_id,
                    entity_type=request.entity_type,
                    created=result.get("created", False),
                )
            else:
                # Simple resolve (no create)
                await cur.execute(
                    """
                    SELECT masterdata.resolve_external_id(%s, %s, %s, %s) AS internal_id
                    """,
                    (tenant.tenant_id, request.external_system, request.entity_type,
                     request.external_id)
                )
                row = await cur.fetchone()
                internal_id = row["internal_id"]

                if internal_id:
                    return ResolveResponse(
                        found=True,
                        internal_id=str(internal_id),
                        external_id=request.external_id,
                        entity_type=request.entity_type,
                        created=False,
                    )
                else:
                    return ResolveResponse(
                        found=False,
                        external_id=request.external_id,
                        entity_type=request.entity_type,
                        error="Mapping not found and no create_payload provided",
                    )


@router.post("/resolve-bulk", response_model=BulkResolveResponse)
async def resolve_bulk(
    request: BulkResolveRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Batch resolve multiple external IDs in a single request.

    **Optimized for performance:** Uses single DB roundtrip for all IDs.

    **Returns:** List of resolution results with found/not-found status.

    **Example:**
    ```json
    {
        "external_system": "fls",
        "entity_type": "driver",
        "external_ids": ["DRV-001", "DRV-002", "DRV-003"]
    }
    ```
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Set tenant context for RLS
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant.tenant_id),)
            )

            # Use bulk resolve function
            await cur.execute(
                """
                SELECT * FROM masterdata.resolve_bulk(%s, %s, %s, %s)
                """,
                (tenant.tenant_id, request.external_system, request.entity_type,
                 request.external_ids)
            )
            rows = await cur.fetchall()

            results = []
            found_count = 0

            for row in rows:
                is_found = row["found"]
                if is_found:
                    found_count += 1

                results.append(BulkResolveItem(
                    external_id=row["external_id"],
                    internal_id=str(row["internal_id"]) if row["internal_id"] else None,
                    found=is_found,
                ))

            logger.info(
                "masterdata_bulk_resolved",
                extra={
                    "tenant_id": tenant.tenant_id,
                    "external_system": request.external_system,
                    "entity_type": request.entity_type,
                    "total": len(request.external_ids),
                    "found": found_count,
                }
            )

            return BulkResolveResponse(
                total=len(request.external_ids),
                found=found_count,
                not_found=len(request.external_ids) - found_count,
                results=results,
            )


@router.post("/mappings", response_model=MappingResponse)
async def upsert_mapping(
    request: UpsertMappingRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Create or update an external ID mapping directly.

    **Idempotent:** Safe to call multiple times with same inputs.

    Use this when you already have the internal_id and just need to register the mapping.
    """
    async with db.tenant_transaction(tenant.tenant_id) as conn:
        async with conn.cursor() as cur:
            import json
            metadata_json = json.dumps(request.metadata or {})

            await cur.execute(
                """
                SELECT masterdata.upsert_mapping(%s, %s, %s, %s, %s::uuid, %s::jsonb) AS internal_id
                """,
                (tenant.tenant_id, request.external_system, request.entity_type,
                 request.external_id, request.internal_id, metadata_json)
            )

            # Fetch the created/updated mapping
            await cur.execute(
                """
                SELECT id, external_system, entity_type, external_id, internal_id,
                       sync_status, last_synced_at, created_at
                FROM masterdata.md_external_mappings
                WHERE tenant_id = %s
                  AND external_system = %s
                  AND entity_type = %s
                  AND external_id = %s
                """,
                (tenant.tenant_id, request.external_system, request.entity_type,
                 request.external_id)
            )
            row = await cur.fetchone()

            logger.info(
                "masterdata_mapping_upserted",
                extra={
                    "tenant_id": tenant.tenant_id,
                    "external_system": request.external_system,
                    "entity_type": request.entity_type,
                    "external_id": request.external_id,
                    "internal_id": request.internal_id,
                }
            )

            return MappingResponse(
                id=str(row["id"]),
                external_system=row["external_system"],
                entity_type=row["entity_type"],
                external_id=row["external_id"],
                internal_id=str(row["internal_id"]),
                sync_status=row["sync_status"],
                last_synced_at=str(row["last_synced_at"]) if row["last_synced_at"] else None,
                created_at=str(row["created_at"]),
            )


@router.get("/mappings", response_model=List[MappingResponse])
async def list_mappings(
    external_system: Optional[str] = Query(None, description="Filter by external system"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    limit: int = Query(100, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    List external ID mappings for the tenant.

    Supports filtering by external_system and entity_type.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant.tenant_id),)
            )

            query = """
                SELECT id, external_system, entity_type, external_id, internal_id,
                       sync_status, last_synced_at, created_at
                FROM masterdata.md_external_mappings
                WHERE tenant_id = %s AND sync_status = 'active'
            """
            params = [tenant.tenant_id]

            if external_system:
                query += " AND external_system = %s"
                params.append(external_system)

            if entity_type:
                query += " AND entity_type = %s"
                params.append(entity_type.lower())

            query += " ORDER BY entity_type, external_id LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            await cur.execute(query, tuple(params))
            rows = await cur.fetchall()

            return [
                MappingResponse(
                    id=str(row["id"]),
                    external_system=row["external_system"],
                    entity_type=row["entity_type"],
                    external_id=row["external_id"],
                    internal_id=str(row["internal_id"]),
                    sync_status=row["sync_status"],
                    last_synced_at=str(row["last_synced_at"]) if row["last_synced_at"] else None,
                    created_at=str(row["created_at"]),
                )
                for row in rows
            ]


@router.get("/sites", response_model=List[SiteResponse])
async def list_sites(
    active_only: bool = Query(True, description="Filter active sites only"),
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    List canonical sites for the tenant.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant.tenant_id),)
            )

            query = """
                SELECT id, site_code, name, timezone, is_active, created_at
                FROM masterdata.md_sites
                WHERE tenant_id = %s
            """
            params = [tenant.tenant_id]

            if active_only:
                query += " AND is_active = TRUE"

            query += " ORDER BY site_code"

            await cur.execute(query, tuple(params))
            rows = await cur.fetchall()

            return [
                SiteResponse(
                    id=str(row["id"]),
                    site_code=row["site_code"],
                    name=row["name"],
                    timezone=row["timezone"],
                    is_active=row["is_active"],
                    created_at=str(row["created_at"]),
                )
                for row in rows
            ]


@router.get("/vehicles", response_model=List[VehicleResponse])
async def list_vehicles(
    active_only: bool = Query(True, description="Filter active vehicles only"),
    site_id: Optional[str] = Query(None, description="Filter by site UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    List canonical vehicles for the tenant.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant.tenant_id),)
            )

            query = """
                SELECT id, vehicle_code, name, vehicle_type,
                       capacity_weight_kg, capacity_volume_m3, is_active, created_at
                FROM masterdata.md_vehicles
                WHERE tenant_id = %s
            """
            params = [tenant.tenant_id]

            if active_only:
                query += " AND is_active = TRUE"

            if site_id:
                query += " AND site_id = %s::uuid"
                params.append(site_id)

            query += " ORDER BY vehicle_code"

            await cur.execute(query, tuple(params))
            rows = await cur.fetchall()

            return [
                VehicleResponse(
                    id=str(row["id"]),
                    vehicle_code=row["vehicle_code"],
                    name=row["name"],
                    vehicle_type=row["vehicle_type"],
                    capacity_weight_kg=float(row["capacity_weight_kg"]) if row["capacity_weight_kg"] else None,
                    capacity_volume_m3=float(row["capacity_volume_m3"]) if row["capacity_volume_m3"] else None,
                    is_active=row["is_active"],
                    created_at=str(row["created_at"]),
                )
                for row in rows
            ]


@router.get("/integrity")
async def check_integrity(
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Run MDL integrity checks.

    Returns verification results for RLS, constraints, and functions.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM masterdata.verify_masterdata_integrity()")
            rows = await cur.fetchall()

            results = []
            all_pass = True

            for row in rows:
                status = row["status"]
                if status == "FAIL":
                    all_pass = False

                results.append({
                    "check": row["check_name"],
                    "status": status,
                    "details": row["details"],
                })

            return {
                "overall": "PASS" if all_pass else "FAIL",
                "checks": results,
            }
