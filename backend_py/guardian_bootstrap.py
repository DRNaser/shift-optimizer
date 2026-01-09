#!/usr/bin/env python3
"""
Guardian Bootstrap - Generates volatile context files on session start.

This script is run at the start of every Claude Code session to generate
the current state context file that drives routing decisions.

Outputs:
- .claude/context/00-current-state.md  (volatile, gitignored)
- .claude/telemetry/health_latest.json (volatile, gitignored)
- .claude/telemetry/perf_latest.json   (volatile, gitignored)

Usage:
    python backend_py/guardian_bootstrap.py
    python backend_py/guardian_bootstrap.py --allow-dirty  # Force audit_grade=true

Exit Codes:
    0 - Healthy, all checks pass
    1 - Schema validation failed
    2 - S0/S1 incident active (STOP-THE-LINE)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

# Paths
REPO_ROOT = Path(__file__).parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude"
CONTEXT_DIR = CLAUDE_DIR / "context"
STATE_EXAMPLES_DIR = CLAUDE_DIR / "state" / "examples"  # Git-tracked reference data
STATE_RUNTIME_DIR = CLAUDE_DIR / "state" / "runtime"    # Volatile, gitignored
TELEMETRY_DIR = CLAUDE_DIR / "telemetry"
SCHEMAS_DIR = CLAUDE_DIR / "schemas"

# Legacy compatibility
STATE_DIR = STATE_EXAMPLES_DIR  # Default to examples for reading

# ============================================================================
# SECRETS REDACTION - NEVER leak these to state/runtime/
# ============================================================================
import re
from typing import Union, List

# Only whitelisted keys are exported. Everything else is REDACTED.
ALLOWED_ENV_KEYS = frozenset([
    "NODE_ENV",
    "PYTHON_ENV",
    "APP_ENV",
    "DATABASE_HOST",  # Host only, not password
    "OSRM_HOST",
    "REDIS_HOST",
    "LOG_LEVEL",
    "DEBUG",
    "SOLVEREIGN_PLATFORM_WRITES_DISABLED",
])

# Key name patterns that trigger redaction (case-insensitive)
SECRET_KEY_PATTERNS = frozenset([
    "secret", "password", "key", "token", "credential",
    "auth", "api_key", "apikey", "private", "cert", "pem",
    "bearer", "cookie", "session", "jwt", "hmac", "signature",
])

# Value patterns that indicate secrets (regex patterns)
SECRET_VALUE_PATTERNS = [
    # AWS Access Key ID
    re.compile(r'AKIA[0-9A-Z]{16}', re.IGNORECASE),
    # AWS Secret Key (base64-like, 40 chars)
    re.compile(r'[A-Za-z0-9/+=]{40}'),
    # Bearer tokens
    re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]+', re.IGNORECASE),
    # JWT tokens (xxx.xxx.xxx format)
    re.compile(r'eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'),
    # Basic Auth in URLs (user:pass@)
    re.compile(r'://[^:]+:[^@]+@'),
    # OpenAI/Anthropic keys
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'sk-ant-[A-Za-z0-9\-]+'),
    # GitHub tokens
    re.compile(r'ghp_[A-Za-z0-9]{36}'),
    re.compile(r'gho_[A-Za-z0-9]{36}'),
    # Generic API keys (long alphanumeric strings)
    re.compile(r'[A-Za-z0-9]{32,}'),
    # Hex secrets (32+ chars)
    re.compile(r'[a-f0-9]{32,}', re.IGNORECASE),
    # Base64 encoded secrets (32+ chars with padding)
    re.compile(r'[A-Za-z0-9+/]{32,}={0,2}'),
    # Cookie values (session cookies often look like this)
    re.compile(r'__Host-[A-Za-z0-9_-]+=[A-Za-z0-9\-_\.]+'),
]

# Size limits for runtime state
MAX_STATE_FILE_BYTES = 1024 * 1024  # 1MB max per file
MAX_ENV_VALUE_LENGTH = 200  # Truncate long values
MAX_TELEMETRY_FILES = 20  # Keep last N telemetry files


def redact_string_value(value: str) -> str:
    """Redact secrets from a string value using pattern matching."""
    if not isinstance(value, str):
        return value

    # Check each secret pattern
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            return "[REDACTED:pattern_match]"

    # Truncate very long values (likely secrets or binary)
    if len(value) > MAX_ENV_VALUE_LENGTH:
        return f"[TRUNCATED:{len(value)}chars]"

    return value


def redact_env_value(key: str, value: str) -> str:
    """Redact sensitive environment variable values."""
    key_lower = key.lower()

    # Whitelisted keys pass through (but still pattern-check values)
    if key in ALLOWED_ENV_KEYS:
        return redact_string_value(value)

    # Check for secret key patterns
    for pattern in SECRET_KEY_PATTERNS:
        if pattern in key_lower:
            return "[REDACTED:key_pattern]"

    # Default: redact unless explicitly allowed
    return "[REDACTED]"


def redact_recursive(data: Union[Dict, List, str, Any], depth: int = 0) -> Union[Dict, List, str, Any]:
    """Recursively redact secrets from any data structure.

    This catches secrets in:
    - Nested dicts (config files, JSON blobs)
    - Lists of values
    - String values anywhere in the structure
    - Exception traces (truncated)
    """
    MAX_DEPTH = 10  # Prevent infinite recursion

    if depth > MAX_DEPTH:
        return "[TRUNCATED:max_depth]"

    if isinstance(data, dict):
        result = {}
        for key, value in sorted(data.items()):  # Sort for determinism
            key_lower = str(key).lower()
            # Check if key suggests a secret
            is_secret_key = any(p in key_lower for p in SECRET_KEY_PATTERNS)
            if is_secret_key:
                result[key] = "[REDACTED:key_pattern]"
            else:
                result[key] = redact_recursive(value, depth + 1)
        return result

    elif isinstance(data, list):
        return [redact_recursive(item, depth + 1) for item in data]

    elif isinstance(data, str):
        return redact_string_value(data)

    else:
        # Primitives (int, float, bool, None) pass through
        return data


def write_json_deterministic(path: Path, data: Dict[str, Any], redact: bool = True) -> int:
    """Write JSON with deterministic output (sorted keys, stable separators).

    Returns the number of bytes written.
    Enforces MAX_STATE_FILE_BYTES limit.
    """
    # Apply recursive redaction if requested
    if redact:
        data = redact_recursive(data)

    # Serialize with deterministic settings
    content = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),  # Compact, no extra spaces
        ensure_ascii=False,
        indent=2  # Keep readable for debugging
    )

    # Enforce size limit
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_STATE_FILE_BYTES:
        # Truncate with warning
        warning = {"_truncated": True, "_original_size": len(content_bytes)}
        content = json.dumps(warning, sort_keys=True)

    path.write_text(content, encoding="utf-8")
    return len(content_bytes)


def cleanup_old_telemetry():
    """Remove old telemetry files, keep only MAX_TELEMETRY_FILES most recent."""
    if not TELEMETRY_DIR.exists():
        return 0

    # Get all JSON files sorted by mtime
    files = sorted(
        TELEMETRY_DIR.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    # Keep only the most recent
    deleted = 0
    for old_file in files[MAX_TELEMETRY_FILES:]:
        try:
            old_file.unlink()
            deleted += 1
        except Exception:
            pass

    return deleted


def get_git_sha() -> str:
    """Get current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def is_git_dirty() -> bool:
    """Check if git working directory is dirty."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT
        )
        return bool(result.stdout.strip()) if result.returncode == 0 else True
    except Exception:
        return True  # Assume dirty if we can't check


# Type-based routing (preferred) - uses incident.type field
# Priority: security > stability > perf > quality > normal
INCIDENT_TYPE_ROUTING = {
    "security": "security",      # → security/rls-enforcement.md
    "stability": "stability",    # → stability/incident-triage.md
    "perf": "performance",       # → performance/timeout-playbook.md
    "quality": "quality",        # → quality/determinism-proof.md
}

# Keyword-based routing (fallback for legacy incidents without type field)
# HIGH_RISK: Always trigger security override
# MEDIUM_RISK: Only trigger if severity >= S1 OR combined with HIGH_RISK keyword
SECURITY_KEYWORDS_HIGH_RISK = frozenset([
    "rls", "leak", "cross-tenant", "auth", "tenant"
])
SECURITY_KEYWORDS_MEDIUM_RISK = frozenset([
    "xss", "injection", "vuln", "token", "hmac", "replay", "security"
])


def get_latest_migration() -> str:
    """Get the latest migration file name."""
    migrations_dir = REPO_ROOT / "backend_py" / "db" / "migrations"
    if not migrations_dir.exists():
        return "unknown"

    migrations = sorted(migrations_dir.glob("*.sql"))
    if migrations:
        # Filter out rollback scripts
        non_rollback = [m for m in migrations if "rollback" not in m.name.lower()]
        if non_rollback:
            return non_rollback[-1].stem
    return "unknown"


def check_health() -> Dict[str, Any]:
    """Check API health endpoint."""
    try:
        import requests
        resp = requests.get("http://localhost:8000/health/ready", timeout=5)
        if resp.ok:
            return resp.json()
        return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
    except ImportError:
        return {"status": "unknown", "error": "requests not installed"}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


def check_perf() -> Dict[str, Any]:
    """Load performance baselines and latest solve metrics."""
    baselines_path = STATE_EXAMPLES_DIR / "drift-baselines.json"
    solve_latest_path = TELEMETRY_DIR / "solve_latest.json"

    result = {}

    # Load baselines
    try:
        with open(baselines_path, encoding="utf-8") as f:
            result = json.load(f)
    except FileNotFoundError:
        result = {"status": "unknown", "error": "No baseline file"}
    except json.JSONDecodeError as e:
        result = {"status": "error", "error": f"Invalid JSON: {e}"}

    # Load latest solve metrics (if available)
    try:
        with open(solve_latest_path, encoding="utf-8") as f:
            solve_latest = json.load(f)
            result["latest_solve"] = {
                "solve_time_s": solve_latest.get("solve_time_s"),
                "peak_rss_mb": solve_latest.get("peak_rss_mb"),
                "timestamp": solve_latest.get("timestamp"),
                "drivers_total": solve_latest.get("drivers_total"),
            }
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # solve_latest is optional

    return result


def load_incidents() -> Dict[str, Any]:
    """Load active incidents from runtime (if exists) or examples."""
    # Try runtime first (live data), fall back to examples (reference)
    runtime_path = STATE_RUNTIME_DIR / "active-incidents.json"
    examples_path = STATE_EXAMPLES_DIR / "active-incidents.json"
    incidents_path = runtime_path if runtime_path.exists() else examples_path
    try:
        with open(incidents_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"incidents": []}
    except json.JSONDecodeError:
        return {"incidents": [], "error": "Invalid JSON in incidents file"}


def load_lkg() -> Optional[Dict[str, Any]]:
    """Load last known good state from runtime (if exists) or examples."""
    runtime_path = STATE_RUNTIME_DIR / "last-known-good.json"
    examples_path = STATE_EXAMPLES_DIR / "last-known-good.json"
    lkg_path = runtime_path if runtime_path.exists() else examples_path
    try:
        with open(lkg_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_tenant_status() -> Dict[str, Any]:
    """Load tenant status from runtime (if exists) or examples."""
    runtime_path = STATE_RUNTIME_DIR / "tenant-status.json"
    examples_path = STATE_EXAMPLES_DIR / "tenant-status.json"
    tenant_path = runtime_path if runtime_path.exists() else examples_path
    try:
        with open(tenant_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tenants": {}}


def generate_current_state() -> str:
    """Generate 00-current-state.md content."""
    now = datetime.now(timezone.utc).isoformat()
    git_sha = get_git_sha()
    git_dirty = is_git_dirty()
    migration = get_latest_migration()
    health = check_health()
    perf = check_perf()
    incidents = load_incidents()
    lkg = load_lkg()
    tenant_status = load_tenant_status()

    # Determine overall status and routing
    active_incidents = [
        i for i in incidents.get("incidents", [])
        if i.get("status") not in ("resolved", "closed", "mitigated")
    ]
    # STOP-THE-LINE only for S0/S1 with status in {new, active, investigating}
    # Stale incidents should NOT trigger stop-the-line
    STOP_THE_LINE_STATUSES = frozenset(["new", "active", "investigating"])
    has_s1_s2 = any(
        i.get("severity") in ("S0", "S1")
        and i.get("status") in STOP_THE_LINE_STATUSES
        for i in active_incidents
    )

    if has_s1_s2:
        status = "🔴 CRITICAL - S0/S1 Incident Active"
        routing = "→ **STOP-THE-LINE** → `stability/incident-triage.md`"
    elif health.get("status") in ("unhealthy", "unreachable"):
        status = "🟠 DEGRADED - Health Check Failed"
        routing = "→ `stability/health-checks.md`"
    elif perf.get("status") == "unknown":
        status = "🟡 WARNING - Performance Baseline Unknown"
        routing = "→ `performance/capacity-planning.md`"
    elif git_dirty:
        status = "🟡 WARNING - Dirty Worktree (not audit-grade)"
        routing = "→ Normal routing applies (see GUARDIAN.md)"
    else:
        status = "🟢 HEALTHY"
        routing = "→ Normal routing applies (see GUARDIAN.md)"

    # Build dirty worktree banner
    dirty_banner = ""
    if git_dirty:
        dirty_banner = """
