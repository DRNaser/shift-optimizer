# Tenant Onboarding

> **Purpose**: New tenant setup and validation gates
> **Last Updated**: 2026-01-07

---

## ONBOARDING GATES

Every new tenant must pass ALL 4 gates before going live.

| Gate | Name | Purpose | Pass Criteria |
|------|------|---------|---------------|
| 1 | RLS Harness | Verify tenant isolation | No cross-tenant data leaks |
| 2 | Determinism Proof | Verify reproducibility | Same seed = same hash |
| 3 | Golden Path E2E | Full workflow test | All stages pass |
| 4 | Integrations | External service check | Auth, storage, OSRM work |

---

## GATE 1: RLS HARNESS

### What It Tests

- Tenant A cannot see Tenant B's data
- RLS policies exist on all tenant-scoped tables
- `set_config` is called correctly in all code paths

### How to Run

```bash
python -m backend_py.tests.test_security_proofs \
    --tenant NEW_TENANT_CODE \
    --verbose
```

### Common Failures

| Failure | Fix |
|---------|-----|
| `RLS policy missing on table X` | Add policy in migration |
| `set_config not called` | Check code path sets tenant context |
| `Cross-tenant leak detected` | Fix query or policy |

### Recovery Path

```bash
# 1. Identify missing policy
psql -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN (SELECT tablename FROM pg_policies WHERE schemaname='public')"

# 2. Add missing policy
psql << EOF
ALTER TABLE missing_table ENABLE ROW LEVEL SECURITY;
ALTER TABLE missing_table FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON missing_table
    USING (tenant_id::text = current_setting('app.current_tenant_id', true));
EOF

# 3. Rerun gate
python -m backend_py.tests.test_security_proofs --tenant NEW_TENANT_CODE
```

---

## GATE 2: DETERMINISM PROOF

### What It Tests

- Same forecast + same seed produces identical output_hash
- No random variance in solver
- Matrices are locked (not live OSRM)

### How to Run

```bash
python -m backend_py.v3.determinism_proof \
    --tenant NEW_TENANT_CODE \
    --forecast-id TEST_FORECAST \
    --seed 94 \
    --runs 3
```

### Common Failures

| Failure | Fix |
|---------|-----|
| `Hash mismatch on run N` | Check for randomness sources |
| `OSRM drift detected` | Use StaticMatrix instead |
| `Floating point variance` | Use Decimal or round consistently |

### Recovery Path

```bash
# 1. Enable debug logging
export DEBUG_DETERMINISM=1

# 2. Run with verbose output
python -m backend_py.v3.determinism_proof --verbose

# 3. Compare outputs line by line
diff run1.json run2.json

# 4. Fix source of randomness

# 5. Rerun gate
python -m backend_py.v3.determinism_proof --tenant NEW_TENANT_CODE
```

---

## GATE 3: GOLDEN PATH E2E

### What It Tests

- Full workflow: Parse → Expand → Solve → Audit → Lock
- All 7 roster audits pass (or pack-specific audits)
- Data flows correctly through all stages

### How to Run

```bash
python -m backend_py.tests.golden_path_e2e \
    --tenant NEW_TENANT_CODE \
    --pack roster \
    --dataset gurkerl_small
```

### Stages Tested

1. Parse forecast input
2. Expand tour templates to instances
3. Run solver with test seed
4. Run all audits
5. Lock plan
6. Verify locked state

### Common Failures

| Failure | Fix |
|---------|-----|
| `Stage X failed: error` | Check specific stage logs |
| `Audit Y: FAIL` | Review audit violation details |
| `Timeout on solve` | Check input size, increase limit |

### Recovery Path

```bash
# 1. Run with verbose output
python -m backend_py.tests.golden_path_e2e --verbose

# 2. Identify failing stage
# Check output for "FAIL" or "ERROR"

# 3. Fix issue (depends on failure type)

# 4. Rerun gate
python -m backend_py.tests.golden_path_e2e --tenant NEW_TENANT_CODE
```

---

## GATE 4: INTEGRATIONS CONTRACT

### What It Tests

- Authentication works (Entra ID or API Key)
- Artifact storage accessible (S3/Azure/Local)
- External services reachable (OSRM if used)

### How to Run

```bash
python -m backend_py.tests.integrations_contract \
    --tenant NEW_TENANT_CODE \
    --verbose
```

### Checks Performed

```python
checks = [
    ("auth", test_auth_flow),           # API key or Entra token
    ("artifact_store", test_upload),     # Can upload/download
    ("osrm", test_osrm_reachable),       # If routing pack
    ("database", test_db_connection),    # Pool works
]
```

### Common Failures

| Failure | Fix |
|---------|-----|
| `Auth flow failed: token invalid` | Check Entra config or API key |
| `Artifact store: connection refused` | Check S3/Azure credentials |
| `OSRM: timeout` | Check network, OSRM service |

### Recovery Path

```bash
# 1. Check environment variables
env | grep -E "(ENTRA|S3|AZURE|OSRM)"

# 2. Test connectivity manually
curl http://osrm:5000/health
aws s3 ls s3://bucket-name/

# 3. Fix configuration

# 4. Rerun gate
python -m backend_py.tests.integrations_contract --tenant NEW_TENANT_CODE
```

---

## FULL ONBOARDING VALIDATION

### Run All Gates

```bash
python -m backend_py.tools.onboarding_contract validate \
    --tenant NEW_TENANT_CODE \
    --all-gates
```

### Expected Output

```
=== Tenant Onboarding Validation ===
Tenant: NEW_TENANT_CODE

Gate 1: RLS Harness
  ✅ PASS - No cross-tenant leaks detected

Gate 2: Determinism Proof
  ✅ PASS - 3/3 runs produced identical hash

Gate 3: Golden Path E2E
  ✅ PASS - All stages completed successfully

Gate 4: Integrations Contract
  ✅ PASS - All integrations verified

=== OVERALL: 4/4 GATES PASS ===
Tenant NEW_TENANT_CODE is approved for pilot.
```

---

## TENANT CONFIGURATION

### Create Tenant Record

```sql
INSERT INTO core.tenants (code, name, status, settings)
VALUES (
    'new_tenant',
    'New Tenant Inc.',
    'onboarding',
    '{"packs": ["roster"], "features": ["basic"]}'
);
```

### Create API Key

```sql
INSERT INTO tenants (name, api_key, is_active)
VALUES (
    'new_tenant',
    'sk_live_' || encode(gen_random_bytes(32), 'hex'),
    true
);
```

### Configure Pack

```python
# Set default policy profile
await policy_service.set_active_profile(
    tenant_id=tenant.id,
    pack_id="roster",
    profile_id=None,  # Use pack defaults
    updated_by="onboarding"
)
```

---

## POST-ONBOARDING

### After All Gates Pass

1. [ ] Change tenant status to `active`
2. [ ] Send welcome email with credentials
3. [ ] Schedule onboarding call
4. [ ] Update tenant-status.json

### Monitoring First Week

- [ ] Daily health check
- [ ] Review first 5 solves
- [ ] Check for support tickets
- [ ] Verify KPIs match expectations

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Any gate fails | S3 | Block go-live. Fix and retry. |
| Gate flaky (intermittent) | S3 | Investigate. Improve test. |
| All gates pass but issues in pilot | S2 | Review gates. Add missing checks. |
| Customer requesting bypass | S2 | No exceptions. Fix issues first. |
