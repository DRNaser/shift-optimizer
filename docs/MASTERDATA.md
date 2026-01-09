# Master Data Layer (MDL) - Kernel Service

> **Version**: V3.8.0
> **Status**: COMPLETE
> **Migration**: `028_masterdata.sql`

---

## Overview

The Master Data Layer (MDL) is a kernel subsystem that provides canonical entity management and external ID mapping for SOLVEREIGN domain packs.

**Key Principle**: Packs NEVER store external IDs directly. All external identifiers from customer systems (FLS, SAP, Google Sheets, etc.) are resolved to canonical internal UUIDs through MDL.

```
┌─────────────────────────────────────────────────────────────────┐
│                    MASTER DATA LAYER                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   EXTERNAL SYSTEMS              MDL KERNEL              PACKS    │
│   ├─ FLS Export        →     ┌─────────────┐      ←   Routing   │
│   ├─ SAP Integration   →     │  RESOLVE    │      ←   Roster    │
│   ├─ Google Sheets     →     │  external   │      ←   Dispatch  │
│   └─ Customer ERP      →     │  → internal │      ←   Future    │
│                              └─────────────┘                     │
│                                     ↓                            │
│                        md_external_mappings                      │
│                  (tenant, system, type, ext_id)                  │
│                              → internal_uuid                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Entity Catalog (P0)

| Entity | Table | Purpose |
|--------|-------|---------|
| **Site** | `masterdata.md_sites` | Depots, hubs, branches |
| **Location** | `masterdata.md_locations` | Geocoded addresses (lat/lng) |
| **Vehicle** | `masterdata.md_vehicles` | Fleet vehicles with capacity |
| **External Mapping** | `masterdata.md_external_mappings` | External ID → Internal UUID |

### Future Entities (P1+)

- `md_drivers` - Driver master data
- `md_customers` - Customer/delivery points
- `md_skills` - Driver skills/certifications
- `md_zones` - Geographic zones/regions

---

## Mapping Rule

The core mapping constraint ensures one internal ID per external identifier:

```
UNIQUE (tenant_id, external_system, entity_type, external_id) → internal_uuid
```

**Example mappings:**

| tenant_id | external_system | entity_type | external_id | internal_id |
|-----------|-----------------|-------------|-------------|-------------|
| 1 | fls | driver | DRV-001 | `a1b2c3d4-...` |
| 1 | fls | driver | DRV-002 | `e5f6g7h8-...` |
| 1 | sap | driver | DRV-001 | `i9j0k1l2-...` | ← Same ext_id, different system |
| 1 | fls | vehicle | DRV-001 | `m3n4o5p6-...` | ← Same ext_id, different type |

---

## API Endpoints

Base URL: `/api/v1/masterdata`

### POST /resolve

Resolve a single external ID to internal UUID.

**Request:**
```json
{
  "external_system": "fls",
  "entity_type": "driver",
  "external_id": "DRV-001",
  "create_payload": {
    "name": "Max Mustermann",
    "license_class": "C"
  }
}
```

**Response (found):**
```json
{
  "found": true,
  "internal_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "external_id": "DRV-001",
  "entity_type": "driver",
  "created": false
}
```

**Response (created):**
```json
{
  "found": true,
  "internal_id": "new-uuid-here",
  "external_id": "DRV-001",
  "entity_type": "driver",
  "created": true
}
```

**Response (not found, no payload):**
```json
{
  "found": false,
  "external_id": "DRV-001",
  "entity_type": "driver",
  "error": "Mapping not found and no create_payload provided"
}
```

**Behavior:**
1. If mapping exists → return `internal_id`
2. If not found AND `create_payload` provided → create entity + mapping
3. If not found AND no payload → return `found: false` with error

### POST /resolve-bulk

Batch resolve multiple external IDs in a single request.

**Request:**
```json
{
  "external_system": "fls",
  "entity_type": "driver",
  "external_ids": ["DRV-001", "DRV-002", "DRV-003"]
}
```

**Response:**
```json
{
  "total": 3,
  "found": 2,
  "not_found": 1,
  "results": [
    {"external_id": "DRV-001", "internal_id": "uuid-1", "found": true},
    {"external_id": "DRV-002", "internal_id": "uuid-2", "found": true},
    {"external_id": "DRV-003", "internal_id": null, "found": false}
  ]
}
```

**Performance:** Uses single DB roundtrip for all IDs. Supports up to 1000 IDs per request.

### POST /mappings

Create or update a mapping directly (when you already have the internal_id).

**Request:**
```json
{
  "external_system": "fls",
  "entity_type": "driver",
  "external_id": "DRV-001",
  "internal_id": "existing-uuid",
  "metadata": {"source": "manual_import"}
}
```

### GET /mappings

List external mappings for the tenant.

**Query parameters:**
- `external_system` - Filter by system (optional)
- `entity_type` - Filter by type (optional)
- `limit` - Max results (default 100, max 1000)
- `offset` - Pagination offset

### GET /sites

List canonical sites for the tenant.

### GET /vehicles

List canonical vehicles for the tenant.

### GET /integrity

Run MDL integrity checks (RLS, constraints, functions).

---

## Database Schema

### masterdata.md_sites

```sql
CREATE TABLE masterdata.md_sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'Europe/Vienna',
    is_active BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT md_sites_unique_code UNIQUE (tenant_id, site_code)
);
```

### masterdata.md_locations

```sql
CREATE TABLE masterdata.md_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_id UUID REFERENCES masterdata.md_sites(id),
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    address_text VARCHAR(500),
    address_norm VARCHAR(500),  -- Normalized for deduplication
    location_type VARCHAR(50) DEFAULT 'customer',
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### masterdata.md_vehicles