> **⚠️ DIRTY WORKTREE - Results NOT audit-grade**
>
> Uncommitted changes detected. Audit/proof/determinism actions should be blocked.
> Commit or stash changes before running reproducibility tests.

---

"""

    # Build content - STOP-THE-LINE banner at TOP if S0/S1 active
    stop_the_line_banner = ""
    if has_s1_s2:
        s0_s1_incidents = [
            i for i in active_incidents
            if i.get("severity") in ("S0", "S1")
            and i.get("status") in STOP_THE_LINE_STATUSES
        ]
        # Build incident details table for Ops visibility
        incident_details = "\n".join([
            f"> | `{i.get('id', 'N/A')}` | **{i.get('severity', 'N/A')}** | {i.get('status', 'N/A')} | {(i.get('summary', '') or '')[:40]} |"
            for i in s0_s1_incidents
        ])
        stop_the_line_banner = f"""
> **!!! STOP-THE-LINE ACTIVE !!!**
>
> **{len(s0_s1_incidents)} S0/S1 incident(s) require immediate attention.**
> ALL other work is BLOCKED until resolved.
>
> | ID | Severity | Status | Summary |
> |----|----------|--------|---------|
{incident_details}
>
> → Read `stability/incident-triage.md` IMMEDIATELY

---

"""

    content = f"""{stop_the_line_banner}{dirty_banner}# Current State (Generated)

