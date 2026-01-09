# ADR-002: Travel Time Provider Decision

> **Status**: DECIDED
> **Date**: 2026-01-06
> **Decision**: Hybrid (StaticMatrix for Pilot, OSRM for Production)

---

## Context

SOLVEREIGN Routing Pack requires travel time and distance matrices for VRP optimization.
The choice of provider impacts:
- **Accuracy**: Road-based vs straight-line distances
- **Performance**: API latency vs local computation
- **Cost**: Self-hosted vs paid API
- **Coverage**: Geographic availability

## Decision Drivers

1. **Pilot Phase**: Need quick deployment without infrastructure setup
2. **Production Phase**: Need accurate road-based routing
3. **Fallback**: Must work even if external API fails
4. **Evidence**: Matrix must be reproducible for audit

## Options Considered

### Option A: StaticMatrix Only

| Aspect | Assessment |
|--------|------------|
| Accuracy | LOW - Haversine estimates only |
| Performance | HIGH - Local computation |
| Setup | EASY - No external dependencies |
| Coverage | UNLIMITED - Works anywhere |
| Cost | FREE |

**Pros**:
- No external dependencies
- Instant matrix computation
- Deterministic (same input = same output)

**Cons**:
- Haversine underestimates urban travel times
- Doesn't account for road network
- Poor accuracy for real-world routing

### Option B: OSRM Only

| Aspect | Assessment |
|--------|------------|
| Accuracy | HIGH - Real road network |
| Performance | MEDIUM - HTTP requests |
| Setup | MEDIUM - Requires OSRM server |
| Coverage | Germany (with OSM data) |
| Cost | FREE (self-hosted) |

**Pros**:
- Accurate road-based distances
- Handles one-way streets, turn restrictions
- Free and open source
- Can self-host for data control

**Cons**:
- Requires server infrastructure
- API latency (~50-200ms per request)
- Needs OSM data updates

### Option C: Google Maps API

| Aspect | Assessment |
|--------|------------|
| Accuracy | HIGHEST - Traffic data |
| Performance | MEDIUM - HTTP requests |
| Setup | EASY - Just API key |
| Coverage | GLOBAL |
| Cost | HIGH ($5-10 per 1000 matrix elements) |

**Pros**:
- Best accuracy with live traffic
- No infrastructure needed
- Global coverage

**Cons**:
- Cost prohibitive at scale (500 stops = $2.50/matrix)
- Vendor lock-in
- Rate limits

### Option D: Hybrid (DECISION)

**Pilot**: StaticMatrix with Haversine fallback
**Production**: OSRM with StaticMatrix fallback

| Phase | Primary | Fallback |
|-------|---------|----------|
| Pilot (v1.0) | StaticMatrix | Haversine |
| Production (v1.1+) | OSRM | StaticMatrix → Haversine |

## Decision

**Use Hybrid approach with OSRM as primary provider in production.**

### Phase 1: Pilot (Now - 4 weeks)

```python
# config/routing.py
TRAVEL_TIME_CONFIG = {
    "provider": "static_matrix",
    "fallback": "haversine",
    "average_speed_kmh": 30.0,  # Urban average
}
```

**Rationale**:
- Focus on solver logic, not infrastructure
- Acceptable accuracy for initial validation
- No external dependencies

### Phase 2: Production (4+ weeks)

```python
TRAVEL_TIME_CONFIG = {
    "provider": "osrm",
    "osrm_url": "http://osrm.internal:5000",
    "fallback": "static_matrix",
    "cache_enabled": True,
    "cache_ttl_seconds": 86400,  # 24h
}
```

**Rationale**:
- OSRM provides road-accurate routing
- Self-hosted for data control
- Redis cache for performance
- StaticMatrix fallback for resilience

## Implementation

### Provider Selection Logic

```python
def get_travel_time_provider(config: dict) -> TravelTimeProvider:
    """
    Get travel time provider based on configuration.

    Priority:
    1. Check lat/lng coverage
    2. Check OSRM health
    3. Fall back to StaticMatrix
    4. Fall back to Haversine
    """
    provider_name = config.get("provider", "static_matrix")

    if provider_name == "osrm":
        osrm = OSRMProvider(OSRMConfig(
            base_url=config["osrm_url"],
            cache_enabled=config.get("cache_enabled", True),
            redis_url=config.get("redis_url"),
        ))

        # Health check
        if osrm.health_check():
            logger.info("Using OSRM provider")
            return osrm
        else:
            logger.warning("OSRM unhealthy, falling back to StaticMatrix")

    # Fallback to StaticMatrix
    return StaticMatrixProvider(StaticMatrixConfig(
        use_haversine_fallback=True,
        average_speed_kmh=config.get("average_speed_kmh", 30.0),
    ))
```

