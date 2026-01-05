# ADR-001: Multi-Tenant Architecture

## Status
Accepted

## Context
SOLVEREIGN V3.3a transforms the system from a single-tenant internal tool to a multi-tenant SaaS platform. We needed to decide on the tenant isolation strategy.

## Decision
We chose **Column-based isolation** with `tenant_id` on all data tables:

1. **tenants** table as master registry
2. **tenant_id** column added to:
   - forecast_versions
   - tours_raw
   - tours_normalized
   - tour_instances
   - plan_versions
   - assignments
   - audit_log
   - diff_results
   - idempotency_keys
   - tour_groups
   - tour_segments

3. **API Key authentication** via X-API-Key header
4. **SHA256 hashing** of API keys in database

## Consequences

### Positive
- Single database, simpler operations
- Easy cross-tenant analytics (if needed)
- Lower infrastructure cost
- Familiar PostgreSQL patterns

### Negative
- Must ensure ALL queries filter by tenant_id
- Risk of data leaks if queries miss tenant filter
- No physical isolation for compliance-sensitive tenants

### Mitigations
- Repository pattern enforces tenant_id on all queries
- Index on (tenant_id, ...) for all tables
- Future: PostgreSQL RLS for defense-in-depth

## Alternatives Considered

1. **Schema-per-tenant**: Too complex for ops
2. **Database-per-tenant**: Too expensive, scaling issues
3. **JWT-based auth**: Overkill for M2M API

## References
- Migration 006: Multi-tenant
- backend_py/api/dependencies.py: get_current_tenant()
- backend_py/api/repositories/base.py: BaseRepository
