#!/usr/bin/env python3
"""
Unit tests for Enterprise Audit Report Generator (Skill 113).

Tests cover:
- Evidence collection
- Report generation
- Redaction
- Compliance matrix
- Evidence packaging
- Exit codes
"""

import pytest
import asyncio
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backend_py.skills.audit_report import (
    EnterpriseAuditReportGenerator,
    AuditEvidence,
    AuditReport,
    AuditRedactor,
    OutputMode,
)
from backend_py.skills.audit_report.redaction import verify_customer_safe


class TestAuditEvidence:
    """Test AuditEvidence dataclass."""

    def test_to_dict(self):
        """Should convert evidence to dictionary."""
        evidence = AuditEvidence(
            category="security",
            name="rls_harness",
            source_skill="101",
            status="PASS",
            timestamp=datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc),
            data={"coverage_percent": 100.0},
            hash="abc123",
        )

        d = evidence.to_dict()

        assert d["category"] == "security"
        assert d["name"] == "rls_harness"
        assert d["status"] == "PASS"
        assert d["data"]["coverage_percent"] == 100.0


class TestAuditReport:
    """Test AuditReport dataclass."""

    def test_exit_code_pass(self):
        """PASS status should return exit code 0."""
        report = AuditReport(
            report_id="TEST",
            generated_at=datetime.now(timezone.utc),
            scope="platform",
            tenant_code=None,
            evidence=[],
            evidence_hashes={},
            overall_status="PASS",
            pass_count=5,
            fail_count=0,
            warn_count=0,
            summary_path="",
            compliance_path="",
            evidence_zip_path="",
        )

        assert report.exit_code == 0

    def test_exit_code_partial(self):
        """PARTIAL status should return exit code 1."""
        report = AuditReport(
            report_id="TEST",
            generated_at=datetime.now(timezone.utc),
            scope="platform",
            tenant_code=None,
            evidence=[],
            evidence_hashes={},
            overall_status="PARTIAL",
            pass_count=4,
            fail_count=0,
            warn_count=1,
            summary_path="",
            compliance_path="",
            evidence_zip_path="",
        )

        assert report.exit_code == 1

    def test_exit_code_fail(self):
        """FAIL status should return exit code 2."""
        report = AuditReport(
            report_id="TEST",
            generated_at=datetime.now(timezone.utc),
            scope="platform",
            tenant_code=None,
            evidence=[],
            evidence_hashes={},
            overall_status="FAIL",
            pass_count=3,
            fail_count=2,
            warn_count=0,
            summary_path="",
            compliance_path="",
            evidence_zip_path="",
        )

        assert report.exit_code == 2


class TestRedaction:
    """Test redaction functionality."""

    def test_internal_mode_no_redaction(self):
        """Internal mode should not redact anything."""
        redactor = AuditRedactor(OutputMode.INTERNAL)

        data = {
            "password": "secret123",
            "email": "test@example.com",
            "ip": "192.168.1.1",
        }

        result = redactor.redact(data)

        assert result["password"] == "secret123"
        assert result["email"] == "test@example.com"
        assert result["ip"] == "192.168.1.1"

    def test_customer_mode_redacts_passwords(self):
        """Customer mode should redact passwords."""
        redactor = AuditRedactor(OutputMode.CUSTOMER_SAFE)

        text = 'password="secret123"'
        result = redactor.redact_text(text)

        assert "secret123" not in result
        assert "REDACTED" in result

    def test_customer_mode_redacts_emails(self):
        """Customer mode should redact emails."""
        redactor = AuditRedactor(OutputMode.CUSTOMER_SAFE)

        text = 'Contact: user@example.com for support'
        result = redactor.redact_text(text)

        assert "user@example.com" not in result
        assert "EMAIL_REDACTED" in result

    def test_customer_mode_redacts_ips(self):
        """Customer mode should redact IP addresses."""
        redactor = AuditRedactor(OutputMode.CUSTOMER_SAFE)

        text = 'Server IP: 192.168.1.100'
        result = redactor.redact_text(text)

        assert "192.168.1.100" not in result
        assert "IP_REDACTED" in result

    def test_customer_mode_removes_sensitive_keys(self):
        """Customer mode should remove sensitive keys entirely."""
        redactor = AuditRedactor(OutputMode.CUSTOMER_SAFE)

        data = {
            "public_info": "visible",
            "stack_trace": "Error at line 42...",
            "request_id": "req-123-abc",
            "token": "secret-token",
        }

        result = redactor.redact(data)

        assert "public_info" in result
        assert "stack_trace" not in result
        assert "request_id" not in result
        assert "token" not in result

    def test_redaction_audit_generation(self):
        """Should generate redaction audit record."""
        redactor = AuditRedactor(OutputMode.CUSTOMER_SAFE)

        # Use data with sensitive keys that get removed entirely
        original = {"stack_trace": "Error at line 42", "public": "data"}
        redacted = redactor.redact(original)
        audit = redactor.generate_redaction_audit(original, redacted)

        assert audit["mode"] == "CUSTOMER_SAFE"
        assert "original_hash" in audit
        assert "redacted_hash" in audit
        # Hash should differ because stack_trace key is removed
        assert audit["original_hash"] != audit["redacted_hash"]
        assert audit["fields_removed"] > 0


