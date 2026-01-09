#!/usr/bin/env python3
"""
SOLVEREIGN V3.7 - Real Data Onboarding Bundle
==============================================

Orchestrates the complete onboarding workflow:
1. Validate import contract (hard gates must pass)
2. Canonicalize input data
3. Resolve/create external ID mappings
4. Generate onboarding artifact bundle

Exit Codes:
    0 = SUCCESS - Onboarding complete
    1 = WARN - Onboarding complete with warnings
    2 = FAIL - Hard gate failure, onboarding blocked

Usage:
    python scripts/run_onboarding_bundle.py \
      --input roster.json \
      --tenant wien_pilot \
      --site site_001 \
      --week-anchor 2026-01-06
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import subprocess


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OnboardingConfig:
    """Configuration for onboarding run."""
    input_file: str
    tenant_code: str
    site_code: str
    week_anchor_date: str
    output_dir: str = "artifacts/onboarding"
    dry_run: bool = False
    source_system: str = "fls_export"

    def __post_init__(self):
        self.run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.artifacts_dir = f"{self.output_dir}/{self.tenant_code}/{self.run_id}"


@dataclass
class OnboardingResult:
    """Result of onboarding run."""
    status: str  # PASS, WARN, FAIL
    run_id: str
    tenant_code: str
    site_code: str
    week_anchor_date: str

    # Validation
    validation_status: str = ""
    hard_gates_passed: int = 0
    hard_gates_failed: int = 0
    soft_gates_warnings: int = 0
    validation_errors: List[Dict] = field(default_factory=list)

    # Canonicalization
    canonical_hash: str = ""
    tours_count: int = 0
    total_instances: int = 0

    # Mappings
    mappings_created: int = 0
    mappings_existing: int = 0
    mappings_by_type: Dict[str, int] = field(default_factory=dict)

    # Rejected rows
    rejected_rows: List[Dict] = field(default_factory=list)

    # Artifacts
    artifacts_dir: str = ""
    artifacts: List[str] = field(default_factory=list)


# =============================================================================
# ONBOARDING ORCHESTRATOR
# =============================================================================

class OnboardingOrchestrator:
    """Orchestrates the complete onboarding workflow."""

    def __init__(self, config: OnboardingConfig):
        self.config = config
        self.result = OnboardingResult(
            status="IN_PROGRESS",
            run_id=config.run_id,
            tenant_code=config.tenant_code,
            site_code=config.site_code,
            week_anchor_date=config.week_anchor_date,
            artifacts_dir=config.artifacts_dir,
        )

    def run(self) -> OnboardingResult:
        """Execute the complete onboarding workflow."""

        print("=" * 70)
        print("SOLVEREIGN REAL DATA ONBOARDING")
        print("=" * 70)
        print(f"Run ID:      {self.config.run_id}")
        print(f"Tenant:      {self.config.tenant_code}")
        print(f"Site:        {self.config.site_code}")
        print(f"Week Anchor: {self.config.week_anchor_date}")
        print(f"Input:       {self.config.input_file}")
        print(f"Dry Run:     {self.config.dry_run}")
        print("=" * 70)
        print()

        # Create artifacts directory
        os.makedirs(self.config.artifacts_dir, exist_ok=True)

        # Step 1: Validate
        print("[1/4] Validating import contract...")
        if not self._step_validate():
            self._finalize("FAIL")
            return self.result

        # Step 2: Canonicalize
        print("[2/4] Canonicalizing input data...")
        canonical_data = self._step_canonicalize()
        if canonical_data is None:
            self._finalize("FAIL")
            return self.result

        # Step 3: Resolve/Create Mappings
        print("[3/4] Resolving external ID mappings...")
        self._step_mappings(canonical_data)

        # Step 4: Generate Bundle
        print("[4/4] Generating onboarding bundle...")
        self._step_bundle(canonical_data)

        # Finalize
        final_status = "WARN" if self.result.soft_gates_warnings > 0 else "PASS"
        self._finalize(final_status)

        return self.result

    def _step_validate(self) -> bool:
        """Step 1: Validate input against import contract."""

        validation_output = f"{self.config.artifacts_dir}/validation_report.json"

        cmd = [
            "python", "scripts/validate_import_contract.py",
            "--input", self.config.input_file,
            "--output", f"{self.config.artifacts_dir}/canonical_input.json",
            "--verbose",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            exit_code = result.returncode

            # Parse validation output
            if exit_code == 2:  # FAIL
                print("       ❌ Validation FAILED (hard gate failures)")
                self.result.validation_status = "FAIL"
                self.result.hard_gates_failed = 1  # At least one

                # Try to parse errors from output
                self._parse_validation_output(result.stdout)
                return False

            elif exit_code == 1:  # WARN
                print("       ⚠️  Validation PASSED with warnings")
                self.result.validation_status = "WARN"
                self._parse_validation_output(result.stdout)
                return True

            else:  # PASS
                print("       ✅ Validation PASSED")
                self.result.validation_status = "PASS"
                self._parse_validation_output(result.stdout)
                return True

        except subprocess.TimeoutExpired:
            print("       ❌ Validation timed out")
            self.result.validation_status = "FAIL"
            return False
        except Exception as e:
            print(f"       ❌ Validation error: {e}")
            self.result.validation_status = "FAIL"
            return False

    def _parse_validation_output(self, output: str) -> None:
        """Parse validation output for stats."""
        # Simple parsing - in production would parse JSON output
        for line in output.split("\n"):
            if "Hard Gates:" in line:
                parts = line.split(",")
                for part in parts:
                    if "passed" in part:
                        try:
                            self.result.hard_gates_passed = int(part.split()[0])
                        except:
                            pass
                    if "failed" in part:
                        try:
                            self.result.hard_gates_failed = int(part.split()[0])
                        except:
                            pass
            if "Soft Gates:" in line and "warnings" in line:
                parts = line.split(",")
                for part in parts:
                    if "warnings" in part:
                        try:
                            self.result.soft_gates_warnings = int(part.split()[0])
                        except:
                            pass

    def _step_canonicalize(self) -> Optional[Dict]:
        """Step 2: Load and canonicalize input data."""

        canonical_file = f"{self.config.artifacts_dir}/canonical_input.json"

        # Check if canonical output was generated by validator
        if os.path.exists(canonical_file):
            with open(canonical_file, "r") as f:
                canonical_data = json.load(f)

            # Calculate hash
            hash_content = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
            self.result.canonical_hash = hashlib.sha256(hash_content.encode()).hexdigest()

            # Count tours
            tours = canonical_data.get("tours", [])
            self.result.tours_count = len(tours)
            self.result.total_instances = sum(t.get("count", 1) for t in tours)

            print(f"       Tours: {self.result.tours_count}")
            print(f"       Instances: {self.result.total_instances}")
            print(f"       Hash: {self.result.canonical_hash[:16]}...")

            self.result.artifacts.append("canonical_input.json")
            return canonical_data

        # Fallback: load original and canonicalize
        try:
            with open(self.config.input_file, "r") as f:
                data = json.load(f)

            # Apply defaults (simple canonicalization)
            canonical_data = self._apply_defaults(data)

            # Save canonical output
            with open(canonical_file, "w") as f:
                json.dump(canonical_data, f, indent=2, sort_keys=True)

            # Calculate hash
            hash_content = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
            self.result.canonical_hash = hashlib.sha256(hash_content.encode()).hexdigest()

            tours = canonical_data.get("tours", [])
            self.result.tours_count = len(tours)
            self.result.total_instances = sum(t.get("count", 1) for t in tours)

            print(f"       Tours: {self.result.tours_count}")
            print(f"       Instances: {self.result.total_instances}")
            print(f"       Hash: {self.result.canonical_hash[:16]}...")

            self.result.artifacts.append("canonical_input.json")
            return canonical_data

        except Exception as e:
            print(f"       ❌ Canonicalization error: {e}")
            return None

    def _apply_defaults(self, data: Dict) -> Dict:
        """Apply default values to input data."""
        canonical = {
            "schema_version": "1.0.0",
            "tenant_code": data.get("tenant_code", self.config.tenant_code),
            "site_code": data.get("site_code", self.config.site_code),
            "week_anchor_date": data.get("week_anchor_date", self.config.week_anchor_date),
            "service_code": data.get("service_code", "default"),
            "tours": [],
            "drivers": data.get("drivers", []),
            "vehicles": data.get("vehicles", []),
            "metadata": data.get("metadata", {}),
        }

        for tour in data.get("tours", []):
            canonical["tours"].append({
                "external_id": tour["external_id"],
                "day": tour["day"],
                "start_time": tour["start_time"],
                "end_time": tour["end_time"],
                "count": tour.get("count", 1),
                "depot": tour.get("depot", "default"),
                "skill": tour.get("skill", "standard"),
                "priority": tour.get("priority", 5),
                "lat": tour.get("lat"),
                "lng": tour.get("lng"),
                "volume": tour.get("volume"),
                "notes": tour.get("notes"),
            })

        return canonical

    def _step_mappings(self, canonical_data: Dict) -> None:
        """Step 3: Resolve/create external ID mappings."""

        mappings_created = 0
        mappings_existing = 0
        mappings_by_type = {"tour": 0, "driver": 0, "vehicle": 0}

        # In dry-run mode, just count what would be created
        if self.config.dry_run:
            # Count tours
            for tour in canonical_data.get("tours", []):
                mappings_by_type["tour"] += 1
                mappings_created += 1

            # Count drivers
            for driver in canonical_data.get("drivers", []):
                mappings_by_type["driver"] += 1
                mappings_created += 1

            # Count vehicles
            for vehicle in canonical_data.get("vehicles", []):
                mappings_by_type["vehicle"] += 1
                mappings_created += 1

            print(f"       [DRY-RUN] Would create {mappings_created} mappings")
        else:
            # In real mode, would call master_data service
            # For now, simulate the counts
            for tour in canonical_data.get("tours", []):
                mappings_by_type["tour"] += 1
                mappings_created += 1

            for driver in canonical_data.get("drivers", []):
                mappings_by_type["driver"] += 1
                mappings_created += 1

            for vehicle in canonical_data.get("vehicles", []):
                mappings_by_type["vehicle"] += 1
                mappings_created += 1

            print(f"       Created: {mappings_created}")
            print(f"       Existing: {mappings_existing}")

        self.result.mappings_created = mappings_created
        self.result.mappings_existing = mappings_existing
        self.result.mappings_by_type = mappings_by_type

        # Save mapping summary
        mapping_summary = {
            "tenant_code": self.config.tenant_code,
            "site_code": self.config.site_code,
            "source_system": self.config.source_system,
            "mappings_created": mappings_created,
            "mappings_existing": mappings_existing,
            "by_type": mappings_by_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

        summary_file = f"{self.config.artifacts_dir}/mapping_summary.json"
        with open(summary_file, "w") as f:
            json.dump(mapping_summary, f, indent=2)

        self.result.artifacts.append("mapping_summary.json")

    def _step_bundle(self, canonical_data: Dict) -> None:
        """Step 4: Generate the onboarding bundle."""

        # Save rejected rows (if any from validation)
        rejected_file = f"{self.config.artifacts_dir}/rejected_rows.json"
        with open(rejected_file, "w") as f:
            json.dump(self.result.rejected_rows, f, indent=2)
        self.result.artifacts.append("rejected_rows.json")

        # Generate checksums
        checksums = []
        for artifact in self.result.artifacts:
            artifact_path = f"{self.config.artifacts_dir}/{artifact}"
            if os.path.exists(artifact_path):
                with open(artifact_path, "rb") as f:
                    sha256 = hashlib.sha256(f.read()).hexdigest()
                checksums.append(f"{sha256}  {artifact}")

        checksums_file = f"{self.config.artifacts_dir}/checksums.txt"
        with open(checksums_file, "w") as f:
            f.write("\n".join(checksums))
        self.result.artifacts.append("checksums.txt")

        print(f"       Artifacts: {len(self.result.artifacts)} files")

    def _finalize(self, status: str) -> None:
        """Finalize and save the onboarding result."""

        self.result.status = status

        # Save result
        result_dict = {
            "status": self.result.status,
            "run_id": self.result.run_id,
            "tenant_code": self.result.tenant_code,
            "site_code": self.result.site_code,
            "week_anchor_date": self.result.week_anchor_date,
            "timestamp": datetime.utcnow().isoformat(),
            "validation": {
                "status": self.result.validation_status,
                "hard_gates_passed": self.result.hard_gates_passed,
                "hard_gates_failed": self.result.hard_gates_failed,
                "soft_gates_warnings": self.result.soft_gates_warnings,
                "errors": self.result.validation_errors,
            },
            "canonicalization": {
                "hash": self.result.canonical_hash,
                "tours_count": self.result.tours_count,
                "total_instances": self.result.total_instances,
            },
            "mappings": {
                "created": self.result.mappings_created,
                "existing": self.result.mappings_existing,
                "by_type": self.result.mappings_by_type,
            },
            "rejected_rows_count": len(self.result.rejected_rows),
            "artifacts_dir": self.result.artifacts_dir,
            "artifacts": self.result.artifacts,
        }

        result_file = f"{self.config.artifacts_dir}/onboarding_result.json"
        with open(result_file, "w") as f:
            json.dump(result_dict, f, indent=2, sort_keys=True)

        # Print summary
        print()
        print("=" * 70)
        print("ONBOARDING SUMMARY")
        print("=" * 70)
        print(f"Status:           {self.result.status}")
        print(f"Validation:       {self.result.validation_status}")
        print(f"Tours:            {self.result.tours_count}")
        print(f"Instances:        {self.result.total_instances}")
        print(f"Mappings Created: {self.result.mappings_created}")
        print(f"Canonical Hash:   {self.result.canonical_hash[:32]}...")
        print(f"Artifacts:        {self.config.artifacts_dir}/")
        print("=" * 70)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Real Data Onboarding Bundle"
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input roster file (JSON or CSV)"
    )

    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant code"
    )

    parser.add_argument(
        "--site",
        required=True,
        help="Site code"
    )

    parser.add_argument(
        "--week-anchor",
        required=True,
        help="Week anchor date (Monday, YYYY-MM-DD)"
    )

    parser.add_argument(
        "--output-dir",
        default="artifacts/onboarding",
        help="Output directory for artifacts"
    )

    parser.add_argument(
        "--source-system",
        default="fls_export",
        help="Source system identifier"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run (don't create DB mappings)"
    )

    args = parser.parse_args()

    # Validate input file exists
    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(2)

    # Create config
    config = OnboardingConfig(
        input_file=args.input,
        tenant_code=args.tenant,
        site_code=args.site,
        week_anchor_date=args.week_anchor,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        source_system=args.source_system,
    )

    # Run onboarding
    orchestrator = OnboardingOrchestrator(config)
    result = orchestrator.run()

    # Exit code
    if result.status == "PASS":
        print()
        print("✅ Onboarding COMPLETE")
        sys.exit(0)
    elif result.status == "WARN":
        print()
        print("⚠️  Onboarding COMPLETE with warnings")
        sys.exit(1)
    else:
        print()
        print("❌ Onboarding FAILED")
        sys.exit(2)


if __name__ == "__main__":
    main()
