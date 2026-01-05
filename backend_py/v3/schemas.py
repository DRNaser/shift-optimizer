"""
SOLVEREIGN V3 Enterprise Schemas
=================================

Pydantic/Dataclass definitions for all core entities.
Single Source of Truth for data structures.

Key Concepts:
    - Duty: A work unit assigned to a driver on a single day (1er/2er/3er block)
    - Segment: A continuous work period within a duty (individual tour)
    - Instance: The actual assignment slot (1:1 with assignments table)

Hierarchy:
    Duty (block)
      └─ Segment[] (tours within block)
           └─ Instance (assignment slot)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
import hashlib
import json


# ============================================================================
# ENUMS
# ============================================================================

class ForecastStatus(str, Enum):
    """Forecast validation status."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class PlanStatus(str, Enum):
    """Plan lifecycle status."""
    DRAFT = "DRAFT"
    SOLVING = "SOLVING"
    FAILED = "FAILED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class AuditStatus(str, Enum):
    """Audit check result."""
    PASS = "PASS"
    FAIL = "FAIL"
    OVERRIDE = "OVERRIDE"


class DiffType(str, Enum):
    """Diff change type."""
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


class BlockType(str, Enum):
    """Block type classification."""
    SINGLE = "1er"           # Single tour
    DOUBLE_REG = "2er-reg"   # 2 tours, 30-60min gap
    DOUBLE_SPLIT = "2er-split"  # 2 tours, 240-360min break
    TRIPLE = "3er-chain"     # 3 tours, 30-60min gaps


