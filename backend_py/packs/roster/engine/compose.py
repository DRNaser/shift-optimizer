"""
SOLVEREIGN V3 Compose Engine
============================

Deterministic PATCH/LWW composition for partial forecasts.
Each Slack message becomes a PATCH event, COMPOSED forecast generated via LWW merge.

Key Concepts:
- PATCH: Partial forecast update for a week (can provide subset of days)
- COMPOSED: Merged result of all patches for a week_key
- LWW: Latest-Write-Wins based on created_at timestamp
- Tombstone: Explicit removal marker for tours
- Advisory Lock: Prevents concurrent compose for same week_key
"""

from datetime import datetime, time
from typing import Optional
import hashlib
import json


# ============================================================================
# Advisory Lock for Compose Concurrency Control
# ============================================================================

def _compute_week_lock_id(week_key: str) -> int:
    """
    Compute a stable lock ID for a week_key.

    PostgreSQL advisory locks use bigint IDs. We hash the week_key
    to get a deterministic ID.

    Args:
        week_key: Week identifier (e.g., "2026-W01")

    Returns:
        Integer lock ID (truncated to fit bigint)
    """
    # Use first 8 bytes of SHA256 as lock ID
    hash_bytes = hashlib.sha256(f"compose:{week_key}".encode()).digest()[:8]
    lock_id = int.from_bytes(hash_bytes, byteorder='big', signed=True)
    return lock_id


def acquire_compose_lock(db_connection, week_key: str, timeout_ms: int = 5000) -> bool:
    """
    Acquire advisory lock for compose operation.

    SPEC: Prevents double-ingest race conditions.

    Args:
        db_connection: Database connection
        week_key: Week to lock
        timeout_ms: Lock timeout in milliseconds (default 5s)

    Returns:
        True if lock acquired, False if timeout
    """
    lock_id = _compute_week_lock_id(week_key)

    with db_connection.cursor() as cur:
        # Set lock timeout
        cur.execute(f"SET LOCAL lock_timeout = '{timeout_ms}ms'")

        try:
            # Try to acquire advisory lock (session-level, released on commit/rollback)
            cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
            result = cur.fetchone()
            acquired = result[0] if result else False

            if acquired:
                print(f"[COMPOSE LOCK] Acquired lock for {week_key} (id={lock_id})")
            else:
                print(f"[COMPOSE LOCK] Failed to acquire lock for {week_key} (id={lock_id})")

            return acquired
        except Exception as e:
            print(f"[COMPOSE LOCK] Error acquiring lock: {e}")
            return False


def release_compose_lock(db_connection, week_key: str) -> bool:
    """
    Release advisory lock for compose operation.

    Args:
        db_connection: Database connection
        week_key: Week to unlock

    Returns:
        True if released, False if not held
    """
    lock_id = _compute_week_lock_id(week_key)

    with db_connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        result = cur.fetchone()
        released = result[0] if result else False

        if released:
            print(f"[COMPOSE LOCK] Released lock for {week_key} (id={lock_id})")

        return released

from .models import (
    ForecastSource,
    ForecastStatus,
    CompletenessStatus,
    TourState,
    PatchEvent,
    ComposeResult,
    compute_tour_fingerprint,
    compute_input_hash,
)


# ============================================================================
# Compose Engine Core
# ============================================================================

