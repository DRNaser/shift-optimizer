# FLS Export Contract v1.0

> **Status**: FROZEN
> **Effective**: 2026-01-06
> **Owner**: SOLVEREIGN Routing Pack

---

## 1. Overview

This document defines the **frozen contract** for FLS (Fleet Logistics System) data export/import.
All routing scenarios must conform to this specification.

**Contract Version**: `1.0`
**Breaking changes require version bump and migration path.**

---

## 2. File Format

### 2.1 General Rules

| Property | Value |
|----------|-------|
| Format | CSV (RFC 4180 compliant) |
| Encoding | UTF-8 (with BOM for Excel compatibility) |
| Line Ending | CRLF (`\r\n`) |
| Delimiter | Semicolon (`;`) |
| Quoting | Double quotes for fields containing delimiter, newline, or quotes |
| Escape | Double quote (`""`) within quoted fields |

### 2.2 File Naming Convention

```
{tenant_slug}_{vertical}_{plan_date}_{version}.csv

Examples:
lts-transport_MEDIAMARKT_2026-01-06_v1.csv
lts-transport_HDL_PLUS_2026-01-06_v2.csv
```

---

## 3. Stop Export Headers

### 3.1 Required Headers (MUST be present)

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `order_id` | STRING | Unique order identifier | `ORD-2026-001234` |
| `service_code` | STRING | Service type code | `MM_DELIVERY_MONTAGE` |
| `address_raw` | STRING | Full address string | `Hauptstr. 123, 12345 Berlin` |
| `lat` | DECIMAL(10,7) | Latitude (WGS84) | `52.5200000` |
| `lng` | DECIMAL(10,7) | Longitude (WGS84) | `13.4050000` |
| `tw_start` | ISO8601 | Time window start | `2026-01-06T08:00:00+01:00` |
| `tw_end` | ISO8601 | Time window end | `2026-01-06T12:00:00+01:00` |
| `tw_is_hard` | BOOLEAN | Hard constraint flag | `true` |

### 3.2 Optional Headers

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `service_duration_min` | INTEGER | From template | Override service time |
| `requires_two_person` | BOOLEAN | `false` | 2-Mann requirement |
| `required_skills` | STRING[] | `[]` | Pipe-separated skills |
| `volume_m3` | DECIMAL | `0.0` | Volume in cubic meters |
| `weight_kg` | DECIMAL | `0.0` | Weight in kilograms |
| `floor` | INTEGER | `null` | Floor number |
| `priority` | ENUM | `NORMAL` | `NORMAL\|HIGH\|CRITICAL` |
| `customer_name` | STRING | `null` | Customer display name |
| `customer_phone` | STRING | `null` | Contact phone |
| `notes` | STRING | `null` | Delivery notes |

---

## 4. Timezone Rules (CRITICAL)

### 4.1 General Principle

**All timestamps MUST include timezone offset.**

```
CORRECT:   2026-01-06T08:00:00+01:00
CORRECT:   2026-01-06T08:00:00Z
WRONG:     2026-01-06T08:00:00         (no timezone)
WRONG:     2026-01-06 08:00            (not ISO8601)
```

### 4.2 Timezone Handling

| Scenario | Rule |
|----------|------|
| Input without TZ | **REJECT** with error `MISSING_TIMEZONE` |
| Input with `Z` suffix | Convert to scenario timezone |
| Input with offset | Use as-is, convert for display |
| DST transitions | Use explicit offset, not zone name |

### 4.3 Reference Timezone

Each scenario has a `timezone` field (e.g., `Europe/Berlin`).
- Used for display formatting
- Used for day boundary calculation
- **NOT** used for timestamp parsing (use explicit offset)

### 4.4 Implementation

```python
# CORRECT: Parse with timezone
from datetime import datetime
from zoneinfo import ZoneInfo

def parse_timestamp(value: str, scenario_tz: str) -> datetime:
    """Parse ISO8601 timestamp with timezone."""
    if not value:
        raise ValueError("MISSING_TIMESTAMP")

    # Must have timezone info
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"MISSING_TIMEZONE: {value}")

    return dt

# WRONG: Naive datetime
def parse_timestamp_wrong(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")  # NO!
```

---

## 5. Geocoding Rules (lat/lng)

### 5.1 Coordinate Format

| Property | Specification |
|----------|---------------|
| Datum | WGS84 |
| Latitude | Decimal degrees, 7 decimal places |
| Longitude | Decimal degrees, 7 decimal places |
| Valid lat range | -90.0 to +90.0 |
| Valid lng range | -180.0 to +180.0 |

### 5.2 Geocode Quality

| Quality | lat/lng | address_raw | Action |
|---------|---------|-------------|--------|
| `HIGH` | Present, verified | Present | Use coordinates |
| `MEDIUM` | Present, unverified | Present | Use with warning |
| `LOW` | Present, interpolated | Present | Use with warning |
| `MANUAL` | User-corrected | Present | Use coordinates |
| `MISSING` | NULL/empty | Present | Geocode on import |
| `FAILED` | NULL/empty | Invalid | **REJECT** |

