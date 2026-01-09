# =============================================================================
# SOLVEREIGN Routing Pack - OSRM Map Hash Tests
# =============================================================================
# Tests for path-neutral deterministic OSRM map hash computation.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_osrm_map_hash.py -v
# =============================================================================

import os
import pytest
import tempfile
from pathlib import Path

from backend_py.packs.routing.services.finalize.osrm_map_hash import (
    compute_osrm_map_hash,
    get_osrm_map_hash_from_env,
    check_osrm_map_usable,
    OSRMMapInfo,
    OSRMMapStatus,
    HashScope,
    OSRM_REQUIRED_EXTENSIONS,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_osrm_files():
    """Create temporary OSRM files with known content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = Path(tmpdir) / "test-map"

        # Create required files with deterministic content
        content = {
            ".osrm": b"OSRM_GRAPH_DATA_V1" + b"\x00" * 100,
            ".osrm.names": b"street_names_index_v1" + b"\x00" * 50,
            ".osrm.properties": b"profile=car\nversion=5.27.1\n",
        }

        for ext, data in content.items():
            file_path = Path(f"{base_path}{ext}")
            file_path.write_bytes(data)

        yield str(base_path), content


@pytest.fixture
def temp_osrm_files_different_paths():
    """Create identical OSRM files at two different paths."""
    with tempfile.TemporaryDirectory() as tmpdir1, \
         tempfile.TemporaryDirectory() as tmpdir2:

        base_path1 = Path(tmpdir1) / "austria-latest"
        base_path2 = Path(tmpdir2) / "staging" / "map" / "austria-v2"
        base_path2.parent.mkdir(parents=True, exist_ok=True)

        # Same content at both paths
        content = {
            ".osrm": b"IDENTICAL_OSRM_GRAPH_DATA" + b"\x00" * 100,
            ".osrm.names": b"identical_street_names" + b"\x00" * 50,
            ".osrm.properties": b"profile=car\nversion=5.27.1\n",
        }

        for ext, data in content.items():
            Path(f"{base_path1}{ext}").write_bytes(data)
            Path(f"{base_path2}{ext}").write_bytes(data)

        yield str(base_path1), str(base_path2), content


# =============================================================================
# PATH-NEUTRAL DETERMINISM TESTS
# =============================================================================

class TestPathNeutralDeterminism:
    """Tests for path-neutral hash computation."""

    def test_same_content_different_paths_same_hash(
        self,
        temp_osrm_files_different_paths,
    ):
        """
        CRITICAL: Same map content at different paths MUST produce identical hash.

        This is the key property for audit consistency across staging/prod.
        """
        path1, path2, _ = temp_osrm_files_different_paths

        info1 = compute_osrm_map_hash(path1)
        info2 = compute_osrm_map_hash(path2)

        # Both must succeed
        assert info1.status == OSRMMapStatus.OK, f"Path1 failed: {info1.error_message}"
        assert info2.status == OSRMMapStatus.OK, f"Path2 failed: {info2.error_message}"

        # Hashes MUST be identical
        assert info1.map_hash == info2.map_hash, \
            f"Hash mismatch! Path1: {info1.map_hash[:16]}... Path2: {info2.map_hash[:16]}..."

        # Verify paths are actually different
        assert path1 != path2

    def test_hash_is_stable_across_runs(self, temp_osrm_files):
        """Same path computed multiple times produces identical hash."""
        base_path, _ = temp_osrm_files

        hashes = []
        for _ in range(5):
            info = compute_osrm_map_hash(base_path)
            assert info.status == OSRMMapStatus.OK
            hashes.append(info.map_hash)

        assert len(set(hashes)) == 1, f"Hash instability: {hashes}"

    def test_different_content_different_hash(self, temp_osrm_files):
        """Different content MUST produce different hash."""
        base_path, _ = temp_osrm_files

        # Get original hash
        info1 = compute_osrm_map_hash(base_path)
        assert info1.status == OSRMMapStatus.OK

        # Modify content
        osrm_file = Path(f"{base_path}.osrm")
        original_content = osrm_file.read_bytes()
        osrm_file.write_bytes(original_content + b"MODIFIED")

        # Get new hash
        info2 = compute_osrm_map_hash(base_path)
        assert info2.status == OSRMMapStatus.OK

        # Hashes MUST be different
        assert info1.map_hash != info2.map_hash


# =============================================================================
# MISSING REQUIRED FILES TESTS
# =============================================================================

class TestMissingRequiredFiles:
    """Tests for fail-closed behavior with missing files."""

    def test_missing_required_returns_status_not_ok(self, temp_osrm_files):
        """Missing required file returns MISSING_REQUIRED status, not OK."""
        base_path, _ = temp_osrm_files

        # Delete a required file
        properties_file = Path(f"{base_path}.osrm.properties")
        properties_file.unlink()

        info = compute_osrm_map_hash(base_path)

        # Status must NOT be OK
        assert info.status == OSRMMapStatus.MISSING_REQUIRED
        assert info.map_hash is None
        assert ".osrm.properties" in info.missing_files

    def test_missing_required_blocks_usability(self, temp_osrm_files):
        """Missing required file causes block in usability check."""
        base_path, _ = temp_osrm_files

        # Delete required file
        Path(f"{base_path}.osrm.names").unlink()

        info = compute_osrm_map_hash(base_path)
        is_usable, block_reason = check_osrm_map_usable(info)

        assert not is_usable
        assert block_reason is not None
        assert "Missing" in block_reason

    def test_all_required_files_missing(self):
        """No files at path returns NOT_FOUND."""
        with tempfile.TemporaryDirectory() as tmpdir:
            info = compute_osrm_map_hash(f"{tmpdir}/nonexistent")

            assert info.status == OSRMMapStatus.NOT_FOUND
            assert info.map_hash is None


# =============================================================================
# ENV PROFILE PROPAGATION TESTS
# =============================================================================

class TestEnvProfilePropagation:
    """Tests for environment variable profile propagation."""

    def test_profile_from_env_with_hash(self, monkeypatch):
        """Profile is correctly set when using pre-computed hash."""
        monkeypatch.setenv("SOLVEREIGN_OSRM_MAP_HASH", "abc123def456")
        monkeypatch.setenv("SOLVEREIGN_OSRM_PROFILE", "truck")

        info = get_osrm_map_hash_from_env()

        assert info.status == OSRMMapStatus.OK
        assert info.profile == "truck"
        assert info.map_hash == "abc123def456"

    def test_profile_from_env_with_path(self, temp_osrm_files, monkeypatch):
        """Profile is correctly propagated when computing from path."""
        base_path, _ = temp_osrm_files

        monkeypatch.setenv("SOLVEREIGN_OSRM_MAP_PATH", base_path)
        monkeypatch.setenv("SOLVEREIGN_OSRM_PROFILE", "bicycle")

        info = get_osrm_map_hash_from_env()

        assert info.status == OSRMMapStatus.OK
        assert info.profile == "bicycle"

    def test_default_profile_is_car(self, monkeypatch):
        """Default profile is 'car' when not specified."""
        monkeypatch.setenv("SOLVEREIGN_OSRM_MAP_HASH", "xyz789")
        monkeypatch.delenv("SOLVEREIGN_OSRM_PROFILE", raising=False)

        info = get_osrm_map_hash_from_env()

        assert info.profile == "car"


# =============================================================================
# STATUS AND USABILITY TESTS
# =============================================================================

class TestStatusAndUsability:
    """Tests for status field and usability checks."""

    def test_ok_status_is_usable(self, temp_osrm_files):
        """OK status is usable."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path)

        assert info.status == OSRMMapStatus.OK
        assert info.is_ok
        assert info.is_usable

        is_usable, block_reason = check_osrm_map_usable(info)
        assert is_usable
        assert block_reason is None

    def test_not_configured_blocks_by_default(self, monkeypatch):
        """NOT_CONFIGURED status blocks by default."""
        monkeypatch.delenv("SOLVEREIGN_OSRM_MAP_HASH", raising=False)
        monkeypatch.delenv("SOLVEREIGN_OSRM_MAP_PATH", raising=False)

        info = get_osrm_map_hash_from_env()

        assert info.status == OSRMMapStatus.NOT_CONFIGURED

        is_usable, block_reason = check_osrm_map_usable(info, allow_degraded=False)
        assert not is_usable
        assert "not configured" in block_reason.lower()

    def test_not_configured_allowed_in_degraded_mode(self, monkeypatch):
        """NOT_CONFIGURED status is allowed in degraded mode."""
        monkeypatch.delenv("SOLVEREIGN_OSRM_MAP_HASH", raising=False)
        monkeypatch.delenv("SOLVEREIGN_OSRM_MAP_PATH", raising=False)

        info = get_osrm_map_hash_from_env()

        is_usable, block_reason = check_osrm_map_usable(info, allow_degraded=True)
        assert is_usable
        assert block_reason is None


# =============================================================================
# HASH SCOPE TESTS
# =============================================================================

class TestHashScope:
    """Tests for hash scope field."""

    def test_full_set_scope_by_default(self, temp_osrm_files):
        """Default scope is FULL_SET."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path, include_all=True)

        assert info.hash_scope == HashScope.FULL_SET

    def test_required_only_scope(self, temp_osrm_files):
        """include_all=False gives REQUIRED_ONLY scope."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path, include_all=False)

        assert info.hash_scope == HashScope.REQUIRED_ONLY


# =============================================================================
# EVIDENCE FORMAT TESTS
# =============================================================================

class TestEvidenceFormat:
    """Tests for evidence dict format."""

    def test_to_evidence_dict_structure(self, temp_osrm_files):
        """Evidence dict has correct structure."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path)
        evidence = info.to_evidence_dict()

        assert "osrm_map" in evidence
        osrm_map = evidence["osrm_map"]

        # Required fields
        assert "status" in osrm_map
        assert "hash" in osrm_map
        assert "hash_algorithm" in osrm_map
        assert "hash_scope" in osrm_map
        assert "profile" in osrm_map
        assert "computed_at" in osrm_map

    def test_to_dict_includes_error_message(self):
        """Error message is included in dict for failed status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            info = compute_osrm_map_hash(f"{tmpdir}/nonexistent")
            d = info.to_dict()

            assert d["status"] == "NOT_FOUND"
            assert d["map_hash"] is None
            assert d["error_message"] is not None


# =============================================================================
# UTC TIMESTAMP TESTS
# =============================================================================

class TestUTCTimestamps:
    """Tests for UTC timestamp handling."""

    def test_computed_at_is_utc(self, temp_osrm_files):
        """computed_at is timezone-aware UTC."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path)

        assert info.computed_at.tzinfo is not None
        assert info.computed_at.tzname() == "UTC"

    def test_newest_mtime_is_utc(self, temp_osrm_files):
        """newest_mtime is timezone-aware UTC."""
        base_path, _ = temp_osrm_files

        info = compute_osrm_map_hash(base_path)

        assert info.newest_mtime is not None
        assert info.newest_mtime.tzinfo is not None
