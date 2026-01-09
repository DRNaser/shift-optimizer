# Audit Compliance

> **Purpose**: 7 mandatory audit checks for plan release
> **Last Updated**: 2026-01-07

---

## RELEASE GATE RULE

**ALL 7 audits must PASS before a plan can be LOCKED.**

Any FAIL status blocks the lock endpoint (HTTP 409 Conflict).

---

## THE 7 MANDATORY AUDITS

### 1. Coverage Check

**Rule**: Every tour_instance must be assigned exactly once.

```python
def coverage_check(plan_version_id: int) -> AuditResult:
    instances = get_tour_instances(forecast_version_id)
    assignments = get_assignments(plan_version_id)

    assigned_ids = {a.tour_instance_id for a in assignments}
    expected_ids = {i.id for i in instances}

    unassigned = expected_ids - assigned_ids
    double_assigned = [id for id in assigned_ids if assigned_ids.count(id) > 1]

    if unassigned or double_assigned:
        return AuditResult(
            status="FAIL",
            violations=len(unassigned) + len(double_assigned),
            details={
                "unassigned": list(unassigned),
                "double_assigned": double_assigned
            }
        )
    return AuditResult(status="PASS")
```

**Common Failures**:
- Solver didn't assign all instances
- Duplicate assignments in output

---

### 2. Overlap Check

**Rule**: No driver can work concurrent tours.

```python
def overlap_check(plan_version_id: int) -> AuditResult:
    assignments = get_assignments_with_times(plan_version_id)

    violations = []
    for driver_id, driver_assignments in group_by_driver(assignments):
        sorted_tours = sorted(driver_assignments, key=lambda a: a.start_datetime)

        for i in range(len(sorted_tours) - 1):
            current = sorted_tours[i]
            next_tour = sorted_tours[i + 1]

            if current.end_datetime > next_tour.start_datetime:
                violations.append({
                    "driver_id": driver_id,
                    "tour_1": current.tour_instance_id,
                    "tour_2": next_tour.tour_instance_id,
                    "overlap_minutes": (current.end_datetime - next_tour.start_datetime).minutes
                })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

**Common Failures**:
- Same driver assigned to overlapping tours
- Cross-midnight calculation error

---

### 3. Rest Check

**Rule**: ≥11 hours rest between daily blocks.

```python
def rest_check(plan_version_id: int) -> AuditResult:
    MIN_REST_HOURS = 11

    violations = []
    for driver_id, blocks in group_by_driver_day(assignments):
        for i in range(len(blocks) - 1):
            current_block_end = blocks[i].latest_end_datetime
            next_block_start = blocks[i + 1].earliest_start_datetime

            rest_hours = (next_block_start - current_block_end).total_seconds() / 3600

            if rest_hours < MIN_REST_HOURS:
                violations.append({
                    "driver_id": driver_id,
                    "day_1": blocks[i].day,
                    "day_2": blocks[i + 1].day,
                    "rest_hours": round(rest_hours, 2),
                    "required": MIN_REST_HOURS
                })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

**Common Failures**:
- Late night shift followed by early morning
- Cross-midnight block end time miscalculated

---

### 4. Span Regular Check

**Rule**: 1er and 2er-regular blocks must have span ≤14 hours.

```python
def span_regular_check(plan_version_id: int) -> AuditResult:
    MAX_SPAN_HOURS = 14

    violations = []
    for block in get_regular_blocks(plan_version_id):  # 1er, 2er-reg
        span_hours = (block.latest_end - block.earliest_start).total_seconds() / 3600

        if span_hours > MAX_SPAN_HOURS:
            violations.append({
                "driver_id": block.driver_id,
                "day": block.day,
                "block_type": block.block_type,
                "span_hours": round(span_hours, 2),
                "max_allowed": MAX_SPAN_HOURS
            })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

---

### 5. Span Split Check

**Rule**: 3er-chain and 2er-split blocks must have:
- Span ≤16 hours
- Split break 240-360 minutes (4-6 hours)

```python
def span_split_check(plan_version_id: int) -> AuditResult:
    MAX_SPAN_HOURS = 16
    MIN_BREAK_MINUTES = 240
    MAX_BREAK_MINUTES = 360

    violations = []
    for block in get_split_blocks(plan_version_id):  # 3er, 2er-split
        span_hours = (block.latest_end - block.earliest_start).total_seconds() / 3600

        if span_hours > MAX_SPAN_HOURS:
            violations.append({
                "type": "span",
                "driver_id": block.driver_id,
                "day": block.day,
                "span_hours": round(span_hours, 2)
            })

        # Check split break (for 2er-split)
        if block.block_type == "2er-split":
            break_minutes = block.break_duration_minutes
            if not (MIN_BREAK_MINUTES <= break_minutes <= MAX_BREAK_MINUTES):
                violations.append({
                    "type": "break",
                    "driver_id": block.driver_id,
                    "day": block.day,
                    "break_minutes": break_minutes,
                    "required": f"{MIN_BREAK_MINUTES}-{MAX_BREAK_MINUTES}"
                })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