### 5.3 Missing Geocode Handling

```python
# On import, if lat/lng missing:
if stop.lat is None or stop.lng is None:
    if stop.address_raw:
        # Attempt geocoding
        result = geocoder.geocode(stop.address_raw)
        if result.success:
            stop.lat = result.lat
            stop.lng = result.lng
            stop.geocode_quality = result.quality
        else:
            # Add to validation warnings
            warnings.append(f"GEOCODE_FAILED: {stop.order_id}")
            stop.geocode_quality = "FAILED"
    else:
        # No address = REJECT
        errors.append(f"NO_ADDRESS: {stop.order_id}")
```

### 5.4 Germany Bounding Box (Plausibility Check)

```python
GERMANY_BBOX = {
    "min_lat": 47.2,   # Southern border
    "max_lat": 55.1,   # Northern border
    "min_lng": 5.8,    # Western border
    "max_lng": 15.1,   # Eastern border
}

def validate_coordinates(lat: float, lng: float) -> bool:
    """Check if coordinates are within Germany."""
    return (
        GERMANY_BBOX["min_lat"] <= lat <= GERMANY_BBOX["max_lat"]
        and GERMANY_BBOX["min_lng"] <= lng <= GERMANY_BBOX["max_lng"]
    )
```

---

## 6. Time Window Rules

### 6.1 Time Window Types

| Type | `tw_is_hard` | Behavior |
|------|--------------|----------|
| Hard | `true` | Vehicle MUST arrive within window. Violation = infeasible. |
| Soft | `false` | Arrival outside window incurs penalty. Solution still valid. |

### 6.2 Validation Rules

```python
def validate_time_window(tw_start: datetime, tw_end: datetime) -> list[str]:
    errors = []

    # Rule 1: End must be after start
    if tw_end <= tw_start:
        errors.append("TW_END_BEFORE_START")

    # Rule 2: Minimum window duration (15 minutes)
    duration = (tw_end - tw_start).total_seconds() / 60
    if duration < 15:
        errors.append(f"TW_TOO_SHORT: {duration}min < 15min")

    # Rule 3: Maximum window duration (12 hours)
    if duration > 720:
        errors.append(f"TW_TOO_LONG: {duration}min > 720min")

    # Rule 4: Window must be in future (for new scenarios)
    if tw_end < datetime.now(tz=tw_end.tzinfo):
        errors.append("TW_IN_PAST")

    return errors
```

### 6.3 Cross-Midnight Time Windows

Time windows spanning midnight are **supported**:

```
# Customer available from 22:00 to 06:00 next day
tw_start: 2026-01-06T22:00:00+01:00
tw_end:   2026-01-07T06:00:00+01:00

# Validation: tw_end > tw_start (different dates OK)
```

### 6.4 Default Time Windows (by Service Code)

| Service Code | Default Window | Notes |
|--------------|----------------|-------|
| `MM_DELIVERY` | 08:00-18:00 | Standard delivery |
| `MM_DELIVERY_MONTAGE` | 08:00-20:00 | Extended for installation |
| `MM_ENTSORGUNG` | 08:00-16:00 | Disposal pickup |
| `HDL_MONTAGE_STANDARD` | 07:00-19:00 | Full day montage |
| `HDL_MONTAGE_COMPLEX` | 07:00-20:00 | Extended complex |

---

## 7. Vehicle Export Headers

### 7.1 Required Headers

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `vehicle_id` | STRING | Unique vehicle ID | `VAN-HH-001` |
| `team_size` | INTEGER | Crew size (1 or 2) | `2` |
| `shift_start_at` | ISO8601 | Shift start time | `2026-01-06T06:00:00+01:00` |
| `shift_end_at` | ISO8601 | Shift end time | `2026-01-06T18:00:00+01:00` |
| `start_depot_id` | STRING | Starting depot | `DEPOT-HH-NORD` |
| `end_depot_id` | STRING | Ending depot | `DEPOT-HH-NORD` |

### 7.2 Optional Headers

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `skills` | STRING[] | `[]` | Pipe-separated skills |
| `capacity_volume_m3` | DECIMAL | `null` | Volume capacity |
| `capacity_weight_kg` | DECIMAL | `null` | Weight capacity |
| `driver_name` | STRING | `null` | Driver display name |
| `driver_phone` | STRING | `null` | Driver contact |

---

## 8. Depot Export Headers

### 8.1 Required Headers

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `depot_id` | STRING | Unique depot ID | `DEPOT-HH-NORD` |
| `name` | STRING | Depot name | `Hamburg Nord` |
| `lat` | DECIMAL(10,7) | Latitude | `53.5511000` |
| `lng` | DECIMAL(10,7) | Longitude | `9.9937000` |

