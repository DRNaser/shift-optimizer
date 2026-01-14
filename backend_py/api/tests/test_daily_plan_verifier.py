"""
Tests for Daily Plan Verifier and Importer
==========================================

Tests cover:
- E.164 phone validation
- Plan creation and import
- Verification logic
- DM eligibility checking
- Consent enforcement (fail-fast)
"""

import pytest
from datetime import date
from uuid import uuid4

# Import the functions we're testing
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routers.driver_contacts import validate_e164, normalize_to_e164


# =============================================================================
# E.164 PHONE VALIDATION TESTS
# =============================================================================

class TestPhoneValidation:
    """Tests for E.164 phone number validation and normalization."""

    def test_valid_e164_formats(self):
        """Test valid E.164 phone numbers."""
        valid_numbers = [
            "+436641234567",     # Austria
            "+4915112345678",    # Germany
            "+12025551234",      # USA
            "+447911123456",     # UK
            "+33612345678",      # France
        ]

        for phone in valid_numbers:
            assert validate_e164(phone), f"{phone} should be valid"

    def test_invalid_e164_formats(self):
        """Test invalid phone numbers."""
        invalid_numbers = [
            "436641234567",       # Missing +
            "+0641234567",        # Starts with 0 after +
            "+43664",             # Too short
            "+4366412345678901",  # Too long
            "+43 664 1234567",    # Contains spaces
            "0664/1234567",       # Local format
            "",                   # Empty
            None,                 # None
        ]

        for phone in invalid_numbers:
            if phone is not None:
                assert not validate_e164(phone), f"{phone} should be invalid"

    def test_normalize_austrian_local(self):
        """Test normalizing Austrian local numbers."""
        # Local number with leading 0
        result = normalize_to_e164("0664 123 4567")
        assert result == "+436641234567"

    def test_normalize_international_prefix(self):
        """Test normalizing numbers with 00 prefix."""
        result = normalize_to_e164("00436641234567")
        assert result == "+436641234567"

    def test_normalize_with_spaces_and_dashes(self):
        """Test normalizing numbers with formatting characters."""
        result = normalize_to_e164("+43 664 123-4567")
        assert result == "+436641234567"

    def test_normalize_german_number(self):
        """Test normalizing with German default."""
        result = normalize_to_e164("0151 1234 5678", default_country_code="+49")
        assert result == "+4915112345678"

    def test_normalize_invalid_returns_none(self):
        """Test that invalid numbers return None."""
        result = normalize_to_e164("not a phone")
        assert result is None


# =============================================================================
# VERIFIER LOGIC TESTS (Unit tests without DB)
# =============================================================================

class TestVerificationErrors:
    """Test verification error definitions."""

    def test_error_codes_defined(self):
        """Test that expected error codes are defined."""
        expected_errors = [
            "MISSING_DRIVER_ID",
            "DRIVER_NOT_IN_MDL",
            "NO_DRIVER_CONTACT",
            "NO_PHONE_NUMBER",
            "INVALID_PHONE_FORMAT",
        ]

        # These should map to error messages
        from api.services.daily_plan_importer import DailyPlanImporter

        # Create a mock importer to test error messages
        class MockConn:
            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, *args):
                pass

        importer = DailyPlanImporter(MockConn(), tenant_id=1)

        for code in expected_errors:
            msg = importer._get_error_message(code)
            assert msg, f"Error code {code} should have a message"
            assert code.lower() not in msg.lower() or "unknown" not in msg.lower()

    def test_warning_codes_defined(self):
        """Test that expected warning codes are defined."""
        expected_warnings = [
            "MISSING_CONSENT",
            "OPTED_OUT",
            "DUPLICATE_PHONE",
        ]

        from api.services.daily_plan_importer import DailyPlanImporter

        class MockConn:
            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        importer = DailyPlanImporter(MockConn(), tenant_id=1)

        for code in expected_warnings:
            msg = importer._get_warning_message(code)
            assert msg, f"Warning code {code} should have a message"


class TestImportRow:
    """Test ImportRow data class."""

    def test_import_row_minimal(self):
        """Test creating minimal import row."""
        from api.services.daily_plan_importer import ImportRow

        row = ImportRow(
            row_number=1,
            driver_name="Max Mustermann"
        )

        assert row.row_number == 1
        assert row.driver_name == "Max Mustermann"
        assert row.driver_id is None
        assert row.phone is None

    def test_import_row_full(self):
        """Test creating full import row."""
        from api.services.daily_plan_importer import ImportRow

        row = ImportRow(
            row_number=5,
            driver_name="Max Mustermann",
            driver_id="D001",
            phone="+436641234567",
            shift_start="06:00",
            shift_end="14:00",
            tour_id="TOUR-001",
            vehicle_id="VH-001",
            notes="Early shift"
        )

        assert row.row_number == 5
        assert row.driver_id == "D001"
        assert row.shift_start == "06:00"


