"""
KPI Baseline Management - Compute and store KPI baselines.

Baselines are computed from historical solver runs and used
for drift detection. Write operations require explicit approval.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
import statistics
import hashlib


@dataclass
class MetricBaseline:
    """Baseline for a single metric."""
    name: str
    mean: float
    std_dev: float
    min_value: float
    max_value: float
    weight: float
    sample_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mean": round(self.mean, 4),
            "std_dev": round(self.std_dev, 4),
            "min": round(self.min_value, 4),
            "max": round(self.max_value, 4),
            "weight": self.weight,
            "sample_count": self.sample_count,
        }


@dataclass
class KPIBaseline:
    """Complete baseline for a tenant/pack."""
    tenant_code: str
    pack: str
    site_code: Optional[str]
    sample_count: int
    computed_at: datetime
    metrics: Dict[str, MetricBaseline]

    def compute_hash(self) -> str:
        """Compute deterministic hash of baseline for audit trail."""
        content = json.dumps(
            {
                "tenant": self.tenant_code,
                "pack": self.pack,
                "metrics": {
                    name: m.to_dict()
                    for name, m in sorted(self.metrics.items())
                }
            },
            sort_keys=True
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_code": self.tenant_code,
            "pack": self.pack,
            "site_code": self.site_code,
            "sample_count": self.sample_count,
            "computed_at": self.computed_at.isoformat(),
            "baseline_hash": self.compute_hash(),
            "metrics": {
                name: metric.to_dict()
                for name, metric in self.metrics.items()
            }
        }


class InsufficientDataError(Exception):
    """Raised when not enough data to compute baseline."""
    pass


class BaselineComputer:
    """
    Computes KPI baselines from historical solver runs.

    Baselines are read from drift-baselines.json.
    """

    MIN_SAMPLE_SIZE = 3
    DEFAULT_SAMPLE_SIZE = 10

    def __init__(self, baselines_path: Optional[Path] = None):
        """Initialize baseline computer."""
        if baselines_path is None:
            repo_root = Path(__file__).parent.parent.parent.parent
            baselines_path = repo_root / ".claude" / "state" / "drift-baselines.json"

        self.baselines_path = baselines_path

    def load_current_baseline(
        self,
        tenant_code: str,
        pack: str,
    ) -> Optional[KPIBaseline]:
        """Load current baseline from state file."""
        try:
            with open(self.baselines_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

        pack_data = data.get(pack, {})
        tenant_data = pack_data.get(tenant_code)

        if not tenant_data:
            return None

        # Convert to KPIBaseline
        metrics = {}
        for name, value in tenant_data.items():
            if name.startswith("_"):
                continue
            if isinstance(value, dict):
                metrics[name] = MetricBaseline(
                    name=name,
                    mean=value.get("mean", value.get("value", 0)),
                    std_dev=value.get("std_dev", 0),
                    min_value=value.get("min", 0),
                    max_value=value.get("max", 0),
                    weight=value.get("weight", 1.0),
                    sample_count=value.get("sample_count", 1),
                )
            else:
                metrics[name] = MetricBaseline(
                    name=name,
                    mean=float(value),
                    std_dev=0,
                    min_value=float(value),
                    max_value=float(value),
                    weight=1.0,
                    sample_count=1,
                )

        return KPIBaseline(
            tenant_code=tenant_code,
            pack=pack,
            site_code=None,
            sample_count=tenant_data.get("_sample_count", 1),
            computed_at=datetime.fromisoformat(
                tenant_data.get("_computed_at", datetime.now(timezone.utc).isoformat())
            ),
            metrics=metrics,
        )

    def compute_baseline_from_history(
        self,
        tenant_code: str,
        pack: str,
        historical_kpis: List[Dict[str, float]],
    ) -> KPIBaseline:
        """
        Compute baseline from historical KPI data.

        Args:
            tenant_code: Tenant identifier
            pack: "routing" or "roster"
            historical_kpis: List of dicts with metric values

        Returns:
            KPIBaseline computed from history

        Raises:
            InsufficientDataError: If not enough samples
        """
        if len(historical_kpis) < self.MIN_SAMPLE_SIZE:
            raise InsufficientDataError(
                f"Need at least {self.MIN_SAMPLE_SIZE} samples, have {len(historical_kpis)}"
            )

        # Get metric weights
        from .detector import METRIC_WEIGHTS
        weights = METRIC_WEIGHTS.get(pack, {})

        # Compute per-metric baselines
        all_metrics = set()
        for kpi in historical_kpis:
            all_metrics.update(kpi.keys())

        metrics = {}
        for name in all_metrics:
            values = [kpi[name] for kpi in historical_kpis if name in kpi]
            if not values:
                continue

            metrics[name] = MetricBaseline(
                name=name,
                mean=statistics.mean(values),
                std_dev=statistics.stdev(values) if len(values) > 1 else 0,
                min_value=min(values),
                max_value=max(values),
                weight=weights.get(name, 1.0),
                sample_count=len(values),
            )

        return KPIBaseline(
            tenant_code=tenant_code,
            pack=pack,
            site_code=None,
            sample_count=len(historical_kpis),
            computed_at=datetime.now(timezone.utc),
            metrics=metrics,
        )

    def propose_baseline_update(
        self,
        tenant_code: str,
        pack: str,
        new_kpis: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Propose a baseline update (dry-run).

        Shows diff between current and proposed baseline.
        Does NOT write to disk - requires explicit accept.

        Returns:
            Dict with current, proposed, and diff
        """
        current = self.load_current_baseline(tenant_code, pack)

        # Compute proposed from single new datapoint (rolling update)
        if current:
            # Combine with existing (weighted rolling average)
            proposed_metrics = {}
            for name, metric in current.metrics.items():
                if name in new_kpis:
                    new_value = new_kpis[name]
                    # Rolling average with decay
                    n = metric.sample_count
                    new_mean = (metric.mean * n + new_value) / (n + 1)
                    proposed_metrics[name] = MetricBaseline(
                        name=name,
                        mean=new_mean,
                        std_dev=metric.std_dev,  # Keep existing std_dev
                        min_value=min(metric.min_value, new_value),
                        max_value=max(metric.max_value, new_value),
                        weight=metric.weight,
                        sample_count=n + 1,
                    )
                else:
                    proposed_metrics[name] = metric

            proposed = KPIBaseline(
                tenant_code=tenant_code,
                pack=pack,
                site_code=None,
                sample_count=current.sample_count + 1,
                computed_at=datetime.now(timezone.utc),
                metrics=proposed_metrics,
            )
        else:
            # No current baseline - create from scratch
            proposed = KPIBaseline(
                tenant_code=tenant_code,
                pack=pack,
                site_code=None,
                sample_count=1,
                computed_at=datetime.now(timezone.utc),
                metrics={
                    name: MetricBaseline(
                        name=name,
                        mean=value,
                        std_dev=0,
                        min_value=value,
                        max_value=value,
                        weight=1.0,
                        sample_count=1,
                    )
                    for name, value in new_kpis.items()
                },
            )

        # Compute diff
        diff = {}
        if current:
            for name in set(current.metrics.keys()) | set(proposed.metrics.keys()):
                old_val = current.metrics.get(name)
                new_val = proposed.metrics.get(name)
                if old_val and new_val:
                    pct_change = ((new_val.mean - old_val.mean) / old_val.mean * 100) if old_val.mean else 0
                    diff[name] = {
                        "old_mean": old_val.mean,
                        "new_mean": new_val.mean,
                        "percent_change": round(pct_change, 2),
                    }

        return {
            "current": current.to_dict() if current else None,
            "proposed": proposed.to_dict(),
            "diff": diff,
            "requires_approval": True,
        }


