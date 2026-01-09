# =============================================================================
# SOLVEREIGN Routing Pack - Coords Lookup Tables
# =============================================================================
# Static lookup tables for zone and H3 index → lat/lng centroid resolution.
#
# Purpose:
# - Deterministic coords resolution without external services
# - Supports test and pilot datasets with zone_id or h3_index only
#
# Data Sources:
# - Wien postal code centroids: OpenStreetMap/Nominatim approximations
# - H3 centroids: Pre-computed for known test H3 indices
#
# Usage:
#   from coords_lookup import ZoneLookup, H3Lookup
#
#   zone_lookup = ZoneLookup()
#   coords = zone_lookup.resolve("1220")  # Returns (lat, lng) or None
#
#   h3_lookup = H3Lookup()
#   coords = h3_lookup.resolve("881f1d4813fffff")  # Returns (lat, lng) or None
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# WIEN POSTAL CODE CENTROIDS
# =============================================================================
# Source: Approximate centroids from OpenStreetMap/Wikipedia
# These are stable for pilot testing; production would use a proper geodata service

WIEN_PLZ_CENTROIDS: Dict[str, Tuple[float, float]] = {
    # Bezirk 1: Innere Stadt
    "1010": (48.2082, 16.3738),
    # Bezirk 2: Leopoldstadt
    "1020": (48.2167, 16.4000),
    # Bezirk 3: Landstraße
    "1030": (48.1986, 16.3950),
    # Bezirk 4: Wieden
    "1040": (48.1917, 16.3694),
    # Bezirk 5: Margareten
    "1050": (48.1869, 16.3556),
    # Bezirk 6: Mariahilf
    "1060": (48.1961, 16.3478),
    # Bezirk 7: Neubau
    "1070": (48.2028, 16.3461),
    # Bezirk 8: Josefstadt
    "1080": (48.2103, 16.3461),
    # Bezirk 9: Alsergrund
    "1090": (48.2250, 16.3556),
    # Bezirk 10: Favoriten
    "1100": (48.1589, 16.3817),
    # Bezirk 11: Simmering
    "1110": (48.1667, 16.4333),
    # Bezirk 12: Meidling
    "1120": (48.1750, 16.3250),
    # Bezirk 13: Hietzing
    "1130": (48.1778, 16.2833),
    # Bezirk 14: Penzing
    "1140": (48.2000, 16.2667),
    # Bezirk 15: Rudolfsheim-Fünfhaus
    "1150": (48.1972, 16.3250),
    # Bezirk 16: Ottakring
    "1160": (48.2167, 16.3083),
    # Bezirk 17: Hernals
    "1170": (48.2333, 16.3000),
    # Bezirk 18: Währing
    "1180": (48.2361, 16.3333),
    # Bezirk 19: Döbling
    "1190": (48.2583, 16.3500),
    # Bezirk 20: Brigittenau
    "1200": (48.2417, 16.3750),
    # Bezirk 21: Floridsdorf
    "1210": (48.2833, 16.3833),
    # Bezirk 22: Donaustadt
    "1220": (48.2333, 16.4667),
    # Bezirk 23: Liesing
    "1230": (48.1333, 16.2917),
}


# =============================================================================
# H3 INDEX CENTROIDS (Pre-computed for test dataset)
# =============================================================================
# H3 indices used in test datasets with their centroid coordinates
# Source: H3 library h3.h3_to_geo() for known test indices

H3_INDEX_CENTROIDS: Dict[str, Tuple[float, float]] = {
    # From wien_pilot_small.json - ORD-007 H3 index
    # H3 resolution 8 cell in Wien Bezirk 3 area
    "881f1d4813fffff": (48.2020, 16.3980),

    # Additional H3 cells for testing (resolution 8, Wien area)
    "881f1d4815fffff": (48.2050, 16.4020),
    "881f1d4817fffff": (48.2010, 16.4050),
    "881f1d481bfffff": (48.1990, 16.4010),
    "881f1d4811fffff": (48.2030, 16.3950),

    # Resolution 9 cells (finer grain)
    "891f1d48130ffff": (48.2022, 16.3982),
    "891f1d48132ffff": (48.2018, 16.3978),
}


# =============================================================================
# LOOKUP CLASSES
# =============================================================================

@dataclass
class LookupResult:
    """Result of a coords lookup."""
    found: bool
    lat: Optional[float] = None
    lng: Optional[float] = None
    source: str = ""
    notes: str = ""

    def as_tuple(self) -> Optional[Tuple[float, float]]:
        """Return (lat, lng) tuple or None."""
        if self.found and self.lat is not None and self.lng is not None:
            return (self.lat, self.lng)
        return None