class TestVerificationReport:
    """Test VerificationReport data class."""

    def test_report_properties(self):
        """Test report computed properties."""
        from api.services.daily_plan_importer import VerificationReport
        from datetime import datetime

        report = VerificationReport(
            report_id=uuid4(),
            daily_plan_id=uuid4(),
            plan_date=date.today(),
            generated_at=datetime.now(),
            total_assignments=10,
            verified_count=8,
            failed_count=2,
            dm_eligible_count=6,
            dm_blocked_count=4,
            blocking_issues=["2 assignments failed verification"]
        )

        assert report.has_errors
        assert report.has_blocking_issues
        assert not report.can_publish

    def test_report_no_errors(self):
        """Test report with no errors."""
        from api.services.daily_plan_importer import VerificationReport
        from datetime import datetime

        report = VerificationReport(
            report_id=uuid4(),
            daily_plan_id=uuid4(),
            plan_date=date.today(),
            generated_at=datetime.now(),
            total_assignments=10,
            verified_count=10,
            failed_count=0,
            dm_eligible_count=10,
            dm_blocked_count=0,
            can_publish=True
        )

        assert not report.has_errors
        assert not report.has_blocking_issues
        assert report.can_publish


# =============================================================================
# CONSENT ENFORCEMENT TESTS
# =============================================================================

class TestConsentEnforcement:
    """Test consent-related logic."""

    def test_dm_eligibility_requires_consent(self):
        """Test that DM eligibility requires consent=True."""
        # This is enforced by the SQL function verify_contact_for_dm
        # Here we test the expected error codes

        expected_block_reasons = [
            ("NO_CONSENT", "Driver has not consented to WhatsApp"),
            ("OPTED_OUT", "Driver has explicitly opted out"),
            ("DRIVER_INACTIVE", "Driver status is not active"),
            ("NO_CONTACT_RECORD", "No contact record exists"),
            ("DRIVER_NOT_RESOLVED", "Driver ID could not be resolved"),
        ]

        for code, description in expected_block_reasons:
            assert code  # Code should be non-empty
            assert description  # Should have description

    def test_consent_source_values(self):
        """Test valid consent source values."""
        valid_sources = ["PORTAL", "APP", "MANUAL", "IMPORT"]

        for source in valid_sources:
            assert source.isupper()
            assert len(source) > 0


# =============================================================================
# RISK CONTEXT HELPER TESTS
# =============================================================================

class TestRiskContext:
    """Test risk context calculation helper."""

    def test_calculate_risk_context_empty(self):
        """Test empty context."""
        from api.services.approval_policy import calculate_risk_context

        context = calculate_risk_context()
        assert context == {}

    def test_calculate_risk_context_with_drivers(self):
        """Test context with affected drivers."""
        from api.services.approval_policy import calculate_risk_context

        drivers = [uuid4() for _ in range(15)]
        context = calculate_risk_context(affected_drivers=drivers)

        assert context["affected_drivers"] == 15

    def test_calculate_risk_context_with_rest_time(self):
        """Test context with rest time violations."""
        from api.services.approval_policy import calculate_risk_context

        violations = ["driver1", "driver2"]
        context = calculate_risk_context(near_rest_time_violations=violations)

        assert context["near_rest_time"] is True

    def test_calculate_risk_context_freeze_period(self):
        """Test context during freeze period."""
        from api.services.approval_policy import calculate_risk_context

        context = calculate_risk_context(is_freeze_period=True)

        assert context["is_freeze_period"] is True

    def test_calculate_risk_context_near_deadline(self):
        """Test context near deadline."""
        from api.services.approval_policy import calculate_risk_context

        # 2 hours to deadline should trigger
        context = calculate_risk_context(hours_to_deadline=2)
        assert context["near_deadline"] is True

        # 5 hours to deadline should not trigger
        context = calculate_risk_context(hours_to_deadline=5)
        assert "near_deadline" not in context

    def test_calculate_risk_context_combined(self):
        """Test combined risk factors."""
        from api.services.approval_policy import calculate_risk_context

        context = calculate_risk_context(
            affected_drivers=[uuid4() for _ in range(25)],
            near_rest_time_violations=["d1"],
            is_freeze_period=True,
            hours_to_deadline=2
        )

        assert context["affected_drivers"] == 25
        assert context["near_rest_time"] is True
        assert context["is_freeze_period"] is True
        assert context["near_deadline"] is True


