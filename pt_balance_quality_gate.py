#!/usr/bin/env python3
"""
pt_balance_quality_gate.py

Offline end-to-end quality gate for Solvereign.
Goal:
  1) Driver hours should be *evenly distributed* (esp. FTE 40–55h).
  2) PT usage should be reduced *as much as possible*.

How this works:
  - Loads a weekly forecast input (matrix style) and expands it into per-tour rows.
  - Runs the *real pipeline* (preferred: src.services.portfolio_controller.run_portfolio).
  - Extracts KPIs (or recomputes from rosters/assignments when possible).
  - Compares against an optional baseline JSON to prevent regressions.
  - Prints a compact report + writes artifacts/kpi_report.json
  - Exit code:
      0 = PASS
      1 = FAIL (hard gates violated or regression vs baseline)
      2 = ERROR (could not execute pipeline / could not parse)

Typical usage (from backend_py/):
  python tests/pt_balance_quality_gate.py --input "../forecast input.txt" --time-budget 180 --seed 0
  python tests/pt_balance_quality_gate.py --input "../forecast input.txt" --update-baseline

Notes:
  - This script is deliberately defensive: it tries multiple import/signature variants.
  - If your project already has a stronger validator (scripts/validate_schedule.py),
    the script will try to call it.
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------
# Forecast parsing (matrix style)
# ---------------------------

GERMAN_DAYS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,  # unused usually
}

DAY_ALIASES = {
    "mo": 0, "mon": 0, "monday": 0,
    "di": 1, "tue": 1, "tuesday": 1,
    "mi": 2, "wed": 2, "wednesday": 2,
    "do": 3, "thu": 3, "thursday": 3,
    "fr": 4, "fri": 4, "friday": 4,
    "sa": 5, "sat": 5, "saturday": 5,
    "so": 6, "sun": 6, "sunday": 6,
}


def _to_minutes(hhmm: str) -> int:
    hhmm = hhmm.strip()
    # allow "2:45" and "02:45"
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm)
    if not m:
        raise ValueError(f"Invalid time '{hhmm}'")
    h = int(m.group(1))
    mi = int(m.group(2))
    return h * 60 + mi


def _parse_time_range(token: str) -> Tuple[int, int]:
    token = token.strip()
    m = re.fullmatch(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", token)
    if not m:
        raise ValueError(f"Invalid time-range '{token}'")
    a = _to_minutes(m.group(1))
    b = _to_minutes(m.group(2))
    # Allow overnight, but normalize to positive duration by adding 24h if needed.
    if b <= a:
        b += 24 * 60
    return a, b


@dataclass
class TourRow:
    tour_id: str
    day: int
    start_min: int
    end_min: int

    @property
    def duration_min(self) -> int:
        return self.end_min - self.start_min

    @property
    def duration_hours(self) -> float:
        return self.duration_min / 60.0


def parse_forecast_matrix(path: Path) -> List[TourRow]:
    """
    Accepts the 'forecast input.txt' style:

      Montag   Anzahl
      04:45-09:15  15
      ...

    Returns one TourRow per counted tour.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines()]

    cur_day: Optional[int] = None
    tours: List[TourRow] = []
    seq = 0

    for ln in lines:
        if not ln or ln == "..." or ln.startswith("#"):
            continue

        header = ln.replace("\t", " ").strip()
        low = header.lower()

        # detect day header
        detected_day = None
        for day_name, day_idx in GERMAN_DAYS.items():
            if re.search(rf"\b{re.escape(day_name)}\b", low):
                detected_day = day_idx
                break
        if detected_day is None:
            parts = re.split(r"\s+", low)
            if parts:
                p0 = parts[0]
                if p0 in DAY_ALIASES:
                    detected_day = DAY_ALIASES[p0]
        if detected_day is not None:
            cur_day = detected_day
            # skip pure header lines
            if re.search(r"(anzahl|count)\b", low) or low in GERMAN_DAYS:
                continue

        # Data row expects a time range + count
        if "-" not in ln:
            continue
        cols = ln.strip().split()
        if len(cols) < 2:
            continue

        time_token = cols[0]
        count_token = cols[1]

        # Some malformed lines: "07:45-1" -> skip
        if not re.fullmatch(r"\d+", count_token):
            if re.fullmatch(r"\d+", cols[-1]):
                count_token = cols[-1]
                time_token = cols[0]
            else:
                continue

        try:
            start_min, end_min = _parse_time_range(time_token)
        except ValueError:
            continue

        if cur_day is None:
            # If file begins without explicit day header, assume Monday.
            cur_day = 0

        count = int(count_token)
        for _ in range(count):
            seq += 1
            tours.append(TourRow(
                tour_id=f"D{cur_day}-T{seq:05d}",
                day=cur_day,
                start_min=start_min,
                end_min=end_min,
            ))

    if not tours:
        raise RuntimeError(f"No tours parsed from {path}")
    return tours


