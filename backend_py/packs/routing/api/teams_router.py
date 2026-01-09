"""
SOLVEREIGN Routing Pack - Teams API Router
==========================================

Minimal endpoints for V1 team management:
- POST /teams_daily/import  - Import teams from CSV/JSON
- GET  /scenarios/{id}/team_requirements - Get requirement hints

These endpoints support the V1 workflow:
1. FLS export -> stops imported
2. GET team_requirements -> shows dispatcher what teams needed
3. Dispatcher creates teams (CSV import or manual)
4. POST import -> teams_daily populated
5. Scenario creation -> snapshot teams to routing_vehicles
"""

import logging
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from math import ceil

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TeamMemberInput(BaseModel):
    """A driver in a team."""
    driver_id: str = Field(..., description="Driver UUID or external_id")
    is_primary: bool = Field(default=True, description="Primary driver (navigator)")


class TeamDailyInput(BaseModel):
    """Input for a single team."""
    driver_1_id: str = Field(..., description="Primary driver ID")
    driver_2_id: Optional[str] = Field(None, description="Secondary driver ID (for 2-person teams)")
    plan_date: str = Field(..., description="Date YYYY-MM-DD")
    site_id: str = Field(..., description="Site/depot UUID")
    shift_start: str = Field(..., description="Shift start ISO8601")
    shift_end: str = Field(..., description="Shift end ISO8601")
    depot_id: str = Field(..., description="Depot UUID")
    vehicle_id: Optional[str] = Field(None, description="Optional vehicle plate/ID")
    capacity_volume_m3: float = Field(default=20.0, ge=0)
    capacity_weight_kg: float = Field(default=1000.0, ge=0)


class TeamsDailyImportRequest(BaseModel):
    """Request to import multiple teams."""
    teams: List[TeamDailyInput]
    overwrite_existing: bool = Field(
        default=False,
        description="If true, delete existing teams for same date/site before import"
    )


class RejectReason(BaseModel):
    """Structured rejection reason."""
    team_index: int
    error_code: str
    message: str
    driver_id: Optional[str] = None


class TeamsDailyImportResponse(BaseModel):
    """Response from team import."""
    imported_count: int
    rejected_count: int
    rejected_teams: List[RejectReason]
    warnings: List[str]


class TeamRequirementResponse(BaseModel):
    """Team requirements derived from stops."""
    total_stops: int
    # Minimum teams needed by type
    min_two_person_teams: int
    min_elektro_teams: int
    min_entsorgung_teams: int
    min_montage_advanced_teams: int
    # Detailed breakdown
    stops_requiring_two_person: int
    stops_requiring_elektro: int
    stops_requiring_entsorgung: int
    stops_requiring_montage_advanced: int
    # Delivery vs Montage split
    delivery_stops: int
    montage_stops: int
    # Recommended capacity
    recommended_solo_teams: int
    recommended_duo_teams: int
    # Human-readable hint
    hint_text: str
    hint_text_de: str


# =============================================================================
# CAPACITY ASSUMPTIONS (configurable per vertical)
# =============================================================================

# Average stops per team per day (conservative for pilot)
STOPS_PER_TEAM_DELIVERY = 15  # Solo team doing deliveries
STOPS_PER_TEAM_MONTAGE = 4    # 2-person team doing montage
STOPS_PER_TEAM_ELEKTRO = 3    # Elektro jobs take longer


# =============================================================================
# DEPENDENCY STUBS (replace with actual deps)
# =============================================================================

async def get_db():
    """Placeholder - inject from FastAPI dependencies."""
    raise NotImplementedError("Replace with actual DB dependency")


async def get_current_tenant():
    """Placeholder - inject from FastAPI dependencies."""
    raise NotImplementedError("Replace with actual tenant dependency")


# =============================================================================
# TEAM REQUIREMENT CALCULATION (FIXED)
# =============================================================================

