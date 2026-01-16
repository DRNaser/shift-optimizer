"""
SOLVEREIGN V3 Parser Module
============================

M1: Whitelist-based tour parsing with strict validation.

Parses German tour specifications from Slack/CSV/Manual input.

Input Format Examples:
    ✅ "Mo 06:00-14:00 3 Fahrer Depot Nord"
    ✅ "Di 06:00-14:00 + 15:00-19:00" (split shift)
    ✅ "Mi 22:00-06:00" (cross-midnight)
    ❌ "Fr early shift" (ambiguous, FAIL)
    ❌ "Sa 25:00-14:00" (invalid time, FAIL)

Flow:
    1. Parse raw text line-by-line
    2. Validate each line (PASS/WARN/FAIL)
    3. Normalize to canonical format
    4. Compute input_hash for deduplication
    5. Store in forecast_versions + tours_raw + tours_normalized

Philosophy: Whitelist-only. No "best effort" fallbacks.
"""

import hashlib
import re
from datetime import time
from typing import List, Optional, Tuple

from .models import (
    Issue,
    ParseResult,
    ParseStatus,
    ForecastStatus,
)
from .db import (
    create_forecast_version,
    create_tour_raw,
    create_tour_normalized,
    get_forecast_by_input_hash,
)
from .config import config


# ============================================================================
# Day Name Mapping (German → Integer)
# ============================================================================

DAY_NAMES = {
    "Mo": 1, "Montag": 1,
    "Di": 2, "Dienstag": 2,
    "Mi": 3, "Mittwoch": 3,
    "Do": 4, "Donnerstag": 4,
    "Fr": 5, "Freitag": 5,
    "Sa": 6, "Samstag": 6,
    "So": 7, "Sonntag": 7,
}


# ============================================================================
# Core Parser Logic
# ============================================================================

def parse_time(time_str: str) -> Tuple[Optional[time], List[Issue]]:
    """
    Parse time string to datetime.time object.

    Args:
        time_str: Time in format "HH:MM" or "H:MM"

    Returns:
        (time_obj, issues)
    """
    issues = []

    # Match HH:MM or H:MM
    match = re.match(r'^(\d{1,2}):(\d{2})$', time_str.strip())

    if not match:
        issues.append(Issue(
            code="INVALID_TIME_FORMAT",
            message=f"Invalid time format: '{time_str}'. Expected HH:MM",
            severity="ERROR"
        ))
        return None, issues

    hour = int(match.group(1))
    minute = int(match.group(2))

    # Validate ranges
    if hour < 0 or hour > 23:
        issues.append(Issue(
            code="INVALID_HOUR",
            message=f"Hour {hour} out of range (0-23)",
            severity="ERROR"
        ))
        return None, issues

    if minute < 0 or minute > 59:
        issues.append(Issue(
            code="INVALID_MINUTE",
            message=f"Minute {minute} out of range (0-59)",
            severity="ERROR"
        ))
        return None, issues

    return time(hour=hour, minute=minute), issues