# ---------------------------
# Pipeline execution (defensive)
# ---------------------------

def _add_repo_to_syspath(repo_root: Path) -> None:
    src = repo_root / "src"
    if src.exists():
        sys.path.insert(0, str(repo_root))
    elif (repo_root / "backend_py" / "src").exists():
        sys.path.insert(0, str(repo_root / "backend_py"))


def _try_import_run_portfolio() -> Any:
    candidates = [
        ("src.services.portfolio_controller", "run_portfolio"),
        ("src.services.portfolio_controller", "run_portfolio_from_tours"),
        ("src.services.portfolio_controller", "solve_portfolio"),
    ]
    last_err = None
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            if callable(fn):
                return fn
        except Exception as e:
            last_err = e
    raise ImportError(f"Could not import portfolio entrypoint. Last error: {last_err!r}")


def _try_make_config(overrides_json: Optional[str]) -> Any:
    cfg_obj: Any = None
    try:
        mod = __import__("src.services.forecast_solver_v4", fromlist=["ConfigV4"])
        ConfigV4 = getattr(mod, "ConfigV4", None)
        if ConfigV4 is not None:
            cfg_obj = ConfigV4()
    except Exception:
        cfg_obj = None

    overrides: Dict[str, Any] = {}
    if overrides_json:
        overrides = json.loads(overrides_json)

    if cfg_obj is None:
        return overrides if overrides else None

    for k, v in overrides.items():
        if hasattr(cfg_obj, k):
            setattr(cfg_obj, k, v)
    return cfg_obj


def _call_entrypoint(fn: Any, tours_payload: Any, config: Any, time_budget: float = 30.0, seed: int = 42) -> Any:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    # (A) Try with all expected parameters first
    try:
        return fn(
            tours=tours_payload,
            time_budget=time_budget,
            seed=seed,
            config=config,
        )
    except TypeError:
        pass

    # (B) positional (tours, config) - legacy
    try:
        if len(params) >= 2:
            return fn(tours_payload, config)
    except TypeError:
        pass

    # (C) keyword variants
    kw = {}
    for name in ("tours", "tour_rows", "forecast_tours", "input_tours"):
        if name in sig.parameters:
            kw[name] = tours_payload
            break
    for name in ("config", "cfg", "run_config"):
        if name in sig.parameters:
            kw[name] = config
            break
    if "time_budget" in sig.parameters:
        kw["time_budget"] = time_budget
    if "seed" in sig.parameters:
        kw["seed"] = seed
    if kw:
        return fn(**kw)

    # (D) single dict input
    try:
        run_input = {"tours": tours_payload, "config": config, "time_budget": time_budget, "seed": seed}
        return fn(run_input)
    except TypeError:
        pass

    raise TypeError(
        f"Could not call {fn.__module__}.{getattr(fn, '__name__', '<?>')} with known signatures. "
        f"Signature is {sig}."
    )



