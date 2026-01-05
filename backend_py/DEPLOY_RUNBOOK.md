# SOLVEREIGN V3.3a Deploy Runbook

**Version**: v3.3a-full-approval
**Commit**: a8005c2

---

## 1. Migrate

```bash
# Backup DB first
pg_dump -h $DB_HOST -U $DB_USER $DB_NAME > backup_$(date +%Y%m%d_%H%M%S).sql

# Run migrations
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f db/init.sql
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f db/migrations/001_tour_instances.sql
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f db/migrations/007_idempotency_keys.sql
```

---

## 2. Start / Restart

```bash
# Docker (recommended)
docker compose up -d

# Or manual
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Verify
curl http://localhost:8000/health
curl http://localhost:8000/metrics | head -5
```

---

## 3. Rollback

```bash
# Stop service
docker compose down

# Restore DB from backup
psql -h $DB_HOST -U $DB_USER -d $DB_NAME < backup_YYYYMMDD_HHMMSS.sql

# Checkout previous version
git checkout v3.2.0  # or previous tag

# Restart
docker compose up -d
```

---

**Emergency Contact**: #solvereign-ops Slack
