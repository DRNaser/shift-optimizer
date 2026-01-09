"""
Publish Gate Service - Gate AA Implementation

Enforces publish/lock authorization with:
- Site-level enablement (Wien only initially)
- Human approval requirement with audit trail
- Evidence hash linkage
- Kill switch for emergency rollback

Exit codes:
- 0: Publish/lock allowed
- 1: Blocked (site not enabled)
- 2: Blocked (approval required but missing)
- 3: Blocked (kill switch active)
- 4: Blocked (pre-publish checks failed)
"""

import json
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PublishGateStatus(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED_SITE_DISABLED = "BLOCKED_SITE_DISABLED"
    BLOCKED_APPROVAL_REQUIRED = "BLOCKED_APPROVAL_REQUIRED"
    BLOCKED_KILL_SWITCH = "BLOCKED_KILL_SWITCH"
    BLOCKED_PRE_CHECKS_FAILED = "BLOCKED_PRE_CHECKS_FAILED"
    BLOCKED_SHADOW_ONLY = "BLOCKED_SHADOW_ONLY"


class AuditEventType(str, Enum):
    PUBLISH_REQUESTED = "PUBLISH_REQUESTED"
    PUBLISH_APPROVED = "PUBLISH_APPROVED"
    PUBLISH_BLOCKED = "PUBLISH_BLOCKED"
    LOCK_REQUESTED = "LOCK_REQUESTED"
    LOCK_COMPLETED = "LOCK_COMPLETED"
    LOCK_BLOCKED = "LOCK_BLOCKED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"


@dataclass
class ApprovalRecord:
    """Human approval for publish/lock operation."""
    approver_id: str
    approver_role: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate approval against config requirements."""
        errors = []
        approval_config = config.get("approval_config", {})

        allowed_roles = approval_config.get("allowed_approver_roles", [])
        if allowed_roles and self.approver_role not in allowed_roles:
            errors.append(f"Approver role '{self.approver_role}' not in allowed roles: {allowed_roles}")

        if approval_config.get("require_reason", True):
            min_length = approval_config.get("min_reason_length", 10)
            if len(self.reason.strip()) < min_length:
                errors.append(f"Reason must be at least {min_length} characters")

        return errors


@dataclass
class PublishGateResult:
    """Result of publish/lock gate check."""
    status: PublishGateStatus
    allowed: bool
    tenant_code: str
    site_code: str
    pack: str
    plan_version_id: Optional[int]
    evidence_hash: Optional[str]
    approval: Optional[ApprovalRecord]
    audit_event_id: Optional[str]
    blocked_reason: Optional[str] = None
    pre_check_failures: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        if self.approval:
            result["approval"] = asdict(self.approval)
        return result


@dataclass
class AuditEvent:
    """Immutable audit event for publish/lock operations."""
    event_id: str
    event_type: AuditEventType
    tenant_code: str
    site_code: str
    pack: str
    plan_version_id: Optional[int]
    evidence_hash: Optional[str]
    approver_id: Optional[str]
    reason: Optional[str]
    result: str
    details: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["event_type"] = self.event_type.value
        return result

    def compute_hash(self) -> str:
        """Compute hash of audit event for integrity verification."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PublishGateService:
    """
    Enforces publish/lock authorization based on site enablement config.

    Key features:
    - Site-level enablement (Wien only initially)
    - Human approval requirement
    - Kill switch for emergency rollback
    - Audit event generation with evidence hash linkage
    """

    DEFAULT_CONFIG_PATH = Path("config/enable_publish_lock_wien.json")

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = self._load_config()
        self._audit_events: List[AuditEvent] = []

    def _load_config(self) -> Dict[str, Any]:
        """Load publish/lock configuration."""
        if not self.config_path.exists():
            logger.warning(f"Config not found at {self.config_path}, using defaults")
            return {
                "global_defaults": {
                    "publish_enabled": False,
                    "lock_enabled": False,
                    "shadow_mode_only": True,
                    "require_human_approval": True
                },
                "site_overrides": {},
                "rollback_toggle": {
                    "kill_switch_active": False
                }
            }

        with open(self.config_path) as f:
            return json.load(f)

    def reload_config(self) -> None:
        """Reload configuration (for kill switch changes without restart)."""
        self.config = self._load_config()
        logger.info("Publish gate config reloaded")

    def _get_site_config(self, tenant_code: str, site_code: str, pack: str) -> Dict[str, Any]:
        """Get configuration for a specific site."""
        # Check for site override
        site_key = f"{site_code}"
        for key, override in self.config.get("site_overrides", {}).items():
            if (override.get("tenant_code") == tenant_code and
                override.get("site_code") == site_code and
                override.get("pack") == pack):
                return override

        # Fall back to global defaults
        return self.config.get("global_defaults", {})

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is active (emergency disable)."""
        rollback = self.config.get("rollback_toggle", {})
        return rollback.get("kill_switch_active", False)

    def activate_kill_switch(self, activated_by: str, reason: str) -> None:
        """Activate kill switch to immediately disable all publish/lock."""
        self.config["rollback_toggle"]["kill_switch_active"] = True
        self.config["rollback_toggle"]["kill_switch_reason"] = reason
        self.config["rollback_toggle"]["kill_switch_activated_by"] = activated_by
        self.config["rollback_toggle"]["kill_switch_activated_at"] = datetime.now(timezone.utc).isoformat()

        # Write config
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

        # Create audit event
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.KILL_SWITCH_ACTIVATED,
            tenant_code="*",
            site_code="*",
            pack="*",
            plan_version_id=None,
            evidence_hash=None,
            approver_id=activated_by,
            reason=reason,
            result="KILL_SWITCH_ACTIVE",
            details={"scope": "all_sites"}
        )
        self._audit_events.append(event)
        logger.critical(f"KILL SWITCH ACTIVATED by {activated_by}: {reason}")

    def deactivate_kill_switch(self, deactivated_by: str, reason: str) -> None:
        """Deactivate kill switch to re-enable publish/lock."""
        self.config["rollback_toggle"]["kill_switch_active"] = False
        self.config["rollback_toggle"]["kill_switch_reason"] = None
        self.config["rollback_toggle"]["kill_switch_activated_by"] = None
        self.config["rollback_toggle"]["kill_switch_activated_at"] = None

        # Write config
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

        # Create audit event
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.KILL_SWITCH_DEACTIVATED,
            tenant_code="*",
            site_code="*",
            pack="*",
            plan_version_id=None,
            evidence_hash=None,
            approver_id=deactivated_by,
            reason=reason,
            result="KILL_SWITCH_DEACTIVATED",
            details={"scope": "all_sites"}
        )
        self._audit_events.append(event)
        logger.warning(f"Kill switch deactivated by {deactivated_by}: {reason}")

    def _generate_event_id(self) -> str:
        """Generate unique audit event ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return f"AE-{timestamp}"

    def check_publish_allowed(
        self,
        tenant_code: str,
        site_code: str,
        pack: str,
        plan_version_id: int,
        evidence_hash: str,
        approval: Optional[ApprovalRecord] = None,
        pre_check_results: Optional[Dict[str, bool]] = None
    ) -> PublishGateResult:
        """
        Check if publish is allowed for the given site and plan.

        Args:
            tenant_code: Tenant identifier (e.g., "lts")
            site_code: Site identifier (e.g., "wien")
            pack: Pack type (e.g., "roster")
            plan_version_id: Plan version to publish
            evidence_hash: Hash of evidence pack
            approval: Human approval record (required for enabled sites)
            pre_check_results: Results of pre-publish checks

        Returns:
            PublishGateResult with status and audit event
        """
        site_config = self._get_site_config(tenant_code, site_code, pack)

        # Check 1: Kill switch
        if self.is_kill_switch_active():
            result = PublishGateResult(
                status=PublishGateStatus.BLOCKED_KILL_SWITCH,
                allowed=False,
                tenant_code=tenant_code,
                site_code=site_code,
                pack=pack,
                plan_version_id=plan_version_id,
                evidence_hash=evidence_hash,
                approval=approval,
                audit_event_id=None,
                blocked_reason="Kill switch is active - all publish/lock operations disabled"
            )
            self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
            return result

        # Check 2: Shadow mode only
        if site_config.get("shadow_mode_only", True):
            result = PublishGateResult(
                status=PublishGateStatus.BLOCKED_SHADOW_ONLY,
                allowed=False,
                tenant_code=tenant_code,
                site_code=site_code,
                pack=pack,
                plan_version_id=plan_version_id,
                evidence_hash=evidence_hash,
                approval=approval,
                audit_event_id=None,
                blocked_reason=f"Site {site_code} is in shadow-only mode"
            )
            self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
            return result

        # Check 3: Publish enabled
        if not site_config.get("publish_enabled", False):
            result = PublishGateResult(
                status=PublishGateStatus.BLOCKED_SITE_DISABLED,
                allowed=False,
                tenant_code=tenant_code,
                site_code=site_code,
                pack=pack,
                plan_version_id=plan_version_id,
                evidence_hash=evidence_hash,
                approval=approval,
                audit_event_id=None,
                blocked_reason=f"Publish not enabled for site {site_code}"
            )
            self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
            return result

        # Check 4: Human approval required
        if site_config.get("require_human_approval", True):
            if approval is None:
                result = PublishGateResult(
                    status=PublishGateStatus.BLOCKED_APPROVAL_REQUIRED,
                    allowed=False,
                    tenant_code=tenant_code,
                    site_code=site_code,
                    pack=pack,
                    plan_version_id=plan_version_id,
                    evidence_hash=evidence_hash,
                    approval=None,
                    audit_event_id=None,
                    blocked_reason="Human approval required but not provided"
                )
                self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
                return result

            # Validate approval
            approval_errors = approval.validate(site_config)
            if approval_errors:
                result = PublishGateResult(
                    status=PublishGateStatus.BLOCKED_APPROVAL_REQUIRED,
                    allowed=False,
                    tenant_code=tenant_code,
                    site_code=site_code,
                    pack=pack,
                    plan_version_id=plan_version_id,
                    evidence_hash=evidence_hash,
                    approval=approval,
                    audit_event_id=None,
                    blocked_reason=f"Approval validation failed: {'; '.join(approval_errors)}"
                )
                self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
                return result

        # Check 5: Pre-publish checks
        if pre_check_results:
            failures = [check for check, passed in pre_check_results.items() if not passed]
            if failures:
                result = PublishGateResult(
                    status=PublishGateStatus.BLOCKED_PRE_CHECKS_FAILED,
                    allowed=False,
                    tenant_code=tenant_code,
                    site_code=site_code,
                    pack=pack,
                    plan_version_id=plan_version_id,
                    evidence_hash=evidence_hash,
                    approval=approval,
                    audit_event_id=None,
                    blocked_reason=f"Pre-publish checks failed: {failures}",
                    pre_check_failures=failures
                )
                self._record_blocked_event(result, AuditEventType.PUBLISH_BLOCKED)
                return result

        # All checks passed - publish allowed
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.PUBLISH_APPROVED,
            tenant_code=tenant_code,
            site_code=site_code,
            pack=pack,
            plan_version_id=plan_version_id,
            evidence_hash=evidence_hash,
            approver_id=approval.approver_id if approval else None,
            reason=approval.reason if approval else None,
            result="ALLOWED",
            details={
                "approval_timestamp": approval.timestamp if approval else None,
                "approver_role": approval.approver_role if approval else None
            }
        )
        self._audit_events.append(event)

        result = PublishGateResult(
            status=PublishGateStatus.ALLOWED,
            allowed=True,
            tenant_code=tenant_code,
            site_code=site_code,
            pack=pack,
            plan_version_id=plan_version_id,
            evidence_hash=evidence_hash,
            approval=approval,
            audit_event_id=event.event_id
        )

        logger.info(f"Publish ALLOWED for {tenant_code}/{site_code}/{pack} plan {plan_version_id}")
        return result

    def check_lock_allowed(
        self,
        tenant_code: str,
        site_code: str,
        pack: str,
        plan_version_id: int,
        evidence_hash: str,
        approval: Optional[ApprovalRecord] = None
    ) -> PublishGateResult:
        """
        Check if lock is allowed for the given site and plan.
        Lock requires publish to be allowed first, plus lock-specific checks.
        """
        # First check publish allowed
        publish_result = self.check_publish_allowed(
            tenant_code=tenant_code,
            site_code=site_code,
            pack=pack,
            plan_version_id=plan_version_id,
            evidence_hash=evidence_hash,
            approval=approval
        )

        if not publish_result.allowed:
            # Convert to lock blocked event
            if publish_result.audit_event_id:
                # Update event type
                for event in self._audit_events:
                    if event.event_id == publish_result.audit_event_id:
                        event.event_type = AuditEventType.LOCK_BLOCKED
            return publish_result

        # Check lock enabled
        site_config = self._get_site_config(tenant_code, site_code, pack)
        if not site_config.get("lock_enabled", False):
            result = PublishGateResult(
                status=PublishGateStatus.BLOCKED_SITE_DISABLED,
                allowed=False,
                tenant_code=tenant_code,
                site_code=site_code,
                pack=pack,
                plan_version_id=plan_version_id,
                evidence_hash=evidence_hash,
                approval=approval,
                audit_event_id=None,
                blocked_reason=f"Lock not enabled for site {site_code}"
            )
            self._record_blocked_event(result, AuditEventType.LOCK_BLOCKED)
            return result

        # Lock allowed
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.LOCK_COMPLETED,
            tenant_code=tenant_code,
            site_code=site_code,
            pack=pack,
            plan_version_id=plan_version_id,
            evidence_hash=evidence_hash,
            approver_id=approval.approver_id if approval else None,
            reason=approval.reason if approval else None,
            result="LOCKED",
            details={
                "approval_timestamp": approval.timestamp if approval else None,
                "approver_role": approval.approver_role if approval else None,
                "publish_event_id": publish_result.audit_event_id
            }
        )
        self._audit_events.append(event)

        result = PublishGateResult(
            status=PublishGateStatus.ALLOWED,
            allowed=True,
            tenant_code=tenant_code,
            site_code=site_code,
            pack=pack,
            plan_version_id=plan_version_id,
            evidence_hash=evidence_hash,
            approval=approval,
            audit_event_id=event.event_id
        )

        logger.info(f"Lock COMPLETED for {tenant_code}/{site_code}/{pack} plan {plan_version_id}")
        return result

    def _record_blocked_event(self, result: PublishGateResult, event_type: AuditEventType) -> None:
        """Record a blocked publish/lock attempt."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=event_type,
            tenant_code=result.tenant_code,
            site_code=result.site_code,
            pack=result.pack,
            plan_version_id=result.plan_version_id,
            evidence_hash=result.evidence_hash,
            approver_id=result.approval.approver_id if result.approval else None,
            reason=result.blocked_reason,
            result="BLOCKED",
            details={
                "status": result.status.value,
                "pre_check_failures": result.pre_check_failures
            }
        )
        self._audit_events.append(event)
        result.audit_event_id = event.event_id

        logger.warning(f"{event_type.value}: {result.blocked_reason}")

    def get_audit_events(self) -> List[Dict[str, Any]]:
        """Get all audit events."""
        return [e.to_dict() for e in self._audit_events]

    def export_audit_events(self, output_path: Path) -> str:
        """Export audit events to JSON file with integrity hash."""
        events = self.get_audit_events()
        export_data = {
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "events": events
        }

        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2)

        # Compute export hash
        canonical = json.dumps(export_data, sort_keys=True, separators=(",", ":"))
        export_hash = hashlib.sha256(canonical.encode()).hexdigest()

        logger.info(f"Exported {len(events)} audit events to {output_path} (hash: {export_hash[:16]}...)")
        return export_hash


# CLI interface
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Publish Gate Service CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Check publish
    check_parser = subparsers.add_parser("check-publish", help="Check if publish is allowed")
    check_parser.add_argument("--tenant", required=True, help="Tenant code")
    check_parser.add_argument("--site", required=True, help="Site code")
    check_parser.add_argument("--pack", default="roster", help="Pack type")
    check_parser.add_argument("--plan-id", type=int, required=True, help="Plan version ID")
    check_parser.add_argument("--evidence-hash", required=True, help="Evidence hash")
    check_parser.add_argument("--approver-id", help="Approver ID")
    check_parser.add_argument("--approver-role", help="Approver role")
    check_parser.add_argument("--reason", help="Approval reason")

    # Kill switch
    kill_parser = subparsers.add_parser("kill-switch", help="Activate/deactivate kill switch")
    kill_parser.add_argument("--activate", action="store_true", help="Activate kill switch")
    kill_parser.add_argument("--deactivate", action="store_true", help="Deactivate kill switch")
    kill_parser.add_argument("--by", required=True, help="User performing action")
    kill_parser.add_argument("--reason", required=True, help="Reason for action")

    # Status
    status_parser = subparsers.add_parser("status", help="Show current status")

    args = parser.parse_args()

    service = PublishGateService()

    if args.command == "check-publish":
        approval = None
        if args.approver_id and args.approver_role and args.reason:
            approval = ApprovalRecord(
                approver_id=args.approver_id,
                approver_role=args.approver_role,
                reason=args.reason
            )

        result = service.check_publish_allowed(
            tenant_code=args.tenant,
            site_code=args.site,
            pack=args.pack,
            plan_version_id=args.plan_id,
            evidence_hash=args.evidence_hash,
            approval=approval
        )

        print(json.dumps(result.to_dict(), indent=2))
        sys.exit(0 if result.allowed else 1)

    elif args.command == "kill-switch":
        if args.activate:
            service.activate_kill_switch(args.by, args.reason)
            print("Kill switch ACTIVATED")
            sys.exit(0)
        elif args.deactivate:
            service.deactivate_kill_switch(args.by, args.reason)
            print("Kill switch DEACTIVATED")
            sys.exit(0)
        else:
            print("Specify --activate or --deactivate")
            sys.exit(1)

    elif args.command == "status":
        print(f"Kill switch active: {service.is_kill_switch_active()}")
        print(f"\nSite overrides:")
        for key, override in service.config.get("site_overrides", {}).items():
            print(f"  {key}:")
            print(f"    publish_enabled: {override.get('publish_enabled', False)}")
            print(f"    lock_enabled: {override.get('lock_enabled', False)}")
            print(f"    shadow_mode_only: {override.get('shadow_mode_only', True)}")
        sys.exit(0)

    else:
        parser.print_help()
        sys.exit(1)
