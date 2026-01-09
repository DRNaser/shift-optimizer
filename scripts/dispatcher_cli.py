#!/usr/bin/env python3
"""
Dispatcher CLI - Gate AB Implementation

Minimum viable operations interface for Wien Pilot dispatchers.
Provides complete weekly workflow without DB/direct SQL access.

Capabilities:
1. list-runs     - Show latest runs with status
2. show-run      - Open evidence pack + audit summary
3. request-repair - One-click sick-call repair
4. publish       - Publish plan (requires approval)
5. lock          - Lock plan for export (requires approval)
6. status        - Show current system status

Exit codes:
- 0: Success
- 1: Operation failed
- 2: Blocked by gate
"""

import argparse
import json
import os
import sys
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class RunStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"


@dataclass
class RunSummary:
    """Summary of a solver run."""
    run_id: str
    week_id: str
    timestamp: str
    status: RunStatus
    tenant_code: str
    site_code: str
    headcount: int
    coverage_percent: float
    audit_pass_count: int
    audit_total: int
    evidence_path: Optional[str]
    kpi_drift_status: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass
class RepairRequest:
    """Sick-call repair request."""
    request_id: str
    timestamp: str
    requester_id: str
    week_id: str
    site_code: str
    driver_id: str
    driver_name: str
    absence_type: str  # sick, vacation, no_show
    affected_tours: List[str]
    urgency: str  # critical, high, normal
    notes: str = ""


