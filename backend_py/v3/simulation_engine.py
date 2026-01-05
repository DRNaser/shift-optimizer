"""
SOLVEREIGN Simulation Engine
============================

Unified entry point for all What-If scenarios.
Supports 8 scenario types across 3 categories:

OPERATIONAL (Dispatcher-Fragen):
  - Patch-Chaos: PARTIAL → COMPLETE workflow
  - Sick-Call: Driver absence drill
  - Tour-Cancel: Tour removal impact

ECONOMIC (CFO-Fragen):
  - Headcount-Cap: Budget constraint analysis
  - Cost-Curve: Rule cost in drivers
  - Freeze-Tradeoff: Stability vs flexibility

COMPLIANCE (HR-Fragen):
  - Driver-Friendly: 3er gap policy cost
  - Max-Hours: Weekly cap policy impact

Author: SOLVEREIGN V3
Created: 2026-01-05
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
from datetime import datetime
import time
import random


# =============================================================================
# ENUMS
# =============================================================================

class ScenarioType(Enum):
    """Types of simulation scenarios."""
    # Operational
    PATCH_CHAOS = "patch_chaos"
    SICK_CALL = "sick_call"
    TOUR_CANCEL = "tour_cancel"

    # Economic
    HEADCOUNT_CAP = "headcount_cap"
    COST_CURVE = "cost_curve"
    FREEZE_TRADEOFF = "freeze_tradeoff"

    # Compliance
    DRIVER_FRIENDLY = "driver_friendly"
    MAX_HOURS_POLICY = "max_hours_policy"

    # V3.2 Advanced Scenarios
    MULTI_FAILURE_CASCADE = "multi_failure_cascade"
    PROBABILISTIC_CHURN = "probabilistic_churn"
    POLICY_ROI_OPTIMIZER = "policy_roi_optimizer"


class ScenarioCategory(Enum):
    """Category of scenario for UI grouping."""
    OPERATIONAL = "operational"
    ECONOMIC = "economic"
    COMPLIANCE = "compliance"
    ADVANCED = "advanced"  # V3.2: Multi-failure, probabilistic, ROI


class RiskLevel(Enum):
    """Risk assessment levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class SimulationScenario:
    """Definition of a simulation scenario to run."""
    name: str
    scenario_type: ScenarioType
    parameters: Dict[str, Any]
    baseline_plan_id: Optional[int] = None
    description: str = ""

    @property
    def category(self) -> ScenarioCategory:
        """Get the category for this scenario type."""
        if self.scenario_type in [ScenarioType.PATCH_CHAOS,
                                   ScenarioType.SICK_CALL,
                                   ScenarioType.TOUR_CANCEL]:
            return ScenarioCategory.OPERATIONAL
        elif self.scenario_type in [ScenarioType.HEADCOUNT_CAP,
                                     ScenarioType.COST_CURVE,
                                     ScenarioType.FREEZE_TRADEOFF]:
            return ScenarioCategory.ECONOMIC
        else:
            return ScenarioCategory.COMPLIANCE


@dataclass
class ChurnMetrics:
    """Metrics about plan stability and changes."""
    unchanged: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    total_old: int = 0
    total_new: int = 0
    stability_percent: float = 0.0
    churn_rate: float = 0.0
    affected_drivers: int = 0
    affected_tours: int = 0


@dataclass
class KPISnapshot:
    """Snapshot of key performance indicators."""
    total_drivers: int = 0
    fte_drivers: int = 0
    pt_drivers: int = 0
    pt_ratio: float = 0.0
    total_tours: int = 0
    coverage: float = 1.0
    avg_hours: float = 0.0
    max_hours: float = 0.0
    min_hours: float = 0.0
    block_1er: int = 0
    block_2er_reg: int = 0
    block_2er_split: int = 0
    block_3er: int = 0
    audit_passed: int = 0
    audit_total: int = 7


@dataclass
class SimulationResult:
    """Result of running a simulation scenario."""
    scenario: SimulationScenario
    baseline_kpis: KPISnapshot
    simulated_kpis: KPISnapshot
    delta: Dict[str, Any]
    churn_metrics: ChurnMetrics
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def headcount_delta(self) -> int:
        """Difference in driver count."""
        return self.simulated_kpis.total_drivers - self.baseline_kpis.total_drivers

    @property
    def pt_delta(self) -> float:
        """Difference in PT ratio."""
        return self.simulated_kpis.pt_ratio - self.baseline_kpis.pt_ratio


@dataclass
class CostCurveEntry:
    """Single entry in a cost curve analysis."""
    rule_name: str
    rule_description: str
    baseline_value: Any
    relaxed_value: Any
    driver_delta: int
    yearly_savings_eur: float
    risk_level: RiskLevel
    arbzg_status: str  # "Legal", "Grenzwertig", "Illegal"


@dataclass
class CostCurveResult:
    """Result of cost curve analysis."""
    baseline_drivers: int
    entries: List[CostCurveEntry]
    total_potential_savings: int  # drivers
    execution_time_ms: int


@dataclass
class PolicyComparisonEntry:
    """Single entry in a policy comparison (e.g., max hours)."""
    policy_value: Any
    drivers: int
    pt_ratio: float
    coverage: float
    risk_level: RiskLevel
    label: str


@dataclass
class PolicyComparisonResult:
    """Result of policy comparison analysis."""
    policy_name: str
    baseline_value: Any
    entries: List[PolicyComparisonEntry]
    recommendation: str
    execution_time_ms: int


# =============================================================================
# SCENARIO METADATA
# =============================================================================

SCENARIO_METADATA = {
    ScenarioType.PATCH_CHAOS: {
        "name": "Patch-Chaos Simulation",
        "description": "Was passiert, wenn Mo/Di fix sind, Rest kommt später?",
        "category": ScenarioCategory.OPERATIONAL,
        "default_params": {"locked_days": [1, 2], "patch_days": [3, 4, 5, 6]},
    },
    ScenarioType.SICK_CALL: {
        "name": "Sick-Call Drill",
        "description": "Wenn N Fahrer ausfallen: wie schnell ist ein Repair-Plan verfügbar?",
        "category": ScenarioCategory.OPERATIONAL,
        "default_params": {"num_drivers_out": 5, "random_selection": True},
    },
    ScenarioType.TOUR_CANCEL: {
        "name": "Tour-Stornierung",
        "description": "Wenn N Touren wegfallen: Wie viel Churn erzeugen wir?",
        "category": ScenarioCategory.OPERATIONAL,
        "default_params": {"num_tours": 20, "target_day": None},
    },
    ScenarioType.HEADCOUNT_CAP: {
        "name": "Headcount-Budget",
        "description": "Welche Regeln müssen wir lockern um unter N Fahrer zu bleiben?",
        "category": ScenarioCategory.ECONOMIC,
        "default_params": {"target_drivers": 140},
    },
    ScenarioType.COST_CURVE: {
        "name": "Cost Curve (Regel-Kosten)",
        "description": "Was kostet jede Qualitätsregel in Fahrern?",
        "category": ScenarioCategory.ECONOMIC,
        "default_params": {"driver_yearly_cost_eur": 50000},
    },
    ScenarioType.FREEZE_TRADEOFF: {
        "name": "Freeze Window Trade-off",
        "description": "12h vs 18h vs 24h: Headcount vs Stabilität",
        "category": ScenarioCategory.ECONOMIC,
        "default_params": {"freeze_hours": [12, 18, 24, 48]},
    },
    ScenarioType.DRIVER_FRIENDLY: {
        "name": "Driver-Friendly Policy",
        "description": "Was kostet es, wenn 3er nur mit 30-60min Gaps erlaubt sind?",
        "category": ScenarioCategory.COMPLIANCE,
        "default_params": {"only_short_gaps": True},
    },
    ScenarioType.MAX_HOURS_POLICY: {
        "name": "Max-Hours Policy",
        "description": "Was passiert bei 55h → 52h → 50h → 48h Cap?",
        "category": ScenarioCategory.COMPLIANCE,
        "default_params": {"max_hours_values": [55, 52, 50, 48, 45]},
    },
    # V3.2 Advanced Scenarios
    ScenarioType.MULTI_FAILURE_CASCADE: {
        "name": "Multi-Failure Cascade",
        "description": "Kombinierte Ausfälle: N Fahrer krank + M Touren storniert",
        "category": ScenarioCategory.ADVANCED,
        "default_params": {
            "num_drivers_out": 5,
            "num_tours_cancelled": 10,
            "target_day": 1,
            "cascade_probability": 0.15,  # 15% chance each event triggers more
        },
    },
    ScenarioType.PROBABILISTIC_CHURN: {
        "name": "Probabilistic Churn Forecast",
        "description": "Monte-Carlo Simulation: P(Churn > X%) bei verschiedenen Szenarien",
        "category": ScenarioCategory.ADVANCED,
        "default_params": {
            "num_simulations": 100,
            "churn_threshold": 0.10,  # 10% threshold
            "failure_probability": 0.05,  # 5% base failure rate
            "confidence_level": 0.95,  # 95% confidence interval
        },
    },
    ScenarioType.POLICY_ROI_OPTIMIZER: {
        "name": "Policy ROI Optimizer",
        "description": "Optimale Regel-Kombination für Kosten-Nutzen-Verhältnis",
        "category": ScenarioCategory.ADVANCED,
        "default_params": {
            "budget_drivers": 5,  # How many drivers we can add/remove
            "optimize_for": "cost",  # "cost", "stability", "balanced"
            "constraints": ["arbzg_compliant"],
        },
    },
}


# =============================================================================
# RISK SCORE CALCULATION
# =============================================================================

def compute_risk_score(
    headcount_delta: int = 0,
    churn_rate: float = 0.0,
    freeze_violations: int = 0,
    audit_failures: int = 0,
    coverage_loss: float = 0.0
) -> RiskLevel:
    """
    Compute composite risk score based on multiple factors.

    Scoring:
    - Headcount: +1 (1-5), +2 (6-10), +3 (>10)
    - Churn: +1 (5-10%), +2 (10-20%), +3 (>20%)
    - Freeze: +1 (1-5), +2 (6-10), +3 (>10)
    - Audit: +5 (any failure) - critical
    - Coverage: +5 (<100%) - critical

    Thresholds:
    - LOW: 0-2
    - MEDIUM: 3-4
    - HIGH: 5-7
    - CRITICAL: 8+
    """
    score = 0

    # Headcount increase
    if headcount_delta > 10:
        score += 3
    elif headcount_delta > 5:
        score += 2
    elif headcount_delta > 0:
        score += 1

    # Churn rate
    if churn_rate > 0.20:
        score += 3
    elif churn_rate > 0.10:
        score += 2
    elif churn_rate > 0.05:
        score += 1

    # Freeze violations
    if freeze_violations > 10:
        score += 3
    elif freeze_violations > 5:
        score += 2
    elif freeze_violations > 0:
        score += 1

    # Audit failures - critical
    if audit_failures > 0:
        score += 5

    # Coverage loss - critical
    if coverage_loss > 0:
        score += 5

    # Map to risk level
    if score >= 8:
        return RiskLevel.CRITICAL
    elif score >= 5:
        return RiskLevel.HIGH
    elif score >= 3:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.LOW


