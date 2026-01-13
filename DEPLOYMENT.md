# SOLVEREIGN - Deployment Guide

## Quick Start

### Docker Compose (Recommended)

```bash
# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker compose logs -f api
```

### Local Development

```bash
cd backend_py

# Install dependencies
pip install -r requirements.txt

# Run Enterprise API (recommended)
uvicorn api.main:app --reload --port 8000

# Or run Legacy API
uvicorn src.main:app --reload --port 8000
```

---

## Services

| Service | Port | Description |
|---------|------|-------------|
| API | 8000 | SOLVEREIGN Enterprise API |
| Frontend (BFF) | 3000 | Next.js frontend |
| PostgreSQL | 5432 | Database (local only) |
| Prometheus | 9090 | Metrics collection |
| Grafana | 3001 | Dashboards |

### Production Deployment

For production, use `docker-compose.prod.yml` with proper secrets:

```bash
# 1. Copy the example env file
cp .env.prod.example .env.prod

# 2. Edit .env.prod with secure values
#    - POSTGRES_PASSWORD: strong random password
#    - SOLVEREIGN_SESSION_SECRET: openssl rand -hex 32
#    - GRAFANA_ADMIN_PASSWORD: strong password

# 3. Deploy with production compose
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

**Key differences from local compose:**
- No exposed PostgreSQL/Redis ports (internal network only)
- No default passwords (must be set in .env.prod)
- Bootstrap disabled by default
- SOLVEREIGN_ENVIRONMENT=production

---

## Secrets Management

### Development

Secrets via Environment Variables in `docker-compose.yml`:

```yaml
environment:
  - SOLVEREIGN_DATABASE_URL=postgresql://...
  - SOLVEREIGN_ENTRA_TENANT_ID=...
  - SOLVEREIGN_ENTRA_CLIENT_ID=...
```

### Production

| Secret | Location | Notes |
|--------|----------|-------|
| `DATABASE_URL` | Azure Key Vault / k8s Secret | PostgreSQL connection string |
| `ENTRA_TENANT_ID` | Azure Key Vault | Microsoft Entra tenant GUID |
| `ENTRA_CLIENT_ID` | Azure Key Vault | Entra application ID |
| `ENCRYPTION_KEY` | Azure Key Vault | AES-256 key for PII encryption |

**Never commit secrets to git.** Use `.env.local` for local dev (gitignored).

---

## Database Migrations

### Automatic (on container start)

PostgreSQL init script runs automatically on first start:

```
backend_py/db/init.sql          # Base schema (runs via docker-entrypoint-initdb.d)
```

### Manual Migrations (V3.3b)

Run in order:

```bash
# Connect to PostgreSQL
docker exec -it solvereign-db psql -U solvereign -d solvereign

# Apply migrations
\i /docker-entrypoint-initdb.d/01-init.sql

# Or via psql from host
psql $DATABASE_URL < backend_py/db/migrations/006_multi_tenant.sql
psql $DATABASE_URL < backend_py/db/migrations/007_idempotency_keys.sql
psql $DATABASE_URL < backend_py/db/migrations/008_tour_segments.sql
psql $DATABASE_URL < backend_py/db/migrations/009_plan_versions_extended.sql
psql $DATABASE_URL < backend_py/db/migrations/010_encryption_keys.sql
psql $DATABASE_URL < backend_py/db/migrations/011_rls_policies.sql
```

Migration order is critical - run sequentially, not in parallel.

---

## Tenant Setup (LTS Mapping)

### Initial Tenant Creation

```sql
-- In PostgreSQL
INSERT INTO tenants (id, name, slug, entra_tenant_id, settings)
VALUES (
  gen_random_uuid(),
  'LTS Transport & Logistik GmbH',
  'lts',
  'YOUR_ENTRA_TENANT_ID',  -- From Azure Portal
  '{"timezone": "Europe/Berlin", "locale": "de-DE"}'
);
```

### Tenant Identity Mapping

Users are mapped via Entra ID token claims:

```sql
-- Map Entra user to tenant
INSERT INTO tenant_identities (tenant_id, entra_object_id, role, email)
VALUES (
  (SELECT id FROM tenants WHERE slug = 'lts'),
  'USER_ENTRA_OBJECT_ID',  -- From Entra ID
  'ADMIN',                  -- PLANNER, APPROVER, or ADMIN
  'user@lts.de'
);
```

See `docs/ENTRA_SETUP_LTS.md` for complete Entra configuration.

---

## Rollback Procedures

### API Rollback (Docker)

```bash
# Tag current as backup
docker tag solvereign-api:latest solvereign-api:backup

