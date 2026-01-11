# Solver Engine Precedence (ADR-003)

## Overview

SOLVEREIGN supports two solver engines:

| Engine | Description | Status | Result |
|--------|-------------|--------|--------|
| **V3** | BlockHeuristicSolver (Min-Cost Max-Flow) | **PRODUCTION** | 145 FTE, 0 PT |
| **V4** | FeasibilityPipeline (Lexicographic) | EXPERIMENTAL | May timeout/produce PT |

**V3 is ALWAYS the default.** V4 must be explicitly opted-in.

---

## Precedence Rules

The solver engine is determined using this priority order (highest to lowest):

| Priority | Source | How to Set | Use Case |
|----------|--------|------------|----------|
| 1 | **Explicit Override** | `solver_engine` parameter in API call | Testing, one-off R&D |
| 2 | **Policy Profile** | `solver_engine: "v4"` in tenant policy config | Tenant-specific R&D |
| 3 | **Environment Variable** | `SOLVER_ENGINE=v4` | Local dev only |
| 4 | **Default** | Hardcoded `"v3"` | Production (non-negotiable) |

### Decision Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Solver Engine Selection                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Is explicit_override provided?                               │
│     └─ Yes → Use override (reason="explicit_override")           │
│     └─ No  → Continue                                            │
│                                                                  │
│  2. Does policy profile have solver_engine?                      │
│     └─ Yes → Use policy setting (reason="policy")                │
│     └─ No  → Continue                                            │
│                                                                  │
│  3. Is SOLVER_ENGINE env var set?                                │
│     └─ Yes → Use env var (reason="env")                          │
│     └─ No  → Continue                                            │
│                                                                  │
│  4. Default: V3 (reason="default")                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Logging

Every solve logs which engine was selected and why:

```
[SOLVER] solver_engine_selected=v3 reason=default
[SOLVER] solver_engine_selected=v3 reason=policy
[SOLVER] solver_engine_selected=v4 reason=explicit_override
```

The reason is also included in the solve result:

```json
{
  "solver_engine": "v3",
  "solver_engine_reason": "default",
  "solver_engine_publishable": true
}
```

---

## Configuration Locations

### 1. Environment Variable (v3/config.py)

```python
# Default: v3 (NEVER change in production)
SOLVER_ENGINE: Literal["v3", "v4"] = os.getenv("SOLVER_ENGINE", "v3")

# V4 publish control
ALLOW_V4_PUBLISH: bool = os.getenv("ALLOW_V4_PUBLISH", "false").lower() == "true"
V4_PUBLISH_KILL_SWITCH: bool = os.getenv("V4_PUBLISH_KILL_SWITCH", "false").lower() == "true"
```

### 2. Policy Profile (packs/roster/config_schema.py)

```python
class RosterPolicyConfig(BaseModel):
    solver_engine: SolverEngine = Field(
        SolverEngine.V3,  # Default: "v3"
        description="Solver engine: 'v3' (production) or 'v4' (R&D only)"
    )
```

### 3. API Parameter (v3/solver_wrapper.py)

```python
def solve_forecast(
    ...,
    solver_engine: Optional[str] = None,  # Override: "v3" or "v4"
):
```

---

## V4 Publish Gate

V4 solver output **cannot be published** unless explicitly allowed:

| Config | V4 Publishable? | Use Case |
|--------|-----------------|----------|
| `ALLOW_V4_PUBLISH=false` (default) | **NO** | Production |
| `ALLOW_V4_PUBLISH=true` | Yes (with warning log) | R&D testing |
| `V4_PUBLISH_KILL_SWITCH=true` | **NO** (overrides ALLOW) | Emergency |

When V4 publish is blocked, the API returns:

```json
{
  "error_code": "V4_PUBLISH_NOT_ALLOWED",
  "message": "V4 solver output cannot be published...",
  "action_required": "Re-solve using V3 solver (default) before publishing"
}
```

---

## Best Practices

### Production/Pilot Deployment

1. **Never set `SOLVER_ENGINE=v4` in production**
2. **Never set `solver_engine: v4` in production policy profiles**
3. **Keep `ALLOW_V4_PUBLISH=false`** (default)
4. **Run regression test** before every release: `python tests/test_v3_solver_regression.py`

### Local Development

```bash
# Run V3 (default)
python tests/test_v3_solver_regression.py

# Test V4 (explicit)
SOLVER_ENGINE=v4 python -c "from v3.config import config; print(config.SOLVER_ENGINE)"
```

### CI/CD

The `v3-solver-regression` gate in `pr-guardian.yml`:
- Runs on every PR
- Validates 145 FTE / 0 PT / 100% coverage
- Uploads evidence artifact
- **Blocks merge if regression detected**

---

## Audit Trail

Every solve records:

| Field | Example | Purpose |
|-------|---------|---------|
| `solver_engine` | `"v3"` | Which engine ran |
| `solver_engine_reason` | `"default"` | Why it was selected |
| `solver_engine_publishable` | `true` | Can output be published? |

Evidence files include:

```json
{
  "solver_engine": "v3",
  "result": {
    "fte_count": 145,
    "pt_count": 0,
    "coverage_percent": 100.0
  }
}
```

---

## Related Documents

- [CLAUDE.md](../CLAUDE.md) - Main project context
- [v3/config.py](../backend_py/v3/config.py) - Environment config
- [packs/roster/config_schema.py](../backend_py/packs/roster/config_schema.py) - Policy schema
- [tests/test_v3_solver_regression.py](../backend_py/tests/test_v3_solver_regression.py) - Regression test
