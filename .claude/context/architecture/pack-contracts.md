# Pack Contracts

> **Purpose**: Define pack API contracts and versioning
> **Last Updated**: 2026-01-07

---

## CONTRACT DEFINITION

Every pack must define a contract that specifies:
1. Kernel dependencies
2. API endpoints
3. Database schema namespace
4. Required audits
5. Configuration schema

---

## CONTRACT TEMPLATE

```yaml
# pack-contract.yaml
pack_id: "routing"
version: "1.0.0"
status: "stable"  # draft | stable | deprecated

kernel_dependencies:
  required:
    - PolicyService
    - TenantContext
    - ArtifactStore
  optional:
    - EscalationService

api:
  prefix: "/api/v1/routing"
  endpoints:
    - method: POST
      path: /scenarios
      description: "Create a new routing scenario"
      auth: tenant
      request_schema: CreateScenarioRequest
      response_schema: ScenarioResponse

    - method: GET
      path: /scenarios/{id}
      description: "Get scenario details"
      auth: tenant
      response_schema: ScenarioResponse

    - method: POST
      path: /scenarios/{id}/solve
      description: "Run solver on scenario"
      auth: tenant
      request_schema: SolveRequest
      response_schema: SolveResponse
      async: true  # Returns task_id

    - method: POST
      path: /scenarios/{id}/lock
      description: "Lock solved scenario"
      auth: approver
      response_schema: LockResponse

database:
  schema: "routing"
  tables:
    - routing.scenarios
    - routing.stops
    - routing.vehicles
    - routing.routes
    - routing.assignments
  foreign_keys:
    - from: routing.scenarios.tenant_id
      to: core.tenants.id

audits:
  required_for_lock:
    - coverage
    - time_window
    - capacity
    - overlap

config:
  schema_file: "config_schema.py"
  schema_class: "RoutingPolicyConfig"
  defaults:
    time_limit_seconds: 60
    metaheuristic: "GUIDED_LOCAL_SEARCH"
```

---

## CURRENT PACK CONTRACTS

### Roster Pack

```yaml
pack_id: "roster"
version: "3.3.0"
status: "stable"

kernel_dependencies:
  required:
    - PolicyService
    - TenantContext
  optional: []

api:
  prefix: "/api/v1"
  endpoints:
    - POST /forecasts
    - GET /forecasts/{id}
    - POST /plans/solve
    - POST /plans/{id}/lock
    - GET /plans/{id}/export

database:
  schema: "public"  # Legacy, consider migrating to roster.*
  tables:
    - forecast_versions
    - tours_raw
    - tours_normalized
    - tour_instances
    - plan_versions
    - assignments
    - audit_log

audits:
  required_for_lock:
    - coverage
    - overlap
    - rest
    - span_regular
    - span_split
    - fatigue
    - weekly_max

config:
  schema_class: "RosterPolicyConfig"
  defaults:
    max_weekly_hours: 55
    min_rest_hours: 11
    max_span_regular: 14
    max_span_split: 16
```

### Routing Pack

```yaml
pack_id: "routing"
version: "1.0.0"
status: "pilot"

kernel_dependencies:
  required:
    - PolicyService
    - TenantContext
    - ArtifactStore
  optional:
    - EscalationService

api:
  prefix: "/api/v1/routing"
  endpoints:
    - POST /scenarios
    - GET /scenarios/{id}
    - POST /scenarios/{id}/solve
    - POST /scenarios/{id}/lock
    - GET /scenarios/{id}/routes
    - POST /scenarios/{id}/repair

database:
  schema: "routing"
  tables:
    - routing.scenarios
    - routing.stops
    - routing.orders
    - routing.vehicles
    - routing.routes
    - routing.assignments

audits:
  required_for_lock:
    - coverage
    - time_window
    - capacity
    - overlap
    - skills_compliance

config:
  schema_class: "RoutingPolicyConfig"
  defaults:
    time_limit_seconds: 60
    solution_limit: 1
    metaheuristic: "GUIDED_LOCAL_SEARCH"
    freeze_horizon_minutes: 60
```

---

## API VERSIONING

### URL Versioning

```
/api/v1/routing/scenarios    # Current stable
/api/v2/routing/scenarios    # Next major version (breaking changes)
```

### Version Compatibility

| Change Type | Version Bump | Compatibility |
|-------------|--------------|---------------|
| Add optional field | PATCH | Backwards compatible |
| Add new endpoint | MINOR | Backwards compatible |
| Remove field | MAJOR | Breaking |
| Change field type | MAJOR | Breaking |
| Remove endpoint | MAJOR | Breaking |

### Deprecation Process

1. Mark endpoint as deprecated (add header)
2. Log usage for 30 days
3. Communicate to users
4. Remove in next major version

```python
@router.get("/old-endpoint", deprecated=True)
async def old_endpoint():
    return RedirectResponse("/new-endpoint")
```

---

## SCHEMA VALIDATION

### Request Validation

```python
from pydantic import BaseModel, Field

class CreateScenarioRequest(BaseModel):
    """Create routing scenario request."""
    name: str = Field(..., min_length=1, max_length=100)
    site_id: str = Field(..., description="Site UUID")
    stops: list[StopInput] = Field(..., min_items=1)
    vehicles: list[VehicleInput] = Field(..., min_items=1)

    class Config:
        extra = "forbid"  # Reject unknown fields
```

### Response Contract

```python
class ScenarioResponse(BaseModel):
    """Scenario response."""
    id: str
    name: str
    site_id: str
    status: ScenarioStatus
    stops_count: int
    vehicles_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        extra = "forbid"
```

---

## PACK REGISTRATION

### Register Pack with Kernel

```python
# backend_py/api/main.py

from backend_py.packs.roster.api import router as roster_router
from backend_py.packs.routing.api import router as routing_router

def create_app():
    app = FastAPI()

    # Register packs
    app.include_router(
        roster_router,
        prefix="/api/v1",
        tags=["roster"]
    )

    app.include_router(
        routing_router,
        prefix="/api/v1/routing",
        tags=["routing"]
    )

    return app
```

### Pack Health Integration

```python
# Each pack provides health check
from backend_py.packs.routing.health import check_routing_health

async def readiness_check():
    checks = {}
    checks["routing"] = await check_routing_health()
    checks["roster"] = await check_roster_health()
    return checks
```

---

## CONTRACT TESTING

### Contract Test

```python
def test_routing_contract():
    """Verify routing pack contract."""

    # Check endpoints exist
    client = TestClient(app)
    assert client.post("/api/v1/routing/scenarios").status_code != 404
    assert client.get("/api/v1/routing/scenarios/123").status_code != 404

    # Check required audits
    from backend_py.packs.routing.services.audit_gate import REQUIRED_AUDITS
    assert "coverage" in REQUIRED_AUDITS
    assert "time_window" in REQUIRED_AUDITS

    # Check config schema
    from backend_py.packs.routing.config_schema import RoutingPolicyConfig
    config = RoutingPolicyConfig()
    assert config.time_limit_seconds == 60
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Breaking API change without version bump | S2 | Roll back. Bump major version. |
| Missing required audit | S2 | Add audit. Block deploys until fixed. |
| Contract validation failure | S3 | Fix schema. Update tests. |
| Deprecated endpoint still in heavy use | S4 | Extend deprecation period. Notify users. |
