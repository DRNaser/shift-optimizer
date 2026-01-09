# ADR-002: Policy Profiles / Tenant Pack Settings

> **Status**: Accepted
> **Date**: 2026-01-07
> **Decision Makers**: Platform Team
> **Supersedes**: None

---

## Context

SOLVEREIGN needs to support multiple tenants using the same pack code with **different business configurations**. Currently:

1. Configuration is hardcoded in solver code
2. All tenants use identical settings
3. No way to version or snapshot configurations
4. Determinism cannot be verified (what config was used for a run?)

For SaaS scaling, we need data-driven configuration that:
- Allows per-tenant, per-pack settings
- Supports versioning (draft → active → archived)
- Snapshots config into each run for determinism
- Validates config against pack-specific schemas

---

## Decision

**Implement a Policy Profile system with per-tenant configuration and mandatory snapshots.**

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Policy Profile** | Named, versioned configuration for a specific pack |
| **Config JSON** | The actual settings (validated against pack schema) |
| **Config Hash** | SHA256 of config JSON for determinism |
| **Active Profile** | Currently used profile for a tenant/pack |
| **Snapshot** | Copy of config hash stored with each run |

---

## Database Schema

### Migration: `023_policy_profiles.sql`

```sql
-- Policy profiles: versioned configuration per tenant/pack
CREATE TABLE core.policy_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    pack_id TEXT NOT NULL CHECK (pack_id IN ('routing', 'roster', 'analytics')),
    name TEXT NOT NULL,
    description TEXT,
    version INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),

    -- Configuration
    config_json JSONB NOT NULL,
    config_hash TEXT GENERATED ALWAYS AS (
        encode(sha256(config_json::text::bytea), 'hex')
    ) STORED,

    -- Schema validation (pack-specific)
    schema_version TEXT NOT NULL DEFAULT '1.0',

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL,

    -- Uniqueness: one active profile per tenant/pack
    UNIQUE (tenant_id, pack_id, name, version)
);

-- Index for fast lookup
CREATE INDEX idx_policy_profiles_tenant_pack ON core.policy_profiles(tenant_id, pack_id);
CREATE INDEX idx_policy_profiles_status ON core.policy_profiles(status) WHERE status = 'active';

-- Active profile selection per tenant/pack
CREATE TABLE core.tenant_pack_settings (
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    pack_id TEXT NOT NULL CHECK (pack_id IN ('routing', 'roster', 'analytics')),
    active_profile_id UUID REFERENCES core.policy_profiles(id),

    -- Defaults used when no profile selected
    use_pack_defaults BOOLEAN NOT NULL DEFAULT true,

    -- Audit
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL,

    PRIMARY KEY (tenant_id, pack_id)
);

-- Trigger: Only one 'active' profile per tenant/pack/name
CREATE OR REPLACE FUNCTION core.enforce_single_active_profile()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'active' THEN
        UPDATE core.policy_profiles
        SET status = 'archived', updated_at = NOW()
        WHERE tenant_id = NEW.tenant_id
          AND pack_id = NEW.pack_id
          AND name = NEW.name
          AND id != NEW.id
          AND status = 'active';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_single_active_profile
BEFORE INSERT OR UPDATE ON core.policy_profiles
FOR EACH ROW EXECUTE FUNCTION core.enforce_single_active_profile();

-- RLS: Tenants can only see their own profiles
ALTER TABLE core.policy_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY policy_profiles_tenant_isolation ON core.policy_profiles
    USING (
        tenant_id::text = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_platform_admin', true) = 'true'
    );

ALTER TABLE core.tenant_pack_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_pack_settings_isolation ON core.tenant_pack_settings
    USING (
        tenant_id::text = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_platform_admin', true) = 'true'
    );
```

### Add Snapshot Fields to Run Tables

```sql
-- Add to routing scenarios
ALTER TABLE routing_scenarios ADD COLUMN IF NOT EXISTS
    policy_profile_id UUID REFERENCES core.policy_profiles(id);
ALTER TABLE routing_scenarios ADD COLUMN IF NOT EXISTS
    policy_config_hash TEXT;

-- Add to plan_versions (roster)
ALTER TABLE plan_versions ADD COLUMN IF NOT EXISTS
    policy_profile_id UUID REFERENCES core.policy_profiles(id);
ALTER TABLE plan_versions ADD COLUMN IF NOT EXISTS
    policy_config_hash TEXT;

-- Comment for clarity
COMMENT ON COLUMN routing_scenarios.policy_config_hash IS
    'SHA256 of policy config at time of scenario creation - ensures determinism';
COMMENT ON COLUMN plan_versions.policy_config_hash IS
    'SHA256 of policy config at time of solve - ensures determinism';
```

---

## Pack-Specific Config Schemas

### Roster Pack Config Schema

