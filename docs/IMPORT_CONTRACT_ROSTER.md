# Import Contract: Roster Input

**System**: SOLVEREIGN V3.7
**Pack**: Roster (Shift Scheduling)
**Version**: 1.0.0
**Last Updated**: 2026-01-08

---

## 1) Overview

This document defines the canonical import contract for roster/shift scheduling input data. Customer data must be transformed to this format before processing.

**Supported Input Formats**:
- JSON (preferred)
- CSV (with header row)

**Validation Script**: `scripts/validate_import_contract.py`

---

## 2) Contract Schema

### 2.1 Top-Level Structure

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://solvereign.com/schemas/import_contract_roster/v1.0.0",
  "version": "1.0.0",
  "type": "object",
  "required": ["tenant_code", "site_code", "week_anchor_date", "tours"],
  "properties": {
    "tenant_code": {
      "type": "string",
      "description": "Unique tenant identifier",
      "pattern": "^[a-z][a-z0-9_]{2,30}$"
    },
    "site_code": {
      "type": "string",
      "description": "Site/depot identifier within tenant",
      "pattern": "^[a-z][a-z0-9_]{2,30}$"
    },
    "week_anchor_date": {
      "type": "string",
      "format": "date",
      "description": "Monday of the target week (YYYY-MM-DD)"
    },
    "service_code": {
      "type": "string",
      "description": "Service type (e.g., delivery, pickup)",
      "default": "default"
    },
    "tours": {
      "type": "array",
      "items": { "$ref": "#/definitions/Tour" },
      "minItems": 1
    },
    "drivers": {
      "type": "array",
      "items": { "$ref": "#/definitions/Driver" },
      "description": "Optional driver roster (if pre-defined)"
    },
    "vehicles": {
      "type": "array",
      "items": { "$ref": "#/definitions/Vehicle" },
      "description": "Optional vehicle list"
    },
    "metadata": {
      "type": "object",
      "description": "Optional metadata for traceability"
    }
  }
}
```

### 2.2 Tour Definition

```json
{
  "definitions": {
    "Tour": {
      "type": "object",
      "required": ["external_id", "day", "start_time", "end_time"],
      "properties": {
        "external_id": {
          "type": "string",
          "description": "Customer's unique tour identifier",
          "maxLength": 100
        },
        "day": {
          "type": "integer",
          "minimum": 1,
          "maximum": 7,
          "description": "Day of week (1=Mon, 2=Tue, ..., 7=Sun)"
        },
        "start_time": {
          "type": "string",
          "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$",
          "description": "Start time (HH:MM, 24h format)"
        },
        "end_time": {
          "type": "string",
          "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$",
          "description": "End time (HH:MM, 24h format)"
        },
        "count": {
          "type": "integer",
          "minimum": 1,
          "default": 1,
          "description": "Number of drivers needed for this tour"
        },
        "depot": {
          "type": "string",
          "description": "Depot/start location code",
          "default": "default"
        },
        "skill": {
          "type": "string",
          "description": "Required skill/certification",
          "default": "standard"
        },
        "priority": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10,
          "default": 5,
          "description": "Assignment priority (1=highest)"
        },
        "lat": {
          "type": "number",
          "minimum": -90,
          "maximum": 90,
          "description": "Latitude (optional, for routing)"
        },
        "lng": {
          "type": "number",
          "minimum": -180,
          "maximum": 180,
          "description": "Longitude (optional, for routing)"
        },
        "volume": {
          "type": "number",
          "minimum": 0,
          "description": "Estimated volume/load (optional)"
        },
        "notes": {
          "type": "string",
          "maxLength": 500,
          "description": "Free-text notes"
        }
      }
    }
  }
}
```

### 2.3 Driver Definition (Optional)

```json
{
  "definitions": {
    "Driver": {
      "type": "object",
      "required": ["external_id", "name"],
      "properties": {
        "external_id": {
          "type": "string",
          "description": "Customer's driver identifier",
          "maxLength": 100
        },
        "name": {
          "type": "string",
          "description": "Driver display name",
          "maxLength": 200
        },
        "skills": {
          "type": "array",
          "items": { "type": "string" },
          "description": "List of skills/certifications"
        },
        "depot": {
          "type": "string",
          "description": "Home depot assignment"
        },
        "max_hours_week": {
          "type": "number",
          "minimum": 0,
          "maximum": 60,
          "default": 48,
          "description": "Maximum weekly hours"
        },
        "contract_type": {
          "type": "string",
          "enum": ["full_time", "part_time", "flex"],
          "default": "full_time"
        },
        "unavailable_days": {
          "type": "array",
          "items": { "type": "integer", "minimum": 1, "maximum": 7 },
          "description": "Days driver is unavailable"
        }
      }
    }
  }
}
```

### 2.4 Vehicle Definition (Optional)

```json
{
  "definitions": {
    "Vehicle": {
      "type": "object",
      "required": ["external_id"],
      "properties": {
        "external_id": {
          "type": "string",
          "description": "Customer's vehicle identifier",
          "maxLength": 100
        },
        "type": {
          "type": "string",
          "description": "Vehicle type (e.g., van, truck)"
        },
        "capacity": {
          "type": "number",
          "minimum": 0,
          "description": "Load capacity"
        },
        "depot": {
          "type": "string",
          "description": "Home depot"
        }
      }
    }
  }
}
```

---

## 3) Validation Rules

### 3.1 Hard Gates (FAIL if violated)

| Gate ID | Rule | Error Code |
|---------|------|------------|
| **HG-001** | `tenant_code` required and valid pattern | `MISSING_TENANT` |
| **HG-002** | `site_code` required and valid pattern | `MISSING_SITE` |
| **HG-003** | `week_anchor_date` required and is Monday | `INVALID_ANCHOR` |
| **HG-004** | At least 1 tour in `tours` array | `NO_TOURS` |
| **HG-005** | Each tour has unique `external_id` | `DUPLICATE_TOUR_ID` |
| **HG-006** | `day` between 1-7 | `INVALID_DAY` |
| **HG-007** | `start_time` valid HH:MM format | `INVALID_START_TIME` |
| **HG-008** | `end_time` valid HH:MM format | `INVALID_END_TIME` |

### 3.2 Soft Gates (WARN if violated)

| Gate ID | Rule | Warning Code |
|---------|------|--------------|
| **SG-001** | `count` > 0 (default: 1) | `DEFAULT_COUNT` |
| **SG-002** | `depot` provided (default: "default") | `DEFAULT_DEPOT` |
| **SG-003** | `skill` provided (default: "standard") | `DEFAULT_SKILL` |
| **SG-004** | Tour duration > 0 and < 16h | `UNUSUAL_DURATION` |
| **SG-005** | Coordinates within expected region | `COORDS_OUT_OF_BOUNDS` |

### 3.3 Cross-Field Validation

| Rule | Error/Warning |
|------|---------------|
| If `lat` provided, `lng` required | `INCOMPLETE_COORDS` (WARN) |
| Driver `external_id` referenced in tours must exist in `drivers` | `UNKNOWN_DRIVER` (WARN) |
| Depot referenced must be consistent | `INCONSISTENT_DEPOT` (WARN) |

---

## 4) CSV Format

### 4.1 Tours CSV

```csv
external_id,day,start_time,end_time,count,depot,skill,priority,lat,lng,volume,notes
TOUR-001,1,08:00,16:00,2,depot_west,standard,5,,,,"Morning shift"
TOUR-002,1,14:00,22:00,1,depot_east,refrigerated,3,48.2082,16.3738,150,
TOUR-003,2,06:00,14:00,3,depot_west,standard,5,,,,
TOUR-004,2,22:00,06:00,1,depot_central,hazmat,2,,,,"Night shift, crosses midnight"
```

**Header Requirements**:
- First row MUST be header
- Required columns: `external_id`, `day`, `start_time`, `end_time`
- Optional columns filled with defaults if missing

### 4.2 Drivers CSV (Optional)

```csv
external_id,name,skills,depot,max_hours_week,contract_type,unavailable_days
DRV-001,Max Mustermann,"standard,refrigerated",depot_west,48,full_time,
DRV-002,Anna Schmidt,standard,depot_east,40,full_time,"6,7"
DRV-003,Hans Weber,"standard,hazmat",depot_central,30,part_time,
```

**Skills Format**: Comma-separated within quotes
**Unavailable Days Format**: Comma-separated integers within quotes

---

## 5) Sample Dataset

### 5.1 Minimal JSON Example

```json
{
  "tenant_code": "wien_pilot",
  "site_code": "site_001",
  "week_anchor_date": "2026-01-06",
  "service_code": "delivery",
  "tours": [
    {
      "external_id": "TOUR-001",
      "day": 1,
      "start_time": "08:00",
      "end_time": "16:00",
      "count": 2,
      "depot": "depot_west"
    },
    {
      "external_id": "TOUR-002",
      "day": 1,
      "start_time": "14:00",
      "end_time": "22:00",
      "count": 1,
      "depot": "depot_east",
      "skill": "refrigerated"
    },
    {
      "external_id": "TOUR-003",
      "day": 2,
      "start_time": "06:00",
      "end_time": "14:00",
      "count": 3
    }
  ],
  "metadata": {
    "source": "customer_export",
    "exported_at": "2026-01-05T15:00:00Z"
  }
}
```

### 5.2 Full JSON Example

```json
{
  "tenant_code": "wien_pilot",
  "site_code": "site_001",
  "week_anchor_date": "2026-01-06",
  "service_code": "delivery",
  "tours": [
    {
      "external_id": "TOUR-001",
      "day": 1,
      "start_time": "08:00",
      "end_time": "16:00",
      "count": 2,
      "depot": "depot_west",
      "skill": "standard",
      "priority": 5,
      "lat": 48.2082,
      "lng": 16.3738,
      "volume": 100,
      "notes": "Regular morning delivery"
    },
    {
      "external_id": "TOUR-002",
      "day": 1,
      "start_time": "22:00",
      "end_time": "06:00",
      "count": 1,
      "depot": "depot_central",
      "skill": "hazmat",
      "priority": 2,
      "notes": "Night shift, crosses midnight"
    }
  ],
  "drivers": [
    {
      "external_id": "DRV-001",
      "name": "Max Mustermann",
      "skills": ["standard", "refrigerated"],
      "depot": "depot_west",
      "max_hours_week": 48,
      "contract_type": "full_time"
    },
    {
      "external_id": "DRV-002",
      "name": "Anna Schmidt",
      "skills": ["standard"],
      "depot": "depot_east",
      "max_hours_week": 30,
      "contract_type": "part_time",
      "unavailable_days": [6, 7]
    }
  ],
  "vehicles": [
    {
      "external_id": "VEH-001",
      "type": "van",
      "capacity": 500,
      "depot": "depot_west"
    }
  ],
  "metadata": {
    "source": "customer_erp",
    "exported_at": "2026-01-05T15:00:00Z",
    "version": "1.0"
  }
}
```

---

## 6) External ID Mapping

### 6.1 Purpose

Customer systems use their own identifiers. SOLVEREIGN maintains mappings to canonical internal IDs.

### 6.2 Mapping Flow

```
Customer External ID  →  Master Data Mapping  →  Canonical Internal ID
    "DRV-001"         →  ExternalMapping      →  driver_id: 12345
    "TOUR-001"        →  ExternalMapping      →  tour_instance_id: 67890