class ComposeEngine:
    """
    Deterministic compose engine for partial forecasts.

    Pipeline:
    1. Fetch all PATCH forecasts for week_key
    2. Sort by created_at (chronological)
    3. Apply LWW merge (latest values win)
    4. Handle tombstones (explicit removals)
    5. Compute completeness (days_present vs expected_days)
    6. Create COMPOSED forecast version
    """

    def __init__(self, db_connection=None):
        """
        Initialize compose engine.

        Args:
            db_connection: Database connection (None for dry-run mode)
        """
        self.db = db_connection
        self._tour_states: dict[str, TourState] = {}  # fingerprint -> state
        self._patches_applied: list[int] = []

    def compose_week(
        self,
        week_key: str,
        expected_days: int = 6,
        save_to_db: bool = True,
        use_lock: bool = True
    ) -> ComposeResult:
        """
        Compose all patches for a week into a single COMPOSED forecast.

        Args:
            week_key: Week identifier (e.g., "2026-W01" or "2026-01-06")
            expected_days: Expected number of days with tours (default 6 = Mo-Sa)
            save_to_db: Whether to persist result to database
            use_lock: Whether to use advisory lock (default True for concurrency safety)

        Returns:
            ComposeResult with composed forecast details

        Raises:
            RuntimeError: If advisory lock cannot be acquired (concurrent compose)
        """
        # SPEC: Acquire advisory lock to prevent concurrent compose
        lock_acquired = False
        if use_lock and self.db:
            lock_acquired = acquire_compose_lock(self.db, week_key)
            if not lock_acquired:
                raise RuntimeError(
                    f"Cannot compose week {week_key}: another compose operation is in progress. "
                    "Retry after current operation completes."
                )

        try:
            return self._compose_week_impl(week_key, expected_days, save_to_db)
        finally:
            # Always release lock if we acquired it
            if lock_acquired and self.db:
                release_compose_lock(self.db, week_key)

    def _compose_week_impl(
        self,
        week_key: str,
        expected_days: int,
        save_to_db: bool
    ) -> ComposeResult:
        """Internal implementation of compose_week (after lock acquired)."""
        # 1. Fetch patches for week
        patches = self._fetch_patches(week_key)

        if not patches:
            raise ValueError(f"No patches found for week_key: {week_key}")

        # 2. Reset state
        self._tour_states = {}
        self._patches_applied = []

        # 3. Apply patches in chronological order (LWW)
        for patch in patches:
            self._apply_patch(patch)

        # 4. Compute final state
        active_tours = [
            state for state in self._tour_states.values()
            if not state.is_removed
        ]

        # 5. Compute completeness
        days_present = len(set(tour.day for tour in active_tours))
        completeness = self._compute_completeness(days_present, expected_days)

        # 6. Compute input hash for composed state
        canonical_lines = self._generate_canonical_lines(active_tours)
        input_hash = compute_input_hash(canonical_lines)

        # 7. Count changes
        tours_added = sum(1 for s in self._tour_states.values() if not s.is_removed)
        tours_removed = sum(1 for s in self._tour_states.values() if s.is_removed)

        # 8. Create result
        result = ComposeResult(
            composed_version_id=0,  # Set after DB insert
            week_key=week_key,
            patch_ids=self._patches_applied,
            tours_total=len(active_tours),
            tours_added=tours_added,
            tours_removed=tours_removed,
            tours_updated=0,  # TODO: Track LWW updates
            days_present=days_present,
            expected_days=expected_days,
            completeness=completeness,
            input_hash=input_hash,
        )

        # 9. Persist if requested
        if save_to_db and self.db:
            result = self._save_composed_forecast(result, active_tours)

        return result

    def _fetch_patches(self, week_key: str) -> list[PatchEvent]:
        """
        Fetch all PATCH forecasts for a week, sorted by created_at.

        Args:
            week_key: Week identifier

        Returns:
            List of PatchEvent sorted chronologically
        """
        if not self.db:
            return []

        with self.db.cursor() as cur:
            cur.execute("""
                SELECT
                    fv.id,
                    fv.week_key,
                    fv.created_at,
                    fv.source,
                    tn.day,
                    tn.start_ts,
                    tn.end_ts,
                    tn.count,
                    tn.depot,
                    tn.skill,
                    tn.tour_fingerprint,
                    tn.metadata
                FROM forecast_versions fv
                JOIN tours_normalized tn ON tn.forecast_version_id = fv.id
                WHERE fv.week_key = %s
                  AND fv.source IN ('patch', 'slack', 'csv', 'manual')
                ORDER BY fv.created_at ASC, fv.id ASC
            """, (week_key,))

            rows = cur.fetchall()

        # Group by forecast_version_id
        patches_dict: dict[int, PatchEvent] = {}

        for row in rows:
            fv_id = row['id']

            if fv_id not in patches_dict:
                patches_dict[fv_id] = PatchEvent(
                    forecast_version_id=fv_id,
                    week_key=row['week_key'],
                    created_at=row['created_at'],
                    source=ForecastSource(row['source']),
                    days_present=set(),
                    tours=[],
                    removals=[],
                )

            patch = patches_dict[fv_id]
            patch.days_present.add(row['day'])
            patch.tours.append({
                'day': row['day'],
                'start_ts': row['start_ts'],
                'end_ts': row['end_ts'],
                'count': row['count'],
                'depot': row['depot'],
                'skill': row['skill'],
                'fingerprint': row['tour_fingerprint'],
                'metadata': row['metadata'],
            })

        # Fetch tombstones for each patch
        for fv_id, patch in patches_dict.items():
            with self.db.cursor() as cur:
                cur.execute("""
                    SELECT tour_fingerprint
                    FROM tour_removals
                    WHERE forecast_version_id = %s
                """, (fv_id,))

                for row in cur.fetchall():
                    patch.removals.append(row['tour_fingerprint'])

        return list(patches_dict.values())

    def _apply_patch(self, patch: PatchEvent) -> None:
        """
        Apply a single patch using LWW semantics.

        Args:
            patch: PatchEvent to apply
        """
        self._patches_applied.append(patch.forecast_version_id)

        # Apply tour updates (LWW - later patch wins)
        for tour in patch.tours:
            fingerprint = tour['fingerprint']

            # Create or update tour state
            self._tour_states[fingerprint] = TourState(
                fingerprint=fingerprint,
                day=tour['day'],
                start_ts=tour['start_ts'],
                end_ts=tour['end_ts'],
                count=tour['count'],
                depot=tour['depot'],
                skill=tour['skill'],
                source_version_id=patch.forecast_version_id,
                source_created_at=patch.created_at,
                is_removed=False,
                metadata=tour['metadata'],
            )

        # Apply tombstones (removals)
        for fingerprint in patch.removals:
            if fingerprint in self._tour_states:
                # Mark existing tour as removed
                state = self._tour_states[fingerprint]
                self._tour_states[fingerprint] = TourState(
                    fingerprint=state.fingerprint,
                    day=state.day,
                    start_ts=state.start_ts,
                    end_ts=state.end_ts,
                    count=state.count,
                    depot=state.depot,
                    skill=state.skill,
                    source_version_id=patch.forecast_version_id,
                    source_created_at=patch.created_at,
                    is_removed=True,
                    metadata=state.metadata,
                )
            else:
                # Create tombstone for tour we haven't seen
                # (defensive: removal before add in patch stream)
                self._tour_states[fingerprint] = TourState(
                    fingerprint=fingerprint,
                    day=0,
                    start_ts=time(0, 0),
                    end_ts=time(0, 0),
                    count=0,
                    depot=None,
                    skill=None,
                    source_version_id=patch.forecast_version_id,
                    source_created_at=patch.created_at,
                    is_removed=True,
                )

    def _compute_completeness(
        self,
        days_present: int,
        expected_days: int
    ) -> CompletenessStatus:
        """
        Compute completeness status.

        Args:
            days_present: Number of days with tours
            expected_days: Expected number of days

        Returns:
            CompletenessStatus enum value
        """
        if days_present >= expected_days:
            return CompletenessStatus.COMPLETE
        elif days_present > 0:
            return CompletenessStatus.PARTIAL
        else:
            return CompletenessStatus.UNKNOWN

    def _generate_canonical_lines(self, tours: list[TourState]) -> list[str]:
        """
        Generate canonical lines for input hash computation.

        Args:
            tours: List of TourState objects

        Returns:
            List of canonical text lines
        """
        lines = []
        for tour in sorted(tours, key=lambda t: (t.day, t.start_ts, t.fingerprint)):
            # Format: DAY|HH:MM-HH:MM|COUNT|DEPOT|SKILL
            parts = [
                str(tour.day),
                f"{tour.start_ts.hour:02d}:{tour.start_ts.minute:02d}",
                f"{tour.end_ts.hour:02d}:{tour.end_ts.minute:02d}",
                str(tour.count),
            ]
            if tour.depot:
                parts.append(tour.depot)
            if tour.skill:
                parts.append(tour.skill)

            lines.append("|".join(parts))

        return lines

    def _save_composed_forecast(
        self,
        result: ComposeResult,
        tours: list[TourState]
    ) -> ComposeResult:
        """
        Save composed forecast to database.

        Args:
            result: ComposeResult to persist
            tours: Active tour states to save

        Returns:
            Updated ComposeResult with composed_version_id
        """
        if not self.db:
            return result

        with self.db.cursor() as cur:
            # 1. Create forecast_version for COMPOSED
            cur.execute("""
                INSERT INTO forecast_versions (
                    source, input_hash, parser_config_hash, status,
                    week_key, completeness_status, expected_days, days_present,
                    provenance_json
                ) VALUES (
                    'composed', %s, 'compose_v1', 'PASS',
                    %s, %s, %s, %s,
                    %s
                )
                RETURNING id
            """, (
                result.input_hash,
                result.week_key,
                result.completeness.value,
                result.expected_days,
                result.days_present,
                json.dumps({'patch_ids': result.patch_ids}),
            ))

            composed_id = cur.fetchone()['id']

            # 2. Insert tours_normalized
            for tour in tours:
                cur.execute("""
                    INSERT INTO tours_normalized (
                        forecast_version_id, day, start_ts, end_ts,
                        duration_min, work_hours, tour_fingerprint,
                        count, depot, skill, source_version_id, is_removed
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                """, (
                    composed_id,
                    tour.day,
                    tour.start_ts,
                    tour.end_ts,
                    self._compute_duration(tour.start_ts, tour.end_ts),
                    self._compute_work_hours(tour.start_ts, tour.end_ts),
                    tour.fingerprint,
                    tour.count,
                    tour.depot,
                    tour.skill,
                    tour.source_version_id,
                    False,
                ))

            # 3. Insert composition provenance
            for order, patch_id in enumerate(result.patch_ids):
                cur.execute("""
                    INSERT INTO forecast_compositions (
                        composed_version_id, patch_version_id, patch_order
                    ) VALUES (%s, %s, %s)
                """, (composed_id, patch_id, order))

            self.db.commit()

        # Update result with ID
        result.composed_version_id = composed_id
        return result

    def _compute_duration(self, start: time, end: time) -> int:
        """Compute duration in minutes (handles cross-midnight)."""
        start_min = start.hour * 60 + start.minute
        end_min = end.hour * 60 + end.minute

        if end_min <= start_min:
            # Cross-midnight
            return (24 * 60 - start_min) + end_min
        return end_min - start_min

    def _compute_work_hours(self, start: time, end: time) -> float:
        """Compute work hours from duration."""
        return self._compute_duration(start, end) / 60.0


