"""
Evidence Filename Security Tests
================================

Tests for path traversal prevention and filename validation.

Run with: pytest backend_py/api/tests/test_evidence_security.py -v
"""

import pytest
from fastapi import HTTPException

# Import the validation function from evidence_viewer
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.evidence_viewer import _validate_evidence_filename


class TestValidEvidenceFilenames:
    """Tests for valid evidence filenames."""

    def test_valid_roster_filename(self):
        """Valid roster evidence filename should pass."""
        result = _validate_evidence_filename(
            "roster_publish_1_10_123_20260110T120000.json",
            tenant_id=1
        )
        assert result == "roster_publish_1_10_123_20260110T120000.json"

    def test_valid_routing_filename(self):
        """Valid routing evidence filename should pass."""
        result = _validate_evidence_filename(
            "routing_solve_2_20_456_20260110T143000.json",
            tenant_id=2
        )
        assert result == "routing_solve_2_20_456_20260110T143000.json"


class TestPathTraversalPrevention:
    """Tests for path traversal attack prevention."""

    def test_blocks_dot_dot_slash(self):
        """Block ../ traversal."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("../../../etc/passwd", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_dot_dot_backslash(self):
        """Block ..\\ traversal."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("..\\..\\Windows\\win.ini", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_url_encoded_traversal(self):
        """Block URL-encoded ../ traversal."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("%2e%2e%2fetc/passwd", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_double_encoded_traversal(self):
        """Block double-encoded ../ traversal."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("%252e%252e%252f", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_url_encoded_backslash(self):
        """Block URL-encoded backslash."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("%5c%5cserver%5cshare", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_null_byte_injection(self):
        """Block null byte injection."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("valid.json\x00.exe", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_url_encoded_null_byte(self):
        """Block URL-encoded null byte."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish_1_10_123_ts.json%00.exe", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_mixed_traversal_attempts(self):
        """Block mixed traversal attempts."""
        payloads = [
            "....//....//etc/passwd",
            "..%2f..%2fetc/passwd",
            "%2e%2e/%2e%2e/etc/passwd",
            "..%252f..%252f",
            "..\\..\\..\\etc\\passwd",
        ]
        for payload in payloads:
            with pytest.raises(HTTPException) as exc:
                _validate_evidence_filename(payload, tenant_id=1)
            assert exc.value.status_code in (400, 404), f"Failed for: {payload}"


class TestAbsolutePathPrevention:
    """Tests for absolute path prevention."""

    def test_blocks_unix_absolute_path(self):
        """Block Unix absolute path."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("/etc/passwd", tenant_id=1)
        assert exc.value.status_code == 404

    def test_blocks_windows_absolute_path(self):
        """Block Windows absolute path."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("C:\\Windows\\win.ini", tenant_id=1)
        assert exc.value.status_code == 404


class TestExtensionWhitelist:
    """Tests for extension whitelist."""

    def test_rejects_exe_extension(self):
        """Reject .exe extension."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish_1_10_123_ts.exe", tenant_id=1)
        assert exc.value.status_code == 404

    def test_rejects_double_extension(self):
        """Reject .json.exe double extension."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish_1_10_123_ts.json.exe", tenant_id=1)
        assert exc.value.status_code == 404

    def test_rejects_txt_extension(self):
        """Reject .txt extension."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish_1_10_123_ts.txt", tenant_id=1)
        assert exc.value.status_code == 404

    def test_rejects_log_extension(self):
        """Reject .log extension."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish_1_10_123_ts.log", tenant_id=1)
        assert exc.value.status_code == 404


class TestFilenameFormat:
    """Tests for filename format validation."""

    def test_rejects_short_filename(self):
        """Reject filename with too few parts."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("roster_publish.json", tenant_id=1)
        assert exc.value.status_code == 400
        assert "Invalid filename format" in str(exc.value.detail)

    def test_rejects_invalid_structure(self):
        """Reject filename without proper structure."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename("somefile.json", tenant_id=1)
        assert exc.value.status_code == 400


class TestTenantIsolation:
    """Tests for tenant isolation."""

    def test_blocks_wrong_tenant_access(self):
        """Block access to other tenant's evidence."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename(
                "roster_publish_2_10_123_20260110T120000.json",
                tenant_id=1  # User is tenant 1, file is tenant 2
            )
        assert exc.value.status_code == 404

    def test_allows_correct_tenant_access(self):
        """Allow access to own tenant's evidence."""
        result = _validate_evidence_filename(
            "roster_publish_1_10_123_20260110T120000.json",
            tenant_id=1
        )
        assert result == "roster_publish_1_10_123_20260110T120000.json"

    def test_rejects_non_numeric_tenant(self):
        """Reject filename with non-numeric tenant ID."""
        with pytest.raises(HTTPException) as exc:
            _validate_evidence_filename(
                "roster_publish_abc_10_123_20260110T120000.json",
                tenant_id=1
            )
        assert exc.value.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