def _convert_tours_to_domain_objects(tours: List[TourRow]) -> Any:
    try:
        mod = __import__("src.domain.models", fromlist=["Tour", "Weekday"])
        Tour = getattr(mod, "Tour", None)
        Weekday = getattr(mod, "Weekday", None)

        if Tour is None or Weekday is None:
             raise ImportError("Missing models")

        from datetime import time as dt_time

        def mins_to_time(m):
            h = (m // 60) % 24
            mi = m % 60
            return dt_time(h, mi)

        DAY_MAP = {
            0: Weekday.MONDAY,
            1: Weekday.TUESDAY,
            2: Weekday.WEDNESDAY,
            3: Weekday.THURSDAY,
            4: Weekday.FRIDAY,
            5: Weekday.SATURDAY,
            6: Weekday.SUNDAY,
        }

        def build_one(t: TourRow) -> Any:
            return Tour(
                id=t.tour_id,
                day=DAY_MAP.get(t.day, Weekday.MONDAY),
                start_time=mins_to_time(t.start_min),
                end_time=mins_to_time(t.end_min),
                location="DEFAULT",
                required_qualifications=[]
            )

        return [build_one(t) for t in tours]
    except Exception as e:
        print(f"DEBUG: Domain conversion failed: {e}")
        pass

    return [
        {
            "tour_id": t.tour_id,
            "id": t.tour_id,
            "day": t.day,
            "start_min": t.start_min,
            "end_min": t.end_min,
            "duration_min": t.duration_min,
        }
        for t in tours
    ]


# ---------------------------
# KPI extraction
# ---------------------------

@dataclass
class Kpis:
    drivers_total: int
    drivers_fte: int
    drivers_pt: int
    total_hours: float
    fte_hours: float
    pt_hours: float
    pt_share_hours: float

    fte_min: float
    fte_avg: float
    fte_max: float
    fte_stddev: float
    fte_p10: float
    fte_p90: float

    fte_under40_count: int
    fte_over55_count: int

    rest_violations: Optional[int] = None
    coverage_ok: Optional[bool] = None
    extraction_meta: Optional[Dict[str, Any]] = None


def _maybe_get(obj: Any, keys: Iterable[str]) -> Any:
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                return obj[k]
        return None
    for k in keys:
        if hasattr(obj, k):
            return getattr(obj, k)
    return None


def _aggregate_assignments_to_rosters(assignments: Any) -> List[Dict[str, Any]]:
    driver_hours = {}
    for a in assignments:
        # assignments might be objects or dicts
        did = getattr(a, "driver_id", None)
        if did is None and isinstance(a, dict):
            did = a.get("driver_id")
            
        block = getattr(a, "block", None)
        if block is None and isinstance(a, dict):
            block = a.get("block")

        hours = 0.0
        if block:
            hours = getattr(block, "total_work_hours", None)
            if hours is None and isinstance(block, dict):
                 hours = block.get("total_work_hours")
            
            # If still None, maybe duration_hours?
            if hours is None:
                # Try simple duration
                hours = getattr(block, "duration_hours", 0.0)
        
        driver_hours[did] = driver_hours.get(did, 0.0) + (hours or 0.0)
    
    return [{"driver_id": did, "total_hours": h} for did, h in driver_hours.items()]


def _iter_rosters(result: Any) -> List[Any]:
    if hasattr(result, "solution"):
        result = result.solution

    # Check for assignments first
    assignments = _maybe_get(result, ["assignments"])
    if assignments:
        return _aggregate_assignments_to_rosters(assignments)

    for key in ("rosters", "driver_rosters", "drivers", "solution_rosters", "weekly_rosters"):
        rosters = _maybe_get(result, [key])
        if isinstance(rosters, list) and rosters:
            return rosters
    sp = _maybe_get(result, ["sp_result", "set_partition_result", "phase2", "phase_2", "phase3", "phase_3"])
    if sp is not None:
        for key in ("rosters", "driver_rosters", "drivers"):
            rosters = _maybe_get(sp, [key])
            if isinstance(rosters, list) and rosters:
                return rosters
    return []


def _extract_hours_from_roster(roster: Any) -> Optional[float]:
    val = _maybe_get(roster, ["total_hours", "hours", "hours_total", "weekly_hours", "work_hours"])
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _extract_driver_id(roster: Any, fallback_idx: int) -> str:
    val = _maybe_get(roster, ["driver_id", "id", "name"])
    if val is None:
        return f"driver_{fallback_idx:04d}"
    return str(val)


def _percentile(xs: List[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs_sorted = sorted(xs)
    if len(xs_sorted) == 1:
        return xs_sorted[0]
    k = (len(xs_sorted) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs_sorted[int(k)]
    d0 = xs_sorted[f] * (c - k)
    d1 = xs_sorted[c] * (k - f)
    return d0 + d1


# ---------------------------
# Deep-Scan KPI Extraction
# ---------------------------

def _deep_scan_hours_by_driver(result: Any) -> Tuple[Optional[Dict[str, float]], str]:
    """
    Scan for hours_by_driver maps in result structure.
    Returns (hours_dict, extraction_path) or (None, "")
    """
    candidates = [
        "hours_by_driver",
        "driver_hours_map",
        "weekly_hours_map",
        "driver_hours",
        "hours_map",
    ]
    
    for key in candidates:
        val = _maybe_get(result, [key])
        if isinstance(val, dict) and val:
            # Verify it looks like {driver_id: hours}
            sample = next(iter(val.items()), (None, None))
            if sample[0] and isinstance(sample[1], (int, float)):
                return {str(k): float(v) for k, v in val.items()}, f"hours_map.{key}"
    
    return None, ""


def _deep_scan_rosters(result: Any) -> Tuple[Optional[List[Dict]], str]:
    """
    Scan for roster lists in result structure.
    Returns (roster_list, extraction_path) or (None, "")
    """
    # Already implemented in _iter_rosters, but we'll extract the path info
    rosters = _iter_rosters(result)
    if rosters:
        # Try to determine which path was used
        for key in ("rosters", "driver_rosters", "drivers", "solution_rosters", "weekly_rosters"):
            test_val = _maybe_get(result, [key])
            if test_val is rosters:
                return rosters, f"rosters.{key}"
        
        # Check nested paths
        for parent_key in ("sp_result", "set_partition_result", "phase2", "phase_2", "phase3", "phase_3"):
            parent = _maybe_get(result, [parent_key])
            if parent:
                for key in ("rosters", "driver_rosters", "drivers"):
                    test_val = _maybe_get(parent, [key])
                    if test_val is rosters:
                        return rosters, f"{parent_key}.{key}"
        
        # Assignments path
        assignments = _maybe_get(result, ["assignments"])
        if assignments:
            return rosters, "assignments.aggregated"
        
        return rosters, "rosters.unknown"
    
    return None, ""


def _deep_scan_assignments(result: Any) -> Tuple[Optional[List[Any]], str]:
    """
    Scan for assignment/shift lists and compute hours.
    Returns (assignments, extraction_path) or (None, "")
    """
    assignment_keys = ["assignments", "driver_assignments", "shifts", "schedule", "weekly_assignments"]
    
    for key in assignment_keys:
        val = _maybe_get(result, [key])
        if isinstance(val, list) and val:
            return val, f"assignments.{key}"
    
    # Check nested
    for parent_key in ("sp_result", "set_partition_result", "solution"):
        parent = _maybe_get(result, [parent_key])
        if parent:
            for key in assignment_keys:
                val = _maybe_get(parent, [key])
                if isinstance(val, list) and val:
                    return val, f"{parent_key}.{key}"
    
    return None, ""


def _extract_hours_deep_scan(result: Any, debug_mode: bool = False) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Main deep-scan orchestrator. Tries multiple extraction methods.
    Returns (hours_dict, metadata)
    """
    metadata = {
        "candidates_tried": [],
        "method_used": None,
        "fallback_count": 0,
        "sample_data": {},
    }
    
    # Method 1: hours_by_driver map
    hours_map, path1 = _deep_scan_hours_by_driver(result)
    metadata["candidates_tried"].append({"method": "hours_map", "path": path1, "success": hours_map is not None})
    if hours_map:
        metadata["method_used"] = path1
        if debug_mode:
            metadata["sample_data"]["hours_map"] = {k: v for i, (k, v) in enumerate(hours_map.items()) if i < 3}
        return hours_map, metadata
    
    metadata["fallback_count"] += 1
    
    # Method 2: Roster lists
    rosters, path2 = _deep_scan_rosters(result)
    metadata["candidates_tried"].append({"method": "rosters", "path": path2, "success": rosters is not None})
    if rosters:
        hours_dict = {}
        for i, r in enumerate(rosters):
            did = _extract_driver_id(r, i)
            h = _extract_hours_from_roster(r)
            if h is not None:
                hours_dict[did] = hours_dict.get(did, 0.0) + h
        
        if hours_dict:
            metadata["method_used"] = path2
            if debug_mode:
                metadata["sample_data"]["rosters"] = [
                    {
                        "driver_id": _extract_driver_id(r, i),
                        "hours": _extract_hours_from_roster(r)
                    }
                    for i, r in enumerate(rosters[:3])
                ]
            return hours_dict, metadata
    
    metadata["fallback_count"] += 1
    
    # Method 3: Assignment lists
    assignments, path3 = _deep_scan_assignments(result)
    metadata["candidates_tried"].append({"method": "assignments", "path": path3, "success": assignments is not None})
    if assignments:
        hours_dict = {}
        for i, a in enumerate(assignments):
            did = _maybe_get(a, ["driver_id", "id"])
            if did is None:
                did = f"driver_{i:04d}"
            
            # Try to get hours from block
            block = _maybe_get(a, ["block"])
            hours = 0.0
            if block:
                hours = _maybe_get(block, ["total_work_hours", "work_hours", "hours", "duration_hours"]) or 0.0
            
            # Fallback: compute from start/end
            if hours == 0.0:
                start = _maybe_get(a, ["start", "start_time", "start_min"])
                end = _maybe_get(a, ["end", "end_time", "end_min"])
                if start is not None and end is not None:
                    if isinstance(start, int) and isinstance(end, int):
                        hours = (end - start) / 60.0
            
            if hours > 0:
                hours_dict[str(did)] = hours_dict.get(str(did), 0.0) + float(hours)
        
        if hours_dict:
            metadata["method_used"] = path3
            if debug_mode:
                metadata["sample_data"]["assignments"] = [
                    {
                        "driver_id": _maybe_get(a, ["driver_id", "id"]),
                        "computed_hours": _maybe_get(_maybe_get(a, ["block"]), ["total_work_hours"])
                    }
                    for a in assignments[:3]
                ]
            return hours_dict, metadata
    
    metadata["fallback_count"] += 1
    metadata["method_used"] = "FAILED"
    
    return {}, metadata


def compute_kpis(result: Any) -> Kpis:
    if hasattr(result, "solution"):
        result = result.solution

    kpi_dict = _maybe_get(result, ["kpis", "metrics", "kpi", "stats"])
    if isinstance(kpi_dict, dict):
        drivers_fte = int(kpi_dict.get("drivers_fte", kpi_dict.get("fte", 0)) or 0)
        drivers_pt = int(kpi_dict.get("drivers_pt", kpi_dict.get("pt", 0)) or 0)
        drivers_total = int(kpi_dict.get("drivers_total", kpi_dict.get("drivers", 0)) or 0)
        if drivers_total == 0:
            drivers_total = drivers_fte + drivers_pt

        pt_share_hours = float(kpi_dict.get("pt_share_hours", kpi_dict.get("pt_share", float("nan"))))

        fte_min = float(kpi_dict.get("fte_min_hours", kpi_dict.get("fte_hours_min", float("nan"))))
        fte_avg = float(kpi_dict.get("fte_avg_hours", kpi_dict.get("fte_hours_avg", float("nan"))))
        fte_max = float(kpi_dict.get("fte_max_hours", kpi_dict.get("fte_hours_max", float("nan"))))

        rest_violations = kpi_dict.get("rest_violations", None)
        if rest_violations is not None:
            rest_violations = int(rest_violations)

        rosters = _iter_rosters(result)
        # print(f"DEBUG: Found {len(rosters)} rosters/assignments")
        if rosters:
            hours = []
            for r in rosters:
                h = _extract_hours_from_roster(r)
                if h is not None and h >= 40.0:
                    hours.append(h)
            if hours:
                fte_stddev = statistics.pstdev(hours) if len(hours) > 1 else 0.0
                fte_p10 = _percentile(hours, 0.10)
                fte_p90 = _percentile(hours, 0.90)
            else:
                fte_stddev, fte_p10, fte_p90 = float("nan"), float("nan"), float("nan")
        else:
            fte_stddev, fte_p10, fte_p90 = float("nan"), float("nan"), float("nan")

        total_hours = float(kpi_dict.get("total_hours", float("nan")) or float("nan"))
        pt_hours = float(kpi_dict.get("pt_hours_total", kpi_dict.get("pt_hours", float("nan"))) or float("nan"))
        fte_hours = float(kpi_dict.get("fte_hours_total", kpi_dict.get("fte_hours", float("nan"))) or float("nan"))

        fte_under40_count = int(kpi_dict.get("fte_under40_count", 0) or 0)
        fte_over55_count = int(kpi_dict.get("fte_over55_count", 0) or 0)

        return Kpis(
            drivers_total=drivers_total,
            drivers_fte=drivers_fte,
            drivers_pt=drivers_pt,
            total_hours=total_hours,
            fte_hours=fte_hours,
            pt_hours=pt_hours,
            pt_share_hours=pt_share_hours,
            fte_min=fte_min,
            fte_avg=fte_avg,
            fte_max=fte_max,
            fte_stddev=fte_stddev,
            fte_p10=fte_p10,
            fte_p90=fte_p90,
            fte_under40_count=fte_under40_count,
            fte_over55_count=fte_over55_count,
            rest_violations=rest_violations,
            coverage_ok=None,
        )

    # Fallback: Try deep-scan if KPI dict didn't work
    hours_dict, extraction_meta = _extract_hours_deep_scan(result, debug_mode=False)
    
    if not hours_dict:
        raise RuntimeError("Could not extract rosters or KPI dict from result; cannot compute KPIs.")

    driver_hours: List[Tuple[str, float]] = list(hours_dict.items())

    if not driver_hours:
        raise RuntimeError("Deep-scan extracted hours but data is empty.")

    total_hours = sum(h for _, h in driver_hours)
    fte_list = [(did, h) for did, h in driver_hours if h >= 40.0]
    pt_list = [(did, h) for did, h in driver_hours if h < 40.0]

    fte_hours = sum(h for _, h in fte_list)
    pt_hours = sum(h for _, h in pt_list)
    pt_share_hours = (pt_hours / total_hours) if total_hours > 0 else float("nan")

    fte_hours_only = [h for _, h in fte_list]
    if fte_hours_only:
        fte_min = min(fte_hours_only)
        fte_avg = sum(fte_hours_only) / len(fte_hours_only)
        fte_max = max(fte_hours_only)
        fte_stddev = statistics.pstdev(fte_hours_only) if len(fte_hours_only) > 1 else 0.0
        fte_p10 = _percentile(fte_hours_only, 0.10)
        fte_p90 = _percentile(fte_hours_only, 0.90)
    else:
        fte_min = fte_avg = fte_max = fte_stddev = fte_p10 = fte_p90 = float("nan")

    fte_under40_count = sum(1 for _, h in fte_list if h < 40.0)
    fte_over55_count = sum(1 for _, h in fte_list if h > 55.0)

    return Kpis(
        drivers_total=len(driver_hours),
        drivers_fte=len(fte_list),
        drivers_pt=len(pt_list),
        total_hours=total_hours,
        fte_hours=fte_hours,
        pt_hours=pt_hours,
        pt_share_hours=pt_share_hours,
        fte_min=fte_min,
        fte_avg=fte_avg,
        fte_max=fte_max,
        fte_stddev=fte_stddev,
        fte_p10=fte_p10,
        fte_p90=fte_p90,
        fte_under40_count=fte_under40_count,
        fte_over55_count=fte_over55_count,
        rest_violations=None,
        coverage_ok=None,
        extraction_meta=extraction_meta,
    )


# ---------------------------
# Optional: call project validator if present
# ---------------------------

def try_validate_schedule(result: Any) -> Tuple[Optional[bool], Optional[int], List[str]]:
    msgs: List[str] = []
    try:
        mod = __import__("scripts.validate_schedule", fromlist=["validate_schedule"])
        validate_schedule = getattr(mod, "validate_schedule")
    except Exception:
        return None, None, msgs

    schedule = _maybe_get(result, ["schedule", "plan", "assignments", "output"])
    if schedule is None:
        sp = _maybe_get(result, ["sp_result", "set_partition_result"])
        schedule = _maybe_get(sp, ["schedule", "plan", "assignments", "output"]) if sp is not None else None

    if schedule is None:
        msgs.append("validate_schedule available, but could not locate schedule payload in result.")
        return None, None, msgs

    try:
        out = validate_schedule(schedule)
    except TypeError:
        try:
            out = validate_schedule(schedule=schedule)
        except Exception as e2:
            msgs.append(f"validate_schedule call failed: {e2!r}")
            return None, None, msgs
    except Exception as e:
        msgs.append(f"validate_schedule error: {e!r}")
        return None, None, msgs

    coverage_ok = None
    rest_violations = None

    if isinstance(out, dict):
        if "coverage_ok" in out:
            coverage_ok = bool(out.get("coverage_ok"))
        if "rest_violations" in out:
            rest_violations = int(out["rest_violations"])
        viols = out.get("violations")
        if isinstance(viols, list):
            rv = sum(1 for v in viols if isinstance(v, dict) and v.get("type") in ("rest", "rest_violation"))
            if rest_violations is None and rv:
                rest_violations = rv
    elif isinstance(out, tuple) and out:
        if isinstance(out[0], bool):
            coverage_ok = out[0]
        if len(out) > 1 and isinstance(out[1], list):
            rv = sum(1 for v in out[1] if isinstance(v, dict) and v.get("type") in ("rest", "rest_violation"))
            rest_violations = rv if rv else None

    return coverage_ok, rest_violations, msgs


# ---------------------------
# Baseline comparison
# ---------------------------

def score_solution(k: Kpis) -> float:
    imbalance = (k.fte_stddev if not math.isnan(k.fte_stddev) else 0.0) + (max(0.0, k.fte_max - k.fte_min) if not (math.isnan(k.fte_max) or math.isnan(k.fte_min)) else 0.0) * 0.25
    pt = (k.pt_share_hours if not math.isnan(k.pt_share_hours) else 1.0)
    hard = 0.0
    hard += 1000.0 * k.fte_under40_count
    hard += 1000.0 * k.fte_over55_count
    if k.rest_violations is not None:
        hard += 1000.0 * k.rest_violations
    return 1_000_000.0 * pt + 10.0 * imbalance + hard


def load_baseline(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def gate(k: Kpis, baseline: Optional[Dict[str, Any]], strict_pt: bool, require_validator: bool) -> Tuple[str, List[str], Dict[str, Any]]:
    reasons: List[str] = []
    status = "PASS"

    if k.fte_over55_count > 0:
        status = "FAIL"
        reasons.append(f"Hard gate: {k.fte_over55_count} FTE over 55h (must be 0).")
    if k.fte_under40_count > 0:
        status = "FAIL"
        reasons.append(f"Regression: {k.fte_under40_count} FTE under 40h (must be 0; PT reclass expected).")
    if k.rest_violations is not None and k.rest_violations > 0:
        status = "FAIL"
        reasons.append(f"Hard gate: {k.rest_violations} rest violations (must be 0).")
    if require_validator and k.rest_violations is None:
        status = "FAIL"
        reasons.append("Validator required but rest_violations is unknown (could not compute).")

    if not math.isnan(k.pt_share_hours) and k.pt_share_hours > 0.10:
        if strict_pt:
            status = "FAIL"
            reasons.append(f"PT target failed: pt_share_hours={k.pt_share_hours:.3f} > 0.10")
        else:
            if status != "FAIL":
                status = "WARN"
            reasons.append(f"PT target not reached (soft): pt_share_hours={k.pt_share_hours:.3f} > 0.10")

    if not math.isnan(k.fte_stddev) and k.drivers_fte > 0 and k.fte_stddev > 4.0:
        if status != "FAIL":
            status = "WARN"
        reasons.append(f"FTE balance is loose: stddev={k.fte_stddev:.2f}h (soft target <= 4.0h).")

    if baseline is not None:
        base_pt = float(baseline.get("pt_share_hours", float("nan")))
        base_std = float(baseline.get("fte_stddev", float("nan")))
        base_score = float(baseline.get("score", float("nan")))

        if not math.isnan(base_pt) and not math.isnan(k.pt_share_hours):
            if k.pt_share_hours > base_pt + 0.005:
                status = "FAIL"
                reasons.append(f"Regression vs baseline: pt_share_hours {k.pt_share_hours:.3f} > baseline {base_pt:.3f} (+0.005 tol).")

        if not math.isnan(base_std) and not math.isnan(k.fte_stddev):
            if k.fte_stddev > base_std + 0.5:
                if status != "FAIL":
                    status = "WARN"
                reasons.append(f"Balance regressed: fte_stddev {k.fte_stddev:.2f}h > baseline {base_std:.2f}h (+0.5 tol).")

        sc = score_solution(k)
        if not math.isnan(base_score) and sc > base_score * 1.01:
            status = "FAIL"
            reasons.append(f"Regression vs baseline score: {sc:.1f} > {base_score:.1f} (1% tol).")

    report = dataclasses.asdict(k)
    report["score"] = score_solution(k)
    return status, reasons, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to weekly forecast input (matrix style .txt).")
    ap.add_argument("--repo-root", default=".", help="Repo root (backend_py). If script is inside backend_py/tests, keep default.")
    ap.add_argument("--time-budget", type=int, default=None, help="Optional time budget in seconds (sets env QUALITY_TIME_BUDGET).")
    ap.add_argument("--seed", type=int, default=0, help="Seed for determinism if supported by pipeline.")
    ap.add_argument("--config-overrides", default=None, help='JSON string with config overrides, e.g. \'{\"time_budget\":180}\'')
    ap.add_argument("--baseline", default="tests/baselines/pt_balance_baseline.json", help="Baseline JSON path.")
    ap.add_argument("--update-baseline", action="store_true", help="Write current KPIs as new baseline (only if hard gates pass).")
    ap.add_argument("--strict-pt", action="store_true", help="Treat PT target (<=10%) as FAIL instead of WARN.")
    ap.add_argument("--require-validator", action="store_true", help="FAIL if rest_violations cannot be computed via validator.")
    ap.add_argument("--artifacts-dir", default="artifacts", help="Directory to write kpi_report.json")
    ap.add_argument("--debug-extract", action="store_true", help="Write extraction_debug.json with detailed extraction metadata.")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    _add_repo_to_syspath(repo_root)

    inp = Path(args.input).expanduser().resolve()
    if not inp.exists():
        print(f"[ERROR] Input not found: {inp}", file=sys.stderr)
        return 2

    if args.time_budget is not None:
        os.environ["QUALITY_TIME_BUDGET"] = str(args.time_budget)
        os.environ["TIME_BUDGET"] = str(args.time_budget)
    os.environ["SOLVEREIGN_SEED"] = str(args.seed)
    os.environ["PYTHONHASHSEED"] = str(args.seed)

    t0 = time.time()

    try:
        tours = parse_forecast_matrix(inp)
    except Exception as e:
        print(f"[ERROR] Failed parsing forecast input: {e!r}", file=sys.stderr)
        return 2

    tours_payload = _convert_tours_to_domain_objects(tours)
    config = _try_make_config(args.config_overrides)

    try:
        entry = _try_import_run_portfolio()
    except Exception as e:
        print(f"[ERROR] Could not import pipeline entrypoint: {e!r}", file=sys.stderr)
        return 2

    try:
        # Get time budget (default 30s, use 60s for quality runs)
        time_budget = args.time_budget if args.time_budget else 60.0
        result = _call_entrypoint(entry, tours_payload, config, time_budget=float(time_budget), seed=args.seed)
    except Exception as e:
        print(f"[ERROR] Pipeline execution failed: {e!r}", file=sys.stderr)
        return 2

    cov_ok, rest_v, v_msgs = try_validate_schedule(result)

    try:
        k = compute_kpis(result)
    except Exception as e:
        print(f"[ERROR] KPI extraction failed: {e!r}", file=sys.stderr)
        return 2

    if cov_ok is not None:
        k.coverage_ok = cov_ok
    if rest_v is not None:
        k.rest_violations = rest_v

    baseline_path = Path(args.baseline)
    baseline = load_baseline(baseline_path)

    status, reasons, report = gate(k, baseline, strict_pt=args.strict_pt, require_validator=args.require_validator)

    runtime_s = time.time() - t0

    artifacts_dir = Path(args.artifacts_dir)
    report_path = artifacts_dir / "kpi_report.json"
    out = {
        "status": status,
        "reasons": reasons,
        "runtime_s": round(runtime_s, 3),
        "input": str(inp),
        "seed": args.seed,
        "time_budget": args.time_budget,
        "kpis": report,
        "validator_notes": v_msgs,
        "extraction_meta": k.extraction_meta if k.extraction_meta else {"method_used": "kpi_dict"},
    }
    write_json(report_path, out)
    
    # Write extraction debug JSON if requested
    if args.debug_extract and k.extraction_meta:
        debug_path = artifacts_dir / "extraction_debug.json"
        debug_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "input": str(inp),
            "seed": args.seed,
            "extraction_meta": k.extraction_meta,
            "drivers_extracted": k.drivers_total,
            "fte_count": k.drivers_fte,
            "pt_count": k.drivers_pt,
        }
        write_json(debug_path, debug_data)
        print(f"[DEBUG] Extraction debug written to: {debug_path}")

    print("\\n=== Solvereign PT+Balance Quality Gate ===")
    print(f"Input: {inp}")
    print(f"Runtime: {runtime_s:.2f}s | Seed: {args.seed} | Budget: {args.time_budget}")
    print(f"Status: {status}")
    if v_msgs:
        for m in v_msgs:
            print(f"[validator] {m}")

    print("\\nKPIs:")
    print(f"  Drivers: {k.drivers_fte} FTE + {k.drivers_pt} PT = {k.drivers_total}")
    if not math.isnan(k.pt_share_hours):
        print(f"  PT share (hours): {k.pt_share_hours:.3f}")
    else:
        print("  PT share (hours): NaN/unknown")
    print(f"  FTE hours: min {k.fte_min:.1f} | avg {k.fte_avg:.1f} | max {k.fte_max:.1f} | std {k.fte_stddev:.2f}")
    print(f"  FTE p10/p90: {k.fte_p10:.1f} / {k.fte_p90:.1f}")
    print(f"  FTE under 40h: {k.fte_under40_count} | FTE over 55h: {k.fte_over55_count}")
    print(f"  Rest violations: {k.rest_violations if k.rest_violations is not None else 'unknown'}")
    if k.coverage_ok is not None:
        print(f"  Coverage ok: {k.coverage_ok}")
    print(f"  Score: {score_solution(k):.1f}")

    if reasons:
        print("\\nReasons:")
        for r in reasons:
            print(f"  - {r}")

    if args.update_baseline:
        if status in ("FAIL", "ERROR"):
            print("\\n[BASELINE] Not updating baseline because status is not PASS/WARN.", file=sys.stderr)
        else:
            baseline_payload = {
                "pt_share_hours": k.pt_share_hours,
                "fte_stddev": k.fte_stddev,
                "fte_avg": k.fte_avg,
                "drivers_total": k.drivers_total,
                "score": score_solution(k),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "input": str(inp),
            }
            write_json(baseline_path, baseline_payload)
            print(f"\\n[BASELINE] Updated baseline at: {baseline_path}")

    if status in ("PASS", "WARN"):
        return 0
    if status == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
