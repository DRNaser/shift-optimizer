# Pilot ohne Server/Domain (HTTPS Tunnel)

> **Zweck**: Externe Tester können auf das lokale SOLVEREIGN zugreifen, ohne Server-/Domain-Kosten.
> **Voraussetzung**: Local Run erfolgreich (siehe `LOCAL_RUN_PROOF.md`)

---

## A) Tunnel Tool: Cloudflare Quick Tunnel

Kein Account, keine Domain, kostenlos.

### Installation

```powershell
winget install --id Cloudflare.cloudflared -e
cloudflared --version
```

### Tunnel starten

```powershell
# Terminal offen lassen!
cloudflared tunnel --url http://localhost:3000
```

**Output**: URL wie `https://abc123-random.trycloudflare.com`

### Public URL setzen + Health Check

```powershell
# URL aus cloudflared Output kopieren
$PUBLIC_URL = "https://<random>.trycloudflare.com"

# Health check
curl.exe -s "$PUBLIC_URL/api/auth/health"
```

**Expected**: `{"status":"ok","service":"auth",...}`

---

## B) Bootstrap bleibt OFF (Default)

```powershell
Invoke-WebRequest -Method Post -Uri "$PUBLIC_URL/api/auth/staging-bootstrap" -SkipHttpErrorCheck -StatusCodeVariable sc | Out-Null
"Status: $sc"
```

**Expected**: `Status: 403`

---

## C) Bootstrap temporär aktivieren (nur wenn nötig)

> **WICHTIG**: Nur für 1 Request, danach sofort wieder OFF!

```powershell
# 1) Enable
(Get-Content "C:\secrets\shift-optimizer\.env.staging") -replace "STAGING_BOOTSTRAP_ENABLED=false","STAGING_BOOTSTRAP_ENABLED=true" |
  Set-Content "C:\secrets\shift-optimizer\.env.staging"
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d --force-recreate frontend

# 2) Secret lesen (NICHT AUSGEBEN!)
$bootstrapSecret = (Get-Content "C:\secrets\shift-optimizer\.env.staging" | Where-Object {$_ -match '^STAGING_BOOTSTRAP_SECRET='} | ForEach-Object {$_.Split('=',2)[1].Trim()})
$headers = @{ "x-bootstrap-secret" = $bootstrapSecret }

# 3) Ein Request
$resp = Invoke-RestMethod -Method Post -Uri "$PUBLIC_URL/api/auth/staging-bootstrap" -Headers $headers
"csrf_present=" + ([bool]$resp.csrf_token)

# 4) Sofort disable
(Get-Content "C:\secrets\shift-optimizer\.env.staging") -replace "STAGING_BOOTSTRAP_ENABLED=true","STAGING_BOOTSTRAP_ENABLED=false" |
  Set-Content "C:\secrets\shift-optimizer\.env.staging"
docker compose --env-file "C:\secrets\shift-optimizer\.env.staging" up -d --force-recreate frontend

# 5) Verify disabled
Invoke-WebRequest -Method Post -Uri "$PUBLIC_URL/api/auth/staging-bootstrap" -SkipHttpErrorCheck -StatusCodeVariable sc | Out-Null
"Status: $sc"
```

**Expected**:
- `csrf_present=True`
- `Status: 403`

---

## D) Preflight gegen Public URL

```powershell
$env:STAGING_URL = $PUBLIC_URL

# Nur setzen wenn Preflight Bootstrap braucht:
# $env:STAGING_BOOTSTRAP_SECRET = $bootstrapSecret

python scripts/staging_preflight.py

# Evidence anzeigen
Get-ChildItem evidence\staging_preflight_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
```

**Expected**: Evidence JSON mit `ready_for_pilot: true`

---

## E) Stop

```powershell
# Tunnel beenden: Ctrl+C im cloudflared Fenster
# Stack stoppen (optional):
docker compose down
```

---

## Troubleshooting

### Session/Cookie funktioniert nicht über Public URL

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| Login ok, aber danach 401 | Mixed origins | Immer exakt `$PUBLIC_URL` verwenden, keine localhost Tabs parallel |
| Cookie wird nicht gesetzt | Browser Policy | Private/Incognito Window testen |
| `__Host-` Cookie rejected | HTTP statt HTTPS | Tunnel muss HTTPS sein (cloudflared macht das automatisch) |

### Tunnel URL ändert sich

Cloudflare Quick Tunnel erzeugt bei jedem Start eine neue URL. Für persistente URL: kostenlosen Cloudflare Account + named tunnel.

---

## Sicherheitsregeln

1. **Bootstrap niemals dauerhaft ON lassen** - nur für 1 Request
2. **Secrets nie ausgeben** - `$bootstrapSecret` nur in Header verwenden
3. **Tunnel beenden** wenn nicht gebraucht
4. **Evidence lokal speichern** - nicht committen (`.gitignore`)
