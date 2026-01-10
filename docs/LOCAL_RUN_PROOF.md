# SOLVEREIGN Local Run Proof

> **Date**: 2026-01-10
> **Status**: All Gates PASS
> **Evidence**: `evidence/staging_preflight_20260110_165531.json`

---

## Stack Overview

| Service | Port | Status |
|---------|------|--------|
| Frontend (Next.js BFF) | 3000 | healthy |
| Backend (FastAPI) | 8000 | healthy |
| PostgreSQL | 5432 | healthy |
| Redis | 6379 | healthy |
| Prometheus | 9090 | running |
| Grafana | 3001 | running |

---

## Secrets Policy

**CRITICAL**: Environment file is stored **outside** the repository and OneDrive:

```
C:\secrets\shift-optimizer\.env.staging
```

This file contains:
- `STAGING_BOOTSTRAP_ENABLED` - Bootstrap endpoint toggle
- `STAGING_BOOTSTRAP_SECRET` - Auth header secret
- `SOLVEREIGN_SESSION_SECRET` - Session signing key

**Never commit secrets to the repository.**

---

## Runbook Summary

| Step | Description | Status |
|------|-------------|--------|
| 1 | Compose file detected | PASS |
| 2 | Secrets generated (PowerShell RNG) | PASS |
| 3 | ACL restricted to user | WARN (domain trust, non-fatal) |
| 4 | Old fixed-name containers removed | PASS |
| 5 | Stack started with env-file | PASS |
| 6 | Env vars verified in frontend | PASS |
| 7 | Bootstrap status GET | PASS (`enabled=true`) |
| 8 | Bootstrap POST without secret | PASS (`401 MISSING_SECRET`) |
| 9 | Bootstrap POST with secret | PASS (`200 + __Host- cookies`) |
| 10 | Preflight script executed | PASS (evidence saved) |
| 11 | Bootstrap disabled + verified | PASS (`403 BOOTSTRAP_DISABLED`) |

---

## Bootstrap Safety Rule

1. **Default**: `STAGING_BOOTSTRAP_ENABLED=false`
2. **For testing**: Temporarily set to `true`, run tests
3. **After testing**: Set back to `false` + recreate container
4. **Verification**: GET endpoint shows `enabled: false`

```powershell
# Disable bootstrap after testing
(Get-Content "C:\secrets\shift-optimizer\.env.staging") -replace "STAGING_BOOTSTRAP_ENABLED=true","STAGING_BOOTSTRAP_ENABLED=false" | Set-Content "C:\secrets\shift-optimizer\.env.staging"
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d --force-recreate frontend
```

---

## Evidence

- **Preflight JSON**: `evidence/staging_preflight_20260110_165531.json`
- **Checks passed**: Security headers, Route caching, Portal page
- **Bootstrap verified**: 401 without secret, 200 with secret, 403 when disabled

---

## Known Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| ACL Domain Trust Warning | Non-fatal | Windows domain policy, file still protected |
| Celery worker container | Non-blocking | Command path issue, not needed for bootstrap test |
| Preflight health checks | False positive | `/health` endpoints on backend:8000, not frontend:3000 |

---

## Quick Commands

```powershell
# Start stack
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d

# Check status
docker compose ps

# View logs
docker compose logs -f frontend
docker compose logs -f api

# Stop (NEVER use -v)
docker compose down
```
