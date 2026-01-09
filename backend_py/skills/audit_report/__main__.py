#!/usr/bin/env python3
"""CLI for Enterprise Audit Report Generator.

Usage:
    python -m backend_py.skills.audit_report generate --tenant <code>
    python -m backend_py.skills.audit_report platform
    python -m backend_py.skills.audit_report compliance --frameworks gdpr,soc2

Exit codes:
    0: PASS - Full audit pack generated successfully
    1: PARTIAL - Some warnings present
    2: FAIL - Some required evidence missing
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from .generator import EnterpriseAuditReportGenerator, AuditReport
from .redaction import OutputMode, verify_customer_safe


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Enterprise Audit Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate audit report for tenant")
    gen_parser.add_argument(
        "--tenant",
        help="Tenant code (optional, omit for platform-wide)",
    )
    gen_parser.add_argument(
        "--output",
        default="ENTERPRISE_PROOF_PACK.zip",
        help="Output file name",
    )
    gen_parser.add_argument(
        "--mode",
        choices=["internal", "customer"],
        default="customer",
        help="Output mode: internal (full) or customer (redacted)",
    )
    gen_parser.add_argument(
        "--dual-output",
        action="store_true",
        help="Generate both internal AND customer versions",
    )
    gen_parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("."),
        help="Directory containing evidence artifacts",
    )
    gen_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory for output files",
    )

    # platform command
    platform_parser = subparsers.add_parser("platform", help="Generate platform-wide report")
    platform_parser.add_argument(
        "--output",
        default="PLATFORM_AUDIT_SUMMARY.zip",
        help="Output file name",
    )
    platform_parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("."),
        help="Directory containing evidence artifacts",
    )

    # compliance command
    compliance_parser = subparsers.add_parser("compliance", help="Generate compliance matrix only")
    compliance_parser.add_argument(
        "--frameworks",
        default="GDPR,SOC2,ISO27001",
        help="Comma-separated list of frameworks",
    )
    compliance_parser.add_argument(
        "--output",
        default="COMPLIANCE_MATRIX.md",
        help="Output file name",
    )

    # verify-redaction command
    verify_parser = subparsers.add_parser("verify-redaction", help="Verify customer-safe pack")
    verify_parser.add_argument(
        "--input",
        required=True,
        help="Audit pack to verify",
    )

    args = parser.parse_args()

    if args.command == "generate":
        asyncio.run(run_generate(args))

    elif args.command == "platform":
        asyncio.run(run_platform(args))

    elif args.command == "compliance":
        run_compliance(args)

    elif args.command == "verify-redaction":
        run_verify_redaction(args)


async def run_generate(args):
    """Generate tenant or platform audit report."""

    output_mode = (
        OutputMode.INTERNAL if args.mode == "internal"
        else OutputMode.CUSTOMER_SAFE
    )

    generator = EnterpriseAuditReportGenerator(
        evidence_dir=args.evidence_dir,
        output_dir=args.output_dir,
    )

    if args.dual_output:
        # Generate both versions
        customer_report = await generator.generate(
            tenant_code=args.tenant,
            output_mode=OutputMode.CUSTOMER_SAFE,
        )
        internal_report = await generator.generate(
            tenant_code=args.tenant,
            output_mode=OutputMode.INTERNAL,
        )
        print_report_summary(customer_report, "Customer-Safe")
        print_report_summary(internal_report, "Internal")
        sys.exit(max(customer_report.exit_code, internal_report.exit_code))
    else:
        report = await generator.generate(
            tenant_code=args.tenant,
            output_mode=output_mode,
        )
        print_report_summary(report, output_mode.value)
        sys.exit(report.exit_code)


async def run_platform(args):
    """Generate platform-wide audit report."""

    generator = EnterpriseAuditReportGenerator(
        evidence_dir=args.evidence_dir,
        output_dir=Path("."),
    )

    report = await generator.generate(
        tenant_code=None,
        output_mode=OutputMode.CUSTOMER_SAFE,
    )

    print_report_summary(report, "Platform")
    sys.exit(report.exit_code)


def run_compliance(args):
    """Generate compliance matrix only."""

    frameworks = [f.strip().upper() for f in args.frameworks.split(",")]

    print(f"Generating compliance matrix for: {frameworks}")

    content = f"""# Compliance Matrix

**Generated**: {datetime.now(timezone.utc).isoformat()}Z
**Frameworks**: {', '.join(frameworks)}

---

"""

    if 'GDPR' in frameworks:
        content += """
## GDPR (General Data Protection Regulation)

| Article | Requirement | Control | Status |
|---------|-------------|---------|--------|
| Art. 5 | Data minimization | RLS Isolation | (run full audit) |
| Art. 25 | Data protection by design | Multi-tenant architecture | (run full audit) |
| Art. 30 | Records of processing | Audit trail | (run full audit) |
| Art. 32 | Security of processing | Encryption + RLS | (run full audit) |
| Art. 33 | Breach notification | Incident detection | (run full audit) |

"""

    if 'SOC2' in frameworks:
        content += """
## SOC 2 Type II

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| CC6.1 | Logical access | RLS + RBAC | (run full audit) |
| CC6.6 | External threats | Replay protection | (run full audit) |
| CC7.2 | System monitoring | Incident triage | (run full audit) |
| CC8.1 | Change management | Migration contract | (run full audit) |

"""

    if 'ISO27001' in frameworks:
        content += """
## ISO 27001:2022

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| A.5.15 | Access control | RLS + Entra ID | (run full audit) |
| A.8.9 | Configuration management | Migration versioning | (run full audit) |
| A.8.15 | Logging | Audit trail | (run full audit) |
| A.8.24 | Cryptography | AES-256-GCM | (run full audit) |

"""

    content += """
---

*Run `python -m backend_py.skills.audit_report generate` for full compliance status.*
"""

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Compliance matrix written to: {args.output}")
    sys.exit(0)


def run_verify_redaction(args):
    """Verify that customer-safe pack contains no sensitive data."""

    import zipfile

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(2)

    all_violations = []

    try:
        with zipfile.ZipFile(input_path, 'r') as zf:
            for name in zf.namelist():
                try:
                    content = zf.read(name).decode('utf-8')
                    result = verify_customer_safe(content)
                    if not result['passed']:
                        for v in result['violations']:
                            all_violations.append({
                                'file': name,
                                **v
                            })
                except Exception:
                    pass  # Skip binary files

    except Exception as e:
        print(f"Error reading ZIP file: {e}", file=sys.stderr)
        sys.exit(2)

    if all_violations:
        print("[X] REDACTION VERIFICATION FAILED!")
        print()
        for v in all_violations:
            print(f"  - {v['file']}: {v['violation']} ({v['matches']} matches)")
        sys.exit(1)
    else:
        print("[OK] Customer-safe pack verified - no sensitive data found")
        sys.exit(0)


def print_report_summary(report: AuditReport, label: str):
    """Print report summary to console."""

    status_marker = {'PASS': '[OK]', 'FAIL': '[X]', 'WARN': '[!]', 'PARTIAL': '[!]'}

    print()
    print("=" * 60)
    print(f"AUDIT REPORT ({label})")
    print("=" * 60)
    print(f"Report ID: {report.report_id}")
    print(f"Status: {status_marker.get(report.overall_status, '')} {report.overall_status}")
    print(f"Evidence: {report.pass_count} PASS, {report.warn_count} WARN, {report.fail_count} FAIL")
    print()
    print("Outputs:")
    print(f"  - {report.summary_path}")
    print(f"  - {report.compliance_path}")
    print(f"  - {report.evidence_zip_path}")
    print()


if __name__ == "__main__":
    main()