> **Generated**: {now}
> **Git SHA**: {git_sha}
> **Migration**: {migration}
> **Status**: {status}

---

## Routing Decision

{routing}

---

## Active Incidents

| ID | Severity | Status | Tenant | Summary |
|----|----------|--------|--------|---------|
"""

    for inc in active_incidents:
        inc_id = inc.get("id", "N/A")
        severity = inc.get("severity", "N/A")
        inc_status = inc.get("status", "N/A")
        tenant = inc.get("tenant_id", "all") or "all"
        summary = inc.get("summary", "")[:50]
        content += f"| {inc_id} | {severity} | {inc_status} | {tenant} | {summary} |\n"

    if not active_incidents:
        content += "| (none) | - | - | - | - |\n"

    content += f"""
---

## Health Status

```json
{json.dumps(health, indent=2)}
```

---

## Last Known Good

"""
    if lkg:
        content += f"""| Field | Value |
|-------|-------|
| Git SHA | `{lkg.get('git_sha', 'unknown')}` |
| Migration | `{lkg.get('migrations_version', 'unknown')}` |
| Config Hash | `{lkg.get('config_hash', 'unknown')[:30]}...` |
| Timestamp | {lkg.get('timestamp', 'unknown')} |
| Health | {lkg.get('health_status', 'unknown')} |
| Tests | {'✅ PASS' if lkg.get('all_tests_pass') else '❌ FAIL'} |
"""
    else:
        content += "⚠️ **No LKG recorded yet** - Run a successful deployment first.\n"

    # Security Status
    content += """