```python
# packs/roster/config_schema.py

from pydantic import BaseModel, Field
from typing import Optional, List

class RosterPolicyConfig(BaseModel):
    """Configuration schema for roster pack (v1.0)."""

    # === TUNABLE FIELDS (tenant can adjust) ===

    # Driver constraints
    max_weekly_hours: int = Field(55, ge=40, le=60, description="Max weekly hours per driver")
    min_rest_hours: int = Field(11, ge=9, le=12, description="Min rest between blocks")
    max_span_regular_hours: int = Field(14, ge=12, le=16, description="Max span for 1er/2er-reg blocks")
    max_span_split_hours: int = Field(16, ge=14, le=18, description="Max span for 3er/split blocks")

    # Split break constraints
    min_split_break_minutes: int = Field(240, ge=180, le=300, description="Min break in split shift")
    max_split_break_minutes: int = Field(360, ge=300, le=420, description="Max break in split shift")

    # Optimization preferences
    prefer_fte_over_pt: bool = Field(True, description="Prefer full-time over part-time drivers")
    minimize_splits: bool = Field(True, description="Minimize split shifts when possible")
    allow_3er_consecutive: bool = Field(False, description="Allow 3er blocks on consecutive days")

    # Solver settings
    solver_time_limit_seconds: int = Field(300, ge=60, le=3600, description="Max solver time")
    seed: Optional[int] = Field(94, description="Solver seed for reproducibility")

    # === LOCKED FIELDS (German labor law - cannot be changed) ===
    # These are enforced by the solver regardless of config

    class Config:
        # Additional validation
        extra = "forbid"  # No unknown fields allowed

    @classmethod
    def locked_constraints(cls) -> dict:
        """Constraints that CANNOT be overridden (German labor law)."""
        return {
            "absolute_max_weekly_hours": 60,  # ArbZG §3
            "absolute_min_rest_hours": 9,      # ArbZG §5
            "absolute_max_daily_hours": 10,    # ArbZG §3
        }
```

### Routing Pack Config Schema

```python
# packs/routing/config_schema.py

from pydantic import BaseModel, Field
from typing import Optional, Literal

class RoutingPolicyConfig(BaseModel):
    """Configuration schema for routing pack (v1.0)."""

    # === TUNABLE FIELDS ===

    # Time windows
    default_service_time_minutes: int = Field(15, ge=5, le=60)
    time_window_slack_minutes: int = Field(30, ge=0, le=120)

    # Vehicle constraints
    max_route_duration_hours: float = Field(10.0, ge=4.0, le=14.0)
    max_stops_per_route: int = Field(50, ge=10, le=200)

    # Distance/time matrix
    matrix_source: Literal["osrm", "static", "google"] = Field("osrm")
    use_traffic_data: bool = Field(False)

    # Solver settings
    solver_time_limit_seconds: int = Field(60, ge=10, le=600)
    metaheuristic: Literal["GUIDED_LOCAL_SEARCH", "SIMULATED_ANNEALING", "TABU_SEARCH"] = Field("GUIDED_LOCAL_SEARCH")

    # Freeze settings
    freeze_horizon_minutes: int = Field(60, ge=30, le=240)

    class Config:
        extra = "forbid"
```

---

## Service Implementation

### Policy Service (Kernel)

```python
# api/services/policy_service.py

from dataclasses import dataclass
from typing import Optional, Dict, Any
import hashlib
import json

@dataclass
class ActivePolicy:
    profile_id: str
    config: Dict[str, Any]
    config_hash: str
    schema_version: str

@dataclass
class PolicyNotFound:
    reason: str
    use_defaults: bool

class PolicyService:
    """Core service for policy profile management."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def get_active_policy(
        self,
        tenant_id: str,
        pack_id: str,
        site_id: Optional[str] = None
    ) -> ActivePolicy | PolicyNotFound:
        """
        Get active policy for a tenant/pack.

        Returns:
            ActivePolicy if found, PolicyNotFound if no profile configured.
        """
        async with self.db_pool.connection() as conn:
            # Check tenant_pack_settings
            row = await conn.fetchrow("""
                SELECT
                    tps.active_profile_id,
                    tps.use_pack_defaults,
                    pp.config_json,
                    pp.config_hash,
                    pp.schema_version
                FROM core.tenant_pack_settings tps
                LEFT JOIN core.policy_profiles pp ON pp.id = tps.active_profile_id
                WHERE tps.tenant_id = $1 AND tps.pack_id = $2
            """, tenant_id, pack_id)

            if not row:
                return PolicyNotFound(
                    reason=f"No settings for tenant {tenant_id}, pack {pack_id}",
                    use_defaults=True
                )

            if row['use_pack_defaults'] or not row['active_profile_id']:
                return PolicyNotFound(
                    reason="Tenant configured to use pack defaults",
                    use_defaults=True
                )

            return ActivePolicy(
                profile_id=str(row['active_profile_id']),
                config=row['config_json'],
                config_hash=row['config_hash'],
                schema_version=row['schema_version']
            )

    async def create_profile(
        self,
        tenant_id: str,
        pack_id: str,
        name: str,
        config: Dict[str, Any],
        created_by: str,
        schema_version: str = "1.0"
    ) -> str:
        """Create a new policy profile (draft status)."""
        # Validate config against pack schema
        self._validate_config(pack_id, config, schema_version)

        async with self.db_pool.connection() as conn:
            row = await conn.fetchrow("""
                INSERT INTO core.policy_profiles
                    (tenant_id, pack_id, name, config_json, schema_version, created_by, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6, $6)
                RETURNING id
            """, tenant_id, pack_id, name, json.dumps(config), schema_version, created_by)
            return str(row['id'])

    async def activate_profile(
        self,
        profile_id: str,
        activated_by: str
    ) -> None:
        """Activate a profile (archives previous active)."""
        async with self.db_pool.connection() as conn:
            await conn.execute("""
                UPDATE core.policy_profiles
                SET status = 'active', updated_at = NOW(), updated_by = $2
                WHERE id = $1
            """, profile_id, activated_by)

    async def set_active_profile(
        self,
        tenant_id: str,
        pack_id: str,
        profile_id: str,
        updated_by: str
    ) -> None:
        """Set the active profile for a tenant/pack."""
        async with self.db_pool.connection() as conn:
            await conn.execute("""
                INSERT INTO core.tenant_pack_settings
                    (tenant_id, pack_id, active_profile_id, use_pack_defaults, updated_by)
                VALUES ($1, $2, $3, false, $4)
                ON CONFLICT (tenant_id, pack_id) DO UPDATE SET
                    active_profile_id = $3,
                    use_pack_defaults = false,
                    updated_at = NOW(),
                    updated_by = $4
            """, tenant_id, pack_id, profile_id, updated_by)

    def _validate_config(
        self,
        pack_id: str,
        config: Dict[str, Any],
        schema_version: str
    ) -> None:
        """Validate config against pack-specific schema."""
        if pack_id == "roster":
            from ...packs.roster.config_schema import RosterPolicyConfig
            RosterPolicyConfig(**config)  # Raises ValidationError if invalid
        elif pack_id == "routing":
            from ...packs.routing.config_schema import RoutingPolicyConfig
            RoutingPolicyConfig(**config)
        else:
            raise ValueError(f"Unknown pack_id: {pack_id}")
```

