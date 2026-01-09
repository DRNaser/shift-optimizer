# =============================================================================
# SOLVEREIGN Routing Pack - Evidence Pack Writer
# =============================================================================
# Creates structured evidence packages for compliance and audit trails.
#
# Evidence Pack Contents:
# 1. metadata.json - Plan ID, hashes, timestamps, solver config
# 2. input_summary.json - Stops, vehicles, depots summary
# 3. routes.json - Full route assignments with ETAs
# 4. unassigned.json - Unassigned stops with reasons
# 5. audit_results.json - All audit check results
# 6. kpis.json - Key performance indicators
# 7. routes.csv - Flat export for Excel/BI tools
# =============================================================================

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from ..audit.route_auditor import AuditResult

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class InputEvidence:
    """Evidence for solver inputs."""
    scenario_id: str
    tenant_id: int
    vertical: str
    plan_date: str
    total_stops: int
    total_vehicles: int
    total_depots: int
    stops_by_category: Dict[str, int] = field(default_factory=dict)
    vehicles_by_team_size: Dict[int, int] = field(default_factory=dict)
    input_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteStopEvidence:
    """Evidence for a single stop in a route."""
    sequence_index: int
    stop_id: str
    order_id: str
    address: str
    arrival_at: str
    departure_at: str
    tw_start: str
    tw_end: str
    tw_is_hard: bool
    service_duration_min: int
    slack_minutes: int
    skills_required: List[str]
    requires_two_person: bool


@dataclass
class RouteEvidence:
    """Evidence for a single vehicle route."""
    vehicle_id: str
    vehicle_external_id: str
    depot_start: str
    depot_end: str
    shift_start: str
    shift_end: str
    total_stops: int
    total_distance_km: float
    total_duration_min: int
    route_start: str
    route_end: str
    stops: List[RouteStopEvidence] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k != 'stops'},
            'stops': [asdict(s) for s in self.stops]
        }


@dataclass
class UnassignedEvidence:
    """Evidence for an unassigned stop."""
    stop_id: str
    order_id: str
    address: str
    reason_code: str
    reason_details: str
    tw_start: str
    tw_end: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KPIEvidence:
    """Evidence for plan KPIs."""
    total_stops: int
    assigned_stops: int
    unassigned_stops: int
    coverage_percentage: float
    total_vehicles_used: int
    total_vehicles_available: int
    vehicle_utilization_percentage: float
    total_distance_km: float
    total_duration_min: int
    avg_stops_per_vehicle: float
    on_time_percentage: float
    hard_tw_violations: int
    soft_tw_violations: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvidence:
    """Evidence for audit results."""
    audited_at: str
    all_passed: bool
    checks_run: int
    checks_passed: int
    checks_warned: int
    checks_failed: int
    results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_audit_result(cls, result: AuditResult) -> "AuditEvidence":
        return cls(
            audited_at=result.audited_at.isoformat(),
            all_passed=result.all_passed,
            checks_run=result.checks_run,
            checks_passed=result.checks_passed,
            checks_warned=result.checks_warned,
            checks_failed=result.checks_failed,
            results={k.value: v.to_dict() for k, v in result.results.items()}
        )


