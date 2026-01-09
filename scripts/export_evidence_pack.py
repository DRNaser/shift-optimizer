#!/usr/bin/env python3
"""
SOLVEREIGN V3.7 - Evidence Pack Exporter (Gate I)
==================================================

Export audit-grade evidence pack as reproducible ZIP with checksums.

Features:
- Deterministic ZIP generation (sorted entries, fixed timestamps)
- SHA256 checksums for all files
- JSON manifest with metadata
- Schema validation

Usage:
    python scripts/export_evidence_pack.py --run-id drill_20260108_120000_1
    python scripts/export_evidence_pack.py --input artifacts/drills/sick_call/*.json --out evidence.zip

Output:
    evidence_pack_<run_id>.zip containing:
    - manifest.json (evidence metadata)
    - checksums.txt (SHA256 of all files)
    - evidence.json (main evidence data)
    - [optional] audit_log.json, churn_report.json, etc.
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Fixed timestamp for reproducible ZIP
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def export_evidence_pack(
    run_id: str = None,
    input_file: str = None,
    output_path: str = None,
    include_logs: bool = True,
    validate_schema: bool = True
) -> Dict[str, Any]:
    """
    Export evidence pack to ZIP.

    Args:
        run_id: Run ID to export (looks up from artifacts)
        input_file: Direct path to evidence JSON
        output_path: Output ZIP path
        include_logs: Include audit logs if available
        validate_schema: Validate against evidence_pack.schema.json

    Returns:
        Export result dict
    """
    print("=" * 70)
    print("SOLVEREIGN EVIDENCE PACK EXPORTER (Gate I)")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    # Find evidence file
    evidence_file = None
    if input_file:
        evidence_file = Path(input_file)
    elif run_id:
        # Search artifacts directories
        for search_dir in [
            PROJECT_ROOT / "artifacts" / "drills",
            PROJECT_ROOT / "artifacts" / "runs",
            PROJECT_ROOT / "artifacts"
        ]:
            if search_dir.exists():
                for f in search_dir.rglob("*.json"):
                    if run_id in f.name:
                        evidence_file = f
                        break
            if evidence_file:
                break

    if not evidence_file or not evidence_file.exists():
        raise ValueError(f"Evidence file not found for run_id={run_id} or input={input_file}")

    print(f"[1/5] Loading evidence from: {evidence_file}")

    with open(evidence_file) as f:
        evidence_data = json.load(f)

    run_id = evidence_data.get("run_id", run_id or "unknown")

    # Validate schema if requested
    if validate_schema:
        print("[2/5] Validating against schema...")
        schema_valid, schema_errors = _validate_schema(evidence_data)
        if not schema_valid:
            print(f"       WARN: Schema validation failed: {schema_errors}")
        else:
            print("       Schema validation PASS")
    else:
        schema_valid = True
        schema_errors = []

    # Prepare files for ZIP
    print("[3/5] Preparing files...")
    files_to_zip: Dict[str, bytes] = {}

    # Main evidence file
    evidence_json = json.dumps(evidence_data, indent=2, sort_keys=True, default=str)
    files_to_zip["evidence.json"] = evidence_json.encode()
    print(f"       Added: evidence.json ({len(files_to_zip['evidence.json'])} bytes)")

    # Add audit details if present
    if "audit_results" in evidence_data and evidence_data["audit_results"]:
        audit_json = json.dumps(evidence_data["audit_results"], indent=2, sort_keys=True)
        files_to_zip["audit_log.json"] = audit_json.encode()
        print(f"       Added: audit_log.json")

    # Add churn report if present
    if "churn_metrics" in evidence_data and evidence_data["churn_metrics"]:
        churn_json = json.dumps(evidence_data["churn_metrics"], indent=2, sort_keys=True)
        files_to_zip["churn_report.json"] = churn_json.encode()
        print(f"       Added: churn_report.json")

    # Add freeze report if present
    if "freeze" in evidence_data and evidence_data["freeze"]:
        freeze_json = json.dumps(evidence_data["freeze"], indent=2, sort_keys=True)
        files_to_zip["freeze_report.json"] = freeze_json.encode()
        print(f"       Added: freeze_report.json")

    # Compute checksums
    print("[4/5] Computing checksums...")
    checksums: Dict[str, str] = {}
    for filename, content in sorted(files_to_zip.items()):
        checksum = hashlib.sha256(content).hexdigest()
        checksums[filename] = checksum
        print(f"       {filename}: {checksum[:16]}...")

    # Create checksums.txt
    checksums_content = "\n".join(
        f"{checksum}  {filename}"
        for filename, checksum in sorted(checksums.items())
    )
    files_to_zip["checksums.txt"] = checksums_content.encode()

    # Create manifest
    manifest = {
        "version": "1.0.0",
        "run_id": run_id,
        "exported_at": datetime.now().isoformat(),
        "schema_valid": schema_valid,
        "files": [
            {
                "name": filename,
                "sha256": checksums.get(filename, ""),
                "size_bytes": len(content)
            }
            for filename, content in sorted(files_to_zip.items())
            if filename != "manifest.json"
        ],
        "manifest_hash": ""  # Will be computed after
    }

    # Compute manifest hash (without itself)
    manifest_for_hash = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest_for_hash, sort_keys=True).encode()
    ).hexdigest()

    files_to_zip["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode()

    # Create ZIP
    print("[5/5] Creating ZIP archive...")

    if output_path is None:
        output_dir = PROJECT_ROOT / "artifacts" / "evidence_packs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"evidence_pack_{run_id}.zip"
    else:
        output_path = Path(output_path)

    _create_deterministic_zip(output_path, files_to_zip)
    print(f"       Created: {output_path}")

    # Compute ZIP hash
    with open(output_path, "rb") as f:
        zip_hash = hashlib.sha256(f.read()).hexdigest()

    result = {
        "status": "SUCCESS",
        "run_id": run_id,
        "output_path": str(output_path),
        "zip_hash": zip_hash,
        "files_count": len(files_to_zip),
        "total_size_bytes": sum(len(c) for c in files_to_zip.values()),
        "schema_valid": schema_valid,
        "manifest_hash": manifest["manifest_hash"]
    }

    _print_summary(result)
    return result


def _validate_schema(evidence: Dict[str, Any]) -> tuple:
    """Validate evidence against schema."""
    try:
        import jsonschema

        schema_path = PROJECT_ROOT / "backend_py" / "schemas" / "evidence_pack.schema.json"
        if not schema_path.exists():
            return True, ["Schema file not found - skipping validation"]

        with open(schema_path) as f:
            schema = json.load(f)

        jsonschema.validate(evidence, schema)
        return True, []

    except jsonschema.ValidationError as e:
        return False, [str(e)]
    except ImportError:
        return True, ["jsonschema not installed - skipping validation"]
    except Exception as e:
        return False, [str(e)]


def _create_deterministic_zip(output_path: Path, files: Dict[str, bytes]) -> None:
    """Create ZIP with deterministic ordering and timestamps."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in sorted(files.keys()):
            content = files[filename]

            # Create ZipInfo with fixed timestamp
            info = zipfile.ZipInfo(filename, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED

            zf.writestr(info, content)


def _print_summary(result: Dict[str, Any]) -> None:
    """Print export summary."""
    print("\n" + "=" * 70)
    print("EVIDENCE PACK EXPORT SUMMARY")
    print("=" * 70)
    print(f"\nRun ID:       {result['run_id']}")
    print(f"Output:       {result['output_path']}")
    print(f"ZIP Hash:     {result['zip_hash'][:32]}...")
    print(f"Files:        {result['files_count']}")
    print(f"Total Size:   {result['total_size_bytes']} bytes")
    print(f"Schema Valid: {result['schema_valid']}")
    print(f"\nManifest Hash: {result['manifest_hash'][:32]}...")
    print("=" * 70)


def verify_evidence_pack(zip_path: str) -> Dict[str, Any]:
    """
    Verify evidence pack integrity.

    Args:
        zip_path: Path to evidence pack ZIP

    Returns:
        Verification result
    """
    print("=" * 70)
    print("EVIDENCE PACK VERIFICATION")
    print("=" * 70)

    zip_path = Path(zip_path)
    if not zip_path.exists():
        return {"status": "ERROR", "error": "ZIP not found"}

    result = {
        "zip_path": str(zip_path),
        "files_verified": 0,
        "checksums_valid": True,
        "manifest_valid": True,
        "errors": []
    }

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Read checksums
        try:
            checksums_content = zf.read("checksums.txt").decode()
            expected_checksums = {}
            for line in checksums_content.strip().split("\n"):
                if "  " in line:
                    checksum, filename = line.split("  ", 1)
                    expected_checksums[filename] = checksum
        except KeyError:
            result["errors"].append("checksums.txt not found")
            result["checksums_valid"] = False
            expected_checksums = {}

        # Verify each file
        for info in zf.infolist():
            if info.filename in ["manifest.json", "checksums.txt"]:
                continue

            content = zf.read(info.filename)
            actual_checksum = hashlib.sha256(content).hexdigest()

            expected = expected_checksums.get(info.filename)
            if expected and actual_checksum != expected:
                result["errors"].append(f"Checksum mismatch: {info.filename}")
                result["checksums_valid"] = False
            else:
                result["files_verified"] += 1

    result["status"] = "PASS" if result["checksums_valid"] else "FAIL"

    print(f"\nFiles Verified: {result['files_verified']}")
    print(f"Checksums Valid: {result['checksums_valid']}")
    if result["errors"]:
        print(f"Errors: {result['errors']}")
    print(f"\nVERDICT: {result['status']}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Evidence Pack Exporter"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export evidence pack")
    export_parser.add_argument("--run-id", type=str, help="Run ID to export")
    export_parser.add_argument("--input", type=str, help="Direct path to evidence JSON")
    export_parser.add_argument("--out", type=str, help="Output ZIP path")
    export_parser.add_argument("--no-validate", action="store_true", help="Skip schema validation")

    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify evidence pack")
    verify_parser.add_argument("zip_path", type=str, help="Path to evidence ZIP")

    args = parser.parse_args()

    if args.command == "export":
        result = export_evidence_pack(
            run_id=args.run_id,
            input_file=args.input,
            output_path=args.out,
            validate_schema=not args.no_validate
        )
        sys.exit(0 if result["status"] == "SUCCESS" else 1)

    elif args.command == "verify":
        result = verify_evidence_pack(args.zip_path)
        sys.exit(0 if result["status"] == "PASS" else 1)

    else:
        # Default: show help
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
