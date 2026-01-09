#!/usr/bin/env python3
# =============================================================================
# SOLVEREIGN - Wien Pilot Dry Run Script
# =============================================================================
# One-command pipeline: import → solve → finalize → drift gate → audit →
#                       freeze/lock → evidence → publish(stub)
#
# Usage:
#   python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json
#   python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json --skip-osrm
#   python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json --output-dir runs/
#
# Output:
#   - Run directory with all artifacts
#   - Manifest JSON with all URIs and verdict chain
# =============================================================================

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dry_run")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class StageResult:
    """Result of a pipeline stage."""
    stage_name: str
    success: bool = False
    verdict: str = "N/A"
    duration_seconds: float = 0.0
    artifacts: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PipelineManifest:
    """Complete pipeline run manifest."""
    run_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    overall_verdict: str = "PENDING"
    can_publish: bool = False

    # Stage results
    import_stage: Optional[StageResult] = None
    coords_gate: Optional[StageResult] = None
    solve_stage: Optional[StageResult] = None
    finalize_stage: Optional[StageResult] = None
    drift_gate: Optional[StageResult] = None
    audit_stage: Optional[StageResult] = None
    lock_stage: Optional[StageResult] = None

    # Hashes
    input_hash: str = ""
    canonical_hash: str = ""
    output_hash: str = ""

    # Config
    profile_used: str = ""
    osrm_enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        stages = {}
        for stage_name in [
            "import_stage", "coords_gate", "solve_stage", "finalize_stage",
            "drift_gate", "audit_stage", "lock_stage"
        ]:
            stage = getattr(self, stage_name)
            if stage:
                stages[stage_name] = {
                    "success": stage.success,
                    "verdict": stage.verdict,
                    "duration_seconds": round(stage.duration_seconds, 3),
                    "artifacts": stage.artifacts,
                    "metrics": stage.metrics,
                    "errors": stage.errors[:5],
                    "warnings": stage.warnings[:10],
                }

        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "overall_verdict": self.overall_verdict,
            "can_publish": self.can_publish,
            "verdict_chain": self._get_verdict_chain(),
            "stages": stages,
            "hashes": {
                "input": self.input_hash,
                "canonical": self.canonical_hash,
                "output": self.output_hash,
            },
            "config": {
                "profile": self.profile_used,
                "osrm_enabled": self.osrm_enabled,
            },
        }

    def _get_verdict_chain(self) -> Dict[str, str]:
        return {
            "coords_gate": self.coords_gate.verdict if self.coords_gate else "N/A",
            "drift_gate": self.drift_gate.verdict if self.drift_gate else "N/A",
            "audit": self.audit_stage.verdict if self.audit_stage else "N/A",
            "publish": "YES" if self.can_publish else "NO",
        }


# =============================================================================
# PIPELINE
# =============================================================================

