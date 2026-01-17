"""
SOLVEREIGN V3 Data Models
==========================

Dataclasses for V3 architecture components.
Maps to Postgres schema in db/init.sql.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Literal, Optional


# ============================================================================
# Enums
# ============================================================================

class ForecastStatus(str, Enum):
    """Forecast validation status."""
    PASS = "PASS"  # All lines parsed successfully
    WARN = "WARN"  # Warnings present but no failures
    FAIL = "FAIL"  # One or more lines failed parsing


class ParseStatus(str, Enum):
    """Individual line parse status."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class PlanStatus(str, Enum):
    """Plan version lifecycle status."""
    SOLVING = "SOLVING"      # Solver in progress (crash recovery marker)
    SOLVED = "SOLVED"        # Solver completed, awaiting audit
    AUDITED = "AUDITED"      # Audit completed, ready for review
    DRAFT = "DRAFT"          # Completed, under review
    LOCKED = "LOCKED"        # Released to operations
    SUPERSEDED = "SUPERSEDED"  # Replaced by newer plan
    FAILED = "FAILED"        # Solver crashed or timed out


class DiffType(str, Enum):
    """Tour change classification."""
    ADDED = "ADDED"      # New tour in forecast_version N
    REMOVED = "REMOVED"  # Tour present in N-1, absent in N
    CHANGED = "CHANGED"  # Same fingerprint, different attributes


class AuditCheckName(str, Enum):
    """Standardized audit check identifiers."""
    COVERAGE = "COVERAGE"              # Every tour assigned exactly once
    OVERLAP = "OVERLAP"                # No driver works overlapping tours
    REST = "REST"                      # ≥11h rest between blocks
    SPAN_REGULAR = "SPAN_REGULAR"      # ≤14h span for regular blocks
    SPAN_SPLIT = "SPAN_SPLIT"          # ≤16h span + 360min break for splits
    REPRODUCIBILITY = "REPRODUCIBILITY"  # Same inputs → same outputs
    FATIGUE = "FATIGUE"                # No consecutive triple shifts
    SENSITIVITY = "SENSITIVITY"        # Plan stability against config changes


