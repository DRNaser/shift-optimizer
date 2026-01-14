# SOLVEREIGN Release 1 - Decisions Needed

**Date**: 2026-01-13
**Status**: Pre-Release Review

---

## Open Decisions (5 Items)

### 1. Approver Role Naming

**Current State**: No "approver" role exists. `operator_admin` has publish/lock permissions.

**Options**:
| Option | Pros | Cons |
|--------|------|------|
| A) Keep `operator_admin` as approver | No DB changes needed | Name doesn't match policy language |
| B) Rename to `approver` | Matches policy | Requires migration, audit log updates |
| C) Add `approver` alias | Both names work | Complexity, potential confusion |

**Recommended Default**: **A) Keep `operator_admin`**
- Zero code changes
- Document in user guide: "operator_admin = approver role"

**Support Impact**: Low - 1-2 questions during training

---

### 2. Backup Strategy

**Current State**: No automated backup script. Manual `pg_dump` required.

**Options**:
| Option | Implementation | Recovery Time |
|--------|----------------|---------------|
| A) Manual pg_dump | Script + cron | Minutes |
| B) Azure Backup | Azure managed | Automatic |
| C) WAL Archiving | Point-in-time | Seconds |

**Recommended Default**: **A) Manual pg_dump with cron**
- Simple: `pg_dump -Fc solvereign > backup_$(date +%Y%m%d).dump`
- Restore: `pg_restore -d solvereign backup.dump`
- Schedule: Daily at 03:00 UTC

**Support Impact**: High if not implemented - data loss risk

**Action Required**: Create `scripts/backup.sh` before go-live.

---

### 3. Repair Session TTL

**Current State**: Hardcoded 1 hour TTL. Not environment-configurable.

**Options**:
| Option | TTL | Use Case |
|--------|-----|----------|
| A) Keep 1 hour | 60 min | Fast operations |
| B) Extend to 4 hours | 240 min | Long repair sessions |
| C) Make configurable | ENV var | Flexibility |

**Recommended Default**: **A) Keep 1 hour**
- Prevents stale sessions
- Users can create new session if needed
- Matches typical workflow duration

**Support Impact**: Low - 1-2 tickets/month for expired sessions

---

### 4. Second Customer Tenant Setup

**Current State**: Only "E2E Test Tenant" exists. LTS Transport not seeded.

**Questions**:
1. What is the tenant name for LTS Transport?
2. What sites does LTS Transport have? (Wien pilot only?)
3. Who is the tenant_admin contact?
4. What is the second customer's name/contact?

**Recommended Default**: Create during deployment:
```sql
INSERT INTO tenants (name, code, is_active) VALUES
  ('LTS Transport', 'LTS', true),
  ('<Second Customer>', '<CODE>', true);
```

**Support Impact**: Blocking - cannot deploy without tenant setup

---

### 5. Freeze Window Configuration

**Current State**: Freeze window logic exists but no default configuration.

**Questions**:
1. What days/times should publishing be blocked?
2. Is freeze per-tenant or global?
3. How far in advance should freeze start?

**Recommended Default**: No freeze initially
- Enable per-tenant as needed
- Document override process (force_reason required)

**Support Impact**: Low - freeze is opt-in

---

## Decision Summary

| # | Decision | Priority | Owner | Deadline |
|---|----------|----------|-------|----------|
| 1 | Approver role naming | Low | Tech Lead | Pre-training |
| 2 | Backup strategy | **HIGH** | DevOps | **Before go-live** |
| 3 | Repair session TTL | Low | Product | Post-launch |
| 4 | Tenant setup | **BLOCKING** | Product | **Before go-live** |
| 5 | Freeze window config | Low | Product | Post-launch |

---

## Action Items

- [ ] **URGENT**: Create backup script (`scripts/backup.sh`)
- [ ] **URGENT**: Confirm tenant names and admin contacts
- [ ] Document `operator_admin = approver` in user guide
- [ ] Review freeze window requirements with LTS Transport

---

*Generated: 2026-01-13*
*Requires: Product Owner sign-off*
