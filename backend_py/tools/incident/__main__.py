#!/usr/bin/env python3
"""
Incident CLI - Structured incident management for Guardian Context Tree.

Usage:
    python -m backend_py.tools.incident create --type security --severity S1 --summary "RLS leak detected"
    python -m backend_py.tools.incident resolve INC-20260107-ABC123
    python -m backend_py.tools.incident list
    python -m backend_py.tools.incident list --active
    python -m backend_py.tools.incident stale INC-20260107-ABC123

Exit Codes:
    0 - Success
    1 - Validation error
    2 - Incident not found
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import secrets
import string

# Paths
REPO_ROOT = Path(__file__).parent.parent.parent.parent
STATE_DIR = REPO_ROOT / ".claude" / "state"
INCIDENTS_FILE = STATE_DIR / "active-incidents.json"

# Valid values
VALID_TYPES = ["security", "perf", "stability", "quality"]
VALID_SEVERITIES = ["S0", "S1", "S2", "S3"]
VALID_STATUSES = ["new", "active", "investigating", "mitigated", "resolved", "stale"]


def generate_incident_id() -> str:
    """Generate unique incident ID: INC-YYYYMMDD-XXXXXX"""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_str = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"INC-{date_str}-{random_str}"


def load_incidents() -> dict:
    """Load incidents from file."""
    if not INCIDENTS_FILE.exists():
        return {"incidents": []}
    try:
        with open(INCIDENTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"incidents": []}


def save_incidents(data: dict) -> None:
    """Save incidents to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(INCIDENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def cmd_create(args) -> int:
    """Create a new incident."""
    # Validate inputs
    if args.type not in VALID_TYPES:
        print(f"ERROR: Invalid type '{args.type}'. Must be one of: {VALID_TYPES}")
        return 1
    if args.severity not in VALID_SEVERITIES:
        print(f"ERROR: Invalid severity '{args.severity}'. Must be one of: {VALID_SEVERITIES}")
        return 1

    # Generate ID and create incident
    incident_id = generate_incident_id()
    now = datetime.now(timezone.utc).isoformat()

    incident = {
        "id": incident_id,
        "type": args.type,
        "severity": args.severity,
        "status": "new",
        "tenant_id": args.tenant,
        "summary": args.summary,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "assigned_to": args.assignee,
        "root_cause": None,
        "evidence": [],
        "timeline": [
            {
                "timestamp": now,
                "action": f"Incident created via CLI (type={args.type}, severity={args.severity})",
                "actor": args.actor or "cli"
            }
        ]
    }

    # Load and save
    data = load_incidents()
    data["incidents"].append(incident)
    save_incidents(data)

    print(f"Created incident: {incident_id}")
    print(f"  Type: {args.type}")
    print(f"  Severity: {args.severity}")
    print(f"  Summary: {args.summary}")

    # Warn about stop-the-line
    if args.severity in ("S0", "S1"):
        print(f"\n⚠️  WARNING: {args.severity} incident triggers STOP-THE-LINE!")
        print("    All other work blocked until resolved.")

    return 0


def cmd_resolve(args) -> int:
    """Resolve an incident."""
    data = load_incidents()
    found = False

    for incident in data["incidents"]:
        if incident["id"] == args.incident_id:
            found = True
            if incident["status"] == "resolved":
                print(f"Incident {args.incident_id} is already resolved.")
                return 0

            now = datetime.now(timezone.utc).isoformat()
            incident["status"] = "resolved"
            incident["resolved_at"] = now
            incident["updated_at"] = now
            if args.root_cause:
                incident["root_cause"] = args.root_cause
            incident["timeline"].append({
                "timestamp": now,
                "action": f"Resolved: {args.root_cause or 'No root cause provided'}",
                "actor": args.actor or "cli"
            })
            break

    if not found:
        print(f"ERROR: Incident {args.incident_id} not found.")
        return 2

    save_incidents(data)
    print(f"Resolved incident: {args.incident_id}")
    return 0


def cmd_stale(args) -> int:
    """Mark an incident as stale (no longer blocking)."""
    data = load_incidents()
    found = False

    for incident in data["incidents"]:
        if incident["id"] == args.incident_id:
            found = True
            now = datetime.now(timezone.utc).isoformat()
            old_status = incident["status"]
            incident["status"] = "stale"
            incident["updated_at"] = now
            incident["timeline"].append({
                "timestamp": now,
                "action": f"Marked stale (was: {old_status})",
                "actor": args.actor or "cli"
            })
            break

    if not found:
        print(f"ERROR: Incident {args.incident_id} not found.")
        return 2

    save_incidents(data)
    print(f"Marked incident as stale: {args.incident_id}")
    print("  Note: Stale incidents do NOT trigger stop-the-line.")
    return 0


def cmd_update(args) -> int:
    """Update an incident's status."""
    if args.status not in VALID_STATUSES:
        print(f"ERROR: Invalid status '{args.status}'. Must be one of: {VALID_STATUSES}")
        return 1

    data = load_incidents()
    found = False

    for incident in data["incidents"]:
        if incident["id"] == args.incident_id:
            found = True
            now = datetime.now(timezone.utc).isoformat()
            old_status = incident["status"]
            incident["status"] = args.status
            incident["updated_at"] = now
            if args.status == "resolved":
                incident["resolved_at"] = now
            incident["timeline"].append({
                "timestamp": now,
                "action": f"Status changed: {old_status} → {args.status}",
                "actor": args.actor or "cli"
            })
            break

    if not found:
        print(f"ERROR: Incident {args.incident_id} not found.")
        return 2

    save_incidents(data)
    print(f"Updated incident {args.incident_id}: status → {args.status}")
    return 0


def cmd_list(args) -> int:
    """List incidents."""
    data = load_incidents()
    incidents = data.get("incidents", [])

    if args.active:
        incidents = [i for i in incidents if i["status"] not in ("resolved", "stale", "mitigated")]

    if args.type:
        incidents = [i for i in incidents if i.get("type") == args.type]

    if not incidents:
        print("No incidents found.")
        return 0

    # Print table
    print(f"{'ID':<25} {'Type':<10} {'Sev':<4} {'Status':<13} {'Summary':<40}")
    print("-" * 95)
    for inc in incidents:
        inc_id = inc.get("id", "N/A")
        inc_type = inc.get("type", "N/A")
        severity = inc.get("severity", "N/A")
        status = inc.get("status", "N/A")
        summary = (inc.get("summary", "") or "")[:40]
        print(f"{inc_id:<25} {inc_type:<10} {severity:<4} {status:<13} {summary}")

    print(f"\nTotal: {len(incidents)} incident(s)")
    return 0


def cmd_show(args) -> int:
    """Show details of a specific incident."""
    data = load_incidents()

    for incident in data.get("incidents", []):
        if incident["id"] == args.incident_id:
            print(json.dumps(incident, indent=2))
            return 0

    print(f"ERROR: Incident {args.incident_id} not found.")
    return 2


def main():
    parser = argparse.ArgumentParser(
        description="Incident CLI - Structured incident management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Create security incident:
    python -m backend_py.tools.incident create --type security --severity S1 --summary "RLS leak in tenant isolation"

  Create performance incident:
    python -m backend_py.tools.incident create --type perf --severity S2 --summary "Solver timeout > 120s"

  Resolve incident:
    python -m backend_py.tools.incident resolve INC-20260107-ABC123 --root-cause "Fixed RLS policy"

  Mark as stale (stops blocking):
    python -m backend_py.tools.incident stale INC-20260107-ABC123

  List active incidents:
    python -m backend_py.tools.incident list --active

  List by type:
    python -m backend_py.tools.incident list --type security
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # create
    create_parser = subparsers.add_parser("create", help="Create a new incident")
    create_parser.add_argument("--type", "-t", required=True, choices=VALID_TYPES, help="Incident type")
    create_parser.add_argument("--severity", "-s", required=True, choices=VALID_SEVERITIES, help="Severity level")
    create_parser.add_argument("--summary", "-m", required=True, help="Brief description")
    create_parser.add_argument("--tenant", default=None, help="Affected tenant ID (null for platform-wide)")
    create_parser.add_argument("--assignee", default=None, help="Incident commander email/ID")
    create_parser.add_argument("--actor", default=None, help="Who created this incident")

    # resolve
    resolve_parser = subparsers.add_parser("resolve", help="Resolve an incident")
    resolve_parser.add_argument("incident_id", help="Incident ID to resolve")
    resolve_parser.add_argument("--root-cause", "-r", help="Root cause description")
    resolve_parser.add_argument("--actor", default=None, help="Who resolved this")

    # stale
    stale_parser = subparsers.add_parser("stale", help="Mark incident as stale (no longer blocking)")
    stale_parser.add_argument("incident_id", help="Incident ID to mark stale")
    stale_parser.add_argument("--actor", default=None, help="Who marked this stale")

    # update
    update_parser = subparsers.add_parser("update", help="Update incident status")
    update_parser.add_argument("incident_id", help="Incident ID to update")
    update_parser.add_argument("--status", required=True, choices=VALID_STATUSES, help="New status")
    update_parser.add_argument("--actor", default=None, help="Who made this change")

    # list
    list_parser = subparsers.add_parser("list", help="List incidents")
    list_parser.add_argument("--active", action="store_true", help="Only show active (non-resolved, non-stale)")
    list_parser.add_argument("--type", choices=VALID_TYPES, help="Filter by type")

    # show
    show_parser = subparsers.add_parser("show", help="Show incident details")
    show_parser.add_argument("incident_id", help="Incident ID to show")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "create": cmd_create,
        "resolve": cmd_resolve,
        "stale": cmd_stale,
        "update": cmd_update,
        "list": cmd_list,
        "show": cmd_show,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
