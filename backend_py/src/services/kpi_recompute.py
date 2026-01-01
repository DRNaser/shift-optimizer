from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

EPS_HOURS = 0.01
DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_hours(value: str) -> float:
    if not value:
        return 0.0
    s = value.strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _detect_delimiter(header_line: str) -> str:
    if header_line.count(";") >= header_line.count(","):
        return ";"
    return ","


def _iter_rows(csv_path: Path) -> Iterable[dict]:
    with csv_path.open("r", encoding="utf-8-sig") as f:
        header = f.readline()
        if not header:
            return []
        delimiter = _detect_delimiter(header)
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delimiter)
        return list(reader)


def _aggregate_matrix_rows(rows: list[dict]) -> dict:
    drivers_raw = 0
    drivers_active = 0
    fte_active = 0
    pt_active = 0
    total_hours = 0.0
    pt_hours_total = 0.0
    active_day_set: set[str] = set()
    fte_hours = []
    driver_hours = []

    for row in rows:
        drivers_raw += 1
        hours = _parse_hours(row.get("Weekly Hours", "") or "")
        worked_days = 0
        for day in DAY_ORDER:
            if (row.get(day) or "").strip():
                worked_days += 1
                active_day_set.add(day)

        if hours <= EPS_HOURS or worked_days == 0:
            continue

        drivers_active += 1
        total_hours += hours
        driver_hours.append(hours)

        dtype = (row.get("Type") or "").strip().upper()
        if dtype == "FTE":
            fte_active += 1
            fte_hours.append(hours)
        elif dtype == "PT":
            pt_active += 1
            pt_hours_total += hours

    return {
        "drivers_raw": drivers_raw,
        "drivers_active": drivers_active,
        "drivers_fte": fte_active,
        "drivers_pt": pt_active,
        "total_hours": total_hours,
        "pt_hours_total": pt_hours_total,
        "fte_hours": fte_hours,
        "driver_hours": driver_hours,
        "active_days": sorted(active_day_set, key=lambda d: DAY_ORDER.index(d)),
    }


def _aggregate_duty_rows(rows: list[dict]) -> dict:
    drivers = {}
    active_day_set: set[str] = set()

    for row in rows:
        driver_id = (row.get("driver_id") or "").strip()
        if not driver_id:
            continue
        day = (row.get("day") or "").strip()
        if day:
            active_day_set.add(day)
        hours = _parse_hours(row.get("hours", "") or "")
        dtype = "UNKNOWN"
        upper_id = driver_id.upper()
        if "FTE" in upper_id:
            dtype = "FTE"
        elif "PT" in upper_id:
            dtype = "PT"

        entry = drivers.setdefault(driver_id, {"hours": 0.0, "type": dtype})
        entry["hours"] = max(entry["hours"], hours)
        if entry["type"] == "UNKNOWN":
            entry["type"] = dtype

    drivers_raw = len(drivers)
    drivers_active = 0
    fte_active = 0
    pt_active = 0
    total_hours = 0.0
    pt_hours_total = 0.0
    fte_hours = []
    driver_hours = []

    for info in drivers.values():
        hours = info["hours"]
        if hours <= EPS_HOURS:
            continue
        drivers_active += 1
        total_hours += hours
        driver_hours.append(hours)
        if info["type"] == "FTE":
            fte_active += 1
            fte_hours.append(hours)
        elif info["type"] == "PT":
            pt_active += 1
            pt_hours_total += hours

    return {
        "drivers_raw": drivers_raw,
        "drivers_active": drivers_active,
        "drivers_fte": fte_active,
        "drivers_pt": pt_active,
        "total_hours": total_hours,
        "pt_hours_total": pt_hours_total,
        "fte_hours": fte_hours,
        "driver_hours": driver_hours,
        "active_days": sorted(active_day_set, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 999),
    }


def recompute_kpis_from_roster(csv_path: Path, active_days: list[str] | None = None) -> dict:
    rows = _iter_rows(csv_path)
    if not rows:
        return {
            "drivers_total": 0,
            "drivers_fte": 0,
            "drivers_pt": 0,
            "total_hours": 0.0,
            "fte_hours_min": 0.0,
            "fte_hours_max": 0.0,
            "fte_hours_avg": 0.0,
            "pt_hours_total": 0.0,
            "pt_share_hours_pct": 0.0,
            "active_days": [],
            "active_days_count": 0,
            "low_util_hours_threshold": 0.0,
            "low_util_share_hours_pct": 0.0,
            "fte_under_util_count": 0,
            "fte_under_util_pct": 0.0,
        }

    header_keys = {k.lower() for k in rows[0].keys()}
    if "driver id" in header_keys or "weekly hours" in header_keys:
        agg = _aggregate_matrix_rows(rows)
    else:
        agg = _aggregate_duty_rows(rows)

    active_days_list = active_days or agg["active_days"]
    active_days_count = len(active_days_list)
    target_hours = round(active_days_count * 8.0, 2) if active_days_count > 0 else 0.0

    fte_hours = agg["fte_hours"]
    fte_under = [h for h in fte_hours if h < target_hours] if target_hours > 0 else []

    total_hours = agg["total_hours"]
    driver_hours = agg["driver_hours"]
    if target_hours > 0:
        low_util_hours_total = sum(h for h in driver_hours if h < target_hours)
        low_util_drivers = sum(1 for h in driver_hours if h < target_hours)
    else:
        low_util_hours_total = 0.0
        low_util_drivers = 0

    low_util_share_pct = (low_util_hours_total / total_hours * 100) if total_hours > 0 else 0.0

    return {
        "drivers_total": agg["drivers_active"],
        "drivers_raw": agg["drivers_raw"],
        "drivers_fte": agg["drivers_fte"],
        "drivers_pt": agg["drivers_pt"],
        "total_hours": round(total_hours, 2),
        "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0.0,
        "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0.0,
        "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0.0,
        "pt_hours_total": round(agg["pt_hours_total"], 2),
        "pt_share_hours_pct": round((agg["pt_hours_total"] / total_hours * 100) if total_hours > 0 else 0.0, 2),
        "active_days": active_days_list,
        "active_days_count": active_days_count,
        "low_util_hours_threshold": target_hours,
        "low_util_share_hours_pct": round(low_util_share_pct, 2),
        "fte_under_util_count": len(fte_under),
        "fte_under_util_pct": round((len(fte_under) / agg["drivers_fte"] * 100) if agg["drivers_fte"] else 0.0, 2),
    }
