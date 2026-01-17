"""
SOLVEREIGN V3.3a API - Simulations Router
==========================================

What-If simulation endpoints for scenario analysis.
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class SimulationRequest(BaseModel):
    """Request to run a simulation scenario."""
    scenario_type: str = Field(
        ...,
        description="Type of scenario: cost_curve, max_hours_policy, freeze_tradeoff, "
                    "sick_call, tour_cancel, patch_chaos, driver_friendly, headcount_cap"
    )
    name: str = Field("Simulation", description="Display name for this simulation")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Scenario-specific parameters"
    )
    baseline_plan_id: Optional[int] = Field(
        None,
        description="Plan to use as baseline (optional)"
    )


class KPIsResponse(BaseModel):
    """KPI snapshot."""
    total_drivers: int = 0
    fte_drivers: int = 0
    pt_drivers: int = 0
    pt_ratio: float = 0.0
    total_tours: int = 0
    coverage: float = 1.0


class ChurnMetricsResponse(BaseModel):
    """Churn metrics."""
    unchanged: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    churn_rate: float = 0.0
    affected_drivers: int = 0
    affected_tours: int = 0


class SimulationResponse(BaseModel):
    """Response from a simulation run."""
    scenario_type: str
    scenario_name: str
    baseline_kpis: KPIsResponse
    simulated_kpis: KPIsResponse
    delta: Dict[str, Any]
    churn_metrics: ChurnMetricsResponse
    risk_score: str
    recommendations: List[str]
    execution_time_ms: int
    details: Dict[str, Any] = Field(default_factory=dict)


class ScenarioInfo(BaseModel):
    """Information about a simulation scenario type."""
    type: str
    category: str
    name_de: str
    description: str
    description_de: str
    required_params: List[str]


class ScenariosListResponse(BaseModel):
    """List of available scenarios."""
    scenarios: List[ScenarioInfo]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/scenarios", response_model=ScenariosListResponse)
async def list_scenarios(
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    List all available simulation scenarios.

    Returns scenario types with descriptions and required parameters.
    """
    from packs.roster.engine.simulation_engine import ScenarioType, ScenarioCategory

    # Define scenario metadata
    scenarios = [
        ScenarioInfo(
            type="cost_curve",
            category="economic",
            name_de="Regel-Kosten-Analyse",
            description="Cost of each quality rule in drivers",
            description_de="Was kostet jede Qualitaetsregel in Fahrern?",
            required_params=[],
        ),
        ScenarioInfo(
            type="max_hours_policy",
            category="economic",
            name_de="Max-Stunden Policy",
            description="Impact of different weekly hour caps",
            description_de="Was passiert bei 55h -> 52h -> 50h cap?",
            required_params=[],
        ),
        ScenarioInfo(
            type="freeze_tradeoff",
            category="economic",
            name_de="Freeze Window Trade-off",
            description="Stability vs headcount at different freeze windows",
            description_de="Freeze 12h vs 18h vs 24h - Headcount vs Stabilitaet",
            required_params=[],
        ),
        ScenarioInfo(
            type="sick_call",
            category="operational",
            name_de="Krankmeldung Drill",
            description="Impact of driver absences on plan stability",
            description_de="Wenn X Fahrer ausfallen: wie schnell ist Repair verfuegbar?",
            required_params=["num_drivers_out"],
        ),
        ScenarioInfo(
            type="tour_cancel",
            category="operational",
            name_de="Tour-Stornierung",
            description="Impact of tour cancellations on churn",
            description_de="Wenn Touren wegfallen: wie viel Churn?",
            required_params=["num_tours_cancelled"],
        ),
        ScenarioInfo(
            type="patch_chaos",
            category="operational",
            name_de="Patch-Chaos Simulation",
            description="Impact of partial forecast integration",
            description_de="Was passiert wenn Mo/Di fix, Rest kommt spaeter?",
            required_params=["partial_days", "patch_days"],
        ),
        ScenarioInfo(
            type="driver_friendly",
            category="compliance",
            name_de="Fahrer-Freundliche Policy",
            description="Cost of enforcing quality 3er gaps",
            description_de="Was kostet es, wenn 3er nur mit 30-60min Gaps?",
            required_params=[],
        ),
        ScenarioInfo(
            type="headcount_cap",
            category="compliance",
            name_de="Headcount-Budget Analyse",
            description="Which constraints to relax to meet budget?",
            description_de="Wie erreichen wir X Fahrer Ziel?",
            required_params=["target_drivers"],
        ),
    ]

    return ScenariosListResponse(scenarios=scenarios)


