# Versioning Policy

**System**: SOLVEREIGN V3.7
**Standard**: Semantic Versioning 2.0.0
**Last Updated**: 2026-01-08

---

## 1) Semantic Versioning

SOLVEREIGN follows [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]

v3.7.0          # GA release
v3.7.1          # Patch release (bug fixes)
v3.8.0          # Minor release (new features, backward compatible)
v4.0.0          # Major release (breaking changes)
v3.7.0-rc1      # Release candidate
v3.7.0-alpha.1  # Alpha prerelease
```

---

## 2) Version Components

### 2.1 MAJOR Version

Increment when making **incompatible API changes**.

**Examples**:
- Removing an API endpoint
- Changing authentication mechanism
- Breaking database schema changes
- Changing response format incompatibly

```
v3.7.0 → v4.0.0  # Breaking API change
```

### 2.2 MINOR Version

Increment when adding **functionality in a backward compatible manner**.

**Examples**:
- New API endpoints
- New optional parameters
- New features
- New packs or skills
- Backward compatible database migrations

```
v3.7.0 → v3.8.0  # New feature added
```

### 2.3 PATCH Version

Increment when making **backward compatible bug fixes**.

**Examples**:
- Bug fixes
- Security patches
- Performance improvements
- Documentation updates

```
v3.7.0 → v3.7.1  # Bug fix
```

---

## 3) Prerelease Versions

### 3.1 Release Candidates (RC)

Used for staging validation before GA release.

```
v3.7.0-rc1      # First release candidate
v3.7.0-rc2      # Second release candidate (if issues found)
v3.7.0-rc3      # Third release candidate
v3.7.0          # GA release (promoted from rc)
```

**RC Rules**:
- RC must pass staging soak test (>=5 iterations)
- RC must pass all CI gates
- RC can be promoted to GA without code changes
- Each RC must have a unique number (no reuse)

### 3.2 Alpha and Beta

Used for early testing (not typically used for SOLVEREIGN).

```
v3.8.0-alpha.1  # Early development
v3.8.0-beta.1   # Feature complete, testing
v3.8.0-rc1      # Release candidate
v3.8.0          # GA
```

---

## 4) Version Locations

### 4.1 Source of Truth

The canonical version is stored in:

```python
# backend_py/api/__init__.py
__version__ = "3.7.0"
```

### 4.2 Other Locations

Versions are also recorded in:

| Location | Purpose |
|----------|---------|
| `pyproject.toml` | Python package version |
| `package.json` | Frontend version (if applicable) |
| Git tags | Release tracking |
| `release_manifest.json` | Release artifacts |
| Database `schema_migrations` | Migration versions |
| Health endpoint | Runtime version |

### 4.3 Keeping Versions in Sync

```bash
# Use bump-version script to update all locations
python scripts/bump_version.py --new-version 3.7.1

# This updates:
# - backend_py/api/__init__.py
# - pyproject.toml
# - Any other version locations
```

---

## 5) Migration Versioning

### 5.1 Migration Number Format

```
<sequence>_<description>.sql

Examples:
  001_initial_schema.sql
  006_multi_tenant.sql
  025_tenants_rls_fix.sql
  025a_rls_hardening.sql     # Sub-migration (related to 025)
  025b_rls_role_lockdown.sql
```

### 5.2 Sub-Migration Convention

When a migration requires multiple related files:

```
025_tenants_rls_fix.sql        # Main migration
025a_rls_hardening.sql         # Enhancement
025b_rls_role_lockdown.sql     # Further hardening
025c_rls_boundary_fix.sql      # Bug fix
025d_definer_owner_hardening.sql
025e_final_hardening.sql
025f_acl_fix.sql
```

### 5.3 Migration Version Tracking

```sql
-- schema_migrations table
CREATE TABLE schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Query current version
SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;
-- Result: 025f
```

---

## 6) API Versioning

### 6.1 URL Path Versioning

```
/api/v1/forecasts      # API version 1
/api/v2/forecasts      # API version 2 (future)
```

### 6.2 Version Compatibility

| API Version | Status | Support Until |
|-------------|--------|---------------|
| v1 | Current | Indefinite |
| v2 | Planned | N/A |

### 6.3 Deprecation Policy

When deprecating API features:

1. **Announce**: Document in CHANGELOG
2. **Warn**: Return `Deprecation` header for 2 minor versions
3. **Remove**: In next major version

```http
HTTP/1.1 200 OK
Deprecation: Sun, 01 Jun 2026 00:00:00 GMT
Sunset: Sun, 01 Sep 2026 00:00:00 GMT
Link: </api/v2/forecasts>; rel="successor-version"
```

---

## 7) Dependency Versioning

### 7.1 Python Dependencies

```
# requirements.txt - Use exact versions for reproducibility
fastapi==0.109.0
psycopg[binary]==3.1.17
pydantic==2.5.3
uvicorn==0.27.0
```

### 7.2 Version Ranges (Development)

```
# requirements.in - Allow compatible updates
fastapi>=0.109.0,<0.110.0
psycopg[binary]>=3.1.0,<4.0.0
```

### 7.3 Lock Files

```bash
# Generate locked requirements before release
pip-compile requirements.in --output-file requirements.lock.txt --generate-hashes
```

---

## 8) Docker Image Versioning

### 8.1 Tag Format

```
solvereign-api:<version>
solvereign-api:latest       # Points to latest GA
solvereign-api:v3.7.0       # Specific release
solvereign-api:v3.7.0-rc1   # Release candidate
solvereign-api:main         # Latest main branch (CI only)
```

### 8.2 Production Usage

```yaml
# Always use specific tags in production
services:
  api:
    image: solvereign-api:v3.7.0  # NOT :latest
