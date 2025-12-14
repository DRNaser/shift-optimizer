"""
LEARN MANUAL POLICY - v2 Fixed
==============================
Parses manual roster data (traindata.xlsx) to extract shift patterns
and export a policy JSON for the solver to mimic.

FIXES in v2:
1. Only ignore cells if NO time windows present
2. Use findall for robust multi-delimiter parsing
3. Allow 1-2 digit hours (5:00 and 05:00)
4. Sort windows by start time
5. Handle over-midnight times
6. Only count positive gaps

Output:
- manual_policy.json (policy for solver)
- parse_quality.json (sanity report)
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

import pandas as pd


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class TimeWindow(NamedTuple):
    """A time window (start, end) in minutes from midnight."""
    start_mins: int
    end_mins: int
    
    @property
    def duration_mins(self) -> int:
        return self.end_mins - self.start_mins
    
    def __str__(self) -> str:
        sh, sm = divmod(self.start_mins, 60)
        # Handle over-midnight: modulo 24h for display
        eh, em = divmod(self.end_mins % 1440, 60)
        return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"


class DayShift(NamedTuple):
    """A complete day shift with multiple tours."""
    weekday: str
    windows: tuple[TimeWindow, ...]
    
    @property
    def block_type(self) -> str:
        n = len(self.windows)
        if n == 1:
            return "1er"
        elif n == 2:
            return "2er"
        elif n == 3:
            return "3er"
        return f"{n}er"
    
    @property
    def gaps(self) -> list[int]:
        """Gaps between consecutive windows in minutes (positive only)."""
        if len(self.windows) < 2:
            return []
        gaps = []
        for i in range(len(self.windows) - 1):
            gap = self.windows[i + 1].start_mins - self.windows[i].end_mins
            # Only include positive, reasonable gaps (exclude overlaps/negatives)
            if 0 < gap <= 720:  # Max 12h gap sanity check
                gaps.append(gap)
        return gaps
    
    @property
    def is_split(self) -> bool:
        """Has a gap >= 180 minutes (3 hours)."""
        return any(g >= 180 for g in self.gaps)
    
    @property
    def template(self) -> str:
        """Template string for pattern matching."""
        return "/".join(str(w) for w in self.windows)


# =============================================================================
# PARSING
# =============================================================================

# Weekday patterns (German) - use startswith for flexibility
WEEKDAY_PATTERNS = [
    (r"^mo", "Mon"),
    (r"^di", "Tue"),
    (r"^mi", "Wed"),
    (r"^do", "Thu"),
    (r"^fr", "Fri"),
    (r"^sa", "Sat"),
    (r"^so", "Sun"),
]

# Patterns to ignore (non-shift entries) - only if NO time windows present
IGNORE_PATTERNS = [
    "urlaub", "krank", "frei", "schulung", "mediamarkt", 
    "planen", "feiertag", "gek"
]

# Time pattern: H:MM-H:MM or HH:MM-HH:MM (1-2 digit hours)
TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")


# =============================================================================
# PARSE STATS (for quality report)
# =============================================================================

parse_stats = {
    "cells_total": 0,
    "cells_with_time": 0,
    "cells_ignored_by_status": 0,
    "cells_parsed": 0,
    "cells_failed": 0,
    "unparsed_examples": [],
}


def match_weekday(text: str) -> str | None:
    """Match weekday from text using startswith patterns."""
    text_lower = text.strip().lower()
    for pattern, weekday in WEEKDAY_PATTERNS:
        if re.match(pattern, text_lower):
            return weekday
    return None


def parse_time_windows(cell_value) -> list[TimeWindow]:
    """
    Parse all time windows from a cell using findall.
    Handles multiple delimiters: / ; , + newline
    """
    if pd.isna(cell_value):
        return []
    
    text = str(cell_value)
    
    # Find all time patterns
    matches = TIME_PATTERN.findall(text)
    if not matches:
        return []
    
    windows = []
    for sh, sm, eh, em in matches:
        start_mins = int(sh) * 60 + int(sm)
        end_mins = int(eh) * 60 + int(em)
        
        # Handle over-midnight: if end < start, add 24h
        if end_mins < start_mins:
            end_mins += 1440
        
        windows.append(TimeWindow(start_mins, end_mins))
    
    # Sort by start time
    windows.sort(key=lambda w: w.start_mins)
    
    return windows


def parse_cell(cell_value, weekday: str) -> DayShift | None:
    """Parse a cell value into a DayShift."""
    global parse_stats
    parse_stats["cells_total"] += 1
    
    if pd.isna(cell_value):
        return None
    
    text = str(cell_value).strip()
    text_lower = text.lower()
    
    # First, try to extract time windows
    windows = parse_time_windows(cell_value)
    
    # Check if we have time patterns
    has_time = len(windows) > 0
    parse_stats["cells_with_time"] += 1 if has_time else 0
    
    # ONLY ignore if NO time windows AND contains ignore pattern
    if not has_time:
        for pattern in IGNORE_PATTERNS:
            if pattern in text_lower:
                parse_stats["cells_ignored_by_status"] += 1
                return None
        
        # No time, no ignore pattern - might be something else
        if text.strip() and len(text) > 1:
            if len(parse_stats["unparsed_examples"]) < 50:
                parse_stats["unparsed_examples"].append(text[:100])
        parse_stats["cells_failed"] += 1
        return None
    
    # We have time windows - create shift
    parse_stats["cells_parsed"] += 1
    return DayShift(weekday, tuple(windows))


def detect_weekday_columns(df: pd.DataFrame) -> tuple[dict[int, str], int]:
    """
    Detect which columns correspond to which weekdays and find the header row.
    Uses startswith matching for flexibility (Mo, Mo., Montag, Montag Anzahl).
    Returns (weekday_cols, header_row).
    """
    weekday_cols = {}
    header_row = 0
    
    # Scan rows to find a row that looks like weekday headers
    for row_idx in range(min(10, len(df))):
        row_weekdays = {}
        for col_idx in range(len(df.columns)):
            cell = df.iloc[row_idx, col_idx]
            if pd.notna(cell):
                weekday = match_weekday(str(cell))
                if weekday:
                    row_weekdays[col_idx] = weekday
        
        # If we found multiple weekday headers in this row, it's the header row
        if len(row_weekdays) >= 4:
            weekday_cols = row_weekdays
            header_row = row_idx
            break
    
    return weekday_cols, header_row


def parse_training_data(excel_path: Path) -> list[DayShift]:
    """Parse the training Excel file into DayShifts."""
    global parse_stats
    parse_stats = {
        "cells_total": 0,
        "cells_with_time": 0,
        "cells_ignored_by_status": 0,
        "cells_parsed": 0,
        "cells_failed": 0,
        "unparsed_examples": [],
    }
    
    print(f"Loading {excel_path}...")
    
    df = pd.read_excel(excel_path, header=None)
    print(f"Shape: {df.shape}")
    
    # Detect weekday columns and header row
    weekday_cols, header_row = detect_weekday_columns(df)
    print(f"Detected header row: {header_row}")
    print(f"Weekday columns found: {len(weekday_cols)}")
    
    # If no weekday columns detected via names, find columns with time patterns
    if not weekday_cols:
        print("No weekday headers detected, inferring from data...")
        # Find columns that contain time patterns
        time_cols = []
        for col_idx in range(len(df.columns)):
            has_time = False
            for row_idx in range(min(50, len(df))):
                cell = df.iloc[row_idx, col_idx]
                if pd.notna(cell) and TIME_PATTERN.search(str(cell)):
                    has_time = True
                    break
            if has_time:
                time_cols.append(col_idx)
        
        # Assign weekdays cyclically
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, col in enumerate(time_cols):
            weekday_cols[col] = weekdays[i % 7]
        header_row = 0
    
    print(f"Processing {len(weekday_cols)} weekday columns...")
    
    # Parse all shifts from data rows (skip header)
    shifts: list[DayShift] = []
    data_start_row = header_row + 1
    
    for row_idx in range(data_start_row, len(df)):
        for col_idx, weekday in weekday_cols.items():
            if col_idx >= len(df.columns):
                continue
            cell = df.iloc[row_idx, col_idx]
            shift = parse_cell(cell, weekday)
            if shift:
                shifts.append(shift)
    
    print(f"Parsed {len(shifts)} shifts")
    print(f"Parse stats: {parse_stats['cells_parsed']}/{parse_stats['cells_with_time']} with time, "
          f"{parse_stats['cells_ignored_by_status']} ignored by status, "
          f"{parse_stats['cells_failed']} failed")
    
    return shifts


# =============================================================================
# ANALYSIS
# =============================================================================

def analyze_shifts(shifts: list[DayShift]) -> dict:
    """Analyze shifts and extract patterns."""
    
    # Block type distribution
    block_types = Counter(s.block_type for s in shifts)
    total = sum(block_types.values())
    
    # Ensure all types present with 0.0 default
    block_mix_overall = {
        "1er": round(block_types.get("1er", 0) / total, 3) if total > 0 else 0.0,
        "2er": round(block_types.get("2er", 0) / total, 3) if total > 0 else 0.0,
        "3er": round(block_types.get("3er", 0) / total, 3) if total > 0 else 0.0,
    }
    
    # By weekday
    by_weekday: dict[str, list[DayShift]] = defaultdict(list)
    for s in shifts:
        by_weekday[s.weekday].append(s)
    
    block_mix_by_weekday = {}
    split2_by_weekday = {}
    
    all_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for wd in all_weekdays:
        wd_shifts = by_weekday.get(wd, [])
        wd_types = Counter(s.block_type for s in wd_shifts)
        wd_total = sum(wd_types.values())
        
        # Ensure all types present
        block_mix_by_weekday[wd] = {
            "1er": round(wd_types.get("1er", 0) / wd_total, 3) if wd_total > 0 else 0.0,
            "2er": round(wd_types.get("2er", 0) / wd_total, 3) if wd_total > 0 else 0.0,
            "3er": round(wd_types.get("3er", 0) / wd_total, 3) if wd_total > 0 else 0.0,
        }
        
        # Split-2er rate
        wd_2er = [s for s in wd_shifts if s.block_type == "2er"]
        if wd_2er:
            split2_by_weekday[wd] = round(
                sum(1 for s in wd_2er if s.is_split) / len(wd_2er), 3
            )
        else:
            split2_by_weekday[wd] = 0.0
    
    # Overall split2 rate
    all_2er = [s for s in shifts if s.block_type == "2er"]
    split2_overall = round(
        sum(1 for s in all_2er if s.is_split) / len(all_2er), 3
    ) if all_2er else 0.0
    
    # Gap analysis - only positive gaps
    all_gaps = []
    for s in shifts:
        all_gaps.extend(s.gaps)  # Already filtered to positive in DayShift
    
    gap_counter = Counter(all_gaps)
    gap_modes = [gap for gap, _ in gap_counter.most_common(10)]
    
    # Split gap cluster (gaps >= 180 min)
    split_gaps = [g for g in all_gaps if g >= 180]
    split_gap_cluster = {
        "min": min(split_gaps) if split_gaps else 0,
        "max": max(split_gaps) if split_gaps else 0,
        "count": len(split_gaps),
    }
    
    # Canonical windows (time patterns)
    all_windows = []
    windows_by_weekday: dict[str, list[str]] = defaultdict(list)
    
    for s in shifts:
        for w in s.windows:
            w_str = str(w)
            all_windows.append(w_str)
            windows_by_weekday[s.weekday].append(w_str)
    
    window_counter = Counter(all_windows)
    canonical_overall = [w for w, _ in window_counter.most_common(60)]
    
    canonical_by_weekday = {}
    for wd in all_weekdays:
        wd_windows = windows_by_weekday.get(wd, [])
        wd_counter = Counter(wd_windows)
        canonical_by_weekday[wd] = [w for w, _ in wd_counter.most_common(40)]
    
    # Templates (full shift patterns)
    templates_2er = [s.template for s in shifts if s.block_type == "2er"]
    templates_3er = [s.template for s in shifts if s.block_type == "3er"]
    
    template_2er_counter = Counter(templates_2er)
    template_3er_counter = Counter(templates_3er)
    
    top_pair_templates = [t for t, _ in template_2er_counter.most_common(100)]
    top_triple_templates = [t for t, _ in template_3er_counter.most_common(100)]
    
    return {
        "stats": {
            "total_shifts": len(shifts),
            "shifts_by_weekday": {wd: len(by_weekday.get(wd, [])) for wd in all_weekdays},
            "block_type_counts": dict(block_types),
        },
        "target_block_mix_overall": block_mix_overall,
        "target_block_mix_by_weekday": block_mix_by_weekday,
        "split2_rate_overall": split2_overall,
        "split2_rate_by_weekday": split2_by_weekday,
        "gap_modes": gap_modes,
        "gap_histogram": dict(gap_counter.most_common(20)),
        "split_gap_cluster": split_gap_cluster,
        "canonical_windows_overall": canonical_overall,
        "canonical_windows_by_weekday": canonical_by_weekday,
        "top_pair_templates": top_pair_templates,
        "top_triple_templates": top_triple_templates,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    global parse_stats
    
    # Find training data
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent  # backend_py/../
    
    # Check multiple locations
    possible_paths = [
        project_root / "traindata.xlsx",
        script_dir.parent / "traindata.xlsx",  # backend_py/traindata.xlsx
        Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\traindata.xlsx"),
    ]
    
    excel_path = None
    for p in possible_paths:
        if p.exists():
            excel_path = p
            break
    
    if not excel_path:
        print("ERROR: traindata.xlsx not found!")
        print("Searched:")
        for p in possible_paths:
            print(f"  - {p}")
        return 1
    
    # Parse and analyze
    shifts = parse_training_data(excel_path)
    
    if not shifts:
        print("ERROR: No shifts parsed from training data!")
        return 1
    
    analysis = analyze_shifts(shifts)
    
    # Print summary
    print(f"\n{'='*60}")
    print("ANALYSIS SUMMARY")
    print(f"{'='*60}")
    print(f"Total shifts: {analysis['stats']['total_shifts']}")
    print(f"\nBlock mix overall:")
    for bt in ["1er", "2er", "3er"]:
        pct = analysis['target_block_mix_overall'].get(bt, 0)
        print(f"  {bt}: {pct*100:.1f}%")
    
    print(f"\nSplit-2er rate: {analysis['split2_rate_overall']*100:.1f}%")
    print(f"Gap modes: {analysis['gap_modes'][:5]}")
    print(f"Split gap cluster: {analysis['split_gap_cluster']}")
    
    print(f"\nCanonical windows (top 10):")
    for w in analysis['canonical_windows_overall'][:10]:
        print(f"  {w}")
    
    print(f"\nTop pair templates (top 5):")
    for t in analysis['top_pair_templates'][:5]:
        print(f"  {t}")
    
    print(f"\nTop triple templates (top 5):")
    for t in analysis['top_triple_templates'][:5]:
        print(f"  {t}")
    
    # Weekday comparison
    print(f"\n1er rate by weekday (expecting Sat highest):")
    for wd in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
        rate = analysis['target_block_mix_by_weekday'].get(wd, {}).get("1er", 0)
        print(f"  {wd}: {rate*100:.1f}%")
    
    # Save policy
    data_dir = script_dir.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = data_dir / "manual_policy.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print(f"\nPolicy saved to: {output_path}")
    
    # Save parse quality report
    quality_report = {
        "cells_total": parse_stats["cells_total"],
        "cells_with_time": parse_stats["cells_with_time"],
        "cells_ignored_by_status": parse_stats["cells_ignored_by_status"],
        "cells_parsed": parse_stats["cells_parsed"],
        "cells_failed": parse_stats["cells_failed"],
        "parse_rate": round(parse_stats["cells_parsed"] / max(1, parse_stats["cells_with_time"]), 3),
        "unparsed_examples_top20": parse_stats["unparsed_examples"][:20],
    }
    
    quality_path = data_dir / "parse_quality.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    print(f"Parse quality report saved to: {quality_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
