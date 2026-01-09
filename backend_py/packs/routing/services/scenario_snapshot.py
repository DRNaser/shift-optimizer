"""
SOLVEREIGN Routing Pack - Scenario Snapshot Service
====================================================

This service handles the critical operation of snapshotting teams_daily
into routing_vehicles when a scenario is created.

Key Principle:
- teams_daily is the dispatcher's mutable team assignment for a day
- routing_vehicles is an IMMUTABLE snapshot for a specific scenario
- Changes to teams_daily after scenario creation do NOT affect existing scenarios

The snapshot creates a scenario-bound copy that the solver uses.
This ensures reproducibility and auditability.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """Base exception for snapshot errors."""
    pass


class TenantMismatchError(SnapshotError):
    """Raised when tenant IDs don't match."""
    pass


class SiteMismatchError(SnapshotError):
    """Raised when site IDs don't match."""
    pass


class NoTeamsFoundError(SnapshotError):
    """Raised when no active teams found for the date."""
    pass


class DriverNotAvailableError(SnapshotError):
    """Raised when a driver in a team is not available."""
    pass


@dataclass
class SnapshotResult:
    """Result of a scenario snapshot operation."""
    scenario_id: str
    vehicles_created: int
    teams_snapshotted: List[str]  # List of team IDs
    snapshot_hash: str
    warnings: List[str]
    created_at: datetime


@dataclass
class TeamSnapshot:
    """Snapshot of a single team for routing."""
    team_id: str
    driver_1_id: str
    driver_1_external_id: str
    driver_2_id: Optional[str]
    driver_2_external_id: Optional[str]
    team_size: int
    combined_skills: List[str]
    shift_start_at: datetime
    shift_end_at: datetime
    depot_id: str
    depot_lat: float
    depot_lng: float
    vehicle_id: Optional[str]
    capacity_volume_m3: float
    capacity_weight_kg: float


