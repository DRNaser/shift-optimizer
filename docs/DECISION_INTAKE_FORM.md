# SOLVEREIGN Decision Intake Form

**Release**: R1 (LTS Transport + 1 Neukunde)
**Datum**: 2026-01-13
**Status**: AUSSTEHEND (Wartet auf Entscheidungen)

---

## Entscheidungstabelle

| # | Entscheidung | Optionen | IST-Zustand | VERIFIZIERT | Ihre Wahl |
|---|--------------|----------|-------------|-------------|-----------|
| 1 | **Pilot Truth Umgebung** | docker-compose.pilot.yml / Azure AKS / Hetzner | `docker-compose.pilot.yml` auf localhost:8000 | `backend_py/docker-compose.pilot.yml:1-50` | ______ |
| 2 | **Cookie-Namen (Prod)** | `__Host-sv_platform_session` / `admin_session` / custom | `__Host-sv_platform_session` (prod), `sv_platform_session` (dev) | `backend_py/api/security/internal_rbac.py:40-55` | ______ |
| 3 | **Session TTL (Admin)** | 2h / 4h / 8h / 24h | 8 Stunden | `internal_rbac.py:52` SESSION_COOKIE_MAX_AGE = 8*60*60 | ______ |
| 4 | **Session TTL (Portal)** | 30min / 60min / 2h | 60 Minuten | `frontend_v5/app/api/portal/session/route.ts:24` | ______ |
| 5 | **Repair Session TTL** | 15min / 30min / 1h | UNVERIFIED - nicht gefunden | BENÖTIGT KLÄRUNG | ______ |
| 6 | **Publish Policy** | anyone / dispatcher_only / approver_required | UNVERIFIED - kein Approver-Flow im Code | BENÖTIGT KLÄRUNG | ______ |
| 7 | **Wer darf Publish?** | Dispatcher / Operator Admin / Tenant Admin | Alle Rollen mit `plan_versions.write` | `auth.role_permissions` Mapping | ______ |
| 8 | **Freeze Semantik** | soft_lock / hard_lock / immutable | UNVERIFIED - Freeze-Endpunkt vorhanden, Semantik unklar | BENÖTIGT KLÄRUNG | ______ |
| 9 | **Lock Semantik** | UI-only / DB-trigger / RLS-enforced | DB-Trigger via `plan_snapshots_immutable_trigger` | Migration 027_plan_versioning.sql | ______ |
| 10 | **Evidence Pack Format** | JSON / PDF / Excel / ZIP | Alle drei vorhanden (JSON, PDF, Excel) | `frontend_v5/lib/export.ts` | ______ |
| 11 | **Multi-Tenant Isolation** | RLS / Application-Level / Hybrid | RLS + Application-Level (Hybrid) | 16/16 RBAC checks PASS | ______ |
| 12 | **Notification Channel** | WhatsApp / Email / SMS / All | WhatsApp + Email (C# Worker) | `backend_dotnet/Solvereign.Notify/` | ______ |
| 13 | **Backup-Strategie** | pg_dump / WAL-Archiving / Azure Backup | UNVERIFIED - kein Backup-Script gefunden | BENÖTIGT KLÄRUNG | ______ |

---

## Kritische Fragen (Vor Release beantworten)

### Business-Logik

1. **Repair-Workflow**: Wer initiiert Repairs? Dispatcher allein oder nur nach Approver-Freigabe?
2. **Publish-Approval**: Gibt es einen 4-Augen-Prinzip für Publish? Oder darf jeder Dispatcher selbst publishen?
3. **Freeze vs Lock**: Was ist der Unterschied zwischen "Freeze" (temporär) und "Lock" (permanent)?
4. **Undo-Tiefe**: Wie viele Undo-Steps sollen möglich sein? Unbegrenzt oder limitiert?

### Technische Fragen

5. **HTTPS in Produktion**: Ist HTTPS-Terminierung via Reverse Proxy (nginx/traefik) geplant?
6. **Secrets Management**: Wo werden Passwörter gespeichert? Azure Key Vault? Kubernetes Secrets?
7. **Monitoring**: Welches APM-Tool wird genutzt? Application Insights? Grafana?
8. **Backup-Fenster**: Wann soll das tägliche Backup laufen? (Nachts, wenn wenig Last)

### Rollout-Fragen

9. **Migrationsreihenfolge**: Werden beide Kunden (LTS + Neukunde) gleichzeitig live geschaltet?
10. **Fallback-Plan**: Was passiert bei einem kritischen Bug nach Go-Live?
11. **Support-Modell**: Wer beantwortet Dispatcher-Fragen im Betrieb?

---

## Signatur

| Rolle | Name | Datum | Unterschrift |
|-------|------|-------|--------------|
| Product Owner | _________________ | ______ | ______ |
| Tech Lead | _________________ | ______ | ______ |
| Kunde (LTS) | _________________ | ______ | ______ |

---

*Generiert: 2026-01-13 von Claude Code Forensik*
