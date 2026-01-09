# Capacity Planning

> **Purpose**: Load testing and capacity estimation for tenant onboarding
> **Last Updated**: 2026-01-07

---

## CURRENT BASELINES

| Metric | Value | Measurement Conditions |
|--------|-------|----------------------|
| API p95 | 120ms | 100 concurrent users |
| Solver p95 | 45s | 500 tours, 100 drivers |
| Peak RSS | 2GB | Full solve with audits |
| DB connections | 20 | Normal load |

Source: `.claude/state/drift-baselines.json`

---

## CAPACITY LIMITS

### Per-Tenant Limits

| Resource | Soft Limit | Hard Limit | Action at Limit |
|----------|------------|------------|-----------------|
| Tours per solve | 500 | 1000 | Partition or reject |
| Concurrent solves | 1 | 1 | Queue or reject |
| API requests/min | 100 | 500 | Rate limit |
| Storage (artifacts) | 10GB | 50GB | Archive old data |

### Platform Limits

| Resource | Current Capacity | Max Capacity | Scale-up Trigger |
|----------|------------------|--------------|------------------|
| Tenants | 5 | 20 | >80% of current |
| Total daily solves | 100 | 500 | >80% of current |
| DB storage | 50GB | 500GB | >70% used |
| API pods | 2 | 10 | p95 > 200ms |

---

## SIZING GUIDE

### New Tenant Sizing

```python
def estimate_resources(tenant_profile):
    """Estimate resource needs for a new tenant."""

    # Tours per week
    tours = tenant_profile.weekly_tours

    # Estimated solver time
    solver_time_s = 0.1 * tours  # ~100ms per tour

    # Estimated memory
    memory_mb = 50 + (2 * tours)  # Base + per-tour

    # Estimated storage/month
    storage_mb = 10 + (0.5 * tours)  # Artifacts + logs

    return {
        'solver_time_estimate': solver_time_s,
        'memory_estimate_mb': memory_mb,
        'storage_estimate_mb': storage_mb,
        'tier': 'standard' if tours < 500 else 'enterprise'
    }
```

### Sizing Tiers

| Tier | Tours/Week | Solves/Day | Resources |
|------|------------|------------|-----------|
| Small | <200 | 2-3 | Shared infrastructure |
| Standard | 200-500 | 5-10 | Standard allocation |
| Enterprise | 500-1000 | 10-20 | Dedicated resources |
| Custom | >1000 | >20 | Custom planning required |

---

## LOAD TESTING

### Pre-Onboarding Load Test

```bash
# Install locust
pip install locust

# Run load test
locust -f load_tests/api_test.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m
```

### Load Test Script

```python
# load_tests/api_test.py
from locust import HttpUser, task, between

class SolverUser(HttpUser):
    wait_time = between(1, 3)

    @task(10)
    def health_check(self):
        self.client.get("/health/ready")

    @task(5)
    def get_forecasts(self):
        self.client.get("/api/v1/forecasts",
                       headers={"X-API-Key": "test-key"})

    @task(1)
    def solve(self):
        self.client.post("/api/v1/plans/solve",
                        json={"forecast_id": 1, "seed": 94},
                        headers={"X-API-Key": "test-key"})
```

### Metrics to Capture

```
Requests per second (RPS)
Response time p50, p95, p99
Error rate
CPU utilization
Memory usage
DB connection count
Queue depth (if applicable)
```

---

## SCALING PROCEDURES

### Horizontal Scaling (API)

```yaml
# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: solvereign-api
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Vertical Scaling (Solver)

```yaml
# Increase solver pod resources
resources:
  limits:
    memory: "8Gi"
    cpu: "4"
  requests:
    memory: "4Gi"
    cpu: "2"
```

### Database Scaling

```sql
-- Increase connection limit
ALTER SYSTEM SET max_connections = 200;

-- Add read replicas for queries
-- Configure in application:
# READ_DATABASE_URL=postgresql://replica:5432/solvereign
```

---

## BOTTLENECK IDENTIFICATION

### CPU-Bound

**Indicators**:
- CPU > 80% sustained
- Low I/O wait
- Response time correlates with CPU

**Solutions**:
- Add API pods
- Optimize algorithms
- Add caching

### Memory-Bound

**Indicators**:
- RSS approaching limit
- Swap usage increasing
- OOM kills in logs

**Solutions**:
- Increase pod memory
- Fix memory leaks
- Process data in chunks

### I/O-Bound (Database)

**Indicators**:
- High I/O wait
- Slow query log active
- Connection pool exhausted

**Solutions**:
- Add indexes
- Read replicas
- Connection pooling (PgBouncer)

### I/O-Bound (Network)

**Indicators**:
- High latency to external services
- OSRM timeout errors
- Cloud storage slow

**Solutions**:
- Cache external calls
- Use CDN for static assets
- Colocate services

---

## ONBOARDING CHECKLIST

Before going live with new tenant:

- [ ] Estimate resource needs using sizing guide
- [ ] Run load test with expected traffic pattern
- [ ] Verify current capacity has headroom
- [ ] Configure tenant-specific limits
- [ ] Set up monitoring alerts
- [ ] Document scale-up triggers

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Capacity < 20% headroom | S2 | Scale up immediately. |
| New tenant exceeds limits | S3 | Discuss enterprise tier. |
| Load test fails targets | S2 | Optimize or scale before onboard. |
| Baseline drift > 25% | S3 | Investigate regression. |