### lat/lng Coverage Check

```python
def check_coverage(locations: List[Tuple[float, float]]) -> dict:
    """
    Check if all locations are geocoded and within coverage area.

    Returns:
        {
            "total": 150,
            "geocoded": 148,
            "in_germany": 147,
            "coverage_ratio": 0.98,
            "recommendation": "osrm"  # or "static_matrix"
        }
    """
    total = len(locations)
    geocoded = sum(1 for loc in locations if loc[0] != 0 and loc[1] != 0)
    in_germany = sum(1 for loc in locations if _is_in_germany(loc))

    coverage_ratio = geocoded / total if total > 0 else 0

    # Decision rules
    if coverage_ratio < 0.9:
        recommendation = "static_matrix"
        reason = "Too many ungeocode stops"
    elif in_germany / total < 0.95:
        recommendation = "static_matrix"
        reason = "Stops outside Germany coverage"
    else:
        recommendation = "osrm"
        reason = "Good coverage for OSRM"

    return {
        "total": total,
        "geocoded": geocoded,
        "in_germany": in_germany,
        "coverage_ratio": coverage_ratio,
        "recommendation": recommendation,
        "reason": reason,
    }

def _is_in_germany(loc: Tuple[float, float]) -> bool:
    """Check if location is within Germany bounding box."""
    lat, lng = loc
    return (47.2 <= lat <= 55.1) and (5.8 <= lng <= 15.1)
```

## OSRM Setup (Production)

### Docker Compose

```yaml
# docker-compose.osrm.yml
services:
  osrm:
    image: osrm/osrm-backend:latest
    container_name: solvereign-osrm
    ports:
      - "5000:5000"
    volumes:
      - ./osrm-data:/data
    command: >
      osrm-routed --algorithm mld /data/germany-latest.osrm

  osrm-init:
    image: osrm/osrm-backend:latest
    volumes:
      - ./osrm-data:/data
    entrypoint: /bin/sh -c
    command: |
      "cd /data &&
       if [ ! -f germany-latest.osrm ]; then
         wget -q http://download.geofabrik.de/europe/germany-latest.osm.pbf &&
         osrm-extract -p /opt/car.lua germany-latest.osm.pbf &&
         osrm-partition germany-latest.osrm &&
         osrm-customize germany-latest.osrm
       fi"
```

### Initial Setup

```bash
# Download and process Germany OSM data (one-time, ~2 hours)
docker compose -f docker-compose.osrm.yml up osrm-init

# Start OSRM server
docker compose -f docker-compose.osrm.yml up -d osrm

# Test
curl "http://localhost:5000/route/v1/driving/13.388860,52.517037;13.397634,52.529407?overview=false"
```

## Evidence & Audit

### Matrix Snapshot

For reproducibility, each solve must store:

```python
@dataclass
class MatrixSnapshot:
    """Snapshot of travel time matrix for audit."""
    provider: str                         # "osrm" or "static_matrix"
    created_at: datetime
    locations_hash: str                   # SHA256 of sorted locations
    matrix_hash: str                      # SHA256 of matrix values
    config_hash: str                      # Provider config hash

    # Stored in evidence pack
    time_matrix: List[List[int]]
    distance_matrix: List[List[int]]
```

### Determinism Verification

```python
def verify_matrix_determinism(
    provider: TravelTimeProvider,
    locations: List[Tuple[float, float]],
    num_runs: int = 3
) -> bool:
    """
    Verify matrix is deterministic.

    For OSRM: May vary slightly due to floating point
    For StaticMatrix: Must be exactly same
    """
    hashes = []
    for _ in range(num_runs):
        matrix = provider.get_matrix(locations)
        h = hashlib.sha256(
            json.dumps(matrix.time_matrix, sort_keys=True).encode()
        ).hexdigest()
        hashes.append(h)

    return len(set(hashes)) == 1
```

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OSRM server down | Solve fails | Circuit breaker + StaticMatrix fallback |
| OSM data outdated | Inaccurate routes | Monthly data refresh automation |
| Haversine too inaccurate | Bad routes in pilot | Use 30km/h urban speed, add buffer |
| Matrix changes between runs | Non-reproducible | Cache with TTL, store in evidence |

## Decision Record

| Date | Decision |
|------|----------|
| 2026-01-06 | Hybrid approach approved |
| TBD | OSRM staging deployment |
| TBD | Production cutover |

---

**Approved by**: SOLVEREIGN Architecture Team
**Next Review**: After Pilot Phase (4 weeks)