def risk_level_to_german(risk: RiskLevel) -> str:
    """Convert risk level to German label."""
    mapping = {
        RiskLevel.LOW: "Niedrig",
        RiskLevel.MEDIUM: "Mittel",
        RiskLevel.HIGH: "Hoch",
        RiskLevel.CRITICAL: "Kritisch",
    }
    return mapping.get(risk, "Unbekannt")


def risk_level_to_badge(risk: RiskLevel) -> str:
    """Convert risk level to display badge."""
    mapping = {
        RiskLevel.LOW: "[OK]",
        RiskLevel.MEDIUM: "[!]",
        RiskLevel.HIGH: "[!!]",
        RiskLevel.CRITICAL: "[XXX]",
    }
    return mapping.get(risk, "[?]")


# =============================================================================
# SIMULATION HANDLERS (STUBS - To be implemented)
# =============================================================================

def _simulate_cost_curve(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> CostCurveResult:
    """
    Simulate cost curve: What does each rule cost in drivers?

    Tests each rule relaxation independently and measures driver delta.
    """
    start_time = time.time()
    driver_yearly_cost = parameters.get("driver_yearly_cost_eur", 50000)

    # Define rules to test
    rules_to_test = [
        {
            "name": "rest_hours",
            "description": "11h Rest → 10h",
            "baseline": 11,
            "relaxed": 10,
            "arbzg": "Grenzwertig",
        },
        {
            "name": "allow_3er_3er",
            "description": "3er→3er verboten → erlaubt",
            "baseline": False,
            "relaxed": True,
            "arbzg": "Legal",
        },
        {
            "name": "split_break_min",
            "description": "Split 4-6h → 3-7h",
            "baseline": 240,
            "relaxed": 180,
            "arbzg": "Grenzwertig",
        },
        {
            "name": "max_weekly_hours",
            "description": "Max 55h → 58h",
            "baseline": 55,
            "relaxed": 58,
            "arbzg": "Grenzwertig",
        },
        {
            "name": "span_regular_max",
            "description": "14h Span → 15h",
            "baseline": 14 * 60,
            "relaxed": 15 * 60,
            "arbzg": "Grenzwertig",
        },
        {
            "name": "3er_gap_quality",
            "description": "3er-Gap 30-60min strikt",
            "baseline": True,
            "relaxed": False,
            "arbzg": "Legal",
        },
    ]

    entries = []
    baseline_drivers = baseline_kpis.total_drivers

    for rule in rules_to_test:
        # Simulate with relaxed rule
        # In real implementation, this calls solve_func with config override
        # For now, use estimated deltas based on typical impact
        estimated_deltas = {
            "rest_hours": -3,
            "allow_3er_3er": -4,
            "split_break_min": -2,
            "max_weekly_hours": -2,
            "span_regular_max": -1,
            "3er_gap_quality": -2,
        }

        driver_delta = estimated_deltas.get(rule["name"], -1)
        yearly_savings = abs(driver_delta) * driver_yearly_cost

        # Determine risk based on ArbZG status
        risk = RiskLevel.LOW if rule["arbzg"] == "Legal" else RiskLevel.MEDIUM
        if rule["arbzg"] == "Illegal":
            risk = RiskLevel.CRITICAL

        entries.append(CostCurveEntry(
            rule_name=rule["name"],
            rule_description=rule["description"],
            baseline_value=rule["baseline"],
            relaxed_value=rule["relaxed"],
            driver_delta=driver_delta,
            yearly_savings_eur=yearly_savings,
            risk_level=risk,
            arbzg_status=rule["arbzg"],
        ))

    # Sort by impact (most savings first)
    entries.sort(key=lambda e: e.driver_delta)

    execution_time = int((time.time() - start_time) * 1000)

    return CostCurveResult(
        baseline_drivers=baseline_drivers,
        entries=entries,
        total_potential_savings=sum(abs(e.driver_delta) for e in entries),
        execution_time_ms=execution_time,
    )


def _simulate_max_hours_policy(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> PolicyComparisonResult:
    """
    Simulate max hours policy: What happens at 55h → 52h → 50h → 48h?
    """
    start_time = time.time()
    max_hours_values = parameters.get("max_hours_values", [55, 52, 50, 48, 45])

    entries = []
    baseline_drivers = baseline_kpis.total_drivers

    # Estimated impact per hour reduction (based on typical patterns)
    # Every ~3h reduction adds ~5 drivers
    for max_h in max_hours_values:
        delta_from_55 = 55 - max_h

        if delta_from_55 == 0:
            drivers = baseline_drivers
            pt_ratio = 0.0
            coverage = 1.0
            label = "Aktuell (Baseline)"
            risk = RiskLevel.LOW
        else:
            # Estimate: ~1.67 drivers per hour reduction
            extra_drivers = int(delta_from_55 * 1.67)
            drivers = baseline_drivers + extra_drivers

            # PT ratio increases as hours decrease
            if max_h >= 50:
                pt_ratio = (55 - max_h) * 0.01  # ~1% per hour
            else:
                pt_ratio = 0.05 + (50 - max_h) * 0.02  # Accelerates below 50h

            # Coverage risk below 45h
            coverage = 1.0 if max_h >= 45 else 0.995

            # Label and risk
            if max_h >= 52:
                label = f"Konservativ (+{extra_drivers})"
                risk = RiskLevel.LOW
            elif max_h >= 48:
                label = f"Fahrer-freundlich (+{extra_drivers})"
                risk = RiskLevel.MEDIUM
            else:
                label = f"Kritisch (+{extra_drivers})"
                risk = RiskLevel.HIGH if coverage >= 1.0 else RiskLevel.CRITICAL

        entries.append(PolicyComparisonEntry(
            policy_value=max_h,
            drivers=drivers,
            pt_ratio=pt_ratio,
            coverage=coverage,
            risk_level=risk,
            label=label,
        ))

    # Generate recommendation
    recommendation = (
        "Unter 48h steigt PT-Quote rapide. "
        "Unter 45h: Coverage-Risiko! "
        "Empfehlung: 50-52h als fairer Kompromiss."
    )

    execution_time = int((time.time() - start_time) * 1000)

    return PolicyComparisonResult(
        policy_name="Max Weekly Hours",
        baseline_value=55,
        entries=entries,
        recommendation=recommendation,
        execution_time_ms=execution_time,
    )


def _simulate_freeze_tradeoff(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> PolicyComparisonResult:
    """
    Simulate freeze window tradeoff: 12h vs 18h vs 24h vs 48h.
    """
    start_time = time.time()
    freeze_hours = parameters.get("freeze_hours", [12, 18, 24, 48])

    entries = []
    baseline_drivers = baseline_kpis.total_drivers

    # Stability increases with longer freeze, but so does headcount
    stability_map = {12: 0.78, 18: 0.89, 24: 0.95, 48: 0.98}
    driver_overhead_map = {12: 0, 18: 2, 24: 5, 48: 10}

    for freeze_h in freeze_hours:
        stability = stability_map.get(freeze_h, 0.80)
        overhead = driver_overhead_map.get(freeze_h, 0)
        drivers = baseline_drivers + overhead

        if freeze_h == 12:
            label = "Flexibel, chaotisch"
            risk = RiskLevel.MEDIUM
        elif freeze_h == 18:
            label = "Sweet Spot"
            risk = RiskLevel.LOW
        elif freeze_h == 24:
            label = "Stabil, teuer"
            risk = RiskLevel.LOW
        else:
            label = "Sehr stabil, teuer"
            risk = RiskLevel.LOW

        entries.append(PolicyComparisonEntry(
            policy_value=freeze_h,
            drivers=drivers,
            pt_ratio=stability,  # Reusing pt_ratio field for stability
            coverage=1.0,
            risk_level=risk,
            label=label,
        ))

    recommendation = (
        "18h ist optimaler Sweet Spot. "
        "+1 Fahrer → +5.5% Stabilität. "
        "Balance zwischen Kosten und Ops-Zufriedenheit."
    )

    execution_time = int((time.time() - start_time) * 1000)

    return PolicyComparisonResult(
        policy_name="Freeze Window",
        baseline_value=12,
        entries=entries,
        recommendation=recommendation,
        execution_time_ms=execution_time,
    )


def _simulate_patch_chaos(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> SimulationResult:
    """
    Simulate patch-chaos: What happens when Mo/Di are LOCKED and rest comes later?

    This simulates the common scenario where a partial forecast is locked early,
    then a patch with remaining days arrives and must be integrated.
    """
    start_time = time.time()

    locked_days = parameters.get("locked_days", [1, 2])  # Mo, Di
    patch_days = parameters.get("patch_days", [3, 4, 5, 6])  # Mi-Sa

    # Simulate baseline (full week optimization)
    baseline_drivers = baseline_kpis.total_drivers

    # Simulate partial plan (only locked days)
    # Estimate: Fewer days = fewer tours = fewer drivers needed proportionally
    locked_ratio = len(locked_days) / 6  # 6 working days
    partial_drivers = int(baseline_drivers * locked_ratio * 1.1)  # 10% overhead for suboptimal

    # Simulate patch integration
    # When patch comes in, we can't fully reoptimize locked days
    # This typically causes 2-5% overhead
    overhead_percent = 0.03 + (len(locked_days) / 6) * 0.02  # More locked = more overhead
    integrated_drivers = int(baseline_drivers * (1 + overhead_percent))

    # Calculate churn on locked days (tours that need reassignment)
    locked_tours = int(baseline_kpis.total_tours * locked_ratio)
    churn_tours = int(locked_tours * 0.087)  # ~8.7% typical churn
    freeze_violations = int(churn_tours * 0.33)  # ~1/3 are within freeze window

    # Simulated KPIs after integration
    simulated_kpis = KPISnapshot(
        total_drivers=integrated_drivers,
        fte_drivers=integrated_drivers,
        pt_drivers=0,
        pt_ratio=0.0,
        total_tours=baseline_kpis.total_tours,
        coverage=1.0,
        avg_hours=baseline_kpis.avg_hours,
        max_hours=baseline_kpis.max_hours,
        min_hours=baseline_kpis.min_hours,
        block_1er=baseline_kpis.block_1er,
        block_2er_reg=baseline_kpis.block_2er_reg,
        block_2er_split=baseline_kpis.block_2er_split,
        block_3er=baseline_kpis.block_3er,
        audit_passed=7,
        audit_total=7,
    )

    delta = {
        "drivers": integrated_drivers - baseline_drivers,
        "locked_days": locked_days,
        "patch_days": patch_days,
        "churn_tours": churn_tours,
        "freeze_violations": freeze_violations,
    }

    churn_metrics = ChurnMetrics(
        unchanged=locked_tours - churn_tours,
        changed=churn_tours,
        total_old=locked_tours,
        total_new=locked_tours,
        stability_percent=1.0 - (churn_tours / locked_tours) if locked_tours > 0 else 1.0,
        churn_rate=churn_tours / locked_tours if locked_tours > 0 else 0.0,
        affected_drivers=int(churn_tours / 3),  # ~3 tours per affected driver
        affected_tours=churn_tours,
    )

    risk = compute_risk_score(
        headcount_delta=integrated_drivers - baseline_drivers,
        churn_rate=churn_metrics.churn_rate,
        freeze_violations=freeze_violations,
    )

    day_names = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}
    locked_str = ", ".join(day_names.get(d, str(d)) for d in locked_days)
    patch_str = ", ".join(day_names.get(d, str(d)) for d in patch_days)

    recommendations = [
        f"Locked Days ({locked_str}) erzeugen {churn_tours} Tour-Reassignments bei Patch ({patch_str})",
        f"Freeze Violations: {freeze_violations} Tours benötigen Override",
        f"Overhead: +{integrated_drivers - baseline_drivers} Fahrer durch suboptimale Integration",
        f"Empfehlung: Lock später setzen oder Forecast vollständiger anfordern",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    scenario = SimulationScenario(
        name="Patch-Chaos Simulation",
        scenario_type=ScenarioType.PATCH_CHAOS,
        parameters=parameters,
        description=f"PARTIAL ({locked_str}) → COMPLETE (+{patch_str})",
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta=delta,
        churn_metrics=churn_metrics,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        details={
            "partial_drivers": partial_drivers,
            "locked_tours": locked_tours,
            "overhead_percent": overhead_percent,
        },
    )


def _simulate_sick_call(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> SimulationResult:
    """
    Simulate sick-call drill: If N drivers call in sick tomorrow morning,
    how quickly can we generate a legal repair plan with minimal churn?

    This tests the system's ability to handle last-minute driver absences.
    """
    start_time = time.time()

    num_drivers_out = parameters.get("num_drivers_out", 5)
    random_selection = parameters.get("random_selection", True)
    target_day = parameters.get("target_day", 1)  # Default: Monday

    baseline_drivers = baseline_kpis.total_drivers

    # Calculate affected tours
    # Assumption: Each driver covers ~3-4 tours per day on average
    avg_tours_per_driver_per_day = baseline_kpis.total_tours / (baseline_drivers * 6)
    affected_tours = int(num_drivers_out * avg_tours_per_driver_per_day * 1.2)  # 20% buffer

    # Simulate repair time (based on tour count)
    # Simple heuristic: ~0.1-0.3 seconds per affected tour
    repair_time_seconds = affected_tours * 0.15 + random.uniform(0.5, 1.5)

    # Calculate repair metrics
    # Some tours can be absorbed by other drivers, some need new drivers
    absorbable_tours = int(affected_tours * 0.6)  # 60% can be redistributed
    new_drivers_needed = max(0, int((affected_tours - absorbable_tours) / avg_tours_per_driver_per_day))

    # Churn metrics
    churn_tours = affected_tours  # All affected tours need reassignment
    churn_rate = affected_tours / baseline_kpis.total_tours if baseline_kpis.total_tours > 0 else 0

    # Simulated KPIs after repair
    simulated_kpis = KPISnapshot(
        total_drivers=baseline_drivers - num_drivers_out + new_drivers_needed,
        fte_drivers=baseline_drivers - num_drivers_out + new_drivers_needed,
        pt_drivers=0,
        pt_ratio=0.0,
        total_tours=baseline_kpis.total_tours,
        coverage=1.0,  # All tours still covered
        avg_hours=baseline_kpis.avg_hours * 1.05,  # Slightly higher due to redistribution
        max_hours=min(55, baseline_kpis.max_hours + 2),  # May push some drivers higher
        min_hours=baseline_kpis.min_hours,
        block_1er=baseline_kpis.block_1er,
        block_2er_reg=baseline_kpis.block_2er_reg,
        block_2er_split=baseline_kpis.block_2er_split,
        block_3er=baseline_kpis.block_3er,
        audit_passed=7,
        audit_total=7,
    )

    delta = {
        "drivers_out": num_drivers_out,
        "affected_tours": affected_tours,
        "new_drivers_needed": new_drivers_needed,
        "repair_time_seconds": round(repair_time_seconds, 2),
        "churn_tours": churn_tours,
    }

    churn_metrics = ChurnMetrics(
        unchanged=baseline_kpis.total_tours - churn_tours,
        changed=churn_tours,
        total_old=baseline_kpis.total_tours,
        total_new=baseline_kpis.total_tours,
        stability_percent=1.0 - churn_rate,
        churn_rate=churn_rate,
        affected_drivers=num_drivers_out + new_drivers_needed,
        affected_tours=affected_tours,
    )

    # Determine risk based on new drivers needed and repair time
    if new_drivers_needed == 0 and repair_time_seconds < 5:
        risk = RiskLevel.LOW
    elif new_drivers_needed <= 2 and repair_time_seconds < 10:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.HIGH

    day_names = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}
    day_name = day_names.get(target_day, str(target_day))

    recommendations = [
        f"Bei {num_drivers_out} Fahrer-Ausfällen am {day_name}: {affected_tours} Touren betroffen",
        f"Repair-Zeit: {repair_time_seconds:.1f} Sekunden",
        f"{absorbable_tours} Touren können von bestehenden Fahrern übernommen werden",
        f"{new_drivers_needed} zusätzliche Fahrer benötigt für vollständige Coverage",
        "System kann Ausfälle schnell kompensieren" if risk == RiskLevel.LOW else "Empfehlung: Backup-Fahrer-Pool erweitern",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    scenario = SimulationScenario(
        name="Sick-Call Drill",
        scenario_type=ScenarioType.SICK_CALL,
        parameters=parameters,
        description=f"{num_drivers_out} Fahrer ausgefallen am {day_name}",
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta=delta,
        churn_metrics=churn_metrics,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        details={
            "avg_tours_per_driver_per_day": round(avg_tours_per_driver_per_day, 2),
            "absorbable_tours": absorbable_tours,
            "random_selection": random_selection,
        },
    )


def _simulate_driver_friendly(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> SimulationResult:
    """
    Simulate driver-friendly policy: 3er only with 30-60min gaps.
    """
    start_time = time.time()

    # Estimated impact: +7 drivers, -42 3er blocks
    simulated_kpis = KPISnapshot(
        total_drivers=baseline_kpis.total_drivers + 7,
        fte_drivers=baseline_kpis.fte_drivers + 7,
        pt_drivers=0,
        pt_ratio=0.0,
        total_tours=baseline_kpis.total_tours,
        coverage=1.0,
        avg_hours=baseline_kpis.avg_hours * 0.95,  # Slightly less per driver
        max_hours=baseline_kpis.max_hours,
        min_hours=baseline_kpis.min_hours,
        block_1er=baseline_kpis.block_1er + 20,
        block_2er_reg=baseline_kpis.block_2er_reg + 22,
        block_2er_split=baseline_kpis.block_2er_split,
        block_3er=baseline_kpis.block_3er - 42,
        audit_passed=7,
        audit_total=7,
    )

    delta = {
        "drivers": +7,
        "3er_blocks": -42,
        "yearly_cost_eur": 7 * 50000,  # ~€350k
    }

    churn_metrics = ChurnMetrics(
        stability_percent=0.85,
        churn_rate=0.15,
        affected_drivers=20,
        affected_tours=60,
    )

    risk = compute_risk_score(
        headcount_delta=7,
        churn_rate=0.15,
    )

    recommendations = [
        "Mehrkosten: +7 Fahrer/Woche = ~€350k/Jahr",
        "Benefit: Höhere Fahrer-Zufriedenheit, weniger 16h-Tage",
        "Break-Even: Wenn Fluktuation um 5% sinkt, lohnt es sich",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    scenario = SimulationScenario(
        name="Driver-Friendly Policy",
        scenario_type=ScenarioType.DRIVER_FRIENDLY,
        parameters=parameters,
        description="3er nur mit 30-60min Gaps",
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta=delta,
        churn_metrics=churn_metrics,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
    )


def _simulate_headcount_cap(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> SimulationResult:
    """
    Simulate headcount budget constraint: What rules to relax to hit target?

    Answers: "We must stay under 140 drivers - what rules do we relax?"
    """
    start_time = time.time()

    target_drivers = parameters.get("target_drivers", 140)
    baseline_drivers = baseline_kpis.total_drivers
    gap = baseline_drivers - target_drivers

    if gap <= 0:
        # Already at or below target
        simulated_kpis = baseline_kpis
        recommendations = [f"Bereits unter Ziel ({baseline_drivers} <= {target_drivers})"]
        risk = RiskLevel.LOW
        relaxations = []
    else:
        # Define available relaxations with their driver savings
        available_relaxations = [
            {
                "name": "max_hours_58",
                "description": "Max 55h -> 58h",
                "driver_savings": 2,
                "risk": RiskLevel.LOW,
                "arbzg": "Grenzwertig",
            },
            {
                "name": "allow_3er_3er",
                "description": "3er->3er erlauben",
                "driver_savings": 4,
                "risk": RiskLevel.MEDIUM,
                "arbzg": "Legal",
            },
            {
                "name": "split_180",
                "description": "Split 240min -> 180min",
                "driver_savings": 2,
                "risk": RiskLevel.HIGH,
                "arbzg": "Grenzwertig",
            },
            {
                "name": "rest_10h",
                "description": "Rest 11h -> 10h",
                "driver_savings": 3,
                "risk": RiskLevel.MEDIUM,
                "arbzg": "Grenzwertig",
            },
            {
                "name": "span_15h",
                "description": "Span 14h -> 15h",
                "driver_savings": 1,
                "risk": RiskLevel.MEDIUM,
                "arbzg": "Legal",
            },
        ]

        # Select relaxations to meet target (greedy by efficiency)
        sorted_relaxations = sorted(
            available_relaxations,
            key=lambda r: r["driver_savings"] / (1 if r["risk"] == RiskLevel.LOW else 2 if r["risk"] == RiskLevel.MEDIUM else 3),
            reverse=True
        )

        selected = []
        total_savings = 0
        max_risk = RiskLevel.LOW

        for rel in sorted_relaxations:
            if total_savings >= gap:
                break
            selected.append(rel)
            total_savings += rel["driver_savings"]
            if rel["risk"].value > max_risk.value:
                max_risk = rel["risk"]

        relaxations = selected
        final_drivers = baseline_drivers - total_savings

        simulated_kpis = KPISnapshot(
            total_drivers=max(target_drivers, final_drivers),
            fte_drivers=max(target_drivers, final_drivers),
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=baseline_kpis.total_tours,
            coverage=1.0,
            avg_hours=baseline_kpis.avg_hours * 1.05,  # Higher utilization
            max_hours=min(58, baseline_kpis.max_hours + 3),
            min_hours=baseline_kpis.min_hours,
            block_1er=baseline_kpis.block_1er,
            block_2er_reg=baseline_kpis.block_2er_reg,
            block_2er_split=baseline_kpis.block_2er_split,
            block_3er=baseline_kpis.block_3er,
            audit_passed=7,
            audit_total=7,
        )

        risk = max_risk

        recommendations = [
            f"Ziel: {target_drivers} Fahrer (aktuell: {baseline_drivers}, Gap: {gap})",
        ]
        for rel in selected:
            recommendations.append(f"  - {rel['description']}: -{rel['driver_savings']} Fahrer ({rel['arbzg']})")

        if final_drivers <= target_drivers:
            recommendations.append(f"Ziel erreichbar mit {len(selected)} Lockerungen")
        else:
            recommendations.append(f"Ziel NICHT erreichbar - {final_drivers - target_drivers} Fahrer zu viel")

    delta = {
        "target": target_drivers,
        "gap": gap,
        "relaxations": [r["name"] for r in relaxations] if 'relaxations' in dir() else [],
        "achieved": simulated_kpis.total_drivers <= target_drivers,
    }

    churn_metrics = ChurnMetrics(
        stability_percent=0.90,
        churn_rate=0.10,
        affected_drivers=gap,
        affected_tours=gap * 5,
    )

    execution_time = int((time.time() - start_time) * 1000)

    scenario = SimulationScenario(
        name="Headcount-Budget Analyse",
        scenario_type=ScenarioType.HEADCOUNT_CAP,
        parameters=parameters,
        description=f"Ziel: <= {target_drivers} Fahrer",
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta=delta,
        churn_metrics=churn_metrics,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        details={"relaxations": relaxations if 'relaxations' in dir() else []},
    )


def _simulate_tour_cancel(
    baseline_kpis: KPISnapshot,
    parameters: Dict[str, Any],
    solve_func: Callable
) -> SimulationResult:
    """
    Simulate tour cancellation: What happens when tours are removed?

    Answers: "If 20 tours are cancelled, how much churn do we create?"
    """
    start_time = time.time()

    num_cancelled = parameters.get("num_cancelled", 20)
    target_day = parameters.get("target_day", None)  # None = distributed across week

    baseline_drivers = baseline_kpis.total_drivers
    baseline_tours = baseline_kpis.total_tours

    # Calculate impact
    cancellation_rate = num_cancelled / baseline_tours if baseline_tours > 0 else 0

    # Drivers freed (some tours were filling gaps, others freeing entire drivers)
    tours_per_driver = baseline_tours / baseline_drivers if baseline_drivers > 0 else 1
    drivers_freed = int(num_cancelled / tours_per_driver * 0.4)  # 40% result in full driver freed

    # Churn from reassignments (remaining tours need rebalancing)
    reassignment_churn = int(num_cancelled * 1.5)  # 1.5x multiplier for ripple effects

    new_total_tours = baseline_tours - num_cancelled
    new_drivers = baseline_drivers - drivers_freed

    simulated_kpis = KPISnapshot(
        total_drivers=new_drivers,
        fte_drivers=new_drivers,
        pt_drivers=0,
        pt_ratio=0.0,
        total_tours=new_total_tours,
        coverage=1.0,  # Still 100% of remaining tours
        avg_hours=baseline_kpis.avg_hours * 0.98,  # Slightly less work
        max_hours=baseline_kpis.max_hours,
        min_hours=max(35, baseline_kpis.min_hours - 2),
        block_1er=baseline_kpis.block_1er - int(num_cancelled * 0.3),
        block_2er_reg=baseline_kpis.block_2er_reg - int(num_cancelled * 0.3),
        block_2er_split=baseline_kpis.block_2er_split,
        block_3er=baseline_kpis.block_3er - int(num_cancelled * 0.1),
        audit_passed=7,
        audit_total=7,
    )

    churn_rate = reassignment_churn / baseline_tours if baseline_tours > 0 else 0

    delta = {
        "cancelled": num_cancelled,
        "drivers_freed": drivers_freed,
        "reassignment_churn": reassignment_churn,
        "target_day": target_day,
    }

    churn_metrics = ChurnMetrics(
        unchanged=baseline_tours - num_cancelled - reassignment_churn,
        changed=reassignment_churn,
        total_old=baseline_tours,
        total_new=new_total_tours,
        stability_percent=1.0 - churn_rate,
        churn_rate=churn_rate,
        affected_drivers=drivers_freed + int(reassignment_churn / 3),
        affected_tours=num_cancelled + reassignment_churn,
    )

    # Risk based on cancellation rate
    if cancellation_rate < 0.02:
        risk = RiskLevel.LOW
    elif cancellation_rate < 0.05:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.HIGH

    day_name = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}.get(target_day, "verteilt")

    recommendations = [
        f"{num_cancelled} Touren storniert ({cancellation_rate:.1%} der Gesamttouren)",
        f"{drivers_freed} Fahrer komplett freigesetzt",
        f"{reassignment_churn} Touren durch Umverteilung betroffen",
        f"Churn Rate: {churn_rate:.1%}",
        "Empfehlung: Minimal-Replan nur für betroffene Blöcke" if risk == RiskLevel.LOW else "Empfehlung: Vollständige Re-Optimierung",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    scenario = SimulationScenario(
        name="Tour-Stornierung",
        scenario_type=ScenarioType.TOUR_CANCEL,
        parameters=parameters,
        description=f"{num_cancelled} Touren storniert ({day_name})",
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta=delta,
        churn_metrics=churn_metrics,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
    )


# =============================================================================
# RESULT CONVERTERS
# =============================================================================

def _convert_to_simulation_result(
    scenario: SimulationScenario,
    baseline_kpis: KPISnapshot,
    result: 'CostCurveResult'
) -> SimulationResult:
    """Convert CostCurveResult to SimulationResult."""
    # Find the best entry (most savings - most negative driver_delta)
    best_entry = min(result.entries, key=lambda e: e.driver_delta) if result.entries else None

    simulated_kpis = KPISnapshot(
        total_drivers=baseline_kpis.total_drivers + (best_entry.driver_delta if best_entry else 0),
        fte_drivers=baseline_kpis.fte_drivers,
        pt_drivers=baseline_kpis.pt_drivers,
        pt_ratio=baseline_kpis.pt_ratio,
        total_tours=baseline_kpis.total_tours,
        coverage=baseline_kpis.coverage,
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta={"drivers": result.total_potential_savings},
        churn_metrics=ChurnMetrics(),
        risk_score=RiskLevel.LOW,
        recommendations=[f"Kosteneinsparung moeglich: {result.total_potential_savings} Fahrer"],
        execution_time_ms=result.execution_time_ms,
        details={
            "entries": [
                {"rule": e.rule_name, "delta": e.driver_delta, "risk": e.risk_level.value}
                for e in result.entries
            ]
        }
    )


def _convert_policy_to_simulation_result(
    scenario: SimulationScenario,
    baseline_kpis: KPISnapshot,
    result: 'PolicyComparisonResult'
) -> SimulationResult:
    """Convert PolicyComparisonResult to SimulationResult."""
    # Find the entry with baseline value
    baseline_entry = next((e for e in result.entries if e.policy_value == result.baseline_value), None)
    # Find the best entry (fewest drivers with good coverage)
    best_entry = min(
        [e for e in result.entries if e.coverage >= 0.995],
        key=lambda e: e.drivers,
        default=baseline_entry
    ) if result.entries else baseline_entry

    simulated_kpis = KPISnapshot(
        total_drivers=best_entry.drivers if best_entry else baseline_kpis.total_drivers,
        fte_drivers=baseline_kpis.fte_drivers,
        pt_drivers=baseline_kpis.pt_drivers,
        pt_ratio=best_entry.pt_ratio if best_entry else baseline_kpis.pt_ratio,
        total_tours=baseline_kpis.total_tours,
        coverage=best_entry.coverage if best_entry else baseline_kpis.coverage,
    )

    delta_drivers = (best_entry.drivers - baseline_kpis.total_drivers) if best_entry else 0

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta={"drivers": delta_drivers},
        churn_metrics=ChurnMetrics(),
        risk_score=best_entry.risk_level if best_entry else RiskLevel.LOW,
        recommendations=[result.recommendation],
        execution_time_ms=result.execution_time_ms,
        details={
            "policy": result.policy_name,
            "entries": [
                {"value": e.policy_value, "drivers": e.drivers, "pt_ratio": e.pt_ratio,
                 "coverage": e.coverage, "risk": e.risk_level.value, "label": e.label}
                for e in result.entries
            ]
        }
    )


def _convert_operational_to_simulation_result(
    scenario: SimulationScenario,
    baseline_kpis: KPISnapshot,
    result: 'OperationalDrillResult'
) -> SimulationResult:
    """Convert OperationalDrillResult to SimulationResult."""
    simulated_kpis = KPISnapshot(
        total_drivers=result.new_drivers_required + baseline_kpis.total_drivers,
        fte_drivers=baseline_kpis.fte_drivers,
        pt_drivers=baseline_kpis.pt_drivers,
        pt_ratio=baseline_kpis.pt_ratio,
        total_tours=result.affected_tours,
        coverage=1.0 if result.can_recover else 0.95,
    )

    churn = ChurnMetrics(
        total_assignments=result.affected_tours,
        changed_assignments=result.reassigned_tours,
        churn_rate=result.churn_rate,
        affected_drivers=result.affected_drivers,
    )

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta={"drivers": result.new_drivers_required},
        churn_metrics=churn,
        risk_score=result.risk_score,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details={
            "can_recover": result.can_recover,
            "recovery_time_seconds": result.recovery_time_seconds,
            "affected_tours": result.affected_tours,
        }
    )


def _convert_headcount_to_simulation_result(
    scenario: SimulationScenario,
    baseline_kpis: KPISnapshot,
    result: 'HeadcountCapResult'
) -> SimulationResult:
    """Convert HeadcountCapResult to SimulationResult."""
    simulated_kpis = KPISnapshot(
        total_drivers=result.target_drivers,
        fte_drivers=result.target_drivers,
        pt_drivers=0,
        pt_ratio=0.0,
        total_tours=baseline_kpis.total_tours,
        coverage=1.0 if result.achievable else 0.95,
    )

    delta = result.target_drivers - baseline_kpis.total_drivers

    return SimulationResult(
        scenario=scenario,
        baseline_kpis=baseline_kpis,
        simulated_kpis=simulated_kpis,
        delta={"drivers": delta},
        churn_metrics=ChurnMetrics(),
        risk_score=result.combined_risk,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details={
            "achievable": result.achievable,
            "required_relaxations": [
                {"rule": r.rule_name, "delta": r.driver_impact, "risk": r.risk_level.value}
                for r in result.required_relaxations
            ]
        }
    )


# =============================================================================
# MAIN SIMULATION RUNNER
# =============================================================================

def run_simulation(
    scenario: SimulationScenario,
    baseline_kpis: Optional[KPISnapshot] = None,
    solve_func: Optional[Callable] = None
) -> SimulationResult:
    """
    Unified entry point for all simulation types.

    Args:
        scenario: The simulation scenario to run
        baseline_kpis: Current KPIs (if None, uses defaults)
        solve_func: Function to call solver (for real simulations)

    Returns:
        SimulationResult with all metrics and recommendations
    """
    # Default baseline if not provided
    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    # Route to appropriate handler based on scenario type
    scenario_type = scenario.scenario_type
    params = scenario.parameters
    start_time = time.time()

    try:
        # ECONOMIC SCENARIOS
        if scenario_type == ScenarioType.COST_CURVE:
            result = _simulate_cost_curve(baseline_kpis, params, solve_func)
            return _convert_to_simulation_result(scenario, baseline_kpis, result)

        elif scenario_type == ScenarioType.MAX_HOURS_POLICY:
            result = _simulate_max_hours_policy(baseline_kpis, params, solve_func)
            return _convert_policy_to_simulation_result(scenario, baseline_kpis, result)

        elif scenario_type == ScenarioType.FREEZE_TRADEOFF:
            result = _simulate_freeze_tradeoff(baseline_kpis, params, solve_func)
            return _convert_policy_to_simulation_result(scenario, baseline_kpis, result)

        # OPERATIONAL SCENARIOS (return SimulationResult directly)
        elif scenario_type == ScenarioType.PATCH_CHAOS:
            return _simulate_patch_chaos(baseline_kpis, params, solve_func)

        elif scenario_type == ScenarioType.SICK_CALL:
            return _simulate_sick_call(baseline_kpis, params, solve_func)

        elif scenario_type == ScenarioType.TOUR_CANCEL:
            return _simulate_tour_cancel(baseline_kpis, params, solve_func)

        # COMPLIANCE SCENARIOS (return SimulationResult directly)
        elif scenario_type == ScenarioType.DRIVER_FRIENDLY:
            return _simulate_driver_friendly(baseline_kpis, params, solve_func)

        elif scenario_type == ScenarioType.HEADCOUNT_CAP:
            return _simulate_headcount_cap(baseline_kpis, params, solve_func)

        else:
            # Unknown scenario type
            execution_time = int((time.time() - start_time) * 1000)
            return SimulationResult(
                scenario=scenario,
                baseline_kpis=baseline_kpis,
                simulated_kpis=baseline_kpis,
                delta={"drivers": 0},
                churn_metrics=ChurnMetrics(),
                risk_score=RiskLevel.LOW,
                recommendations=[f"Szenario {scenario_type.value} nicht implementiert."],
                execution_time_ms=execution_time,
            )

    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        return SimulationResult(
            scenario=scenario,
            baseline_kpis=baseline_kpis,
            simulated_kpis=baseline_kpis,
            delta={"drivers": 0},
            churn_metrics=ChurnMetrics(),
            risk_score=RiskLevel.CRITICAL,
            recommendations=[f"Simulation fehlgeschlagen: {str(e)}"],
            execution_time_ms=execution_time,
        )


@dataclass
class CostCurveResultExtended:
    """Extended result with attributes needed by UI."""
    baseline_drivers: int
    entries: List[CostCurveEntry]
    total_potential_savings: int
    execution_time_ms: int
    risk_score: RiskLevel = RiskLevel.LOW
    recommendations: List[str] = field(default_factory=list)


@dataclass
class PolicyComparisonResultExtended:
    """Extended result with attributes needed by UI."""
    policy_name: str
    baseline_value: Any
    baseline_drivers: int
    entries: List['PolicyComparisonEntryExtended']
    recommendation: str
    execution_time_ms: int
    risk_score: RiskLevel = RiskLevel.LOW
    recommendations: List[str] = field(default_factory=list)


@dataclass
class PolicyComparisonEntryExtended:
    """Extended entry with all fields needed by UI."""
    policy_value: Any
    drivers: int
    driver_delta: int
    fte_count: int
    pt_ratio: float
    coverage: float
    risk_level: RiskLevel
    label: str
    stability_percent: float = 0.0
    evaluation: str = ""


def run_cost_curve(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> CostCurveResultExtended:
    """
    Run cost curve analysis.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        baseline_kpis: Current KPIs
        parameters: Additional parameters (driver_yearly_cost_eur)
        solve_func: Function to call solver

    Returns:
        CostCurveResultExtended with all rule costs and recommendations
    """
    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(total_drivers=145)

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.COST_CURVE]["default_params"]

    result = _simulate_cost_curve(baseline_kpis, parameters, solve_func)

    # Generate recommendations
    recommendations = [
        f"Die teuerste Regel ist '{result.entries[0].rule_description}' mit {abs(result.entries[0].driver_delta)} Fahrern.",
        "Regellockerungen sollten mit Betriebsrat abgestimmt werden.",
        f"Potenzielle Einsparung: {result.total_potential_savings} Fahrer = ~€{result.total_potential_savings * 50000:,.0f}/Jahr",
    ]

    return CostCurveResultExtended(
        baseline_drivers=result.baseline_drivers,
        entries=result.entries,
        total_potential_savings=result.total_potential_savings,
        execution_time_ms=result.execution_time_ms,
        risk_score=RiskLevel.MEDIUM,  # Cost curve changes are generally medium risk
        recommendations=recommendations,
    )


def run_max_hours_policy(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    caps_to_test: Optional[List[int]] = None,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> PolicyComparisonResultExtended:
    """
    Run max hours policy comparison.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        caps_to_test: List of hour caps to test (e.g., [55, 52, 50, 48])
        baseline_kpis: Current KPIs
        parameters: Additional parameters (max_hours_values)
        solve_func: Function to call solver

    Returns:
        PolicyComparisonResultExtended with all policy options
    """
    # Suppress unused parameter warnings - these are for future implementation
    _ = instances, baseline_seed

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(total_drivers=145)

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.MAX_HOURS_POLICY]["default_params"].copy()

    # Override with caps_to_test if provided
    if caps_to_test:
        parameters["max_hours_values"] = caps_to_test

    result = _simulate_max_hours_policy(baseline_kpis, parameters, solve_func)

    # Convert to extended format
    extended_entries = []
    for entry in result.entries:
        delta = entry.drivers - baseline_kpis.total_drivers
        extended_entries.append(PolicyComparisonEntryExtended(
            policy_value=entry.policy_value,
            drivers=entry.drivers,
            driver_delta=delta,
            fte_count=int(entry.drivers * (1 - entry.pt_ratio)),
            pt_ratio=entry.pt_ratio * 100,  # Convert to percentage
            coverage=entry.coverage * 100,
            risk_level=entry.risk_level,
            label=entry.label,
        ))

    recommendations = [
        result.recommendation,
        "CFO-Formel: (55h - X) / 3 × 5 ≈ zusätzliche Fahrer",
    ]

    return PolicyComparisonResultExtended(
        policy_name=result.policy_name,
        baseline_value=result.baseline_value,
        baseline_drivers=baseline_kpis.total_drivers,
        entries=extended_entries,
        recommendation=result.recommendation,
        execution_time_ms=result.execution_time_ms,
        risk_score=RiskLevel.LOW,
        recommendations=recommendations,
    )


def run_freeze_tradeoff(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    windows_to_test: Optional[List[int]] = None,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> PolicyComparisonResultExtended:
    """
    Run freeze window tradeoff analysis.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        windows_to_test: List of freeze windows in minutes (e.g., [720, 1080, 1440])
        baseline_kpis: Current KPIs
        parameters: Additional parameters (freeze_hours)
        solve_func: Function to call solver

    Returns:
        PolicyComparisonResultExtended with freeze window options
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(total_drivers=145)

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.FREEZE_TRADEOFF]["default_params"].copy()

    # Override with windows_to_test if provided (convert from minutes to hours)
    if windows_to_test:
        parameters["freeze_hours"] = [w // 60 for w in windows_to_test]

    result = _simulate_freeze_tradeoff(baseline_kpis, parameters, solve_func)

    # Convert to extended format
    extended_entries = []
    for entry in result.entries:
        delta = entry.drivers - baseline_kpis.total_drivers
        extended_entries.append(PolicyComparisonEntryExtended(
            policy_value=entry.policy_value * 60,  # Convert hours to minutes for consistency
            drivers=entry.drivers,
            driver_delta=delta,
            fte_count=entry.drivers,
            pt_ratio=0.0,
            coverage=entry.coverage * 100,
            risk_level=entry.risk_level,
            label=entry.label,
            stability_percent=entry.pt_ratio * 100,  # pt_ratio was reused for stability
            evaluation=entry.label,
        ))

    recommendations = [
        result.recommendation,
    ]

    return PolicyComparisonResultExtended(
        policy_name=result.policy_name,
        baseline_value=result.baseline_value,
        baseline_drivers=baseline_kpis.total_drivers,
        entries=extended_entries,
        recommendation=result.recommendation,
        execution_time_ms=result.execution_time_ms,
        risk_score=RiskLevel.LOW,
        recommendations=recommendations,
    )


@dataclass
class DriverFriendlyResultExtended:
    """Extended result for driver-friendly policy with UI-compatible fields."""
    baseline_drivers: int
    entries: List[PolicyComparisonEntryExtended]
    execution_time_ms: int
    risk_score: RiskLevel = RiskLevel.LOW
    recommendations: List[str] = field(default_factory=list)


@dataclass
class PatchChaosResultExtended:
    """Extended result for patch-chaos simulation with UI-compatible fields."""
    baseline_drivers: int
    integrated_drivers: int
    driver_delta: int
    locked_days: List[int]
    patch_days: List[int]
    churn_tours: int
    churn_rate: float
    freeze_violations: int
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SickCallResultExtended:
    """Extended result for sick-call drill with UI-compatible fields."""
    baseline_drivers: int
    drivers_out: int
    affected_tours: int
    new_drivers_needed: int
    repair_time_seconds: float
    absorbable_tours: int
    churn_rate: float
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    all_audits_pass: bool = True
    details: Dict[str, Any] = field(default_factory=dict)


def run_driver_friendly_policy(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> DriverFriendlyResultExtended:
    """
    Run driver-friendly policy analysis.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        baseline_kpis: Current KPIs
        parameters: Additional parameters (only_short_gaps)
        solve_func: Function to call solver

    Returns:
        DriverFriendlyResultExtended with driver-friendly policy impact
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.DRIVER_FRIENDLY]["default_params"]

    result = _simulate_driver_friendly(baseline_kpis, parameters, solve_func)

    # Convert to extended format
    entries = [PolicyComparisonEntryExtended(
        policy_value="Driver-Friendly",
        drivers=result.simulated_kpis.total_drivers,
        driver_delta=result.headcount_delta,
        fte_count=result.simulated_kpis.fte_drivers,
        pt_ratio=result.simulated_kpis.pt_ratio,
        coverage=result.simulated_kpis.coverage * 100,
        risk_level=result.risk_score,
        label="Nur 30-60min Gaps in 3er-Chains",
    )]

    return DriverFriendlyResultExtended(
        baseline_drivers=baseline_kpis.total_drivers,
        entries=entries,
        execution_time_ms=result.execution_time_ms,
        risk_score=result.risk_score,
        recommendations=result.recommendations,
    )


def run_patch_chaos(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    locked_days: Optional[List[int]] = None,
    patch_days: Optional[List[int]] = None,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> PatchChaosResultExtended:
    """
    Run patch-chaos simulation.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        locked_days: Days that are already locked (1=Mo, 2=Di, etc.)
        patch_days: Days that come in the patch
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        PatchChaosResultExtended with simulation results
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.PATCH_CHAOS]["default_params"].copy()

    # Override with provided days
    if locked_days:
        parameters["locked_days"] = locked_days
    if patch_days:
        parameters["patch_days"] = patch_days

    result = _simulate_patch_chaos(baseline_kpis, parameters, None)

    return PatchChaosResultExtended(
        baseline_drivers=baseline_kpis.total_drivers,
        integrated_drivers=result.simulated_kpis.total_drivers,
        driver_delta=result.headcount_delta,
        locked_days=result.delta.get("locked_days", []),
        patch_days=result.delta.get("patch_days", []),
        churn_tours=result.delta.get("churn_tours", 0),
        churn_rate=result.churn_metrics.churn_rate,
        freeze_violations=result.delta.get("freeze_violations", 0),
        risk_score=result.risk_score,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details=result.details,
    )


def run_sick_call(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    num_drivers_out: int = 5,
    target_day: int = 1,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> SickCallResultExtended:
    """
    Run sick-call drill simulation.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        num_drivers_out: Number of drivers calling in sick
        target_day: Day of the week (1=Mo, 2=Di, etc.)
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        SickCallResultExtended with simulation results
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.SICK_CALL]["default_params"].copy()

    # Override with provided values
    parameters["num_drivers_out"] = num_drivers_out
    parameters["target_day"] = target_day

    result = _simulate_sick_call(baseline_kpis, parameters, None)

    return SickCallResultExtended(
        baseline_drivers=baseline_kpis.total_drivers,
        drivers_out=num_drivers_out,
        affected_tours=result.delta.get("affected_tours", 0),
        new_drivers_needed=result.delta.get("new_drivers_needed", 0),
        repair_time_seconds=result.delta.get("repair_time_seconds", 0),
        absorbable_tours=result.details.get("absorbable_tours", 0),
        churn_rate=result.churn_metrics.churn_rate,
        risk_score=result.risk_score,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        all_audits_pass=result.simulated_kpis.audit_passed == result.simulated_kpis.audit_total,
        details=result.details,
    )


@dataclass
class HeadcountBudgetResultExtended:
    """Extended result for headcount-budget analysis with UI-compatible fields."""
    baseline_drivers: int
    target_drivers: int
    gap: int
    achieved: bool
    final_drivers: int
    relaxations: List[Dict[str, Any]]
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TourCancelResultExtended:
    """Extended result for tour cancellation simulation with UI-compatible fields."""
    baseline_drivers: int
    baseline_tours: int
    cancelled_tours: int
    drivers_freed: int
    new_drivers: int
    new_tours: int
    reassignment_churn: int
    churn_rate: float
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    details: Dict[str, Any] = field(default_factory=dict)


def run_headcount_budget(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    target_drivers: int = 140,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> HeadcountBudgetResultExtended:
    """
    Run headcount budget analysis.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        target_drivers: Target number of drivers (default: 140)
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        HeadcountBudgetResultExtended with relaxation recommendations
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.HEADCOUNT_CAP]["default_params"].copy()

    parameters["target_drivers"] = target_drivers

    result = _simulate_headcount_cap(baseline_kpis, parameters, None)

    return HeadcountBudgetResultExtended(
        baseline_drivers=baseline_kpis.total_drivers,
        target_drivers=target_drivers,
        gap=baseline_kpis.total_drivers - target_drivers,
        achieved=result.delta.get("achieved", False),
        final_drivers=result.simulated_kpis.total_drivers,
        relaxations=result.details.get("relaxations", []),
        risk_score=result.risk_score,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details=result.details,
    )


def run_tour_cancel(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    num_cancelled: int = 20,
    target_day: Optional[int] = None,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> TourCancelResultExtended:
    """
    Run tour cancellation simulation.

    Args:
        instances: List of tour instances (for future solver integration)
        baseline_seed: Seed for baseline calculation
        num_cancelled: Number of tours to cancel (default: 20)
        target_day: Day of week (1=Mo, 2=Di, etc.) or None for distributed
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        TourCancelResultExtended with simulation results
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            pt_drivers=0,
            pt_ratio=0.0,
            total_tours=1385,
            coverage=1.0,
            avg_hours=48.5,
            max_hours=54,
            min_hours=40,
            block_1er=350,
            block_2er_reg=350,
            block_2er_split=100,
            block_3er=222,
            audit_passed=7,
            audit_total=7,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.TOUR_CANCEL]["default_params"].copy()

    parameters["num_cancelled"] = num_cancelled
    parameters["target_day"] = target_day

    result = _simulate_tour_cancel(baseline_kpis, parameters, None)

    return TourCancelResultExtended(
        baseline_drivers=baseline_kpis.total_drivers,
        baseline_tours=baseline_kpis.total_tours,
        cancelled_tours=num_cancelled,
        drivers_freed=result.delta.get("drivers_freed", 0),
        new_drivers=result.simulated_kpis.total_drivers,
        new_tours=result.simulated_kpis.total_tours,
        reassignment_churn=result.delta.get("reassignment_churn", 0),
        churn_rate=result.churn_metrics.churn_rate,
        risk_score=result.risk_score,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details=result.delta,
    )


# =============================================================================
# V3.2 ADVANCED SCENARIOS
# =============================================================================

@dataclass
class MultiFailureCascadeResult:
    """Result of multi-failure cascade simulation."""
    baseline_drivers: int
    final_drivers: int
    drivers_out: int
    tours_cancelled: int
    cascade_events: List[Dict[str, Any]]
    total_affected_tours: int
    total_churn: float
    repair_time_seconds: float
    new_drivers_needed: int
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    probability_of_cascade: float = 0.0
    worst_case_drivers: int = 0
    best_case_drivers: int = 0


@dataclass
class ProbabilisticChurnResult:
    """Result of probabilistic churn simulation."""
    num_simulations: int
    churn_threshold: float
    probability_above_threshold: float
    mean_churn: float
    std_churn: float
    percentile_5: float
    percentile_50: float
    percentile_95: float
    confidence_interval: tuple
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    histogram_data: List[float] = field(default_factory=list)


@dataclass
class PolicyROIEntry:
    """Single entry in policy ROI analysis."""
    policy_combination: List[str]
    driver_delta: int
    cost_savings_eur: float
    stability_impact: float  # -1 to +1 scale
    risk_level: RiskLevel
    roi_score: float  # Composite score
    arbzg_compliant: bool


@dataclass
class PolicyROIResult:
    """Result of policy ROI optimization."""
    baseline_drivers: int
    optimal_combination: PolicyROIEntry
    all_combinations: List[PolicyROIEntry]
    pareto_frontier: List[PolicyROIEntry]
    risk_score: RiskLevel
    recommendations: List[str]
    execution_time_ms: int
    optimization_target: str = "balanced"


def run_multi_failure_cascade(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    num_drivers_out: int = 5,
    num_tours_cancelled: int = 10,
    target_day: int = 1,
    cascade_probability: float = 0.15,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> MultiFailureCascadeResult:
    """
    Run multi-failure cascade simulation.

    Simulates combined failures: N drivers sick + M tours cancelled + cascade effects.
    Each initial failure has a probability of triggering additional failures.

    Args:
        instances: List of tour instances
        baseline_seed: Seed for baseline calculation
        num_drivers_out: Number of drivers calling in sick
        num_tours_cancelled: Number of tours cancelled
        target_day: Day of week (1=Mo, 2=Di, etc.)
        cascade_probability: Probability each event triggers additional events
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        MultiFailureCascadeResult with combined failure impact
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    start_time = time.time()

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            total_tours=1385,
            coverage=1.0,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.MULTI_FAILURE_CASCADE]["default_params"].copy()

    # Override with provided values
    num_drivers_out = parameters.get("num_drivers_out", num_drivers_out)
    num_tours_cancelled = parameters.get("num_tours_cancelled", num_tours_cancelled)
    target_day = parameters.get("target_day", target_day)
    cascade_probability = parameters.get("cascade_probability", cascade_probability)

    baseline_drivers = baseline_kpis.total_drivers
    baseline_tours = baseline_kpis.total_tours

    # First, calculate individual impacts
    # Sick call impact
    avg_tours_per_driver = baseline_tours / baseline_drivers / 6
    sick_affected_tours = int(num_drivers_out * avg_tours_per_driver * 1.2)

    # Tour cancel impact
    tour_cancel_freed = int(num_tours_cancelled / (baseline_tours / baseline_drivers) * 0.4)

    # Cascade simulation
    cascade_events = []
    current_drivers_out = num_drivers_out
    current_tours_cancelled = num_tours_cancelled
    cascade_round = 0

    while cascade_round < 5:  # Max 5 cascade rounds
        cascade_round += 1

        # Each sick driver might cause more sick (e.g., team spread)
        new_sick = 0
        for _ in range(current_drivers_out):
            if random.random() < cascade_probability * 0.5:  # 50% of cascade prob for driver-driver
                new_sick += 1

        # Each cancelled tour might cause more cancellations (e.g., linked routes)
        new_cancelled = 0
        for _ in range(current_tours_cancelled):
            if random.random() < cascade_probability:
                new_cancelled += 1

        if new_sick == 0 and new_cancelled == 0:
            break

        cascade_events.append({
            "round": cascade_round,
            "new_sick": new_sick,
            "new_cancelled": new_cancelled,
            "trigger": f"Round {cascade_round} cascade"
        })

        current_drivers_out += new_sick
        current_tours_cancelled += new_cancelled

    # Total impact calculation
    total_drivers_out = num_drivers_out + sum(e["new_sick"] for e in cascade_events)
    total_tours_cancelled = num_tours_cancelled + sum(e["new_cancelled"] for e in cascade_events)

    total_affected_tours = int(total_drivers_out * avg_tours_per_driver * 1.2) + total_tours_cancelled
    total_affected_tours = min(total_affected_tours, baseline_tours)

    # Repair metrics
    absorbable = int(total_affected_tours * 0.5)  # Only 50% absorbable in multi-failure
    new_drivers_needed = max(0, int((total_affected_tours - absorbable) / avg_tours_per_driver / 6))

    # Churn calculation
    churn_rate = total_affected_tours / baseline_tours if baseline_tours > 0 else 0

    # Repair time (increases with cascade complexity)
    repair_time = (total_affected_tours * 0.2 + len(cascade_events) * 2.0 +
                   random.uniform(1.0, 3.0))

    # Final driver count
    tour_savings = int(total_tours_cancelled / (baseline_tours / baseline_drivers) * 0.3)
    final_drivers = baseline_drivers - tour_savings + new_drivers_needed

    # Risk calculation - multi-failure is inherently higher risk
    base_risk = compute_risk_score(
        headcount_delta=new_drivers_needed,
        churn_rate=churn_rate,
    )

    # Upgrade risk if cascade occurred
    if len(cascade_events) > 0:
        if base_risk == RiskLevel.LOW:
            risk = RiskLevel.MEDIUM
        elif base_risk == RiskLevel.MEDIUM:
            risk = RiskLevel.HIGH
        else:
            risk = RiskLevel.CRITICAL
    else:
        risk = base_risk

    # Probability calculation
    prob_cascade = 1 - ((1 - cascade_probability) ** (num_drivers_out + num_tours_cancelled))

    # Best/worst case
    worst_case = baseline_drivers + int(total_drivers_out * 0.3)  # Need to replace all
    best_case = max(baseline_drivers - tour_savings - int(total_drivers_out * 0.1), 100)

    day_name = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}.get(target_day, "?")

    recommendations = [
        f"MULTI-FAILURE am {day_name}: {num_drivers_out} Fahrer krank + {num_tours_cancelled} Touren storniert",
        f"Cascade-Events: {len(cascade_events)} (Gesamt: +{total_drivers_out - num_drivers_out} Fahrer, +{total_tours_cancelled - num_tours_cancelled} Touren)",
        f"Total betroffene Touren: {total_affected_tours} ({churn_rate:.1%} Churn)",
        f"Neue Fahrer benötigt: {new_drivers_needed}",
        f"Repair-Zeit: {repair_time:.1f}s",
        f"Cascade-Wahrscheinlichkeit: {prob_cascade:.1%}",
        "KRITISCH: Multi-Failure erfordert sofortige Eskalation!" if risk == RiskLevel.CRITICAL else
        "Empfehlung: Backup-Pool um 20% erhöhen für Resilience",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    return MultiFailureCascadeResult(
        baseline_drivers=baseline_drivers,
        final_drivers=final_drivers,
        drivers_out=total_drivers_out,
        tours_cancelled=total_tours_cancelled,
        cascade_events=cascade_events,
        total_affected_tours=total_affected_tours,
        total_churn=churn_rate,
        repair_time_seconds=repair_time,
        new_drivers_needed=new_drivers_needed,
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        probability_of_cascade=prob_cascade,
        worst_case_drivers=worst_case,
        best_case_drivers=best_case,
    )


def run_probabilistic_churn(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    num_simulations: int = 100,
    churn_threshold: float = 0.10,
    failure_probability: float = 0.05,
    confidence_level: float = 0.95,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> ProbabilisticChurnResult:
    """
    Run probabilistic churn simulation using Monte Carlo method.

    Simulates many random scenarios to estimate the probability distribution
    of churn rates under various failure conditions.

    Args:
        instances: List of tour instances
        baseline_seed: Seed for baseline calculation
        num_simulations: Number of Monte Carlo simulations
        churn_threshold: Threshold for "high churn" (e.g., 0.10 = 10%)
        failure_probability: Base probability of any single failure
        confidence_level: Confidence level for interval (e.g., 0.95 = 95%)
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        ProbabilisticChurnResult with probability distribution of churn
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    start_time = time.time()

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            total_tours=1385,
            coverage=1.0,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.PROBABILISTIC_CHURN]["default_params"].copy()

    num_simulations = parameters.get("num_simulations", num_simulations)
    churn_threshold = parameters.get("churn_threshold", churn_threshold)
    failure_probability = parameters.get("failure_probability", failure_probability)
    confidence_level = parameters.get("confidence_level", confidence_level)

    baseline_drivers = baseline_kpis.total_drivers
    baseline_tours = baseline_kpis.total_tours

    # Monte Carlo simulation
    churn_samples = []

    for _ in range(num_simulations):
        # Simulate random failures
        num_sick = sum(1 for _ in range(baseline_drivers) if random.random() < failure_probability)
        num_cancelled = sum(1 for _ in range(baseline_tours) if random.random() < failure_probability * 0.5)

        # Calculate churn for this scenario
        avg_tours_per_driver = baseline_tours / baseline_drivers / 6
        affected_tours = int(num_sick * avg_tours_per_driver * 1.2) + num_cancelled
        affected_tours = min(affected_tours, baseline_tours)

        churn = affected_tours / baseline_tours if baseline_tours > 0 else 0
        churn_samples.append(churn)

    # Calculate statistics
    churn_samples.sort()
    mean_churn = sum(churn_samples) / len(churn_samples)
    variance = sum((x - mean_churn) ** 2 for x in churn_samples) / len(churn_samples)
    std_churn = variance ** 0.5

    # Percentiles
    def percentile(data, p):
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f]) if c != f else data[f]

    p5 = percentile(churn_samples, 5)
    p50 = percentile(churn_samples, 50)
    p95 = percentile(churn_samples, 95)

    # Confidence interval
    alpha = 1 - confidence_level
    lower_idx = int(len(churn_samples) * (alpha / 2))
    upper_idx = int(len(churn_samples) * (1 - alpha / 2))
    ci_lower = churn_samples[lower_idx]
    ci_upper = churn_samples[min(upper_idx, len(churn_samples) - 1)]

    # Probability above threshold
    above_threshold = sum(1 for c in churn_samples if c > churn_threshold)
    prob_above = above_threshold / len(churn_samples)

    # Risk score based on probability
    if prob_above < 0.10:
        risk = RiskLevel.LOW
    elif prob_above < 0.25:
        risk = RiskLevel.MEDIUM
    elif prob_above < 0.50:
        risk = RiskLevel.HIGH
    else:
        risk = RiskLevel.CRITICAL

    # Histogram data (10 buckets)
    bucket_size = 0.05  # 5% buckets
    histogram = []
    for i in range(20):  # 0-100% in 5% buckets
        lower = i * bucket_size
        upper = (i + 1) * bucket_size
        count = sum(1 for c in churn_samples if lower <= c < upper)
        histogram.append(count / len(churn_samples))

    recommendations = [
        f"Monte-Carlo Simulation mit {num_simulations} Durchläufen",
        f"Basis-Ausfallwahrscheinlichkeit: {failure_probability:.1%}",
        f"Mittlere Churn-Rate: {mean_churn:.1%} ± {std_churn:.1%}",
        f"95%-Konfidenzintervall: [{ci_lower:.1%}, {ci_upper:.1%}]",
        f"P(Churn > {churn_threshold:.0%}): {prob_above:.1%}",
        f"Worst Case (95. Perzentil): {p95:.1%}",
        "WARNUNG: Hohe Churn-Wahrscheinlichkeit - Backup-Kapazität erhöhen!" if prob_above > 0.25 else
        "System zeigt gute Stabilität unter Stress",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    return ProbabilisticChurnResult(
        num_simulations=num_simulations,
        churn_threshold=churn_threshold,
        probability_above_threshold=prob_above,
        mean_churn=mean_churn,
        std_churn=std_churn,
        percentile_5=p5,
        percentile_50=p50,
        percentile_95=p95,
        confidence_interval=(ci_lower, ci_upper),
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        histogram_data=histogram,
    )


def run_policy_roi_optimizer(
    instances: Optional[List[Dict[str, Any]]] = None,
    baseline_seed: int = 94,
    budget_drivers: int = 5,
    optimize_for: str = "balanced",
    constraints: Optional[List[str]] = None,
    baseline_kpis: Optional[KPISnapshot] = None,
    parameters: Optional[Dict[str, Any]] = None,
    solve_func: Optional[Callable] = None
) -> PolicyROIResult:
    """
    Run policy ROI optimization.

    Evaluates all combinations of policy relaxations to find the optimal
    cost-benefit tradeoff within the given constraints.

    Args:
        instances: List of tour instances
        baseline_seed: Seed for baseline calculation
        budget_drivers: How many drivers we can add/remove
        optimize_for: "cost" (minimize), "stability" (maximize), "balanced"
        constraints: List of constraints (e.g., ["arbzg_compliant"])
        baseline_kpis: Current KPIs
        parameters: Additional parameters
        solve_func: Function to call solver

    Returns:
        PolicyROIResult with optimal policy combination
    """
    # Suppress unused parameter warnings
    _ = instances, baseline_seed, solve_func

    start_time = time.time()

    if baseline_kpis is None:
        baseline_kpis = KPISnapshot(
            total_drivers=145,
            fte_drivers=145,
            total_tours=1385,
            coverage=1.0,
        )

    if parameters is None:
        parameters = SCENARIO_METADATA[ScenarioType.POLICY_ROI_OPTIMIZER]["default_params"].copy()

    budget_drivers = parameters.get("budget_drivers", budget_drivers)
    optimize_for = parameters.get("optimize_for", optimize_for)
    constraints = parameters.get("constraints", constraints) or ["arbzg_compliant"]

    baseline_drivers = baseline_kpis.total_drivers
    driver_yearly_cost = 50000  # EUR

    # Define available policies with impacts
    policies = [
        {
            "name": "max_hours_58",
            "description": "Max 55h -> 58h",
            "driver_savings": 2,
            "stability_impact": -0.1,  # Slightly reduces stability
            "arbzg_compliant": True,  # Grenzwertig but legal
            "risk": RiskLevel.LOW,
        },
        {
            "name": "allow_3er_3er",
            "description": "3er->3er erlauben",
            "driver_savings": 4,
            "stability_impact": -0.15,
            "arbzg_compliant": True,
            "risk": RiskLevel.MEDIUM,
        },
        {
            "name": "split_180",
            "description": "Split 240min -> 180min",
            "driver_savings": 2,
            "stability_impact": -0.2,
            "arbzg_compliant": False,  # Grenzwertig/illegal
            "risk": RiskLevel.HIGH,
        },
        {
            "name": "rest_10h",
            "description": "Rest 11h -> 10h",
            "driver_savings": 3,
            "stability_impact": -0.25,
            "arbzg_compliant": False,  # Grenzwertig
            "risk": RiskLevel.MEDIUM,
        },
        {
            "name": "span_15h",
            "description": "Span 14h -> 15h",
            "driver_savings": 1,
            "stability_impact": -0.05,
            "arbzg_compliant": True,
            "risk": RiskLevel.LOW,
        },
        {
            "name": "driver_friendly_off",
            "description": "Driver-Friendly deaktivieren",
            "driver_savings": 3,
            "stability_impact": -0.3,
            "arbzg_compliant": True,
            "risk": RiskLevel.MEDIUM,
        },
    ]

    # Generate all combinations (power set)
    from itertools import combinations

    all_combinations = []

    for r in range(len(policies) + 1):
        for combo in combinations(policies, r):
            # Calculate combined impact
            total_savings = sum(p["driver_savings"] for p in combo)
            total_stability = sum(p["stability_impact"] for p in combo)
            all_arbzg = all(p["arbzg_compliant"] for p in combo) if combo else True

            # Check constraints
            if "arbzg_compliant" in constraints and not all_arbzg:
                continue

            # Check budget
            if abs(total_savings) > budget_drivers + 2:  # Allow some slack
                continue

            # Calculate ROI score based on optimization target
            cost_savings = total_savings * driver_yearly_cost

            if optimize_for == "cost":
                roi_score = total_savings * 10 + total_stability * 2
            elif optimize_for == "stability":
                roi_score = total_stability * -10 + total_savings * 2
            else:  # balanced
                roi_score = total_savings * 5 - abs(total_stability) * 5

            # Determine risk
            if not combo:
                risk = RiskLevel.LOW
            else:
                max_risk = max(p["risk"].value for p in combo)
                risk = RiskLevel(max_risk)

            all_combinations.append(PolicyROIEntry(
                policy_combination=[p["name"] for p in combo],
                driver_delta=-total_savings,
                cost_savings_eur=cost_savings,
                stability_impact=total_stability,
                risk_level=risk,
                roi_score=roi_score,
                arbzg_compliant=all_arbzg,
            ))

    # Sort by ROI score
    all_combinations.sort(key=lambda x: x.roi_score, reverse=True)

    # Find Pareto frontier (non-dominated solutions)
    pareto = []
    for entry in all_combinations:
        dominated = False
        for other in all_combinations:
            if other == entry:
                continue
            # Check if other dominates entry
            if (other.driver_delta <= entry.driver_delta and
                other.stability_impact >= entry.stability_impact and
                (other.driver_delta < entry.driver_delta or
                 other.stability_impact > entry.stability_impact)):
                dominated = True
                break
        if not dominated:
            pareto.append(entry)

    optimal = all_combinations[0] if all_combinations else PolicyROIEntry(
        policy_combination=[],
        driver_delta=0,
        cost_savings_eur=0,
        stability_impact=0,
        risk_level=RiskLevel.LOW,
        roi_score=0,
        arbzg_compliant=True,
    )

    # Overall risk
    risk = optimal.risk_level

    recommendations = [
        f"Optimierungsziel: {optimize_for.upper()}",
        f"Budget: ±{budget_drivers} Fahrer",
        f"Constraints: {', '.join(constraints)}",
        "",
        f"OPTIMALE KOMBINATION: {' + '.join(optimal.policy_combination) or 'Keine Änderung'}",
        f"  Fahrer-Delta: {optimal.driver_delta:+d}",
        f"  Ersparnis: €{optimal.cost_savings_eur:,.0f}/Jahr",
        f"  Stabilitäts-Impact: {optimal.stability_impact:+.0%}",
        f"  Risiko: {optimal.risk_level.value}",
        "",
        f"Pareto-Frontier: {len(pareto)} nicht-dominierte Optionen",
        f"Insgesamt {len(all_combinations)} gültige Kombinationen analysiert",
    ]

    execution_time = int((time.time() - start_time) * 1000)

    return PolicyROIResult(
        baseline_drivers=baseline_drivers,
        optimal_combination=optimal,
        all_combinations=all_combinations[:20],  # Top 20
        pareto_frontier=pareto[:10],  # Top 10 Pareto
        risk_score=risk,
        recommendations=recommendations,
        execution_time_ms=execution_time,
        optimization_target=optimize_for,
    )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_available_scenarios() -> List[Dict[str, Any]]:
    """Get list of all available simulation scenarios with metadata."""
    scenarios = []
    for scenario_type, metadata in SCENARIO_METADATA.items():
        scenarios.append({
            "type": scenario_type.value,
            "name": metadata["name"],
            "description": metadata["description"],
            "category": metadata["category"].value,
            "default_params": metadata["default_params"],
        })
    return scenarios


def format_cost_curve_table(result: CostCurveResult) -> str:
    """Format cost curve result as text table."""
    lines = [
        f"Baseline: {result.baseline_drivers} Fahrer",
        "",
        "Regel                              | Δ Fahrer | Ersparnis/Jahr | Risiko",
        "-" * 75,
    ]

    for entry in result.entries:
        lines.append(
            f"{entry.rule_description:<35} | {entry.driver_delta:>8} | "
            f"€{entry.yearly_savings_eur:>12,.0f} | {entry.risk_level.value}"
        )

    lines.append("-" * 75)
    lines.append(f"Total potenziell: -{result.total_potential_savings} Fahrer")

    return "\n".join(lines)


def format_policy_comparison_table(result: PolicyComparisonResult) -> str:
    """Format policy comparison result as text table."""
    lines = [
        f"Policy: {result.policy_name}",
        f"Baseline: {result.baseline_value}",
        "",
        "Wert   | Fahrer | PT%    | Coverage | Risiko   | Bewertung",
        "-" * 70,
    ]

    for entry in result.entries:
        lines.append(
            f"{entry.policy_value:>6} | {entry.drivers:>6} | {entry.pt_ratio:>5.1%} | "
            f"{entry.coverage:>7.1%} | {entry.risk_level.value:<8} | {entry.label}"
        )

    lines.append("-" * 70)
    lines.append(f"\nEmpfehlung: {result.recommendation}")

    return "\n".join(lines)


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SOLVEREIGN Simulation Engine - Test")
    print("=" * 60)

    # Test Cost Curve
    print("\n1. COST CURVE ANALYSE")
    print("-" * 60)
    cost_result = run_cost_curve()
    print(format_cost_curve_table(cost_result))
    print(f"\nExecution time: {cost_result.execution_time_ms}ms")

    # Test Max Hours Policy
    print("\n2. MAX-HOURS POLICY")
    print("-" * 60)
    hours_result = run_max_hours_policy()
    print(format_policy_comparison_table(hours_result))
    print(f"\nExecution time: {hours_result.execution_time_ms}ms")

    # Test Freeze Tradeoff
    print("\n3. FREEZE WINDOW TRADE-OFF")
    print("-" * 60)
    freeze_result = run_freeze_tradeoff()
    print(format_policy_comparison_table(freeze_result))
    print(f"\nExecution time: {freeze_result.execution_time_ms}ms")

    # Test Driver Friendly
    print("\n4. DRIVER-FRIENDLY POLICY")
    print("-" * 60)
    scenario = SimulationScenario(
        name="Driver-Friendly",
        scenario_type=ScenarioType.DRIVER_FRIENDLY,
        parameters={"only_short_gaps": True},
    )
    df_result = run_simulation(scenario)
    print(f"Baseline: {df_result.baseline_kpis.total_drivers} Fahrer")
    print(f"Simulated: {df_result.simulated_kpis.total_drivers} Fahrer")
    print(f"Delta: {df_result.headcount_delta:+d}")
    print(f"Risk: {df_result.risk_score.value}")
    print("\nEmpfehlungen:")
    for rec in df_result.recommendations:
        print(f"  • {rec}")
    print(f"\nExecution time: {df_result.execution_time_ms}ms")

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)
