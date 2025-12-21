# Rollback Procedure: Shift Optimizer

> **Current Production Commit:** `571699f`  
> **Previous Known Good Commit:** `e6641b6`

---

## When to Rollback

- CRITICAL alert triggered (Starvation, Infeasible regression)
- Healthcheck failing
- Unexpected exceptions in logs
- Performance degradation > 50%

---

## Rollback Steps (Docker Compose)

### 1. Stop Current Deployment

```bash
docker-compose down
```

### 2. Checkout Previous Good Commit

```bash
git checkout e6641b6
```

### 3. Restart Services

```bash
docker-compose up -d --build
```

### 4. Verify Rollback

```bash
# Check commit
curl -fsS http://localhost:8000/api/v1/readyz | jq '.git_commit'
# Expected: "e6641b6"

# Check health
curl -fsS http://localhost:8000/api/v1/healthz
# Expected: {"status": "alive", "version": "2.0.0"}

# Check metrics
curl -fsS http://localhost:8000/api/v1/metrics | grep solver_signature_runs_total
```

---

## Rollback Steps (Local Development)

### 1. Stop Backend

```powershell
# Find PID
netstat -ano | findstr :8000

# Kill process
Stop-Process -Id <PID> -Force
```

### 2. Checkout Previous Commit

```bash
git checkout e6641b6
```

### 3. Restart Backend

```bash
cd backend_py
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 1
```

### 4. Verify

```bash
curl -fsS http://127.0.0.1:8000/api/v1/readyz
# Verify git_commit matches
```

---

## Post-Rollback Actions

1. **Notify stakeholders** of rollback
2. **Preserve logs** from failed deployment
3. **Document issue** in incident report
4. **Run smoke tests** on rolled-back version
5. **Monitor alerts** for 30 minutes

---

## Rollback Commit History

| Commit | Date | Status | Notes |
|--------|------|--------|-------|
| `571699f` | 2025-12-21 | Current | cap_quota_2er=0.30 default ON |
| `e6641b6` | 2025-12-21 | Fallback | Stage 1 canary PASSED |
| `4e1abb5` | 2025-12-21 | Fallback | Stage 0 baseline |

---

## Tested Rollback (Dry Run)

| Step | Command | Expected | Verified |
|------|---------|----------|----------|
| Stop | `docker-compose down` | Containers stopped | ☐ |
| Checkout | `git checkout e6641b6` | HEAD at e6641b6 | ☐ |
| Start | `docker-compose up -d` | Containers running | ☐ |
| Healthz | `curl /api/v1/healthz` | 200 OK | ☐ |
| Readyz | `curl /api/v1/readyz` | git_commit=e6641b6 | ☐ |
