# Shift Optimizer - Deployment Guide

## Quick Start

### Local Development

```bash
cd backend_py

# Install dependencies
pip install -r requirements.txt

# Run development server
python -m uvicorn src.main:app --reload --port 8000
```

### Docker

```bash
# Build image
docker build -t shift-optimizer:2.0.0 ./backend_py

# Run container
docker run -p 8000:8000 shift-optimizer:2.0.0

# Run with environment overrides
docker run -p 8000:8000 \
  -e PYTHONUNBUFFERED=1 \
  shift-optimizer:2.0.0
```

### Docker Compose

```bash
docker-compose up --build
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYTHONUNBUFFERED` | `1` | Disable output buffering |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |

---

## Healthcheck Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /api/v1/healthz` | Liveness probe | `{"status": "alive"}` |
| `GET /api/v1/readyz` | Readiness probe | `{"status": "ready", "solver": "warm"}` |

### Kubernetes Probe Configuration

```yaml
livenessProbe:
  httpGet:
    path: /api/v1/healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 10

readinessProbe:
  httpGet:
    path: /api/v1/readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
```

---

## Rollback Procedure

### Docker Rollback

```bash
# List available images
docker images shift-optimizer

# Rollback to previous version
docker stop shift-optimizer-prod
docker run -d --name shift-optimizer-prod -p 8000:8000 shift-optimizer:1.9.0
```

### Kubernetes Rollback

```bash
# Rollback to previous revision
kubectl rollout undo deployment/shift-optimizer

# Rollback to specific revision
kubectl rollout undo deployment/shift-optimizer --to-revision=2
```

---

## Monitoring

### Prometheus Metrics Endpoint

Metrics are exposed at `/metrics` (if Prometheus middleware is enabled).

Key metrics:
- `solver_budget_overrun_total` - Should be 0
- `solver_phase_duration_seconds` - Phase timing histograms
- `solver_path_selection_total` - Path A/B/C distribution

### Log Streaming

Real-time solver logs via SSE:
```
GET /api/v1/logs/stream
```

---

## Canary Deployment

### Stage 0 (Flags OFF)

```bash
# Deploy with default config
docker run -p 8000:8000 shift-optimizer:2.0.0
```

Exit criteria: No budget overruns, stable signatures.

### Stage 1 (Flags ON)

```bash
# Deploy with feature flags enabled
docker run -p 8000:8000 \
  -e ENABLE_FILL_TO_TARGET=true \
  -e ENABLE_BAD_BLOCK_MIX_RERUN=true \
  shift-optimizer:2.0.0
```

Exit criteria: KPI improvement, no regressions.

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `BUDGET_OVERRUN` in reason_codes | Solver exceeded time budget | Check instance size, increase budget |
| Signature instability | Non-deterministic behavior | Verify `seed` is set, `num_workers=1` |
| High PT ratio | Peak demand exceeds FTE capacity | Enable Path B, increase time budget |

### Debug Logging

```bash
# Enable verbose logging
export LOGLEVEL=DEBUG
python -m uvicorn src.main:app --log-level debug
```
