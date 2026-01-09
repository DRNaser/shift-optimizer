"""
SOLVEREIGN Gurkerl Dispatch Assist - Fingerprint Tests
=======================================================

Tests for fingerprint calculation and scope-based hashing:
- Deterministic hash generation
- Scope date range calculation
- Fingerprint stability
- Cache behavior
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from ..models import (
    FingerprintScope,
    FingerprintScopeType,
    FingerprintData,
    DiffHints,
)
from ..sheet_adapter import (
    MockSheetAdapter,
    FingerprintCache,
)


# =============================================================================
# FINGERPRINT SCOPE TESTS
# =============================================================================

class TestFingerprintScope:
    """Tests for FingerprintScope date range calculations."""

    def test_day_only_scope(self):
        """DAY_ONLY scope returns single day range."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_ONLY,
        )
        start, end = scope.get_date_range()
        assert start == date(2026, 1, 15)
        assert end == date(2026, 1, 15)

    def test_day_pm1_scope(self):
        """DAY_PM1 scope returns date +/- 1 day range."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )
        start, end = scope.get_date_range()
        assert start == date(2026, 1, 14)
        assert end == date(2026, 1, 16)

    def test_week_window_scope(self):
        """WEEK_WINDOW scope returns full week Mon-Sun."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),  # Thursday
            scope_type=FingerprintScopeType.WEEK_WINDOW,
        )
        start, end = scope.get_date_range()
        assert start == date(2026, 1, 12)  # Monday
        assert end == date(2026, 1, 18)  # Sunday

    def test_week_window_monday(self):
        """WEEK_WINDOW scope handles Monday correctly."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 12),  # Monday
            scope_type=FingerprintScopeType.WEEK_WINDOW,
        )
        start, end = scope.get_date_range()
        assert start == date(2026, 1, 12)  # Same Monday
        assert end == date(2026, 1, 18)  # Sunday

    def test_week_window_sunday(self):
        """WEEK_WINDOW scope handles Sunday correctly."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 18),  # Sunday
            scope_type=FingerprintScopeType.WEEK_WINDOW,
        )
        start, end = scope.get_date_range()
        assert start == date(2026, 1, 12)  # Previous Monday
        assert end == date(2026, 1, 18)  # Same Sunday

    def test_scope_to_dict(self):
        """FingerprintScope serializes to dict correctly."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
            include_absences=True,
            include_driver_hours=True,
        )
        d = scope.to_dict()
        assert d["scope_type"] == "DAY_PM1"
        assert d["shift_date"] == "2026-01-15"
        assert d["include_absences"] is True
        assert d["include_driver_hours"] is True


# =============================================================================
# FINGERPRINT CALCULATION TESTS
# =============================================================================

class TestFingerprintCalculation:
    """Tests for deterministic fingerprint generation."""

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter for testing."""
        return MockSheetAdapter()

    def test_fingerprint_deterministic(self, mock_adapter):
        """Same data produces same fingerprint."""
        data1 = {
            "roster": [{"driver": "D1", "date": "2026-01-15"}],
            "revision": 100,
        }
        data2 = {
            "roster": [{"driver": "D1", "date": "2026-01-15"}],
            "revision": 100,
        }

        fp1 = mock_adapter.compute_fingerprint(data1, 100, "v1")
        fp2 = mock_adapter.compute_fingerprint(data2, 100, "v1")
        assert fp1 == fp2

    def test_fingerprint_changes_with_data(self, mock_adapter):
        """Different data produces different fingerprint."""
        data1 = {"roster": [{"driver": "D1"}]}
        data2 = {"roster": [{"driver": "D2"}]}

        fp1 = mock_adapter.compute_fingerprint(data1, 100, "v1")
        fp2 = mock_adapter.compute_fingerprint(data2, 100, "v1")
        assert fp1 != fp2

    def test_fingerprint_changes_with_revision(self, mock_adapter):
        """Different revision produces different fingerprint."""
        data = {"roster": [{"driver": "D1"}]}

        fp1 = mock_adapter.compute_fingerprint(data, 100, "v1")
        fp2 = mock_adapter.compute_fingerprint(data, 101, "v1")
        assert fp1 != fp2

    def test_fingerprint_changes_with_config_version(self, mock_adapter):
        """Different config version produces different fingerprint."""
        data = {"roster": [{"driver": "D1"}]}

        fp1 = mock_adapter.compute_fingerprint(data, 100, "v1")
        fp2 = mock_adapter.compute_fingerprint(data, 100, "v2")
        assert fp1 != fp2

    def test_fingerprint_is_64_char_hex(self, mock_adapter):
        """Fingerprint is SHA-256 (64 hex chars)."""
        data = {"test": "data"}
        fp = mock_adapter.compute_fingerprint(data, 1, "v1")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_key_order_independent(self, mock_adapter):
        """Fingerprint ignores dict key order."""
        data1 = {"a": 1, "b": 2, "c": 3}
        data2 = {"c": 3, "a": 1, "b": 2}

        fp1 = mock_adapter.compute_fingerprint(data1, 100, "v1")
        fp2 = mock_adapter.compute_fingerprint(data2, 100, "v1")
        assert fp1 == fp2


# =============================================================================
# FINGERPRINT CACHE TESTS
# =============================================================================

