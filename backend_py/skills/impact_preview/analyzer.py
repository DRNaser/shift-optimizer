"""Impact Preview - Change Impact Analyzer.

Provides risk assessment for configuration, pack, migration, and code changes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Awaitable
from enum import Enum
import json
import hashlib
import re
from pathlib import Path


class RiskLevel(Enum):
    """Risk level classification."""
    SAFE = "SAFE"           # Green - proceed
    CAUTION = "CAUTION"     # Yellow - review
    RISKY = "RISKY"         # Orange - approval needed
    BLOCKED = "BLOCKED"     # Red - policy blocked


class ChangeType(Enum):
    """Type of change being analyzed."""
    CONFIG = "config"
    PACK = "pack"
    MIGRATION = "migration"
    CODE = "code"


@dataclass
class AffectedTenant:
    """Details about an affected tenant."""
    code: str
    name: str
    status: str  # active, pilot, blocked
    active_operations: int = 0
    last_solve_at: Optional[datetime] = None
    packs_enabled: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "name": self.name,
            "status": self.status,
            "active_operations": self.active_operations,
            "last_solve_at": self.last_solve_at.isoformat() if self.last_solve_at else None,
            "packs_enabled": self.packs_enabled,
        }


@dataclass
class ImpactResult:
    """Result of impact analysis."""
    change_id: str
    change_type: ChangeType
    target: str
    action: str

    # Risk assessment
    risk_level: RiskLevel
    risk_score: float  # 0-1

    # Impact scope
    affected_tenants: List[str]
    affected_sites: List[str]
    affected_packs: List[str]

    # Risk matrix (S0-S3 likelihood)
    risk_matrix: Dict[str, float]

    # Recommendations
    recommendations: List[str]
    approval_required: bool
    blocking_reason: Optional[str]

    # Rollback plan
    rollback_steps: List[str]
    rollback_complexity: str  # "trivial", "simple", "complex", "impossible"

    # Generated at
    analyzed_at: datetime

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "change_id": self.change_id,
            "change_type": self.change_type.value,
            "target": self.target,
            "action": self.action,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "affected_tenants": self.affected_tenants,
            "affected_sites": self.affected_sites,
            "affected_packs": self.affected_packs,
            "risk_matrix": self.risk_matrix,
            "recommendations": self.recommendations,
            "approval_required": self.approval_required,
            "blocking_reason": self.blocking_reason,
            "rollback_steps": self.rollback_steps,
            "rollback_complexity": self.rollback_complexity,
            "analyzed_at": self.analyzed_at.isoformat(),
        }

    @property
    def exit_code(self) -> int:
        """Get exit code based on risk level."""
        return {
            RiskLevel.SAFE: 0,
            RiskLevel.CAUTION: 1,
            RiskLevel.RISKY: 2,
            RiskLevel.BLOCKED: 3,
        }[self.risk_level]


class ChangeImpactAnalyzer:
    """Analyzes impact of configuration and code changes."""

    # Solver config targets
    SOLVER_CONFIG_TARGETS = [
        "SOLVER_TIME_LIMIT",
        "SOLVER_SEED",
        "MAX_ITERATIONS",
        "COST_WEIGHTS",
    ]

    # Feature flag targets
    FEATURE_FLAG_TARGETS = [
        "ENABLE_FREEZE_WINDOWS",
        "ENABLE_ROUTING_PACK",
        "ENABLE_ROSTER_PACK",
        "STRICT_RLS_MODE",
    ]

    # Security config targets
    SECURITY_CONFIG_TARGETS = [
        "RATE_LIMIT_",
        "AUTH_",
        "SIGNATURE_",
    ]

    def __init__(
        self,
        state_provider: Optional[Callable[[], Awaitable[Dict]]] = None,
        tenant_provider: Optional[Callable[[str], Awaitable[List[Dict]]]] = None,
        active_ops_provider: Optional[Callable[[str], Awaitable[int]]] = None,
        active_solves_provider: Optional[Callable[[], Awaitable[int]]] = None,
    ):
        """Initialize analyzer.

        Args:
            state_provider: Async function returning system state dict
            tenant_provider: Async function returning tenants using a pack
            active_ops_provider: Async function returning active operation count
            active_solves_provider: Async function returning active solve count
        """
        self._state_provider = state_provider
        self._tenant_provider = tenant_provider
        self._active_ops_provider = active_ops_provider
        self._active_solves_provider = active_solves_provider

    async def _get_state(self) -> Dict:
        """Get current system state."""
        if self._state_provider:
            return await self._state_provider()

        # Default state for standalone testing
        return {
            "tenants": [
                {"code": "gurkerl", "name": "Gurkerl", "status": "active"},
                {"code": "mediamarkt", "name": "MediaMarkt", "status": "active"},
                {"code": "test_tenant", "name": "Test Tenant", "status": "pilot"},
            ],
            "packs": [
                {"name": "routing", "enabled": True, "has_solver": True},
                {"name": "roster", "enabled": True, "has_solver": True},
            ],
            "migrations": {
                "current": "022_replay_protection",
                "pending": [],
            },
            "env_config": {},
            "feature_flags": {},
        }

    async def _get_tenants_using_pack(self, pack_name: str) -> List[Dict]:
        """Get tenants using a specific pack."""
        if self._tenant_provider:
            return await self._tenant_provider(pack_name)

        # Default: all active tenants for known packs
        state = await self._get_state()
        return [t for t in state["tenants"] if t["status"] in ("active", "pilot")]

    async def _count_active_operations(self, pack_name: str) -> int:
        """Count active operations for a pack."""
        if self._active_ops_provider:
            return await self._active_ops_provider(pack_name)
        return 0

    async def _count_active_solves(self) -> int:
        """Count active solve operations."""
        if self._active_solves_provider:
            return await self._active_solves_provider()
        return 0

    async def analyze(
        self,
        change_type: ChangeType,
        target: str,
        action: str = "modify",
        new_value: Optional[Any] = None,
        changed_files: Optional[List[str]] = None,
    ) -> ImpactResult:
        """Analyze impact of a proposed change."""

        change_id = f"CHG_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        # Get current system state
        current_state = await self._get_state()

        # Analyze based on change type
        if change_type == ChangeType.CONFIG:
            impact = await self._analyze_config_change(target, new_value, current_state)
        elif change_type == ChangeType.PACK:
            impact = await self._analyze_pack_change(target, action, current_state)
        elif change_type == ChangeType.MIGRATION:
            impact = await self._analyze_migration(target, current_state)
        elif change_type == ChangeType.CODE:
            impact = await self._analyze_code_change(changed_files or [], current_state)
        else:
            raise ValueError(f"Unknown change type: {change_type}")

        # Calculate overall risk
        risk_level, risk_score = self._calculate_risk(impact)

        # Generate rollback plan
        rollback = self._generate_rollback_plan(change_type, target, action, current_state)

        # Generate recommendations
        recommendations = self._generate_recommendations(impact, risk_level)

        return ImpactResult(
            change_id=change_id,
            change_type=change_type,
            target=target,
            action=action,
            risk_level=risk_level,
            risk_score=risk_score,
            affected_tenants=impact.get("affected_tenants", []),
            affected_sites=impact.get("affected_sites", []),
            affected_packs=impact.get("affected_packs", []),
            risk_matrix=impact.get("risk_matrix", {"S0": 0, "S1": 0, "S2": 0, "S3": 0}),
            recommendations=recommendations,
            approval_required=risk_level in [RiskLevel.RISKY, RiskLevel.BLOCKED],
            blocking_reason=impact.get("blocking_reason"),
            rollback_steps=rollback["steps"],
            rollback_complexity=rollback["complexity"],
            analyzed_at=datetime.now(timezone.utc),
        )

    async def _analyze_config_change(
        self,
        target: str,
        new_value: Any,
        state: Dict,
    ) -> Dict:
        """Analyze impact of config change."""

        impact = {
            "affected_tenants": [],
            "affected_sites": [],
            "affected_packs": [],
            "risk_matrix": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
        }

        # Solver config changes
        if target.startswith("SOLVER_") or target in self.SOLVER_CONFIG_TARGETS:
            # All tenants with active packs are affected
            impact["affected_packs"] = [p["name"] for p in state["packs"] if p.get("enabled")]
            impact["affected_tenants"] = [
                t["code"] for t in state["tenants"] if t["status"] == "active"
            ]

            # Check for active solves
            active_solves = await self._count_active_solves()
            if active_solves > 0:
                impact["risk_matrix"]["S2"] = 0.5  # Medium degraded risk
                impact["active_solves"] = active_solves

            # Determinism check
            if target == "SOLVER_SEED":
                impact["risk_matrix"]["S1"] = 0.3  # Reproducibility risk
                impact["warning"] = "Changing seed affects determinism proof"

        # Feature flag changes
        elif target.startswith("ENABLE_"):
            pack_name = target.replace("ENABLE_", "").replace("_PACK", "").lower()
            impact["affected_packs"] = [pack_name]

            # Find tenants using this pack
            tenants_using_pack = await self._get_tenants_using_pack(pack_name)
            impact["affected_tenants"] = [t["code"] for t in tenants_using_pack]

            if new_value is False:  # Disabling
                if tenants_using_pack:
                    impact["risk_matrix"]["S1"] = 0.7  # High integrity risk
                    impact["blocking_reason"] = (
                        f"Cannot disable pack with {len(tenants_using_pack)} active tenants"
                    )

        # Security config changes
        elif any(target.startswith(prefix) for prefix in self.SECURITY_CONFIG_TARGETS):
            impact["affected_tenants"] = [t["code"] for t in state["tenants"]]
            impact["risk_matrix"]["S0"] = 0.1  # Low security risk
            impact["risk_matrix"]["S1"] = 0.2

        return impact

    async def _analyze_pack_change(
        self,
        pack_name: str,
        action: str,
        state: Dict,
    ) -> Dict:
        """Analyze impact of pack enable/disable."""

        impact = {
            "affected_tenants": [],
            "affected_sites": [],
            "affected_packs": [pack_name],
            "risk_matrix": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
        }

        if action == "disable":
            # Check tenants using pack
            tenants = await self._get_tenants_using_pack(pack_name)
            impact["affected_tenants"] = [t["code"] for t in tenants]

            if tenants:
                # Calculate risk based on tenant count and status
                active_count = sum(1 for t in tenants if t["status"] == "active")
                pilot_count = sum(1 for t in tenants if t["status"] == "pilot")

                if active_count > 0:
                    impact["risk_matrix"]["S0"] = 0.5  # Critical - production impact
                    impact["blocking_reason"] = (
                        f"Cannot disable pack with {active_count} active production tenants"
                    )
                elif pilot_count > 0:
                    impact["risk_matrix"]["S1"] = 0.6
                    impact["warning"] = f"{pilot_count} pilot tenants affected"

            # Check for in-flight operations
            active_ops = await self._count_active_operations(pack_name)
            if active_ops > 0:
                impact["risk_matrix"]["S1"] = max(impact["risk_matrix"]["S1"], 0.4)
                impact["active_operations"] = active_ops

        elif action == "enable":
            # Check if pack is ready
            pack_info = next((p for p in state["packs"] if p["name"] == pack_name), None)
            if not pack_info:
                impact["risk_matrix"]["S1"] = 0.8
                impact["blocking_reason"] = f"Pack {pack_name} does not exist"
            elif not pack_info.get("has_solver"):
                impact["risk_matrix"]["S1"] = 0.8
                impact["blocking_reason"] = f"Pack {pack_name} is not ready (missing solver)"

            # Check migrations
            if state.get("migrations", {}).get("pending"):
                impact["risk_matrix"]["S2"] = 0.5
                impact["warning"] = "Pending migrations may be required"

        return impact

    async def _analyze_migration(
        self,
        file_path: str,
        state: Dict,
    ) -> Dict:
        """Analyze impact of database migration."""

        impact = {
            "affected_tenants": [],
            "affected_sites": [],
            "affected_packs": [],
            "risk_matrix": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
        }

        # Parse migration file
        migration_analysis = self._parse_migration(file_path)

        # Check for table locks
        if migration_analysis.get("has_table_lock"):
            impact["risk_matrix"]["S2"] = 0.6  # Degraded risk
            impact["lock_tables"] = migration_analysis.get("locked_tables", [])

        # Check RLS
        if migration_analysis.get("creates_table") and not migration_analysis.get("has_rls"):
            impact["risk_matrix"]["S0"] = 0.9  # Critical security
            impact["blocking_reason"] = "New table missing RLS policy"

        if migration_analysis.get("creates_table") and not migration_analysis.get("has_tenant_id"):
            impact["risk_matrix"]["S0"] = 0.9
            impact["blocking_reason"] = "New table missing tenant_id column"

        # Check rollback
        if not migration_analysis.get("is_reversible"):
            impact["rollback_warning"] = "Migration is not easily reversible"
            impact["risk_matrix"]["S1"] = max(impact["risk_matrix"]["S1"], 0.4)

        # All tenants affected by schema changes
        impact["affected_tenants"] = [t["code"] for t in state["tenants"]]

        return impact

    def _parse_migration(self, file_path: str) -> Dict:
        """Parse migration file for risk indicators."""

        result = {
            "creates_table": False,
            "has_tenant_id": False,
            "has_rls": False,
            "has_table_lock": False,
            "locked_tables": [],
            "is_reversible": True,
        }

        try:
            path = Path(file_path)
            if not path.exists():
                return result

            content = path.read_text(encoding="utf-8").upper()

            # Check for CREATE TABLE
            if "CREATE TABLE" in content:
                result["creates_table"] = True

                # Check for tenant_id
                if "TENANT_ID" in content:
                    result["has_tenant_id"] = True

                # Check for RLS
                if "ROW LEVEL SECURITY" in content or "ENABLE ROW" in content:
                    result["has_rls"] = True

            # Check for exclusive locks
            if "EXCLUSIVE" in content or "ACCESS EXCLUSIVE" in content:
                result["has_table_lock"] = True
                # Extract table names (simplified)
                for match in re.findall(r"ALTER TABLE\s+(\w+)", content):
                    result["locked_tables"].append(match.lower())

            # Check reversibility
            if "DROP" in content and "CREATE" not in content:
                result["is_reversible"] = False

        except Exception:
            pass

        return result

    async def _analyze_code_change(
        self,
        changed_files: List[str],
        state: Dict,
    ) -> Dict:
        """Analyze impact of code changes."""

        impact = {
            "affected_tenants": [],
            "affected_sites": [],
            "affected_packs": [],
            "risk_matrix": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
        }

        if not changed_files:
            return impact

        # Categorize changed files
        kernel_files = [f for f in changed_files if "api/" in f and "packs/" not in f]
        security_files = [f for f in changed_files if "security/" in f]
        pack_files = {
            "routing": [f for f in changed_files if "packs/routing/" in f],
            "roster": [f for f in changed_files if "v3/" in f or "/src/" in f],
        }

        # Security file changes are highest risk
        if security_files:
            impact["risk_matrix"]["S0"] = 0.3
            impact["risk_matrix"]["S1"] = 0.4
            impact["affected_tenants"] = [t["code"] for t in state["tenants"]]
            impact["security_files"] = security_files

        # Kernel changes affect all tenants
        if kernel_files:
            impact["risk_matrix"]["S1"] = max(impact["risk_matrix"]["S1"], 0.3)
            impact["affected_tenants"] = [t["code"] for t in state["tenants"]]
            impact["kernel_files"] = kernel_files

        # Pack changes only affect that pack
        for pack_name, files in pack_files.items():
            if files:
                impact["affected_packs"].append(pack_name)
                tenants = await self._get_tenants_using_pack(pack_name)
                impact["affected_tenants"].extend([t["code"] for t in tenants])

        # Deduplicate tenants
        impact["affected_tenants"] = list(set(impact["affected_tenants"]))

        return impact

    def _calculate_risk(self, impact: Dict) -> tuple:
        """Calculate overall risk level and score."""

        risk_matrix = impact.get("risk_matrix", {"S0": 0, "S1": 0, "S2": 0, "S3": 0})

        # Weighted score
        weights = {"S0": 10, "S1": 5, "S2": 2, "S3": 1}
        total_weight = sum(weights.values())
        score = sum(risk_matrix.get(s, 0) * weights[s] for s in weights) / total_weight

        # Check for blocking conditions
        if impact.get("blocking_reason"):
            return RiskLevel.BLOCKED, 1.0

        # Check for high S0 risk
        if risk_matrix.get("S0", 0) > 0.5:
            return RiskLevel.BLOCKED, score

        # Check tenant count
        tenant_count = len(impact.get("affected_tenants", []))
        if tenant_count > 5:
            return RiskLevel.RISKY, score
        elif tenant_count > 0:
            if risk_matrix.get("S1", 0) > 0.3:
                return RiskLevel.RISKY, score
            return RiskLevel.CAUTION, score

        if score > 0.3:
            return RiskLevel.CAUTION, score

        return RiskLevel.SAFE, score

    def _generate_rollback_plan(
        self,
        change_type: ChangeType,
        target: str,
        action: str,
        state: Dict,
    ) -> Dict:
        """Generate rollback plan for change."""

        if change_type == ChangeType.CONFIG:
            # Get current value for rollback
            current_value = (
                state.get("env_config", {}).get(target) or
                state.get("feature_flags", {}).get(target) or
                "<previous_value>"
            )
            return {
                "complexity": "trivial",
                "steps": [
                    f"1. Revert config: {target} = {current_value}",
                    "2. Restart affected services",
                    "3. Verify health endpoints",
                    "4. Check active operations",
                ],
            }

        elif change_type == ChangeType.PACK:
            opposite_action = "disable" if action == "enable" else "enable"
            return {
                "complexity": "simple",
                "steps": [
                    f"1. {opposite_action.capitalize()} pack: {target}",
                    "2. Verify pack status in dashboard",
                    "3. Check affected tenants",
                    "4. Run golden path test",
                ],
            }

        elif change_type == ChangeType.MIGRATION:
            rollback_file = target.replace(".sql", "_rollback.sql")
            return {
                "complexity": "complex",
                "steps": [
                    "1. STOP: Do not rollback without DBA approval",
                    f"2. Review rollback script: {rollback_file}",
                    "3. Create database backup",
                    "4. Execute rollback in transaction",
                    "5. Verify schema state",
                    "6. Run RLS harness",
                ],
            }

        elif change_type == ChangeType.CODE:
            return {
                "complexity": "simple",
                "steps": [
                    "1. Revert commit: git revert <commit>",
                    "2. Redeploy previous version",
                    "3. Verify health endpoints",
                    "4. Run smoke tests",
                ],
            }

        return {"complexity": "unknown", "steps": ["Manual rollback required"]}

    def _generate_recommendations(
        self,
        impact: Dict,
        risk_level: RiskLevel,
    ) -> List[str]:
        """Generate recommendations based on impact."""

        recommendations = []

        if risk_level == RiskLevel.BLOCKED:
            blocking_reason = impact.get("blocking_reason", "Unknown blocking condition")
            recommendations.append(f"BLOCKED: {blocking_reason}")
            recommendations.append("Resolve blocking issue before proceeding")

        if risk_level in [RiskLevel.RISKY, RiskLevel.BLOCKED]:
            recommendations.append("Requires explicit approval from platform team")
            recommendations.append("Schedule change during maintenance window")

        if impact.get("active_operations"):
            recommendations.append(
                f"Wait for {impact['active_operations']} active operations to complete"
            )

        if impact.get("active_solves"):
            recommendations.append(
                f"Wait for {impact['active_solves']} active solves to complete"
            )

        if impact.get("security_files"):
            recommendations.append("Security team review required")
            recommendations.append("Run full security test suite before merge")

        if len(impact.get("affected_tenants", [])) > 3:
            recommendations.append("Consider phased rollout (pilot first)")

        if impact.get("lock_tables"):
            tables = ", ".join(impact["lock_tables"])
            recommendations.append(f"Table locks expected on: {tables}")
            recommendations.append("Schedule during low-traffic period")

        if impact.get("warning"):
            recommendations.append(f"Warning: {impact['warning']}")

        return recommendations