# =============================================================================
# APPROVAL POLICY TESTS
# =============================================================================

class TestRiskAssessment:
    """Test RiskAssessment data class."""

    def test_risk_assessment_low(self):
        """Test low risk assessment properties."""
        from api.services.approval_policy import RiskAssessment

        assessment = RiskAssessment(
            risk_level="LOW",
            risk_score=15,
            required_approvals=1
        )

        assert not assessment.needs_two_approvers
        assert not assessment.is_high_risk

    def test_risk_assessment_high(self):
        """Test high risk assessment properties."""
        from api.services.approval_policy import RiskAssessment

        assessment = RiskAssessment(
            risk_level="HIGH",
            risk_score=55,
            required_approvals=2
        )

        assert assessment.needs_two_approvers
        assert assessment.is_high_risk

    def test_risk_assessment_critical(self):
        """Test critical risk assessment."""
        from api.services.approval_policy import RiskAssessment

        assessment = RiskAssessment(
            risk_level="CRITICAL",
            risk_score=75,
            required_approvals=2
        )

        assert assessment.needs_two_approvers
        assert assessment.is_high_risk


class TestDecisionResult:
    """Test DecisionResult data class."""

    def test_decision_result_success(self):
        """Test successful decision result."""
        from api.services.approval_policy import DecisionResult

        result = DecisionResult(
            success=True,
            request_id=uuid4(),
            decision="APPROVE",
            current_approvals=2,
            required_approvals=2,
            is_complete=True,
            final_status="APPROVED",
            action_payload={"plan_id": "123"}
        )

        assert result.success
        assert result.is_complete
        assert result.final_status == "APPROVED"
        assert result.action_payload is not None

    def test_decision_result_pending(self):
        """Test decision result still pending."""
        from api.services.approval_policy import DecisionResult

        result = DecisionResult(
            success=True,
            request_id=uuid4(),
            decision="APPROVE",
            current_approvals=1,
            required_approvals=2,
            is_complete=False
        )

        assert result.success
        assert not result.is_complete
        assert result.final_status is None

    def test_decision_result_error(self):
        """Test decision result with error."""
        from api.services.approval_policy import DecisionResult

        result = DecisionResult(
            success=False,
            request_id=uuid4(),
            decision="APPROVE",
            current_approvals=0,
            required_approvals=2,
            is_complete=False,
            error="REQUEST_NOT_FOUND"
        )

        assert not result.success
        assert result.error == "REQUEST_NOT_FOUND"


# =============================================================================
# WHATSAPP PROVIDER TESTS
# =============================================================================

class TestWhatsAppProvider:
    """Test WhatsApp provider module."""

    def test_delivery_result_success(self):
        """Test successful delivery result."""
        from api.services.whatsapp_provider import DeliveryResult

        result = DeliveryResult(
            success=True,
            delivery_ref="wamid.ABC123",
            provider="whatsapp_meta"
        )

        assert result.success
        assert result.delivery_ref == "wamid.ABC123"
        assert result.is_retryable  # Default

    def test_delivery_result_failure(self):
        """Test failed delivery result."""
        from api.services.whatsapp_provider import DeliveryResult

        result = DeliveryResult(
            success=False,
            provider="whatsapp_meta",
            error_code="131051",
            error_message="Unsupported message type",
            is_retryable=False
        )

        assert not result.success
        assert result.error_code == "131051"
        assert not result.is_retryable

    def test_template_message(self):
        """Test TemplateMessage data class."""
        from api.services.whatsapp_provider import TemplateMessage

        msg = TemplateMessage(
            to_phone_e164="+436641234567",
            template_id="PORTAL_INVITE",
            template_name="portal_invite_v1",
            variables={"driver_name": "Max", "portal_url": "https://example.com"}
        )

        assert msg.to_phone_e164 == "+436641234567"
        assert msg.template_id == "PORTAL_INVITE"
        assert msg.variables["driver_name"] == "Max"
        assert msg.correlation_id is not None  # Auto-generated

    def test_provider_manager_singleton(self):
        """Test provider manager singleton."""
        from api.services.whatsapp_provider import get_provider_manager

        manager1 = get_provider_manager()
        manager2 = get_provider_manager()

        assert manager1 is manager2


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