class RiskLevel(str, Enum):
    """Simulation risk level."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ============================================================================
# TIME UTILITIES (Centralized)
# ============================================================================

@dataclass
class NormalizedTime:
    """
    Normalized time on a linear axis (minutes from week start).

    Solves cross-midnight ambiguity by using absolute minutes.
    Week starts Monday 00:00 = minute 0.
    """
    minutes_from_week_start: int

    @classmethod
    def from_day_time(cls, day: int, t: time, crosses_midnight: bool = False) -> NormalizedTime:
        """
        Convert (day, time) to normalized minutes.

        Args:
            day: Day number 1-7 (Mo=1, So=7)
            t: Time of day
            crosses_midnight: If True and time is early morning, add 24h

        Returns:
            NormalizedTime with absolute minutes from week start
        """
        day_offset = (day - 1) * 24 * 60  # Minutes from Monday 00:00
        time_minutes = t.hour * 60 + t.minute

        # Handle cross-midnight: early morning times belong to next day
        if crosses_midnight and time_minutes < 12 * 60:  # Before noon
            day_offset += 24 * 60  # Add one day

        return cls(minutes_from_week_start=day_offset + time_minutes)

    @classmethod
    def from_datetime(cls, dt: datetime, week_anchor: date) -> NormalizedTime:
        """Convert datetime to normalized minutes using week anchor."""
        delta = dt - datetime.combine(week_anchor, time(0, 0))
        return cls(minutes_from_week_start=int(delta.total_seconds() / 60))

    def to_datetime(self, week_anchor: date) -> datetime:
        """Convert back to datetime using week anchor."""
        return datetime.combine(week_anchor, time(0, 0)) + timedelta(minutes=self.minutes_from_week_start)

    def __lt__(self, other: NormalizedTime) -> bool:
        return self.minutes_from_week_start < other.minutes_from_week_start

    def __le__(self, other: NormalizedTime) -> bool:
        return self.minutes_from_week_start <= other.minutes_from_week_start

    def __sub__(self, other: NormalizedTime) -> int:
        """Returns difference in minutes."""
        return self.minutes_from_week_start - other.minutes_from_week_start

    def overlaps(self, other_start: NormalizedTime, other_end: NormalizedTime,
                 self_end: NormalizedTime) -> bool:
        """Check if [self, self_end) overlaps with [other_start, other_end)."""
        return self.minutes_from_week_start < other_end.minutes_from_week_start and \
               self_end.minutes_from_week_start > other_start.minutes_from_week_start


# ============================================================================
# CORE ENTITIES
# ============================================================================

@dataclass
class Segment:
    """
    A continuous work period (single tour).

    This is the atomic unit of work - a driver works continuously
    from start to end without interruption.
    """
    id: Optional[int] = None
    tour_instance_id: int = 0

    # Time (normalized)
    start: NormalizedTime = field(default_factory=lambda: NormalizedTime(0))
    end: NormalizedTime = field(default_factory=lambda: NormalizedTime(0))

    # Original values (for display)
    day: int = 1
    start_ts: Optional[time] = None
    end_ts: Optional[time] = None
    crosses_midnight: bool = False

    # Metadata
    duration_min: int = 0
    work_hours: float = 0.0
    depot: Optional[str] = None
    skill: Optional[str] = None

    @property
    def span_minutes(self) -> int:
        """Duration from start to end in minutes."""
        return self.end - self.start

    def overlaps_with(self, other: Segment) -> bool:
        """Check if this segment overlaps with another."""
        return self.start.overlaps(other.start, other.end, self.end)


@dataclass
class Duty:
    """
    A work unit assigned to a driver on a single day.

    Contains 1-3 segments (tours) that form a logical block:
    - 1er: Single segment
    - 2er-reg: Two segments with 30-60min gap
    - 2er-split: Two segments with 240-360min break
    - 3er-chain: Three segments with 30-60min gaps
    """
    id: Optional[int] = None
    driver_id: str = ""
    day: int = 1
    block_id: str = ""

    # Segments (ordered by start time)
    segments: List[Segment] = field(default_factory=list)

    # Classification
    block_type: BlockType = BlockType.SINGLE

    # Computed values (cached)
    _span_minutes: Optional[int] = field(default=None, repr=False)
    _total_work_minutes: Optional[int] = field(default=None, repr=False)
    _gaps: Optional[List[int]] = field(default=None, repr=False)

    @property
    def span_minutes(self) -> int:
        """Total span from first segment start to last segment end."""
        if self._span_minutes is None and self.segments:
            self._span_minutes = self.segments[-1].end - self.segments[0].start
        return self._span_minutes or 0

    @property
    def total_work_minutes(self) -> int:
        """Sum of all segment durations."""
        if self._total_work_minutes is None:
            self._total_work_minutes = sum(s.duration_min for s in self.segments)
        return self._total_work_minutes or 0

    @property
    def gaps(self) -> List[int]:
        """List of gap durations between segments (in minutes)."""
        if self._gaps is None:
            self._gaps = []
            for i in range(1, len(self.segments)):
                gap = self.segments[i].start - self.segments[i-1].end
                self._gaps.append(gap)
        return self._gaps

    @property
    def split_break_minutes(self) -> Optional[int]:
        """Break duration for split shifts (None if not split)."""
        if self.block_type == BlockType.DOUBLE_SPLIT and self.gaps:
            return self.gaps[0]
        return None

    def classify(self) -> BlockType:
        """Classify the duty based on segment count and gaps."""
        n = len(self.segments)

        if n == 1:
            return BlockType.SINGLE
        elif n == 2:
            gap = self.gaps[0] if self.gaps else 0
            if 240 <= gap <= 360:  # 4-6 hours
                return BlockType.DOUBLE_SPLIT
            else:
                return BlockType.DOUBLE_REG
        elif n >= 3:
            return BlockType.TRIPLE

        return BlockType.SINGLE

    def is_valid_gaps(self) -> bool:
        """Check if gaps are within allowed ranges for block type."""
        if self.block_type == BlockType.DOUBLE_REG:
            return all(30 <= g <= 60 for g in self.gaps)
        elif self.block_type == BlockType.DOUBLE_SPLIT:
            return all(240 <= g <= 360 for g in self.gaps)
        elif self.block_type == BlockType.TRIPLE:
            return all(30 <= g <= 60 for g in self.gaps)
        return True


@dataclass
class DailySchedule:
    """A driver's schedule for a single day."""
    driver_id: str
    day: int
    duties: List[Duty] = field(default_factory=list)

    @property
    def total_work_hours(self) -> float:
        """Total work hours across all duties."""
        return sum(d.total_work_minutes for d in self.duties) / 60.0

    @property
    def span_hours(self) -> float:
        """Total span from first duty start to last duty end."""
        if not self.duties:
            return 0.0
        all_segments = [s for d in self.duties for s in d.segments]
        if not all_segments:
            return 0.0
        return (all_segments[-1].end - all_segments[0].start) / 60.0


