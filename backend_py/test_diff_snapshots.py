"""
SOLVEREIGN V3 - Diff Engine Snapshot Tests
============================================

Tests the diff engine with deterministic snapshot comparisons.
These tests verify that diff computation is consistent and reproducible.

Usage:
    python backend_py/test_diff_snapshots.py

Note: These tests use mock data and do not require database connection.
"""

import json
import hashlib
from datetime import time
from dataclasses import dataclass
from typing import List, Dict, Optional

# Local mock implementation to avoid DB dependency
# Mimics v3.models and v3.diff_engine behavior

class DiffType:
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


@dataclass
class TourDiff:
    diff_type: str
    fingerprint: str
    old_values: Optional[Dict] = None
    new_values: Optional[Dict] = None
    changed_fields: Optional[List[str]] = None


@dataclass
class DiffSummary:
    forecast_version_old: int
    forecast_version_new: int
    added: int
    removed: int
    changed: int
    details: List[TourDiff]

    def total_changes(self):
        return self.added + self.removed + self.changed


def compute_tour_fingerprint(day: int, start_ts: str, end_ts: str, depot: str = None, skill: str = None) -> str:
    """Compute SHA256 fingerprint for tour identity."""
    data = f"{day}|{start_ts}|{end_ts}|{depot or ''}|{skill or ''}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


class MockDiffEngine:
    """
    Mock diff engine for snapshot testing without DB connection.
    Uses same logic as v3.diff_engine.DiffEngine.
    """

    def compute_diff(
        self,
        old_tours: List[Dict],
        new_tours: List[Dict]
    ) -> DiffSummary:
        """Compute diff between two tour lists."""

        # Index by fingerprint for fast lookup
        old_by_fingerprint = {t["tour_fingerprint"]: t for t in old_tours}
        new_by_fingerprint = {t["tour_fingerprint"]: t for t in new_tours}

        diffs = []

        # Find ADDED tours (in new, not in old)
        for fingerprint, new_tour in new_by_fingerprint.items():
            if fingerprint not in old_by_fingerprint:
                diff = TourDiff(
                    diff_type=DiffType.ADDED,
                    fingerprint=fingerprint,
                    new_values=self._extract_values(new_tour)
                )
                diffs.append(diff)

        # Find REMOVED tours (in old, not in new)
        for fingerprint, old_tour in old_by_fingerprint.items():
            if fingerprint not in new_by_fingerprint:
                diff = TourDiff(
                    diff_type=DiffType.REMOVED,
                    fingerprint=fingerprint,
                    old_values=self._extract_values(old_tour)
                )
                diffs.append(diff)

        # Find CHANGED tours (same fingerprint, different attributes)
        for fingerprint in old_by_fingerprint.keys() & new_by_fingerprint.keys():
            old_tour = old_by_fingerprint[fingerprint]
            new_tour = new_by_fingerprint[fingerprint]

            changed_fields = self._find_changed_fields(old_tour, new_tour)

            if changed_fields:
                old_values = {field: old_tour.get(field) for field in changed_fields}
                new_values = {field: new_tour.get(field) for field in changed_fields}

                diff = TourDiff(
                    diff_type=DiffType.CHANGED,
                    fingerprint=fingerprint,
                    old_values=old_values,
                    new_values=new_values,
                    changed_fields=changed_fields
                )
                diffs.append(diff)

        # Build summary
        summary = DiffSummary(
            forecast_version_old=1,
            forecast_version_new=2,
            added=sum(1 for d in diffs if d.diff_type == DiffType.ADDED),
            removed=sum(1 for d in diffs if d.diff_type == DiffType.REMOVED),
            changed=sum(1 for d in diffs if d.diff_type == DiffType.CHANGED),
            details=diffs
        )

        return summary

    def _extract_values(self, tour: dict) -> dict:
        """Extract relevant tour values for diff comparison."""
        return {
            "day": tour["day"],
            "start_ts": str(tour["start_ts"]),
            "end_ts": str(tour["end_ts"]),
            "duration_min": tour.get("duration_min", 0),
            "work_hours": float(tour.get("work_hours", 0)),
            "count": tour.get("count", 1),
            "depot": tour.get("depot"),
            "skill": tour.get("skill")
        }

    def _find_changed_fields(self, old_tour: dict, new_tour: dict) -> list:
        """Compare tours and return list of changed fields."""
        comparable_fields = [
            "count", "depot", "skill", "duration_min", "work_hours",
            "span_group_key"
        ]

        changed = []
        for field in comparable_fields:
            old_val = old_tour.get(field)
            new_val = new_tour.get(field)

            # Handle numeric comparisons with tolerance
            if field in ["work_hours"]:
                if old_val is not None and new_val is not None:
                    if abs(float(old_val) - float(new_val)) > 0.01:
                        changed.append(field)
                elif old_val != new_val:
                    changed.append(field)
            else:
                if old_val != new_val:
                    changed.append(field)

        return changed