@dataclass
class RoutingEvidence:
    """
    Evidence for routing provider chain.

    Tracks matrix version, OSRM validation, and finalize verdict.
    Critical for reproducibility and drift analysis.
    """
    # Matrix version tracking
    matrix_version: str
    matrix_hash: str

    # OSRM validation info
    osrm_enabled: bool
    osrm_map_hash: Optional[str] = None
    osrm_profile: Optional[str] = None

    # Finalize verdict
    finalize_verdict: str = "N/A"  # OK / WARN / BLOCK / N/A
    finalize_time_seconds: float = 0.0

    # Drift summary
    drift_p95_ratio: Optional[float] = None
    drift_max_ratio: Optional[float] = None
    drift_mean_ratio: Optional[float] = None

    # TW validation summary
    tw_violations_count: int = 0
    tw_max_violation_seconds: int = 0

    # Timeout/fallback rates
    timeout_rate: float = 0.0
    fallback_rate: float = 0.0
    total_legs: int = 0

    # Artifact references (for cloud storage)
    drift_report_artifact_id: Optional[str] = None
    fallback_report_artifact_id: Optional[str] = None
    tw_validation_artifact_id: Optional[str] = None

    # Verdict reasons (if WARN or BLOCK)
    verdict_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "matrix": {
                "version": self.matrix_version,
                "hash": self.matrix_hash,
            },
            "osrm": {
                "enabled": self.osrm_enabled,
                "map_hash": self.osrm_map_hash,
                "profile": self.osrm_profile,
            },
            "finalize": {
                "verdict": self.finalize_verdict,
                "time_seconds": round(self.finalize_time_seconds, 3),
                "verdict_reasons": self.verdict_reasons,
            },
            "drift": {
                "p95_ratio": self.drift_p95_ratio,
                "max_ratio": self.drift_max_ratio,
                "mean_ratio": self.drift_mean_ratio,
            },
            "tw_validation": {
                "violations_count": self.tw_violations_count,
                "max_violation_seconds": self.tw_max_violation_seconds,
            },
            "rates": {
                "timeout_rate": round(self.timeout_rate, 4),
                "fallback_rate": round(self.fallback_rate, 4),
                "total_legs": self.total_legs,
            },
            "artifacts": {
                "drift_report": self.drift_report_artifact_id,
                "fallback_report": self.fallback_report_artifact_id,
                "tw_validation": self.tw_validation_artifact_id,
            },
        }

    @classmethod
    def from_finalize_result(
        cls,
        matrix_version: str,
        matrix_hash: str,
        finalize_result: Any,  # FinalizeResult from osrm_finalize
        osrm_enabled: bool = True,
        osrm_profile: str = "car",
    ) -> "RoutingEvidence":
        """
        Create RoutingEvidence from FinalizeResult.

        Args:
            matrix_version: Version ID of static matrix
            matrix_hash: Content hash of static matrix
            finalize_result: Result from OSRMFinalizeStage.finalize()
            osrm_enabled: Whether OSRM was used
            osrm_profile: OSRM routing profile
        """
        drift_report = finalize_result.drift_report
        tw_validation = finalize_result.tw_validation
        fallback_report = finalize_result.fallback_report

        return cls(
            matrix_version=matrix_version,
            matrix_hash=matrix_hash,
            osrm_enabled=osrm_enabled,
            osrm_map_hash=drift_report.osrm_map_hash if drift_report else None,
            osrm_profile=osrm_profile,
            finalize_verdict=finalize_result.verdict,
            finalize_time_seconds=finalize_result.finalize_time_seconds,
            drift_p95_ratio=drift_report.p95_ratio if drift_report else None,
            drift_max_ratio=drift_report.max_ratio if drift_report else None,
            drift_mean_ratio=drift_report.mean_ratio if drift_report else None,
            tw_violations_count=tw_validation.violations_count if tw_validation else 0,
            tw_max_violation_seconds=tw_validation.max_violation_seconds if tw_validation else 0,
            timeout_rate=fallback_report.timeout_rate if fallback_report else 0.0,
            fallback_rate=fallback_report.fallback_rate if fallback_report else 0.0,
            total_legs=drift_report.total_legs if drift_report else 0,
            verdict_reasons=finalize_result.verdict_reasons,
        )

    @classmethod
    def without_osrm(cls, matrix_version: str, matrix_hash: str) -> "RoutingEvidence":
        """
        Create RoutingEvidence when OSRM validation is disabled.

        Args:
            matrix_version: Version ID of static matrix
            matrix_hash: Content hash of static matrix
        """
        return cls(
            matrix_version=matrix_version,
            matrix_hash=matrix_hash,
            osrm_enabled=False,
            finalize_verdict="N/A",
        )