@dataclass
class WeeklySchedule:
    """A driver's complete weekly schedule."""
    driver_id: str
    week_anchor: date
    daily_schedules: Dict[int, DailySchedule] = field(default_factory=dict)

    @property
    def total_work_hours(self) -> float:
        """Total work hours for the week."""
        return sum(ds.total_work_hours for ds in self.daily_schedules.values())

    @property
    def work_days(self) -> List[int]:
        """Days with assigned work."""
        return sorted(self.daily_schedules.keys())

    def get_duty_sequence(self) -> List[Duty]:
        """All duties in chronological order."""
        return [d for day in sorted(self.daily_schedules.keys())
                for d in self.daily_schedules[day].duties]


# ============================================================================
# FORECAST & PLAN ENTITIES
# ============================================================================

@dataclass
class ForecastVersion:
    """Immutable forecast version."""
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    source: str = "manual"
    input_hash: str = ""
    parser_config_hash: str = ""
    status: ForecastStatus = ForecastStatus.PASS
    week_key: Optional[str] = None
    week_anchor_date: Optional[date] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
            "input_hash": self.input_hash,
            "parser_config_hash": self.parser_config_hash,
            "status": self.status.value,
            "week_key": self.week_key,
            "week_anchor_date": self.week_anchor_date.isoformat() if self.week_anchor_date else None,
            "notes": self.notes,
        }


@dataclass
class TourTemplate:
    """Normalized tour template (before instance expansion)."""
    id: Optional[int] = None
    forecast_version_id: int = 0
    day: int = 1
    start_ts: Optional[time] = None
    end_ts: Optional[time] = None
    duration_min: int = 0
    work_hours: float = 0.0
    span_group_key: Optional[str] = None
    tour_fingerprint: str = ""
    count: int = 1
    depot: Optional[str] = None
    skill: Optional[str] = None
    split_break_minutes: Optional[int] = None


@dataclass
class TourInstance:
    """Expanded tour instance (1:1 with assignment)."""
    id: Optional[int] = None
    forecast_version_id: int = 0
    tour_template_id: int = 0
    instance_no: int = 1
    day: int = 1
    start_ts: Optional[time] = None
    end_ts: Optional[time] = None
    crosses_midnight: bool = False
    duration_min: int = 0
    work_hours: float = 0.0
    span_group_key: Optional[str] = None
    split_break_minutes: Optional[int] = None
    depot: Optional[str] = None
    skill: Optional[str] = None

    def to_segment(self, week_anchor: Optional[date] = None) -> Segment:
        """Convert to Segment with normalized times."""
        start_norm = NormalizedTime.from_day_time(
            self.day, self.start_ts, crosses_midnight=False
        ) if self.start_ts else NormalizedTime(0)

        end_norm = NormalizedTime.from_day_time(
            self.day, self.end_ts, crosses_midnight=self.crosses_midnight
        ) if self.end_ts else NormalizedTime(0)

        return Segment(
            id=None,
            tour_instance_id=self.id or 0,
            start=start_norm,
            end=end_norm,
            day=self.day,
            start_ts=self.start_ts,
            end_ts=self.end_ts,
            crosses_midnight=self.crosses_midnight,
            duration_min=self.duration_min,
            work_hours=self.work_hours,
            depot=self.depot,
            skill=self.skill,
        )


