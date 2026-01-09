"""
SOLVEREIGN V4.1 - Driver View Renderer
========================================

Renders driver-specific views from plan_snapshots (DB source of truth).
NOT from Google Sheets.

Output formats:
    - HTML (mobile-friendly, for portal)
    - JSON (for API/frontend consumption)
    - PDF (optional, via HTML-to-PDF conversion)

Key Principle:
    Driver views MUST be generated from plan_snapshots.assignments_snapshot,
    which is immutable and stored in Postgres. This ensures:
    - Audit trail consistency
    - No dependency on external systems at read time
    - Version integrity (snapshot is published, not live)
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, time, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from .models import DriverView

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ShiftInfo:
    """Information about a single shift."""
    shift_date: date
    shift_start: time
    shift_end: time
    route_id: Optional[str] = None
    zone: Optional[str] = None
    vehicle_id: Optional[str] = None
    notes: Optional[str] = None

    @property
    def duration_hours(self) -> float:
        """Calculate shift duration in hours."""
        start_minutes = self.shift_start.hour * 60 + self.shift_start.minute
        end_minutes = self.shift_end.hour * 60 + self.shift_end.minute
        if end_minutes < start_minutes:
            end_minutes += 24 * 60  # Overnight shift
        return (end_minutes - start_minutes) / 60

    @property
    def weekday_name(self) -> str:
        """German weekday name."""
        weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        return weekdays[self.shift_date.weekday()]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "date": self.shift_date.isoformat(),
            "weekday": self.weekday_name,
            "start": self.shift_start.strftime("%H:%M"),
            "end": self.shift_end.strftime("%H:%M"),
            "duration_hours": round(self.duration_hours, 2),
            "route_id": self.route_id,
            "zone": self.zone,
            "vehicle_id": self.vehicle_id,
            "notes": self.notes,
        }


@dataclass
class WeekPlan:
    """Driver's weekly plan."""
    driver_id: str
    driver_name: Optional[str] = None
    week_start: Optional[date] = None
    week_end: Optional[date] = None
    shifts: List[ShiftInfo] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        """Total scheduled hours for the week."""
        return sum(s.duration_hours for s in self.shifts)

    @property
    def shift_count(self) -> int:
        """Number of shifts."""
        return len(self.shifts)

    @property
    def days_working(self) -> int:
        """Number of unique days with shifts."""
        return len(set(s.shift_date for s in self.shifts))

    def get_shifts_by_date(self) -> Dict[date, List[ShiftInfo]]:
        """Group shifts by date."""
        result: Dict[date, List[ShiftInfo]] = {}
        for shift in self.shifts:
            if shift.shift_date not in result:
                result[shift.shift_date] = []
            result[shift.shift_date].append(shift)
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "driver_id": self.driver_id,
            "driver_name": self.driver_name,
            "week_start": self.week_start.isoformat() if self.week_start else None,
            "week_end": self.week_end.isoformat() if self.week_end else None,
            "total_hours": round(self.total_hours, 2),
            "shift_count": self.shift_count,
            "days_working": self.days_working,
            "shifts": [s.to_dict() for s in sorted(self.shifts, key=lambda s: (s.shift_date, s.shift_start))],
        }


@dataclass
class RenderedView:
    """Result of rendering a driver view."""
    driver_id: str
    snapshot_id: str
    format: str  # "html", "json", "pdf"
    content: str  # Rendered content
    content_hash: str  # SHA-256 of content
    render_version: int = 1
    rendered_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def artifact_uri(self) -> str:
        """Generate artifact URI path."""
        return f"views/{self.snapshot_id}/{self.driver_id}/{self.format}"


# =============================================================================
# DRIVER VIEW RENDERER
# =============================================================================