```

### 6.3 Resolution Rules

1. On import, check if `external_id` exists in `external_mappings`
2. If exists, use mapped canonical ID
3. If not exists, create new canonical entity and mapping
4. Never store external IDs directly in core tables

---

## 7) Validation Script Usage

### 7.1 Command Line

```bash
# Validate JSON file
python scripts/validate_import_contract.py --input data.json

# Validate CSV file
python scripts/validate_import_contract.py --input tours.csv --format csv

# Output canonical JSON
python scripts/validate_import_contract.py --input data.json --output canonical.json

# Strict mode (WARN = FAIL)
python scripts/validate_import_contract.py --input data.json --strict

# Verbose output
python scripts/validate_import_contract.py --input data.json --verbose
```

### 7.2 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Valid, no errors or warnings |
| 1 | Valid with warnings |
| 2 | Invalid, hard gate failures |

### 7.3 Output Format

```json
{
  "status": "PASS",
  "input_file": "data.json",
  "input_hash": "sha256:abc123...",
  "validation": {
    "hard_gates": {
      "passed": 8,
      "failed": 0,
      "results": []
    },
    "soft_gates": {
      "passed": 3,
      "warnings": 2,
      "results": [
        {
          "gate": "SG-002",
          "message": "Tour TOUR-003: depot defaulted to 'default'",
          "line": 15,
          "field": "depot"
        }
      ]
    }
  },
  "summary": {
    "tours": 3,
    "drivers": 0,
    "vehicles": 0,
    "total_tour_instances": 6
  },
  "canonical_output": "canonical.json"
}
```

---

## 8) Error Messages

### 8.1 Hard Gate Errors

| Code | Message Template |
|------|------------------|
| `MISSING_TENANT` | `Required field 'tenant_code' is missing` |
| `MISSING_SITE` | `Required field 'site_code' is missing` |
| `INVALID_ANCHOR` | `week_anchor_date '{date}' is not a Monday` |
| `NO_TOURS` | `At least one tour is required` |
| `DUPLICATE_TOUR_ID` | `Duplicate external_id '{id}' at lines {l1}, {l2}` |
| `INVALID_DAY` | `Tour '{id}': day {day} must be 1-7` |
| `INVALID_START_TIME` | `Tour '{id}': invalid start_time '{time}'` |
| `INVALID_END_TIME` | `Tour '{id}': invalid end_time '{time}'` |

### 8.2 Soft Gate Warnings

| Code | Message Template |
|------|------------------|
| `DEFAULT_COUNT` | `Tour '{id}': count defaulted to 1` |
| `DEFAULT_DEPOT` | `Tour '{id}': depot defaulted to 'default'` |
| `DEFAULT_SKILL` | `Tour '{id}': skill defaulted to 'standard'` |
| `UNUSUAL_DURATION` | `Tour '{id}': duration {hours}h may be unusual` |
| `COORDS_OUT_OF_BOUNDS` | `Tour '{id}': coordinates outside expected region` |

---

## 9) Integration with SOLVEREIGN

### 9.1 Import Flow

```
1. Customer provides file (JSON/CSV)
              │
              ▼
