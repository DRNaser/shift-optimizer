"""
Core v2 - Guard Cascade

Hard-stop validation for invariants, coverage, and output contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
import os
from typing import Iterable, Optional

from .validator.rules import ValidatorV2, RULES


def _format_sample(items: Iterable[str], limit: int = 10) -> str:
    sample = list(items)[:limit]
    return ", ".join(sample) + ("..." if len(sample) >= limit else "")


@dataclass
class AtomicInvariantGuard:
    """Ensure every tour has at least one atomic (singleton) column."""

    @staticmethod
    def validate(pool_columns: list, all_tour_ids: set[str]) -> None:
        atomic_tours = set()
        for col in pool_columns:
            if getattr(col, "is_singleton", False) and len(col.covered_tour_ids) == 1:
                atomic_tours.update(col.covered_tour_ids)

        missing = set(all_tour_ids) - atomic_tours
        if missing:
            raise AssertionError(
                "AtomicInvariantGuard failed: "
                f"missing {len(missing)} tours: {_format_sample(sorted(missing))}"
            )


@dataclass
class AtomicCoverageGuard:
    """Ensure every tour has at least one covering column in the pool."""

    @staticmethod
    def validate(pool_columns: list, all_tour_ids: set[str]) -> None:
        support = {tid: 0 for tid in all_tour_ids}
        for col in pool_columns:
            for tid in col.covered_tour_ids:
                if tid in support:
                    support[tid] += 1

        missing = [tid for tid, count in support.items() if count == 0]
        if missing:
            counts = sorted(support.values())
            min_support = counts[0] if counts else 0
            median_support = counts[len(counts) // 2] if counts else 0
            p10_support = counts[max(0, int(len(counts) * 0.1))] if counts else 0
            raise AssertionError(
                "AtomicCoverageGuard failed: "
                f"missing {len(missing)} tours: {_format_sample(sorted(missing))}; "
                f"support_hist(min/median/p10)={min_support}/{median_support}/{p10_support}; "
                f"pool_size={len(pool_columns)}"
            )


@dataclass
class GapDayGuard:
    """Ensure no roster exceeds weekly duty count limit."""

    @staticmethod
    def validate(columns: list) -> None:
        for col in columns:
            if len(col.duties) > RULES.MAX_DUTIES_PER_WEEK:
                raise AssertionError(
                    f"GapDayGuard failed: column {col.col_id} has "
                    f"{len(col.duties)} duties > {RULES.MAX_DUTIES_PER_WEEK}"
                )


@dataclass
class RestTimeGuard:
    """Ensure 11h rest between consecutive duties, including week wrap."""

    @staticmethod
    def _rest_minutes(duty_a, duty_b, day_offset: int = 0) -> int:
        abs_end = duty_a.day * 1440 + duty_a.end_min
        abs_start = (duty_b.day + day_offset) * 1440 + duty_b.start_min
        return abs_start - abs_end

    @staticmethod
    def validate(columns: list) -> None:
        for col in columns:
            duties = list(col.duties)
            if len(duties) < 2:
                continue

            duties_sorted = sorted(duties, key=lambda d: d.day)
            for i in range(len(duties_sorted) - 1):
                d1 = duties_sorted[i]
                d2 = duties_sorted[i + 1]
                if not ValidatorV2.can_chain_days(d1, d2):
                    rest_min = RestTimeGuard._rest_minutes(d1, d2)
                    raise AssertionError(
                        "RestTimeGuard failed: "
                        f"{d1.day}->{d2.day} rest {rest_min} min < {RULES.MIN_REST_MINUTES}"
                    )

            # Week wrap: Sunday -> Monday (day 6 -> day 0)
            first = duties_sorted[0]
            last = duties_sorted[-1]
            if last.day == 6 and first.day == 0:
                rest_min = RestTimeGuard._rest_minutes(last, first, day_offset=7)
                if rest_min < RULES.MIN_REST_MINUTES:
                    raise AssertionError(
                        "RestTimeGuard failed: "
                        f"Sunday->Monday rest {rest_min} min < {RULES.MIN_REST_MINUTES}"
                    )


@dataclass
class OutputContractGuard:
    """Validate output artifacts and exact-once coverage."""

    REQUIRED_RUN_FIELDS = {
        "run_id",
        "git_sha",
        "seed",
        "profile",
        "config_snapshot",
        "kpis",
        "timing",
        "cg",
        "pricing",
    }
    REQUIRED_KPI_FIELDS = {
        "coverage_exact_once",
        "drivers_total",
        "avg_days_per_driver",
        "tours_per_driver",
        "fleet_peak",
    }

    @staticmethod
    def _read_csv_rows(roster_path: str) -> list[dict]:
        with open(roster_path, "r", encoding="utf-8") as handle:
            sample = handle.read(1024)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","
            reader = csv.DictReader(handle, delimiter=delimiter)
            return list(reader)

    @staticmethod
    def validate(
        manifest_path: str,
        roster_path: Optional[str],
        expected_tour_ids: Optional[set[str]] = None,
        strict: bool = True,
    ) -> None:
        if not os.path.exists(manifest_path):
            raise AssertionError(f"OutputContractGuard failed: missing manifest {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        run_id = manifest.get("run_id")
        if not run_id:
            raise AssertionError("OutputContractGuard failed: run_id missing in manifest")

        if strict and ("config_snapshot" in manifest or "cg" in manifest):
            missing_fields = OutputContractGuard.REQUIRED_RUN_FIELDS - set(manifest.keys())
            if missing_fields:
                raise AssertionError(
                    "OutputContractGuard failed: missing manifest fields: "
                    f"{sorted(missing_fields)}"
                )

            kpis = manifest.get("kpis", {})
            missing_kpis = OutputContractGuard.REQUIRED_KPI_FIELDS - set(kpis.keys())
            if missing_kpis:
                raise AssertionError(
                    "OutputContractGuard failed: missing KPI fields: "
                    f"{sorted(missing_kpis)}"
                )

        if roster_path:
            if not os.path.exists(roster_path):
                raise AssertionError(f"OutputContractGuard failed: missing roster {roster_path}")

            if expected_tour_ids:
                rows = OutputContractGuard._read_csv_rows(roster_path)
                if not rows or "tour_ids" not in rows[0]:
                    raise AssertionError(
                        "OutputContractGuard failed: roster missing tour_ids column"
                    )

                counts = {tid: 0 for tid in expected_tour_ids}
                for row in rows:
                    for tid in row.get("tour_ids", "").split("|"):
                        tid = tid.strip()
                        if tid in counts:
                            counts[tid] += 1

                missing = [tid for tid, count in counts.items() if count == 0]
                dupes = [tid for tid, count in counts.items() if count > 1]
                if missing or dupes:
                    raise AssertionError(
                        "OutputContractGuard failed: coverage exact-once violated. "
                        f"missing={len(missing)} dupes={len(dupes)}"
                    )
                if strict and manifest.get("kpis", {}).get("coverage_exact_once") is False:
                    raise AssertionError(
                        "OutputContractGuard failed: manifest coverage_exact_once is false"
                    )


def run_post_seed_guards(pool_columns: list, all_tour_ids: set[str]) -> None:
    AtomicInvariantGuard.validate(pool_columns, all_tour_ids)


def run_pre_mip_guards(pool_columns: list, all_tour_ids: set[str]) -> None:
    AtomicCoverageGuard.validate(pool_columns, all_tour_ids)


def run_post_solve_guards(selected_columns: list) -> None:
    GapDayGuard.validate(selected_columns)
    RestTimeGuard.validate(selected_columns)