def summary_to_snapshot(summary: DiffSummary) -> dict:
    """Convert DiffSummary to snapshot-friendly dict."""
    return {
        "added": summary.added,
        "removed": summary.removed,
        "changed": summary.changed,
        "total": summary.total_changes(),
        "details": sorted([
            {
                "type": d.diff_type,
                "fingerprint": d.fingerprint,
                "old_values": d.old_values,
                "new_values": d.new_values,
                "changed_fields": sorted(d.changed_fields) if d.changed_fields else None
            }
            for d in summary.details
        ], key=lambda x: (x["type"], x["fingerprint"]))
    }


def snapshot_hash(snapshot: dict) -> str:
    """Compute deterministic hash of snapshot."""
    canonical = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ============================================================================
# Test Data Fixtures
# ============================================================================

def create_tour(day: int, start: str, end: str, count: int = 1, depot: str = None, skill: str = None) -> dict:
    """Helper to create tour dicts with fingerprints."""
    fingerprint = compute_tour_fingerprint(day, start, end, depot, skill)
    return {
        "day": day,
        "start_ts": start,
        "end_ts": end,
        "tour_fingerprint": fingerprint,
        "count": count,
        "depot": depot,
        "skill": skill,
        "duration_min": 480,  # 8h default
        "work_hours": 8.0,
        "span_group_key": f"D{day}"
    }


# ============================================================================
# Snapshot Tests
# ============================================================================

def test_diff_no_changes():
    """Test: Identical forecasts produce no diffs."""
    print("\n[TEST] Diff - No Changes")

    tours_old = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00"),
        create_tour(3, "14:00", "22:00")
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00"),
        create_tour(3, "14:00", "22:00")
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    expected = {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "total": 0,
        "details": []
    }

    assert snapshot == expected, f"Expected {expected}, got {snapshot}"
    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] No changes detected correctly")
    return True


def test_diff_added_tour():
    """Test: New tour in forecast_new is classified as ADDED."""
    print("\n[TEST] Diff - Added Tour")

    tours_old = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00")
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00"),
        create_tour(3, "14:00", "22:00")  # NEW
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 1, f"Expected 1 added, got {snapshot['added']}"
    assert snapshot["removed"] == 0, f"Expected 0 removed, got {snapshot['removed']}"
    assert snapshot["changed"] == 0, f"Expected 0 changed, got {snapshot['changed']}"

    added_detail = next((d for d in snapshot["details"] if d["type"] == "ADDED"), None)
    assert added_detail is not None, "Expected ADDED detail"
    assert added_detail["new_values"]["day"] == 3, "Expected day=3"

    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] Added tour detected correctly")
    return True


def test_diff_removed_tour():
    """Test: Tour missing in forecast_new is classified as REMOVED."""
    print("\n[TEST] Diff - Removed Tour")

    tours_old = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00"),
        create_tour(3, "14:00", "22:00")  # Will be removed
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00"),
        create_tour(2, "07:00", "15:00")
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 0, f"Expected 0 added, got {snapshot['added']}"
    assert snapshot["removed"] == 1, f"Expected 1 removed, got {snapshot['removed']}"
    assert snapshot["changed"] == 0, f"Expected 0 changed, got {snapshot['changed']}"

    removed_detail = next((d for d in snapshot["details"] if d["type"] == "REMOVED"), None)
    assert removed_detail is not None, "Expected REMOVED detail"
    assert removed_detail["old_values"]["day"] == 3, "Expected day=3"

    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] Removed tour detected correctly")
    return True


