# Determinism Proof

> **Purpose**: Verify solver reproducibility
> **Last Updated**: 2026-01-07

---

## CORE REQUIREMENT

**Same inputs + same seed = same output hash. ALWAYS.**

This is a release-blocking requirement. If determinism fails, the plan cannot be locked.

---

## DETERMINISM COMPONENTS

### 1. Input Hash

Computed from canonical representation of forecast:

```python
def compute_input_hash(forecast_version_id: int) -> str:
    """Compute SHA256 of canonical input representation."""
    tours = get_tours_normalized(forecast_version_id)

    # Canonical representation (sorted, consistent format)
    canonical = json.dumps(
        [asdict(t) for t in sorted(tours, key=lambda t: t.tour_fingerprint)],
        sort_keys=True,
        separators=(',', ':')
    )

    return hashlib.sha256(canonical.encode()).hexdigest()
```

### 2. Solver Config Hash

Computed from solver configuration:

```python
def compute_solver_config_hash(config: SolverConfig) -> str:
    """Compute SHA256 of solver configuration."""
    canonical = json.dumps({
        'seed': config.seed,
        'time_limit_seconds': config.time_limit_seconds,
        'solution_limit': config.solution_limit,
        'metaheuristic': config.metaheuristic,
        'version': config.version
    }, sort_keys=True, separators=(',', ':'))

    return hashlib.sha256(canonical.encode()).hexdigest()
```

### 3. Output Hash

Computed from solver assignments:

```python
def compute_output_hash(plan_version_id: int) -> str:
    """Compute SHA256 of canonical output representation."""
    assignments = get_assignments(plan_version_id)

    # Canonical representation
    canonical = json.dumps(
        [asdict(a) for a in sorted(assignments, key=lambda a: (a.driver_id, a.tour_instance_id))],
        sort_keys=True,
        separators=(',', ':')
    )

    return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## VERIFICATION PROCEDURE

### Pre-Release Verification

```bash
# Run determinism proof
python -m backend_py.v3.determinism_proof --forecast-id 1 --seed 94 --runs 3

# Expected output:
# Run 1: output_hash = abc123...
# Run 2: output_hash = abc123...
# Run 3: output_hash = abc123...
# DETERMINISM VERIFIED: All 3 runs produced identical output_hash
```

### Automated CI Check

```python
def test_determinism():
    """Verify solver produces identical output for same inputs."""
    forecast_id = 1
    seed = 94

    # Run solver 3 times
    results = []
    for i in range(3):
        result = solve_forecast(forecast_id, seed=seed)
        results.append(result['output_hash'])

    # All hashes must be identical
    assert len(set(results)) == 1, f"Determinism failed: {results}"
```

---

## COMMON DETERMINISM FAILURES

### 1. Random Seed Not Fixed

**Symptom**: Different output_hash each run

**Detection**:
```python
# Check if seed is being used
print(f"Solver seed: {solver_config.seed}")
```

**Fix**:
```python
# Always pass seed explicitly
solver.parameters.random_seed = seed
```

### 2. Floating Point Instability

**Symptom**: Slight variations in cost calculations

**Detection**:
```python
# Check for floating point in output
for assignment in assignments:
    if isinstance(assignment.cost, float):
        print(f"WARNING: Floating point cost: {assignment.cost}")
```

**Fix**:
```python
# Use Decimal or round consistently
from decimal import Decimal, ROUND_HALF_UP
cost = Decimal(str(cost)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

### 3. Dictionary/Set Ordering

**Symptom**: Order of assignments differs

**Detection**:
```python
# Check if using unordered collections
print(type(assignments))  # Should be list, not set
```

**Fix**:
```python
# Always sort before hashing
sorted_assignments = sorted(assignments, key=lambda a: (a.driver_id, a.tour_instance_id))
```

### 4. Timestamp in Output

**Symptom**: output_hash includes current timestamp

**Detection**:
```python
# Check canonical representation
print(canonical)  # Look for timestamps
```

**Fix**:
```python
# Exclude timestamps from hash computation
assignment_for_hash = {k: v for k, v in assignment.items() if k != 'created_at'}
```

### 5. External Service Drift (OSRM)

**Symptom**: Different results when OSRM data changes

**Detection**:
```python
# Check matrix source
print(f"Matrix source: {matrix.source}")  # Should be 'static' for determinism
```

**Fix**:
```python
# Lock matrix for reproducibility
matrix = load_static_matrix(scenario_id)  # Not OSRM
```

---

## DETERMINISM PROOF SCRIPT

```python
#!/usr/bin/env python3
"""Determinism proof generator."""

import hashlib
import json
from backend_py.v3.solver_wrapper import solve_forecast

def prove_determinism(forecast_id: int, seed: int, runs: int = 3) -> dict:
    """Run solver multiple times and verify identical output."""

    results = []

    for i in range(runs):
        result = solve_forecast(forecast_id, seed=seed, save_to_db=False)
        results.append({
            'run': i + 1,
            'input_hash': result['input_hash'],
            'output_hash': result['output_hash'],
            'solver_config_hash': result['solver_config_hash']
        })

    # Check all output_hashes are identical
    output_hashes = [r['output_hash'] for r in results]
    all_identical = len(set(output_hashes)) == 1

    return {
        'forecast_id': forecast_id,
        'seed': seed,
        'runs': runs,
        'results': results,
        'determinism_verified': all_identical,
        'unique_output_hashes': list(set(output_hashes))
    }

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--forecast-id', type=int, required=True)
    parser.add_argument('--seed', type=int, default=94)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()

    proof = prove_determinism(args.forecast_id, args.seed, args.runs)

    if proof['determinism_verified']:
        print(f"✅ DETERMINISM VERIFIED: {args.runs} runs produced identical output_hash")
        print(f"   output_hash: {proof['results'][0]['output_hash']}")
    else:
        print(f"❌ DETERMINISM FAILED: {len(proof['unique_output_hashes'])} unique hashes")
        for r in proof['results']:
            print(f"   Run {r['run']}: {r['output_hash']}")
        exit(1)
```

---

## RELEASE GATE

```python
def check_determinism_gate(plan_version_id: int) -> bool:
    """Check if plan passes determinism gate for release."""

    plan = get_plan_version(plan_version_id)

    # Recompute output_hash
    current_hash = compute_output_hash(plan_version_id)

    # Compare with stored hash
    if current_hash != plan.output_hash:
        raise AuditGateError(
            "Determinism check failed: "
            f"stored={plan.output_hash}, computed={current_hash}"
        )

    return True
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Different hash for same seed | S2 | Block release. Investigate source of randomness. |
| Hash verification failed | S2 | Block release. Check data integrity. |
| OSRM drift detected | S3 | Lock matrix. Document baseline. |
| Floating point variance | S3 | Fix precision. Rerun proof. |