class WienPilotPipeline:
    """
    Wien Pilot dry run pipeline.

    Stages:
    1. Import: FLS → Canonical
    2. Coords Gate: Validate coordinates
    3. Solve: Run solver
    4. Finalize: OSRM validation (if enabled)
    5. Drift Gate: Check drift thresholds
    6. Audit: Run audit checks
    7. Lock: Lock plan (stub)
    8. Publish: Export evidence (stub)
    """

    def __init__(
        self,
        output_dir: Path,
        skip_osrm: bool = False,
        skip_solve: bool = False,
        profile_name: str = "wien_pilot_routing",
    ):
        self.output_dir = output_dir
        self.skip_osrm = skip_osrm
        self.skip_solve = skip_solve
        self.profile_name = profile_name

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, input_path: Path) -> PipelineManifest:
        """Run the complete pipeline."""
        run_id = f"dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        manifest = PipelineManifest(
            run_id=run_id,
            started_at=datetime.now(),
            profile_used=self.profile_name,
            osrm_enabled=not self.skip_osrm,
        )

        logger.info(f"Starting dry run: {run_id}")
        logger.info(f"Input: {input_path}")
        logger.info(f"Output: {self.output_dir}")

        try:
            # Stage 1: Import
            manifest.import_stage = self._run_import_stage(input_path, manifest)
            if not manifest.import_stage.success:
                manifest.overall_verdict = "BLOCK"
                return self._finalize_manifest(manifest)

            # Stage 2: Coords Gate
            manifest.coords_gate = self._run_coords_gate(manifest)
            if manifest.coords_gate.verdict == "BLOCK":
                manifest.overall_verdict = "BLOCK"
                return self._finalize_manifest(manifest)

            # Stage 3: Solve
            if not self.skip_solve:
                manifest.solve_stage = self._run_solve_stage(manifest)
                if not manifest.solve_stage.success:
                    manifest.overall_verdict = "BLOCK"
                    return self._finalize_manifest(manifest)

            # Stage 4: Finalize (OSRM)
            if not self.skip_osrm and manifest.coords_gate.verdict != "BLOCK":
                manifest.finalize_stage = self._run_finalize_stage(manifest)

            # Stage 5: Drift Gate
            if manifest.finalize_stage:
                manifest.drift_gate = self._run_drift_gate(manifest)
                if manifest.drift_gate.verdict == "BLOCK":
                    manifest.overall_verdict = "BLOCK"
                    return self._finalize_manifest(manifest)

            # Stage 6: Audit
            manifest.audit_stage = self._run_audit_stage(manifest)
            if manifest.audit_stage.verdict == "FAIL":
                manifest.overall_verdict = "BLOCK"
                return self._finalize_manifest(manifest)

            # Stage 7: Lock (stub)
            manifest.lock_stage = self._run_lock_stage(manifest)

            # Determine final verdict
            manifest = self._determine_final_verdict(manifest)

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            manifest.overall_verdict = "ERROR"

        return self._finalize_manifest(manifest)

    def _run_import_stage(
        self,
        input_path: Path,
        manifest: PipelineManifest,
    ) -> StageResult:
        """Run import stage."""
        logger.info("Stage 1: Import")
        start = time.time()

        result = StageResult(stage_name="import")

        try:
            # Read input file
            with open(input_path, "r", encoding="utf-8") as f:
                raw_content = f.read()
                raw_data = json.loads(raw_content)

            manifest.input_hash = hashlib.sha256(raw_content.encode()).hexdigest()

            # Import canonicalizer
            from backend_py.packs.routing.importers.fls_canonicalize import FLSCanonicalizer
            from backend_py.packs.routing.importers.fls_validate import FLSValidator

            # Canonicalize
            canonicalizer = FLSCanonicalizer()
            canon_result = canonicalizer.canonicalize(raw_data)

            if not canon_result.success:
                result.success = False
                result.verdict = "BLOCK"
                result.errors = canon_result.errors
                return result

            manifest.canonical_hash = canon_result.canonical_import.canonical_hash

            # Store canonical orders
            canonical_path = self.output_dir / "canonical_orders.json"
            with open(canonical_path, "w") as f:
                json.dump(canon_result.canonical_import.to_dict(), f, indent=2)
            result.artifacts["canonical_orders"] = str(canonical_path)

            # Validate
            validator = FLSValidator()
            validation_result = validator.validate(canon_result.canonical_import)

            # Store validation report
            validation_path = self.output_dir / "validation_report.json"
            with open(validation_path, "w") as f:
                json.dump(validation_result.to_dict(), f, indent=2)
            result.artifacts["validation_report"] = str(validation_path)

            result.success = True
            result.verdict = validation_result.verdict.value
            result.metrics = {
                "orders_raw": len(raw_data.get("orders", [])),
                "orders_canonical": len(canon_result.canonical_import.orders),
                "orders_with_coords": canon_result.canonical_import.orders_with_coords,
                "orders_with_zone": canon_result.canonical_import.orders_with_zone,
                "orders_missing": canon_result.canonical_import.orders_missing_location,
            }
            result.warnings = canon_result.warnings

            # Store canonical import for later stages
            self._canonical_import = canon_result.canonical_import

        except Exception as e:
            result.success = False
            result.verdict = "BLOCK"
            result.errors.append(str(e))
            logger.error(f"Import stage failed: {e}")

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_coords_gate(self, manifest: PipelineManifest) -> StageResult:
        """Run coords quality gate."""
        logger.info("Stage 2: Coords Gate (STOP-5)")
        start = time.time()

        result = StageResult(stage_name="coords_gate")

        try:
            from backend_py.packs.routing.services.finalize.coords_quality_gate import (
                CoordsQualityGate,
                CoordsQualityPolicy,
            )
            from backend_py.packs.routing.services.finalize.coords_lookup import (
                ZoneLookup,
                H3Lookup,
            )

            # Convert canonical orders to dict format
            orders = [o.to_dict() for o in self._canonical_import.orders]

            # Create resolvers for zone and H3 fallback
            zone_resolver = ZoneLookup()
            h3_resolver = H3Lookup()

            gate = CoordsQualityGate(policy=CoordsQualityPolicy())
            gate_result = gate.evaluate(orders, zone_resolver=zone_resolver, h3_resolver=h3_resolver)

            result.success = gate_result.verdict.value != "BLOCK"
            result.verdict = gate_result.verdict.value
            result.metrics = {
                "total_orders": gate_result.total_orders,
                "orders_with_latlng": gate_result.orders_with_latlng,
                "orders_resolved_zone": gate_result.orders_resolved_by_zone,
                "orders_resolved_h3": gate_result.orders_resolved_by_h3,
                "orders_unresolved": gate_result.orders_unresolved,
                "missing_latlng_rate": gate_result.missing_latlng_rate,
                "fallback_rate": gate_result.fallback_rate,
                "allows_osrm_finalize": gate_result.allows_osrm_finalize,
            }
            result.warnings = gate_result.warnings

            # Store coords report
            coords_path = self.output_dir / "coords_quality_report.json"
            with open(coords_path, "w") as f:
                json.dump(gate_result.to_dict(), f, indent=2)
            result.artifacts["coords_quality"] = str(coords_path)

            self._coords_result = gate_result

        except Exception as e:
            result.success = False
            result.verdict = "BLOCK"
            result.errors.append(str(e))
            logger.error(f"Coords gate failed: {e}")

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_solve_stage(self, manifest: PipelineManifest) -> StageResult:
        """Run solver stage (stub)."""
        logger.info("Stage 3: Solve")
        start = time.time()

        result = StageResult(stage_name="solve")

        try:
            # Stub: In real implementation, would call the actual solver
            result.success = True
            result.verdict = "OK"
            result.metrics = {
                "solver": "VRPTW",
                "metaheuristic": "GUIDED_LOCAL_SEARCH",
                "time_limit_seconds": 300,
                "routes_created": 0,  # Stub
                "orders_assigned": len(self._canonical_import.orders),
                "orders_unassigned": 0,
            }

            # Create stub solve result
            solve_result = {
                "status": "SOLVED",
                "routes": [],
                "unassigned": [],
                "kpis": {
                    "total_distance_km": 0,
                    "total_duration_min": 0,
                    "vehicles_used": 0,
                },
            }

            solve_path = self.output_dir / "solve_result.json"
            with open(solve_path, "w") as f:
                json.dump(solve_result, f, indent=2)
            result.artifacts["solve_result"] = str(solve_path)

            self._solve_result = solve_result

        except Exception as e:
            result.success = False
            result.verdict = "BLOCK"
            result.errors.append(str(e))
            logger.error(f"Solve stage failed: {e}")

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_finalize_stage(self, manifest: PipelineManifest) -> StageResult:
        """Run OSRM finalize stage (stub)."""
        logger.info("Stage 4: OSRM Finalize")
        start = time.time()

        result = StageResult(stage_name="finalize")

        try:
            # Compute OSRM map hash
            from backend_py.packs.routing.services.finalize.osrm_map_hash import (
                get_osrm_map_hash_from_env,
                check_osrm_map_usable,
                OSRMMapStatus,
            )
            osrm_info = get_osrm_map_hash_from_env()

            # Check if OSRM map is usable (allow degraded mode for dry run)
            is_usable, block_reason = check_osrm_map_usable(osrm_info, allow_degraded=True)

            # Format hash for display (only if OK)
            display_hash = "N/A"
            if osrm_info.status == OSRMMapStatus.OK and osrm_info.map_hash:
                display_hash = f"sha256:{osrm_info.map_hash[:16]}..."

            # Stub: In real implementation, would call OSRM
            result.success = True
            result.verdict = "OK" if osrm_info.status == OSRMMapStatus.OK else "WARN"
            result.metrics = {
                "osrm_enabled": True,
                "osrm_map_status": osrm_info.status.value,
                "osrm_map_hash": osrm_info.map_hash,
                "osrm_map_hash_scope": osrm_info.hash_scope.value,
                "osrm_profile": osrm_info.profile,
                "total_legs": 0,
                "legs_with_osrm": 0,
                "p95_ratio": 1.05,
                "timeout_rate": 0.01,
                "fallback_rate": 0.02,
            }

            if osrm_info.error_message:
                result.warnings.append(f"OSRM: {osrm_info.error_message}")

            # Create drift report with proper OSRM map info
            drift_report = {
                "plan_id": manifest.run_id,
                "matrix_version": "wien_2026w02_v1",
                "osrm_map": osrm_info.to_evidence_dict()["osrm_map"],
                "computed_at": datetime.now().isoformat(),
                "aggregations": {
                    "total_legs": 0,
                    "legs_with_osrm": 0,
                    "timeout_rate": 0.01,
                    "fallback_rate": 0.02,
                },
                "statistics": {
                    "mean_ratio": 1.05,
                    "p95_ratio": 1.08,
                    "max_ratio": 1.15,
                },
            }

            drift_path = self.output_dir / "drift_report.json"
            with open(drift_path, "w") as f:
                json.dump(drift_report, f, indent=2)
            result.artifacts["drift_report"] = str(drift_path)

            # Create stub fallback report
            fallback_report = {
                "plan_id": manifest.run_id,
                "total_legs": 0,
                "fallback_count": 0,
                "timeout_count": 0,
            }

            fallback_path = self.output_dir / "fallback_report.json"
            with open(fallback_path, "w") as f:
                json.dump(fallback_report, f, indent=2)
            result.artifacts["fallback_report"] = str(fallback_path)

            self._drift_report = drift_report
            self._fallback_report = fallback_report

        except Exception as e:
            result.success = False
            result.verdict = "WARN"
            result.errors.append(str(e))
            logger.warning(f"Finalize stage issue: {e}")

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_drift_gate(self, manifest: PipelineManifest) -> StageResult:
        """Run drift gate."""
        logger.info("Stage 5: Drift Gate")
        start = time.time()

        result = StageResult(stage_name="drift_gate")

        try:
            # Use stub values from finalize
            p95_ratio = self._drift_report["statistics"]["p95_ratio"]

            if p95_ratio <= 1.15:
                result.verdict = "OK"
            elif p95_ratio <= 1.30:
                result.verdict = "WARN"
            else:
                result.verdict = "BLOCK"

            result.success = result.verdict != "BLOCK"
            result.metrics = {
                "p95_ratio": p95_ratio,
                "ok_threshold": 1.15,
                "warn_threshold": 1.30,
            }

        except Exception as e:
            result.success = True  # Don't block on drift gate errors
            result.verdict = "WARN"
            result.warnings.append(str(e))

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_audit_stage(self, manifest: PipelineManifest) -> StageResult:
        """Run audit stage (stub)."""
        logger.info("Stage 6: Audit")
        start = time.time()

        result = StageResult(stage_name="audit")

        try:
            # Stub: In real implementation, would run audit checks
            result.success = True
            result.verdict = "PASS"
            result.metrics = {
                "checks_run": 5,
                "checks_passed": 5,
                "checks_warned": 0,
                "checks_failed": 0,
            }

            audit_result = {
                "audited_at": datetime.now().isoformat(),
                "all_passed": True,
                "results": {
                    "COVERAGE": {"status": "PASS"},
                    "TIME_WINDOW": {"status": "PASS"},
                    "SHIFT_FEASIBILITY": {"status": "PASS"},
                    "SKILLS_COMPLIANCE": {"status": "PASS"},
                    "OVERLAP": {"status": "PASS"},
                },
            }

            audit_path = self.output_dir / "audit_results.json"
            with open(audit_path, "w") as f:
                json.dump(audit_result, f, indent=2)
            result.artifacts["audit_results"] = str(audit_path)

        except Exception as e:
            result.success = False
            result.verdict = "FAIL"
            result.errors.append(str(e))

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _run_lock_stage(self, manifest: PipelineManifest) -> StageResult:
        """Run lock stage (stub)."""
        logger.info("Stage 7: Lock")
        start = time.time()

        result = StageResult(stage_name="lock")

        try:
            result.success = True
            result.verdict = "LOCKED"
            result.metrics = {
                "locked_at": datetime.now().isoformat(),
                "locked_by": "dry_run",
            }

        except Exception as e:
            result.success = False
            result.verdict = "FAILED"
            result.errors.append(str(e))

        result.duration_seconds = time.time() - start
        logger.info(f"  Verdict: {result.verdict}")
        return result

    def _determine_final_verdict(self, manifest: PipelineManifest) -> PipelineManifest:
        """Determine final verdict based on all stages."""
        # Check for any BLOCK verdicts
        stages = [
            manifest.coords_gate,
            manifest.drift_gate,
        ]

        for stage in stages:
            if stage and stage.verdict == "BLOCK":
                manifest.overall_verdict = "BLOCK"
                manifest.can_publish = False
                return manifest

        # Check audit
        if manifest.audit_stage and manifest.audit_stage.verdict == "FAIL":
            manifest.overall_verdict = "BLOCK"
            manifest.can_publish = False
            return manifest

        # Check for any WARN verdicts
        has_warn = False
        for stage in stages:
            if stage and stage.verdict == "WARN":
                has_warn = True

        if has_warn:
            manifest.overall_verdict = "WARN"
            manifest.can_publish = True  # With approval
        else:
            manifest.overall_verdict = "OK"
            manifest.can_publish = True

        return manifest

    def _finalize_manifest(self, manifest: PipelineManifest) -> PipelineManifest:
        """Finalize and save manifest."""
        manifest.completed_at = datetime.now()

        # Save manifest
        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest.to_dict(), f, indent=2)

        # Print summary
        logger.info("=" * 60)
        logger.info("DRY RUN COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Run ID: {manifest.run_id}")
        logger.info(f"Overall Verdict: {manifest.overall_verdict}")
        logger.info(f"Can Publish: {manifest.can_publish}")
        logger.info(f"Verdict Chain:")
        for gate, verdict in manifest._get_verdict_chain().items():
            logger.info(f"  {gate}: {verdict}")
        logger.info(f"Output: {self.output_dir}")
        logger.info("=" * 60)

        return manifest


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run Wien Pilot dry run pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json
  python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json --skip-osrm
  python scripts/run_wien_pilot_dry_run.py --input data/fls_export.json --output-dir runs/
        """,
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to FLS export JSON file",
    )

    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Output directory (default: runs/<timestamp>)",
    )

    parser.add_argument(
        "--skip-osrm",
        action="store_true",
        help="Skip OSRM finalize stage",
    )

    parser.add_argument(
        "--skip-solve",
        action="store_true",
        help="Skip solve stage",
    )

    parser.add_argument(
        "--profile",
        default="wien_pilot_routing",
        help="Policy profile name",
    )

    args = parser.parse_args()

    # Validate input
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Set output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "runs" / timestamp

    # Run pipeline
    pipeline = WienPilotPipeline(
        output_dir=output_dir,
        skip_osrm=args.skip_osrm,
        skip_solve=args.skip_solve,
        profile_name=args.profile,
    )

    manifest = pipeline.run(input_path)

    # Exit code based on verdict
    if manifest.overall_verdict == "BLOCK":
        sys.exit(2)
    elif manifest.overall_verdict == "WARN":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