# ============================================================================
# Completeness Gate
# ============================================================================

def check_release_gate(
    forecast_version_id: int,
    db_connection,
    require_complete: bool = True,
    admin_override: bool = False,
    admin_user: Optional[str] = None
) -> dict:
    """
    Check if forecast can be released (completeness gate).

    Args:
        forecast_version_id: Forecast to check
        db_connection: Database connection
        require_complete: Whether COMPLETE status is required
        admin_override: Admin override for PARTIAL releases
        admin_user: Admin user performing override

    Returns:
        dict with: can_release, reason, completeness_status
    """
    with db_connection.cursor() as cur:
        cur.execute("""
            SELECT completeness_status, days_present, expected_days, week_key
            FROM forecast_versions
            WHERE id = %s
        """, (forecast_version_id,))

        row = cur.fetchone()

        if not row:
            return {
                'can_release': False,
                'reason': 'Forecast version not found',
                'completeness_status': None,
            }

        status = CompletenessStatus(row['completeness_status'])
        days_present = row['days_present']
        expected_days = row['expected_days']
        week_key = row['week_key']

        # Check gate
        if status == CompletenessStatus.COMPLETE:
            return {
                'can_release': True,
                'reason': f'Complete forecast ({days_present}/{expected_days} days)',
                'completeness_status': status.value,
            }

        if status == CompletenessStatus.PARTIAL and admin_override:
            # Log override to audit
            cur.execute("""
                INSERT INTO audit_log (
                    plan_version_id, check_name, status, count, details_json
                ) VALUES (
                    NULL, 'PARTIAL_RELEASE_OVERRIDE', 'PASS', 1,
                    %s
                )
            """, (json.dumps({
                'forecast_version_id': forecast_version_id,
                'week_key': week_key,
                'days_present': days_present,
                'expected_days': expected_days,
                'admin_user': admin_user,
                'timestamp': datetime.now().isoformat(),
            }),))
            db_connection.commit()

            return {
                'can_release': True,
                'reason': f'Admin override for partial forecast ({days_present}/{expected_days} days)',
                'completeness_status': status.value,
                'override_by': admin_user,
            }

        if status == CompletenessStatus.PARTIAL:
            return {
                'can_release': False,
                'reason': f'Incomplete forecast ({days_present}/{expected_days} days). Admin override required.',
                'completeness_status': status.value,
            }

        return {
            'can_release': False,
            'reason': f'Unknown completeness status',
            'completeness_status': status.value,
        }