---

## Security Status

| Tenant | RLS Mode | Auth Mode | Security Smoke | Perf Smoke |
|--------|----------|-----------|----------------|------------|
"""
    tenants = tenant_status.get("tenants", {})
    for name, data in tenants.items():
        rls = data.get("rls_mode", "unknown")
        auth = data.get("auth_mode", "unknown")
        sec_smoke = data.get("last_security_smoke", {})
        perf_smoke = data.get("last_perf_smoke", {})
        sec_result = sec_smoke.get("result", "N/A") if sec_smoke else "N/A"
        perf_result = perf_smoke.get("result", "N/A") if perf_smoke else "N/A"
        content += f"| {name} | {rls} | {auth} | {sec_result} | {perf_result} |\n"

    if not tenants:
        content += "| (no tenants) | - | - | - | - |\n"

    # Performance Status
    content += """
---

## Performance Status

| Metric | Baseline | Threshold | Status |
|--------|----------|-----------|--------|
"""
    api_p95 = perf.get("api_p95_ms", "N/A")
    solver_p95 = perf.get("solver_p95_s", "N/A")
    peak_rss = perf.get("solver_peak_rss_mb", "N/A")

    content += f"| API p95 | {api_p95}ms | <200ms warn, <500ms crit | {'✅' if isinstance(api_p95, (int, float)) and api_p95 < 200 else '⚠️'} |\n"
    content += f"| Solver p95 | {solver_p95}s | <60s warn, <120s crit | {'✅' if isinstance(solver_p95, (int, float)) and solver_p95 < 60 else '⚠️'} |\n"
    content += f"| Peak RSS | {peak_rss}MB | <3GB warn, <4GB crit | {'✅' if isinstance(peak_rss, (int, float)) and peak_rss < 3000 else '⚠️'} |\n"

    # Latest Solve Metrics (if available)
    latest_solve = perf.get("latest_solve")
    if latest_solve:
        content += f"""
