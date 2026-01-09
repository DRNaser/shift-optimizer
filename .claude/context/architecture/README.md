# Architecture Branch - Router Checklist

> **Purpose**: Kernel/Pack boundaries, migrations, and contracts
> **Severity Default**: S3 - Important for long-term health

---

## ENTRY CHECKLIST

Before proceeding, answer these questions:

1. **Is this a database migration?**
   - YES → Read `migration-rules.md` FIRST
   - NO → Continue

2. **Are you modifying Kernel code?**
   - YES → Read `kernel-boundary.md`
   - NO → Continue

3. **Are you creating/modifying a Pack?**
   - YES → Read `pack-contracts.md`
   - NO → Continue

4. **Is this a breaking API change?**
   - YES → Read `pack-contracts.md` (API versioning section)
   - NO → Use general architecture guidance below

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `kernel-boundary.md` | What belongs in Kernel vs Packs | Code organization decisions |
| `pack-contracts.md` | Pack API contracts and versioning | Pack development |
| `migration-rules.md` | Database migration procedures | Schema changes |

---

## KERNEL VS PACK BOUNDARY

### KERNEL (Shared Platform)
- Multi-tenancy + RLS
- Authentication (Entra ID, HMAC, API Key)
- Plan lifecycle state machine
- Audit-gating at lock
- Evidence pack + artifact storage
- Service status / escalations
- BFF boundary + request signing

### PACKS (Domain-Specific)
- **Routing Pack**: VRPTW solver, stops, vehicles, routes
- **Roster Pack**: Block heuristic, tours, drivers, schedules

### RULE
```
Kernel code NEVER imports from packs.
Packs CAN import from Kernel.
Packs NEVER import from other packs.
```

---

## MIGRATION RULES

### Before ANY Migration

1. **Backup first**
   ```bash
   pg_dump solvereign > backup_$(date +%Y%m%d_%H%M%S).sql
   ```

2. **Check migration contract**
   - [ ] Has `tenant_id` column (if tenant-scoped)
   - [ ] Has RLS policy (if tenant-scoped)
   - [ ] Has rollback script
   - [ ] Has been tested on staging

3. **Migration naming**
   ```
   NNN_description.sql
   # Example: 024_add_policy_profiles.sql
   ```

4. **Update last-known-good.json after success**
   ```json
   {
     "migrations_version": "024_add_policy_profiles",
     ...
   }
   ```

---

## PACK CONTRACT TEMPLATE

```yaml
pack_id: "routing"
version: "1.0.0"
kernel_dependencies:
  - PolicyService
  - EscalationService
  - ArtifactStore

api_endpoints:
  - POST /api/v1/routing/scenarios
  - GET /api/v1/routing/scenarios/{id}
  - POST /api/v1/routing/scenarios/{id}/solve

db_schema_namespace: "routing.*"

audit_checks:
  - coverage
  - time_window
  - capacity
  - overlap
```

---

## QUICK CHECKS

### Verify Pack Isolation
```bash
# Should find NO cross-pack imports
grep -r "from backend_py.packs.roster" backend_py/packs/routing/
grep -r "from backend_py.packs.routing" backend_py/packs/roster/
```

### Check Kernel Imports in Pack
```bash
# These are ALLOWED
grep -r "from backend_py.api.services" backend_py/packs/
grep -r "from backend_py.api.dependencies" backend_py/packs/
```

### Verify Migration Sequence
```bash
ls -la backend_py/db/migrations/*.sql | tail -10
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Pack imports from another pack | S3 | Refactor. Extract to Kernel if shared. |
| Kernel imports from pack | S2 | Fix immediately. Violates architecture. |
| Migration missing rollback | S3 | Add rollback before applying. |
| Migration missing tenant_id | S2 | Fix before applying. RLS will fail. |
| Breaking API without version | S2 | Add version. Maintain backwards compat. |

---

## RELATED BRANCHES

- Need to deploy? → `operations/deployment-checklist.md`
- Security implications? → `security/rls-enforcement.md`
- Performance implications? → `performance/capacity-planning.md`