# Stop current
docker compose stop api

# Roll back to previous version
docker compose up -d api --build  # Uses git checkout to previous commit

# Or pull specific tag
docker pull solvereign-api:3.2.0
docker compose up -d api
```

### API Rollback (Kubernetes)

```bash
# View history
kubectl rollout history deployment/solvereign-api

# Rollback to previous
kubectl rollout undo deployment/solvereign-api

# Rollback to specific revision
kubectl rollout undo deployment/solvereign-api --to-revision=2
```

### Database Rollback

**CAUTION: Data migrations may not be reversible.**

```bash
# 1. Stop API to prevent writes
docker compose stop api

# 2. Create backup
docker exec solvereign-db pg_dump -U solvereign solvereign > backup_$(date +%Y%m%d).sql

# 3. Restore from backup
docker exec -i solvereign-db psql -U solvereign solvereign < backup_YYYYMMDD.sql

# 4. Restart API
docker compose up -d api
```

For schema-only rollback, apply reverse migration scripts (if available).

---

## Monitoring & Alerting

### Health Endpoints

| Endpoint | Purpose | Alert if |
|----------|---------|----------|
| `GET /health` | Liveness | Returns non-200 |
| `GET /health/ready` | Readiness | `database != "healthy"` |
| `GET /metrics` | Prometheus | N/A (scrape target) |

### Prometheus Metrics (What's Red?)

| Metric | Alert Threshold | Meaning |
|--------|----------------|---------|
| `http_requests_total{status="5xx"}` | > 10/min | API errors |
| `solver_duration_seconds` | > 300s | Solver timeout |
| `db_pool_available_connections` | < 2 | Pool exhaustion |
| `http_request_duration_seconds_p99` | > 5s | Slow responses |

### Grafana Dashboards

Pre-configured at http://localhost:3000 (admin/admin):

- **SOLVEREIGN Overview**: Request rate, error rate, latency
- **Solver Performance**: Solve times, coverage, driver counts
- **Database Health**: Connection pool, query latency

### Alerting Setup

```yaml
# prometheus/alerts.yml (example)
groups:
  - name: solvereign
    rules:
      - alert: APIDown
        expr: up{job="solvereign"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "SOLVEREIGN API is down"

      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SOLVEREIGN_DATABASE_URL` | - | PostgreSQL connection string |
| `SOLVEREIGN_ENVIRONMENT` | development | Environment name |
| `SOLVEREIGN_LOG_LEVEL` | INFO | Logging level |
| `SOLVEREIGN_ENTRA_TENANT_ID` | - | Microsoft Entra tenant |
| `SOLVEREIGN_ENTRA_CLIENT_ID` | - | Entra application ID |
| `API_MODULE` | api.main:app | Which API to run |

---

## Frontend (Optional)

The `frontend_v5/` folder contains a Next.js frontend (not required for API-only deployment):

```bash
cd frontend_v5
npm install
npm run build
npm start
```

Note: `node_modules/` is gitignored and must be regenerated via `npm install`.

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| DB connection timeout | Wrong DATABASE_URL | Use Docker service name `postgres` |
| Health check fails | Wrong endpoint | Use `/health` not `/api/v1/healthz` |
| Import errors | Missing deps | Check requirements.txt |
| 401 Unauthorized | Invalid/expired token | Check Entra configuration |
| 403 Forbidden | Insufficient permissions | Check tenant_identities role |

### Debug Logging

```bash
SOLVEREIGN_LOG_LEVEL=DEBUG uvicorn api.main:app --reload
```