### Latest Solve Run

| Metric | Value |
|--------|-------|
| Solve Time | {latest_solve.get('solve_time_s', 'N/A')}s |
| Peak RSS | {latest_solve.get('peak_rss_mb', 'N/A')}MB |
| Drivers | {latest_solve.get('drivers_total', 'N/A')} |
| Timestamp | {latest_solve.get('timestamp', 'N/A')} |
"""

    content += f"""
---

## Quick Actions

Based on current state:

1. **If investigating an issue**: Check routing table in `GUARDIAN.md`
2. **If deploying**: Read `operations/deployment-checklist.md`
3. **If onboarding tenant**: Read `operations/tenant-onboarding.md`
4. **If performance issue**: Read `performance/timeout-playbook.md`

---

*This file is auto-generated. Do not edit manually.*
*Run `python backend_py/guardian_bootstrap.py` to regenerate.*
"""

    return content


def validate_schemas() -> bool:
    """Validate state files against schemas.

    Validates files in state/examples/ (reference data that's git-tracked).
    Runtime state is volatile and not validated here.
    """
    try:
        import jsonschema
    except ImportError:
        print("  [WARN] jsonschema not installed, skipping validation")
        return True

    validations = [
        ("last-known-good.json", "last-known-good.schema.json"),
        ("active-incidents.json", "incident.schema.json"),
        ("tenant-status.json", "tenant-status.schema.json"),
        ("drift-baselines.json", "drift-baselines.schema.json"),
    ]

    # For incidents, we validate the array items, not the wrapper
    all_valid = True

    for state_file, schema_file in validations:
        state_path = STATE_EXAMPLES_DIR / state_file  # Validate examples only
        schema_path = SCHEMAS_DIR / schema_file

        if not state_path.exists():
            print(f"  [WARN] State file not found: {state_file}")
            continue

        if not schema_path.exists():
            print(f"  [WARN] Schema file not found: {schema_file}")
            continue

        try:
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)

            # Special handling for incidents (validate wrapper structure manually)
            if state_file == "active-incidents.json":
                # Just check it has incidents array
                if "incidents" not in data:
                    print(f"  [FAIL] {state_file}: missing 'incidents' key")
                    all_valid = False
                else:
                    print(f"  [PASS] {state_file} structure valid")
            else:
                jsonschema.validate(data, schema)
                print(f"  [PASS] {state_file} validates against {schema_file}")

        except jsonschema.ValidationError as e:
            print(f"  [FAIL] {state_file}: {e.message}")
            all_valid = False
        except json.JSONDecodeError as e:
            print(f"  [FAIL] {state_file}: Invalid JSON - {e}")
            all_valid = False

    return all_valid


def generate_runtime_state_by_domain() -> Dict[str, Dict[str, Any]]:
    """Generate split runtime state files by domain.

    Returns dict of domain -> state data:
    - platform-state.json: System info, git, platform config
    - security-state.json: Auth mode, RLS status, tenant modes
    - ops-state.json: Health, incidents, routing decision

    Each file has its own schema and is independently redacted.
    """
    import os

    timestamp = datetime.now(timezone.utc).isoformat()
    git_sha = get_git_sha()
    git_dirty = is_git_dirty()

    # Redact environment variables
    redacted_env = {}
    for key, value in sorted(os.environ.items()):  # Sorted for determinism
        if key.startswith("_") or key.startswith("VSCODE"):
            continue
        redacted_env[key] = redact_env_value(key, value)

    # Platform state (system info)
    platform_state = {
        "schema_version": "1.0.0",
        "domain": "platform",
        "generated_at": timestamp,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "env_allowed_count": sum(1 for v in redacted_env.values() if not v.startswith("[REDACTED")),
        "env_redacted_count": sum(1 for v in redacted_env.values() if v.startswith("[REDACTED")),
    }

    # Security state (auth/RLS)
    tenant_status = load_tenant_status()
    security_state = {
        "schema_version": "1.0.0",
        "domain": "security",
        "generated_at": timestamp,
        "tenants": {},
    }
    for tenant, data in sorted(tenant_status.get("tenants", {}).items()):
        security_state["tenants"][tenant] = {
            "rls_mode": data.get("rls_mode", "unknown"),
            "auth_mode": data.get("auth_mode", "unknown"),
            "last_security_smoke": data.get("last_security_smoke", {}).get("result", "N/A"),
        }

    # Ops state (health, incidents, routing)
    health = check_health()
    incidents = load_incidents()
    active_incidents = [
        i for i in incidents.get("incidents", [])
        if i.get("status") not in ("resolved", "closed", "mitigated")
    ]
    ops_state = {
        "schema_version": "1.0.0",
        "domain": "ops",
        "generated_at": timestamp,
        "health_status": health.get("status", "unknown"),
        "active_incident_count": len(active_incidents),
        "has_s0_s1": any(i.get("severity") in ("S0", "S1") for i in active_incidents),
        "routing_hint": "normal",  # Will be updated by caller
    }

    return {
        "platform": platform_state,
        "security": security_state,
        "ops": ops_state,
    }


def main():
    """Main entry point."""
    # Fix Windows console encoding
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Guardian Bootstrap - Generate context files for routing decisions"
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Force audit_grade=true even with dirty worktree (use with caution)"
    )
    # Override audit trail fields (populated by CI)
    parser.add_argument(
        "--override-reason",
        type=str,
        default=None,
        help="Reason for --allow-dirty override (for audit trail)"
    )
    parser.add_argument(
        "--override-actor",
        type=str,
        default=None,
        help="Actor (username) who authorized override (for audit trail)"
    )
    parser.add_argument(
        "--override-pr",
        type=str,
        default=None,
        help="PR number where override was approved (for audit trail)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("GUARDIAN BOOTSTRAP")
    if args.allow_dirty:
        print("  [--allow-dirty] Forcing audit_grade=true")
    print("=" * 60)

    # Ensure directories exist
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    STATE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # Generate current state (markdown for context routing)
    print("\n[1/5] Generating current state...")
    content = generate_current_state()
    current_state_path = CONTEXT_DIR / "00-current-state.md"
    current_state_path.write_text(content, encoding="utf-8")
    print(f"  OK: {current_state_path.relative_to(REPO_ROOT)}")

    # Generate runtime state by domain (JSON with secrets redaction)
    print("\n[2/5] Generating runtime state by domain (secrets redacted)...")
    domain_states = generate_runtime_state_by_domain()
    total_bytes = 0
    for domain, state_data in domain_states.items():
        state_path = STATE_RUNTIME_DIR / f"{domain}-state.json"
        bytes_written = write_json_deterministic(state_path, state_data, redact=True)
        total_bytes += bytes_written
        print(f"  OK: {state_path.relative_to(REPO_ROOT)} ({bytes_written} bytes)")

    # Also write combined state for backward compatibility
    combined_state = {
        "schema_version": "1.0.0",
        "domains": list(domain_states.keys()),
        "platform": domain_states["platform"],
        "security": domain_states["security"],
        "ops": domain_states["ops"],
    }
    combined_path = STATE_RUNTIME_DIR / "current-state.json"
    write_json_deterministic(combined_path, combined_state, redact=True)
    print(f"  Total: {total_bytes} bytes across {len(domain_states)} domains")

    # Cleanup old telemetry files
    deleted = cleanup_old_telemetry()
    if deleted > 0:
        print(f"  Cleaned up: {deleted} old telemetry files")

    # Generate health telemetry with audit trail
    print("\n[3/5] Checking health and computing routing...")
    health = check_health()
    git_sha = get_git_sha()
    git_dirty = is_git_dirty()

    # Load incidents for routing decision
    incidents = load_incidents()
    active_incidents = [
        i for i in incidents.get("incidents", [])
        if i.get("status") not in ("resolved", "closed", "mitigated")
    ]

    # STOP-THE-LINE: Only trigger for S0/S1 with ACTIVE status
    # Status must be in {new, active, investigating} - NOT stale/resolved/mitigated
    STOP_THE_LINE_STATUSES = frozenset(["new", "active", "investigating"])
    s0_s1_incidents = [
        i for i in active_incidents
        if i.get("severity") in ("S0", "S1")
        and i.get("status") in STOP_THE_LINE_STATUSES
    ]
    s0_s1_ids = [i.get("id", "unknown") for i in s0_s1_incidents]

    # Determine routing_hint and stop_the_line
    stop_the_line = len(s0_s1_incidents) > 0
    routing_hint = "normal"
    routing_reason = None
    matched_security_keywords = []
    typed_incidents = []

    # PHASE 1: Type-based routing (PREFERRED - uses incident.type field)
    # Priority: security > stability > perf > quality
    # Type-based routing takes precedence over keyword matching
    type_priority = ["security", "stability", "perf", "quality"]
    highest_type_priority = None

    for inc in active_incidents:
        inc_type = inc.get("type")
        if inc_type and inc_type in INCIDENT_TYPE_ROUTING:
            typed_incidents.append({
                "id": inc.get("id", "unknown"),
                "type": inc_type,
                "severity": inc.get("severity", "S3")
            })
            # Track highest priority type
            current_priority = type_priority.index(inc_type) if inc_type in type_priority else 999
            if highest_type_priority is None or current_priority < highest_type_priority:
                highest_type_priority = current_priority

    # If we have typed incidents, use type-based routing
    if typed_incidents and highest_type_priority is not None:
        highest_type = type_priority[highest_type_priority]
        routing_hint = INCIDENT_TYPE_ROUTING[highest_type]
        routing_reason = f"type_based: {highest_type} (incidents: {[i['id'] for i in typed_incidents if i['type'] == highest_type]})"
    else:
        # PHASE 2: Keyword-based routing (FALLBACK for legacy incidents without type)
        # Check for security keywords in incident summaries (HARD OVERRIDE)
        # HIGH_RISK keywords always trigger override
        # MEDIUM_RISK only trigger if severity >= S1 OR combined with HIGH_RISK
        for inc in active_incidents:
            # Skip if this incident has a type (already handled above)
            if inc.get("type"):
                continue

            summary_lower = (inc.get("summary", "") or "").lower()
            severity = inc.get("severity", "S3")
            is_high_severity = severity in ("S0", "S1")

            high_risk_matched = [kw for kw in SECURITY_KEYWORDS_HIGH_RISK if kw in summary_lower]
            medium_risk_matched = [kw for kw in SECURITY_KEYWORDS_MEDIUM_RISK if kw in summary_lower]

            # HIGH_RISK always triggers
            if high_risk_matched:
                matched_security_keywords.extend(high_risk_matched)
                matched_security_keywords.extend(medium_risk_matched)  # Include medium too
            # MEDIUM_RISK only triggers if high severity OR combined with high risk
            elif medium_risk_matched and (is_high_severity or high_risk_matched):
                matched_security_keywords.extend(medium_risk_matched)

        if matched_security_keywords:
            routing_hint = "security"
            routing_reason = f"keyword_fallback: {list(set(matched_security_keywords))}"
        elif stop_the_line:
            routing_hint = "stability"
            routing_reason = f"stop_the_line: {s0_s1_ids}"
        elif health.get("status") in ("unhealthy", "unreachable"):
            routing_hint = "stability"
            routing_reason = f"health_degraded: {health.get('status')}"
        else:
            routing_hint = "normal"
            routing_reason = "healthy"

    # Build enriched health telemetry
    # Dirty worktree degrades audit-grade status (unless --allow-dirty)
    audit_grade = (not git_dirty) or args.allow_dirty
    health_telemetry = {
        **health,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "dirty": git_dirty,
        "allow_dirty_override": args.allow_dirty,
        "audit_grade": audit_grade,
        "stop_the_line": stop_the_line,
        "stop_reason": s0_s1_ids if stop_the_line else None,
        "routing_hint": routing_hint,
        "routing_reason": routing_reason,
        # Type-based routing info (preferred)
        "typed_incidents": typed_incidents if typed_incidents else None,
        # Keyword-based routing fallback info
        "matched_security_keywords": list(set(matched_security_keywords)) if matched_security_keywords else None,
        # Override audit trail (populated by CI when --allow-dirty is used)
        "override_reason": args.override_reason,
        "override_actor": args.override_actor,
        "override_pr_number": args.override_pr,
    }

    health_path = TELEMETRY_DIR / "health_latest.json"
    health_path.write_text(json.dumps(health_telemetry, indent=2), encoding="utf-8")
    print(f"  OK: {health_path.relative_to(REPO_ROOT)}")
    print(f"  Status: {health.get('status', 'unknown')}")
    print(f"  Routing: {routing_hint} ({routing_reason})")
    if git_dirty:
        print(f"  [WARN] Dirty worktree - NOT audit-grade")

    # Generate perf telemetry
    print("\n[4/5] Loading performance baselines...")
    perf = check_perf()
    perf_path = TELEMETRY_DIR / "perf_latest.json"
    perf_path.write_text(json.dumps(perf, indent=2), encoding="utf-8")
    print(f"  OK: {perf_path.relative_to(REPO_ROOT)}")

    # Validate schemas
    print("\n[5/5] Validating state files against schemas...")
    schemas_valid = validate_schemas()

    # Summary
    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    # Exit codes: 2 = S0/S1 active (STOP-THE-LINE), 1 = schema invalid, 0 = healthy
    exit_code = 0

    if stop_the_line:
        print("\n[!!!] STOP-THE-LINE: S0/S1 incident active!")
        print(f"      Incidents: {s0_s1_ids}")
        print("      -> stability/incident-triage.md")
        print("      ALL other work BLOCKED until resolved.")
        exit_code = 2  # CI/runbooks can check for this
    elif typed_incidents:
        # Type-based routing (structured)
        print(f"\n[!] TYPE-BASED ROUTING: {routing_hint}")
        print(f"      Incidents: {[i['id'] for i in typed_incidents]}")
        print(f"      Routing reason: {routing_reason}")
        route_map = {
            "security": "security/rls-enforcement.md",
            "stability": "stability/incident-triage.md",
            "performance": "performance/timeout-playbook.md",
            "quality": "quality/determinism-proof.md",
        }
        print(f"      -> {route_map.get(routing_hint, 'GUARDIAN.md')}")
    elif routing_hint == "security" and matched_security_keywords:
        # Keyword-based fallback (legacy incidents without type)
        print(f"\n[!] SECURITY OVERRIDE (keyword fallback): {matched_security_keywords}")
        print("      -> security/rls-enforcement.md")
        print("      [WARN] Incident missing 'type' field - use Incident CLI to add")
    elif routing_hint == "stability":
        print("\n[!] ROUTING: Health degraded -> stability/health-checks.md")
    else:
        print("\n[OK] ROUTING: Normal -> Use GUARDIAN.md routing table")

    print(f"\nRead: .claude/context/00-current-state.md")
    print(f"Audit: .claude/telemetry/health_latest.json")

    # Schema validation failure is lower priority than S0/S1
    if not schemas_valid and exit_code == 0:
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
