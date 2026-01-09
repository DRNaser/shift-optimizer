# =============================================================================
# SOLVEREIGN Routing Pack - FLS Canonicalizer
# =============================================================================
# Transforms raw FLS export data into canonical format for routing.
#
# Normalization rules:
# - Timezone: Convert all timestamps to Europe/Vienna
# - Seconds rounding: Round service_seconds to nearest 60
# - TW parsing: Support multiple formats, normalize to ISO 8601
# - Duplicate detection: Flag duplicate order_ids
# - Coords normalization: Round to 6 decimal places
# =============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Vienna timezone for normalization
TZ_VIENNA = ZoneInfo("Europe/Vienna")
TZ_UTC = timezone.utc


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CanonicalOrder:
    """Canonical representation of an order for routing."""

    # Required fields
    order_id: str
    tw_start: datetime
    tw_end: datetime

    # Coordinates (at least one location method required)
    lat: Optional[float] = None
    lng: Optional[float] = None
    zone_id: Optional[str] = None
    h3_index: Optional[str] = None

    # Service details
    service_code: str = "DELIVERY"
    service_seconds: int = 300
    tw_is_hard: bool = True

    # Assignment hints
    depot_id: Optional[str] = None
    priority: int = 50

    # Skills and capacity
    required_skills: List[str] = field(default_factory=list)
    requires_two_person: bool = False
    weight_kg: float = 0.0
    volume_m3: float = 0.0

    # Display info
    customer_name: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_postal_code: Optional[str] = None
    notes: Optional[str] = None

    # Traceability
    fls_internal_id: Optional[str] = None
    raw_line_number: Optional[int] = None

    # Canonicalization metadata
    coords_source: str = "LATLNG"  # LATLNG, ZONE, H3, MISSING
    had_coords_issue: bool = False

    def has_coords(self) -> bool:
        """Check if order has valid coordinates."""
        return self.lat is not None and self.lng is not None

    def has_zone_fallback(self) -> bool:
        """Check if order has zone/h3 fallback for coords."""
        return bool(self.zone_id or self.h3_index)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format
        data["tw_start"] = self.tw_start.isoformat()
        data["tw_end"] = self.tw_end.isoformat()
        return data

    def compute_fingerprint(self) -> str:
        """Compute deterministic fingerprint for deduplication."""
        content = f"{self.order_id}|{self.tw_start.isoformat()}|{self.tw_end.isoformat()}"
        if self.lat and self.lng:
            content += f"|{self.lat:.6f}|{self.lng:.6f}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class CanonicalImport:
    """Canonical representation of an import batch."""

    # Metadata
    source: str
    tenant_id: int
    site_id: int
    plan_date: str
    export_timestamp: datetime

    # Orders
    orders: List[CanonicalOrder] = field(default_factory=list)

    # Hashes
    canonical_hash: str = ""
    raw_hash: str = ""

    # Stats
    total_orders: int = 0
    orders_with_coords: int = 0
    orders_with_zone: int = 0
    orders_missing_location: int = 0
    duplicate_order_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "metadata": {
                "source": self.source,
                "tenant_id": self.tenant_id,
                "site_id": self.site_id,
                "plan_date": self.plan_date,
                "export_timestamp": self.export_timestamp.isoformat(),
                "canonical_hash": self.canonical_hash,
                "raw_hash": self.raw_hash,
            },
            "statistics": {
                "total_orders": self.total_orders,
                "orders_with_coords": self.orders_with_coords,
                "orders_with_zone": self.orders_with_zone,
                "orders_missing_location": self.orders_missing_location,
                "duplicate_order_ids": self.duplicate_order_ids,
            },
            "orders": [o.to_dict() for o in self.orders],
        }


@dataclass
class CanonicalizeResult:
    """Result of canonicalization process."""

    success: bool
    canonical_import: Optional[CanonicalImport]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Stats
    orders_processed: int = 0
    orders_canonical: int = 0
    orders_skipped: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "errors": self.errors,
            "warnings": self.warnings,
            "statistics": {
                "orders_processed": self.orders_processed,
                "orders_canonical": self.orders_canonical,
                "orders_skipped": self.orders_skipped,
            },
        }