@dataclass
class PlanEvidence:
    """Complete plan evidence."""
    plan_id: str
    scenario_id: str
    tenant_id: int
    created_at: str
    status: str
    seed: int
    solver_config_hash: str
    output_hash: str
    locked_at: Optional[str]
    locked_by: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePack:
    """Complete evidence package for a plan."""
    plan: PlanEvidence
    input: InputEvidence
    routes: List[RouteEvidence]
    unassigned: List[UnassignedEvidence]
    audit: AuditEvidence
    kpis: KPIEvidence
    routing: Optional[RoutingEvidence] = None  # NEW: Routing provider chain evidence
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def compute_pack_hash(self) -> str:
        """
        Compute hash of evidence pack for integrity.

        Excludes volatile timestamps (created_at, audited_at, generated_at)
        to ensure same inputs produce same hash.
        """
        # Create stable copies without timestamps
        plan_dict = self.plan.to_dict()
        plan_dict.pop("created_at", None)
        plan_dict.pop("locked_at", None)

        audit_dict = self.audit.to_dict()
        audit_dict.pop("audited_at", None)

        # Include routing evidence (exclude finalize_time_seconds as it's volatile)
        routing_dict = None
        if self.routing:
            routing_dict = self.routing.to_dict()
            routing_dict.get("finalize", {}).pop("time_seconds", None)

        content = json.dumps({
            "plan": plan_dict,
            "input": self.input.to_dict(),
            "routes": [r.to_dict() for r in self.routes],
            "unassigned": [u.to_dict() for u in self.unassigned],
            "audit": audit_dict,
            "kpis": self.kpis.to_dict(),
            "routing": routing_dict,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()


# =============================================================================
# EVIDENCE PACK WRITER
# =============================================================================

class EvidencePackWriter:
    """
    Creates evidence packages for routing plans.

    Evidence packs include:
    - Solver inputs summary
    - Full route assignments
    - Unassigned stops with reasons
    - Audit results
    - KPIs
    - CSV exports for BI tools

    Usage:
        writer = EvidencePackWriter()
        pack = writer.create_evidence_pack(
            plan_id="plan-123",
            scenario_id="scenario-456",
            tenant_id=1,
            stops=stops,
            vehicles=vehicles,
            assignments=assignments,
            unassigned=unassigned,
            audit_result=audit_result,
            seed=42,
            solver_config_hash="abc123"
        )

        # Export to zip
        writer.write_zip(pack, "evidence_plan_123.zip")

        # Export to directory
        writer.write_directory(pack, "/path/to/evidence/")
    """

    def __init__(self, include_csv: bool = True):
        """
        Initialize evidence pack writer.

        Args:
            include_csv: Include CSV exports in the pack
        """
        self.include_csv = include_csv

    def create_evidence_pack(
        self,
        plan_id: str,
        scenario_id: str,
        tenant_id: int,
        vertical: str,
        plan_date: str,
        stops: List[Dict],
        vehicles: List[Dict],
        depots: List[Dict],
        assignments: List[Dict],
        unassigned: List[Dict],
        audit_result: AuditResult,
        seed: int,
        solver_config_hash: str,
        output_hash: str = "",
        plan_status: str = "SOLVED",
        locked_at: Optional[str] = None,
        locked_by: Optional[str] = None,
    ) -> EvidencePack:
        """
        Create complete evidence pack from plan data.

        Args:
            plan_id: The plan ID
            scenario_id: The scenario ID
            tenant_id: Tenant ID
            vertical: Business vertical (MEDIAMARKT, HDL_PLUS)
            plan_date: Plan date (ISO format)
            stops: List of stop dicts
            vehicles: List of vehicle dicts
            depots: List of depot dicts
            assignments: List of assignment dicts
            unassigned: List of unassigned dicts
            audit_result: Audit results
            seed: Solver seed
            solver_config_hash: Config hash
            output_hash: Output hash for reproducibility
            plan_status: Current plan status
            locked_at: Lock timestamp if locked
            locked_by: Who locked the plan

        Returns:
            Complete EvidencePack
        """
        # Build lookups
        stops_by_id = {s["id"]: s for s in stops}
        vehicles_by_id = {v["id"]: v for v in vehicles}
        depots_by_id = {d["id"]: d for d in depots}

        # Group assignments by vehicle
        assignments_by_vehicle: Dict[str, List[Dict]] = {}
        for a in assignments:
            vid = a["vehicle_id"]
            if vid not in assignments_by_vehicle:
                assignments_by_vehicle[vid] = []
            assignments_by_vehicle[vid].append(a)

        # Sort assignments by sequence
        for vid in assignments_by_vehicle:
            assignments_by_vehicle[vid].sort(key=lambda x: x.get("sequence_index", 0))

        # Create input evidence
        input_evidence = self._create_input_evidence(
            scenario_id, tenant_id, vertical, plan_date,
            stops, vehicles, depots
        )

        # Create route evidence
        routes_evidence = self._create_routes_evidence(
            assignments_by_vehicle, stops_by_id, vehicles_by_id, depots_by_id
        )

        # Create unassigned evidence
        unassigned_evidence = self._create_unassigned_evidence(
            unassigned, stops_by_id
        )

        # Create KPI evidence
        kpis_evidence = self._create_kpis_evidence(
            stops, vehicles, assignments, unassigned,
            routes_evidence, audit_result
        )

        # Create plan evidence
        plan_evidence = PlanEvidence(
            plan_id=plan_id,
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            created_at=datetime.now().isoformat(),
            status=plan_status,
            seed=seed,
            solver_config_hash=solver_config_hash,
            output_hash=output_hash,
            locked_at=locked_at,
            locked_by=locked_by,
        )

        # Create audit evidence
        audit_evidence = AuditEvidence.from_audit_result(audit_result)

        return EvidencePack(
            plan=plan_evidence,
            input=input_evidence,
            routes=routes_evidence,
            unassigned=unassigned_evidence,
            audit=audit_evidence,
            kpis=kpis_evidence,
        )

    def _create_input_evidence(
        self,
        scenario_id: str,
        tenant_id: int,
        vertical: str,
        plan_date: str,
        stops: List[Dict],
        vehicles: List[Dict],
        depots: List[Dict],
    ) -> InputEvidence:
        """Create input summary evidence."""
        # Count stops by category
        stops_by_category: Dict[str, int] = {}
        for s in stops:
            cat = s.get("category", "UNKNOWN")
            stops_by_category[cat] = stops_by_category.get(cat, 0) + 1

        # Count vehicles by team size
        vehicles_by_team: Dict[int, int] = {}
        for v in vehicles:
            size = v.get("team_size", 1)
            vehicles_by_team[size] = vehicles_by_team.get(size, 0) + 1

        # Compute input hash
        content = json.dumps({
            "stops": sorted([s["id"] for s in stops]),
            "vehicles": sorted([v["id"] for v in vehicles]),
            "depots": sorted([d["id"] for d in depots]),
        }, sort_keys=True)
        input_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return InputEvidence(
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            vertical=vertical,
            plan_date=plan_date,
            total_stops=len(stops),
            total_vehicles=len(vehicles),
            total_depots=len(depots),
            stops_by_category=stops_by_category,
            vehicles_by_team_size=vehicles_by_team,
            input_hash=input_hash,
        )

    def _create_routes_evidence(
        self,
        assignments_by_vehicle: Dict[str, List[Dict]],
        stops_by_id: Dict[str, Dict],
        vehicles_by_id: Dict[str, Dict],
        depots_by_id: Dict[str, Dict],
    ) -> List[RouteEvidence]:
        """Create route evidence for all vehicles."""
        routes = []

        for vehicle_id, vehicle_assignments in assignments_by_vehicle.items():
            vehicle = vehicles_by_id.get(vehicle_id)
            if not vehicle:
                continue

            # Get depot info
            start_depot = depots_by_id.get(vehicle.get("start_depot_id", ""))
            end_depot = depots_by_id.get(vehicle.get("end_depot_id", ""))

            # Build stop evidence
            stop_evidence_list = []
            total_distance = 0.0
            total_duration = 0

            for a in vehicle_assignments:
                stop = stops_by_id.get(a["stop_id"])
                if not stop:
                    continue

                # Build address string
                addr = stop.get("address", {})
                if isinstance(addr, dict):
                    address_str = f"{addr.get('street', '')} {addr.get('house_number', '')}, {addr.get('postal_code', '')} {addr.get('city', '')}"
                else:
                    address_str = str(addr)

                stop_ev = RouteStopEvidence(
                    sequence_index=a.get("sequence_index", 0),
                    stop_id=a["stop_id"],
                    order_id=stop.get("order_id", ""),
                    address=address_str,
                    arrival_at=self._format_datetime(a.get("arrival_at")),
                    departure_at=self._format_datetime(a.get("departure_at")),
                    tw_start=self._format_datetime(stop.get("tw_start")),
                    tw_end=self._format_datetime(stop.get("tw_end")),
                    tw_is_hard=stop.get("tw_is_hard", True),
                    service_duration_min=stop.get("service_duration_min", 0),
                    slack_minutes=a.get("slack_minutes", 0),
                    skills_required=stop.get("required_skills", []),
                    requires_two_person=stop.get("requires_two_person", False),
                )
                stop_evidence_list.append(stop_ev)

                # Accumulate totals (if available)
                total_duration += stop.get("service_duration_min", 0)

            # Compute route timing
            route_start = ""
            route_end = ""
            if vehicle_assignments:
                route_start = self._format_datetime(vehicle_assignments[0].get("arrival_at"))
                route_end = self._format_datetime(vehicle_assignments[-1].get("departure_at"))

            route_ev = RouteEvidence(
                vehicle_id=vehicle_id,
                vehicle_external_id=vehicle.get("external_id", ""),
                depot_start=start_depot.get("name", "") if start_depot else "",
                depot_end=end_depot.get("name", "") if end_depot else "",
                shift_start=self._format_datetime(vehicle.get("shift_start_at")),
                shift_end=self._format_datetime(vehicle.get("shift_end_at")),
                total_stops=len(stop_evidence_list),
                total_distance_km=total_distance,
                total_duration_min=total_duration,
                route_start=route_start,
                route_end=route_end,
                stops=stop_evidence_list,
            )
            routes.append(route_ev)

        return routes

    def _create_unassigned_evidence(
        self,
        unassigned: List[Dict],
        stops_by_id: Dict[str, Dict],
    ) -> List[UnassignedEvidence]:
        """Create unassigned stops evidence."""
        evidence = []

        for u in unassigned:
            stop = stops_by_id.get(u["stop_id"], {})

            addr = stop.get("address", {})
            if isinstance(addr, dict):
                address_str = f"{addr.get('street', '')} {addr.get('house_number', '')}, {addr.get('postal_code', '')} {addr.get('city', '')}"
            else:
                address_str = str(addr)

            ev = UnassignedEvidence(
                stop_id=u["stop_id"],
                order_id=stop.get("order_id", ""),
                address=address_str,
                reason_code=u.get("reason_code", "UNKNOWN"),
                reason_details=u.get("reason_details", ""),
                tw_start=self._format_datetime(stop.get("tw_start")),
                tw_end=self._format_datetime(stop.get("tw_end")),
            )
            evidence.append(ev)

        return evidence

    def _create_kpis_evidence(
        self,
        stops: List[Dict],
        vehicles: List[Dict],
        assignments: List[Dict],
        unassigned: List[Dict],
        routes: List[RouteEvidence],
        audit_result: AuditResult,
    ) -> KPIEvidence:
        """Create KPI evidence."""
        total_stops = len(stops)
        assigned_stops = len(assignments)
        unassigned_stops = len(unassigned)
        coverage = (assigned_stops / total_stops * 100) if total_stops else 0

        vehicles_used = len(set(a["vehicle_id"] for a in assignments))
        total_vehicles = len(vehicles)
        utilization = (vehicles_used / total_vehicles * 100) if total_vehicles else 0

        total_distance = sum(r.total_distance_km for r in routes)
        total_duration = sum(r.total_duration_min for r in routes)
        avg_stops = (assigned_stops / vehicles_used) if vehicles_used else 0

        # Get TW info from audit
        tw_check = audit_result.results.get("TIME_WINDOW")
        if tw_check:
            on_time = tw_check.details.get("on_time_percentage", 0)
            hard_violations = tw_check.details.get("hard_violations", 0)
            soft_violations = tw_check.details.get("soft_violations", 0)
        else:
            on_time = 100.0
            hard_violations = 0
            soft_violations = 0

        return KPIEvidence(
            total_stops=total_stops,
            assigned_stops=assigned_stops,
            unassigned_stops=unassigned_stops,
            coverage_percentage=round(coverage, 2),
            total_vehicles_used=vehicles_used,
            total_vehicles_available=total_vehicles,
            vehicle_utilization_percentage=round(utilization, 2),
            total_distance_km=round(total_distance, 2),
            total_duration_min=total_duration,
            avg_stops_per_vehicle=round(avg_stops, 2),
            on_time_percentage=round(on_time, 2),
            hard_tw_violations=hard_violations,
            soft_tw_violations=soft_violations,
        )

    def _format_datetime(self, dt: Any) -> str:
        """Format datetime to ISO string."""
        if dt is None:
            return ""
        if isinstance(dt, datetime):
            return dt.isoformat()
        if isinstance(dt, str):
            return dt
        return str(dt)

    # =========================================================================
    # EXPORT METHODS
    # =========================================================================

    def write_zip(self, pack: EvidencePack, output_path: Union[str, Path]) -> Path:
        """
        Write evidence pack to ZIP file.

        Args:
            pack: Evidence pack to export
            output_path: Output ZIP file path

        Returns:
            Path to created ZIP file
        """
        output_path = Path(output_path)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Metadata
            metadata = {
                "pack_hash": pack.compute_pack_hash(),
                "generated_at": pack.generated_at,
                "plan_id": pack.plan.plan_id,
                "scenario_id": pack.plan.scenario_id,
                "tenant_id": pack.plan.tenant_id,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

            # Plan info
            zf.writestr("plan.json", json.dumps(pack.plan.to_dict(), indent=2))

            # Input summary
            zf.writestr("input_summary.json", json.dumps(pack.input.to_dict(), indent=2))

            # Routes
            routes_data = [r.to_dict() for r in pack.routes]
            zf.writestr("routes.json", json.dumps(routes_data, indent=2))

            # Unassigned
            unassigned_data = [u.to_dict() for u in pack.unassigned]
            zf.writestr("unassigned.json", json.dumps(unassigned_data, indent=2))

            # Audit
            zf.writestr("audit_results.json", json.dumps(pack.audit.to_dict(), indent=2))

            # KPIs
            zf.writestr("kpis.json", json.dumps(pack.kpis.to_dict(), indent=2))

            # Routing evidence (if present)
            if pack.routing:
                zf.writestr("routing.json", json.dumps(pack.routing.to_dict(), indent=2))

            # CSV exports
            if self.include_csv:
                zf.writestr("routes.csv", self._routes_to_csv(pack.routes))
                zf.writestr("unassigned.csv", self._unassigned_to_csv(pack.unassigned))

        logger.info(f"Evidence pack written to {output_path}")
        return output_path

    def write_directory(self, pack: EvidencePack, output_dir: Union[str, Path]) -> Path:
        """
        Write evidence pack to directory.

        Args:
            pack: Evidence pack to export
            output_dir: Output directory path

        Returns:
            Path to created directory
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Metadata
        metadata = {
            "pack_hash": pack.compute_pack_hash(),
            "generated_at": pack.generated_at,
            "plan_id": pack.plan.plan_id,
            "scenario_id": pack.plan.scenario_id,
            "tenant_id": pack.plan.tenant_id,
        }
        (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        # Plan info
        (output_dir / "plan.json").write_text(json.dumps(pack.plan.to_dict(), indent=2))

        # Input summary
        (output_dir / "input_summary.json").write_text(json.dumps(pack.input.to_dict(), indent=2))

        # Routes
        routes_data = [r.to_dict() for r in pack.routes]
        (output_dir / "routes.json").write_text(json.dumps(routes_data, indent=2))

        # Unassigned
        unassigned_data = [u.to_dict() for u in pack.unassigned]
        (output_dir / "unassigned.json").write_text(json.dumps(unassigned_data, indent=2))

        # Audit
        (output_dir / "audit_results.json").write_text(json.dumps(pack.audit.to_dict(), indent=2))

        # KPIs
        (output_dir / "kpis.json").write_text(json.dumps(pack.kpis.to_dict(), indent=2))

        # Routing evidence (if present)
        if pack.routing:
            (output_dir / "routing.json").write_text(json.dumps(pack.routing.to_dict(), indent=2))

        # CSV exports
        if self.include_csv:
            (output_dir / "routes.csv").write_text(self._routes_to_csv(pack.routes))
            (output_dir / "unassigned.csv").write_text(self._unassigned_to_csv(pack.unassigned))

        logger.info(f"Evidence pack written to {output_dir}")
        return output_dir

    def _routes_to_csv(self, routes: List[RouteEvidence]) -> str:
        """Convert routes to CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "vehicle_id",
            "vehicle_external_id",
            "sequence",
            "stop_id",
            "order_id",
            "address",
            "arrival",
            "departure",
            "tw_start",
            "tw_end",
            "tw_is_hard",
            "service_min",
            "slack_min",
            "skills",
            "two_person",
        ])

        # Data rows
        for route in routes:
            for stop in route.stops:
                writer.writerow([
                    route.vehicle_id,
                    route.vehicle_external_id,
                    stop.sequence_index,
                    stop.stop_id,
                    stop.order_id,
                    stop.address,
                    stop.arrival_at,
                    stop.departure_at,
                    stop.tw_start,
                    stop.tw_end,
                    "Y" if stop.tw_is_hard else "N",
                    stop.service_duration_min,
                    stop.slack_minutes,
                    ";".join(stop.skills_required),
                    "Y" if stop.requires_two_person else "N",
                ])

        return output.getvalue()

    def _unassigned_to_csv(self, unassigned: List[UnassignedEvidence]) -> str:
        """Convert unassigned to CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "stop_id",
            "order_id",
            "address",
            "reason_code",
            "reason_details",
            "tw_start",
            "tw_end",
        ])

        # Data rows
        for u in unassigned:
            writer.writerow([
                u.stop_id,
                u.order_id,
                u.address,
                u.reason_code,
                u.reason_details,
                u.tw_start,
                u.tw_end,
            ])

        return output.getvalue()
