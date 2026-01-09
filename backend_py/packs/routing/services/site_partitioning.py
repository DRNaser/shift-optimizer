# =============================================================================
# SOLVEREIGN Routing Pack - Gate 4: Site/Depot Partitioning
# =============================================================================
# Enforces site-scoped operations for multi-depot scenarios.
#
# Gate 4 Requirements:
# - scenario.site_id FK auf routing_depots
# - Lock-Key Query muss WHERE site_id = scenario.site_id enthalten
# - All vehicles in scenario must use depots with matching site_id
# =============================================================================

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class SitePartitioningError(Exception):
    """Base exception for site partitioning errors."""
    pass


class SiteMismatchError(SitePartitioningError):
    """Site ID mismatch between scenario and depot."""
    def __init__(self, message: str, scenario_site_id: str, depot_site_id: str):
        super().__init__(message)
        self.scenario_site_id = scenario_site_id
        self.depot_site_id = depot_site_id


class MissingSiteIdError(SitePartitioningError):
    """Scenario is missing required site_id."""
    pass


class DepotNotFoundError(SitePartitioningError):
    """Depot not found for site_id."""
    pass


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SiteContext:
    """
    Site-scoped context for operations.
    All operations within this context are partitioned to the site.
    """
    tenant_id: int
    site_id: str
    depot_ids: List[str]

    @property
    def partition_key(self) -> str:
        """Generate partition key for logging/tracing."""
        return f"tenant:{self.tenant_id}:site:{self.site_id}"


@dataclass
class AdvisoryLockKey:
    """
    Advisory lock key for site-scoped operations.
    Prevents concurrent solves within same (tenant, site, scenario).
    """
    tenant_id: int
    site_id: str
    scenario_id: str

    def to_hash(self) -> int:
        """
        Generate deterministic hash for pg_try_advisory_lock.

        The hash is a 64-bit integer derived from:
        routing:{tenant_id}:{site_id}:{scenario_id}
        """
        key_str = f"routing:{self.tenant_id}:{self.site_id}:{self.scenario_id}"
        # Use first 16 hex chars of SHA256, convert to signed 64-bit int
        hash_hex = hashlib.sha256(key_str.encode()).hexdigest()[:16]
        # Convert to signed 64-bit integer (Python handles arbitrary precision)
        hash_int = int(hash_hex, 16)
        # Ensure it fits in signed 64-bit (PostgreSQL bigint range)
        if hash_int >= 2**63:
            hash_int -= 2**64
        return hash_int

    def __str__(self) -> str:
        return f"AdvisoryLock(tenant={self.tenant_id}, site={self.site_id}, scenario={self.scenario_id})"


# =============================================================================
# SITE PARTITIONING SERVICE
# =============================================================================