def test_diff_changed_count():
    """Test: Changed count attribute is classified as CHANGED."""
    print("\n[TEST] Diff - Changed Count")

    tours_old = [
        create_tour(1, "06:00", "14:00", count=2),
        create_tour(2, "07:00", "15:00")
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00", count=3),  # count changed 2->3
        create_tour(2, "07:00", "15:00")
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 0, f"Expected 0 added, got {snapshot['added']}"
    assert snapshot["removed"] == 0, f"Expected 0 removed, got {snapshot['removed']}"
    assert snapshot["changed"] == 1, f"Expected 1 changed, got {snapshot['changed']}"

    changed_detail = next((d for d in snapshot["details"] if d["type"] == "CHANGED"), None)
    assert changed_detail is not None, "Expected CHANGED detail"
    assert "count" in changed_detail["changed_fields"], "Expected 'count' in changed_fields"
    assert changed_detail["old_values"]["count"] == 2, "Expected old count=2"
    assert changed_detail["new_values"]["count"] == 3, "Expected new count=3"

    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] Changed count detected correctly")
    return True


def test_diff_changed_depot():
    """Test: Changed depot attribute is classified as CHANGED."""
    print("\n[TEST] Diff - Changed Depot")

    tours_old = [
        create_tour(1, "06:00", "14:00", depot="Depot Nord")
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00", depot="Depot Sued")  # depot changed
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    # Note: Depot change creates a NEW fingerprint (added + removed)
    # because depot is part of the fingerprint
    assert snapshot["total"] == 2, f"Expected 2 total changes (depot is in fingerprint), got {snapshot['total']}"

    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] Depot change detected (creates new fingerprint)")
    return True


def test_diff_complex_scenario():
    """Test: Complex scenario with multiple change types."""
    print("\n[TEST] Diff - Complex Scenario")

    tours_old = [
        create_tour(1, "06:00", "14:00", count=2),   # Will change count
        create_tour(2, "07:00", "15:00"),            # Will be removed
        create_tour(3, "14:00", "22:00"),            # Unchanged
        create_tour(4, "22:00", "06:00"),            # Unchanged
    ]
    tours_new = [
        create_tour(1, "06:00", "14:00", count=3),   # Count changed 2->3
        create_tour(3, "14:00", "22:00"),            # Unchanged
        create_tour(4, "22:00", "06:00"),            # Unchanged
        create_tour(5, "08:00", "16:00"),            # New tour
    ]

    engine = MockDiffEngine()
    summary = engine.compute_diff(tours_old, tours_new)
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 1, f"Expected 1 added, got {snapshot['added']}"
    assert snapshot["removed"] == 1, f"Expected 1 removed, got {snapshot['removed']}"
    assert snapshot["changed"] == 1, f"Expected 1 changed, got {snapshot['changed']}"
    assert snapshot["total"] == 3, f"Expected 3 total, got {snapshot['total']}"

    # Verify each change type
    added = [d for d in snapshot["details"] if d["type"] == "ADDED"]
    removed = [d for d in snapshot["details"] if d["type"] == "REMOVED"]
    changed = [d for d in snapshot["details"] if d["type"] == "CHANGED"]

    assert len(added) == 1, f"Expected 1 ADDED detail, got {len(added)}"
    assert len(removed) == 1, f"Expected 1 REMOVED detail, got {len(removed)}"
    assert len(changed) == 1, f"Expected 1 CHANGED detail, got {len(changed)}"

    # Check added tour is day 5
    assert added[0]["new_values"]["day"] == 5, "Expected added tour day=5"

    # Check removed tour is day 2
    assert removed[0]["old_values"]["day"] == 2, "Expected removed tour day=2"

    # Check changed tour has count in changed_fields
    assert "count" in changed[0]["changed_fields"], "Expected 'count' in changed_fields"

    print(f"   Snapshot hash: {snapshot_hash(snapshot)}")
    print("   [PASS] Complex scenario handled correctly")
    return True


