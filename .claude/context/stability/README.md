# Stability Branch - Router Checklist

> **Purpose**: Incident management, health checks, and escalation
> **Severity Default**: S1/S2 - STOP-THE-LINE until resolved

---

## ENTRY CHECKLIST (MANDATORY)

**STOP. Before ANY action:**

1. **Is there an active S1/S2 incident?**
   - Check: `.claude/state/active-incidents.json`
   - YES → Read `incident-triage.md` FIRST. No exceptions.
   - NO → Continue

2. **Are health probes failing?**
   - Check: `curl http://localhost:8000/health/ready`
   - YES → Read `health-checks.md`
   - NO → Continue

3. **Did user report "broken", "down", "crash", "error"?**
   - YES → Read `incident-triage.md` (even if no formal incident)
   - NO → Continue

4. **Is this a customer-impacting issue?**
   - YES → Read `escalation-matrix.md`
   - NO → Use routing table in GUARDIAN.md

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `incident-triage.md` | Incident response procedures | ANY suspected incident |
| `health-checks.md` | Health probe configuration and debugging | Probe failures |
| `escalation-matrix.md` | Who to notify and when | Customer impact, severity decisions |

---

## EVIDENCE-FIRST RULE

**Before making ANY changes during an incident:**

```bash
# 1. Capture Run-ID / Request-ID
grep "request_id" /var/log/solvereign/*.log | tail -100 > evidence/request_ids.txt

# 2. Capture current state
curl http://localhost:8000/health/ready > evidence/health_snapshot.json
pg_dump -t service_escalations solvereign > evidence/escalations.sql

# 3. Capture logs
docker logs solvereign-api --since 1h > evidence/api_logs.txt

# 4. Document current state in incident
echo "Evidence secured at $(date)" >> evidence/timeline.txt
```

---

## INCIDENT SEVERITY QUICK REFERENCE

| Severity | Definition | Response Time | Examples |
|----------|------------|---------------|----------|
| S1 | System down, data at risk | Immediate | DB unreachable, data leak, all pods down |
| S2 | Major feature broken | <30min | Solver fails, auth broken, writes blocked |
| S3 | Minor feature degraded | <4h | Slow responses, UI glitch, non-critical error |
| S4 | Cosmetic/minor | Next sprint | Typo, minor UI issue, logging gap |

---

## STOP-THE-LINE CONDITIONS

Immediately halt ALL other work if:

- [ ] Cross-tenant data visible (RLS bypass)
- [ ] Authentication completely broken
- [ ] Database unreachable or corrupted
- [ ] Solver producing invalid results
- [ ] Evidence of data loss
- [ ] Security breach detected

**Resume work only when:**
1. Root cause identified
2. Mitigation applied
3. Health probes pass
4. Incident marked `mitigated` or `resolved`

---

## QUICK HEALTH CHECK

```bash
# Full health check
curl -s http://localhost:8000/health/ready | jq .

# Expected output:
# {
#   "status": "ready",
#   "checks": {
#     "database": "healthy",
#     "policy_service": "healthy",
#     "packs": {"roster": "available", "routing": "available"}
#   }
# }
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| System completely down | S1 | All hands. Notify stakeholders. |
| Data integrity issue | S1 | Block ALL writes. Preserve evidence. |
| Single tenant affected | S2 | Isolate tenant. Notify tenant admin. |
| Performance degraded | S2 | See `performance/timeout-playbook.md` |
| Non-critical error | S3 | Log incident. Schedule investigation. |

---

## RELATED BRANCHES

- Performance issue? → `performance/timeout-playbook.md`
- Security breach? → `security/known-vulns.md`
- Need to rollback? → `operations/rollback-procedures.md`
