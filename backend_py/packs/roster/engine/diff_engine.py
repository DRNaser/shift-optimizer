"""
SOLVEREIGN V3 Diff Engine
==========================

Compute deterministic diffs between forecast versions.
Milestone 3 (M3) implementation.
"""

from .db import (
    get_tours_normalized,
    create_diff_result,
    get_diff_results,
)
from .models import DiffType, DiffSummary, TourDiff


class DiffEngine:
    """
    Compute and cache differences between forecast versions.

    Changes are classified as:
    - ADDED: New tour in forecast_version_new
    - REMOVED: Tour in forecast_version_old but not in new
    - CHANGED: Same fingerprint, different attributes
    """

    def compute_diff(
        self,
        forecast_version_old: int,
        forecast_version_new: int,
        use_cache: bool = True
    ) -> DiffSummary:
        """
        Compute diff between two forecast versions.

        Args:
            forecast_version_old: Previous forecast version ID
            forecast_version_new: New forecast version ID
            use_cache: If True, use cached diff_results if available

        Returns:
            DiffSummary with classified changes
        """
        # Check cache first
        if use_cache:
            cached = get_diff_results(forecast_version_old, forecast_version_new)
            if cached:
                return self._build_summary_from_cache(
                    forecast_version_old,
                    forecast_version_new,
                    cached
                )

        # Load tours for both versions
        old_tours = get_tours_normalized(forecast_version_old)
        new_tours = get_tours_normalized(forecast_version_new)

        # Index by fingerprint for fast lookup
        old_by_fingerprint = {t["tour_fingerprint"]: t for t in old_tours}
        new_by_fingerprint = {t["tour_fingerprint"]: t for t in new_tours}

        # Classify changes
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

                # Store in cache
                create_diff_result(
                    forecast_version_old,
                    forecast_version_new,
                    DiffType.ADDED.value,
                    fingerprint,
                    new_values=diff.new_values
                )

        # Find REMOVED tours (in old, not in new)
        for fingerprint, old_tour in old_by_fingerprint.items():
            if fingerprint not in new_by_fingerprint:
                diff = TourDiff(
                    diff_type=DiffType.REMOVED,
                    fingerprint=fingerprint,
                    old_values=self._extract_values(old_tour)
                )
                diffs.append(diff)

                # Store in cache
                create_diff_result(
                    forecast_version_old,
                    forecast_version_new,
                    DiffType.REMOVED.value,
                    fingerprint,
                    old_values=diff.old_values
                )

        # Find CHANGED tours (same fingerprint, different attributes)
        for fingerprint in old_by_fingerprint.keys() & new_by_fingerprint.keys():
            old_tour = old_by_fingerprint[fingerprint]
            new_tour = new_by_fingerprint[fingerprint]

            changed_fields = self._find_changed_fields(old_tour, new_tour)

            if changed_fields:
                old_values = {field: old_tour[field] for field in changed_fields}
                new_values = {field: new_tour[field] for field in changed_fields}

                diff = TourDiff(
                    diff_type=DiffType.CHANGED,
                    fingerprint=fingerprint,
                    old_values=old_values,
                    new_values=new_values,
                    changed_fields=changed_fields
                )
                diffs.append(diff)

                # Store in cache
                create_diff_result(
                    forecast_version_old,
                    forecast_version_new,
                    DiffType.CHANGED.value,
                    fingerprint,
                    old_values=old_values,
                    new_values=new_values,
                    changed_fields=changed_fields
                )

        # Build summary
        summary = DiffSummary(
            forecast_version_old=forecast_version_old,
            forecast_version_new=forecast_version_new,
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
            "duration_min": tour["duration_min"],
            "work_hours": float(tour["work_hours"]),
            "count": tour["count"],
            "depot": tour.get("depot"),
            "skill": tour.get("skill")
        }

    def _find_changed_fields(self, old_tour: dict, new_tour: dict) -> list[str]:
        """
        Compare tours and return list of changed fields.

        Only compares mutable fields (not ID, forecast_version_id, or fingerprint).
        """
        comparable_fields = [
            "count", "depot", "skill", "duration_min", "work_hours",
            "span_group_key", "metadata"
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

    def _build_summary_from_cache(
        self,
        forecast_version_old: int,
        forecast_version_new: int,
        cached_diffs: list[dict]
    ) -> DiffSummary:
        """Build DiffSummary from cached diff_results."""
        diffs = []

        for cached in cached_diffs:
            diff = TourDiff(
                diff_type=DiffType(cached["diff_type"]),
                fingerprint=cached["tour_fingerprint"],
                old_values=cached.get("old_values"),
                new_values=cached.get("new_values"),
                changed_fields=cached.get("changed_fields", [])
            )
            diffs.append(diff)

        summary = DiffSummary(
            forecast_version_old=forecast_version_old,
            forecast_version_new=forecast_version_new,
            added=sum(1 for d in diffs if d.diff_type == DiffType.ADDED),
            removed=sum(1 for d in diffs if d.diff_type == DiffType.REMOVED),
            changed=sum(1 for d in diffs if d.diff_type == DiffType.CHANGED),
            details=diffs
        )

        return summary

    def get_diff_summary_json(self, summary: DiffSummary) -> dict:
        """Convert DiffSummary to JSON-serializable dict."""
        return {
            "forecast_version_old": summary.forecast_version_old,
            "forecast_version_new": summary.forecast_version_new,
            "summary": {
                "added": summary.added,
                "removed": summary.removed,
                "changed": summary.changed,
                "total_changes": summary.total_changes()
            },
            "details": [
                {
                    "diff_type": d.diff_type.value,
                    "fingerprint": d.fingerprint,
                    "old_values": d.old_values,
                    "new_values": d.new_values,
                    "changed_fields": d.changed_fields
                }
                for d in summary.details
            ]
        }


# ============================================================================
# Convenience Functions
# ============================================================================

def compute_diff(
    forecast_version_old: int,
    forecast_version_new: int,
    use_cache: bool = True
) -> DiffSummary:
    """
    Convenience function to compute diff between forecast versions.

    Usage:
        from packs.roster.engine.diff_engine import compute_diff

        diff = compute_diff(forecast_old=47, forecast_new=48)
        print(f"Added: {diff.added}, Removed: {diff.removed}, Changed: {diff.changed}")
    """
    engine = DiffEngine()
    return engine.compute_diff(forecast_version_old, forecast_version_new, use_cache)


def get_diff_json(
    forecast_version_old: int,
    forecast_version_new: int,
    use_cache: bool = True
) -> dict:
    """
    Get diff as JSON-serializable dict.

    Usage:
        from packs.roster.engine.diff_engine import get_diff_json
        import json

        diff_json = get_diff_json(47, 48)
        print(json.dumps(diff_json, indent=2))
    """
    engine = DiffEngine()
    summary = engine.compute_diff(forecast_version_old, forecast_version_new, use_cache)
    return engine.get_diff_summary_json(summary)