def compute_team_requirements(stops: List[Dict[str, Any]]) -> TeamRequirementResponse:
    """
    Compute team requirements from stops.

    FIXED BUGS:
    - Uses ceil() instead of integer division
    - Returns 0 when demand is 0 (no max(1, ...))
    - Separates montage vs delivery assumptions
    """
    if not stops:
        return TeamRequirementResponse(
            total_stops=0,
            min_two_person_teams=0,
            min_elektro_teams=0,
            min_entsorgung_teams=0,
            min_montage_advanced_teams=0,
            stops_requiring_two_person=0,
            stops_requiring_elektro=0,
            stops_requiring_entsorgung=0,
            stops_requiring_montage_advanced=0,
            delivery_stops=0,
            montage_stops=0,
            recommended_solo_teams=0,
            recommended_duo_teams=0,
            hint_text="No stops to analyze",
            hint_text_de="Keine Stops zur Analyse",
        )

    # Count stops by requirement
    requires_two_person = 0
    requires_elektro = 0
    requires_entsorgung = 0
    requires_montage_advanced = 0
    delivery_stops = 0
    montage_stops = 0

    for stop in stops:
        # Check two-person requirement
        if stop.get('requires_two_person', False):
            requires_two_person += 1

        # Check skills
        skills = stop.get('required_skills', []) or []
        service_code = stop.get('service_code', '') or ''

        if 'ELEKTRO' in skills:
            requires_elektro += 1

        if 'ENTSORGUNG' in skills or service_code.endswith('ENTSORGUNG'):
            requires_entsorgung += 1

        if 'MONTAGE_ADVANCED' in skills:
            requires_montage_advanced += 1

        # Categorize by service type
        if 'MONTAGE' in service_code.upper() or stop.get('requires_two_person'):
            montage_stops += 1
        else:
            delivery_stops += 1

    # Calculate minimum teams needed
    # FIX: Use ceil() and return 0 when demand is 0
    min_two_person = ceil(requires_two_person / STOPS_PER_TEAM_MONTAGE) if requires_two_person > 0 else 0
    min_elektro = ceil(requires_elektro / STOPS_PER_TEAM_ELEKTRO) if requires_elektro > 0 else 0
    min_entsorgung = ceil(requires_entsorgung / STOPS_PER_TEAM_MONTAGE) if requires_entsorgung > 0 else 0
    min_advanced = ceil(requires_montage_advanced / STOPS_PER_TEAM_MONTAGE) if requires_montage_advanced > 0 else 0

    # Recommended team composition
    # Montage stops need 2-person teams
    recommended_duo = max(min_two_person, ceil(montage_stops / STOPS_PER_TEAM_MONTAGE)) if montage_stops > 0 else 0

    # Delivery stops can use solo teams
    recommended_solo = ceil(delivery_stops / STOPS_PER_TEAM_DELIVERY) if delivery_stops > 0 else 0

    # Build hint text
    hint_lines = []
    hint_lines_de = []

    if requires_two_person > 0:
        hint_lines.append(f"Need {min_two_person} 2-person teams for {requires_two_person} stops")
        hint_lines_de.append(f"Mindestens {min_two_person} 2-Mann Teams für {requires_two_person} Stops")

    if requires_elektro > 0:
        hint_lines.append(f"Need {min_elektro} teams with ELEKTRO skill for {requires_elektro} stops")
        hint_lines_de.append(f"Davon {min_elektro} mit ELEKTRO Skill für {requires_elektro} Stops")

    if requires_entsorgung > 0:
        hint_lines.append(f"Need {min_entsorgung} teams for ENTSORGUNG ({requires_entsorgung} stops)")
        hint_lines_de.append(f"Mindestens {min_entsorgung} Teams für ENTSORGUNG ({requires_entsorgung} Stops)")

    if requires_montage_advanced > 0:
        hint_lines.append(f"Need {min_advanced} advanced montage teams ({requires_montage_advanced} stops)")
        hint_lines_de.append(f"Mindestens {min_advanced} Teams für komplexe Montage ({requires_montage_advanced} Stops)")

    if delivery_stops > 0:
        hint_lines.append(f"Recommend {recommended_solo} solo teams for {delivery_stops} deliveries")
        hint_lines_de.append(f"Empfohlen: {recommended_solo} Solo-Teams für {delivery_stops} Lieferungen")

    if not hint_lines:
        hint_lines = ["No special requirements detected"]
        hint_lines_de = ["Keine besonderen Anforderungen"]

    return TeamRequirementResponse(
        total_stops=len(stops),
        min_two_person_teams=min_two_person,
        min_elektro_teams=min_elektro,
        min_entsorgung_teams=min_entsorgung,
        min_montage_advanced_teams=min_advanced,
        stops_requiring_two_person=requires_two_person,
        stops_requiring_elektro=requires_elektro,
        stops_requiring_entsorgung=requires_entsorgung,
        stops_requiring_montage_advanced=requires_montage_advanced,
        delivery_stops=delivery_stops,
        montage_stops=montage_stops,
        recommended_solo_teams=recommended_solo,
        recommended_duo_teams=recommended_duo,
        hint_text="\n".join(hint_lines),
        hint_text_de="\n".join(hint_lines_de),
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/teams_daily/import", response_model=TeamsDailyImportResponse)
async def import_teams_daily(
    request: TeamsDailyImportRequest,
    db=Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """
    Import teams for a given date.

    Validates:
    - Driver existence
    - Driver availability
    - Site matching
    - Shift bounds
    - No duplicate drivers across teams

    Returns structured rejection reasons for any invalid teams.
    """
    imported = 0
    rejected = []
    warnings = []
    seen_drivers: Dict[str, int] = {}  # driver_id -> team_index

    async with db.get_connection() as conn:
        # Optional: Deactivate existing teams if overwrite requested
        # P0 FIX: Use deactivate_teams_for_date() instead of DELETE
        if request.overwrite_existing and request.teams:
            first_team = request.teams[0]
            result = await conn.fetchrow(
                "SELECT deactivate_teams_for_date($1, $2, $3) AS count",
                tenant.tenant_id,
                first_team.site_id,
                first_team.plan_date,
            )
            deactivated_count = result['count'] if result else 0
            if deactivated_count > 0:
                warnings.append(f"Deactivated {deactivated_count} existing teams for {first_team.plan_date}")

        for idx, team in enumerate(request.teams):
            try:
                # Validate driver_1 exists
                d1 = await conn.fetchrow(
                    """
                    SELECT id, site_id, status FROM drivers
                    WHERE tenant_id = $1 AND (id::text = $2 OR external_id = $2)
                    """,
                    tenant.tenant_id, team.driver_1_id
                )
                if not d1:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_NOT_FOUND",
                        message=f"Driver {team.driver_1_id} not found",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                if d1['status'] != 'ACTIVE':
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_NOT_ACTIVE",
                        message=f"Driver {team.driver_1_id} is {d1['status']}",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                driver_1_uuid = d1['id']

                # Check driver not already in another team
                if team.driver_1_id in seen_drivers:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_DUPLICATE",
                        message=f"Driver {team.driver_1_id} already in team {seen_drivers[team.driver_1_id]}",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                # Validate availability
                avail = await conn.fetchrow(
                    """
                    SELECT available, site_id FROM driver_availability_daily
                    WHERE tenant_id = $1 AND driver_id = $2 AND plan_date = $3
                    """,
                    tenant.tenant_id, driver_1_uuid, team.plan_date
                )
                if not avail:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_NO_AVAILABILITY",
                        message=f"No availability record for driver {team.driver_1_id} on {team.plan_date}",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                if not avail['available']:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_NOT_AVAILABLE",
                        message=f"Driver {team.driver_1_id} not available on {team.plan_date}",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                if str(avail['site_id']) != team.site_id:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="DRIVER_1_WRONG_SITE",
                        message=f"Driver {team.driver_1_id} availability is for different site",
                        driver_id=team.driver_1_id,
                    ))
                    continue

                # Validate driver_2 if present
                driver_2_uuid = None
                team_size = 1

                if team.driver_2_id:
                    d2 = await conn.fetchrow(
                        """
                        SELECT id, site_id, status FROM drivers
                        WHERE tenant_id = $1 AND (id::text = $2 OR external_id = $2)
                        """,
                        tenant.tenant_id, team.driver_2_id
                    )
                    if not d2:
                        rejected.append(RejectReason(
                            team_index=idx,
                            error_code="DRIVER_2_NOT_FOUND",
                            message=f"Driver {team.driver_2_id} not found",
                            driver_id=team.driver_2_id,
                        ))
                        continue

                    if d2['status'] != 'ACTIVE':
                        rejected.append(RejectReason(
                            team_index=idx,
                            error_code="DRIVER_2_NOT_ACTIVE",
                            message=f"Driver {team.driver_2_id} is {d2['status']}",
                            driver_id=team.driver_2_id,
                        ))
                        continue

                    driver_2_uuid = d2['id']

                    if team.driver_2_id in seen_drivers:
                        rejected.append(RejectReason(
                            team_index=idx,
                            error_code="DRIVER_2_DUPLICATE",
                            message=f"Driver {team.driver_2_id} already in team {seen_drivers[team.driver_2_id]}",
                            driver_id=team.driver_2_id,
                        ))
                        continue

                    # Check driver_2 availability
                    avail2 = await conn.fetchrow(
                        """
                        SELECT available, site_id FROM driver_availability_daily
                        WHERE tenant_id = $1 AND driver_id = $2 AND plan_date = $3
                        """,
                        tenant.tenant_id, driver_2_uuid, team.plan_date
                    )
                    if not avail2 or not avail2['available']:
                        rejected.append(RejectReason(
                            team_index=idx,
                            error_code="DRIVER_2_NOT_AVAILABLE",
                            message=f"Driver {team.driver_2_id} not available on {team.plan_date}",
                            driver_id=team.driver_2_id,
                        ))
                        continue

                    if str(avail2['site_id']) != team.site_id:
                        rejected.append(RejectReason(
                            team_index=idx,
                            error_code="DRIVER_2_WRONG_SITE",
                            message=f"Driver {team.driver_2_id} availability is for different site",
                            driver_id=team.driver_2_id,
                        ))
                        continue

                    team_size = 2

                # Parse shift times
                try:
                    shift_start = datetime.fromisoformat(team.shift_start.replace('Z', '+00:00'))
                    shift_end = datetime.fromisoformat(team.shift_end.replace('Z', '+00:00'))
                except ValueError as e:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="INVALID_SHIFT_TIME",
                        message=f"Invalid shift time format: {e}",
                    ))
                    continue

                if shift_end <= shift_start:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="INVALID_SHIFT_RANGE",
                        message="Shift end must be after shift start",
                    ))
                    continue

                # P0 FIX: Use upsert_team_daily() for idempotent import
                # This handles ON CONFLICT gracefully
                result = await conn.fetchrow(
                    """
                    SELECT upsert_team_daily(
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
                    ) AS team_id
                    """,
                    tenant.tenant_id, team.site_id, team.plan_date,
                    driver_1_uuid, driver_2_uuid, team_size,
                    shift_start, shift_end,
                    team.depot_id, team.vehicle_id,
                    team.capacity_volume_m3, team.capacity_weight_kg,
                    'IMPORT'
                )

                if not result or not result['team_id']:
                    rejected.append(RejectReason(
                        team_index=idx,
                        error_code="UPSERT_FAILED",
                        message="Failed to create/update team",
                    ))
                    continue

                # Mark drivers as used
                seen_drivers[team.driver_1_id] = idx
                if team.driver_2_id:
                    seen_drivers[team.driver_2_id] = idx

                imported += 1

            except Exception as e:
                logger.exception(f"Failed to import team {idx}")
                rejected.append(RejectReason(
                    team_index=idx,
                    error_code="UNEXPECTED_ERROR",
                    message=str(e),
                ))

    return TeamsDailyImportResponse(
        imported_count=imported,
        rejected_count=len(rejected),
        rejected_teams=rejected,
        warnings=warnings,
    )