def parse_tour_line(raw_text: str, line_no: int) -> ParseResult:
    """
    Parse a single tour line using whitelist patterns.

    Supported patterns:
        1. "Mo 06:00-14:00"
        2. "Mo 06:00-14:00 3 Fahrer"
        3. "Mo 06:00-14:00 Depot Nord"
        4. "Mo 06:00-14:00 3 Fahrer Depot Nord"
        5. "Mo 06:00-14:00 + 15:00-19:00" (split shift)

    Args:
        raw_text: Raw input line
        line_no: Line number for error reporting

    Returns:
        ParseResult with status, normalized fields, and issues
    """
    issues = []
    normalized_fields = {}

    # Strip whitespace
    line = raw_text.strip()

    # Skip empty lines
    if not line:
        return ParseResult(
            parse_status=ParseStatus.PASS,
            normalized_fields={},
            canonical_text="",
            issues=[]
        )

    # Skip comments (lines starting with #)
    if line.startswith('#'):
        return ParseResult(
            parse_status=ParseStatus.PASS,
            normalized_fields={},
            canonical_text=line,
            issues=[]
        )

    # Pattern 1: Day parsing
    # Match day name at start of line
    day_match = None
    day_num = None

    for day_name, day_value in DAY_NAMES.items():
        if line.startswith(day_name + " ") or line == day_name:
            day_match = day_name
            day_num = day_value
            break

    if not day_match:
        issues.append(Issue(
            code="MISSING_DAY",
            message=f"Line {line_no}: No valid day name found. Expected: Mo, Di, Mi, Do, Fr, Sa, So",
            severity="ERROR"
        ))
        return ParseResult(
            parse_status=ParseStatus.FAIL,
            normalized_fields={},
            canonical_text=line,
            issues=issues
        )

    normalized_fields['day'] = day_num

    # Remove day from line
    remainder = line[len(day_match):].strip()

    # Pattern 2: Time range parsing
    # Match "HH:MM-HH:MM" or "HH:MM-HH:MM + HH:MM-HH:MM" (split)

    # Check for split shift (contains "+")
    is_split = '+' in remainder

    if is_split:
        # Split shift: "06:00-14:00 + 15:00-19:00"
        parts = remainder.split('+')
        if len(parts) != 2:
            issues.append(Issue(
                code="INVALID_SPLIT_FORMAT",
                message=f"Line {line_no}: Split shift must have exactly 2 parts separated by '+'",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        # Parse both time ranges
        part1_tokens = parts[0].strip().split()
        part2_tokens = parts[1].strip().split()

        # Validate both parts have content
        if not part1_tokens:
            issues.append(Issue(
                code="INVALID_TIME_RANGE",
                message=f"Line {line_no}: Missing time range before '+' in split shift",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        if not part2_tokens:
            issues.append(Issue(
                code="INVALID_TIME_RANGE",
                message=f"Line {line_no}: Missing time range after '+' in split shift",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        time_range_1 = part1_tokens[0]  # "06:00-14:00"
        time_range_2 = part2_tokens[0]  # "15:00-19:00"

        # Parse part 1
        times_1 = time_range_1.split('-')
        if len(times_1) != 2:
            issues.append(Issue(
                code="INVALID_TIME_RANGE",
                message=f"Line {line_no}: Invalid time range format for split part 1",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        start_1, start_issues = parse_time(times_1[0])
        end_1, end_issues = parse_time(times_1[1])

        issues.extend(start_issues)
        issues.extend(end_issues)

        if start_1 is None or end_1 is None:
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        # Parse part 2
        times_2 = time_range_2.split('-')
        if len(times_2) != 2:
            issues.append(Issue(
                code="INVALID_TIME_RANGE",
                message=f"Line {line_no}: Invalid time range format for split part 2",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        start_2, start_issues = parse_time(times_2[0])
        end_2, end_issues = parse_time(times_2[1])

        issues.extend(start_issues)
        issues.extend(end_issues)

        if start_2 is None or end_2 is None:
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        # Store split shift times
        normalized_fields['start_ts'] = start_1
        normalized_fields['end_ts'] = end_2  # Overall end is end of second part
        normalized_fields['is_split'] = True
        normalized_fields['split_start_1'] = start_1
        normalized_fields['split_end_1'] = end_1
        normalized_fields['split_start_2'] = start_2
        normalized_fields['split_end_2'] = end_2

        # Calculate split break
        def time_to_minutes(t: time) -> int:
            return t.hour * 60 + t.minute

        break_minutes = time_to_minutes(start_2) - time_to_minutes(end_1)
        normalized_fields['split_break_minutes'] = break_minutes

        # Remainder for count/depot parsing (after second time range)
        remainder = parts[1].strip()[len(time_range_2):].strip()

    else:
        # Regular shift: "06:00-14:00"
        # Extract time range (first token should be time range)
        tokens = remainder.split()

        if not tokens:
            issues.append(Issue(
                code="MISSING_TIME_RANGE",
                message=f"Line {line_no}: No time range found",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        time_range = tokens[0]
        times = time_range.split('-')

        if len(times) != 2:
            issues.append(Issue(
                code="INVALID_TIME_RANGE",
                message=f"Line {line_no}: Invalid time range format. Expected HH:MM-HH:MM",
                severity="ERROR"
            ))
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        start_time, start_issues = parse_time(times[0])
        end_time, end_issues = parse_time(times[1])

        issues.extend(start_issues)
        issues.extend(end_issues)

        if start_time is None or end_time is None:
            return ParseResult(
                parse_status=ParseStatus.FAIL,
                normalized_fields=normalized_fields,
                canonical_text=line,
                issues=issues
            )

        normalized_fields['start_ts'] = start_time
        normalized_fields['end_ts'] = end_time
        normalized_fields['is_split'] = False

        # Remainder for count/depot parsing
        remainder = ' '.join(tokens[1:])

    # Detect cross-midnight
    crosses_midnight = normalized_fields['end_ts'] < normalized_fields['start_ts']
    normalized_fields['crosses_midnight'] = crosses_midnight

    # Pattern 3: Count parsing ("3 Fahrer" or just "3")
    count = 1  # Default count
    count_match = re.search(r'(\d+)\s*(Fahrer|fahrer|driver|Driver)?', remainder)
    if count_match:
        count = int(count_match.group(1))
        # Remove count from remainder
        remainder = remainder[:count_match.start()] + remainder[count_match.end():]
        remainder = remainder.strip()

    normalized_fields['count'] = count

    # Pattern 4: Depot/Zone parsing
    # Remaining text is depot/zone/notes
    if remainder:
        # Simple heuristic: if it contains "Depot", extract depot
        depot_match = re.search(r'Depot\s+(\w+)', remainder, re.IGNORECASE)
        if depot_match:
            normalized_fields['depot'] = depot_match.group(1)

        # Store remainder as notes
        normalized_fields['notes'] = remainder.strip()

    # Calculate duration and work hours
    def time_to_minutes(t: time) -> int:
        return t.hour * 60 + t.minute

    start_min = time_to_minutes(normalized_fields['start_ts'])
    end_min = time_to_minutes(normalized_fields['end_ts'])

    if crosses_midnight:
        end_min += 24 * 60

    duration_min = end_min - start_min

    # For split shifts, subtract break time from work hours
    if normalized_fields.get('is_split'):
        work_min = duration_min - normalized_fields.get('split_break_minutes', 0)
    else:
        work_min = duration_min

    normalized_fields['duration_min'] = duration_min
    normalized_fields['work_hours'] = round(work_min / 60, 2)

    # Warnings (non-blocking)
    if count > 10:
        issues.append(Issue(
            code="HIGH_COUNT",
            message=f"Line {line_no}: Unusually high count ({count} drivers)",
            severity="WARNING"
        ))

    if work_min > 16 * 60:  # > 16h work
        issues.append(Issue(
            code="EXCESSIVE_WORK_HOURS",
            message=f"Line {line_no}: Work hours {normalized_fields['work_hours']}h exceeds 16h limit",
            severity="WARNING"
        ))

    # Determine parse status
    has_errors = any(i.severity == "ERROR" for i in issues)
    has_warnings = any(i.severity == "WARNING" for i in issues)

    if has_errors:
        parse_status = ParseStatus.FAIL
    elif has_warnings:
        parse_status = ParseStatus.WARN
    else:
        parse_status = ParseStatus.PASS

    # Canonical text (normalized representation for hashing)
    day_abbr = [k for k, v in DAY_NAMES.items() if v == day_num and len(k) == 2][0]
    canonical = f"{day_abbr} {normalized_fields['start_ts']}-{normalized_fields['end_ts']}"
    if normalized_fields.get('is_split'):
        canonical += f" + {normalized_fields['split_start_2']}-{normalized_fields['split_end_2']}"
    if count > 1:
        canonical += f" {count}"
    if normalized_fields.get('depot'):
        canonical += f" Depot {normalized_fields['depot']}"

    return ParseResult(
        parse_status=parse_status,
        normalized_fields=normalized_fields,
        canonical_text=canonical,
        issues=issues
    )


def parse_forecast_text(
    raw_text: str,
    source: str = "manual",
    notes: Optional[str] = None,
    save_to_db: bool = True,
    week_key: Optional[str] = None,
    week_anchor_date: Optional[str] = None,
    tenant_id: int = 1  # Default tenant for backward compatibility
) -> dict:
    """
    Parse complete forecast text (multi-line input).

    Args:
        raw_text: Complete forecast text (one tour per line)
        source: Input source ('slack', 'csv', 'manual')
        notes: Optional notes for forecast version
        save_to_db: Whether to save to database
        week_key: Week identifier (e.g., "2026-W01") - REQUIRED for compose
        week_anchor_date: Monday of the week (YYYY-MM-DD) - for datetime computation

    Returns:
        dict with:
            - forecast_version_id: ID of created forecast (if save_to_db=True)
            - status: PASS/WARN/FAIL
            - lines_total: Total lines parsed
            - lines_passed: Lines that passed validation
            - lines_warned: Lines with warnings
            - lines_failed: Lines that failed validation
            - tours_created: Number of tours created
            - input_hash: SHA256 of canonical input
            - parse_results: List of ParseResult per line
    """
    lines = raw_text.strip().split('\n')

    parse_results = []
    canonical_lines = []

    lines_passed = 0
    lines_warned = 0
    lines_failed = 0
    tours_count = 0

    for line_no, line in enumerate(lines, start=1):
        result = parse_tour_line(line, line_no)
        parse_results.append(result)

        if result.canonical_text:
            canonical_lines.append(result.canonical_text)

        if result.parse_status == ParseStatus.PASS:
            lines_passed += 1
            if result.normalized_fields:
                # Sum up the count field (e.g., "15 Fahrer" = 15 tours)
                tours_count += result.normalized_fields.get('count', 1)
        elif result.parse_status == ParseStatus.WARN:
            lines_warned += 1
            if result.normalized_fields:
                tours_count += result.normalized_fields.get('count', 1)
        elif result.parse_status == ParseStatus.FAIL:
            lines_failed += 1

    # Compute input hash (canonical representation)
    canonical_text = '\n'.join(canonical_lines)
    input_hash = hashlib.sha256(canonical_text.encode()).hexdigest()

    # Determine overall status
    if lines_failed > 0:
        overall_status = ForecastStatus.FAIL
    elif lines_warned > 0:
        overall_status = ForecastStatus.WARN
    else:
        overall_status = ForecastStatus.PASS

    # Count unique tour lines (lines with valid tours)
    lines_with_tours = lines_passed + lines_warned

    result = {
        "forecast_version_id": None,
        "status": overall_status.value,
        "lines_total": len(lines),
        "lines_passed": lines_passed,
        "lines_warned": lines_warned,
        "lines_failed": lines_failed,
        "lines_with_tours": lines_with_tours,  # Unique tour lines (e.g., 277)
        "tours_count": tours_count,  # Total tours (sum of counts, e.g., 1385)
        "input_hash": input_hash,
        "parse_results": parse_results,
        "canonical_text": canonical_text,
        "week_key": week_key,
        "week_anchor_date": week_anchor_date
    }

    # Save to database
    if save_to_db:
        # Check for existing forecast with same input_hash (deduplication)
        existing = get_forecast_by_input_hash(input_hash)
        if existing:
            # Forecast already exists - return existing ID
            result['forecast_version_id'] = existing['id']
            result['duplicate'] = True
            result['duplicate_message'] = f"Forecast already exists (ID: {existing['id']})"
            return result

        # Create forecast version
        parser_config_hash = hashlib.sha256(
            f"parser_v{config.PARSER_CONFIG_VERSION}".encode()
        ).hexdigest()

        forecast_version_id = create_forecast_version(
            source=source,
            input_hash=input_hash,
            parser_config_hash=parser_config_hash,
            status=overall_status.value,
            notes=notes or f"Parsed {tours_count} tours from {source}",
            week_key=week_key,
            week_anchor_date=week_anchor_date,
            tenant_id=tenant_id
        )

        result['forecast_version_id'] = forecast_version_id
        result['duplicate'] = False

        # Save raw lines
        for line_no, (line, parse_result) in enumerate(zip(lines, parse_results), start=1):
            create_tour_raw(
                forecast_version_id=forecast_version_id,
                line_no=line_no,
                raw_text=line,
                parse_status=parse_result.parse_status.value,
                parse_errors=[
                    {"code": i.code, "message": i.message, "severity": i.severity}
                    for i in parse_result.issues if i.severity == "ERROR"
                ] if parse_result.issues else None,
                parse_warnings=[
                    {"code": i.code, "message": i.message, "severity": i.severity}
                    for i in parse_result.issues if i.severity == "WARNING"
                ] if parse_result.issues else None,
                canonical_text=parse_result.canonical_text,
                tenant_id=tenant_id
            )

        # Save normalized tours
        from .models import compute_tour_fingerprint

        for parse_result in parse_results:
            if parse_result.normalized_fields and parse_result.parse_status != ParseStatus.FAIL:
                fields = parse_result.normalized_fields

                # Compute tour fingerprint
                fingerprint = compute_tour_fingerprint(
                    day=fields['day'],
                    start=fields['start_ts'],
                    end=fields['end_ts'],
                    depot=fields.get('depot'),
                    skill=None
                )

                # Generate span_group_key for split shifts
                span_group_key = None
                split_break_minutes = None
                if fields.get('is_split'):
                    # Format: "D{day}_{start1}-{end1}_{start2}-{end2}"
                    day_abbr = [k for k, v in DAY_NAMES.items() if v == fields['day'] and len(k) == 2][0]
                    span_group_key = (
                        f"{day_abbr}_"
                        f"{fields['split_start_1'].strftime('%H%M')}-{fields['split_end_1'].strftime('%H%M')}_"
                        f"{fields['split_start_2'].strftime('%H%M')}-{fields['split_end_2'].strftime('%H%M')}"
                    )
                    split_break_minutes = fields.get('split_break_minutes')

                create_tour_normalized(
                    forecast_version_id=forecast_version_id,
                    day=fields['day'],
                    start_ts=fields['start_ts'],
                    end_ts=fields['end_ts'],
                    duration_min=fields['duration_min'],
                    work_hours=fields['work_hours'],
                    tour_fingerprint=fingerprint,
                    count=fields.get('count', 1),
                    depot=fields.get('depot'),
                    skill=None,  # Not parsed yet
                    span_group_key=span_group_key,
                    split_break_minutes=split_break_minutes,
                    tenant_id=tenant_id
                )

    return result
