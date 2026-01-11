# Wien Pilot Launch Blockers

> **Stand**: 2026-01-09
> **Status**: 3 Blocker, 2 Warnings, 3 Pilot-Kill Checks (auto-prüfbar)
> **Internal RBAC**: V4.4.0 COMPLETE (ersetzt Entra ID)

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

### 2. Production Migrations ❌ NICHT APPLIED

**Problem**: Ohne 037/037a/038/039 gibt es keine Portal-Notify Integration + RBAC in Prod.

**Fix**:
```bash
# Pre-Gate (MUSS grün sein)
python scripts/prod_migration_gate.py --env prod --phase pre

# Apply (Reihenfolge wichtig!)
psql $DATABASE_URL_PROD < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/037a_portal_notify_hardening.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/038_bounce_dnc.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/039_internal_rbac.sql

# Post-Gate (MUSS grün sein)
python scripts/prod_migration_gate.py --env prod --phase post

# Verify
psql $DATABASE_URL_PROD -c "SELECT * FROM portal.verify_notify_integration();"
psql $DATABASE_URL_PROD -c "SELECT * FROM notify.verify_notification_integrity();"
psql $DATABASE_URL_PROD -c "SELECT * FROM auth.verify_rbac_integrity();"
```

---

### 3. Security Headers Verification ❌ NICHT PER CURL GEPRÜFT

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

### 4. Smoke Test (7 States) ⚠️ NICHT DURCHGEFÜHRT

**Diese States müssen live funktionieren**:
1. [ ] Valid Token → Plan sichtbar
2. [ ] Refresh/Back → Plan noch sichtbar (Session Cookie)
3. [ ] Superseded Snapshot → "Neue Version" Banner
4. [ ] Expired Token → Fehlerseite
5. [ ] Accept → Status ändert sich + Audit Event
6. [ ] Decline + Reason → Status + Reason sichtbar
7. [ ] SKIPPED Driver → Grund in Table/Drawer sichtbar

---

### 5. Rate Limit Test ⚠️ NICHT GETESTET

**Implementiert**: 10 resends/hour/user (Code existiert)

**Test benötigt**:
```bash
# 11 Resends innerhalb 1h → #11 MUSS 429 sein
for i in {1..11}; do
  curl -X POST https://staging.solvereign.com/api/v1/portal/dashboard/resend \
    -H "Cookie: admin_session=<session_token>" \
    -H "Content-Type: application/json" \
    -d '{"snapshot_id":"test","filter":"UNREAD"}'
  echo ""
done
```

---

## PILOT-KILL CHECKS (3 letzte kritische Prüfungen)

Diese 3 Checks sind jetzt in `staging_preflight.py` integriert:

### PK1. Cookie Domain/Proxy ⚠️ AUTO-GEPRÜFT

**Problem**: Bei TLS-Termination (Reverse Proxy) können Secure-Cookies "wegoptimiert" werden.

**Automatischer Check in staging_preflight.py**:
- Prüft `Set-Cookie` Header auf `Secure`, `HttpOnly`, `SameSite` Flags
- BLOCKER auf HTTPS wenn Secure fehlt
- WARNING auf HTTP (localhost dev)

### PK2. CSRF Protection ⚠️ AUTO-GEPRÜFT

**Design-Entscheidung**: CSRF-Schutz via `SameSite=Strict` Cookie (nicht Origin/Referer blocking)

**Warum SameSite=Strict statt Origin-Check**:
- `SameSite=Strict`: Browser sendet Cookie NIE bei Cross-Site Requests → 99%+ Browser Coverage
- Origin/Referer: API-Clients (curl, Postman) senden keine Origin → würde legitime Calls blocken

**Automatischer Check in staging_preflight.py**:
- Prüft `Set-Cookie` auf `samesite=strict` oder `samesite=lax`
- BLOCKER wenn `SameSite=None`

### PK3. Session TTL/Time Drift ⚠️ AUTO-GEPRÜFT

**Problem**: Falsche Serverzeit → `expires_at` im Cookie/DB falsch → Session-Probleme.

**Automatischer Check in staging_preflight.py**:
- Login → `/api/auth/me` abrufen
- Prüft ob Session valide ist und `user_id` zurückkommt
- BLOCKER wenn Session sofort ungültig

**Alle 3 Checks ausführen**:
```bash
export STAGING_URL=https://staging.solvereign.com
export STAGING_EMAIL=dispatcher@lts.at
export STAGING_PASSWORD=<password>

python scripts/staging_preflight.py
# Expected: 9 checks, 0 BLOCKERs → READY FOR PILOT
```

---

## RESOLVED ✅ (V4.4.0 Internal RBAC)