@router.get("/scenarios/{scenario_id}/team_requirements", response_model=TeamRequirementResponse)
async def get_team_requirements(
    scenario_id: str,
    db=Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """
    Get team requirements for a scenario based on its stops.

    This endpoint helps dispatchers understand what teams they need
    to create before running the routing solver.

    Returns:
    - Minimum teams by type (2-person, ELEKTRO, etc.)
    - Stop counts by requirement
    - Human-readable hints in EN and DE
    """
    async with db.get_connection() as conn:
        # Verify scenario exists and belongs to tenant
        scenario = await conn.fetchrow(
            """
            SELECT id, tenant_id, site_id FROM routing_scenarios
            WHERE id = $1
            """,
            scenario_id
        )

        if not scenario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scenario {scenario_id} not found"
            )

        if scenario['tenant_id'] != tenant.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Scenario belongs to different tenant"
            )

        # Load stops for scenario
        stops = await conn.fetch(
            """
            SELECT
                id, service_code, requires_two_person, required_skills
            FROM routing_stops
            WHERE scenario_id = $1
            """,
            scenario_id
        )

        stops_list = [dict(s) for s in stops]

    return compute_team_requirements(stops_list)


@router.get("/dates/{plan_date}/teams", response_model=List[Dict[str, Any]])
async def list_teams_for_date(
    plan_date: str,
    site_id: str,
    db=Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """
    List teams for a specific date and site.

    Used by UI to show current team configuration.
    """
    async with db.get_connection() as conn:
        teams = await conn.fetch(
            """
            SELECT
                t.id,
                t.driver_1_id,
                d1.external_id AS driver_1_external_id,
                d1.name AS driver_1_name,
                t.driver_2_id,
                d2.external_id AS driver_2_external_id,
                d2.name AS driver_2_name,
                t.team_size,
                t.combined_skills,
                t.shift_start_at,
                t.shift_end_at,
                t.depot_id,
                t.vehicle_id,
                t.is_active,
                t.created_by,
                t.created_at
            FROM teams_daily t
            JOIN drivers d1 ON t.driver_1_id = d1.id
            LEFT JOIN drivers d2 ON t.driver_2_id = d2.id
            WHERE t.tenant_id = $1
              AND t.site_id = $2
              AND t.plan_date = $3
            ORDER BY t.created_at
            """,
            tenant.tenant_id, site_id, plan_date
        )

        return [dict(t) for t in teams]