@dataclass
class SolverConfig:
    """Solver configuration (versioned)."""
    seed: int = 94
    weekly_hours_cap: float = 55.0
    freeze_window_minutes: int = 720
    triple_gap_min: int = 30
    triple_gap_max: int = 60
    split_break_min: int = 240
    split_break_max: int = 360
    churn_weight: float = 0.0
    seed_sweep_count: int = 1
    rest_min_minutes: int = 660
    span_regular_max: int = 840
    span_split_max: int = 960

    def to_dict(self) -> Dict[str, Any]:
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
        """Compute deterministic hash of config."""
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True).encode()
        ).hexdigest()


@dataclass
class PlanVersion:
    """Immutable plan version."""
    id: Optional[int] = None
    forecast_version_id: int = 0
    created_at: Optional[datetime] = None
    seed: int = 94
    solver_config_hash: str = ""
    solver_config_json: Optional[Dict[str, Any]] = None
    output_hash: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    notes: Optional[str] = None

    # Extended fields
    baseline_plan_version_id: Optional[int] = None
    scenario_label: Optional[str] = None
    churn_count: Optional[int] = None
    churn_drivers_affected: Optional[int] = None


@dataclass
class Assignment:
    """Driver-to-tour assignment."""
    id: Optional[int] = None
    plan_version_id: int = 0
    driver_id: str = ""
    tour_instance_id: int = 0
    day: int = 1
    block_id: str = ""
    role: str = "PRIMARY"
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# AUDIT ENTITIES
# ============================================================================

@dataclass
class AuditResult:
    """Result of a single audit check."""
    check_name: str
    status: AuditStatus
    violation_count: int = 0
    details: Optional[Dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        return self.status == AuditStatus.PASS


@dataclass
class AuditReport:
    """Complete audit report for a plan."""
    plan_version_id: int
    checks_run: int = 0
    checks_passed: int = 0
    all_passed: bool = False
    results: Dict[str, AuditResult] = field(default_factory=dict)

    def add_result(self, result: AuditResult):
        self.results[result.check_name] = result
        self.checks_run += 1
        if result.passed:
            self.checks_passed += 1
        self.all_passed = (self.checks_run == self.checks_passed)


# ============================================================================
# DIFF ENTITIES
# ============================================================================

@dataclass
class DiffChange:
    """A single change between forecasts."""
    diff_type: DiffType
    tour_fingerprint: str
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    changed_fields: Optional[List[str]] = None

    @property
    def is_time_change(self) -> bool:
        """Check if this is a time-related change."""
        if not self.changed_fields:
            return False
        time_fields = {"start_ts", "end_ts", "duration_min", "crosses_midnight"}
        return bool(time_fields & set(self.changed_fields))

    @property
    def is_meta_change(self) -> bool:
        """Check if this is a metadata-only change."""
        if not self.changed_fields:
            return False
        meta_fields = {"depot", "skill", "count", "notes"}
        return bool(meta_fields & set(self.changed_fields)) and not self.is_time_change


@dataclass
class DiffResult:
    """Complete diff between two forecasts."""
    forecast_version_old: int
    forecast_version_new: int
    changes: List[DiffChange] = field(default_factory=list)

    @property
    def added(self) -> List[DiffChange]:
        return [c for c in self.changes if c.diff_type == DiffType.ADDED]

    @property
    def removed(self) -> List[DiffChange]:
        return [c for c in self.changes if c.diff_type == DiffType.REMOVED]

    @property
    def changed(self) -> List[DiffChange]:
        return [c for c in self.changes if c.diff_type == DiffType.CHANGED]

    @property
    def time_changes(self) -> List[DiffChange]:
        """Changes affecting tour timing (impacts audit)."""
        return [c for c in self.changed if c.is_time_change]

    @property
    def meta_changes(self) -> List[DiffChange]:
        """Changes affecting metadata only (safe for ops)."""
        return [c for c in self.changed if c.is_meta_change]

    @property
    def summary(self) -> str:
        return f"{len(self.added)} added, {len(self.removed)} removed, {len(self.changed)} changed"


# ============================================================================
# KPI ENTITIES
# ============================================================================

@dataclass
class PlanKPIs:
    """Key Performance Indicators for a plan."""
    plan_version_id: int

    # Driver metrics
    total_drivers: int = 0
    fte_drivers: int = 0  # >=40h
    pt_drivers: int = 0   # <40h
    pt_ratio: float = 0.0

    # Hours metrics
    avg_work_hours: float = 0.0
    max_work_hours: float = 0.0
    min_work_hours: float = 0.0
    total_work_hours: float = 0.0

    # Block metrics
    block_counts: Dict[str, int] = field(default_factory=dict)
    total_blocks: int = 0

    # Coverage
    total_tours: int = 0
    assigned_tours: int = 0
    coverage_rate: float = 0.0

    # Quality
    near_violations: int = 0
    churn_rate: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_version_id": self.plan_version_id,
            "total_drivers": self.total_drivers,
            "fte_drivers": self.fte_drivers,
            "pt_drivers": self.pt_drivers,
            "pt_ratio": self.pt_ratio,
            "avg_work_hours": self.avg_work_hours,
            "max_work_hours": self.max_work_hours,
            "min_work_hours": self.min_work_hours,
            "total_work_hours": self.total_work_hours,
            "block_counts": self.block_counts,
            "total_blocks": self.total_blocks,
            "total_tours": self.total_tours,
            "assigned_tours": self.assigned_tours,
            "coverage_rate": self.coverage_rate,
            "near_violations": self.near_violations,
            "churn_rate": self.churn_rate,
        }


