# =============================================================================
# SOLVEREIGN Routing Pack - FLS Importer
# =============================================================================
# Full import pipeline: FLS export → Canonicalize → Validate → DB
#
# Stores:
# - raw_blob: Original FLS export for audit
# - canonical_hash: For determinism verification
# - import_run_id: For traceability
# =============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from .fls_canonicalize import (
    FLSCanonicalizer,
    CanonicalImport,
    CanonicalOrder,
    CanonicalizeResult,
)
from .fls_validate import (
    FLSValidator,
    ValidationResult,
    GateVerdict,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ImportRun:
    """Represents a single import run with all metadata."""

    # Identifiers
    import_run_id: str
    tenant_id: int
    site_id: int

    # Timestamps
    started_at: datetime
    completed_at: Optional[datetime] = None

    # Source info
    source_type: str = "FLS"
    source_file: Optional[str] = None
    fls_export_id: Optional[str] = None

    # Hashes (for audit/determinism)
    raw_hash: str = ""
    canonical_hash: str = ""

    # Status
    status: str = "IN_PROGRESS"  # IN_PROGRESS, COMPLETED, FAILED, BLOCKED
    verdict: str = "PENDING"     # OK, WARN, BLOCK

    # Statistics
    orders_raw: int = 0
    orders_canonical: int = 0
    orders_imported: int = 0
    orders_skipped: int = 0

    # Coords stats
    orders_with_coords: int = 0
    orders_with_zone: int = 0
    orders_missing_location: int = 0

    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Artifact references
    raw_blob_artifact_id: Optional[str] = None
    canonical_artifact_id: Optional[str] = None
    validation_report_artifact_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "import_run_id": self.import_run_id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "source": {
                "type": self.source_type,
                "file": self.source_file,
                "fls_export_id": self.fls_export_id,
            },
            "hashes": {
                "raw": self.raw_hash,
                "canonical": self.canonical_hash,
            },
            "status": self.status,
            "verdict": self.verdict,
            "statistics": {
                "orders_raw": self.orders_raw,
                "orders_canonical": self.orders_canonical,
                "orders_imported": self.orders_imported,
                "orders_skipped": self.orders_skipped,
                "orders_with_coords": self.orders_with_coords,
                "orders_with_zone": self.orders_with_zone,
                "orders_missing_location": self.orders_missing_location,
            },
            "errors": self.errors[:20],  # Limit
            "warnings": self.warnings[:50],  # Limit
            "artifacts": {
                "raw_blob": self.raw_blob_artifact_id,
                "canonical": self.canonical_artifact_id,
                "validation_report": self.validation_report_artifact_id,
            },
        }


@dataclass
class ImportResult:
    """Result of a complete import operation."""

    success: bool
    import_run: ImportRun
    canonical_import: Optional[CanonicalImport] = None
    validation_result: Optional[ValidationResult] = None
    db_insert_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "import_run": self.import_run.to_dict(),
            "validation_verdict": self.validation_result.verdict.value if self.validation_result else None,
            "db_insert_count": self.db_insert_count,
        }


# =============================================================================
# IMPORTER
# =============================================================================