class DispatcherCLI:
    """
    CLI interface for dispatcher operations.

    This provides a verified procedure for completing the weekly workflow
    without requiring direct database or SQL access.
    """

    RUNS_DIR = PROJECT_ROOT / "runs"
    EVIDENCE_DIR = PROJECT_ROOT / "artifacts" / "evidence"
    REPAIR_DIR = PROJECT_ROOT / "artifacts" / "repair_requests"

    def __init__(self, tenant_code: str = "lts", site_code: str = "wien"):
        self.tenant_code = tenant_code
        self.site_code = site_code
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Ensure required directories exist."""
        self.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        self.REPAIR_DIR.mkdir(parents=True, exist_ok=True)

    def _load_runs(self) -> List[RunSummary]:
        """Load run summaries from artifacts."""
        runs = []
        runs_pattern = self.RUNS_DIR / "*.json"

        for run_file in sorted(self.RUNS_DIR.glob("*.json"), reverse=True):
            try:
                with open(run_file) as f:
                    data = json.load(f)
                    run = RunSummary(
                        run_id=data.get("run_id", run_file.stem),
                        week_id=data.get("week_id", "unknown"),
                        timestamp=data.get("timestamp", ""),
                        status=RunStatus(data.get("status", "PENDING")),
                        tenant_code=data.get("tenant_code", self.tenant_code),
                        site_code=data.get("site_code", self.site_code),
                        headcount=data.get("headcount", 0),
                        coverage_percent=data.get("coverage_percent", 0),
                        audit_pass_count=data.get("audit_pass_count", 0),
                        audit_total=data.get("audit_total", 7),
                        evidence_path=data.get("evidence_path"),
                        kpi_drift_status=data.get("kpi_drift_status", "UNKNOWN"),
                        notes=data.get("notes", "")
                    )
                    if run.site_code == self.site_code:
                        runs.append(run)
            except Exception as e:
                print(f"Warning: Could not load {run_file}: {e}", file=sys.stderr)

        return runs[:20]  # Return last 20 runs

    def list_runs(self, limit: int = 10) -> int:
        """
        List latest runs with status.

        Returns exit code: 0 = success
        """
        runs = self._load_runs()[:limit]

        if not runs:
            print("No runs found.")
            print(f"\nTo create a run, use: python scripts/run_parallel_week.py --week 2026-W03")
            return 0

        # Header
        print(f"\n{'='*80}")
        print(f"LATEST RUNS - {self.tenant_code.upper()}/{self.site_code.upper()}")
        print(f"{'='*80}\n")

        # Status legend
        print("Status: ✅ PASS | ⚠️  WARN | ❌ FAIL | 🚫 BLOCKED | ⏳ PENDING\n")

        # Table header
        print(f"{'Run ID':<12} {'Week':<10} {'Status':<10} {'Drivers':<8} {'Coverage':<10} {'Audits':<8} {'Drift':<10}")
        print("-" * 80)

        for run in runs:
            status_icon = {
                RunStatus.PASS: "✅",
                RunStatus.WARN: "⚠️ ",
                RunStatus.FAIL: "❌",
                RunStatus.BLOCKED: "🚫",
                RunStatus.PENDING: "⏳"
            }.get(run.status, "?")

            print(f"{run.run_id:<12} {run.week_id:<10} {status_icon} {run.status.value:<6} "
                  f"{run.headcount:<8} {run.coverage_percent:>6.1f}%   "
                  f"{run.audit_pass_count}/{run.audit_total:<5} {run.kpi_drift_status:<10}")

        print("-" * 80)
        print(f"\nShowing {len(runs)} of {len(self._load_runs())} runs")
        print(f"\nUse 'dispatcher_cli.py show-run <run_id>' for details")

        return 0

    def show_run(self, run_id: str) -> int:
        """
        Show detailed run information including evidence and audit summary.

        Returns exit code: 0 = success, 1 = not found
        """
        runs = self._load_runs()
        run = next((r for r in runs if r.run_id == run_id), None)

        if not run:
            print(f"Run not found: {run_id}")
            print(f"\nAvailable runs:")
            for r in runs[:5]:
                print(f"  - {r.run_id}")
            return 1

        # Header
        print(f"\n{'='*80}")
        print(f"RUN DETAILS: {run_id}")
        print(f"{'='*80}\n")

        # Basic info
        print(f"Week ID:     {run.week_id}")
        print(f"Timestamp:   {run.timestamp}")
        print(f"Site:        {run.tenant_code}/{run.site_code}")
        print(f"Status:      {run.status.value}")

        # KPIs
        print(f"\n--- KPIs ---")
        print(f"Headcount:   {run.headcount} drivers")
        print(f"Coverage:    {run.coverage_percent:.1f}%")
        print(f"KPI Drift:   {run.kpi_drift_status}")

        # Audit summary
        print(f"\n--- Audit Summary ---")
        print(f"Passed:      {run.audit_pass_count}/{run.audit_total}")

        audit_checks = [
            ("Coverage", "100% tours assigned"),
            ("Overlap", "No concurrent tours"),
            ("Rest", ">=11h between days"),
            ("Span Regular", "<=14h for 1er/2er-reg"),
            ("Span Split", "<=16h for split/3er"),
            ("Fatigue", "No 3er→3er"),
            ("Reproducibility", "Deterministic")
        ]

        for i, (name, desc) in enumerate(audit_checks):
            status = "✅" if i < run.audit_pass_count else "❌"
            print(f"  {status} {name}: {desc}")

        # Evidence
        print(f"\n--- Evidence ---")
        if run.evidence_path:
            evidence_path = Path(run.evidence_path)
            if evidence_path.exists():
                print(f"Path: {run.evidence_path}")
                # List evidence files
                if evidence_path.is_dir():
                    for f in sorted(evidence_path.iterdir())[:10]:
                        size = f.stat().st_size if f.is_file() else 0
                        print(f"  - {f.name} ({size:,} bytes)")
            else:
                print(f"Path: {run.evidence_path} (NOT FOUND)")
        else:
            print("No evidence pack available")

        # Notes
        if run.notes:
            print(f"\n--- Notes ---")
            print(run.notes)

        # Actions
        print(f"\n--- Available Actions ---")
        if run.status == RunStatus.PASS:
            print(f"  • Publish: dispatcher_cli.py publish {run_id} --approver <your_id> --reason '<reason>'")
            print(f"  • Lock:    dispatcher_cli.py lock {run_id} --approver <your_id> --reason '<reason>'")
        elif run.status == RunStatus.WARN:
            print(f"  • Review warnings before publish")
            print(f"  • Publish with override: dispatcher_cli.py publish {run_id} --approver <your_id> --reason '<reason>' --override-warn")
        else:
            print(f"  • Run cannot be published (status: {run.status.value})")
            print(f"  • Request repair if needed: dispatcher_cli.py request-repair --week {run.week_id}")

        return 0

    def request_repair(
        self,
        week_id: str,
        driver_id: str,
        driver_name: str,
        absence_type: str,
        affected_tours: List[str],
        requester_id: str,
        urgency: str = "normal",
        notes: str = ""
    ) -> int:
        """
        Request sick-call repair.

        Returns exit code: 0 = success, 1 = failed
        """
        # Generate request ID
        timestamp = datetime.now(timezone.utc)
        request_id = f"REP-{timestamp.strftime('%Y%m%d%H%M%S')}"

        request = RepairRequest(
            request_id=request_id,
            timestamp=timestamp.isoformat(),
            requester_id=requester_id,
            week_id=week_id,
            site_code=self.site_code,
            driver_id=driver_id,
            driver_name=driver_name,
            absence_type=absence_type,
            affected_tours=affected_tours,
            urgency=urgency,
            notes=notes
        )

        # Save request
        request_file = self.REPAIR_DIR / f"{request_id}.json"
        with open(request_file, "w") as f:
            json.dump(asdict(request), f, indent=2)

        # Print confirmation
        print(f"\n{'='*60}")
        print(f"REPAIR REQUEST CREATED")
        print(f"{'='*60}\n")
        print(f"Request ID:    {request_id}")
        print(f"Week:          {week_id}")
        print(f"Driver:        {driver_name} ({driver_id})")
        print(f"Absence Type:  {absence_type}")
        print(f"Urgency:       {urgency}")
        print(f"Affected Tours: {', '.join(affected_tours)}")
        if notes:
            print(f"Notes:         {notes}")

        print(f"\nRequest saved to: {request_file}")

        # Next steps
        print(f"\n--- Next Steps ---")
        print(f"1. Run repair solver: python scripts/run_repair.py --request {request_id}")
        print(f"2. Review repair result")
        print(f"3. Approve and apply repair")

        return 0

    def publish(
        self,
        run_id: str,
        approver_id: str,
        approver_role: str,
        reason: str,
        override_warn: bool = False
    ) -> int:
        """
        Publish a plan (requires approval).

        Returns exit code: 0 = success, 1 = failed, 2 = blocked
        """
        from backend_py.api.services.publish_gate import (
            PublishGateService,
            ApprovalRecord,
            PublishGateStatus
        )

        # Load run
        runs = self._load_runs()
        run = next((r for r in runs if r.run_id == run_id), None)

        if not run:
            print(f"Run not found: {run_id}")
            return 1

        # Check status
        if run.status == RunStatus.FAIL or run.status == RunStatus.BLOCKED:
            print(f"Cannot publish run with status: {run.status.value}")
            return 2

        if run.status == RunStatus.WARN and not override_warn:
            print(f"Run has warnings. Use --override-warn to publish anyway.")
            return 2

        # Compute evidence hash
        evidence_hash = "placeholder"
        if run.evidence_path:
            evidence_path = Path(run.evidence_path)
            if evidence_path.exists():
                # Simple hash of evidence directory
                hasher = hashlib.sha256()
                if evidence_path.is_dir():
                    for f in sorted(evidence_path.iterdir()):
                        if f.is_file():
                            hasher.update(f.read_bytes())
                evidence_hash = f"sha256:{hasher.hexdigest()}"

        # Create approval
        approval = ApprovalRecord(
            approver_id=approver_id,
            approver_role=approver_role,
            reason=reason
        )

        # Check publish gate
        service = PublishGateService()
        result = service.check_publish_allowed(
            tenant_code=self.tenant_code,
            site_code=self.site_code,
            pack="roster",
            plan_version_id=int(run_id.split("-")[-1]) if "-" in run_id else hash(run_id) % 10000,
            evidence_hash=evidence_hash,
            approval=approval
        )

        if not result.allowed:
            print(f"\n❌ PUBLISH BLOCKED")
            print(f"Reason: {result.blocked_reason}")
            return 2

        # Success
        print(f"\n{'='*60}")
        print(f"✅ PUBLISH APPROVED")
        print(f"{'='*60}\n")
        print(f"Run ID:        {run_id}")
        print(f"Week:          {run.week_id}")
        print(f"Approver:      {approver_id} ({approver_role})")
        print(f"Reason:        {reason}")
        print(f"Evidence Hash: {evidence_hash[:40]}...")
        print(f"Audit Event:   {result.audit_event_id}")

        # Update run status
        run_file = self.RUNS_DIR / f"{run_id}.json"
        if run_file.exists():
            with open(run_file) as f:
                run_data = json.load(f)
            run_data["published"] = True
            run_data["published_at"] = datetime.now(timezone.utc).isoformat()
            run_data["published_by"] = approver_id
            with open(run_file, "w") as f:
                json.dump(run_data, f, indent=2)

        print(f"\nPlan is now available for lock.")
        print(f"Lock command: dispatcher_cli.py lock {run_id} --approver {approver_id} --reason '<reason>'")

        return 0

    def lock(
        self,
        run_id: str,
        approver_id: str,
        approver_role: str,
        reason: str
    ) -> int:
        """
        Lock a published plan for export.

        Returns exit code: 0 = success, 1 = failed, 2 = blocked
        """
        from backend_py.api.services.publish_gate import (
            PublishGateService,
            ApprovalRecord,
            PublishGateStatus
        )

        # Load run
        runs = self._load_runs()
        run = next((r for r in runs if r.run_id == run_id), None)

        if not run:
            print(f"Run not found: {run_id}")
            return 1

        # Compute evidence hash
        evidence_hash = "placeholder"
        if run.evidence_path:
            evidence_path = Path(run.evidence_path)
            if evidence_path.exists():
                hasher = hashlib.sha256()
                if evidence_path.is_dir():
                    for f in sorted(evidence_path.iterdir()):
                        if f.is_file():
                            hasher.update(f.read_bytes())
                evidence_hash = f"sha256:{hasher.hexdigest()}"

        # Create approval
        approval = ApprovalRecord(
            approver_id=approver_id,
            approver_role=approver_role,
            reason=reason
        )

        # Check lock gate
        service = PublishGateService()
        result = service.check_lock_allowed(
            tenant_code=self.tenant_code,
            site_code=self.site_code,
            pack="roster",
            plan_version_id=int(run_id.split("-")[-1]) if "-" in run_id else hash(run_id) % 10000,
            evidence_hash=evidence_hash,
            approval=approval
        )

        if not result.allowed:
            print(f"\n❌ LOCK BLOCKED")
            print(f"Reason: {result.blocked_reason}")
            return 2

        # Success
        print(f"\n{'='*60}")
        print(f"🔒 PLAN LOCKED")
        print(f"{'='*60}\n")
        print(f"Run ID:        {run_id}")
        print(f"Week:          {run.week_id}")
        print(f"Approver:      {approver_id} ({approver_role})")
        print(f"Reason:        {reason}")
        print(f"Evidence Hash: {evidence_hash[:40]}...")
        print(f"Audit Event:   {result.audit_event_id}")

        # Update run status
        run_file = self.RUNS_DIR / f"{run_id}.json"
        if run_file.exists():
            with open(run_file) as f:
                run_data = json.load(f)
            run_data["locked"] = True
            run_data["locked_at"] = datetime.now(timezone.utc).isoformat()
            run_data["locked_by"] = approver_id
            with open(run_file, "w") as f:
                json.dump(run_data, f, indent=2)

        print(f"\n✅ Plan is now LOCKED and ready for export.")
        print(f"The plan is immutable and can be exported to the dispatch system.")

        return 0

    def status(self) -> int:
        """
        Show current system status.

        Returns exit code: 0
        """
        from backend_py.api.services.publish_gate import PublishGateService

        print(f"\n{'='*60}")
        print(f"SYSTEM STATUS - {self.tenant_code.upper()}/{self.site_code.upper()}")
        print(f"{'='*60}\n")

        # Check publish gate
        try:
            service = PublishGateService()
            kill_switch = service.is_kill_switch_active()
            print(f"Kill Switch:     {'🚫 ACTIVE' if kill_switch else '✅ Inactive'}")

            site_config = service._get_site_config(self.tenant_code, self.site_code, "roster")
            publish_enabled = site_config.get("publish_enabled", False)
            lock_enabled = site_config.get("lock_enabled", False)
            shadow_only = site_config.get("shadow_mode_only", True)

            print(f"Publish Enabled: {'✅ Yes' if publish_enabled else '❌ No'}")
            print(f"Lock Enabled:    {'✅ Yes' if lock_enabled else '❌ No'}")
            print(f"Shadow Mode:     {'⚠️  Active' if shadow_only else '✅ Disabled'}")
        except Exception as e:
            print(f"Publish Gate:    ⚠️  Error loading config: {e}")

        # Latest run
        print(f"\n--- Latest Run ---")
        runs = self._load_runs()
        if runs:
            latest = runs[0]
            status_icon = {
                RunStatus.PASS: "✅",
                RunStatus.WARN: "⚠️ ",
                RunStatus.FAIL: "❌",
                RunStatus.BLOCKED: "🚫",
                RunStatus.PENDING: "⏳"
            }.get(latest.status, "?")
            print(f"Run ID:    {latest.run_id}")
            print(f"Week:      {latest.week_id}")
            print(f"Status:    {status_icon} {latest.status.value}")
            print(f"Timestamp: {latest.timestamp}")
        else:
            print("No runs available")

        # Pending repairs
        print(f"\n--- Pending Repairs ---")
        repair_files = list(self.REPAIR_DIR.glob("*.json"))
        if repair_files:
            print(f"{len(repair_files)} pending repair request(s)")
            for f in repair_files[:3]:
                print(f"  - {f.stem}")
        else:
            print("No pending repairs")

        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Dispatcher CLI for Wien Pilot operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dispatcher_cli.py list-runs
  dispatcher_cli.py show-run RUN-20260115-001
  dispatcher_cli.py request-repair --week 2026-W03 --driver D001 --name "Max Mustermann" --type sick --tours T1,T2
  dispatcher_cli.py publish RUN-001 --approver disp001 --role dispatcher --reason "Approved after review"
  dispatcher_cli.py lock RUN-001 --approver ops001 --role ops_lead --reason "Ready for export"
  dispatcher_cli.py status
        """
    )

    parser.add_argument("--tenant", default="lts", help="Tenant code (default: lts)")
    parser.add_argument("--site", default="wien", help="Site code (default: wien)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # list-runs
    list_parser = subparsers.add_parser("list-runs", help="List latest runs")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of runs to show")

    # show-run
    show_parser = subparsers.add_parser("show-run", help="Show run details")
    show_parser.add_argument("run_id", help="Run ID to show")

    # request-repair
    repair_parser = subparsers.add_parser("request-repair", help="Request sick-call repair")
    repair_parser.add_argument("--week", required=True, help="Week ID (e.g., 2026-W03)")
    repair_parser.add_argument("--driver", required=True, help="Driver ID")
    repair_parser.add_argument("--name", required=True, help="Driver name")
    repair_parser.add_argument("--type", required=True, choices=["sick", "vacation", "no_show"], help="Absence type")
    repair_parser.add_argument("--tours", required=True, help="Affected tour IDs (comma-separated)")
    repair_parser.add_argument("--requester", required=True, help="Your user ID")
    repair_parser.add_argument("--urgency", default="normal", choices=["critical", "high", "normal"], help="Urgency level")
    repair_parser.add_argument("--notes", default="", help="Additional notes")

    # publish
    publish_parser = subparsers.add_parser("publish", help="Publish a plan")
    publish_parser.add_argument("run_id", help="Run ID to publish")
    publish_parser.add_argument("--approver", required=True, help="Your user ID")
    publish_parser.add_argument("--role", required=True, choices=["dispatcher", "ops_lead", "platform_admin"], help="Your role")
    publish_parser.add_argument("--reason", required=True, help="Approval reason (min 10 chars)")
    publish_parser.add_argument("--override-warn", action="store_true", help="Override WARN status")

    # lock
    lock_parser = subparsers.add_parser("lock", help="Lock a published plan")
    lock_parser.add_argument("run_id", help="Run ID to lock")
    lock_parser.add_argument("--approver", required=True, help="Your user ID")
    lock_parser.add_argument("--role", required=True, choices=["dispatcher", "ops_lead", "platform_admin"], help="Your role")
    lock_parser.add_argument("--reason", required=True, help="Lock reason (min 10 chars)")

    # status
    status_parser = subparsers.add_parser("status", help="Show system status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    cli = DispatcherCLI(tenant_code=args.tenant, site_code=args.site)

    if args.command == "list-runs":
        return cli.list_runs(limit=args.limit)

    elif args.command == "show-run":
        return cli.show_run(args.run_id)

    elif args.command == "request-repair":
        tours = [t.strip() for t in args.tours.split(",")]
        return cli.request_repair(
            week_id=args.week,
            driver_id=args.driver,
            driver_name=args.name,
            absence_type=args.type,
            affected_tours=tours,
            requester_id=args.requester,
            urgency=args.urgency,
            notes=args.notes
        )

    elif args.command == "publish":
        return cli.publish(
            run_id=args.run_id,
            approver_id=args.approver,
            approver_role=args.role,
            reason=args.reason,
            override_warn=args.override_warn
        )

    elif args.command == "lock":
        return cli.lock(
            run_id=args.run_id,
            approver_id=args.approver,
            approver_role=args.role,
            reason=args.reason
        )

    elif args.command == "status":
        return cli.status()

    return 0


if __name__ == "__main__":
    sys.exit(main())