# ============================================================================
# Convenience Functions
# ============================================================================

def compose_week_forecast(
    week_key: str,
    db_connection,
    expected_days: int = 6,
    save_to_db: bool = True
) -> ComposeResult:
    """
    Convenience function to compose all patches for a week.

    Args:
        week_key: Week identifier (e.g., "2026-W01")
        db_connection: Database connection
        expected_days: Expected days (default 6 = Mo-Sa)
        save_to_db: Whether to persist

    Returns:
        ComposeResult
    """
    engine = ComposeEngine(db_connection)
    return engine.compose_week(week_key, expected_days, save_to_db)


def get_week_patches(week_key: str, db_connection) -> list[dict]:
    """
    Get all patches for a week with summary info.

    Args:
        week_key: Week identifier
        db_connection: Database connection

    Returns:
        List of patch summaries
    """
    with db_connection.cursor() as cur:
        cur.execute("""
            SELECT
                fv.id,
                fv.created_at,
                fv.source,
                fv.status,
                fv.days_present,
                COUNT(tn.id) as tour_count
            FROM forecast_versions fv
            LEFT JOIN tours_normalized tn ON tn.forecast_version_id = fv.id
            WHERE fv.week_key = %s
              AND fv.source != 'composed'
            GROUP BY fv.id
            ORDER BY fv.created_at ASC
        """, (week_key,))

        return [dict(row) for row in cur.fetchall()]