class AuditStatus(str, Enum):
    """Audit check result."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # Not applicable (e.g., partial forecast)


class ForecastSource(str, Enum):
    """Forecast input source type."""
    SLACK = "slack"
    CSV = "csv"
    MANUAL = "manual"
    PATCH = "patch"       # Partial update for a week
    COMPOSED = "composed"  # LWW merge of multiple patches


class CompletenessStatus(str, Enum):
    """Forecast completeness for release gating."""
    UNKNOWN = "UNKNOWN"    # Not yet evaluated
    PARTIAL = "PARTIAL"    # Missing expected days
    COMPLETE = "COMPLETE"  # All expected days present


# ============================================================================
# Parser Models
# ============================================================================

@dataclass
class Issue:
    """Parser issue (error or warning)."""
    code: str           # e.g., "INVALID_TIME_FORMAT", "MISSING_DAY"
    message: str        # Human-readable description
    severity: Literal["ERROR", "WARNING"]


@dataclass
class ParseResult:
    """Result of parsing a single tour line."""
    parse_status: ParseStatus
    normalized_fields: dict  # {day, start, end, count, depot?, zone?}
    canonical_text: str      # Standardized format for hashing
    issues: list[Issue] = field(default_factory=list)

    def has_errors(self) -> bool:
        """Check if any ERROR severity issues exist."""
        return any(issue.severity == "ERROR" for issue in self.issues)

    def has_warnings(self) -> bool:
        """Check if any WARNING severity issues exist."""
        return any(issue.severity == "WARNING" for issue in self.issues)


@dataclass
class ForecastValidation:
    """Aggregated validation result for entire forecast."""
    status: ForecastStatus
    line_results: list[ParseResult]
    input_hash: str
    parser_config_hash: str

    def total_lines(self) -> int:
        return len(self.line_results)

    def passed_lines(self) -> int:
        return sum(1 for r in self.line_results if r.parse_status == ParseStatus.PASS)

    def failed_lines(self) -> int:
        return sum(1 for r in self.line_results if r.parse_status == ParseStatus.FAIL)

    def warned_lines(self) -> int:
        return sum(1 for r in self.line_results if r.parse_status == ParseStatus.WARN)


# ============================================================================
# Database Models (matching schema)
# ============================================================================

@dataclass
class ForecastVersion:
    """Forecast version (from forecast_versions table)."""
    id: int
    created_at: datetime
    source: Literal["slack", "csv", "manual"]
    input_hash: str
    parser_config_hash: str
    status: ForecastStatus
    notes: Optional[str] = None


@dataclass
class TourRaw:
    """Raw tour line (from tours_raw table)."""
    id: int
    forecast_version_id: int
    line_no: int
    raw_text: str
    parse_status: ParseStatus
    parse_errors: Optional[list[dict]] = None
    parse_warnings: Optional[list[dict]] = None
    canonical_text: Optional[str] = None


@dataclass
class TourNormalized:
    """Normalized tour (from tours_normalized table)."""
    id: int
    forecast_version_id: int
    day: int  # 1-7 (Mo-So)
    start_ts: time
    end_ts: time
    duration_min: int
    work_hours: float
    span_group_key: Optional[str]
    tour_fingerprint: str
    count: int = 1
    depot: Optional[str] = None
    skill: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class PlanVersion:
    """Plan version (from plan_versions table)."""
    id: int
    forecast_version_id: int
    created_at: datetime
    seed: int
    solver_config_hash: str
    output_hash: str
    status: PlanStatus
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Assignment:
    """Driver-to-tour assignment (from assignments table)."""
    id: int
    plan_version_id: int
    driver_id: str
    tour_id: int
    day: int
    block_id: str
    role: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class AuditLog:
    """Audit check result (from audit_log table)."""
    id: int
    plan_version_id: int
    check_name: AuditCheckName
    status: AuditStatus
    count: int
    details_json: Optional[dict] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class FreezeWindow:
    """Freeze window rule (from freeze_windows table)."""
    id: int
    rule_name: str
    minutes_before_start: int
    behavior: Literal["FROZEN", "OVERRIDE_REQUIRED"]
    enabled: bool
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Diff Engine Models
# ============================================================================

@dataclass
class TourDiff:
    """Single tour change between forecast versions."""
    diff_type: DiffType
    fingerprint: str
    old_values: Optional[dict] = None  # For REMOVED/CHANGED
    new_values: Optional[dict] = None  # For ADDED/CHANGED
    changed_fields: list[str] = field(default_factory=list)  # For CHANGED only


@dataclass
class DiffSummary:
    """Aggregated diff between two forecast versions."""
    forecast_version_old: int
    forecast_version_new: int
    added: int
    removed: int
    changed: int
    details: list[TourDiff]

    def total_changes(self) -> int:
        """Total number of changes."""
        return self.added + self.removed + self.changed

    def has_changes(self) -> bool:
        """Check if any changes exist."""
        return self.total_changes() > 0


# ============================================================================
# Solver Models
# ============================================================================

@dataclass
class Block:
    """Daily block (1er/2er/3er) from partition stage."""
    block_id: str
    day: int
    tour_ids: list[int]
    start_time: time
    end_time: time
    duration_min: int
    work_hours: float
    block_type: Literal["1er", "2er", "3er", "split_2er"]
    is_split: bool = False
    span_group_key: Optional[str] = None


@dataclass
class DriverPath:
    """Weekly driver assignment path (sequence of blocks)."""
    driver_id: str
    blocks: list[Block]
    total_work_hours: float
    is_full_time: bool  # work_hours >= 40

    def num_blocks(self) -> int:
        return len(self.blocks)

    def has_triples(self) -> bool:
        """Check if path contains any triple blocks."""
        return any(b.block_type == "3er" for b in self.blocks)

    def has_consecutive_triples(self) -> bool:
        """Check if path has consecutive triple shifts (fatigue violation)."""
        for i in range(len(self.blocks) - 1):
            if self.blocks[i].block_type == "3er" and self.blocks[i + 1].block_type == "3er":
                if self.blocks[i + 1].day == self.blocks[i].day + 1:
                    return True
        return False


@dataclass
class SolverResult:
    """Complete solver output."""
    plan_version_id: int
    forecast_version_id: int
    seed: int
    num_drivers: int
    num_full_time: int
    num_part_time: int
    avg_work_hours: float
    paths: list[DriverPath]
    assignments: list[Assignment]
    kpis: dict
    solver_time_seconds: float


# ============================================================================
# KPI Models
# ============================================================================

@dataclass
class KPISummary:
    """Aggregated KPIs for a plan version."""
    plan_version_id: int
    num_drivers: int
    num_full_time: int
    num_part_time: int
    part_time_ratio: float  # num_part_time / num_drivers
    avg_work_hours: float
    min_work_hours: float
    max_work_hours: float
    block_mix: dict[str, int]  # {"1er": 10, "2er": 30, "3er": 50}
    num_splits: int
    peak_fleet: int  # Max concurrent active tours
    coverage: float  # Should be 1.0 (100%)
    violations: dict[str, int]  # {check_name: count}


# ============================================================================
# Compose Engine Models
# ============================================================================

@dataclass
class PatchEvent:
    """Single patch event for a week."""
    forecast_version_id: int
    week_key: str
    created_at: datetime
    source: ForecastSource
    days_present: set[int]  # Which days this patch provides (1-7)
    tours: list[dict]       # Normalized tour data
    removals: list[str]     # Fingerprints of tours to remove


@dataclass
class ComposeResult:
    """Result of composing multiple patches into a single forecast."""
    composed_version_id: int
    week_key: str
    patch_ids: list[int]            # Contributing patch IDs in order
    tours_total: int                # Total tours after composition
    tours_added: int                # From patches
    tours_removed: int              # Via tombstones
    tours_updated: int              # Count changes via LWW
    days_present: int               # Actual days with tours
    expected_days: int              # Expected days for week type
    completeness: CompletenessStatus
    input_hash: str                 # Hash of composed state


@dataclass
class TourState:
    """Current state of a tour during composition (LWW)."""
    fingerprint: str
    day: int
    start_ts: time
    end_ts: time
    count: int
    depot: Optional[str]
    skill: Optional[str]
    source_version_id: int          # Which patch provided this state
    source_created_at: datetime     # For LWW ordering
    is_removed: bool = False        # Tombstone marker
    metadata: Optional[dict] = None


# ============================================================================
# Scenario Models
# ============================================================================

@dataclass
class SolverConfig:
    """Full solver configuration for scenario runs."""
    seed: int
    weekly_hours_cap: int = 55              # Hard cap
    freeze_window_minutes: int = 720        # 12h default
    triple_gap_min: int = 30                # 3er-chain gap min (minutes)
    triple_gap_max: int = 60                # 3er-chain gap max
    split_break_min: int = 240              # Split break min (4h)
    split_break_max: int = 360              # Split break max (6h)
    churn_weight: float = 0.0               # 0 = no stability, >0 = penalize churn
    seed_sweep_count: int = 1               # 1 = single seed, >1 = sweep
    rest_min_minutes: int = 660             # 11h
    span_regular_max: int = 840             # 14h
    span_split_max: int = 960               # 16h

    def to_dict(self) -> dict:
        """Convert to dict for JSON storage."""
        return {
            "seed": self.seed,
            "weekly_hours_cap": self.weekly_hours_cap,
            "freeze_window_minutes": self.freeze_window_minutes,
            "triple_gap_min": self.triple_gap_min,
            "triple_gap_max": self.triple_gap_max,
            "split_break_min": self.split_break_min,
            "split_break_max": self.split_break_max,
            "churn_weight": self.churn_weight,
            "seed_sweep_count": self.seed_sweep_count,
            "rest_min_minutes": self.rest_min_minutes,
            "span_regular_max": self.span_regular_max,
            "span_split_max": self.span_split_max,
        }

    def compute_hash(self) -> str:
        """Compute deterministic hash for config versioning."""
        import hashlib
        import json
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class ScenarioResult:
    """Result of a single scenario run."""
    plan_version_id: int
    scenario_label: str
    forecast_version_id: int
    baseline_plan_version_id: Optional[int]
    config: SolverConfig
    # Metrics
    drivers_total: int
    fte_count: int
    pt_count: int
    avg_weekly_hours: float
    max_weekly_hours: float
    # Churn (vs baseline)
    churn_count: int = 0
    churn_drivers_affected: int = 0
    churn_percent: float = 0.0
    # Audit summary
    audits_passed: int = 0
    audits_total: int = 0
    # Timing
    solve_time_seconds: float = 0.0


@dataclass
class ScenarioComparison:
    """Comparison of multiple scenario results."""
    forecast_version_id: int
    week_key: str
    baseline_plan_version_id: Optional[int]
    scenarios: list[ScenarioResult]
    created_at: datetime = field(default_factory=datetime.now)

    def best_by_drivers(self) -> Optional[ScenarioResult]:
        """Get scenario with minimum drivers (among those with all audits passed)."""
        valid = [s for s in self.scenarios if s.audits_passed == s.audits_total]
        if not valid:
            return None
        return min(valid, key=lambda s: s.drivers_total)

    def best_by_churn(self) -> Optional[ScenarioResult]:
        """Get scenario with minimum churn (among those with all audits passed)."""
        valid = [s for s in self.scenarios if s.audits_passed == s.audits_total]
        if not valid:
            return None
        return min(valid, key=lambda s: s.churn_count)


# ============================================================================
# Utility Functions
# ============================================================================

def compute_tour_fingerprint(day: int, start: time, end: time, depot: Optional[str] = None, skill: Optional[str] = None) -> str:
    """
    Compute stable tour fingerprint for diff matching.

    fingerprint = hash(day, start_minute, end_minute, depot?, skill?)
    """
    import hashlib

    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute

    parts = [str(day), str(start_min), str(end_min)]
    if depot:
        parts.append(depot)
    if skill:
        parts.append(skill)

    fingerprint_str = "_".join(parts)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def compute_input_hash(canonical_lines: list[str]) -> str:
    """Compute stable hash of canonicalized input."""
    import hashlib

    # Sort for determinism (order shouldn't matter for hashing)
    sorted_lines = sorted(canonical_lines)
    content = "\n".join(sorted_lines)
    return hashlib.sha256(content.encode()).hexdigest()


def compute_output_hash(assignments: list[Assignment], kpis: dict) -> str:
    """Compute hash of solver output for reproducibility testing."""
    import hashlib
    import json

    # Sort assignments for determinism
    sorted_assignments = sorted(
        [(a.driver_id, a.tour_id, a.day, a.block_id) for a in assignments]
    )

    # Combine assignments + KPIs
    output_data = {
        "assignments": sorted_assignments,
        "kpis": kpis
    }

    content = json.dumps(output_data, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()