---

### 6. Fatigue Check

**Rule**: No consecutive 3er→3er blocks (different days).

```python
def fatigue_check(plan_version_id: int) -> AuditResult:
    violations = []

    for driver_id, daily_blocks in group_by_driver(assignments):
        sorted_days = sorted(daily_blocks.keys())

        for i in range(len(sorted_days) - 1):
            current_day = sorted_days[i]
            next_day = sorted_days[i + 1]

            # Only check consecutive days
            if next_day - current_day != 1:
                continue

            current_block = daily_blocks[current_day]
            next_block = daily_blocks[next_day]

            if current_block.block_type == "3er" and next_block.block_type == "3er":
                violations.append({
                    "driver_id": driver_id,
                    "day_1": current_day,
                    "day_2": next_day,
                    "violation": "3er→3er consecutive"
                })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

---

### 7. 55h Max Check

**Rule**: No driver can work >55 hours per week.

```python
def weekly_max_check(plan_version_id: int) -> AuditResult:
    MAX_WEEKLY_HOURS = 55

    violations = []
    for driver_id, assignments in group_by_driver(assignments):
        total_hours = sum(a.work_hours for a in assignments)

        if total_hours > MAX_WEEKLY_HOURS:
            violations.append({
                "driver_id": driver_id,
                "total_hours": round(total_hours, 2),
                "max_allowed": MAX_WEEKLY_HOURS,
                "over_by": round(total_hours - MAX_WEEKLY_HOURS, 2)
            })

    if violations:
        return AuditResult(status="FAIL", violations=len(violations), details=violations)
    return AuditResult(status="PASS")
```

---

## RUNNING AUDITS

### Run All Audits

```bash
python -m backend_py.v3.audit_fixed --plan-version-id 123

# Output:
# CoverageCheckFixed:    PASS (0 violations)
# OverlapCheckFixed:     PASS (0 violations)
# RestCheckFixed:        PASS (0 violations)
# SpanRegularCheckFixed: PASS (0 violations)
# SpanSplitCheckFixed:   PASS (0 violations)
# FatigueCheckFixed:     PASS (0 violations)
# WeeklyMaxCheckFixed:   PASS (0 violations)
#
# OVERALL: 7/7 PASS - Plan can be locked
```

### Run Single Audit

```bash
python -m backend_py.v3.audit_fixed --plan-version-id 123 --check coverage
```

---

## AUDIT GATE AT LOCK

```python
@router.post("/plans/{plan_id}/lock")
async def lock_plan(plan_id: int):
    # Run all audits
    audit_results = await run_all_audits(plan_id)

    # Check for failures
    failed_checks = [
        name for name, result in audit_results.items()
        if result.status == "FAIL"
    ]

    if failed_checks:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Audit gate failed",
                "failed_checks": failed_checks,
                "message": "Fix audit violations before locking"
            }
        )

    # Lock the plan
    await lock_plan_version(plan_id)
    return {"status": "locked"}
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Any audit FAIL on lock attempt | S2 | Block lock. Fix violations. |
| Audit check itself errors | S2 | Investigate. Fix audit code. |
| Audit passes but violation exists | S1 | Fix audit immediately. Review past plans. |
| 55h exceeded by small margin (<1h) | S3 | Warn. May need schedule adjustment. |
