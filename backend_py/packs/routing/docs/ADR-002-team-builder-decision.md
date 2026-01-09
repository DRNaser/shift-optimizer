# ADR-002: Team Builder vs. Direct Routing

**Status**: PROPOSED
**Date**: 2026-01-06
**Author**: SOLVEREIGN Team

## Context

MediaMarkt/HDL Plus routing requires 2-person teams with specific skills:
- 2-Mann Montage (mandatory)
- Elektro certification
- Entsorgung qualification
- Advanced montage skills

The question: Should we build a Team Builder solver, or handle teams as fixed vehicles?

## Decision Drivers

1. **Pilot Timeline**: Wien pilot in ~4 weeks
2. **Dispatcher Experience**: Dispo knows their drivers well
3. **Data Availability**: No historical pairing data yet
4. **Complexity Budget**: Limited dev capacity

## Options Considered

### Option A: Two-Stage (Team Builder → Routing)

```
Driver Pool → Team Builder → Teams → Routing → Routes
                    ↓
             Matching Solver
             (Skill coverage,
              Stability,
              Shift compat)
```

**Pros**:
- Industry standard
- Explicit stability optimization
- Dispatcher validation step
- Cleaner repair (team-level)

**Cons**:
- +2-3 weeks development
- Matching solver complexity
- Suboptimal without historical data
- Two systems to maintain

### Option B: Teams as Vehicles (V1)

```
Driver Pool → Dispatcher → Teams → Routing → Routes
                 (manual)     ↓
                         1 Team = 1 Vehicle
                         (Skills, Shift, Depot)
```

**Pros**:
- Zero additional development
- Dispatcher control (knows team dynamics)
- Simpler system
- Can collect data for V2

**Cons**:
- Manual team formation (~10-15 min/day)
- No stability optimization
- Dispatcher bottleneck

## Decision

**V1 (Pilot)**: Option B - Teams as Vehicles (manual)

**V2 (Post-Pilot)**: Option A - Team Builder solver

### Rationale

1. **V1 Priority is proving routing value**, not team optimization
2. **Dispatcher knowledge > Algorithm** without historical data
3. **Data collection**: V1 collects pairing data for V2 Team Builder
4. **Risk reduction**: Ship smaller, iterate faster

## Implementation

### V1 Workflow

```
1. FLS Export → Stop Requirements → Show to Dispatcher
   "You need: 8× 2-Mann, davon 2× Elektro"

2. Dispatcher creates teams in UI (5-10 min)
   - Select drivers
   - Assign to depot
   - Set shift times

3. Teams → Vehicles → Routing Solver
   - Each team = 1 vehicle with combined skills
   - Routing solver assigns stops to vehicles

4. Results → Driver App
   - Each team member sees route
   - Primary driver = navigator
```

### V1.5 Enhancement (after 4 weeks)

```
1. Team Suggestion API
   - Based on availability + skills
   - No optimization, just feasibility

2. Dispatcher sees suggestions
   - "Diese Paarung hat 12× zusammen gearbeitet"
   - "Warnung: Müller kann nicht mit Schmidt"

3. One-click accept or modify
```

### V2 Full Team Builder (after 3 months)

```
1. Matching Solver
   - Objective: min(skill_gaps) + max(stability) + balance(workload)
   - Constraint: all 2-Mann requirements covered
   - Soft: prefer historical pairings

2. Inputs
   - Driver pool (availability, skills, preferences)
   - Job requirements (from FLS)
   - Historical pairings (from V1 data)
   - Dispatcher overrides

3. Output
   - Suggested teams
   - Coverage score
   - Stability score
   - Warnings
```

## Data Collection for V2

In V1, we track:

```sql
-- Team history table
CREATE TABLE team_history (
    id UUID PRIMARY KEY,
    tenant_id INT,
    plan_date DATE,
    driver_1_id VARCHAR(100),
    driver_2_id VARCHAR(100),
    team_type VARCHAR(50),
    created_by VARCHAR(50),  -- 'dispatcher' | 'team_builder'
    success_score FLOAT,     -- Post-day rating (optional)
    created_at TIMESTAMPTZ
);

-- Query for V2: common pairings
SELECT driver_1_id, driver_2_id, COUNT(*) as times_together
FROM team_history
WHERE tenant_id = $1
GROUP BY driver_1_id, driver_2_id
ORDER BY times_together DESC;
```

## Consequences

### Positive
- Faster V1 delivery
- Dispatcher stays in control
- Data-driven V2 development
- Lower risk

### Negative
- Manual overhead in V1 (~10 min/day)
- V2 requires significant development
- Potential suboptimality in team formation

### Neutral
- Team Builder becomes V2 feature
- Need UI for team creation in V1

## Related Decisions

- ADR-001: Multi-tenant architecture (already decided)
- Future: ADR-003 will cover Team Builder algorithm

## Notes

The 10 minutes daily dispatcher time in V1 is acceptable because:
1. Dispatcher already spends 30+ min on manual routing
2. Team formation is familiar task
3. Gives dispatcher ownership of result
4. Builds trust before automation
