#!/bin/bash
# =============================================================================
# SOLVEREIGN OSRM Setup Script
# =============================================================================
# Downloads Austria OSM data and prepares it for OSRM routing.
#
# Usage:
#   ./scripts/setup_osrm.sh [--region austria|vienna]
#
# Requirements:
#   - Docker installed and running
#   - ~5GB free disk space
#   - ~30 minutes for Austria extraction
#
# Output:
#   - data/osrm/austria-latest.osrm (MLD prepared routing data)
#   - data/osrm/map_metadata.json (version and hash info)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OSRM_DATA_DIR="$PROJECT_ROOT/data/osrm"
OSRM_IMAGE="osrm/osrm-backend:v5.27.1"

# Default to Austria (covers Wien pilot)
REGION="${1:-austria}"

# Map region to Geofabrik URL
case "$REGION" in
    austria)
        OSM_URL="https://download.geofabrik.de/europe/austria-latest.osm.pbf"
        OSM_FILE="austria-latest.osm.pbf"
        OSRM_FILE="austria-latest.osrm"
        ;;
    vienna)
        # Vienna extract (smaller, faster for testing)
        OSM_URL="https://download.geofabrik.de/europe/austria-latest.osm.pbf"
        OSM_FILE="austria-latest.osm.pbf"
        OSRM_FILE="austria-latest.osrm"
        echo "[INFO] Note: Using full Austria data (Vienna-only extract not available from Geofabrik)"
        ;;
    *)
        echo "[ERROR] Unknown region: $REGION"
        echo "Usage: $0 [austria|vienna]"
        exit 1
        ;;
esac

echo "=============================================="
echo "SOLVEREIGN OSRM Setup"
echo "=============================================="
echo "Region: $REGION"
echo "Data directory: $OSRM_DATA_DIR"
echo ""

# Create data directory
mkdir -p "$OSRM_DATA_DIR"

# Step 1: Download OSM data
echo "[1/5] Downloading OSM data..."
if [ -f "$OSRM_DATA_DIR/$OSM_FILE" ]; then
    echo "      File already exists, skipping download"
else
    echo "      Downloading from $OSM_URL"
    echo "      This may take a few minutes..."
    curl -L -o "$OSRM_DATA_DIR/$OSM_FILE" "$OSM_URL"
fi

# Compute hash of OSM file
OSM_HASH=$(sha256sum "$OSRM_DATA_DIR/$OSM_FILE" | cut -d' ' -f1)
echo "      OSM file hash: ${OSM_HASH:0:16}..."

# Step 2: Extract (convert OSM to OSRM graph)
echo ""
echo "[2/5] Extracting road network (this takes ~10-20 minutes)..."
docker run --rm -v "$OSRM_DATA_DIR:/data" "$OSRM_IMAGE" \
    osrm-extract -p /opt/car.lua "/data/$OSM_FILE"

# Step 3: Partition (prepare for MLD algorithm)
echo ""
echo "[3/5] Partitioning graph for MLD algorithm..."
docker run --rm -v "$OSRM_DATA_DIR:/data" "$OSRM_IMAGE" \
    osrm-partition "/data/$OSRM_FILE"

# Step 4: Customize (finalize MLD preparation)
echo ""
echo "[4/5] Customizing graph..."
docker run --rm -v "$OSRM_DATA_DIR:/data" "$OSRM_IMAGE" \
    osrm-customize "/data/$OSRM_FILE"

# Step 5: Generate metadata file
echo ""
echo "[5/5] Generating metadata..."

# Compute hash of the prepared OSRM file
OSRM_HASH=$(sha256sum "$OSRM_DATA_DIR/$OSRM_FILE" 2>/dev/null | cut -d' ' -f1 || echo "not_computed")

# Create metadata JSON
cat > "$OSRM_DATA_DIR/map_metadata.json" << EOF
{
    "region": "$REGION",
    "osm_source": "$OSM_URL",
    "osm_file": "$OSM_FILE",
    "osm_hash": "$OSM_HASH",
    "osrm_file": "$OSRM_FILE",
    "osrm_hash": "$OSRM_HASH",
    "osrm_image": "$OSRM_IMAGE",
    "algorithm": "MLD",
    "profile": "car",
    "prepared_at": "$(date -Iseconds)",
    "prepared_by": "$(whoami)@$(hostname)"
}
EOF

echo ""
echo "=============================================="
echo "OSRM Setup Complete!"
echo "=============================================="
echo ""
echo "Map metadata saved to: $OSRM_DATA_DIR/map_metadata.json"
echo ""
echo "To start OSRM server:"
echo "  docker-compose --profile routing up -d osrm"
echo ""
echo "To test OSRM:"
echo "  curl 'http://localhost:5000/route/v1/driving/16.3738,48.2082;16.4097,48.2206'"
echo ""
echo "Map hash for evidence tracking:"
echo "  $OSRM_HASH"