2. validate_import_contract.py
   - Hard gates → FAIL or PASS
   - Soft gates → WARN logged
              │
              ▼
3. Canonical JSON output
              │
              ▼
4. Master data mapping resolution
   - external_id → canonical_id
              │
              ▼
5. Insert into forecast_versions + tours_normalized
              │
              ▼
6. Expand to tour_instances
              │
              ▼
7. Ready for solver
```

### 9.2 API Endpoint (Future)

```http
POST /api/v1/import/roster
Content-Type: application/json

{
  "tenant_code": "wien_pilot",
  "site_code": "site_001",
  ...
}

Response:
{
  "status": "accepted",
  "forecast_version_id": 123,
  "validation": {...},
  "warnings": [...]
}
```

---

## 10) Sample Dataset Files

Sample datasets are located in:

```
golden_datasets/roster/
├── wien_pilot_minimal/
│   ├── input.json           # Minimal valid input
│   ├── expected_output.json # Expected canonical output
│   └── README.md
├── wien_pilot_full/
│   ├── input.json           # Full featured input
│   ├── drivers.csv          # Driver roster
│   ├── expected_output.json
│   └── README.md
└── error_cases/
    ├── missing_tenant.json  # FAIL: HG-001
    ├── duplicate_ids.json   # FAIL: HG-005
    ├── invalid_times.json   # FAIL: HG-007, HG-008
    └── README.md
```

---

**Document Version**: 1.0

**Schema Version**: 1.0.0

**Last Updated**: 2026-01-08

**Owner**: Product Engineering