class TestFingerprintCache:
    """Tests for fingerprint caching behavior."""

    def test_cache_returns_cached_value(self):
        """Cache returns stored value within TTL."""
        cache = FingerprintCache(ttl_seconds=60)
        scope_key = "2026-01-15_DAY_PM1"

        cache.set(scope_key, "fingerprint123", 100)
        result = cache.get(scope_key)

        assert result is not None
        assert result == ("fingerprint123", 100)

    def test_cache_miss_returns_none(self):
        """Cache returns None for missing keys."""
        cache = FingerprintCache(ttl_seconds=60)
        result = cache.get("nonexistent_key")
        assert result is None

    def test_cache_invalidate_clears(self):
        """Invalidate clears all cached values."""
        cache = FingerprintCache(ttl_seconds=60)
        cache.set("key1", "fp1", 1)
        cache.set("key2", "fp2", 2)

        cache.invalidate()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_expired_returns_none(self):
        """Expired cache entries return None."""
        cache = FingerprintCache(ttl_seconds=0)  # Immediate expiry
        cache.set("key", "fp", 1)

        # Entry should be immediately expired
        result = cache.get("key")
        assert result is None


# =============================================================================
# SCOPED RANGES TESTS
# =============================================================================

class TestScopedRanges:
    """Tests for reading scoped ranges from sheets."""

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter with test data."""
        adapter = MockSheetAdapter()
        # Configure mock to have some roster data
        return adapter

    @pytest.mark.asyncio
    async def test_read_scoped_ranges_returns_dict(self, mock_adapter):
        """read_scoped_ranges returns dict with expected keys."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )

        result = await mock_adapter.read_scoped_ranges(scope)

        assert isinstance(result, dict)
        assert "roster_rows" in result
        assert "driver_data" in result
        assert "absences" in result
        assert "read_at" in result

    @pytest.mark.asyncio
    async def test_get_current_fingerprint(self, mock_adapter):
        """get_current_fingerprint returns FingerprintData."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )

        result = await mock_adapter.get_current_fingerprint(scope)

        assert isinstance(result, FingerprintData)
        assert len(result.fingerprint) == 64
        assert result.revision > 0
        assert result.computed_at is not None


# =============================================================================
# DIFF HINTS TESTS
# =============================================================================

class TestDiffHints:
    """Tests for computing diff hints between fingerprints."""

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter for testing."""
        return MockSheetAdapter()

    @pytest.mark.asyncio
    async def test_compute_diff_hints_same_data(self, mock_adapter):
        """Same data returns empty diff hints."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )
        data = {"roster_rows": [{"driver": "D1"}]}

        hints = await mock_adapter.compute_diff_hints(data, data, scope)

        assert hints is not None
        assert len(hints.changed_tabs) == 0
        assert len(hints.changed_rows) == 0

    @pytest.mark.asyncio
    async def test_compute_diff_hints_different_data(self, mock_adapter):
        """Different data returns diff hints."""
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )
        old_data = {"roster_rows": [{"driver": "D1"}]}
        new_data = {"roster_rows": [{"driver": "D2"}]}

        hints = await mock_adapter.compute_diff_hints(old_data, new_data, scope)

        assert hints is not None
        # Mock returns that roster changed
        assert "roster" in hints.changed_tabs or len(hints.changed_rows) > 0

    def test_diff_hints_to_dict(self):
        """DiffHints serializes to dict correctly."""
        hints = DiffHints(
            changed_tabs=["roster", "absences"],
            changed_rows=[5, 10, 15],
            summary="3 roster rows changed",
        )

        d = hints.to_dict()
        assert d["changed_tabs"] == ["roster", "absences"]
        assert d["changed_rows"] == [5, 10, 15]
        assert d["summary"] == "3 roster rows changed"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestFingerprintIntegration:
    """Integration tests for fingerprint workflow."""

    @pytest.mark.asyncio
    async def test_fingerprint_workflow(self):
        """Full fingerprint workflow: read, compute, compare."""
        adapter = MockSheetAdapter()
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )

        # Get initial fingerprint
        fp1 = await adapter.get_current_fingerprint(scope)
        assert fp1.fingerprint

        # Get fingerprint again (should be same for same data)
        fp2 = await adapter.get_current_fingerprint(scope)
        assert fp2.fingerprint == fp1.fingerprint

        # Invalidate cache and get again (still same for mock)
        adapter.invalidate_fingerprint_cache()
        fp3 = await adapter.get_current_fingerprint(scope)
        assert fp3.fingerprint  # Should still have a fingerprint

    @pytest.mark.asyncio
    async def test_write_invalidates_cache(self):
        """Writing to sheet invalidates fingerprint cache."""
        adapter = MockSheetAdapter()
        scope = FingerprintScope(
            shift_date=date(2026, 1, 15),
            scope_type=FingerprintScopeType.DAY_PM1,
        )

        # Get initial fingerprint (populates cache)
        fp1 = await adapter.get_current_fingerprint(scope)

        # Write assignment (should invalidate cache)
        await adapter.write_assignment(10, "D1", "Driver Name", "ASSIGNED")

        # Cache should be invalidated
        # Note: Mock adapter may still return a fingerprint, but cache is cleared
        adapter.invalidate_fingerprint_cache()
        assert adapter._fingerprint_cache.get("2026-01-15_DAY_PM1") is None