def get_latest_composed(week_key: str, db_connection) -> Optional[dict]:
    """
    Get the latest COMPOSED forecast for a week.

    Args:
        week_key: Week identifier
        db_connection: Database connection

    Returns:
        Composed forecast details or None
    """
    with db_connection.cursor() as cur:
        cur.execute("""
            SELECT
                fv.*,
                COUNT(tn.id) as tour_count
            FROM forecast_versions fv
            LEFT JOIN tours_normalized tn ON tn.forecast_version_id = fv.id
            WHERE fv.week_key = %s
              AND fv.source = 'composed'
            GROUP BY fv.id
            ORDER BY fv.created_at DESC
            LIMIT 1
        """, (week_key,))

        row = cur.fetchone()
        return dict(row) if row else None


def add_tour_removal(
    forecast_version_id: int,
    tour_fingerprint: str,
    db_connection,
    reason: Optional[str] = None
) -> int:
    """
    Add a tombstone for a removed tour.

    Args:
        forecast_version_id: Patch forecast ID
        tour_fingerprint: Fingerprint of tour to remove
        db_connection: Database connection
        reason: Optional removal reason

    Returns:
        Tombstone ID
    """
    with db_connection.cursor() as cur:
        cur.execute("""
            INSERT INTO tour_removals (
                forecast_version_id, tour_fingerprint, reason
            ) VALUES (%s, %s, %s)
            ON CONFLICT (forecast_version_id, tour_fingerprint) DO UPDATE
            SET reason = EXCLUDED.reason, removed_at = NOW()
            RETURNING id
        """, (forecast_version_id, tour_fingerprint, reason))

        result = cur.fetchone()
        db_connection.commit()

        return result['id']


def compute_week_key(date: datetime) -> str:
    """
    Compute ISO week key from date.

    Args:
        date: Date to compute week key for

    Returns:
        Week key in format "YYYY-WNN"
    """
    iso_cal = date.isocalendar()
    return f"{iso_cal[0]}-W{iso_cal[1]:02d}"


def get_baseline_plan(week_key: str, db_connection) -> Optional[dict]:
    """
    Get the last LOCKED plan for a week (baseline for churn calculation).

    Args:
        week_key: Week identifier
        db_connection: Database connection

    Returns:
        Baseline plan details or None
    """
    with db_connection.cursor() as cur:
        cur.execute("""
            SELECT pv.*
            FROM plan_versions pv
            JOIN forecast_versions fv ON fv.id = pv.forecast_version_id
            WHERE fv.week_key = %s
              AND pv.status = 'LOCKED'
            ORDER BY pv.locked_at DESC
            LIMIT 1
        """, (week_key,))

        row = cur.fetchone()
        return dict(row) if row else None