class SitePartitioningService:
    """
    Enforces site-scoped operations for multi-depot routing.

    Gate 4 Implementation:
    1. Validates scenario.site_id matches depot.site_id
    2. Generates site-scoped advisory lock keys
    3. Filters depots by site_id
    4. Prevents cross-site vehicle assignments
    """

    def __init__(self, strict_mode: bool = True):
        """
        Initialize site partitioning service.

        Args:
            strict_mode: If True, raise errors on site_id violations.
                        If False, log warnings but allow operation.
        """
        self.strict_mode = strict_mode

    def validate_scenario_depot_match(
        self,
        scenario_site_id: Optional[str],
        depot_site_id: str,
    ) -> bool:
        """
        Validate that scenario's site_id matches depot's site_id.

        Args:
            scenario_site_id: Site ID from scenario (may be None for legacy)
            depot_site_id: Site ID from depot

        Returns:
            True if match or scenario has no site_id (legacy)

        Raises:
            SiteMismatchError: If strict_mode and site IDs don't match
        """
        # Legacy scenarios (no site_id) are allowed any depot
        if scenario_site_id is None:
            logger.debug("Legacy scenario (no site_id) - allowing any depot")
            return True

        if scenario_site_id != depot_site_id:
            msg = (
                f"Gate 4 violation: Scenario site_id ({scenario_site_id}) "
                f"does not match depot site_id ({depot_site_id})"
            )
            if self.strict_mode:
                raise SiteMismatchError(msg, scenario_site_id, depot_site_id)
            else:
                logger.warning(msg)
                return False

        return True

    def validate_vehicle_depots(
        self,
        scenario_site_id: Optional[str],
        start_depot_site_id: str,
        end_depot_site_id: str,
    ) -> bool:
        """
        Validate that vehicle's start/end depots match scenario's site_id.

        Args:
            scenario_site_id: Site ID from scenario
            start_depot_site_id: Site ID from start depot
            end_depot_site_id: Site ID from end depot

        Returns:
            True if all match or scenario has no site_id

        Raises:
            SiteMismatchError: If strict_mode and any site_id doesn't match
        """
        # Check start depot
        if not self.validate_scenario_depot_match(scenario_site_id, start_depot_site_id):
            return False

        # Check end depot
        if not self.validate_scenario_depot_match(scenario_site_id, end_depot_site_id):
            return False

        return True

    def get_advisory_lock_key(
        self,
        tenant_id: int,
        site_id: str,
        scenario_id: str,
    ) -> AdvisoryLockKey:
        """
        Generate site-scoped advisory lock key.

        Args:
            tenant_id: Tenant ID
            site_id: Site ID (use 'GLOBAL' if no site partitioning)
            scenario_id: Scenario ID (UUID as string)

        Returns:
            AdvisoryLockKey with computed hash
        """
        return AdvisoryLockKey(
            tenant_id=tenant_id,
            site_id=site_id or "GLOBAL",
            scenario_id=scenario_id,
        )

    def filter_depots_by_site(
        self,
        depots: List[Dict[str, Any]],
        site_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Filter depots to only those matching site_id.

        Args:
            depots: List of depot dicts (must have 'site_id' key)
            site_id: Site ID to filter by

        Returns:
            Filtered list of depots
        """
        return [d for d in depots if d.get("site_id") == site_id]

    def create_site_context(
        self,
        tenant_id: int,
        site_id: str,
        depot_ids: List[str],
    ) -> SiteContext:
        """
        Create a site context for operations.

        Args:
            tenant_id: Tenant ID
            site_id: Site ID
            depot_ids: List of valid depot IDs for this site

        Returns:
            SiteContext object
        """
        return SiteContext(
            tenant_id=tenant_id,
            site_id=site_id,
            depot_ids=depot_ids,
        )

    def validate_scenario_site_required(
        self,
        scenario_site_id: Optional[str],
    ) -> None:
        """
        Validate that scenario has a site_id (required for new scenarios).

        Args:
            scenario_site_id: Site ID from scenario

        Raises:
            MissingSiteIdError: If site_id is None and strict_mode
        """
        if scenario_site_id is None:
            msg = "Gate 4: New scenarios require site_id"
            if self.strict_mode:
                raise MissingSiteIdError(msg)
            else:
                logger.warning(msg)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_lock_key_sql(tenant_id: int, site_id: str, scenario_id: str) -> str:
    """
    Generate SQL for advisory lock key.

    This can be used directly in SQL queries:
    SELECT pg_try_advisory_lock({lock_key})

    Returns:
        SQL expression for the lock key
    """
    # Use the same hash algorithm as AdvisoryLockKey
    key = AdvisoryLockKey(tenant_id, site_id or "GLOBAL", scenario_id)
    return str(key.to_hash())


def validate_all_vehicles_site_match(
    scenario_site_id: Optional[str],
    vehicles: List[Dict[str, Any]],
    depots: Dict[str, Dict[str, Any]],  # depot_id -> depot
) -> List[str]:
    """
    Validate all vehicles have depots matching scenario's site_id.

    Args:
        scenario_site_id: Site ID from scenario
        vehicles: List of vehicle dicts (with start_depot_id, end_depot_id)
        depots: Dict of depot_id -> depot dict (with site_id)

    Returns:
        List of error messages (empty if all valid)
    """
    if scenario_site_id is None:
        return []  # Legacy mode - no validation

    errors = []
    for vehicle in vehicles:
        vehicle_id = vehicle.get("id", "unknown")

        # Check start depot
        start_depot_id = vehicle.get("start_depot_id")
        if start_depot_id:
            start_depot = depots.get(start_depot_id)
            if start_depot:
                if start_depot.get("site_id") != scenario_site_id:
                    errors.append(
                        f"Vehicle {vehicle_id}: start_depot site_id "
                        f"({start_depot.get('site_id')}) != scenario site_id ({scenario_site_id})"
                    )
            else:
                errors.append(f"Vehicle {vehicle_id}: start_depot {start_depot_id} not found")

        # Check end depot
        end_depot_id = vehicle.get("end_depot_id")
        if end_depot_id:
            end_depot = depots.get(end_depot_id)
            if end_depot:
                if end_depot.get("site_id") != scenario_site_id:
                    errors.append(
                        f"Vehicle {vehicle_id}: end_depot site_id "
                        f"({end_depot.get('site_id')}) != scenario site_id ({scenario_site_id})"
                    )
            else:
                errors.append(f"Vehicle {vehicle_id}: end_depot {end_depot_id} not found")

    return errors


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Default instance with strict mode
site_partitioning = SitePartitioningService(strict_mode=True)
