# Health Check Configuration

> **Purpose**: Health probe configuration and debugging
> **Last Updated**: 2026-01-07

---

## HEALTH ENDPOINTS

### Liveness Probe

**Endpoint**: `GET /health/live`

**Purpose**: Is the process running?

**Response**:
```json
{"status": "alive"}
```

**Configuration** (Kubernetes):
```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3
```

**Failure Action**: Restart pod

---

### Readiness Probe

**Endpoint**: `GET /health/ready`

**Purpose**: Can this pod serve traffic?

**Response** (Healthy):
```json
{
  "status": "ready",
  "checks": {
    "database": "healthy",
    "policy_service": "healthy",
    "packs": {
      "roster": "available",
      "routing": "available"
    }
  },
  "timestamp": "2026-01-07T10:30:00Z"
}
```

**Response** (Unhealthy):
```json
{
  "status": "not_ready",
  "checks": {
    "database": "unhealthy: connection refused",
    "policy_service": "not_initialized",
    "packs": {
      "roster": "available",
      "routing": "unavailable: import error"
    }
  },
  "timestamp": "2026-01-07T10:30:00Z"
}
```

**Configuration** (Kubernetes):
```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 3
```

**Failure Action**: Remove from load balancer (no restart)

---

### Basic Health Check

**Endpoint**: `GET /health`

**Purpose**: Quick status check

**Response**:
```json
{
  "status": "healthy",
  "version": "3.3.1",
  "timestamp": "2026-01-07T10:30:00Z",
  "environment": "production"
}
```

---

## HEALTH CHECK COMPONENTS

### Database Check

```python
async def check_database(db_pool) -> str:
    try:
        async with db_pool.connection() as conn:
            await conn.execute("SELECT 1")
        return "healthy"
    except Exception as e:
        return f"unhealthy: {str(e)}"
```

**Common Failures**:
- `connection refused` - DB not running
- `timeout` - Network issue or overload
- `too many connections` - Pool exhausted

### PolicyService Check

```python
def check_policy_service(app_state) -> str:
    policy_service = getattr(app_state, 'policy_service', None)
    if policy_service:
        return "healthy"
    return "not_initialized"
```

**Common Failures**:
- `not_initialized` - App startup incomplete

### Pack Availability Check

```python
def check_pack(pack_name: str) -> str:
    try:
        importlib.import_module(f"backend_py.packs.{pack_name}.api")
        return "available"
    except ImportError as e:
        return f"unavailable: {str(e)}"
```

**Common Failures**:
- `unavailable: No module named ...` - Pack not installed
- `unavailable: ImportError ...` - Missing dependency

---

## DEBUGGING FAILED PROBES

### Step 1: Check Logs

```bash
# API logs
docker logs solvereign-api --tail 100 | grep -E "(health|ERROR)"

# Kubernetes events
kubectl get events --sort-by=.metadata.creationTimestamp | tail -20
```

### Step 2: Test Endpoints Directly

```bash
# From inside the cluster
kubectl exec -it solvereign-api-xxx -- curl localhost:8000/health/ready

# From outside
curl -v http://api.solvereign.local/health/ready
```

### Step 3: Check Dependencies

```bash
# Database
psql -h localhost -U solvereign -c "SELECT 1"

# OSRM (if applicable)
curl http://osrm:5000/health
```

### Step 4: Check Resource Limits

```bash
# Pod resources
kubectl top pod solvereign-api-xxx

# Node resources
kubectl top node
```

---

## COMMON ISSUES AND FIXES

### Issue: Database Connection Refused

**Symptoms**:
- `database: unhealthy: connection refused`
- Readiness probe fails

**Investigation**:
```bash
# Check DB is running
docker ps | grep postgres

# Check network
ping postgres-host

# Check credentials
psql -h postgres-host -U solvereign -c "SELECT 1"
```

**Fixes**:
- Start database: `docker compose up -d postgres`
- Fix network/firewall
- Fix credentials in environment

### Issue: Pool Exhausted

**Symptoms**:
- `database: unhealthy: too many connections`
- Intermittent failures

**Investigation**:
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'solvereign';
```

**Fixes**:
- Increase `max_connections` in PostgreSQL
- Reduce pool size
- Check for connection leaks

### Issue: Pack Import Error

**Symptoms**:
- `packs.routing: unavailable: ImportError`

**Investigation**:
```python
python -c "from backend_py.packs.routing.api import router"
```

**Fixes**:
- Install missing dependencies
- Fix import errors in pack code

### Issue: Slow Startup

**Symptoms**:
- Readiness probe fails initially
- Eventually becomes healthy

**Investigation**:
```bash
# Check startup time
kubectl logs solvereign-api-xxx | grep -E "(startup|ready)"
```

**Fixes**:
- Increase `initialDelaySeconds`
- Optimize startup (lazy loading)

---

## HEALTH MONITORING

### Prometheus Metrics

```python
# Add to health router
from prometheus_client import Counter, Gauge

health_check_total = Counter('health_check_total', 'Total health checks', ['status'])
health_check_duration = Gauge('health_check_duration_seconds', 'Health check duration')

@router.get("/ready")
async def readiness_check():
    start = time.time()
    # ... check logic ...
    health_check_duration.set(time.time() - start)
    health_check_total.labels(status=overall_status).inc()
    return response
```

### Alerting Rules

```yaml
# Prometheus alerting rules
groups:
- name: health
  rules:
  - alert: ServiceUnhealthy
    expr: up{job="solvereign-api"} == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "SOLVEREIGN API is down"

  - alert: ReadinessProbeFailures
    expr: increase(kube_pod_container_status_restarts_total{container="api"}[1h]) > 3
    labels:
      severity: warning
    annotations:
      summary: "API pod restarting frequently"
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| All probes failing | S1 | STOP-THE-LINE. Check infrastructure. |
| Database unhealthy | S2 | Check DB. May need failover. |
| Pack unavailable | S2 | Check pack. Disable if non-critical. |
| Intermittent failures | S3 | Monitor. Investigate if increasing. |