@router.post("/run", response_model=SimulationResponse)
async def run_simulation_endpoint(
    request: SimulationRequest,
    db: DatabaseManager = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Run a simulation scenario.

    Supported scenario types:
    - **cost_curve**: Analyze cost of each rule in drivers
    - **max_hours_policy**: Compare 55h vs 52h vs 50h caps
    - **freeze_tradeoff**: Compare freeze windows
    - **sick_call**: Simulate driver absences (requires num_drivers_out)
    - **tour_cancel**: Simulate tour cancellations (requires num_tours_cancelled)
    - **patch_chaos**: Simulate partial forecast (requires partial_days, patch_days)
    - **driver_friendly**: Analyze 3er gap quality costs
    - **headcount_cap**: Find constraint relaxations for budget (requires target_drivers)
    """
    from packs.roster.engine.simulation_engine import (
        run_simulation,
        SimulationScenario,
        ScenarioType,
    )

    # Map string to enum
    scenario_type_map = {
        "cost_curve": ScenarioType.COST_CURVE,
        "max_hours_policy": ScenarioType.MAX_HOURS_POLICY,
        "freeze_tradeoff": ScenarioType.FREEZE_TRADEOFF,
        "sick_call": ScenarioType.SICK_CALL,
        "tour_cancel": ScenarioType.TOUR_CANCEL,
        "patch_chaos": ScenarioType.PATCH_CHAOS,
        "driver_friendly": ScenarioType.DRIVER_FRIENDLY,
        "headcount_cap": ScenarioType.HEADCOUNT_CAP,
    }

    scenario_type = scenario_type_map.get(request.scenario_type.lower())
    if not scenario_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown scenario type: {request.scenario_type}. "
                   f"Valid types: {list(scenario_type_map.keys())}"
        )

    # Create scenario
    scenario = SimulationScenario(
        name=request.name,
        scenario_type=scenario_type,
        parameters=request.parameters,
        baseline_plan_id=request.baseline_plan_id,
    )

    # Run simulation
    result = run_simulation(scenario)

    # Convert to response
    return SimulationResponse(
        scenario_type=request.scenario_type,
        scenario_name=result.scenario.name,
        baseline_kpis=KPIsResponse(
            total_drivers=result.baseline_kpis.total_drivers,
            fte_drivers=result.baseline_kpis.fte_drivers,
            pt_drivers=result.baseline_kpis.pt_drivers,
            pt_ratio=result.baseline_kpis.pt_ratio,
            total_tours=result.baseline_kpis.total_tours,
            coverage=result.baseline_kpis.coverage,
        ),
        simulated_kpis=KPIsResponse(
            total_drivers=result.simulated_kpis.total_drivers,
            fte_drivers=result.simulated_kpis.fte_drivers,
            pt_drivers=result.simulated_kpis.pt_drivers,
            pt_ratio=result.simulated_kpis.pt_ratio,
            total_tours=result.simulated_kpis.total_tours,
            coverage=result.simulated_kpis.coverage,
        ),
        delta=result.delta,
        churn_metrics=ChurnMetricsResponse(
            unchanged=result.churn_metrics.unchanged,
            added=result.churn_metrics.added,
            removed=result.churn_metrics.removed,
            changed=result.churn_metrics.changed,
            churn_rate=result.churn_metrics.churn_rate,
            affected_drivers=result.churn_metrics.affected_drivers,
            affected_tours=result.churn_metrics.affected_tours,
        ),
        risk_score=result.risk_score.value,
        recommendations=result.recommendations,
        execution_time_ms=result.execution_time_ms,
        details=result.details,
    )


@router.post("/compare")
async def compare_simulations(
    scenarios: List[SimulationRequest],
    db: DatabaseManager = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Run multiple simulations and compare results.

    Returns ranked comparison of all scenarios.
    """
    from packs.roster.engine.simulation_engine import (
        run_simulation,
        SimulationScenario,
        ScenarioType,
    )

    scenario_type_map = {
        "cost_curve": ScenarioType.COST_CURVE,
        "max_hours_policy": ScenarioType.MAX_HOURS_POLICY,
        "freeze_tradeoff": ScenarioType.FREEZE_TRADEOFF,
        "sick_call": ScenarioType.SICK_CALL,
        "tour_cancel": ScenarioType.TOUR_CANCEL,
        "patch_chaos": ScenarioType.PATCH_CHAOS,
        "driver_friendly": ScenarioType.DRIVER_FRIENDLY,
        "headcount_cap": ScenarioType.HEADCOUNT_CAP,
    }

    results = []
    for req in scenarios:
        scenario_type = scenario_type_map.get(req.scenario_type.lower())
        if not scenario_type:
            continue

        scenario = SimulationScenario(
            name=req.name,
            scenario_type=scenario_type,
            parameters=req.parameters,
            baseline_plan_id=req.baseline_plan_id,
        )

        result = run_simulation(scenario)
        results.append({
            "name": req.name,
            "scenario_type": req.scenario_type,
            "drivers": result.simulated_kpis.total_drivers,
            "pt_ratio": result.simulated_kpis.pt_ratio,
            "coverage": result.simulated_kpis.coverage,
            "risk_score": result.risk_score.value,
            "recommendations": result.recommendations[:2],
        })

    # Sort by drivers (primary), then PT ratio (secondary)
    results.sort(key=lambda r: (r["drivers"], r["pt_ratio"]))

    return {
        "results": results,
        "best_option": results[0] if results else None,
        "summary": f"Best option: {results[0]['name']} with {results[0]['drivers']} drivers" if results else "No results",
    }
