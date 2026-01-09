"""
SOLVEREIGN Gurkerl Dispatch Assist - Data Models
=================================================

Core data structures for dispatch assist operations.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID


# =============================================================================
# ENUMS
# =============================================================================

class ShiftStatus(str, Enum):
    """Status of a shift assignment."""
    ASSIGNED = "assigned"      # Driver assigned and confirmed
    OPEN = "open"             # No driver assigned (needs fill)
    PENDING = "pending"       # Awaiting confirmation
    CANCELLED = "cancelled"   # Shift cancelled


class AbsenceType(str, Enum):
    """Type of driver absence."""
    SICK = "sick"
    VACATION = "vacation"
    TRAINING = "training"
    PERSONAL = "personal"
    UNKNOWN = "unknown"


class ProposalStatus(str, Enum):
    """Status of a candidate proposal."""
    # Legacy statuses (for in-memory proposals)
    PENDING = "pending"       # Waiting for dispatcher review
    ACCEPTED = "accepted"     # Dispatcher approved
    REJECTED = "rejected"     # Dispatcher rejected
    EXPIRED = "expired"       # Time window passed
    # DB-backed statuses (for persisted proposals with fingerprinting)
    GENERATED = "generated"   # Candidates generated, fingerprint captured
    PROPOSED = "proposed"     # Sent to dispatcher, awaiting apply
    APPLIED = "applied"       # Applied to sheet successfully
    INVALIDATED = "invalidated"  # Sheet changed, proposal no longer valid


class OpenShiftStatus(str, Enum):
    """Status of an open shift in the dispatch lifecycle."""
    DETECTED = "detected"                # Just discovered from sheet
    PROPOSAL_GENERATED = "proposal_generated"  # Proposal created
    APPLIED = "applied"                  # Driver assigned via apply
    CLOSED = "closed"                    # Filled externally or no longer needed
    INVALIDATED = "invalidated"          # Data changed, needs re-detection


class FingerprintScopeType(str, Enum):
    """Scope type for fingerprint calculation."""
    DAY_ONLY = "DAY_ONLY"      # Only the shift date
    DAY_PM1 = "DAY_PM1"        # Day ± 1 (default, for rest constraint)
    WEEK_WINDOW = "WEEK_WINDOW"  # Full week (for weekly hours constraint)


class DisqualificationReason(str, Enum):
    """Reasons why a driver is not eligible for a shift."""
    ABSENT = "absent"                      # Driver is on leave
    ALREADY_ASSIGNED = "already_assigned"  # Already has shift that day
    INSUFFICIENT_REST = "insufficient_rest"  # 11h rest violated
    MAX_DAILY_TOURS = "max_daily_tours"    # Too many tours in day
    WEEKLY_HOURS_EXCEEDED = "weekly_hours_exceeded"  # 55h limit
    SKILL_MISMATCH = "skill_mismatch"      # Missing required skill
    ZONE_MISMATCH = "zone_mismatch"        # Wrong zone
    BLACKLISTED = "blacklisted"            # Manual exclusion


# =============================================================================
# CORE DATA CLASSES
# =============================================================================

@dataclass
class TimeWindow:
    """A time window (start to end)."""
    start: time
    end: time

    @property
    def duration_minutes(self) -> int:
        """Duration in minutes."""
        start_mins = self.start.hour * 60 + self.start.minute
        end_mins = self.end.hour * 60 + self.end.minute
        if end_mins < start_mins:
            # Overnight shift
            end_mins += 24 * 60
        return end_mins - start_mins


@dataclass
class ShiftAssignment:
    """A shift assignment from the roster."""
    id: str
    shift_date: date
    shift_start: time
    shift_end: time
    driver_id: Optional[str] = None  # External driver ID from sheets
    driver_name: Optional[str] = None
    route_id: Optional[str] = None
    zone: Optional[str] = None
    status: ShiftStatus = ShiftStatus.ASSIGNED
    notes: Optional[str] = None
    row_index: Optional[int] = None  # Row in Google Sheet

    @property
    def duration_minutes(self) -> int:
        """Shift duration in minutes."""
        return TimeWindow(self.shift_start, self.shift_end).duration_minutes

    @property
    def duration_hours(self) -> float:
        """Shift duration in hours."""
        return self.duration_minutes / 60.0


@dataclass
class OpenShift:
    """An open shift that needs to be filled."""
    id: str
    shift_date: date
    shift_start: time
    shift_end: time
    route_id: Optional[str] = None
    zone: Optional[str] = None
    required_skills: List[str] = field(default_factory=list)
    priority: int = 1  # 1=highest, 5=lowest
    reason: str = "unassigned"  # Why is this open?
    original_driver_id: Optional[str] = None  # Who was originally assigned?
    row_index: Optional[int] = None  # Row in Google Sheet
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def duration_hours(self) -> float:
        """Shift duration in hours."""
        return TimeWindow(self.shift_start, self.shift_end).duration_minutes / 60.0


@dataclass
class DriverState:
    """Current state of a driver for eligibility checking."""
    driver_id: str
    driver_name: str

    # Weekly state
    week_start: date
    hours_worked_this_week: float = 0.0
    tours_this_week: int = 0
    target_weekly_hours: float = 40.0

    # Daily state (for the day being evaluated)
    shifts_today: List[ShiftAssignment] = field(default_factory=list)
    last_shift_end: Optional[datetime] = None  # For 11h rest check

    # Absences
    absences: List[Dict[str, Any]] = field(default_factory=list)

    # Skills and zones
    skills: List[str] = field(default_factory=list)
    home_zones: List[str] = field(default_factory=list)

    # Flags
    is_active: bool = True
    is_part_time: bool = False
    max_weekly_hours: float = 55.0  # Hard limit

    def is_absent_on(self, check_date: date) -> Optional[AbsenceType]:
        """Check if driver is absent on a specific date."""
        for absence in self.absences:
            start = absence.get("start_date")
            end = absence.get("end_date")
            if start and end:
                if isinstance(start, str):
                    start = date.fromisoformat(start)
                if isinstance(end, str):
                    end = date.fromisoformat(end)
                if start <= check_date <= end:
                    return AbsenceType(absence.get("type", "unknown"))
        return None

    @property
    def hours_gap(self) -> float:
        """Gap between worked hours and target (positive = under target)."""
        return self.target_weekly_hours - self.hours_worked_this_week


@dataclass
class Disqualification:
    """Reason why a driver is disqualified for a shift."""
    reason: DisqualificationReason
    details: str
    severity: int = 1  # 1=hard block, 2=soft warning


@dataclass
class Candidate:
    """A candidate driver for an open shift."""
    driver_id: str
    driver_name: str

    # Eligibility
    is_eligible: bool = True
    disqualifications: List[Disqualification] = field(default_factory=list)

    # Scoring (lower = better, like golf)
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # State info
    current_weekly_hours: float = 0.0
    hours_after_assignment: float = 0.0
    fairness_score: float = 0.0  # Gap to target hours

    # Ranking
    rank: int = 0
    reasons: List[str] = field(default_factory=list)  # Why ranked this way

    @property
    def is_qualified(self) -> bool:
        """Qualified = eligible with no hard disqualifications."""
        if not self.is_eligible:
            return False
        hard_blocks = [d for d in self.disqualifications if d.severity == 1]
        return len(hard_blocks) == 0


@dataclass
class Proposal:
    """A proposal to fill an open shift."""
    id: str
    open_shift_id: str
    shift_date: date

    # Top candidates (ranked)
    candidates: List[Candidate] = field(default_factory=list)
    top_candidate_id: Optional[str] = None
    top_candidate_name: Optional[str] = None

    # Metadata
    generated_at: datetime = field(default_factory=datetime.now)
    generated_by: str = "solvereign"
    status: ProposalStatus = ProposalStatus.PENDING

    # If applied
    applied_at: Optional[datetime] = None
    applied_by: Optional[str] = None
    selected_candidate_id: Optional[str] = None

    # For writeback
    proposal_row_index: Optional[int] = None  # Row in Proposals tab

    @property
    def has_candidates(self) -> bool:
        """Check if any eligible candidates found."""
        return len([c for c in self.candidates if c.is_qualified]) > 0


# =============================================================================
# SHEET CONFIGURATION
# =============================================================================

@dataclass
class SheetConfig:
    """Configuration for Google Sheets roster structure."""
    spreadsheet_id: str

    # Tab names
    roster_tab: str = "Dienstplan"
    proposals_tab: str = "Proposals"
    drivers_tab: str = "Fahrer"
    absences_tab: str = "Abwesenheiten"

    # Column mappings for roster tab
    roster_columns: Dict[str, str] = field(default_factory=lambda: {
        "date": "A",           # Date column
        "shift_start": "B",    # Shift start time
        "shift_end": "C",      # Shift end time
        "driver_id": "D",      # Driver ID/code
        "driver_name": "E",    # Driver name
        "route": "F",          # Route ID
        "zone": "G",           # Zone
        "status": "H",         # Status
        "notes": "I",          # Notes
    })

    # Column mappings for drivers tab
    driver_columns: Dict[str, str] = field(default_factory=lambda: {
        "driver_id": "A",
        "name": "B",
        "target_hours": "C",
        "skills": "D",
        "zones": "E",
        "is_active": "F",
    })

    # Column mappings for absences tab
    absence_columns: Dict[str, str] = field(default_factory=lambda: {
        "driver_id": "A",
        "start_date": "B",
        "end_date": "C",
        "type": "D",
        "notes": "E",
    })

    # Header row (1-indexed)
    header_row: int = 1

    # Date format in sheets
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H:%M"

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "SheetConfig":
        """Create config from JSON."""
        return cls(
            spreadsheet_id=data["spreadsheet_id"],
            roster_tab=data.get("roster_tab", "Dienstplan"),
            proposals_tab=data.get("proposals_tab", "Proposals"),
            drivers_tab=data.get("drivers_tab", "Fahrer"),
            absences_tab=data.get("absences_tab", "Abwesenheiten"),
            roster_columns=data.get("roster_columns", cls.__dataclass_fields__["roster_columns"].default_factory()),
            driver_columns=data.get("driver_columns", cls.__dataclass_fields__["driver_columns"].default_factory()),
            absence_columns=data.get("absence_columns", cls.__dataclass_fields__["absence_columns"].default_factory()),
            header_row=data.get("header_row", 1),
            date_format=data.get("date_format", "%Y-%m-%d"),
            time_format=data.get("time_format", "%H:%M"),
        )


# =============================================================================
# FINGERPRINT & CONCURRENCY CONTROL
# =============================================================================

@dataclass
class FingerprintScope:
    """
    Defines what data to include in fingerprint calculation.

    The fingerprint is a SHA-256 hash of relevant sheet data within a scope.
    This allows detecting changes that could affect proposal validity.
    """
    shift_date: date
    scope_type: FingerprintScopeType = FingerprintScopeType.DAY_PM1
    include_absences: bool = True
    include_driver_hours: bool = True  # Weekly hours for eligibility check

    def get_date_range(self) -> tuple:
        """Get the date range for this scope."""
        if self.scope_type == FingerprintScopeType.DAY_ONLY:
            return (self.shift_date, self.shift_date)
        elif self.scope_type == FingerprintScopeType.DAY_PM1:
            return (
                self.shift_date - timedelta(days=1),
                self.shift_date + timedelta(days=1)
            )
        else:  # WEEK_WINDOW
            # Monday of the week containing shift_date
            week_start = self.shift_date - timedelta(days=self.shift_date.weekday())
            week_end = week_start + timedelta(days=6)
            return (week_start, week_end)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONB storage."""
        return {
            "shift_date": self.shift_date.isoformat(),
            "scope_type": self.scope_type.value,
            "include_absences": self.include_absences,
            "include_driver_hours": self.include_driver_hours,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FingerprintScope":
        """Deserialize from dict."""
        return cls(
            shift_date=date.fromisoformat(data["shift_date"]) if isinstance(data["shift_date"], str) else data["shift_date"],
            scope_type=FingerprintScopeType(data.get("scope_type", "DAY_PM1")),
            include_absences=data.get("include_absences", True),
            include_driver_hours=data.get("include_driver_hours", True),
        )


@dataclass
class FingerprintData:
    """Result of fingerprint calculation."""
    fingerprint: str  # SHA-256 hex string (64 chars)
    revision: int  # Google Sheets revision number
    scope: FingerprintScope
    computed_at: datetime = field(default_factory=datetime.now)

    # Raw data used for fingerprint (for diff hints)
    roster_rows_count: int = 0
    drivers_count: int = 0
    absences_count: int = 0


@dataclass
class DiffHints:
    """Hints about what changed between two fingerprints."""
    roster_changed: bool = False
    drivers_changed: bool = False
    absences_changed: bool = False
    changed_roster_rows: List[int] = field(default_factory=list)  # Row indices
    changed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONB storage."""
        return {
            "roster_changed": self.roster_changed,
            "drivers_changed": self.drivers_changed,
            "absences_changed": self.absences_changed,
            "changed_roster_rows": self.changed_roster_rows[:10],  # Limit for response size
            "changed_at": self.changed_at.isoformat(),
        }


# =============================================================================
# APPLY WORKFLOW MODELS
# =============================================================================

@dataclass
class ApplyRequest:
    """Request to apply a proposal (assign driver to shift)."""
    proposal_id: str
    selected_driver_id: str
    expected_plan_fingerprint: str
    apply_request_id: Optional[str] = None  # Idempotency key (UUID)
    force: bool = False
    force_reason: Optional[str] = None  # Required if force=True (min 10 chars)


@dataclass
class ApplyResult:
    """Result of applying a proposal."""
    success: bool
    proposal_id: str

    # Success details
    selected_driver_id: Optional[str] = None
    selected_driver_name: Optional[str] = None
    applied_at: Optional[datetime] = None
    applied_by: Optional[str] = None
    cells_written: List[str] = field(default_factory=list)

    # Error details
    error_code: Optional[str] = None  # PLAN_CHANGED, NOT_ELIGIBLE, INVALID_STATUS, etc.
    error_message: Optional[str] = None

    # Conflict details (if error_code == PLAN_CHANGED)
    expected_fingerprint: Optional[str] = None
    latest_fingerprint: Optional[str] = None
    hint_diffs: Optional[DiffHints] = None

    # Eligibility failure details (if error_code == NOT_ELIGIBLE)
    disqualifications: List[Disqualification] = field(default_factory=list)

    # Idempotency
    is_idempotent_replay: bool = False  # True if this is a cached result

    @property
    def is_conflict(self) -> bool:
        """Check if this is a fingerprint conflict."""
        return self.error_code == "PLAN_CHANGED"

    @property
    def is_eligibility_failure(self) -> bool:
        """Check if this is an eligibility failure."""
        return self.error_code == "NOT_ELIGIBLE"


@dataclass
class PersistedProposal:
    """
    A proposal persisted to the database with fingerprinting.

    This extends the in-memory Proposal with DB-specific fields.
    """
    id: str  # UUID
    tenant_id: int
    open_shift_id: str  # UUID
    shift_key: str

    # Fingerprint for concurrency control
    expected_plan_fingerprint: str
    expected_revision: Optional[int] = None
    fingerprint_scope: Optional[FingerprintScope] = None
    config_version: str = "v1"

    # Candidates
    candidates: List[Candidate] = field(default_factory=list)

    # Status
    status: ProposalStatus = ProposalStatus.GENERATED

    # Timestamps
    generated_at: datetime = field(default_factory=datetime.now)
    generated_by: str = "solvereign"
    proposed_at: Optional[datetime] = None
    proposed_by: Optional[str] = None
    applied_at: Optional[datetime] = None
    applied_by: Optional[str] = None

    # Apply details
    selected_driver_id: Optional[str] = None
    selected_driver_name: Optional[str] = None
    apply_request_id: Optional[str] = None

    # Force tracking
    forced_apply: bool = False
    force_reason: Optional[str] = None

    # Conflict tracking
    latest_fingerprint: Optional[str] = None
    hint_diffs: Optional[DiffHints] = None

    # Site reference
    site_id: Optional[str] = None

    @property
    def is_applied(self) -> bool:
        """Check if proposal has been applied."""
        return self.status == ProposalStatus.APPLIED

    @property
    def can_apply(self) -> bool:
        """Check if proposal can be applied (status allows it)."""
        return self.status == ProposalStatus.PROPOSED

    @property
    def has_eligible_candidates(self) -> bool:
        """Check if any eligible candidates exist."""
        return any(c.is_eligible for c in self.candidates)


# =============================================================================
# SHEET CONTRACT VALIDATION
# =============================================================================

@dataclass
class SheetContractValidation:
    """
    Result of validating sheet structure matches expected contract.

    This prevents silent failures when:
    - Columns are moved/renamed
    - Tabs are renamed/deleted
    - Schema drift between config and actual sheet
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Detailed checks
    tabs_found: List[str] = field(default_factory=list)
    tabs_missing: List[str] = field(default_factory=list)
    columns_found: Dict[str, List[str]] = field(default_factory=dict)
    columns_missing: Dict[str, List[str]] = field(default_factory=dict)

    validated_at: datetime = field(default_factory=datetime.now)

    def add_error(self, error: str) -> None:
        """Add a validation error."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a validation warning (doesn't fail validation)."""
        self.warnings.append(warning)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API response."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "tabs_missing": self.tabs_missing,
            "columns_missing": self.columns_missing,
            "validated_at": self.validated_at.isoformat(),
        }

    @property
    def error_message(self) -> str:
        """Get combined error message for API response."""
        if not self.errors:
            return ""
        return f"Sheet contract invalid: {'; '.join(self.errors)}"
