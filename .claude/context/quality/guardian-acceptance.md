# Guardian Acceptance Gate (10 Points)

> **Purpose**: Validate Guardian Context Tree is functioning correctly
> **When to Run**: Before any audit, proof, or determinism work
> **Pass Criteria**: ALL 10 checks PASS

---

## Quick Validation

```bash
# Run all checks
python backend_py/guardian_bootstrap.py
echo "Exit code: $?"

# Expected:
# - Exit 0: All healthy
# - Exit 1: Schema validation failed
# - Exit 2: S0/S1 STOP-THE-LINE active
```

---

## 10-Point Checklist

### 1. Git Clean (or Dirty-Handling Active)

```bash
git status --porcelain
# Empty = clean
# Non-empty = dirty (check 00-current-state.md shows warning)
```

**Pass if**: Clean OR dirty warning appears in `00-current-state.md`

---

### 2. Schemas Validate

```bash
python -c "
import json
import jsonschema
from pathlib import Path

for schema_file in Path('.claude/schemas').glob('*.json'):
    with open(schema_file) as f:
        schema = json.load(f)
    jsonschema.Draft7Validator.check_schema(schema)
    print(f'PASS: {schema_file.name}')
"
```

**Pass if**: All 4 schemas are valid Draft-07

---

### 3. Bootstrap Exit Codes Correct

```bash
# Test healthy state
python backend_py/guardian_bootstrap.py
echo "Healthy exit: $?"  # Should be 0

# Test S0/S1 detection (manual)
# Edit active-incidents.json with S0 incident, run bootstrap
# Should exit 2
```

**Pass if**: Exit 0 when healthy, Exit 2 when S0/S1 active

---

### 4. Security Override Test

```bash
# Create test incident with security keyword
echo '{"incidents": [{"id": "INC-20260107-TEST01", "severity": "S2", "status": "active", "created_at": "2026-01-07T00:00:00Z", "summary": "RLS leak in tenant isolation"}]}' > .claude/state/active-incidents.json

python backend_py/guardian_bootstrap.py

# Check routing_hint in health_latest.json
cat .claude/telemetry/health_latest.json | grep routing_hint
# Should show: "routing_hint": "security"

# Restore
git checkout .claude/state/active-incidents.json
```

**Pass if**: Security keywords trigger security override

---

### 5. Stop-the-Line Banner Test

```bash
# Create S1 incident
echo '{"incidents": [{"id": "INC-20260107-TEST02", "severity": "S1", "status": "active", "created_at": "2026-01-07T00:00:00Z", "summary": "Integrity issue"}]}' > .claude/state/active-incidents.json

python backend_py/guardian_bootstrap.py

# Check banner in 00-current-state.md
head -10 .claude/context/00-current-state.md
# Should show STOP-THE-LINE banner at top

# Restore
git checkout .claude/state/active-incidents.json
```

**Pass if**: S0/S1 incidents show STOP-THE-LINE banner at TOP of `00-current-state.md`

---

### 6. Bootstrap Offline-Mode Test

```bash
# Stop API if running, then run bootstrap
# Bootstrap should handle unreachable API gracefully

python backend_py/guardian_bootstrap.py
cat .claude/telemetry/health_latest.json | grep status
# Should show "unreachable" or "unknown", NOT crash
```

**Pass if**: Bootstrap completes without crash when API unreachable

---

### 7. State Files Not Modified

```bash
# Run bootstrap and verify state/ unchanged
git diff .claude/state/
# Should be empty (no modifications)
```

**Pass if**: Bootstrap NEVER modifies `state/*.json`

---

### 8. Telemetry Contains Audit Trail

```bash
cat .claude/telemetry/health_latest.json
# Must contain:
# - git_sha
# - dirty
# - audit_grade
# - stop_the_line
# - routing_hint
# - routing_reason
```

**Pass if**: All audit trail fields present in `health_latest.json`

---

### 9. Severity System Matches Kernel

```bash
# Check incident schema uses S0-S3 (not S1-S4)
cat .claude/schemas/incident.schema.json | grep enum
# Should show: ["S0", "S1", "S2", "S3"]

# Check GUARDIAN.md uses S0/S1
grep -E "S0|S1" .claude/GUARDIAN.md | head -5
# Should reference S0/S1 for STOP-THE-LINE
```

**Pass if**: S0-S3 everywhere (matches Kernel escalation service)

---

### 10. Security Keywords Scoped

```bash
# Test: XSS alone with S3 severity should NOT trigger security override
echo '{"incidents": [{"id": "INC-20260107-TEST03", "severity": "S3", "status": "active", "created_at": "2026-01-07T00:00:00Z", "summary": "Minor XSS fix needed"}]}' > .claude/state/active-incidents.json

python backend_py/guardian_bootstrap.py
cat .claude/telemetry/health_latest.json | grep routing_hint
# Should show "normal", NOT "security"

# Test: XSS with S1 severity SHOULD trigger
echo '{"incidents": [{"id": "INC-20260107-TEST04", "severity": "S1", "status": "active", "created_at": "2026-01-07T00:00:00Z", "summary": "Critical XSS vulnerability"}]}' > .claude/state/active-incidents.json

python backend_py/guardian_bootstrap.py
cat .claude/telemetry/health_latest.json | grep routing_hint
# Should show "security" (because S1 + medium-risk keyword)

# Restore
git checkout .claude/state/active-incidents.json
```

**Pass if**: Medium-risk keywords only trigger security override when severity >= S1

---

## Summary Table

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Git clean | `git status --porcelain` | Empty or warning shown |
| 2 | Schemas valid | `jsonschema.Draft7Validator.check_schema()` | All pass |
| 3 | Exit codes | `echo $?` after bootstrap | 0/1/2 correct |
| 4 | Security override | Check `routing_hint` | "security" when keywords match |
| 5 | Stop-the-line | Check `00-current-state.md` | Banner at top for S0/S1 |
| 6 | Offline mode | Bootstrap without API | Completes, shows "unreachable" |
| 7 | State unchanged | `git diff .claude/state/` | Empty |
| 8 | Audit trail | `cat health_latest.json` | All fields present |
| 9 | Severity S0-S3 | Check schema + GUARDIAN.md | S0-S3 everywhere |
| 10 | Keywords scoped | Test XSS+S3 vs XSS+S1 | Scoped correctly |

---

## Automation Script

```bash
#!/bin/bash
# guardian_acceptance_test.sh

set -e
echo "=== Guardian Acceptance Gate ==="

echo "[1/10] Git status..."
if [ -z "$(git status --porcelain .claude/state/)" ]; then
    echo "PASS: State files clean"
else
    echo "WARN: State files have changes (expected if testing)"
fi

echo "[2/10] Schema validation..."
python -c "
import json, jsonschema
from pathlib import Path
for f in Path('.claude/schemas').glob('*.json'):
    with open(f) as fp: schema = json.load(fp)
    jsonschema.Draft7Validator.check_schema(schema)
print('PASS: All schemas valid')
"

echo "[3/10] Bootstrap exit code..."
python backend_py/guardian_bootstrap.py > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "PASS: Exit 0 (healthy)"
else
    echo "INFO: Exit $? (check if expected)"
fi

echo "[4-10] Manual checks required - see guardian-acceptance.md"

echo "=== DONE ==="
```

---

*Last Updated: 2026-01-07*
*Run this before any audit, proof, or determinism work.*