class TestVerifyCustomerSafe:
    """Test customer-safe verification."""

    def test_clean_content_passes(self):
        """Content without sensitive data should pass."""
        content = "This is a clean audit report with no sensitive data."
        result = verify_customer_safe(content)

        assert result["passed"] is True
        assert len(result["violations"]) == 0

    def test_content_with_email_fails(self):
        """Content with email should fail."""
        content = "Contact: admin@company.com for help"
        result = verify_customer_safe(content)

        assert result["passed"] is False
        assert len(result["violations"]) > 0

    def test_content_with_ip_fails(self):
        """Content with IP address should fail."""
        content = "Server at 10.0.0.1 is down"
        result = verify_customer_safe(content)

        assert result["passed"] is False

    def test_content_with_traceback_fails(self):
        """Content with stack trace should fail."""
        content = "Traceback (most recent call last):\n  File ..."
        result = verify_customer_safe(content)

        assert result["passed"] is False


class TestEnterpriseAuditReportGenerator:
    """Test the full audit report generator."""

    @pytest.mark.asyncio
    async def test_generate_platform_report(self):
        """Should generate platform-wide report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
            )

            report = await generator.generate(tenant_code=None)

            assert report.scope == "platform"
            assert report.tenant_code is None
            assert len(report.evidence) >= 5  # At least 5 evidence types
            assert "MASTER" in report.evidence_hashes

    @pytest.mark.asyncio
    async def test_generate_tenant_report(self):
        """Should generate tenant-specific report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
            )

            report = await generator.generate(tenant_code="test_tenant")

            assert report.scope == "tenant"
            assert report.tenant_code == "test_tenant"

    @pytest.mark.asyncio
    async def test_output_files_created(self):
        """Should create all output files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate()

            # Check files exist
            assert Path(report.summary_path).exists()
            assert Path(report.compliance_path).exists()
            assert Path(report.evidence_zip_path).exists()

    @pytest.mark.asyncio
    async def test_evidence_zip_structure(self):
        """Should create properly structured ZIP file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate()

            with zipfile.ZipFile(report.evidence_zip_path, 'r') as zf:
                names = zf.namelist()

                assert 'AUDIT_SUMMARY.md' in names
                assert 'COMPLIANCE_MATRIX.md' in names
                assert 'EVIDENCE_HASHES.json' in names
                assert 'MANIFEST.json' in names

                # Check evidence folder
                evidence_files = [n for n in names if n.startswith('evidence/')]
                assert len(evidence_files) >= 5

    @pytest.mark.asyncio
    async def test_master_hash_computed(self):
        """Should compute master hash from all evidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
            )

            report = await generator.generate()

            assert "MASTER" in report.evidence_hashes
            assert len(report.evidence_hashes["MASTER"]) == 64  # SHA256 hex

    @pytest.mark.asyncio
    async def test_status_calculation_pass(self):
        """Should calculate PASS status when all evidence passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
            )

            report = await generator.generate()

            # Default simulated evidence should all pass
            assert report.overall_status == "PASS"
            assert report.fail_count == 0

    @pytest.mark.asyncio
    async def test_customer_safe_mode(self):
        """Should generate customer-safe report with redaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate(output_mode=OutputMode.CUSTOMER_SAFE)

            assert "CUSTOMER" in report.evidence_zip_path

    @pytest.mark.asyncio
    async def test_internal_mode(self):
        """Should generate internal report without redaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate(output_mode=OutputMode.INTERNAL)

            assert "INTERNAL" in report.evidence_zip_path


class TestComplianceMatrix:
    """Test compliance matrix generation."""

    @pytest.mark.asyncio
    async def test_includes_gdpr(self):
        """Should include GDPR compliance mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate(frameworks=["GDPR"])

            content = Path(report.compliance_path).read_text(encoding='utf-8')
            assert "GDPR" in content
            assert "Art. 5" in content
            assert "Art. 32" in content

    @pytest.mark.asyncio
    async def test_includes_soc2(self):
        """Should include SOC2 compliance mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate(frameworks=["SOC2"])

            content = Path(report.compliance_path).read_text(encoding='utf-8')
            assert "SOC 2" in content
            assert "CC6.1" in content

    @pytest.mark.asyncio
    async def test_includes_iso27001(self):
        """Should include ISO27001 compliance mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            generator = EnterpriseAuditReportGenerator(
                evidence_dir=output_dir,
                output_dir=output_dir,
            )

            report = await generator.generate(frameworks=["ISO27001"])

            content = Path(report.compliance_path).read_text(encoding='utf-8')
            assert "ISO 27001" in content
            assert "A.5.15" in content


class TestCustomEvidenceLoader:
    """Test custom evidence loading."""

    @pytest.mark.asyncio
    async def test_custom_evidence_loader(self):
        """Should use custom evidence loader when provided."""
        async def custom_loader(name: str):
            if name == "rls_harness.json":
                return {
                    "coverage_percent": 100.0,
                    "leaks_detected": 0,
                    "timestamp": "2026-01-07T12:00:00Z",
                }
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            generator = EnterpriseAuditReportGenerator(
                output_dir=Path(tmpdir),
                evidence_loader=custom_loader,
            )

            report = await generator.generate()

            rls_evidence = next(e for e in report.evidence if e.name == "rls_harness")
            assert rls_evidence.status == "PASS"
            assert rls_evidence.data["coverage_percent"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
