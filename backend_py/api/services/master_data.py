"""
SOLVEREIGN V3.7 - Master Data Mapping Service
==============================================

Provides canonical ID resolution for external identifiers.
Ensures packs never store external IDs directly.

Entities:
- Tenant: Multi-tenant isolation
- Site: Depot/location within tenant
- ExternalMapping: External ID → Canonical ID resolution
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class EntityType(str, Enum):
    """Supported entity types for external mapping."""
    DRIVER = "driver"
    VEHICLE = "vehicle"
    TOUR = "tour"
    DEPOT = "depot"
    SKILL = "skill"
    CUSTOMER = "customer"


class MappingStatus(str, Enum):
    """Status of external mapping."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"  # Old ID, replaced by newer mapping
    DELETED = "deleted"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Tenant:
    """Tenant entity."""
    id: int
    code: str
    name: str
    is_active: bool = True
    config: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Site:
    """Site/depot entity within a tenant."""
    id: int
    tenant_id: int
    code: str
    name: str
    is_active: bool = True
    timezone: str = "Europe/Vienna"
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ExternalMapping:
    """Maps external IDs to canonical internal IDs."""
    id: int
    tenant_id: int
    site_id: Optional[int]
    entity_type: EntityType
    external_id: str
    canonical_id: int
    source_system: str  # e.g., "customer_erp", "fls_export"
    status: MappingStatus = MappingStatus.ACTIVE
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class MappingResult:
    """Result of ID resolution."""
    found: bool
    canonical_id: Optional[int] = None
    external_id: Optional[str] = None
    entity_type: Optional[EntityType] = None
    mapping: Optional[ExternalMapping] = None
    created_new: bool = False


# =============================================================================
# SERVICE
# =============================================================================