# =============================================================================
# CANONICALIZER
# =============================================================================

class FLSCanonicalizer:
    """
    Transforms raw FLS export data into canonical format.

    Normalization rules:
    1. Timezone: All timestamps converted to Europe/Vienna
    2. Seconds: service_seconds rounded to nearest 60
    3. Coordinates: Rounded to 6 decimal places
    4. Duplicates: Detected and flagged
    5. Missing fields: Filled with defaults where possible

    Usage:
        canonicalizer = FLSCanonicalizer()
        result = canonicalizer.canonicalize(raw_data)
        if result.success:
            canonical_orders = result.canonical_import.orders
    """

    # Time window format patterns
    TW_PATTERNS = [
        # ISO 8601
        re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
        # German format: DD.MM.YYYY HH:MM
        re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})"),
        # Time only: HH:MM
        re.compile(r"^(\d{2}):(\d{2})$"),
    ]

    # Known service codes
    KNOWN_SERVICE_CODES = {
        "DELIVERY", "PICKUP", "SERVICE", "RETURN", "EXCHANGE",
        "INSTALL", "REPAIR", "COLLECT", "EXPRESS", "STANDARD",
    }

    # Austria bounding box (extended)
    AUSTRIA_BOUNDS = {
        "lat_min": 46.0,
        "lat_max": 49.5,
        "lng_min": 9.0,
        "lng_max": 18.0,
    }

    def __init__(
        self,
        default_service_seconds: int = 300,
        round_service_to_minutes: bool = True,
        coord_decimals: int = 6,
        strict_coords: bool = False,
    ):
        """
        Initialize canonicalizer.

        Args:
            default_service_seconds: Default service time if not specified
            round_service_to_minutes: Round service_seconds to nearest 60
            coord_decimals: Decimal places for coordinate rounding
            strict_coords: If True, reject orders without coords even if zone available
        """
        self.default_service_seconds = default_service_seconds
        self.round_service_to_minutes = round_service_to_minutes
        self.coord_decimals = coord_decimals
        self.strict_coords = strict_coords

    def canonicalize(self, raw_data: Dict[str, Any]) -> CanonicalizeResult:
        """
        Canonicalize raw FLS export data.

        Args:
            raw_data: Raw JSON data from FLS export

        Returns:
            CanonicalizeResult with canonical import or errors
        """
        errors = []
        warnings = []

        # Validate required top-level fields
        if "orders" not in raw_data:
            return CanonicalizeResult(
                success=False,
                canonical_import=None,
                errors=["Missing 'orders' field in input"],
            )

        if "import_metadata" not in raw_data:
            return CanonicalizeResult(
                success=False,
                canonical_import=None,
                errors=["Missing 'import_metadata' field in input"],
            )

        # Parse metadata
        meta = raw_data["import_metadata"]
        try:
            export_ts = self._parse_datetime(meta.get("export_timestamp", ""))
            if export_ts is None:
                export_ts = datetime.now(TZ_VIENNA)
                warnings.append("Missing export_timestamp, using current time")
        except Exception as e:
            errors.append(f"Invalid export_timestamp: {e}")
            return CanonicalizeResult(success=False, canonical_import=None, errors=errors)

        # Compute raw hash
        raw_hash = hashlib.sha256(json.dumps(raw_data, sort_keys=True).encode()).hexdigest()

        # Initialize canonical import
        canonical_import = CanonicalImport(
            source=meta.get("source", "FLS"),
            tenant_id=meta.get("tenant_id", 0),
            site_id=meta.get("site_id", 0),
            plan_date=meta.get("plan_date", ""),
            export_timestamp=export_ts,
            raw_hash=raw_hash,
        )

        # Process orders
        raw_orders = raw_data.get("orders", [])
        seen_order_ids: Dict[str, int] = {}
        canonical_orders = []
        orders_processed = 0
        orders_skipped = 0

        for idx, raw_order in enumerate(raw_orders):
            orders_processed += 1
            line_num = idx + 1

            try:
                canonical_order = self._canonicalize_order(raw_order, line_num, warnings)

                # Check for duplicates
                oid = canonical_order.order_id
                if oid in seen_order_ids:
                    warnings.append(
                        f"Duplicate order_id '{oid}' at line {line_num} "
                        f"(first seen at line {seen_order_ids[oid]})"
                    )
                    canonical_import.duplicate_order_ids.append(oid)
                else:
                    seen_order_ids[oid] = line_num

                canonical_orders.append(canonical_order)

            except ValueError as e:
                orders_skipped += 1
                errors.append(f"Order at line {line_num}: {e}")

        # Update canonical import
        canonical_import.orders = canonical_orders
        canonical_import.total_orders = len(canonical_orders)
        canonical_import.orders_with_coords = sum(1 for o in canonical_orders if o.has_coords())
        canonical_import.orders_with_zone = sum(1 for o in canonical_orders if o.has_zone_fallback())
        canonical_import.orders_missing_location = sum(
            1 for o in canonical_orders
            if not o.has_coords() and not o.has_zone_fallback()
        )

        # Compute canonical hash
        canonical_content = json.dumps(
            [o.to_dict() for o in canonical_orders],
            sort_keys=True
        )
        canonical_import.canonical_hash = hashlib.sha256(canonical_content.encode()).hexdigest()

        # Determine success
        success = len(errors) == 0 and len(canonical_orders) > 0

        return CanonicalizeResult(
            success=success,
            canonical_import=canonical_import,
            errors=errors,
            warnings=warnings,
            orders_processed=orders_processed,
            orders_canonical=len(canonical_orders),
            orders_skipped=orders_skipped,
        )

    def _canonicalize_order(
        self,
        raw: Dict[str, Any],
        line_num: int,
        warnings: List[str],
    ) -> CanonicalOrder:
        """
        Canonicalize a single order.

        Args:
            raw: Raw order dict
            line_num: Line number for error messages
            warnings: List to append warnings to

        Returns:
            CanonicalOrder

        Raises:
            ValueError: If order cannot be canonicalized (hard gate violation)
        """
        # HARD GATE: order_id required
        order_id = raw.get("order_id", "").strip()
        if not order_id:
            raise ValueError("Missing required field: order_id")

        # HARD GATE: tw_start required
        tw_start_raw = raw.get("tw_start", "")
        tw_start = self._parse_datetime(tw_start_raw)
        if tw_start is None:
            raise ValueError(f"Invalid or missing tw_start: {tw_start_raw}")

        # HARD GATE: tw_end required
        tw_end_raw = raw.get("tw_end", "")
        tw_end = self._parse_datetime(tw_end_raw)
        if tw_end is None:
            raise ValueError(f"Invalid or missing tw_end: {tw_end_raw}")

        # HARD GATE: tw_end must be after tw_start
        if tw_end <= tw_start:
            raise ValueError(f"tw_end ({tw_end}) must be after tw_start ({tw_start})")

        # Parse coordinates
        lat = self._parse_coord(raw.get("lat"))
        lng = self._parse_coord(raw.get("lng"))
        zone_id = raw.get("zone_id", "").strip() or None
        h3_index = raw.get("h3_index", "").strip() or None

        # Determine coords source
        coords_source = "MISSING"
        had_coords_issue = False

        if lat is not None and lng is not None:
            # Validate coords are in Austria bounds
            if not self._coords_in_bounds(lat, lng):
                warnings.append(
                    f"Order {order_id}: coords ({lat}, {lng}) outside Austria bounds"
                )
                had_coords_issue = True
            coords_source = "LATLNG"
            # Round coordinates
            lat = round(lat, self.coord_decimals)
            lng = round(lng, self.coord_decimals)
        elif zone_id:
            coords_source = "ZONE"
        elif h3_index:
            coords_source = "H3"

        # Parse service_seconds
        service_seconds = raw.get("service_seconds", self.default_service_seconds)
        if isinstance(service_seconds, str):
            try:
                service_seconds = int(service_seconds)
            except ValueError:
                service_seconds = self.default_service_seconds
                warnings.append(f"Order {order_id}: invalid service_seconds, using default")

        # Round to nearest minute if configured
        if self.round_service_to_minutes:
            service_seconds = round(service_seconds / 60) * 60
            service_seconds = max(60, service_seconds)  # Minimum 1 minute

        # Normalize service_code
        service_code = raw.get("service_code", "DELIVERY").upper().strip()
        if service_code not in self.KNOWN_SERVICE_CODES:
            warnings.append(f"Order {order_id}: unknown service_code '{service_code}'")

        # Parse priority (0-100)
        priority = raw.get("priority", 50)
        if isinstance(priority, str):
            try:
                priority = int(priority)
            except ValueError:
                priority = 50
        priority = max(0, min(100, priority))

        # Parse skills
        required_skills = raw.get("required_skills", [])
        if isinstance(required_skills, str):
            required_skills = [s.strip() for s in required_skills.split(",") if s.strip()]

        # Parse address
        address = raw.get("address", {})
        if isinstance(address, str):
            address = {"street": address}

        return CanonicalOrder(
            order_id=order_id,
            tw_start=tw_start,
            tw_end=tw_end,
            lat=lat,
            lng=lng,
            zone_id=zone_id,
            h3_index=h3_index,
            service_code=service_code,
            service_seconds=service_seconds,
            tw_is_hard=raw.get("tw_is_hard", True),
            depot_id=raw.get("depot_id"),
            priority=priority,
            required_skills=required_skills,
            requires_two_person=raw.get("requires_two_person", False),
            weight_kg=float(raw.get("weight_kg", 0)),
            volume_m3=float(raw.get("volume_m3", 0)),
            customer_name=raw.get("customer_name"),
            address_street=address.get("street"),
            address_city=address.get("city"),
            address_postal_code=address.get("postal_code"),
            notes=raw.get("notes"),
            fls_internal_id=raw.get("fls_internal_id"),
            raw_line_number=line_num,
            coords_source=coords_source,
            had_coords_issue=had_coords_issue,
        )

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if value is None or value == "":
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=TZ_VIENNA)
            return value.astimezone(TZ_VIENNA)

        value_str = str(value).strip()

        # Try ISO 8601 first
        try:
            dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_VIENNA)
            return dt.astimezone(TZ_VIENNA)
        except ValueError:
            pass

        # Try German format: DD.MM.YYYY HH:MM
        match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})", value_str)
        if match:
            day, month, year, hour, minute = map(int, match.groups())
            return datetime(year, month, day, hour, minute, tzinfo=TZ_VIENNA)

        # Try German format: DD.MM.YYYY HH:MM:SS
        match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", value_str)
        if match:
            day, month, year, hour, minute, second = map(int, match.groups())
            return datetime(year, month, day, hour, minute, second, tzinfo=TZ_VIENNA)

        return None

    def _parse_coord(self, value: Any) -> Optional[float]:
        """Parse coordinate value."""
        if value is None or value == "":
            return None

        try:
            coord = float(value)
            return coord if not (coord == 0.0) else None  # 0,0 is likely missing
        except (ValueError, TypeError):
            return None

    def _coords_in_bounds(self, lat: float, lng: float) -> bool:
        """Check if coordinates are within Austria bounds."""
        return (
            self.AUSTRIA_BOUNDS["lat_min"] <= lat <= self.AUSTRIA_BOUNDS["lat_max"] and
            self.AUSTRIA_BOUNDS["lng_min"] <= lng <= self.AUSTRIA_BOUNDS["lng_max"]
        )
