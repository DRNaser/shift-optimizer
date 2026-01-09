# Wien Pilot Launch Blockers

> **Stand**: 2026-01-09
> **Status**: 4 Blocker, 2 Warnings

---

## P0 BLOCKERS (Pilot = Tot ohne diese)

### 1. Real Provider E2E ❌ NICHT GETESTET

**Problem**: E2E mit `--mock-provider` zeigt nur, dass Code existiert. Nicht, dass WhatsApp/SendGrid funktionieren.

**Was schief gehen kann**:
- SendGrid Domain/SPF/DKIM nicht korrekt → Bounces
- WhatsApp Template nicht approved → Silent fail
- Webhook URLs/Secrets falsch → Delivery status unknown

**Fix**:
```bash
# MUSS auf staging laufen (nicht lokal mit mock)
export STAGING_URL=https://staging.solvereign.com
export SENDGRID_API_KEY=<real_key>
export WHATSAPP_ACCESS_TOKEN=<real_token>

python scripts/e2e_portal_notify_evidence.py --env staging
```

**Evidence benötigt**:
- [ ] Email landet im Postfach (Screenshot)
- [ ] WhatsApp Message kommt an (Screenshot)
- [ ] Webhook events in DB sichtbar

---

### 2. Entra ID aud/iss Verification ❌ NICHT GETESTET

**Problem**: Wenn `oidc_audience` oder `oidc_issuer` falsch konfiguriert → random 401 auf allen API calls.

**Was schief gehen kann**:
- `OIDC_AUDIENCE` = `api://<wrong-client-id>` → "Invalid audience"
- `OIDC_ISSUER` fehlt multi-tenant wildcard → "Invalid issuer"
- `tenant_identities` Mapping fehlt → "TENANT_NOT_MAPPED"

**Fix**:
```bash
# Staging pre-flight mit echtem Token
export STAGING_URL=https://staging.solvereign.com
export STAGING_TOKEN=<entra_bearer_token>

python scripts/staging_preflight.py
```

**Checklist**:
- [ ] `OIDC_AUDIENCE` = `api://<client-id>` (von Azure AD App Registration)
- [ ] `OIDC_ISSUER` = `https://login.microsoftonline.com/<tenant-id>/v2.0`
- [ ] `tenant_identities` hat Eintrag für LTS Entra tid

**Config prüfen (staging env)**:
```bash
# Diese müssen gesetzt sein
OIDC_AUDIENCE=api://xxxxx
OIDC_ISSUER=https://login.microsoftonline.com/<tid>/v2.0
ENTRA_TENANT_ID=<tid>
```

---

### 3. Production Migrations ❌ NICHT APPLIED

**Problem**: Ohne 037/037a/038 gibt es keine Portal-Notify Integration in Prod.

**Fix**:
```bash
# Pre-Gate (MUSS grün sein)
python scripts/prod_migration_gate.py --env prod --phase pre

# Apply (Reihenfolge wichtig!)
psql $DATABASE_URL_PROD < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/037a_portal_notify_hardening.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/038_bounce_dnc.sql

# Post-Gate (MUSS grün sein)
python scripts/prod_migration_gate.py --env prod --phase post

# Verify
psql $DATABASE_URL_PROD -c "SELECT * FROM portal.verify_notify_integration();"
psql $DATABASE_URL_PROD -c "SELECT * FROM notify.verify_notification_integrity();"
```

---

### 4. Security Headers Verification ❌ NICHT PER CURL GEPRÜFT

**Problem**: `next.config.ts` hat Headers definiert, aber CDN/Proxy kann überschreiben.

**Fix**:
```bash
# MUSS auf staging/prod per curl geprüft werden
curl -I https://staging.solvereign.com/my-plan | grep -i "referrer\|cache-control\|frame-options\|csp"

# Erwartete Output:
# referrer-policy: no-referrer
# cache-control: no-store, no-cache, must-revalidate, proxy-revalidate
# x-frame-options: DENY
# content-security-policy: default-src 'self'; ...
```

---

## P1 WARNINGS (Pilot riskant ohne diese)

### 5. Smoke Test (7 States) ⚠️ NICHT DURCHGEFÜHRT

**Diese States müssen live funktionieren**:
1. [ ] Valid Token → Plan sichtbar
2. [ ] Refresh/Back → Plan noch sichtbar (Session Cookie)
3. [ ] Superseded Snapshot → "Neue Version" Banner
4. [ ] Expired Token → Fehlerseite
5. [ ] Accept → Status ändert sich + Audit Event
6. [ ] Decline + Reason → Status + Reason sichtbar
7. [ ] SKIPPED Driver → Grund in Table/Drawer sichtbar

---

### 6. Rate Limit Test ⚠️ NICHT GETESTET

**Implementiert**: 10 resends/hour/user (Code existiert)

**Test benötigt**:
```bash
# 11 Resends innerhalb 1h → #11 MUSS 429 sein
for i in {1..11}; do
  curl -X POST https://staging.solvereign.com/api/v1/portal/dashboard/resend \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"snapshot_id":"test","filter":"UNREAD"}'
  echo ""
done
```

---

## Was bereits funktioniert ✅

| Check | Status | Evidenz |
|-------|--------|---------|
| Security Headers (Code) | ✅ | `next.config.ts` korrekt |
| Rate Limit (Code) | ✅ | 10/h in `portal_admin.py` |
| Session Cookie Pattern | ✅ | Build passed, E2E mock passed |
| SKIPPED Visibility | ✅ | `getSkippedReasonLabel()` + UI |
| E2E Script (Mock) | ✅ | 5/5 gates passed |
| Feature Flag | ✅ | `features.portal_enabled` ready |

---

## Launch Checkliste

```
[ ] P0.1 Real Provider E2E → Email + WhatsApp Screenshots
[ ] P0.2 Entra ID → staging_preflight.py PASS
[ ] P0.3 Prod Migrations → 037, 037a, 038 applied
[ ] P0.4 Security Headers → curl output zeigt alle Headers

[ ] P1.5 Smoke Test → 7 States dokumentiert
[ ] P1.6 Rate Limit → 11. Request = 429

[ ] Feature Flag aktivieren:
    UPDATE tenants SET features = features || '{"portal_enabled": true}'::jsonb WHERE id = 1;

[ ] Monitoring aktiv:
    - Token issuance rate
    - Notification delivery rate
    - Read rate
    - Ack completion rate
```

---

## Rollback Plan

```sql
-- Feature Flag OFF (Airbag)
UPDATE tenants
SET features = features - 'portal_enabled'
WHERE id = 1;

-- Notify Worker stoppen
docker stop notify-worker

-- Bei DB Issues: KEINE Rollback-Migration
-- Stattdessen: Feature Flag OFF + DBA kontaktieren
```

---

## Kontakte

| Rolle | Name | Erreichbar |
|-------|------|------------|
| Platform Lead | TBD | - |
| DBA | TBD | - |
| On-Call | TBD | - |

---

**Nächste Aktion**: Staging Token holen und `python scripts/staging_preflight.py` ausführen.