```sql
CREATE TABLE masterdata.md_vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_id UUID REFERENCES masterdata.md_sites(id),
    vehicle_code VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    vehicle_type VARCHAR(50) DEFAULT 'van',

    -- Capacity fields
    capacity_weight_kg NUMERIC(10,2),
    capacity_volume_m3 NUMERIC(10,2),
    capacity_pallets INTEGER,
    capacity_items INTEGER,

    -- Constraints
    max_range_km NUMERIC(10,2),
    fuel_type VARCHAR(50),
    is_refrigerated BOOLEAN DEFAULT FALSE,
    is_adr_certified BOOLEAN DEFAULT FALSE,

    is_active BOOLEAN DEFAULT TRUE,
    flags JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT md_vehicles_unique_code UNIQUE (tenant_id, vehicle_code)
);
```

### masterdata.md_external_mappings

```sql
CREATE TABLE masterdata.md_external_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),

    -- Mapping keys
    external_system VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    external_id VARCHAR(255) NOT NULL,

    -- Target
    internal_id UUID NOT NULL,

    -- Metadata
    sync_status VARCHAR(50) DEFAULT 'active',
    last_synced_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- THE CRITICAL CONSTRAINT
    CONSTRAINT md_external_mappings_unique_external
        UNIQUE (tenant_id, external_system, entity_type, external_id)
);
```

---

## Security

### Row-Level Security (RLS)

All MDL tables have RLS enabled with tenant isolation:

```sql
ALTER TABLE masterdata.md_sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.md_sites FORCE ROW LEVEL SECURITY;

CREATE POLICY md_sites_tenant_isolation ON masterdata.md_sites
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);
```

### Role Permissions

| Role | Permissions |
|------|-------------|
| `solvereign_api` | SELECT, INSERT, UPDATE |
| `solvereign_platform` | ALL |

---

## Database Functions

### masterdata.resolve_external_id

```sql
SELECT masterdata.resolve_external_id(
    1,          -- tenant_id
    'fls',      -- external_system
    'driver',   -- entity_type
    'DRV-001'   -- external_id
);
-- Returns: UUID or NULL
```

### masterdata.upsert_mapping

```sql
SELECT masterdata.upsert_mapping(
    1,              -- tenant_id
    'fls',          -- external_system
    'driver',       -- entity_type
    'DRV-001',      -- external_id
    'uuid-here',    -- internal_id
    '{}'::jsonb     -- metadata
);
-- Returns: internal_id
```

### masterdata.resolve_or_create

```sql
SELECT masterdata.resolve_or_create(
    1,
    'fls',
    'site',
    'SITE-001',
    '{"site_code": "WIEN", "name": "Vienna Depot"}'::jsonb
);
-- Returns: JSONB with found, internal_id, created flags
```

### masterdata.resolve_bulk

```sql
SELECT * FROM masterdata.resolve_bulk(
    1,
    'fls',
    'driver',
    ARRAY['DRV-001', 'DRV-002', 'DRV-003']
);
-- Returns: TABLE(external_id, internal_id, found)
```

### masterdata.verify_masterdata_integrity

```sql
SELECT * FROM masterdata.verify_masterdata_integrity();
```

Expected output:
```
check_name                | status | details
--------------------------|--------|----------------------------------
rls_enabled              | PASS   | 4/4 tables have RLS enabled
force_rls_enabled        | PASS   | 4/4 tables have FORCE RLS enabled
mapping_unique_constraint | PASS   | Unique constraint exists
rls_policies_exist       | PASS   | 4 RLS policies found
functions_exist          | PASS   | 4+ functions found
orphaned_mappings        | PASS   | 0 orphaned mappings
```

---

## Usage Examples

### Example 1: Import drivers from FLS export

```python
# In pack code
async def import_drivers_from_fls(tenant_id: int, fls_data: list):
    for driver in fls_data:
        result = await masterdata_service.resolve(
            tenant_id=tenant_id,
            external_system="fls",
            entity_type="driver",
            external_id=driver["fls_id"],
            create_payload={
                "name": driver["name"],
                "license_class": driver["license"],
            }
        )
        # Use result.internal_id for all subsequent operations
        canonical_driver_id = result.internal_id
```

### Example 2: Bulk resolve for roster import

```python
async def import_roster(tenant_id: int, roster_data: dict):
    # Collect all external IDs
    driver_ids = [row["driver_id"] for row in roster_data["assignments"]]

    # Bulk resolve
    results = await masterdata_service.resolve_bulk(
        tenant_id=tenant_id,
        external_system="google_sheets",
        entity_type="driver",
        external_ids=driver_ids
    )

    # Build lookup map
    id_map = {r.external_id: r.internal_id for r in results if r.found}

    # Process with canonical IDs
    for assignment in roster_data["assignments"]:
        canonical_id = id_map.get(assignment["driver_id"])
        if canonical_id:
            # Use canonical_id
            ...
```

---

## Migration

Apply migration:
```bash
psql $DATABASE_URL < backend_py/db/migrations/028_masterdata.sql
```

Verify:
```bash
psql $DATABASE_URL -c "SELECT * FROM masterdata.verify_masterdata_integrity();"
```

---

## Key Design Decisions

1. **UUIDs for internal IDs**: All canonical entities use UUIDs to avoid integer ID collisions across tenants and systems.

2. **Separate schema**: MDL uses `masterdata` schema for isolation and clear ownership.

3. **Idempotent operations**: All resolve/upsert operations are idempotent. Safe to retry.

4. **No cascade deletes on mappings**: Mappings use `sync_status = 'deprecated'` instead of DELETE to preserve audit trail.

5. **Entity-agnostic mapping table**: `md_external_mappings` can map ANY entity type, not just those with dedicated tables.

---

*MDL is part of the SOLVEREIGN Kernel, providing the foundation for multi-system integration.*