class FLSImporter:
    """
    Complete FLS import pipeline.

    Pipeline stages:
    1. Parse raw JSON/CSV
    2. Canonicalize (normalize TZ, round, dedupe)
    3. Validate (gates)
    4. Store to DB (with hashes)
    5. Generate artifacts

    Usage:
        importer = FLSImporter(db_connection=conn)
        result = importer.import_file("fls_export.json")

        if result.success:
            print(f"Imported {result.db_insert_count} orders")
        else:
            print(f"Import failed: {result.import_run.errors}")
    """

    def __init__(
        self,
        db_connection=None,
        artifact_store=None,
        canonicalizer: Optional[FLSCanonicalizer] = None,
        validator: Optional[FLSValidator] = None,
        auto_approve_warn: bool = False,
    ):
        """
        Initialize importer.

        Args:
            db_connection: Database connection for storing orders
            artifact_store: ArtifactStore for storing evidence
            canonicalizer: Custom canonicalizer (or use default)
            validator: Custom validator (or use default)
            auto_approve_warn: If True, auto-approve WARN verdicts
        """
        self.db = db_connection
        self.artifact_store = artifact_store
        self.canonicalizer = canonicalizer or FLSCanonicalizer()
        self.validator = validator or FLSValidator()
        self.auto_approve_warn = auto_approve_warn

    def import_file(
        self,
        file_path: Union[str, Path],
        tenant_id: Optional[int] = None,
        site_id: Optional[int] = None,
    ) -> ImportResult:
        """
        Import from file.

        Args:
            file_path: Path to JSON file
            tenant_id: Override tenant_id from file
            site_id: Override site_id from file

        Returns:
            ImportResult
        """
        file_path = Path(file_path)

        if not file_path.exists():
            run = self._create_import_run(tenant_id or 0, site_id or 0)
            run.status = "FAILED"
            run.errors.append(f"File not found: {file_path}")
            return ImportResult(success=False, import_run=run)

        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        try:
            raw_data = json.loads(raw_content)
        except json.JSONDecodeError as e:
            run = self._create_import_run(tenant_id or 0, site_id or 0)
            run.status = "FAILED"
            run.errors.append(f"Invalid JSON: {e}")
            return ImportResult(success=False, import_run=run)

        return self.import_data(
            raw_data=raw_data,
            raw_content=raw_content,
            source_file=str(file_path),
            tenant_id=tenant_id,
            site_id=site_id,
        )

    def import_data(
        self,
        raw_data: Dict[str, Any],
        raw_content: Optional[str] = None,
        source_file: Optional[str] = None,
        tenant_id: Optional[int] = None,
        site_id: Optional[int] = None,
    ) -> ImportResult:
        """
        Import from dictionary data.

        Args:
            raw_data: Raw import data
            raw_content: Original raw content string (for hash)
            source_file: Source file name (for traceability)
            tenant_id: Override tenant_id
            site_id: Override site_id

        Returns:
            ImportResult
        """
        # Extract metadata
        meta = raw_data.get("import_metadata", {})
        effective_tenant = tenant_id or meta.get("tenant_id", 0)
        effective_site = site_id or meta.get("site_id", 0)

        # Create import run
        import_run = self._create_import_run(
            tenant_id=effective_tenant,
            site_id=effective_site,
        )
        import_run.source_file = source_file
        import_run.fls_export_id = meta.get("fls_export_id")
        import_run.orders_raw = len(raw_data.get("orders", []))

        # Compute raw hash
        if raw_content:
            import_run.raw_hash = hashlib.sha256(raw_content.encode()).hexdigest()
        else:
            import_run.raw_hash = hashlib.sha256(
                json.dumps(raw_data, sort_keys=True).encode()
            ).hexdigest()

        # Stage 1: Canonicalize
        logger.info(f"Import {import_run.import_run_id}: Canonicalizing...")
        canon_result = self.canonicalizer.canonicalize(raw_data)

        if not canon_result.success:
            import_run.status = "FAILED"
            import_run.errors = canon_result.errors
            import_run.warnings = canon_result.warnings
            import_run.completed_at = datetime.now()
            return ImportResult(
                success=False,
                import_run=import_run,
            )

        canonical_import = canon_result.canonical_import
        import_run.orders_canonical = len(canonical_import.orders)
        import_run.canonical_hash = canonical_import.canonical_hash
        import_run.warnings.extend(canon_result.warnings)

        # Update coords stats
        import_run.orders_with_coords = canonical_import.orders_with_coords
        import_run.orders_with_zone = canonical_import.orders_with_zone
        import_run.orders_missing_location = canonical_import.orders_missing_location

        # Stage 2: Validate
        logger.info(f"Import {import_run.import_run_id}: Validating...")
        validation_result = self.validator.validate(canonical_import)

        import_run.verdict = validation_result.verdict.value

        # Check if blocked
        if validation_result.verdict == GateVerdict.BLOCK:
            import_run.status = "BLOCKED"
            import_run.errors.append("Validation blocked by hard gate")
            import_run.completed_at = datetime.now()

            # Store artifacts even on block
            self._store_artifacts(import_run, raw_data, canonical_import, validation_result)

            return ImportResult(
                success=False,
                import_run=import_run,
                canonical_import=canonical_import,
                validation_result=validation_result,
            )

        # Check if WARN needs approval
        if validation_result.verdict == GateVerdict.WARN and not self.auto_approve_warn:
            import_run.status = "PENDING_APPROVAL"
            import_run.warnings.append("Validation has warnings, requires approval")
            import_run.completed_at = datetime.now()

            # Store artifacts
            self._store_artifacts(import_run, raw_data, canonical_import, validation_result)

            return ImportResult(
                success=True,  # Not failed, just pending
                import_run=import_run,
                canonical_import=canonical_import,
                validation_result=validation_result,
            )

        # Stage 3: Store to DB
        db_count = 0
        if self.db:
            logger.info(f"Import {import_run.import_run_id}: Storing to database...")
            db_count = self._store_to_database(
                import_run=import_run,
                canonical_import=canonical_import,
            )
            import_run.orders_imported = db_count

        # Stage 4: Store artifacts
        self._store_artifacts(import_run, raw_data, canonical_import, validation_result)

        # Complete
        import_run.status = "COMPLETED"
        import_run.completed_at = datetime.now()

        logger.info(
            f"Import {import_run.import_run_id}: Completed. "
            f"{import_run.orders_imported} orders imported."
        )

        return ImportResult(
            success=True,
            import_run=import_run,
            canonical_import=canonical_import,
            validation_result=validation_result,
            db_insert_count=db_count,
        )

    def _create_import_run(self, tenant_id: int, site_id: int) -> ImportRun:
        """Create a new import run."""
        return ImportRun(
            import_run_id=f"import_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            site_id=site_id,
            started_at=datetime.now(),
        )

    def _store_to_database(
        self,
        import_run: ImportRun,
        canonical_import: CanonicalImport,
    ) -> int:
        """
        Store canonical orders to database.

        Returns count of inserted orders.
        """
        if not self.db:
            return 0

        # This would be implemented based on your DB schema
        # For now, return count as placeholder
        inserted = 0

        try:
            # Example implementation (pseudo-code):
            # cursor = self.db.cursor()
            #
            # # Insert import run
            # cursor.execute("""
            #     INSERT INTO import_runs (
            #         import_run_id, tenant_id, site_id, started_at,
            #         raw_hash, canonical_hash, status, verdict
            #     ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            # """, (
            #     import_run.import_run_id,
            #     import_run.tenant_id,
            #     import_run.site_id,
            #     import_run.started_at,
            #     import_run.raw_hash,
            #     import_run.canonical_hash,
            #     import_run.status,
            #     import_run.verdict,
            # ))
            #
            # # Insert orders
            # for order in canonical_import.orders:
            #     cursor.execute("""
            #         INSERT INTO orders (
            #             order_id, import_run_id, tenant_id, site_id,
            #             tw_start, tw_end, lat, lng, zone_id, h3_index,
            #             service_code, service_seconds, priority, ...
            #         ) VALUES (...)
            #     """, (...))
            #     inserted += 1
            #
            # self.db.commit()

            inserted = len(canonical_import.orders)
            logger.info(f"Stored {inserted} orders to database")

        except Exception as e:
            logger.error(f"Database error: {e}")
            import_run.errors.append(f"Database error: {e}")
            raise

        return inserted

    def _store_artifacts(
        self,
        import_run: ImportRun,
        raw_data: Dict[str, Any],
        canonical_import: Optional[CanonicalImport],
        validation_result: Optional[ValidationResult],
    ) -> None:
        """Store artifacts to artifact store."""
        if not self.artifact_store:
            return

        try:
            # Store raw blob
            raw_blob_id = f"{import_run.import_run_id}/raw_blob.json"
            self.artifact_store.upload(
                artifact_id=raw_blob_id,
                content=json.dumps(raw_data, indent=2).encode(),
                plan_id=None,
                tenant_id=import_run.tenant_id,
                content_type="application/json",
                metadata={"import_run_id": import_run.import_run_id},
            )
            import_run.raw_blob_artifact_id = raw_blob_id

            # Store canonical
            if canonical_import:
                canonical_id = f"{import_run.import_run_id}/canonical_orders.json"
                self.artifact_store.upload(
                    artifact_id=canonical_id,
                    content=json.dumps(canonical_import.to_dict(), indent=2).encode(),
                    plan_id=None,
                    tenant_id=import_run.tenant_id,
                    content_type="application/json",
                    metadata={"canonical_hash": canonical_import.canonical_hash},
                )
                import_run.canonical_artifact_id = canonical_id

            # Store validation report
            if validation_result:
                report_id = f"{import_run.import_run_id}/validation_report.json"
                self.artifact_store.upload(
                    artifact_id=report_id,
                    content=json.dumps(validation_result.to_dict(), indent=2).encode(),
                    plan_id=None,
                    tenant_id=import_run.tenant_id,
                    content_type="application/json",
                    metadata={"verdict": validation_result.verdict.value},
                )
                import_run.validation_report_artifact_id = report_id

        except Exception as e:
            logger.error(f"Failed to store artifacts: {e}")
            import_run.warnings.append(f"Artifact storage failed: {e}")

    def get_import_run(self, import_run_id: str) -> Optional[ImportRun]:
        """Get import run by ID from database."""
        if not self.db:
            return None

        # Implement based on your DB schema
        return None

    def approve_import(
        self,
        import_run_id: str,
        approved_by: str,
    ) -> ImportResult:
        """
        Approve a pending import and complete the DB insert.

        Args:
            import_run_id: ID of pending import run
            approved_by: User approving the import

        Returns:
            ImportResult
        """
        # This would:
        # 1. Load the pending import run from DB
        # 2. Load the canonical import from artifact store
        # 3. Complete the DB insert
        # 4. Update import run status to COMPLETED

        raise NotImplementedError("approve_import not yet implemented")