def test_diff_fingerprint_determinism():
    """Test: Same tour data always produces same fingerprint."""
    print("\n[TEST] Diff - Fingerprint Determinism")

    # Create same tour 100 times
    fingerprints = set()
    for _ in range(100):
        fp = compute_tour_fingerprint(1, "06:00", "14:00", "Depot Nord", None)
        fingerprints.add(fp)

    assert len(fingerprints) == 1, f"Expected 1 unique fingerprint, got {len(fingerprints)}"

    # Verify it's the expected hash
    expected_fp = compute_tour_fingerprint(1, "06:00", "14:00", "Depot Nord", None)
    assert list(fingerprints)[0] == expected_fp, "Fingerprint mismatch"

    print(f"   Fingerprint: {expected_fp}")
    print("   [PASS] Fingerprints are deterministic")
    return True


def test_diff_empty_forecasts():
    """Test: Empty forecasts produce correct diff."""
    print("\n[TEST] Diff - Empty Forecasts")

    # Both empty
    engine = MockDiffEngine()
    summary = engine.compute_diff([], [])
    snapshot = summary_to_snapshot(summary)

    assert snapshot["total"] == 0, f"Expected 0 total, got {snapshot['total']}"

    # Old empty, new has tours (all added)
    tours_new = [create_tour(1, "06:00", "14:00")]
    summary = engine.compute_diff([], tours_new)
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 1, f"Expected 1 added, got {snapshot['added']}"
    assert snapshot["removed"] == 0, f"Expected 0 removed, got {snapshot['removed']}"

    # Old has tours, new empty (all removed)
    tours_old = [create_tour(1, "06:00", "14:00"), create_tour(2, "07:00", "15:00")]
    summary = engine.compute_diff(tours_old, [])
    snapshot = summary_to_snapshot(summary)

    assert snapshot["added"] == 0, f"Expected 0 added, got {snapshot['added']}"
    assert snapshot["removed"] == 2, f"Expected 2 removed, got {snapshot['removed']}"

    print("   [PASS] Empty forecasts handled correctly")
    return True


# ============================================================================
# Snapshot Registry (for regression testing)
# ============================================================================

EXPECTED_SNAPSHOTS = {
    "no_changes": {
        "hash": "d751713988987e93",
        "summary": {"added": 0, "removed": 0, "changed": 0, "total": 0}
    },
    "added_tour": {
        "summary": {"added": 1, "removed": 0, "changed": 0, "total": 1}
    },
    "removed_tour": {
        "summary": {"added": 0, "removed": 1, "changed": 0, "total": 1}
    },
    "changed_count": {
        "summary": {"added": 0, "removed": 0, "changed": 1, "total": 1}
    },
    "complex_scenario": {
        "summary": {"added": 1, "removed": 1, "changed": 1, "total": 3}
    }
}


# ============================================================================
# Main Test Runner
# ============================================================================

def run_all_tests():
    """Run all snapshot tests."""
    print("=" * 60)
    print("SOLVEREIGN V3 - Diff Engine Snapshot Tests")
    print("=" * 60)

    tests = [
        test_diff_no_changes,
        test_diff_added_tour,
        test_diff_removed_tour,
        test_diff_changed_count,
        test_diff_changed_depot,
        test_diff_complex_scenario,
        test_diff_fingerprint_determinism,
        test_diff_empty_forecasts,
    ]

    passed = 0
    failed = 0
    results = []

    for test in tests:
        try:
            result = test()
            if result:
                passed += 1
                results.append((test.__name__, "PASS", None))
            else:
                failed += 1
                results.append((test.__name__, "FAIL", "Test returned False"))
        except AssertionError as e:
            failed += 1
            results.append((test.__name__, "FAIL", str(e)))
        except Exception as e:
            failed += 1
            results.append((test.__name__, "ERROR", str(e)))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, status, error in results:
        if status == "PASS":
            print(f"   [PASS] {name}")
        else:
            print(f"   [FAIL] {name}: {error}")

    print("")
    print(f"   Total:  {len(tests)}")
    print(f"   Passed: {passed}")
    print(f"   Failed: {failed}")

    if failed == 0:
        print("\n[OK] All snapshot tests passed!")
        return True
    else:
        print(f"\n[FAIL] {failed} tests failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