class ScenarioSnapshotService:
    """
    Service for snapshotting teams_daily into routing_vehicles.

    Usage:
        service = ScenarioSnapshotService(conn)
        result = service.snapshot_teams_to_vehicles(
            tenant_id=1,
            site_id="...",
            plan_date=date(2026, 1, 7),
            scenario_id="..."
        )
    """

    def __init__(self, conn):
        """
        Initialize with database connection.

        Args:
            conn: Database connection (psycopg or asyncpg)
        """
        self.conn = conn

    def snapshot_teams_to_vehicles(
        self,
        tenant_id: int,
        site_id: str,
        plan_date: date,
        scenario_id: str,
        validate_availability: bool = True,
    ) -> SnapshotResult:
        """
        Snapshot teams_daily into routing_vehicles for a scenario.

        This is the core operation that bridges team management and routing.

        Args:
            tenant_id: Tenant ID (must match scenario's tenant)
            site_id: Site/depot ID (must match scenario's site)
            plan_date: Plan date to snapshot teams for
            scenario_id: Target scenario ID
            validate_availability: If True, validate driver availability

        Returns:
            SnapshotResult with created vehicles

        Raises:
            TenantMismatchError: If tenant IDs don't match
            SiteMismatchError: If site IDs don't match
            NoTeamsFoundError: If no active teams found
            DriverNotAvailableError: If a driver is not available
        """
        warnings = []

        # 1. Validate scenario exists and matches tenant/site
        scenario = self._get_and_validate_scenario(
            scenario_id, tenant_id, site_id, plan_date
        )

        # 2. Load active teams for the date
        teams = self._load_active_teams(tenant_id, site_id, plan_date)

        if not teams:
            raise NoTeamsFoundError(
                f"No active teams found for tenant={tenant_id}, "
                f"site={site_id}, date={plan_date}"
            )

        # 3. Validate driver availability (if enabled)
        if validate_availability:
            self._validate_team_availability(teams, tenant_id, site_id, plan_date)

        # 4. Load depot information for each team
        teams_with_depots = self._enrich_teams_with_depots(teams, tenant_id)

        # 5. Create routing_vehicles from teams
        vehicles_created = self._insert_routing_vehicles(
            scenario_id, tenant_id, teams_with_depots
        )

        # 6. Compute snapshot hash for reproducibility
        snapshot_hash = self._compute_snapshot_hash(teams_with_depots)

        # 7. Record in team_history (for V2 stability)
        self._record_team_history(teams_with_depots, tenant_id, site_id, plan_date)

        logger.info(
            "scenario_snapshot_complete",
            extra={
                "scenario_id": scenario_id,
                "tenant_id": tenant_id,
                "site_id": site_id,
                "plan_date": str(plan_date),
                "vehicles_created": vehicles_created,
                "snapshot_hash": snapshot_hash,
            }
        )

        return SnapshotResult(
            scenario_id=scenario_id,
            vehicles_created=vehicles_created,
            teams_snapshotted=[t.team_id for t in teams_with_depots],
            snapshot_hash=snapshot_hash,
            warnings=warnings,
            created_at=datetime.utcnow(),
        )

    def _get_and_validate_scenario(
        self,
        scenario_id: str,
        tenant_id: int,
        site_id: str,
        plan_date: date,
    ) -> Dict[str, Any]:
        """Validate scenario exists and matches tenant/site/date."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT id, tenant_id, site_id, plan_date, vertical
            FROM routing_scenarios
            WHERE id = %s
            """,
            (scenario_id,)
        )
        row = cursor.fetchone()

        if not row:
            raise SnapshotError(f"Scenario {scenario_id} not found")

        scenario = dict(row) if hasattr(row, 'keys') else {
            'id': row[0], 'tenant_id': row[1], 'site_id': row[2],
            'plan_date': row[3], 'vertical': row[4]
        }

        # Validate tenant match
        if scenario['tenant_id'] != tenant_id:
            raise TenantMismatchError(
                f"Scenario tenant_id={scenario['tenant_id']} does not match "
                f"requested tenant_id={tenant_id}"
            )

        # Validate site match
        if str(scenario['site_id']) != str(site_id):
            raise SiteMismatchError(
                f"Scenario site_id={scenario['site_id']} does not match "
                f"requested site_id={site_id}"
            )

        # Validate date match
        scenario_date = scenario['plan_date']
        if isinstance(scenario_date, str):
            scenario_date = datetime.strptime(scenario_date, '%Y-%m-%d').date()

        if scenario_date != plan_date:
            raise SnapshotError(
                f"Scenario plan_date={scenario_date} does not match "
                f"requested plan_date={plan_date}"
            )

        return scenario

    def _load_active_teams(
        self,
        tenant_id: int,
        site_id: str,
        plan_date: date,
    ) -> List[Dict[str, Any]]:
        """Load active teams for the given date."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT
                t.id,
                t.driver_1_id,
                d1.external_id AS driver_1_external_id,
                t.driver_2_id,
                d2.external_id AS driver_2_external_id,
                t.team_size,
                t.combined_skills,
                t.shift_start_at,
                t.shift_end_at,
                t.depot_id,
                t.vehicle_id,
                t.capacity_volume_m3,
                t.capacity_weight_kg
            FROM teams_daily t
            JOIN drivers d1 ON t.driver_1_id = d1.id
            LEFT JOIN drivers d2 ON t.driver_2_id = d2.id
            WHERE t.tenant_id = %s
              AND t.site_id = %s
              AND t.plan_date = %s
              AND t.is_active = TRUE
            ORDER BY t.created_at
            """,
            (tenant_id, site_id, plan_date)
        )

        rows = cursor.fetchall()
        teams = []

        for row in rows:
            if hasattr(row, 'keys'):
                teams.append(dict(row))
            else:
                teams.append({
                    'id': row[0],
                    'driver_1_id': row[1],
                    'driver_1_external_id': row[2],
                    'driver_2_id': row[3],
                    'driver_2_external_id': row[4],
                    'team_size': row[5],
                    'combined_skills': row[6] or [],
                    'shift_start_at': row[7],
                    'shift_end_at': row[8],
                    'depot_id': row[9],
                    'vehicle_id': row[10],
                    'capacity_volume_m3': row[11],
                    'capacity_weight_kg': row[12],
                })

        return teams

    def _validate_team_availability(
        self,
        teams: List[Dict[str, Any]],
        tenant_id: int,
        site_id: str,
        plan_date: date,
    ) -> None:
        """Validate that all drivers in teams are available."""
        cursor = self.conn.cursor()

        for team in teams:
            # Check driver 1
            cursor.execute(
                """
                SELECT * FROM validate_team_availability(%s, %s, %s, %s, %s)
                """,
                (tenant_id, site_id, plan_date,
                 team['driver_1_id'], team['driver_2_id'])
            )
            result = cursor.fetchone()

            is_valid = result[0] if result else False
            error_code = result[1] if result and len(result) > 1 else None
            error_message = result[2] if result and len(result) > 2 else None

            if not is_valid:
                raise DriverNotAvailableError(
                    f"Team {team['id']}: {error_code} - {error_message}"
                )

    def _enrich_teams_with_depots(
        self,
        teams: List[Dict[str, Any]],
        tenant_id: int,
    ) -> List[TeamSnapshot]:
        """Add depot lat/lng to teams."""
        cursor = self.conn.cursor()

        # Load all depots for efficiency
        depot_ids = list(set(t['depot_id'] for t in teams))

        cursor.execute(
            """
            SELECT id, lat, lng
            FROM routing_depots
            WHERE id = ANY(%s) AND tenant_id = %s
            """,
            (depot_ids, tenant_id)
        )

        depot_map = {}
        for row in cursor.fetchall():
            if hasattr(row, 'keys'):
                depot_map[str(row['id'])] = (float(row['lat']), float(row['lng']))
            else:
                depot_map[str(row[0])] = (float(row[1]), float(row[2]))

        # Build TeamSnapshot objects
        snapshots = []
        for team in teams:
            depot_id = str(team['depot_id'])
            lat, lng = depot_map.get(depot_id, (0.0, 0.0))

            snapshots.append(TeamSnapshot(
                team_id=str(team['id']),
                driver_1_id=str(team['driver_1_id']),
                driver_1_external_id=team['driver_1_external_id'],
                driver_2_id=str(team['driver_2_id']) if team['driver_2_id'] else None,
                driver_2_external_id=team.get('driver_2_external_id'),
                team_size=team['team_size'],
                combined_skills=team['combined_skills'] or [],
                shift_start_at=team['shift_start_at'],
                shift_end_at=team['shift_end_at'],
                depot_id=depot_id,
                depot_lat=lat,
                depot_lng=lng,
                vehicle_id=team.get('vehicle_id'),
                capacity_volume_m3=float(team['capacity_volume_m3'] or 20.0),
                capacity_weight_kg=float(team['capacity_weight_kg'] or 1000.0),
            ))

        return snapshots

    def _insert_routing_vehicles(
        self,
        scenario_id: str,
        tenant_id: int,
        teams: List[TeamSnapshot],
    ) -> int:
        """Insert teams as routing_vehicles (scenario-bound snapshot)."""
        cursor = self.conn.cursor()

        for team in teams:
            cursor.execute(
                """
                INSERT INTO routing_vehicles (
                    scenario_id,
                    tenant_id,
                    external_id,
                    team_size,
                    skills,
                    shift_start_at,
                    shift_end_at,
                    start_depot_id,
                    end_depot_id,
                    capacity_volume_m3,
                    capacity_weight_kg
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    scenario_id,
                    tenant_id,
                    team.vehicle_id or team.team_id,  # Use vehicle_id if set
                    team.team_size,
                    team.combined_skills,
                    team.shift_start_at,
                    team.shift_end_at,
                    team.depot_id,
                    team.depot_id,  # Same depot for start/end in V1
                    team.capacity_volume_m3,
                    team.capacity_weight_kg,
                )
            )

        self.conn.commit()
        return len(teams)

    def _compute_snapshot_hash(self, teams: List[TeamSnapshot]) -> str:
        """Compute hash of snapshot for reproducibility tracking."""
        # Sort teams by ID for deterministic hash
        sorted_teams = sorted(teams, key=lambda t: t.team_id)

        # Build canonical string
        parts = []
        for t in sorted_teams:
            parts.append(
                f"{t.team_id}:{t.driver_1_external_id}:{t.driver_2_external_id or ''}:"
                f"{t.team_size}:{','.join(sorted(t.combined_skills))}:"
                f"{t.shift_start_at.isoformat()}:{t.shift_end_at.isoformat()}:"
                f"{t.depot_id}"
            )

        canonical = "|".join(parts)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _record_team_history(
        self,
        teams: List[TeamSnapshot],
        tenant_id: int,
        site_id: str,
        plan_date: date,
    ) -> None:
        """Record team history for V2 stability tracking."""
        cursor = self.conn.cursor()

        for team in teams:
            # Determine team type
            if team.team_size == 1:
                team_type = 'SOLO'
            elif 'ELEKTRO' in team.combined_skills:
                team_type = 'DUO_ELEKTRO'
            elif 'MONTAGE_ADVANCED' in team.combined_skills:
                team_type = 'DUO_ADVANCED'
            else:
                team_type = 'DUO_STANDARD'

            cursor.execute(
                """
                INSERT INTO team_history (
                    tenant_id, site_id, plan_date,
                    driver_1_id, driver_1_external_id,
                    driver_2_id, driver_2_external_id,
                    team_type, combined_skills, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SNAPSHOT'
                )
                ON CONFLICT DO NOTHING
                """,
                (
                    tenant_id, site_id, plan_date,
                    team.driver_1_id, team.driver_1_external_id,
                    team.driver_2_id, team.driver_2_external_id,
                    team_type, team.combined_skills,
                )
            )

        self.conn.commit()


# =============================================================================
# ASYNC VERSION (for FastAPI)
# =============================================================================

class AsyncScenarioSnapshotService:
    """Async version of ScenarioSnapshotService for FastAPI."""

    def __init__(self, conn):
        self.conn = conn

    async def snapshot_teams_to_vehicles(
        self,
        tenant_id: int,
        site_id: str,
        plan_date: date,
        scenario_id: str,
        validate_availability: bool = True,
    ) -> SnapshotResult:
        """Async version of snapshot_teams_to_vehicles."""
        warnings = []

        # 1. Validate scenario
        scenario = await self._get_and_validate_scenario(
            scenario_id, tenant_id, site_id, plan_date
        )

        # 2. Load active teams
        teams = await self._load_active_teams(tenant_id, site_id, plan_date)

        if not teams:
            raise NoTeamsFoundError(
                f"No active teams found for tenant={tenant_id}, "
                f"site={site_id}, date={plan_date}"
            )

        # 3. Validate availability
        if validate_availability:
            await self._validate_team_availability(
                teams, tenant_id, site_id, plan_date
            )

        # 4. Enrich with depots
        teams_with_depots = await self._enrich_teams_with_depots(teams, tenant_id)

        # 5. Insert vehicles
        vehicles_created = await self._insert_routing_vehicles(
            scenario_id, tenant_id, teams_with_depots
        )

        # 6. Compute hash
        snapshot_hash = self._compute_snapshot_hash(teams_with_depots)

        # 7. Record history
        await self._record_team_history(
            teams_with_depots, tenant_id, site_id, plan_date
        )

        return SnapshotResult(
            scenario_id=scenario_id,
            vehicles_created=vehicles_created,
            teams_snapshotted=[t.team_id for t in teams_with_depots],
            snapshot_hash=snapshot_hash,
            warnings=warnings,
            created_at=datetime.utcnow(),
        )

    async def _get_and_validate_scenario(
        self, scenario_id: str, tenant_id: int, site_id: str, plan_date: date
    ) -> Dict[str, Any]:
        """Async validate scenario."""
        row = await self.conn.fetchrow(
            """
            SELECT id, tenant_id, site_id, plan_date, vertical
            FROM routing_scenarios
            WHERE id = $1
            """,
            scenario_id
        )

        if not row:
            raise SnapshotError(f"Scenario {scenario_id} not found")

        if row['tenant_id'] != tenant_id:
            raise TenantMismatchError(
                f"Scenario tenant mismatch: {row['tenant_id']} != {tenant_id}"
            )

        if str(row['site_id']) != str(site_id):
            raise SiteMismatchError(
                f"Scenario site mismatch: {row['site_id']} != {site_id}"
            )

        return dict(row)

    async def _load_active_teams(
        self, tenant_id: int, site_id: str, plan_date: date
    ) -> List[Dict[str, Any]]:
        """Async load active teams."""
        rows = await self.conn.fetch(
            """
            SELECT
                t.id,
                t.driver_1_id,
                d1.external_id AS driver_1_external_id,
                t.driver_2_id,
                d2.external_id AS driver_2_external_id,
                t.team_size,
                t.combined_skills,
                t.shift_start_at,
                t.shift_end_at,
                t.depot_id,
                t.vehicle_id,
                t.capacity_volume_m3,
                t.capacity_weight_kg
            FROM teams_daily t
            JOIN drivers d1 ON t.driver_1_id = d1.id
            LEFT JOIN drivers d2 ON t.driver_2_id = d2.id
            WHERE t.tenant_id = $1
              AND t.site_id = $2
              AND t.plan_date = $3
              AND t.is_active = TRUE
            ORDER BY t.created_at
            """,
            tenant_id, site_id, plan_date
        )
        return [dict(r) for r in rows]

    async def _validate_team_availability(
        self, teams: List[Dict], tenant_id: int, site_id: str, plan_date: date
    ) -> None:
        """Async validate availability."""
        for team in teams:
            row = await self.conn.fetchrow(
                "SELECT * FROM validate_team_availability($1, $2, $3, $4, $5)",
                tenant_id, site_id, plan_date,
                team['driver_1_id'], team.get('driver_2_id')
            )
            if row and not row[0]:
                raise DriverNotAvailableError(
                    f"Team {team['id']}: {row[1]} - {row[2]}"
                )

    async def _enrich_teams_with_depots(
        self, teams: List[Dict], tenant_id: int
    ) -> List[TeamSnapshot]:
        """Async enrich with depots."""
        depot_ids = list(set(str(t['depot_id']) for t in teams))

        rows = await self.conn.fetch(
            """
            SELECT id, lat, lng
            FROM routing_depots
            WHERE id = ANY($1) AND tenant_id = $2
            """,
            depot_ids, tenant_id
        )

        depot_map = {str(r['id']): (float(r['lat']), float(r['lng'])) for r in rows}

        snapshots = []
        for team in teams:
            depot_id = str(team['depot_id'])
            lat, lng = depot_map.get(depot_id, (0.0, 0.0))

            snapshots.append(TeamSnapshot(
                team_id=str(team['id']),
                driver_1_id=str(team['driver_1_id']),
                driver_1_external_id=team['driver_1_external_id'],
                driver_2_id=str(team['driver_2_id']) if team.get('driver_2_id') else None,
                driver_2_external_id=team.get('driver_2_external_id'),
                team_size=team['team_size'],
                combined_skills=team.get('combined_skills') or [],
                shift_start_at=team['shift_start_at'],
                shift_end_at=team['shift_end_at'],
                depot_id=depot_id,
                depot_lat=lat,
                depot_lng=lng,
                vehicle_id=team.get('vehicle_id'),
                capacity_volume_m3=float(team.get('capacity_volume_m3') or 20.0),
                capacity_weight_kg=float(team.get('capacity_weight_kg') or 1000.0),
            ))

        return snapshots

    async def _insert_routing_vehicles(
        self, scenario_id: str, tenant_id: int, teams: List[TeamSnapshot]
    ) -> int:
        """Async insert routing vehicles."""
        for team in teams:
            await self.conn.execute(
                """
                INSERT INTO routing_vehicles (
                    scenario_id, tenant_id, external_id, team_size, skills,
                    shift_start_at, shift_end_at,
                    start_depot_id, end_depot_id,
                    capacity_volume_m3, capacity_weight_kg
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                scenario_id, tenant_id,
                team.vehicle_id or team.team_id,
                team.team_size, team.combined_skills,
                team.shift_start_at, team.shift_end_at,
                team.depot_id, team.depot_id,
                team.capacity_volume_m3, team.capacity_weight_kg
            )
        return len(teams)

    def _compute_snapshot_hash(self, teams: List[TeamSnapshot]) -> str:
        """Compute snapshot hash (same as sync version)."""
        sorted_teams = sorted(teams, key=lambda t: t.team_id)
        parts = []
        for t in sorted_teams:
            parts.append(
                f"{t.team_id}:{t.driver_1_external_id}:{t.driver_2_external_id or ''}:"
                f"{t.team_size}:{','.join(sorted(t.combined_skills))}:"
                f"{t.shift_start_at.isoformat()}:{t.shift_end_at.isoformat()}:"
                f"{t.depot_id}"
            )
        canonical = "|".join(parts)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def _record_team_history(
        self, teams: List[TeamSnapshot], tenant_id: int, site_id: str, plan_date: date
    ) -> None:
        """Async record team history."""
        for team in teams:
            if team.team_size == 1:
                team_type = 'SOLO'
            elif 'ELEKTRO' in team.combined_skills:
                team_type = 'DUO_ELEKTRO'
            elif 'MONTAGE_ADVANCED' in team.combined_skills:
                team_type = 'DUO_ADVANCED'
            else:
                team_type = 'DUO_STANDARD'

            await self.conn.execute(
                """
                INSERT INTO team_history (
                    tenant_id, site_id, plan_date,
                    driver_1_id, driver_1_external_id,
                    driver_2_id, driver_2_external_id,
                    team_type, combined_skills, created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'SNAPSHOT')
                ON CONFLICT DO NOTHING
                """,
                tenant_id, site_id, plan_date,
                team.driver_1_id, team.driver_1_external_id,
                team.driver_2_id, team.driver_2_external_id,
                team_type, team.combined_skills
            )
