"""
SOLVEREIGN V4.6 - Daily Plan Importer + Verifier Service
==========================================================

Service for importing daily plans from Google Sheets and verifying
driver assignments before sending WhatsApp DMs.

Key Principle: DAILY plans from Google Sheets are trusted input.
               Verification ensures all driver references are valid
               and consent exists before DM delivery.

Verification Rules:
- Every driver assignment must resolve to a known driver_id
- Driver must have consent_whatsapp = TRUE to receive DMs
- Duplicate phone numbers flagged
- Unknown drivers flagged

Usage:
    importer = DailyPlanImporter(tenant_id)
    plan_id = await importer.create_plan(date, source_url)
    await importer.import_rows(plan_id, rows)
    report_id = await importer.verify_plan(plan_id)
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, time, datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ImportRow:
    """Single row from Google Sheets import."""
    row_number: int
    driver_name: str
    driver_id: Optional[str] = None  # External ID from sheet
    phone: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    tour_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class VerificationError:
    """Single verification error."""
    assignment_id: UUID
    row_number: int
    driver_name: str
    error_code: str
    error_message: str
    is_blocking: bool = True


@dataclass
class VerificationWarning:
    """Single verification warning (non-blocking)."""
    assignment_id: UUID
    row_number: int
    driver_name: str
    warning_code: str
    warning_message: str


@dataclass
class VerificationReport:
    """Complete verification report for a daily plan."""
    report_id: UUID
    daily_plan_id: UUID
    plan_date: date
    generated_at: datetime

    # Counts
    total_assignments: int = 0
    verified_count: int = 0
    failed_count: int = 0
    warning_count: int = 0
    dm_eligible_count: int = 0
    dm_blocked_count: int = 0

    # Error breakdown
    missing_driver_id_count: int = 0
    unknown_driver_count: int = 0
    duplicate_phone_count: int = 0
    missing_consent_count: int = 0
    invalid_phone_count: int = 0

    # Details
    errors: List[VerificationError] = field(default_factory=list)
    warnings: List[VerificationWarning] = field(default_factory=list)

    # Recommendation
    can_publish: bool = False
    blocking_issues: List[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return self.failed_count > 0

    @property
    def has_blocking_issues(self) -> bool:
        return len(self.blocking_issues) > 0


# =============================================================================
# DAILY PLAN IMPORTER SERVICE
# =============================================================================

class DailyPlanImporter:
    """
    Service for importing and verifying daily plans.

    Handles:
    - Plan creation from Google Sheets
    - Row-by-row import with validation
    - Full plan verification
    - DM eligibility checking
    """

    def __init__(self, conn: psycopg.Connection, tenant_id: int):
        """
        Initialize importer with database connection.

        Args:
            conn: Database connection
            tenant_id: Tenant ID for RLS context
        """
        self.conn = conn
        self.tenant_id = tenant_id

    def _set_rls_context(self, cur):
        """Set RLS context for tenant isolation."""
        cur.execute("SELECT set_config('app.current_tenant_id', %s, TRUE)", (str(self.tenant_id),))

    async def create_plan(
        self,
        plan_date: date,
        source_url: Optional[str] = None,
        source_sheet_name: Optional[str] = None,
        source_range: Optional[str] = None,
        site_id: Optional[UUID] = None,
        shift_type: str = "REGULAR",
        imported_by: Optional[str] = None
    ) -> UUID:
        """
        Create a new daily plan.

        Args:
            plan_date: Date of the plan
            source_url: Google Sheets URL
            source_sheet_name: Sheet tab name
            source_range: Cell range
            site_id: Site UUID
            shift_type: REGULAR, EARLY, LATE, NIGHT, SPLIT
            imported_by: Email of importer

        Returns:
            UUID of created plan
        """
        # Calculate import hash for deduplication
        import_hash = hashlib.sha256(
            f"{self.tenant_id}:{plan_date}:{source_url or ''}:{shift_type}".encode()
        ).hexdigest()

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                INSERT INTO masterdata.daily_plans (
                    tenant_id, site_id, plan_date, shift_type,
                    source_type, source_url, source_sheet_name, source_range,
                    import_hash, imported_by, status
                ) VALUES (
                    %s, %s, %s, %s,
                    'GOOGLE_SHEETS', %s, %s, %s,
                    %s, %s, 'DRAFT'
                )
                ON CONFLICT (tenant_id, site_id, plan_date, shift_type)
                DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    source_sheet_name = EXCLUDED.source_sheet_name,
                    source_range = EXCLUDED.source_range,
                    import_hash = EXCLUDED.import_hash,
                    imported_by = EXCLUDED.imported_by,
                    imported_at = NOW(),
                    status = 'DRAFT',
                    updated_at = NOW()
                RETURNING id
            """, (
                self.tenant_id,
                str(site_id) if site_id else None,
                plan_date,
                shift_type,
                source_url,
                source_sheet_name,
                source_range,
                import_hash,
                imported_by
            ))

            plan_id = cur.fetchone()[0]
            self.conn.commit()

            logger.info(f"Created daily plan {plan_id} for {plan_date}")
            return plan_id

    async def import_row(self, plan_id: UUID, row: ImportRow) -> UUID:
        """
        Import a single row into the daily plan.

        Args:
            plan_id: Daily plan UUID
            row: Import row data

        Returns:
            UUID of created assignment
        """
        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT masterdata.import_daily_plan_row(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                str(plan_id),
                row.row_number,
                row.driver_name,
                row.driver_id,
                row.phone,
                row.shift_start,
                row.shift_end,
                row.tour_id,
                row.vehicle_id,
                row.notes
            ))

            assignment_id = cur.fetchone()[0]
            return assignment_id

    async def import_rows(self, plan_id: UUID, rows: List[ImportRow]) -> int:
        """
        Import multiple rows into the daily plan.

        Args:
            plan_id: Daily plan UUID
            rows: List of import rows

        Returns:
            Number of rows imported
        """
        imported = 0

        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            for row in rows:
                try:
                    cur.execute("""
                        SELECT masterdata.import_daily_plan_row(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        str(plan_id),
                        row.row_number,
                        row.driver_name,
                        row.driver_id,
                        row.phone,
                        row.shift_start,
                        row.shift_end,
                        row.tour_id,
                        row.vehicle_id,
                        row.notes
                    ))
                    imported += 1
                except Exception as e:
                    logger.warning(f"Failed to import row {row.row_number}: {e}")

            self.conn.commit()

        logger.info(f"Imported {imported}/{len(rows)} rows into plan {plan_id}")
        return imported

    async def verify_plan(self, plan_id: UUID, verified_by: Optional[str] = None) -> VerificationReport:
        """
        Verify all assignments in a daily plan.

        Runs the database verification function and builds a detailed report.

        Args:
            plan_id: Daily plan UUID
            verified_by: Email of verifier

        Returns:
            VerificationReport with detailed results
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            # Run database verification
            cur.execute("""
                SELECT masterdata.verify_daily_plan(%s, %s)
            """, (str(plan_id), verified_by))

            report_id = cur.fetchone()["verify_daily_plan"]
            self.conn.commit()

            # Fetch the generated report
            cur.execute("""
                SELECT * FROM masterdata.verification_reports
                WHERE id = %s
            """, (str(report_id),))

            report_data = cur.fetchone()

            # Fetch plan info
            cur.execute("""
                SELECT plan_date FROM masterdata.daily_plans
                WHERE id = %s
            """, (str(plan_id),))

            plan_data = cur.fetchone()

            # Build verification report
            report = VerificationReport(
                report_id=report_id,
                daily_plan_id=plan_id,
                plan_date=plan_data["plan_date"],
                generated_at=report_data["generated_at"],
                total_assignments=report_data["total_assignments"],
                verified_count=report_data["verified_count"],
                failed_count=report_data["failed_count"],
                warning_count=report_data["warning_count"],
                dm_eligible_count=report_data["dm_eligible_count"],
                dm_blocked_count=report_data["dm_blocked_count"],
                missing_driver_id_count=report_data["missing_driver_id_count"],
                unknown_driver_count=report_data["unknown_driver_count"],
                duplicate_phone_count=report_data["duplicate_phone_count"],
                missing_consent_count=report_data["missing_consent_count"],
                invalid_phone_count=report_data["invalid_phone_count"],
                can_publish=report_data["can_publish"],
                blocking_issues=report_data["blocking_issues"] or []
            )

            # Parse detailed results
            details = report_data.get("details", [])
            if details:
                for item in details:
                    if isinstance(item, dict):
                        errors = item.get("errors", [])
                        warnings = item.get("warnings", [])

                        for error in errors:
                            report.errors.append(VerificationError(
                                assignment_id=UUID(item.get("assignment_id", "")),
                                row_number=item.get("row_number", 0),
                                driver_name=item.get("driver_name", "Unknown"),
                                error_code=error,
                                error_message=self._get_error_message(error),
                                is_blocking=error not in ("MISSING_CONSENT",)
                            ))

                        for warning in warnings:
                            report.warnings.append(VerificationWarning(
                                assignment_id=UUID(item.get("assignment_id", "")),
                                row_number=item.get("row_number", 0),
                                driver_name=item.get("driver_name", "Unknown"),
                                warning_code=warning,
                                warning_message=self._get_warning_message(warning)
                            ))

            logger.info(
                f"Verified plan {plan_id}: {report.verified_count}/{report.total_assignments} verified, "
                f"{report.dm_eligible_count} DM eligible, can_publish={report.can_publish}"
            )

            return report

    def _get_error_message(self, error_code: str) -> str:
        """Get human-readable error message."""
        messages = {
            "MISSING_DRIVER_ID": "No driver ID provided in source data",
            "DRIVER_NOT_IN_MDL": "Driver not found in master data (unknown driver)",
            "NO_DRIVER_CONTACT": "No contact record for this driver",
            "NO_PHONE_NUMBER": "No phone number available for driver",
            "INVALID_PHONE_FORMAT": "Phone number is not valid E.164 format",
        }
        return messages.get(error_code, f"Unknown error: {error_code}")

    def _get_warning_message(self, warning_code: str) -> str:
        """Get human-readable warning message."""
        messages = {
            "MISSING_CONSENT": "Driver has not given WhatsApp consent",
            "OPTED_OUT": "Driver has opted out of WhatsApp messages",
            "DUPLICATE_PHONE": "Phone number appears multiple times",
        }
        return messages.get(warning_code, f"Unknown warning: {warning_code}")

    async def get_dm_eligibility(self, plan_id: UUID) -> List[Dict[str, Any]]:
        """
        Get DM eligibility status for all assignments in a plan.

        Args:
            plan_id: Daily plan UUID

        Returns:
            List of eligibility results
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT * FROM masterdata.check_dm_eligibility_bulk(%s)
            """, (str(plan_id),))

            rows = cur.fetchall()

            return [
                {
                    "assignment_id": row["assignment_id"],
                    "driver_id": row["driver_id"],
                    "driver_name": row["driver_name"],
                    "dm_eligible": row["dm_eligible"],
                    "block_reason": row["block_reason"]
                }
                for row in rows
            ]

    async def get_contactable_for_plan(self, plan_id: UUID) -> List[Dict[str, Any]]:
        """
        Get only drivers who can be contacted from a plan.

        Args:
            plan_id: Daily plan UUID

        Returns:
            List of contactable drivers with phone numbers
        """
        eligibility = await self.get_dm_eligibility(plan_id)
        return [d for d in eligibility if d["dm_eligible"]]