class DriverViewRenderer:
    """
    Renders driver-specific views from plan_snapshots.

    Source: plan_snapshots.assignments_snapshot (immutable DB)
    Output: HTML, JSON, or PDF
    """

    def __init__(self, render_version: int = 1):
        """
        Initialize renderer.

        Args:
            render_version: Version number for rendered views
        """
        self.render_version = render_version

    def extract_driver_plan(
        self,
        assignments_snapshot: Dict[str, Any],
        driver_id: str,
    ) -> WeekPlan:
        """
        Extract a driver's plan from the snapshot.

        Args:
            assignments_snapshot: The assignments_snapshot from plan_snapshots
            driver_id: Driver ID to extract

        Returns:
            WeekPlan with driver's shifts
        """
        plan = WeekPlan(driver_id=driver_id)

        # Parse assignments from snapshot
        # Expected format: {"assignments": [{driver_id, date, start, end, route, zone, ...}]}
        assignments = assignments_snapshot.get("assignments", [])

        if not assignments:
            logger.warning(f"No assignments in snapshot for driver {driver_id}")
            return plan

        # Filter for this driver
        driver_assignments = [a for a in assignments if a.get("driver_id") == driver_id]

        if not driver_assignments:
            logger.info(f"No assignments for driver {driver_id}")
            return plan

        # Get driver name from first assignment if available
        plan.driver_name = driver_assignments[0].get("driver_name")

        # Convert to ShiftInfo objects
        dates = []
        for a in driver_assignments:
            try:
                shift_date = self._parse_date(a.get("date") or a.get("shift_date"))
                if shift_date:
                    dates.append(shift_date)
                    shift = ShiftInfo(
                        shift_date=shift_date,
                        shift_start=self._parse_time(a.get("shift_start") or a.get("start") or "06:00"),
                        shift_end=self._parse_time(a.get("shift_end") or a.get("end") or "14:00"),
                        route_id=a.get("route_id") or a.get("route"),
                        zone=a.get("zone"),
                        vehicle_id=a.get("vehicle_id") or a.get("vehicle"),
                        notes=a.get("notes"),
                    )
                    plan.shifts.append(shift)
            except Exception as e:
                logger.warning(f"Error parsing assignment: {e}")

        # Set week boundaries
        if dates:
            plan.week_start = min(dates)
            plan.week_end = max(dates)

        return plan

    def render_html(
        self,
        plan: WeekPlan,
        snapshot_id: str,
        include_actions: bool = False,
    ) -> RenderedView:
        """
        Render driver plan as mobile-friendly HTML.

        Args:
            plan: WeekPlan to render
            snapshot_id: Snapshot UUID
            include_actions: Whether to include ack buttons (usually False for pre-render)

        Returns:
            RenderedView with HTML content
        """
        # Generate HTML
        shifts_by_date = plan.get_shifts_by_date()

        # Generate day cards
        day_cards = ""
        if plan.week_start and plan.week_end:
            current = plan.week_start
            while current <= plan.week_end:
                day_shifts = shifts_by_date.get(current, [])
                day_cards += self._render_day_card(current, day_shifts)
                current += timedelta(days=1)
        else:
            # No week boundaries, just render what we have
            for shift_date, shifts in sorted(shifts_by_date.items()):
                day_cards += self._render_day_card(shift_date, shifts)

        # Summary
        summary = f"""
        <div class="summary">
            <div class="stat">
                <span class="value">{plan.shift_count}</span>
                <span class="label">Schichten</span>
            </div>
            <div class="stat">
                <span class="value">{plan.days_working}</span>
                <span class="label">Tage</span>
            </div>
            <div class="stat">
                <span class="value">{plan.total_hours:.1f}h</span>
                <span class="label">Stunden</span>
            </div>
        </div>
        """

        # Full HTML
        html = f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wochenplan - {plan.driver_name or plan.driver_id}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f3f4f6;
            padding: 16px;
            max-width: 600px;
            margin: 0 auto;
            line-height: 1.5;
        }}
        .header {{
            text-align: center;
            margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 20px;
            color: #111827;
        }}
        .header .period {{
            color: #6b7280;
            font-size: 14px;
        }}
        .summary {{
            display: flex;
            justify-content: space-around;
            background: white;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .stat {{
            text-align: center;
        }}
        .stat .value {{
            display: block;
            font-size: 24px;
            font-weight: 600;
            color: #2563eb;
        }}
        .stat .label {{
            font-size: 12px;
            color: #6b7280;
        }}
        .day-card {{
            background: white;
            border-radius: 12px;
            margin-bottom: 12px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .day-header {{
            background: #2563eb;
            color: white;
            padding: 12px 16px;
            font-weight: 500;
        }}
        .day-header.free {{
            background: #d1d5db;
            color: #6b7280;
        }}
        .shift {{
            padding: 12px 16px;
            border-bottom: 1px solid #e5e7eb;
        }}
        .shift:last-child {{
            border-bottom: none;
        }}
        .shift-time {{
            font-weight: 600;
            color: #111827;
        }}
        .shift-details {{
            font-size: 14px;
            color: #6b7280;
            margin-top: 4px;
        }}
        .no-shift {{
            padding: 12px 16px;
            color: #9ca3af;
            font-style: italic;
        }}
        .footer {{
            text-align: center;
            color: #9ca3af;
            font-size: 11px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Wochenplan</h1>
        <div class="period">
            {plan.driver_name or plan.driver_id}<br>
            {plan.week_start.strftime('%d.%m.') if plan.week_start else ''} - {plan.week_end.strftime('%d.%m.%Y') if plan.week_end else ''}
        </div>
    </div>

    {summary}

    <div class="days">
        {day_cards}
    </div>

    <div class="footer">
        SOLVEREIGN v4.1 | Snapshot: {snapshot_id[:8]}...
    </div>
</body>
</html>
"""

        # Calculate hash
        content_hash = hashlib.sha256(html.encode()).hexdigest()

        return RenderedView(
            driver_id=plan.driver_id,
            snapshot_id=snapshot_id,
            format="html",
            content=html,
            content_hash=content_hash,
            render_version=self.render_version,
        )

    def render_json(
        self,
        plan: WeekPlan,
        snapshot_id: str,
    ) -> RenderedView:
        """
        Render driver plan as JSON.

        Args:
            plan: WeekPlan to render
            snapshot_id: Snapshot UUID

        Returns:
            RenderedView with JSON content
        """
        data = plan.to_dict()
        data["snapshot_id"] = snapshot_id
        data["render_version"] = self.render_version
        data["rendered_at"] = datetime.utcnow().isoformat()

        content = json.dumps(data, indent=2, ensure_ascii=False)
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        return RenderedView(
            driver_id=plan.driver_id,
            snapshot_id=snapshot_id,
            format="json",
            content=content,
            content_hash=content_hash,
            render_version=self.render_version,
        )

    def render_all_drivers(
        self,
        assignments_snapshot: Dict[str, Any],
        snapshot_id: str,
        format: str = "html",
    ) -> List[RenderedView]:
        """
        Render views for all drivers in a snapshot.

        Args:
            assignments_snapshot: The assignments_snapshot from plan_snapshots
            snapshot_id: Snapshot UUID
            format: Output format ("html" or "json")

        Returns:
            List of RenderedView for each driver
        """
        # Get unique driver IDs
        assignments = assignments_snapshot.get("assignments", [])
        driver_ids = list(set(a.get("driver_id") for a in assignments if a.get("driver_id")))

        logger.info(f"Rendering views for {len(driver_ids)} drivers in snapshot {snapshot_id[:8]}...")

        views = []
        for driver_id in driver_ids:
            plan = self.extract_driver_plan(assignments_snapshot, driver_id)
            if format == "json":
                view = self.render_json(plan, snapshot_id)
            else:
                view = self.render_html(plan, snapshot_id)
            views.append(view)

        return views

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _render_day_card(self, day: date, shifts: List[ShiftInfo]) -> str:
        """Render a single day card."""
        weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][day.weekday()]
        date_str = day.strftime("%d.%m.")

        if not shifts:
            return f"""
            <div class="day-card">
                <div class="day-header free">{weekday}, {date_str}</div>
                <div class="no-shift">Frei</div>
            </div>
            """

        shifts_html = ""
        for shift in sorted(shifts, key=lambda s: s.shift_start):
            details = []
            if shift.route_id:
                details.append(f"Route: {shift.route_id}")
            if shift.zone:
                details.append(f"Zone: {shift.zone}")
            if shift.vehicle_id:
                details.append(f"Fahrzeug: {shift.vehicle_id}")

            shifts_html += f"""
            <div class="shift">
                <div class="shift-time">{shift.shift_start.strftime('%H:%M')} - {shift.shift_end.strftime('%H:%M')} ({shift.duration_hours:.1f}h)</div>
                {'<div class="shift-details">' + ' | '.join(details) + '</div>' if details else ''}
            </div>
            """

        return f"""
        <div class="day-card">
            <div class="day-header">{weekday}, {date_str}</div>
            {shifts_html}
        </div>
        """

    def _parse_date(self, value: Any) -> Optional[date]:
        """Parse date from various formats."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    def _parse_time(self, value: Any) -> time:
        """Parse time from various formats."""
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            try:
                parts = value.split(":")
                return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except (ValueError, IndexError):
                pass
        return time(0, 0)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_renderer(render_version: int = 1) -> DriverViewRenderer:
    """Create a driver view renderer."""
    return DriverViewRenderer(render_version=render_version)


def render_driver_view_from_snapshot(
    snapshot_data: Dict[str, Any],
    driver_id: str,
    snapshot_id: str,
    format: str = "html",
) -> RenderedView:
    """
    Convenience function to render a single driver's view.

    Args:
        snapshot_data: The full snapshot data (or just assignments_snapshot)
        driver_id: Driver ID
        snapshot_id: Snapshot UUID
        format: Output format

    Returns:
        RenderedView
    """
    renderer = create_renderer()

    # Handle both full snapshot and just assignments_snapshot
    if "assignments_snapshot" in snapshot_data:
        assignments = snapshot_data["assignments_snapshot"]
    elif "assignments" in snapshot_data:
        assignments = snapshot_data
    else:
        assignments = {"assignments": []}

    plan = renderer.extract_driver_plan(assignments, driver_id)

    if format == "json":
        return renderer.render_json(plan, snapshot_id)
    else:
        return renderer.render_html(plan, snapshot_id)