class BaselineProtection:
    """
    Enforces write protection on KPI baselines.

    Baseline writes require:
    1. Explicit user approval (not automation)
    2. APPROVER or higher role
    3. Documented reason
    4. Audit trail entry
    """

    REQUIRED_ROLES = ['APPROVER', 'PLATFORM_ADMIN', 'TENANT_ADMIN']

    def __init__(self, baselines_path: Optional[Path] = None):
        if baselines_path is None:
            repo_root = Path(__file__).parent.parent.parent.parent
            baselines_path = repo_root / ".claude" / "state" / "drift-baselines.json"

        self.baselines_path = baselines_path
        self.audit_path = baselines_path.parent / "baseline-audit-log.json"

    def can_write_baseline(
        self,
        user: Optional[str],
        role: Optional[str],
        is_automation: bool,
    ) -> tuple[bool, str]:
        """Check if baseline write is allowed."""

        # RULE 1: Automation can NEVER write baseline
        if is_automation:
            return False, "Automation cannot update baselines - requires human approval"

        # RULE 2: Must have user identity
        if not user:
            return False, "Baseline update requires authenticated user"

        # RULE 3: Must have APPROVER role or higher
        if role and role not in self.REQUIRED_ROLES:
            return False, f"Role {role} cannot update baselines - requires APPROVER"

        return True, "Allowed"

    def accept_baseline(
        self,
        tenant_code: str,
        pack: str,
        new_baseline: KPIBaseline,
        approved_by: str,
        reason: str,
        role: str = "APPROVER",
    ) -> Dict[str, Any]:
        """
        Accept and persist new baseline with full audit trail.

        Args:
            tenant_code: Tenant identifier
            pack: "routing" or "roster"
            new_baseline: New baseline to accept
            approved_by: Email of approver
            reason: Reason for update
            role: Role of approver

        Returns:
            Dict with success status and audit entry
        """
        # Check permission
        allowed, msg = self.can_write_baseline(
            user=approved_by,
            role=role,
            is_automation=False,
        )

        if not allowed:
            return {
                "success": False,
                "error": msg,
            }

        # Load current state
        try:
            with open(self.baselines_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        # Get old hash for audit
        old_pack = data.get(pack, {})
        old_tenant = old_pack.get(tenant_code, {})
        old_hash = old_tenant.get("baseline_output_hash", "NONE")

        # Update baseline
        if pack not in data:
            data[pack] = {}

        data[pack][tenant_code] = {
            **{name: metric.to_dict() for name, metric in new_baseline.metrics.items()},
            "_sample_count": new_baseline.sample_count,
            "_computed_at": new_baseline.computed_at.isoformat(),
            "baseline_output_hash": new_baseline.compute_hash(),
        }

        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["updated_by"] = approved_by

        # Write to file
        with open(self.baselines_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Create audit entry
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "baseline_accepted",
            "tenant_code": tenant_code,
            "pack": pack,
            "old_hash": old_hash,
            "new_hash": new_baseline.compute_hash(),
            "approved_by": approved_by,
            "reason": reason,
            "sample_count": new_baseline.sample_count,
        }

        self._append_audit_log(audit_entry)

        return {
            "success": True,
            "audit_entry": audit_entry,
        }

    def _append_audit_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to audit log."""
        try:
            with open(self.audit_path, encoding="utf-8") as f:
                log = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            log = {"entries": []}

        log["entries"].append(entry)

        with open(self.audit_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