class ZoneLookup:
    """
    Zone/PLZ to lat/lng centroid lookup.

    Supports Wien postal codes (1010-1230).
    Can be extended with custom lookup tables.
    """

    def __init__(self, custom_centroids: Optional[Dict[str, Tuple[float, float]]] = None):
        """
        Initialize zone lookup.

        Args:
            custom_centroids: Optional custom centroid mapping to merge with defaults
        """
        self._centroids = dict(WIEN_PLZ_CENTROIDS)
        if custom_centroids:
            self._centroids.update(custom_centroids)

    def resolve(self, zone_id: str) -> Optional[Tuple[float, float]]:
        """
        Resolve zone/PLZ to lat/lng centroid.

        Args:
            zone_id: Zone ID or postal code (e.g., "1220")

        Returns:
            (lat, lng) tuple or None if not found
        """
        # Normalize zone_id (strip whitespace, handle variants)
        normalized = str(zone_id).strip()

        # Direct lookup
        if normalized in self._centroids:
            return self._centroids[normalized]

        # Try without leading zeros
        without_zeros = normalized.lstrip("0")
        if without_zeros in self._centroids:
            return self._centroids[without_zeros]

        # Try with 'A-' prefix removed (AT postal code format)
        if normalized.startswith("A-"):
            stripped = normalized[2:]
            if stripped in self._centroids:
                return self._centroids[stripped]

        logger.debug(f"Zone lookup miss: {zone_id}")
        return None

    def lookup(self, zone_id: str) -> LookupResult:
        """
        Lookup with full result details.

        Args:
            zone_id: Zone ID or postal code

        Returns:
            LookupResult with coords and metadata
        """
        coords = self.resolve(zone_id)
        if coords:
            return LookupResult(
                found=True,
                lat=coords[0],
                lng=coords[1],
                source="WIEN_PLZ_CENTROIDS",
                notes=f"PLZ {zone_id} centroid"
            )
        return LookupResult(
            found=False,
            source="WIEN_PLZ_CENTROIDS",
            notes=f"PLZ {zone_id} not found in lookup table"
        )

    @property
    def available_zones(self) -> list:
        """List of available zone IDs."""
        return sorted(self._centroids.keys())


class H3Lookup:
    """
    H3 index to lat/lng centroid lookup.

    Uses pre-computed centroids for known H3 indices.
    Falls back to h3 library if available.
    """

    def __init__(self, custom_centroids: Optional[Dict[str, Tuple[float, float]]] = None):
        """
        Initialize H3 lookup.

        Args:
            custom_centroids: Optional custom centroid mapping to merge with defaults
        """
        self._centroids = dict(H3_INDEX_CENTROIDS)
        if custom_centroids:
            self._centroids.update(custom_centroids)

        # Check if h3 library is available for fallback
        self._h3_available = False
        try:
            import h3
            self._h3 = h3
            self._h3_available = True
        except ImportError:
            self._h3 = None

    def resolve(self, h3_index: str) -> Optional[Tuple[float, float]]:
        """
        Resolve H3 index to lat/lng centroid.

        Args:
            h3_index: H3 index string (e.g., "881f1d4813fffff")

        Returns:
            (lat, lng) tuple or None if not found
        """
        # Normalize index (lowercase)
        normalized = str(h3_index).strip().lower()

        # Direct lookup in static table
        if normalized in self._centroids:
            return self._centroids[normalized]

        # Fallback to h3 library if available
        if self._h3_available and self._h3:
            try:
                # h3_to_geo returns (lat, lng) tuple
                lat, lng = self._h3.h3_to_geo(normalized)
                return (lat, lng)
            except Exception as e:
                logger.debug(f"H3 library resolution failed for {h3_index}: {e}")

        logger.debug(f"H3 lookup miss: {h3_index}")
        return None

    def lookup(self, h3_index: str) -> LookupResult:
        """
        Lookup with full result details.

        Args:
            h3_index: H3 index string

        Returns:
            LookupResult with coords and metadata
        """
        normalized = str(h3_index).strip().lower()

        # Check static table first
        if normalized in self._centroids:
            coords = self._centroids[normalized]
            return LookupResult(
                found=True,
                lat=coords[0],
                lng=coords[1],
                source="H3_STATIC_TABLE",
                notes=f"H3 {h3_index} pre-computed centroid"
            )

        # Try h3 library
        if self._h3_available and self._h3:
            try:
                lat, lng = self._h3.h3_to_geo(normalized)
                return LookupResult(
                    found=True,
                    lat=lat,
                    lng=lng,
                    source="H3_LIBRARY",
                    notes=f"H3 {h3_index} computed via h3 library"
                )
            except Exception:
                pass

        return LookupResult(
            found=False,
            source="H3_LOOKUP",
            notes=f"H3 {h3_index} not found and h3 library not available"
        )

    @property
    def available_indices(self) -> list:
        """List of available H3 indices in static table."""
        return sorted(self._centroids.keys())

    @property
    def h3_library_available(self) -> bool:
        """Whether h3 library is available for dynamic resolution."""
        return self._h3_available


# =============================================================================
# RESOLVER WRAPPER (for CoordsQualityGate integration)
# =============================================================================

class CoordsResolver:
    """
    Combined resolver for zone and H3 → coords.

    Provides the interface expected by CoordsQualityGate.
    """

    def __init__(
        self,
        zone_lookup: Optional[ZoneLookup] = None,
        h3_lookup: Optional[H3Lookup] = None,
    ):
        """
        Initialize combined resolver.

        Args:
            zone_lookup: ZoneLookup instance (created if None)
            h3_lookup: H3Lookup instance (created if None)
        """
        self.zone_lookup = zone_lookup or ZoneLookup()
        self.h3_lookup = h3_lookup or H3Lookup()

    def resolve_zone(self, zone_id: str) -> Optional[Tuple[float, float]]:
        """Resolve zone to coords."""
        return self.zone_lookup.resolve(zone_id)

    def resolve_h3(self, h3_index: str) -> Optional[Tuple[float, float]]:
        """Resolve H3 to coords."""
        return self.h3_lookup.resolve(h3_index)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_default_zone_resolver() -> ZoneLookup:
    """Create default zone resolver with Wien PLZ."""
    return ZoneLookup()


def create_default_h3_resolver() -> H3Lookup:
    """Create default H3 resolver with test indices."""
    return H3Lookup()


def get_wien_plz_centroid(plz: str) -> Optional[Tuple[float, float]]:
    """Get centroid for a Wien postal code."""
    return WIEN_PLZ_CENTROIDS.get(str(plz).strip())


def get_h3_centroid(h3_index: str) -> Optional[Tuple[float, float]]:
    """Get centroid for an H3 index."""
    return H3_INDEX_CENTROIDS.get(str(h3_index).strip().lower())