### 8.2 Optional Headers

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `loading_time_min` | INTEGER | `15` | Default loading time |
| `address` | STRING | `null` | Depot address |

---

## 9. Service Codes (Frozen List)

### 9.1 MediaMarkt Verticals

| Code | Description | Base Duration | 2-Mann |
|------|-------------|---------------|--------|
| `MM_DELIVERY` | Standard delivery | 10 min | No |
| `MM_DELIVERY_MONTAGE` | Delivery + installation | 60 min | Yes |
| `MM_ENTSORGUNG` | Disposal pickup | 15 min | No |
| `MM_PICKUP` | Store pickup | 10 min | No |

### 9.2 HDL Plus Verticals

| Code | Description | Base Duration | 2-Mann |
|------|-------------|---------------|--------|
| `HDL_MONTAGE_STANDARD` | Standard montage | 90 min | Yes |
| `HDL_MONTAGE_COMPLEX` | Complex montage | 150 min | Yes |
| `HDL_DELIVERY` | HDL delivery | 15 min | No |

### 9.3 Unknown Service Code Handling

```python
def get_service_template(service_code: str) -> JobTemplate:
    """Get template for service code, with fallback."""
    if service_code in JOB_TEMPLATES:
        return JOB_TEMPLATES[service_code]

    # Log warning for unknown code
    logger.warning(f"Unknown service_code: {service_code}, using FALLBACK")

    return JobTemplate(
        base_service_min=30,
        variance_min=15,
        risk_buffer_min=10,
        default_skills=[],
        requires_two_person=False,
    )
```

---

## 10. Validation Summary

### 10.1 REJECT (Hard Errors)

| Code | Description |
|------|-------------|
| `MISSING_ORDER_ID` | order_id is empty |
| `MISSING_SERVICE_CODE` | service_code is empty |
| `MISSING_TIMEZONE` | Timestamp without timezone |
| `TW_END_BEFORE_START` | Invalid time window |
| `NO_ADDRESS` | No address and no coordinates |
| `INVALID_COORDINATES` | lat/lng out of valid range |
| `DUPLICATE_ORDER_ID` | Duplicate order in same scenario |

### 10.2 WARN (Soft Warnings)

| Code | Description |
|------|-------------|
| `GEOCODE_FAILED` | Could not geocode address |
| `COORDS_OUTSIDE_GERMANY` | Coordinates outside DE bbox |
| `TW_TOO_SHORT` | Time window < 15 min |
| `TW_TOO_LONG` | Time window > 12 hours |
| `UNKNOWN_SERVICE_CODE` | Using fallback template |
| `MISSING_SKILLS` | Vehicle may not have required skills |

### 10.3 Validation Response

```json
{
  "status": "PASS|WARN|FAIL",
  "errors": [
    {"code": "MISSING_TIMEZONE", "stop_id": "ORD-001", "field": "tw_start"}
  ],
  "warnings": [
    {"code": "COORDS_OUTSIDE_GERMANY", "stop_id": "ORD-002", "lat": 48.1, "lng": 16.3}
  ],
  "stats": {
    "total_stops": 150,
    "valid_stops": 148,
    "rejected_stops": 2,
    "warning_stops": 5
  }
}
```

---

## 11. Example CSV

### 11.1 Stops CSV

```csv
order_id;service_code;address_raw;lat;lng;tw_start;tw_end;tw_is_hard;requires_two_person;required_skills;volume_m3;weight_kg
ORD-2026-001234;MM_DELIVERY_MONTAGE;Hauptstr. 123, 12345 Berlin;52.5200000;13.4050000;2026-01-06T08:00:00+01:00;2026-01-06T12:00:00+01:00;true;true;MONTAGE_BASIC;2.5;150.0
ORD-2026-001235;MM_DELIVERY;Nebenstr. 45, 12345 Berlin;52.5150000;13.4100000;2026-01-06T10:00:00+01:00;2026-01-06T14:00:00+01:00;false;false;;0.5;25.0
```

### 11.2 Vehicles CSV

```csv
vehicle_id;team_size;shift_start_at;shift_end_at;start_depot_id;end_depot_id;skills;capacity_volume_m3;capacity_weight_kg
VAN-HH-001;2;2026-01-06T06:00:00+01:00;2026-01-06T18:00:00+01:00;DEPOT-HH-NORD;DEPOT-HH-NORD;MONTAGE_BASIC|ELEKTRO;15.0;1000.0
VAN-HH-002;1;2026-01-06T07:00:00+01:00;2026-01-06T17:00:00+01:00;DEPOT-HH-NORD;DEPOT-HH-NORD;;12.0;800.0
```

---

## 12. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-06 | Initial frozen contract |

---

**Contract Status: FROZEN**

Any changes require:
1. Version bump (1.0 → 1.1 or 2.0)
2. Migration documentation
3. Backwards compatibility plan
4. Stakeholder sign-off
