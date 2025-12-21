# Deployment Checklist: Shift Optimizer v2.0.0

> **Release Tag:** `v2.0.0-rc1`  
> **App Commit:** `571699f` (core features + config defaults)  
> **Docs Commit:** `30c6d81` (runbooks added on top)  
> **Date:** 2025-12-21

> [!NOTE]
> The running app is on `571699f`. Runbooks were added in `30c6d81`.
> Both commits are equivalent for behavior; only documentation differs.

---

## Pre-Deployment

```bash
# 1. Verify on correct commit
git rev-parse --short HEAD
# Expected: 571699f

# 2. Run unit tests
cd backend_py
python -m pytest tests/ -q
# Expected: All tests pass
```

---

## Deployment (Docker Compose)

```bash
# 1. Build and start all services
docker-compose up -d --build

# 2. Check containers are running
docker-compose ps
# Expected: api, prometheus, grafana all "Up"
```

---

## Smoke Verification

### A) Healthcheck

```bash
curl -fsS http://localhost:8000/api/v1/healthz
```

**Expected:**
```json
{"status": "alive", "version": "2.0.0"}
```

### B) Readiness Check

```bash
curl -fsS http://localhost:8000/api/v1/readyz
```

**Expected:**
```json
{
  "status": "ready",
  "solver": "warm",
  "ortools_version": "9.11.4210",
  "app_version": "2.0.0",
  "git_commit": "571699f",
  "config": {"cap_quota_2er": 0.3}
}
```

**Verify:**
- `git_commit` matches deployed commit
- `cap_quota_2er` = 0.3 (default ON)

### C) Metrics Endpoint

```bash
curl -fsS http://localhost:8000/api/v1/metrics | grep solver_candidates
```

**Expected patterns:**
```
solver_candidates_kept_total{size="1er"} ...
solver_candidates_kept_total{size="2er"} ...
solver_candidates_kept_total{size="3er"} ...
```

---

## Monitoring Verification

### Prometheus (http://localhost:9090)

1. Go to **Status → Targets**
2. Verify `shift-optimizer` job is **UP**
3. Verify `metrics_path = /api/v1/metrics`

### Grafana (http://localhost:3000)

1. Login: `admin` / `admin`
2. Go to **Dashboards → Shift Optimizer**
3. Verify dashboards loaded:
   - `Rollout Safety`
   - `Solver Performance`
4. Verify `$job` and `$instance` variables work

---

## Post-Deployment Validation

Run a single solver test to confirm metrics flow:

```bash
cd backend_py
python scripts/run_forecast_test.py
```

Then verify in Prometheus:
```promql
solver_signature_runs_total
```
Should increment by 1.

---

## Sign-Off

| Check | Expected | Actual |
|-------|----------|--------|
| git_commit | 571699f | _____ |
| /healthz | 200 | _____ |
| /readyz config.cap_quota_2er | 0.3 | _____ |
| Prometheus target UP | Yes | _____ |
| Grafana dashboards loaded | Yes | _____ |

**Deployed by:** _______________  
**Date/Time:** _______________