# ============================================================================
# SIMULATION ENTITIES
# ============================================================================

@dataclass
class SimulationResult:
    """Result of a simulation scenario."""
    scenario_name: str
    scenario_type: str

    # Baseline vs simulated
    baseline_kpis: Optional[PlanKPIs] = None
    simulated_kpis: Optional[PlanKPIs] = None

    # Deltas
    delta_drivers: int = 0
    delta_pt_ratio: float = 0.0
    delta_churn: float = 0.0

    # Risk assessment
    risk_score: RiskLevel = RiskLevel.LOW
    risk_factors: List[str] = field(default_factory=list)

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    # Timing
    execution_time_ms: int = 0


# ============================================================================
# HASH UTILITIES
# ============================================================================

def compute_input_hash(canonical_text: str) -> str:
    """Compute SHA256 hash of canonical input text."""
    return hashlib.sha256(canonical_text.encode('utf-8')).hexdigest()


def compute_output_hash(assignments: List[Assignment], solver_config_hash: str) -> str:
    """
    Compute deterministic output hash.

    Includes:
    - solver_config_hash (ensures config is part of identity)
    - All assignments sorted by (driver_id, day, tour_instance_id)
    """
    sorted_assignments = sorted(
        [
            {
                "driver_id": a.driver_id,
                "tour_instance_id": a.tour_instance_id,
                "day": a.day,
            }
            for a in assignments
        ],
        key=lambda x: (x["driver_id"], x["day"], x["tour_instance_id"])
    )

    output_data = {
        "solver_config_hash": solver_config_hash,
        "assignments": sorted_assignments,
    }

    return hashlib.sha256(
        json.dumps(output_data, sort_keys=True).encode()
    ).hexdigest()


def compute_tour_fingerprint(
    day: int,
    start: time,
    end: time,
    depot: Optional[str] = None,
    skill: Optional[str] = None
) -> str:
    """Compute stable fingerprint for diff matching."""
    data = {
        "day": day,
        "start": start.strftime("%H:%M") if start else "",
        "end": end.strftime("%H:%M") if end else "",
        "depot": depot or "",
        "skill": skill or "",
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()
