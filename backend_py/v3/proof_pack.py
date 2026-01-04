"""
SOLVEREIGN V3.1 Proof Pack Generator
=====================================

Generates verifiable proof pack for LOCKED plans per SKILL.md section 11.

Artifacts:
- matrix.csv (driver x day)
- rosters.csv (per-driver detail)
- kpis.json (drivers, hours, PT%, block mix)
- audit_summary.json (all audit results)
- metadata.json (all ids + hashes + seed + config_hashes)
- manifest.json (sha256 per artifact)
"""

import hashlib
import json
import csv
import os
from datetime import datetime
from typing import Optional
from pathlib import Path


def compute_file_hash(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_proof_pack(
    plan_version_id: int,
    output_dir: str,
    db_connection=None,
    metadata: Optional[dict] = None,
    kpis: Optional[dict] = None,
    audit_results: Optional[dict] = None,
    matrix_data: Optional[list] = None,
    roster_data: Optional[list] = None,
) -> dict:
    """
    Generate complete proof pack for a LOCKED plan.

    Args:
        plan_version_id: Plan version to export
        output_dir: Directory to write artifacts
        db_connection: Database connection (optional)
        metadata: Pre-computed metadata dict
        kpis: Pre-computed KPIs dict
        audit_results: Pre-computed audit results
        matrix_data: Pre-computed matrix rows
        roster_data: Pre-computed roster rows

    Returns:
        Manifest dict with file hashes
    """
    os.makedirs(output_dir, exist_ok=True)

    files = {}
    generated_at = datetime.now().isoformat()

    # 1. Write metadata.json
    if metadata is None:
        metadata = {
            'plan_version_id': plan_version_id,
            'generated_at': generated_at,
            'note': 'Metadata should be provided by caller',
        }

    metadata_path = os.path.join(output_dir, 'metadata.json')
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, default=str)
    files['metadata.json'] = compute_file_hash(metadata_path)

    # 2. Write kpis.json
    if kpis is None:
        kpis = {'plan_version_id': plan_version_id, 'note': 'KPIs should be provided by caller'}

    kpis_path = os.path.join(output_dir, 'kpis.json')
    with open(kpis_path, 'w', encoding='utf-8') as f:
        json.dump(kpis, f, indent=2, default=str)
    files['kpis.json'] = compute_file_hash(kpis_path)

    # 3. Write audit_summary.json
    if audit_results is None:
        audit_results = {'plan_version_id': plan_version_id, 'note': 'Audit results should be provided by caller'}

    audit_path = os.path.join(output_dir, 'audit_summary.json')
    with open(audit_path, 'w', encoding='utf-8') as f:
        json.dump(audit_results, f, indent=2, default=str)
    files['audit_summary.json'] = compute_file_hash(audit_path)

    # 4. Write matrix.csv
    matrix_path = os.path.join(output_dir, 'matrix.csv')
    if matrix_data:
        with open(matrix_path, 'w', newline='', encoding='utf-8') as f:
            if matrix_data:
                writer = csv.DictWriter(f, fieldnames=matrix_data[0].keys())
                writer.writeheader()
                writer.writerows(matrix_data)
    else:
        with open(matrix_path, 'w', encoding='utf-8') as f:
            f.write('driver_id,Mo,Di,Mi,Do,Fr,Sa,So,total_hours\n')
            f.write('# Matrix data should be provided by caller\n')
    files['matrix.csv'] = compute_file_hash(matrix_path)

    # 5. Write rosters.csv
    rosters_path = os.path.join(output_dir, 'rosters.csv')
    if roster_data:
        with open(rosters_path, 'w', newline='', encoding='utf-8') as f:
            if roster_data:
                writer = csv.DictWriter(f, fieldnames=roster_data[0].keys())
                writer.writeheader()
                writer.writerows(roster_data)
    else:
        with open(rosters_path, 'w', encoding='utf-8') as f:
            f.write('driver_id,day,tour_instance_id,start_ts,end_ts,work_hours\n')
            f.write('# Roster data should be provided by caller\n')
    files['rosters.csv'] = compute_file_hash(rosters_path)

    # 6. Generate manifest.json
    manifest = {
        'plan_version_id': plan_version_id,
        'generated_at': generated_at,
        'version': 'v3.1',
        'files': files,
        'verification': {
            'algorithm': 'SHA256',
            'verify_script_ps1': 'verify.ps1',
            'verify_script_sh': 'verify.sh',
        },
    }

    # Add hashes from metadata if available
    if 'input_hash' in (metadata or {}):
        manifest['input_hash'] = metadata['input_hash']
    if 'output_hash' in (metadata or {}):
        manifest['output_hash'] = metadata['output_hash']
    if 'solver_config_hash' in (metadata or {}):
        manifest['solver_config_hash'] = metadata['solver_config_hash']

    manifest_path = os.path.join(output_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    # Copy verify scripts if they exist
    script_dir = Path(__file__).parent.parent / 'exports'
    for script in ['verify.ps1', 'verify.sh']:
        src = script_dir / script
        dst = os.path.join(output_dir, script)
        if src.exists():
            with open(src, 'r', encoding='utf-8') as sf:
                content = sf.read()
            with open(dst, 'w', encoding='utf-8') as df:
                df.write(content)

    return manifest


def verify_proof_pack(export_dir: str) -> dict:
    """
    Verify a proof pack by checking manifest checksums.

    Args:
        export_dir: Directory containing proof pack

    Returns:
        dict with verification results
    """
    manifest_path = os.path.join(export_dir, 'manifest.json')

    if not os.path.exists(manifest_path):
        return {
            'valid': False,
            'error': 'manifest.json not found',
            'passed': 0,
            'failed': 0,
        }

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    results = {
        'valid': True,
        'plan_version_id': manifest.get('plan_version_id'),
        'generated_at': manifest.get('generated_at'),
        'passed': 0,
        'failed': 0,
        'details': {},
    }

    for filename, expected_hash in manifest.get('files', {}).items():
        filepath = os.path.join(export_dir, filename)

        if not os.path.exists(filepath):
            results['details'][filename] = {'status': 'MISSING'}
            results['failed'] += 1
            results['valid'] = False
            continue

        actual_hash = compute_file_hash(filepath)

        if actual_hash.lower() == expected_hash.lower():
            results['details'][filename] = {'status': 'PASS'}
            results['passed'] += 1
        else:
            results['details'][filename] = {
                'status': 'FAIL',
                'expected': expected_hash,
                'actual': actual_hash,
            }
            results['failed'] += 1
            results['valid'] = False

    return results


def print_verification_result(result: dict) -> None:
    """Print verification result to console."""
    print("=" * 70)
    print("SOLVEREIGN Proof Pack Verification")
    print("=" * 70)

    if 'error' in result:
        print(f"\nERROR: {result['error']}")
        return

    print(f"\nPlan Version ID: {result['plan_version_id']}")
    print(f"Generated: {result['generated_at']}")
    print()

    for filename, detail in result.get('details', {}).items():
        status = detail['status']
        if status == 'PASS':
            print(f"PASS: {filename}")
        elif status == 'MISSING':
            print(f"FAIL: {filename} - File not found")
        else:
            print(f"FAIL: {filename}")
            print(f"       Expected: {detail['expected']}")
            print(f"       Actual:   {detail['actual']}")

    print()
    print("=" * 70)
    print(f"RESULTS: {result['passed']} PASSED, {result['failed']} FAILED")
    print("=" * 70)

    if result['valid']:
        print("\nVERIFICATION PASSED - All checksums match")
    else:
        print("\nVERIFICATION FAILED - Proof pack may be corrupted or tampered")