### ~~Entra ID aud/iss Verification~~ → **ENTFERNT**

**Status**: Nicht mehr relevant - Internal RBAC ersetzt Entra ID

Die interne RBAC-Authentifizierung (V4.4.0) ersetzt Microsoft Entra ID:
- Email/Password Login mit Argon2id
- Server-side Sessions mit HttpOnly Cookies
- Keine externen OIDC Dependencies

**Neue Pre-Flight**:
```bash
# Mit Internal RBAC Credentials (nicht Entra Token)
export STAGING_URL=https://staging.solvereign.com
export STAGING_EMAIL=dispatcher@lts.at
export STAGING_PASSWORD=<password>

python scripts/staging_preflight.py
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
| **Internal RBAC** | ✅ | Migration 039 + Tests passing |
| **Login Page** | ✅ | Email/Password mit deutscher UI |
| **Session Auth** | ✅ | HttpOnly Cookie + BFF forwarding |

---

## Launch Checkliste (RBAC-FIRST!)

### Phase 1: RBAC Setup (VOR allen anderen Schritten)

```bash
# 1. Migration 039 anwenden (falls noch nicht geschehen)
psql $DATABASE_URL_PROD < backend_py/db/migrations/039_internal_rbac.sql

# 2. RBAC Integrität verifizieren (MUSS 8x PASS)
psql $DATABASE_URL_PROD -c "SELECT * FROM auth.verify_rbac_integrity();"

# 3. User anlegen mit CLI Script (NICHT manuelle SQL!)
python scripts/create_user.py create \
    --email dispatcher@lts.at \
    --name "Dispatcher Wien" \
    --tenant 1 \
    --site 10 \
    --role dispatcher

# 4. Admin User anlegen
python scripts/create_user.py create \
    --email admin@solvereign.com \
    --name "Platform Admin" \
    --tenant 1 \
    --role platform_admin

# 5. User Liste verifizieren
python scripts/create_user.py list

# 6. RBAC Integrität erneut prüfen
python scripts/create_user.py verify
```

### Phase 2: Provider + Migrations

```
[ ] P0.1 Real Provider E2E → Email + WhatsApp Screenshots
[ ] P0.2 Prod Migrations → 037, 037a, 038 applied
[ ] P0.3 Security Headers → curl output zeigt alle Headers
```

### Phase 3: Feature Activation

```bash
# Feature Flag aktivieren (NUR nach Phase 1+2!)
psql $DATABASE_URL_PROD -c "
    UPDATE tenants
    SET features = features || '{\"portal_enabled\": true}'::jsonb
    WHERE id = 1;
"
```

### Phase 4: Smoke Tests

```
[ ] P1.4 Smoke Test → 7 States dokumentiert
[ ] P1.5 Rate Limit → 11. Request = 429
[ ] P1.6 Login Test → Dispatcher kann sich einloggen
[ ] P1.7 Session Refresh → F5 behält Session bei
```

### Phase 5: Monitoring

```
[ ] Token issuance rate aktiv
[ ] Notification delivery rate aktiv
[ ] Read rate aktiv
[ ] Ack completion rate aktiv
[ ] Login failures monitored
```

---

## User Management CLI (create_user.py)

**WICHTIG**: Für User-Erstellung IMMER das CLI Script verwenden, NICHT manuelle SQL!

**SECURITY**: Passwörter NIEMALS in der Kommandozeile übergeben! Stattdessen:
1. Interaktive Eingabe (empfohlen): `--password` weglassen → sicherer Prompt
2. Environment Variable: `export USER_PASSWORD=... && python scripts/create_user.py create ...`

```bash
# Befehle
python scripts/create_user.py create    # Neuen User anlegen (Passwort-Prompt)
python scripts/create_user.py list      # Alle User anzeigen
python scripts/create_user.py verify    # RBAC Integrität prüfen
python scripts/create_user.py cleanup-sessions --force    # Expired Sessions löschen

# Beispiel: Dispatcher für Wien (INTERAKTIVER PASSWORT-PROMPT)
python scripts/create_user.py create \
    --email max.mustermann@lts.at \
    --name "Max Mustermann" \
    --tenant 1 \
    --site 10 \
    --role dispatcher
# → Passwort wird sicher abgefragt (kein Echo)

# Verfügbare Rollen:
# - platform_admin: Vollzugriff
# - operator_admin: Tenant-Admin
# - dispatcher: Portal + Plan Management
# - ops_readonly: Nur Lesen
```

---

## Rollback Plan

### Stufe 1: Feature Flag OFF (Sofort, < 1 Min)

```sql
-- Portal Feature deaktivieren (Airbag)
-- Wirkung: Portal-URLs zeigen "Feature deaktiviert"
UPDATE tenants
SET features = features - 'portal_enabled'
WHERE id = 1;

