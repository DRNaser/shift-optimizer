# FLS Import Contract - Wien Pilot

> **Version**: 1.0
> **Last Updated**: 2026-01-18
> **Status**: DRAFT - Requires Customer Validation

---

## Overview

This document defines the data contract for importing tour data from FLS (Fleet Logistics System) into SOLVEREIGN for the Wien Pilot deployment.

---

## Required Fields

| Field | Type | Required | Example | Description |
|-------|------|----------|---------|-------------|
| `external_order_id` | STRING | YES | `"FLS-2026-001234"` | Unique identifier from FLS |
| `service_code` | STRING | YES | `"DELIVERY"` | Service type code |
| `time_window_start` | ISO8601 | YES | `"2026-01-20T06:00:00+01:00"` | Earliest start time |
| `time_window_end` | ISO8601 | YES | `"2026-01-20T10:00:00+01:00"` | Latest end time |
| `duration_min` | INTEGER | YES | `30` | Expected service duration in minutes |
| `depot_id` | STRING | YES | `"WIEN_HQ"` | Depot/hub identifier |
| `site_id` | INTEGER | YES | `10` | SOLVEREIGN site mapping (see below) |

---

## Optional Fields

| Field | Type | Default | Example | Description |
|-------|------|---------|---------|-------------|
| `lat` | FLOAT | NULL | `48.2082` | Latitude (WGS84) |
| `lng` | FLOAT | NULL | `16.3738` | Longitude (WGS84) |
| `skill_required` | STRING | NULL | `"ADR"` | Required driver certification |
| `priority` | INTEGER | `5` | `1-10` | Order priority (1=highest) |
| `customer_name` | STRING | NULL | `"Mustermann GmbH"` | Customer display name |
| `notes` | STRING | NULL | `"Ring twice"` | Delivery instructions |

---

## Site Mapping

| FLS Depot | SOLVEREIGN site_id | Description |
|-----------|-------------------|-------------|
| `WIEN_HQ` | `10` | Wien Hauptstandort |
| `WIEN_SUED` | `11` | Wien Süd |
| `WIEN_NORD` | `12` | Wien Nord |

**Unmapped depot**: Reject with `INVALID_DEPOT` error.

---

## Geolocation Rules

| Condition | Action |
|-----------|--------|
| `lat` AND `lng` provided | Use for routing optimization |
| `lat` OR `lng` missing | Use depot-based static matrix |
| Both missing | Log warning, use depot fallback |

**Note**: For Wien Pilot, OSRM/static matrix decision is made at solve time, not import time.

---

## Validation Rules

### Hard Rejections (Order NOT imported)

| Code | Condition | Example |
|------|-----------|---------|
| `MISSING_REQUIRED` | Any required field is NULL/empty | `external_order_id` missing |
| `INVALID_TIME_WINDOW` | `time_window_end <= time_window_start` | End before start |
| `INVALID_DURATION` | `duration_min <= 0 OR duration_min > 480` | Negative or >8h |
| `INVALID_DEPOT` | `depot_id` not in site mapping | Unknown depot |
| `DUPLICATE_ORDER` | `external_order_id` already exists for date | Same order twice |

### Soft Warnings (Order imported with flag)

| Code | Condition | Action |
|------|-----------|--------|
| `MISSING_GEOCODE` | `lat` or `lng` missing | Use depot fallback |
| `WIDE_TIME_WINDOW` | Window > 6 hours | Log warning |
| `SHORT_DURATION` | `duration_min < 5` | Log warning |

---

## File Format

### CSV (Primary)

```csv
external_order_id,service_code,time_window_start,time_window_end,duration_min,depot_id,site_id,lat,lng,skill_required
FLS-2026-001234,DELIVERY,2026-01-20T06:00:00+01:00,2026-01-20T10:00:00+01:00,30,WIEN_HQ,10,48.2082,16.3738,
FLS-2026-001235,DELIVERY,2026-01-20T08:00:00+01:00,2026-01-20T12:00:00+01:00,45,WIEN_HQ,10,48.1951,16.3650,ADR
```

**Encoding**: UTF-8 with BOM
**Delimiter**: Comma (`,`)
**Quote char**: Double quote (`"`) for fields containing commas
**Header**: Required

### JSON (Alternative)

```json
{
  "contract_version": "1.0",
  "export_date": "2026-01-20",
  "orders": [
    {
      "external_order_id": "FLS-2026-001234",
      "service_code": "DELIVERY",
      "time_window_start": "2026-01-20T06:00:00+01:00",
      "time_window_end": "2026-01-20T10:00:00+01:00",
      "duration_min": 30,
      "depot_id": "WIEN_HQ",
      "site_id": 10,
      "lat": 48.2082,
      "lng": 16.3738,
      "skill_required": null
    }
  ]
}
```

---

## Import Response

### Success Response

```json
{
  "status": "SUCCESS",
  "import_run_id": "IR-2026-01-20-001",
  "total_orders": 150,
  "imported": 148,
  "rejected": 2,
  "warnings": 5,
  "rejected_orders": [
    {
      "external_order_id": "FLS-2026-001299",
      "reason": "INVALID_TIME_WINDOW",
      "details": "time_window_end before time_window_start"
    }
  ]
}
```

### Failure Response

```json
{
  "status": "FAILED",
  "error": "PARSE_ERROR",
  "details": "Invalid CSV format at line 47",
  "imported": 0,
  "rejected": 0
}
```

---

## Versioning

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-18 | Initial contract for Wien Pilot |

**Contract Compatibility**: Breaking changes require version bump and 2-week migration period.

---

## Contact

For contract clarifications:
- Technical: [SOLVEREIGN Tech Lead]
- FLS Export: [Customer IT Contact]

---

*This contract is the single source of truth for FLS data import.*
