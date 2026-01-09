"""
Tests for Publish Gate Service - Gate AA Implementation

Tests:
1. Non-Wien site blocked
2. Wien publish requires approval
3. Wien publish with valid approval succeeds
4. Kill switch blocks all operations
5. Evidence hash linkage in audit events
6. Lock requires publish to be allowed first
"""

import json
import tempfile
import pytest
from pathlib import Path
from datetime import datetime, timezone

from backend_py.api.services.publish_gate import (
    PublishGateService,
    PublishGateStatus,
    ApprovalRecord,
    AuditEventType,
)


@pytest.fixture
def wien_enabled_config():
    """Create a config with Wien enabled."""
    return {
        "version": "1.0.0",
        "global_defaults": {
            "publish_enabled": False,
            "lock_enabled": False,
            "shadow_mode_only": True,
            "require_human_approval": True
        },
        "site_overrides": {
            "wien_pilot": {
                "tenant_code": "lts",
                "site_code": "wien",
                "pack": "roster",
                "publish_enabled": True,
                "lock_enabled": True,
                "shadow_mode_only": False,
                "require_human_approval": True,
                "approval_config": {
                    "min_approvers": 1,
                    "allowed_approver_roles": ["dispatcher", "ops_lead", "platform_admin"],
                    "require_reason": True,
                    "min_reason_length": 10
                }
            }
        },
        "rollback_toggle": {
            "kill_switch_active": False
        }
    }