```

---

## 9) Schema Versioning

### 9.1 JSON Schema Versioning

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://solvereign.com/schemas/evidence_pack/v1.0.0",
  "version": "1.0.0",
  "title": "Evidence Pack Schema"
}
```

### 9.2 Schema Version in Files

```
backend_py/schemas/
├── evidence_pack.schema.json      # v1.0.0
├── routing_evidence.schema.json   # v1.0.0
├── drift_report.schema.json       # v1.0.0
└── incident.schema.json           # v1.0.0
```

---

## 10) Component Version Matrix

### 10.1 Current Versions

| Component | Version | Notes |
|-----------|---------|-------|
| **Application** | 3.7.0 | Wien Pilot GA |
| **API** | v1 | Stable |
| **Database Schema** | 025f | Latest migration |
| **Python** | 3.11.x | Required |
| **PostgreSQL** | 16.x | Required |
| **FastAPI** | 0.109.x | Pinned |
| **OR-Tools** | 9.8.x | Solver |
| **OSRM** | PARKED | Not in use |

### 10.2 Compatibility Matrix

| SOLVEREIGN | Python | PostgreSQL | FastAPI |
|------------|--------|------------|---------|
| 3.7.x | 3.11+ | 15+, 16+ | 0.109+ |
| 3.6.x | 3.11+ | 15+, 16+ | 0.109+ |
| 3.5.x | 3.10+ | 15+ | 0.100+ |

---

## 11) Version Display

### 11.1 Health Endpoint

```json
GET /health

{
  "status": "healthy",
  "version": "3.7.0",
  "api_version": "v1",
  "migrations_version": "025f",
  "git_sha": "abc123def456"
}
```

### 11.2 CLI Version

```bash
$ solvereign --version
SOLVEREIGN v3.7.0 (abc123de)
API: v1
Database: 025f
Python: 3.11.0
```

---

## 12) Version Bumping Rules

### 12.1 Decision Tree

```
Is there a breaking API change?
├── Yes → Bump MAJOR
└── No → Is there new functionality?
         ├── Yes → Bump MINOR
         └── No → Bump PATCH
```

### 12.2 Specific Rules

| Change Type | Version Bump |
|-------------|--------------|
| Remove endpoint | MAJOR |
| Change response format (breaking) | MAJOR |
| Remove required field | MAJOR |
| Add new endpoint | MINOR |
| Add optional field | MINOR |
| Add new pack/skill | MINOR |
| New migration (backward compatible) | MINOR |
| Bug fix | PATCH |
| Security patch | PATCH |
| Performance improvement | PATCH |
| Documentation update | PATCH (or none) |

---

## 13) Pre-1.0 vs Post-1.0

### 13.1 Current Status

SOLVEREIGN is at **v3.x** (post-1.0), meaning:
- MAJOR version changes indicate breaking changes
- MINOR version changes are backward compatible
- Stable API contract expected

### 13.2 Historical Context

```
v1.x - Initial release (legacy)
v2.x - V2 solver architecture
v3.x - V3 event-sourced architecture (current)
v4.x - Future (multi-region, etc.)
```

---

## 14) References

- [Semantic Versioning 2.0.0](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [RELEASE.md](RELEASE.md) - Release process
- [CHANGELOG.md](CHANGELOG.md) - Version history

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Owner**: Platform Engineering