-- Verify
SELECT features->'portal_enabled' FROM tenants WHERE id = 1;
-- Erwartung: NULL oder false
```

### Stufe 2: Notify Worker stoppen (< 5 Min)

```bash
# Keine neuen Notifications mehr
docker stop notify-worker

# Oder bei Kubernetes:
kubectl scale deployment notify-worker --replicas=0
```

### Stufe 3: Session Cleanup (bei Session-Problemen)

```sql
-- Alle aktiven Sessions invalidieren (Force Logout)
UPDATE auth.sessions SET revoked_at = NOW() WHERE revoked_at IS NULL;

-- Expired Sessions entfernen
SELECT auth.cleanup_expired_sessions();
```

### Stufe 4: User Deaktivierung (bei kompromittiertem Account)

```sql
-- Einzelnen User deaktivieren
UPDATE auth.users SET is_active = FALSE WHERE email = 'user@example.com';

-- Alle Sessions dieses Users revoken
UPDATE auth.sessions s
SET revoked_at = NOW()
FROM auth.users u
WHERE s.user_id = u.id AND u.email = 'user@example.com';
```

### KRITISCH: Was NICHT tun

- **KEINE Rollback-Migration** für 039_internal_rbac.sql ausführen
- **KEINE DROP SCHEMA auth** ohne DBA-Genehmigung
- Bei DB-Issues: Feature Flag OFF + DBA kontaktieren

---

## Kontakte

| Rolle | Name | Erreichbar |
|-------|------|------------|
| Platform Lead | TBD | - |
| DBA | TBD | - |
| On-Call | TBD | - |

---

## Staging Execution Guide (Copy-Paste Ready)

### Schritt 1: Environment Setup

```bash
# Staging Database URL (vom DBA anfordern)
export DATABASE_URL="postgresql://user:pass@staging-db:5432/solvereign"

# Staging Frontend URL
export STAGING_URL="https://staging.solvereign.com"
```

### Schritt 2: Migration 039 anwenden

```bash
# Apply Internal RBAC migration
psql $DATABASE_URL < backend_py/db/migrations/039_internal_rbac.sql

# Verify (MUSS 8x PASS zeigen)
psql $DATABASE_URL -c "SELECT * FROM auth.verify_rbac_integrity();"
```

### Schritt 3: Dispatcher User anlegen

```bash
# User erstellen (Passwort wird sicher abgefragt)
python scripts/create_user.py create \
    --email dispatcher@lts.at \
    --name "Dispatcher Wien" \
    --tenant 1 \
    --site 10 \
    --role dispatcher

# RBAC Integrität verifizieren
python scripts/create_user.py verify

# User-Liste prüfen
python scripts/create_user.py list
```

### Schritt 4: Staging Preflight (9 Checks)

```bash
# Staging Credentials für Preflight
export STAGING_EMAIL="dispatcher@lts.at"
# Passwort wird interaktiv abgefragt oder via env:
# export STAGING_PASSWORD="..."

# Alle 9 Checks ausführen
python scripts/staging_preflight.py

# Erwartetes Ergebnis:
# ✅ security_headers: PASS
# ✅ route_caching: PASS
# ✅ internal_auth: PASS
# ✅ api_health: PASS
# ✅ auth_health: PASS
# ✅ portal_page: PASS
# ✅ cookie_secure_flag: PASS
# ✅ csrf_protection: PASS
# ✅ session_ttl: PASS
#
# Result: 9/9 PASS, 0 BLOCKER
```

### Schritt 5: Real Provider E2E (Optional)

```bash
# Nur wenn SendGrid/WhatsApp konfiguriert
export SENDGRID_API_KEY="..."
export WHATSAPP_ACCESS_TOKEN="..."

python scripts/e2e_portal_notify_evidence.py --env staging
```

### Schritt 6: Feature Flag aktivieren (NUR nach allen grünen Checks!)

```sql
-- Portal für Tenant 1 aktivieren
UPDATE tenants
SET features = features || '{"portal_enabled": true}'::jsonb
WHERE id = 1;

-- Verify
SELECT features FROM tenants WHERE id = 1;
```

---

**Nächste Aktion (TL;DR)**:
1. `psql $DATABASE_URL < backend_py/db/migrations/039_internal_rbac.sql`
2. `python scripts/create_user.py create --email dispatcher@lts.at --tenant 1 --site 10 --role dispatcher`
3. `python scripts/create_user.py verify`
4. `python scripts/staging_preflight.py`
5. Bei 9/9 PASS → Feature Flag aktivieren