@pytest.fixture
def temp_config_file(wien_enabled_config):
    """Create temporary config file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(wien_enabled_config, f)
        return Path(f.name)


@pytest.fixture
def service(temp_config_file):
    """Create service with test config."""
    return PublishGateService(config_path=temp_config_file)


class TestNonWienSiteBlocked:
    """Test that non-Wien sites are blocked."""

    def test_munich_site_blocked(self, service):
        """Munich site should be blocked (not in overrides)."""
        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="munich",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123"
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_SHADOW_ONLY
        assert "shadow-only" in result.blocked_reason.lower()

    def test_berlin_site_blocked(self, service):
        """Berlin site should be blocked."""
        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="berlin",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123"
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_SHADOW_ONLY

    def test_different_tenant_blocked(self, service):
        """Different tenant should be blocked even with 'wien' site code."""
        result = service.check_publish_allowed(
            tenant_code="other_company",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123"
        )

        assert not result.allowed


class TestWienApprovalRequired:
    """Test that Wien requires human approval."""

    def test_wien_without_approval_blocked(self, service):
        """Wien publish without approval should be blocked."""
        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123"
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_APPROVAL_REQUIRED
        assert "approval required" in result.blocked_reason.lower()

    def test_wien_with_invalid_role_blocked(self, service):
        """Wien publish with invalid approver role should be blocked."""
        approval = ApprovalRecord(
            approver_id="user123",
            approver_role="intern",  # Not in allowed roles
            reason="Weekly plan approved for release"
        )

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123",
            approval=approval
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_APPROVAL_REQUIRED
        assert "role" in result.blocked_reason.lower()

    def test_wien_with_short_reason_blocked(self, service):
        """Wien publish with too short reason should be blocked."""
        approval = ApprovalRecord(
            approver_id="user123",
            approver_role="dispatcher",
            reason="OK"  # Too short (min 10 chars)
        )

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123",
            approval=approval
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_APPROVAL_REQUIRED
        assert "10 characters" in result.blocked_reason


class TestWienApprovalSuccess:
    """Test Wien publish with valid approval."""

    def test_wien_with_dispatcher_approval(self, service):
        """Wien publish with valid dispatcher approval should succeed."""
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Weekly plan 2026-W03 reviewed and approved for release"
        )

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash="sha256:abc123def456",
            approval=approval
        )

        assert result.allowed
        assert result.status == PublishGateStatus.ALLOWED
        assert result.audit_event_id is not None

    def test_wien_with_ops_lead_approval(self, service):
        """Wien publish with ops_lead approval should succeed."""
        approval = ApprovalRecord(
            approver_id="ops_lead001",
            approver_role="ops_lead",
            reason="Approved after KPI review - all metrics within threshold"
        )

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash="sha256:abc123def456",
            approval=approval
        )

        assert result.allowed
        assert result.approval.approver_role == "ops_lead"


class TestKillSwitch:
    """Test kill switch emergency disable."""

    def test_kill_switch_blocks_wien(self, service, temp_config_file):
        """Kill switch should block even Wien site."""
        # First verify Wien works
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Weekly plan approved for release"
        )

        result1 = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123",
            approval=approval
        )
        assert result1.allowed

        # Activate kill switch
        service.activate_kill_switch("security_admin", "Security incident detected")

        # Now Wien should be blocked
        result2 = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=2,
            evidence_hash="abc123",
            approval=approval
        )

        assert not result2.allowed
        assert result2.status == PublishGateStatus.BLOCKED_KILL_SWITCH
        assert "kill switch" in result2.blocked_reason.lower()

    def test_kill_switch_deactivate_restores(self, service, temp_config_file):
        """Deactivating kill switch should restore functionality."""
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Weekly plan approved for release"
        )

        # Activate and then deactivate
        service.activate_kill_switch("security_admin", "False alarm")
        service.deactivate_kill_switch("security_admin", "Issue resolved")

        # Wien should work again
        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123",
            approval=approval
        )

        assert result.allowed

    def test_kill_switch_creates_audit_events(self, service, temp_config_file):
        """Kill switch operations should create audit events."""
        service.activate_kill_switch("admin1", "Testing")
        service.deactivate_kill_switch("admin2", "Test complete")

        events = service.get_audit_events()
        event_types = [e["event_type"] for e in events]

        assert "KILL_SWITCH_ACTIVATED" in event_types
        assert "KILL_SWITCH_DEACTIVATED" in event_types


class TestEvidenceHashLinkage:
    """Test evidence hash is recorded in audit events."""

    def test_evidence_hash_in_approved_event(self, service):
        """Evidence hash should be recorded in approval event."""
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Weekly plan approved for release"
        )
        evidence_hash = "sha256:abcdef1234567890"

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash=evidence_hash,
            approval=approval
        )

        assert result.allowed
        events = service.get_audit_events()
        approved_event = [e for e in events if e["event_type"] == "PUBLISH_APPROVED"][0]

        assert approved_event["evidence_hash"] == evidence_hash
        assert approved_event["plan_version_id"] == 42

    def test_evidence_hash_in_blocked_event(self, service):
        """Evidence hash should be recorded even in blocked events."""
        evidence_hash = "sha256:blocked123"

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash=evidence_hash
            # No approval - will be blocked
        )

        assert not result.allowed
        events = service.get_audit_events()
        blocked_event = [e for e in events if e["event_type"] == "PUBLISH_BLOCKED"][0]

        assert blocked_event["evidence_hash"] == evidence_hash


class TestLockRequiresPublish:
    """Test that lock requires publish to be allowed first."""

    def test_lock_without_approval_blocked(self, service):
        """Lock without approval should be blocked."""
        result = service.check_lock_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc123"
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_APPROVAL_REQUIRED

    def test_lock_with_valid_approval(self, service):
        """Lock with valid approval should succeed."""
        approval = ApprovalRecord(
            approver_id="ops_lead001",
            approver_role="ops_lead",
            reason="Lock approved - ready for export to dispatch system"
        )

        result = service.check_lock_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash="sha256:lock123",
            approval=approval
        )

        assert result.allowed
        assert result.audit_event_id is not None

        # Check audit event type
        events = service.get_audit_events()
        lock_event = [e for e in events if e["event_type"] == "LOCK_COMPLETED"]
        assert len(lock_event) == 1


class TestPrePublishChecks:
    """Test pre-publish check enforcement."""

    def test_failed_audit_blocks_publish(self, service):
        """Failed audit check should block publish."""
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Weekly plan for release"
        )

        pre_checks = {
            "audit_all_pass": False,  # FAILED
            "coverage_100_percent": True,
            "determinism_verified": True
        }

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash="abc123",
            approval=approval,
            pre_check_results=pre_checks
        )

        assert not result.allowed
        assert result.status == PublishGateStatus.BLOCKED_PRE_CHECKS_FAILED
        assert "audit_all_pass" in result.pre_check_failures

    def test_all_checks_pass_allows_publish(self, service):
        """All checks passing should allow publish."""
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="All checks verified, approving"
        )

        pre_checks = {
            "audit_all_pass": True,
            "coverage_100_percent": True,
            "determinism_verified": True,
            "no_block_kpi_drift": True
        }

        result = service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=42,
            evidence_hash="abc123",
            approval=approval,
            pre_check_results=pre_checks
        )

        assert result.allowed


class TestAuditEventExport:
    """Test audit event export functionality."""

    def test_export_produces_hash(self, service, tmp_path):
        """Export should produce integrity hash."""
        # Generate some events
        approval = ApprovalRecord(
            approver_id="dispatcher001",
            approver_role="dispatcher",
            reason="Export test approval"
        )
        service.check_publish_allowed(
            tenant_code="lts",
            site_code="wien",
            pack="roster",
            plan_version_id=1,
            evidence_hash="abc",
            approval=approval
        )

        output_path = tmp_path / "audit_export.json"
        export_hash = service.export_audit_events(output_path)

        assert output_path.exists()
        assert len(export_hash) == 64  # SHA256 hex

        # Verify file contents
        with open(output_path) as f:
            data = json.load(f)
        assert data["event_count"] >= 1
        assert len(data["events"]) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