# =============================================================================
# PLAN VERIFIER API
# =============================================================================

class PlanVerifier:
    """
    Standalone verifier for checking plan readiness.

    Use this for pre-publish checks and DM batch verification.
    """

    def __init__(self, conn: psycopg.Connection, tenant_id: int):
        self.conn = conn
        self.tenant_id = tenant_id

    def _set_rls_context(self, cur):
        cur.execute("SELECT set_config('app.current_tenant_id', %s, TRUE)", (str(self.tenant_id),))

    async def verify_single_driver(self, driver_id: UUID) -> Dict[str, Any]:
        """
        Verify a single driver can receive DMs.

        Args:
            driver_id: Driver UUID

        Returns:
            Verification result dict
        """
        with self.conn.cursor() as cur:
            self._set_rls_context(cur)

            cur.execute("""
                SELECT masterdata.verify_contact_for_dm(%s, %s)
            """, (self.tenant_id, str(driver_id)))

            result = cur.fetchone()[0]
            return result

    async def verify_batch(self, driver_ids: List[UUID]) -> Dict[str, Any]:
        """
        Verify multiple drivers for DM eligibility.

        Args:
            driver_ids: List of driver UUIDs

        Returns:
            Summary with eligible/blocked counts
        """
        results = []
        eligible_count = 0
        blocked_count = 0
        blocked_reasons: Dict[str, int] = {}

        for driver_id in driver_ids:
            result = await self.verify_single_driver(driver_id)
            results.append(result)

            if result.get("can_send"):
                eligible_count += 1
            else:
                blocked_count += 1
                for error in result.get("errors", []):
                    blocked_reasons[error] = blocked_reasons.get(error, 0) + 1

        return {
            "total": len(driver_ids),
            "eligible_count": eligible_count,
            "blocked_count": blocked_count,
            "blocked_reasons": blocked_reasons,
            "can_proceed": blocked_count == 0,
            "details": results
        }

    async def check_consent_coverage(self, site_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Check overall consent coverage for a tenant/site.

        Args:
            site_id: Optional site filter

        Returns:
            Coverage statistics
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            self._set_rls_context(cur)

            # Get total drivers with contacts
            site_filter = "AND site_id = %s" if site_id else ""
            params = [self.tenant_id]
            if site_id:
                params.append(str(site_id))

            cur.execute(f"""
                SELECT
                    COUNT(*) as total_contacts,
                    COUNT(*) FILTER (WHERE consent_whatsapp = TRUE) as consented,
                    COUNT(*) FILTER (WHERE consent_whatsapp = FALSE) as not_consented,
                    COUNT(*) FILTER (WHERE opt_out_at IS NOT NULL) as opted_out,
                    COUNT(*) FILTER (WHERE status = 'active') as active,
                    COUNT(*) FILTER (WHERE status = 'inactive') as inactive,
                    COUNT(*) FILTER (WHERE status = 'blocked') as blocked
                FROM masterdata.driver_contacts
                WHERE tenant_id = %s {site_filter}
            """, params)

            stats = cur.fetchone()

            total = stats["total_contacts"]
            consented = stats["consented"]

            return {
                "total_contacts": total,
                "consented": consented,
                "not_consented": stats["not_consented"],
                "opted_out": stats["opted_out"],
                "active": stats["active"],
                "inactive": stats["inactive"],
                "blocked": stats["blocked"],
                "consent_rate": round(consented / total * 100, 1) if total > 0 else 0,
                "dm_ready_rate": round(
                    (consented - stats["opted_out"]) / total * 100, 1
                ) if total > 0 else 0
            }