class MasterDataService:
    """
    Master data service for external ID resolution.

    Key principle: Packs never store external IDs directly.
    All external IDs are resolved to canonical IDs via this service.
    """

    def __init__(self, db_manager):
        """
        Initialize with database manager.

        Args:
            db_manager: Database manager with connection pool
        """
        self.db = db_manager
        self._cache: Dict[str, ExternalMapping] = {}
        self._cache_ttl = 300  # 5 minutes

    # =========================================================================
    # TENANT OPERATIONS
    # =========================================================================

    async def get_tenant_by_code(self, tenant_code: str) -> Optional[Tenant]:
        """Get tenant by code."""
        async with self.db.connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, code, name, is_active, config, created_at, updated_at
                FROM tenants
                WHERE code = $1 AND is_active = TRUE
                """,
                tenant_code
            )
            if row:
                return Tenant(
                    id=row["id"],
                    code=row["code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    config=row.get("config"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            return None

    async def list_tenants(self, active_only: bool = True) -> List[Tenant]:
        """List all tenants (platform role required)."""
        async with self.db.connection() as conn:
            query = """
                SELECT id, code, name, is_active, config, created_at, updated_at
                FROM tenants
            """
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY code"

            rows = await conn.fetch(query)
            return [
                Tenant(
                    id=row["id"],
                    code=row["code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    config=row.get("config"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
                for row in rows
            ]

    # =========================================================================
    # SITE OPERATIONS
    # =========================================================================

    async def get_site_by_code(self, tenant_id: int, site_code: str) -> Optional[Site]:
        """Get site by code within tenant."""
        async with self.db.connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, code, name, is_active, timezone,
                       lat, lng, address, config, created_at, updated_at
                FROM sites
                WHERE tenant_id = $1 AND code = $2 AND is_active = TRUE
                """,
                tenant_id, site_code
            )
            if row:
                return Site(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    code=row["code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    timezone=row.get("timezone", "Europe/Vienna"),
                    lat=row.get("lat"),
                    lng=row.get("lng"),
                    address=row.get("address"),
                    config=row.get("config"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            return None

    async def list_sites(self, tenant_id: int, active_only: bool = True) -> List[Site]:
        """List sites for tenant."""
        async with self.db.connection() as conn:
            query = """
                SELECT id, tenant_id, code, name, is_active, timezone,
                       lat, lng, address, config, created_at, updated_at
                FROM sites
                WHERE tenant_id = $1
            """
            if active_only:
                query += " AND is_active = TRUE"
            query += " ORDER BY code"

            rows = await conn.fetch(query, tenant_id)
            return [
                Site(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    code=row["code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    timezone=row.get("timezone", "Europe/Vienna"),
                    lat=row.get("lat"),
                    lng=row.get("lng"),
                    address=row.get("address"),
                    config=row.get("config"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
                for row in rows
            ]

    async def create_site(
        self,
        tenant_id: int,
        code: str,
        name: str,
        timezone: str = "Europe/Vienna",
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        address: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Site:
        """Create a new site."""
        async with self.db.connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sites (tenant_id, code, name, timezone, lat, lng, address, config)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, tenant_id, code, name, is_active, timezone, lat, lng, address, config, created_at, updated_at
                """,
                tenant_id, code, name, timezone, lat, lng, address, config
            )
            return Site(
                id=row["id"],
                tenant_id=row["tenant_id"],
                code=row["code"],
                name=row["name"],
                is_active=row["is_active"],
                timezone=row["timezone"],
                lat=row.get("lat"),
                lng=row.get("lng"),
                address=row.get("address"),
                config=row.get("config"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    # =========================================================================
    # EXTERNAL MAPPING OPERATIONS
    # =========================================================================

    async def resolve_external_id(
        self,
        tenant_id: int,
        entity_type: EntityType,
        external_id: str,
        site_id: Optional[int] = None,
    ) -> MappingResult:
        """
        Resolve external ID to canonical ID.

        Args:
            tenant_id: Tenant context
            entity_type: Type of entity (driver, vehicle, etc.)
            external_id: Customer's external identifier
            site_id: Optional site context

        Returns:
            MappingResult with canonical_id if found
        """
        # Check cache first
        cache_key = self._cache_key(tenant_id, entity_type, external_id, site_id)
        cached = self._cache.get(cache_key)
        if cached:
            return MappingResult(
                found=True,
                canonical_id=cached.canonical_id,
                external_id=external_id,
                entity_type=entity_type,
                mapping=cached,
                created_new=False,
            )

        # Query database
        async with self.db.connection() as conn:
            query = """
                SELECT id, tenant_id, site_id, entity_type, external_id,
                       canonical_id, source_system, status, metadata, created_at, updated_at
                FROM external_mappings
                WHERE tenant_id = $1
                  AND entity_type = $2
                  AND external_id = $3
                  AND status = 'active'
            """
            params = [tenant_id, entity_type.value, external_id]

            if site_id is not None:
                query += " AND (site_id = $4 OR site_id IS NULL)"
                params.append(site_id)

            query += " ORDER BY site_id DESC NULLS LAST LIMIT 1"

            row = await conn.fetchone(query, *params)

            if row:
                mapping = ExternalMapping(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    site_id=row.get("site_id"),
                    entity_type=EntityType(row["entity_type"]),
                    external_id=row["external_id"],
                    canonical_id=row["canonical_id"],
                    source_system=row["source_system"],
                    status=MappingStatus(row["status"]),
                    metadata=row.get("metadata"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )

                # Update cache
                self._cache[cache_key] = mapping

                return MappingResult(
                    found=True,
                    canonical_id=mapping.canonical_id,
                    external_id=external_id,
                    entity_type=entity_type,
                    mapping=mapping,
                    created_new=False,
                )

            return MappingResult(
                found=False,
                external_id=external_id,
                entity_type=entity_type,
            )

    async def upsert_mapping(
        self,
        tenant_id: int,
        entity_type: EntityType,
        external_id: str,
        canonical_id: int,
        source_system: str,
        site_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExternalMapping:
        """
        Create or update external ID mapping.

        Args:
            tenant_id: Tenant context
            entity_type: Type of entity
            external_id: Customer's external identifier
            canonical_id: Internal canonical ID
            source_system: Source of the mapping
            site_id: Optional site context
            metadata: Optional metadata

        Returns:
            Created or updated mapping
        """
        async with self.db.connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO external_mappings
                    (tenant_id, site_id, entity_type, external_id, canonical_id, source_system, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (tenant_id, entity_type, external_id)
                    WHERE site_id IS NOT DISTINCT FROM $2
                DO UPDATE SET
                    canonical_id = EXCLUDED.canonical_id,
                    source_system = EXCLUDED.source_system,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id, tenant_id, site_id, entity_type, external_id,
                          canonical_id, source_system, status, metadata, created_at, updated_at
                """,
                tenant_id, site_id, entity_type.value, external_id,
                canonical_id, source_system, metadata
            )

            mapping = ExternalMapping(
                id=row["id"],
                tenant_id=row["tenant_id"],
                site_id=row.get("site_id"),
                entity_type=EntityType(row["entity_type"]),
                external_id=row["external_id"],
                canonical_id=row["canonical_id"],
                source_system=row["source_system"],
                status=MappingStatus(row["status"]),
                metadata=row.get("metadata"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            # Update cache
            cache_key = self._cache_key(tenant_id, entity_type, external_id, site_id)
            self._cache[cache_key] = mapping

            logger.info(
                f"Upserted mapping: {entity_type.value}/{external_id} -> {canonical_id}",
                extra={
                    "tenant_id": tenant_id,
                    "entity_type": entity_type.value,
                    "external_id": external_id,
                    "canonical_id": canonical_id,
                }
            )

            return mapping

    async def list_mappings(
        self,
        tenant_id: int,
        entity_type: Optional[EntityType] = None,
        site_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExternalMapping]:
        """List external mappings."""
        async with self.db.connection() as conn:
            query = """
                SELECT id, tenant_id, site_id, entity_type, external_id,
                       canonical_id, source_system, status, metadata, created_at, updated_at
                FROM external_mappings
                WHERE tenant_id = $1 AND status = 'active'
            """
            params = [tenant_id]
            param_idx = 2

            if entity_type:
                query += f" AND entity_type = ${param_idx}"
                params.append(entity_type.value)
                param_idx += 1

            if site_id is not None:
                query += f" AND (site_id = ${param_idx} OR site_id IS NULL)"
                params.append(site_id)
                param_idx += 1

            query += f" ORDER BY entity_type, external_id LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([limit, offset])

            rows = await conn.fetch(query, *params)

            return [
                ExternalMapping(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    site_id=row.get("site_id"),
                    entity_type=EntityType(row["entity_type"]),
                    external_id=row["external_id"],
                    canonical_id=row["canonical_id"],
                    source_system=row["source_system"],
                    status=MappingStatus(row["status"]),
                    metadata=row.get("metadata"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
                for row in rows
            ]

    async def deprecate_mapping(
        self,
        tenant_id: int,
        entity_type: EntityType,
        external_id: str,
        site_id: Optional[int] = None,
    ) -> bool:
        """Mark a mapping as deprecated."""
        async with self.db.connection() as conn:
            result = await conn.execute(
                """
                UPDATE external_mappings
                SET status = 'deprecated', updated_at = NOW()
                WHERE tenant_id = $1
                  AND entity_type = $2
                  AND external_id = $3
                  AND (site_id = $4 OR ($4 IS NULL AND site_id IS NULL))
                  AND status = 'active'
                """,
                tenant_id, entity_type.value, external_id, site_id
            )

            # Clear cache
            cache_key = self._cache_key(tenant_id, entity_type, external_id, site_id)
            self._cache.pop(cache_key, None)

            return result != "UPDATE 0"

    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================

    async def resolve_batch(
        self,
        tenant_id: int,
        entity_type: EntityType,
        external_ids: List[str],
        site_id: Optional[int] = None,
    ) -> Dict[str, MappingResult]:
        """
        Resolve multiple external IDs in batch.

        Returns dict mapping external_id -> MappingResult
        """
        results = {}

        for ext_id in external_ids:
            results[ext_id] = await self.resolve_external_id(
                tenant_id, entity_type, ext_id, site_id
            )

        return results

    async def upsert_batch(
        self,
        tenant_id: int,
        mappings: List[Tuple[EntityType, str, int, str]],  # (type, ext_id, canonical_id, source)
        site_id: Optional[int] = None,
    ) -> int:
        """
        Upsert multiple mappings in batch.

        Returns count of mappings upserted.
        """
        count = 0
        for entity_type, external_id, canonical_id, source_system in mappings:
            await self.upsert_mapping(
                tenant_id=tenant_id,
                entity_type=entity_type,
                external_id=external_id,
                canonical_id=canonical_id,
                source_system=source_system,
                site_id=site_id,
            )
            count += 1

        return count

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_cache(self, tenant_id: Optional[int] = None) -> int:
        """Clear mapping cache."""
        if tenant_id is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        else:
            keys_to_remove = [
                k for k in self._cache.keys()
                if k.startswith(f"{tenant_id}:")
            ]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    def _cache_key(
        self,
        tenant_id: int,
        entity_type: EntityType,
        external_id: str,
        site_id: Optional[int],
    ) -> str:
        """Generate cache key."""
        return f"{tenant_id}:{site_id or 'null'}:{entity_type.value}:{external_id}"


# =============================================================================
# ROUTER (FastAPI)
# =============================================================================

def create_master_data_router(get_db, get_tenant):
    """
    Create FastAPI router for master data endpoints.

    Args:
        get_db: Dependency to get database manager
        get_tenant: Dependency to get tenant context
    """
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel
    from typing import Optional as Opt

    router = APIRouter(prefix="/api/v1/master-data", tags=["master-data"])

    # Pydantic models
    class SiteCreate(BaseModel):
        code: str
        name: str
        timezone: str = "Europe/Vienna"
        lat: Opt[float] = None
        lng: Opt[float] = None
        address: Opt[str] = None

    class MappingCreate(BaseModel):
        entity_type: str
        external_id: str
        canonical_id: int
        source_system: str
        site_id: Opt[int] = None
        metadata: Opt[dict] = None

    class MappingResolve(BaseModel):
        entity_type: str
        external_id: str
        site_id: Opt[int] = None

    # Endpoints
    @router.get("/sites")
    async def list_sites(
        active_only: bool = True,
        db=Depends(get_db),
        tenant=Depends(get_tenant),
    ):
        """List sites for current tenant."""
        service = MasterDataService(db)
        sites = await service.list_sites(tenant.id, active_only)
        return {
            "sites": [
                {
                    "id": s.id,
                    "code": s.code,
                    "name": s.name,
                    "timezone": s.timezone,
                    "lat": s.lat,
                    "lng": s.lng,
                    "is_active": s.is_active,
                }
                for s in sites
            ]
        }

    @router.post("/sites")
    async def create_site(
        site: SiteCreate,
        db=Depends(get_db),
        tenant=Depends(get_tenant),
    ):
        """Create a new site."""
        service = MasterDataService(db)
        created = await service.create_site(
            tenant_id=tenant.id,
            code=site.code,
            name=site.name,
            timezone=site.timezone,
            lat=site.lat,
            lng=site.lng,
            address=site.address,
        )
        return {
            "id": created.id,
            "code": created.code,
            "name": created.name,
        }

    @router.post("/mappings/resolve")
    async def resolve_mapping(
        request: MappingResolve,
        db=Depends(get_db),
        tenant=Depends(get_tenant),
    ):
        """Resolve external ID to canonical ID."""
        try:
            entity_type = EntityType(request.entity_type)
        except ValueError:
            raise HTTPException(400, f"Invalid entity_type: {request.entity_type}")

        service = MasterDataService(db)
        result = await service.resolve_external_id(
            tenant_id=tenant.id,
            entity_type=entity_type,
            external_id=request.external_id,
            site_id=request.site_id,
        )

        return {
            "found": result.found,
            "canonical_id": result.canonical_id,
            "external_id": result.external_id,
            "entity_type": request.entity_type,
        }

    @router.post("/mappings")
    async def upsert_mapping(
        mapping: MappingCreate,
        db=Depends(get_db),
        tenant=Depends(get_tenant),
    ):
        """Create or update external ID mapping."""
        try:
            entity_type = EntityType(mapping.entity_type)
        except ValueError:
            raise HTTPException(400, f"Invalid entity_type: {mapping.entity_type}")

        service = MasterDataService(db)
        created = await service.upsert_mapping(
            tenant_id=tenant.id,
            entity_type=entity_type,
            external_id=mapping.external_id,
            canonical_id=mapping.canonical_id,
            source_system=mapping.source_system,
            site_id=mapping.site_id,
            metadata=mapping.metadata,
        )

        return {
            "id": created.id,
            "external_id": created.external_id,
            "canonical_id": created.canonical_id,
            "entity_type": created.entity_type.value,
        }

    @router.get("/mappings")
    async def list_mappings(
        entity_type: Opt[str] = None,
        site_id: Opt[int] = None,
        limit: int = Query(default=100, le=1000),
        offset: int = Query(default=0, ge=0),
        db=Depends(get_db),
        tenant=Depends(get_tenant),
    ):
        """List external mappings."""
        et = None
        if entity_type:
            try:
                et = EntityType(entity_type)
            except ValueError:
                raise HTTPException(400, f"Invalid entity_type: {entity_type}")

        service = MasterDataService(db)
        mappings = await service.list_mappings(
            tenant_id=tenant.id,
            entity_type=et,
            site_id=site_id,
            limit=limit,
            offset=offset,
        )

        return {
            "mappings": [
                {
                    "id": m.id,
                    "entity_type": m.entity_type.value,
                    "external_id": m.external_id,
                    "canonical_id": m.canonical_id,
                    "source_system": m.source_system,
                    "site_id": m.site_id,
                }
                for m in mappings
            ],
            "count": len(mappings),
        }

    return router