### Usage in Pack (Roster Example)

```python
# packs/roster/services/solver_service.py

from ....api.services.policy_service import PolicyService, ActivePolicy, PolicyNotFound
from ..config_schema import RosterPolicyConfig

class RosterSolverService:
    def __init__(self, db_pool, policy_service: PolicyService):
        self.db_pool = db_pool
        self.policy_service = policy_service

    async def solve(
        self,
        tenant_id: str,
        forecast_version_id: int
    ) -> dict:
        # Get active policy
        policy_result = await self.policy_service.get_active_policy(
            tenant_id=tenant_id,
            pack_id="roster"
        )

        if isinstance(policy_result, PolicyNotFound):
            # Use pack defaults
            config = RosterPolicyConfig()
            config_hash = self._compute_hash(config.dict())
            profile_id = None
        else:
            config = RosterPolicyConfig(**policy_result.config)
            config_hash = policy_result.config_hash
            profile_id = policy_result.profile_id

        # Run solver with config
        result = await self._run_solver(forecast_version_id, config)

        # Create plan_version with policy snapshot
        plan_version_id = await self._create_plan_version(
            forecast_version_id=forecast_version_id,
            policy_profile_id=profile_id,
            policy_config_hash=config_hash,
            result=result
        )

        return {
            "plan_version_id": plan_version_id,
            "policy_config_hash": config_hash,
            "config_used": config.dict()
        }

    def _compute_hash(self, config: dict) -> str:
        canonical = json.dumps(config, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## Consequences

### Positive

- **SaaS Ready**: Multiple tenants, same code, different configs
- **Determinism**: Config hash in every run enables reproducibility
- **Auditability**: Full version history of policy changes
- **Validation**: Pack-specific schemas prevent invalid configs
- **Evidence**: Policy snapshot in evidence pack

### Negative

- **Complexity**: Additional tables and service layer
- **Migration**: Existing runs don't have policy snapshots

### Neutral

- **Default Behavior**: Falls back to pack defaults if no profile configured

---

## Verification

### Test: Same Policy Hash = Same Results

```python
async def test_determinism_with_policy():
    # Create policy
    profile_id = await policy_service.create_profile(
        tenant_id="tenant-1",
        pack_id="roster",
        name="test-policy",
        config={"seed": 42, "max_weekly_hours": 55}
    )
    await policy_service.activate_profile(profile_id)
    await policy_service.set_active_profile("tenant-1", "roster", profile_id)

    # Run solver twice
    result1 = await solver_service.solve("tenant-1", forecast_id)
    result2 = await solver_service.solve("tenant-1", forecast_id)

    # Same policy hash
    assert result1["policy_config_hash"] == result2["policy_config_hash"]

    # Same output (determinism)
    assert result1["output_hash"] == result2["output_hash"]
```

---

## References

- [ADR-001: Kernel vs Pack Boundary](./ADR-001-kernel-vs-pack-boundary.md)
- [Architecture Correctness Report](../../docs/ARCHITECTURE_CORRECTNESS_REPORT.md)
