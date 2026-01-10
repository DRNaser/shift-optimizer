# Pilot to Server Deployment Checklist

> Checklist for deploying SOLVEREIGN to a staging/production server.

---

## 1. Bootstrap Default OFF

- [ ] Set `STAGING_BOOTSTRAP_ENABLED=false` in server env
- [ ] Bootstrap only temporarily enabled for preflight
- [ ] After preflight: disable + recreate containers
- [ ] Verify: GET `/api/auth/staging-bootstrap` returns `enabled: false`

```bash
# On server
grep STAGING_BOOTSTRAP_ENABLED /etc/solvereign/.env
# Expected: STAGING_BOOTSTRAP_ENABLED=false
```

---

## 2. TLS & __Host Cookies

### Requirements

| Requirement | Reason |
|-------------|--------|
| HTTPS only | `__Host-` prefix requires `Secure` flag |
| Valid certificate | Browser rejects invalid certs |
| `X-Forwarded-Proto: https` | Backend needs to know it's behind TLS |

### Reverse Proxy Config (nginx example)

```nginx
location / {
    proxy_pass http://frontend:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;  # CRITICAL
}
```

### Cookie Requirements

- [ ] `Secure=true` (HTTPS only)
- [ ] `Path=/` (root path)
- [ ] NO `Domain` attribute (required for `__Host-` prefix)
- [ ] `SameSite=strict`

---

## 3. Secrets Handling

### Server Env File Location

```bash
# Create secure directory
sudo mkdir -p /etc/solvereign
sudo chmod 700 /etc/solvereign

# Create env file
sudo touch /etc/solvereign/.env
sudo chmod 600 /etc/solvereign/.env
sudo chown root:root /etc/solvereign/.env
```

### Required Secrets

| Variable | Purpose | Rotation Impact |
|----------|---------|-----------------|
| `SOLVEREIGN_SESSION_SECRET` | Session signing | All active sessions invalidated |
| `STAGING_BOOTSTRAP_SECRET` | Preflight auth | No impact (short-lived) |

### Rotation Plan

1. Generate new secret: `openssl rand -base64 32`
2. Update env file
3. Recreate containers: `docker compose up -d --force-recreate`
4. Impact: All users must re-login

---

## 4. Gate A–D on Server

### Pre-Deployment

```bash
# Set environment
export STAGING_URL=https://staging.yourdomain.com
export STAGING_BOOTSTRAP_SECRET=<from-env-file>

# Run preflight
python scripts/staging_preflight.py --url $STAGING_URL
```

### Gate Checklist

| Gate | Check | Pass Criteria |
|------|-------|---------------|
| A1 | Bootstrap session | 200 + cookies |
| A2 | Session validation | 401 without, 200 with cookie |
| A3 | Role enforcement | Correct permissions |
| A4 | Write guards | CSRF + idempotency required |
| B | Security headers | All headers present |
| C | API health | /health returns 200 |
| D | Migrations | All verify functions PASS |

### Evidence Artifact

```bash
# Save evidence
cp evidence/staging_preflight_*.json /var/log/solvereign/
```

### WAIVER-001 Check

- [ ] CSP `unsafe-inline`/`unsafe-eval` waiver documented
- [ ] 90-day expiry tracked
- [ ] Exit plan in place (remove inline scripts)

---

## 5. Observability Sanity

### Prometheus

- [ ] Scrape endpoint accessible: `http://api:8000/metrics`
- [ ] No auth required for metrics (internal network only)
- [ ] Scrape interval configured

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'solvereign-api'
    static_configs:
      - targets: ['api:8000']
```

### Grafana

- [ ] Accessible on expected port (3001 default)
- [ ] Default admin password changed
- [ ] No auth bypass for dashboards
- [ ] Prometheus datasource configured

### Logging

- [ ] No secrets in logs (grep test)
- [ ] Log rotation configured
- [ ] Error alerting set up

```bash
# Verify no secrets in logs
docker compose logs api | grep -i "secret\|password\|token" | head -10
# Should return nothing sensitive
```

---

## Deployment Commands (Linux)

```bash
# Pull latest
git pull origin main

# Create env file (first time)
cat > /etc/solvereign/.env << 'EOF'
STAGING_BOOTSTRAP_ENABLED=false
STAGING_BOOTSTRAP_SECRET=$(openssl rand -base64 32 | tr -d '+/=')
SOLVEREIGN_SESSION_SECRET=$(openssl rand -base64 32 | tr -d '+/=')
EOF

# Set permissions
chmod 600 /etc/solvereign/.env

# Start stack
docker compose --env-file /etc/solvereign/.env up -d --build

# Verify
docker compose ps
curl -s https://staging.yourdomain.com/api/auth/staging-bootstrap
```

---

## Post-Deployment Verification

```bash
# 1. Health check
curl -s https://staging.yourdomain.com/health

# 2. Bootstrap disabled
curl -s https://staging.yourdomain.com/api/auth/staging-bootstrap | jq .enabled
# Expected: false

# 3. Security headers
curl -sI https://staging.yourdomain.com/my-plan | grep -E "^(x-|content-security|referrer)"

# 4. Cookie flags (via browser dev tools)
# Check: __Host-sv_platform_session has Secure, HttpOnly, SameSite=Strict
```

---

## Emergency Rollback

```bash
# Stop current
docker compose down

# Rollback to previous image
docker compose pull  # if using registry
# or: git checkout <previous-commit>

# Restart
docker compose --env-file /etc/solvereign/.env up -d

# Verify
docker compose ps
```
