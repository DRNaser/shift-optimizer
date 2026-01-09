"""
SOLVEREIGN Gurkerl Dispatch Assist - Google Sheets Adapter
===========================================================

Reads roster data from Google Sheets and writes proposals back.

Google Sheets remains the SOURCE OF TRUTH for the operational plan.
SOLVEREIGN only reads and writes to designated tabs.

Required Setup:
1. Create service account in Google Cloud Console
2. Share spreadsheet with service account email
3. Set environment variables:
   - SHEETS_SPREADSHEET_ID: The spreadsheet ID
   - SHEETS_SERVICE_ACCOUNT_JSON: Path to service account JSON or JSON string

Column Mapping:
    Column mappings are configurable via SheetConfig.
    DO NOT hardcode column letters - use config.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod

from .models import (
    ShiftAssignment,
    OpenShift,
    DriverState,
    Proposal,
    Candidate,
    ShiftStatus,
    ProposalStatus,
    SheetConfig,
    FingerprintScope,
    FingerprintScopeType,
    FingerprintData,
    DiffHints,
    SheetContractValidation,
)

logger = logging.getLogger(__name__)


# =============================================================================
# FINGERPRINT CACHE
# =============================================================================

class FingerprintCache:
    """
    Simple TTL cache for fingerprints.

    Avoids excessive API calls when checking fingerprints repeatedly.
    Cache is invalidated after any write operation.
    """

    def __init__(self, ttl_seconds: int = 60):
        """
        Initialize cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default 60s)
        """
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[FingerprintData, datetime]] = {}

    def _make_key(self, spreadsheet_id: str, scope: FingerprintScope) -> str:
        """Create cache key from spreadsheet ID and scope."""
        scope_str = f"{scope.shift_date}_{scope.scope_type.value}"
        return f"{spreadsheet_id}:{scope_str}"

    def get(self, spreadsheet_id: str, scope: FingerprintScope) -> Optional[FingerprintData]:
        """
        Get cached fingerprint if still valid.

        Args:
            spreadsheet_id: The spreadsheet ID
            scope: The fingerprint scope

        Returns:
            FingerprintData if cached and valid, None otherwise
        """
        key = self._make_key(spreadsheet_id, scope)
        if key in self._cache:
            fp_data, cached_at = self._cache[key]
            if datetime.now() - cached_at < timedelta(seconds=self.ttl):
                logger.debug(f"Fingerprint cache hit for {key}")
                return fp_data
            else:
                # Expired
                del self._cache[key]
        return None

    def set(self, spreadsheet_id: str, fp_data: FingerprintData) -> None:
        """
        Cache a fingerprint.

        Args:
            spreadsheet_id: The spreadsheet ID
            fp_data: The fingerprint data to cache
        """
        key = self._make_key(spreadsheet_id, fp_data.scope)
        self._cache[key] = (fp_data, datetime.now())
        logger.debug(f"Cached fingerprint for {key}")

    def invalidate(self, spreadsheet_id: str) -> None:
        """
        Invalidate all cached fingerprints for a spreadsheet.

        Call this after any write operation.

        Args:
            spreadsheet_id: The spreadsheet ID
        """
        keys_to_delete = [k for k in self._cache if k.startswith(f"{spreadsheet_id}:")]
        for key in keys_to_delete:
            del self._cache[key]
        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cached fingerprints for {spreadsheet_id}")

    def clear(self) -> None:
        """Clear all cached fingerprints."""
        self._cache.clear()


# Global fingerprint cache (shared across adapter instances)
_fingerprint_cache = FingerprintCache()


# =============================================================================
# ABSTRACT ADAPTER (for testing/mocking)
# =============================================================================

class SheetAdapterBase(ABC):
    """Abstract base class for sheet adapters."""

    @abstractmethod
    async def read_roster(self, date_range: Optional[Tuple[date, date]] = None) -> List[ShiftAssignment]:
        """Read roster data from sheets."""
        pass

    @abstractmethod
    async def read_drivers(self) -> List[DriverState]:
        """Read driver master data from sheets."""
        pass

    @abstractmethod
    async def detect_open_shifts(self, roster: List[ShiftAssignment]) -> List[OpenShift]:
        """Detect open shifts from roster."""
        pass

    @abstractmethod
    async def write_proposals(self, proposals: List[Proposal]) -> int:
        """Write proposals to sheets. Returns count written."""
        pass

    # =========================================================================
    # FINGERPRINT METHODS (for optimistic concurrency control)
    # =========================================================================

    @abstractmethod
    async def get_sheet_revision(self) -> int:
        """Get the current revision number of the spreadsheet."""
        pass

    @abstractmethod
    async def read_scoped_ranges(self, scope: FingerprintScope) -> Dict[str, Any]:
        """
        Read data within the fingerprint scope.

        Returns dict with roster_data, drivers_data, absences_data, read_at.
        """
        pass

    @abstractmethod
    def compute_fingerprint(
        self,
        scoped_values: Dict[str, Any],
        revision: int,
        config_version: str = "v1",
    ) -> str:
        """Compute SHA-256 fingerprint of scoped data."""
        pass

    @abstractmethod
    async def get_current_fingerprint(self, scope: FingerprintScope) -> FingerprintData:
        """Get current fingerprint for scope (with caching)."""
        pass

    @abstractmethod
    async def compute_diff_hints(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        scope: FingerprintScope,
    ) -> DiffHints:
        """Compute hints about what changed between two states."""
        pass

    @abstractmethod
    async def write_assignment(
        self,
        row_index: int,
        driver_id: str,
        driver_name: str,
        status: str = "ASSIGNED",
    ) -> List[str]:
        """
        Write driver assignment to specific row.

        Returns list of cell addresses written (e.g., ["D10", "E10"]).
        """
        pass

    @abstractmethod
    async def validate_sheet_contract(self) -> SheetContractValidation:
        """
        Validate that sheet structure matches expected contract.

        Checks:
        - Required tabs exist (roster, drivers, absences, proposals)
        - Required columns exist in each tab
        - Column headers match expected names

        Returns:
            SheetContractValidation with errors if invalid
        """
        pass

    @abstractmethod
    def invalidate_fingerprint_cache(self) -> None:
        """Invalidate fingerprint cache after writes."""
        pass


# =============================================================================
# GOOGLE SHEETS ADAPTER
# =============================================================================

class GoogleSheetsAdapter(SheetAdapterBase):
    """
    Google Sheets adapter for roster operations.

    Uses Google Sheets API v4 via gspread library.
    """

    def __init__(self, config: SheetConfig, credentials: Optional[Dict] = None):
        """
        Initialize adapter.

        Args:
            config: Sheet configuration
            credentials: Optional service account credentials dict.
                        If None, will read from SHEETS_SERVICE_ACCOUNT_JSON env var.
        """
        self.config = config
        self._credentials = credentials
        self._client = None
        self._spreadsheet = None

    async def _get_client(self):
        """Lazy-load gspread client."""
        if self._client is None:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
            except ImportError:
                raise ImportError(
                    "Google Sheets adapter requires gspread and google-auth packages. "
                    "Install with: pip install gspread google-auth"
                )

            # Get credentials
            if self._credentials:
                creds_dict = self._credentials
            else:
                creds_env = os.environ.get("SHEETS_SERVICE_ACCOUNT_JSON", "")
                if creds_env.startswith("{"):
                    # JSON string
                    creds_dict = json.loads(creds_env)
                elif os.path.exists(creds_env):
                    # File path
                    with open(creds_env) as f:
                        creds_dict = json.load(f)
                else:
                    raise ValueError(
                        "SHEETS_SERVICE_ACCOUNT_JSON must be set to JSON string or file path"
                    )

            # Create credentials
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            self._client = gspread.authorize(creds)

        return self._client

    async def _get_spreadsheet(self):
        """Get the spreadsheet object."""
        if self._spreadsheet is None:
            client = await self._get_client()
            self._spreadsheet = client.open_by_key(self.config.spreadsheet_id)
        return self._spreadsheet

    async def read_roster(
        self,
        date_range: Optional[Tuple[date, date]] = None,
    ) -> List[ShiftAssignment]:
        """
        Read roster assignments from the Dienstplan tab.

        Args:
            date_range: Optional (start_date, end_date) filter

        Returns:
            List of ShiftAssignment objects
        """
        spreadsheet = await self._get_spreadsheet()
        worksheet = spreadsheet.worksheet(self.config.roster_tab)

        # Get all values
        values = worksheet.get_all_values()
        if len(values) <= self.config.header_row:
            return []

        # Parse headers
        headers = values[self.config.header_row - 1]
        data_rows = values[self.config.header_row:]

        # Build column index map
        col_map = self._build_column_map(headers, self.config.roster_columns)

        assignments = []
        for row_idx, row in enumerate(data_rows, start=self.config.header_row + 1):
            try:
                assignment = self._parse_roster_row(row, col_map, row_idx)
                if assignment:
                    # Filter by date range if specified
                    if date_range:
                        if assignment.shift_date < date_range[0] or assignment.shift_date > date_range[1]:
                            continue
                    assignments.append(assignment)
            except Exception as e:
                logger.warning(f"Error parsing roster row {row_idx}: {e}")

        logger.info(f"Read {len(assignments)} roster assignments from sheets")
        return assignments

    async def read_drivers(self) -> List[DriverState]:
        """
        Read driver master data from the Fahrer tab.

        Returns:
            List of DriverState objects (without shift/hours data - those come from roster)
        """
        spreadsheet = await self._get_spreadsheet()

        try:
            worksheet = spreadsheet.worksheet(self.config.drivers_tab)
        except Exception:
            logger.warning(f"Drivers tab '{self.config.drivers_tab}' not found")
            return []

        values = worksheet.get_all_values()
        if len(values) <= self.config.header_row:
            return []

        headers = values[self.config.header_row - 1]
        data_rows = values[self.config.header_row:]

        col_map = self._build_column_map(headers, self.config.driver_columns)

        drivers = []
        for row in data_rows:
            try:
                driver = self._parse_driver_row(row, col_map)
                if driver:
                    drivers.append(driver)
            except Exception as e:
                logger.warning(f"Error parsing driver row: {e}")

        # Read absences
        absences_by_driver = await self._read_absences()

        # Merge absences into drivers
        for driver in drivers:
            driver.absences = absences_by_driver.get(driver.driver_id, [])

        logger.info(f"Read {len(drivers)} drivers from sheets")
        return drivers

    async def _read_absences(self) -> Dict[str, List[Dict]]:
        """Read absences from the Abwesenheiten tab."""
        spreadsheet = await self._get_spreadsheet()

        try:
            worksheet = spreadsheet.worksheet(self.config.absences_tab)
        except Exception:
            logger.warning(f"Absences tab '{self.config.absences_tab}' not found")
            return {}

        values = worksheet.get_all_values()
        if len(values) <= self.config.header_row:
            return {}

        headers = values[self.config.header_row - 1]
        data_rows = values[self.config.header_row:]

        col_map = self._build_column_map(headers, self.config.absence_columns)

        absences_by_driver: Dict[str, List[Dict]] = {}

        for row in data_rows:
            try:
                driver_id_col = col_map.get("driver_id", 0)
                driver_id = row[driver_id_col] if len(row) > driver_id_col else None

                if not driver_id:
                    continue

                start_col = col_map.get("start_date", 1)
                end_col = col_map.get("end_date", 2)
                type_col = col_map.get("type", 3)

                absence = {
                    "start_date": self._parse_date(row[start_col] if len(row) > start_col else ""),
                    "end_date": self._parse_date(row[end_col] if len(row) > end_col else ""),
                    "type": row[type_col] if len(row) > type_col else "unknown",
                }

                if absence["start_date"] and absence["end_date"]:
                    if driver_id not in absences_by_driver:
                        absences_by_driver[driver_id] = []
                    absences_by_driver[driver_id].append(absence)

            except Exception as e:
                logger.warning(f"Error parsing absence row: {e}")

        return absences_by_driver

    async def detect_open_shifts(
        self,
        roster: List[ShiftAssignment],
    ) -> List[OpenShift]:
        """
        Detect open shifts from roster.

        Open shift criteria:
        - driver_id is empty/None
        - status is OPEN
        - status is empty and driver_id is empty

        Args:
            roster: List of roster assignments

        Returns:
            List of OpenShift objects
        """
        open_shifts = []

        for assignment in roster:
            is_open = (
                assignment.status == ShiftStatus.OPEN or
                (not assignment.driver_id and assignment.status != ShiftStatus.CANCELLED)
            )

            if is_open:
                open_shift = OpenShift(
                    id=f"open_{assignment.shift_date}_{assignment.row_index}",
                    shift_date=assignment.shift_date,
                    shift_start=assignment.shift_start,
                    shift_end=assignment.shift_end,
                    route_id=assignment.route_id,
                    zone=assignment.zone,
                    reason=f"unassigned (row {assignment.row_index})",
                    original_driver_id=None,  # Could be filled if tracking history
                    row_index=assignment.row_index,
                )
                open_shifts.append(open_shift)

        logger.info(f"Detected {len(open_shifts)} open shifts")
        return open_shifts

    async def write_proposals(self, proposals: List[Proposal]) -> int:
        """
        Write proposals to the Proposals tab.

        Creates the tab if it doesn't exist.

        Args:
            proposals: List of proposals to write

        Returns:
            Number of proposals written
        """
        if not proposals:
            return 0

        spreadsheet = await self._get_spreadsheet()

        # Get or create Proposals worksheet
        try:
            worksheet = spreadsheet.worksheet(self.config.proposals_tab)
        except Exception:
            # Create the tab
            worksheet = spreadsheet.add_worksheet(
                title=self.config.proposals_tab,
                rows=1000,
                cols=15,
            )
            # Add headers
            headers = [
                "Proposal ID", "Shift Date", "Shift Start", "Shift End",
                "Route", "Zone", "Generated At", "Status",
                "Top Candidate ID", "Top Candidate Name", "Score",
                "Candidate 2", "Candidate 3", "Notes", "Original Row"
            ]
            worksheet.append_row(headers)

        # Write proposals
        rows_to_add = []
        for proposal in proposals:
            top = proposal.candidates[0] if proposal.candidates else None
            second = proposal.candidates[1] if len(proposal.candidates) > 1 else None
            third = proposal.candidates[2] if len(proposal.candidates) > 2 else None

            # Find the original shift for context
            shift_info = self._get_shift_info(proposal)

            row = [
                proposal.id,
                proposal.shift_date.isoformat() if proposal.shift_date else "",
                shift_info.get("start", ""),
                shift_info.get("end", ""),
                shift_info.get("route", ""),
                shift_info.get("zone", ""),
                proposal.generated_at.isoformat() if proposal.generated_at else "",
                proposal.status.value,
                top.driver_id if top else "",
                top.driver_name if top else "",
                f"{top.score:.2f}" if top else "",
                f"{second.driver_name} ({second.score:.2f})" if second else "",
                f"{third.driver_name} ({third.score:.2f})" if third else "",
                "; ".join(top.reasons[:2]) if top and top.reasons else "",
                str(proposal.proposal_row_index) if proposal.proposal_row_index else "",
            ]
            rows_to_add.append(row)

        # Batch write
        if rows_to_add:
            worksheet.append_rows(rows_to_add)

        logger.info(f"Wrote {len(rows_to_add)} proposals to sheets")
        return len(rows_to_add)

    def _get_shift_info(self, proposal: Proposal) -> Dict[str, str]:
        """Extract shift info from proposal for display."""
        # This would need the original OpenShift reference
        # For now, return empty
        return {"start": "", "end": "", "route": "", "zone": ""}

    # =========================================================================
    # FINGERPRINT METHODS (Optimistic Concurrency Control)
    # =========================================================================

    async def get_sheet_revision(self) -> int:
        """
        Get the current revision number of the spreadsheet.

        Uses Drive API to get file version/revision.

        Returns:
            Integer revision number (0 if unable to retrieve)
        """
        try:
            # gspread doesn't expose revision directly
            # Use the spreadsheet's lastModifiedTime as a proxy
            spreadsheet = await self._get_spreadsheet()

            # Try to get version from metadata
            # The 'version' property in Drive API
            try:
                # Access internal client to make Drive API call
                client = await self._get_client()
                # gspread's client has http_client that we can use
                # But for simplicity, use the spreadsheet's fetchSheetMetadata
                meta = spreadsheet.fetch_sheet_metadata()
                # Sheet metadata doesn't have revision, use a hash of titles/ids
                sheet_ids = [s.get("properties", {}).get("sheetId", 0) for s in meta.get("sheets", [])]
                revision = sum(sheet_ids) % 1000000  # Simple deterministic number
                return revision
            except Exception as e:
                logger.warning(f"Could not get sheet revision via metadata: {e}")
                return 0

        except Exception as e:
            logger.warning(f"Could not get sheet revision: {e}")
            return 0

    async def read_scoped_ranges(self, scope: FingerprintScope) -> Dict[str, Any]:
        """
        Read data within the fingerprint scope.

        Only reads rows/columns relevant to the scope for efficiency.

        Args:
            scope: FingerprintScope defining what data to include

        Returns:
            Dict with roster_data, drivers_data, absences_data, read_at
        """
        spreadsheet = await self._get_spreadsheet()
        date_start, date_end = scope.get_date_range()

        # Read roster data (filtered by date range)
        roster_data = []
        try:
            roster_ws = spreadsheet.worksheet(self.config.roster_tab)
            all_roster = roster_ws.get_all_values()
            if len(all_roster) > self.config.header_row:
                headers = all_roster[self.config.header_row - 1]
                col_map = self._build_column_map(headers, self.config.roster_columns)
                date_col = col_map.get("date", 0)

                for row_idx, row in enumerate(all_roster[self.config.header_row:], start=self.config.header_row + 1):
                    if len(row) > date_col:
                        row_date = self._parse_date(row[date_col])
                        if row_date and date_start <= row_date <= date_end:
                            # Include relevant columns only for fingerprint
                            roster_data.append({
                                "row": row_idx,
                                "date": row[date_col] if len(row) > date_col else "",
                                "driver_id": row[col_map.get("driver_id", -1)] if col_map.get("driver_id", -1) < len(row) else "",
                                "status": row[col_map.get("status", -1)] if col_map.get("status", -1) < len(row) else "",
                                "shift_start": row[col_map.get("shift_start", -1)] if col_map.get("shift_start", -1) < len(row) else "",
                                "shift_end": row[col_map.get("shift_end", -1)] if col_map.get("shift_end", -1) < len(row) else "",
                            })
        except Exception as e:
            logger.warning(f"Error reading roster for fingerprint: {e}")

        # Read driver master data (all active drivers - needed for eligibility)
        drivers_data = []
        try:
            drivers_ws = spreadsheet.worksheet(self.config.drivers_tab)
            all_drivers = drivers_ws.get_all_values()
            if len(all_drivers) > self.config.header_row:
                headers = all_drivers[self.config.header_row - 1]
                col_map = self._build_column_map(headers, self.config.driver_columns)

                for row in all_drivers[self.config.header_row:]:
                    driver_id = row[col_map.get("driver_id", 0)] if col_map.get("driver_id", 0) < len(row) else ""
                    if driver_id:
                        drivers_data.append({
                            "driver_id": driver_id,
                            "target_hours": row[col_map.get("target_hours", -1)] if col_map.get("target_hours", -1) < len(row) else "",
                            "skills": row[col_map.get("skills", -1)] if col_map.get("skills", -1) < len(row) else "",
                            "zones": row[col_map.get("zones", -1)] if col_map.get("zones", -1) < len(row) else "",
                            "is_active": row[col_map.get("is_active", -1)] if col_map.get("is_active", -1) < len(row) else "",
                        })
        except Exception as e:
            logger.warning(f"Error reading drivers for fingerprint: {e}")

        # Read absences (filtered by date range if enabled)
        absences_data = []
        if scope.include_absences:
            try:
                absences_ws = spreadsheet.worksheet(self.config.absences_tab)
                all_absences = absences_ws.get_all_values()
                if len(all_absences) > self.config.header_row:
                    headers = all_absences[self.config.header_row - 1]
                    col_map = self._build_column_map(headers, self.config.absence_columns)

                    for row in all_absences[self.config.header_row:]:
                        start_date = self._parse_date(row[col_map.get("start_date", 1)] if col_map.get("start_date", 1) < len(row) else "")
                        end_date = self._parse_date(row[col_map.get("end_date", 2)] if col_map.get("end_date", 2) < len(row) else "")

                        # Include if absence overlaps with scope date range
                        if start_date and end_date:
                            if not (end_date < date_start or start_date > date_end):
                                absences_data.append({
                                    "driver_id": row[col_map.get("driver_id", 0)] if col_map.get("driver_id", 0) < len(row) else "",
                                    "start_date": row[col_map.get("start_date", 1)] if col_map.get("start_date", 1) < len(row) else "",
                                    "end_date": row[col_map.get("end_date", 2)] if col_map.get("end_date", 2) < len(row) else "",
                                    "type": row[col_map.get("type", 3)] if col_map.get("type", 3) < len(row) else "",
                                })
            except Exception as e:
                logger.warning(f"Error reading absences for fingerprint: {e}")

        return {
            "roster_data": roster_data,
            "drivers_data": drivers_data,
            "absences_data": absences_data,
            "read_at": datetime.now().isoformat(),
            "scope": scope.to_dict(),
        }

    def compute_fingerprint(
        self,
        scoped_values: Dict[str, Any],
        revision: int,
        config_version: str = "v1",
    ) -> str:
        """
        Compute SHA-256 fingerprint of scoped data.

        Fingerprint = SHA256(
            sorted_json(roster_data) +
            sorted_json(drivers_data) +
            sorted_json(absences_data) +
            str(revision) +
            config_version
        )

        Args:
            scoped_values: Dict from read_scoped_ranges
            revision: Sheet revision number
            config_version: Config schema version for migration compatibility

        Returns:
            SHA-256 hex string (64 characters)
        """
        def stable_json(data: Any) -> str:
            """Create deterministic JSON representation."""
            return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)

        parts = [
            stable_json(scoped_values.get("roster_data", [])),
            stable_json(scoped_values.get("drivers_data", [])),
            stable_json(scoped_values.get("absences_data", [])),
            str(revision),
            config_version,
        ]

        combined = "|".join(parts)
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    async def get_current_fingerprint(self, scope: FingerprintScope) -> FingerprintData:
        """
        Get current fingerprint for scope.

        Uses caching to avoid repeated API calls.

        Args:
            scope: FingerprintScope defining what data to include

        Returns:
            FingerprintData with fingerprint, revision, and metadata
        """
        # Check cache first
        cached = _fingerprint_cache.get(self.config.spreadsheet_id, scope)
        if cached:
            return cached

        # Compute fresh fingerprint
        revision = await self.get_sheet_revision()
        scoped_data = await self.read_scoped_ranges(scope)
        fingerprint = self.compute_fingerprint(scoped_data, revision)

        fp_data = FingerprintData(
            fingerprint=fingerprint,
            revision=revision,
            scope=scope,
            computed_at=datetime.now(),
            roster_rows_count=len(scoped_data.get("roster_data", [])),
            drivers_count=len(scoped_data.get("drivers_data", [])),
            absences_count=len(scoped_data.get("absences_data", [])),
        )

        # Cache the result
        _fingerprint_cache.set(self.config.spreadsheet_id, fp_data)

        logger.info(f"Computed fingerprint {fingerprint[:16]}... for scope {scope.scope_type.value}")
        return fp_data

    async def compute_diff_hints(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        scope: FingerprintScope,
    ) -> DiffHints:
        """
        Compute hints about what changed between two states.

        Args:
            old_data: Previous scoped data (from read_scoped_ranges)
            new_data: Current scoped data
            scope: The fingerprint scope used

        Returns:
            DiffHints with change details
        """
        hints = DiffHints(changed_at=datetime.now())

        # Compare roster data
        old_roster = {r["row"]: r for r in old_data.get("roster_data", []) if "row" in r}
        new_roster = {r["row"]: r for r in new_data.get("roster_data", []) if "row" in r}

        if old_roster != new_roster:
            hints.roster_changed = True
            # Find changed rows
            all_rows = set(old_roster.keys()) | set(new_roster.keys())
            for row in all_rows:
                if old_roster.get(row) != new_roster.get(row):
                    hints.changed_roster_rows.append(row)
            hints.changed_roster_rows = sorted(hints.changed_roster_rows)[:10]  # Limit

        # Compare driver data
        old_drivers = sorted(old_data.get("drivers_data", []), key=lambda x: x.get("driver_id", ""))
        new_drivers = sorted(new_data.get("drivers_data", []), key=lambda x: x.get("driver_id", ""))
        hints.drivers_changed = old_drivers != new_drivers

        # Compare absences data
        old_absences = sorted(old_data.get("absences_data", []), key=lambda x: (x.get("driver_id", ""), x.get("start_date", "")))
        new_absences = sorted(new_data.get("absences_data", []), key=lambda x: (x.get("driver_id", ""), x.get("start_date", "")))
        hints.absences_changed = old_absences != new_absences

        return hints

    async def write_assignment(
        self,
        row_index: int,
        driver_id: str,
        driver_name: str,
        status: str = "ASSIGNED",
    ) -> List[str]:
        """
        Write driver assignment to specific row in roster.

        This is an ATOMIC operation for the row - only updates
        driver_id, driver_name, and status columns.

        Args:
            row_index: 1-indexed row number in the roster sheet
            driver_id: Driver ID to assign
            driver_name: Driver name to assign
            status: Status to set (default "ASSIGNED")

        Returns:
            List of cell addresses written (e.g., ["D10", "E10", "H10"])
        """
        spreadsheet = await self._get_spreadsheet()
        worksheet = spreadsheet.worksheet(self.config.roster_tab)

        # Get column letters from config
        driver_id_col = self.config.roster_columns.get("driver_id", "D")
        driver_name_col = self.config.roster_columns.get("driver_name", "E")
        status_col = self.config.roster_columns.get("status", "H")

        cells_written = []

        # Build batch update
        updates = [
            (f"{driver_id_col}{row_index}", driver_id),
            (f"{driver_name_col}{row_index}", driver_name),
            (f"{status_col}{row_index}", status),
        ]

        # Use batch_update for atomicity
        cell_list = []
        for cell_addr, value in updates:
            cell_list.append({
                'range': cell_addr,
                'values': [[value]],
            })
            cells_written.append(cell_addr)

        worksheet.batch_update(cell_list)

        # Invalidate fingerprint cache after write
        _fingerprint_cache.invalidate(self.config.spreadsheet_id)

        logger.info(f"Wrote assignment to row {row_index}: {driver_id} ({driver_name}), cells: {cells_written}")
        return cells_written

    async def validate_sheet_contract(self) -> SheetContractValidation:
        """
        Validate that sheet structure matches expected contract.

        Prevents silent failures when sheet structure changes.
        """
        validation = SheetContractValidation(is_valid=True)

        try:
            spreadsheet = await self._get_spreadsheet()

            # Check required tabs exist
            required_tabs = [
                self.config.roster_tab,
                self.config.drivers_tab,
                self.config.absences_tab,
            ]

            existing_tabs = [ws.title for ws in spreadsheet.worksheets()]

            for tab in required_tabs:
                if tab in existing_tabs:
                    validation.tabs_found.append(tab)
                else:
                    validation.tabs_missing.append(tab)
                    validation.add_error(f"Required tab '{tab}' not found")

            # Check columns in roster tab
            if self.config.roster_tab in existing_tabs:
                roster_ws = spreadsheet.worksheet(self.config.roster_tab)
                headers = roster_ws.row_values(self.config.header_row)

                required_cols = ["date", "driver_id", "status"]
                found_cols = []
                missing_cols = []

                for col_name in required_cols:
                    col_letter = self.config.roster_columns.get(col_name)
                    if col_letter:
                        col_idx = self._col_letter_to_index(col_letter)
                        if col_idx < len(headers) and headers[col_idx]:
                            found_cols.append(col_name)
                        else:
                            missing_cols.append(col_name)
                            validation.add_warning(f"Column '{col_name}' at {col_letter} appears empty in roster")

                validation.columns_found["roster"] = found_cols
                if missing_cols:
                    validation.columns_missing["roster"] = missing_cols

            # Check columns in drivers tab
            if self.config.drivers_tab in existing_tabs:
                drivers_ws = spreadsheet.worksheet(self.config.drivers_tab)
                headers = drivers_ws.row_values(self.config.header_row)

                required_cols = ["driver_id"]
                found_cols = []

                for col_name in required_cols:
                    col_letter = self.config.driver_columns.get(col_name)
                    if col_letter:
                        col_idx = self._col_letter_to_index(col_letter)
                        if col_idx < len(headers) and headers[col_idx]:
                            found_cols.append(col_name)

                validation.columns_found["drivers"] = found_cols

        except Exception as e:
            validation.add_error(f"Failed to validate sheet: {str(e)}")

        if validation.is_valid:
            logger.info("Sheet contract validation passed")
        else:
            logger.warning(f"Sheet contract validation failed: {validation.errors}")

        return validation

    def invalidate_fingerprint_cache(self) -> None:
        """Invalidate fingerprint cache for this spreadsheet."""
        _fingerprint_cache.invalidate(self.config.spreadsheet_id)

    # =========================================================================
    # PARSING HELPERS
    # =========================================================================

    def _build_column_map(
        self,
        headers: List[str],
        config_columns: Dict[str, str],
    ) -> Dict[str, int]:
        """Build column name -> index map."""
        col_map = {}
        for field_name, col_letter in config_columns.items():
            # Convert column letter to index (A=0, B=1, etc.)
            col_idx = self._col_letter_to_index(col_letter)
            col_map[field_name] = col_idx
        return col_map

    def _col_letter_to_index(self, letter: str) -> int:
        """Convert column letter (A, B, ..., Z, AA, AB) to 0-indexed."""
        result = 0
        for char in letter.upper():
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result - 1

    def _parse_roster_row(
        self,
        row: List[str],
        col_map: Dict[str, int],
        row_idx: int,
    ) -> Optional[ShiftAssignment]:
        """Parse a single roster row."""
        def get_val(field: str) -> str:
            idx = col_map.get(field, -1)
            if idx >= 0 and idx < len(row):
                return row[idx].strip()
            return ""

        date_str = get_val("date")
        if not date_str:
            return None

        shift_date = self._parse_date(date_str)
        if not shift_date:
            return None

        shift_start = self._parse_time(get_val("shift_start"))
        shift_end = self._parse_time(get_val("shift_end"))

        if not shift_start or not shift_end:
            return None

        status_str = get_val("status").lower()
        if status_str == "open":
            status = ShiftStatus.OPEN
        elif status_str == "cancelled":
            status = ShiftStatus.CANCELLED
        elif status_str == "pending":
            status = ShiftStatus.PENDING
        else:
            status = ShiftStatus.ASSIGNED

        driver_id = get_val("driver_id")
        if not driver_id and status == ShiftStatus.ASSIGNED:
            status = ShiftStatus.OPEN

        return ShiftAssignment(
            id=f"{shift_date}_{row_idx}",
            shift_date=shift_date,
            shift_start=shift_start,
            shift_end=shift_end,
            driver_id=driver_id or None,
            driver_name=get_val("driver_name") or None,
            route_id=get_val("route") or None,
            zone=get_val("zone") or None,
            status=status,
            notes=get_val("notes") or None,
            row_index=row_idx,
        )

    def _parse_driver_row(
        self,
        row: List[str],
        col_map: Dict[str, int],
    ) -> Optional[DriverState]:
        """Parse a single driver row."""
        def get_val(field: str) -> str:
            idx = col_map.get(field, -1)
            if idx >= 0 and idx < len(row):
                return row[idx].strip()
            return ""

        driver_id = get_val("driver_id")
        if not driver_id:
            return None

        target_hours_str = get_val("target_hours")
        try:
            target_hours = float(target_hours_str) if target_hours_str else 40.0
        except ValueError:
            target_hours = 40.0

        skills_str = get_val("skills")
        skills = [s.strip() for s in skills_str.split(",") if s.strip()] if skills_str else []

        zones_str = get_val("zones")
        zones = [z.strip() for z in zones_str.split(",") if z.strip()] if zones_str else []

        is_active_str = get_val("is_active").lower()
        is_active = is_active_str not in ("false", "0", "no", "inactive")

        return DriverState(
            driver_id=driver_id,
            driver_name=get_val("name") or driver_id,
            week_start=date.today(),  # Will be set properly by service
            target_weekly_hours=target_hours,
            skills=skills,
            home_zones=zones,
            is_active=is_active,
        )

    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, self.config.date_format).date()
        except ValueError:
            # Try common formats
            for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        return None

    def _parse_time(self, time_str: str) -> Optional[time]:
        """Parse time string."""
        if not time_str:
            return None
        try:
            return datetime.strptime(time_str, self.config.time_format).time()
        except ValueError:
            # Try common formats
            for fmt in ["%H:%M", "%H:%M:%S", "%I:%M %p"]:
                try:
                    return datetime.strptime(time_str, fmt).time()
                except ValueError:
                    continue
        return None


# =============================================================================
# MOCK ADAPTER (for testing without Google API)
# =============================================================================

class MockSheetAdapter(SheetAdapterBase):
    """
    Mock adapter for testing without Google Sheets API.

    Stores data in memory. Supports fingerprint testing.
    """

    def __init__(self):
        self.roster: List[ShiftAssignment] = []
        self.drivers: List[DriverState] = []
        self._drivers: List[DriverState] = []  # Alias for test compatibility
        self.absences: Dict[str, List[Dict]] = {}  # driver_id -> absences
        self.proposals_written: List[Proposal] = []
        self.assignments_written: List[Dict[str, Any]] = []  # Track write_assignment calls
        self._revision: int = 1
        self._spreadsheet_id: str = "mock-spreadsheet-id"
        self._fingerprint_cache = FingerprintCache()
        self._contract_errors: List[str] = []

    def set_roster(self, roster: List[ShiftAssignment]) -> None:
        """Set mock roster data."""
        self.roster = roster
        self._revision += 1  # Simulate revision change

    def set_drivers(self, drivers: List[DriverState]) -> None:
        """Set mock driver data."""
        self.drivers = drivers
        self._drivers = drivers  # Keep alias in sync
        self._revision += 1

    def set_absences(self, absences: Dict[str, List[Dict]]) -> None:
        """Set mock absences data."""
        self.absences = absences
        self._revision += 1

    def increment_revision(self) -> None:
        """Manually increment revision (simulate external change)."""
        self._revision += 1

    async def read_roster(
        self,
        date_range: Optional[Tuple[date, date]] = None,
    ) -> List[ShiftAssignment]:
        if date_range:
            return [a for a in self.roster
                    if date_range[0] <= a.shift_date <= date_range[1]]
        return self.roster

    async def read_drivers(self) -> List[DriverState]:
        return self.drivers

    async def detect_open_shifts(
        self,
        roster: List[ShiftAssignment],
    ) -> List[OpenShift]:
        open_shifts = []
        for assignment in roster:
            if assignment.status == ShiftStatus.OPEN or not assignment.driver_id:
                open_shifts.append(OpenShift(
                    id=f"open_{assignment.id}",
                    shift_date=assignment.shift_date,
                    shift_start=assignment.shift_start,
                    shift_end=assignment.shift_end,
                    route_id=assignment.route_id,
                    zone=assignment.zone,
                    row_index=assignment.row_index,
                ))
        return open_shifts

    async def write_proposals(self, proposals: List[Proposal]) -> int:
        self.proposals_written.extend(proposals)
        return len(proposals)

    # =========================================================================
    # FINGERPRINT METHODS (Mock Implementation)
    # =========================================================================

    async def get_sheet_revision(self) -> int:
        """Return mock revision number."""
        return self._revision

    async def read_scoped_ranges(self, scope: FingerprintScope) -> Dict[str, Any]:
        """Read mock data within scope."""
        date_start, date_end = scope.get_date_range()

        # Filter roster by date range
        roster_data = []
        for a in self.roster:
            if date_start <= a.shift_date <= date_end:
                roster_data.append({
                    "row": a.row_index or 0,
                    "date": a.shift_date.isoformat(),
                    "driver_id": a.driver_id or "",
                    "status": a.status.value if a.status else "",
                    "shift_start": a.shift_start.isoformat() if a.shift_start else "",
                    "shift_end": a.shift_end.isoformat() if a.shift_end else "",
                })

        # Driver data
        drivers_data = []
        for d in self.drivers:
            drivers_data.append({
                "driver_id": d.driver_id,
                "target_hours": str(d.target_weekly_hours),
                "skills": ",".join(d.skills),
                "zones": ",".join(d.home_zones),
                "is_active": "true" if d.is_active else "false",
            })

        # Absences data (filtered by date range)
        absences_data = []
        if scope.include_absences:
            for driver_id, driver_absences in self.absences.items():
                for absence in driver_absences:
                    start = absence.get("start_date")
                    end = absence.get("end_date")
                    if isinstance(start, str):
                        start = date.fromisoformat(start)
                    if isinstance(end, str):
                        end = date.fromisoformat(end)
                    if start and end:
                        if not (end < date_start or start > date_end):
                            absences_data.append({
                                "driver_id": driver_id,
                                "start_date": start.isoformat() if isinstance(start, date) else str(start),
                                "end_date": end.isoformat() if isinstance(end, date) else str(end),
                                "type": absence.get("type", "unknown"),
                            })

        return {
            "roster_data": roster_data,
            "drivers_data": drivers_data,
            "absences_data": absences_data,
            "read_at": datetime.now().isoformat(),
            "scope": scope.to_dict(),
        }

    def compute_fingerprint(
        self,
        scoped_values: Dict[str, Any],
        revision: int,
        config_version: str = "v1",
    ) -> str:
        """Compute fingerprint using same algorithm as real adapter."""
        def stable_json(data: Any) -> str:
            return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)

        parts = [
            stable_json(scoped_values.get("roster_data", [])),
            stable_json(scoped_values.get("drivers_data", [])),
            stable_json(scoped_values.get("absences_data", [])),
            str(revision),
            config_version,
        ]

        combined = "|".join(parts)
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    async def get_current_fingerprint(self, scope: FingerprintScope) -> FingerprintData:
        """Get current fingerprint for scope."""
        revision = await self.get_sheet_revision()
        scoped_data = await self.read_scoped_ranges(scope)
        fingerprint = self.compute_fingerprint(scoped_data, revision)

        return FingerprintData(
            fingerprint=fingerprint,
            revision=revision,
            scope=scope,
            computed_at=datetime.now(),
            roster_rows_count=len(scoped_data.get("roster_data", [])),
            drivers_count=len(scoped_data.get("drivers_data", [])),
            absences_count=len(scoped_data.get("absences_data", [])),
        )

    async def compute_diff_hints(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        scope: FingerprintScope,
    ) -> DiffHints:
        """Compute diff hints between two states."""
        hints = DiffHints(changed_at=datetime.now())

        old_roster = {r.get("row", i): r for i, r in enumerate(old_data.get("roster_data", []))}
        new_roster = {r.get("row", i): r for i, r in enumerate(new_data.get("roster_data", []))}

        if old_roster != new_roster:
            hints.roster_changed = True
            all_rows = set(old_roster.keys()) | set(new_roster.keys())
            for row in all_rows:
                if old_roster.get(row) != new_roster.get(row):
                    hints.changed_roster_rows.append(row)
            hints.changed_roster_rows = sorted(hints.changed_roster_rows)[:10]

        hints.drivers_changed = old_data.get("drivers_data", []) != new_data.get("drivers_data", [])
        hints.absences_changed = old_data.get("absences_data", []) != new_data.get("absences_data", [])

        return hints

    async def write_assignment(
        self,
        row_index: int,
        driver_id: str,
        driver_name: str,
        status: str = "ASSIGNED",
    ) -> List[str]:
        """Mock write assignment - updates roster and tracks writes."""
        # Track the write
        self.assignments_written.append({
            "row_index": row_index,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "status": status,
            "written_at": datetime.now().isoformat(),
        })

        # Update the roster data
        for assignment in self.roster:
            if assignment.row_index == row_index:
                assignment.driver_id = driver_id
                assignment.driver_name = driver_name
                assignment.status = ShiftStatus.ASSIGNED
                break

        # Increment revision to simulate change
        self._revision += 1

        # Return mock cell addresses
        return [f"D{row_index}", f"E{row_index}", f"H{row_index}"]

    async def validate_sheet_contract(self) -> SheetContractValidation:
        """Mock contract validation - always passes unless configured otherwise."""
        validation = SheetContractValidation(is_valid=True)

        # Mock tabs found
        validation.tabs_found = ["Dienstplan", "Fahrer", "Abwesenheiten"]
        validation.columns_found = {
            "roster": ["date", "driver_id", "status"],
            "drivers": ["driver_id"],
        }

        # Can be configured to fail for testing
        if hasattr(self, "_contract_errors") and self._contract_errors:
            for error in self._contract_errors:
                validation.add_error(error)

        return validation

    def set_contract_errors(self, errors: List[str]) -> None:
        """Configure mock to return contract validation errors."""
        self._contract_errors = errors

    def invalidate_fingerprint_cache(self) -> None:
        """Mock cache invalidation - just clears internal cache."""
        self._fingerprint_cache.clear()
