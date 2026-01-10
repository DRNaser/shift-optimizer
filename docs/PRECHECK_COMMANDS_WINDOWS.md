# SOLVEREIGN Daily Ops Commands (Windows)

> Minimal commands for daily operations. No secrets output.

---

## Stack Status

```powershell
# View all containers
docker compose ps

# View specific service status
docker compose ps frontend
docker compose ps api
```

---

## Logs

```powershell
# Frontend logs (follow)
docker compose logs -f frontend

# Backend logs (follow)
docker compose logs -f api

# All logs (last 100 lines)
docker compose logs --tail=100
```

---

## Health Checks

```powershell
# Backend health
curl.exe -s http://localhost:8000/health

# Frontend bootstrap status (no auth required)
curl.exe -s http://localhost:3000/api/auth/staging-bootstrap

# Backend auth health
curl.exe -s http://localhost:8000/api/auth/health
```

---

## Start / Stop

```powershell
# Start with env-file
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d

# Stop (keeps volumes)
docker compose down

# Restart single service
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d --force-recreate frontend
```

---

## Rebuild

```powershell
# Rebuild frontend
docker compose build --no-cache frontend

# Rebuild all
docker compose build --no-cache
```

---

## NEVER DO

```powershell
# NEVER use -v flag (deletes all data!)
# docker compose down -v  # <-- FORBIDDEN

# NEVER echo secrets
# echo $secret  # <-- FORBIDDEN
```

---

## Check Env Vars (Safe)

```powershell
# Show env var names only (not values)
docker compose exec frontend sh -c "env | grep -E '^(STAGING_|SOLVEREIGN_)' | sed 's/=.*/=<SET>/'"
```

Expected output:
```
STAGING_BOOTSTRAP_ENABLED=<SET>
STAGING_BOOTSTRAP_SECRET=<SET>
SOLVEREIGN_SESSION_SECRET=<SET>
```

---

## Port Reference

| Service | Port |
|---------|------|
| Frontend | 3000 |
| Backend | 8000 |
| Grafana | 3001 |
| Prometheus | 9090 |
| PostgreSQL | 5432 |
| Redis | 6379 |
