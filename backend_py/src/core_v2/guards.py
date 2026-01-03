"""
Critical Guards - Hard Contracts for Solvereign
================================================
These are NON-NEGOTIABLE invariants that prevent infeasibility and drift.
ALL guards raise AssertionError on violation (HARD FAIL).

Guards:
1. AtomicCoverageGuard - Every tour has at least one covering column
2. RestTimeGuard - Rest between duties >= 11h (handles cross-midnight, Sunday→Monday)
3. GapDayGuard - Gap day (rest > 24h) requires full-day window in linker
4. OutputContractGuard - Output artifacts are complete and parseable
5. AtomicInvariantGuard - Atomics exist for every tour in pool (code invariant)
"""

from typing import Dict, Set, List, Tuple, Optional, Any, TYPE_CHECKING
from dataclasses import dataclass
import logging
import json

if TYPE_CHECKING:
    from .model.column import ColumnV2
    from .model.duty import DutyV2

logger = logging.getLogger("Guards")


# ============================================================================
# GUARD 1: Atomic Coverage (HARD FAIL)
# ============================================================================
class AtomicCoverageGuard:
    """
    INVARIANT: Every required tour MUST have at least one covering column.
    If this fails → MIP is INFEASIBLE.
    """
    
    @staticmethod
    def validate(
        pool: List[Any],
        required_tour_ids: Set[str],
        raise_on_fail: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        HARD ASSERTION: Every tour is covered.
        
        Raises:
            AssertionError with full diagnostic info if ANY tour is uncovered.
        """
        coverage: Dict[str, int] = {tid: 0 for tid in required_tour_ids}
        
        for col in pool:
            for tid in col.covered_tour_ids:
                if tid in coverage:
                    coverage[tid] += 1
        
        uncovered = [tid for tid, count in coverage.items() if count == 0]
        
        if uncovered:
            diagnostic = {
                "guard": "AtomicCoverageGuard",
                "violation": "ZERO_COVERAGE_TOURS",
                "uncovered_count": len(uncovered),
                "uncovered_sample": uncovered[:20],
                "pool_size": len(pool),
                "required_tours": len(required_tour_ids),
                "covered_tours": len(required_tour_ids) - len(uncovered),
            }
            
            error_msg = (
                f"\n{'='*60}\n"
                f"  GUARD FAILURE: AtomicCoverageGuard\n"
                f"{'='*60}\n"
                f"  {len(uncovered)} tours have ZERO covering columns.\n"
                f"  First 10: {uncovered[:10]}\n"
                f"  Pool Size: {len(pool)}\n"
                f"  Required Tours: {len(required_tour_ids)}\n"
                f"\n"
                f"  ROOT CAUSE: Subset selection removed all columns for these tours.\n"
                f"  FIX: Ensure atomics are UNPRUNABLE.\n"
                f"{'='*60}\n"
                f"DIAGNOSTIC: {json.dumps(diagnostic)}"
            )
            
            logger.error(error_msg)
            
            if raise_on_fail:
                raise AssertionError(error_msg)
            return False, uncovered
        
        min_coverage = min(coverage.values()) if coverage else 0
        logger.info(
            f"GUARD_PASS: AtomicCoverage OK - "
            f"{len(required_tour_ids)} tours, min_coverage={min_coverage}"
        )
        return True, []


# ============================================================================
# GUARD 2: Rest Time (HARD FAIL) - Handles Cross-Midnight & Sunday→Monday
# ============================================================================
class RestTimeGuard:
    """
    INVARIANT: Rest between duties >= 11 hours (660 minutes).
    
    CRITICAL EDGE CASES:
    - Cross-midnight duties (end_min > 1440)
    - Sunday (day=6) → Monday (day=0) wrap (if present)
    - Gap days (rest > 24h) are always OK
    """
    
    MIN_REST_MINUTES = 660  # 11 hours
    MINUTES_PER_DAY = 1440
    
    @staticmethod
    def calculate_rest(
        d1_day: int, d1_end_min: int,
        d2_day: int, d2_start_min: int
    ) -> int:
        """
        Calculate rest minutes between two duties.
        
        Handles:
        - Cross-midnight (d1_end_min > 1440 means duty spilled into next day)
        - Sunday→Monday wrap (if d1_day=6 and d2_day=0, treat as next week)
        
        Returns:
            Rest in minutes (can be negative if overlap)
        """
        # Absolute times from week start (Monday = day 0)
        abs_end_1 = d1_day * RestTimeGuard.MINUTES_PER_DAY + d1_end_min
        abs_start_2 = d2_day * RestTimeGuard.MINUTES_PER_DAY + d2_start_min
        
        # Handle Sunday→Monday wrap (d2 is in next week)
        if d2_day < d1_day:
            # d2 is in next week (e.g., Sunday duty → Monday duty)
            abs_start_2 += 7 * RestTimeGuard.MINUTES_PER_DAY
        
        return abs_start_2 - abs_end_1
    
    @staticmethod
    def validate_column_duties(duties: List[Any]) -> None:
        """
        HARD ASSERTION: All rest periods in a column are legal.
        
        Args:
            duties: List of duty objects with .day, .start_min, .end_min
            
        Raises:
            AssertionError with diagnostic info if rest < 11h
        """
        if len(duties) < 2:
            return  # Single duty, no rest needed
        
        sorted_duties = sorted(duties, key=lambda d: (d.day, d.start_min))
        violations = []
        
        for i in range(len(sorted_duties) - 1):
            d1 = sorted_duties[i]
            d2 = sorted_duties[i + 1]
            
            rest = RestTimeGuard.calculate_rest(
                d1.day, d1.end_min,
                d2.day, d2.start_min
            )
            
            if rest < RestTimeGuard.MIN_REST_MINUTES:
                violations.append({
                    "from_duty": getattr(d1, 'duty_id', f'day{d1.day}'),
                    "to_duty": getattr(d2, 'duty_id', f'day{d2.day}'),
                    "from_day": d1.day,
                    "from_end": d1.end_min,
                    "to_day": d2.day,
                    "to_start": d2.start_min,
                    "rest_min": rest,
                    "required_min": RestTimeGuard.MIN_REST_MINUTES,
                    "shortfall_min": RestTimeGuard.MIN_REST_MINUTES - rest,
                    "is_cross_midnight": d1.end_min > RestTimeGuard.MINUTES_PER_DAY,
                    "is_sunday_monday": d1.day == 6 and d2.day == 0,
                })
        
        if violations:
            error_msg = (
                f"\n{'='*60}\n"
                f"  GUARD FAILURE: RestTimeGuard\n"
                f"{'='*60}\n"
                f"  {len(violations)} rest period violations found.\n"
            )
            for v in violations[:5]:
                cross_mid_note = " [CROSS-MIDNIGHT]" if v['is_cross_midnight'] else ""
                sun_mon_note = " [SUNDAY→MONDAY]" if v['is_sunday_monday'] else ""
                error_msg += (
                    f"  - Day {v['from_day']} ({v['from_end']}min) → "
                    f"Day {v['to_day']} ({v['to_start']}min): "
                    f"rest={v['rest_min']}min < {v['required_min']}min "
                    f"(short by {v['shortfall_min']}min){cross_mid_note}{sun_mon_note}\n"
                )
            error_msg += f"{'='*60}\n"
            error_msg += f"DIAGNOSTIC: {json.dumps(violations[:5])}\n"
            
            logger.error(error_msg)
            raise AssertionError(error_msg)


# ============================================================================
# GUARD 3: Gap-Day Window (HARD FAIL in Linker)
# ============================================================================
class GapDayGuard:
    """
    INVARIANT: If rest > 24h (gap day), linker MUST use full-day window (0-24h).
    
    This guard validates that the linker is using the correct window.
    If gap day is detected but window is restricted, it's a BUG.
    """
    
    GAP_DAY_THRESHOLD_MINUTES = 24 * 60  # 1440 min
    MIN_REST_MINUTES = 11 * 60  # 660 min
    
    @staticmethod
    def is_gap_day(rest_minutes: int) -> bool:
        """Check if rest qualifies as a gap day."""
        return rest_minutes > GapDayGuard.GAP_DAY_THRESHOLD_MINUTES
    
    @staticmethod
    def validate_linker_window(
        rest_minutes: int,
        actual_window_start: int,
        actual_window_end: int
    ) -> None:
        """
        HARD ASSERTION: If gap day, window MUST be (0, 24).
        
        Call this in the SPPRC linker BEFORE filtering candidates.
        
        Raises:
            AssertionError if gap day with restricted window
        """
        if rest_minutes > GapDayGuard.GAP_DAY_THRESHOLD_MINUTES:
            # This is a gap day - window MUST be full day
            if actual_window_start != 0 or actual_window_end != 24:
                error_msg = (
                    f"\n{'='*60}\n"
                    f"  GUARD FAILURE: GapDayGuard\n"
                    f"{'='*60}\n"
                    f"  Gap day detected (rest={rest_minutes}min > 24h)\n"
                    f"  BUT linker window is ({actual_window_start}, {actual_window_end})\n"
                    f"  EXPECTED: (0, 24) - FULL DAY\n"
                    f"\n"
                    f"  ROOT CAUSE: Linker bug - gap day logic not applied.\n"
                    f"  FIX: When rest > 24h, use connector_window = (0, 1440).\n"
                    f"{'='*60}\n"
                )
                logger.error(error_msg)
                raise AssertionError(error_msg)
    
    @staticmethod
    def get_window_for_rest(rest_minutes: int) -> Tuple[int, int]:
        """
        Get the correct search window for given rest time.
        
        Returns:
            (window_start_hour, window_end_hour)
        """
        if rest_minutes > GapDayGuard.GAP_DAY_THRESHOLD_MINUTES:
            return (0, 24)  # Full day
        else:
            return (0, 24)  # Also full day for safety (can be tuned later)
    
    @staticmethod
    def log_gap_day_stats(columns: List[Any]) -> Dict[str, Any]:
        """Log gap-day statistics (diagnostic, not a failure guard)."""
        gap_day_count = 0
        total_transitions = 0
        
        for col in columns:
            if len(col.duties) < 2:
                continue
            sorted_duties = sorted(col.duties, key=lambda d: d.day)
            for i in range(len(sorted_duties) - 1):
                total_transitions += 1
                rest = RestTimeGuard.calculate_rest(
                    sorted_duties[i].day, sorted_duties[i].end_min,
                    sorted_duties[i+1].day, sorted_duties[i+1].start_min
                )
                if GapDayGuard.is_gap_day(rest):
                    gap_day_count += 1
        
        stats = {
            "total_transitions": total_transitions,
            "gap_day_transitions": gap_day_count,
            "gap_day_pct": (gap_day_count / max(1, total_transitions)) * 100,
        }
        logger.info(f"GAP_DAY_STATS: {stats}")
        return stats


# ============================================================================
# GUARD 4: Output Contract (HARD FAIL) - Enhanced
# ============================================================================
class OutputContractGuard:
    """
    INVARIANT: Output artifacts must be complete, valid, and parseable.
    
    Validates:
    - Manifest: run_id, git_sha, seed, config_snapshot, kpis, stop_reason, etc.
    - Roster: columns exist, no nulls, each tour exactly once
    - Coverage: must be 100%
    """
    
    # Manifest Pflichtfelder
    REQUIRED_MANIFEST_KEYS = [
        "run_id", "status", "kpis", "stop_reason", "wall_time_sec", "iterations_done"
    ]
    
    # KPI Pflichtfelder
    REQUIRED_KPI_KEYS = [
        "coverage_pct", "drivers_total", "avg_days_per_driver", "fleet_peak"
    ]
    
    # Roster Pflichtspalten
    REQUIRED_ROSTER_COLUMNS = [
        "driver_id", "day", "duty_start", "duty_end", "tour_ids"
    ]
    
    @staticmethod
    def validate(
        manifest_path: str, 
        roster_path: str = None,
        expected_tour_ids: set = None,
        strict: bool = True
    ) -> None:
        """
        Validate output artifacts with comprehensive checks.
        
        Args:
            manifest_path: Path to run_manifest.json
            roster_path: Path to roster.csv (optional)
            expected_tour_ids: Set of all tour IDs that should be covered
            strict: If True, raises on any issue
            
        Raises:
            AssertionError if validation fails
        """
        from pathlib import Path
        import csv
        
        issues = []
        warnings = []
        
        # ===== MANIFEST VALIDATION =====
        manifest_file = Path(manifest_path)
        manifest = None
        
        if not manifest_file.exists():
            issues.append(f"MISSING manifest: {manifest_path}")
        else:
            try:
                with open(manifest_file) as f:
                    manifest = json.load(f)
                
                # Check required keys
                missing_keys = [k for k in OutputContractGuard.REQUIRED_MANIFEST_KEYS if k not in manifest]
                if missing_keys:
                    issues.append(f"Manifest missing keys: {missing_keys}")
                
                # Check KPIs
                if "kpis" in manifest:
                    kpis = manifest["kpis"]
                    missing_kpis = [k for k in OutputContractGuard.REQUIRED_KPI_KEYS if k not in kpis]
                    if missing_kpis:
                        issues.append(f"Missing KPIs: {missing_kpis}")
                    
                    # Coverage MUST be 100%
                    coverage = kpis.get("coverage_pct", 0)
                    if coverage < 100.0:
                        issues.append(f"COVERAGE NOT 100%: {coverage}% (HARD FAIL)")
                else:
                    issues.append("Manifest missing 'kpis' section")
                
                # Check status
                status = manifest.get("status", "")
                if status != "SUCCESS":
                    issues.append(f"Run status is '{status}', not 'SUCCESS'")
                    
            except json.JSONDecodeError as e:
                issues.append(f"Manifest parse error: {e}")
        
        # ===== ROSTER VALIDATION =====
        if roster_path:
            roster_file = Path(roster_path)
            if not roster_file.exists():
                issues.append(f"MISSING roster: {roster_path}")
            else:
                try:
                    with open(roster_file, encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                    
                    if len(rows) == 0:
                        issues.append("roster.csv is empty")
                    else:
                        # Check required columns exist
                        header = rows[0].keys()
                        missing_cols = [c for c in OutputContractGuard.REQUIRED_ROSTER_COLUMNS if c not in header]
                        if missing_cols:
                            issues.append(f"Roster missing columns: {missing_cols}")
                        
                        # Check for nulls in critical columns
                        null_checks = ["driver_id", "day", "duty_start", "duty_end"]
                        for i, row in enumerate(rows):
                            for col in null_checks:
                                if col in row and (row[col] is None or row[col] == ""):
                                    issues.append(f"Row {i}: NULL in {col}")
                                    break  # One per row max
                        
                        # Tour coverage check (each tour exactly once)
                        if expected_tour_ids:
                            covered_tours = {}
                            for row in rows:
                                tour_str = row.get("tour_ids", "")
                                if tour_str:
                                    for tid in tour_str.split("|"):
                                        tid = tid.strip()
                                        if tid:
                                            covered_tours[tid] = covered_tours.get(tid, 0) + 1
                            
                            # Check for missing tours
                            missing_tours = expected_tour_ids - set(covered_tours.keys())
                            if missing_tours:
                                issues.append(f"Tours NOT covered (0×): {len(missing_tours)} - first 5: {list(missing_tours)[:5]}")
                            
                            # Check for duplicate tours
                            dupe_tours = [t for t, count in covered_tours.items() if count > 1]
                            if dupe_tours:
                                issues.append(f"Tours covered >1×: {len(dupe_tours)} - first 5: {dupe_tours[:5]}")
                                
                except Exception as e:
                    issues.append(f"Roster parse error: {e}")
        
        # ===== RESULT =====
        if issues:
            error_msg = (
                f"\n{'='*60}\n"
                f"  GUARD FAILURE: OutputContractGuard\n"
                f"{'='*60}\n"
                f"  {len(issues)} issues found:\n"
            )
            for issue in issues:
                error_msg += f"  - {issue}\n"
            error_msg += f"{'='*60}\n"
            
            logger.error(error_msg)
            
            if strict:
                raise AssertionError(error_msg)
        else:
            logger.info("GUARD_PASS: OutputContract OK (manifest + roster valid)")
    
    @staticmethod
    def validate_manifest_only(manifest_path: str) -> None:
        """Quick validation of manifest only."""
        OutputContractGuard.validate(manifest_path, roster_path=None, strict=True)


# ============================================================================
# GUARD 5: Atomic Invariant (CODE INVARIANT - Pool Creation)
# ============================================================================
class AtomicInvariantGuard:
    """
    INVARIANT: After pool creation (seeding), every tour MUST have at least
    one atomic column (singleton).
    
    This is enforced at pool creation, not just before MIP.
    """
    
    @staticmethod
    def validate_seed_pool(
        pool: List[Any],
        all_tour_ids: Set[str]
    ) -> None:
        """
        HARD ASSERTION: After seeding, every tour has an atomic.
        
        Call this IMMEDIATELY after seeder.generate_seeds().
        
        Raises:
            AssertionError if any tour lacks an atomic
        """
        atomic_tours: Set[str] = set()
        
        for col in pool:
            # Atomic = singleton column covering exactly 1 tour
            if col.is_singleton and len(col.covered_tour_ids) == 1:
                atomic_tours.update(col.covered_tour_ids)
        
        missing_atomics = all_tour_ids - atomic_tours
        
        if missing_atomics:
            error_msg = (
                f"\n{'='*60}\n"
                f"  GUARD FAILURE: AtomicInvariantGuard\n"
                f"{'='*60}\n"
                f"  {len(missing_atomics)} tours have NO atomic column after seeding.\n"
                f"  First 10: {list(missing_atomics)[:10]}\n"
                f"  Total Tours: {len(all_tour_ids)}\n"
                f"  Tours with Atomics: {len(atomic_tours)}\n"
                f"\n"
                f"  ROOT CAUSE: Seeder did not create singletons for all tours.\n"
                f"  FIX: GreedySeeder._generate_singletons must cover ALL tours.\n"
                f"{'='*60}\n"
            )
            logger.error(error_msg)
            raise AssertionError(error_msg)
        
        logger.info(f"GUARD_PASS: AtomicInvariant OK - {len(all_tour_ids)} tours have atomics")


# ============================================================================
# MASTER GUARDS: Run All
# ============================================================================
def run_pre_mip_guards(
    pool: List[Any],
    required_tour_ids: Set[str]
) -> None:
    """
    Run all pre-MIP guards. Any failure raises AssertionError.
    Call this BEFORE MasterMIP.solve().
    """
    logger.info("Running PRE-MIP guards...")
    AtomicCoverageGuard.validate(pool, required_tour_ids)
    logger.info("All PRE-MIP guards PASSED.")


def run_post_seed_guards(
    pool: List[Any],
    all_tour_ids: Set[str]
) -> None:
    """
    Run guards after seeding. Ensures atomics exist.
    Call this AFTER seeder.generate_seeds().
    """
    logger.info("Running POST-SEED guards...")
    AtomicInvariantGuard.validate_seed_pool(pool, all_tour_ids)
    logger.info("All POST-SEED guards PASSED.")


def run_post_solve_guards(
    columns: List[Any],
    manifest_path: str = None,
    roster_path: str = None
) -> None:
    """
    Run all post-solve guards.
    Call this AFTER MIP success.
    """
    logger.info("Running POST-SOLVE guards...")
    
    # Validate rest times in all columns
    for col in columns:
        RestTimeGuard.validate_column_duties(list(col.duties))
    
    # Gap day stats (diagnostic)
    GapDayGuard.log_gap_day_stats(columns)
    
    # Output contract
    if manifest_path:
        OutputContractGuard.validate(manifest_path, roster_path)
    
    logger.info("All POST-SOLVE guards PASSED.")
