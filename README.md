# SOLVEREIGN

**Enterprise Shift Scheduling Platform for Last-Mile Delivery**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue.svg)](https://www.postgresql.org)
[![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-red.svg)](https://developers.google.com/optimization)

## Overview

SOLVEREIGN is an event-sourced, version-controlled shift scheduling platform that transforms tour forecasts into optimal weekly driver assignments. Built for LTS Transport & Logistik GmbH.

### Key Features

- **Multi-Tenant Architecture**: PostgreSQL RLS with tenant isolation
- **Enterprise Security**: Microsoft Entra ID OIDC authentication
- **OR-Tools Solver**: Heuristic block solver (145 drivers, 100% coverage)
- **7 Compliance Audits**: Coverage, Overlap, Rest, Span, Split, Fatigue, Freeze
- **Event Sourcing**: Immutable versions with diff engine
- **Structured Logging**: JSON logs with correlation IDs

---

## Quick Start

### Docker Compose (Recommended)

```bash
# Clone and start
git clone <repo-url>
cd solvereign
docker compose up -d

# Verify health
curl http://localhost:8000/health
```

### Endpoints

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## API Endpoints

### Health Checks

```bash
# Liveness (API is running)
curl http://localhost:8000/health

# Readiness (DB connected)
curl http://localhost:8000/health/ready
```

### Solver

```bash
# Solve forecast
curl -X POST http://localhost:8000/api/v1/plans/solve \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"forecast_version_id": 1, "seed": 94}'
```

---

## Architecture

```
solvereign/
├── backend_py/
│   ├── api/              # Enterprise API (V3.3b)
│   │   ├── main.py       # FastAPI application
│   │   ├── routers/      # HTTP endpoints
│   │   ├── security/     # Entra ID, JWT, encryption
│   │   └── repositories/ # Database access
│   ├── v3/               # Core business logic
│   │   ├── solver_v2_integration.py
│   │   ├── audit_fixed.py
│   │   └── parser.py
│   └── db/               # PostgreSQL schema
├── monitoring/           # Prometheus + Grafana
└── docker-compose.yml
```

---

## Compliance Audits

| Audit | Description |
|-------|-------------|
| Coverage | Every tour assigned exactly once |
| Overlap | No concurrent tours per driver |
| Rest | >= 11h rest between work days |
| Span Regular | 1er/2er blocks <= 14h span |
| Span Split | 3er/split blocks <= 16h span |
| Fatigue | No consecutive 3er blocks |
| Freeze | No changes within 12h of start |

---

## Configuration

Environment variables (prefix: `SOLVEREIGN_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `ENVIRONMENT` | development | Environment name |
| `LOG_LEVEL` | INFO | Logging level |
| `ENTRA_TENANT_ID` | - | Microsoft Entra tenant |
| `ENTRA_CLIENT_ID` | - | Entra application ID |

---

## Development

```bash
# Install dependencies
cd backend_py
pip install -r requirements.txt

# Run API locally
uvicorn api.main:app --reload

# Run tests
python -m pytest tests/ -v
```

---

## License

Proprietary - LTS Transport & Logistik GmbH
